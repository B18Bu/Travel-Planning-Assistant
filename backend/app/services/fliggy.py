from datetime import datetime, timezone

from app.models.fliggy import (
    FliggyServiceStatus,
    TicketPoiReference,
    TicketProduct,
    TicketSearchRequest,
    TicketSearchResponse,
)
from app.services.fliggy_flyai_client import FlyAIClient


class FliggyNotConfiguredError(RuntimeError):
    """飞猪门票查询功能未启用或尚未完成配置。"""


class DisabledFliggyTicketService:
    """默认关闭态，不执行任何外部网络请求。"""

    def status(self) -> FliggyServiceStatus:
        return FliggyServiceStatus(
            available=False,
            message="飞猪门票查询服务尚未配置",
        )

    def search_tickets(self, request: TicketSearchRequest):
        raise FliggyNotConfiguredError


class MockFliggyTicketService:
    """本地演示适配器，明确返回 mock 数据，不访问飞猪。"""

    def status(self) -> FliggyServiceStatus:
        return FliggyServiceStatus(available=True, message="门票查询演示服务")

    def search_tickets(self, request: TicketSearchRequest) -> TicketSearchResponse:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        if request.scenic_keyword not in {"西湖", "故宫", "黄山"}:
            return TicketSearchResponse(
                source_name="演示数据",
                retrieved_at=retrieved_at,
                data_status="mock",
                scenic_keyword=request.scenic_keyword,
                visitor_count=request.visitor_count,
                warnings=("未找到演示门票商品，请调整景点关键词。",),
            )

        scenic = request.scenic_keyword
        tickets = (
            TicketProduct(
                item_id=f"mock-{scenic}-adult",
                item_name=f"{scenic}景区门票",
                ticket_type="成人票",
                entry_date=request.entry_date,
                price_amount=1234,
                stock=12,
                stock_status="available",
                entry_type="二维码直接入园",
                entry_address=f"{scenic}景区入口",
                refund_description="演示退改规则，请以官方渠道为准",
                visitor_requirement="购票时可能需要游客信息",
                purchase_limit="演示限购规则",
            ),
            TicketProduct(
                item_id=f"mock-{scenic}-child",
                item_name=f"{scenic}景区门票",
                ticket_type="儿童票",
                entry_date=request.entry_date,
                price_amount=800,
                stock=0,
                stock_status="empty",
                entry_type="二维码直接入园",
                entry_address=f"{scenic}景区入口",
                refund_description="演示退改规则，请以官方渠道为准",
                visitor_requirement="购票时可能需要游客信息",
                purchase_limit="演示限购规则",
            ),
        )
        return TicketSearchResponse(
            source_name="演示数据",
            retrieved_at=retrieved_at,
            data_status="mock",
            scenic_keyword=request.scenic_keyword,
            visitor_count=request.visitor_count,
            tickets=tickets,
            warnings=("当前为演示数据，不代表飞猪实时价格、库存或可售状态。",),
        )


class FlyAIFliggyTicketService:
    """FlyAI 只读文本检索门票服务；不填充结构化价格、库存或 SKU。"""

    def __init__(self, client: FlyAIClient) -> None:
        self._client = client

    def status(self) -> FliggyServiceStatus:
        return FliggyServiceStatus(available=True, message="FlyAI 门票文本检索服务")

    async def search_tickets(self, request: TicketSearchRequest) -> TicketSearchResponse:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        if request.city_name.strip():
            return await self._search_poi(request, retrieved_at)
        summary = await self._client.search(request.scenic_keyword, request.entry_date)
        if not summary or not summary.strip():
            return TicketSearchResponse(
                source_name="飞猪 AI 开放平台",
                retrieved_at=retrieved_at,
                data_status="flyai_text",
                scenic_keyword=request.scenic_keyword,
                visitor_count=request.visitor_count,
                warnings=("未找到相关门票信息，请调整关键词后重试。",),
            )
        return TicketSearchResponse(
            source_name="飞猪 AI 开放平台",
            retrieved_at=retrieved_at,
            data_status="flyai_text",
            scenic_keyword=request.scenic_keyword,
            visitor_count=request.visitor_count,
            summary=summary.strip(),
            warnings=(
                "FlyAI 文本检索结果，不代表实时可售状态。",
                "价格信息暂不可用。",
                "库存信息暂不可用。请以飞猪官方页面为准。",
            ),
        )

    async def _search_poi(
        self, request: TicketSearchRequest, retrieved_at: str
    ) -> TicketSearchResponse:
        pois = await self._client.search_poi(request.city_name, request.scenic_keyword)
        poi_results = tuple(
            TicketPoiReference(
                poi_name=poi.poi_name,
                address=poi.address,
                category=poi.category,
                ticket_name=poi.ticket_name,
                price_text=poi.price_text,
                price_date=poi.price_date,
                description=poi.description,
            )
            for poi in pois
        )
        if not poi_results:
            return TicketSearchResponse(
                source_name="飞猪 AI 开放平台",
                retrieved_at=retrieved_at,
                data_status="flyai_text",
                scenic_keyword=request.scenic_keyword,
                city_name=request.city_name,
                visitor_count=request.visitor_count,
                warnings=("未找到相关门票信息，请调整关键词或城市后重试。",),
            )
        summary = next(
            (poi.description for poi in poi_results if poi.description), None
        )
        return TicketSearchResponse(
            source_name="飞猪 AI 开放平台",
            retrieved_at=retrieved_at,
            data_status="flyai_text",
            scenic_keyword=request.scenic_keyword,
            city_name=request.city_name,
            visitor_count=request.visitor_count,
            poi_results=poi_results,
            summary=summary,
            warnings=("门票价格与票种为飞猪平台参考信息，以官方页面为准，不代表实时可售状态。",),
        )
