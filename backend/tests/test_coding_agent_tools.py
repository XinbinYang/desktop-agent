import subprocess

import pytest


@pytest.mark.asyncio
async def test_code_search_finds_context(tmp_path, isolate_projects):
    from app.project_manager import ProjectManager
    from app.tools.coding_tool import CodeSearchTool

    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def alpha():\n    return 'needle'\n", encoding="utf-8")
    ProjectManager.open_project(str(tmp_path))

    result = await CodeSearchTool().execute("needle", path="src", context_lines=1, max_results=5)

    assert not result.error
    assert "needle" in result.output
    assert "src/app.py" in result.output.replace("\\", "/")


@pytest.mark.asyncio
async def test_file_outline_python_symbols(tmp_path, isolate_projects):
    from app.project_manager import ProjectManager
    from app.tools.coding_tool import FileOutlineTool

    path = tmp_path / "module.py"
    path.write_text("import os\n\nclass Service:\n    pass\n\ndef run():\n    return os.name\n", encoding="utf-8")
    ProjectManager.open_project(str(tmp_path))

    result = await FileOutlineTool().execute("module.py")

    assert not result.error
    assert '"name": "Service"' in result.output
    assert '"name": "run"' in result.output


@pytest.mark.asyncio
async def test_file_patch_exact_replacement_emits_diff(tmp_path, isolate_projects):
    from app.project_manager import ProjectManager
    from app.tools.coding_tool import FilePatchTool

    path = tmp_path / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    ProjectManager.open_project(str(tmp_path))

    result = await FilePatchTool().execute("module.py", "value = 1", "value = 2")

    assert not result.error
    assert path.read_text(encoding="utf-8") == "value = 2\n"
    edit = result.metadata["file_edit"]
    assert edit["operation"] == "modify"
    assert "+value = 2" in edit["unified_diff"]


@pytest.mark.asyncio
async def test_file_patch_blocks_multiple_matches(tmp_path, isolate_projects):
    from app.project_manager import ProjectManager
    from app.tools.coding_tool import FilePatchTool

    path = tmp_path / "module.py"
    path.write_text("x = 1\nx = 1\n", encoding="utf-8")
    ProjectManager.open_project(str(tmp_path))

    result = await FilePatchTool().execute("module.py", "x = 1", "x = 2")

    assert result.error
    assert "appears 2 times" in result.error.lower()


@pytest.mark.asyncio
async def test_verify_project_command_override(tmp_path, isolate_projects):
    from app.project_manager import ProjectManager
    from app.tools.coding_tool import VerifyProjectTool

    ProjectManager.open_project(str(tmp_path))
    result = await VerifyProjectTool().execute(command_override="python -c \"print('verify-ok')\"")

    assert not result.error
    assert result.metadata["verification"]["passed"] is True
    assert result.metadata["verification"]["green_level"] == "targeted_tests"
    assert result.metadata["verification"]["scope"] == "auto"
    assert "verify-ok" in result.output


def test_guardrails_block_dangerous_shell():
    from app.guardrails import evaluate_pre_tool
    from app.coding_runs import RunContext

    decision = evaluate_pre_tool("shell_execute", {"command": "git reset --hard"})

    assert decision["decision"] == "blocked"
    assert decision["requires_approval"] is True

    verify_decision = evaluate_pre_tool("verify_project", {"command_override": "git clean -fd"})
    assert verify_decision["decision"] == "blocked"

    portable_decision = evaluate_pre_tool("shell_execute", {"command": "pytest | tail -20"})
    assert portable_decision["decision"] == "blocked"

    ctx = RunContext(
        run_id="r1",
        session_id="s1",
        project_path="C:/repo",
        mode="current_dir",
        worktree_path="",
        base_branch="",
        base_commit="",
        prompt="fix failing tests for volume_price_tracker",
    )
    test_edit = evaluate_pre_tool("file_patch", {"path": "tests/test_example.py", "new_text": "x"}, ctx=ctx)
    assert test_edit["decision"] == "blocked"

    ctx.prompt = "add tests for the parser"
    allowed_test_edit = evaluate_pre_tool("file_patch", {"path": "tests/test_example.py", "new_text": "x"}, ctx=ctx)
    assert allowed_test_edit["decision"] == "allowed"


def test_worker_profiles_expose_coding_kernel_tools():
    from app.worker import WORKER_PROFILES

    assert "architect" in WORKER_PROFILES
    assert "editor" in WORKER_PROFILES
    assert "verifier" in WORKER_PROFILES
    assert "reviewer" in WORKER_PROFILES
    assert "file_patch" in WORKER_PROFILES["editor"].tools
    assert "file_write" not in WORKER_PROFILES["architect"].tools


def test_coding_run_worktree_lifecycle(tmp_path, isolate_projects, monkeypatch):
    from app import coding_runs
    from app.coding_runs import create_coding_run, discard_run, get_run
    from app.project_manager import ProjectManager

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.local"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    monkeypatch.setattr(coding_runs, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(coding_runs, "runtime_dir", lambda *parts: tmp_path.joinpath("runtime", *parts))
    ProjectManager.open_project(str(tmp_path))

    ctx = create_coding_run("s1", "run-test", "change readme")

    assert ctx is not None
    assert ctx.mode == "worktree"
    assert get_run("run-test") is not None
    assert discard_run("run-test")["status"] == "discarded"
