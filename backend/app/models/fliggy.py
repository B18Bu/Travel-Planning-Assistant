from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TicketSearchRequest(BaseModel):
    """门票查询请求；游客人数仅用于本地校验和结果上下文。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenic_keyword: str = Field(min_length=1, max_length=100)
    city_name: str = Field(default="", max_length=50)
    entry_date: date
    visitor_count: int = Field(ge=1, le=20)

    @field_validator("entry_date")
    @classmethod
    def entry_date_must_not_be_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("入园日期不得早于今天")
        return value


class FliggyServiceStatus(BaseModel):
    """对前端公开的飞猪服务状态。"""

    model_config = ConfigDict(extra="forbid")

    available: bool
    message: str


class TicketProduct(BaseModel):
    """门票商品的安全展示字段。"""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    item_name: str
    ticket_type: str
    entry_date: date
    price_amount: int
    currency: str = "CNY"
    price_unit: str = "分"
    stock: int | None
    stock_status: Literal["available", "empty", "unknown"]
    entry_type: str
    entry_address: str
    refund_description: str
    visitor_requirement: str
    purchase_limit: str
    image_urls: tuple[str, ...] = ()


class TicketPoiReference(BaseModel):
    """FlyAI search-poi 返回的景点门票参考；价格与票种为官方参考，非实时保证。"""

    model_config = ConfigDict(extra="forbid")

    poi_name: str
    address: str | None = None
    category: str | None = None
    ticket_name: str | None = None
    price_text: str | None = None
    price_date: str | None = None
    description: str | None = None


class TicketSearchResponse(BaseModel):
    """门票查询规范化响应。"""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    retrieved_at: str
    data_status: Literal["mock", "realtime", "degraded", "flyai_text"]
    scenic_keyword: str
    city_name: str = ""
    visitor_count: int
    tickets: tuple[TicketProduct, ...] = ()
    poi_results: tuple[TicketPoiReference, ...] = ()
    warnings: tuple[str, ...] = ()
    summary: str | None = None
