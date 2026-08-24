from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.resilience import ExternalServiceUnavailable, request_with_retry


_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DNS_HOST_PATTERN = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class MinerUClient:
    """MinerU PDF 解析端点的受控客户端，不负责轮询。"""

    _base_url = "https://mineru.net"

    def __init__(
        self,
        api_key: str,
        base_url: str = _base_url,
        allowed_download_hosts: set[str] | None = None,
        allowed_result_hosts: set[str] | None = None,
        max_attempts: int = 3,
        timeout: httpx.Timeout | float = 10.0,
    ) -> None:
        if base_url != self._base_url:
            raise ExternalServiceUnavailable("MinerU 服务地址不受支持")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts 必须在 1 到 3 之间")
        self.api_key = api_key
        self.allowed_download_hosts = self._validate_allowed_hosts(allowed_download_hosts)
        self.allowed_result_hosts = self._validate_allowed_hosts(allowed_result_hosts)
        self.max_attempts = max_attempts
        self.timeout = timeout

    def require_configured(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ExternalServiceUnavailable("MinerU API 密钥未配置")

    async def submit_task(self, file_url: str) -> str:
        self.require_configured()
        self._validate_https_url(file_url, self.allowed_download_hosts, "MinerU 请求文件无效")
        payload = await self._request("POST", "/api/v4/file-urls/batch", {"files": [{"url": file_url}]})
        task_id = self._data_value(payload, "batch_id")
        self._validate_task_id(task_id)
        return task_id

    async def get_task_status(self, task_id: str) -> str:
        self.require_configured()
        self._validate_task_id(task_id)
        payload = await self._request("GET", f"/api/v4/extract/task/{task_id}")
        status = self._data_value(payload, "state")
        if not isinstance(status, str) or not status.strip():
            raise ExternalServiceUnavailable("MinerU 未返回有效数据")
        return status

    async def get_completed_result(self, task_id: str) -> dict[str, str]:
        self.require_configured()
        self._validate_task_id(task_id)
        payload = await self._request("GET", f"/api/v4/extract/task/{task_id}/result")
        download_url = self._data_value(payload, "full_zip_url")
        self._validate_https_url(download_url, self.allowed_result_hosts, "MinerU 结果无效")
        return {"full_zip_url": download_url}

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method == "POST":
                    response = await client.request(method, f"{self._base_url}{path}", headers={"Authorization": f"Bearer {self.api_key}"}, json=json)
                else:
                    response = await request_with_retry(
                        lambda: client.request(method, f"{self._base_url}{path}", headers={"Authorization": f"Bearer {self.api_key}"}, json=json),
                        max_attempts=self.max_attempts,
                    )
            if not 200 <= response.status_code < 300:
                raise ExternalServiceUnavailable("MinerU 未返回有效数据")
            payload: Any = response.json()
            if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
                raise ExternalServiceUnavailable("MinerU 未返回有效数据")
            return payload
        except ExternalServiceUnavailable:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError):
            raise ExternalServiceUnavailable("MinerU 未返回有效数据") from None

    @staticmethod
    def _validate_https_url(value: object, allowed_hosts: frozenset[str], message: str) -> None:
        if not isinstance(value, str) or not allowed_hosts:
            raise ExternalServiceUnavailable(message)
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError:
            raise ExternalServiceUnavailable(message) from None
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port not in {None, 443} or parsed.hostname not in allowed_hosts or _DNS_HOST_PATTERN.fullmatch(parsed.hostname) is None:
            raise ExternalServiceUnavailable(message)
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return
        raise ExternalServiceUnavailable(message)

    @staticmethod
    def _validate_allowed_hosts(hosts: set[str] | None) -> frozenset[str]:
        values = frozenset(hosts or ())
        if any(not isinstance(host, str) or _DNS_HOST_PATTERN.fullmatch(host) is None for host in values):
            raise ValueError("允许下载主机必须是 DNS 主机名")
        return values

    @staticmethod
    def _validate_task_id(value: object) -> None:
        if not isinstance(value, str) or _TASK_ID_PATTERN.fullmatch(value) is None:
            raise ExternalServiceUnavailable("MinerU 任务无效")

    @staticmethod
    def _data_value(payload: dict[str, Any], key: str) -> object:
        return payload["data"].get(key)
