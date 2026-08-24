# 智能文旅策划 · 天气 15 天 / 方案同等天数 / Markdown 推荐菜品 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 或 superpowers:subagent-driven-development 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 三项后端数据合同优化：(1) 和风天气查询由上限 3 天改为 15 天；(2) 保证路线/景点/餐饮方案与天气生成同等天数的方案；(3) 最终 Markdown 从高德 POI 提取店铺推荐菜品并展示。

**架构：** 天气天数改动集中在 `HeWeatherClient`（端点 `3d→15d`、`min(days,3)→min(days,15)`）与天气 Agent 的缺失字段命名（`_to_N→_to<实际值>`）；「同等天数」经代码核对已由各 Agent 的 `range(1, days+1)` 全量遍历满足，任务二以回归测试锁定；推荐菜品经「高德 POI 投影保留 `tags` → 餐饮 Agent 提取 `FoodCandidate.specialties` → 汇总 Agent 渲染到 Markdown」三级链路实现。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、httpx、pytest + pytest-asyncio + respx（测试 mock 外部 HTTP）。

**执行前注意：** 工作区 `frontend/styles.css` 有任务四未提交改动（`M`）。开始前先与用户确认：将任务四改动单独提交，再开始本计划；每任务完成后分别提交，不混合提交。

---

## 文件结构

- 修改 `backend/app/services/heweather.py` — 天气客户端天数上限与端点
- 修改 `backend/app/agents/weather.py` — 缺失天气字段命名不再用 `_N` 兜底
- 修改 `backend/app/services/amap.py` — POI 投影新增保留 `tags`
- 修改 `backend/app/agents/food.py` — 提取 `specialties`（tags → 菜系兜底）
- 修改 `backend/app/agents/summary.py` — Markdown 餐饮区渲染推荐菜品
- 修改 `backend/tests/test_heweather.py` — 端点 mock 与 15 天上限断言
- 修改 `backend/tests/test_agents_weather_route.py` — 天气缺失字段断言、新增同等天数回归测试
- 修改 `backend/tests/test_agents_poi.py` — 推荐菜品提取断言、POI 夹具 tags
- 修改 `backend/tests/test_amap.py` — POI 投影字段集合新增 `tags`
- 修改 `backend/tests/test_summary.py` — Markdown 餐饮区断言
- 修改 `README.md` — 天气 15 日、餐饮推荐菜品合同描述

---

## 任务一：和风天气查询 3 天 → 15 天

**文件：**
- 修改 `backend/app/services/heweather.py:42` 与 `:55`
- 修改 `backend/app/agents/weather.py:117-122`
- 修改 `backend/tests/test_heweather.py`（约 26 处端点字符串 + 3 个天数相关测试）
- 修改 `backend/tests/test_agents_weather_route.py:248-261`

- [ ] **步骤 1：更新天气客户端天数上限与端点**

`backend/app/services/heweather.py` 两处：

```python
# :42 处，原：effective_days = min(days, 3)
        effective_days = min(days, 15)
```

```python
# :55 处，原：/v7/weather/3d
                response = await request_with_retry(lambda: client.get(f"{self._base_url}/v7/weather/15d", params={"location": location_id, "key": self.api_key}), max_attempts=self.max_attempts)
```

- [ ] **步骤 2：更新天气 Agent 缺失字段命名**

`backend/app/agents/weather.py` `_missing_fields`：

```python
    @staticmethod
    def _missing_fields(request_days: int, actual_days: int) -> tuple[str, ...]:
        if actual_days >= request_days:
            return ()
        return (f"daily_forecast_days_{actual_days + 1}_to_{request_days}",)
```

（原 `end = "N" if request_days > 3 else str(request_days)` 删除；`request_days ≤ 14`，15 日端点可完整覆盖。）

- [ ] **步骤 3：同步天气客户端测试到 15d 端点**

`backend/tests/test_heweather.py`：全文替换所有 `f"{BASE}/v7/weather/3d"` 为 `f"{BASE}/v7/weather/15d"`（用编辑器的 replace_all，约 26 处）。

- [ ] **步骤 4：更新 15 天上限测试**

`backend/tests/test_heweather.py` `test_weather_filters_before_start_and_limits_to_three_days` 改名并改为 15 天断言：

```python
@respx.mock
@pytest.mark.asyncio
async def test_weather_filters_before_start_and_limits_to_fifteen_days():
    respx.get(f"{BASE}/v7/weather/15d").mock(return_value=httpx.Response(200, json={
        "code": "200", "updateTime": "2026-08-20T10:00:00Z", "daily": [
            {"fxDate": "2026-08-31", "textDay": "旧", "tempMin": "1", "tempMax": "2"},
            *[{"fxDate": f"2026-09-{day:02d}", "textDay": "晴", "tempMin": "20", "tempMax": "28"} for day in range(1, 17)],
        ],
    }))
    result = await client().daily_forecast("city", date(2026, 9, 1), 16)
    assert [item["date"] for item in result["daily"]] == [date(2026, 9, day) for day in range(1, 16)]
```

- [ ] **步骤 5：更新两个缓存键测试（3/9 → 15/16 别名）**

`backend/tests/test_heweather.py`：

```python
# test_weather_days_three_and_nine_share_effective_cache_key → 改名
async def test_weather_days_fifteen_and_sixteen_share_effective_cache_key():
    # mock 保持返回 3 日即可；请求天数改为 15 与 16
    first = await weather_client.daily_forecast("city", date(2026, 9, 1), 15)
    second = await weather_client.daily_forecast("city", date(2026, 9, 1), 16)
    assert route.call_count == 1
    assert first["daily"] == second["daily"]
    assert second["data_status"] == "cached"
```

```python
# test_weather_effective_cache_key_avoids_days_alias → 两处请求天数 3/9 改为 15/16
    await client(cache=cache).daily_forecast("city", date(2026, 9, 1), 15)
    await client(cache=cache).daily_forecast("city", date(2026, 9, 1), 16)
    assert route.call_count == 1
```

- [ ] **步骤 6：更新天气 Agent 短缺字段断言**

`backend/tests/test_agents_weather_route.py:248-261` 改名并更新断言：

```python
def test_weather_agent_marks_shortfall_days_to_requested_range():
    agent = WeatherAgent(
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
        weather_client=FakeWeatherClient(weather_payload(days=3)),
    )
    result = __import__("asyncio").run(agent.run(request(days=5), **ids()))
    assert result.status is AgentStatus.partial
    assert len(result.data.daily) == 3
    assert result.missing_fields == ("daily_forecast_days_4_to_5",)
```

- [ ] **步骤 7：运行天气相关测试验证通过**

运行（在 `backend/` 目录）：

```bash
python -m pytest tests/test_heweather.py tests/test_agents_weather_route.py -q
```

预期：全部 PASS（含改名后的 15 天/缓存键/短缺字段测试）。

- [ ] **步骤 8：更新 README 天气描述**

`README.md` 中：
- `GET /v7/weather/3d` → `GET /v7/weather/15d`
- 「最多使用 3 日逐日预报」 → 「最多使用 15 日逐日预报」
- 在「和风天气：逐日预报」小节补一句：15 日逐日预报需使用支持 15d 的服务密钥。

- [ ] **步骤 9：提交任务一**

```bash
git add backend/app/services/heweather.py backend/app/agents/weather.py backend/tests/test_heweather.py backend/tests/test_agents_weather_route.py README.md
git commit -m "feat: 和风天气查询上限由 3 天提升至 15 天"
```

---

## 任务二：路线 / 景点 / 餐饮方案与天气同等天数

**核对结论：** `RouteAgent._build_itineraries` 与 `daily_areas` 均遍历 `range(1, request.days + 1)`；`FoodAgent.run` 对缺失天数显式补齐 `request.days × 2` 餐次。结构上已满足「同等天数」，任务一的天气修复消除了唯一缺口（天气被 3 天截断）。本任务以回归测试锁定该保证，不新增生产逻辑。

**文件：**
- 修改 `backend/tests/test_agents_weather_route.py`
- 修改 `backend/tests/test_agents_poi.py`

- [ ] **步骤 1：新增天气 10 天回归测试**

`backend/tests/test_agents_weather_route.py` 新增：

```python
def test_weather_agent_returns_weather_for_full_request_days():
    agent = WeatherAgent(
        amap_client=FakeAmapClient(geocodes={"杭州": {"name": "杭州", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}}),
        weather_client=FakeWeatherClient(weather_payload(days=10)),
    )
    result = __import__("asyncio").run(agent.run(request(days=10), **ids()))
    assert result.status is AgentStatus.success
    assert len(result.data.daily) == 10
```

- [ ] **步骤 2：新增路线 10 天回归测试**

`backend/tests/test_agents_weather_route.py` 新增：

```python
@pytest.mark.asyncio
async def test_route_agent_generates_itinerary_for_every_request_day():
    pois = [attraction(f"景区{i}", location=f"120.{i},30.{i}") for i in range(40)]
    amap = FakeAmapClient(
        geocodes={"上海": {"name": "上海市", "location": "121,31", "adcode": "310000", **source_metadata(SourceType.map_api)}, "杭州": {"name": "杭州市", "location": "120,30", "adcode": "330100", **source_metadata(SourceType.map_api)}},
        route={"distance_meters": 100, "duration_minutes": 1, **source_metadata(SourceType.map_api)},
        routes={("121,31", "120,30"): {"distance_meters": 180000, "duration_minutes": 150, **source_metadata(SourceType.map_api)}, ("120,30", "121,31"): {"distance_meters": 181000, "duration_minutes": 151, **source_metadata(SourceType.map_api)}},
        nearby_results={("风景名胜", "120,30", 50000): pois},
    )
    result = await RouteAgent(amap).run(request(days=10), weather_result(10), ids())
    assert [item.day for item in result.data.daily_itineraries] == list(range(1, 11))
    assert [item.day for item in result.data.daily_areas] == list(range(1, 11))
```

- [ ] **步骤 3：新增餐饮 10 天回归测试**

`backend/tests/test_agents_poi.py` 新增：

```python
@pytest.mark.asyncio
async def test_food_generates_plans_for_every_request_day_including_ten():
    client = FakePoiClient()
    result = await FoodAgent(client).run(request(days=10), (), REQUEST_ID, REQUEST_ID)
    assert [(plan.day, plan.meal_period) for plan in result.data.daily_food] == [
        (day, meal) for day in range(1, 11) for meal in ("午餐", "晚餐")
    ]
    assert len(result.data.daily_food) == 20
```

- [ ] **步骤 4：运行 Agent 测试验证通过**

```bash
python -m pytest tests/test_agents_weather_route.py tests/test_agents_poi.py -q
```

预期：全部 PASS（含新增 10 天回归测试）。

- [ ] **步骤 5：提交任务二**

```bash
git add backend/tests/test_agents_weather_route.py backend/tests/test_agents_poi.py
git commit -m "test: 锁定路线与餐饮方案按请求天数全量生成"
```

---

## 任务三：Markdown 推荐菜品（高德 POI tags 提取 + 菜系兜底）

**文件：**
- 修改 `backend/app/services/amap.py:139-150`（POI 投影新增 `tags`）
- 修改 `backend/app/agents/food.py`（新增 `_specialties`/`_cuisine` 并在 `_plan_meal` 填充）
- 修改 `backend/app/agents/summary.py:146-153`（渲染推荐菜品）
- 修改 `backend/tests/test_amap.py`（3 处字段集合断言）
- 修改 `backend/tests/test_agents_poi.py`（夹具 tags、新增提取测试）
- 修改 `backend/tests/test_summary.py`（餐饮区断言）
- 修改 `README.md`（餐饮合同描述）

- [ ] **步骤 1：高德 POI 投影保留 tags**

`backend/app/services/amap.py` `_project` 的 POI 分支：

```python
        mapped = []
        for item in pois[:10]:
            if not isinstance(item, dict):
                raise ExternalServiceUnavailable("高德地图未返回有效 POI")
            candidate = {
                "name": item.get("name"),
                "address": item.get("address"),
                "location": item.get("location"),
                "category": item.get("type"),
                "tags": _normalize_tags(item.get("tags")),
            }
            if not _non_empty_text(candidate["name"]) or not _non_empty_text(candidate["category"]) or not _optional_text(candidate["address"]) or not _optional_text(candidate["location"]):
                raise ExternalServiceUnavailable("高德地图未返回有效 POI")
            mapped.append(candidate)
        return mapped
```

文件末尾新增模块级辅助函数：

```python
def _normalize_tags(value: object) -> tuple[str, ...]:
    """将高德 tags 规整为非空字符串元组，去重并限长。"""
    if not isinstance(value, (list, tuple)):
        return ()
    collected: list[str] = []
    for tag in value:
        if not isinstance(tag, str):
            continue
        text = tag.strip()
        if not text or len(text) > 100 or text in collected:
            continue
        collected.append(text)
        if len(collected) >= 10:
            break
    return tuple(collected)
```

- [ ] **步骤 2：同步高德 POI 字段集合断言**

`backend/tests/test_amap.py` 三处：

```python
# :43 与 :423，set(pois[0]) / set(first[0]) 中加入 "tags"
    assert set(pois[0]) == {"name", "address", "location", "category", "tags", "data_status", "source_updated_at", "retrieved_at"}
```

```python
# :73，缓存投影字段集合
    assert set(cached_value["data"][0]) == {"name", "address", "location", "category", "tags"}
```

- [ ] **步骤 3：餐饮 Agent 提取 specialties**

`backend/app/agents/food.py` 类内新增常量与提取方法（放在 `_plan_meal` 之前）：

```python
    _MAX_SPECIALTIES = 5
    _MAX_SPECIALTY_LENGTH = 20
    _GENERIC_CUISINE_LABELS = {
        "餐饮服务", "美食", "中餐厅", "西餐厅", "日餐厅", "快餐厅", "咖啡厅", "酒吧", "食堂", "小吃", "甜品", "面包店",
    }

    @classmethod
    def _specialties(cls, item: dict[str, Any]) -> tuple[str, ...]:
        """从 POI tags 提取菜品/招牌词；无则回退分类第三级菜系。"""
        collected: list[str] = []
        raw_tags = item.get("tags")
        if isinstance(raw_tags, (list, tuple)):
            for tag in raw_tags:
                if not isinstance(tag, str):
                    continue
                text = tag.strip()
                if not text or len(text) > cls._MAX_SPECIALTY_LENGTH or text in collected:
                    continue
                collected.append(text)
                if len(collected) >= cls._MAX_SPECIALTIES:
                    break
        if not collected:
            cuisine = cls._cuisine(item.get("category"))
            if cuisine:
                collected.append(cuisine)
        return tuple(collected)

    @classmethod
    def _cuisine(cls, category: object) -> str | None:
        """提取高德 type 第三级菜系（如 川菜馆），过滤通用餐饮标签。"""
        if not isinstance(category, str):
            return None
        parts = [part.strip() for part in category.split(";") if part.strip()]
        if not parts:
            return None
        last = parts[-1]
        if last in cls._GENERIC_CUISINE_LABELS or len(last) > cls._MAX_SPECIALTY_LENGTH:
            return None
        return last
```

`_plan_meal` 中构造候选处（`:223`）改为：

```python
                    try:
                        candidate = FoodCandidate(poi=self._poi(poi_item, "amap:food", "餐饮服务"), specialties=self._specialties(poi_item))
                    except (KeyError, TypeError, ValueError, ValidationError):
                        continue
```

- [ ] **步骤 4：同步餐饮测试夹具 tags**

`backend/tests/test_agents_poi.py` 的 `poi()` 助手默认 `tags` 改为空元组：

```python
def poi(name="西湖酒店", category="住宿服务", **extra):
    return {
        "name": name, "address": "西湖边", "location": "120.1,30.2", "category": category,
        "tags": [], "data_status": "realtime",
        "source_updated_at": None, "retrieved_at": datetime(2026, 8, 21, tzinfo=timezone.utc), **extra,
    }
```

（lodging 测试不断言 tags，不受影响；food 测试按需通过 `**extra` 显式传餐饮 tags。）

- [ ] **步骤 5：更新「禁止招牌菜」断言并新增提取测试**

`backend/tests/test_agents_poi.py` `test_food_filters_non_food_and_keeps_first_valid_candidate`：给有效餐厅传餐饮 tags，禁止列表去掉「招牌菜」：

```python
async def test_food_filters_non_food_and_keeps_first_valid_candidate():
    client = FakePoiClient(nearby_results={("餐饮服务", "120.1,30.2", 2000): [
        poi(name="商场", category="购物服务"), poi(name="真实餐厅", category="餐饮服务", tags=["川菜", "水煮鱼"]), poi(name="第二餐厅", category="餐饮服务")
    ]})
    result = await FoodAgent(client).run(request(days=1), (itinerary(1, attraction("上午", "西湖")),), REQUEST_ID, REQUEST_ID)
    candidate = result.data.daily_food[0].candidates[0]
    assert candidate.poi.name == "真实餐厅"
    assert candidate.specialties == ("川菜", "水煮鱼")
    assert len(result.data.daily_food[0].candidates) == 1
    assert all(term not in result.model_dump_json() for term in ("rating", "score", "recommendation"))
```

新增菜系兜底测试：

```python
@pytest.mark.asyncio
async def test_food_specialties_fall_back_to_cuisine_when_no_tags():
    client = FakePoiClient(nearby_results={("餐饮服务", "120.1,30.2", 2000): [
        poi(name="川味馆", category="餐饮服务;中餐厅;川菜馆", tags=[]),
    ]})
    result = await FoodAgent(client).run(request(days=1), (itinerary(1, attraction("上午", "西湖")),), REQUEST_ID, REQUEST_ID)
    assert result.data.daily_food[0].candidates[0].specialties == ("川菜馆",)
```

- [ ] **步骤 6：汇总 Agent 渲染推荐菜品**

`backend/app/agents/summary.py` `_markdown` 餐饮候选循环（`:147-148` 之间）插入：

```python
                    if daily.candidates:
                        for candidate in daily.candidates:
                            lines.append(f"- {cls._safe(candidate.poi.name)}：{cls._safe(candidate.poi.address or '地址待核验')}。")
                            if candidate.specialties:
                                lines.append(f"- 推荐菜品：{cls._safe('、'.join(candidate.specialties))}。")
```

- [ ] **步骤 7：更新汇总 Markdown 测试**

`backend/tests/test_summary.py` `test_summary_markdown_renders_daily_itinerary_and_food_details_without_raw_fields`：给第一个 FoodCandidate 加 `specialties` 并断言推荐菜品行，禁止列表去掉「招牌菜」：

```python
    food_data = FoodPlanData(daily_food=(
        DailyFoodPlan(day=1, area="故宫", meal_period="午餐", nearby_attraction_name="故宫",
                      candidates=(FoodCandidate(poi=PoiCandidate(name="宫廷菜", address="午餐地址", category="餐馆", source_ids=("f",)), specialties=("东坡肉", "龙井虾仁")),)),
        # ...其余三项保持不变
    ))
    # 断言列表中加入 "推荐菜品：东坡肉、龙井虾仁"
    for text in (... "推荐菜品：东坡肉、龙井虾仁", ...):
        assert text in markdown
    # :134 禁止列表改为
    for forbidden in ("rating", "score", "开放时间"):
        assert forbidden not in markdown
```

- [ ] **步骤 8：运行全部受影响测试验证通过**

```bash
python -m pytest tests/test_amap.py tests/test_agents_poi.py tests/test_summary.py -q
```

预期：全部 PASS。

- [ ] **步骤 9：更新 README 餐饮合同**

`README.md` 中：
- 「POI 仅保留名称、地址、经纬度、类别和内部来源标识。」 → 补充「及标签（tags）」
- 「餐饮展示真实名称和地址，不展示评分、推荐指数或招牌菜。」 → 「餐饮展示真实名称、地址，以及来自地图 POI 的推荐菜品（标签提取，菜系兜底），不展示评分与推荐指数。」
- 数据流中的 `餐饮 Agent` 描述补充推荐菜品提取。

- [ ] **步骤 10：提交任务三**

```bash
git add backend/app/services/amap.py backend/app/agents/food.py backend/app/agents/summary.py backend/tests/test_amap.py backend/tests/test_agents_poi.py backend/tests/test_summary.py README.md
git commit -m "feat: 从高德 POI 提取推荐菜品并渲染到 Markdown"
```

---

## 自检

- **规格覆盖度：** 任务一覆盖「和风 3→15 天」（端点 + 上限 + 缺失字段命名 + 测试 + README）；任务二覆盖「路线/景点/餐饮同等天数」（回归测试 + 结论说明）；任务三覆盖「Markdown 从高德 POI 获取推荐菜品」（投影 tags → 餐饮提取 → Markdown 渲染 + 测试 + README）。无遗漏需求。
- **占位符扫描：** 无「待定/TODO」；每个代码步骤均含完整代码与精确路径；命令给出预期输出。
- **类型一致性：** `_specialties`/`_cuisine` 为 `FoodAgent` 类方法，`FoodCandidate.specialties` 类型为 `tuple[NonEmptyText, ...]`（每项 ≤100），提取上限 5 项、每项 ≤20 字符，满足模型约束；`_normalize_tags` 返回 `tuple[str, ...]` 与 `PoiCandidate.tags` 兼容。三任务均使用现有 `FoodCandidate`/`PoiCandidate`/`AgentResult` 契约，无新增不匹配类型。
