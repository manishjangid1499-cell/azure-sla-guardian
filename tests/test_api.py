import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from guardian.config import settings
from guardian.main import app, lifespan

# Disable background scheduler during API tests
settings.SCHEDULER_ENABLED = False


@pytest_asyncio.fixture(autouse=True)
async def setup_app_lifespan():
    async with lifespan(app):
        yield


@pytest.mark.asyncio
async def test_api_root_and_metrics():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test dashboard HTML endpoint
        res = await client.get("/")
        assert res.status_code == 200
        assert "Azure Guardian" in res.text

        # Test Prometheus metrics endpoint
        metrics_res = await client.get("/metrics")
        assert metrics_res.status_code == 200
        assert "azure_guardian_api_calls_total" in metrics_res.text


@pytest.mark.asyncio
async def test_api_full_discovery_and_snapshot_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Discover assets
        disc_res = await client.post("/api/v1/assets/discover")
        assert disc_res.status_code == 200
        assets = disc_res.json()
        assert len(assets) > 0
        
        # Pick an asset to test
        unprotected = [a for a in assets if a["status"] == "UNPROTECTED"]
        test_asset = unprotected[0] if unprotected else assets[-1]
        test_asset["status"] = "UNPROTECTED"
        asset_id = test_asset["id"]

        # 2. Get Policies
        pol_res = await client.get("/api/v1/policies")
        assert pol_res.status_code == 200
        policies = pol_res.json()
        assert len(policies) > 0
        gold_policy_id = policies[0]["id"]

        # 3. Assign Policy
        assign_res = await client.post(
            f"/api/v1/assets/{asset_id}/assign-policy",
            json={"policy_id": gold_policy_id}
        )
        assert assign_res.status_code == 200
        assert assign_res.json()["status"] == "PROTECTED"

        # 4. Trigger Snapshot
        snap_res = await client.post(f"/api/v1/snapshots/trigger/{asset_id}")
        assert snap_res.status_code == 200
        snapshot = snap_res.json()
        assert snapshot["status"] == "READY"
        assert "azure_snapshot_id" in snapshot

        # 5. Check Metrics Summary
        summary_res = await client.get("/api/v1/metrics/summary")
        assert summary_res.status_code == 200
        summary = summary_res.json()
        assert summary["total_assets"] >= 1
        assert summary["total_snapshots"] >= 1

