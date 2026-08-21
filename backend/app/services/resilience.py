import asyncio
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, TypeVar

import httpx


class ExternalServiceUnavailable(Exception):
    """外部服务不可用的受控错误。"""

    def __init__(self, message: str = "外部服务暂不可用") -> None:
        super().__init__(message)


class CircuitBreaker:
    """按连续失败次数控制外部服务熔断。"""

    def __init__(self, failure_threshold: int, open_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self.failure_count = 0
        self._opened_at: datetime | None = None

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self._opened_at = datetime.now(timezone.utc)

    def ensure_available(self) -> None:
        if self._opened_at is None:
            return

        opened_at = self._opened_at
        if datetime.now(timezone.utc) - opened_at >= timedelta(
            seconds=self.open_seconds
        ):
            self.failure_count = 0
            self._opened_at = None
            return
        raise ExternalServiceUnavailable("外部服务熔断中")

    def record_success(self) -> None:
        self.failure_count = 0
        self._opened_at = None


ResponseT = TypeVar("ResponseT")
SendCallable = Callable[[], Awaitable[ResponseT]]


async def request_with_retry(
    send: SendCallable[ResponseT], max_attempts: int
) -> ResponseT:
    """执行请求，仅对受控瞬时错误重试。"""

    for attempt in range(max_attempts):
        try:
            response = await send()
        except (httpx.TimeoutException, httpx.TransportError) as error:
            if attempt == max_attempts - 1:
                raise ExternalServiceUnavailable() from None
            await asyncio.sleep(0.05 * (2**attempt))
            continue

        status_code = getattr(response, "status_code", None)
        if status_code == 429 or status_code is not None and 500 <= status_code < 600:
            if attempt == max_attempts - 1:
                raise ExternalServiceUnavailable()
            await asyncio.sleep(0.05 * (2**attempt))
            continue
        return response

    raise ExternalServiceUnavailable()
