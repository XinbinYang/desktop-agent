import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.rag.splitter import recursive_split_text, split_document
from app.rag.embedding import encode_texts, encode_query, get_embedding_dim
from app.rag.engine import RAGEngine, DB_PATH, get_rag_status, has_indexed_docs


class TestTextSplitter:
    def test_small_text_no_split(self):
        text = "Hello world"
        chunks = recursive_split_text(text, chunk_size=100, chunk_overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_large_text_splits(self):
        text = "Sentence one. " * 100
        chunks = recursive_split_text(text, chunk_size=50, chunk_overlap=5)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 55  # 允许少量超出

    def test_markdown_split(self):
        text = "# Title\n\nPara one.\n\n## Section\n\nPara two.\n\nPara three."
        chunks = recursive_split_text(text, chunk_size=30, chunk_overlap=5)
        assert len(chunks) >= 2

    def test_split_document(self):
        chunks = split_document("Line 1\nLine 2\nLine 3", "/tmp/test.md", chunk_size=10, chunk_overlap=2)
        assert len(chunks) > 0
        assert chunks[0]["source_path"] == "/tmp/test.md"
        assert "index" in chunks[0]


class TestEmbedding:
    def test_encode_texts(self):
        texts = ["hello", "world"]
        embeddings = encode_texts(texts)
        assert len(embeddings) == 2
        assert len(embeddings[0]) == get_embedding_dim()
        assert len(embeddings[1]) == get_embedding_dim()

    def test_encode_query(self):
        emb = encode_query("test query")
        assert len(emb) == get_embedding_dim()
        assert isinstance(emb, list)
        assert all(isinstance(x, float) for x in emb)


class TestRAGStatus:
    def test_has_indexed_docs_false_when_db_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.rag.engine.DB_PATH", tmp_path / "missing.db")

        assert has_indexed_docs() is False

    def test_has_indexed_docs_false_when_doc_table_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.rag.engine.DB_PATH", tmp_path / "empty.db")
        (tmp_path / "empty.db").touch()

        assert has_indexed_docs() is False

    def test_get_rag_status_reports_missing_sqlite_vec(self, monkeypatch, tmp_path):
        import app.rag.engine as engine_mod

        monkeypatch.setattr("app.rag.engine.DB_PATH", tmp_path / "knowledge.db")
        original_find_spec = engine_mod.importlib.util.find_spec

        def fake_find_spec(name):
            if name == "sqlite_vec":
                return None
            return original_find_spec(name)

        monkeypatch.setattr(engine_mod.importlib.util, "find_spec", fake_find_spec)

        status = get_rag_status()

        assert status["status"] == "unavailable"
        assert status["sqlite_vec_available"] is False
        assert "sqlite-vec" in status["error"]


class TestRAGEngine:
    @pytest.fixture(autouse=True)
    def isolate_db(self, monkeypatch, tmp_path):
        """每个测试使用独立的临时数据库。"""
        test_db = tmp_path / "test_knowledge.db"
        monkeypatch.setattr("app.rag.engine.DB_PATH", test_db)
        # 清空全局单例，强制重新初始化
        import app.rag.engine as engine_mod
        engine_mod._rag_engine = None
        yield
        engine_mod._rag_engine = None

    def test_index_and_search_file(self, tmp_path):
        test_file = tmp_path / "notes.md"
        test_file.write_text("# Project\n\nDesktop Agent is a cool project.\n\nIt supports RAG.", encoding="utf-8")

        engine = RAGEngine()
        result = engine.index_file(str(test_file), recursive=False)
        assert "error" not in result
        assert result["indexed"] == 1
        assert result["chunks"] > 0

        docs = engine.list_docs()
        assert len(docs) == 1
        assert docs[0]["source_path"] == str(test_file)

        results = engine.search("RAG support", top_k=3)
        assert len(results) > 0
        assert any("RAG" in r.content for r in results)

    def test_index_folder(self, tmp_path):
        (tmp_path / "a.txt").write_text("Apple banana cherry", encoding="utf-8")
        (tmp_path / "b.txt").write_text("Dog elephant fox", encoding="utf-8")

        engine = RAGEngine()
        result = engine.index_file(str(tmp_path), recursive=False)
        assert result["indexed"] == 2
        assert result["chunks"] > 0

    def test_delete_doc(self, tmp_path):
        test_file = tmp_path / "temp.md"
        test_file.write_text("Temporary content", encoding="utf-8")

        engine = RAGEngine()
        engine.index_file(str(test_file), recursive=False)
        assert len(engine.list_docs()) == 1

        engine.delete_doc(str(test_file))
        assert len(engine.list_docs()) == 0

    def test_search_empty_db(self):
        engine = RAGEngine()
        results = engine.search("nonexistent query")
        assert results == []

    def test_reindex_replaces_chunks(self, tmp_path):
        """Re-indexing the same file must not duplicate chunks."""
        test_file = tmp_path / "notes.md"
        test_file.write_text("# Project\n\nFirst version.\n\nMore lines here.", encoding="utf-8")

        engine = RAGEngine()
        first = engine.index_file(str(test_file), recursive=False)
        assert first["indexed"] == 1
        first_count = first["chunks"]
        assert first_count > 0
        assert sum(d["chunk_count"] for d in engine.list_docs()) == first_count

        # Modify file and re-index — total chunks for this source must equal
        # the new count, not (old + new).
        test_file.write_text("# Project\n\nSecond version with longer content.", encoding="utf-8")
        second = engine.index_file(str(test_file), recursive=False)
        assert second["indexed"] == 1
        second_count = second["chunks"]
        assert sum(d["chunk_count"] for d in engine.list_docs()) == second_count

    def test_reindex_folder_replaces_chunks(self, tmp_path):
        """Re-indexing a folder is also idempotent across all contained files."""
        (tmp_path / "a.txt").write_text("Apple banana cherry", encoding="utf-8")
        (tmp_path / "b.txt").write_text("Dog elephant fox", encoding="utf-8")

        engine = RAGEngine()
        first = engine.index_file(str(tmp_path), recursive=False)
        first_total = sum(d["chunk_count"] for d in engine.list_docs())
        assert first_total == first["chunks"]

        engine.index_file(str(tmp_path), recursive=False)
        second_total = sum(d["chunk_count"] for d in engine.list_docs())
        assert second_total == first_total  # not doubled

    def test_source_filter(self, tmp_path):
        f1 = tmp_path / "project" / "code.py"
        f1.parent.mkdir(parents=True, exist_ok=True)
        f1.write_text("def hello(): pass", encoding="utf-8")

        f2 = tmp_path / "docs" / "readme.md"
        f2.parent.mkdir(parents=True, exist_ok=True)
        f2.write_text("# Hello world", encoding="utf-8")

        engine = RAGEngine()
        engine.index_file(str(tmp_path), recursive=True)

        results = engine.search("hello", top_k=5, source_filter=str(f1.parent))
        assert len(results) > 0
        assert all(r.source_path.startswith(str(f1.parent)) for r in results)
