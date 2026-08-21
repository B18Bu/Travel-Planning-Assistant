from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.api.travel import router as travel_router
from app.config import Settings, get_settings
from app.dependencies import build_orchestrator
from app.security import SecurityHeadersMiddleware


def _frontend_dir() -> Path:
    """返回前端静态资源目录。"""

    return Path(__file__).resolve().parents[2] / "frontend"


def create_app(orchestrator=None, settings: Settings | None = None) -> FastAPI:
    """创建 v1 后端应用。"""

    settings = settings if settings is not None else get_settings()
    app = FastAPI(title="智能文旅策划助手", version="1.0.0")
    app.state.settings = settings
    app.state.orchestrator = (
        orchestrator if orchestrator is not None else build_orchestrator(settings)
    )
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

    @app.get("/api/ready")
    async def ready() -> dict[str, str]:
        if not settings.heweather_api_key or not settings.amap_api_key:
            raise HTTPException(status_code=503, detail="外部数据服务尚未配置")
        return {"status": "ready"}

    app.include_router(travel_router)
    frontend_dir = _frontend_dir()
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


app = create_app()
