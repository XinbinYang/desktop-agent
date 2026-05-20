import threading

import pytest

from app.collaboration import manager
from app.collaboration.models import ResultPacket, TaskPacket
from app.collaboration.parser import parse_coding_mention


@pytest.fixture()
def isolated_collaboration_db(tmp_path, monkeypatch):
    conn = getattr(manager._conn_local, "conn", None)
    if conn is not None:
        conn.close()
    monkeypatch.setattr(manager, "DB_PATH", tmp_path / "collaboration.db")
    monkeypatch.setattr(manager, "_conn_local", threading.local())
    yield
    conn = getattr(manager._conn_local, "conn", None)
    if conn is not None:
        conn.close()


def test_parse_coding_mention_modes():
    consult = parse_coding_mention("@coding agent inspect this error")
    assert consult is not None
    assert consult.task == "inspect this error"
    assert consult.mode == "consult"

    execute = parse_coding_mention("@coding agent fix this bug")
    assert execute is not None
    assert execute.task == "fix this bug"
    assert execute.mode == "execute"

    handoff = parse_coding_mention("@coding agent")
    assert handoff is not None
    assert handoff.task == ""
    assert handoff.mode == "handoff"


def test_collaboration_run_task_lifecycle(isolated_collaboration_db):
    run = manager.create_run(session_id="s1", goal="diagnose failing tests", mode="consult")
    task = manager.add_task(
        run.run_id,
        TaskPacket(goal="diagnose failing tests", mode="consult", acceptance_criteria=["explain cause"]),
    )

    running = manager.update_task(task.task_id, status="running")
    assert running is not None
    assert running.status == "running"

    result = ResultPacket(status="pass", summary="The failure is caused by stale mock data.")
    completed = manager.update_task(task.task_id, status="completed", result=result)
    assert completed is not None
    assert completed.result is not None
    assert completed.result.summary.startswith("The failure")

    finished = manager.complete_run(run.run_id, "completed", "done")
    assert finished is not None
    assert finished.status == "completed"

    event_types = [event.type for event in manager.list_events(run.run_id)]
    assert event_types == [
        "collaboration_run_created",
        "collaboration_task_update",
        "collaboration_task_update",
        "collaboration_task_update",
        "collaboration_run_completed",
    ]


def test_cancel_run_marks_pending_tasks_cancelled(isolated_collaboration_db):
    run = manager.create_run(session_id="s1", goal="fix styling", mode="execute")
    task = manager.add_task(run.run_id, TaskPacket(goal="fix styling", mode="execute"))

    cancelled = manager.cancel_run(run.run_id)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    stored_task = manager.get_task(task.task_id)
    assert stored_task is not None
    assert stored_task.status == "cancelled"


def test_collaboration_rest_run_lifecycle(isolated_collaboration_db, client):
    created = client.post(
        "/api/collaboration/runs",
        json={"session_id": "s1", "goal": "inspect failure", "mode": "consult"},
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["run_id"]

    fetched = client.get(f"/api/collaboration/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["run"]["goal"] == "inspect failure"

    cancelled = client.post(f"/api/collaboration/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["run"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_personal_explicit_coding_mention_triggers_collaboration(monkeypatch, isolated_collaboration_db, isolate_projects, tmp_path):
    from app import agent as agent_module
    from app.agent import AgentSession
    from app.config import get_model_for_agent
    from app.project_manager import ProjectManager

    project = tmp_path / "opened-project"
    project.mkdir()
    ProjectManager._current_project = {"path": str(project), "name": "opened-project"}
    seen = {}

    async def fake_consult_worker(packet, *, run_id, task_id, project_path=""):
        seen["project_path"] = project_path
        return ResultPacket(status="pass", summary="Mock diagnosis.\nACCEPTANCE: PASS"), []

    monkeypatch.setattr(agent_module, "run_consult_worker", fake_consult_worker)
    session = AgentSession(
        model_id=get_model_for_agent("personal"),
        session_id="test_collab_session",
        agent_type="personal",
    )
    session._save = lambda: None  # type: ignore[method-assign]

    events = [event async for event in session.run("@coding agent inspect this error")]

    assert any(event["type"] == "collaboration_run_created" for event in events)
    assert any(event["type"] == "collaboration_task_update" for event in events)
    assert any(event["type"] == "collaboration_run_completed" for event in events)
    assert any(
        event["type"] == "content" and "Mock diagnosis" in event["data"].get("text", "")
        for event in events
    )
    assert seen["project_path"] == str(project)


@pytest.mark.asyncio
async def test_personal_explicit_coding_mention_without_project_blocks(monkeypatch, isolated_collaboration_db, isolate_projects):
    from app import agent as agent_module
    from app.agent import AgentSession
    from app.config import get_model_for_agent

    async def fake_consult_worker(*args, **kwargs):
        raise AssertionError("Coding worker should not run without a project path")

    monkeypatch.setattr(agent_module, "run_consult_worker", fake_consult_worker)
    session = AgentSession(
        model_id=get_model_for_agent("personal"),
        session_id="test_collab_no_project",
        agent_type="personal",
    )
    session._save = lambda: None  # type: ignore[method-assign]

    events = [event async for event in session.run("@coding agent inspect this error")]

    assert not any(event["type"] == "collaboration_run_created" for event in events)
    assert any(
        event["type"] == "content" and "需要先打开一个项目" in event["data"].get("text", "")
        for event in events
    )
