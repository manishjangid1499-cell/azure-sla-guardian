import time
from typing import Dict, Any


class MetricsCollector:
    """
    In-memory performance and observability tracker.
    Tracks Azure API latencies, 429 throttling occurrences, and SLA compliance.
    """
    def __init__(self):
        self.api_calls_count = 0
        self.throttled_429_count = 0
        self.snapshots_created_count = 0
        self.snapshots_pruned_count = 0
        self.anomalies_detected_count = 0
        self.total_latency_ms = 0.0

    def record_api_call(self, latency_ms: float, status_code: int = 200):
        self.api_calls_count += 1
        self.total_latency_ms += latency_ms
        if status_code == 429:
            self.throttled_429_count += 1

    def record_snapshot_created(self):
        self.snapshots_created_count += 1

    def record_snapshot_pruned(self):
        self.snapshots_pruned_count += 1

    def record_anomaly(self):
        self.anomalies_detected_count += 1

    def get_summary(self) -> Dict[str, Any]:
        avg_latency = (
            round(self.total_latency_ms / self.api_calls_count, 2)
            if self.api_calls_count > 0
            else 0.0
        )
        return {
            "api_calls_count": self.api_calls_count,
            "throttled_429_count": self.throttled_429_count,
            "snapshots_created_count": self.snapshots_created_count,
            "snapshots_pruned_count": self.snapshots_pruned_count,
            "anomalies_detected_count": self.anomalies_detected_count,
            "avg_latency_ms": avg_latency
        }

    def generate_prometheus_metrics(self) -> str:
        """Outputs Prometheus exposition format."""
        summary = self.get_summary()
        lines = [
            "# HELP azure_guardian_api_calls_total Total calls made to Azure APIs",
            "# TYPE azure_guardian_api_calls_total counter",
            f"azure_guardian_api_calls_total {summary['api_calls_count']}",
            "",
            "# HELP azure_guardian_api_429_throttled_total Total 429 rate-limit responses received",
            "# TYPE azure_guardian_api_429_throttled_total counter",
            f"azure_guardian_api_429_throttled_total {summary['throttled_429_count']}",
            "",
            "# HELP azure_guardian_snapshots_created_total Total snapshots orchestrated",
            "# TYPE azure_guardian_snapshots_created_total counter",
            f"azure_guardian_snapshots_created_total {summary['snapshots_created_count']}",
            "",
            "# HELP azure_guardian_anomalies_detected_total Total ransomware / surge anomalies",
            "# TYPE azure_guardian_anomalies_detected_total counter",
            f"azure_guardian_anomalies_detected_total {summary['anomalies_detected_count']}",
            "",
            "# HELP azure_guardian_api_latency_ms Average latency of cloud API calls",
            "# TYPE azure_guardian_api_latency_ms gauge",
            f"azure_guardian_api_latency_ms {summary['avg_latency_ms']}",
        ]
        return "\n".join(lines) + "\n"


metrics = MetricsCollector()
