from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import Field, field_validator

from app.models.travel import NonEmptyText, StrictModel, TravelPreferenceProfile


class TravelQueryParseRequest(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=4000)]

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return value.strip()


class TravelQueryParseResponse(StrictModel):
    origin: str | None = None
    destination: str | None = None
    departure_date: date | None = None
    travelers: int | None = Field(default=None, ge=1, le=20)
    days: int | None = Field(default=None, ge=1, le=14)
    budget: int | None = Field(default=None, ge=0, le=200000)
    preferences: tuple[NonEmptyText, ...] = Field(default=(), max_length=12)
    profile: TravelPreferenceProfile = Field(default_factory=TravelPreferenceProfile)
    missing_fields: tuple[NonEmptyText, ...] = ()
    ambiguous_fields: tuple[NonEmptyText, ...] = ()

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def normalize_location(cls, value):
        return value.strip() if isinstance(value, str) else value


class TravelPlanRevisionRequest(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    version: int = Field(ge=1)
