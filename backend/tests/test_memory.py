"""Tests for cross-session memory system."""
import time
from pathlib import Path
from app.memory import (
    MemoryEntry,
    save_memory,
    load_memories,
    delete_memory,
    search_memories,
    build_memory_prompt,
    _slugify,
)


class TestSlugify:
    def test_basic(self):
        assert "hello-world" in _slugify("Hello World!")

    def test_chinese(self):
        # Non-ASCII chars are stripped by the slug regex — returns empty string
        slug = _slugify("中文测试")
        assert isinstance(slug, str)

    def test_truncation(self):
        long_text = "a" * 200
        slug = _slugify(long_text)
        assert len(slug) <= 80


class TestSaveAndLoadMemory:
    def test_save_and_load(self, tmp_path):
        entry = save_memory(str(tmp_path), "project_knowledge", "This project uses FastAPI", ["api", "python"])
        assert entry is not None
        assert entry.type == "project_knowledge"
        assert "FastAPI" in entry.content

        loaded = load_memories(str(tmp_path))
        assert len(loaded) == 1
        assert loaded[0].type == "project_knowledge"
        assert "FastAPI" in loaded[0].content
        assert "api" in loaded[0].tags

    def test_load_empty_directory(self, tmp_path):
        loaded = load_memories(str(tmp_path))
        assert loaded == []

    def test_save_multiple_entries(self, tmp_path):
        save_memory(str(tmp_path), "user_preference", "prefer pytest", ["testing"])
        save_memory(str(tmp_path), "project_knowledge", "use TypeScript", ["frontend"])
        loaded = load_memories(str(tmp_path))
        assert len(loaded) == 2
        types = {e.type for e in loaded}
        assert "user_preference" in types
        assert "project_knowledge" in types

    def test_save_without_tags(self, tmp_path):
        entry = save_memory(str(tmp_path), "decision_log", "Use worktree for evals")
        assert entry is not None
        assert entry.tags == []

    def test_invalid_path_returns_none(self):
        entry = save_memory("", "test", "content")
        assert entry is None


class TestDeleteMemory:
    def test_delete_existing(self, tmp_path):
        entry = save_memory(str(tmp_path), "test", "content")
        assert entry is not None
        assert delete_memory(str(tmp_path), entry.id) == True
        assert load_memories(str(tmp_path)) == []

    def test_delete_nonexistent(self, tmp_path):
        assert delete_memory(str(tmp_path), "nonexistent") == False

    def test_delete_empty_project(self):
        assert delete_memory("", "anything") == False


class TestSearchMemories:
    def test_search_by_content(self, tmp_path):
        save_memory(str(tmp_path), "test", "FastAPI is great")
        save_memory(str(tmp_path), "test", "TypeScript is nice")
        results = search_memories(str(tmp_path), "FastAPI")
        assert len(results) == 1
        assert "FastAPI" in results[0].content

    def test_search_by_tag(self, tmp_path):
        save_memory(str(tmp_path), "test", "content", ["python"])
        save_memory(str(tmp_path), "test", "other", ["typescript"])
        results = search_memories(str(tmp_path), "python")
        assert len(results) == 1

    def test_search_no_match(self, tmp_path):
        save_memory(str(tmp_path), "test", "content")
        results = search_memories(str(tmp_path), "xyznotfound")
        assert results == []

    def test_search_empty(self, tmp_path):
        assert search_memories(str(tmp_path), "anything") == []


class TestBuildMemoryPrompt:
    def test_empty_directory(self, tmp_path):
        prompt = build_memory_prompt(str(tmp_path))
        assert prompt == ""

    def test_returns_markdown_section(self, tmp_path):
        save_memory(str(tmp_path), "project_knowledge", "Use FastAPI")
        prompt = build_memory_prompt(str(tmp_path))
        assert "Session Memory" in prompt
        assert "FastAPI" in prompt

    def test_respects_max_entries(self, tmp_path):
        for i in range(10):
            save_memory(str(tmp_path), "project_knowledge", f"Memory {i}")
        prompt = build_memory_prompt(str(tmp_path), max_entries=3)
        lines = [l for l in prompt.split("\n") if l.startswith("-")]
        assert len(lines) <= 3

    def test_prioritizes_user_preference(self, tmp_path):
        save_memory(str(tmp_path), "project_knowledge", "Knowledge")
        save_memory(str(tmp_path), "user_preference", "Preference")
        prompt = build_memory_prompt(str(tmp_path), max_entries=1)
        assert "Preference" in prompt


class TestMemoryEntry:
    def test_to_dict(self):
        entry = MemoryEntry(id="test-1", type="project_knowledge", content="content", tags=["tag"])
        d = entry.to_dict()
        assert d["id"] == "test-1"
        assert d["type"] == "project_knowledge"
        assert "tag" in d["tags"]
