# 门票查询 UI 布局优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将门票查询表单从窄单列改为与现有工作台适配的宽卡片双列布局，同时保持查询字段、接口和交互行为不变。

**架构：** 仅调整门票查询视图的 HTML 容器结构和 CSS。三个现有字段在桌面端横向排列，查询按钮右对齐；在 768px 以下回退为单列。服务状态、同意弹窗、结果区域和现有 JavaScript ID 全部保持不变。

**技术栈：** 原生 HTML、CSS、现有 FastAPI 静态前端、pytest 前端资源断言。

---

## 文件清单

- 修改：`frontend/index.html:210-226`，为现有门票表单增加卡片容器和字段分组，不改变既有字段 ID/name。
- 修改：`frontend/styles.css:159-170`，增加门票查询卡片、三列字段和响应式规则，沿用现有颜色令牌、圆角和阴影。
- 修改：`backend/tests/test_frontend_assets.py`，增加结构断言，确保方案 A 的卡片和字段分组存在且业务接口标记未被删除。

### 任务 1：增加门票查询卡片结构

**文件：**
- 修改：`frontend/index.html:217-225`
- 测试：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：添加结构断言**

在 `test_frontend_uses_ticket_query_view` 中增加以下断言，锁定布局结构而非像素值：

```python
assert 'class="ticket-query-card"' in html
assert 'class="ticket-query-fields"' in html
assert 'class="ticket-query-actions"' in html
assert 'class="ticket-query-field scenic"' in html
```

- [ ] **步骤 2：运行前端资源测试确认失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py::test_frontend_uses_ticket_query_view -q
```

预期：FAIL，因新布局类尚不存在。

- [ ] **步骤 3：实现最少 HTML 结构**

将原有表单改为以下结构，保留所有现有表单控件属性、`id`、`name` 和提交按钮：

```html
<div class="ticket-query-card">
  <form id="ticket-form" class="fliggy-form">
    <div class="ticket-query-fields">
      <label class="ticket-query-field scenic">景点关键词<input id="ticket-scenic-keyword" name="scenic_keyword" maxlength="100" placeholder="例如：西湖" required></label>
      <label class="ticket-query-field">入园日期<input id="ticket-entry-date" name="entry_date" type="date" required></label>
      <label class="ticket-query-field">游客人数<input id="ticket-visitor-count" name="visitor_count" type="number" min="1" max="20" value="1" required></label>
    </div>
    <div class="ticket-query-actions">
      <button id="ticket-submit" class="btn-primary" type="submit" disabled>查询门票</button>
    </div>
  </form>
</div>
```

- [ ] **步骤 4：运行测试确认结构断言通过**

运行同步骤 2 命令，预期：PASS。

- [ ] **步骤 5：提交结构变更**

用户未要求提交，故不执行 git commit；保留工作区变更供后续统一审阅。

### 任务 2：实现宽卡片双列视觉样式

**文件：**
- 修改：`frontend/styles.css:159-170` 和响应式区块

- [ ] **步骤 1：替换门票表单布局样式**

使用现有设计令牌实现以下规则：

```css
.fliggy-page { max-width: 960px; }
.ticket-query-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 18px;
  padding: 22px; box-shadow: var(--shadow);
}
.fliggy-form { display: grid; gap: 16px; }
.ticket-query-fields { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(150px, 1fr) minmax(110px, .72fr); gap: 12px; }
.ticket-query-field { display: grid; gap: 7px; color: var(--text-dim); font-size: 13px; }
.ticket-query-field input { width: 100%; box-sizing: border-box; }
.ticket-query-actions { display: flex; justify-content: flex-end; padding-top: 2px; }
```

保留 `.fliggy-status`、`.fliggy-results`、`.fliggy-ticket-card` 和 `.fliggy-notice` 的现有业务展示规则。

- [ ] **步骤 2：添加窄屏回退规则**

在 `@media (max-width: 768px)` 中加入：

```css
.ticket-query-fields { grid-template-columns: 1fr; }
.ticket-query-actions .btn-primary { width: 100%; }
```

- [ ] **步骤 3：运行静态检查**

运行：

```powershell
git diff --check
node --check frontend/app.js
```

预期：两个命令退出码均为 0。

### 任务 3：回归验证门票界面

**文件：**
- 验证：`frontend/index.html`、`frontend/styles.css`、`frontend/app.js`
- 测试：`backend/tests/test_frontend_assets.py`

- [ ] **步骤 1：运行前端资源测试**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"
python -m pytest -c backend/pytest.ini backend/tests/test_frontend_assets.py -q
```

预期：全部通过。

- [ ] **步骤 2：验证服务端仍能提供最新静态页面**

运行：

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -UseBasicParsing | Select-Object -ExpandProperty StatusCode
```

预期：输出 `200`。

- [ ] **步骤 3：检查变更范围**

运行：

```powershell
git diff --stat
git diff -- frontend/index.html frontend/styles.css backend/tests/test_frontend_assets.py
```

确认只涉及门票查询 UI 结构、样式和对应静态断言，不改查询接口和业务脚本。
