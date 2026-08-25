from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from datetime import date

Runner = Callable[[str, list[str], float], Awaitable[str | tuple[int, str, str]]]


class FlyAIUpstreamError(RuntimeError):
    """FlyAI CLI 调用失败的受控错误，不携带上游自由文本。"""

    _codes = frozenset({"CLI_ERROR", "TIMEOUT", "INVALID_RESPONSE"})

    def __init__(self, code: str) -> None:
        if code not in self._codes:
            raise ValueError("code 不是受控 FlyAI 错误码")
        self.code = code
        super().__init__(code)


class FlyAIClient:
    """通过官方 flyai CLI 的 ai-search 命令进行门票只读文本检索。

    认证由 CLI 通过环境变量 FLYAI_API_KEY 管理；后端不猜测 MCP endpoint 和工具 schema。
    ai-search 的响应 data 字段为文本字符串，直接作为门票摘要返回，不解析价格、库存或 SKU。
    """

    _summary_max_length = 8000
    _prompt_template = (
        "查询景点「{keyword}」在 {entry_date} 的门票信息，"
        "仅返回景点门票相关文本。只读查询，不预订、不下单、不支付。"
    )

    def __init__(
        self,
        api_key: str,
        *,
        command: str = "flyai",
        timeout_seconds: float = 30.0,
        runner: Runner | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("FlyAI API Key 未配置")
        if not isinstance(command, str) or not command:
            raise ValueError("FlyAI CLI 命令无效")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("FlyAI 超时时间无效")
        self._api_key = api_key
        self._command = command
        self._timeout_seconds = float(timeout_seconds)
        self._runner = runner or _subprocess_runner(api_key)

    async def search(self, scenic_keyword: str, entry_date: date) -> str:
        """查询指定景点和日期的门票文本摘要；不含游客人数或身份字段。"""

        query = self._prompt_template.format(
            keyword=scenic_keyword,
            entry_date=entry_date.isoformat(),
        )
        args = ["ai-search", "--query", query]

        try:
            raw = await self._runner(self._command, args, self._timeout_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            raise FlyAIUpstreamError("TIMEOUT") from None
        except Exception:
            raise FlyAIUpstreamError("CLI_ERROR") from None

        stdout = _stdout_from_runner_result(raw)
        if stdout is None:
            raise FlyAIUpstreamError("CLI_ERROR")
        try:
            body = json.loads(stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise FlyAIUpstreamError("INVALID_RESPONSE") from None
        if not isinstance(body, dict):
            raise FlyAIUpstreamError("INVALID_RESPONSE")
        data = body.get("data")
        if not isinstance(data, str):
            raise FlyAIUpstreamError("INVALID_RESPONSE")
        return data[: self._summary_max_length]


def _subprocess_runner(api_key: str) -> Runner:
    async def run(command: str, args: list[str], timeout: float) -> tuple[int, str, str]:
        environment = os.environ.copy()
        environment["FLYAI_API_KEY"] = api_key
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise
        return process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    return run


def _stdout_from_runner_result(raw: str | tuple[int, str, str]) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, tuple) and len(raw) == 3:
        return raw[1] if raw[0] == 0 and isinstance(raw[1], str) else None
    return None
