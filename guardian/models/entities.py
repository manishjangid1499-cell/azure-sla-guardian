from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from guardian.models.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    frequency_minutes: Mapped[int] = mapped_column(Integer, default=60)  # minutes between snapshots
    retention_days: Mapped[int] = mapped_column(Integer, default=30)     # days before deletion
    tier_to_cool_after_days: Mapped[int] = mapped_column(Integer, default=7)
    ransomware_scan_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assets: Mapped[list["Asset"]] = relationship("Asset", back_populates="policy", lazy="selectin")
    snapshots: Mapped[list["Snapshot"]] = relationship("Snapshot", back_populates="policy", lazy="selectin")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    azure_resource_id: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    asset_type: Mapped[str] = mapped_column(String(50), default="BLOB_CONTAINER") # BLOB_CONTAINER, MANAGED_DISK
    resource_group: Mapped[str] = mapped_column(String(100), default="rg-guardian")
    region: Mapped[str] = mapped_column(String(50), default="eastus")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(50), default="Hot")
    status: Mapped[str] = mapped_column(String(50), default="UNPROTECTED") # PROTECTED, UNPROTECTED, ANOMALOUS
    last_snapshot_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    policy_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("policies.id"), nullable=True)

    policy: Mapped[Optional[Policy]] = relationship("Policy", back_populates="assets", lazy="selectin")
    snapshots: Mapped[list["Snapshot"]] = relationship("Snapshot", back_populates="asset", cascade="all, delete-orphan", lazy="selectin")
    alerts: Mapped[list["AnomalyAlert"]] = relationship("AnomalyAlert", back_populates="asset", lazy="selectin")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    azure_snapshot_id: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    asset_id: Mapped[int] = mapped_column(Integer, ForeignKey("assets.id"), index=True)
    policy_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("policies.id"), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    entropy_score: Mapped[float] = mapped_column(Float, default=0.0)
    tier: Mapped[str] = mapped_column(String(50), default="Hot") # Hot, Cool, Archive
    status: Mapped[str] = mapped_column(String(50), default="READY") # READY, CREATING, PRUNED, ANOMALOUS
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    asset: Mapped[Asset] = relationship("Asset", back_populates="snapshots", lazy="selectin")
    policy: Mapped[Optional[Policy]] = relationship("Policy", back_populates="snapshots", lazy="selectin")


class AnomalyAlert(Base):
    __tablename__ = "anomaly_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(Integer, ForeignKey("assets.id"))
    snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("snapshots.id"), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(100)) # HIGH_ENTROPY_RANSOMWARE, SURGE_DATA_MODIFICATION
    severity: Mapped[str] = mapped_column(String(50), default="CRITICAL") # CRITICAL, WARNING, INFO
    entropy_score: Mapped[float] = mapped_column(Float, default=0.0)
    size_delta_percent: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    asset: Mapped[Asset] = relationship("Asset", back_populates="alerts", lazy="selectin")


class MetricLog(Base):
    __tablename__ = "metric_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    metric_type: Mapped[str] = mapped_column(String(100)) # AZURE_API_CALL, RATE_LIMIT_THROTTLED_429, BACKUP_COMPLETED
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
