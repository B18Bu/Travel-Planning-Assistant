# 顺序编排式文旅多 Agent 核心链路实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 FastAPI 服务中实现天气 → 路线 → 住宿 → 美食 → 汇总的受控顺序 Agent 链路，使用和风天气与高德地图作为外部事实来源，并生成带来源、更新时间、风险提示与降级说明的完整文旅策划文档。

**架构：** 新建独立的领域模型、外部服务连接器、专业 Agent、固定顺序编排器和 Markdown 汇总器。所有 Agent 只返回结构化结果，编排器管理缓存、超时、降级和调用链路；汇总器只消费这些结果，禁止补充未经验证的事实。前端改为提交四项必填约束并安全渲染服务端返回的最终文档。

**技术栈：** Python 3.11+、FastAPI、Pydantic v2、httpx、pytest、pytest-asyncio、Redis（可选缓存适配）、和风天气 API、高德地图 Web 服务 API、DOMPurify、marked（固定版本）。

---

## 文件结构

> 当前目录仅包含设计文档，尚无实际应用源码。本计划以 `backend/` 与 `frontend/` 建立首期可运行边界；不得直接复用原始项目文档中的示例 `main.py`，以避免复制其中的公开密钥接口、宽松 CORS 与 XSS 风险。

| 路径 | 职责 |
|---|---|
| `backend/app/main.py` | FastAPI 应用工厂、路由注册、生命周期管理和安全中间件。 |
| `backend/app/config.py` | 环境变量读取、服务端密钥、固定 API 域名、超时、缓存与调用预算配置。 |
| `backend/app/models/travel.py` | 用户请求、Agent 结果、来源、最终文档及状态的 Pydantic 模型。 |
| `backend/app/services/cache.py` | 缓存接口、内存开发实现和未来 Redis 适配入口。 |
| `backend/app/services/heweather.py` | 和风天气 API 客户端、响应映射、缓存和故障分类。 |
| `backend/app/services/amap.py` | 高德地理编码、路线规划、POI 查询客户端、响应映射、缓存和故障分类。 |
| `backend/app/services/knowledge.py` | 已审核住宿与餐饮知识库的只读检索接口及开发样本实现。 |
| `backend/app/agents/weather.py` | 天气与气候预测 Agent。 |
| `backend/app/agents/route.py` | 旅游路线规划 Agent。 |
| `backend/app/agents/lodging.py` | 旅店测评 Agent。 |
| `backend/app/agents/food.py` | 美食品鉴 Agent。 |
| `backend/app/agents/summary.py` | 汇总校验与 Markdown 文档生成器。 |
| `backend/app/orchestration/sequential.py` | 固定顺序状态机、Agent 调用、降级编排与 trace 记录。 |
| `backend/app/api/travel.py` | `POST /api/travel-plans` 与健康/就绪接口。 |
| `backend/app/security.py` | 请求 ID、受信任来源 CORS、输入长度限制及安全响应头。 |
| `backend/requirements.txt` | 锁定运行依赖与开发测试依赖。 |
| `backend/.env.example` | 非敏感配置模板；不提供前端配置或密钥回显。 |
| `backend/tests/conftest.py` | pytest 异步配置、httpx mock、应用工厂和固定测试数据。 |
| `backend/tests/test_models.py` | 用户输入模型及默认天数规则测试。 |
| `backend/tests/test_heweather.py` | 和风客户端成功、超时、`429`/`5xx` 与缓存测试。 |
| `backend/tests/test_amap.py` | 高德客户端地理编码、路径、POI 与失败降级测试。 |
| `backend/tests/test_agents.py` | 四个专业 Agent 的结构化输出、禁止字段、来源和约束测试。 |
| `backend/tests/test_orchestrator.py` | 顺序、数据传递、天气风险、单 Agent 失败和 trace 测试。 |
| `backend/tests/test_api.py` | API 校验、响应合同、安全响应头与失败响应测试。 |
| `frontend/index.html` | 旅行需求表单、请求提交、状态显示、净化 Markdown 和来源渲染。 |
| `frontend/app.js` | 表单校验、API 调用、进度渲染及纯 DOM 安全渲染。 |
| `frontend/styles.css` | 响应式展示、风险提示、来源和降级说明样式。 |
| `frontend/vendor/marked.min.js` | 固定版本的本地 Markdown 渲染库。 |
| `frontend/vendor/purify.min.js` | 固定版本的本地 DOMPurify 净化库。 |
| `README.md` | 本地运行、环境变量、外部 API 开通、测试与安全边界说明。 |

## 任务 1：创建后端骨架与安全配置

**文件：**
- 创建：`backend/app/__init__.py`
- 创建：`backend/app/main.py`
- 创建：`backend/app/config.py`
- 创建：`backend/app/security.py`
- 创建：`backend/requirements.txt`
- 创建：`backend/.env.example`
- 创建：`backend/tests/conftest.py`
- 创建：`backend/tests/test_api.py`

- [ ] **步骤 1：编写应用工厂和安全响应头的失败测试**

```python
# backend/tests/test_api.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_health_returns_request_id_and_security_headers():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-frame-options"] == "DENY"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_api.py::test_health_returns_request_id_and_security_headers -v`  
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app'`。

- [ ] **步骤 3：编写最小应用工厂、配置和安全中间件**

```python
# backend/app/config.py
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    heweather_api_key: str = ""
    amap_api_key: str = ""
    heweather_base_url: str = "https://devapi.qweather.com"
    amap_base_url: str = "https://restapi.amap.com"
    external_connect_timeout_seconds: float = 3.0
    external_read_timeout_seconds: float = 8.0
    external_total_timeout_seconds: float = 10.0
    agent_timeout_seconds: float = 15.0
    summary_timeout_seconds: float = 20.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# backend/app/security.py
from uuid import uuid4
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        return response
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.security import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="智能文旅策划助手", version="5.0.0")
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-Id"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

```text
# backend/requirements.txt
fastapi==0.115.12
uvicorn[standard]==0.34.2
httpx==0.28.1
pydantic==2.11.3
pydantic-settings==2.8.1
pytest==8.3.5
pytest-asyncio==0.26.0
respx==0.22.0
```

```text
# backend/.env.example
APP_ENV=development
ALLOWED_ORIGINS=["http://localhost:5173"]
HEWEATHER_API_KEY=
AMAP_API_KEY=
HEWEATHER_BASE_URL=https://devapi.qweather.com
AMAP_BASE_URL=https://restapi.amap.com
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_api.py::test_health_returns_request_id_and_security_headers -v`  
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend
git commit -m "feat: add secure FastAPI application skeleton"
```

## 任务 2：定义旅行请求、来源和 Agent 结果合同

**文件：**
- 创建：`backend/app/models/__init__.py`
- 创建：`backend/app/models/travel.py`
- 创建：`backend/tests/test_models.py`

- [ ] **步骤 1：编写旅行请求默认值与边界的失败测试**

```python
# backend/tests/test_models.py
from datetime import date
import pytest
from pydantic import ValidationError

from app.models.travel import TravelPlanRequest


def test_travel_request_defaults_to_three_days_two_nights():
    request = TravelPlanRequest(
        origin="北京",
        destination="成都",
        departure_date=date(2026, 9, 1),
        travelers=2,
    )

    assert request.days == 3
    assert request.nights == 2


def test_travel_request_rejects_blank_destination_and_invalid_travelers():
    with pytest.raises(ValidationError):
        TravelPlanRequest(
            origin="北京",
            destination=" ",
            departure_date=date(2026, 9, 1),
            travelers=0,
        )
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_models.py -v`  
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.models'`。

- [ ] **步骤 3：实现所有 Agent 共用的 Pydantic 数据合同**

```python
# backend/app/models/travel.py
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


class AgentStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    FAILED = "failed"


class Source(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=50)
    updated_at: datetime | None = None
    url: str | None = None


class TravelPlanRequest(BaseModel):
    origin: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=100)
    departure_date: date
    travelers: int = Field(ge=1, le=20)
    days: int = Field(default=3, ge=1, le=14)
    budget: int | None = Field(default=None, ge=0, le=200000)
    preferences: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("origin", "destination")
    @classmethod
    def strip_location(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("地点不能为空")
        return value

    @model_validator(mode="after")
    def validate_date(self) -> "TravelPlanRequest":
        if self.departure_date < date.today():
            raise ValueError("出行日期不能早于今天")
        return self

    @property
    def nights(self) -> int:
        return max(self.days - 1, 0)


class AgentResult(BaseModel):
    agent: str
    status: AgentStatus
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False
    request_id: str
    trace_id: str


class TravelPlanDocument(BaseModel):
    request_id: str
    trace_id: str
    status: AgentStatus
    markdown: str
    sources: list[Source]
    warnings: list[str]
    degraded_agents: list[str]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_models.py -v`  
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/models backend/tests/test_models.py
git commit -m "feat: define travel agent data contracts"
```

## 任务 3：实现缓存接口与和风天气客户端

**文件：**
- 创建：`backend/app/services/__init__.py`
- 创建：`backend/app/services/cache.py`
- 创建：`backend/app/services/heweather.py`
- 创建：`backend/tests/test_heweather.py`

- [ ] **步骤 1：编写和风天气成功映射、缓存与超时降级的失败测试**

```python
# backend/tests/test_heweather.py
from datetime import date
import httpx
import pytest
import respx

from app.services.cache import MemoryCache
from app.services.heweather import HeWeatherClient, ExternalServiceUnavailable


@respx.mock
@pytest.mark.asyncio
async def test_weather_client_maps_daily_forecast_and_reuses_cache():
    route = respx.get("https://devapi.qweather.com/v7/weather/3d").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "200",
                "updateTime": "2026-08-18T10:00+08:00",
                "daily": [{"fxDate": "2026-09-01", "textDay": "小雨", "tempMin": "21", "tempMax": "28"}],
            },
        )
    )
    client = HeWeatherClient(api_key="weather-key", cache=MemoryCache())

    first = await client.daily_forecast("101270101", date(2026, 9, 1), 3)
    second = await client.daily_forecast("101270101", date(2026, 9, 1), 3)

    assert first["daily"][0]["condition"] == "小雨"
    assert second == first
    assert route.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_weather_client_converts_timeout_to_service_unavailable():
    respx.get("https://devapi.qweather.com/v7/weather/3d").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )
    client = HeWeatherClient(api_key="weather-key", cache=MemoryCache())

    with pytest.raises(ExternalServiceUnavailable):
        await client.daily_forecast("101270101", date(2026, 9, 1), 3)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_heweather.py -v`  
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.services'`。

- [ ] **步骤 3：实现内存缓存与受限和风天气客户端**

```python
# backend/app/services/cache.py
from datetime import datetime, timedelta, timezone
from typing import Any


class MemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[datetime, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= datetime.now(timezone.utc):
            self._items.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._items[key] = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            value,
        )
```

```python
# backend/app/services/heweather.py
from datetime import date
import httpx

from app.services.cache import MemoryCache


class ExternalServiceUnavailable(Exception):
    pass


class HeWeatherClient:
    def __init__(
        self,
        api_key: str,
        cache: MemoryCache,
        base_url: str = "https://devapi.qweather.com",
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.cache = cache
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def daily_forecast(self, location_id: str, start: date, days: int) -> dict:
        key = f"weather:{location_id}:{start.isoformat()}:{days}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/v7/weather/3d",
                    params={"location": location_id, "key": self.api_key},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as error:
            raise ExternalServiceUnavailable("和风天气服务暂不可用") from error
        if payload.get("code") != "200":
            raise ExternalServiceUnavailable("和风天气未返回有效预报")
        result = {
            "updated_at": payload.get("updateTime"),
            "daily": [
                {
                    "date": item["fxDate"],
                    "condition": item.get("textDay", "未知"),
                    "temp_min": item.get("tempMin"),
                    "temp_max": item.get("tempMax"),
                }
                for item in payload.get("daily", [])[:days]
            ],
        }
        self.cache.set(key, result, ttl_seconds=1800)
        return result
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_heweather.py -v`  
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services backend/tests/test_heweather.py
git commit -m "feat: add cached HeWeather client"
```

## 任务 4：实现高德地图客户端与只读知识库接口

**文件：**
- 创建：`backend/app/services/amap.py`
- 创建：`backend/app/services/knowledge.py`
- 创建：`backend/tests/test_amap.py`

- [ ] **步骤 1：编写高德地理编码、路径和 POI 映射的失败测试**

```python
# backend/tests/test_amap.py
import httpx
import pytest
import respx

from app.services.amap import AmapClient
from app.services.cache import MemoryCache


@respx.mock
@pytest.mark.asyncio
async def test_amap_client_returns_normalized_location_route_and_pois():
    respx.get("https://restapi.amap.com/v3/geocode/geo").mock(
        return_value=httpx.Response(200, json={"status": "1", "geocodes": [{"formatted_address": "四川省成都市", "location": "104.0665,30.5728", "adcode": "510100"}]})
    )
    respx.get("https://restapi.amap.com/v5/direction/driving").mock(
        return_value=httpx.Response(200, json={"status": "1", "route": {"paths": [{"distance": "1800", "duration": "600"}]}})
    )
    respx.get("https://restapi.amap.com/v5/place/text").mock(
        return_value=httpx.Response(200, json={"status": "1", "pois": [{"name": "示例酒店", "address": "示例路 1 号", "location": "104.08,30.57", "type": "住宿服务"}]})
    )
    client = AmapClient(api_key="amap-key", cache=MemoryCache())

    location = await client.geocode("成都")
    route = await client.driving_route("104.06,30.57", "104.08,30.57")
    pois = await client.search_poi("住宿服务", "成都")

    assert location["adcode"] == "510100"
    assert route["duration_minutes"] == 10
    assert pois[0]["name"] == "示例酒店"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_amap.py -v`  
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.services.amap'`。

- [ ] **步骤 3：实现高德受控客户端和开发知识库**

```python
# backend/app/services/amap.py
import httpx
from app.services.cache import MemoryCache
from app.services.heweather import ExternalServiceUnavailable


class AmapClient:
    def __init__(self, api_key: str, cache: MemoryCache, base_url: str = "https://restapi.amap.com", timeout: float = 10.0) -> None:
        self.api_key = api_key
        self.cache = cache
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _get(self, path: str, params: dict[str, str], cache_key: str, ttl_seconds: int) -> dict:
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}{path}", params={**params, "key": self.api_key})
                response.raise_for_status()
                payload = response.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as error:
            raise ExternalServiceUnavailable("高德地图服务暂不可用") from error
        if payload.get("status") != "1":
            raise ExternalServiceUnavailable("高德地图未返回有效数据")
        self.cache.set(cache_key, payload, ttl_seconds)
        return payload

    async def geocode(self, keyword: str) -> dict:
        payload = await self._get("/v3/geocode/geo", {"address": keyword}, f"geo:{keyword}", 604800)
        item = payload.get("geocodes", [{}])[0]
        if not item.get("location"):
            raise ExternalServiceUnavailable("未找到地点")
        return {"name": item.get("formatted_address", keyword), "location": item["location"], "adcode": item.get("adcode")}

    async def driving_route(self, origin: str, destination: str) -> dict:
        payload = await self._get("/v5/direction/driving", {"origin": origin, "destination": destination}, f"route:{origin}:{destination}", 900)
        path = payload.get("route", {}).get("paths", [{}])[0]
        return {"distance_meters": int(path.get("distance", 0)), "duration_minutes": round(int(path.get("duration", 0)) / 60)}

    async def search_poi(self, types: str, city: str) -> list[dict]:
        payload = await self._get("/v5/place/text", {"keywords": types, "city": city, "citylimit": "true"}, f"poi:{types}:{city}", 3600)
        return [{"name": item.get("name"), "address": item.get("address"), "location": item.get("location"), "type": item.get("type")} for item in payload.get("pois", [])[:10]]
```

```python
# backend/app/services/knowledge.py
class CuratedKnowledgeBase:
    def __init__(self, lodging: list[dict] | None = None, food: list[dict] | None = None) -> None:
        self._lodging = lodging or []
        self._food = food or []

    def lodging_for(self, destination: str) -> list[dict]:
        return [item for item in self._lodging if item.get("destination") == destination]

    def food_for(self, destination: str, area: str | None = None) -> list[dict]:
        return [item for item in self._food if item.get("destination") == destination and (area is None or item.get("area") == area)]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_amap.py -v`  
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/services/amap.py backend/app/services/knowledge.py backend/tests/test_amap.py
git commit -m "feat: add Amap and curated knowledge services"
```

## 任务 5：实现天气与路线专业 Agent

**文件：**
- 创建：`backend/app/agents/__init__.py`
- 创建：`backend/app/agents/weather.py`
- 创建：`backend/app/agents/route.py`
- 创建：`backend/tests/test_agents.py`

- [ ] **步骤 1：编写天气预警约束和路线消费约束的失败测试**

```python
# backend/tests/test_agents.py
from datetime import date
import pytest

from app.agents.weather import WeatherAgent
from app.agents.route import RouteAgent
from app.models.travel import TravelPlanRequest


class StubWeatherClient:
    async def daily_forecast(self, location_id, start, days):
        return {"updated_at": "2026-08-18T10:00:00+08:00", "daily": [{"date": "2026-09-01", "condition": "暴雨", "temp_min": "22", "temp_max": "26"}]}


class StubAmapClient:
    async def geocode(self, keyword):
        return {"name": keyword, "location": "104.06,30.57", "adcode": "510100"}

    async def driving_route(self, origin, destination):
        return {"distance_meters": 1800, "duration_minutes": 10}


@pytest.mark.asyncio
async def test_weather_agent_emits_outdoor_constraint_for_heavy_rain():
    request = TravelPlanRequest(origin="北京", destination="成都", departure_date=date(2026, 9, 1), travelers=2)
    result = await WeatherAgent(StubWeatherClient(), StubAmapClient()).run(request, "req-1", "trace-1")

    assert result.status == "success"
    assert "避免长时间户外活动" in result.constraints[0]


@pytest.mark.asyncio
async def test_route_agent_marks_route_as_weather_adjusted():
    request = TravelPlanRequest(origin="北京", destination="成都", departure_date=date(2026, 9, 1), travelers=2)
    result = await RouteAgent(StubAmapClient()).run(request, ["第 1 天避免长时间户外活动"], "req-1", "trace-1")

    assert result.data["weather_adjusted"] is True
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_agents.py -v`  
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.agents'`。

- [ ] **步骤 3：实现天气与路线 Agent 的最小结构化输出**

```python
# backend/app/agents/weather.py
from datetime import datetime
from app.models.travel import AgentResult, AgentStatus, Source, TravelPlanRequest
from app.services.heweather import ExternalServiceUnavailable


class WeatherAgent:
    def __init__(self, weather_client, amap_client) -> None:
        self.weather_client = weather_client
        self.amap_client = amap_client

    async def run(self, request: TravelPlanRequest, request_id: str, trace_id: str) -> AgentResult:
        try:
            destination = await self.amap_client.geocode(request.destination)
            forecast = await self.weather_client.daily_forecast(destination["adcode"], request.departure_date, request.days)
            constraints = []
            warnings = []
            for item in forecast["daily"]:
                if any(word in item["condition"] for word in ("暴雨", "大雨", "台风", "强对流")):
                    constraints.append(f"第 {len(constraints) + 1} 天避免长时间户外活动")
                    warnings.append(f"{item['date']} 预报为{item['condition']}，请关注官方预警")
            return AgentResult(agent="weather", status=AgentStatus.SUCCESS, summary="已获取目的地天气与活动建议。", data=forecast, constraints=constraints, sources=[Source(name="和风天气", type="weather_api", updated_at=datetime.fromisoformat(forecast["updated_at"]))], warnings=warnings, request_id=request_id, trace_id=trace_id)
        except ExternalServiceUnavailable:
            return AgentResult(agent="weather", status=AgentStatus.DEGRADED, summary="天气服务暂不可用。", warnings=["天气数据暂不可用，请出行前再次核验。"], degraded=True, request_id=request_id, trace_id=trace_id)
```

```python
# backend/app/agents/route.py
from datetime import datetime, timezone
from app.models.travel import AgentResult, AgentStatus, Source, TravelPlanRequest
from app.services.heweather import ExternalServiceUnavailable


class RouteAgent:
    def __init__(self, amap_client) -> None:
        self.amap_client = amap_client

    async def run(self, request: TravelPlanRequest, weather_constraints: list[str], request_id: str, trace_id: str) -> AgentResult:
        try:
            origin = await self.amap_client.geocode(request.origin)
            destination = await self.amap_client.geocode(request.destination)
            route = await self.amap_client.driving_route(origin["location"], destination["location"])
            areas = [{"day": day, "area": destination["name"], "activity_window": "09:00-18:00"} for day in range(1, request.days + 1)]
            return AgentResult(agent="route", status=AgentStatus.SUCCESS, summary="已生成往返与每日活动区域建议。", data={"origin": origin, "destination": destination, "round_trip": route, "daily_areas": areas, "weather_adjusted": bool(weather_constraints)}, constraints=weather_constraints, sources=[Source(name="高德地图", type="map_api", updated_at=datetime.now(timezone.utc))], warnings=[], request_id=request_id, trace_id=trace_id)
        except ExternalServiceUnavailable:
            return AgentResult(agent="route", status=AgentStatus.DEGRADED, summary="路线服务暂不可用，已改为区域化建议。", data={"daily_areas": [{"day": day, "area": request.destination} for day in range(1, request.days + 1)], "weather_adjusted": bool(weather_constraints)}, constraints=weather_constraints, warnings=["未获得精确路线与通行时间，请使用地图应用再次核验。"], degraded=True, request_id=request_id, trace_id=trace_id)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_agents.py -v`  
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/agents/weather.py backend/app/agents/route.py backend/tests/test_agents.py
git commit -m "feat: add weather and route agents"
```

## 任务 6：实现旅店与美食专业 Agent

**文件：**
- 创建：`backend/app/agents/lodging.py`
- 创建：`backend/app/agents/food.py`
- 修改：`backend/tests/test_agents.py`

- [ ] **步骤 1：编写住宿、餐饮禁止实时字段及 POI 降级的失败测试**

```python
# 追加到 backend/tests/test_agents.py
from app.agents.food import FoodAgent
from app.agents.lodging import LodgingAgent


class StubKnowledge:
    def lodging_for(self, destination):
        return [{"name": "知识库住宿", "destination": destination, "facilities": ["亲子"], "source": "审核知识库 v1"}]

    def food_for(self, destination, area=None):
        return [{"name": "知识库餐馆", "destination": destination, "area": area, "cuisine": "川菜", "source": "审核知识库 v1"}]


class StubPoiAmap(StubAmapClient):
    async def search_poi(self, types, city):
        return [{"name": "地图 POI", "address": "示例路 1 号", "location": "104.08,30.57", "type": types}]


@pytest.mark.asyncio
async def test_lodging_agent_omits_unauthorized_live_price_and_inventory():
    request = TravelPlanRequest(origin="北京", destination="成都", departure_date=date(2026, 9, 1), travelers=2)
    result = await LodgingAgent(StubPoiAmap(), StubKnowledge()).run(request, [{"day": 1, "area": "成都"}], "req-1", "trace-1")

    serialized = result.model_dump_json()
    assert "price" not in serialized
    assert "inventory" not in serialized
    assert result.sources


@pytest.mark.asyncio
async def test_food_agent_returns_area_based_recommendations_without_queue_claims():
    request = TravelPlanRequest(origin="北京", destination="成都", departure_date=date(2026, 9, 1), travelers=2)
    result = await FoodAgent(StubPoiAmap(), StubKnowledge()).run(request, [{"day": 1, "area": "成都"}], "req-1", "trace-1")

    serialized = result.model_dump_json()
    assert "queue" not in serialized
    assert result.data["daily_food"][0]["day"] == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_agents.py -v`  
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.agents.food'`。

- [ ] **步骤 3：实现住宿与餐饮 Agent**

```python
# backend/app/agents/lodging.py
from datetime import datetime, timezone
from app.models.travel import AgentResult, AgentStatus, Source, TravelPlanRequest
from app.services.heweather import ExternalServiceUnavailable


class LodgingAgent:
    def __init__(self, amap_client, knowledge_base) -> None:
        self.amap_client = amap_client
        self.knowledge_base = knowledge_base

    async def run(self, request: TravelPlanRequest, daily_areas: list[dict], request_id: str, trace_id: str) -> AgentResult:
        try:
            pois = await self.amap_client.search_poi("住宿服务", request.destination)
            candidates = pois[:3] + self.knowledge_base.lodging_for(request.destination)[:3]
            return AgentResult(agent="lodging", status=AgentStatus.SUCCESS, summary="已根据行程区域提供住宿位置建议。", data={"nights": request.nights, "candidates": candidates, "recommended_area": daily_areas[0]["area"] if daily_areas else request.destination}, sources=[Source(name="高德地图", type="poi_api", updated_at=datetime.now(timezone.utc)), Source(name="已审核住宿知识库", type="knowledge_base")], warnings=["未接入授权 OTA 数据，不包含实时房价、余房或可订状态。"], request_id=request_id, trace_id=trace_id)
        except ExternalServiceUnavailable:
            curated = self.knowledge_base.lodging_for(request.destination)
            return AgentResult(agent="lodging", status=AgentStatus.DEGRADED, summary="未获得实时 POI，已返回已审核住宿区域建议。", data={"nights": request.nights, "candidates": curated, "recommended_area": request.destination}, sources=[Source(name="已审核住宿知识库", type="knowledge_base")], warnings=["请通过官方或授权平台核验房价和可订状态。"], degraded=True, request_id=request_id, trace_id=trace_id)
```

```python
# backend/app/agents/food.py
from datetime import datetime, timezone
from app.models.travel import AgentResult, AgentStatus, Source, TravelPlanRequest
from app.services.heweather import ExternalServiceUnavailable


class FoodAgent:
    def __init__(self, amap_client, knowledge_base) -> None:
        self.amap_client = amap_client
        self.knowledge_base = knowledge_base

    async def run(self, request: TravelPlanRequest, daily_areas: list[dict], request_id: str, trace_id: str) -> AgentResult:
        daily_food = []
        try:
            pois = await self.amap_client.search_poi("餐饮服务", request.destination)
            for item in daily_areas:
                curated = self.knowledge_base.food_for(request.destination, item["area"])
                daily_food.append({"day": item["day"], "area": item["area"], "candidates": (curated + pois)[:5]})
            return AgentResult(agent="food", status=AgentStatus.SUCCESS, summary="已按每日活动区域提供餐饮建议。", data={"daily_food": daily_food}, sources=[Source(name="高德地图", type="poi_api", updated_at=datetime.now(timezone.utc)), Source(name="已审核餐饮知识库", type="knowledge_base")], warnings=["未接入授权餐饮平台数据，不包含排队时长、实时优惠或未经授权评分。"], request_id=request_id, trace_id=trace_id)
        except ExternalServiceUnavailable:
            for item in daily_areas:
                daily_food.append({"day": item["day"], "area": item["area"], "candidates": self.knowledge_base.food_for(request.destination, item["area"])})
            return AgentResult(agent="food", status=AgentStatus.DEGRADED, summary="未获得实时 POI，已返回已审核餐饮知识库建议。", data={"daily_food": daily_food}, sources=[Source(name="已审核餐饮知识库", type="knowledge_base")], warnings=["请以商家官方信息为准。"], degraded=True, request_id=request_id, trace_id=trace_id)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_agents.py -v`  
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/agents/lodging.py backend/app/agents/food.py backend/tests/test_agents.py
git commit -m "feat: add lodging and food agents"
```

## 任务 7：实现汇总校验 Agent，生成受来源约束的 Markdown

**文件：**
- 创建：`backend/app/agents/summary.py`
- 修改：`backend/tests/test_agents.py`

- [ ] **步骤 1：编写汇总器不新增实时字段、展示来源与降级说明的失败测试**

```python
# 追加到 backend/tests/test_agents.py
from app.agents.summary import SummaryAgent
from app.models.travel import AgentResult, AgentStatus, Source


def test_summary_includes_sources_warnings_and_never_invents_live_inventory():
    results = [
        AgentResult(agent="weather", status=AgentStatus.SUCCESS, summary="小雨", data={"daily": []}, sources=[Source(name="和风天气", type="weather_api")], request_id="req-1", trace_id="trace-1"),
        AgentResult(agent="lodging", status=AgentStatus.DEGRADED, summary="区域建议", warnings=["请核验可订状态。"], degraded=True, request_id="req-1", trace_id="trace-1"),
    ]
    document = SummaryAgent().run(results, "req-1", "trace-1")

    assert "## 来源与更新时间" in document.markdown
    assert "请核验可订状态。" in document.markdown
    assert "余房" not in document.markdown
    assert document.degraded_agents == ["lodging"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_agents.py::test_summary_includes_sources_warnings_and_never_invents_live_inventory -v`  
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.agents.summary'`。

- [ ] **步骤 3：实现基于结构化数据的汇总校验器**

```python
# backend/app/agents/summary.py
from app.models.travel import AgentResult, AgentStatus, Source, TravelPlanDocument


class SummaryAgent:
    def run(self, results: list[AgentResult], request_id: str, trace_id: str) -> TravelPlanDocument:
        warnings = [warning for result in results for warning in result.warnings]
        sources: list[Source] = []
        seen = set()
        for result in results:
            for source in result.sources:
                key = (source.name, source.type, source.updated_at)
                if key not in seen:
                    seen.add(key)
                    sources.append(source)
        degraded_agents = [result.agent for result in results if result.degraded]
        sections = ["# 文旅策划建议"]
        for result in results:
            sections.extend([f"## {result.agent} 建议", result.summary])
            if result.constraints:
                sections.append("- 约束：" + "；".join(result.constraints))
            if result.warnings:
                sections.append("- 提示：" + "；".join(result.warnings))
        sections.append("## 来源与更新时间")
        sections.extend([f"- {source.name}（{source.type}）" + (f"：{source.updated_at.isoformat()}" if source.updated_at else "") for source in sources])
        if degraded_agents:
            sections.extend(["## 降级说明", "以下模块未获得完整实时数据：" + "、".join(degraded_agents) + "。请以官方或授权平台信息为准。"])
        return TravelPlanDocument(request_id=request_id, trace_id=trace_id, status=AgentStatus.DEGRADED if degraded_agents else AgentStatus.SUCCESS, markdown="\n\n".join(sections), sources=sources, warnings=warnings, degraded_agents=degraded_agents)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_agents.py::test_summary_includes_sources_warnings_and_never_invents_live_inventory -v`  
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/agents/summary.py backend/tests/test_agents.py
git commit -m "feat: add constrained travel plan summary agent"
```

## 任务 8：实现顺序编排器与端到端降级测试

**文件：**
- 创建：`backend/app/orchestration/__init__.py`
- 创建：`backend/app/orchestration/sequential.py`
- 创建：`backend/tests/test_orchestrator.py`

- [ ] **步骤 1：编写顺序、天气约束传递及单 Agent 故障不终止请求的失败测试**

```python
# backend/tests/test_orchestrator.py
from datetime import date
import pytest

from app.models.travel import AgentResult, AgentStatus, TravelPlanRequest
from app.orchestration.sequential import SequentialTravelOrchestrator


class RecordingAgent:
    def __init__(self, name, calls, result):
        self.name, self.calls, self.result = name, calls, result

    async def run(self, *args):
        self.calls.append(self.name)
        return self.result


@pytest.mark.asyncio
async def test_orchestrator_runs_agents_in_fixed_order_and_returns_document():
    calls = []
    request = TravelPlanRequest(origin="北京", destination="成都", departure_date=date(2026, 9, 1), travelers=2)
    def result(name, **kwargs):
        return AgentResult(agent=name, status=AgentStatus.SUCCESS, summary=name, request_id="req-1", trace_id="trace-1", **kwargs)
    orchestrator = SequentialTravelOrchestrator(
        weather_agent=RecordingAgent("weather", calls, result("weather", constraints=["避免户外"])),
        route_agent=RecordingAgent("route", calls, result("route", data={"daily_areas": [{"day": 1, "area": "成都"}]})),
        lodging_agent=RecordingAgent("lodging", calls, result("lodging")),
        food_agent=RecordingAgent("food", calls, result("food")),
        summary_agent=__import__("app.agents.summary", fromlist=["SummaryAgent"]).SummaryAgent(),
    )

    document = await orchestrator.run(request, request_id="req-1", trace_id="trace-1")

    assert calls == ["weather", "route", "lodging", "food"]
    assert document.status == AgentStatus.SUCCESS
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_orchestrator.py -v`  
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.orchestration'`。

- [ ] **步骤 3：实现固定顺序编排器**

```python
# backend/app/orchestration/sequential.py
from app.models.travel import TravelPlanRequest, TravelPlanDocument


class SequentialTravelOrchestrator:
    def __init__(self, weather_agent, route_agent, lodging_agent, food_agent, summary_agent) -> None:
        self.weather_agent = weather_agent
        self.route_agent = route_agent
        self.lodging_agent = lodging_agent
        self.food_agent = food_agent
        self.summary_agent = summary_agent

    async def run(self, request: TravelPlanRequest, request_id: str, trace_id: str) -> TravelPlanDocument:
        weather = await self.weather_agent.run(request, request_id, trace_id)
        route = await self.route_agent.run(request, weather.constraints, request_id, trace_id)
        daily_areas = route.data.get("daily_areas", [{"day": day, "area": request.destination} for day in range(1, request.days + 1)])
        lodging = await self.lodging_agent.run(request, daily_areas, request_id, trace_id)
        food = await self.food_agent.run(request, daily_areas, request_id, trace_id)
        return self.summary_agent.run([weather, route, lodging, food], request_id, trace_id)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd backend && pytest tests/test_orchestrator.py -v`  
预期：PASS。

- [ ] **步骤 5：补充住宿 Agent 失败的端到端回归测试**

```python
# 追加到 backend/tests/test_orchestrator.py
@pytest.mark.asyncio
async def test_orchestrator_returns_degraded_document_when_lodging_is_degraded():
    calls = []
    request = TravelPlanRequest(origin="北京", destination="成都", departure_date=date(2026, 9, 1), travelers=2)
    def result(name, **kwargs):
        return AgentResult(agent=name, status=AgentStatus.SUCCESS, summary=name, request_id="req-2", trace_id="trace-2", **kwargs)
    orchestrator = SequentialTravelOrchestrator(
        RecordingAgent("weather", calls, result("weather")),
        RecordingAgent("route", calls, result("route", data={"daily_areas": [{"day": 1, "area": "成都"}]})),
        RecordingAgent("lodging", calls, AgentResult(agent="lodging", status=AgentStatus.DEGRADED, summary="住宿降级", degraded=True, warnings=["请核验可订状态。"], request_id="req-2", trace_id="trace-2")),
        RecordingAgent("food", calls, result("food")),
        __import__("app.agents.summary", fromlist=["SummaryAgent"]).SummaryAgent(),
    )

    document = await orchestrator.run(request, "req-2", "trace-2")

    assert document.status == AgentStatus.DEGRADED
    assert document.degraded_agents == ["lodging"]
```

- [ ] **步骤 6：运行端到端回归测试**

运行：`cd backend && pytest tests/test_orchestrator.py -v`  
预期：PASS。

- [ ] **步骤 7：Commit**

```bash
git add backend/app/orchestration backend/tests/test_orchestrator.py
git commit -m "feat: add sequential travel agent orchestrator"
```

## 任务 9：暴露旅行规划 API，并注入受控依赖

**文件：**
- 创建：`backend/app/api/__init__.py`
- 创建：`backend/app/api/travel.py`
- 修改：`backend/app/main.py`
- 修改：`backend/tests/test_api.py`

- [ ] **步骤 1：编写 API 的必填字段、默认天数和完整文档响应失败测试**

```python
# 追加到 backend/tests/test_api.py
from datetime import date
from app.models.travel import AgentStatus, TravelPlanDocument


class StubOrchestrator:
    async def run(self, request, request_id, trace_id):
        return TravelPlanDocument(
            request_id=request_id,
            trace_id=trace_id,
            status=AgentStatus.SUCCESS,
            markdown="# 文旅策划建议",
            sources=[],
            warnings=[],
            degraded_agents=[],
        )


@pytest.mark.asyncio
async def test_create_travel_plan_requires_four_core_fields_and_uses_default_days():
    app = create_app(orchestrator=StubOrchestrator())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        invalid = await client.post("/api/travel-plans", json={"origin": "北京"})
        valid = await client.post("/api/travel-plans", json={"origin": "北京", "destination": "成都", "departure_date": str(date.today()), "travelers": 2})

    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert valid.json()["markdown"] == "# 文旅策划建议"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_api.py::test_create_travel_plan_requires_four_core_fields_and_uses_default_days -v`  
预期：FAIL，报错 `TypeError: create_app() got an unexpected keyword argument 'orchestrator'`。

- [ ] **步骤 3：实现依赖注入和旅行规划路由**

```python
# backend/app/api/travel.py
from fastapi import APIRouter, Request
from app.models.travel import TravelPlanDocument, TravelPlanRequest

router = APIRouter(prefix="/api", tags=["travel"])


@router.post("/travel-plans", response_model=TravelPlanDocument)
async def create_travel_plan(payload: TravelPlanRequest, request: Request) -> TravelPlanDocument:
    orchestrator = request.app.state.orchestrator
    request_id = request.state.request_id
    return await orchestrator.run(payload, request_id=request_id, trace_id=request_id)
```

```python
# 在 backend/app/main.py 中替换 create_app 签名及路由注册
from app.api.travel import router as travel_router


def create_app(orchestrator=None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="智能文旅策划助手", version="5.0.0")
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-Id"],
    )
    if orchestrator is not None:
        app.state.orchestrator = orchestrator
    app.include_router(travel_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **步骤 4：运行 API 测试验证通过**

运行：`cd backend && pytest tests/test_api.py -v`  
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_api.py
git commit -m "feat: expose sequential travel plan API"
```

## 任务 10：完成生产依赖组装、健康检查与可执行入口

**文件：**
- 修改：`backend/app/main.py`
- 修改：`backend/app/config.py`
- 创建：`backend/app/dependencies.py`
- 修改：`backend/tests/test_api.py`

- [ ] **步骤 1：编写就绪检查在外部密钥缺失时返回不可就绪的失败测试**

```python
# 追加到 backend/tests/test_api.py
@pytest.mark.asyncio
async def test_readiness_returns_503_without_required_external_keys(monkeypatch):
    monkeypatch.setenv("HEWEATHER_API_KEY", "")
    monkeypatch.setenv("AMAP_API_KEY", "")
    from app.config import get_settings
    get_settings.cache_clear()
    app = create_app(orchestrator=StubOrchestrator())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get("/api/ready")

    assert response.status_code == 503
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd backend && pytest tests/test_api.py::test_readiness_returns_503_without_required_external_keys -v`  
预期：FAIL，报错 `404 Not Found`。

- [ ] **步骤 3：实现依赖组装和就绪检查**

```python
# backend/app/dependencies.py
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
from app.services.knowledge import CuratedKnowledgeBase


def build_orchestrator(settings: Settings) -> SequentialTravelOrchestrator:
    cache = MemoryCache()
    amap = AmapClient(settings.amap_api_key, cache, settings.amap_base_url, settings.external_total_timeout_seconds)
    weather = HeWeatherClient(settings.heweather_api_key, cache, settings.heweather_base_url, settings.external_total_timeout_seconds)
    knowledge = CuratedKnowledgeBase()
    return SequentialTravelOrchestrator(
        weather_agent=WeatherAgent(weather, amap),
        route_agent=RouteAgent(amap),
        lodging_agent=LodgingAgent(amap, knowledge),
        food_agent=FoodAgent(amap, knowledge),
        summary_agent=SummaryAgent(),
    )
```

```python
# 追加到 backend/app/main.py
from fastapi import HTTPException
from app.dependencies import build_orchestrator

# 在 create_app 中，替换原有 orchestrator 分支：
app.state.settings = settings
app.state.orchestrator = orchestrator or build_orchestrator(settings)

# 追加路由：
@app.get("/api/ready")
async def ready() -> dict[str, str]:
    if not settings.heweather_api_key or not settings.amap_api_key:
        raise HTTPException(status_code=503, detail="外部数据服务密钥未配置")
    return {"status": "ready"}
```

- [ ] **步骤 4：运行就绪检查测试验证通过**

运行：`cd backend && pytest tests/test_api.py::test_readiness_returns_503_without_required_external_keys -v`  
预期：PASS。

- [ ] **步骤 5：运行后端完整测试集**

运行：`cd backend && pytest -v`  
预期：全部 PASS。

- [ ] **步骤 6：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: wire production travel agent dependencies"
```

## 任务 11：实现安全前端表单和文档展示

**文件：**
- 创建：`frontend/index.html`
- 创建：`frontend/app.js`
- 创建：`frontend/styles.css`
- 创建：`frontend/vendor/marked.min.js`
- 创建：`frontend/vendor/purify.min.js`

- [ ] **步骤 1：创建前端安全渲染的浏览器测试页面**

创建 `frontend/manual-security-check.html`：

```html
<!doctype html>
<meta charset="utf-8">
<script src="./vendor/marked.min.js"></script>
<script src="./vendor/purify.min.js"></script>
<script>
  const malicious = '# 测试\n<img src=x onerror="window.xssTriggered=true">';
  const safe = DOMPurify.sanitize(marked.parse(malicious), {USE_PROFILES: {html: true}});
  document.body.innerHTML = safe;
  setTimeout(() => document.body.dataset.xss = String(Boolean(window.xssTriggered)), 0);
</script>
```

- [ ] **步骤 2：在浏览器打开验证安全渲染失败前提**

运行：使用浏览器打开 `frontend/manual-security-check.html`。  
预期：在供应商库尚未落盘时，浏览器控制台报脚本加载失败；记录该状态后继续下一步。

- [ ] **步骤 3：下载并固定前端依赖，编写页面结构**

将经过版本锁定和许可证审查的 `marked` 与 `DOMPurify` 文件下载到 `frontend/vendor/`。页面必须使用本地文件，不允许 CDN。

```html
<!-- frontend/index.html 的核心结构 -->
<form id="travel-form" novalidate>
  <label>出发地<input name="origin" required maxlength="100"></label>
  <label>目的地<input name="destination" required maxlength="100"></label>
  <label>出行日期<input name="departure_date" type="date" required></label>
  <label>人数<input name="travelers" type="number" required min="1" max="20"></label>
  <label>旅行天数（默认 3 天 2 晚）<input name="days" type="number" min="1" max="14"></label>
  <label>预算（可选）<input name="budget" type="number" min="0" max="200000"></label>
  <button type="submit">生成文旅策划</button>
</form>
<main id="result" aria-live="polite"></main>
<script src="./vendor/marked.min.js"></script>
<script src="./vendor/purify.min.js"></script>
<script src="./app.js"></script>
```

- [ ] **步骤 4：实现表单提交与纯 DOM 安全渲染**

```javascript
// frontend/app.js
const form = document.querySelector('#travel-form');
const result = document.querySelector('#result');

function renderDocument(plan) {
  result.replaceChildren();
  const content = document.createElement('article');
  content.className = 'plan-content';
  content.innerHTML = DOMPurify.sanitize(marked.parse(plan.markdown), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'script', 'svg', 'math'],
  });
  result.append(content);

  const meta = document.createElement('section');
  meta.className = 'plan-meta';
  const heading = document.createElement('h2');
  heading.textContent = '数据来源与提示';
  meta.append(heading);
  for (const source of plan.sources) {
    const item = document.createElement('p');
    item.textContent = `${source.name}（${source.type}）${source.updated_at ? `：${source.updated_at}` : ''}`;
    meta.append(item);
  }
  for (const warning of plan.warnings) {
    const item = document.createElement('p');
    item.className = 'warning';
    item.textContent = warning;
    meta.append(item);
  }
  result.append(meta);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(form));
  const payload = {
    origin: values.origin.trim(),
    destination: values.destination.trim(),
    departure_date: values.departure_date,
    travelers: Number(values.travelers),
    ...(values.days ? { days: Number(values.days) } : {}),
    ...(values.budget ? { budget: Number(values.budget) } : {}),
  };
  const response = await fetch('/api/travel-plans', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const plan = await response.json();
  if (!response.ok) throw new Error(plan.detail || '生成失败');
  renderDocument(plan);
});
```

- [ ] **步骤 5：重新运行浏览器安全检查**

运行：使用浏览器打开 `frontend/manual-security-check.html`。  
预期：`document.body.dataset.xss` 为 `false`，页面不执行恶意事件属性。

- [ ] **步骤 6：移除手工安全检查页面并提交前端**

```bash
git add frontend
git rm frontend/manual-security-check.html
git commit -m "feat: add safe travel plan frontend"
```

## 任务 12：编写运行文档、完成质量验证与发布前检查

**文件：**
- 创建：`README.md`
- 创建：`.gitignore`
- 修改：`backend/.env.example`

- [ ] **步骤 1：编写 `.gitignore`，防止密钥、索引与运行数据入库**

```gitignore
# Secrets and local configuration
.env
.env.*
!.env.example

# Python
__pycache__/
.pytest_cache/
.venv/
*.py[cod]

# Runtime data and logs
data/
logs/
*.log

# Local models and indexes
models/
index/
knowledge/documents/

# Frontend build artifacts
frontend/dist/
```

- [ ] **步骤 2：编写 README 的运行和安全边界说明**

`README.md` 必须包含以下可执行内容：

```markdown
## 本地运行

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell 使用 .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env    # Linux/macOS 使用 cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

在 `.env` 中填写 `HEWEATHER_API_KEY` 和 `AMAP_API_KEY`。不要把 `.env`、密钥、知识库原始文件或运行数据提交到版本控制。

## 测试

```bash
cd backend
pytest -v
```

## 数据边界

首期仅使用和风天气、高德地图 POI 与已审核知识库。系统不会输出或承诺未经授权的实时房价、余房、可订状态、排队时长、实时优惠或第三方平台评分。
```
```

- [ ] **步骤 3：运行完整后端测试**

运行：`cd backend && pytest -v`  
预期：全部 PASS。

- [ ] **步骤 4：执行密钥泄露扫描**

运行：`git grep -nE "(sk-[A-Za-z0-9_-]{10,}|HEWEATHER_API_KEY=.+|AMAP_API_KEY=.+)" -- ':!.env.example'`  
预期：退出码为 `1`，没有匹配项。

- [ ] **步骤 5：执行依赖漏洞扫描**

运行：`cd backend && pip-audit -r requirements.txt`  
预期：未报告高危漏洞；若发现漏洞，升级受影响的锁定版本后重新执行本步骤与完整测试。

- [ ] **步骤 6：Commit**

```bash
git add README.md .gitignore backend/.env.example
git commit -m "docs: add travel agent setup and security guidance"
```

---

## 计划自检

- **规格覆盖度：** 任务 1、10 与 12 覆盖安全、密钥、健康检查与运行基线；任务 2 覆盖统一数据合同和输入默认值；任务 3—4 覆盖和风天气、高德地图、缓存和只读知识库；任务 5—7 覆盖 4 个专业 Agent 与受来源约束的汇总器；任务 8—9 覆盖顺序编排、降级和 API；任务 11 覆盖安全前端渲染；任务 12 覆盖测试、依赖扫描和密钥防泄露。
- **占位符扫描：** 已检查计划内容，未使用「TODO」「待定」「后续实现」「补充细节」「添加适当的错误处理」或「处理边界情况」等占位表达。
- **类型一致性：** 所有 Agent 使用 `TravelPlanRequest`、`AgentResult`、`TravelPlanDocument`、`AgentStatus`；编排器与 API 使用统一的 `request_id` 和 `trace_id`；外部服务故障统一映射为 `ExternalServiceUnavailable`。
