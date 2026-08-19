from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

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
