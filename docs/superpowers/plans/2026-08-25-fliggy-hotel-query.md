# 飞猪酒店低价查询实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 新增默认关闭的飞猪 API 56180 酒店低价查询接口，并按飞猪返回的最低价做确定性推荐。

**架构：** 新增独立的酒店请求/响应模型、TOP 签名纯函数、飞猪酒店客户端和酒店查询服务；路由仅负责校验、依赖调用和安全错误映射。现有 `/api/fliggy/tickets/*`、高德住宿 POI 和旅行规划合同保持不变。

**技术栈：** FastAPI、Pydantic v2、pydantic-settings、httpx、pytest、pytest-asyncio、respx、Python `Decimal`。

---

## 文件结构与职责

创建或修改以下文件：

- 创建 `backend/app/models/fliggy_hotel.py`：酒店查询请求、来源、酒店条目和响应模型；不修改现有门票模型。
- 创建 `backend/app/errors.py`：酒店配置错误和上游错误的安全领域异常；不改变现有旅行路由错误合同。
- 创建 `backend/app/services/fliggy_signing.py`：TOP 公共参数和 MD5 签名纯函数。
- 创建 `backend/app/services/fliggy_hotel_client.py`：56180 HTTP 客户端与供应商响应投影，定义 `FliggyHotelClient`。
- 创建 `backend/app/services/fliggy_hotel.py`：价格过滤、稳定排序、分转元和响应组装。
- 修改 `backend/app/config.py`：新增飞猪酒店凭据、渠道、网关和开关配置，并校验固定 HTTPS 网关。
- 修改 `backend/.env.example`：补充酒店配置说明，不写入真实凭据。
- 修改 `backend/app/dependencies.py`：新增酒店服务构造函数。
- 修改 `backend/app/main.py`：将酒店服务放入 `app.state`；保留门票服务和现有编排器。
- 修改 `backend/app/api/fliggy.py`：新增 `POST /api/fliggy/hotels/search`，保留门票路由。
- 创建 `backend/tests/test_fliggy_hotel_models.py`。
- 创建 `backend/tests/test_fliggy_signing.py`。
- 创建 `backend/tests/test_fliggy_hotel_client.py`。
- 创建 `backend/tests/test_fliggy_hotel_service.py`。
- 创建 `backend/tests/test_fliggy_hotel_api.py`。
- 修改或创建配置/依赖测试文件，覆盖默认关闭和零外部请求。

---

### 任务 1：建立酒店模型合同

**文件：**
- 创建：`backend/app/models/fliggy_hotel.py`
- 创建：`backend/tests/test_fliggy_hotel_models.py`

- [ ] **步骤 1：编写失败测试**

覆盖有效请求、日期顺序、过去日期、分页边界、空城市名、未知字段和不可变模型：

```python
from datetime import date, timedelta
import pytest
from pydantic import ValidationError
from app.models.fliggy_hotel import FliggyHotelSearchRequest


def test_request_strips_city_and_accepts_valid_dates():
    request = FliggyHotelSearchRequest(
        city_name=" 杭州 ", check_in=date.today(), check_out=date.today() + timedelta(days=1)
    )
    assert request.city_name == "杭州"
    assert request.page_no == 1
    assert request.page_size == 20


def test_request_rejects_invalid_date_range_page_and_unknown_field():
    with pytest.raises(ValidationError):
        FliggyHotelSearchRequest(
            city_name="杭州", check_in=date.today() + timedelta(days=1),
            check_out=date.today(), page_no=0, unexpected="x"
        )
```

另测 `FliggyHotelSearchResponse` 的 `status="realtime"`、`provider="fliggy"`、UTC `retrieved_at`、`Decimal` 价格、酒店 ID 字符串化和 UUID v1-v5 trace ID。模型沿用 `travel.StrictModel` 的 `extra="forbid"`、`frozen=True`；酒店列表内部可用 tuple，但 JSON 必须序列化为数组。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
cd backend
python -m pytest tests/test_fliggy_hotel_models.py -q
```

预期：因 `app.models.fliggy_hotel` 尚不存在而失败。

- [ ] **步骤 3：编写最小模型实现**

实现 `FliggyHotelSearchRequest`、`FliggyHotelSource`、`FliggyHotel`、`FliggyHotelSearchResponse`。日期用 Pydantic `date`，模型校验 `check_in >= date.today()` 且 `check_in < check_out`；价格字段使用 `Decimal`，货币固定 `CNY`，供应商固定 `飞猪`。

- [ ] **步骤 4：运行模型测试**

运行：`python -m pytest tests/test_fliggy_hotel_models.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交模型变更**

```bash
git add backend/app/models/fliggy_hotel.py backend/tests/test_fliggy_hotel_models.py
git commit -m "feat: add fliggy hotel models"
```

---

### 任务 2：实现安全错误类型与 TOP 签名

**文件：**
- 创建：`backend/app/errors.py`
- 创建：`backend/app/services/fliggy_signing.py`
- 创建：`backend/tests/test_fliggy_signing.py`

- [ ] **步骤 1：编写失败测试**

为固定 timestamp 写 TOP MD5 已知向量测试，并验证嵌套业务 JSON、中文 UTF-8、ASCII 参数排序和 secret 不出现在结果参数中：

```python
from datetime import datetime
from app.services.fliggy_signing import build_top_params, sign_top_request


def test_top_params_contain_compact_business_json_and_fixed_method():
    params = build_top_params(
        app_key="app", timestamp=datetime(2026, 8, 25, 12, 0, 0),
        business_payload={"city_name": "杭州", "order": 2}
    )
    assert params["method"] == "alitrip.btrip.hotel.distribution.search.low.price"
    assert '"city_name":"杭州"' in params["param_hotel_search_list_r_q"]


def test_md5_signature_uses_secret_wrapping_and_uppercase_hex():
    params = {"app_key": "app", "method": "demo", "timestamp": "2026-08-25 12:00:00"}
    assert sign_top_request(params, "secret") == "7ED4D301D64B06F075FF4DFA15525302"
```

测试同时断言异常文本和返回参数不包含 `secret`。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_fliggy_signing.py -q`

预期：导入失败或签名断言失败。

- [ ] **步骤 3：实现最小签名模块**

`build_top_params` 固定 method、`format=json`、`v=2.0`、`sign_method=md5`，注入 timestamp 和 `param_hotel_search_list_r_q`；业务 JSON 使用紧凑分隔符和 UTF-8。`sign_top_request` 按参数名 ASCII 排序，拼接 `secret + key + value + secret` 后 MD5 大写。异常类型至少包含 `FliggyHotelNotConfigured` 和带受控 `code/provider_code/retryable` 的 `FliggyHotelUpstreamError`，不得保存完整供应商响应或签名原文。

- [ ] **步骤 4：运行签名测试**

运行：`python -m pytest tests/test_fliggy_signing.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交签名与错误变更**

```bash
git add backend/app/errors.py backend/app/services/fliggy_signing.py backend/tests/test_fliggy_signing.py
git commit -m "feat: add fliggy top signing"
```

---

### 任务 3：实现 56180 飞猪客户端

**文件：**
- 创建：`backend/app/services/fliggy_hotel_client.py`
- 创建：`backend/tests/test_fliggy_hotel_client.py`

- [ ] **步骤 1：编写 respx 失败测试**

测试客户端 `search_low_price(city_name, check_in, check_out, page_no, page_size)`：请求必须是 POST 到 `https://eco.taobao.com/router/rest`，业务 JSON 必须包含服务端 `sub_channel`、`order=2`、`dir=1` 和分页字段；不得接受客户端透传其他字段。

成功 fixture 使用以下已确认字段：

```json
{"alitrip_btrip_hotel_distribution_search_low_price_response":
 {"result":{"module":{"hotels":[{"shid":10076614,"name":"杭州中洲大酒店","low_price":18000,"supplier_name":"飞猪"}],"total":1}}}}
```

另测空结果、供应商认证/权限/渠道错误、429/5xx 重试、超时/连接失败、非 JSON、缺字段、负数价格和非 HTTPS/非 canonical URL。异常文本不得包含 AppSecret、完整签名或原始 body。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_fliggy_hotel_client.py -q`

预期：客户端模块不存在导致失败。

- [ ] **步骤 3：实现最小客户端**

新增不可变内部 `FliggyRawHotel`/`FliggyRawSearchResult`。客户端固定 method、网关和业务字段，使用 `httpx.AsyncClient`、项目 `request_with_retry`；只投影 `shid/name/low_price/supplier_name/total`，不缓存低价。将 HTTP、JSON、供应商业务错误和结构错误转为受控上游异常；允许重试的网络/429/5xx 不记录敏感参数。

- [ ] **步骤 4：运行客户端测试**

运行：`python -m pytest tests/test_fliggy_hotel_client.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交客户端变更**

```bash
git add backend/app/services/fliggy_hotel_client.py backend/tests/test_fliggy_hotel_client.py
git commit -m "feat: add fliggy hotel client"
```

---

### 任务 4：实现价格优先酒店服务

**文件：**
- 创建：`backend/app/services/fliggy_hotel.py`
- 创建：`backend/tests/test_fliggy_hotel_service.py`

- [ ] **步骤 1：编写失败测试**

使用 fake client 验证：18000 分转换为 `Decimal("180.00")`、价格升序、同价稳定、零/负数/缺失价格过滤、酒店 ID 保持字符串、供应商 total 保留、source 为实时飞猪数据，且 fake Amap 不会被调用。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_fliggy_hotel_service.py -q`

预期：服务模块不存在导致失败。

- [ ] **步骤 3：实现最小服务**

实现 `HotelSearchService.search(request, trace_id)`：调用客户端，按整数 cents 做 `sorted(..., key=lambda item: item.low_price_cents)`，保留稳定同价顺序；过滤非正价格；使用 `Decimal(cents) / Decimal(100)`；构造 `status="realtime"`、UTC `retrieved_at`、来源和 trace ID。不调用高德、RAG 或门票服务，不缓存。

- [ ] **步骤 4：运行服务测试**

运行：`python -m pytest tests/test_fliggy_hotel_service.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交服务变更**

```bash
git add backend/app/services/fliggy_hotel.py backend/tests/test_fliggy_hotel_service.py
git commit -m "feat: add fliggy hotel price recommendations"
```

---

### 任务 5：接入配置、依赖和应用状态

**文件：**
- 修改：`backend/app/config.py`
- 修改：`backend/.env.example`
- 修改：`backend/app/dependencies.py`
- 修改：`backend/app/main.py`
- 创建：`backend/tests/test_fliggy_hotel_config.py`

- [ ] **步骤 1：编写配置失败测试**

覆盖默认值、固定 URL、开关关闭、任一凭据缺失，以及关闭态零外部请求：

```python
def test_hotel_fliggy_is_disabled_by_default():
    settings = Settings()
    assert settings.fliggy_hotel_enabled is False
    assert settings.fliggy_hotel_api_url == "https://eco.taobao.com/router/rest"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_fliggy_hotel_config.py -q`

预期：字段不存在导致失败。

- [ ] **步骤 3：实现配置与组装**

新增 `fliggy_hotel_enabled=False`、`fliggy_hotel_app_key`、`fliggy_hotel_app_secret`、`fliggy_hotel_sub_channel`、`fliggy_hotel_api_url`；名称避免覆盖现有门票 `fliggy_enabled`。`.env.example` 使用对应的大写环境变量 `FLIGGY_HOTEL_ENABLED`、`FLIGGY_HOTEL_APP_KEY`、`FLIGGY_HOTEL_APP_SECRET`、`FLIGGY_HOTEL_SUB_CHANNEL`、`FLIGGY_HOTEL_API_URL`。配置 validator 只允许精确的 `https://eco.taobao.com/router/rest`。新增 `build_hotel_search_service(settings)`；关闭或凭据缺失时构造不会建立 HTTP 请求，调用抛出 `FliggyHotelNotConfigured`。`create_app()` 将服务放入 `app.state.fliggy_hotel_service`，不改变现有 `fliggy_ticket_service`。

- [ ] **步骤 4：运行配置与回归测试**

运行：`python -m pytest tests/test_fliggy_hotel_config.py tests/test_fliggy_models.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交配置变更**

```bash
git add backend/app/config.py backend/.env.example backend/app/dependencies.py backend/app/main.py backend/tests/test_fliggy_hotel_config.py
git commit -m "feat: configure fliggy hotel search"
```

---

### 任务 6：新增酒店 API 路由并映射安全错误

**文件：**
- 修改：`backend/app/api/fliggy.py`
- 创建：`backend/tests/test_fliggy_hotel_api.py`

- [ ] **步骤 1：编写 ASGI API 失败测试**

使用 `create_app()` 和 `ASGITransport` 覆盖：

- `POST /api/fliggy/hotels/search` 成功返回模型 JSON；
- 城市/日期/分页错误与未知字段返回 422；
- 默认关闭返回 503 且 respx 无请求；
- 上游认证、权限、渠道、超时、连接、5xx、结构错误返回 502；
- response 不包含 AppSecret、签名、完整供应商 body；
- 现有门票 `/api/fliggy/tickets/search` 测试继续通过。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_fliggy_hotel_api.py tests/test_fliggy_api.py -q`

预期：酒店路径返回 404 或路由导入缺失。

- [ ] **步骤 3：实现路由**

在现有 `APIRouter(prefix="/api/fliggy")` 中新增：

```python
@router.post("/hotels/search", response_model=FliggyHotelSearchResponse)
async def search_hotels(payload: FliggyHotelSearchRequest, request: Request):
    trace_id = getattr(request.state, "request_id", str(uuid4()))
    try:
        return await request.app.state.fliggy_hotel_service.search(payload, trace_id)
    except FliggyHotelNotConfigured as error:
        raise HTTPException(status_code=503, detail="飞猪酒店查询服务尚未配置") from error
    except FliggyHotelUpstreamError as error:
        raise HTTPException(status_code=502, detail={"code": error.code, "trace_id": trace_id}) from error
```

路由不实现签名、供应商字段映射或推荐排序；供应商自由文本不直接进入响应。

- [ ] **步骤 4：运行 API 测试**

运行：`python -m pytest tests/test_fliggy_hotel_api.py tests/test_fliggy_api.py -q`

预期：全部 PASS。

- [ ] **步骤 5：提交路由变更**

```bash
git add backend/app/api/fliggy.py backend/tests/test_fliggy_hotel_api.py
git commit -m "feat: expose fliggy hotel search api"
```

---

### 任务 7：完整验证与安全回归

**文件：**
- 测试：前述所有酒店测试及现有后端测试。

- [ ] **步骤 1：运行酒店专项测试**

```bash
cd backend
python -m pytest tests/test_fliggy_hotel*.py tests/test_fliggy_api.py -q
```

预期：全部 PASS，默认关闭测试确认没有飞猪外部请求。

- [ ] **步骤 2：运行相关回归测试**

```bash
python -m pytest tests/test_amap.py tests/test_agents_poi.py tests/test_api.py -q
```

预期：全部 PASS，现有高德住宿 POI 和旅行规划行为不变。

- [ ] **步骤 3：运行全量测试和编译检查**

```bash
python -m pytest -q
python -m compileall app tests
```

预期：pytest 全部通过，compileall 返回 0。

- [ ] **步骤 4：检查敏感信息和差异**

```bash
git diff --check
git status --short
```

预期：酒店代码、测试和文档中没有真实 AppSecret、签名原文或供应商完整响应；仅保留用户原有未跟踪日志文件，不覆盖或删除它们。

- [ ] **步骤 5：提交最终测试修正**

```bash
git add backend docs/superpowers/plans/2026-08-25-fliggy-hotel-query.md
git commit -m "test: verify fliggy hotel query integration"
```
