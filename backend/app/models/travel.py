from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)
from uuid import UUID


def validate_uuid_v1_to_v5(value: str) -> str:
    """校验字符串为 UUID v1 至 v5。"""

    parsed = UUID(value)
    if parsed.version not in {1, 2, 3, 4, 5}:
        raise ValueError("必须是 UUID v1 至 v5")
    return str(parsed)


class StrictModel(BaseModel):
    """禁止接收未声明字段且构造后不可修改的基础模型。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


NonEmptyText = Annotated[str, Field(min_length=1, max_length=100)]
UUIDV1ToV5 = Annotated[str, AfterValidator(validate_uuid_v1_to_v5)]


class DataStatus(StrEnum):
    """数据状态。"""

    realtime = "realtime"
    cached = "cached"
    knowledge_base = "knowledge_base"
    degraded = "degraded"


class SourceType(StrEnum):
    """来源类型。"""

    weather_api = "weather_api"
    map_api = "map_api"
    poi_api = "poi_api"
    knowledge_base = "knowledge_base"


class WeatherRiskLevel(StrEnum):
    """天气风险等级。"""

    low = "low"
    medium = "medium"
    high = "high"


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


class Source(StrictModel):
    """外部或知识库来源合同。"""

    name: NonEmptyText
    type: SourceType
    data_status: DataStatus
    source_updated_at: datetime | None = None
    retrieved_at: datetime
    url: HttpUrl | None = None
    knowledge_version: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "Source":
        """校验来源状态、时间和知识库版本之间的约束。"""

        if self.data_status in {DataStatus.realtime, DataStatus.cached}:
            if self.source_updated_at is None:
                raise ValueError("实时或缓存来源必须提供上游更新时间")
        if self.type is SourceType.knowledge_base:
            if self.data_status is not DataStatus.knowledge_base:
                raise ValueError("知识库来源的数据状态必须为 knowledge_base")
            if self.knowledge_version is None:
                raise ValueError("知识库来源必须提供版本")
        else:
            if self.data_status is DataStatus.knowledge_base:
                raise ValueError("非知识库来源不得标记为 knowledge_base")
            if self.knowledge_version is not None:
                raise ValueError("非知识库来源不得提供知识库版本")
        if self.url is not None and self.url.scheme != "https":
            raise ValueError("来源 URL 仅允许 HTTPS")
        return self


class NormalizedLocation(StrictModel):
    """标准化地点事实。"""

    name: NonEmptyText
    location: str | None = None
    adcode: str | None = None


class PoiCandidate(StrictModel):
    """候选 POI 基础事实。"""

    name: NonEmptyText
    address: str | None = None
    location: str | None = None
    category: NonEmptyText
    tags: tuple[NonEmptyText, ...] = ()
    source_ids: tuple[NonEmptyText, ...] = Field(min_length=1)


class DailyWeather(StrictModel):
    """单日天气基础事实。"""

    date: date
    condition: NonEmptyText
    temp_min: int | None = None
    temp_max: int | None = None
    risk_level: WeatherRiskLevel
    activity_suitability: str | None = None
    equipment_suggestions: tuple[NonEmptyText, ...] = ()


class RouteEstimate(StrictModel):
    """路线估算基础事实。"""

    distance_meters: int = Field(ge=0)
    duration_minutes: int = Field(ge=0)
    is_estimate: Literal[True] = True


class DailyArea(StrictModel):
    """每日活动区域基础事实。"""

    day: int = Field(ge=1)
    area: NonEmptyText
    activity_window: str | None = None


class WeatherPlanData(StrictModel):
    """天气 Agent 的规划结果。"""

    destination: NonEmptyText
    daily: tuple[DailyWeather, ...] = ()
    constraints: tuple[NonEmptyText, ...] = ()


class RoutePlanData(StrictModel):
    """路线 Agent 的规划结果。"""

    origin: NonEmptyText
    destination: NonEmptyText
    round_trip: RouteEstimate | None = None
    daily_areas: tuple[DailyArea, ...] = Field(min_length=1)
    weather_adjusted: bool


class LodgingCandidate(StrictModel):
    """住宿候选项。"""

    poi: PoiCandidate
    facilities: tuple[NonEmptyText, ...] = ()
    suitable_for: tuple[NonEmptyText, ...] = ()
    commute_note: str | None = None
    recommendation_reason: str | None = None


class LodgingPlanData(StrictModel):
    """住宿 Agent 的规划结果。"""

    nights: int = Field(ge=0)
    recommended_area: NonEmptyText
    candidates: tuple[LodgingCandidate, ...] = ()
    filter_suggestions: tuple[NonEmptyText, ...] = ()


class FoodCandidate(StrictModel):
    """餐饮候选项。"""

    poi: PoiCandidate
    cuisine: str | None = None
    specialties: tuple[NonEmptyText, ...] = ()
    suitable_for: tuple[NonEmptyText, ...] = ()
    dietary_notes: tuple[NonEmptyText, ...] = ()
    business_hours_note: str | None = None


class DailyFoodPlan(StrictModel):
    """单日餐饮规划。"""

    day: int = Field(ge=1)
    area: NonEmptyText
    meal_period: str | None = None
    candidates: tuple[FoodCandidate, ...] = ()
    filter_suggestions: tuple[NonEmptyText, ...] = ()


class FoodPlanData(StrictModel):
    """餐饮 Agent 的规划结果。"""

    daily_food: tuple[DailyFoodPlan, ...] = Field(min_length=1)


class ErrorDetail(StrictModel):
    """面向调用方的受控错误信息。"""

    code: NonEmptyText
    message: NonEmptyText
    retryable: bool


ResultData = TypeVar("ResultData")


class AgentResult(StrictModel, Generic[ResultData]):
    """专业 Agent 的通用结果信封。"""

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
    def validate_status_contract(self) -> "AgentResult[ResultData]":
        """校验状态、数据、缺失字段和错误之间的约束。"""

        if self.status is AgentStatus.success:
            if self.data is None or self.missing_fields or self.error is not None:
                raise ValueError("success 结果必须含数据且不得含缺失字段或错误")
        elif self.status is AgentStatus.partial:
            if self.data is None or not self.missing_fields:
                raise ValueError("partial 结果必须含数据和缺失字段")
        elif self.status is AgentStatus.degraded:
            if self.data is None or (not self.missing_fields and self.error is None):
                raise ValueError("degraded 结果必须含数据及缺失字段或错误")
        elif self.data is not None or not self.missing_fields or self.error is None:
            raise ValueError("failed 结果不得含数据且必须含缺失字段和错误")
        if self.trace_id != self.request_id:
            raise ValueError("trace_id 必须与 request_id 一致")
        return self


class TravelPlanData(StrictModel):
    """四个专业 Agent 的结构化行程结果。"""

    weather: AgentResult[WeatherPlanData]
    route: AgentResult[RoutePlanData]
    lodging: AgentResult[LodgingPlanData]
    food: AgentResult[FoodPlanData]

    @model_validator(mode="after")
    def validate_agent_slots(self) -> "TravelPlanData":
        """校验各专业槽位只能接收同名 Agent 结果。"""

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
    """面向调用方的最终行程文档合同。"""

    request_id: UUIDV1ToV5
    trace_id: UUIDV1ToV5
    status: Literal[AgentStatus.success, AgentStatus.degraded, AgentStatus.failed]
    itinerary: TravelPlanData
    markdown: Annotated[str, Field(min_length=1)]
    sources: tuple[Source, ...] = ()
    warnings: tuple[NonEmptyText, ...] = ()
    degraded_agents: tuple[AgentName, ...] = ()

    @model_validator(mode="after")
    def validate_document_contract(self) -> "TravelPlanDocument":
        """校验关联标识、降级专业项和整体状态。"""

        results = {
            "weather": self.itinerary.weather,
            "route": self.itinerary.route,
            "lodging": self.itinerary.lodging,
            "food": self.itinerary.food,
        }
        for name, result in results.items():
            if result.request_id != self.request_id:
                raise ValueError(f"{name} 的 request_id 必须与文档一致")
            if result.trace_id != self.trace_id:
                raise ValueError(f"{name} 的 trace_id 必须与文档一致")

        expected_sources: list[Source] = []
        seen_source_keys: set[tuple[object, ...]] = set()
        expected_warnings: list[str] = []
        for result in results.values():
            for source in result.sources:
                source_key = (
                    source.name,
                    source.type,
                    source.data_status,
                    source.source_updated_at,
                    str(source.url) if source.url is not None else None,
                    source.knowledge_version,
                )
                if source_key not in seen_source_keys:
                    seen_source_keys.add(source_key)
                    expected_sources.append(source)
            expected_warnings.extend(result.warnings)
        if self.sources != tuple(expected_sources):
            raise ValueError("文档来源必须按专业结果首次出现顺序去重聚合")
        if self.warnings != tuple(expected_warnings):
            raise ValueError("文档警告必须按专业结果顺序聚合")

        if len(self.degraded_agents) != len(set(self.degraded_agents)):
            raise ValueError("degraded_agents 不得包含重复项")
        degraded_agents = {
            name for name, result in results.items() if result.status is AgentStatus.degraded
        }
        if set(self.degraded_agents) != degraded_agents:
            raise ValueError("degraded_agents 必须与降级专业项完全一致")

        statuses = {result.status for result in results.values()}
        if self.status is AgentStatus.success:
            if AgentStatus.degraded in statuses or AgentStatus.failed in statuses:
                raise ValueError("success 文档不得包含 degraded 或 failed 专业结果")
        elif self.status is AgentStatus.degraded:
            if AgentStatus.degraded not in statuses or AgentStatus.failed in statuses:
                raise ValueError("degraded 文档必须包含 degraded 且不得包含 failed 专业结果")
        elif AgentStatus.failed not in statuses:
            raise ValueError("failed 文档必须包含 failed 专业结果")
        return self


class TravelPlanRequest(StrictModel):
    """旅行规划请求的数据合同。"""

    origin: NonEmptyText
    destination: NonEmptyText
    departure_date: date
    travelers: Annotated[int, Field(ge=1, le=20)]
    days: Annotated[int, Field(ge=1, le=14)] = 3
    budget: Annotated[int | None, Field(ge=0, le=200000)] = None
    preferences: Annotated[tuple[NonEmptyText, ...], Field(max_length=12)] = ()

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        """去除出发地和目的地的首尾空白。"""

        return value.strip() if isinstance(value, str) else value

    @field_validator("preferences", mode="before")
    @classmethod
    def normalize_preferences(cls, value: object) -> object:
        """去除偏好项的首尾空白。"""

        if not isinstance(value, list):
            raise ValueError("偏好必须是列表")
        return [item.strip() if isinstance(item, str) else item for item in value]

    @field_validator("departure_date")
    @classmethod
    def validate_departure_date(cls, value: date) -> date:
        """确保出发日期不早于服务端当天。"""

        if value < date.today():
            raise ValueError("出发日期不得早于当天")
        return value

    @property
    def nights(self) -> int:
        """返回住宿晚数。"""

        return max(self.days - 1, 0)
