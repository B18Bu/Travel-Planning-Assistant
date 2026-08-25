from fastapi import APIRouter, HTTPException, Request

from app.models.fliggy import FliggyServiceStatus, TicketSearchRequest

router = APIRouter(prefix="/api/fliggy", tags=["fliggy"])


@router.get("/status", response_model=FliggyServiceStatus)
async def get_fliggy_status(request: Request) -> FliggyServiceStatus:
    return request.app.state.fliggy_ticket_service.status()


@router.post("/tickets/search")
async def search_tickets(payload: TicketSearchRequest, request: Request):
    try:
        return request.app.state.fliggy_ticket_service.search_tickets(payload)
    except Exception as error:
        if error.__class__.__name__ == "FliggyNotConfiguredError":
            raise HTTPException(status_code=503, detail="飞猪门票查询服务尚未配置") from error
        raise HTTPException(status_code=503, detail="实时门票查询暂不可用") from error
