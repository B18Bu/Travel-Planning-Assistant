# 用户偏好画像实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将老人、儿童和饮食偏好解析为确定性约束，并贯穿行程生成与最终摘要。

**架构：** 在旅行请求模型中新增不可变的 `TravelPreferenceProfile`，由解析服务构造并经编排器传给各 Agent。路线和餐饮执行确定性筛选，摘要展示响应与核验项，编排器在汇总前二次清理明确饮食冲突。

**技术栈：** Python 3、FastAPI、Pydantic、pytest。

---

## 文件结构

- 修改：`backend/app/models/travel.py` — 画像合同与请求字段。
- 修改：`backend/app/services/query_parser.py` — 规则识别和画像构造。
- 修改：`backend/app/agents/route.py`、`food.py`、`lodging.py`、`summary.py` — 约束执行与可核验提示。
- 修改：`backend/app/orchestration/sequential.py` — 最终合规校验与摘要入参。
- 修改：`backend/tests/test_query_parser.py`、`test_agents_weather_route.py`、`test_summary.py`。
- 创建：`backend/tests/test_food_preferences.py` — 餐饮硬约束回归测试。

### 任务 1：画像合同与确定性解析

**文件：** `backend/app/models/travel.py`、`backend/app/services/query_parser.py`、`backend/tests/test_query_parser.py`

- [ ] 编写失败测试：
```python
assert result.preferences == ("不吃辣", "清真", "不吃猪肉", "行程不要太赶")
assert result.profile.has_children is True
assert result.profile.has_elderly is True
assert result.profile.low_intensity is True
```
- [ ] 运行：`cd backend; pytest tests/test_query_parser.py -q`，预期画像属性不存在而失败。
- [ ] 最少实现：增加冻结 `TravelPreferenceProfile`；在 `TravelPlanRequest` 中声明 `profile`；在 `_rule_values` 识别“老人、儿童、清真、不吃猪肉、不吃辣、不要太赶”，并由单一 `build_preference_profile()` 映射字段。
```python
class TravelPreferenceProfile(StrictModel):
    has_children: bool = False
    has_elderly: bool = False
    low_intensity: bool = False
    child_friendly: bool = False
    no_spicy: bool = False
    no_pork: bool = False
    halal: bool = False
    verification_notes: tuple[NonEmptyText, ...] = ()
```
- [ ] 重跑同一命令，预期通过；提交 `feat: 增加旅行偏好画像解析`。

### 任务 2：路线密度与亲子排序

**文件：** `backend/app/agents/route.py`、`backend/tests/test_agents_weather_route.py`

- [ ] 编写失败测试：老人儿童请求在三天路线中每个 `DailyItinerary` 最多两项，且候选中存在“科技馆”时排在普通候选前。
- [ ] 运行：`cd backend; pytest tests/test_agents_weather_route.py -q`，预期失败。
- [ ] 最少实现：将固定时段替换为根据 `request.profile.low_intensity` 选择 `("上午", "下午")` 或完整时段；在候选排序键中对儿童关键词加权，明确高强度标签在低强度模式下过滤。
```python
slots = ("上午", "下午") if request.profile.low_intensity else ("上午", "下午", "傍晚")
```
- [ ] 重跑同一命令，预期通过；提交 `feat: 按同行人群调整路线密度`。

### 任务 3：餐饮过滤与核验提示

**文件：** `backend/app/agents/food.py`、`backend/app/agents/lodging.py`、`backend/tests/test_food_preferences.py`

- [ ] 编写失败测试：含“川菜”“麻辣”“火锅”或猪肉关键词的候选在 `no_spicy` / `no_pork` 请求中被移除；`halal` 请求的未知候选包含“需向商家确认”提示。
- [ ] 运行：`cd backend; pytest tests/test_food_preferences.py -q`，预期失败。
- [ ] 最少实现：集中 `is_food_candidate_allowed()` 和 `dietary_verification_notes()`，只依据候选名称、菜系、标签和特色字段做明确冲突判定；住宿只增加不虚构设施的筛选建议。
```python
if profile.no_spicy and any(word in text for word in SPICY_WORDS):
    return False
```
- [ ] 重跑同一命令，预期通过；提交 `feat: 过滤明确饮食冲突餐饮`。

### 任务 4：最终合规校验与摘要

**文件：** `backend/app/orchestration/sequential.py`、`backend/app/agents/summary.py`、`backend/tests/test_summary.py`、`backend/tests/test_orchestrator.py`

- [ ] 编写失败测试：即使餐饮 Agent 返回冲突候选，编排结果也不包含它；摘要含“已响应的用户偏好”和待确认说明。
- [ ] 运行：`cd backend; pytest tests/test_summary.py tests/test_orchestrator.py -q`，预期失败。
- [ ] 最少实现：在 `SummaryAgent.run` 增加 `profile` 入参；编排器在汇总前替换餐饮数据中的冲突候选，摘要使用画像字段生成确定性条目。
```python
document = self.summary_agent.run(weather, route, lodging, food, request.profile, request_id, trace_id)
```
- [ ] 重跑同一命令，预期通过；提交 `feat: 在摘要中展示偏好合规信息`。

### 任务 5：关联验证

- [ ] 运行：`cd backend; pytest tests/test_query_parser.py tests/test_agents_weather_route.py tests/test_food_preferences.py tests/test_summary.py tests/test_orchestrator.py -q`。
- [ ] 预期：新增及关联测试全绿；若完整套件因既有过期日期失败，记录失败文件与原因，不修改无关夹具。
- [ ] 提交并推送已验证实现：`git push origin master:main`。
