import inspect

from fastapi import APIRouter, HTTPException, Request

from app.models.fliggy import FliggyServiceStatus, TicketSearchRequest
from app.services.fliggy import FliggyNotConfiguredError

router = APIRouter(prefix="/api/fliggy", tags=["fliggy"])


@router.get("/status", response_model=FliggyServiceStatus)
async def get_fliggy_status(request: Request) -> FliggyServiceStatus:
    return request.app.state.fliggy_ticket_service.status()


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
