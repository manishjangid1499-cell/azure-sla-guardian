import asyncio
import time
import random
from typing import Callable, Any, TypeVar, Coroutine
import logging

logger = logging.getLogger("guardian.rate_limiter")

T = TypeVar("T")


class AzureRateLimitException(Exception):
    """Raised when Azure returns HTTP 429 Too Many Requests."""
    def __init__(self, retry_after_seconds: float = 2.0, message: str = "Azure API rate limit reached (HTTP 429)"):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TokenBucketRateLimiter:
    """
    Token Bucket Rate Limiter to throttle outbound requests to Azure APIs.
    Ensures outbound bursts are smoothly controlled without exhausting cloud quotas.
    """
    def __init__(self, tokens_per_second: float = 10.0, capacity: int = 25):
        self.rate = tokens_per_second
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquires `tokens`. If not enough tokens are available, calculates delay and sleeps.
        Returns the duration waited in seconds.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.last_refill = now
            # Refill tokens according to elapsed time
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0

            # Compute needed sleep duration
            needed = tokens - self.tokens
            wait_time = needed / self.rate
            self.tokens = 0.0

        if wait_time > 0:
            logger.debug(f"[RateLimiter] Throttling outbound request, waiting {wait_time:.3f}s")
            await asyncio.sleep(wait_time)
        return wait_time


class ResilientAzureExecutor:
    """
    Wraps asynchronous calls with Token Bucket Throttling and
    Full-Jitter Exponential Backoff for handling HTTP 429 and transient errors.
    """
    def __init__(
        self,
        rate_limiter: TokenBucketRateLimiter,
        max_retries: int = 5,
        base_backoff: float = 0.5,
        max_backoff: float = 10.0,
        enable_jitter: bool = True
    ):
        self.rate_limiter = rate_limiter
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.enable_jitter = enable_jitter
        self.throttled_429_count = 0
        self.total_retries = 0

    def _calculate_backoff(self, attempt: int, retry_after: float = 0.0) -> float:
        if retry_after > 0:
            return retry_after

        # Exponential backoff: base * 2^attempt
        delay = min(self.max_backoff, self.base_backoff * (2 ** attempt))

        if self.enable_jitter:
            # Full jitter: random between 0 and delay
            delay = random.uniform(self.base_backoff, delay)
        return delay

    async def execute(self, func: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        """
        Executes the coroutine `func` with token bucket pre-flight and
        exponential backoff retry upon encountering AzureRateLimitException.
        """
        # 1. Pre-flight token bucket acquisition
        await self.rate_limiter.acquire(1)

        attempt = 0
        start_time = time.monotonic()

        while True:
            try:
                return await func(*args, **kwargs)
            except AzureRateLimitException as exc:
                self.throttled_429_count += 1
                self.total_retries += 1
                attempt += 1

                if attempt > self.max_retries:
                    logger.error(f"[ResilienceEngine] Exceeded max retries ({self.max_retries}) for call: {exc}")
                    raise

                backoff = self._calculate_backoff(attempt, exc.retry_after_seconds)
                logger.warning(
                    f"[ResilienceEngine] Azure 429 received. Attempt {attempt}/{self.max_retries}. "
                    f"Backing off for {backoff:.2f}s with jitter..."
                )
                await asyncio.sleep(backoff)
            except Exception as e:
                # Other non-429 exceptions bubble up immediately
                raise e
