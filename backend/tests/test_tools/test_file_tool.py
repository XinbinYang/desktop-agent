from pathlib import Path

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
    async def test_read_nonexistent_file(self, tool, temp_dir):
        result = await tool.execute(path=str(temp_dir / "nonexistent.txt"))
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_read_directory_not_file(self, tool, temp_dir):
        result = await tool.execute(path=str(temp_dir))
        assert "not a file" in result.error

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
        assert "too large" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_accepts_file_path_alias(self, tool, temp_dir, monkeypatch):
        from app.project_manager import ProjectManager

        monkeypatch.setattr(ProjectManager, "_current_project", {"path": str(temp_dir), "name": "tmp"})
        test_file = temp_dir / "alias.txt"
        test_file.write_text("alias-ok", encoding="utf-8")

        result = await tool.execute(file_path="alias.txt", project_relative=True)

        assert result.error == ""
        assert "alias-ok" in result.output


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
        edit = result.metadata["file_edit"]
        assert edit["operation"] == "create"
        assert edit["new_text"] == "new content"
        assert edit["stats"]["added"] >= 1

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
        edit = result.metadata["file_edit"]
        assert edit["operation"] == "modify"
        assert edit["old_text"] == "old"
        assert edit["new_text"] == "new"
        assert "--- a/existing.txt" in edit["unified_diff"]

    @pytest.mark.asyncio
    async def test_write_large_file_truncates_inline_diff(self, tool, temp_dir):
        target = temp_dir / "large.txt"
        result = await tool.execute(path=str(target), content="x" * 1_000_001)
        assert result.error == ""
        edit = result.metadata["file_edit"]
        assert edit["truncated"] is True
        assert "old_text" not in edit
        assert "new_text" not in edit


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
    async def test_list_nonexistent_directory(self, tool, temp_dir):
        result = await tool.execute(path=str(temp_dir / "nonexistent_dir"))
        assert "not found" in result.error


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
        assert "No matching" in result.output


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
    async def test_delete_nonexistent_file(self, tool, temp_dir):
        result = await tool.execute(path=str(temp_dir / "nonexistent.txt"))
        assert "Not a file" in result.error

    @pytest.mark.asyncio
    async def test_delete_directory_is_rejected(self, tool, temp_dir):
        result = await tool.execute(path=str(temp_dir))
        assert "Not a file" in result.error


class TestFileSandbox:
    """路径沙箱安全测试"""

    @pytest.fixture(autouse=True)
    def _force_sandbox_mode(self, monkeypatch):
        """Tests must not depend on local models.yaml sandbox_mode (e.g. unrestricted)."""
        import app.config as config_mod

        orig = config_mod.load_config

        def wrapped():
            c = orig()
            c.settings.sandbox_mode = "sandbox"
            return c

        monkeypatch.setattr(config_mod, "load_config", wrapped)

    @pytest.fixture
    def read_tool(self):
        return FileReadTool()

    @pytest.fixture
    def write_tool(self):
        return FileWriteTool()

    @pytest.mark.asyncio
    async def test_read_outside_project_is_blocked(self, read_tool):
        result = await read_tool.execute(path="C:/Windows/System32/notepad.exe")
        assert "out of bounds" in result.error

    @pytest.mark.asyncio
    async def test_prefix_similar_sibling_path_is_blocked(self, read_tool):
        # A file in a sibling directory OUTSIDE the project root should be blocked
        backend_root = Path(__file__).parents[2]  # backend/
        outside_dir = backend_root.parent.parent / f"{backend_root.parent.name}_evil"
        outside_dir.mkdir(exist_ok=True)
        target = outside_dir / "sensitive.txt"
        target.write_text("outside", encoding="utf-8")
        try:
            result = await read_tool.execute(path=str(target))
            assert "out of bounds" in result.error
        finally:
            target.unlink(missing_ok=True)
            outside_dir.rmdir()

    @pytest.mark.asyncio
    async def test_write_outside_project_is_blocked(self, write_tool):
        result = await write_tool.execute(path="C:/tmp/hack.txt", content="bad")
        assert "out of bounds" in result.error

    @pytest.mark.asyncio
    async def test_traverse_parent_directory_is_blocked(self, read_tool):
        # 尝试用 ../ 跳出项目目录
        result = await read_tool.execute(path="../../outside.txt")
        assert "out of bounds" in result.error

    @pytest.mark.asyncio
    async def test_agents_relative_path_writes_to_runtime_not_repo(self, write_tool):
        """Regression: relative 'AGENTS/personal/__probe__.md' with
        project_relative=False must land under the mutable runtime AGENTS
        workspace, not the repo template directory or backend cwd."""
        from app.runtime_paths import agents_dir, repo_root

        probe_rel = "AGENTS/personal/__test_probe__.md"
        expected = agents_dir() / "personal" / "__test_probe__.md"
        repo_template = repo_root() / probe_rel
        # Clean up any leftover from previous runs
        if expected.exists():
            expected.unlink()
        if repo_template.exists():
            repo_template.unlink()

        result = await write_tool.execute(path=probe_rel, content="probe ok")
        assert result.error == "", f"unexpected error: {result.error}"

        # Verify the file was created at the runtime AGENTS path
        assert expected.exists(), f"File not found at expected path: {expected}"
        assert expected.read_text(encoding="utf-8") == "probe ok"
        assert not repo_template.exists(), f"File incorrectly landed at repo template path: {repo_template}"

        # Double-check: it should NOT exist under backend/
        wrong = Path("backend") / probe_rel
        assert not wrong.exists(), f"File incorrectly landed at {wrong}"

        # Cleanup
        expected.unlink(missing_ok=True)


class TestFileSandboxUnrestricted:
    """End-to-end path anchor tests with sandbox_mode=unrestricted.

    Same assertions as TestFileSandbox but in unrestricted mode, since
    the unrestricted code path in file_tool.py had the same cwd bug.
    """

    @pytest.fixture(autouse=True)
    def _force_unrestricted_mode(self, monkeypatch):
        import app.config as config_mod

        orig = config_mod.load_config

        def wrapped():
            c = orig()
            c.settings.sandbox_mode = "unrestricted"
            return c

        monkeypatch.setattr(config_mod, "load_config", wrapped)

    @pytest.fixture
    def write_tool(self):
        return FileWriteTool()

    @pytest.mark.asyncio
    async def test_agents_relative_path_writes_to_runtime_not_cwd(self, write_tool):
        """Same regression test but exercising the unrestricted code path."""
        from app.runtime_paths import agents_dir, repo_root

        probe_rel = "AGENTS/personal/__test_probe_unrestricted__.md"
        expected = agents_dir() / "personal" / "__test_probe_unrestricted__.md"
        repo_template = repo_root() / probe_rel
        if expected.exists():
            expected.unlink()
        if repo_template.exists():
            repo_template.unlink()

        result = await write_tool.execute(path=probe_rel, content="unrestricted ok")
        assert result.error == "", f"unexpected error: {result.error}"

        assert expected.exists(), f"File not found at expected path: {expected}"
        assert expected.read_text(encoding="utf-8") == "unrestricted ok"
        assert not repo_template.exists(), f"File incorrectly landed at repo template path: {repo_template}"

        wrong = Path("backend") / probe_rel
        assert not wrong.exists(), f"File incorrectly landed at {wrong}"

        expected.unlink(missing_ok=True)
