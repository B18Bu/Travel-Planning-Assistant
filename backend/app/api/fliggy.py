import inspect
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from app.errors import FliggyHotelNotConfigured, FliggyHotelUpstreamError
from app.models.fliggy import FliggyServiceStatus, TicketSearchRequest
from app.models.fliggy_hotel import FliggyHotelSearchRequest, FliggyHotelSearchResponse
from app.services.fliggy import FliggyNotConfiguredError

router = APIRouter(prefix="/api/fliggy", tags=["fliggy"])


@router.get("/status", response_model=FliggyServiceStatus)
async def get_fliggy_status(request: Request) -> FliggyServiceStatus:
    return request.app.state.fliggy_ticket_service.status()


@router.post("/hotels/search", response_model=FliggyHotelSearchResponse)
async def search_hotels(payload: FliggyHotelSearchRequest, request: Request):
    trace_id = getattr(request.state, "request_id", None) or str(uuid4())
    try:
        return await request.app.state.fliggy_hotel_service.search(payload, trace_id)
    except FliggyHotelNotConfigured as error:
        raise HTTPException(status_code=503, detail="飞猪酒店查询服务尚未配置") from error
    except FliggyHotelUpstreamError as error:
        detail = {"code": error.code, "trace_id": trace_id}
        if error.provider_code is not None:
            detail["provider_code"] = error.provider_code
        raise HTTPException(status_code=502, detail=detail) from error


@router.post("/tickets/search")
async def search_tickets(payload: TicketSearchRequest, request: Request):
    try:
        result = request.app.state.fliggy_ticket_service.search_tickets(payload)
        if inspect.isawaitable(result):
            result = await result
        return result
    except FliggyNotConfiguredError as error:
        raise HTTPException(status_code=503, detail="飞猪门票查询服务尚未配置") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="实时门票查询暂不可用") from error
