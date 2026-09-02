# 行程规划智能化与方案制定实现计划

> **面向 AI 代理的工作者：** 按任务顺序实现，每项先补失败测试，再写最少实现。

**目标：** 将行程规划升级为自然语言解析、RAG 融合和可编辑保存方案闭环。

**架构：** FastAPI 新增 query 解析与方案记录边界；编排器接收结构化请求和知识上下文；原生前端移除攻略查询视图并增加方案制定与 AI 修改交互。

**技术栈：** FastAPI、Pydantic、现有 DeepSeek/RAG 服务、SQLite/现有记录存储、原生 HTML/CSS/JavaScript。

---

### 任务 1：自然语言需求解析与缺失字段合同

**文件：**
- 创建：`backend/app/models/planning.py`
- 修改：`backend/app/api/travel.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_planning_api.py`

- [x] 定义 `TravelQueryParseRequest/Response`，必填字段为 origin、destination、departure_date、travelers、days。
- [x] 增加 `POST /api/travel-plans/parse`，调用现有 DeepSeek 服务并校验结构化结果。
- [x] 为模型失败、JSON 无法解析、字段歧义返回受控错误。
- [ ] 运行解析 API 与模型合同测试（环境缺少依赖，暂未执行）。

### 任务 2：RAG 融入旅行规划编排

**文件：**
- 创建：`backend/app/services/travel_knowledge.py`
- 修改：`backend/app/orchestration/sequential.py`
- 修改：`backend/app/agents/route.py`
- 测试：`backend/tests/test_travel_knowledge.py`、`backend/tests/test_orchestrator.py`

- [ ] 按目的地、日期、人群和偏好调用现有知识检索服务。
- [ ] 命中时将受控片段与来源传入路线/汇总上下文；未命中时保留多 Agent 生成路径。
- [ ] 偏好进入路线、住宿和餐饮 Agent 的约束。
- [ ] 保留现有来源、降级和追踪标识合同。

### 任务 3：方案保存、查询和版本修改 API

**文件：**
- 创建：`backend/app/services/travel_plan_store.py`
- 修改：`backend/app/api/travel.py`
- 测试：`backend/tests/test_travel_plan_store.py`、`backend/tests/test_planning_api.py`

- [x] 持久化原始 query、结构化请求、TravelPlanDocument、版本和更新时间。
- [x] 增加方案列表/详情接口。
- [x] 增加 `POST /api/travel-plans/{plan_id}/revisions`，解析修改意图并重新运行必要 Agent。
- [x] 使用版本条件校验，失败不覆盖旧版本。

### 任务 4：前端自然语言规划与方案制定

**文件：**
- 修改：`frontend/index.html`
- 修改：`frontend/app.js`
- 修改：`frontend/styles.css`
- 测试：`backend/tests/test_frontend_assets.py`

- [x] 将固定表单替换为多行自然语言输入和解析状态。
- [x] 缺失/歧义字段使用弹窗提示；不发起规划请求。
- [x] 删除“攻略查询”导航和独立视图，保留文档库。
- [x] 新增“方案制定”导航、方案列表、详情和 AI 修改区。
- [x] 修改成功后同步详情、列表摘要和查询记录。

### 任务 5：回归验证

- [ ] 运行新增测试和全量 `pytest`（依赖环境阻断）。
- [x] 运行 `node --check frontend/app.js` 与 `git diff --check`。
- [ ] 核对安全渲染、来源追踪、失败降级和历史版本不丢失。
