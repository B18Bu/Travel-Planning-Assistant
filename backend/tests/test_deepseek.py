import json

import httpx
import pytest
import respx

from app.services.deepseek import DeepSeekClient
from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable


BASE = "https://api.deepseek.com"
LONG_ANSWER = "成都美食攻略。" * 10


def client(**kwargs):
    options = {
        "api_key": "deepseek-key",
        "base_url": BASE,
        "breaker": CircuitBreaker(failure_threshold=3, open_seconds=60),
        "max_attempts": 3,
        "max_tokens": 2000,
        "timeout": httpx.Timeout(2.0),
    }
    options.update(kwargs)
    return DeepSeekClient(**options)


def completion_response(content):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


@respx.mock
@pytest.mark.asyncio
async def test_returns_content_and_sends_expected_request_body():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=completion_response(LONG_ANSWER))

    result = await client().chat_completion("system prompt", "user prompt")

    assert route.call_count == 1
    assert result == LONG_ANSWER
    payload = json.loads(route.calls[0].request.content)
    assert payload["model"] == "deepseek-chat"
    assert payload["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 2000
    assert route.calls[0].request.headers["authorization"] == "Bearer deepseek-key"


@respx.mock
@pytest.mark.asyncio
async def test_retries_transient_status_then_succeeds():
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limit"}),
            completion_response(LONG_ANSWER),
        ]
    )

    result = await client().chat_completion("s", "u")

    assert route.call_count == 2
    assert result == LONG_ANSWER


@respx.mock
@pytest.mark.asyncio
async def test_exhausted_retries_raise_and_record_breaker_failure():
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(500, json={}),
            httpx.Response(500, json={}),
            httpx.Response(500, json={}),
        ]
    )
    breaker = CircuitBreaker(failure_threshold=3, open_seconds=60)

    with pytest.raises(ExternalServiceUnavailable):
        await client(breaker=breaker).chat_completion("s", "u")

    assert route.call_count == 3
    assert breaker.failure_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_raises_when_choices_missing():
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, json={"unexpected": True}))

    with pytest.raises(ExternalServiceUnavailable):
        await client().chat_completion("s", "u")


@respx.mock
@pytest.mark.asyncio
async def test_raises_when_content_empty_or_too_short():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=completion_response("   "))

    with pytest.raises(ExternalServiceUnavailable):
        await client().chat_completion("s", "u")
    assert route.call_count == 1

    respx.post(f"{BASE}/chat/completions").mock(return_value=completion_response("太短"))
    with pytest.raises(ExternalServiceUnavailable):
        await client().chat_completion("s", "u")


@respx.mock
@pytest.mark.asyncio
async def test_accepts_short_response_when_min_response_length_lowered():
    short = "0.8|切题"
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=completion_response(short))

    result = await client(min_response_length=1).chat_completion("s", "u")

    assert route.call_count == 1
    assert result == short


@respx.mock
@pytest.mark.asyncio
async def test_missing_key_raises_without_http_call():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=completion_response(LONG_ANSWER))

    with pytest.raises(ExternalServiceUnavailable) as error:
        await client(api_key="").chat_completion("s", "u")

    assert "密钥未配置" in str(error.value)
    assert route.call_count == 0


def test_rejects_noncanonical_base_url():
    for url in ("http://api.deepseek.com", "https://api.deepseek.com/", "https://evil.example"):
        with pytest.raises(ExternalServiceUnavailable):
            client(base_url=url)


@pytest.mark.parametrize("value", [0, 255, 8193, True, False, 1.5, "not-a-number"])
def test_rejects_invalid_max_tokens(value):
    with pytest.raises(ValueError):
        client(max_tokens=value)


@pytest.mark.parametrize("value", [0, 101, True, False, 1.5, "not-a-number"])
def test_rejects_invalid_min_response_length(value):
    with pytest.raises(ValueError):
        client(min_response_length=value)
