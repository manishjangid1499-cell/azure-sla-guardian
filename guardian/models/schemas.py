from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


# Policy Schemas
class PolicyBase(BaseModel):
    name: str
    description: Optional[str] = None
    frequency_minutes: int = 60
    retention_days: int = 30
    tier_to_cool_after_days: int = 7
    ransomware_scan_enabled: bool = True


class PolicyCreate(PolicyBase):
    pass


class PolicyResponse(PolicyBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Asset Schemas
class AssetBase(BaseModel):
    azure_resource_id: str
    name: str
    asset_type: str
    resource_group: str
    region: str
    size_bytes: int
    tier: str


class AssetCreate(AssetBase):
    pass


class AssetResponse(AssetBase):
    id: int
    status: str
    last_snapshot_at: Optional[datetime] = None
    last_discovered_at: datetime
    policy_id: Optional[int] = None
    policy: Optional[PolicyResponse] = None
    model_config = ConfigDict(from_attributes=True)


class AssetPolicyAssign(BaseModel):
    policy_id: int


# Snapshot Schemas
class SnapshotResponse(BaseModel):
    id: int
    azure_snapshot_id: str
    asset_id: int
    policy_id: Optional[int] = None
    size_bytes: int
    entropy_score: float
    tier: str
    status: str
    created_at: datetime
    expires_at: datetime
    metadata_json: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# Anomaly Alert Schemas
class AnomalyAlertResponse(BaseModel):
    id: int
    asset_id: int
    snapshot_id: Optional[int] = None
    alert_type: str
    severity: str
    entropy_score: float
    size_delta_percent: float
    details: str
    resolved: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Metrics & Simulation Schemas
class MetricsSummary(BaseModel):
    total_assets: int
    protected_assets: int
    total_snapshots: int
    active_anomalies: int
    api_calls_count: int
    rate_limit_throttled_count: int
    avg_latency_ms: float


class SimulationInjectRequest(BaseModel):
    inject_429_throttling: bool = False
    simulate_ransomware_on_asset: Optional[str] = None # asset name or id
    data_surge_percentage: Optional[float] = None
