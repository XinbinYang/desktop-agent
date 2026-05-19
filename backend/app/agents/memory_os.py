"""Local Personal Agent Memory OS.

This module turns the existing markdown memory files into an indexed,
auditable local store. It deliberately lives under the runtime user-data
directory through ``runtime_file`` and never writes database state to the repo.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from app.agents.manager import AgentManager
from app.rag.embedding import encode_query, encode_texts, get_embedding_dim, get_model_name
from app.runtime_paths import runtime_file

logger = logging.getLogger(__name__)

DB_PATH = runtime_file("data", "personal_memory_os.db")

MEMORY_TYPES = frozenset({"working", "episodic", "semantic", "procedural", "identity"})
TIERS = frozenset({"hot", "warm", "cold", "archived"})
TIER_BOOST = {"hot": 0.08, "warm": 0.04, "cold": 0.0, "archived": -0.05}


@dataclass
class MemoryItem:
    id: str
    memory_type: str
    content: str
    summary: str
    source: str
    source_ref: str
    scope: str
    tier: str
    confidence: float
    created_by: str
    created_at: float
    updated_at: float
    last_verified_at: float
    metadata: dict[str, Any]
    score: float = 0.0
    deleted_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "content": self.content,
            "summary": self.summary,
            "source": self.source,
            "source_ref": self.source_ref,
            "scope": self.scope,
            "tier": self.tier,
            "confidence": self.confidence,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_verified_at": self.last_verified_at,
            "metadata": self.metadata,
            "score": round(self.score, 4),
            "deleted_at": self.deleted_at,
        }


def _sqlite_vec_available() -> bool:
    return importlib.util.find_spec("sqlite_vec") is not None


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    sqlite_vec = importlib.import_module("sqlite_vec")
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def _now() -> float:
    return time.time()


def _content_hash(text: str) -> str:
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()[:16]


def _make_id(source_ref: str, content: str) -> str:
    key = f"{source_ref}\n{_content_hash(content)}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def _summary_for(content: str, max_len: int = 220) -> str:
    compact = re.sub(r"\s+", " ", content.strip())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1].rstrip() + "..."


def _safe_json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _sanitize_match_query(query: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query, flags=re.UNICODE)
    tokens = [t for t in tokens if t.strip()]
    return " OR ".join(f'"{t}"' for t in tokens[:12])


def _tier_from_text(text: str, default: str = "warm") -> str:
    upper = text.upper()
    if "[HOT]" in upper:
        return "hot"
    if "[WARM]" in upper:
        return "warm"
    if "[COLD]" in upper:
        return "cold"
    return default


def _type_or_default(value: str, default: str = "episodic") -> str:
    return value if value in MEMORY_TYPES else default


def _tier_or_default(value: str, default: str = "warm") -> str:
    return value if value in TIERS else default


class MemoryOS:
    """SQLite-backed local memory store with keyword and optional vector search."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        self._write_lock = threading.Lock()
        self._vector_error = ""
        self._init_db()

    def _connect(self, load_vec: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        if load_vec:
            try:
                _load_sqlite_vec(conn)
            except Exception as exc:
                self._vector_error = str(exc)
                raise
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'personal',
                    tier TEXT NOT NULL DEFAULT 'warm',
                    confidence REAL NOT NULL DEFAULT 0.7,
                    created_by TEXT NOT NULL DEFAULT 'indexer',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_verified_at REAL NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    content_hash TEXT NOT NULL,
                    deleted_at REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_type ON memory_items(memory_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_tier ON memory_items(tier)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_source ON memory_items(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_hash ON memory_items(content_hash)")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(
                    item_id UNINDEXED,
                    content,
                    summary,
                    source_ref
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    before_json TEXT NOT NULL DEFAULT '{}',
                    after_json TEXT NOT NULL DEFAULT '{}',
                    actor TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT NOT NULL DEFAULT '',
                    promoted_item_id TEXT,
                    created_at REAL NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()
        self._init_vector_table()

    def _init_vector_table(self) -> None:
        if not _sqlite_vec_available():
            self._vector_error = "sqlite-vec is not available"
            return
        try:
            conn = self._connect(load_vec=True)
            try:
                dim = get_embedding_dim()
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_memory_items USING vec0(
                        item_id TEXT PRIMARY KEY,
                        embedding FLOAT[{dim}] DISTANCE_METRIC=cosine
                    )
                """)
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            self._vector_error = str(exc)

    def status(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM memory_items WHERE deleted_at IS NULL"
            ).fetchone()["c"]
            by_type = {
                r["memory_type"]: r["c"]
                for r in conn.execute(
                    "SELECT memory_type, COUNT(*) AS c FROM memory_items WHERE deleted_at IS NULL GROUP BY memory_type"
                )
            }
            by_tier = {
                r["tier"]: r["c"]
                for r in conn.execute(
                    "SELECT tier, COUNT(*) AS c FROM memory_items WHERE deleted_at IS NULL GROUP BY tier"
                )
            }
            pending = conn.execute(
                "SELECT COUNT(*) AS c FROM memory_candidates WHERE status = 'pending'"
            ).fetchone()["c"]
        finally:
            conn.close()
        return {
            "status": "ok",
            "db_path": str(self.db_path),
            "db_size_mb": round((self.db_path.stat().st_size if self.db_path.exists() else 0) / 1024 / 1024, 2),
            "total_items": int(total),
            "counts_by_type": by_type,
            "counts_by_tier": by_tier,
            "pending_candidates": int(pending),
            "vector_available": _sqlite_vec_available() and not self._vector_error,
            "vector_error": self._vector_error,
            "embedding_model": get_model_name(),
        }

    def list_items(
        self,
        memory_type: str = "",
        tier: str = "",
        source: str = "",
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where, params = self._filters(memory_type, tier, source, include_deleted)
        limit = max(1, min(limit, 500))
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM memory_items {where} ORDER BY updated_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [self._row_to_item(r).to_dict() for r in rows]
        finally:
            conn.close()

    def search(
        self,
        query: str = "",
        memory_type: str = "",
        tier: str = "",
        source: str = "",
        include_deleted: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        limit = max(1, min(limit, 100))
        scores: dict[str, float] = {}

        if query:
            for item_id, score in self._keyword_scores(query, limit * 4):
                scores[item_id] = max(scores.get(item_id, 0.0), score)
            for item_id, score in self._vector_scores(query, limit * 4):
                scores[item_id] = max(scores.get(item_id, 0.0), score)

        where, params = self._filters(memory_type, tier, source, include_deleted)
        conn = self._connect()
        try:
            if query and scores:
                placeholders = ",".join("?" * len(scores))
                prefix = "WHERE" if not where else f"{where} AND"
                rows = conn.execute(
                    f"SELECT * FROM memory_items {prefix} id IN ({placeholders})",
                    [*params, *scores.keys()],
                ).fetchall()
            elif query:
                like = f"%{query}%"
                prefix = "WHERE" if not where else f"{where} AND"
                rows = conn.execute(
                    f"SELECT * FROM memory_items {prefix} (content LIKE ? OR summary LIKE ? OR source_ref LIKE ?)",
                    [*params, like, like, like],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM memory_items {where} ORDER BY updated_at DESC LIMIT ?",
                    [*params, limit],
                ).fetchall()
        finally:
            conn.close()

        items = []
        now = _now()
        for row in rows:
            item = self._row_to_item(row)
            base = scores.get(item.id, 0.45 if query else 0.2)
            age_days = max(0.0, (now - item.updated_at) / 86400.0)
            recency = max(0.0, 0.08 * (1.0 - min(age_days, 30.0) / 30.0))
            item.score = base + recency + (item.confidence * 0.08) + TIER_BOOST.get(item.tier, 0.0)
            items.append(item)
        items.sort(key=lambda x: (x.score, x.updated_at), reverse=True)
        return [i.to_dict() for i in items[:limit]]

    def upsert_item(
        self,
        content: str,
        memory_type: str,
        source: str,
        source_ref: str,
        *,
        summary: str = "",
        scope: str = "personal",
        tier: str = "warm",
        confidence: float = 0.7,
        created_by: str = "indexer",
        metadata: Optional[dict[str, Any]] = None,
        item_id: str = "",
    ) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise ValueError("Memory content cannot be empty")
        memory_type = _type_or_default(memory_type)
        tier = _tier_or_default(tier)
        confidence = max(0.0, min(float(confidence), 1.0))
        item_id = item_id or _make_id(source_ref, content)
        content_hash = _content_hash(content)
        now = _now()
        metadata = metadata or {}
        summary = summary.strip() or _summary_for(content)

        with self._write_lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT * FROM memory_items WHERE id = ? OR (content_hash = ? AND deleted_at IS NULL)",
                    (item_id, content_hash),
                ).fetchone()
                if existing:
                    item_id = existing["id"]
                    before = self._row_to_item(existing).to_dict()
                    created_at = float(existing["created_at"])
                    conn.execute(
                        """
                        UPDATE memory_items
                        SET memory_type=?, content=?, summary=?, source=?, source_ref=?, scope=?,
                            tier=?, confidence=?, created_by=?, updated_at=?,
                            last_verified_at=?, metadata=?, content_hash=?, deleted_at=NULL
                        WHERE id=?
                        """,
                        (
                            memory_type, content, summary, source, source_ref, scope, tier, confidence,
                            created_by, now, now, json.dumps(metadata, ensure_ascii=False), content_hash, item_id,
                        ),
                    )
                    after = {**before, "content": content, "summary": summary, "updated_at": now}
                    self._audit(conn, item_id, "upsert", before, after, created_by)
                else:
                    created_at = now
                    conn.execute(
                        """
                        INSERT INTO memory_items (
                            id, memory_type, content, summary, source, source_ref, scope, tier,
                            confidence, created_by, created_at, updated_at, last_verified_at,
                            metadata, content_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id, memory_type, content, summary, source, source_ref, scope, tier,
                            confidence, created_by, created_at, now, now,
                            json.dumps(metadata, ensure_ascii=False), content_hash,
                        ),
                    )
                    self._audit(conn, item_id, "create", {}, {"content": content, "source_ref": source_ref}, created_by)
                self._sync_fts(conn, item_id, content, summary, source_ref)
                conn.commit()
            finally:
                conn.close()
        self._sync_vector(item_id, f"{summary}\n{content}")
        return self.get_item(item_id) or {}

    def get_item(self, item_id: str) -> Optional[dict[str, Any]]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
            return self._row_to_item(row).to_dict() if row else None
        finally:
            conn.close()

    def patch_item(self, item_id: str, updates: dict[str, Any], actor: str = "user") -> Optional[dict[str, Any]]:
        allowed = {"memory_type", "content", "summary", "source", "source_ref", "scope", "tier", "confidence", "metadata"}
        clean = {k: v for k, v in updates.items() if k in allowed}
        if not clean:
            return self.get_item(item_id)
        if "memory_type" in clean:
            clean["memory_type"] = _type_or_default(str(clean["memory_type"]))
        if "tier" in clean:
            clean["tier"] = _tier_or_default(str(clean["tier"]))
        if "confidence" in clean:
            clean["confidence"] = max(0.0, min(float(clean["confidence"]), 1.0))
        if "content" in clean:
            clean["content"] = str(clean["content"]).strip()
            clean["content_hash"] = _content_hash(clean["content"])
        if "summary" in clean:
            clean["summary"] = str(clean["summary"]).strip()
        if "metadata" in clean:
            clean["metadata"] = json.dumps(clean["metadata"] or {}, ensure_ascii=False)
        now = _now()
        clean["updated_at"] = now
        clean["last_verified_at"] = now

        with self._write_lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
                if not row:
                    return None
                before = self._row_to_item(row).to_dict()
                assignments = ", ".join(f"{k}=?" for k in clean)
                conn.execute(
                    f"UPDATE memory_items SET {assignments} WHERE id=?",
                    [*clean.values(), item_id],
                )
                updated = conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
                after = self._row_to_item(updated).to_dict()
                self._sync_fts(conn, item_id, after["content"], after["summary"], after["source_ref"])
                self._audit(conn, item_id, "update", before, after, actor)
                conn.commit()
            finally:
                conn.close()
        after_item = self.get_item(item_id)
        if after_item:
            self._sync_vector(item_id, f"{after_item['summary']}\n{after_item['content']}")
        return after_item

    def delete_item(self, item_id: str, actor: str = "user") -> bool:
        with self._write_lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
                if not row:
                    return False
                before = self._row_to_item(row).to_dict()
                conn.execute("UPDATE memory_items SET deleted_at=?, updated_at=? WHERE id=?", (_now(), _now(), item_id))
                conn.execute("DELETE FROM memory_items_fts WHERE item_id=?", (item_id,))
                self._audit(conn, item_id, "delete", before, {"deleted_at": _now()}, actor)
                conn.commit()
            finally:
                conn.close()
        self._delete_vector(item_id)
        return True

    def rebuild_from_workspace(self) -> dict[str, Any]:
        personal_dir = AgentManager._personal_dir()
        memory_dir = AgentManager._memory_dir()
        with self._write_lock:
            conn = self._connect()
            try:
                ids = [
                    r["id"]
                    for r in conn.execute(
                        "SELECT id FROM memory_items WHERE created_by='indexer'"
                    ).fetchall()
                ]
                if ids:
                    placeholders = ",".join("?" * len(ids))
                    conn.execute(f"DELETE FROM memory_items WHERE id IN ({placeholders})", ids)
                    conn.execute(f"DELETE FROM memory_items_fts WHERE item_id IN ({placeholders})", ids)
                conn.commit()
            finally:
                conn.close()
        for item_id in ids:
            self._delete_vector(item_id)

        indexed = 0
        skipped = 0
        for item in self._iter_workspace_items(personal_dir, memory_dir):
            try:
                self.upsert_item(**item)
                indexed += 1
            except Exception as exc:
                skipped += 1
                logger.info("Memory OS rebuild skipped item from %s: %s", item.get("source_ref"), exc)
        return {"indexed": indexed, "skipped": skipped, "status": self.status()}

    def record_dream_entries(self, entries: Iterable[str], scores: Optional[dict[str, float]] = None) -> dict[str, Any]:
        scores = scores or {}
        promoted = 0
        for entry in entries:
            content = entry.strip()
            if not content:
                continue
            score = float(scores.get(entry[:40], scores.get(content, 0.85)))
            candidate_id = _make_id(f"dream:{int(_now())}", content)
            item = self.upsert_item(
                content=content,
                memory_type="semantic",
                source="DREAM",
                source_ref=f"DREAM:{time.strftime('%Y-%m-%d')}",
                tier=_tier_from_text(content, "hot"),
                confidence=max(0.75, min(score, 0.98)),
                created_by="dream",
                metadata={"dream_score": score},
            )
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO memory_candidates
                    (id, content, source_ref, score, status, reason, promoted_item_id, created_at)
                    VALUES (?, ?, ?, ?, 'promoted', '', ?, ?)
                    """,
                    (candidate_id, content, item.get("source_ref", "DREAM"), score, item.get("id"), _now()),
                )
                conn.commit()
            finally:
                conn.close()
            promoted += 1
        return {"promoted": promoted}

    def _filters(
        self,
        memory_type: str,
        tier: str,
        source: str,
        include_deleted: bool,
    ) -> tuple[str, list[Any]]:
        clauses = []
        params: list[Any] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if memory_type:
            clauses.append("memory_type = ?")
            params.append(_type_or_default(memory_type))
        if tier:
            clauses.append("tier = ?")
            params.append(_tier_or_default(tier))
        if source:
            clauses.append("source = ?")
            params.append(source)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def _keyword_scores(self, query: str, limit: int) -> list[tuple[str, float]]:
        match = _sanitize_match_query(query)
        if not match:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT item_id, bm25(memory_items_fts) AS rank
                FROM memory_items_fts
                WHERE memory_items_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match, limit),
            ).fetchall()
            return [(r["item_id"], min(0.95, 0.65 + 1.0 / (1.0 + abs(float(r["rank"]))))) for r in rows]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    def _vector_scores(self, query: str, limit: int) -> list[tuple[str, float]]:
        if self._vector_error:
            return []
        try:
            embedding = encode_query(query)
            conn = self._connect(load_vec=True)
            try:
                rows = conn.execute(
                    """
                    SELECT item_id, distance
                    FROM vec_memory_items
                    WHERE embedding MATCH ?
                    ORDER BY distance
                    LIMIT ?
                    """,
                    (json.dumps(embedding), limit),
                ).fetchall()
                return [(r["item_id"], max(0.0, 1.0 - float(r["distance"]))) for r in rows]
            finally:
                conn.close()
        except Exception as exc:
            self._vector_error = str(exc)
            return []

    def _sync_fts(self, conn: sqlite3.Connection, item_id: str, content: str, summary: str, source_ref: str) -> None:
        conn.execute("DELETE FROM memory_items_fts WHERE item_id=?", (item_id,))
        conn.execute(
            "INSERT INTO memory_items_fts (item_id, content, summary, source_ref) VALUES (?, ?, ?, ?)",
            (item_id, content, summary, source_ref),
        )

    def _sync_vector(self, item_id: str, text: str) -> None:
        if self._vector_error:
            return
        try:
            embedding = encode_texts([text])[0]
            conn = self._connect(load_vec=True)
            try:
                conn.execute("DELETE FROM vec_memory_items WHERE item_id=?", (item_id,))
                conn.execute(
                    "INSERT INTO vec_memory_items (item_id, embedding) VALUES (?, ?)",
                    (item_id, json.dumps(embedding)),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            self._vector_error = str(exc)

    def _delete_vector(self, item_id: str) -> None:
        if self._vector_error:
            return
        try:
            conn = self._connect(load_vec=True)
            try:
                conn.execute("DELETE FROM vec_memory_items WHERE item_id=?", (item_id,))
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            self._vector_error = str(exc)

    def _audit(
        self,
        conn: sqlite3.Connection,
        item_id: str,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
        actor: str,
    ) -> None:
        conn.execute(
            "INSERT INTO memory_audit (item_id, action, before_json, after_json, actor, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                item_id,
                action,
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                actor,
                _now(),
            ),
        )

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            memory_type=row["memory_type"],
            content=row["content"],
            summary=row["summary"],
            source=row["source"],
            source_ref=row["source_ref"],
            scope=row["scope"],
            tier=row["tier"],
            confidence=float(row["confidence"]),
            created_by=row["created_by"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            last_verified_at=float(row["last_verified_at"]),
            metadata=_safe_json_loads(row["metadata"]),
            deleted_at=float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        )

    def _iter_workspace_items(self, personal_dir: Path, memory_dir: Path) -> Iterable[dict[str, Any]]:
        for name in ("USER.md", "SOUL.md", "IDENTITY.md", "INNER.md"):
            path = personal_dir / name
            text = self._read_text(path)
            if text:
                yield self._item_kwargs(text, "identity", name, f"{name}:all", "hot", 0.92)

        memory_text = self._read_text(personal_dir / "MEMORY.md")
        if memory_text:
            for line_no, line in self._significant_lines(memory_text):
                if line.startswith("#") or line.startswith(">") or line.startswith("---"):
                    continue
                yield self._item_kwargs(
                    line,
                    "semantic",
                    "MEMORY.md",
                    f"MEMORY.md:{line_no}",
                    _tier_from_text(line, "warm"),
                    0.86,
                )

        handoff = self._read_text(personal_dir / "session_handoff.md")
        if handoff:
            yield self._item_kwargs(handoff, "working", "session_handoff.md", "session_handoff.md:all", "hot", 0.78)

        dreams = self._read_text(personal_dir / "DREAMS.md")
        if dreams:
            for idx, chunk in enumerate(self._paragraphs(dreams)):
                yield self._item_kwargs(chunk, "episodic", "DREAMS.md", f"DREAMS.md:{idx + 1}", "warm", 0.7)

        if memory_dir.exists():
            for diary in sorted(memory_dir.glob("*.md"), reverse=True):
                text = self._read_text(diary)
                for idx, chunk in enumerate(self._paragraphs(text)):
                    yield self._item_kwargs(chunk, "episodic", "diary", f"memory/{diary.name}:{idx + 1}", "warm", 0.66)

        learnings = personal_dir / ".learnings"
        if learnings.exists():
            for learning in sorted(learnings.glob("*.md")):
                text = self._read_text(learning)
                if text:
                    yield self._item_kwargs(text, "procedural", "learnings", f".learnings/{learning.name}:all", "warm", 0.76)

    def _item_kwargs(
        self,
        content: str,
        memory_type: str,
        source: str,
        source_ref: str,
        tier: str,
        confidence: float,
    ) -> dict[str, Any]:
        return {
            "content": content,
            "memory_type": memory_type,
            "source": source,
            "source_ref": source_ref,
            "tier": tier,
            "confidence": confidence,
            "created_by": "indexer",
            "metadata": {"indexed_from": source_ref},
        }

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8") if path.exists() else ""
        except (OSError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _paragraphs(text: str) -> list[str]:
        chunks = [c.strip() for c in re.split(r"\n\s*\n", text or "") if c.strip()]
        return [c for c in chunks if len(c) >= 20 and not c.startswith("---")][:200]

    @staticmethod
    def _significant_lines(text: str) -> list[tuple[int, str]]:
        lines = []
        for idx, line in enumerate((text or "").splitlines(), start=1):
            clean = line.strip()
            if len(clean) < 8:
                continue
            if clean.startswith(("(", "（")):
                continue
            lines.append((idx, clean))
        return lines


_memory_os: Optional[MemoryOS] = None


def get_memory_os() -> MemoryOS:
    global _memory_os
    if _memory_os is None:
        _memory_os = MemoryOS()
    return _memory_os
