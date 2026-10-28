import json
from datetime import timedelta
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from guardian.azure_client.base import CloudClient
from guardian.core.rate_limiter import ResilientAzureExecutor
from guardian.core.entropy import EntropyAnalyzer
from guardian.core.metrics import metrics
from guardian.config import settings
from guardian.models.entities import Asset, Policy, Snapshot, AnomalyAlert, utc_now
import logging

logger = logging.getLogger("guardian.orchestration")


class OrchestrationService:
    def __init__(self, cloud_client: CloudClient, executor: ResilientAzureExecutor):
        self.cloud_client = cloud_client
        self.executor = executor

    async def assign_policy(self, db: AsyncSession, asset_id: int, policy_id: int) -> Asset:
        """Assigns an SLA Policy to a cloud asset and marks it as PROTECTED."""
        asset = await db.get(Asset, asset_id)
        if not asset:
            raise ValueError(f"Asset with id {asset_id} does not exist.")
        
        policy = await db.get(Policy, policy_id)
        if not policy:
            raise ValueError(f"Policy with id {policy_id} does not exist.")

        asset.policy_id = policy.id
        if asset.status != "ANOMALOUS":
            asset.status = "PROTECTED"

        await db.commit()
        await db.refresh(asset)
        logger.info(f"[Orchestration] Assigned Policy '{policy.name}' to Asset '{asset.name}'")
        return asset

    async def create_snapshot_for_asset(self, db: AsyncSession, asset_id: int) -> Snapshot:
        """
        Executes a snapshot for an asset, analyzes Shannon entropy for ransomware,
        and enforces SLA retention expiry.
        """
        asset = await db.get(Asset, asset_id)
        if not asset:
            raise ValueError(f"Asset with id {asset_id} does not exist.")

        # Get policy parameters
        policy = None
        retention_days = 30
        ransomware_scan_enabled = True

        if asset.policy_id:
            policy = await db.get(Policy, asset.policy_id)
            if policy:
                retention_days = policy.retention_days
                ransomware_scan_enabled = policy.ransomware_scan_enabled

        # 1. Orchestrate cloud snapshot creation using Resilient Executor
        logger.info(f"[Orchestration] Initiating snapshot creation for asset: {asset.name}")
        cloud_snap = await self.executor.execute(
            self.cloud_client.create_snapshot,
            {
                "azure_resource_id": asset.azure_resource_id,
                "name": asset.name,
                "resource_group": asset.resource_group,
                "region": asset.region,
                "size_bytes": asset.size_bytes
            }
        )

        # 2. Fetch sample payload to evaluate Shannon entropy
        sample_bytes = await self.executor.execute(
            self.cloud_client.read_snapshot_sample,
            cloud_snap["azure_snapshot_id"]
        )

        # 3. Retrieve previous snapshot size to evaluate data surge
        stmt = (
            select(Snapshot)
            .where(Snapshot.asset_id == asset.id)
            .order_by(desc(Snapshot.created_at))
            .limit(1)
        )
        prev_result = await db.execute(stmt)
        prev_snapshot = prev_result.scalar_one_or_none()
        prev_size = prev_snapshot.size_bytes if prev_snapshot else None

        # 4. Anomaly Evaluation
        entropy_score = 0.0
        is_anomalous = False
        anomaly_reason = None

        if ransomware_scan_enabled:
            entropy_score, is_anomalous, anomaly_reason = EntropyAnalyzer.evaluate_snapshot(
                current_data=sample_bytes,
                previous_size=prev_size,
                entropy_threshold=settings.ENTROPY_THRESHOLD,
                size_delta_threshold_percent=settings.SIZE_DELTA_THRESHOLD_PERCENT
            )

        now = utc_now()
        expires_at = now + timedelta(days=retention_days)

        snapshot_status = "ANOMALOUS" if is_anomalous else "READY"

        snapshot = Snapshot(
            azure_snapshot_id=cloud_snap["azure_snapshot_id"],
            asset_id=asset.id,
            policy_id=asset.policy_id,
            size_bytes=cloud_snap.get("size_bytes", asset.size_bytes),
            entropy_score=entropy_score,
            tier=cloud_snap.get("tier", "Hot"),
            status=snapshot_status,
            created_at=now,
            expires_at=expires_at,
            metadata_json=json.dumps({
                "region": asset.region,
                "resource_group": asset.resource_group,
                "sample_entropy": entropy_score
            })
        )
        db.add(snapshot)

        # Update Asset state
        asset.last_snapshot_at = now
        if is_anomalous:
            asset.status = "ANOMALOUS"
            metrics.record_anomaly()
            alert = AnomalyAlert(
                asset_id=asset.id,
                alert_type="HIGH_ENTROPY_RANSOMWARE" if entropy_score >= settings.ENTROPY_THRESHOLD else "SURGE_DATA_MODIFICATION",
                severity="CRITICAL",
                entropy_score=entropy_score,
                size_delta_percent=(
                    round(abs(asset.size_bytes - prev_size) / prev_size * 100.0, 2)
                    if prev_size and prev_size > 0
                    else 0.0
                ),
                details=anomaly_reason or "Suspicious anomaly detected",
                resolved=False,
                created_at=now
            )
            db.add(alert)
            logger.critical(f"[SECURITY ALERT] {anomaly_reason} for Asset: {asset.name}")

        await db.commit()
        await db.refresh(snapshot)
        logger.info(f"[Orchestration] Snapshot created: {snapshot.azure_snapshot_id} (Entropy: {entropy_score:.2f})")
        return snapshot

    async def get_latest_clean_recovery_point(self, db: AsyncSession, asset_id: int) -> Optional[Snapshot]:
        """
        Rubrik Point-in-time recovery: finds the latest non-anomalous snapshot
        prior to any ransomware or corruption event.
        """
        stmt = (
            select(Snapshot)
            .where(Snapshot.asset_id == asset_id, Snapshot.status == "READY")
            .order_by(desc(Snapshot.created_at))
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
