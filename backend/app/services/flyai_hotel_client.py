from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from app.models.flyai_hotel import FlyAIHotel, FlyAIHotelSearchRequest


class FlyAIHotelError(RuntimeError):
    """FlyAI CLI 调用失败的受控错误，不携带上游自由文本。"""

    _codes = frozenset({"CLI_ERROR", "TIMEOUT", "INVALID_RESPONSE"})

    def __init__(self, code: str) -> None:
        if code not in self._codes:
            raise ValueError("code 不是受控 FlyAI 错误码")
        self.code = code
        super().__init__(code)


Runner = Callable[[str, list[str], float], Awaitable[str | tuple[int, str, str]]]


class FlyAIHotelClient:
    """通过官方 flyai CLI 查询酒店，并执行严格白名单投影。"""

    def __init__(
        self,
        api_key: str,
        *,
        command: str = "flyai",
        timeout_seconds: float = 30.0,
        runner: Runner | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("FlyAI API Key 未配置")
        if not isinstance(command, str) or not command:
            raise ValueError("FlyAI CLI 命令无效")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("FlyAI 超时时间无效")
        self._api_key = api_key
        self._command = command
        self._timeout_seconds = float(timeout_seconds)
        self._runner = runner or _subprocess_runner(api_key)

    async def search_hotels(self, request: FlyAIHotelSearchRequest) -> list[FlyAIHotel]:
        args = [
            "search-hotel",
            "--dest-name", request.city_name,
        ]
        if request.poi_name is not None:
            args.extend(("--poi-name", request.poi_name))
        args.extend(
            (
                "--check-in-date", request.check_in.isoformat(),
                "--check-out-date", request.check_out.isoformat(),
                "--sort", request.sort,
            )
        )
        if request.max_price is not None:
            args.extend(("--max-price", _decimal_text(request.max_price)))

        try:
            raw = await self._runner(self._command, args, self._timeout_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            raise FlyAIHotelError("TIMEOUT") from None
        except Exception:
            raise FlyAIHotelError("CLI_ERROR") from None

        stdout = _stdout_from_runner_result(raw)
        if stdout is None:
            raise FlyAIHotelError("CLI_ERROR")
        try:
            body = json.loads(stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise FlyAIHotelError("INVALID_RESPONSE") from None
        if not isinstance(body, dict):
            raise FlyAIHotelError("INVALID_RESPONSE")
        data = body.get("data")
        items = data.get("itemList") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise FlyAIHotelError("INVALID_RESPONSE")

        projected: list[FlyAIHotel] = []
        for item in items:
            if not isinstance(item, dict):
                raise FlyAIHotelError("INVALID_RESPONSE")
            try:
                projected.append(
                    FlyAIHotel(
                        hotel_id=item.get("shId"),
                        name=item.get("name"),
                        address=item.get("address"),
                        latitude=_as_decimal(item.get("latitude", item.get("lat"))),
                        longitude=_as_decimal(item.get("longitude", item.get("lon"))),
                        main_pic=_https_url(item.get("mainPic")),
                        detail_url=_https_url(item.get("detailUrl")),
                        price=_as_decimal(item.get("price")),
                        score=_as_decimal(item.get("score")),
                        star=_as_int(item.get("star")),
                    )
                )
            except (ValidationError, TypeError, ValueError):
                raise FlyAIHotelError("INVALID_RESPONSE") from None
        return projected


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


def _https_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return None
    return value


def _as_decimal(value: object) -> Decimal | None:
    """从整数、小数或货币字符串（如“¥30”）提取 Decimal；无法解析返回 None。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace("¥", "").replace("￥", "").replace(",", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _as_int(value: object) -> int | None:
    """从数字或数字字符串提取 int；非数字星级等文本返回 None，不伪造。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
