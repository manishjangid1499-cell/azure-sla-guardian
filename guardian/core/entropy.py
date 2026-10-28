import math
from collections import Counter
from typing import Tuple, Optional


class EntropyAnalyzer:
    """
    Computes Shannon Entropy on raw byte data and detects high-entropy
    encryption typical of ransomware infections.
    
    Formula:
        H(X) = - SUM( P(x) * log2(P(x)) )
        Maximum entropy for byte data (256 states) is 8.0.
    """

    @staticmethod
    def calculate_entropy(data: bytes) -> float:
        """
        Calculates the Shannon entropy score (0.0 to 8.0) of a byte array.
        - Text / structured data: typically 3.5 - 5.5
        - Compiled binaries / light compression: ~6.0 - 7.0
        - Strong encryption / AES / Ransomware payloads: >= 7.2 to 7.99
        """
        if not data:
            return 0.0

        length = len(data)
        counts = Counter(data)
        entropy = 0.0

        for count in counts.values():
            p_x = count / length
            if p_x > 0:
                entropy -= p_x * math.log2(p_x)

        return round(entropy, 4)

    @classmethod
    def evaluate_snapshot(
        cls,
        current_data: bytes,
        previous_size: Optional[int] = None,
        entropy_threshold: float = 7.2,
        size_delta_threshold_percent: float = 50.0
    ) -> Tuple[float, bool, Optional[str]]:
        """
        Evaluates a snapshot payload for anomalies.
        Returns:
            (entropy_score, is_anomalous, anomaly_reason)
        """
        entropy = cls.calculate_entropy(current_data)
        current_size = len(current_data)

        # 1. Check for Ransomware / Encryption pattern
        if entropy >= entropy_threshold:
            return (
                entropy,
                True,
                f"CRITICAL: High entropy detected ({entropy:.2f} >= {entropy_threshold}). "
                "Data matches signatures of strong symmetric encryption (potential ransomware)."
            )

        # 2. Check for unexpected massive size surge/drop
        if previous_size and previous_size > 0:
            delta_percent = abs(current_size - previous_size) / previous_size * 100.0
            if delta_percent >= size_delta_threshold_percent:
                return (
                    entropy,
                    True,
                    f"WARNING: Abnormal data change delta ({delta_percent:.1f}% >= {size_delta_threshold_percent}%). "
                    f"Previous size: {previous_size} bytes, Current size: {current_size} bytes."
                )

        return (entropy, False, None)
