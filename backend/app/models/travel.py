from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class StrictModel(BaseModel):
    """禁止接收未声明字段的基础模型。"""

    model_config = ConfigDict(extra="forbid")


NonEmptyText = Annotated[str, Field(min_length=1, max_length=100)]


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
        elif self.knowledge_version is not None:
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
    tags: list[NonEmptyText] = Field(default_factory=list)
    source_ids: list[NonEmptyText] = Field(min_length=1)


class DailyWeather(StrictModel):
    """单日天气基础事实。"""

    date: date
    condition: NonEmptyText
    temp_min: int | None = None
    temp_max: int | None = None
    risk_level: WeatherRiskLevel
    activity_suitability: str | None = None
    equipment_suggestions: list[NonEmptyText] = Field(default_factory=list)


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
    daily: list[DailyWeather] = Field(min_length=1)
    constraints: list[NonEmptyText] = Field(default_factory=list)


class RoutePlanData(StrictModel):
    """路线 Agent 的规划结果。"""

    origin: NonEmptyText
    destination: NonEmptyText
    round_trip: RouteEstimate | None = None
    daily_areas: list[DailyArea] = Field(min_length=1)
    weather_adjusted: bool


class LodgingCandidate(StrictModel):
    """住宿候选项。"""

    poi: PoiCandidate
    facilities: list[NonEmptyText] = Field(default_factory=list)
    suitable_for: list[NonEmptyText] = Field(default_factory=list)
    commute_note: str | None = None
    recommendation_reason: str | None = None


class LodgingPlanData(StrictModel):
    """住宿 Agent 的规划结果。"""

    nights: int = Field(ge=0)
    recommended_area: NonEmptyText
    candidates: list[LodgingCandidate] = Field(default_factory=list)
    filter_suggestions: list[NonEmptyText] = Field(default_factory=list)


class FoodCandidate(StrictModel):
    """餐饮候选项。"""

    poi: PoiCandidate
    cuisine: str | None = None
    specialties: list[NonEmptyText] = Field(default_factory=list)
    suitable_for: list[NonEmptyText] = Field(default_factory=list)
    dietary_notes: list[NonEmptyText] = Field(default_factory=list)
    business_hours_note: str | None = None


class DailyFoodPlan(StrictModel):
    """单日餐饮规划。"""

    day: int = Field(ge=1)
    area: NonEmptyText
    meal_period: str | None = None
    candidates: list[FoodCandidate] = Field(default_factory=list)
    filter_suggestions: list[NonEmptyText] = Field(default_factory=list)


class FoodPlanData(StrictModel):
    """餐饮 Agent 的规划结果。"""

    daily_food: list[DailyFoodPlan] = Field(min_length=1)


class ErrorDetail(StrictModel):
    """面向调用方的受控错误信息。"""

    code: NonEmptyText
    message: NonEmptyText
    retryable: bool


ResultData = TypeVar("ResultData")


class AgentResult(StrictModel, Generic[ResultData]):
    """专业 Agent 的通用结果信封。"""

    agent: NonEmptyText
    status: AgentStatus
    summary: NonEmptyText
    data: ResultData | None = None
    constraints: list[NonEmptyText] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)
    missing_fields: list[NonEmptyText] = Field(default_factory=list)
    error: ErrorDetail | None = None
    request_id: str
    trace_id: str

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
        return self


class TravelPlanData(StrictModel):
    """四个专业 Agent 的结构化行程结果。"""

    weather: AgentResult[WeatherPlanData]
    route: AgentResult[RoutePlanData]
    lodging: AgentResult[LodgingPlanData]
    food: AgentResult[FoodPlanData]


class TravelPlanDocument(StrictModel):
    """面向调用方的最终行程文档合同。"""

    request_id: str
    trace_id: str
    status: Literal[AgentStatus.success, AgentStatus.degraded, AgentStatus.failed]
    itinerary: TravelPlanData
    markdown: Annotated[str, Field(min_length=1)]
    sources: list[Source] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)
    degraded_agents: list[NonEmptyText] = Field(default_factory=list)

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
    preferences: Annotated[list[NonEmptyText], Field(max_length=12)] = Field(
        default_factory=list
    )

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
