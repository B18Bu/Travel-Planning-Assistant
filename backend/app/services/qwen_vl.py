from __future__ import annotations

import base64
from typing import TypedDict

import httpx

from app.services.resilience import ExternalServiceUnavailable, request_with_retry


class ChartOcrResult(TypedDict):
    text: str | None
    degraded: bool
    failure_message: str | None


class QwenVLClient:
    """Qwen-VL 单图图表 OCR 的可降级客户端。"""

    _base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    _prompt = "仅提取图中可见文字、标题、坐标轴、图例、标签。禁止趋势推理或补充解释。仅输出纯文本。"

    def __init__(self, api_key: str, model: str = "qwen-vl-max", base_url: str = _base_url, max_attempts: int = 3, timeout: httpx.Timeout | float = 10.0) -> None:
        if base_url != self._base_url:
            raise ExternalServiceUnavailable("Qwen-VL 服务地址不受支持")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts 必须在 1 到 3 之间")
        self.api_key = api_key
        self.model = model
        self.max_attempts = max_attempts
        self.timeout = timeout

    async def recognize_chart(self, image_bytes: bytes, media_type: str) -> ChartOcrResult:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            return self._degraded("Qwen-VL API 密钥未配置")
        if not isinstance(image_bytes, bytes) or not image_bytes or media_type not in {"image/png", "image/jpeg", "image/webp"}:
            return self._degraded("图表图片无效")
        data_uri = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retry(
                    lambda: client.post(f"{self._base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"}, json={"model": self.model, "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_uri}}, {"type": "text", "text": self._prompt}]}]}),
                    max_attempts=self.max_attempts,
                )
            if not 200 <= response.status_code < 300:
                return self._degraded("Qwen-VL 图表识别失败")
            payload = response.json()
            choices = payload.get("choices") if isinstance(payload, dict) else None
            message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
            text = message.get("content") if isinstance(message, dict) else None
            if not isinstance(text, str) or not text.strip():
                return self._degraded("Qwen-VL 图表识别失败")
            return {"text": text.strip(), "degraded": False, "failure_message": None}
        except (ExternalServiceUnavailable, httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError):
            return self._degraded("Qwen-VL 图表识别失败")

    @staticmethod
    def _degraded(message: str) -> ChartOcrResult:
        return {"text": None, "degraded": True, "failure_message": message}
