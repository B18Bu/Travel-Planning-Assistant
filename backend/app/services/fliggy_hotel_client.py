from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from app.errors import FliggyHotelUpstreamError
from app.services.fliggy_signing import build_top_params, sign_top_request
from app.services.resilience import ExternalServiceUnavailable, request_with_retry


@dataclass(frozen=True)
class FliggyRawHotel:
    """飞猪低价接口的最小不可变酒店投影；价格单位为分。"""

    shid: str
    name: str
    low_price_cents: int
    supplier_name: str


@dataclass(frozen=True)
class FliggyRawSearchResult:
    """飞猪低价接口的最小不可变查询投影。"""

    hotels: tuple[FliggyRawHotel, ...]
    total: int


class FliggyHotelClient:
    """API 56180 客户端，仅访问固定飞猪 TOP 网关且不缓存结果。"""

    _canonical_url = "https://eco.taobao.com/router/rest"
    _method = "alitrip.btrip.hotel.distribution.search.low.price"

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        sub_channel: str,
        *,
        max_attempts: int = 3,
        timeout: httpx.Timeout | float = 10.0,
        base_url: str = _canonical_url,
    ) -> None:
        if base_url != self._canonical_url:
            raise ValueError("飞猪酒店网关必须使用固定官方 HTTPS 地址")
        if not isinstance(app_key, str) or not app_key.strip():
            raise ValueError("飞猪 AppKey 未配置")
        if not isinstance(app_secret, str) or not app_secret:
            raise ValueError("飞猪 AppSecret 未配置")
        if not isinstance(sub_channel, str) or not sub_channel.strip():
            raise ValueError("飞猪 sub_channel 未配置")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts 必须在 1 到 3 之间")
        self._app_key = app_key
        self._app_secret = app_secret
        self._sub_channel = sub_channel
        self._max_attempts = max_attempts
        self._timeout = timeout

    async def search_low_price(
        self,
        city_name: str,
        check_in: date | str,
        check_out: date | str,
        page_no: int,
        page_size: int,
    ) -> FliggyRawSearchResult:
        payload = self._business_payload(city_name, check_in, check_out, page_no, page_size)
        params = build_top_params(
            app_key=self._app_key,
            timestamp=datetime.now(),
            business_payload=payload,
        )
        params["sign"] = sign_top_request(params, self._app_secret)
        last_status: int | None = None
        last_failure: str | None = None

        async def send() -> httpx.Response:
            nonlocal last_status, last_failure
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(self._canonical_url, data=params)
                last_status = response.status_code
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    last_failure = "http"
                return response
            except httpx.TimeoutException:
                last_failure = "timeout"
                raise
            except httpx.TransportError:
                last_failure = "network"
                raise

        try:
            response = await request_with_retry(send, max_attempts=self._max_attempts)
        except ExternalServiceUnavailable:
            if last_failure == "timeout":
                raise FliggyHotelUpstreamError("TIMEOUT", None, True) from None
            if last_failure == "network":
                raise FliggyHotelUpstreamError("NETWORK_ERROR", None, True) from None
            raise FliggyHotelUpstreamError("HTTP_ERROR", _status_code(last_status), True) from None

        if not 200 <= response.status_code < 300:
            raise FliggyHotelUpstreamError(
                _http_error_code(response.status_code), _status_code(response.status_code), False
            )
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            raise FliggyHotelUpstreamError("INVALID_RESPONSE", None, False) from None
        return self._parse_response(body)

    def _business_payload(
        self,
        city_name: str,
        check_in: date | str,
        check_out: date | str,
        page_no: int,
        page_size: int,
    ) -> dict[str, object]:
        if not isinstance(city_name, str) or not city_name.strip():
            raise ValueError("城市名无效")
        in_date = _date_text(check_in)
        out_date = _date_text(check_out)
        if not isinstance(page_no, int) or isinstance(page_no, bool) or page_no < 1:
            raise ValueError("页码无效")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 50:
            raise ValueError("分页大小无效")
        return {
            "city_name": city_name.strip(),
            "check_in": in_date,
            "check_out": out_date,
            "page_no": page_no,
            "page_size": page_size,
            "sub_channel": self._sub_channel,
            "order": 2,
            "dir": 1,
        }

    @classmethod
    def _parse_response(cls, body: object) -> FliggyRawSearchResult:
        if not isinstance(body, dict):
            return _invalid_response()
        error = body.get("error_response")
        if isinstance(error, dict):
            return _provider_error(error)
        envelope = body.get(f"{cls._method.replace('.', '_')}_response")
        if not isinstance(envelope, dict):
            return _invalid_response()
        error = envelope.get("error_response")
        if isinstance(error, dict):
            return _provider_error(error)
        result = envelope.get("result")
        module = result.get("module") if isinstance(result, dict) else None
        hotels = module.get("hotels") if isinstance(module, dict) else None
        total = module.get("total") if isinstance(module, dict) else None
        if not isinstance(hotels, list) or not _non_negative_int(total):
            return _invalid_response()
        projected: list[FliggyRawHotel] = []
        for item in hotels:
            if not isinstance(item, dict):
                return _invalid_response()
            shid, name, price, supplier = (
                item.get("shid"), item.get("name"), item.get("low_price"), item.get("supplier_name")
            )
            if isinstance(shid, bool) or not isinstance(shid, (int, str)) or (isinstance(shid, str) and not shid.strip()):
                return _invalid_response()
            if not _non_empty_text(name) or not _non_negative_int(price) or not _non_empty_text(supplier):
                return _invalid_response()
            projected.append(FliggyRawHotel(str(shid), name, price, supplier))
        return FliggyRawSearchResult(tuple(projected), total)


def _date_text(value: date | str) -> str:
    if isinstance(value, datetime):
        raise ValueError("日期不得包含时间")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("日期必须为 YYYY-MM-DD") from error
        if value != parsed.isoformat():
            raise ValueError("日期必须为 YYYY-MM-DD")
        return value
    raise ValueError("日期无效")


def _provider_error(error: dict[str, Any]) -> FliggyRawSearchResult:
    raw_code = error.get("code")
    code_text = str(raw_code).upper() if raw_code is not None else "UPSTREAM"
    if "401" in code_text or "AUTH" in code_text:
        code = "AUTH_ERROR"
    elif "403" in code_text or "PERMISSION" in code_text:
        code = "PERMISSION_ERROR"
    elif "CHANNEL" in code_text or "SUB_CHANNEL" in code_text:
        code = "CHANNEL_ERROR"
    else:
        code = "UPSTREAM_ERROR"
    provider_code = code_text if 1 <= len(code_text) <= 32 and all(c.isalnum() or c in "_-" for c in code_text) else None
    raise FliggyHotelUpstreamError(code, provider_code, False)


def _invalid_response() -> FliggyRawSearchResult:
    raise FliggyHotelUpstreamError("INVALID_RESPONSE", None, False)


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _status_code(status: int | None) -> str | None:
    return str(status) if status is not None else None


def _http_error_code(status: int) -> str:
    if status in (401,):
        return "AUTH_ERROR"
    if status in (403,):
        return "PERMISSION_ERROR"
    return "HTTP_ERROR"
