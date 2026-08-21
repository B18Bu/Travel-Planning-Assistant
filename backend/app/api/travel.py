from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.models.travel import TravelPlanDocument, TravelPlanRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/travel-plans", response_model=TravelPlanDocument)
async def create_travel_plan(
    payload: TravelPlanRequest, request: Request
) -> TravelPlanDocument:
    request_id = request.state.request_id
    try:
        return await request.app.state.orchestrator.run(
            payload, request_id, trace_id=request_id
        )
    except Exception as error:
        logger.exception("旅行规划执行失败")
        raise HTTPException(status_code=500, detail="旅行规划暂时不可用") from error
