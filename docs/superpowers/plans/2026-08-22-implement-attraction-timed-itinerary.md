# 景区级时段行程实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将每日活动区域升级为天气驱动的景区级时段行程，并为午餐和晚餐返回对应景区周边的真实高德餐馆候选。

**架构：** Weather Agent 确定性输出每日提醒和室内优先标志；Route Agent 按天气搜索景区、分配上午/下午/傍晚、查询相邻景区驾车预估；Food Agent 接收 `daily_itineraries`，围绕上午与傍晚（回退下午）景区坐标查询附近餐饮。全程不使用 LLM，不引入评分、招牌菜、开放时间等未授权事实。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、httpx、respx、pytest、现有和风天气/高德地图 API。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `backend/app/models/travel.py` | 定义时段景区、每日行程、天气提醒与午晚餐合同。 |
| `backend/app/services/amap.py` | 新增固定 Host 的高德附近 POI 查询。 |
| `backend/app/agents/weather.py` | 生成确定性的天气提醒与室内优先标志。 |
| `backend/app/agents/route.py` | 查询天气匹配的景区，生成时段和相邻驾车预估。 |
| `backend/app/agents/food.py` | 根据景区坐标查询午餐、晚餐附近餐饮。 |
| `backend/app/orchestration/sequential.py` | 将 `daily_itineraries` 传给 Food Agent。 |
| `backend/app/agents/summary.py` | 渲染每日提醒、景区时段、通勤、午晚餐。 |
| `backend/tests/test_models.py` | 覆盖新模型与合同边界。 |
| `backend/tests/test_amap.py` | 覆盖附近 POI 客户端、缓存和输入校验。 |
| `backend/tests/test_agents_weather_route.py` | 覆盖天气提醒、室内切换、景区排程、通勤降级。 |
| `backend/tests/test_agents_poi.py` | 覆盖景区附近午餐/晚餐、餐饮降级。 |
| `backend/tests/test_orchestration.py` | 覆盖 `daily_itineraries` 向 Food Agent 的传递。 |
| `backend/tests/test_summary.py` | 覆盖时段行程 Markdown 与未授权字段边界。 |
| `README.md` | 更新已实现能力、数据来源、输入输出与限制。 |

---

### 任务 1：扩展旅行数据合同

**文件：**
- 修改：`backend/app/models/travel.py:131-220`
- 测试：`backend/tests/test_models.py`

- [ ] **步骤 1：编写失败测试**

新增模型测试，明确每天最多三个时段、时段受限、天气提醒不可为空、餐饮只允许午餐/晚餐：

```python
def test_timed_itinerary_contract_limits_slots_and_requires_reminder():
    attraction = {
        "time_slot": "上午",
        "poi": {"name": "故宫", "category": "风景名胜", "source_ids": ["amap:attraction"]},
        "suggested_duration_minutes": 120,
    }
    itinerary = DailyItinerary(day=1, weather_reminder="天气晴，注意防晒补水。", attractions=(attraction,))

    assert itinerary.attractions[0].time_slot == "上午"
    with pytest.raises(ValueError):
        DailyItinerary(day=1, weather_reminder="", attractions=())
    with pytest.raises(ValueError):
        DailyItinerary(day=1, weather_reminder="提醒", attractions=(attraction,) * 4)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_models.py -q`

预期：FAIL，原因是 `DailyItinerary` 与 `TimedAttraction` 尚未定义。

- [ ] **步骤 3：实现最小模型变更**

在 `DailyWeather` 添加：

```python
travel_reminder: NonEmptyText
indoor_preferred: bool
```

新增：

```python
class TimedAttraction(StrictModel):
    time_slot: Literal["上午", "下午", "傍晚"]
    poi: PoiCandidate
    suggested_duration_minutes: int = Field(ge=1)
    activity_note: str | None = None
    travel_to_next: RouteEstimate | None = None

class DailyItinerary(StrictModel):
    day: int = Field(ge=1)
    weather_reminder: NonEmptyText
    attractions: tuple[TimedAttraction, ...] = Field(max_length=3)
    missing_fields: tuple[NonEmptyText, ...] = ()
```

扩展 `RoutePlanData`：

```python
daily_itineraries: tuple[DailyItinerary, ...] = Field(min_length=1)
```

扩展 `DailyFoodPlan`：

```python
meal_period: Literal["午餐", "晚餐"] | None = None
nearby_attraction_name: NonEmptyText | None = None
```

更新所有已有测试构造的 `DailyWeather`、`RoutePlanData`，为常规天气提供 `travel_reminder="天气待核验。"`、`indoor_preferred=False`，并提供包含空 `attractions` 的 `DailyItinerary`。

- [ ] **步骤 4：运行模型测试验证通过**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_models.py -q`

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/models/travel.py backend/tests/test_models.py backend/tests
git commit -m "feat: add timed attraction itinerary contracts"
```

---

### 任务 2：增加高德附近 POI 服务能力

**文件：**
- 修改：`backend/app/services/amap.py:54-130`
- 修改：`backend/tests/test_amap.py`

- [ ] **步骤 1：编写失败测试**

新增 `test_nearby_poi_uses_fixed_endpoint_and_radius`：

```python
route = respx.get(f"{BASE}/v5/place/around").mock(return_value=httpx.Response(
    200,
    json={"status": "1", "pois": [{"name": "餐馆", "address": "景区路", "location": "116.4,39.9", "type": "餐饮服务;中餐厅"}]},
))
result = await client().search_nearby_poi("餐饮服务", "116.4,39.9", 2000)
assert route.calls[0].request.url.params["location"] == "116.4,39.9"
assert route.calls[0].request.url.params["radius"] == "2000"
assert result[0]["name"] == "餐馆"
```

另加参数化测试，拒绝空坐标、半径 `0`、负数、布尔和非整数。

- [ ] **步骤 2：运行测试验证失败**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_amap.py -q`

预期：FAIL，原因是 `AmapClient.search_nearby_poi` 尚未定义。

- [ ] **步骤 3：实现最小客户端方法**

新增：

```python
async def search_nearby_poi(self, keywords: str, location: str, radius_meters: int) -> list[dict[str, Any]]:
    self._require_text(keywords, "高德地图请求关键词无效")
    self._require_text(location, "高德地图请求坐标无效")
    if not isinstance(radius_meters, int) or isinstance(radius_meters, bool) or radius_meters <= 0:
        raise ExternalServiceUnavailable("高德地图请求半径无效")
    result = await self._get(
        "nearby_poi", [keywords, location, str(radius_meters)], "/v5/place/around",
        {"keywords": keywords, "location": location, "radius": str(radius_meters)},
        self.poi_cache_ttl_seconds,
    )
    # 与 search_poi 相同的列表和白名单字段验证、元数据投影。
```

将 `_project` 的 POI 分支改为同时接受 `/v5/place/text` 与 `/v5/place/around`：

```python
if path not in {"/v5/place/text", "/v5/place/around"}:
    raise ExternalServiceUnavailable("高德地图未返回有效数据")
```

- [ ] **步骤 4：运行服务测试验证通过**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_amap.py -q`

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services/amap.py backend/tests/test_amap.py
git commit -m "feat: add amap nearby poi search"
```

---

### 任务 3：生成每日天气提醒与室内优先规则

**文件：**
- 修改：`backend/app/agents/weather.py:22-127`
- 修改：`backend/tests/test_agents_weather_route.py`

- [ ] **步骤 1：编写失败测试**

新增：

```python
def test_weather_agent_marks_high_risk_day_indoor_and_adds_actionable_reminder():
    result = __import__("asyncio").run(agent_for_condition("高温").run(request(days=1), **ids()))

    daily = result.data.daily[0]
    assert daily.indoor_preferred is True
    assert "防晒补水" in daily.travel_reminder
    assert result.constraints
```

再新增晴天用例，断言 `indoor_preferred is False` 且提醒包含“关注天气变化”。

- [ ] **步骤 2：运行测试验证失败**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_agents_weather_route.py -q`

预期：FAIL，原因是新字段不存在或值未满足断言。

- [ ] **步骤 3：实现确定性提醒函数**

新增：

```python
@staticmethod
def _travel_guidance(condition: str) -> tuple[str, bool]:
    if any(word in condition for word in ("暴雨", "台风", "强对流")):
        return "减少户外暴露，关注官方预警；当日优先室内文化场所。", True
    if "高温" in condition:
        return "注意防晒补水，避免长时间户外暴晒；当日优先室内文化场所。", True
    return "关注天气变化，按实际天气调整出游安排。", False
```

在 `_daily_item` 中调用该函数，并填充 `travel_reminder` 与 `indoor_preferred`。`_constraints` 与 `_warnings` 使用已生成的字段，避免重复硬编码。

- [ ] **步骤 4：运行 Agent 测试验证通过**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_agents_weather_route.py -q`

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/agents/weather.py backend/tests/test_agents_weather_route.py
git commit -m "feat: add actionable weather reminders for itinerary planning"
```

---

### 任务 4：Route Agent 生成景区时段与通勤预估

**文件：**
- 修改：`backend/app/agents/route.py`
- 修改：`backend/tests/test_agents_weather_route.py`

- [ ] **步骤 1：扩展测试替身与编写失败测试**

为 `FakeAmapClient` 增加：

```python
async def search_poi(self, keywords, city):
    self.calls.append(("search_poi", keywords, city))
    return self.poi_results[(keywords, city)]
```

新增常规天气用例：断言调用 `("search_poi", "风景名胜", "杭州市")`、每天按上午/下午/傍晚分配、候选多天不重复，且相邻坐标用于 `driving_route`。

新增高温用例：断言只依次查询 `博物馆`、`美术馆`、`展馆`，不得查询 `风景名胜`，每段 `activity_note` 含“室内文化场所”。

- [ ] **步骤 2：运行测试验证失败**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_agents_weather_route.py -q`

预期：FAIL，Route Agent 当前不调用景区 POI，且没有 `daily_itineraries`。

- [ ] **步骤 3：实现候选收集与时段分配**

在 `RouteAgent.run` 接收 `weather: AgentResult[WeatherPlanData]` 替代自由文本约束；编排器将在任务 6 同步更新调用。

实现辅助方法：

```python
_SLOTS = ("上午", "下午", "傍晚")
_INDOOR_KEYWORDS = ("博物馆", "美术馆", "展馆")

def _attraction_keywords(indoor_preferred: bool) -> tuple[str, ...]:
    return _INDOOR_KEYWORDS if indoor_preferred else ("风景名胜",)
```

每日期从候选池取尚未使用的最多 3 个 POI；每个 POI 转为 `PoiCandidate(source_ids=("amap:attraction",))`，每段设置 `suggested_duration_minutes=120`。对相邻景区调用 `driving_route` 并赋给前一段 `travel_to_next`；失败时保持 `None` 并增加 `route_day_{day}_travel_{index}` 缺失字段。

`daily_areas` 仍按当天第一个景区地址的行政区域不可得时用目的地名称；不要从地址推断行政区，直接保留 `destination["name"]` 作为兼容区域。

- [ ] **步骤 4：实现候选不足与天气缺失降级**

- 天气无对应日期：常规关键词，提醒为“天气待核验，请出行前确认。”；
- 候选不足：不复用，写 `route_day_{day}_attraction_{slot_index}`；
- 景区 POI 缺坐标：保留 POI，但不查通勤；
- 路线 Agent 仍维持 `RoutePlanData` 合同，候选不足时为 `partial`，完全无景区时为 `degraded`。

- [ ] **步骤 5：运行测试验证通过**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_agents_weather_route.py -q`

预期：PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/agents/route.py backend/tests/test_agents_weather_route.py
git commit -m "feat: build weather-aware timed attraction itineraries"
```

---

### 任务 5：Food Agent 基于景区坐标生成午餐和晚餐

**文件：**
- 修改：`backend/app/agents/food.py`
- 修改：`backend/tests/test_agents_poi.py`

- [ ] **步骤 1：编写失败测试**

把 `FoodAgent.run` 的输入改为 `daily_itineraries`，并新增：

```python
@pytest.mark.asyncio
async def test_food_uses_morning_attraction_for_lunch_and_evening_for_dinner():
    itineraries = (daily_itinerary(day=1, morning_location="120,30", evening_location="120.1,30.1"),)
    result = await FoodAgent(client).run(request(days=1), itineraries, REQUEST_ID, REQUEST_ID)

    assert client.nearby_calls == [
        ("餐饮服务", "120,30", 2000),
        ("餐饮服务", "120.1,30.1", 2000),
    ]
    assert [item.meal_period for item in result.data.daily_food] == ["午餐", "晚餐"]
    assert result.data.daily_food[0].nearby_attraction_name == "上午景区"
```

新增傍晚缺失时晚餐使用下午景区、附近 POI 无结果只缺对应餐段、非餐饮 POI 过滤的用例。

- [ ] **步骤 2：运行测试验证失败**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_agents_poi.py -q`

预期：FAIL，Food Agent 仍以 `daily_areas` 调用文本 POI 搜索。

- [ ] **步骤 3：实现附近餐饮排程**

将方法签名改为：

```python
async def run(self, request, daily_itineraries, request_id, trace_id) -> AgentResult[FoodPlanData]:
```

对每一天：

```python
lunch_attraction = _find_attraction(itinerary, "上午")
dinner_attraction = _find_attraction(itinerary, "傍晚") or _find_attraction(itinerary, "下午")
```

对每个可用景区坐标调用：

```python
await self.amap_client.search_nearby_poi("餐饮服务", attraction.poi.location, 2000)
```

保留首个类别匹配的餐馆；建立：

```python
DailyFoodPlan(
    day=itinerary.day,
    area=attraction.poi.address or request.destination,
    meal_period="午餐",
    nearby_attraction_name=attraction.poi.name,
    candidates=(candidate,),
)
```

当景区、坐标或附近候选缺失时，不调用不安全的替代搜索，分别写入 `food_day_{day}_lunch_*` 或 `food_day_{day}_dinner_*`，并保留官方核验提示。

- [ ] **步骤 4：运行 Food Agent 测试验证通过**

运行：`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_agents_poi.py -q`

预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/agents/food.py backend/tests/test_agents_poi.py
git commit -m "feat: recommend lunch and dinner near timed attractions"
```

---

### 任务 6：更新编排器和 Markdown 汇总

**文件：**
- 修改：`backend/app/orchestration/sequential.py:18-48`
- 修改：`backend/app/agents/summary.py:85-164`
- 修改：`backend/tests/test_orchestration.py`
- 修改：`backend/tests/test_summary.py`

- [ ] **步骤 1：编写失败测试**

在编排测试中断言：

```python
food.run.assert_awaited_once_with(request, route.data.daily_itineraries, request_id, trace_id)
```

在汇总测试中构造一个含上午故宫、下午天坛、午餐/晚餐和 `travel_to_next` 的文档，断言 Markdown 包含：

```python
assert "### 今日出游提醒" in document.markdown
assert "### 上午 · 故宫" in document.markdown
assert "建议游玩约 120 分钟" in document.markdown
assert "驾车约 18 分钟" in document.markdown
assert "### 午餐 · 故宫附近" in document.markdown
assert "营业时间、菜品与服务安排请以商家官方信息为准" in document.markdown
```

并断言 Markdown 不包含 `rating`、`score`、`招牌菜`。

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_orchestration.py backend/tests/test_summary.py -q
```

预期：FAIL，编排器仍传 `daily_areas`，汇总器未渲染时段信息。

- [ ] **步骤 3：修改编排器数据流**

Route Agent 调用改为传完整天气结果：

```python
route = await self._safe_agent_call(
    "route", lambda: self.route.run(request, weather, request_id, trace_id), request_id, trace_id
)
```

Food Agent 调用改为：

```python
daily_itineraries = getattr(route_data, "daily_itineraries", ()) or ()
food = await self._safe_agent_call(
    "food", lambda: self.food.run(request, daily_itineraries, request_id, trace_id), request_id, trace_id
)
```

若 route 失败或不含行程，构造每一天 `DailyItinerary(day=..., weather_reminder="路线待核验。", attractions=())`，不再伪造景区。

- [ ] **步骤 4：修改 SummaryAgent Markdown**

替换“每日路线”仅输出区域的逻辑：逐个 `DailyItinerary` 输出当天提醒、每个时段景区、建议游玩时长、地址、前往下一景区的驾车预估。按 `day + meal_period` 找到 Food Agent 对应计划，输出午餐、晚餐的真实餐馆名/地址；缺失时输出受控核验提示。

所有上游文本继续通过 `_safe()` 转义；不要将 POI 原始字段、评分或菜品写入 Markdown。

- [ ] **步骤 5：运行编排与汇总测试验证通过**

运行：

```bash
PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests/test_orchestration.py backend/tests/test_summary.py -q
```

预期：PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend/app/orchestration/sequential.py backend/app/agents/summary.py backend/tests/test_orchestration.py backend/tests/test_summary.py
git commit -m "feat: render timed attractions and nearby meal plans"
```

---

### 任务 7：文档、全量回归与真实 API 验证

**文件：**
- 修改：`README.md`

- [x] **步骤 1：更新 README 与企业级版本讲解**

已基于当前实现更新 `README.md` 与 `docs/智能文旅策划助手-v1企业级版本讲解.md`，同步模块职责、企业 API 来源、API 输出展示、限制和验收说明：

- Route Agent 写为按天气选择景区并输出时段行程；
- Food Agent 写为按景区附近 POI 提供午餐/晚餐候选；
- 增加 `/v5/place/around`、固定 2000 米半径与餐馆字段边界；
- 明确高德当前接口不提供评分、推荐指数、招牌菜；
- 明确高风险天气优先室内文化场所且开放时间待核验；
- 删除所有“每日仅统一活动区域”的描述。

- [ ] **步骤 2：运行完整测试套件**

未在本次文档任务中运行测试。结果以当前完整测试命令实际结果为准：

`PYTHONPATH=backend python -m pytest -c backend/pytest.ini backend/tests -q`

- [ ] **步骤 3：真实 API 冒烟验证**

未在本次文档任务中运行真实 API 冒烟验证；需使用和风 3 日窗口内日期，并以当前环境实际结果为准。

启动服务：

```bash
PYTHONPATH=backend python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

使用和风 3 日窗口内的出发日期调用：

```bash
curl -s -X POST http://127.0.0.1:8000/api/travel-plans \
  -H "Content-Type: application/json" \
  --data-binary @travel_payload.json
```

验证响应：

- `itinerary.route.data.daily_itineraries` 存在；
- 高风险日仅使用室内文化关键词；常规日使用 `风景名胜`；
- 每天景区不重复且时段顺序为上午、下午、傍晚；
- 可用景区间含距离/分钟预估；
- Food 结果有午餐、晚餐并包含真实名称、地址；
- 响应和 Markdown 不含 `rating`、`score`、`招牌菜`；
- `/api/health` 与 `/api/ready` 返回 HTTP 200。

- [ ] **步骤 4：执行差异检查**

运行：`git diff --check`

预期：无空白错误。

- [ ] **步骤 5：Commit**

```bash
git add README.md
git commit -m "docs: describe weather-aware attraction itinerary planning"
```

---

## 自检记录

- **规格覆盖：** 任务 1 覆盖模型；任务 2 覆盖附近 POI；任务 3 覆盖天气提醒；任务 4 覆盖景区时段和通勤；任务 5 覆盖午晚餐；任务 6 覆盖编排与 Markdown；任务 7 覆盖文档、全量测试和真实 API。
- **数据流一致性：** Weather Agent → Route Agent（完整天气结果）→ Food Agent（`daily_itineraries`）；Lodging Agent 保持 `daily_areas` 兼容链路。
- **事实边界：** 所有任务明确禁止评分、推荐指数、招牌菜、开放时间、预约、价格和交易字段；模型不参与决策。
- **执行注意：** 当前主工作区存在未提交改动。实施前应按用户选择建立隔离 worktree，或在原地实施并避免将既有无关改动混入任务 commit。
