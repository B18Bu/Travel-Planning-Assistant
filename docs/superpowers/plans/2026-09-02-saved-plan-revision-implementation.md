# 已保存方案修订实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让用户选择一条已保存方案后输入修改描述，由 AI 生成新版本，并支持删除与状态保持。

**架构：** 存储层提供原子删除，API 暴露删除接口；前端以单个两步弹窗管理方案选择和修订输入。修订成功刷新当前工作台，关闭弹窗仅关闭遮罩。

**技术栈：** Python 3、FastAPI、原生 HTML/CSS/JavaScript、pytest、httpx。

---

## 文件结构

- 修改：`backend/app/services/travel_plan_store.py`、`backend/app/api/travel.py`。
- 创建：`backend/tests/test_travel_plan_store.py`、`backend/tests/test_travel_plan_revisions.py`。
- 修改：`frontend/index.html`、`frontend/app.js`、`frontend/styles.css`。
- 修改：`backend/tests/test_frontend_assets.py` — 保持现有静态资源回归策略。

### 任务 1：保存方案删除接口

**文件：** `backend/app/services/travel_plan_store.py`、`backend/app/api/travel.py`、`backend/tests/test_travel_plan_store.py`、`backend/tests/test_travel_plan_revisions.py`

- [ ] 编写失败测试：保存两条记录后 `delete(plan_id)` 仅删除目标；API `DELETE /api/travel-plans/saved/{plan_id}` 返回成功，缺失 ID 返回 404。
- [ ] 运行：`cd backend; pytest tests/test_travel_plan_store.py tests/test_travel_plan_revisions.py -q`，预期失败。
- [ ] 最少实现：`TravelPlanStore.delete(plan_id) -> bool` 在锁内重写记录；路由只在成功删除时返回 204。
```python
@router.delete("/travel-plans/saved/{plan_id}", status_code=204)
async def delete_saved_travel_plan(plan_id: str, request: Request) -> None:
    if not request.app.state.travel_plan_store.delete(plan_id):
        raise HTTPException(status_code=404, detail="方案不存在")
```
- [ ] 重跑测试，预期通过；提交 `feat: 支持删除已保存旅行方案`。

### 任务 2：修订接口完整回归

**文件：** `backend/tests/test_travel_plan_revisions.py`、`backend/app/api/travel.py`

- [ ] 编写失败测试：选定 ID 和当前版本时创建 `version + 1`；不存在返回 404、旧版本返回 409、解析后缺字段返回 422。
- [ ] 运行：`cd backend; pytest tests/test_travel_plan_revisions.py -q`，预期失败。
- [ ] 最少实现：保留现有 `POST .../revisions` 语义，补全受控异常并确保 `new_request` 带有解析出的画像。
- [ ] 重跑测试，预期通过；提交 `test: 覆盖方案修订版本和异常`。

### 任务 3：两步选择与修订弹窗

**文件：** `frontend/index.html`、`frontend/app.js`、`frontend/styles.css`、`backend/tests/test_frontend_assets.py`

- [ ] 编写失败静态断言：页面包含修订弹窗、步骤提示、方案列表、带 label 的描述字段、确认删除弹窗；脚本包含方案选择状态、禁用提交、404/409/422 中文恢复文案与 `DELETE` 请求。
- [ ] 运行：`cd backend; pytest tests/test_frontend_assets.py -q`，预期失败。
- [ ] 最少实现：删除页面中裸露的输入框；新增 `selectedSavedPlan`、`openRevisionModal()`、`selectSavedPlan()`、`updateRevisionSubmitState()` 与 `deleteSavedPlan()`。第一步加载方案列表并选择，第二步输入后调用既有修订接口。
```javascript
revisionSubmit.disabled = !selectedSavedPlan || !revisionQuery.value.trim() || revisionSubmitting;
```
- [ ] CSS 使用已有 modal token，增加 44px 最小操作高度、可见 `:focus-visible`、两步状态及危险删除按钮。
- [ ] 重跑测试，预期通过；提交 `feat: 增加选择式方案 AI 修订界面`。

### 任务 4：工作台状态与浏览器验证

**文件：** `frontend/app.js`、`backend/tests/test_frontend_assets.py`

- [ ] 编写失败断言：`closeTravelModal` 不调用 `showView`；修订成功在当前视图渲染文档后关闭修订弹窗；焦点回到触发按钮。
- [ ] 运行：`cd backend; pytest tests/test_frontend_assets.py -q`，预期失败。
- [ ] 最少实现：保存 `revisionTrigger`，关闭时只移除 `show` 并恢复焦点；成功刷新列表并使用当前 `activeView` 展示结果，不将视图切为独立白屏任务页。
- [ ] 重跑测试，预期通过；提交 `fix: 保持方案修订后的工作台状态`。

### 任务 5：本地验收与推送

- [ ] 运行：`cd backend; pytest tests/test_travel_plan_store.py tests/test_travel_plan_revisions.py tests/test_frontend_assets.py -q`。
- [ ] 提交并推送：`git push origin master:main`。
- [ ] 再启动本地服务，浏览器按“选择方案 → 填写描述 → 生成新版本 → 关闭结果”验证；确认删除后列表刷新且页面未白屏。
