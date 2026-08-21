# v1 旅行数据合同实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不接入外部服务或 Agent 的前提下，实现 v1 强类型旅行数据模型与对应的 Pydantic v2 合同测试。

**架构：** 新建一个封闭的 `app.models.travel` 模块，将请求、来源、领域事实、执行状态和最终文档统一建模。模型通过 `extra="forbid"`、字段约束和跨字段校验阻断未授权数据；测试从用户请求、来源、领域结果、执行状态和最终文档五个边界验证合同意图。

**技术栈：** Python 3.12、Pydantic 2.11、pytest 8.3。

---

## 文件结构

- 创建：`backend/app/models/__init__.py` — 标记 `models` 为 Python 包，不导入或执行领域逻辑。
- 创建：`backend/app/models/travel.py` — 定义旅行请求、来源、天气、路线、住宿、餐饮、Agent 结果和最终文档的 Pydantic 模型。
- 创建：`backend/tests/test_models.py` — 验证数据合同边界、状态一致性、安全字段拒绝和结构化最终文档。
- 不修改：`backend/app/main.py`、`backend/app/config.py`、`backend/app/security.py`、`backend/tests/test_api.py`。

## 统一执行约定

所有测试命令从当前工作树的仓库根目录执行，不依赖主工作区绝对路径：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

全量回归命令：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -v
```

---

### 任务 1：建立领域模型包与请求合同

**文件：**
- 创建：`backend/app/models/__init__.py`
- 创建：`backend/app/models/travel.py`
- 测试：`backend/tests/test_models.py`

- [ ] **步骤 1：编写请求模型的失败测试**

在 `backend/tests/test_models.py` 中写入：

```python
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.models.travel import TravelPlanRequest


def test_travel_plan_request_applies_defaults_and_derives_nights():
    request = TravelPlanRequest(
        origin=" 上海 ",
        destination=" 杭州 ",
        departure_date=date.today(),
        travelers=2,
    )

    assert request.origin == "上海"
    assert request.destination == "杭州"
    assert request.days == 3
    assert request.nights == 2
    assert request.preferences == ()


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"origin": " ", "destination": "杭州"}, "origin"),
        ({"origin": "上海", "destination": " "}, "destination"),
        ({"origin": "上海", "destination": "杭州", "travelers": 0}, "travelers"),
        ({"origin": "上海", "destination": "杭州", "days": 15}, "days"),
        ({"origin": "上海", "destination": "杭州", "departure_date": date.today() - timedelta(days=1)}, "departure_date"),
        ({"origin": "上海", "destination": "杭州", "preferences": [" "]}, "preferences"),
        ({"origin": "上海", "destination": "杭州", "unexpected": "value"}, "unexpected"),
    ],
)
def test_travel_plan_request_rejects_invalid_or_unknown_input(payload, field):
    payload.setdefault("departure_date", date.today())
    payload.setdefault("travelers", 2)

    with pytest.raises(ValidationError) as exc_info:
        TravelPlanRequest(**payload)

    assert field in str(exc_info.value)
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：FAIL，报错包含 `ModuleNotFoundError: No module named 'app.models'`。

- [x] **步骤 3：创建包与最小请求模型实现**

创建 `backend/app/models/__init__.py`：

```python
"""旅行领域模型包。"""
```

创建 `backend/app/models/travel.py`，先实现本任务所需的部分：

```python
from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_uuid_v1_to_v5(value: str) -> str:
    """校验字符串为 UUID v1 至 v5。"""

    parsed = UUID(value)
    if parsed.version not in {1, 2, 3, 4, 5}:
        raise ValueError("必须是 UUID v1 至 v5")
    return str(parsed)


class StrictModel(BaseModel):
    """拒绝未声明字段的领域模型基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


NonEmptyText = Annotated[str, Field(min_length=1, max_length=100)]
UUIDV1ToV5 = Annotated[str, AfterValidator(validate_uuid_v1_to_v5)]


class TravelPlanRequest(StrictModel):
    """旅行规划请求。"""

    origin: NonEmptyText
    destination: NonEmptyText
    departure_date: date
    travelers: int = Field(ge=1, le=20)
    days: int = Field(default=3, ge=1, le=14)
    budget: int | None = Field(default=None, ge=0, le=200000)
    preferences: tuple[NonEmptyText, ...] = Field(default=(), max_length=12)

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def strip_location(cls, value: str) -> str:
        return value.strip()

    @field_validator("preferences", mode="before")
    @classmethod
    def normalize_preferences(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("preferences 必须为数组")
        return [item.strip() for item in value]

    @model_validator(mode="after")
    def validate_departure_date(self) -> "TravelPlanRequest":
        if self.departure_date < date.today():
            raise ValueError("出行日期不得早于当前日期")
        return self

    @property
    def nights(self) -> int:
        """返回由天数推导出的住宿晚数。"""

        return max(self.days - 1, 0)
```

- [x] **步骤 4：运行请求测试验证通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：PASS，`2 passed`。

- [ ] **步骤 5：Commit**

```powershell
git add backend/app/models/__init__.py backend/app/models/travel.py backend/tests/test_models.py
git commit -m "feat: add travel request contract"
```

---

### 任务 2：实现来源合同与基础领域事实

**文件：**
- 修改：`backend/app/models/travel.py`
- 修改：`backend/tests/test_models.py`

- [ ] **步骤 1：编写来源与领域事实的失败测试**

在 `backend/tests/test_models.py` 的现有内容后追加：

```python
from datetime import datetime, timezone

from app.models.travel import (
    DataStatus,
    DailyArea,
    DailyWeather,
    NormalizedLocation,
    PoiCandidate,
    RouteEstimate,
    Source,
    SourceType,
    WeatherRiskLevel,
)


def test_source_preserves_distinct_update_and_retrieval_times():
    source = Source(
        name="和风天气",
        type=SourceType.weather_api,
        data_status=DataStatus.realtime,
        source_updated_at=datetime(2026, 8, 19, 8, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 8, 19, 8, 1, tzinfo=timezone.utc),
        url="https://dev.qweather.com",
    )

    assert source.source_updated_at < source.retrieved_at


@pytest.mark.parametrize(
    "payload",
    [
        {
            "name": "高德地图",
            "type": "map_api",
            "data_status": "cached",
            "retrieved_at": datetime.now(timezone.utc),
        },
        {
            "name": "地图服务伪装知识库",
            "type": "map_api",
            "data_status": "knowledge_base",
            "retrieved_at": datetime.now(timezone.utc),
        },
        {
            "name": "和风天气",
            "type": "weather_api",
            "data_status": "realtime",
            "source_updated_at": datetime.now(timezone.utc),
            "retrieved_at": datetime.now(timezone.utc),
            "knowledge_version": "v1",
        },
        {
            "name": "高德地图",
            "type": "map_api",
            "data_status": "realtime",
            "source_updated_at": datetime.now(timezone.utc),
            "retrieved_at": datetime.now(timezone.utc),
            "url": "http://example.com",
        },
    ],
)
def test_source_rejects_inconsistent_time_or_knowledge_metadata(payload):
    with pytest.raises(ValidationError):
        Source(**payload)


def test_domain_fact_models_enforce_numeric_and_day_boundaries():
    poi = PoiCandidate(
        name="西湖景区",
        category="景区",
        source_ids=["amap:123"],
    )
    weather = DailyWeather(
        date=date.today(),
        condition="多云",
        risk_level=WeatherRiskLevel.low,
    )
    route = RouteEstimate(distance_meters=12000, duration_minutes=35)
    area = DailyArea(day=1, area="西湖周边")

    assert poi.name == "西湖景区"
    assert weather.risk_level is WeatherRiskLevel.low
    assert route.is_estimate is True
    assert area.day == 1


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (PoiCandidate, {"name": "西湖景区", "category": "景区", "source_ids": [], "rating": 4.9}),
        (RouteEstimate, {"distance_meters": -1, "duration_minutes": 20}),
        (DailyArea, {"day": 0, "area": "西湖周边"}),
        (NormalizedLocation, {"name": "杭州", "price": 100}),
    ],
)
def test_domain_fact_models_reject_forbidden_or_invalid_fields(model, payload):
    with pytest.raises(ValidationError):
        model(**payload)
```

- [ ] **步骤 2：运行新增测试验证失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：FAIL，报错包含 `cannot import name 'DataStatus' from 'app.models.travel'`。

- [x] **步骤 3：实现来源与基础领域事实模型**

在 `backend/app/models/travel.py` 的 `TravelPlanRequest` 后追加：

```python
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import HttpUrl


class AgentStatus(StrEnum):
    """专业 Agent 的执行状态。"""

    success = "success"
    partial = "partial"
    degraded = "degraded"
    failed = "failed"


class AgentName(StrEnum):
    """受控的专业 Agent 名称。"""

    weather = "weather"
    route = "route"
    lodging = "lodging"
    food = "food"


class DataStatus(StrEnum):
    """来源数据的取得方式。"""

    realtime = "realtime"
    cached = "cached"
    knowledge_base = "knowledge_base"
    degraded = "degraded"


class SourceType(StrEnum):
    """允许的事实来源类别。"""

    weather_api = "weather_api"
    map_api = "map_api"
    poi_api = "poi_api"
    knowledge_base = "knowledge_base"


class WeatherRiskLevel(StrEnum):
    """天气风险等级。"""

    low = "low"
    medium = "medium"
    high = "high"


class Source(StrictModel):
    """可追溯的事实来源。"""

    name: NonEmptyText
    type: SourceType
    data_status: DataStatus
    source_updated_at: datetime | None = None
    retrieved_at: datetime
    url: HttpUrl | None = None
    knowledge_version: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_source_metadata(self) -> "Source":
        if self.data_status in {DataStatus.realtime, DataStatus.cached} and self.source_updated_at is None:
            raise ValueError("实时或缓存来源必须提供上游更新时间")
        if self.type is SourceType.knowledge_base:
            if self.data_status is not DataStatus.knowledge_base:
                raise ValueError("知识库来源必须标记为知识库数据")
            if self.knowledge_version is None:
                raise ValueError("知识库来源必须提供知识库版本")
        elif self.knowledge_version is not None:
            raise ValueError("非知识库来源不得提供知识库版本")
        if self.url is not None and self.url.scheme != "https":
            raise ValueError("来源 URL 必须使用 HTTPS")
        return self


class NormalizedLocation(StrictModel):
    """标准化地点。"""

    name: NonEmptyText
    location: str | None = None
    adcode: str | None = None


class PoiCandidate(StrictModel):
    """可引用的 POI 候选。"""

    name: NonEmptyText
    address: str | None = None
    location: str | None = None
    category: NonEmptyText
    tags: tuple[NonEmptyText, ...] = ()
    source_ids: tuple[NonEmptyText, ...] = Field(min_length=1)


class DailyWeather(StrictModel):
    """单日天气事实与活动提示。"""

    date: date
    condition: NonEmptyText
    temp_min: int | None = None
    temp_max: int | None = None
    risk_level: WeatherRiskLevel
    activity_suitability: str | None = None
    equipment_suggestions: tuple[NonEmptyText, ...] = ()


class RouteEstimate(StrictModel):
    """地图提供的非实时路线估算。"""

    distance_meters: int = Field(ge=0)
    duration_minutes: int = Field(ge=0)
    is_estimate: Literal[True] = True


class DailyArea(StrictModel):
    """某一行程日的活动区域。"""

    day: int = Field(ge=1)
    area: NonEmptyText
    activity_window: str | None = None
```

说明：不要将 `Source.url` 放宽为 HTTP 或任意字符串；在模型校验中显式拒绝非 HTTPS URL。

- [x] **步骤 4：运行来源与领域事实测试验证通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：PASS，所有已定义测试通过。

- [ ] **步骤 5：Commit**

```powershell
git add backend/app/models/travel.py backend/tests/test_models.py
git commit -m "feat: add travel source and domain facts"
```

---

### 任务 3：实现专业结果与状态一致性

**文件：**
- 修改：`backend/app/models/travel.py`
- 修改：`backend/tests/test_models.py`

- [ ] **步骤 1：编写领域计划与 Agent 状态的失败测试**

在 `backend/tests/test_models.py` 的现有内容后追加：

```python
from uuid import uuid4

from app.models.travel import (
    AgentResult,
    AgentStatus,
    ErrorDetail,
    FoodCandidate,
    FoodPlanData,
    LodgingCandidate,
    LodgingPlanData,
    RoutePlanData,
    WeatherPlanData,
)


def make_source() -> Source:
    return Source(
        name="和风天气",
        type=SourceType.weather_api,
        data_status=DataStatus.realtime,
        source_updated_at=datetime.now(timezone.utc),
        retrieved_at=datetime.now(timezone.utc),
    )


def make_weather_data() -> WeatherPlanData:
    return WeatherPlanData(
        destination="杭州",
        daily=[
            DailyWeather(
                date=date.today(),
                condition="多云",
                risk_level=WeatherRiskLevel.low,
            )
        ],
    )


def test_domain_plan_models_keep_only_non_transactional_information():
    poi = PoiCandidate(name="湖滨住宿区", category="住宿", source_ids=["kb:hotel-area"])
    lodging = LodgingPlanData(
        nights=2,
        recommended_area="西湖周边",
        candidates=[LodgingCandidate(poi=poi, facilities=["地铁便利"])],
    )
    food = FoodPlanData(
        daily_food=[
            {
                "day": 1,
                "area": "西湖周边",
                "candidates": [
                    FoodCandidate(poi=PoiCandidate(name="杭帮菜馆", category="餐饮", source_ids=["kb:food"])),
                ],
            }
        ]
    )
    route = RoutePlanData(
        origin="上海",
        destination="杭州",
        daily_areas=[DailyArea(day=1, area="西湖周边")],
        weather_adjusted=True,
    )

    assert lodging.nights == 2
    assert food.daily_food[0].day == 1
    assert route.weather_adjusted is True


@pytest.mark.parametrize(
    ("status", "data", "missing_fields", "error"),
    [
        (AgentStatus.success, None, [], None),
        (AgentStatus.success, make_weather_data(), ["daily_forecast"], None),
        (AgentStatus.partial, make_weather_data(), [], None),
        (AgentStatus.degraded, make_weather_data(), [], None),
        (AgentStatus.failed, make_weather_data(), ["daily_forecast"], ErrorDetail(code="external_service_unavailable", message="天气服务暂不可用", retryable=True)),
        (AgentStatus.failed, None, [], ErrorDetail(code="external_service_unavailable", message="天气服务暂不可用", retryable=True)),
    ],
)
def test_agent_result_rejects_inconsistent_status(status, data, missing_fields, error):
    request_id = str(uuid4())

    with pytest.raises(ValidationError):
        AgentResult[WeatherPlanData](
            agent="weather",
            status=status,
            summary="天气结果",
            data=data,
            missing_fields=missing_fields,
            error=error,
            request_id=request_id,
            trace_id=request_id,
        )


def test_agent_result_accepts_degraded_result_with_explicit_missing_fields():
    request_id = str(uuid4())
    result = AgentResult[WeatherPlanData](
        agent="weather",
        status=AgentStatus.degraded,
        summary="仅获得首日天气信息",
        data=make_weather_data(),
        missing_fields=["remaining_daily_forecast"],
        sources=[make_source()],
        warnings=["其余日期天气暂无法核验。"],
        request_id=request_id,
        trace_id=request_id,
    )

    assert result.status is AgentStatus.degraded
    assert result.error is None
```

- [ ] **步骤 2：运行新增测试验证失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：FAIL，报错包含 `cannot import name 'AgentResult' from 'app.models.travel'`。

- [x] **步骤 3：实现领域计划、受控错误和泛型 Agent 结果**

在 `backend/app/models/travel.py` 的 `DailyArea` 后追加：

```python
from typing import Generic, TypeVar


class WeatherPlanData(StrictModel):
    """天气 Agent 的领域结果。"""

    destination: NonEmptyText
    daily: tuple[DailyWeather, ...] = Field(min_length=1)
    constraints: tuple[NonEmptyText, ...] = ()


class RoutePlanData(StrictModel):
    """路线 Agent 的领域结果。"""

    origin: NonEmptyText
    destination: NonEmptyText
    round_trip: RouteEstimate | None = None
    daily_areas: tuple[DailyArea, ...] = Field(min_length=1)
    weather_adjusted: bool


class LodgingCandidate(StrictModel):
    """住宿区域候选。"""

    poi: PoiCandidate
    facilities: tuple[NonEmptyText, ...] = ()
    suitable_for: tuple[NonEmptyText, ...] = ()
    commute_note: str | None = None
    recommendation_reason: str | None = None


class LodgingPlanData(StrictModel):
    """住宿 Agent 的领域结果。"""

    nights: int = Field(ge=0)
    recommended_area: NonEmptyText
    candidates: tuple[LodgingCandidate, ...] = ()
    filter_suggestions: tuple[NonEmptyText, ...] = ()


class FoodCandidate(StrictModel):
    """餐饮候选。"""

    poi: PoiCandidate
    cuisine: str | None = None
    specialties: tuple[NonEmptyText, ...] = ()
    suitable_for: tuple[NonEmptyText, ...] = ()
    dietary_notes: tuple[NonEmptyText, ...] = ()
    business_hours_note: str | None = None


class DailyFoodPlan(StrictModel):
    """单日餐饮建议。"""

    day: int = Field(ge=1)
    area: NonEmptyText
    meal_period: str | None = None
    candidates: tuple[FoodCandidate, ...] = ()
    filter_suggestions: tuple[NonEmptyText, ...] = ()


class FoodPlanData(StrictModel):
    """餐饮 Agent 的领域结果。"""

    daily_food: tuple[DailyFoodPlan, ...] = Field(min_length=1)


class ErrorDetail(StrictModel):
    """可对外展示的受控错误摘要。"""

    code: NonEmptyText
    message: NonEmptyText
    retryable: bool


ResultData = TypeVar("ResultData")


class AgentResult(StrictModel, Generic[ResultData]):
    """专业 Agent 的强类型执行结果。"""

    agent: AgentName
    status: AgentStatus
    summary: NonEmptyText
    data: ResultData | None = None
    constraints: tuple[NonEmptyText, ...] = ()
    sources: tuple[Source, ...] = ()
    warnings: tuple[NonEmptyText, ...] = ()
    missing_fields: tuple[NonEmptyText, ...] = ()
    error: ErrorDetail | None = None
    request_id: UUIDV1ToV5
    trace_id: UUIDV1ToV5

    @model_validator(mode="after")
    def validate_status_payload(self) -> "AgentResult[ResultData]":
        if self.status is AgentStatus.success:
            if self.data is None or self.missing_fields or self.error is not None:
                raise ValueError("成功结果必须有数据且不得包含缺失字段或错误")
        elif self.status is AgentStatus.partial:
            if self.data is None or not self.missing_fields:
                raise ValueError("部分结果必须有数据和缺失字段")
        elif self.status is AgentStatus.degraded:
            if self.data is None or (not self.missing_fields and self.error is None):
                raise ValueError("降级结果必须有数据且说明缺失字段或错误")
        elif self.data is not None or not self.missing_fields or self.error is None:
            raise ValueError("失败结果不得有数据且必须说明缺失字段和错误")
        if self.trace_id != self.request_id:
            raise ValueError("trace_id 必须与 request_id 一致")
        return self
```

同时在文件顶部的 `typing` 导入中保留 `Annotated`，并合并为：

```python
from typing import Annotated, Generic, Literal, TypeVar
```

不要保留重复导入，也不要为 `AgentResult` 加 `degraded: bool`。

- [x] **步骤 4：运行领域计划与状态测试验证通过**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：PASS，所有已定义测试通过。

- [ ] **步骤 5：Commit**

```powershell
git add backend/app/models/travel.py backend/tests/test_models.py
git commit -m "feat: add typed agent result contracts"
```

---

### 任务 4：实现最终结构化文档与全量回归

**文件：**
- 修改：`backend/app/models/travel.py`
- 修改：`backend/tests/test_models.py`

说明：本任务中，四个嵌套 `AgentResult` 的 `request_id` 与 `trace_id` 必须等于外层 `TravelPlanDocument` 的相应值；最终模型将显式验证这一追踪一致性。

- [ ] **步骤 1：编写最终文档的失败测试**

在 `backend/tests/test_models.py` 的现有内容后追加：

```python
from app.models.travel import AgentName, DailyFoodPlan, TravelPlanData, TravelPlanDocument


def make_result(agent: str, status: AgentStatus, data, request_id: str):
    payload = {
        "agent": agent,
        "status": status,
        "summary": f"{agent} 结果",
        "data": data,
        "request_id": request_id,
        "trace_id": request_id,
    }
    if status is AgentStatus.degraded:
        payload["missing_fields"] = ["optional_detail"]
    return payload


def test_travel_plan_document_preserves_typed_itinerary_and_markdown():
    request_id = str(uuid4())
    shared_source = make_source()
    itinerary = TravelPlanData(
        weather=AgentResult[WeatherPlanData](
            **{
                **make_result("weather", AgentStatus.success, make_weather_data(), request_id),
                "sources": [shared_source],
                "warnings": ["天气信息请在出行前复核。"],
            }
        ),
        route=AgentResult[RoutePlanData](
            **{
                **make_result(
                    "route",
                    AgentStatus.success,
                    RoutePlanData(
                        origin="上海",
                        destination="杭州",
                        daily_areas=[DailyArea(day=1, area="西湖周边")],
                        weather_adjusted=True,
                    ),
                    request_id,
                ),
                "sources": [shared_source],
                "warnings": ["路线时间仅为估算。"],
            }
        ),
        lodging=AgentResult[LodgingPlanData](
            **{
                **make_result(
                    "lodging",
                    AgentStatus.degraded,
                    LodgingPlanData(nights=2, recommended_area="西湖周边"),
                    request_id,
                ),
                "sources": [shared_source],
                "warnings": ["住宿候选信息不完整。"],
            }
        ),
        food=AgentResult[FoodPlanData](
            **{
                **make_result(
                    "food",
                    AgentStatus.success,
                    FoodPlanData(daily_food=[DailyFoodPlan(day=1, area="西湖周边")]),
                    request_id,
                ),
                "sources": [shared_source],
                "warnings": ["餐饮营业信息请复核。"],
            }
        ),
    )
    document = TravelPlanDocument(
        request_id=request_id,
        trace_id=request_id,
        status=AgentStatus.degraded,
        itinerary=itinerary,
        markdown="# 杭州 3 日行程\n\n请通过官方渠道确认营业信息。",
        sources=[shared_source],
        warnings=[
            "天气信息请在出行前复核。",
            "路线时间仅为估算。",
            "住宿候选信息不完整。",
            "餐饮营业信息请复核。",
        ],
        degraded_agents=["lodging"],
    )

    assert document.itinerary.weather.data.destination == "杭州"
    assert document.markdown.startswith("# 杭州")
    assert document.sources == (shared_source,)
    assert document.warnings == (
        "天气信息请在出行前复核。",
        "路线时间仅为估算。",
        "住宿候选信息不完整。",
        "餐饮营业信息请复核。",
    )
    assert document.degraded_agents == (AgentName.lodging,)


@pytest.mark.parametrize(
    ("status", "degraded_agents"),
    [
        (AgentStatus.success, ["lodging"]),
        (AgentStatus.failed, ["lodging"]),
        (AgentStatus.degraded, ["weather"]),
    ],
)
def test_travel_plan_document_rejects_inconsistent_degraded_agent_list(status, degraded_agents):
    request_id = str(uuid4())
    itinerary = TravelPlanData(
        weather=AgentResult[WeatherPlanData](**make_result("weather", AgentStatus.success, make_weather_data(), request_id)),
        route=AgentResult[RoutePlanData](
            **make_result(
                "route",
                AgentStatus.success,
                RoutePlanData(
                    origin="上海",
                    destination="杭州",
                    daily_areas=[DailyArea(day=1, area="西湖周边")],
                    weather_adjusted=True,
                ),
                request_id,
            )
        ),
        lodging=AgentResult[LodgingPlanData](
            **make_result(
                "lodging",
                AgentStatus.success,
                LodgingPlanData(nights=2, recommended_area="西湖周边"),
                request_id,
            )
        ),
        food=AgentResult[FoodPlanData](
            **make_result(
                "food",
                AgentStatus.success,
                FoodPlanData(daily_food=[DailyFoodPlan(day=1, area="西湖周边")]),
                request_id,
            )
        ),
    )

    with pytest.raises(ValidationError):
        TravelPlanDocument(
            request_id=request_id,
            trace_id=request_id,
            status=status,
            itinerary=itinerary,
            markdown="# 行程",
            degraded_agents=degraded_agents,
        )
```

- [ ] **步骤 2：运行新增测试验证失败**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：FAIL，报错包含 `cannot import name 'TravelPlanData' from 'app.models.travel'`。

- [x] **步骤 3：实现最终结构化行程与文档模型**

在 `backend/app/models/travel.py` 的 `AgentResult` 后追加：

```python
class TravelPlanData(StrictModel):
    """最终行程的结构化领域事实。"""

    weather: AgentResult[WeatherPlanData]
    route: AgentResult[RoutePlanData]
    lodging: AgentResult[LodgingPlanData]
    food: AgentResult[FoodPlanData]


    @model_validator(mode="after")
    def validate_agent_slots(self) -> "TravelPlanData":
        expected_agents = {
            "weather": AgentName.weather,
            "route": AgentName.route,
            "lodging": AgentName.lodging,
            "food": AgentName.food,
        }
        for slot, expected_agent in expected_agents.items():
            if getattr(self, slot).agent is not expected_agent:
                raise ValueError(f"{slot} 槽位必须包含 {expected_agent.value} Agent 结果")
        return self


class TravelPlanDocument(StrictModel):
    """供 API 返回的结构化行程与 Markdown 文档。"""

    request_id: UUIDV1ToV5
    trace_id: UUIDV1ToV5
    status: Literal[AgentStatus.success, AgentStatus.degraded, AgentStatus.failed]
    itinerary: TravelPlanData
    markdown: str = Field(min_length=1)
    sources: tuple[Source, ...] = ()
    warnings: tuple[NonEmptyText, ...] = ()
    degraded_agents: tuple[AgentName, ...] = ()

    @model_validator(mode="after")
    def validate_degraded_agents(self) -> "TravelPlanDocument":
        results = (
            self.itinerary.weather,
            self.itinerary.route,
            self.itinerary.lodging,
            self.itinerary.food,
        )
        if any(
            result.request_id != self.request_id or result.trace_id != self.trace_id
            for result in results
        ):
            raise ValueError("专业结果必须使用文档的请求与追踪标识")
        actual_degraded_agents = {
            name
            for name, result in {
                "weather": self.itinerary.weather,
                "route": self.itinerary.route,
                "lodging": self.itinerary.lodging,
                "food": self.itinerary.food,
            }.items()
            if result.status is AgentStatus.degraded
        }
        if set(self.degraded_agents) != actual_degraded_agents:
            raise ValueError("降级 Agent 列表必须与行程中的降级结果一致")
        if self.status is AgentStatus.success and actual_degraded_agents:
            raise ValueError("含降级结果的文档不得标记为成功")
        if self.status is AgentStatus.failed and not any(
            result.status is AgentStatus.failed for result in results
        ):
            raise ValueError("失败文档必须包含失败的专业结果")
        return self
```

实现约束：`TravelPlanDocument` 必须从 `weather`、`route`、`lodging`、`food` 四个结果重新计算并校验顶层 `sources` 与 `warnings`，不能只校验调用方传入值。来源去重键只能使用 `name`、`type`、`data_status`、`source_updated_at`、`url` 和 `knowledge_version` 等来源事实字段，明确忽略每次读取都会变化的 `retrieved_at`；相同键的来源只保留四个 Agent 顺序中首次出现的完整 `Source` 实例。`warnings` 必须按 weather、route、lodging、food 顺序拼接。测试应使用不同 `Source` 实例、相同去重键且可有不同 `retrieved_at`，以防实现退回按对象身份或包含 `retrieved_at` 去重；来源或警告有漏项、额外值或顺序错误时必须拒绝。

- [x] **步骤 4：运行模型测试与完整后端回归**

先运行模型测试：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests/test_models.py -v
```

预期：PASS。

再运行完整后端测试：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -m pytest -c backend/pytest.ini backend/tests -v
```

预期：PASS，`test_models.py` 和已有 `test_api.py` 均通过。

- [ ] **步骤 5：执行显式安全与导入检查**

运行：

```powershell
$env:PYTHONPATH = "$PWD\backend"; python -c "from app.models.travel import TravelPlanDocument; print(TravelPlanDocument.__name__)"
```

预期输出：

```text
TravelPlanDocument
```

运行：

```powershell
rg -n "degraded: bool|price:|inventory:|availability:|queue_time:|discount:|rating:" backend/app/models/travel.py
```

预期：无匹配，退出码为 1；这表示合同没有定义重复降级布尔字段或禁止字段。

- [ ] **步骤 6：Commit**

```powershell
git add backend/app/models/travel.py backend/app/security.py backend/tests/test_models.py backend/tests/test_api.py
git commit -m "feat: add travel plan document contract"
```

---

## 验证记录

- 红灯阶段：API UUID v6 用例因安全中间件原样回显 v6 失败；非知识库来源使用 `knowledge_base` 状态的 3 个用例因模型未拒绝失败；文档来源/警告漏项与伪造值用例因未强制聚合失败。序列化回归用例已先通过，证明既有 JSON 数组行为满足要求。
- 本次绿灯验证：定向 API 测试 2 项通过，定向模型测试 6 项通过；完整模型测试 142 项通过；完整后端测试 147 项通过；`git diff --check` 通过。
- 任务 4 步骤 4 已完成并勾选；红灯历史步骤保持未勾选，红灯命令与失败原因如上；未提交。

## 计划自检

### 规格覆盖度

- `TravelPlanRequest`、默认 3 天、`nights`、边界、未知字段：任务 1。
- `Source` 的来源类型、数据状态、更新时间、读取时间、知识库版本与 HTTPS URL：任务 2。
- POI、天气、路线的基础事实模型、禁止字段和数值边界：任务 2。
- 天气、路线、住宿、餐饮四类领域计划结果：任务 3。
- `success`、`partial`、`degraded`、`failed` 的唯一状态与跨字段约束：任务 3。
- 受控错误、警告、缺失字段、请求与追踪标识：任务 3。
- `TravelPlanData`、`TravelPlanDocument`、结构化 `itinerary + markdown`、降级 Agent 一致性：任务 4。
- 模型拒绝密钥、原始异常和其他未知安全字段：任务 1 与任务 2 的 `extra="forbid"` 测试；任务 4 的全量回归。
- 不实现外部服务、Agent、编排器、API 和前端：文件结构与各任务范围均未涉及这些模块。

### 占位符扫描

计划未使用「TODO」「待定」「后续实现」「添加适当的错误处理」「类似任务」等未定义实现描述。每个代码变更步骤提供了具体文件、完整代码片段、命令与预期结果。

### 类型一致性

- 所有任务都使用同一组 `AgentStatus`、`Source`、`WeatherPlanData`、`RoutePlanData`、`LodgingPlanData`、`FoodPlanData`、`AgentResult`、`TravelPlanData` 与 `TravelPlanDocument` 名称。
- `AgentResult` 的状态约束与规格中的 `success`、`partial`、`degraded`、`failed` 规则一致。
- `TravelPlanDocument.degraded_agents` 始终由 `TravelPlanData` 内的四个 `AgentResult.status` 推导和验证。
- 计划只创建模型包、模型实现与测试，不修改已完成的安全后端骨架。
