import asyncio
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from sqlalchemy import select
from guardian.models.database import AsyncSessionLocal, init_db
from guardian.models.entities import Asset, Policy, Snapshot, AnomalyAlert
from guardian.azure_client.simulator import AzureSimulatorClient
from guardian.azure_client.live import LiveAzureClient
from guardian.core.rate_limiter import TokenBucketRateLimiter, ResilientAzureExecutor
from guardian.services.discovery import DiscoveryService
from guardian.services.orchestration import OrchestrationService
from guardian.services.retention import RetentionService
from guardian.config import settings

cli_app = typer.Typer(help="Azure-SLA-Guardian CLI: Enterprise Cloud Native Protection Tool")
console = Console()


def get_services():
    limiter = TokenBucketRateLimiter(
        tokens_per_second=settings.RATE_LIMIT_TOKENS_PER_SEC,
        capacity=settings.RATE_LIMIT_BUCKET_CAPACITY
    )
    executor = ResilientAzureExecutor(
        rate_limiter=limiter,
        max_retries=settings.MAX_RETRIES,
        base_backoff=settings.BACKOFF_BASE_SECONDS,
        max_backoff=settings.BACKOFF_MAX_SECONDS,
        enable_jitter=settings.BACKOFF_JITTER
    )

    if settings.CLOUD_MODE == "azure":
        client = LiveAzureClient()
        sim = None
    else:
        client = AzureSimulatorClient()
        sim = client

    discovery = DiscoveryService(client, executor)
    orchestration = OrchestrationService(client, executor)
    retention = RetentionService(client, executor)
    return discovery, orchestration, retention, sim


async def seed_default_policies():
    """Seeds Gold, Silver, and Bronze SLA policies if they don't exist."""
    async with AsyncSessionLocal() as db:
        stmt = select(Policy)
        result = await db.execute(stmt)
        existing = result.scalars().all()
        if not existing:
            default_policies = [
                Policy(name="Gold", description="Mission critical (15m backup, 30d retention, Cool after 7d)", frequency_minutes=15, retention_days=30, tier_to_cool_after_days=7),
                Policy(name="Silver", description="Standard production (1h backup, 14d retention)", frequency_minutes=60, retention_days=14, tier_to_cool_after_days=5),
                Policy(name="Bronze", description="Dev / Non-critical (24h backup, 7d retention)", frequency_minutes=1440, retention_days=7, tier_to_cool_after_days=3),
            ]
            db.add_all(default_policies)
            await db.commit()


@cli_app.command("discover")
def discover_cmd(resource_group: str = typer.Option("rg-guardian", help="Azure Resource Group to scan")):
    """Discovers all Azure Cloud Assets and syncs to database."""
    async def _run():
        await init_db()
        await seed_default_policies()
        discovery, _, _, _ = get_services()
        async with AsyncSessionLocal() as db:
            console.print(f"[bold blue]Scanning cloud resources in group '{resource_group}'...[/bold blue]")
            assets = await discovery.discover_and_sync(db, resource_group=resource_group)
            
            table = Table(title=f"Discovered Cloud Assets ({len(assets)})", header_style="bold magenta")
            table.add_column("ID", justify="right")
            table.add_column("Asset Name", style="cyan")
            table.add_column("Type", style="green")
            table.add_column("Region")
            table.add_column("Size (MB)", justify="right")
            table.add_column("Status")

            for a in assets:
                table.add_row(
                    str(a.id),
                    a.name,
                    a.asset_type,
                    a.region,
                    f"{a.size_bytes / (1024*1024):.1f}",
                    f"[green]{a.status}[/green]" if a.status == "PROTECTED" else f"[yellow]{a.status}[/yellow]"
                )
            console.print(table)

    asyncio.run(_run())


@cli_app.command("list-assets")
def list_assets_cmd():
    """Lists all tracked assets and SLA assignment."""
    async def _run():
        await init_db()
        async with AsyncSessionLocal() as db:
            stmt = select(Asset).order_by(Asset.id)
            result = await db.execute(stmt)
            assets = result.scalars().all()

            if not assets:
                console.print("[yellow]No assets found in catalog. Run 'discover' first.[/yellow]")
                return

            table = Table(title="Tracked Cloud Assets", header_style="bold cyan")
            table.add_column("ID", justify="right")
            table.add_column("Name", style="bold white")
            table.add_column("Type")
            table.add_column("Policy (SLA)")
            table.add_column("Status")
            table.add_column("Last Snapshot")

            for a in assets:
                policy_name = a.policy.name if a.policy else "None"
                status_color = "green" if a.status == "PROTECTED" else ("red" if a.status == "ANOMALOUS" else "yellow")
                last_snap = a.last_snapshot_at.strftime("%Y-%m-%d %H:%M") if a.last_snapshot_at else "Never"
                table.add_row(
                    str(a.id),
                    a.name,
                    a.asset_type,
                    f"[magenta]{policy_name}[/magenta]",
                    f"[{status_color}]{a.status}[/{status_color}]",
                    last_snap
                )
            console.print(table)

    asyncio.run(_run())


@cli_app.command("assign-sla")
def assign_sla_cmd(
    asset_id: int = typer.Option(..., "--asset-id", "-a", help="Asset ID"),
    policy_id: int = typer.Option(..., "--policy-id", "-p", help="Policy ID (1: Gold, 2: Silver, 3: Bronze)")
):
    """Assigns an SLA Policy to a cloud asset."""
    async def _run():
        await init_db()
        _, orchestration, _, _ = get_services()
        async with AsyncSessionLocal() as db:
            try:
                asset = await orchestration.assign_policy(db, asset_id, policy_id)
                console.print(f"[bold green]Successfully assigned SLA to '{asset.name}'! Status is now {asset.status}.[/bold green]")
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")

    asyncio.run(_run())


@cli_app.command("snapshot")
def snapshot_cmd(asset_id: int = typer.Option(..., "--asset-id", "-a", help="Asset ID to snapshot")):
    """Manually triggers a snapshot with Shannon entropy & ransomware scan."""
    async def _run():
        await init_db()
        _, orchestration, _, _ = get_services()
        async with AsyncSessionLocal() as db:
            console.print(f"[cyan]Orchestrating snapshot for Asset #{asset_id}...[/cyan]")
            try:
                snap = await orchestration.create_snapshot_for_asset(db, asset_id)
                entropy_color = "red" if snap.entropy_score >= 7.2 else "green"
                status_color = "red" if snap.status == "ANOMALOUS" else "green"

                panel = Panel(
                    f"[bold white]Snapshot ID:[/bold white] {snap.azure_snapshot_id}\n"
                    f"[bold white]Status:[/bold white] [{status_color}]{snap.status}[/{status_color}]\n"
                    f"[bold white]Shannon Entropy:[/bold white] [{entropy_color}]{snap.entropy_score:.4f}[/{entropy_color}] (Threshold: 7.2)\n"
                    f"[bold white]Tier:[/bold white] {snap.tier}\n"
                    f"[bold white]Expires At:[/bold white] {snap.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    title="Snapshot Result",
                    border_style=status_color
                )
                console.print(panel)
            except Exception as e:
                console.print(f"[bold red]Failed:[/bold red] {e}")

    asyncio.run(_run())


@cli_app.command("simulate-ransomware")
def simulate_ransomware_cmd(asset_name: str = typer.Option("customer-records", help="Asset name to infect")):
    """Simulates a ransomware encryption surge on an asset to test detection."""
    _, _, _, sim = get_services()
    if not sim:
        console.print("[red]Simulate command only available when CLOUD_MODE=simulator[/red]")
        return

    try:
        sim.simulate_ransomware_on_asset(asset_name)
        console.print(Panel(
            f"[bold red]Ransomware infection simulated on '{asset_name}'![/bold red]\n"
            "Payload has been replaced with high-entropy pseudo-random ciphertext (AES-256 signature).\n"
            "Run 'snapshot' on this asset to observe the entropy alarm!",
            title="Chaos Engineering",
            border_style="red"
        ))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@cli_app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", help="Host address"),
    port: int = typer.Option(8000, help="Port")
):
    """Starts the FastAPI Web Service, Dashboard, and SLA Background Daemon."""
    import uvicorn
    console.print(f"[bold green]Starting Azure Guardian Server on http://{host}:{port}...[/bold green]")
    uvicorn.run("guardian.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    cli_app()
