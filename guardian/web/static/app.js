// Azure SLA Guardian Dashboard Frontend Logic

let chaos429Active = false;

document.addEventListener("DOMContentLoaded", () => {
    fetchMetrics();
    fetchAssets();
    fetchSnapshots();
    fetchAnomalies();

    // Attach button listeners
    document.getElementById("btn-discover").addEventListener("click", triggerDiscovery);
    document.getElementById("btn-chaos-429").addEventListener("click", toggleChaos429);
    document.getElementById("btn-chaos-ransomware").addEventListener("click", triggerRansomwareChaos);

    // Auto refresh every 5 seconds
    setInterval(() => {
        fetchMetrics();
        fetchAssets();
        fetchSnapshots();
        fetchAnomalies();
    }, 5000);
});

async function fetchMetrics() {
    try {
        const res = await fetch("/api/v1/metrics/summary");
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById("val-total-assets").innerText = data.total_assets;
        document.getElementById("val-protected-assets").innerText = `${data.protected_assets} Protected with SLA`;
        document.getElementById("val-total-snapshots").innerText = data.total_snapshots;
        document.getElementById("val-active-anomalies").innerText = data.active_anomalies;
        document.getElementById("val-429-count").innerText = data.rate_limit_throttled_count;
        document.getElementById("val-avg-latency").innerText = `Avg Latency: ${data.avg_latency_ms}ms`;

        const anomalyStatus = document.getElementById("val-anomaly-status");
        if (data.active_anomalies > 0) {
            anomalyStatus.innerText = "THREAT DETECTED";
            anomalyStatus.className = "metric-footer text-danger";
        } else {
            anomalyStatus.innerText = "System Secure";
            anomalyStatus.className = "metric-footer text-success";
        }
    } catch (e) {
        console.error("Failed to fetch metrics", e);
    }
}

async function fetchAssets() {
    try {
        const res = await fetch("/api/v1/assets");
        if (!res.ok) return;
        const assets = await res.json();
        const tbody = document.getElementById("assets-table-body");

        if (assets.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">Click "Discover Assets" to scan the cloud.</td></tr>`;
            return;
        }

        tbody.innerHTML = assets.map(asset => {
            const sizeMb = (asset.size_bytes / (1024 * 1024)).toFixed(1);
            let statusBadge = "badge-muted";
            if (asset.status === "PROTECTED") statusBadge = "badge-success";
            else if (asset.status === "ANOMALOUS") statusBadge = "badge-danger";

            const policyLabel = asset.policy ? `<span class="badge badge-info">${asset.policy.name}</span>` : `<span class="badge badge-muted">None</span>`;

            return `
                <tr>
                    <td><strong>${asset.name}</strong></td>
                    <td><code>${asset.asset_type}</code></td>
                    <td>${asset.region} / ${asset.tier}</td>
                    <td>${sizeMb} MB</td>
                    <td>${policyLabel}</td>
                    <td><span class="badge ${statusBadge}">${asset.status}</span></td>
                    <td>
                        <button class="btn btn-sm btn-primary" onclick="snapshotAsset(${asset.id})">Snapshot</button>
                        <button class="btn btn-sm btn-warning" onclick="assignSla(${asset.id})">Set Gold SLA</button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Failed to fetch assets", e);
    }
}

async function fetchSnapshots() {
    try {
        const res = await fetch("/api/v1/snapshots");
        if (!res.ok) return;
        const snapshots = await res.json();
        const tbody = document.getElementById("snapshots-table-body");

        if (snapshots.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No snapshots recorded yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = snapshots.slice(0, 10).map(snap => {
            let entropyBadge = "badge-success";
            if (snap.entropy_score >= 7.2) {
                entropyBadge = "badge-danger";
            } else if (snap.entropy_score >= 6.0) {
                entropyBadge = "badge-warning";
            }

            const created = new Date(snap.created_at).toLocaleTimeString();
            const expires = new Date(snap.expires_at).toLocaleDateString();

            return `
                <tr>
                    <td><code>${snap.azure_snapshot_id.split('/').pop()}</code></td>
                    <td>#${snap.asset_id}</td>
                    <td><span class="badge badge-info">${snap.tier}</span></td>
                    <td><span class="badge ${entropyBadge}">H(X) = ${snap.entropy_score.toFixed(2)}</span></td>
                    <td>${created}</td>
                    <td>${expires}</td>
                    <td><span class="badge ${snap.status === 'READY' ? 'badge-success' : 'badge-danger'}">${snap.status}</span></td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Failed to fetch snapshots", e);
    }
}

async function fetchAnomalies() {
    try {
        const res = await fetch("/api/v1/anomalies");
        if (!res.ok) return;
        const alerts = await res.json();
        const active = alerts.filter(a => !a.resolved);
        const alertBox = document.getElementById("security-alert-box");

        if (active.length > 0) {
            alertBox.style.display = "block";
            const topAlert = active[0];
            document.getElementById("alert-title").innerText = `CRITICAL THREAT: ${topAlert.alert_type} on Asset #${topAlert.asset_id}`;
            document.getElementById("alert-desc").innerText = topAlert.details;
        } else {
            alertBox.style.display = "none";
        }
    } catch (e) {
        console.error("Failed to fetch anomalies", e);
    }
}

async function triggerDiscovery() {
    const btn = document.getElementById("btn-discover");
    btn.disabled = true;
    btn.innerText = "Scanning...";
    try {
        await fetch("/api/v1/assets/discover", { method: "POST" });
        await fetchAssets();
        await fetchMetrics();
    } finally {
        btn.disabled = false;
        btn.innerText = "🔍 Discover Assets";
    }
}

async function snapshotAsset(assetId) {
    try {
        const res = await fetch(`/api/v1/snapshots/trigger/${assetId}`, { method: "POST" });
        if (res.ok) {
            await fetchSnapshots();
            await fetchAssets();
            await fetchMetrics();
            await fetchAnomalies();
        }
    } catch (e) {
        alert("Snapshot failed: " + e);
    }
}

async function assignSla(assetId) {
    try {
        // Assign Gold Policy (id: 1)
        const res = await fetch(`/api/v1/assets/${assetId}/assign-policy`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ policy_id: 1 })
        });
        if (res.ok) {
            await fetchAssets();
            await fetchMetrics();
        }
    } catch (e) {
        alert("Assign policy failed: " + e);
    }
}

async function toggleChaos429() {
    chaos429Active = !chaos429Active;
    const label = document.getElementById("label-chaos-429");
    label.innerText = chaos429Active ? "🛑 Disable 429 Chaos" : "⚡ Inject HTTP 429";

    await fetch("/api/v1/simulate/inject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inject_429_throttling: chaos429Active })
    });
}

async function triggerRansomwareChaos() {
    const assetName = prompt("Enter asset name to infect with simulated ransomware (e.g. customer-records):", "customer-records");
    if (!assetName) return;

    const res = await fetch("/api/v1/simulate/inject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ simulate_ransomware_on_asset: assetName })
    });
    const data = await res.json();
    alert(data.actions.join("\n"));
}
