from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """禁止接收未声明字段的基础模型。"""

    model_config = ConfigDict(extra="forbid")


NonEmptyText = Annotated[str, Field(min_length=1, max_length=100)]


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
    def normalize_preferences(cls, value: list[str]) -> list[str]:
        """去除偏好项的首尾空白。"""

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
