# 模拟界面企业级 UI 重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不改变模拟任务、反馈、设置和数据看板业务逻辑的前提下，将 `layout-prototype.html` 重构为已确认的企业级前导页、统一首页导航窗格和可管理查询记录界面。

**架构：** 继续使用单个独立 HTML 文件：HTML 仅重排现有的首页、导航和前导页 DOM；CSS 通过新增设计令牌、组件样式与关键帧实现视觉和动效；JavaScript 保留既有任务模型和事件函数，仅添加图片轮播状态、记录面板收起状态和相应渲染逻辑。所有新增 UI 都通过现有函数 `homeRegion()`、`homePlan()`、`quickRegion()`、`selectTask()`、`clearTasks()`、`confirmDelete()` 与 `startExperience()` 连接。

**技术栈：** 原生 HTML、CSS、JavaScript；浏览器 `requestAnimationFrame`、CSS Keyframes、`matchMedia('(prefers-reduced-motion: reduce)')`。

---

## 文件结构

- 修改：`layout-prototype.html`
  - 保留现有独立原型和全部演示数据。
  - 重排首页/前导页/左侧导航 HTML，新增图片轮播及数字人占位 DOM。
  - 更新 CSS 令牌、响应式布局、动效与管理记录样式。
  - 最小扩展 JS：管理图片轮播和查询记录收起状态，不改任务与设置数据模型。
- 修改：`docs/superpowers/specs/2026-08-20-layout-prototype-ui-redesign-design.md`
  - 仅在实施中发现规范需澄清且已获得用户确认时更新；本计划执行时预期无需修改。

## 验收口径

- 原型在浏览器中可加载，前导页、首页、任务结果、数据看板、设置和删除确认均正常工作。
- 首页不再显示旧的双模式卡片，改为包含垂直虚线的统一双区导航窗格。
- 左侧查询记录可选择、收起/展开、单条删除与清空；任务行为和内容不变。
- 前导页符合确认的 A2 放大航迹方案：无中间分割线、左 46% / 右 54%、保留所有三项能力文案。
- 运动效果无硬切，并在减少动态效果偏好下关闭或降级。

### 任务 1：重构首页统一导航窗格

**文件：**
- 修改：`layout-prototype.html:54-101`（首页结构）
- 修改：`layout-prototype.html:369-404`（首页与按钮样式）
- 修改：`layout-prototype.html:576-594`（响应式规则）

- [ ] **步骤 1：以原有函数和 ID 为约束检查首页事件接线**

确认以下属性在改造后保持存在，避免修改任务逻辑：

```html
<input id="home-origin" placeholder="现居地，如：北京">
<input id="home-dest" placeholder="目的地，如：成都">
<button class="btn-primary" onclick="homePlan()">生成方案</button>
<input id="home-region-input" placeholder="地区名，如：成都" onkeydown="if(event.key==='Enter')homeRegion()">
<button class="btn-primary" onclick="homeRegion()">查攻略</button>
<button class="region-chip" onclick="quickRegion('成都')">成都</button>
```

运行：在 `layout-prototype.html` 中检查 `homePlan`、`homeRegion` 和 `quickRegion` 的定义。

预期：三个函数仍分别调用 `createTask('plan', o + '→' + d)` 或 `createTask('region', ...)`。

- [ ] **步骤 2：替换旧的 `.mode-cards` 内容为单个双区导航窗格**

将 `#view-home` 内的 `.mode-cards` 和页面外 `.quick-row` 替换为下列结构。保留上述元素 ID、按钮文字和 onclick：

```html
<div class="journey-panel">
  <section class="planner-zone">
    <div class="eyebrow">TRAVEL PLANNING</div>
    <h3>出行规划</h3>
    <p>设定始发地与目的地，生成完整出行方案。</p>
    <div class="travel-showcase" aria-label="旅行图片展示窗口">
      <div class="travel-slide is-active"></div>
      <div class="travel-slide"></div>
      <div class="travel-slide"></div>
      <div class="travel-showcase-copy"><strong>发现下一段旅程</strong><span>文旅图片将在此自动切换</span></div>
      <div class="travel-dots" aria-hidden="true"><i></i><i></i><i></i></div>
    </div>
    <div class="route-fields">...</div>
    <button class="btn-primary btn-block" onclick="homePlan()">生成方案</button>
    <div class="quick-regions"><span class="eyebrow">快捷地区</span><div class="region-list">...</div></div>
  </section>
  <div class="journey-divider" aria-hidden="true"></div>
  <section class="search-zone">
    <div class="agent-placeholder" data-agent-anchor="visual-placeholder">
      <div class="agent-avatar" aria-hidden="true"></div>
      <div><strong>智能出行助手</strong><span>数字人模型接入预留区</span><div class="agent-wave" aria-hidden="true"></div><small>VISUAL ANCHOR · PLACEHOLDER</small></div>
    </div>
    <div class="eyebrow">CUSTOM SEARCH</div>
    <h3>自定义搜索</h3>
    <p>检索已收录的景点、美食与行程攻略。</p>
    <div class="search-field">...</div>
  </section>
</div>
```

- [ ] **步骤 3：添加统一导航窗格的最小样式**

在现有“首页 · 模式选择”样式段落内移除 `.mode-cards` / `.mode-card` 专有规则，并添加：

```css
.journey-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr);
  gap: 28px;
  padding: 26px;
  background: var(--surface);
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  box-shadow: var(--shadow);
}
.journey-divider { background: repeating-linear-gradient(to bottom, #d1d5db 0 5px, transparent 5px 10px); }
.travel-showcase { position: relative; height: 176px; overflow: hidden; border-radius: 12px; margin: 16px 0; background: #24445e; }
.agent-placeholder { min-height: 140px; display: flex; align-items: center; justify-content: center; gap: 14px; border: 1px dashed #94a3b8; border-radius: 12px; background: radial-gradient(circle at 42% 40%, #eff6ff, #fff 68%); }
```

主按钮继续使用 `.btn-primary`，但色值改为 `#2563eb`，悬停色改为 `#1d4ed8`；次级控制保留白底描边。

- [ ] **步骤 4：添加首页响应式规则**

在现有 `@media (max-width: 900px)` 里添加：

```css
.journey-panel { grid-template-columns: 1fr; gap: 20px; }
.journey-divider { height: 1px; background: repeating-linear-gradient(to right, #d1d5db 0 5px, transparent 5px 10px); }
```

在 `@media (max-width: 640px)` 添加：

```css
.route-fields { grid-template-columns: 1fr; }
.route-fields .arrow { display: none; }
```

- [ ] **步骤 5：手工验证首页核心路径**

运行：使用浏览器打开 `layout-prototype.html`，依次输入“北京 / 成都”点击“生成方案”、输入“成都”点击“查攻略”、点击“成都”快捷地区。

预期：每次创建相应任务并显示既有处理中卡片，随后显示既有结果内容；左侧记录增加且无控制台异常。

- [ ] **步骤 6：Commit**

```bash
git add layout-prototype.html
git commit -m "feat: redesign unified travel navigation"
```

### 任务 2：将查询记录升级为可管理交互键组

**文件：**
- 修改：`layout-prototype.html:29-36`（查询记录 HTML）
- 修改：`layout-prototype.html:307-347`（任务列表样式）
- 修改：`layout-prototype.html:755-777`（`renderNav`）
- 修改：`layout-prototype.html:597-602`（模块级 UI 状态）

- [ ] **步骤 1：添加记录面板的稳定 DOM**

将查询记录区替换为：

```html
<div class="history-panel">
  <div class="history-head">
    <div class="side-label">查询记录 <span id="history-count" class="history-count">0</span></div>
    <div class="history-actions">
      <button class="history-toggle" id="history-toggle" onclick="toggleHistory()" aria-expanded="true" aria-label="收起查询记录">⌃</button>
      <button class="side-clear" onclick="clearTasks()">清空</button>
    </div>
  </div>
  <div class="task-list" id="task-list"></div>
  <div class="history-foot"><span>按时间排序</span><button class="history-manage" type="button">管理记录 →</button></div>
</div>
```

- [ ] **步骤 2：添加 CSS 管理容器和键组状态**

使用现有 `.task-item` 作为整行按钮，新增：

```css
.history-panel { overflow: hidden; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.history-head, .history-foot { min-height: 38px; padding: 0 10px; display: flex; align-items: center; justify-content: space-between; }
.history-head { border-bottom: 1px solid var(--border); background: #fbfdff; }
.history-foot { border-top: 1px solid var(--border); color: var(--text-dim); font-size: 11px; }
.history-count { padding: 2px 6px; border-radius: 999px; background: #eff6ff; color: #2563eb; font-size: 10px; }
.history-panel.is-collapsed .task-list, .history-panel.is-collapsed .history-foot { display: none; }
.task-item.active { background: #eff6ff; border-color: #bfdbfe; box-shadow: none; }
```

保留既有 `.task-delete` 的悬停滑入与确认删除行为。

- [ ] **步骤 3：最小扩展记录 UI 状态与渲染**

在 `let seq = 0;` 后添加：

```js
let historyCollapsed = false;

function toggleHistory() {
  historyCollapsed = !historyCollapsed;
  renderNav();
}
```

在 `renderNav()` 末尾设置记录数量、折叠类和无障碍属性：

```js
const panel = document.querySelector('.history-panel');
const count = document.getElementById('history-count');
const toggle = document.getElementById('history-toggle');
panel.classList.toggle('is-collapsed', historyCollapsed);
count.textContent = tasks.length;
toggle.textContent = historyCollapsed ? '⌄' : '⌃';
toggle.setAttribute('aria-expanded', String(!historyCollapsed));
toggle.setAttribute('aria-label', historyCollapsed ? '展开查询记录' : '收起查询记录');
```

`history-manage` 不绑定新事件：它只作为经过确认的视觉预留入口。

- [ ] **步骤 4：手工验证任务记录行为**

运行：在首页创建两条新任务；点击任一记录；点击折叠/展开；悬停并删除一条；点击清空并在确认弹窗中完成操作。

预期：记录数实时更新；选中态随任务切换；折叠只隐藏列表和底栏；删除与清空使用既有逻辑、结果页面与导航均无异常。

- [ ] **步骤 5：Commit**

```bash
git add layout-prototype.html
git commit -m "feat: add query history management panel"
```

### 任务 3：实现多图旅行展示窗口

**文件：**
- 修改：`layout-prototype.html:369-404`（首页视觉样式）
- 修改：`layout-prototype.html:597-602`（图片配置状态）
- 修改：`layout-prototype.html:934-940`（初始化代码）

- [ ] **步骤 1：定义本地可替换的图片列表和减少动画判断**

在脚本开头增加显式配置，后续用户只替换 `src` 字符串：

```js
const travelImages = [
  { src: '', alt: '山海与城市的旅行意象' },
  { src: '', alt: '自然风景的旅行意象' },
  { src: '', alt: '城市文化的旅行意象' },
];
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
```

空 `src` 由 CSS 默认渐变占位视觉兜底；不进行网络请求或上传处理。

- [ ] **步骤 2：添加图片应用与轮播函数**

添加：

```js
function setupTravelShowcase() {
  const slides = [...document.querySelectorAll('.travel-slide')];
  const dots = [...document.querySelectorAll('.travel-dots i')];
  slides.forEach((slide, index) => {
    const image = travelImages[index];
    if (image?.src) slide.style.backgroundImage = `url("${image.src}")`;
    slide.setAttribute('aria-label', image?.alt || '旅行图片占位');
  });
  if (reduceMotion || slides.length < 2) return;
  let current = 0;
  window.setInterval(() => {
    slides[current].classList.remove('is-active');
    dots[current].classList.remove('is-active');
    current = (current + 1) % slides.length;
    slides[current].classList.add('is-active');
    dots[current].classList.add('is-active');
  }, 4000);
}
```

在现有初始化尾部 `showView('home')` 后调用 `setupTravelShowcase()`。

- [ ] **步骤 3：添加交叉淡入与降级 CSS**

```css
.travel-slide { position: absolute; inset: 0; opacity: 0; transform: scale(1.04); transition: opacity .8s ease, transform 4s ease; background: linear-gradient(125deg, #165d77, #46a7a6 55%, #d9cc94); background-position: center; background-size: cover; }
.travel-slide.is-active { opacity: 1; transform: scale(1); }
.travel-dots i.is-active { width: 18px; background: #fff; }
@media (prefers-reduced-motion: reduce) { .travel-slide { transition: none; } .travel-slide:not(:first-child) { display: none; } }
```

- [ ] **步骤 4：手工验证图片窗口**

运行：刷新原型，观察超过 8 秒；在系统或浏览器模拟减少动态效果后刷新。

预期：普通模式每 4 秒交叉淡入下一张并更新进度点；减少动态效果模式下仅展示首个占位；无闪烁、无布局偏移和无控制台异常。

- [ ] **步骤 5：Commit**

```bash
git add layout-prototype.html
git commit -m "feat: add travel image showcase"
```

### 任务 4：重构确认的 A2 前导页

**文件：**
- 修改：`layout-prototype.html:3-17`（前导页 HTML）
- 修改：`layout-prototype.html:478-511`（前导页样式）
- 修改：`layout-prototype.html:576-579`（减少动态效果样式）

- [ ] **步骤 1：替换前导页 DOM，保留所有既有信息和入口**

将 `.intro-inner` 更换为：

```html
<div class="intro-top"><span class="intro-brand">🌍 智能文旅策划助手</span><span class="intro-note">界面原型 · 演示数据</span></div>
<div class="intro-layout">
  <section class="intro-content">
    <h1 class="intro-title">把下一段旅程<br>交给智能规划</h1>
    <p class="intro-sub">输入出发地或地区名，一键生成 / 检索属于你的旅行方案</p>
    <button class="intro-btn" onclick="startExperience()">开始体验</button>
    <div class="intro-features">...</div>
  </section>
  <aside class="intro-visual" aria-label="抽象地平线航迹">
    <div class="intro-route-arc"></div><div class="intro-route-arc-inner"></div>
    <i class="intro-node intro-node-start"></i><i class="intro-node intro-node-end"></i>
    <span class="intro-route-label intro-route-start">FROM · START</span>
    <span class="intro-route-label intro-route-end">TO · DISCOVER</span>
    <span class="intro-route-caption">TRAVEL · PLAN · DISCOVER</span>
  </aside>
</div>
```

将现有三条 `.intro-feature` 文案原样置于新的 `.intro-features` 内；不要加入正文地球图标。

- [ ] **步骤 2：实现 46/54 无分割线的前导页 CSS**

移除旧的居中 `.intro-inner` 和 `.intro-mark` 专有样式，添加：

```css
.intro { background: linear-gradient(145deg, #f8fafc 0%, #fff 49%, #f1f5f9 100%); }
.intro-top { position: absolute; top: 0; left: 0; right: 0; height: 62px; padding: 0 28px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #edf0f4; }
.intro-layout { width: min(1100px, 100%); min-height: 590px; margin-top: 62px; display: grid; grid-template-columns: 46% 54%; }
.intro-content { padding: 80px 28px 48px 66px; display: flex; flex-direction: column; justify-content: center; text-align: left; }
.intro-visual { position: relative; overflow: hidden; }
```

不添加任何左右分隔线。使用 `::before` 创建右侧大面积柔和蓝光，双层虚线弧线与节点使用 `.intro-route-*` 类绘制。

- [ ] **步骤 3：添加分段入场和减少动画规则**

```css
.intro-title { animation: introRise .66s .06s cubic-bezier(.16, 1, .3, 1) both; }
.intro-sub { animation: introRise .66s .14s cubic-bezier(.16, 1, .3, 1) both; }
.intro-btn { animation: introRise .66s .22s cubic-bezier(.16, 1, .3, 1) both; }
.intro-feature { opacity: 0; animation: introRise .52s cubic-bezier(.16, 1, .3, 1) forwards; }
.intro-feature:nth-child(1) { animation-delay: .40s; }
.intro-feature:nth-child(2) { animation-delay: .52s; }
.intro-feature:nth-child(3) { animation-delay: .64s; }
.intro-visual { animation: introFadeRise .8s .32s cubic-bezier(.16, 1, .3, 1) both; }
@media (prefers-reduced-motion: reduce) { .intro-title, .intro-sub, .intro-btn, .intro-feature, .intro-visual, .intro-node { animation: none; opacity: 1; } }
```

- [ ] **步骤 4：添加前导页响应式布局**

```css
@media (max-width: 750px) {
  .intro-layout { display: block; min-height: 0; margin-top: 62px; }
  .intro-content { padding: 55px 25px 40px; }
  .intro-visual { display: none; }
  .intro-features { grid-template-columns: 1fr; }
}
```

- [ ] **步骤 5：手工验证前导页**

运行：强制刷新页面；观察初始入场；点击“开始体验”；使用窄屏与减少动态效果模式复验。

预期：不出现正文地球图标或中间分割线；右侧航迹为明显主视觉且保留全部指定英文小字；按钮仍使前导页淡出、顶部栏/侧栏/主内容按既有逻辑进入；移动端无横向滚动。

- [ ] **步骤 6：Commit**

```bash
git add layout-prototype.html
git commit -m "feat: redesign travel intro screen"
```

### 任务 5：端到端回归与视觉验证

**文件：**
- 修改：无（仅在发现明确实现错误时修改 `layout-prototype.html`）

- [ ] **步骤 1：运行静态语法检查**

运行：

```bash
node --check <(python -c "from pathlib import Path; s=Path('layout-prototype.html').read_text(encoding='utf-8'); print(s.split('<script>', 1)[1].split('</script>', 1)[0])")
```

预期：退出码 `0`，无 JavaScript 语法错误。

- [ ] **步骤 2：使用浏览器做全流程回归**

运行：通过项目运行/浏览器工具打开 `layout-prototype.html`，完成以下流程：

1. 前导页点击“开始体验”。
2. 在出行规划输入“北京”“成都”，生成任务并等待结果。
3. 在自定义搜索输入“成都”，按 Enter 创建攻略任务。
4. 点击快捷地区“三亚”。
5. 在左侧折叠/展开记录，切换记录，删除一条记录并取消一次删除确认，再确认删除一次。
6. 访问数据看板，检查数字滚动、进度条和表格渐现。
7. 打开设置，填写任一字段、保存，重新打开确认字段存在。
8. 在 1440px、900px、640px 检查无页面水平滚动。

预期：所有既有演示流程保持工作，无控制台 `TypeError`、`ReferenceError` 或未处理 Promise 错误。

- [ ] **步骤 3：核验动效降级**

运行：浏览器模拟 `prefers-reduced-motion: reduce` 后刷新。

预期：前导页内容直接可见；图片窗口只显示第一张；右侧节点和页面/数据进入动画不播放；所有交互仍可用。

- [ ] **步骤 4：检查工作区差异**

运行：

```bash
git diff --check
git status --short
```

预期：`git diff --check` 无输出；状态只包含本任务产生的预期修改。

- [ ] **步骤 5：Commit**

若验证步骤修复了 `layout-prototype.html`，运行：

```bash
git add layout-prototype.html
git commit -m "fix: polish travel prototype responsive states"
```

若未产生修复，不创建空提交。
