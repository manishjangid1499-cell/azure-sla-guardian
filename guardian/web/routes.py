from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from guardian.models.database import get_db
from guardian.models.entities import Asset, Policy, Snapshot, AnomalyAlert
from guardian.models.schemas import (
    AssetResponse, AssetPolicyAssign, PolicyResponse, PolicyCreate,
    SnapshotResponse, AnomalyAlertResponse, MetricsSummary, SimulationInjectRequest
)
from guardian.core.metrics import metrics
from guardian.services.discovery import DiscoveryService
from guardian.services.orchestration import OrchestrationService
from guardian.azure_client.simulator import AzureSimulatorClient

api_router = APIRouter(prefix="/api/v1")

# We will inject these dependencies during application initialization
discovery_service: Optional[DiscoveryService] = None
orchestration_service: Optional[OrchestrationService] = None
simulator_client: Optional[AzureSimulatorClient] = None


def set_services(disc: DiscoveryService, orch: OrchestrationService, sim: Optional[AzureSimulatorClient]):
    global discovery_service, orchestration_service, simulator_client
    discovery_service = disc
    orchestration_service = orch
    simulator_client = sim


# ----------------- ASSETS -----------------
@api_router.get("/assets", response_model=List[AssetResponse])
async def list_assets(db: AsyncSession = Depends(get_db)):
    stmt = select(Asset).order_by(Asset.id)
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.post("/assets/discover", response_model=List[AssetResponse])
async def discover_cloud_assets(
    resource_group: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    if not discovery_service:
        raise HTTPException(status_code=500, detail="Discovery service not initialized")
    assets = await discovery_service.discover_and_sync(db, resource_group=resource_group)
    return assets


@api_router.post("/assets/{asset_id}/assign-policy", response_model=AssetResponse)
async def assign_policy_to_asset(
    asset_id: int,
    payload: AssetPolicyAssign,
    db: AsyncSession = Depends(get_db)
):
    if not orchestration_service:
        raise HTTPException(status_code=500, detail="Orchestration service not initialized")
    try:
        updated_asset = await orchestration_service.assign_policy(db, asset_id, payload.policy_id)
        return updated_asset
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ----------------- POLICIES (SLA DOMAINS) -----------------
@api_router.get("/policies", response_model=List[PolicyResponse])
async def list_policies(db: AsyncSession = Depends(get_db)):
    stmt = select(Policy).order_by(Policy.id)
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.post("/policies", response_model=PolicyResponse)
async def create_policy(payload: PolicyCreate, db: AsyncSession = Depends(get_db)):
    policy = Policy(
        name=payload.name,
        description=payload.description,
        frequency_minutes=payload.frequency_minutes,
        retention_days=payload.retention_days,
        tier_to_cool_after_days=payload.tier_to_cool_after_days,
        ransomware_scan_enabled=payload.ransomware_scan_enabled
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


# ----------------- SNAPSHOTS & RECOVERY -----------------
@api_router.get("/snapshots", response_model=List[SnapshotResponse])
async def list_snapshots(
    asset_id: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Snapshot).order_by(desc(Snapshot.created_at)).limit(limit)
    if asset_id:
        stmt = stmt.where(Snapshot.asset_id == asset_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.post("/snapshots/trigger/{asset_id}", response_model=SnapshotResponse)
async def trigger_snapshot(asset_id: int, db: AsyncSession = Depends(get_db)):
    if not orchestration_service:
        raise HTTPException(status_code=500, detail="Orchestration service not initialized")
    try:
        snapshot = await orchestration_service.create_snapshot_for_asset(db, asset_id)
        return snapshot
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@api_router.get("/recovery-point/{asset_id}", response_model=Optional[SnapshotResponse])
async def get_latest_clean_recovery_point(asset_id: int, db: AsyncSession = Depends(get_db)):
    """Rubrik Point-in-time recovery point lookup (filters out ransomware snapshots)."""
    if not orchestration_service:
        raise HTTPException(status_code=500, detail="Orchestration service not initialized")
    point = await orchestration_service.get_latest_clean_recovery_point(db, asset_id)
    if not point:
        raise HTTPException(status_code=404, detail="No clean recovery point found for this asset.")
    return point


# ----------------- ANOMALIES & ALERTS -----------------
@api_router.get("/anomalies", response_model=List[AnomalyAlertResponse])
async def list_anomaly_alerts(db: AsyncSession = Depends(get_db)):
    stmt = select(AnomalyAlert).order_by(desc(AnomalyAlert.created_at))
    result = await db.execute(stmt)
    return result.scalars().all()


@api_router.post("/anomalies/{alert_id}/resolve")
async def resolve_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    alert = await db.get(AnomalyAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.resolved = True
    await db.commit()
    return {"status": "success", "message": f"Alert {alert_id} resolved"}


# ----------------- METRICS -----------------
@api_router.get("/metrics/summary", response_model=MetricsSummary)
async def get_metrics_summary(db: AsyncSession = Depends(get_db)):
    total_assets = await db.scalar(select(func.count(Asset.id))) or 0
    protected_assets = await db.scalar(select(func.count(Asset.id)).where(Asset.status == "PROTECTED")) or 0
    total_snapshots = await db.scalar(select(func.count(Snapshot.id)).where(Snapshot.status == "READY")) or 0
    active_anomalies = await db.scalar(select(func.count(AnomalyAlert.id)).where(AnomalyAlert.resolved == False)) or 0

    summary = metrics.get_summary()
    return MetricsSummary(
        total_assets=total_assets,
        protected_assets=protected_assets,
        total_snapshots=total_snapshots,
        active_anomalies=active_anomalies,
        api_calls_count=summary["api_calls_count"],
        rate_limit_throttled_count=summary["throttled_429_count"],
        avg_latency_ms=summary["avg_latency_ms"]
    )


# ----------------- SIMULATION & CHAOS INJECTION -----------------
@api_router.post("/simulate/inject")
async def inject_simulation_faults(payload: SimulationInjectRequest):
    """
    Chaos Engineering endpoint:
    - Injects HTTP 429 throttling to test token-bucket rate limiter & backoff.
    - Injects high-entropy ransomware payload into an asset to test ransomware detection.
    """
    if not simulator_client:
        return {"status": "ignored", "message": "Simulation is only active in simulator mode."}

    messages = []
    if payload.inject_429_throttling is not None:
        simulator_client.set_fault_injection(payload.inject_429_throttling, probability=0.6)
        state_str = "ENABLED (60% probability)" if payload.inject_429_throttling else "DISABLED"
        messages.append(f"Azure HTTP 429 Rate Throttling: {state_str}")

    if payload.simulate_ransomware_on_asset:
        try:
            target = simulator_client.simulate_ransomware_on_asset(payload.simulate_ransomware_on_asset)
            messages.append(f"Injected high-entropy ransomware payload into '{target}'. Next snapshot will trigger security alarm.")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return {"status": "ok", "actions": messages}
