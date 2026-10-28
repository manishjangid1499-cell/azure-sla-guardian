import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from guardian.models.database import Base
from guardian.models.entities import Policy, Asset, Snapshot
from guardian.azure_client.simulator import AzureSimulatorClient
from guardian.core.rate_limiter import TokenBucketRateLimiter, ResilientAzureExecutor
from guardian.services.discovery import DiscoveryService
from guardian.services.orchestration import OrchestrationService
from guardian.services.retention import RetentionService


@pytest_asyncio.fixture
async def in_memory_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_end_to_end_orchestration_flow(in_memory_db: AsyncSession):
    sim = AzureSimulatorClient()
    limiter = TokenBucketRateLimiter(tokens_per_second=100.0, capacity=20)
    executor = ResilientAzureExecutor(limiter, max_retries=2, base_backoff=0.01)

    discovery = DiscoveryService(sim, executor)
    orchestration = OrchestrationService(sim, executor)
    retention = RetentionService(sim, executor)

    # 1. Seed Gold Policy
    gold_policy = Policy(
        name="Gold-Test",
        frequency_minutes=15,
        retention_days=30,
        tier_to_cool_after_days=7,
        ransomware_scan_enabled=True
    )
    in_memory_db.add(gold_policy)
    await in_memory_db.commit()
    await in_memory_db.refresh(gold_policy)

    # 2. Discover Assets
    assets = await discovery.discover_and_sync(in_memory_db)
    assert len(assets) > 0
    test_asset = assets[0]
    assert test_asset.status == "UNPROTECTED"

    # 3. Assign SLA
    updated_asset = await orchestration.assign_policy(in_memory_db, test_asset.id, gold_policy.id)
    assert updated_asset.status == "PROTECTED"
    assert updated_asset.policy_id == gold_policy.id

    # 4. Trigger Snapshot
    snapshot = await orchestration.create_snapshot_for_asset(in_memory_db, test_asset.id)
    assert snapshot is not None
    assert snapshot.status == "READY"
    assert snapshot.tier == "Hot"
    assert snapshot.entropy_score < 7.2  # clean simulated data

    # 5. Point-in-time recovery lookup
    recovery_snap = await orchestration.get_latest_clean_recovery_point(in_memory_db, test_asset.id)
    assert recovery_snap.id == snapshot.id
