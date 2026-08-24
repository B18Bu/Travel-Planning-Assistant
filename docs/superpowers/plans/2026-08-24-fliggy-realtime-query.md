# 飞猪实时车票与酒店查询实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在既有工作台中增加受控的“车票查询”“酒店查询”入口和默认关闭态；待取得飞猪正式 API 合同后，以独立适配器接入飞猪授权的实时查询数据。

**架构：** 前端通过既有 `showView()` 新增两个独立页面，先调用后端状态接口决定是否可查询。后端以 Pydantic 数据合同、`/api/fliggy/*` 路由和飞猪服务接口隔离供应商细节；默认使用未配置实现，所有真实访问必须由服务端开关、固定 HTTPS 地址和正式字段映射控制。既有行程规划与知识检索 API 不修改。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、pytest、原生 HTML/CSS/JavaScript、既有 `fetch` 与安全 DOM API。

**设计依据：**

- [飞猪实时车票与酒店查询设计](../specs/2026-08-24-fliggy-realtime-query-design.md)
- [飞猪 API 接入资料登记表](../specs/2026-08-24-fliggy-api-integration-registry.md)

---

## 实施前提与阶段划分

本计划严禁猜测飞猪 API。实施分为两个明确阶段：

1. **阶段 A：当前可实施。** 完成前端入口、后端状态接口、输入合同、默认关闭态、隐私同意和自动化测试。此阶段不含真实飞猪请求、模拟实时结果或任何交易字段。
2. **阶段 B：资料齐备后实施。** 仅在《飞猪 API 接入资料登记表》的“接入验收清单”全部完成，并经过安全、合规和发布评审后，依据正式 API 文档完成真实适配器、字段映射、错误处理及沙箱契约测试。

阶段 A 可独立上线为“服务筹备中”状态。阶段 B 未满足前置条件时不得启动。

## 文件结构

### 阶段 A：默认关闭态

| 文件 | 变更职责 |
| --- | --- |
| `backend/app/models/fliggy.py` | 新增车票、酒店输入合同和非敏感服务状态合同。 |
| `backend/app/services/fliggy.py` | 定义只读查询服务协议和默认未配置实现。 |
| `backend/app/api/fliggy.py` | 提供受控状态接口；预留查询路由但在关闭态统一返回 `503`。 |
| `backend/app/config.py` | 新增默认关闭的非敏感飞猪功能开关及其验证。 |
| `backend/app/main.py` | 注册飞猪 API 路由。 |
| `frontend/index.html` | 增加两个导航项、两个独立查询页与隐私同意弹窗。 |
| `frontend/app.js` | 拉取服务状态、维护会话同意、校验表单、渲染未配置态与受控失败态。 |
| `frontend/styles.css` | 新增查询表单、状态说明、结果容器和窄屏规则。 |
| `backend/tests/test_fliggy_models.py` | 验证两个请求合同的业务边界。 |
| `backend/tests/test_fliggy_api.py` | 验证默认关闭态、输入拒绝、无外部访问及信息不泄露。 |
| `backend/tests/test_frontend_assets.py` | 增加导航、状态接口、同意流程和安全渲染静态约束。 |
| `README.md` | 说明功能筹备状态、无真实查询/订单/支付的边界和后续资料前置条件。 |

### 阶段 B：正式飞猪授权接入

| 文件 | 变更职责 |
| --- | --- |
| `backend/app/config.py` | 根据正式文档增加凭据名称、固定基础 URL、超时、限流与开关；真实值仅从部署环境获取。 |
| `backend/app/services/fliggy.py` | 实现固定端点、认证/签名、字段白名单映射、受控错误分类与只读 HTTP 请求。 |
| `backend/app/models/fliggy.py` | 将飞猪已授权的展示字段固化为严格响应模型，不保留自由字典。 |
| `backend/app/api/fliggy.py` | 将关闭态查询路由接到真实服务，并仅返回规范化合同。 |
| `backend/tests/test_fliggy_service.py` | 按飞猪沙箱/官方样例验证请求、签名、字段映射、错误和无结果。 |
| `backend/tests/test_fliggy_api.py` | 验证 API 合同、状态码、酒店价格排序、来源时间和错误脱敏。 |
| `frontend/app.js` | 根据已授权字段渲染火车、航班、酒店列表和重试按钮。 |
| `frontend/styles.css` | 增加真实结果卡片样式，不添加订单或跳转操作。 |
| `README.md`、`docs/项目宪法.md` | 将原 OTA 禁止条款变更为“仅飞猪授权只读查询的受控例外”，同步说明合规边界。 |

---

## 阶段 A：默认关闭态

### 任务 1：定义飞猪查询的最小输入与状态模型

**文件：**
- 创建：`backend/app/models/fliggy.py`
- 测试：`backend/tests/test_fliggy_models.py`

- [ ] **步骤 1：编写车票查询合同的失败测试**

```python
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.models.fliggy import TicketSearchRequest


def test_ticket_search_rejects_past_date() -> None:
    with pytest.raises(ValidationError):
        TicketSearchRequest(
            origin="北京",
            destination="上海",
            departure_date=date.today() - timedelta(days=1),
            passenger_count=1,
            transport_type="all",
        )


def test_ticket_search_rejects_unknown_transport_type() -> None:
    with pytest.raises(ValidationError):
        TicketSearchRequest(
            origin="北京",
            destination="上海",
            departure_date=date.today(),
            passenger_count=1,
            transport_type="bus",
        )
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_models.py -q
```

预期：失败，提示 `ModuleNotFoundError: No module named 'app.models.fliggy'`。

- [ ] **步骤 3：补充酒店查询合同的失败测试**

```python
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.models.fliggy import HotelSearchRequest


def test_hotel_search_requires_check_out_after_check_in() -> None:
    today = date.today()
    with pytest.raises(ValidationError):
        HotelSearchRequest(
            destination="杭州",
            check_in_date=today,
            check_out_date=today,
            guest_count=2,
        )


def test_hotel_search_rejects_guest_count_above_twenty() -> None:
    with pytest.raises(ValidationError):
        HotelSearchRequest(
            destination="杭州",
            check_in_date=date.today(),
            check_out_date=date.today() + timedelta(days=1),
            guest_count=21,
        )
```

- [ ] **步骤 4：实现最小严格模型**

在 `backend/app/models/fliggy.py` 创建以下模型，风格与 `backend/app/models/travel.py` 一致：

```python
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TicketSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    origin: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=100)
    departure_date: date
    passenger_count: int = Field(ge=1, le=20)
    transport_type: Literal["all", "train", "flight"] = "all"

    @field_validator("departure_date")
    @classmethod
    def departure_date_must_not_be_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("出发日期不得早于今天")
        return value


class HotelSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    destination: str = Field(min_length=1, max_length=100)
    check_in_date: date
    check_out_date: date
    guest_count: int = Field(ge=1, le=20)

    @field_validator("check_in_date")
    @classmethod
    def check_in_date_must_not_be_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("入住日期不得早于今天")
        return value

    @model_validator(mode="after")
    def check_out_must_follow_check_in(self) -> "HotelSearchRequest":
        if self.check_out_date <= self.check_in_date:
            raise ValueError("离店日期必须晚于入住日期")
        return self


class FliggyServiceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    message: str
```

- [ ] **步骤 5：运行模型测试确认通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_models.py -q
```

预期：PASS。

- [ ] **步骤 6：提交模型与测试**

```powershell
git add backend/app/models/fliggy.py backend/tests/test_fliggy_models.py
git commit -m "feat: 定义飞猪查询输入合同"
```

### 任务 2：实现默认关闭的服务状态与 API

**文件：**
- 创建：`backend/app/services/fliggy.py`
- 创建：`backend/app/api/fliggy.py`
- 修改：`backend/app/config.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_fliggy_api.py`

- [ ] **步骤 1：编写默认关闭态的失败测试**

复用 `backend/tests/conftest.py` 的 TestClient fixture 组装模式，写入：

```python
from fastapi.testclient import TestClient


def test_fliggy_status_is_unavailable_by_default(client: TestClient) -> None:
    response = client.get("/api/fliggy/status")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "message": "飞猪实时查询服务尚未配置",
    }


def test_closed_fliggy_ticket_search_returns_controlled_503(client: TestClient) -> None:
    response = client.post(
        "/api/fliggy/tickets/search",
        json={
            "origin": "北京",
            "destination": "上海",
            "departure_date": "2099-01-01",
            "passenger_count": 1,
            "transport_type": "all",
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "飞猪实时查询服务尚未配置"}
```

- [ ] **步骤 2：运行 API 测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_api.py -q
```

预期：失败，提示路由不存在或返回 `404`。

- [ ] **步骤 3：为 Settings 增加默认关闭开关**

在 `backend/app/config.py` 的 `Settings` 中添加：

```python
fliggy_enabled: bool = False
```

不要在本阶段新增真实 URL、App ID、密钥或签名字段；这些字段必须等待正式文档填写登记表后再确定。

- [ ] **步骤 4：实现未配置服务**

在 `backend/app/services/fliggy.py` 创建：

```python
from app.models.fliggy import FliggyServiceStatus


class FliggyNotConfiguredError(RuntimeError):
    """飞猪实时查询功能未启用或尚未完成配置。"""


class DisabledFliggyService:
    """默认关闭态，不执行任何外部网络请求。"""

    def status(self) -> FliggyServiceStatus:
        return FliggyServiceStatus(
            available=False,
            message="飞猪实时查询服务尚未配置",
        )

    def search_tickets(self, request) -> None:
        raise FliggyNotConfiguredError

    def search_hotels(self, request) -> None:
        raise FliggyNotConfiguredError
```

- [ ] **步骤 5：实现受控 API 路由并注册**

在 `backend/app/api/fliggy.py` 创建 `APIRouter(prefix="/api/fliggy", tags=["fliggy"])`，实现：

```python
@router.get("/status", response_model=FliggyServiceStatus)
async def get_fliggy_status(request: Request) -> FliggyServiceStatus:
    return request.app.state.fliggy_service.status()


@router.post("/tickets/search")
async def search_tickets(payload: TicketSearchRequest, request: Request):
    raise HTTPException(status_code=503, detail="飞猪实时查询服务尚未配置")


@router.post("/hotels/search")
async def search_hotels(payload: HotelSearchRequest, request: Request):
    raise HTTPException(status_code=503, detail="飞猪实时查询服务尚未配置")
```

在 `backend/app/main.py`：

1. 导入 `fliggy_router` 和 `DisabledFliggyService`；
2. 在 `create_app()` 中设置 `app.state.fliggy_service = DisabledFliggyService()`；
3. 使用 `app.include_router(fliggy_router)` 注册路由，放在静态文件挂载之前。

本阶段即使 `fliggy_enabled=true` 也必须保持关闭，避免在没有正式供应商合同的情况下意外开放请求。

- [ ] **步骤 6：运行 API 测试确认通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_api.py -q
```

预期：PASS，且测试过程中没有任何外部 HTTP 请求。

- [ ] **步骤 7：提交关闭态 API**

```powershell
git add backend/app/config.py backend/app/services/fliggy.py backend/app/api/fliggy.py backend/app/main.py backend/tests/test_fliggy_api.py
git commit -m "feat: 添加飞猪查询关闭态接口"
```

### 任务 3：实现两个独立页面与未配置态

**文件：**
- 修改：`frontend/index.html`
- 修改：`frontend/app.js`
- 修改：`frontend/styles.css`
- 测试：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：增加前端静态约束测试**

在 `backend/tests/test_frontend_assets.py` 中添加断言，验证：

```python
def test_frontend_contains_closed_fliggy_views(frontend_dir: Path) -> None:
    index = (frontend_dir / "index.html").read_text(encoding="utf-8")
    script = (frontend_dir / "app.js").read_text(encoding="utf-8")

    assert 'id="nav-ticket"' in index
    assert 'id="nav-hotel"' in index
    assert 'id="view-ticket"' in index
    assert 'id="view-hotel"' in index
    assert '"/api/fliggy/status"' in script
    assert "sessionStorage" in script
    assert "window.showView = showView" in script
```

- [ ] **步骤 2：运行前端测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：失败，缺少新增导航或状态接口引用。

- [ ] **步骤 3：扩展 `index.html` 的导航、视图和弹窗**

在现有“功能”区、`nav-guide` 后加入：

```html
<button class="side-nav" id="nav-ticket" onclick="showView('ticket')"><span>🚆</span> 车票查询</button>
<button class="side-nav" id="nav-hotel" onclick="showView('hotel')"><span>🏨</span> 酒店查询</button>
```

在 `view-guide` 后、`view-task` 前增加两个 `.view`：

```html
<section id="view-ticket" class="view">
  <div class="feature-page fliggy-page">
    <div class="feature-page-head">
      <div>Fliggy Ticket Search</div>
      <h2>车票查询</h2>
      <p>查询火车票和航班实时信息。当前仅提供查询，不创建订单或处理支付。</p>
    </div>
    <p id="ticket-service-status" class="fliggy-status" role="status" aria-live="polite"></p>
    <form id="ticket-form" class="fliggy-form">
      <!-- origin、destination、departure_date、passenger_count、transport_type 五项字段 -->
      <button id="ticket-submit" class="btn-primary" type="submit">查询车票</button>
    </form>
    <section id="ticket-results" class="fliggy-results" hidden></section>
  </div>
</section>

<section id="view-hotel" class="view">
  <div class="feature-page fliggy-page">
    <div class="feature-page-head">
      <div>Fliggy Hotel Search</div>
      <h2>酒店查询</h2>
      <p>查询酒店实时信息。当前仅提供查询，不创建订单或处理支付。</p>
    </div>
    <p id="hotel-service-status" class="fliggy-status" role="status" aria-live="polite"></p>
    <form id="hotel-form" class="fliggy-form">
      <!-- destination、check_in_date、check_out_date、guest_count 四项字段 -->
      <button id="hotel-submit" class="btn-primary" type="submit">查询酒店</button>
    </form>
    <section id="hotel-results" class="fliggy-results" hidden></section>
  </div>
</section>
```

在现有模态框后新增“首次使用飞猪实时查询”同意弹窗。弹窗必须有同意和拒绝按钮、可访问标签，且不展示输入值或密钥。

- [ ] **步骤 4：实现前端状态、同意与未配置行为**

在 `frontend/app.js` 中：

1. 缓存新导航、表单、按钮、状态和结果元素；
2. 新增 `let fliggyStatus = { available: false, message: "飞猪实时查询服务尚未配置" };`；
3. 在 `showView("ticket")` 或 `showView("hotel")` 时调用 `loadFliggyStatus()`；
4. `loadFliggyStatus()` 请求 `/api/fliggy/status`，只使用 `available`、`message` 更新文字和按钮 `disabled` 状态；请求失败时视为 `available=false`，文案为“飞猪实时查询服务暂不可用”；
5. 使用常量 `const FLIGGY_CONSENT_KEY = "fliggy-query-consent";`，通过包裹 `try/catch` 的 `sessionStorage.getItem/setItem` 保存会话同意；
6. 提交表单时，先检查服务可用，再调用 `requestFliggyConsent(onApproved)`；拒绝时不调用 `fetch` 查询接口；
7. 关闭态下结果容器必须 `replaceChildren()` 后保持 `hidden=true`，避免残留旧结果；
8. 当前阶段 `submitTicketSearch` 与 `submitHotelSearch` 不应因关闭态向查询端点发送请求。

同意弹窗核心文案：

> 首次查询将向飞猪发送完成本次查询所必需的地点、日期、人数及交通类型信息，用于获取实时查询结果。本系统不代为下单或支付。是否同意？

- [ ] **步骤 5：添加最小样式**

在 `frontend/styles.css` 新增并复用现有设计令牌：

```css
.fliggy-page { max-width: 960px; }
.fliggy-form { display: grid; gap: 16px; }
.fliggy-status { min-height: 1.5em; }
.fliggy-results { margin-top: 24px; }
```

在既有窄屏媒体查询中，确保 `.fliggy-form` 单列、输入和按钮宽度不溢出。不要改动既有行程、攻略、文档库和数据看板的布局规则。

- [ ] **步骤 6：运行静态与前端测试确认通过**

运行：

```powershell
node --check frontend/app.js
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
git diff --check
```

预期：三条命令均成功。

- [ ] **步骤 7：提交前端关闭态**

```powershell
git add frontend/index.html frontend/app.js frontend/styles.css backend/tests/test_frontend_assets.py
git commit -m "feat: 添加飞猪查询筹备页面"
```

### 任务 4：补齐关闭态运行文档与全量回归

**文件：**
- 修改：`README.md`
- 修改：`docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md`
- 测试：`backend/tests/test_docs.py`

- [ ] **步骤 1：为文档边界编写失败测试**

在 `backend/tests/test_docs.py` 增加：

```python
def test_readme_marks_fliggy_as_disabled_pending_authorization(repo_root: Path) -> None:
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "飞猪" in readme
    assert "默认关闭" in readme
    assert "不创建订单" in readme
```

- [ ] **步骤 2：运行文档测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
```

预期：失败，因为 README 尚未定义飞猪筹备状态。

- [ ] **步骤 3：更新 README 与登记表状态**

在 README 的“范围与非目标”及“配置”附近增加“飞猪实时查询（筹备中）”说明：

- 新增入口当前默认关闭，未接入飞猪网络请求；
- 不创建订单、不处理支付、不收集身份或支付信息；
- 真实启用前须完成登记表内的授权、字段展示、沙箱、隐私和安全验收；
- 不展示模拟、缓存或模型生成的实时交易信息。

在 `docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md` 的顶部状态行改为：

```markdown
**状态：** 接入资料待补全；项目默认关闭态可实施，真实飞猪请求不得启用
```

- [ ] **步骤 4：运行文档测试和全量回归**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
python -m pytest -c backend/pytest.ini backend/tests -q
node --check frontend/app.js
git diff --check
```

预期：全部 PASS；如任何测试失败，记录失败名称和输出，不得声明全量通过。

- [ ] **步骤 5：提交文档与关闭态完成结果**

```powershell
git add README.md docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md backend/tests/test_docs.py
git commit -m "docs: 说明飞猪查询筹备边界"
```

---

## 阶段 B：飞猪正式 API 合同到位后

> **启动门槛：** 未获得正式飞猪文档与凭据时，不得执行本阶段的任何编码步骤。开始前必须先补齐 `docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md`，并将具体端点、字段、认证与限流规则反映到本计划的后续修订版本。

### 任务 5：根据正式合同锁定配置与响应模型

**文件：**
- 修改：`backend/app/config.py`
- 修改：`backend/app/models/fliggy.py`
- 测试：`backend/tests/test_config.py`
- 测试：`backend/tests/test_fliggy_models.py`

- [ ] **步骤 1：将正式 API 文档资料填写到登记表**

填写以下必填项后再修改代码：基础 URL、端点、认证/签名、请求参数、响应字段、金额单位、状态枚举、错误码、限流、缓存许可、展示许可和沙箱样例。将资料链接、章节号或文档版本写入字段映射表的“依据链接/章节”。

- [ ] **步骤 2：编写配置与字段映射失败测试**

测试必须使用正式文档的无密钥样例，断言：

```python
def test_fliggy_base_url_rejects_unapproved_host() -> None:
    with pytest.raises(ValidationError):
        Settings(fliggy_base_url="https://untrusted.example")
```

并在 `test_fliggy_models.py` 使用正式样例断言金额单位、可订状态枚举和禁止未知字段。

- [ ] **步骤 3：实现固定 URL 和严格响应模型**

依据已填写合同：

1. 在 `Settings` 新增不含真实值的配置字段；
2. 使用 `field_validator` 将基础 URL 限制为书面授权的 HTTPS 地址；
3. 用明确 Pydantic 模型定义火车、航班、酒店及房型的**已授权展示字段**；
4. 所有金额字段采用精确整数最小货币单位或文档规定的安全类型，并明确 `currency` 与单位；
5. 不创建 `dict[str, Any]` 原始响应出口，不接收或返回身份、支付、订单、Cookie、Token 和签名字段。

- [ ] **步骤 4：运行配置与模型测试确认通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_config.py backend/tests/test_fliggy_models.py -q
```

预期：PASS。

- [ ] **步骤 5：提交合同实现**

```powershell
git add backend/app/config.py backend/app/models/fliggy.py backend/tests/test_config.py backend/tests/test_fliggy_models.py docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md
git commit -m "feat: 固化飞猪授权查询合同"
```

### 任务 6：实现并验证飞猪只读服务适配器

**文件：**
- 修改：`backend/app/services/fliggy.py`
- 测试：`backend/tests/test_fliggy_service.py`

- [ ] **步骤 1：用官方沙箱样例编写失败的服务测试**

测试至少覆盖：

1. 请求只发送已授权的最小字段；
2. 使用固定的 HTTPS 主机、方法和端点；
3. 认证/签名与官方样例一致，但测试不记录真实密钥；
4. 成功响应被映射到严格领域模型；
5. 上游原始字段不出现在领域模型；
6. 超时、`429`、`5xx`、鉴权失败、业务错误与无结果按照登记表映射。

使用项目现有的 HTTP Mock 方式；不在单元测试中访问真实飞猪网络。

- [ ] **步骤 2：运行服务测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_service.py -q
```

预期：失败，正式适配器或映射函数尚不存在。

- [ ] **步骤 3：实现正式只读适配器**

依据登记表中的准确值，实现：

```python
class FliggyService:
    def search_tickets(self, request: TicketSearchRequest) -> TicketSearchResponse:
        """调用飞猪已授权的火车/航班只读查询端点并映射为领域合同。"""

    def search_hotels(self, request: HotelSearchRequest) -> HotelSearchResponse:
        """调用飞猪已授权的酒店只读查询端点并按价格升序返回领域合同。"""
```

实现必须满足：

- URL、HTTP 方法、参数、请求头和签名均从正式合同固定生成；
- 只使用允许的 HTTP 客户端、超时、重试和熔断机制；
- 每次主动查询直接访问上游，不读写实时交易缓存；
- 规范化结果均设置 `source_name="飞猪"`、`retrieved_at` 和 `data_status="realtime"`；
- 只对登记表允许的可重试错误进行有限重试；
- 不记录原始响应、敏感请求字段或认证信息；
- 酒店结果仅在价格可比较且货币/单位一致时排序，否则按合同定义的无价格语义处理。

- [ ] **步骤 4：运行服务测试确认通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_service.py -q
```

预期：PASS，且 Mock 断言确认没有未授权主机、端点或字段。

- [ ] **步骤 5：提交服务适配器**

```powershell
git add backend/app/services/fliggy.py backend/tests/test_fliggy_service.py
git commit -m "feat: 接入飞猪只读查询服务"
```

### 任务 7：启用 API、渲染授权结果并做契约回归

**文件：**
- 修改：`backend/app/api/fliggy.py`
- 修改：`backend/app/main.py`
- 修改：`frontend/app.js`
- 修改：`frontend/styles.css`
- 修改：`backend/tests/test_fliggy_api.py`
- 修改：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：编写 API 与前端结果处理失败测试**

使用正式领域响应 fixture，断言：

```python
def test_hotel_search_returns_prices_in_ascending_order(client: TestClient) -> None:
    response = client.post("/api/fliggy/hotels/search", json=VALID_HOTEL_REQUEST)

    assert response.status_code == 200
    amounts = [item["price_amount"] for item in response.json()["hotels"]]
    assert amounts == sorted(amounts)
    assert response.json()["data_status"] == "realtime"
    assert response.json()["source_name"] == "飞猪"
```

前端静态断言必须验证：火车、航班分区容器存在；酒店展示中不含下单、支付、订单或跳转 URL 的行为。

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_api.py backend/tests/test_frontend_assets.py -q
```

预期：失败，关闭态尚未替换为正式结果合同和渲染逻辑。

- [ ] **步骤 3：仅在通过启用门槛时组装正式服务**

在 `backend/app/main.py` 或 `backend/app/dependencies.py` 中：

1. 仅当 `FLIGGY_ENABLED=true`、所有必须配置已通过校验且正式服务可创建时，注入 `FliggyService`；
2. 否则始终注入 `DisabledFliggyService`；
3. `GET /api/fliggy/status` 仅据此返回可用状态，且不泄露原因；
4. 查询 API 调用注入的服务，将受控供应商异常统一映射为既定 `503` 文案。

- [ ] **步骤 4：实现安全结果渲染**

在 `frontend/app.js` 中实现：

- `renderTicketResults(payload)`：使用 `createElement` / `textContent` 创建火车票和航班分区；
- `renderHotelResults(payload)`：使用同样方式创建按后端排序的酒店卡片；
- 每个结果和顶层区域显示来源、查询时间、实时状态与核验提示；
- 失败时先 `replaceChildren()` 清空结果，再渲染受控错误、重试按钮与官方核验提示；
- 不用 `innerHTML` 写入飞猪字段；
- 不添加订单、支付、退改、外部跳转或身份信息输入。

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

- [ ] **步骤 6：执行飞猪沙箱契约验证**

以部署环境中的测试凭据执行飞猪书面验收用例。记录调用时间、端点版本、返回状态、字段映射和限流结果；日志不得输出真实凭据或完整原始响应。任何字段、金额单位、认证或展示许可偏差都必须回到登记表和模型修正，不能通过前端容错掩盖。

- [ ] **步骤 7：提交正式接入**

```powershell
git add backend/app/api/fliggy.py backend/app/main.py frontend/app.js frontend/styles.css backend/tests/test_fliggy_api.py backend/tests/test_frontend_assets.py
git commit -m "feat: 启用飞猪实时查询页面"
```

### 任务 8：更新治理文档并完成发布门禁

**文件：**
- 修改：`README.md`
- 修改：`docs/项目宪法.md`
- 修改：`docs/superpowers/specs/2026-08-24-fliggy-realtime-query-design.md`
- 修改：`docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md`
- 测试：`backend/tests/test_docs.py`

- [ ] **步骤 1：编写治理边界失败测试**

在 `backend/tests/test_docs.py` 断言项目文档同时包含：

- 仅飞猪书面授权范围内的只读查询；
- 不创建订单、不支付、不退改；
- 价格和库存以查询时刻为准，需官方渠道最终核验；
- 功能开关、可观测、可禁用与可回滚要求。

- [ ] **步骤 2：运行文档测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_docs.py -q
```

预期：失败，旧文档仍将所有 OTA/实时交易字段一概列为禁止。

- [ ] **步骤 3：以受控例外更新文档**

更新 `docs/项目宪法.md` 与 README：原先广义禁止的 OTA/实时交易字段，改为仅允许“飞猪已书面授权、只读、字段白名单、来源可追溯、可关闭”的例外；其余 OTA、订单、支付、退改和未经授权字段保持禁止。

更新两份飞猪规格：填写实际合同版本、启用日期、字段映射依据、沙箱验证结果、责任人及回滚开关位置。

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

预期：测试与检查通过，`git status --short` 仅显示本任务预期且尚未提交的文档/测试变更；若存在其他文件，明确区分且不纳入提交。

- [ ] **步骤 5：提交治理与发布资料**

```powershell
git add README.md docs/项目宪法.md docs/superpowers/specs/2026-08-24-fliggy-realtime-query-design.md docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md backend/tests/test_docs.py
git commit -m "docs: 纳入飞猪授权查询治理"
```

---

## 规格覆盖自检

- 导航、独立查询页、最小表单与不联动行程规划：任务 3。
- 未配置可见且禁用、无模拟实时数据：任务 2 与任务 3。
- 首次会话同意、拒绝不请求：任务 3。
- 车票火车/航班分区、酒店按价格升序：任务 7。
- 实时字段不缓存、失败不显示旧数据：任务 6 与任务 7。
- 无订单、支付、退改、跳转与身份信息：任务 1、任务 3、任务 7、任务 8。
- 飞猪正式文档为真实接入前置条件：阶段划分、任务 5 至任务 8。
- 固定供应商地址、密钥不泄露、字段白名单和受控错误：任务 5 至任务 7。
- 合规、项目宪法修订、开关与回滚：任务 8。

占位符扫描结果：阶段 B 中“依据正式文档”的内容是显式启动门槛，不是接口实现占位；实际端点、字段与签名不得在资料缺失时编造。
