from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.security import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    """创建 v1 后端应用。"""

    settings = get_settings()
    app = FastAPI(title="智能文旅策划助手", version="1.0.0")
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

    return app


app = create_app()
