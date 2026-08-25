from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.services.fliggy_flyai_client import FlyAIClient, FlyAIUpstreamError


@pytest.mark.asyncio
async def test_search_builds_safe_cli_args_and_extracts_data_text() -> None:
    calls = []

    async def fake_run(command, args, timeout):
        calls.append((command, args, timeout))
        return '{"data":"西湖门票信息摘要。成人票与儿童票请以官方页面为准。","status":0,"message":"success"}'

    client = FlyAIClient("server-secret", runner=fake_run)
    result = await client.search("西湖", date(2026, 9, 1))

    assert calls[0][0] == "flyai"
    assert calls[0][1][0] == "ai-search"
    assert calls[0][1][1] == "--query"
    assert "西湖" in calls[0][1][2]
    assert "2026-09-01" in calls[0][1][2]
    assert all("server-secret" not in arg for arg in calls[0][1])
    assert result == "西湖门票信息摘要。成人票与儿童票请以官方页面为准。"


@pytest.mark.asyncio
async def test_search_does_not_include_visitor_count_or_identity_fields() -> None:
    calls = []

    async def fake_run(command, args, timeout):
        calls.append((command, args, timeout))
        return '{"data":"门票摘要"}'

    await FlyAIClient("server-secret", runner=fake_run).search("西湖", date(2026, 9, 1))

    query = calls[0][1][2]
    assert "visitor_count" not in query
    assert "人数" not in query
    assert "姓名" not in query
    assert "身份证" not in query
    assert "手机" not in query


@pytest.mark.asyncio
async def test_search_maps_timeout_to_controlled_error() -> None:
    async def fake_run(command, args, timeout):
        raise asyncio.TimeoutError

    with pytest.raises(FlyAIUpstreamError) as exc_info:
        await FlyAIClient("server-secret", runner=fake_run).search("西湖", date(2026, 9, 1))

    assert exc_info.value.code == "TIMEOUT"


@pytest.mark.asyncio
async def test_search_maps_nonzero_exit_to_cli_error() -> None:
    async def fake_run(command, args, timeout):
        return (1, "", "unknown command")

    with pytest.raises(FlyAIUpstreamError) as exc_info:
        await FlyAIClient("server-secret", runner=fake_run).search("西湖", date(2026, 9, 1))

    assert exc_info.value.code == "CLI_ERROR"


@pytest.mark.asyncio
async def test_search_maps_invalid_json_to_invalid_response() -> None:
    async def fake_run(command, args, timeout):
        return (0, "not-json", "")

    with pytest.raises(FlyAIUpstreamError) as exc_info:
        await FlyAIClient("server-secret", runner=fake_run).search("西湖", date(2026, 9, 1))

    assert exc_info.value.code == "INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_search_rejects_non_string_data_field() -> None:
    async def fake_run(command, args, timeout):
        return '{"data":{"itemList":[]},"status":0}'

    with pytest.raises(FlyAIUpstreamError) as exc_info:
        await FlyAIClient("server-secret", runner=fake_run).search("西湖", date(2026, 9, 1))

    assert exc_info.value.code == "INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_search_truncates_overlong_text_to_8000_chars() -> None:
    async def fake_run(command, args, timeout):
        return '{"data":"' + "门" * 12000 + '"}'

    result = await FlyAIClient("server-secret", runner=fake_run).search("西湖", date(2026, 9, 1))

    assert len(result) == 8000


@pytest.mark.asyncio
async def test_search_accepts_valid_json_even_when_exit_code_nonzero() -> None:
    # Windows 上官方 flyai CLI 可能因 libuv 断言退出码非 0，但 stdout 仍是有效 JSON。
    async def fake_run(command, args, timeout):
        return (127, '{"data":"西湖门票摘要"}', "Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)")

    result = await FlyAIClient("server-secret", runner=fake_run).search("西湖", date(2026, 9, 1))

    assert result == "西湖门票摘要"


def test_resolve_command_wraps_cmd_shim_on_windows(monkeypatch):
    from app.services import fliggy_flyai_client as module

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda command: r"C:\Users\asus\AppData\Roaming\npm\flyai.CMD",
    )

    resolved = module._resolve_command("flyai")

    assert isinstance(resolved, list)
    assert resolved[-1] == r"C:\Users\asus\AppData\Roaming\npm\flyai.CMD"
    assert "/c" in resolved


def test_resolve_command_keeps_plain_command_on_non_windows(monkeypatch):
    from app.services import fliggy_flyai_client as module

    monkeypatch.setattr(module.sys, "platform", "linux")

    assert module._resolve_command("flyai") == "flyai"
