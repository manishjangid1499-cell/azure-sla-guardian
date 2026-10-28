import asyncio
import pytest
from guardian.core.rate_limiter import (
    TokenBucketRateLimiter,
    ResilientAzureExecutor,
    AzureRateLimitException
)


@pytest.mark.asyncio
async def test_token_bucket_allows_within_capacity():
    limiter = TokenBucketRateLimiter(tokens_per_second=10.0, capacity=5)
    # 5 acquisitions should pass with near zero wait
    waited = await limiter.acquire(tokens=1)
    assert waited == 0.0


@pytest.mark.asyncio
async def test_token_bucket_throttles_burst():
    limiter = TokenBucketRateLimiter(tokens_per_second=100.0, capacity=2)
    await limiter.acquire(2)
    # Bucket is empty, next acquire should calculate wait time
    waited = await limiter.acquire(1)
    assert waited >= 0.005


@pytest.mark.asyncio
async def test_resilient_executor_recovers_from_429():
    limiter = TokenBucketRateLimiter(tokens_per_second=100.0, capacity=10)
    executor = ResilientAzureExecutor(
        rate_limiter=limiter,
        max_retries=3,
        base_backoff=0.01,
        max_backoff=0.1,
        enable_jitter=False
    )

    call_count = 0

    async def transient_azure_call():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Simulate Azure 429 on first 2 attempts
            raise AzureRateLimitException(retry_after_seconds=0.01)
        return "SUCCESS"

    result = await executor.execute(transient_azure_call)
    assert result == "SUCCESS"
    assert call_count == 3
    assert executor.throttled_429_count == 2


@pytest.mark.asyncio
async def test_resilient_executor_exceeds_max_retries():
    limiter = TokenBucketRateLimiter(tokens_per_second=100.0, capacity=10)
    executor = ResilientAzureExecutor(
        rate_limiter=limiter,
        max_retries=2,
        base_backoff=0.01,
        max_backoff=0.05
    )

    async def permanently_failing_call():
        raise AzureRateLimitException(retry_after_seconds=0.01)

    with pytest.raises(AzureRateLimitException):
        await executor.execute(permanently_failing_call)

    assert executor.total_retries == 3
