from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from app.models.travel import StrictModel, UUIDV1ToV5


HotelText = Annotated[str, Field(min_length=1, max_length=200)]


class FliggyHotelSearchRequest(StrictModel):
    """飞猪酒店低价查询请求。"""

    city_name: HotelText
    check_in: date
    check_out: date
    page_no: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)

    @field_validator("city_name", mode="before")
    @classmethod
    def strip_city_name(cls, value: object) -> object:
        """清洗城市名首尾空白。"""

        return value.strip() if isinstance(value, str) else value

    @field_validator("check_in", "check_out", mode="before")
    @classmethod
    def require_date_only_input(cls, value: object) -> object:
        """仅接受日期对象或 YYYY-MM-DD 字符串，不接受 datetime 字符串。"""

        if isinstance(value, datetime):
            raise ValueError("日期不得包含时间")
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
            except ValueError as error:
                raise ValueError("日期必须为 YYYY-MM-DD") from error
            if value != parsed.isoformat():
                raise ValueError("日期必须为 YYYY-MM-DD")
        return value

    @field_validator("check_in")
    @classmethod
    def check_in_not_before_today(cls, value: date) -> date:
        """入住日期不得早于今天。"""

        if value < date.today():
            raise ValueError("入住日期不得早于今天")
        return value

    @model_validator(mode="after")
    def check_date_order(self) -> "FliggyHotelSearchRequest":
        """校验入住日期早于离店日期。"""

        if self.check_in >= self.check_out:
            raise ValueError("入住日期必须早于离店日期")
        return self


class FliggyHotelSource(StrictModel):
    """飞猪酒店实时结果来源。"""

    provider: Literal["fliggy"] = "fliggy"
    retrieved_at: datetime

    @field_validator("retrieved_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        """来源获取时间必须包含 UTC 时区。"""

        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("retrieved_at 必须为 UTC 时间")
        return value


class FliggyHotel(StrictModel):
    """飞猪酒店低价结果。"""

    hotel_id: str
    name: HotelText
    low_price: Annotated[Decimal, Field(ge=Decimal("0"))]
    currency: Literal["CNY"] = "CNY"
    supplier: Literal["飞猪"] = "飞猪"

    @field_validator("hotel_id", mode="before")
    @classmethod
    def stringify_hotel_id(cls, value: object) -> str:
        """统一非空整数或字符串酒店 ID 为字符串。"""

        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError("酒店 ID 必须是整数或字符串")
        if isinstance(value, str) and not value.strip():
            raise ValueError("酒店 ID 不得为空")
        return str(value)

    @field_serializer("low_price", when_used="json")
    def serialize_low_price(self, value: Decimal) -> int | float:
        """将 Decimal 价格边界编码为 JSON 数字。"""

        if value == value.to_integral_value():
            return int(value)
        return float(value)


class FliggyHotelSearchResponse(StrictModel):
    """飞猪酒店实时低价查询响应。"""

    status: Literal["realtime"] = "realtime"
    source: FliggyHotelSource
    hotels: tuple[FliggyHotel, ...]
    total: int = Field(ge=0)
    page_no: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    trace_id: UUIDV1ToV5
