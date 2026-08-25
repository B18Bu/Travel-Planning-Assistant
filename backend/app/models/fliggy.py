from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TicketSearchRequest(BaseModel):
    """门票查询请求；游客人数仅用于本地校验和结果上下文。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenic_keyword: str = Field(min_length=1, max_length=100)
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
