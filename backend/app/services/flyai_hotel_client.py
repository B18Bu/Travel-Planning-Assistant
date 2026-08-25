from __future__ import annotations

import asyncio
import json
import os
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
                "--limit", str(request.limit),
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
                        latitude=item.get("latitude", item.get("lat")),
                        longitude=item.get("longitude", item.get("lon")),
                        main_pic=_https_url(item.get("mainPic")),
                        detail_url=_https_url(item.get("detailUrl")),
                        price=item.get("price"),
                        score=item.get("score"),
                        star=item.get("star"),
                    )
                )
            except (ValidationError, TypeError, ValueError):
                raise FlyAIHotelError("INVALID_RESPONSE") from None
        return projected


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


def _https_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return None
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
