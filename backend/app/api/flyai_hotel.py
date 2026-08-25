from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.errors import FliggyHotelNotConfigured
from app.models.flyai_hotel import CombinedHotelResult, FlyAIHotelSearchRequest
from app.services.flyai_hotel_client import FlyAIHotelError

router = APIRouter(prefix="/api/fliggy", tags=["fliggy"])


class HotelRecommendationResponse(BaseModel):
    """FlyAI 酒店与高德 POI 并列推荐结果的 JSON 合同。"""

    hotels: tuple[CombinedHotelResult, ...]
    flyai_retrieved_at: datetime
    amap_retrieved_at: datetime | None
    poi_unavailable: bool


@router.post("/hotels/recommend", response_model=HotelRecommendationResponse)
async def recommend_hotels(
    payload: FlyAIHotelSearchRequest, request: Request
) -> HotelRecommendationResponse:
    trace_id = getattr(request.state, "request_id", None) or str(uuid4())
    service = request.app.state.flyai_hotel_recommendation_service
    server_limit = request.app.state.settings.flyai_hotel_limit
    if server_limit < payload.limit:
        payload = payload.model_copy(update={"limit": server_limit})
    try:
        result = await service.recommend(payload)
    except FliggyHotelNotConfigured as error:
        raise HTTPException(status_code=503, detail="飞猪酒店查询服务尚未配置") from error
    except FlyAIHotelError as error:
        raise HTTPException(
            status_code=502, detail={"code": error.code, "trace_id": trace_id}
        ) from error
    return HotelRecommendationResponse(
        hotels=result,
        flyai_retrieved_at=result.flyai_retrieved_at,
        amap_retrieved_at=result.amap_retrieved_at,
        poi_unavailable=result.poi_unavailable,
    )
