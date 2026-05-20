from pathlib import Path
from typing import List

from app.runtime_paths import runtime_dir

# 延迟加载 sentence-transformers，避免启动时耗时
_model = None
_model_name: str | None = None
_embedding_dim: int | None = None


def _get_model_dir() -> Path:
    base = runtime_dir("models") / "embeddings"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_model_cache_dir() -> str:
    return str(_get_model_dir())


def _resolve_model_config():
    global _model_name, _embedding_dim
    if _model_name is not None:
        return
    from app.config import load_config
    cfg = load_config()
    _model_name = cfg.rag.embedding_model
    # 常见模型的已知维度，未知模型在首次加载后自动检测
    _known_dims = {
        "all-MiniLM-L6-v2": 384,
        "all-mpnet-base-v2": 768,
        "intfloat/multilingual-e5-large": 1024,
        "BAAI/bge-large-zh-v1.5": 1024,
        "BAAI/bge-small-zh-v1.5": 512,
        "intfloat/e5-large-v2": 1024,
    }
    _embedding_dim = _known_dims.get(_model_name, 384)


def get_model_name() -> str:
    _resolve_model_config()
    return _model_name  # type: ignore[return-value]


def get_embedding_dim() -> int:
    _resolve_model_config()
    return _embedding_dim  # type: ignore[return-value]


def get_embedding_model():
    global _model, _embedding_dim
    _resolve_model_config()
    if _model is None:
        from sentence_transformers import SentenceTransformer
        cache_dir = str(_get_model_dir())
        _model = SentenceTransformer(_model_name, cache_folder=cache_dir)
        # Auto-detect embedding dim if not in known_dims
        if _embedding_dim is None or _embedding_dim == 384:
            detected = _model.get_sentence_embedding_dimension()
            if detected:
                _embedding_dim = detected
    return _model


def encode_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    model = get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [e.tolist() for e in embeddings]


def encode_query(text: str) -> List[float]:
    model = get_embedding_model()
    embedding = model.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return embedding.tolist()
