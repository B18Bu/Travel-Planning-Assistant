import base64
import json

import httpx
import pytest
import respx

from app.services.qwen_vl import QwenVLClient


BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
IMAGE_BYTES = b"\x89PNG\r\n\x1a\nexample"


@pytest.mark.asyncio
async def test_qwen_vl_returns_recordable_degradation_without_key():
    result = await QwenVLClient(api_key="").recognize_chart(IMAGE_BYTES, "image/png")

    assert result == {"text": None, "degraded": True, "failure_message": "Qwen-VL API 密钥未配置"}


@pytest.mark.asyncio
@respx.mock
async def test_qwen_vl_builds_data_uri_from_image_bytes_and_uses_extraction_only_prompt():
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "横轴：月份\n图例：客流", "private": "discard"}}]})
    )
    client = QwenVLClient(api_key="qwen-key", timeout=2.0)

    result = await client.recognize_chart(IMAGE_BYTES, "image/png")

    assert result == {"text": "横轴：月份\n图例：客流", "degraded": False, "failure_message": None}
    payload = json.loads(route.calls[0].request.content)
    content = payload["messages"][0]["content"]
    assert content[0]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(IMAGE_BYTES).decode("ascii")
    prompt = content[1]["text"]
    assert "可见文字、标题、坐标轴、图例、标签" in prompt
    assert "禁止趋势推理" in prompt
    assert "纯文本" in prompt
    assert route.calls[0].request.headers["Authorization"] == "Bearer qwen-key"


@pytest.mark.asyncio
@respx.mock
async def test_qwen_vl_single_image_failure_is_degraded_and_does_not_raise():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(500, text="secret payload https://private.example")
    )
    client = QwenVLClient(api_key="qwen-key", max_attempts=1)

    result = await client.recognize_chart(IMAGE_BYTES, "image/png")

    assert result["text"] is None
    assert result["degraded"] is True
    assert "private" not in result["failure_message"]
    assert "secret" not in result["failure_message"]
