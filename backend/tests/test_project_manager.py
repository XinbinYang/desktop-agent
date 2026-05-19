import pytest
import json
import subprocess
from pathlib import Path
from app.project_manager import ProjectManager, RECENT_FILE


@pytest.fixture(autouse=True)
def reset_project_manager():
    """Reset ProjectManager state before each test"""
    ProjectManager._current_project = None
    # Clear recent file
    if RECENT_FILE.exists():
        RECENT_FILE.unlink()
    yield
    ProjectManager._current_project = None
    if RECENT_FILE.exists():
        RECENT_FILE.unlink()


class TestProjectManager:
    def test_create_project_empty(self, temp_dir):
        """Create empty project template"""
        project = ProjectManager.create_project(str(temp_dir), "empty-project", "empty")
        assert project["name"] == "empty-project"
        assert project["path"] == str(temp_dir / "empty-project")
        assert (temp_dir / "empty-project" / "README.md").exists()
        assert (temp_dir / "empty-project" / ".gitignore").exists()

    def test_create_project_python(self, temp_dir):
        """Create Python project template"""
        project = ProjectManager.create_project(str(temp_dir), "py-project", "python")
        assert project["name"] == "py-project"
        path = Path(project["path"])
        assert (path / "src").is_dir()
        assert (path / "tests").is_dir()
        assert (path / "requirements.txt").exists()
        assert (path / "main.py").exists()

    def test_create_project_react(self, temp_dir):
        """Create React project template"""
        project = ProjectManager.create_project(str(temp_dir), "react-app", "react")
        assert project["name"] == "react-app"
        path = Path(project["path"])
        assert (path / "src").is_dir()
        assert (path / "package.json").exists()
        assert (path / "vite.config.js").exists()

    def test_create_project_nodejs(self, temp_dir):
        """Create Node.js project template"""
        project = ProjectManager.create_project(str(temp_dir), "node-app", "nodejs")
        assert project["name"] == "node-app"
        path = Path(project["path"])
        assert (path / "package.json").exists()
        assert (path / "index.js").exists()

    def test_create_duplicate_name_raises(self, temp_dir):
        """Creating project with duplicate name raises ValueError"""
        ProjectManager.create_project(str(temp_dir), "dup", "empty")
        with pytest.raises(ValueError, match="目录已存在"):
            ProjectManager.create_project(str(temp_dir), "dup", "empty")

    def test_create_project_rejects_path_traversal_name(self, temp_dir):
        """Project names cannot escape the selected parent directory"""
        with pytest.raises(ValueError):
            ProjectManager.create_project(str(temp_dir), "..\\outside", "empty")

    def test_open_project(self, temp_dir):
        """Open an existing directory as project"""
        test_path = temp_dir / "existing"
        test_path.mkdir()
        (test_path / "file.txt").write_text("hello")
        project = ProjectManager.open_project(str(test_path))
        assert project["name"] == "existing"
        assert project["path"] == str(test_path)

    def test_open_nonexistent_raises(self):
        """Opening nonexistent path raises ValueError"""
        with pytest.raises(ValueError, match="路径不存在"):
            ProjectManager.open_project("/nonexistent/path/12345")

    def test_open_file_raises(self, temp_dir):
        """Opening a file (not dir) raises ValueError"""
        f = temp_dir / "notadir.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="路径不是目录"):
            ProjectManager.open_project(str(f))

    def test_close_project(self, temp_dir):
        """Close current project clears state"""
        ProjectManager.open_project(str(temp_dir))
        assert ProjectManager.get_current() is not None
        ProjectManager.close_project()
        assert ProjectManager.get_current() is None

    def test_get_current_no_project(self):
        """get_current returns None when no project open"""
        assert ProjectManager.get_current() is None

    def test_list_recent(self, temp_dir):
        """Recent projects are persisted and ordered"""
        p1 = temp_dir / "proj1"
        p2 = temp_dir / "proj2"
        p1.mkdir()
        p2.mkdir()
        ProjectManager.open_project(str(p1))
        ProjectManager.open_project(str(p2))
        recent = ProjectManager.list_recent()
        assert len(recent) == 2
        assert recent[0]["name"] == "proj2"  # most recent first
        assert recent[1]["name"] == "proj1"

    def test_recent_deduplication(self, temp_dir):
        """Re-opening same project moves it to top without duplication"""
        p = temp_dir / "proj"
        p.mkdir()
        ProjectManager.open_project(str(p))
        ProjectManager.open_project(str(p))
        recent = ProjectManager.list_recent()
        assert len(recent) == 1

    def test_git_subdirectory_opens_as_repo_root(self, temp_dir):
        """Opening a directory inside a Git repo uses the repo root as the project."""
        if subprocess.run(["git", "--version"], capture_output=True, text=True).returncode != 0:
            pytest.skip("git is not available")
        repo = temp_dir / "repo"
        subdir = repo / "nested"
        subdir.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, text=True, check=True)

        project = ProjectManager.open_project(str(subdir))

        assert project["path"] == str(repo.resolve())
        recent = ProjectManager.list_recent()
        assert len(recent) == 1
        assert recent[0]["path"] == str(repo.resolve())

    def test_open_project_without_touching_recent_keeps_order(self, temp_dir):
        """UI focus sync can switch current project without reordering recent projects."""
        p1 = temp_dir / "proj1"
        p2 = temp_dir / "proj2"
        p1.mkdir()
        p2.mkdir()
        ProjectManager.open_project(str(p1))
        ProjectManager.open_project(str(p2))

        project = ProjectManager.open_project(str(p1), touch_recent=False)

        assert project["path"] == str(p1.resolve())
        assert ProjectManager.get_current()["path"] == str(p1.resolve())
        assert [item["path"] for item in ProjectManager.list_recent()] == [
            str(p2.resolve()),
            str(p1.resolve()),
        ]

    def test_get_tree_empty_no_project(self):
        """get_tree returns empty when no project open"""
        assert ProjectManager.get_tree() == []

    def test_get_tree(self, temp_dir):
        """get_tree returns directory structure"""
        root = temp_dir / "treeproj"
        root.mkdir()
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("x")
        (root / "README.md").write_text("x")
        ProjectManager.open_project(str(root))
        nodes = ProjectManager.get_tree()
        names = [n["name"] for n in nodes]
        assert "README.md" in names
        assert "src" in names
        # src dir should have children
        src_node = next(n for n in nodes if n["name"] == "src")
        assert src_node["type"] == "dir"
        assert len(src_node.get("children", [])) > 0

    def test_get_tree_excludes(self, temp_dir):
        """get_tree excludes node_modules, .git, etc"""
        root = temp_dir / "excludeproj"
        root.mkdir()
        (root / "node_modules").mkdir()
        (root / "node_modules" / "x").mkdir()
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("x")
        ProjectManager.open_project(str(root))
        nodes = ProjectManager.get_tree()
        names = [n["name"] for n in nodes]
        assert "node_modules" not in names
        assert "src" in names

    def test_get_tree_path_escape_blocked(self, temp_dir):
        """get_tree blocks path traversal outside project"""
        root = temp_dir / "safe"
        root.mkdir()
        ProjectManager.open_project(str(root))
        # Try to access parent directory via relative path
        assert ProjectManager.get_tree("../") == []
