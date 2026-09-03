from __future__ import annotations

import httpx

from app.agents.food import FoodAgent
from app.agents.lodging import LodgingAgent
from app.agents.route import RouteAgent
from app.agents.summary import SummaryAgent
from app.agents.weather import WeatherAgent
from app.config import Settings
from app.orchestration.sequential import SequentialTravelOrchestrator
from app.services.amap import AmapClient
from app.services.cache import MemoryCache
from app.services.fliggy_hotel import HotelSearchService
from app.services.fliggy_hotel_client import FliggyHotelClient
from app.services.flyai_hotel_client import FlyAIHotelClient
from app.services.flyai_hotel_recommendation import FlyAIHotelRecommendationService
from app.services.fliggy_flyai_client import FlyAIClient
from app.services.resilience import CircuitBreaker
from app.services.travel_knowledge import TravelKnowledgeService
from app.errors import FliggyHotelNotConfigured


class _DisabledHotelSearchService:
    async def search(self, request, trace_id: str):
        raise FliggyHotelNotConfigured()


def build_hotel_search_service(settings: Settings):
    """按配置构造飞猪酒店查询服务；未配置时不创建 HTTP 客户端。"""

    credentials = (
        settings.fliggy_hotel_app_key,
        settings.fliggy_hotel_app_secret,
        settings.fliggy_hotel_sub_channel,
    )
    if not settings.fliggy_hotel_enabled or not all(
        isinstance(value, str) and bool(value.strip()) for value in credentials
    ):
        return _DisabledHotelSearchService()
    return HotelSearchService(
        FliggyHotelClient(
            *credentials,
            max_attempts=settings.external_max_attempts,
            timeout=httpx.Timeout(
                settings.external_total_timeout_seconds,
                connect=settings.external_connect_timeout_seconds,
                read=settings.external_read_timeout_seconds,
                write=settings.external_read_timeout_seconds,
                pool=settings.external_total_timeout_seconds,
            ),
            base_url=settings.fliggy_hotel_api_url,
        )
    )


class _DisabledFlyAIHotelRecommendationService:
    """FlyAI 推荐服务未启用或 Key 缺失时的安全替身，调用即抛受控错误。"""

    async def recommend(self, request):
        raise FliggyHotelNotConfigured()

    async def search(self, request):
        raise FliggyHotelNotConfigured()


def build_flyai_hotel_recommendation_service(settings: Settings):
    """按配置构造 FlyAI 酒店推荐服务；未配置时不创建任何会发请求的客户端。"""

    if not settings.flyai_hotel_enabled or not (
        isinstance(settings.flyai_api_key, str) and bool(settings.flyai_api_key.strip())
    ):
        return _DisabledFlyAIHotelRecommendationService()
    return FlyAIHotelRecommendationService(
        FlyAIHotelClient(
            settings.flyai_api_key,
            command=settings.flyai_cli_command,
            timeout_seconds=settings.flyai_cli_timeout_seconds,
        ),
        AmapClient(
            settings.amap_api_key,
            security_key=settings.amap_security_key,
            base_url=settings.amap_base_url,
            cache=MemoryCache(),
            breaker=CircuitBreaker(
                settings.circuit_breaker_failure_threshold,
                settings.circuit_breaker_open_seconds,
            ),
            max_attempts=settings.external_max_attempts,
            geocode_cache_ttl_seconds=settings.amap_geocode_cache_ttl_seconds,
            route_cache_ttl_seconds=settings.amap_route_cache_ttl_seconds,
            poi_cache_ttl_seconds=settings.amap_poi_cache_ttl_seconds,
            timeout=httpx.Timeout(
                settings.external_total_timeout_seconds,
                connect=settings.external_connect_timeout_seconds,
                read=settings.external_read_timeout_seconds,
                write=settings.external_read_timeout_seconds,
                pool=settings.external_total_timeout_seconds,
            ),
        ),
    )


def build_orchestrator(settings: Settings, *, document_store=None, chroma_store=None) -> SequentialTravelOrchestrator:
    """按服务端配置组装完整旅行规划编排。"""

    timeout = httpx.Timeout(
        settings.external_total_timeout_seconds,
        connect=settings.external_connect_timeout_seconds,
        read=settings.external_read_timeout_seconds,
        write=settings.external_read_timeout_seconds,
        pool=settings.external_total_timeout_seconds,
    )
    cache = MemoryCache()
    amap_breaker = CircuitBreaker(
        settings.circuit_breaker_failure_threshold,
        settings.circuit_breaker_open_seconds,
    )
    amap_client = AmapClient(
            settings.amap_api_key,
            security_key=settings.amap_security_key,
        base_url=settings.amap_base_url,
        cache=cache,
        breaker=amap_breaker,
        max_attempts=settings.external_max_attempts,
        geocode_cache_ttl_seconds=settings.amap_geocode_cache_ttl_seconds,
        route_cache_ttl_seconds=settings.amap_route_cache_ttl_seconds,
        poi_cache_ttl_seconds=settings.amap_poi_cache_ttl_seconds,
        timeout=timeout,
    )
    flyai_client = (
        FlyAIClient(
            settings.flyai_api_key,
            command=settings.flyai_cli_command,
            timeout_seconds=settings.flyai_cli_timeout_seconds,
        )
        if isinstance(settings.flyai_api_key, str) and settings.flyai_api_key.strip()
        else None
    )
    return SequentialTravelOrchestrator(
        WeatherAgent(amap_client, amap_client),
        RouteAgent(amap_client),
        LodgingAgent(amap_client),
        FoodAgent(amap_client, flyai_client=flyai_client),
        SummaryAgent(),
        TravelKnowledgeService(document_store, chroma_store) if document_store is not None and chroma_store is not None else None,
    )
