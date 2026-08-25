# 飞猪门票查询实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将工作台“车票查询”改为默认关闭的“门票查询”，并在授权和测试条件满足后，通过飞猪门票 API 查询景点商品、指定日期价格/库存与入园规则。

**架构：** 前端沿用现有 `showView()` 内部视图，门票页面提交景点关键词、入园日期和游客人数。后端新增严格的门票请求/响应模型与 `/api/fliggy/tickets/search`，服务内部按 `scenic.query → product.query → rule.query` 顺序调用飞猪 TOP Router；默认注入关闭实现，真实适配器只在服务端开关、授权和字段许可均满足时启用。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、pytest、现有 HTTP 客户端/韧性工具、原生 HTML/CSS/JavaScript、`fetch`、安全 DOM API。

**官方依据：**

- [门票 API 类目](https://open.alitrip.com/docs/api_list.htm?cid=20722)
- [`alitrip.ticket.scenic.query`](https://open.alitrip.com/docs/api.htm?apiId=27941)
- [`alitrip.ticket.product.query`](https://open.alitrip.com/docs/api.htm?apiId=27945)
- [`alitrip.ticket.rule.query`](https://open.alitrip.com/docs/api.htm?apiId=27942)
- [淘宝开放平台 API 公共调用参数说明（见各 API 详情页）](https://open.alitrip.com/docs/api.htm?apiId=27945)

---

## 实施边界

### 当前可实施阶段：默认关闭态

可以实现输入合同、服务状态、导航入口、页面筹备态、会话同意和测试，但不访问飞猪，不显示模拟价格/库存，不提供预订按钮。

### 授权后阶段：真实只读查询

只有在以下资料完成并记录到 `docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md` 后，才能执行真实适配器任务：

- 应用授权主体、卖家/渠道范围和 `session` 获取方式；
- `scenic.query`、`product.query`、`rule.query` 字段、错误码和展示许可；
- 正式/测试环境、`app_key`、签名密钥保存位置和限流规则；
- 价格、库存、图片、游客信息要求和规则文本的展示许可；
- 沙箱契约样例、安全评审和发布批准。

---

## 文件结构

### 当前默认关闭态

| 文件 | 职责 |
| --- | --- |
| `backend/app/models/fliggy.py` | 门票查询请求、服务状态和关闭态响应合同。 |
| `backend/app/services/fliggy.py` | 门票服务协议与默认关闭实现。 |
| `backend/app/api/fliggy.py` | 门票状态和查询 API；关闭态返回受控 `503`。 |
| `backend/app/config.py` | 默认关闭的飞猪开关。 |
| `backend/app/main.py` | 注入关闭服务并注册路由。 |
| `frontend/index.html` | 将“车票查询”改为“门票查询”，增加门票表单和同意弹窗。 |
| `frontend/app.js` | 门票视图、状态加载、会话同意和关闭态渲染。 |
| `frontend/styles.css` | 门票表单、商品结果、状态和窄屏样式。 |
| `backend/tests/test_fliggy_models.py` | 请求边界和未知字段测试。 |
| `backend/tests/test_fliggy_api.py` | 状态、关闭态、参数错误和无外部访问测试。 |
| `backend/tests/test_frontend_assets.py` | 导航、门票视图、同意和安全渲染静态测试。 |
| `README.md` | 门票查询筹备状态和交易边界说明。 |

### 授权后真实查询

| 文件 | 职责 |
| --- | --- |
| `backend/app/config.py` | 按正式合同增加 TOP Router、凭据名称、开关和超时配置。 |
| `backend/app/models/fliggy.py` | 增加景点、商品、日期库存、规则和规范化响应模型。 |
| `backend/app/services/fliggy.py` | 实现签名、三段调用链、字段白名单、实时查询和错误归类。 |
| `backend/app/api/fliggy.py` | 将查询路由接入真实服务并映射受控错误。 |
| `backend/tests/test_fliggy_service.py` | 使用官方样例 Mock 验证请求映射、调用顺序、结果和错误。 |
| `frontend/app.js` | 安全渲染门票商品卡片、价格、库存、图片和规则。 |
| `frontend/styles.css` | 真实门票结果卡片样式。 |
| `docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md` | 记录授权、字段映射和验收结果。 |
| `README.md`、`docs/项目宪法.md` | 记录飞猪授权只读查询例外和发布边界。 |

---

## 阶段 A：默认关闭态

### 任务 1：定义门票请求和服务状态模型

**文件：**
- 创建：`backend/app/models/fliggy.py`
- 测试：`backend/tests/test_fliggy_models.py`

- [ ] **步骤 1：编写失败测试，锁定请求边界**

```python
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.models.fliggy import TicketSearchRequest


def test_ticket_search_accepts_minimal_request() -> None:
    request = TicketSearchRequest(
        scenic_keyword="西湖",
        entry_date=date.today(),
        visitor_count=2,
    )

    assert request.scenic_keyword == "西湖"
    assert request.visitor_count == 2


def test_ticket_search_rejects_past_date_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TicketSearchRequest(
            scenic_keyword="西湖",
            entry_date=date.today() - timedelta(days=1),
            visitor_count=2,
            item_id="must-not-be-client-controlled",
        )


def test_ticket_search_rejects_invalid_visitor_count() -> None:
    with pytest.raises(ValidationError):
        TicketSearchRequest(
            scenic_keyword="西湖",
            entry_date=date.today(),
            visitor_count=21,
        )
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_models.py -q
```

预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.models.fliggy'`。

- [ ] **步骤 3：实现最小严格模型**

```python
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TicketSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenic_keyword: str = Field(min_length=1, max_length=100)
    entry_date: date
    visitor_count: int = Field(ge=1, le=20)

    @field_validator("entry_date")
    @classmethod
    def entry_date_must_not_be_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("入园日期不得早于今天")
        return value


class FliggyServiceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    message: str
```

模型不包含 `item_id`、`ali_scenic_id`、`out_scenic_id` 或游客身份字段；这些由后端适配器处理，客户端不能覆盖。

- [ ] **步骤 4：运行模型测试确认通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_models.py -q
```

预期：PASS。

- [ ] **步骤 5：提交模型合同**

```powershell
git add backend/app/models/fliggy.py backend/tests/test_fliggy_models.py
git commit -m "feat: 定义门票查询请求合同"
```

### 任务 2：实现默认关闭的门票服务和 API

**文件：**
- 创建：`backend/app/services/fliggy.py`
- 创建：`backend/app/api/fliggy.py`
- 修改：`backend/app/config.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_fliggy_api.py`

- [ ] **步骤 1：编写失败测试，验证关闭态不会访问外部服务**

```python
from fastapi.testclient import TestClient


def test_fliggy_status_is_unavailable_by_default(client: TestClient) -> None:
    response = client.get("/api/fliggy/status")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "message": "飞猪门票查询服务尚未配置",
    }


def test_ticket_search_is_closed_without_fliggy_request(client: TestClient) -> None:
    response = client.post(
        "/api/fliggy/tickets/search",
        json={
            "scenic_keyword": "西湖",
            "entry_date": "2099-09-01",
            "visitor_count": 2,
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "飞猪门票查询服务尚未配置"}
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_api.py -q
```

预期：FAIL，路由不存在或返回 `404`。

- [ ] **步骤 3：增加默认关闭配置**

在 `backend/app/config.py` 的 `Settings` 中加入：

```python
fliggy_enabled: bool = False
```

当前不增加真实 `app_key`、`secret`、`session` 或 `sub_channel` 的默认值；真实配置必须依赖授权登记表。

- [ ] **步骤 4：实现关闭服务**

```python
from app.models.fliggy import FliggyServiceStatus


class FliggyNotConfiguredError(RuntimeError):
    """飞猪门票查询功能未启用或尚未完成配置。"""


class DisabledFliggyTicketService:
    def status(self) -> FliggyServiceStatus:
        return FliggyServiceStatus(
            available=False,
            message="飞猪门票查询服务尚未配置",
        )

    def search_tickets(self, request):
        raise FliggyNotConfiguredError
```

- [ ] **步骤 5：实现并注册关闭态路由**

`backend/app/api/fliggy.py` 必须提供：

```python
@router.get("/status", response_model=FliggyServiceStatus)
async def get_fliggy_status(request: Request) -> FliggyServiceStatus:
    return request.app.state.fliggy_ticket_service.status()


@router.post("/tickets/search")
async def search_tickets(payload: TicketSearchRequest, request: Request):
    raise HTTPException(status_code=503, detail="飞猪门票查询服务尚未配置")
```

在 `backend/app/main.py` 中设置 `app.state.fliggy_ticket_service = DisabledFliggyTicketService()`，并在静态文件挂载前注册 `fliggy_router`。关闭态路由不得创建 HTTP 客户端或访问外部 URL。

- [ ] **步骤 6：运行 API 测试确认通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_api.py -q
```

预期：PASS。

- [ ] **步骤 7：提交关闭态 API**

```powershell
git add backend/app/config.py backend/app/services/fliggy.py backend/app/api/fliggy.py backend/app/main.py backend/tests/test_fliggy_api.py
git commit -m "feat: 增加门票查询关闭态接口"
```

### 任务 3：将前端“车票查询”改为“门票查询”

**文件：**
- 修改：`frontend/index.html`
- 修改：`frontend/app.js`
- 修改：`frontend/styles.css`
- 测试：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：编写失败的前端静态测试**

```python
def test_frontend_uses_ticket_query_view(frontend_dir: Path) -> None:
    index = (frontend_dir / "index.html").read_text(encoding="utf-8")
    script = (frontend_dir / "app.js").read_text(encoding="utf-8")

    assert "门票查询" in index
    assert 'id="view-ticket"' in index
    assert 'id="ticket-form"' in index
    assert '"/api/fliggy/status"' in script
    assert "sessionStorage" in script
    assert "预订" not in index
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：FAIL，因为现有页面仍是“车票查询”规划状态，或没有门票视图。

- [ ] **步骤 3：修改导航和门票视图**

在 `frontend/index.html` 中将原车票入口替换为：

```html
<button class="side-nav" id="nav-ticket" onclick="showView('ticket')">
  <span>🎟️</span> 门票查询
</button>
```

增加独立视图：

```html
<section id="view-ticket" class="view">
  <div class="feature-page fliggy-page">
    <div class="feature-page-head">
      <div>Fliggy Ticket Search</div>
      <h2>门票查询</h2>
      <p>查询景点门票、指定日期价格、库存和入园规则。</p>
    </div>
    <p id="ticket-service-status" class="fliggy-status" role="status" aria-live="polite"></p>
    <form id="ticket-form" class="fliggy-form">
      <label>景点关键词<input id="ticket-scenic-keyword" name="scenic_keyword" maxlength="100" required></label>
      <label>入园日期<input id="ticket-entry-date" name="entry_date" type="date" required></label>
      <label>游客人数<input id="ticket-visitor-count" name="visitor_count" type="number" min="1" max="20" value="1" required></label>
      <button id="ticket-submit" class="btn-primary" type="submit" disabled>查询门票</button>
    </form>
    <section id="ticket-results" class="fliggy-results" hidden></section>
  </div>
</section>
```

不添加预订、购买、支付或游客身份输入控件。

- [ ] **步骤 4：实现状态加载和会话同意**

在 `frontend/app.js` 中实现以下确定性行为：

```javascript
const FLIGGY_CONSENT_KEY = "fliggy-ticket-query-consent";
let fliggyStatus = { available: false, message: "飞猪门票查询服务尚未配置" };

function hasFliggyConsent() {
  try {
    return sessionStorage.getItem(FLIGGY_CONSENT_KEY) === "accepted";
  } catch {
    return false;
  }
}

function saveFliggyConsent() {
  try {
    sessionStorage.setItem(FLIGGY_CONSENT_KEY, "accepted");
    return true;
  } catch {
    return false;
  }
}
```

`loadFliggyStatus()` 只请求 `/api/fliggy/status`，只读取 `available` 和 `message`；失败按不可用处理。提交时先确认服务可用，再弹出会话级同意；拒绝或存储失败不发送查询请求。关闭态结果区必须清空并保持隐藏。

- [ ] **步骤 5：增加样式并保留既有模块行为**

在 `frontend/styles.css` 中增加：

```css
.fliggy-page { max-width: 960px; }
.fliggy-form { display: grid; gap: 16px; }
.fliggy-status { min-height: 1.5em; }
.fliggy-results { margin-top: 24px; }
```

在窄屏媒体查询中确保输入和按钮不产生横向溢出。不得重构既有行程规划、攻略查询、文档库或看板样式。

- [ ] **步骤 6：运行前端测试确认通过**

运行：

```powershell
node --check frontend/app.js
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
git diff --check
```

预期：PASS。

- [ ] **步骤 7：提交前端门票入口**

```powershell
git add frontend/index.html frontend/app.js frontend/styles.css backend/tests/test_frontend_assets.py
git commit -m "feat: 将车票入口改为门票查询"
```

### 任务 4：补充关闭态文档与回归测试

**文件：**
- 修改：`README.md`
- 修改：`docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md`
- 测试：`backend/tests/test_docs.py`

- [ ] **步骤 1：编写文档失败测试**

```python
def test_readme_describes_ticket_query_as_read_only(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "门票查询" in readme
    assert "不创建订单" in readme
    assert "不处理支付" in readme
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
```

预期：FAIL，因为 README 仍未描述门票查询入口。

- [ ] **步骤 3：更新 README 和登记表**

README 必须说明：

- 车票查询已调整为门票查询；
- 当前只提供景点门票商品、价格/库存和规则查询；
- 默认关闭，不使用模拟实时数据；
- 不预订、不下单、不支付、不退款、不核销；
- 不收集游客身份信息；
- 真实启用必须完成飞猪授权、展示许可、沙箱测试和安全评审。

登记表新增官方门票 API 记录：`27941`、`27945`、`27942`，并记录“景点查询只能返回卖家已发布商品”“product.query 不包含游客人数参数”“价格精确到分”“库存来自日期库存字段”等事实。

- [ ] **步骤 4：运行回归测试**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
python -m pytest -c backend/pytest.ini backend/tests -q
node --check frontend/app.js
git diff --check
```

预期：全部 PASS；若失败，记录实际失败项，不得以部分测试代替全量结果。

- [ ] **步骤 5：提交关闭态文档**

```powershell
git add README.md docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md backend/tests/test_docs.py
git commit -m "docs: 说明门票查询关闭态边界"
```

---

## 阶段 B：取得授权后实现真实查询

### 任务 5：固化正式配置与响应模型

**文件：**
- 修改：`backend/app/config.py`
- 修改：`backend/app/models/fliggy.py`
- 测试：`backend/tests/test_config.py`
- 测试：`backend/tests/test_fliggy_models.py`

- [ ] **步骤 1：先完成授权资料登记**

在修改代码前，填写登记表中的应用主体、卖家/渠道范围、正式/测试地址、`session` 获取方式、签名算法、展示许可、限流和错误码。真实密钥只登记环境变量名或密钥服务路径。

- [ ] **步骤 2：编写正式字段的失败测试**

使用官方无密钥响应样例，覆盖：

```python
def test_ticket_response_rejects_raw_supplier_fields() -> None:
    with pytest.raises(ValidationError):
        TicketSearchResponse.model_validate({"tickets": [{"raw_response": {}}]})


def test_ticket_price_unit_is_explicit() -> None:
    result = TicketProduct(price_amount=1234, price_unit="分", currency="CNY")
    assert result.price_amount == 1234
    assert result.price_unit == "分"
```

- [ ] **步骤 3：实现严格领域模型和配置校验**

实现 `TicketProduct`、`TicketRule`、`TicketSearchResponse` 等模型，字段只覆盖已获书面允许的商品、图片、票种、日期库存和规则数据；使用 `extra="forbid"`。价格使用整数和明确 `price_unit`、`currency`；库存区分正数、0、缺失和异常状态。配置中的正式 URL 只允许 HTTPS，`app_key`、密钥和 `session` 不设代码默认真实值。

- [ ] **步骤 4：运行模型和配置测试**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_config.py backend/tests/test_fliggy_models.py -q
```

预期：PASS。

- [ ] **步骤 5：提交领域合同**

```powershell
git add backend/app/config.py backend/app/models/fliggy.py backend/tests/test_config.py backend/tests/test_fliggy_models.py
git commit -m "feat: 固化门票查询领域合同"
```

### 任务 6：实现三段飞猪只读调用链

**文件：**
- 修改：`backend/app/services/fliggy.py`
- 测试：`backend/tests/test_fliggy_service.py`

- [ ] **步骤 1：编写调用顺序和字段白名单失败测试**

使用 HTTP Mock 验证：

```python
def test_ticket_service_queries_scenic_then_product_then_rule(http_mock) -> None:
    service = build_fliggy_ticket_service(http_mock)
    result = service.search_tickets(
        TicketSearchRequest(
            scenic_keyword="西湖",
            entry_date=date(2026, 9, 1),
            visitor_count=2,
        )
    )

    assert http_mock.methods == [
        "alitrip.ticket.scenic.query",
        "alitrip.ticket.product.query",
        "alitrip.ticket.rule.query",
    ]
    assert http_mock.requests[1]["visitor_count"] is None
    assert result.data_status == "realtime"
```

另测：多个商品全部保留、只选 `entry_date` 对应库存、规则映射、景点无商品跳过后续调用、单商品失败继续处理、全商品失败进入受控失败。

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_service.py -q
```

预期：FAIL，正式适配器或调用顺序尚不存在。

- [ ] **步骤 3：实现适配器**

实现内部接口：

```python
class FliggyTicketService:
    def search_tickets(self, request: TicketSearchRequest) -> TicketSearchResponse:
        """查询已授权景点的门票商品、日期价格/库存和规则。"""
```

实现要求：

1. 统一使用官方 TOP Router HTTPS 地址；
2. 后端固定 `method`、`v=2.0`、JSON、时间戳和签名；
3. `scenic.query` 根据关键词匹配已发布景点商品；
4. `product.query` 只使用适配器得到的 `ali_product_id`、`out_product_id` 或 `item_id`；
5. `rule.query` 只使用商品关联的 `out_rule_id`；
6. 绝不把 `visitor_count` 添加到飞猪请求；
7. 每次查询重新请求日期价格/库存，不读取实时字段缓存；
8. 只映射白名单字段，丢弃原始响应、签名、session、订单和个人信息；
9. `stock = 0`、缺失和异常分别保留其状态；
10. 上游错误映射为受控异常，日志不记录敏感字段。

- [ ] **步骤 4：运行服务测试确认通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_service.py -q
```

预期：PASS，且 Mock 确认调用顺序、固定地址和字段白名单正确。

- [ ] **步骤 5：提交真实服务**

```powershell
git add backend/app/services/fliggy.py backend/tests/test_fliggy_service.py
git commit -m "feat: 接入飞猪门票只读查询"
```

### 任务 7：接通 API 并安全渲染门票结果

**文件：**
- 修改：`backend/app/api/fliggy.py`
- 修改：`backend/app/main.py`
- 修改：`frontend/app.js`
- 修改：`frontend/styles.css`
- 测试：`backend/tests/test_fliggy_api.py`
- 测试：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：编写结果 API 失败测试**

```python
def test_ticket_search_returns_all_products_and_realtime_metadata(client: TestClient) -> None:
    response = client.post("/api/fliggy/tickets/search", json=VALID_TICKET_REQUEST)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["tickets"]) == 2
    assert payload["source_name"] == "飞猪"
    assert payload["data_status"] == "realtime"
    assert payload["visitor_count"] == 2
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_api.py -q
```

预期：FAIL，查询路由仍为关闭态。

- [ ] **步骤 3：按开关组装真实服务**

仅当 `FLIGGY_ENABLED=true`、全部凭据/授权配置有效且适配器构造成功时，向 `app.state.fliggy_ticket_service` 注入真实服务；否则保持关闭服务。API 捕获已分类的供应商异常并返回统一 `503`，不回显原始响应。

- [ ] **步骤 4：实现前端结果渲染**

实现 `renderTicketResults(payload)`：

- 使用 `createElement`、`textContent`、`replaceChildren`；
- 显示全部商品卡片；
- 价格显示精确值、币种和单位转换后的文案；
- `stock > 0` 显示库存，`stock = 0` 显示“库存为 0”，缺失/异常显示对应不可用文案；
- 图片只有 `image_display_allowed=true` 且 URL 通过协议校验时才渲染；
- 展示票种、场次/区域、入园地址、换票方式、退改、游客信息和限购规则；
- 不显示预订、购买、支付或跳转按钮；
- 查询失败前先清空结果，显示重试和官方核验提示。

- [ ] **步骤 5：运行 API、前端和全量测试**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_api.py backend/tests/test_frontend_assets.py -q
python -m pytest -c backend/pytest.ini backend/tests -q
node --check frontend/app.js
git diff --check
```

预期：全部 PASS。

- [ ] **步骤 6：执行沙箱契约验收**

使用受控测试凭据验证三条接口的签名、`session`、字段、金额单位、库存状态、错误码和限流；不得将真实密钥或完整原始响应写入日志。验收结果写回登记表。

- [ ] **步骤 7：提交页面和 API 接通**

```powershell
git add backend/app/api/fliggy.py backend/app/main.py frontend/app.js frontend/styles.css backend/tests/test_fliggy_api.py backend/tests/test_frontend_assets.py
git commit -m "feat: 展示飞猪门票查询结果"
```

### 任务 8：完成治理文档和发布门禁

**文件：**
- 修改：`README.md`
- 修改：`docs/项目宪法.md`
- 修改：`docs/superpowers/specs/2026-08-25-fliggy-ticket-query-design.md`
- 修改：`docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md`
- 测试：`backend/tests/test_docs.py`

- [ ] **步骤 1：编写治理文档失败测试**

断言文档同时说明：

```python
def test_governance_docs_limit_ticket_feature_to_read_only(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    constitution = (repo_root / "docs/项目宪法.md").read_text(encoding="utf-8")

    assert "门票查询" in readme
    assert "不创建订单" in readme
    assert "不处理支付" in readme
    assert "授权" in constitution
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
```

预期：FAIL，治理文档尚未纳入门票查询受控例外。

- [ ] **步骤 3：更新治理文档**

README 和项目宪法只允许以下受控例外：飞猪书面授权、只读、白名单字段、来源可追溯、服务可关闭、无订单/支付/游客身份收集。所有其他 OTA 交易、订单、支付、退款和未授权实时字段继续禁止。

- [ ] **步骤 4：执行最终验证**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
python -m pytest -c backend/pytest.ini backend/tests -q
node --check frontend/app.js
git diff --check
git status --short
```

预期：所有已执行测试通过；`git status --short` 仅包含本计划预期文件或明确的用户原有变更。

- [ ] **步骤 5：提交治理文档**

```powershell
git add README.md docs/项目宪法.md docs/superpowers/specs/2026-08-25-fliggy-ticket-query-design.md docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md backend/tests/test_docs.py
git commit -m "docs: 纳入门票查询治理边界"
```

---

## 计划自检

### 规格覆盖度

- 页面改名和独立表单：任务 3。
- 景点关键词、入园日期、游客人数：任务 1 和任务 3。
- 游客人数不发送给飞猪：任务 1、任务 6、任务 7。
- 景点 → 商品 → 规则调用链：任务 6。
- 多商品全部展示：任务 6 和任务 7。
- 指定日期价格/库存、库存 0/缺失/异常：任务 6 和任务 7。
- 图片授权开关：任务 7。
- 会话隐私同意、不收集身份信息：任务 3 和任务 7。
- 无预订按钮、无订单/支付：任务 3、任务 7、任务 8。
- 无结果和分项降级：任务 6 和任务 7。
- 默认关闭、固定 HTTPS、密钥保护、治理和回滚：任务 2、任务 6、任务 8。

### 占位符扫描

计划不假设飞猪尚未确认的端点、认证细节、渠道资格或展示许可。阶段 B 的启动门槛明确要求先填写登记表和完成授权评审；代码步骤只使用已在任务 1 和任务 2 中定义的模型与服务名称。

### 类型一致性

- 请求模型统一为 `TicketSearchRequest`；
- 服务统一使用 `search_tickets(request)`；
- 状态模型统一为 `FliggyServiceStatus`；
- 前端视图统一使用 `ticket` / `view-ticket`；
- 服务状态字段统一为 `available`、`message`；
- 响应元数据统一使用 `source_name`、`retrieved_at`、`data_status`、`visitor_count` 和 `tickets`。
