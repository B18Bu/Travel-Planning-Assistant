# 工作台行程规划与攻略查询拆分实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不改变欢迎页文案和其他工作台模块的前提下，将行程规划与攻略查询拆分到两个独立的前端内部视图。

**架构：** 继续使用现有 `showView()` 控制单页内部视图。`index.html` 将既有功能 DOM 从首页移动到 `view-plan` 与 `view-guide`，首页只保留原有欢迎内容；`app.js` 将新导航纳入激活态和异步搜索的视图守卫；`styles.css` 使用通用双栏容器承载两类功能页，并在窄屏改为纵向布局。后端接口与既有方案结果页不变。

**技术栈：** 原生 HTML、CSS、JavaScript、既有 `showView()`、Fetch API、浏览器手工验收。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `frontend/index.html` | 增加两个导航入口和两个独立视图；首页保留欢迎内容，移动既有轮播、表单、数字人、搜索和结果 DOM。 |
| `frontend/app.js` | 管理 plan/guide 的导航激活态、默认新建任务跳转、攻略检索响应守卫；复用既有业务函数。 |
| `frontend/styles.css` | 新功能页的桌面双栏与窄屏单栏布局；移除首页旧双栏容器的布局依赖，保留既有组件视觉样式。 |
| `docs/superpowers/specs/2026-08-24-workspace-feature-split-design.md` | 实现后登记测试命令与已实现状态。 |

## 任务 1：拆分 HTML 视图与导航

**文件：**
- 修改：`frontend/index.html:49-245`

- [ ] **步骤 1：增加两个功能导航入口**

在左侧“管理”区前插入：

```html
<div class="side-section">
  <div class="side-label">功能</div>
  <button class="side-nav" id="nav-plan" onclick="showView('plan')">
    <span>🧭</span> 行程规划
  </button>
  <button class="side-nav" id="nav-guide" onclick="showView('guide')">
    <span>🔎</span> 攻略查询
  </button>
</div>
```

- [ ] **步骤 2：将首页缩减为原有欢迎内容**

保留 `#view-home`、`.home`、`.home-welcome` 中的下列文案逐字不变；删除该 section 内原 `.home-nav-pane` 及其全部子节点：

```html
<div class="home-eyebrow">企业级智能文旅工作台</div>
<h2>欢迎使用智能文旅策划助手</h2>
<p>统一入口承载出行规划、数字人服务与目的地知识检索</p>
```

- [ ] **步骤 3：新增行程规划视图并移动原有轮播和表单**

在 `view-home` 后、`view-task` 前新增：

```html
<section id="view-plan" class="view">
  <div class="feature-page">
    <div class="feature-page-head">
      <div class="zone-kicker">Trip Planning</div>
      <h2>行程规划</h2>
      <p>填写出行信息，生成交通、景点、美食与行程建议。</p>
    </div>
    <div class="feature-split feature-split-plan">
      <section class="feature-visual"><!-- 移入原 travel-window --></section>
      <section class="feature-action"><!-- 移入原 travel-form --></section>
    </div>
  </div>
</section>
```

把原 `.travel-window`（含所有 `travel-slide`、`travel-dot`）移到 `.feature-visual`；把原 `#travel-form` 移到 `.feature-action`。以下 id 必须保持不变且全页仅出现一次：`travel-form`、`home-origin`、`home-dest`、`home-date`、`home-travelers`、`home-days`、`home-budget`、`home-preferences`、`home-status`、`home-error`。

- [ ] **步骤 4：新增攻略查询视图并移动原有数字人与搜索区域**

在 `view-plan` 后新增：

```html
<section id="view-guide" class="view">
  <div class="feature-page">
    <div class="feature-page-head">
      <div class="zone-kicker">Knowledge Search</div>
      <h2>攻略查询</h2>
      <p>从已收录攻略中检索目的地、路线与美食信息。</p>
    </div>
    <div class="feature-split feature-split-guide">
      <section class="feature-visual"><!-- 移入原 digital-human-card --></section>
      <section class="feature-action"><!-- 移入原 search-card 和 knowledge-panel --></section>
    </div>
  </div>
</section>
```

把原 `.digital-human-card` 移到左栏；把原 `.search-card`、`.knowledge-panel` 移到右栏。保留 `home-region-input` 和 `knowledge-results` 的 id，搜索按钮仍调用 `homeRegion()`。

- [ ] **步骤 5：验证 HTML 结构**

运行：

```bash
grep -nE 'id="(view-home|view-plan|view-guide|nav-plan|nav-guide|travel-form|home-region-input|knowledge-results)"' frontend/index.html
```

预期：每个 id 恰好出现一次；首页保留欢迎语但没有 `travel-form` 或 `knowledge-results`；行程规划页包含表单，攻略查询页包含搜索区。

- [ ] **步骤 6：Commit**

```bash
git add frontend/index.html
git commit -m "feat: split workspace planning and guide views"
```

## 任务 2：调整视图状态与攻略检索守卫

**文件：**
- 修改：`frontend/app.js:85-105, 313-326, 1046-1084, 1143-1168`

- [ ] **步骤 1：先确认新建任务的当前失败行为**

浏览器控制台执行：

```js
resetPlanForm();
console.assert(activeView === "plan");
console.assert(document.getElementById("view-plan").classList.contains("active"));
```

预期：修改前失败，因为 `resetPlanForm()` 调用 `showView("home")`。

- [ ] **步骤 2：将“新建任务”改为进入行程规划页**

在 `resetPlanForm()` 中将：

```js
showView("home");
originInput.focus();
```

替换为：

```js
showView("plan");
originInput.focus();
```

`clearTasks()`、删除当前任务后的回退和品牌返回仍继续使用 `showView("home")`，保持默认欢迎首页语义。

- [ ] **步骤 3：为新导航加入激活态**

在 `showView()` 内已有 dashboard/library 引用后新增：

```js
const plan = document.getElementById("nav-plan");
const guide = document.getElementById("nav-guide");
if (plan) plan.classList.toggle("active", name === "plan");
if (guide) guide.classList.toggle("active", name === "guide");
```

保留 dashboard/library 的现有加载逻辑。

- [ ] **步骤 4：把攻略检索守卫改为攻略查询视图**

在 `homeRegion()` 的成功和错误分支分别将：

```js
activeView !== "home"
```

替换为：

```js
activeView !== "guide"
```

在 `showView()` 中将：

```js
if (name !== "home") knowledgeRequestGeneration += 1;
```

替换为：

```js
if (name !== "guide") knowledgeRequestGeneration += 1;
```

这样从攻略查询切出后，旧响应不会写入其他视图；在攻略查询中提交请求不会被当前视图本身错误取消。

- [ ] **步骤 5：调整首页高度适配计算**

在 `fitWorkbenchToViewport()` 中保留 `#view-home` 查询与非首页恢复滚动的逻辑；删除 `navPane` 查询，并把自然高度改为：

```js
const welcome = homeView.querySelector(".home-welcome");
const natural = (welcome ? welcome.offsetHeight : 0) + 48;
```

- [ ] **步骤 6：验证视图切换与异步边界**

在浏览器验证：

1. 点击行程规划后 `#view-plan` 和 `#nav-plan` 同时激活；
2. 点击攻略查询后 `#view-guide` 和 `#nav-guide` 同时激活；
3. 攻略查询发起请求后切换首页，旧响应不会渲染；
4. 点击“＋ 新建任务”后显示行程规划页并聚焦始发地；
5. 点击品牌仍回到首页。

- [ ] **步骤 7：Commit**

```bash
git add frontend/app.js
git commit -m "fix: route workspace actions to split views"
```

## 任务 3：实现共享双栏布局与响应式规则

**文件：**
- 修改：`frontend/styles.css:155-281, 560-620`

- [ ] **步骤 1：建立新功能页与共享双栏样式**

替换只服务旧首页 `.home-nav-pane`、`.home-zone`、`.home-plan-zone`、`.home-service-zone`、`.pane-divider` 的布局规则，新增：

```css
.feature-page { max-width: 1080px; margin: 8px auto 0; }
.feature-page-head { margin-bottom: 20px; }
.feature-page-head h2 { margin-top: 6px; font-size: 28px; }
.feature-page-head p { margin-top: 7px; color: var(--text-dim); font-size: 13px; line-height: 1.7; }
.feature-split {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, .92fr); gap: 24px;
  align-items: start;
}
.feature-visual, .feature-action {
  min-width: 0; background: var(--surface); border: 1px solid var(--border);
  border-radius: 18px; padding: 22px; box-shadow: var(--shadow);
}
```

保留 `.travel-window`、`.digital-human-card`、`.search-card`、`.route-form`、`.knowledge-panel` 的既有视觉细节。

- [ ] **步骤 2：限定欢迎页样式只服务欢迎内容**

保留 `.home`、`.home-welcome`、`.home-eyebrow`、`.home-welcome h2`、`.home-welcome p` 的现有字体、颜色与间距。

将：

```css
#view-home.active { height: 100%; min-height: 0; overflow: hidden; }
```

调整为：

```css
#view-home.active { min-height: 0; }
```

- [ ] **步骤 3：设置两个功能页的内部尺寸**

新增：

```css
.feature-split-plan .feature-visual { display: flex; flex-direction: column; }
.feature-split-plan .travel-window { height: 320px; }
.feature-split-plan .route-form { margin-top: 0; }
.feature-split-guide .feature-visual { display: flex; }
.feature-split-guide .digital-human-card { width: 100%; min-height: 280px; }
.feature-split-guide .search-card { padding: 0; border: 0; box-shadow: none; background: transparent; }
.feature-split-guide .knowledge-panel { margin-top: 18px; min-height: 280px; }
```

这些选择器只能作用于新功能页，不能影响数据看板、文档库、结果页或欢迎页。

- [ ] **步骤 4：增加窄屏堆叠规则**

在现有 `@media (max-width: 768px)` 中增加：

```css
.feature-split { grid-template-columns: 1fr; }
.feature-page { margin-top: 0; }
```

在 `@media (max-width: 640px)` 中增加：

```css
.feature-visual, .feature-action { padding: 16px; border-radius: 14px; }
.feature-split-plan .travel-window { height: 170px; }
.feature-split-guide .digital-human-card { min-height: 220px; }
```

保留既有 `.route-fields` 与 `.search-form` 的窄屏纵向规则。

- [ ] **步骤 5：浏览器视觉验证**

用桌面与 640px 以下宽度检查：

1. 首页只显示原欢迎内容，欢迎字体与说明未变；
2. 行程规划页左图右表单，无重叠或横向溢出；
3. 攻略查询页左数字人右搜索与结果，结果区可纵向滚动；
4. 窄屏下两个功能页均为展示区在上、操作区在下；
5. 数据看板、文档库和结果页样式未变。

- [ ] **步骤 6：Commit**

```bash
git add frontend/styles.css
git commit -m "style: lay out split workspace feature views"
```

## 任务 4：最终验证与规格状态更新

**文件：**
- 修改：`docs/superpowers/specs/2026-08-24-workspace-feature-split-design.md`

- [ ] **步骤 1：检查 JavaScript 语法**

运行：

```bash
node --check frontend/app.js
```

预期：退出码 0，无输出。

- [ ] **步骤 2：验证 DOM id 与欢迎页边界**

运行：

```bash
python -c "from pathlib import Path; from collections import Counter; import re; html=Path('frontend/index.html').read_text(encoding='utf-8'); ids=Counter(re.findall(r'\bid=\"([^\"]+)\"', html)); [(_ for _ in ()).throw(AssertionError((name, ids[name]))) for name in ('travel-form','home-origin','home-region-input','knowledge-results','view-home','view-plan','view-guide') if ids[name] != 1]; home=re.search(r'<section id=\"view-home\".*?</section>', html, re.S).group(0); assert '欢迎使用智能文旅策划助手' in home; assert 'travel-form' not in home; assert 'knowledge-results' not in home; print('HTML 结构验证通过')"
```

预期：输出 `HTML 结构验证通过`。

- [ ] **步骤 3：完成浏览器手工回归**

启动项目现有前端服务，检查默认首页、两个导航视图、行程提交到既有结果页、攻略查询结果、切换视图时取消过期查询、桌面与窄屏布局、数据看板、文档库、查询记录和设置。

若失败，仅修复 `frontend/index.html`、`frontend/app.js` 或 `frontend/styles.css` 中对应问题；不得修改后端或欢迎页文案。

- [ ] **步骤 4：更新规格状态与验证记录**

将规格文档状态改为：

```markdown
**状态：** 已实现并完成前端回归验证
```

并在末尾追加：

```markdown
## 7. 实现验证

已执行：`node --check frontend/app.js`、HTML 结构验证脚本，以及桌面端和窄屏的浏览器手工回归。
```

- [ ] **步骤 5：检查范围并提交**

运行：

```bash
git diff --check
git status --short
```

预期：`git diff --check` 无输出；除了用户已有未跟踪 PPT 文档外，所有本任务改动均已经提交。

然后运行：

```bash
git add docs/superpowers/specs/2026-08-24-workspace-feature-split-design.md
git commit -m "docs: record workspace split verification"
```
