import re
from typing import Final


class FliggyHotelNotConfigured(RuntimeError):
    """飞猪酒店查询功能未启用或尚未完成配置。"""

    def __init__(self, *_: object) -> None:
        super().__init__("飞猪酒店查询服务尚未配置")


_FLIGGY_ERROR_CODES: Final = frozenset(
    {
        "UPSTREAM_ERROR",
        "AUTH_ERROR",
        "PERMISSION_ERROR",
        "CHANNEL_ERROR",
        "TIMEOUT",
        "NETWORK_ERROR",
        "HTTP_ERROR",
        "INVALID_RESPONSE",
    }
)


def _validate_short_code(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9_-]{1,32}", value, flags=re.ASCII):
        raise ValueError(f"{field_name} 必须是 ASCII 大写短码")
    return value


class FliggyHotelUpstreamError(RuntimeError):
    """飞猪酒店上游调用失败的受控错误。"""

    def __init__(self, code: str, provider_code: str | None, retryable: bool) -> None:
        if code not in _FLIGGY_ERROR_CODES:
            raise ValueError("code 不是受控飞猪错误码")
        self.code = code
        if not isinstance(retryable, bool):
            raise TypeError("retryable 必须是 bool")
        self.provider_code = _validate_short_code(provider_code, "provider_code")
        self.retryable = retryable
        super().__init__(code)
