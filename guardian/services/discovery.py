from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from guardian.azure_client.base import CloudClient
from guardian.core.rate_limiter import ResilientAzureExecutor
from guardian.models.entities import Asset, utc_now
import logging

logger = logging.getLogger("guardian.discovery")


class DiscoveryService:
    def __init__(self, cloud_client: CloudClient, executor: ResilientAzureExecutor):
        self.cloud_client = cloud_client
        self.executor = executor

    async def discover_and_sync(self, db: AsyncSession, resource_group: Optional[str] = None) -> List[Asset]:
        """
        Discovers cloud assets using resilient backoff executor,
        syncs them into the database, preserving existing policy bindings.
        """
        logger.info(f"[Discovery] Initiating cloud discovery for resource group: {resource_group or 'ALL'}")
        
        # Resilient API call (will handle 429 automatically if encountered)
        raw_assets = await self.executor.execute(
            self.cloud_client.discover_resources,
            resource_group=resource_group
        )

        synced_assets: List[Asset] = []

        for item in raw_assets:
            # Check if asset already exists in database
            stmt = select(Asset).where(Asset.azure_resource_id == item["azure_resource_id"])
            result = await db.execute(stmt)
            existing_asset = result.scalar_one_or_none()

            if existing_asset:
                existing_asset.size_bytes = item["size_bytes"]
                existing_asset.tier = item["tier"]
                existing_asset.last_discovered_at = utc_now()
                synced_assets.append(existing_asset)
            else:
                new_asset = Asset(
                    azure_resource_id=item["azure_resource_id"],
                    name=item["name"],
                    asset_type=item["asset_type"],
                    resource_group=item["resource_group"],
                    region=item["region"],
                    size_bytes=item["size_bytes"],
                    tier=item["tier"],
                    status="UNPROTECTED",
                    last_discovered_at=utc_now()
                )
                db.add(new_asset)
                synced_assets.append(new_asset)

        await db.commit()
        for a in synced_assets:
            await db.refresh(a)

        logger.info(f"[Discovery] Successfully synced {len(synced_assets)} cloud assets.")
        return synced_assets
