import json
import logging
import sqlite3
import threading
import uuid
import importlib
import importlib.util
from pathlib import Path
from typing import List, Optional

from app.rag.embedding import encode_query, encode_texts, get_embedding_dim, get_model_cache_dir, get_model_name
from app.rag.models import DocumentChunk, SearchResult
from app.rag.splitter import split_document
from app.runtime_paths import runtime_file

logger = logging.getLogger(__name__)

DB_PATH = runtime_file("data", "knowledge.db")


def _sqlite_vec_available() -> bool:
    return importlib.util.find_spec("sqlite_vec") is not None


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    try:
        sqlite_vec = importlib.import_module("sqlite_vec")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception as exc:
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass
        raise RuntimeError(
            "sqlite-vec is not available. Install backend requirements or rebuild the packaged backend "
            "with `--collect-all sqlite_vec`."
        ) from exc


def get_rag_status() -> dict:
    """Return knowledge-base health without forcing vec/model initialization."""
    sqlite_ok = _sqlite_vec_available()
    total_chunks = 0
    source_count = 0
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    db_error = ""
    if DB_PATH.exists():
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='doc_chunks' LIMIT 1"
            ).fetchone()
            if table:
                total = conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()
                sources = conn.execute("SELECT COUNT(DISTINCT source_path) FROM doc_chunks").fetchone()
                total_chunks = int(total[0]) if total else 0
                source_count = int(sources[0]) if sources else 0
        except sqlite3.Error as exc:
            db_error = str(exc)
        finally:
            if conn is not None:
                conn.close()

    error = ""
    if not sqlite_ok:
        error = "sqlite-vec is not installed or was not bundled into the packaged backend."
    elif db_error:
        error = db_error

    return {
        "status": "ok" if not error else "unavailable",
        "sqlite_vec_available": sqlite_ok,
        "total_chunks": total_chunks,
        "source_count": source_count,
        "db_size_mb": round(db_size / 1024 / 1024, 2),
        "embedding_model": get_model_name(),
        "embedding_dim": get_embedding_dim(),
        "model_cache_dir": get_model_cache_dir(),
        "error": error,
    }


def has_indexed_docs() -> bool:
    """Return whether the knowledge DB has indexed docs without loading vec0."""
    if not DB_PATH.exists():
        return False
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='doc_chunks' LIMIT 1"
        ).fetchone()
        if not table:
            return False
        row = conn.execute("SELECT 1 FROM doc_chunks LIMIT 1").fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def _get_chunk_config():
    from app.config import load_config
    cfg = load_config()
    return cfg.rag.chunk_size, cfg.rag.chunk_overlap


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _load_sqlite_vec(conn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    conn = _get_connection()
    dim = get_embedding_dim()
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            chunk_id TEXT PRIMARY KEY,
            embedding FLOAT[{dim}] DISTANCE_METRIC=cosine
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_chunks (
            chunk_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            created_at INTEGER DEFAULT (unixepoch())
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_source ON doc_chunks(source_path)
    """)
    conn.commit()
    conn.close()


class RAGEngine:
    """RAG 引擎：管理文档索引、向量检索和元数据。"""

    def __init__(self):
        self._write_lock = threading.Lock()
        self._availability_error = ""
        try:
            _init_db()
        except RuntimeError as exc:
            self._availability_error = str(exc)

    def _ensure_available(self) -> None:
        if self._availability_error:
            raise RuntimeError(self._availability_error)

    def index_file(self, file_path: str, recursive: bool = False) -> dict:
        """索引单个文件或文件夹。重复索引同一路径会先删除旧 chunks 再重写。"""
        if self._availability_error:
            return {"error": self._availability_error}
        path = Path(file_path).resolve()
        if not path.exists():
            return {"error": f"路径不存在: {file_path}"}

        files_to_index = []
        if path.is_file():
            files_to_index.append(path)
        elif path.is_dir():
            if recursive:
                files_to_index = list(path.rglob("*"))
            else:
                files_to_index = list(path.iterdir())
            files_to_index = [f for f in files_to_index if f.is_file()]

        indexed = 0
        skipped = 0
        skip_reasons: list[str] = []
        all_chunks = []
        readable_paths: list[str] = []

        for fp in files_to_index:
            text, reason = self._read_file_text(fp)
            if text is None:
                skipped += 1
                if reason:
                    skip_reasons.append(f"{fp}: {reason}")
                continue
            source_path = str(fp)
            readable_paths.append(source_path)
            chunk_size, chunk_overlap = _get_chunk_config()
            chunks = split_document(text, source_path, chunk_size, chunk_overlap)
            for c in chunks:
                all_chunks.append(c)
            indexed += 1

        result: dict = {"indexed": indexed, "skipped": skipped, "chunks": len(all_chunks)}
        if skip_reasons:
            result["skip_reasons"] = skip_reasons[:20]
            for reason in skip_reasons[:10]:
                logger.info("RAG index skip: %s", reason)
        if not all_chunks:
            return result
            return {"indexed": indexed, "skipped": skipped, "chunks": 0}

        # 批量生成 embedding
        texts = [c["content"] for c in all_chunks]
        embeddings = encode_texts(texts)

        with self._write_lock:
            conn = _get_connection()
            try:
                if readable_paths:
                    placeholders = ",".join("?" * len(readable_paths))
                    stale = conn.execute(
                        f"SELECT chunk_id FROM doc_chunks WHERE source_path IN ({placeholders})",
                        readable_paths,
                    ).fetchall()
                    stale_ids = [r["chunk_id"] for r in stale]
                    if stale_ids:
                        id_placeholders = ",".join("?" * len(stale_ids))
                        conn.execute(
                            f"DELETE FROM doc_chunks WHERE chunk_id IN ({id_placeholders})",
                            stale_ids,
                        )
                        conn.execute(
                            f"DELETE FROM vec_chunks WHERE chunk_id IN ({id_placeholders})",
                            stale_ids,
                        )

                for i, chunk in enumerate(all_chunks):
                    chunk_id = str(uuid.uuid4())
                    embedding = embeddings[i]
                    metadata = json.dumps({"index": chunk["index"]})
                    conn.execute(
                        "INSERT INTO doc_chunks (chunk_id, source_path, content, metadata) VALUES (?, ?, ?, ?)",
                        (chunk_id, chunk["source_path"], chunk["content"], metadata),
                    )
                    conn.execute(
                        "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                        (chunk_id, json.dumps(embedding)),
                    )
                conn.commit()
            finally:
                conn.close()

        return {"indexed": indexed, "skipped": skipped, "chunks": len(all_chunks)}

    def search(self, query: str, top_k: int = 5, source_filter: Optional[str] = None) -> List[SearchResult]:
        """语义检索知识库。"""
        self._ensure_available()
        query_embedding = encode_query(query)
        conn = _get_connection()
        try:
            # sqlite-vec KNN 查询
            vec_sql = """
                SELECT chunk_id, distance
                FROM vec_chunks
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            """
            rows = conn.execute(vec_sql, (json.dumps(query_embedding), top_k * 3)).fetchall()
            if not rows:
                return []

            chunk_ids = [r["chunk_id"] for r in rows]
            distance_map = {r["chunk_id"]: r["distance"] for r in rows}

            # 批量查询元数据
            placeholders = ",".join("?" * len(chunk_ids))
            meta_sql = f"SELECT chunk_id, source_path, content FROM doc_chunks WHERE chunk_id IN ({placeholders})"
            meta_rows = conn.execute(meta_sql, chunk_ids).fetchall()

            results = []
            for row in meta_rows:
                source = row["source_path"]
                if source_filter and not source.startswith(source_filter):
                    continue
                results.append(SearchResult(
                    chunk_id=row["chunk_id"],
                    source_path=source,
                    content=row["content"],
                    score=round(1.0 - distance_map.get(row["chunk_id"], 1.0), 4),
                ))
            # 按 score 降序
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]
        finally:
            conn.close()

    def list_docs(self) -> List[dict]:
        """列出所有已索引的源文件及其 chunk 数量。"""
        self._ensure_available()
        conn = _get_connection()
        try:
            rows = conn.execute("""
                SELECT source_path, COUNT(*) as chunk_count, MAX(created_at) as last_indexed
                FROM doc_chunks
                GROUP BY source_path
                ORDER BY last_indexed DESC
            """).fetchall()
            return [
                {
                    "source_path": r["source_path"],
                    "chunk_count": r["chunk_count"],
                    "last_indexed": r["last_indexed"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def delete_doc(self, source_path: str) -> dict:
        """删除指定路径的所有 chunks。"""
        self._ensure_available()
        with self._write_lock:
            conn = _get_connection()
            try:
                rows = conn.execute(
                    "SELECT chunk_id FROM doc_chunks WHERE source_path = ?", (source_path,)
                ).fetchall()
                chunk_ids = [r["chunk_id"] for r in rows]
                if not chunk_ids:
                    return {"deleted": 0}
                placeholders = ",".join("?" * len(chunk_ids))
                conn.execute(f"DELETE FROM doc_chunks WHERE chunk_id IN ({placeholders})", chunk_ids)
                conn.execute(f"DELETE FROM vec_chunks WHERE chunk_id IN ({placeholders})", chunk_ids)
                conn.commit()
                return {"deleted": len(chunk_ids)}
            finally:
                conn.close()

    def clear_all(self) -> dict:
        """清空整个知识库。"""
        self._ensure_available()
        with self._write_lock:
            conn = _get_connection()
            try:
                conn.execute("DELETE FROM doc_chunks")
                conn.execute("DELETE FROM vec_chunks")
                conn.commit()
                return {"cleared": True}
            finally:
                conn.close()

    def get_stats(self) -> dict:
        """返回知识库统计信息。"""
        if self._availability_error:
            status = get_rag_status()
            status["error"] = self._availability_error
            status["status"] = "unavailable"
            return status
        conn = _get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM doc_chunks").fetchone()
            sources = conn.execute("SELECT COUNT(DISTINCT source_path) as cnt FROM doc_chunks").fetchone()
            db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
            return {
                "status": "ok",
                "sqlite_vec_available": True,
                "total_chunks": total["cnt"] if total else 0,
                "source_count": sources["cnt"] if sources else 0,
                "db_size_mb": round(db_size / 1024 / 1024, 2),
                "embedding_model": get_model_name(),
                "embedding_dim": get_embedding_dim(),
                "model_cache_dir": get_model_cache_dir(),
                "error": "",
            }
        finally:
            conn.close()

    @staticmethod
    def _read_file_text(path: Path) -> tuple:
        """尝试读取文件为纯文本。返回 (text, skip_reason)。"""
        text_exts = {
            ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx", ".jsx",
            ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
            ".csv", ".log", ".sql", ".sh", ".ps1", ".bat", ".html", ".htm",
            ".css", ".scss", ".less", ".xml", ".rst", ".rb", ".go", ".rs",
            ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt",
            ".php", ".lua", ".r", ".m", ".scala", ".dart", ".vim", ".el",
        }
        if path.suffix.lower() not in text_exts:
            return None, f"unsupported extension: {path.suffix}"
        try:
            size = path.stat().st_size
            if size > 10 * 1024 * 1024:
                return None, f"file too large ({size / 1024 / 1024:.1f}MB)"
            return path.read_text(encoding="utf-8", errors="ignore"), ""
        except UnicodeDecodeError:
            return None, "encoding error (not valid UTF-8)"
        except PermissionError:
            return None, "permission denied"
        except OSError as e:
            return None, f"read error: {e}"


# 全局单例
_rag_engine: Optional[RAGEngine] = None


def get_rag_engine() -> RAGEngine:
    global _rag_engine
    if _rag_engine is None:
        _rag_engine = RAGEngine()
    return _rag_engine
