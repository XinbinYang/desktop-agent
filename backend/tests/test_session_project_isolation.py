"""Per-session project isolation.

Core guarantee behind parallel multi-project sessions: a session's project
binding travels with its own asyncio task (a ContextVar), so opening another
project in the UI (the global ProjectManager) cannot redirect an
already-running session to the wrong directory.
"""
import asyncio

import pytest

from app.coding_runs import (
    RunContext,
    create_coding_run,
    effective_project_path,
    reset_run_context,
    reset_session_project,
    set_run_context,
    set_session_project,
)
from app.agent import AgentSession, _session_record_matches, _sessions
from app.project_manager import ProjectManager


def test_effective_path_falls_back_to_global_when_unbound(isolate_projects, tmp_path):
    proj = tmp_path / "global_proj"
    proj.mkdir()
    ProjectManager._current_project = {"path": str(proj), "name": "global_proj"}
    assert effective_project_path() == str(proj)


def test_session_binding_overrides_global(isolate_projects, tmp_path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    # UI/global points at B ...
    ProjectManager._current_project = {"path": str(b), "name": "B"}
    # ... but this session is bound to A.
    token = set_session_project(str(a))
    try:
        assert effective_project_path() == str(a)
    finally:
        reset_session_project(token)
    # After teardown the binding is gone, global is visible again.
    assert effective_project_path() == str(b)


def test_live_session_record_match_uses_bound_project(isolate_projects, tmp_path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    session = AgentSession(model_id="gpt-4o", session_id="live-project-match", agent_type="coding")
    session.project_path = str(a)
    _sessions[session.session_id] = session
    ProjectManager._current_project = {"path": str(b), "name": "B"}
    try:
        assert _session_record_matches(session.session_id, agent_type="coding", project_path=str(a))
        assert not _session_record_matches(session.session_id, agent_type="coding", project_path=str(b))
    finally:
        _sessions.pop(session.session_id, None)


def test_run_context_takes_priority(isolate_projects, tmp_path):
    a = tmp_path / "A"
    a.mkdir()
    ProjectManager._current_project = {"path": str(tmp_path / "B"), "name": "B"}
    sp_token = set_session_project(str(tmp_path / "C"))
    rc_token = set_run_context(
        RunContext(run_id="r1", session_id="s1", project_path=str(a), mode="current_dir")
    )
    try:
        assert effective_project_path() == str(a)
    finally:
        reset_run_context(rc_token)
        reset_session_project(sp_token)


@pytest.mark.asyncio
async def test_concurrent_sessions_do_not_clobber(isolate_projects, tmp_path):
    """Two sessions bound to different projects run concurrently; each must
    keep seeing its own project even while the other runs and even when the
    global current project is flipped mid-flight."""
    a = tmp_path / "proj_a"
    b = tmp_path / "proj_b"
    a.mkdir()
    b.mkdir()
    ProjectManager._current_project = {"path": str(tmp_path / "elsewhere"), "name": "x"}

    async def session_task(project: str, flip_to: str) -> list[str]:
        token = set_session_project(project)
        seen = []
        try:
            seen.append(effective_project_path())
            await asyncio.sleep(0)  # yield: let the other task run + flip global
            # Another project opened in the UI while we were "thinking".
            ProjectManager._current_project = {"path": flip_to, "name": "flip"}
            await asyncio.sleep(0)
            seen.append(effective_project_path())
        finally:
            reset_session_project(token)
        return seen

    # asyncio.create_task copies the current context — mirrors SessionRuntime.
    ta = asyncio.create_task(session_task(str(a), str(b)))
    tb = asyncio.create_task(session_task(str(b), str(a)))
    seen_a, seen_b = await asyncio.gather(ta, tb)

    assert seen_a == [str(a), str(a)]
    assert seen_b == [str(b), str(b)]


def test_create_coding_run_uses_passed_project_not_global(isolate_projects, tmp_path):
    bound = tmp_path / "bound_proj"
    other = tmp_path / "global_proj"
    bound.mkdir()
    other.mkdir()
    # Global UI project is a different directory.
    ProjectManager._current_project = {"path": str(other), "name": "global_proj"}

    ctx = create_coding_run(
        session_id="s-iso",
        run_id="run-iso-1",
        prompt="noop",
        project_path=str(bound),
    )
    assert ctx is not None
    assert ctx.project_path == str(bound.resolve())
    # No git repo in the temp dir → stays in current_dir mode on the bound path.
    assert ctx.active_path == str(bound.resolve())
