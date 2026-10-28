import os
import pytest
from guardian.core.entropy import EntropyAnalyzer


def test_entropy_zero_on_empty():
    assert EntropyAnalyzer.calculate_entropy(b"") == 0.0


def test_entropy_low_on_repetitive_data():
    # Repetitive character has low entropy (0.0 for all identical bytes)
    data = b"A" * 1000
    entropy = EntropyAnalyzer.calculate_entropy(data)
    assert entropy == 0.0


def test_entropy_normal_text():
    # Natural language structured text is typically between 3.5 and 5.5
    text = (
        b"Rubrik Cloud Native Protection orchestrates data management, "
        b"incremental snapshots, and disaster recovery across Microsoft Azure."
    ) * 10
    entropy = EntropyAnalyzer.calculate_entropy(text)
    assert 3.5 <= entropy <= 5.5


def test_entropy_high_on_random_ciphertext():
    # High-entropy random bytes (AES encryption / ransomware payload signature)
    # 8-bit random bytes have entropy approaching theoretical max (8.0), typically > 7.9
    encrypted_data = os.urandom(4096)
    entropy = EntropyAnalyzer.calculate_entropy(encrypted_data)
    assert entropy >= 7.8


def test_evaluate_snapshot_detects_ransomware():
    encrypted_data = os.urandom(4096)
    entropy, is_anomalous, reason = EntropyAnalyzer.evaluate_snapshot(
        current_data=encrypted_data,
        previous_size=4096,
        entropy_threshold=7.2
    )
    assert is_anomalous is True
    assert "High entropy detected" in reason
    assert entropy >= 7.2


def test_evaluate_snapshot_detects_size_surge():
    normal_data = b"Normal application log payload " * 100
    entropy, is_anomalous, reason = EntropyAnalyzer.evaluate_snapshot(
        current_data=normal_data,
        previous_size=500, # Current size is 3100, delta > 500%
        entropy_threshold=7.2,
        size_delta_threshold_percent=50.0
    )
    assert is_anomalous is True
    assert "Abnormal data change delta" in reason
