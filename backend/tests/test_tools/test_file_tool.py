import pytest
from app.tools.file_tool import FileReadTool, FileWriteTool, FileListTool, FileSearchTool, FileDeleteTool


class TestFileReadTool:
    @pytest.fixture
    def tool(self):
        return FileReadTool()

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tool, temp_dir):
        test_file = temp_dir / "test.txt"
        test_file.write_text("hello world", encoding="utf-8")

        result = await tool.execute(path=str(test_file))
        assert result.error == ""
        assert "hello world" in result.output

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tool):
        result = await tool.execute(path="/nonexistent/path/file.txt")
        assert "不存在" in result.error

    @pytest.mark.asyncio
    async def test_read_directory_not_file(self, tool, temp_dir):
        result = await tool.execute(path=str(temp_dir))
        assert "不是文件" in result.error

    @pytest.mark.asyncio
    async def test_read_with_offset_and_limit(self, tool, temp_dir):
        test_file = temp_dir / "lines.txt"
        test_file.write_text("line0\nline1\nline2\nline3\nline4\n", encoding="utf-8")

        result = await tool.execute(path=str(test_file), offset=1, limit=2)
        assert "line1" in result.output
        assert "line2" in result.output
        assert "line0" not in result.output

    @pytest.mark.asyncio
    async def test_read_oversized_file(self, tool, temp_dir):
        test_file = temp_dir / "big.bin"
        test_file.write_bytes(b"x" * (11 * 1024 * 1024))  # 11MB

        result = await tool.execute(path=str(test_file))
        assert "过大" in result.error


class TestFileWriteTool:
    @pytest.fixture
    def tool(self):
        return FileWriteTool()

    @pytest.mark.asyncio
    async def test_write_new_file(self, tool, temp_dir):
        target = temp_dir / "output.txt"
        result = await tool.execute(path=str(target), content="new content")
        assert result.error == ""
        assert target.read_text(encoding="utf-8") == "new content"

    @pytest.mark.asyncio
    async def test_write_creates_directories(self, tool, temp_dir):
        target = temp_dir / "sub" / "dir" / "file.txt"
        result = await tool.execute(path=str(target), content="nested")
        assert result.error == ""
        assert target.exists()

    @pytest.mark.asyncio
    async def test_overwrite_existing_file(self, tool, temp_dir):
        target = temp_dir / "existing.txt"
        target.write_text("old", encoding="utf-8")
        result = await tool.execute(path=str(target), content="new")
        assert target.read_text(encoding="utf-8") == "new"


class TestFileListTool:
    @pytest.fixture
    def tool(self):
        return FileListTool()

    @pytest.mark.asyncio
    async def test_list_directory(self, tool, temp_dir):
        (temp_dir / "a.txt").write_text("a")
        (temp_dir / "b.txt").write_text("b")
        (temp_dir / "subdir").mkdir()

        result = await tool.execute(path=str(temp_dir))
        assert result.error == ""
        assert "a.txt" in result.output
        assert "b.txt" in result.output
        assert "subdir" in result.output

    @pytest.mark.asyncio
    async def test_list_recursive(self, tool, temp_dir):
        sub = temp_dir / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("x")

        result = await tool.execute(path=str(temp_dir), recursive=True)
        assert "nested.txt" in result.output

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self, tool):
        result = await tool.execute(path="/nonexistent/dir")
        assert "不存在" in result.error


class TestFileSearchTool:
    @pytest.fixture
    def tool(self):
        return FileSearchTool()

    @pytest.mark.asyncio
    async def test_search_found(self, tool, temp_dir):
        (temp_dir / "hello.txt").write_text("x")
        (temp_dir / "world.py").write_text("y")

        result = await tool.execute(path=str(temp_dir), keyword="hello")
        assert "hello.txt" in result.output
        assert "world.py" not in result.output

    @pytest.mark.asyncio
    async def test_search_not_found(self, tool, temp_dir):
        result = await tool.execute(path=str(temp_dir), keyword="nothing")
        assert "未找到" in result.output


class TestFileDeleteTool:
    @pytest.fixture
    def tool(self):
        return FileDeleteTool()

    @pytest.mark.asyncio
    async def test_delete_file(self, tool, temp_dir):
        target = temp_dir / "to_delete.txt"
        target.write_text("bye")

        result = await tool.execute(path=str(target))
        assert result.error == ""
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, tool):
        result = await tool.execute(path="/nonexistent/file.txt")
        assert "不是文件或不存在" in result.error

    @pytest.mark.asyncio
    async def test_delete_directory_is_rejected(self, tool, temp_dir):
        result = await tool.execute(path=str(temp_dir))
        assert "不是文件或不存在" in result.error
