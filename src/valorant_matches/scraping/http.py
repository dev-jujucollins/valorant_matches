# Shared HTTP fetching: retries, rate limiting, and a circuit breaker.

import asyncio
import logging
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType

import aiohttp
from bs4 import BeautifulSoup

from valorant_matches.config import (
    HEADERS,
    MAX_RETRIES,
    RATE_LIMIT_DELAY,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
)
from valorant_matches.scraping.matches import FetchError

logger = logging.getLogger("valorant_matches")

# Maximum backoff delay in seconds
MAX_BACKOFF_DELAY = 30

# Circuit breaker settings
CIRCUIT_BREAKER_THRESHOLD = 5  # Number of consecutive failures to trip
CIRCUIT_BREAKER_RESET_TIME = 60  # Seconds before attempting to reset


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and requests are blocked."""


def calculate_backoff(attempt: int) -> float:
    """Calculate exponential backoff with up to 25% jitter.

    Args:
        attempt: Zero-based retry attempt.

    Returns:
        Seconds to wait, capped at MAX_BACKOFF_DELAY.
    """
    delay = RETRY_DELAY * (2**attempt)
    jitter = delay * 0.25 * random.random()
    return min(delay + jitter, MAX_BACKOFF_DELAY)


def retry_delay(retry_after: str | None, attempt: int) -> float:
    """Honor delta-seconds and HTTP-date Retry-After values.

    Args:
        retry_after: Raw Retry-After header, if any.
        attempt: Zero-based retry attempt, used for the backoff fallback.

    Returns:
        Seconds to wait before the next attempt.
    """
    if retry_after:
        try:
            if retry_after.strip().isdigit():
                return float(retry_after)
            deadline = parsedate_to_datetime(retry_after)
            if deadline.tzinfo is not None:
                return max(0.0, (deadline - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    return calculate_backoff(attempt)


def is_retryable_status(status: int) -> bool:
    """Return True for HTTP statuses worth retrying (5xx and 429).

    Args:
        status: HTTP response status code.
    """
    return status >= 500 or status == 429


class CircuitBreaker:
    """Block requests for a while after repeated consecutive failures."""

    def __init__(
        self,
        threshold: int = CIRCUIT_BREAKER_THRESHOLD,
        reset_time: float = CIRCUIT_BREAKER_RESET_TIME,
    ) -> None:
        self.threshold = threshold
        self.reset_time = reset_time
        self.failure_count = 0
        self.opened_at: float | None = None

    def check(self) -> None:
        """Allow a request, or raise while the breaker is open.

        Raises:
            CircuitBreakerOpen: When requests are still blocked.
        """
        if self.opened_at is None:
            return
        elapsed = time.monotonic() - self.opened_at
        if elapsed < self.reset_time:
            raise CircuitBreakerOpen(
                f"Circuit breaker open. Retry in {self.reset_time - elapsed:.0f}s"
            )
        logger.info("Circuit breaker attempting reset...")
        self.record_success()

    def record_success(self) -> None:
        """Close the breaker and reset the failure count."""
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        """Count a failure, opening the breaker at the threshold."""
        self.failure_count += 1
        if self.failure_count >= self.threshold:
            self.opened_at = time.monotonic()
            logger.error(
                f"Circuit breaker tripped after {self.failure_count} consecutive "
                f"failures. Blocking requests for {self.reset_time:.0f}s"
            )


class AsyncRateLimiter:
    """Space out request starts by a minimum delay."""

    def __init__(self, delay: float = RATE_LIMIT_DELAY) -> None:
        self._delay = delay
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until the next request may start."""
        async with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self._delay:
                await asyncio.sleep(self._delay - elapsed)
            self._last_request = time.monotonic()


class HttpFetcher:
    """Fetch and parse pages over one session with the shared request policy.

    Use as an async context manager. Failures are recorded in ``errors`` keyed
    by URL so callers can report why a page is missing.
    """

    def __init__(self, rate_limit_delay: float = RATE_LIMIT_DELAY) -> None:
        self.breaker = CircuitBreaker()
        self.rate_limiter = AsyncRateLimiter(rate_limit_delay)
        self.errors: dict[str, FetchError] = {}
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "HttpFetcher":
        """Open the HTTP session."""
        self._session = aiohttp.ClientSession(
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            connector=aiohttp.TCPConnector(limit=20, limit_per_host=10),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()

    def _fail(self, url: str, error_type: str, message: str) -> None:
        """Record a final failure for a URL."""
        self.errors[url] = FetchError(url, error_type, message)

    async def fetch(self, url: str, retries: int = MAX_RETRIES) -> BeautifulSoup | None:
        """Fetch and parse a page, retrying transient failures.

        Args:
            url: Absolute URL to fetch.
            retries: Total attempts, including the first.

        Returns:
            The parsed page, or None after recording the failure in ``errors``.

        Raises:
            RuntimeError: When used outside ``async with``.
        """
        if not self._session:
            raise RuntimeError("Fetcher not initialized. Use async with context.")

        self.errors.pop(url, None)
        for attempt in range(retries):
            last_attempt = attempt == retries - 1
            try:
                self.breaker.check()
                await self.rate_limiter.acquire()
                # Recheck: another request may have tripped it while queued.
                self.breaker.check()
                async with self._session.get(url) as response:
                    if response.status >= 400:
                        if is_retryable_status(response.status) and not last_attempt:
                            logger.warning(
                                f"Retryable status {response.status} "
                                f"(attempt {attempt + 1})"
                            )
                            await asyncio.sleep(
                                retry_delay(
                                    response.headers.get("Retry-After"), attempt
                                )
                            )
                            continue
                        logger.warning(f"HTTP error {response.status} for {url}")
                        self.breaker.record_failure()
                        self._fail(url, "http", f"HTTP {response.status}")
                        return None

                    text = await response.text()
                    self.breaker.record_success()
                    # Parse in a worker thread so large pages don't block the loop.
                    return await asyncio.to_thread(BeautifulSoup, text, "lxml")

            except CircuitBreakerOpen as e:
                logger.warning(str(e))
                self._fail(url, "circuit", str(e))
                return None

            except TimeoutError:
                if not last_attempt:
                    logger.warning(f"Timeout (attempt {attempt + 1}/{retries})")
                    await asyncio.sleep(calculate_backoff(attempt))
                    continue
                logger.error(f"Timeout after {retries} attempts for {url}")
                self.breaker.record_failure()
                self._fail(url, "timeout", f"Timed out after {retries} attempts")
                return None

            except aiohttp.ClientError as e:
                if not last_attempt:
                    logger.warning(f"Client error (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(calculate_backoff(attempt))
                    continue
                logger.error(f"Failed after {retries} attempts: {e}")
                self.breaker.record_failure()
                self._fail(url, "network", str(e))
                return None

        return None


def fetch_page(url: str) -> BeautifulSoup | None:
    """Fetch one page synchronously with the shared request policy.

    Must not be called from inside a running event loop.

    Args:
        url: Absolute URL to fetch.

    Returns:
        The parsed page, or None when the request failed.
    """

    async def _fetch() -> BeautifulSoup | None:
        async with HttpFetcher(rate_limit_delay=0) as fetcher:
            return await fetcher.fetch(url)

    return asyncio.run(_fetch())
