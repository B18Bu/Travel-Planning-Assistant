# 工作台欢迎语并入功能页实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 删除无交互的工作台内部首页，并在行程规划、攻略查询两个功能页顶部展示相同的现有欢迎语区。

**架构：** `index.html` 删除 `view-home`，并将同一份欢迎内容分别放到 `view-plan` 与 `view-guide`；`app.js` 将所有旧首页回退收敛为 `plan`，并删除只服务首页的高度适配代码；`styles.css` 保留欢迎文字视觉规则，新增受限的功能页欢迎区间距，不改动既有双栏、移动端和结果区滚动规则。

**技术栈：** 原生 HTML、CSS、JavaScript、既有 `showView()`、浏览器手工回归。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `frontend/index.html` | 删除 `view-home`；在行程规划和攻略查询视图中各加入一致的欢迎语区。 |
| `frontend/app.js` | 将品牌、清空记录、删除当前任务的回退目标改为 `plan`；删除首页高度适配逻辑。 |
| `frontend/styles.css` | 移除 `#view-home` 专属规则；为 `.feature-page` 内的欢迎语区设置间距，保持原欢迎文字视觉。 |
| `docs/superpowers/specs/2026-08-24-workspace-welcome-integration-design.md` | 记录实现完成与验证结果。 |

## 任务 1：迁移欢迎语并删除空白首页

**文件：**
- 修改：`frontend/index.html:91-215`

- [ ] **步骤 1：建立失败的结构检查基线**

运行：

```bash
python -c "from pathlib import Path; import re; html=Path('frontend/index.html').read_text(encoding='utf-8'); assert 'id=\"view-home\"' not in html; assert html.count('欢迎使用智能文旅策划助手') == 2"
```

预期：失败，因为当前文件仍存在 `view-home`，且欢迎语仅出现一次。

- [ ] **步骤 2：删除 `view-home` 整个 section**

移除以下内部首页节点及其所有子节点：

```html
<section id="view-home" class="view active">
  <div class="home">
    <div class="home-welcome">...</div>
  </div>
</section>
```

不得删除 `view-plan`、`view-guide`、`view-task`、`view-dashboard` 或 `view-library`。

- [ ] **步骤 3：在两个功能页各插入原欢迎语区**

在 `view-plan > .feature-page` 和 `view-guide > .feature-page` 的首个子节点位置，各插入以下完全一致的结构和文案：

```html
<div class="home-welcome">
  <div class="home-eyebrow">企业级智能文旅工作台</div>
  <h2>欢迎使用智能文旅策划助手</h2>
  <p>统一入口承载出行规划、数字人服务与目的地知识检索</p>
</div>
```

这两个 DOM 片段必须在对应的 `.feature-page-head` 前；不增加 id，避免重复 id。

- [ ] **步骤 4：运行结构检查确认通过**

运行：

```bash
python -c "from pathlib import Path; import re; html=Path('frontend/index.html').read_text(encoding='utf-8'); assert 'id=\"view-home\"' not in html; assert html.count('欢迎使用智能文旅策划助手') == 2; assert html.count('企业级智能文旅工作台') == 2; assert html.count('统一入口承载出行规划、数字人服务与目的地知识检索') == 2; plan=re.search(r'<section id=\"view-plan\".*?</section>', html, re.S).group(0); guide=re.search(r'<section id=\"view-guide\".*?</section>', html, re.S).group(0); assert plan.index('home-welcome') < plan.index('feature-page-head'); assert guide.index('home-welcome') < guide.index('feature-page-head'); print('欢迎语结构验证通过')"
```

预期：输出 `欢迎语结构验证通过`。

- [ ] **步骤 5：Commit**

```bash
git add frontend/index.html
git commit -m "feat: show workspace welcome on feature views"
```

## 任务 2：收敛默认回退行为并删除首页适配

**文件：**
- 修改：`frontend/app.js:60-105, 388-418, 1135-1168`

- [ ] **步骤 1：确认旧首页回退调用**

运行：

```bash
grep -n 'showView("home")' frontend/app.js
```

预期：至少匹配品牌返回、清空记录或删除当前记录中的旧首页回退调用。

- [ ] **步骤 2：将所有旧首页回退改为行程规划**

在以下行为中使用 `showView("plan")`：

1. `showIntro()` 中从介绍页进入工作台后的默认视图；
2. `clearTasks()` 清空查询记录后；
3. `doDelete()` 删除当前任务后。

对于 `showIntro()`：在恢复工作台可见、移除 inert 属性后调用 `showView("plan")`，确保 `activeView` 与实际激活视图一致；调用位置必须在 `main.focus()` 前。

保留 `resetPlanForm()` 已有的 `showView("plan")`，不得改动任务结果成功跳转、攻略检索代际失效或 dashboard/library 加载逻辑。

- [ ] **步骤 3：删除只服务首页的视口适配函数与调用**

删除完整的 `fitWorkbenchToViewport()` 函数、`workbenchFitScheduled` 变量、`MutationObserver(fitWorkbenchToViewport)`、`window.addEventListener("resize", fitWorkbenchToViewport)` 和所有直接调用。

删除后，`startExperience()` 不得调用已删除的函数。保留 `.main` 的现有正常滚动语义，由 CSS 控制功能页高度。

- [ ] **步骤 4：验证 JavaScript 行为边界**

运行：

```bash
node --check frontend/app.js
grep -nE 'showView\("(home|plan)"\)|fitWorkbenchToViewport|view-home' frontend/app.js
```

预期：语法检查通过；输出中没有 `showView("home")`、`fitWorkbenchToViewport` 或 `view-home`，并保留期望的 `showView("plan")` 回退调用。

- [ ] **步骤 5：Commit**

```bash
git add frontend/app.js
git commit -m "fix: default workspace navigation to planning"
```

## 任务 3：调整欢迎语容器样式并完成回归验证

**文件：**
- 修改：`frontend/styles.css:150-190`
- 修改：`docs/superpowers/specs/2026-08-24-workspace-welcome-integration-design.md`

- [ ] **步骤 1：确认首页专用样式当前存在**

运行：

```bash
grep -nE '#view-home|\.home \{' frontend/styles.css
```

预期：匹配 `#view-home.active` 和 `.home` 规则。

- [ ] **步骤 2：移除首页专用规则，保留欢迎文字视觉规则**

删除：

```css
#view-home.active { min-height: 0; }
.home { max-width: 1080px; margin: 0 auto; padding-top: 8px; }
```

保留以下既有选择器的字体、颜色、间距声明：

```css
.home-welcome { ... }
.home-eyebrow { ... }
.home-welcome h2 { ... }
.home-welcome p { ... }
```

新增仅用于功能页内的受控间距：

```css
.feature-page > .home-welcome { margin-bottom: 24px; }
```

不得调整 `.feature-page-head`、`.feature-split`、`.feature-visual`、`.feature-action`、`.knowledge-panel` 的既有布局或滚动规则。

- [ ] **步骤 3：静态验证欢迎页删除与样式边界**

运行：

```bash
python -c "from pathlib import Path; import re; html=Path('frontend/index.html').read_text(encoding='utf-8'); css=Path('frontend/styles.css').read_text(encoding='utf-8'); assert 'id=\"view-home\"' not in html; assert '#view-home' not in css; assert html.count('欢迎使用智能文旅策划助手') == 2; assert '.feature-page > .home-welcome' in css; print('欢迎语集成静态验证通过')"
node --check frontend/app.js
git diff --check
```

预期：输出 `欢迎语集成静态验证通过`，JavaScript 与差异检查均通过。

- [ ] **步骤 4：浏览器手工回归**

启动当前项目的 FastAPI 服务后检查：

1. 点击进入工作台直接进入行程规划，不存在空白首页；
2. 行程规划与攻略查询都显示完整欢迎语区，随后才显示各自标题和双栏内容；
3. 点击顶部品牌、清空记录、删除当前任务后进入行程规划；
4. 行程表单提交和失败回退仍显示行程规划；
5. 攻略查询、数字人占位、桌面双栏、窄屏纵向堆叠、数据看板、文档库与任务结果页正常；
6. 浏览器控制台没有 JavaScript 错误。

- [ ] **步骤 5：更新规格状态与验证记录**

把规格第 4 行改为：

```markdown
**状态：** 已实现并完成前端回归验证
```

并在末尾追加：

```markdown
## 6. 实现验证

已执行：`node --check frontend/app.js`、欢迎语集成静态验证、`git diff --check`，以及桌面端和窄屏的浏览器回归。
```

- [ ] **步骤 6：Commit**

```bash
git add frontend/styles.css docs/superpowers/specs/2026-08-24-workspace-welcome-integration-design.md
git commit -m "docs: record workspace welcome integration verification"
```
