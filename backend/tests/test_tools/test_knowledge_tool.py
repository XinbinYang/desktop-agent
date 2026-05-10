import pytest
from pathlib import Path

from app.tools.knowledge_tool import KnowledgeIndexTool, KnowledgeSearchTool, KnowledgeListTool


class TestKnowledgeTools:
    @pytest.fixture(autouse=True)
    def isolate_db(self, monkeypatch, tmp_path):
        test_db = tmp_path / "test_knowledge.db"
        monkeypatch.setattr("app.rag.engine.DB_PATH", test_db)
        import app.rag.engine as engine_mod
        engine_mod._rag_engine = None
        yield
        engine_mod._rag_engine = None

    @pytest.mark.asyncio
    async def test_knowledge_list_empty(self):
        tool = KnowledgeListTool()
        result = await tool.execute()
        assert "知识库为空" in result.output

    @pytest.mark.asyncio
    async def test_knowledge_index_and_search(self, tmp_path):
        test_file = tmp_path / "doc.md"
        test_file.write_text("# Test\n\nThis is a test document about machine learning.", encoding="utf-8")

        index_tool = KnowledgeIndexTool()
        result = await index_tool.execute(path=str(test_file), recursive=False)
        assert result.error == ""
        assert "索引完成" in result.output

        search_tool = KnowledgeSearchTool()
        result = await search_tool.execute(query="machine learning", top_k=3)
        assert result.error == ""
        assert "machine learning" in result.output.lower()

        list_tool = KnowledgeListTool()
        result = await list_tool.execute()
        assert str(test_file) in result.output

    @pytest.mark.asyncio
    async def test_knowledge_index_nonexistent(self):
        tool = KnowledgeIndexTool()
        result = await tool.execute(path="/nonexistent/path/file.txt", recursive=False)
        assert "路径不存在" in result.error

    @pytest.mark.asyncio
    async def test_knowledge_search_no_results(self):
        tool = KnowledgeSearchTool()
        result = await tool.execute(query="xyz123nonexistent", top_k=3)
        assert "未找到" in result.output
