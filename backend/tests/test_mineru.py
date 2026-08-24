import httpx
import pytest
import respx

from app.services.mineru import MinerUClient
from app.services.resilience import ExternalServiceUnavailable


BASE = "https://mineru.net"
ALLOWED_HOST = "uploads.example"


def client(**overrides):
    options = {"api_key": "mineru-key", "allowed_download_hosts": {ALLOWED_HOST}, "allowed_result_hosts": {"result.example"}}
    options.update(overrides)
    return MinerUClient(**options)


def test_mineru_requires_configured_key_before_request():
    client = MinerUClient(api_key="")

    with pytest.raises(ExternalServiceUnavailable, match="密钥未配置"):
        client.require_configured()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://uploads.example/report.pdf", "https://127.0.0.1/report.pdf", "https://localhost/report.pdf"])
async def test_mineru_rejects_all_urls_without_an_explicit_allowlist_before_http(url, monkeypatch):
    mineru = MinerUClient(api_key="mineru-key")
    monkeypatch.setattr(mineru, "_request", lambda *_args: (_ for _ in ()).throw(AssertionError("不应发起 HTTP")))

    with pytest.raises(ExternalServiceUnavailable, match="请求文件无效"):
        await mineru.submit_task(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://uploads.example/report.pdf", "file:///private/report.pdf", "C:/private/report.pdf", "https://evil.example/report.pdf", "https://127.0.0.1/report.pdf", "https://localhost/report.pdf", "https://uploads.example:444/report.pdf"])
async def test_mineru_rejects_non_https_or_unapproved_download_urls_before_http(url, monkeypatch):
    mineru = client()
    monkeypatch.setattr(mineru, "_request", lambda *_args: (_ for _ in ()).throw(AssertionError("不应发起 HTTP")))

    with pytest.raises(ExternalServiceUnavailable, match="请求文件无效"):
        await mineru.submit_task(url)


@pytest.mark.asyncio
@respx.mock
async def test_mineru_submits_task_to_fixed_endpoint_and_returns_task_id():
    route = respx.post(f"{BASE}/api/v4/file-urls/batch").mock(return_value=httpx.Response(200, json={"code": 0, "data": {"batch_id": "batch-1", "private": "discard"}}))

    task_id = await client().submit_task("https://uploads.example/report.pdf")

    assert task_id == "batch-1"
    assert route.calls[0].request.headers["Authorization"] == "Bearer mineru-key"
    assert "private" not in task_id


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("task_id", ["batch?x=1", "batch#fragment", "batch%2Fother", "bad/id", "x" * 129])
async def test_mineru_rejects_unsafe_task_id_returned_by_submit_response(task_id):
    respx.post(f"{BASE}/api/v4/file-urls/batch").mock(return_value=httpx.Response(200, json={"code": 0, "data": {"batch_id": task_id}}))

    with pytest.raises(ExternalServiceUnavailable, match="任务无效"):
        await client().submit_task("https://uploads.example/report.pdf")


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://127.0.0.1/report.pdf", "https://[::1]/report.pdf", "https://127.1/report.pdf", "https://2130706433/report.pdf", "https://0x7f000001/report.pdf", "https://0177.0.0.1/report.pdf"])
async def test_mineru_rejects_ip_literals_and_ambiguous_numeric_hosts_before_http(url, monkeypatch):
    mineru = MinerUClient(api_key="mineru-key", allowed_download_hosts={"uploads.example"})
    monkeypatch.setattr(mineru, "_request", lambda *_args: (_ for _ in ()).throw(AssertionError("不应发起 HTTP")))

    with pytest.raises(ExternalServiceUnavailable, match="请求文件无效"):
        await mineru.submit_task(url)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "127.1", "2130706433", "0x7f000001", "0177.0.0.1"])
def test_mineru_rejects_non_dns_allowlist_hosts(host):
    with pytest.raises(ValueError, match="DNS 主机名"):
        MinerUClient(api_key="mineru-key", allowed_download_hosts={host})


@pytest.mark.asyncio
@respx.mock
async def test_mineru_queries_task_status_and_returns_controlled_projection():
    route = respx.get(f"{BASE}/api/v4/extract/task/batch-1").mock(return_value=httpx.Response(200, json={"code": 0, "data": {"state": "done", "private": "discard"}}))

    assert await client().get_task_status("batch-1") == "done"
    assert route.calls[0].request.headers["Authorization"] == "Bearer mineru-key"


@pytest.mark.asyncio
@respx.mock
async def test_mineru_rejects_path_injection_task_ids_before_http():
    called = False

    def request_handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, json={"code": 0, "data": {"state": "done"}})

    respx.get(url__regex=r"https://mineru\.net/.*").mock(side_effect=request_handler)
    mineru = client()
    for task_id in ["batch?admin=true", "batch#fragment", "batch%2Fother", "../batch"]:
        with pytest.raises(ExternalServiceUnavailable, match="任务无效"):
            await mineru.get_task_status(task_id)
    assert not called


@pytest.mark.asyncio
@respx.mock
async def test_mineru_returns_completed_result_without_polling():
    respx.get(f"{BASE}/api/v4/extract/task/batch-1/result").mock(return_value=httpx.Response(200, json={"code": 0, "data": {"full_zip_url": "https://result.example/archive.zip", "private": "discard"}}))

    assert await client().get_completed_result("batch-1") == {"full_zip_url": "https://result.example/archive.zip"}


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("result_url", ["http://result.example/archive.zip", "https://evil.example/archive.zip", "https://127.0.0.1/archive.zip", "https://localhost/archive.zip", "https://result.example:444/archive.zip"])
async def test_mineru_rejects_untrusted_completed_result_urls(result_url):
    route = respx.get(f"{BASE}/api/v4/extract/task/batch-1/result").mock(return_value=httpx.Response(200, json={"code": 0, "data": {"full_zip_url": result_url}}))

    with pytest.raises(ExternalServiceUnavailable, match="结果无效"):
        await client().get_completed_result("batch-1")
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_mineru_post_submission_is_not_retried_to_avoid_duplicate_tasks():
    route = respx.post(f"{BASE}/api/v4/file-urls/batch").mock(return_value=httpx.Response(503, text="secret response body"))

    with pytest.raises(ExternalServiceUnavailable) as error:
        await client(max_attempts=3).submit_task("https://uploads.example/report.pdf")

    assert route.call_count == 1
    assert "secret" not in str(error.value)
