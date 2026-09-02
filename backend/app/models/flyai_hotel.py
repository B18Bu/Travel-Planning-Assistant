from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, field_serializer, field_validator, model_validator

from app.models.travel import NonEmptyText, StrictModel


HotelText = Annotated[str, Field(min_length=1, max_length=200)]
SortOrder = Literal["distance_asc", "rate_desc", "price_asc", "price_desc", "no_rank"]


def _serialize_decimal(value: Decimal | None) -> int | float | None:
    """将 Decimal 编码为 JSON 数字，缺失值仍保持 None。"""

    if value is None:
        return None
    if value == value.to_integral_value():
        return int(value)
    return float(value)


class FlyAIHotelSearchRequest(StrictModel):
    """FlyAI 酒店查询请求。"""

    city_name: NonEmptyText
    check_in: date
    check_out: date
    poi_name: NonEmptyText | None = None
    sort: SortOrder = "rate_desc"
    max_price: Annotated[Decimal | None, Field(default=None, ge=Decimal("0"))]
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("city_name", "poi_name", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        """清洗查询文本首尾空白。"""

        return value.strip() if isinstance(value, str) else value

    @field_validator("check_in", "check_out", mode="before")
    @classmethod
    def require_date_only_input(cls, value: object) -> object:
        """仅接受日期对象或严格 YYYY-MM-DD 字符串。"""

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
    def check_date_order(self) -> "FlyAIHotelSearchRequest":
        """校验入住日期早于离店日期。"""

        if self.check_in >= self.check_out:
            raise ValueError("入住日期必须早于离店日期")
        return self

    @field_serializer("max_price", when_used="json")
    def serialize_max_price(self, value: Decimal | None) -> int | float | None:
        return _serialize_decimal(value)


class FlyAIHotel(StrictModel):
    """FlyAI 酒店原始响应的白名单投影。"""

    hotel_id: NonEmptyText
    name: NonEmptyText
    address: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    price: Annotated[Decimal | None, Field(default=None, ge=Decimal("0"))]
    score: Decimal | None = None
    star: int | None = None
    main_pic: HttpUrl | None = None
    detail_url: HttpUrl | None = None

    @field_validator("hotel_id", mode="before")
    @classmethod
    def stringify_hotel_id(cls, value: object) -> object:
        """将非空整数或字符串酒店 ID 统一为字符串。"""

        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError("酒店 ID 必须是整数或字符串")
        if isinstance(value, str) and not value.strip():
            raise ValueError("酒店 ID 不得为空")
        return str(value)

    @field_validator("main_pic", "detail_url")
    @classmethod
    def require_https_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        """图片和详情链接仅允许 HTTPS。"""

        if value is not None and value.scheme != "https":
            raise ValueError("图片和详情链接仅允许 HTTPS")
        return value

    @field_serializer("latitude", "longitude", "price", "score", when_used="json")
    def serialize_decimal(self, value: Decimal | None) -> int | float | None:
        return _serialize_decimal(value)


class CombinedHotelResult(StrictModel):
    """FlyAI 酒店与高德 POI 的并列合并结果。"""

    hotel_name: NonEmptyText
    flyai_price: Annotated[Decimal | None, Field(default=None, ge=Decimal("0"))]
    flyai_score: Decimal | None = None
    flyai_star: int | None = None
    flyai_main_pic: HttpUrl | None = None
    detail_url: HttpUrl | None = None
    amap_address: str | None = None
    amap_location: str | None = None
    price_source: Literal["flyai"] | None = None
    poi_source: Literal["amap"] | None = None
    match_status: Literal["matched", "flyai_only", "poi_only"]

    @field_validator("flyai_main_pic", "detail_url")
    @classmethod
    def require_https_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        """图片和详情链接仅允许 HTTPS。"""

        if value is not None and value.scheme != "https":
            raise ValueError("图片和详情链接仅允许 HTTPS")
        return value

    @field_serializer("flyai_price", "flyai_score", when_used="json")
    def serialize_decimal(self, value: Decimal | None) -> int | float | None:
        return _serialize_decimal(value)

    @model_validator(mode="after")
    def validate_sources_and_match(self) -> "CombinedHotelResult":
        """确保匹配状态与两侧白名单字段及来源标记一致。"""

        flyai_fields = (
            self.flyai_price,
            self.flyai_score,
            self.flyai_star,
            self.flyai_main_pic,
            self.detail_url,
        )
        amap_fields = (self.amap_address, self.amap_location)

        if self.flyai_price is not None and self.price_source != "flyai":
            raise ValueError("存在 FlyAI 价格时 price_source 必须为 flyai")
        if self.match_status == "matched":
            if self.poi_source != "amap" or not any(value is not None for value in flyai_fields):
                raise ValueError("matched 结果必须同时包含 FlyAI 与高德来源")
        elif self.match_status == "flyai_only":
            if self.poi_source is not None or any(value is not None for value in amap_fields):
                raise ValueError("flyai_only 结果不得包含高德字段或来源")
            if not any(value is not None for value in flyai_fields):
                raise ValueError("flyai_only 结果必须包含 FlyAI 字段")
        else:
            if self.price_source is not None or any(value is not None for value in flyai_fields):
                raise ValueError("poi_only 结果不得包含 FlyAI 字段或来源")
            if self.poi_source != "amap":
                raise ValueError("poi_only 结果必须标记高德来源")
        return self
