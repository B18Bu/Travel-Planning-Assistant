from __future__ import annotations

from pathlib import Path
import mimetypes

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as documents_router
from app.api.fliggy import router as fliggy_router
from app.api.travel import router as travel_router
from app.config import Settings, get_settings
from app.dependencies import build_orchestrator
from app.security import SecurityHeadersMiddleware
from app.services.chroma_store import ChromaStore
from app.services.deepseek import DeepSeekClient
from app.services.document_processor import DocumentProcessor
from app.services.document_store import DocumentStore
from app.services.fliggy import (
    DisabledFliggyTicketService,
    FlyAIFliggyTicketService,
    MockFliggyTicketService,
)
from app.services.fliggy_flyai_client import FlyAIClient
from app.services.embeddings import LocalBgeEmbedder
from app.services.knowledge_polish import KnowledgePolisher
from app.services.mineru import MinerUClient
from app.services.qwen_vl import QwenVLClient
from app.services.query_record_store import QueryRecordStore


def _frontend_dir() -> Path:
    """返回前端静态资源目录。"""

    return Path(__file__).resolve().parents[2] / "frontend"


def _image_dir() -> Path:
    """返回旅行轮播图片目录。"""

    return Path(__file__).resolve().parents[2] / "image"


def _build_ticket_service(settings: Settings):
    """按 FLIGGY_TICKET_PROVIDER 构造门票服务；flyai 缺 Key 时保持关闭。"""

    provider = settings.fliggy_ticket_provider
    if provider == "mock":
        return MockFliggyTicketService()
    if provider == "flyai" and settings.flyai_api_key.strip():
        return FlyAIFliggyTicketService(
            FlyAIClient(
                api_key=settings.flyai_api_key,
                timeout_seconds=settings.flyai_timeout_seconds,
            )
        )
    return DisabledFliggyTicketService()


def create_app(
    orchestrator=None,
    settings: Settings | None = None,
    document_store=None,
    document_processor=None,
    chroma_store=None,
    fliggy_ticket_service=None,
) -> FastAPI:
    """创建 v1 后端应用。"""

    settings = settings if settings is not None else get_settings()
    app = FastAPI(title="智能文旅策划助手", version="1.0.0")
    app.state.settings = settings
    app.state.orchestrator = (
        orchestrator if orchestrator is not None else build_orchestrator(settings)
    )
    app.state.document_store = document_store if document_store is not None else DocumentStore(settings.document_data_dir)
    app.state.chroma_store = chroma_store
    if app.state.chroma_store is None:
        try:
            app.state.chroma_store = ChromaStore(
                app.state.document_store.chroma_dir,
                settings.chroma_collection_name,
                LocalBgeEmbedder(settings.bge_model_path),
            )
        except RuntimeError:
            app.state.chroma_store = None
    app.state.document_processor = document_processor
    if app.state.document_processor is None and app.state.chroma_store is not None:
        app.state.document_processor = DocumentProcessor(
            app.state.document_store,
            MinerUClient(settings.mineru_api_key),
            QwenVLClient(settings.qwen_vl_api_key, model=settings.qwen_vl_model),
            app.state.chroma_store,
        )
    app.state.query_record_store = QueryRecordStore(app.state.document_store.data_dir)
    app.state.fliggy_ticket_service = fliggy_ticket_service or _build_ticket_service(settings)
    app.state.knowledge_polisher = KnowledgePolisher(
        DeepSeekClient(
            settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            max_tokens=settings.deepseek_max_tokens,
            timeout=settings.deepseek_timeout_seconds,
        )
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
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
    app.include_router(documents_router)
    app.include_router(fliggy_router)
    image_dir = _image_dir()
    if image_dir.is_dir():
        mimetypes.add_type("image/webp", ".webp")
        app.mount("/image", StaticFiles(directory=image_dir), name="images")
    frontend_dir = _frontend_dir()
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


app = create_app()
