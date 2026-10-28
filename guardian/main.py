import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select

from guardian.config import settings
from guardian.models.database import init_db, AsyncSessionLocal
from guardian.models.entities import Policy
from guardian.core.rate_limiter import TokenBucketRateLimiter, ResilientAzureExecutor
from guardian.core.metrics import metrics
from guardian.core.scheduler import BackgroundSLAScheduler
from guardian.azure_client.simulator import AzureSimulatorClient
from guardian.azure_client.live import LiveAzureClient
from guardian.services.discovery import DiscoveryService
from guardian.services.orchestration import OrchestrationService
from guardian.services.retention import RetentionService
from guardian.web.routes import api_router, set_services
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("guardian.main")

scheduler_daemon = None


async def seed_initial_data():
    """Seeds default Gold, Silver, Bronze SLA policies if they don't already exist."""
    async with AsyncSessionLocal() as db:
        stmt = select(Policy)
        result = await db.execute(stmt)
        if not result.scalars().first():
            policies = [
                Policy(
                    name="Gold",
                    description="Mission Critical: 15-min snapshot interval, 30-day retention, Cool tier after 7 days",
                    frequency_minutes=15,
                    retention_days=30,
                    tier_to_cool_after_days=7,
                    ransomware_scan_enabled=True
                ),
                Policy(
                    name="Silver",
                    description="Standard Production: 1-hour interval, 14-day retention, Cool tier after 5 days",
                    frequency_minutes=60,
                    retention_days=14,
                    tier_to_cool_after_days=5,
                    ransomware_scan_enabled=True
                ),
                Policy(
                    name="Bronze",
                    description="Non-Critical / Staging: 24-hour interval, 7-day retention",
                    frequency_minutes=1440,
                    retention_days=7,
                    tier_to_cool_after_days=3,
                    ransomware_scan_enabled=True
                )
            ]
            db.add_all(policies)
            await db.commit()
            logger.info("[Init] Seeded Gold, Silver, and Bronze SLA policies.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler_daemon
    logger.info(f"[Lifecycle] Starting {settings.APP_NAME} in mode: {settings.CLOUD_MODE.upper()}")

    # 1. Initialize DB tables
    await init_db()
    await seed_initial_data()

    # 2. Wire core components
    limiter = TokenBucketRateLimiter(
        tokens_per_second=settings.RATE_LIMIT_TOKENS_PER_SEC,
        capacity=settings.RATE_LIMIT_BUCKET_CAPACITY
    )
    executor = ResilientAzureExecutor(
        rate_limiter=limiter,
        max_retries=settings.MAX_RETRIES,
        base_backoff=settings.BACKOFF_BASE_SECONDS,
        max_backoff=settings.BACKOFF_MAX_SECONDS,
        enable_jitter=settings.BACKOFF_JITTER
    )

    if settings.CLOUD_MODE == "azure":
        cloud_client = LiveAzureClient()
        simulator = None
    else:
        cloud_client = AzureSimulatorClient()
        simulator = cloud_client

    discovery = DiscoveryService(cloud_client, executor)
    orchestration = OrchestrationService(cloud_client, executor)
    retention = RetentionService(cloud_client, executor)

    set_services(discovery, orchestration, simulator)

    # 3. Start background scheduler
    if settings.SCHEDULER_ENABLED:
        scheduler_daemon = BackgroundSLAScheduler(
            orchestration_service=orchestration,
            retention_service=retention,
            poll_interval_seconds=settings.SLA_EVALUATION_INTERVAL_SECONDS
        )
        scheduler_daemon.start()

    yield

    # Teardown
    if scheduler_daemon:
        scheduler_daemon.stop()
    logger.info("[Lifecycle] Azure Guardian shut down cleanly.")


app = FastAPI(
    title=settings.APP_NAME,
    description="Enterprise Cloud Native Protection & SLA Engine for Microsoft Azure",
    version="1.0.0",
    lifespan=lifespan
)

# Include API Router
app.include_router(api_router)

# Mount Static Files
static_dir = os.path.join(os.path.dirname(__file__), "web", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def prometheus_metrics():
    """Prometheus exposition metrics endpoint."""
    return metrics.generate_prometheus_metrics()
