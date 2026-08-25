# 项目架构可视化 HTML 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 创建一个可离线打开、响应式、主题可切换的项目架构可视化 HTML，展示当前系统架构、核心流程、文档处理链路、熔断判断、状态合同和安全边界。

**架构：** 单个 `docs/project-architecture.html` 自包含页面，使用语义化 HTML 承载说明，使用内联 SVG 绘制图形，使用内联 CSS 实现响应式和主题，使用少量原生 JavaScript 实现目录定位、主题切换和展开说明。页面不修改业务代码，不加载外部资源。

**技术栈：** HTML5、CSS、内联 SVG、原生 JavaScript、浏览器 `localStorage`。

---

## 文件职责

- 创建：`docs/project-architecture.html` —— 项目架构可视化单页，包含所有章节、SVG 图、样式和交互。
- 参考：`README.md` —— 核对模块、流程、熔断参数和安全边界事实。
- 参考：`backend/app/main.py`、`backend/app/orchestration/sequential.py`、`backend/app/services/resilience.py`、`backend/app/services/document_processor.py` —— 核对实现名称与实际数据流。

### 任务 1：核对实现事实并建立页面骨架

**文件：**
- 创建：`docs/project-architecture.html`
- 参考：`README.md`
- 参考：`backend/app/main.py`
- 参考：`backend/app/orchestration/sequential.py`
- 参考：`backend/app/services/resilience.py`
- 参考：`backend/app/services/document_processor.py`

- [ ] **步骤 1：读取关键实现文件并记录页面必须出现的真实模块**

读取上述文件，确认应用入口、API 路由、顺序编排器、缓存/韧性接口和文档处理组件名称；页面只使用实际存在的模块名，并将未实现能力标注为规划项。

- [ ] **步骤 2：创建 HTML5 页面骨架和导航章节**

创建包含以下元素的文件：`<title>智能文旅策划 Agent · 系统架构</title>`、跳过链接、侧栏目录、`main` 主内容区、七个带唯一 `id` 的章节：`overview`、`architecture`、`travel-flow`、`document-flow`、`resilience`、`status-contract`、`security`。

- [ ] **步骤 3：加入项目概览和事实边界内容**

在 `overview` 中写明“只读式行程建议服务”“当前 MVP 不执行预订、支付或交易”，并添加架构层、外部服务、韧性机制、核心接口四个摘要卡片；禁止出现实时指标或虚构可用性数据。

- [ ] **步骤 4：运行基础结构检查确认骨架有效**

运行：`python -c "from pathlib import Path; p=Path('docs/project-architecture.html'); s=p.read_text(encoding='utf-8'); assert '<main' in s and 'overview' in s and 'security' in s; print('HTML skeleton OK')"`

预期输出：`HTML skeleton OK`。

- [ ] **步骤 5：提交页面骨架**

```powershell
git add docs/project-architecture.html
git commit -m "docs: 添加架构可视化页面骨架"
```

### 任务 2：实现总体架构图和旅行规划流程图

**文件：**
- 修改：`docs/project-architecture.html` 的 `architecture`、`travel-flow` 章节

- [ ] **步骤 1：加入总体架构 SVG 和文字图例**

在 `architecture` 章节加入带 `viewBox` 的内联 SVG，按“浏览器 → FastAPI API 层 → SequentialTravelOrchestrator → 五类 Agent → TravelPlanDocument → 前端展示”绘制主链路，并将和风天气、高德地图、Pydantic 合同、缓存/重试/熔断画成依赖或横切节点；SVG 节点必须同时有可读文本，颜色不能作为唯一语义。

- [ ] **步骤 2：加入旅行规划端到端流程 SVG**

在 `travel-flow` 章节绘制“提交表单 → 请求合同校验 → 生成/规范化 request_id 与 trace_id → 天气 → 路线 → 住宿 → 餐饮 → 汇总 → 返回文档 → 前端净化 Markdown”的顺序流程，并用分支节点表达单个 Agent 异常转为受控 `failed`、其余信息继续汇总。

- [ ] **步骤 3：补充流程关键约束说明**

在 SVG 下方说明 `itinerary` 是唯一机器事实载体，`markdown` 是表现层；顶层状态由专业 Agent 状态汇总决定；前端只调用同源相对路径且不接触供应商密钥。

- [ ] **步骤 4：用文本检查确认架构图节点齐全**

运行：`python -c "from pathlib import Path; s=Path('docs/project-architecture.html').read_text(encoding='utf-8'); required=['FastAPI','SequentialTravelOrchestrator','天气 Agent','路线 Agent','住宿 Agent','餐饮 Agent','汇总 Agent','TravelPlanDocument','request_id','trace_id']; missing=[x for x in required if x not in s]; assert not missing, missing; print('Architecture labels OK')"`

预期输出：`Architecture labels OK`。

- [ ] **步骤 5：提交架构和主流程图**

```powershell
git add docs/project-architecture.html
git commit -m "docs: 增加系统架构与旅行流程图"
```

### 任务 3：实现文档处理流程和熔断状态图

**文件：**
- 修改：`docs/project-architecture.html` 的 `document-flow`、`resilience` 章节

- [ ] **步骤 1：加入文档处理流程 SVG**

绘制“PDF/DOCX → MIME/后缀/文件签名校验 → 202 接收或 422 拒绝 → 本地 PyMuPDF / DOCX 文本提取 → 分块 → BGE Embedding → Chroma 存储 → 关键词/向量检索 → 受控知识润色”的流程；明确 MinerU/Qwen-VL 为保留配置或后续受控能力，不能画成当前默认调用链。

- [ ] **步骤 2：加入缓存、重试、熔断和恢复 SVG**

绘制以下判断顺序：缓存命中则返回 `cached`；未命中访问上游；连接错误、超时、429、5xx 才允许最多 3 次指数退避；业务参数错误不重试；连续失败达到阈值后进入打开状态；打开期间拒绝上游调用；窗口结束允许探测；探测成功恢复，探测失败继续降级。

- [ ] **步骤 3：补充熔断参数和 MVP 限制**

明确默认 `CIRCUIT_BREAKER_FAILURE_THRESHOLD=3`、`CIRCUIT_BREAKER_OPEN_SECONDS=60`，并注明这是进程内熔断，不是分布式流量治理；Agent 异常转换为受控 `failed`，汇总器保留其他可用信息。

- [ ] **步骤 4：用文本检查确认韧性与文档标签齐全**

运行：`python -c "from pathlib import Path; s=Path('docs/project-architecture.html').read_text(encoding='utf-8'); required=['PyMuPDF','BGE','Chroma','MinerU','Qwen-VL','cached','429','5xx','指数退避','熔断','探测','CIRCUIT_BREAKER_FAILURE_THRESHOLD','CIRCUIT_BREAKER_OPEN_SECONDS']; missing=[x for x in required if x not in s]; assert not missing, missing; print('Resilience labels OK')"`

预期输出：`Resilience labels OK`。

- [ ] **步骤 5：提交文档和韧性图**

```powershell
git add docs/project-architecture.html
git commit -m "docs: 增加文档处理与熔断流程图"
```

### 任务 4：实现状态、安全、主题和响应式交互

**文件：**
- 修改：`docs/project-architecture.html` 的 `status-contract`、`security` 章节及内联样式/脚本

- [ ] **步骤 1：加入状态合同判断矩阵**

用 HTML 表格表达 `success`、`partial`、`degraded`、`failed` 的 data、missing_fields、error 要求，并说明顶层文档使用 `success`、`degraded` 或 `failed`；禁止把 `partial` 直接当作顶层状态。

- [ ] **步骤 2：加入安全边界和当前限制卡片**

说明后端密钥、固定供应商域名、同源相对路径、原始响应不透传、交易字段禁入、Markdown 经 `DOMPurify` 净化；另列认证、限流、租户隔离、集中式密钥、审计、监控和告警等当前未实现生产化能力。

- [ ] **步骤 3：实现主题切换和侧栏定位脚本**

使用原生 JavaScript：主题按钮在 `document.documentElement.dataset.theme` 上切换 `light`/`dark`，用 `localStorage` 保存；目录链接使用原生锚点；脚本失败不影响正文阅读。脚本不发起网络请求、不使用 `innerHTML` 拼接不可信数据。

- [ ] **步骤 4：补齐主题、窄屏和减少动效 CSS**

在 `:root` 定义完整浅色 token，在 `@media (prefers-color-scheme: dark)` 和 `[data-theme="dark"]` 中覆盖深色 token；`@media (max-width: 820px)` 将侧栏改为顶部横向目录；SVG 使用独立横向滚动容器；`@media (prefers-reduced-motion: reduce)` 禁用过渡动画。

- [ ] **步骤 5：提交完整页面**

```powershell
git add docs/project-architecture.html
git commit -m "docs: 完善架构页面状态安全与主题交互"
```

### 任务 5：执行最终验证并检查页面范围

**文件：**
- 检查：`docs/project-architecture.html`

- [ ] **步骤 1：执行差异空白检查**

运行：`git diff HEAD~4 --check`

预期：无输出且退出码为 0。

- [ ] **步骤 2：执行离线依赖检查**

运行：`python -c "from pathlib import Path; s=Path('docs/project-architecture.html').read_text(encoding='utf-8').lower(); forbidden=['https://','http://','<script src=','<link rel=']; found=[x for x in forbidden if x in s]; assert not found, found; print('Offline dependency check OK')"`

预期输出：`Offline dependency check OK`。

- [ ] **步骤 3：执行章节和图形数量检查**

运行：`python -c "from pathlib import Path; s=Path('docs/project-architecture.html').read_text(encoding='utf-8'); assert s.count('<svg') >= 4; assert all(f'id=\"{x}\"' in s for x in ['overview','architecture','travel-flow','document-flow','resilience','status-contract','security']); print('Sections and diagrams OK')"`

预期输出：`Sections and diagrams OK`。

- [ ] **步骤 4：检查工作树只包含目标新增页面及用户原有变更**

运行：`git status --short`

确认没有删除或覆盖用户已有修改；只将本次页面相关文件纳入本次提交范围。

- [ ] **步骤 5：报告验证结果**

记录页面路径、提交哈希、结构检查结果、离线依赖检查结果和任何未执行的浏览器视觉检查；未运行浏览器时不得声称已完成真实浏览器渲染验证。
