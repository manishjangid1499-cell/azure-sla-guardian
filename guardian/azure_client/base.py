from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class CloudClient(ABC):
    """
    Abstract interface for Cloud Infrastructure Operations.
    Implemented by LiveAzureClient (production Azure SDK)
    and AzureSimulatorClient (local sandbox & interview demonstration).
    """

    @abstractmethod
    async def discover_resources(self, resource_group: Optional[str] = None) -> List[Dict[str, Any]]:
        """Discovers all Azure Storage Blobs and Managed Disks."""
        pass

    @abstractmethod
    async def create_snapshot(self, asset: Dict[str, Any]) -> Dict[str, Any]:
        """Creates an incremental point-in-time snapshot for a given cloud asset."""
        pass

    @abstractmethod
    async def delete_snapshot(self, azure_snapshot_id: str) -> bool:
        """Deletes a snapshot on the cloud provider."""
        pass

    @abstractmethod
    async def change_snapshot_tier(self, azure_snapshot_id: str, new_tier: str) -> bool:
        """Transitions snapshot storage tier (e.g. Hot -> Cool -> Archive)."""
        pass

    @abstractmethod
    async def read_snapshot_sample(self, azure_snapshot_id: str) -> bytes:
        """Reads sample payload from snapshot to calculate Shannon entropy."""
        pass
