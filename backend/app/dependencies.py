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
from app.services.heweather import HeWeatherClient
from app.services.resilience import CircuitBreaker


def build_orchestrator(settings: Settings) -> SequentialTravelOrchestrator:
    """按服务端配置组装完整旅行规划编排。"""

    timeout = httpx.Timeout(
        settings.external_total_timeout_seconds,
        connect=settings.external_connect_timeout_seconds,
        read=settings.external_read_timeout_seconds,
        write=settings.external_read_timeout_seconds,
        pool=settings.external_total_timeout_seconds,
    )
    cache = MemoryCache()
    weather_breaker = CircuitBreaker(
        settings.circuit_breaker_failure_threshold,
        settings.circuit_breaker_open_seconds,
    )
    amap_breaker = CircuitBreaker(
        settings.circuit_breaker_failure_threshold,
        settings.circuit_breaker_open_seconds,
    )
    weather_client = HeWeatherClient(
        settings.heweather_api_key,
        base_url=settings.heweather_base_url,
        cache=cache,
        breaker=weather_breaker,
        max_attempts=settings.external_max_attempts,
        cache_ttl_seconds=settings.weather_cache_ttl_seconds,
        timeout=timeout,
    )
    amap_client = AmapClient(
        settings.amap_api_key,
        base_url=settings.amap_base_url,
        cache=cache,
        breaker=amap_breaker,
        max_attempts=settings.external_max_attempts,
        geocode_cache_ttl_seconds=settings.amap_geocode_cache_ttl_seconds,
        route_cache_ttl_seconds=settings.amap_route_cache_ttl_seconds,
        poi_cache_ttl_seconds=settings.amap_poi_cache_ttl_seconds,
        timeout=timeout,
    )
    return SequentialTravelOrchestrator(
        WeatherAgent(weather_client, amap_client),
        RouteAgent(amap_client),
        LodgingAgent(amap_client),
        FoodAgent(amap_client),
        SummaryAgent(),
    )
