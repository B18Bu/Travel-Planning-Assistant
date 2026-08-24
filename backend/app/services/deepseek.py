from __future__ import annotations

import httpx

from app.services.resilience import CircuitBreaker, ExternalServiceUnavailable, request_with_retry


class DeepSeekClient:
    """DeepSeek 大模型的受控只读客户端，仅用于生成最终表达文案。"""

    _base_url = "https://api.deepseek.com"

    def __init__(
        self,
        api_key: str,
        base_url: str = _base_url,
        model: str = "deepseek-chat",
        *,
        breaker: CircuitBreaker | None = None,
        max_attempts: int = 3,
        max_tokens: int = 2000,
        timeout: httpx.Timeout | float = 10.0,
    ) -> None:
        if base_url != self._base_url:
            raise ExternalServiceUnavailable("DeepSeek 服务地址不受支持")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model 必须为非空字符串")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts 必须在 1 到 3 之间")
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 256 <= max_tokens <= 8192:
            raise ValueError("max_tokens 必须在 256 到 8192 之间")
        self.api_key = api_key
        self.model = model
        self.breaker = breaker or CircuitBreaker(3, 60)
        self.max_attempts = max_attempts
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        self._require_key()
        token = self.breaker.ensure_available()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retry(
                    lambda: client.post(
                        f"{self._base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "temperature": 0.2,
                            "max_tokens": self.max_tokens,
                        },
                    ),
                    max_attempts=self.max_attempts,
                )
                if not 200 <= response.status_code < 300:
                    raise ExternalServiceUnavailable("DeepSeek 未返回有效数据")
                payload = response.json()
            content = self._parse_content(payload)
        except ExternalServiceUnavailable:
            self.breaker.record_failure(token)
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            self.breaker.record_failure(token)
            raise ExternalServiceUnavailable("DeepSeek 未返回有效数据") from None
        self.breaker.record_success(token)
        return content

    def _require_key(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ExternalServiceUnavailable("DeepSeek API 密钥未配置")

    def _parse_content(self, payload: object) -> str:
        if not isinstance(payload, dict):
            raise ValueError("DeepSeek 响应结构错误")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("DeepSeek 响应结构错误")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("DeepSeek 响应结构错误")
        stripped = content.strip()
        if len(stripped) < 20 or len(stripped) > self.max_tokens * 4:
            raise ValueError("DeepSeek 响应长度无效")
        return stripped
