# 用户偏好画像实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将老人、儿童和饮食偏好解析为确定性约束，并贯穿行程生成与最终摘要。

**架构：** 在旅行请求模型中新增不可变的 `TravelPreferenceProfile`，由解析模型提取并经编排器传给各 Agent。代码只校验受控 JSON、执行模型输出禁止项的通用文本过滤并在模型失败时显式降级；路线、餐饮和摘要使用模型产生的 Agent 指导。

**技术栈：** Python 3、FastAPI、Pydantic、pytest。

---

## 文件结构

- 修改：`backend/app/models/travel.py`、`backend/app/models/planning.py` — 画像合同、规划请求与解析响应字段。
- 修改：`backend/app/services/query_parser.py` — 规则识别和画像构造。
- 修改：`backend/app/agents/weather.py`、`route.py`、`food.py`、`lodging.py`、`summary.py` — 画像指导、来源融合与富内容返回。
- 修改：`backend/app/orchestration/sequential.py` — 画像完整传递与最终合规校验。
- 修改：`backend/app/orchestration/sequential.py` — 最终合规校验与摘要入参。
- 修改：`backend/tests/test_query_parser.py`、`test_agents_weather_route.py`、`test_summary.py`。
- 创建：`backend/tests/test_food_preferences.py` — 餐饮硬约束回归测试。

### 任务 1：模型优先的画像合同与解析

**文件：** `backend/app/models/travel.py`、`backend/app/models/planning.py`、`backend/app/services/query_parser.py`、`backend/tests/test_query_parser.py`

- [ ] 编写失败测试：模拟模型返回儿童老人、清真饮食及未预设的“摄影友好”偏好，断言其被完整保留；模型失败时断言画像为空且含“偏好理解暂不可用”提示。
```python
assert result.profile.summary == "亲子和摄影友好行程"
assert result.profile.preferences[0].instruction == "优先儿童互动体验"
assert result.profile.preferences[1].instruction == "摄影友好"
```
- [ ] 运行：`cd backend; pytest tests/test_query_parser.py -q`，预期画像属性不存在而失败。
- [ ] 最少实现：增加冻结 `TravelPreferenceProfile`、`PreferenceItem` 与 `AgentGuidance`；在模型提示中声明 JSON Schema，在 `TravelPlanRequest` 和 `TravelQueryParseResponse` 中声明 `profile`；解析服务仅校验模型输出并将其原样传递。前端以解析响应中的 `profile` 原样提交。
```python
class TravelPreferenceProfile(StrictModel):
    summary: NonEmptyText | None = None
    companions: tuple[Companion, ...] = ()
    preferences: tuple[PreferenceItem, ...] = ()
    agent_guidance: AgentGuidance = Field(default_factory=AgentGuidance)
    verification_notes: tuple[NonEmptyText, ...] = ()
```
- [ ] 重跑同一命令，预期通过；提交 `feat: 增加旅行偏好画像解析`。

### 任务 2：按模型路线指导调整密度与排序

**文件：** `backend/app/agents/route.py`、`backend/tests/test_agents_weather_route.py`

- [ ] 编写失败测试：模型返回“每日两个主要时段”和“亲子互动优先”指导时，路线采用对应密度与排序；未预设偏好仍出现在路线约束说明中。
- [ ] 运行：`cd backend; pytest tests/test_agents_weather_route.py -q`，预期失败。
- [ ] 最少实现：由模型生成的路线指导提供时段上限和排序关键词；路线 Agent 不解析老人或儿童词表。
```python
slots = request.profile.agent_guidance.route_slots or ("上午", "下午", "傍晚")
```
- [ ] 重跑同一命令，预期通过；提交 `feat: 按同行人群调整路线密度`。

### 任务 3：通用餐饮禁止项过滤与核验提示

**文件：** `backend/app/agents/food.py`、`backend/app/agents/lodging.py`、`backend/tests/test_food_preferences.py`

- [ ] 编写失败测试：模型输出任意 `exclude_terms` 后，候选的名称、菜系、标签或特色命中时被移除；需核验偏好为未知候选添加确认提示。
- [ ] 运行：`cd backend; pytest tests/test_food_preferences.py -q`，预期失败。
- [ ] 最少实现：集中 `is_food_candidate_allowed()` 和 `preference_verification_notes()`，只依据模型提供的禁止项对候选文本做通用匹配；住宿只增加不虚构设施的模型指导。
```python
if any(term.casefold() in text.casefold() for term in exclude_terms):
    return False
```
- [ ] 重跑同一命令，预期通过；提交 `feat: 过滤明确饮食冲突餐饮`。

### 任务 4：最终合规校验与摘要

**文件：** `backend/app/orchestration/sequential.py`、`backend/app/agents/summary.py`、`backend/tests/test_summary.py`、`backend/tests/test_orchestrator.py`

- [ ] 编写失败测试：即使餐饮 Agent 返回模型禁止项命中的候选，编排结果也不包含它；摘要完整展示模型提取的偏好、响应情况和待确认说明。
- [ ] 运行：`cd backend; pytest tests/test_summary.py tests/test_orchestrator.py -q`，预期失败。
- [ ] 最少实现：在 `SummaryAgent.run` 增加 `profile` 入参；编排器在汇总前替换餐饮数据中的冲突候选，摘要使用画像字段生成确定性条目。
```python
document = self.summary_agent.run(weather, route, lodging, food, request.profile, request_id, trace_id)
```
- [ ] 重跑同一命令，预期通过；提交 `feat: 在摘要中展示偏好合规信息`。

### 任务 5：飞猪 AI 与高德的住宿/餐饮融合

**文件：** `backend/app/agents/lodging.py`、`backend/app/agents/food.py`、`backend/app/agents/summary.py`、`backend/tests/test_flyai_hotel_recommendation.py`、`backend/tests/test_food_preferences.py`

- [ ] 编写失败测试：高德与飞猪 AI 同时成功时合并真实字段；高德失败时保留飞猪候选并标记位置待核验；飞猪失败时保留高德候选并标记价格评分待核验；两侧失败时无候选。
- [ ] 最少实现：住宿 Agent 注入既有 `FlyAIHotelRecommendationService`，以入住离店日期和画像指导查询；餐饮高德无候选时使用受控飞猪文本补充，所有返回字段保留来源与核验说明。
- [ ] 重跑：`cd backend; pytest tests/test_flyai_hotel_recommendation.py tests/test_food_preferences.py -q`；提交 `feat: 融合飞猪与高德旅行候选`。

### 任务 5：关联验证

- [ ] 运行：`cd backend; pytest tests/test_query_parser.py tests/test_agents_weather_route.py tests/test_food_preferences.py tests/test_summary.py tests/test_orchestrator.py -q`。
- [ ] 预期：新增及关联测试全绿；若完整套件因既有过期日期失败，记录失败文件与原因，不修改无关夹具。
- [ ] 提交并推送已验证实现：`git push origin master:main`。
