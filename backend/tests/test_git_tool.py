import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.tools.git_tool import (
    GitCloneTool, GitStatusTool, GitDiffTool, GitCommitTool,
    GitPullTool, GitPushTool, GitBranchTool, GitRemoteTool
)
from app.project_manager import ProjectManager


@pytest.fixture(autouse=True)
def reset_project_manager():
    ProjectManager._current_project = None
    yield
    ProjectManager._current_project = None


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository for testing"""
    repo = tmp_path / "testrepo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    (repo / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo), check=True, capture_output=True)
    return repo


@pytest.fixture
def second_repo(tmp_path):
    """Create a second bare repo to act as remote"""
    repo = tmp_path / "remote.git"
    repo.mkdir()
    subprocess.run(["git", "init", "--bare"], cwd=str(repo), check=True, capture_output=True)
    return repo


class TestGitStatusTool:
    @pytest.mark.asyncio
    async def test_status_clean(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        tool = GitStatusTool()
        result = await tool.execute()
        assert not result.error
        assert "main" in result.output or "master" in result.output

    @pytest.mark.asyncio
    async def test_status_with_modified(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        (git_repo / "file.txt").write_text("modified")
        tool = GitStatusTool()
        result = await tool.execute()
        assert not result.error
        assert "modified" in result.output


class TestGitDiffTool:
    @pytest.mark.asyncio
    async def test_diff_no_project(self):
        tool = GitDiffTool()
        result = await tool.execute()
        assert result.error is not None
        assert "No project" in result.error or "no project" in result.error.lower()

    @pytest.mark.asyncio
    async def test_diff_with_modified_file(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        (git_repo / "file.txt").write_text("modified")
        tool = GitDiffTool()
        result = await tool.execute()
        assert not result.error
        assert "modified" in result.output

    @pytest.mark.asyncio
    async def test_diff_lists_untracked_file(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        (git_repo / "new.txt").write_text("new")
        tool = GitDiffTool()
        result = await tool.execute()
        assert not result.error
        assert "Untracked files" in result.output
        assert "new.txt" in result.output


class TestGitCommitTool:
    @pytest.mark.asyncio
    async def test_commit(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        (git_repo / "new.txt").write_text("new file")
        tool = GitCommitTool()
        result = await tool.execute("add new file")
        assert not result.error
        assert "Committed" in result.output


class TestGitBranchTool:
    @pytest.mark.asyncio
    async def test_branch_list(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        tool = GitBranchTool()
        result = await tool.execute("list")
        assert not result.error
        assert "main" in result.output or "master" in result.output

    @pytest.mark.asyncio
    async def test_branch_create(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        tool = GitBranchTool()
        result = await tool.execute("create", "feature-x")
        assert not result.error
        assert "feature-x" in result.output

    @pytest.mark.asyncio
    async def test_branch_switch(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        tool = GitBranchTool()
        await tool.execute("create", "feature-x")
        # Switch to the default branch (main or master)
        default_branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(git_repo),
            capture_output=True, text=True
        ).stdout.strip()
        result = await tool.execute("switch", default_branch)
        assert not result.error or "Already on" in result.error


class TestGitRemoteTool:
    @pytest.mark.asyncio
    async def test_remote_list_empty(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        tool = GitRemoteTool()
        result = await tool.execute("list")
        assert not result.error

    @pytest.mark.asyncio
    async def test_remote_add(self, git_repo):
        ProjectManager.open_project(str(git_repo))
        tool = GitRemoteTool()
        result = await tool.execute("add", "origin", "https://github.com/test/repo.git")
        assert not result.error
        assert "origin" in result.output


class TestGitPushPull:
    @pytest.mark.asyncio
    async def test_push_to_remote(self, git_repo, second_repo):
        """Push to a bare repo should succeed"""
        ProjectManager.open_project(str(git_repo))
        # Get default branch name
        default_branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(git_repo),
            capture_output=True, text=True
        ).stdout.strip()
        # Add remote
        remote_tool = GitRemoteTool()
        await remote_tool.execute("add", "origin", str(second_repo))
        # Push with upstream
        tool = GitPushTool()
        result = await tool.execute("origin", default_branch)
        assert not result.error
        assert "Pushed" in result.output

    @pytest.mark.asyncio
    async def test_pull_no_remote(self, git_repo):
        """Pull without remote should fail gracefully"""
        ProjectManager.open_project(str(git_repo))
        tool = GitPullTool()
        result = await tool.execute("origin")
        # Should fail because no remote configured
        assert result.error is not None


class TestGitPushForce:
    @pytest.mark.asyncio
    @patch("app.config.load_config")
    async def test_force_push_denied_in_sandbox(self, mock_load_config, git_repo):
        """Force push should be denied when sandbox_mode is not unrestricted."""
        mock_cfg = MagicMock()
        mock_cfg.settings.sandbox_mode = "default"
        mock_load_config.return_value = mock_cfg
        ProjectManager.open_project(str(git_repo))
        tool = GitPushTool()
        result = await tool.execute("origin", "main", force=True)
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    @patch("app.config.load_config")
    async def test_force_push_allowed_in_unrestricted(self, mock_load_config, git_repo, second_repo):
        """Force push should be allowed when sandbox_mode is unrestricted."""
        mock_cfg = MagicMock()
        mock_cfg.settings.sandbox_mode = "unrestricted"
        mock_load_config.return_value = mock_cfg
        ProjectManager.open_project(str(git_repo))
        default_branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(git_repo),
            capture_output=True, text=True
        ).stdout.strip()
        remote_tool = GitRemoteTool()
        await remote_tool.execute("add", "origin", str(second_repo))
        tool = GitPushTool()
        result = await tool.execute("origin", default_branch, force=True)
        assert not result.error
        assert "Pushed" in result.output

    @pytest.mark.asyncio
    async def test_normal_push_no_force_still_works(self, git_repo, second_repo):
        """Normal push without force parameter should still work."""
        ProjectManager.open_project(str(git_repo))
        default_branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(git_repo),
            capture_output=True, text=True
        ).stdout.strip()
        remote_tool = GitRemoteTool()
        await remote_tool.execute("add", "origin", str(second_repo))
        tool = GitPushTool()
        result = await tool.execute("origin", default_branch)
        assert not result.error


class TestGitCloneTool:
    @pytest.mark.asyncio
    async def test_clone(self, git_repo, tmp_path):
        target = tmp_path / "cloned"
        tool = GitCloneTool()
        result = await tool.execute(str(git_repo), str(target))
        assert not result.error
        assert target.exists()
        assert (target / ".git").exists()
        assert (target / "file.txt").exists()


class TestGitToolNoProject:
    @pytest.mark.asyncio
    async def test_status_no_project(self):
        """Git tools fail gracefully when no project open"""
        tool = GitStatusTool()
        result = await tool.execute()
        assert result.error is not None
        assert "No project" in result.error or "no project" in result.error.lower()
