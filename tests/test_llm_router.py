"""LLM provider retry, fallback, and circuit breaker tests."""

import pytest

from src.llm_router import CallableProvider, LLMRouter, ProviderServerError, RateLimitError


@pytest.mark.asyncio
async def test_router_falls_back_after_retryable_primary_errors() -> None:
    calls = 0

    async def failing_primary(prompt: str) -> str:
        nonlocal calls
        calls += 1
        raise RateLimitError(f"synthetic rate limit for {prompt}")

    async def healthy_fallback(prompt: str) -> str:
        return f"fallback:{prompt}"

    router = LLMRouter(
        CallableProvider("primary", failing_primary),
        CallableProvider("fallback", healthy_fallback),
        max_attempts=2,
    )

    result = await router.generate("diagnose")

    assert result == "fallback:diagnose"
    assert calls == 2
    assert router.metrics.fallback_count == 1
    assert router.metrics.failure_count == 0


@pytest.mark.asyncio
async def test_router_opens_circuit_after_repeated_primary_failures() -> None:
    primary_calls = 0

    async def failing_primary(prompt: str) -> str:
        nonlocal primary_calls
        primary_calls += 1
        raise ProviderServerError(prompt)

    async def fallback(prompt: str) -> str:
        return prompt

    router = LLMRouter(
        CallableProvider("primary", failing_primary),
        CallableProvider("fallback", fallback),
        max_attempts=1,
        circuit_failure_threshold=2,
    )

    await router.generate("one")
    await router.generate("two")
    await router.generate("three")

    assert router.circuit_open is True
    assert primary_calls == 2
    assert router.metrics.fallback_count == 3
    assert router.metrics.average_latency_ms >= 0.0
