from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.resilience import ExternalServiceUnavailable


class LocalBgeEmbedder:
    """按需加载本地 BGE 模型，并仅在本地生成归一化向量。"""

    def __init__(self, model_path: str | Path) -> None:
        self._model_path = Path(model_path)
        self._model: Any | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        try:
            embeddings = model.encode(texts, normalize_embeddings=True)
            return [list(map(float, embedding)) for embedding in embeddings]
        except Exception:
            raise ExternalServiceUnavailable("本地 BGE 模型暂不可用") from None

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not self._model_path.is_dir():
            raise ExternalServiceUnavailable("本地 BGE 模型未配置")
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(str(self._model_path), local_files_only=True)
        except Exception:
            raise ExternalServiceUnavailable("本地 BGE 模型暂不可用") from None
        return self._model
