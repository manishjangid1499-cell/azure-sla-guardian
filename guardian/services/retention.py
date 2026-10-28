from datetime import timedelta
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from guardian.azure_client.base import CloudClient
from guardian.core.rate_limiter import ResilientAzureExecutor
from guardian.models.entities import Snapshot, Policy, utc_now
import logging

logger = logging.getLogger("guardian.retention")


class RetentionService:
    def __init__(self, cloud_client: CloudClient, executor: ResilientAzureExecutor):
        self.cloud_client = cloud_client
        self.executor = executor

    async def sweep_and_prune_expired(self, db: AsyncSession) -> int:
        """
        Deletes expired snapshots from cloud storage and marks them PRUNED in DB.
        """
        now = utc_now()
        stmt = select(Snapshot).where(
            Snapshot.expires_at <= now,
            Snapshot.status.in_(["READY", "ANOMALOUS"])
        )
        result = await db.execute(stmt)
        expired_snapshots = result.scalars().all()

        pruned_count = 0
        for snap in expired_snapshots:
            try:
                # Delete snapshot on cloud via resilient executor
                await self.executor.execute(
                    self.cloud_client.delete_snapshot,
                    snap.azure_snapshot_id
                )
                snap.status = "PRUNED"
                pruned_count += 1
                logger.info(f"[Retention] Successfully pruned expired snapshot: {snap.azure_snapshot_id}")
            except Exception as e:
                logger.error(f"[Retention] Failed to prune snapshot {snap.azure_snapshot_id}: {e}")

        if pruned_count > 0:
            await db.commit()

        return pruned_count

    async def tier_aging_snapshots(self, db: AsyncSession) -> int:
        """
        Transitions snapshots older than policy.tier_to_cool_after_days from Hot to Cool tier.
        """
        now = utc_now()
        stmt = (
            select(Snapshot, Policy)
            .join(Policy, Snapshot.policy_id == Policy.id)
            .where(Snapshot.tier == "Hot", Snapshot.status == "READY")
        )
        result = await db.execute(stmt)
        records = result.all()

        tiered_count = 0
        for snap, policy in records:
            created = snap.created_at
            if created.tzinfo is None and now.tzinfo is not None:
                created = created.replace(tzinfo=now.tzinfo)
            elif created.tzinfo is not None and now.tzinfo is None:
                created = created.replace(tzinfo=None)
            age_threshold = created + timedelta(days=policy.tier_to_cool_after_days)
            if now >= age_threshold:
                try:
                    await self.executor.execute(
                        self.cloud_client.change_snapshot_tier,
                        snap.azure_snapshot_id,
                        "Cool"
                    )
                    snap.tier = "Cool"
                    tiered_count += 1
                    logger.info(f"[Retention] Tiered snapshot {snap.azure_snapshot_id} to Cool storage.")
                except Exception as e:
                    logger.error(f"[Retention] Failed to tier snapshot {snap.azure_snapshot_id}: {e}")

        if tiered_count > 0:
            await db.commit()

        return tiered_count
