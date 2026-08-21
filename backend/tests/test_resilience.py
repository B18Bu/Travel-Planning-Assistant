from datetime import datetime, timezone

import httpx
import pytest

from app.services.cache import MemoryCache
from app.services.resilience import (
    CircuitBreaker,
    ExternalServiceUnavailable,
    request_with_retry,
)


def test_memory_cache_returns_cached_value():
    cache = MemoryCache()

    cache.set("city", {"name": "杭州"}, ttl_seconds=60)

    assert cache.get("city") == {"name": "杭州"}


def test_memory_cache_deletes_expired_value():
    cache = MemoryCache()
    cache.set("city", "杭州", ttl_seconds=0)

    assert cache.get("city") is None
    assert "city" not in cache._entries


def test_memory_cache_stores_utc_expiration_time():
    cache = MemoryCache()

    cache.set("city", "杭州", ttl_seconds=60)

    expires_at = cache._entries["city"][1]
    assert expires_at.tzinfo == timezone.utc
    assert expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_request_with_retry_succeeds_on_third_attempt_after_429(monkeypatch):
    responses = [
        httpx.Response(429),
        httpx.Response(503),
        httpx.Response(200, json={"ok": True}),
    ]
    sleeps = []

    async def send():
        return responses.pop(0)

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.services.resilience.asyncio.sleep", fake_sleep)

    response = await request_with_retry(send, max_attempts=3)

    assert response.status_code == 200
    assert sleeps == [0.05, 0.1]


@pytest.mark.asyncio
async def test_request_with_retry_retries_transport_error_then_succeeds(monkeypatch):
    attempts = 0
    sleeps = []

    async def send():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.TransportError("private transport detail")
        return httpx.Response(200)

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.services.resilience.asyncio.sleep", fake_sleep)

    response = await request_with_retry(send, max_attempts=2)

    assert response.status_code == 200
    assert attempts == 2
    assert sleeps == [0.05]


@pytest.mark.asyncio
async def test_request_with_retry_returns_400_without_retry():
    attempts = 0

    async def send():
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text="private response body")

    response = await request_with_retry(send, max_attempts=3)

    assert response.status_code == 400
    assert attempts == 1


@pytest.mark.asyncio
async def test_request_with_retry_raises_controlled_error_after_exhaustion(monkeypatch):
    async def send():
        raise httpx.TimeoutException("https://secret.example/path")

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr("app.services.resilience.asyncio.sleep", fake_sleep)

    with pytest.raises(ExternalServiceUnavailable) as exc_info:
        await request_with_retry(send, max_attempts=2)

    assert str(exc_info.value) == "外部服务暂不可用"
    assert "secret.example" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_circuit_breaker_opens_at_failure_threshold():
    breaker = CircuitBreaker(failure_threshold=2, open_seconds=60)

    breaker.record_failure()
    breaker.ensure_available()
    breaker.record_failure()

    with pytest.raises(ExternalServiceUnavailable, match="外部服务熔断中"):
        breaker.ensure_available()


def test_circuit_breaker_resets_after_open_period():
    breaker = CircuitBreaker(failure_threshold=1, open_seconds=0)

    breaker.record_failure()
    breaker.ensure_available()
    breaker.record_failure()
    assert breaker.failure_count == 1


def test_circuit_breaker_success_clears_failures_and_open_state():
    breaker = CircuitBreaker(failure_threshold=2, open_seconds=60)

    breaker.record_failure()
    breaker.record_success()
    breaker.ensure_available()
    breaker.record_failure()
    breaker.ensure_available()
