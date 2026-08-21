# 旅行规划工作台重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将真实 MVP 前端重构为 `layout-prototype.html` 的前导页与企业工作台视觉结构，同时保留真实旅行规划 API、安全 Markdown、双栏结果与降级展示。

**架构：** 前端仍是无框架同源静态页面。页面在 `intro` 与 `workspace` 两个视图间切换；工作台只启用新建旅行规划和真实结果展示，原型中的知识库、数据看板、数字人和设置以不可交互的 MVP 占位呈现。请求、合同和安全 DOM 边界不改变。

**技术栈：** 原生 HTML、CSS、JavaScript、FastAPI StaticFiles、本地 `marked@15.0.12`、本地 DOMPurify@3.2.6、pytest。

---

## 文件结构

- 修改：`frontend/index.html` — 前导页、品牌栏、侧边栏、真实表单和结果工作台的语义结构。
- 修改：`frontend/styles.css` — 原型视觉令牌、前导页航迹、侧边栏、工作区、响应式布局和状态样式。
- 修改：`frontend/app.js` — 前导页切换、工作台重置、焦点管理，以及保留真实安全请求/结果渲染。
- 修改：`backend/tests/test_frontend_assets.py` — 验证原型工作台结构、占位不触发 API、前导页与安全边界。
- 不修改：`frontend/vendor/*`、`backend/app/models/*`、`backend/app/api/*`、所有 Agent、服务层与数据合同。

统一测试命令，从工作树根目录执行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -q
```

---

### 任务 1：用前端回归测试锁定原型工作台行为

**文件：**
- 修改：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：添加前导页、工作台和占位能力的失败测试**

新增测试应读取 `frontend/index.html` 和 `frontend/app.js`，并验证：

```python
def test_frontend_has_intro_and_real_workspace_views():
    html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")

    assert 'id="intro"' in html
    assert 'id="workspace"' in html
    assert 'id="start-experience"' in html
    assert 'id="new-plan"' in html
    assert 'id="travel-form"' in html


def test_frontend_marks_unavailable_prototype_capabilities_as_non_interactive():
    html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")

    assert "当前 MVP 未启用" in html
    assert "知识库检索" in html
    assert "数据看板" in html
    assert "数字人讲解" in html
    assert "/api/knowledge" not in html
    assert "/api/dashboard" not in html


def test_frontend_switches_intro_and_resets_real_plan_without_network_side_effects():
    script = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")

    assert "startExperience" in script
    assert "startNewPlan" in script
    assert "workspace.hidden" in script
    assert "intro.hidden" in script
    assert "form.reset" in script
```

- [ ] **步骤 2：运行前端测试确认失败**

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：FAIL，当前页面没有 `intro` / `workspace` 结构及相应切换函数。

- [ ] **步骤 3：实现最小视图切换函数**

在 `frontend/app.js` 中保留现有请求与安全渲染函数，并新增：

```javascript
function startExperience() {
  intro.hidden = true;
  workspace.hidden = false;
  form.querySelector("input[name=origin]").focus();
}

function startNewPlan() {
  form.reset();
  departureInput.min = todayIso();
  result.hidden = true;
  error.hidden = true;
  status.textContent = "";
  form.querySelector("input[name=origin]").focus();
}
```

函数只能切换本地 DOM 状态，不得调用 `fetch` 或未实现 API。

- [ ] **步骤 4：运行前端测试确认通过**

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：PASS。

- [ ] **步骤 5：提交测试与行为骨架**

```powershell
git add backend/tests/test_frontend_assets.py frontend/app.js
git commit -m "test: define travel workbench behavior"
```

---

### 任务 2：重构前导页与工作台 HTML 结构

**文件：**
- 修改：`frontend/index.html`

- [ ] **步骤 1：替换页面主体为前导页和工作台**

保留 `<head>` 中本地 `/styles.css`、`/vendor/marked.min.js`、`/vendor/purify.min.js` 和 `/app.js`。主体结构必须包含：

```html
<main id="intro" class="intro-view">
  <section class="intro-copy">
    <p class="intro-product">智能文旅策划助手</p>
    <h1>把下一段旅程<br>交给智能规划</h1>
    <p>以受控天气、路线和 POI 数据生成可核验的旅行建议。</p>
    <button id="start-experience" type="button">开始体验</button>
    <ul>
      <li>结构化规划与来源追溯</li>
      <li>天气、路线、住宿与餐饮协同</li>
      <li>异常时明确降级与核验提示</li>
    </ul>
  </section>
  <aside class="intro-visual" aria-label="旅行规划航迹">
    <!-- 内联 SVG 弧线、起点、终点；不引用远程图片。 -->
  </aside>
</main>

<main id="workspace" class="workspace" hidden>
  <header class="topbar">…</header>
  <div class="workbench-shell">
    <aside class="sidebar">
      <button id="new-plan" type="button">＋ 新建旅行规划</button>
      <section>
        <p>当前能力</p>
        <span>旅行规划</span>
      </section>
      <section class="mvp-placeholder" aria-label="未启用能力">
        <p>当前 MVP 未启用</p>
        <span>知识库检索 · 数据看板 · 数字人讲解 · 设置</span>
      </section>
    </aside>
    <section class="workspace-main">…现有真实表单和结果区…</section>
  </div>
</main>
```

真实表单必须完整保留原字段、`id="travel-form"`、状态区、错误区、结果双栏及其 DOM ID：`markdown`、`warnings`、`sources`、`degraded`。

- [ ] **步骤 2：添加可访问性属性**

- 「开始体验」是 `button`，不使用 `onclick` 内联脚本；
- 工作台标题是可聚焦 `h2 tabindex="-1"`，供视图切换后聚焦；
- 未启用能力不使用伪按钮；若需要视觉按钮，使用 `aria-disabled="true"`、`tabindex="-1"` 且不绑定事件；
- 现有 `role="status"`、`role="alert"` 保持。

- [ ] **步骤 3：运行前端和静态根路径测试**

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：PASS，`GET /` 仍返回页面，真实表单仍在 HTML 中。

- [ ] **步骤 4：提交 HTML 工作台结构**

```powershell
git add frontend/index.html
git commit -m "feat: add travel workbench structure"
```

---

### 任务 3：实现原型视觉语言与响应式工作台

**文件：**
- 修改：`frontend/styles.css`

- [ ] **步骤 1：定义工作台视觉令牌**

在 `:root` 中定义浅色企业工作台令牌，至少包含：

```css
:root {
  --bg: #f3f5fa;
  --surface: #fff;
  --surface-muted: #eef1f7;
  --text: #2a3146;
  --text-muted: #6b7489;
  --border: #e3e7f1;
  --accent: #2563eb;
  --accent-soft: #eff6ff;
  --danger: #b91c1c;
  --shadow: 0 10px 30px rgb(15 23 42 / 8%);
}
```

禁止 remote 字体、图片、CDN 样式或脚本。

- [ ] **步骤 2：实现前导页视觉**

- 使用至少 `min-height: 100dvh`；
- 宽屏双栏，窄屏单栏；
- 使用 CSS/SVG 弧线和节点构造旅行航迹；
- 主按钮具有可见 `:focus-visible`；
- 不使用动画作为理解业务的唯一方式，`prefers-reduced-motion` 下关闭非必要动画。

- [ ] **步骤 3：实现工作台和结果双栏**

- `.workbench-shell` 使用侧边栏 + 主区；
- 表单、状态、结果正文和元数据均为独立卡片；
- `.result-layout` 保持正文/侧栏双栏；
- `@media (max-width: 768px)` 下将侧边栏、表单和结果改为单列；
- 未启用能力使用低对比静态说明，不伪装按钮；
- `.markdown-body` 保持安全内容的可读行距、表格/代码溢出处理和图片最大宽度。

- [ ] **步骤 4：运行静态与 JavaScript 检查**

```powershell
node --check frontend/app.js
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：两者 PASS。

- [ ] **步骤 5：提交视觉样式**

```powershell
git add frontend/styles.css
git commit -m "feat: style prototype travel workbench"
```

---

### 任务 4：连接工作台交互与真实安全展示

**文件：**
- 修改：`frontend/app.js`
- 修改：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：绑定工作台 DOM 和事件**

在现有查询节点之后绑定：

```javascript
const intro = document.querySelector("#intro");
const workspace = document.querySelector("#workspace");
const startExperienceButton = document.querySelector("#start-experience");
const newPlanButton = document.querySelector("#new-plan");
const workspaceTitle = document.querySelector("#workspace-title");

startExperienceButton.addEventListener("click", startExperience);
newPlanButton.addEventListener("click", startNewPlan);
```

`startExperience` 与 `startNewPlan` 必须使用 `hidden` 属性和 `focus()`，不得通过 `innerHTML` 重建视图。

- [ ] **步骤 2：在提交状态中隐藏旧结果**

提交表单开始时增加：

```javascript
result.hidden = true;
status.textContent = "正在生成旅行规划…";
```

请求失败时继续调用 `setError`。成功后由 `renderDocument` 显示新结果。这样旧行程不会在新请求加载期间被误认为当前结果。

- [ ] **步骤 3：保持 API 和安全 DOM 边界**

不得改变以下行为：

```javascript
const parsed = marked.parse(documentData.markdown || "");
const clean = DOMPurify.sanitize(parsed, {
  FORBID_TAGS: ["script", "style", "svg", "math"],
  FORBID_ATTR: [/^on/i],
});
markdown.innerHTML = clean;
```

`setTextList`、错误文本、failed/degraded 状态和来源文本继续使用 `textContent`。不展示 `documentData.itinerary`，不添加 `JSON.stringify(documentData)` 或调试输出。

- [ ] **步骤 4：扩展行为回归测试**

在 `test_frontend_assets.py` 中断言：

```python
def test_frontend_preserves_safe_rendering_inside_workbench():
    script = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")

    assert "startExperienceButton.addEventListener" in script
    assert "newPlanButton.addEventListener" in script
    assert "result.hidden = true" in script
    assert "DOMPurify.sanitize" in script
    assert "markdown.innerHTML = clean" in script
    assert "JSON.stringify(documentData)" not in script
```

同时断言未启用能力没有 `fetch("/api/knowledge")`、`fetch("/api/dashboard")`、`localStorage` 或 `sessionStorage`。

- [ ] **步骤 5：运行完整后端回归**

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -q
node --check frontend/app.js
git diff --check
```

预期：全部 PASS。

- [ ] **步骤 6：提交工作台交互**

```powershell
git add frontend/app.js backend/tests/test_frontend_assets.py
git commit -m "feat: connect prototype travel workbench"
```

---

### 任务 5：启动本地检查服务并完成验收

**文件：**
- 验证：`frontend/*`
- 验证：`backend/app/main.py`
- 验证：`backend/tests/*`

- [ ] **步骤 1：运行最终测试与资产验证**

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -q
node --check frontend/app.js
git diff --check
```

预期：全量后端测试通过，JavaScript 语法正确，Git 差异无空白错误。

- [ ] **步骤 2：启动根目录服务供用户检查**

从真实项目根目录启动：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

确认：

```text
http://127.0.0.1:8010/
```

页面显示前导页；点击「开始体验」后显示工作台。端口 `8010` 是本轮检查端口，不替代文档中的常规 `8000`。

- [ ] **步骤 3：完成视觉验收检查**

用户在浏览器检查：

1. 前导页、航迹装饰和「开始体验」；
2. 顶部栏、侧边栏和「当前 MVP 未启用」占位；
3. 表单、按钮、移动端单栏；
4. 真实 API 返回后的正文/元数据双栏；
5. 错误、failed 和 degraded 的可见状态；
6. 页面不出现 JSON 源码、知识库假数据或控制台密钥。

- [ ] **步骤 4：提交最终验收说明**

仅在用户完成视觉检查且无修改要求后：

```powershell
git status --short
git log -1 --oneline
```

不为视觉验收创建空提交；若用户提出调整，按新的视觉需求修改并重新运行步骤 1。

---

## 计划自检

### 规格覆盖度

- 前导页、工作台、品牌栏、侧边栏：任务 2、3、4；
- 真实旅行表单和 API：任务 2、4；
- 安全 Markdown、元数据文本节点、无 JSON 源码：任务 4；
- MVP 未启用占位、无假 API/假数据：任务 1、2、4；
- 双栏与 768px 单栏：任务 3；
- 静态资源、JS、完整后端与用户视觉检查：任务 5。

### 占位符扫描

每项任务包含明确文件、测试、命令、预期结果和提交方式；未使用 TODO、待定、类似任务或未定义的错误处理描述。

### 类型一致性

- 视觉重构不改变 `/api/travel-plans`、`TravelPlanRequest` 或 `TravelPlanDocument`；
- `markdown` 仍是唯一 HTML 输入，`itinerary` 不进入页面；
- `DOMPurify.sanitize` 和 `textContent` 的职责边界保持不变；
- 所有原型未实现能力明确为静态 MVP 占位，不调用后端。