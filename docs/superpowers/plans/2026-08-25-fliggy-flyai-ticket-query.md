# 飞猪 FlyAI 门票只读检索实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在默认关闭和本地 Mock 保留的前提下，增加飞猪 AI 开放平台只读文本检索 provider；安全展示门票文本、来源、时间和状态，不伪造价格、库存或 SKU。

**架构：** 使用 `FLIGGY_TICKET_PROVIDER=disabled|mock|flyai` 选择服务。FlyAI provider 从服务端 `FLYAI_API_KEY` 读取密钥，通过注入的客户端调用官方后端合同，返回 `summary` 文本和固定警告；不调用 TOP API，不从自然语言提取结构化交易字段。前端沿用门票表单和紧凑卡片，使用安全 DOM API。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、pytest、HTTPX、原生 HTML/CSS/JavaScript。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `backend/app/config.py`、`backend/.env.example` | provider、FlyAI Key、超时配置。 |
| `backend/app/models/fliggy.py` | `flyai_text` 状态和文本摘要响应合同。 |
| `backend/app/services/fliggy_flyai_client.py` | FlyAI HTTPS 客户端、超时和错误归类；不记录密钥。 |
| `backend/app/services/fliggy.py` | FlyAI 文本服务；保留 Disabled/Mock。 |
| `backend/app/main.py`、`backend/app/api/fliggy.py` | provider 注入和受控 API 错误映射。 |
| `frontend/app.js`、`frontend/index.html`、`frontend/styles.css` | 文本摘要、来源时间、警告的紧凑安全展示。 |
| `backend/tests/test_fliggy_config.py` | 配置边界。 |
| `backend/tests/test_fliggy_models.py` | 响应字段边界。 |
| `backend/tests/test_fliggy_flyai_client.py` | 请求、密钥保护、错误。 |
| `backend/tests/test_fliggy_flyai_service.py` | 文本归一化和禁止伪造字段。 |
| `backend/tests/test_fliggy_api.py` | provider/API 回归。 |
| `backend/tests/test_fliggy_mock_frontend.py` | 前端安全展示静态约束。 |
| `backend/tests/test_docs.py`、`README.md`、API 登记表 | 文档与启用前置条件。 |

## 阶段 A：配置和领域合同

### 任务 1：增加 provider 配置

**文件：** 修改 `backend/app/config.py`、`backend/.env.example`；测试 `backend/tests/test_fliggy_config.py`。

- [ ] **步骤 1：编写失败测试**

```python
from app.config import Settings


def test_provider_defaults_to_disabled() -> None:
    settings = Settings(_env_file=None)
    assert settings.fliggy_ticket_provider == "disabled"
    assert settings.flyai_api_key == ""
    assert settings.flyai_timeout_seconds == 30


def test_provider_rejects_top() -> None:
    Settings(_env_file=None, fliggy_ticket_provider="mock")
    Settings(_env_file=None, fliggy_ticket_provider="flyai")
    try:
        Settings(_env_file=None, fliggy_ticket_provider="top")
    except ValueError:
        return
    raise AssertionError("不应接受 top provider")
```

- [ ] **步骤 2：运行失败测试**：`$env:PYTHONPATH="$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_config.py -q`；预期因字段不存在失败。
- [ ] **步骤 3：实现最少字段**：增加 `fliggy_ticket_provider: Literal["disabled", "mock", "flyai"] = "disabled"`、`flyai_api_key: str = ""`、`flyai_timeout_seconds: int = Field(default=30, gt=0, le=120)`；模板增加 `FLIGGY_TICKET_PROVIDER=disabled`、`FLYAI_API_KEY=`、`FLYAI_TIMEOUT_SECONDS=30`。
- [ ] **步骤 4：运行同一测试**：预期 PASS。
- [ ] **步骤 5：Commit**：`git add backend/app/config.py backend/.env.example backend/tests/test_fliggy_config.py`；`git commit -m "feat: 增加 FlyAI 门票 provider 配置"`。

### 任务 2：扩展文本响应模型

**文件：** 修改 `backend/app/models/fliggy.py`；测试 `backend/tests/test_fliggy_models.py`。

- [ ] **步骤 1：编写失败测试**：构造 `data_status="flyai_text"` 和 `summary`，断言 `tickets == ()`；用 `ValidationError` 断言 `raw_response` 被 `extra="forbid"` 拒绝。
- [ ] **步骤 2：运行失败测试**：目标模型测试；预期状态枚举和 `summary` 不存在。
- [ ] **步骤 3：实现**：将状态扩展为 `Literal["mock", "flyai_text", "realtime", "degraded"]`，增加 `summary: str | None = None`；不修改 `TicketProduct` 价格/库存语义。
- [ ] **步骤 4：运行门票模型全测**：预期 PASS。
- [ ] **步骤 5：Commit**：`git add backend/app/models/fliggy.py backend/tests/test_fliggy_models.py`；`git commit -m "feat: 增加 FlyAI 门票文本响应合同"`。

## 阶段 B：客户端和服务

### 任务 3：实现 FlyAI CLI 客户端

**命令决策：** Quickstart 示例命令 `fliggy-fast-search` 不在当前官方 skill 的正式命令表（`keyword-search`/`ai-search`/`search-flight`/`search-train`/`search-hotel`/`search-poi`/`search-marriott-hotel`/`search-marriott-package`）中，不能当作稳定合同。本任务采用正式命令 **`ai-search --query`**：其响应 `data` 字段为文本字符串，可直接作为 `summary`，符合“不解析价格/库存/SKU”的文本摘要设计；且不需要城市字段（`search-poi` 要求必填 `--city-name`，与现有 `scenic_keyword` 输入不一致）。调用方式采用 CLI 子进程（`asyncio.create_subprocess_exec`），与并行酒店任务 `FlyAIHotelClient` 模式一致；认证由 CLI 通过环境变量 `FLYAI_API_KEY` 管理，后端不猜测 MCP endpoint 和工具 schema。

**文件：** 创建 `backend/app/services/fliggy_flyai_client.py`；测试 `backend/tests/test_fliggy_flyai_client.py`。

- [ ] **步骤 1：编写失败测试**：用注入的 fake runner 验证命令与参数（`ai-search --query <关键词> 门票 ...`）、环境变量注入 `FLYAI_API_KEY`、stdout JSON 的 `data` 文本字段提取与截断；另测超时映射 `FlyAIUpstreamError("TIMEOUT")`、退出码非 0 映射 `CLI_ERROR`、JSON 解析失败或 `data` 非字符串映射 `INVALID_RESPONSE`；断言任何参数和异常信息不含真实 Key。
- [ ] **步骤 2：运行失败测试**：预期客户端类和异常不存在。
- [ ] **步骤 3：实现最少客户端**：定义异步 `FlyAIClient.search(scenic_keyword, entry_date) -> str`；构造只读提示词（含关键词和日期，要求仅返回景点门票信息、不预订不下单不支付、不含身份信息）；使用注入的 runner（默认 `_subprocess_runner` 注入 `FLYAI_API_KEY` 环境变量）；捕获超时、异常、退出码和 JSON 结构错误，统一抛受控 `FlyAIUpstreamError`；只取 JSON `data` 字符串并截断到 8000 字符；绝不记录或返回密钥。
- [ ] **步骤 4：运行客户端测试**：预期 PASS。
- [ ] **步骤 5：Commit**：`git add backend/app/services/fliggy_flyai_client.py backend/tests/test_fliggy_flyai_client.py`；`git commit -m "feat: 增加 FlyAI 门票 CLI 客户端"`。

### 任务 4：实现文本服务

**文件：** 修改 `backend/app/services/fliggy.py`；测试 `backend/tests/test_fliggy_flyai_service.py`。

- [ ] **步骤 1：编写失败测试**：Stub client 返回包含“价格 100 元、库存 20 张”的文本；断言响应为 `flyai_text`、`summary` 原文、`tickets == ()`，并含价格/库存暂不可用警告。
- [ ] **步骤 2：运行失败测试**：预期服务类不存在。
- [ ] **步骤 3：实现**：定义 `FlyAIFliggyTicketService`；通过异步 `search_tickets` 调用 client；返回来源、UTC 时间、摘要和固定警告；空文本抛受控错误；不解析价格、库存、SKU，不填充 `TicketProduct`。
- [ ] **步骤 4：运行服务及既有 Mock 测试**：预期 PASS。
- [ ] **步骤 5：Commit**：`git add backend/app/services/fliggy.py backend/tests/test_fliggy_flyai_service.py`；`git commit -m "feat: 增加 FlyAI 门票文本服务"`。

## 阶段 C：接线和前端

### 任务 5：按 provider 注入并接通 API

**文件：** 修改 `backend/app/main.py`、`backend/app/api/fliggy.py`；测试 `backend/tests/test_fliggy_api.py`。

- [ ] **步骤 1：编写失败测试**：FlyAI provider 有 Key 时状态可用且不包含密钥；无 Key 保持 503；Mock provider 不访问外部。
- [ ] **步骤 2：运行失败测试**：预期应用仍只读取旧 Mock 开关。
- [ ] **步骤 3：实现**：按 `disabled|mock|flyai` 注入；flyai 缺 Key 注入 Disabled；路由正确 await 异步服务；只映射固定中文错误，不回显上游异常。
- [ ] **步骤 4：运行 API 测试**：`python -m pytest -c backend/pytest.ini backend/tests/test_fliggy_api.py -q`；预期 PASS。
- [ ] **步骤 5：Commit**：`git add backend/app/main.py backend/app/api/fliggy.py backend/tests/test_fliggy_api.py`；`git commit -m "feat: 接通 FlyAI 门票查询 provider"`。

### 任务 6：更新前端文本结果

**文件：** 修改 `frontend/app.js`、`frontend/index.html`、`frontend/styles.css`；测试 `backend/tests/test_fliggy_mock_frontend.py`。

- [ ] **步骤 1：编写失败静态测试**：断言脚本包含 `flyai_text`、`summary`、价格/库存不可用文案和 `textContent`，结果渲染区不使用 `innerHTML`。
- [ ] **步骤 2：运行失败测试**：预期缺少 FlyAI 文本展示。
- [ ] **步骤 3：实现**：`renderTicketResults` 在 `flyai_text` 时创建摘要、来源和查询时间节点；固定追加价格/库存不可用警告；使用 `textContent`/`replaceChildren`；同意文案改为 FlyAI 只读查询；不添加交易控件。
- [ ] **步骤 4：运行 `node --check frontend/app.js` 和前端静态测试**：预期 PASS。
- [ ] **步骤 5：Commit**：`git add frontend/app.js frontend/index.html frontend/styles.css backend/tests/test_fliggy_mock_frontend.py`；`git commit -m "feat: 展示 FlyAI 门票文本结果"`。

## 阶段 D：文档与最终验证

### 任务 7：更新登记表和 README

**文件：** 修改 `docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md`、`README.md`；测试 `backend/tests/test_docs.py`。

- [ ] **步骤 1：编写失败文档测试**：断言登记表含 Quickstart、`FLYAI_API_KEY`、`flyai_text`、未确认结构化价格/库存；README 含只读、不创建订单、不处理支付和默认关闭。
- [ ] **步骤 2：运行失败测试**：预期文档缺少 FlyAI 约定。
- [ ] **步骤 3：实现**：登记官方链接、provider、Key 保存/轮换、endpoint 合同确认边界；README 记录 `.env` 示例和严禁提交真实 Key。
- [ ] **步骤 4：运行文档测试**：预期 PASS。
- [ ] **步骤 5：Commit**：`git add docs/superpowers/specs/2026-08-24-fliggy-api-integration-registry.md README.md backend/tests/test_docs.py`；`git commit -m "docs: 登记 FlyAI 门票只读边界"`。

### 任务 8：最终验证与敏感信息门禁

**文件：** 无新增文件。

- [ ] **步骤 1：运行目标测试**：运行配置、模型、FlyAI 客户端、服务、API、Mock 和前端测试；预期全部 PASS，失败时按文件定位，不跳过。
- [ ] **步骤 2：运行全量验证**：`$env:PYTHONPATH="$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -q; node --check frontend/app.js; git diff --check`；记录实际通过数。
- [ ] **步骤 3：检查密钥和范围**：检查 Git 跟踪文件中无真实 Key；用户原有 `.env`、酒店文件和日志不纳入本任务。
- [ ] **步骤 4：Commit**：`git commit -m "test: 验证 FlyAI 门票查询接入"`。

---

## 计划自检

- 默认关闭、Mock 保留：任务 1、5、8。
- FlyAI Key 服务端读取和保护：任务 1、3、5、8。
- 只读文本查询和不执行交易：任务 3、4、6、7。
- 不伪造价格、库存、SKU：任务 2、4、6。
- 来源、时间、`flyai_text`、警告：任务 2、4、6。
- 错误、超时、限流和文档边界：任务 3、5、7、8。
- 计划不猜测生产 endpoint；使用官方后端合同确认后再配置。
- 类型统一：provider 为 `disabled|mock|flyai`，服务方法为 `status`/`search_tickets`，文本状态为 `flyai_text`，响应含 `summary`。
