"""Resilient LLM provider routing with retries and circuit breaking."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential


class RateLimitError(RuntimeError):
    """Synthetic provider rate-limit error."""


class ProviderServerError(RuntimeError):
    """Synthetic provider 5xx-style error."""


class LLMProvider(Protocol):
    """Minimal asynchronous provider contract."""

    name: str

    async def generate(self, prompt: str) -> str:
        """Generate a response or raise a provider error."""


@dataclass
class CallableProvider:
    """Provider wrapper useful for local simulations and tests."""

    name: str
    handler: Callable[[str], Awaitable[str]]

    async def generate(self, prompt: str) -> str:
        return await self.handler(prompt)


@dataclass
class LLMRouterMetrics:
    primary_success_count: int = 0
    fallback_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    request_count: int = 0

    @property
    def average_latency_ms(self) -> float:
        if self.request_count == 0:
            return 0.0
        return round(self.total_latency_ms / self.request_count, 3)


class LLMRouter:
    """Route provider failures through retry, fallback, and circuit-breaker policy."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        *,
        max_attempts: int = 2,
        circuit_failure_threshold: int = 3,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._max_attempts = max_attempts
        self._circuit_failure_threshold = circuit_failure_threshold
        self._consecutive_primary_failures = 0
        self._circuit_open = False
        self.metrics = LLMRouterMetrics()

    @property
    def circuit_open(self) -> bool:
        return self._circuit_open

    async def generate(self, prompt: str) -> str:
        started = perf_counter()
        try:
            if not self._circuit_open:
                try:
                    result = await self._call_primary(prompt)
                    self._consecutive_primary_failures = 0
                    self.metrics.primary_success_count += 1
                    return result
                except (RateLimitError, ProviderServerError):
                    self._consecutive_primary_failures += 1
                    if self._consecutive_primary_failures >= self._circuit_failure_threshold:
                        self._circuit_open = True

            result = await self._fallback.generate(prompt)
            self.metrics.fallback_count += 1
            return result
        except Exception:
            self.metrics.failure_count += 1
            raise
        finally:
            self.metrics.request_count += 1
            self.metrics.total_latency_ms += (perf_counter() - started) * 1000

    async def _call_primary(self, prompt: str) -> str:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.001, min=0.001, max=0.01),
            retry=retry_if_exception_type((RateLimitError, ProviderServerError)),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._primary.generate(prompt)
        raise RuntimeError("Primary provider retry loop terminated unexpectedly.")
