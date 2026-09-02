from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.models.planning import TravelPlanRevisionRequest, TravelQueryParseRequest, TravelQueryParseResponse
from app.models.travel import TravelPlanDocument, TravelPlanRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/travel-plans/parse", response_model=TravelQueryParseResponse)
async def parse_travel_query(payload: TravelQueryParseRequest, request: Request) -> TravelQueryParseResponse:
    parser = getattr(request.app.state, "query_parser", None)
    if parser is None:
        raise HTTPException(status_code=503, detail="需求解析服务尚未配置")
    try:
        return await parser.parse(payload.query)
    except Exception as error:
        raise HTTPException(status_code=422, detail="无法解析旅行需求，请补充始发地、目的地、日期、人数和天数") from error


@router.post("/travel-plans", response_model=TravelPlanDocument)
async def create_travel_plan(
    payload: TravelPlanRequest, request: Request
) -> TravelPlanDocument:
    request_id = request.state.request_id
    try:
        document = await request.app.state.orchestrator.run(
            payload, request_id, trace_id=request_id
        )
        request.app.state.travel_plan_store.save(request.headers.get("X-Travel-Query", ""), payload, document)
        return document
    except Exception as error:
        logger.exception("旅行规划执行失败")
        raise HTTPException(status_code=500, detail="旅行规划暂时不可用") from error


@router.get("/travel-plans/saved")
async def list_saved_travel_plans(request: Request) -> list[dict]:
    return request.app.state.travel_plan_store.list()


@router.get("/travel-plans/saved/{plan_id}")
async def get_saved_travel_plan(plan_id: str, request: Request) -> dict:
    record = request.app.state.travel_plan_store.get(plan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="方案不存在")
    return record


@router.post("/travel-plans/saved/{plan_id}/revisions")
async def revise_saved_travel_plan(plan_id: str, payload: TravelPlanRevisionRequest, request: Request) -> dict:
    current = request.app.state.travel_plan_store.get(plan_id)
    if current is None:
        raise HTTPException(status_code=404, detail="方案不存在")
    parser = request.app.state.query_parser
    parsed = await parser.parse(f"{current.get('query', '')}\n请按以下要求修改：{payload.query}")
    if parsed.missing_fields or parsed.ambiguous_fields:
        raise HTTPException(status_code=422, detail="修改后缺少必填旅行信息")
    new_request = TravelPlanRequest(**parsed.model_dump(exclude={"missing_fields", "ambiguous_fields"}))
    document = await request.app.state.orchestrator.run(new_request, request.state.request_id, trace_id=request.state.request_id)
    updated = request.app.state.travel_plan_store.revise(plan_id, payload.version, payload.query, new_request, document)
    if updated is None:
        raise HTTPException(status_code=409, detail="方案已被其他修改覆盖，请刷新后重试")
    return updated
