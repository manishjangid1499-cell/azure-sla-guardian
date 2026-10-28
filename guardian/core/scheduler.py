import asyncio
from datetime import timedelta
from sqlalchemy import select
from guardian.models.database import AsyncSessionLocal
from guardian.models.entities import Asset, Policy, utc_now
from guardian.services.orchestration import OrchestrationService
from guardian.services.retention import RetentionService
import logging

logger = logging.getLogger("guardian.scheduler")


class BackgroundSLAScheduler:
    """
    Automated SLA evaluation and retention sweeper daemon.
    Periodically checks if assets need new snapshots according to their SLA domain
    and sweeps expired snapshots.
    """
    def __init__(
        self,
        orchestration_service: OrchestrationService,
        retention_service: RetentionService,
        poll_interval_seconds: int = 15
    ):
        self.orchestration = orchestration_service
        self.retention = retention_service
        self.poll_interval = poll_interval_seconds
        self._running = False
        self._task = None

    async def _run_loop(self):
        logger.info(f"[Scheduler] Background SLA Daemon started (poll interval: {self.poll_interval}s).")
        while self._running:
            try:
                await self.evaluate_slas()
                await self.sweep_retention()
            except Exception as e:
                logger.error(f"[Scheduler] Unexpected error in SLA loop: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def evaluate_slas(self):
        """Finds all protected assets whose SLA snapshot interval has elapsed and triggers backup."""
        async with AsyncSessionLocal() as db:
            now = utc_now()
            stmt = (
                select(Asset, Policy)
                .join(Policy, Asset.policy_id == Policy.id)
                .where(Asset.status.in_(["PROTECTED", "ANOMALOUS"]))
            )
            result = await db.execute(stmt)
            protected_items = result.all()

            for asset, policy in protected_items:
                should_snapshot = False
                if asset.last_snapshot_at is None:
                    should_snapshot = True
                else:
                    due_time = asset.last_snapshot_at + timedelta(minutes=policy.frequency_minutes)
                    if due_time.tzinfo is None and now.tzinfo is not None:
                        due_time = due_time.replace(tzinfo=now.tzinfo)
                    elif due_time.tzinfo is not None and now.tzinfo is None:
                        due_time = due_time.replace(tzinfo=None)
                    if now >= due_time:
                        should_snapshot = True

                if should_snapshot:
                    logger.info(f"[Scheduler] SLA triggered snapshot for asset '{asset.name}' under policy '{policy.name}'")
                    try:
                        await self.orchestration.create_snapshot_for_asset(db, asset.id)
                    except Exception as e:
                        logger.error(f"[Scheduler] Failed SLA snapshot for asset {asset.name}: {e}")

    async def sweep_retention(self):
        """Sweeps expired snapshots and tiers aging ones."""
        async with AsyncSessionLocal() as db:
            pruned = await self.retention.sweep_and_prune_expired(db)
            tiered = await self.retention.tier_aging_snapshots(db)
            if pruned > 0 or tiered > 0:
                logger.info(f"[Scheduler] Retention sweeper completed: {pruned} pruned, {tiered} tiered.")

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())

    def stop(self):
        if self._running:
            self._running = False
            if self._task:
                self._task.cancel()
            logger.info("[Scheduler] Background SLA Daemon stopped.")
