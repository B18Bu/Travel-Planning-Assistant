from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

Runner = Callable[[str, list[str], float], Awaitable[str | tuple[int, str, str]]]


@dataclass(frozen=True)
class FlyAIPoiTicket:
    """search-poi 返回的景点门票参考；价格与票种为官方参考，非实时保证。"""

    poi_name: str
    address: str | None = None
    category: str | None = None
    ticket_name: str | None = None
    price_text: str | None = None
    price_date: str | None = None
    description: str | None = None


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
        return await self._search_text(query)

    async def search_food(
        self,
        city_name: str,
        nearby_attraction: str | None,
        preferences: tuple[str, ...],
    ) -> str:
        """查询餐饮参考文本，不承诺门店、价格、营业时间或可订状态。"""

        if not isinstance(city_name, str) or not city_name.strip():
            raise ValueError("餐饮查询城市无效")
        if nearby_attraction is not None and (
            not isinstance(nearby_attraction, str) or not nearby_attraction.strip()
        ):
            raise ValueError("餐饮查询附近地点无效")
        if not isinstance(preferences, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in preferences
        ):
            raise ValueError("餐饮偏好无效")

        location = (
            f"{city_name.strip()}的{nearby_attraction.strip()}附近"
            if nearby_attraction
            else city_name.strip()
        )
        preference_text = "；".join(preferences) if preferences else "无明确偏好"
        query = (
            f"查询{location}的餐饮参考，偏好：{preference_text}。"
            "仅返回适合上述偏好的餐饮类型、点餐建议与核验要点。"
            "只读查询，不预订、不下单、不支付；不承诺具体门店、价格、营业时间或库存。"
        )
        return await self._search_text(query)

    async def _search_text(self, query: str) -> str:
        """执行 ai-search 并只读取其 data 文本字段。"""

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

    async def search_poi(self, city_name: str, keyword: str) -> list[FlyAIPoiTicket]:
        """按城市与景点关键词查询结构化景点门票参考（search-poi）。"""

        args = ["search-poi", "--city-name", city_name, "--keyword", keyword]

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
        items = data.get("itemList") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise FlyAIUpstreamError("INVALID_RESPONSE")

        results: list[FlyAIPoiTicket] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
                continue
            ticket_info = item.get("ticketInfo") if isinstance(item.get("ticketInfo"), dict) else {}
            results.append(
                FlyAIPoiTicket(
                    poi_name=item["name"].strip(),
                    address=item.get("address") if isinstance(item.get("address"), str) else None,
                    category=item.get("category") if isinstance(item.get("category"), str) else None,
                    ticket_name=(
                        ticket_info.get("ticketName")
                        if isinstance(ticket_info.get("ticketName"), str)
                        else None
                    ),
                    price_text=(
                        ticket_info.get("price")
                        if isinstance(ticket_info.get("price"), str)
                        else None
                    ),
                    price_date=(
                        ticket_info.get("priceDate")
                        if isinstance(ticket_info.get("priceDate"), str)
                        else None
                    ),
                    description=(
                        item.get("description")
                        if isinstance(item.get("description"), str)
                        else None
                    ),
                )
            )
        return results


def _subprocess_runner(api_key: str) -> Runner:
    async def run(command: str, args: list[str], timeout: float) -> tuple[int, str, str]:
        environment = os.environ.copy()
        environment["FLYAI_API_KEY"] = api_key
        process = await _spawn_command(command, args, environment)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise
        return process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    return run


def _resolve_command(command: str) -> str | list[str]:
    """返回可直接 create_subprocess_exec 的命令形式。

    Windows 上 npm 全局 CLI 是 .CMD/.BAT 批处理 shim，CreateProcess 无法直接
    执行，需要 cmd.exe /c 包装；非 Windows 直接返回原命令。
    """

    if sys.platform != "win32":
        return command
    path = shutil.which(command)
    if path and (path.lower().endswith(".cmd") or path.lower().endswith(".bat")):
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/c", path]
    return command


async def _spawn_command(command: str, args: list[str], environment) -> asyncio.subprocess.Process:
    resolved = _resolve_command(command)
    if isinstance(resolved, list):
        return await asyncio.create_subprocess_exec(
            *resolved,
            *args,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    return await asyncio.create_subprocess_exec(
        resolved,
        *args,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def _stdout_from_runner_result(raw: str | tuple[int, str, str]) -> str | None:
    """提取 CLI stdout；只要非空文本即返回，退出码不作为唯一成功依据。

    实测 Windows 上官方 flyai CLI 会输出有效 JSON 到 stdout，但 libuv 断言使
    进程退出码为 127。若严格按退出码判断会拒绝有效结果，因此这里只要求
    stdout 非空；JSON 结构与语义由调用方在解析时校验。
    """

    if isinstance(raw, str):
        return raw
    if isinstance(raw, tuple) and len(raw) == 3:
        stdout = raw[1]
        return stdout if isinstance(stdout, str) and stdout.strip() else None
    return None
