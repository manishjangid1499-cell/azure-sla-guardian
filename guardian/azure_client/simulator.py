import os
import uuid
import time
import random
from typing import List, Dict, Any, Optional
from guardian.azure_client.base import CloudClient
from guardian.core.rate_limiter import AzureRateLimitException
from guardian.core.metrics import metrics
import logging

logger = logging.getLogger("guardian.simulator")


class AzureSimulatorClient(CloudClient):
    """
    High-fidelity Azure Cloud Sandbox Simulator.
    Simulates Azure Resource Manager (ARM), Blob Storage, and Compute Managed Disks.
    Includes built-in fault injection for HTTP 429 throttling, ransomware entropy, and data surges.
    """

    def __init__(self):
        # Initial simulated Azure resources
        self._assets: Dict[str, Dict[str, Any]] = {
            "blob-cust-rec-01": {
                "azure_resource_id": "/subscriptions/sub-sim-001/resourceGroups/rg-guardian/providers/Microsoft.Storage/storageAccounts/stguardian/blobServices/default/containers/customer-records",
                "name": "customer-records",
                "asset_type": "BLOB_CONTAINER",
                "resource_group": "rg-guardian",
                "region": "eastus",
                "size_bytes": 104857600, # 100 MB
                "tier": "Hot",
                "sample_data": b"CUSTOMER_ID,NAME,EMAIL,TIMESTAMP\n" + (b"1001,John Doe,john@example.com,2026-01-01\n" * 500)
            },
            "blob-fin-rep-02": {
                "azure_resource_id": "/subscriptions/sub-sim-001/resourceGroups/rg-guardian/providers/Microsoft.Storage/storageAccounts/stguardian/blobServices/default/containers/financial-reports-q4",
                "name": "financial-reports-q4",
                "asset_type": "BLOB_CONTAINER",
                "resource_group": "rg-guardian",
                "region": "eastus",
                "size_bytes": 524288000, # 500 MB
                "tier": "Hot",
                "sample_data": b"ACCOUNT,QUARTER,BALANCE,AUDIT_ID\n" + (b"AC-994,Q4-2025,4500000.00,AUD-882\n" * 800)
            },
            "disk-prod-db-01": {
                "azure_resource_id": "/subscriptions/sub-sim-001/resourceGroups/rg-guardian/providers/Microsoft.Compute/disks/disk-prod-postgres-db",
                "name": "disk-prod-postgres-db",
                "asset_type": "MANAGED_DISK",
                "resource_group": "rg-guardian",
                "region": "eastus2",
                "size_bytes": 107374182400, # 100 GB
                "tier": "Premium_LRS",
                "sample_data": b"PGDATA_BLOCK_HEADER_MAGIC_X88" + (b"TABLE_INDEX_METADATA_NODE_DATA\x00\x01\x02" * 400)
            },
            "disk-worker-analytics": {
                "azure_resource_id": "/subscriptions/sub-sim-001/resourceGroups/rg-guardian/providers/Microsoft.Compute/disks/disk-analytics-worker-01",
                "name": "disk-analytics-worker-01",
                "asset_type": "MANAGED_DISK",
                "resource_group": "rg-guardian",
                "region": "centralindia",
                "size_bytes": 68719476736, # 64 GB
                "tier": "StandardSSD_LRS",
                "sample_data": b"SPARK_TEMP_SHUFFLE_STREAM_BUFFER" + (b"SHUFFLE_MAP_OUTPUT_PARTITION_ID\x10\x20" * 300)
            }
        }

        # Simulated cloud snapshots store
        self._snapshots: Dict[str, Dict[str, Any]] = {}

        # Chaos / Simulation Flags
        self.fault_429_throttling_enabled = False
        self.throttling_probability = 0.5

        # Check for persistent simulated ransomware
        if os.path.exists(".simulator_ransomware.flag"):
            try:
                with open(".simulator_ransomware.flag", "r") as f:
                    infected_name = f.read().strip()
                for v in self._assets.values():
                    if v["name"] == infected_name:
                        v["sample_data"] = os.urandom(8192)
            except Exception:
                pass

    def set_fault_injection(self, enable_429: bool, probability: float = 0.5):
        self.fault_429_throttling_enabled = enable_429
        self.throttling_probability = probability
        logger.info(f"[Simulator] Fault injection updated: 429_throttling={enable_429} (prob={probability})")

    def simulate_ransomware_on_asset(self, asset_name_or_id: str):
        """Simulates a ransomware attack by encrypting the asset's payload with high-entropy bytes."""
        target_key = None
        for k, v in self._assets.items():
            if k == asset_name_or_id or v["name"] == asset_name_or_id:
                target_key = k
                break

        if not target_key:
            raise ValueError(f"Asset '{asset_name_or_id}' not found in simulated cloud.")

        # Generate pseudorandom high entropy bytes (AES ciphertext signature: entropy ~7.95)
        high_entropy_encrypted_data = os.urandom(8192)
        self._assets[target_key]["sample_data"] = high_entropy_encrypted_data
        self._assets[target_key]["size_bytes"] = int(self._assets[target_key]["size_bytes"] * 1.8) # encryption inflation
        
        # Persist ransomware state to disk for cross-CLI persistence
        try:
            state_file = ".simulator_ransomware.flag"
            with open(state_file, "w") as f:
                f.write(self._assets[target_key]["name"])
        except Exception:
            pass

        logger.warning(f"[Simulator] Injected Ransomware payload into simulated asset: {self._assets[target_key]['name']}")
        return target_key

    def _simulate_azure_latency_and_throttling(self):
        """Simulates network latency and potential Azure 429 throttling."""
        start = time.monotonic()
        # Simulated cloud roundtrip latency: 30ms - 80ms
        latency = random.uniform(0.03, 0.08)
        time.sleep(latency)
        duration_ms = (time.monotonic() - start) * 1000

        if self.fault_429_throttling_enabled and random.random() < self.throttling_probability:
            metrics.record_api_call(duration_ms, status_code=429)
            retry_after = round(random.uniform(0.5, 1.5), 2)
            logger.warning(f"[Simulator] INJECTING HTTP 429 Rate Limit (Retry-After: {retry_after}s)")
            raise AzureRateLimitException(retry_after_seconds=retry_after)

        metrics.record_api_call(duration_ms, status_code=200)

    async def discover_resources(self, resource_group: Optional[str] = None) -> List[Dict[str, Any]]:
        self._simulate_azure_latency_and_throttling()
        results = []
        for asset in self._assets.values():
            if resource_group and asset["resource_group"] != resource_group:
                continue
            results.append({
                "azure_resource_id": asset["azure_resource_id"],
                "name": asset["name"],
                "asset_type": asset["asset_type"],
                "resource_group": asset["resource_group"],
                "region": asset["region"],
                "size_bytes": asset["size_bytes"],
                "tier": asset["tier"]
            })
        return results

    async def create_snapshot(self, asset: Dict[str, Any]) -> Dict[str, Any]:
        self._simulate_azure_latency_and_throttling()
        snapshot_id = f"snap-{uuid.uuid4().hex[:12]}"
        
        # Look up sample data for this asset
        sample = b"DEFAULT_AZURE_SNAPSHOT_BLOCK_DATA"
        for item in self._assets.values():
            if item["azure_resource_id"] == asset.get("azure_resource_id") or item["name"] == asset.get("name"):
                sample = item.get("sample_data", sample)
                break

        snapshot_record = {
            "azure_snapshot_id": f"/subscriptions/sub-sim-001/resourceGroups/{asset.get('resource_group', 'rg-guardian')}/providers/Microsoft.Compute/snapshots/{snapshot_id}",
            "size_bytes": asset.get("size_bytes", 1024),
            "tier": "Hot",
            "sample_data": sample,
            "created_at_epoch": time.time()
        }
        self._snapshots[snapshot_record["azure_snapshot_id"]] = snapshot_record
        metrics.record_snapshot_created()
        return snapshot_record

    async def delete_snapshot(self, azure_snapshot_id: str) -> bool:
        self._simulate_azure_latency_and_throttling()
        if azure_snapshot_id in self._snapshots:
            del self._snapshots[azure_snapshot_id]
            metrics.record_snapshot_pruned()
            return True
        return False

    async def change_snapshot_tier(self, azure_snapshot_id: str, new_tier: str) -> bool:
        self._simulate_azure_latency_and_throttling()
        if azure_snapshot_id in self._snapshots:
            self._snapshots[azure_snapshot_id]["tier"] = new_tier
            return True
        return False

    async def read_snapshot_sample(self, azure_snapshot_id: str) -> bytes:
        self._simulate_azure_latency_and_throttling()
        if azure_snapshot_id in self._snapshots:
            return self._snapshots[azure_snapshot_id].get("sample_data", b"")
        return b""
