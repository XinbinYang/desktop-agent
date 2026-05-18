import json
import subprocess
import uuid

import pytest
from starlette.websockets import WebSocketDisconnect


def receive_until(ws, expected_type: str, limit: int = 30):
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg.get("type"))
        if msg.get("type") == expected_type:
            return msg
    raise AssertionError(f"Did not receive {expected_type}; saw {seen}")


class TestAPIRoutes:
    def test_get_models(self, client):
        """GET /api/models returns model list"""
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert "default" in data
        assert isinstance(data["models"], list)

    def test_get_tools(self, client):
        """GET /api/tools returns tool list"""
        response = client.get("/api/tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert len(data["tools"]) > 0
        assert "name" in data["tools"][0]
        assert "description" in data["tools"][0]

    def test_get_roles(self, client):
        """GET /api/roles returns builtin role list"""
        response = client.get("/api/roles")
        assert response.status_code == 200
        data = response.json()
        assert "roles" in data
        assert len(data["roles"]) >= 4
        role_ids = [r["id"] for r in data["roles"]]
        assert "desktop-agent" in role_ids
        assert "general-assistant" in role_ids
        assert "quant-analyst" in role_ids
        assert "code-expert" in role_ids
        for r in data["roles"]:
            assert "id" in r
            assert "name" in r
            assert "description" in r
            assert "is_builtin" in r

    def test_chat_endpoint(self, client, mock_litellm):
        """POST /api/chat returns events"""
        response = client.post("/api/chat", json={
            "message": "hello",
            "session_id": "test_session",
            "model_id": "gpt-4o"
        })
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_clear_session(self, client):
        """POST /api/sessions/{id}/clear returns ok"""
        response = client.post("/api/sessions/test_session/clear")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_session_context_and_checkpoints_endpoints(self, client, monkeypatch, tmp_path):
        import app.agent as agent_module
        from app.agent import AgentSession

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()
        session = AgentSession(model_id="gpt-4o", session_id="ctx_session")
        session.messages.append({"role": "user", "content": "checkpoint prompt"})
        session.messages.append({"role": "assistant", "content": "answer"})
        agent_module._sessions["ctx_session"] = session

        context = client.get("/api/sessions/ctx_session/context")
        checkpoints = client.get("/api/sessions/ctx_session/checkpoints")

        assert context.status_code == 200
        assert context.json()["model_context"] > 0
        assert checkpoints.status_code == 200
        assert checkpoints.json()["checkpoints"][0]["preview"] == "checkpoint prompt"

    def test_session_rewind_endpoint_trims_history(self, client, monkeypatch, tmp_path):
        import app.agent as agent_module
        from app.agent import AgentSession

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()
        session = AgentSession(model_id="gpt-4o", session_id="rewind_session")
        session.messages.append({"role": "user", "content": "target"})
        session.messages.append({"role": "assistant", "content": "old answer"})
        session.messages.append({"role": "user", "content": "later"})
        checkpoint_id = session.build_checkpoints()[0]["id"]
        agent_module._sessions["rewind_session"] = session

        response = client.post("/api/sessions/rewind_session/rewind", json={
            "checkpoint_id": checkpoint_id,
            "retry": True,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["checkpoint_id"] == checkpoint_id
        assert [m.get("content") for m in data["snapshot"]["messages"] if m.get("role") != "system"] == ["target"]

    def test_session_compact_endpoint_returns_snapshot(self, client, monkeypatch, tmp_path):
        import app.agent as agent_module
        from app.agent import AgentSession

        async def fake_summary(*args, **kwargs):
            return {"choices": [{"message": {"content": "Compact summary"}}]}

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()
        session = AgentSession(model_id="gpt-4o", session_id="compact_session")
        for i in range(6):
            session.messages.append({"role": "user", "content": f"user {i}"})
            session.messages.append({"role": "assistant", "content": f"assistant {i}"})
        session.router.chat_completion_non_stream = fake_summary
        agent_module._sessions["compact_session"] = session

        response = client.post("/api/sessions/compact_session/compact", json={"force": True})

        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] is False
        assert data["summary"] == "Compact summary"
        assert data["snapshot"]["compaction_summary"] == "Compact summary"

    def test_resolve_personal_session_returns_single_primary(self, client, monkeypatch, tmp_path):
        import app.agent as agent_module

        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(agent_module, "SESSIONS_DIR", sessions_dir)
        monkeypatch.setattr(agent_module, "SESSION_REGISTRY_PATH", tmp_path / "session_registry.json")
        agent_module._sessions.clear()

        first = client.post("/api/sessions/resolve", json={
            "agent_type": "personal",
            "policy": "canonical",
        })
        second = client.post("/api/sessions/resolve", json={
            "agent_type": "personal",
            "policy": "canonical",
        })

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["session_id"] == "session_personal_main"
        assert second.json()["session_id"] == "session_personal_main"
        assert first.json()["is_primary"] is True
        assert second.json()["created"] is False

        listed = client.get("/api/sessions").json()["sessions"]
        assert listed[0]["id"] == "session_personal_main"
        assert listed[0]["is_primary"] is True

    def test_resolve_coding_session_uses_last_or_create(self, client, monkeypatch, tmp_path):
        import app.agent as agent_module

        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(agent_module, "SESSIONS_DIR", sessions_dir)
        monkeypatch.setattr(agent_module, "SESSION_REGISTRY_PATH", tmp_path / "session_registry.json")
        agent_module._sessions.clear()

        first = client.post("/api/sessions/resolve", json={
            "agent_type": "coding",
            "policy": "last_or_create",
        })
        second = client.post("/api/sessions/resolve", json={
            "agent_type": "coding",
            "policy": "last_or_create",
        })
        third = client.post("/api/sessions/resolve", json={
            "agent_type": "coding",
            "policy": "new",
        })

        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 200
        assert first.json()["agent_type"] == "coding"
        assert first.json()["session_id"] == second.json()["session_id"]
        assert third.json()["session_id"] != first.json()["session_id"]
        assert third.json()["created"] is True

    def test_upload_image(self, client):
        """POST /api/upload-image accepts file upload"""
        response = client.post(
            "/api/upload-image",
            files={"file": ("test.txt", b"hello", "text/plain")}
        )
        assert response.status_code == 200
        data = response.json()
        assert "base64" in data
        assert data["filename"] == "test.txt"


class TestLocalAuth:
    def test_api_requires_token_when_enabled(self, client, monkeypatch):
        monkeypatch.setenv("DESKTOP_AGENT_AUTH_TOKEN", "test-token")

        response = client.get("/api/models")

        assert response.status_code == 401

    def test_api_accepts_valid_token_header(self, client, monkeypatch):
        monkeypatch.setenv("DESKTOP_AGENT_AUTH_TOKEN", "test-token")

        response = client.get(
            "/api/models",
            headers={"X-Desktop-Agent-Token": "test-token"},
        )

        assert response.status_code == 200

    def test_cors_preflight_is_not_blocked_by_auth(self, client, monkeypatch):
        monkeypatch.setenv("DESKTOP_AGENT_AUTH_TOKEN", "test-token")

        response = client.options(
            "/api/models",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Desktop-Agent-Token",
            },
        )

        assert response.status_code in {200, 204}

    def test_websocket_requires_token_when_enabled(self, client, monkeypatch):
        monkeypatch.setenv("DESKTOP_AGENT_AUTH_TOKEN", "test-token")

        with client.websocket_connect("/ws/auth_missing") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 1008

    def test_websocket_accepts_valid_query_token(self, client, monkeypatch):
        monkeypatch.setenv("DESKTOP_AGENT_AUTH_TOKEN", "test-token")

        with client.websocket_connect("/ws/auth_ok?token=test-token") as ws:
            ws.send_json({"type": "clear"})
            msg = receive_until(ws, "cleared")

        assert msg["type"] == "cleared"


class TestWebSocket:
    @pytest.mark.asyncio
    async def test_websocket_connect_and_chat(self, async_client, mock_litellm):
        """WebSocket handshake and basic message exchange"""
        from app.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        with client.websocket_connect("/ws/test_ws") as ws:
            ws.send_json({
                "type": "chat",
                "text": "hi",
                "model_id": "gpt-4o"
            })
            msgs = []
            for _ in range(30):
                msg = ws.receive_json()
                msgs.append(msg)
                if msg.get("type") == "done":
                    break

            types = [m["type"] for m in msgs]
            assert "skills_matched" in types
            assert "status" in types
            assert "done" in types

    def test_websocket_plan_chat_emits_plan_draft(self, client):
        """Plan mode: LLM calls plan_write_draft → frontend receives plan_draft."""
        from unittest.mock import patch
        from app.agent import PLAN_CONTINUE_MARKER
        from .conftest import _make_stream_mock

        mock_response = {
            "choices": [{
                "message": {
                    "content": "Here is the plan.",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "plan_write_draft",
                            "arguments": json.dumps({
                                "goal": "Test plan",
                                "assumptions": [],
                                "research_notes": "none",
                                "steps": [{"id": "s1", "title": "Step 1", "details": "", "depends_on": []}],
                                "todos": [{"id": "t1", "title": "Todo 1", "acceptance_criteria": "works", "depends_on": []}],
                                "risks": [],
                                "verification": [],
                                "markdown_body": "# Test Plan\n\nTest content.",
                            })
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            with client.websocket_connect(f"/ws/test_plan_ws_{uuid.uuid4().hex}") as ws:
                ws.send_json({
                    "type": "chat",
                    "text": "plan this",
                    "model_id": "gpt-4o",
                    "chat_mode": "plan",
                    "thinking_intensity": "medium",
                })
                types = []
                for _ in range(35):
                    msg = ws.receive_json()
                    types.append(msg["type"])
                    if msg.get("type") == "done":
                        break
                assert "plan_draft" in types
                assert "plan_status" in types
                assert "done" in types

    def test_websocket_chat_without_mode_uses_session_plan_mode(self, client):
        """If the UI already switched to Plan, a chat without chat_mode still runs as Plan."""
        from unittest.mock import patch
        from .conftest import _make_stream_mock

        mock_response = {
            "choices": [{
                "message": {
                    "content": "我需要先确认开放范围。",
                    "role": "assistant",
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            with client.websocket_connect(f"/ws/test_plan_default_ws_{uuid.uuid4().hex}") as ws:
                ws.send_json({"type": "set_chat_mode", "chat_mode": "plan"})
                receive_until(ws, "plan_status")

                ws.send_json({
                    "type": "chat",
                    "text": "plan this without explicit mode",
                    "model_id": "gpt-4o",
                    "thinking_intensity": "medium",
                })
                plan_phases = []
                for _ in range(30):
                    msg = ws.receive_json()
                    if msg.get("type") == "plan_status":
                        plan_phases.append(msg.get("data", {}).get("phase"))
                    if msg.get("type") == "done":
                        break

                assert "clarifying" in plan_phases

    def test_session_connections_endpoint_counts_active_websocket(self, client):
        sid = f"test_active_ws_{uuid.uuid4().hex}"
        with client.websocket_connect(f"/ws/{sid}") as ws:
            snapshot = client.get("/api/sessions/connections").json()
            assert snapshot["total"] >= 1
            assert any(item["session_id"] == sid and item["connections"] == 1 for item in snapshot["connections"])
            ws.close()

    def test_delete_session_closes_active_websocket(self, client):
        sid = f"test_delete_ws_{uuid.uuid4().hex}"
        with client.websocket_connect(f"/ws/{sid}") as ws:
            response = client.delete(f"/api/sessions/{sid}")
            assert response.status_code == 200
            assert response.json()["closed_connections"] == 1
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4004

    def test_websocket_submit_plan_decisions_continues_to_draft(self, client):
        from unittest.mock import patch
        from .conftest import _make_stream_mock

        ask_response = {
            "choices": [{
                "message": {
                    "content": "I need one decision.",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_q",
                        "function": {
                            "name": "plan_ask_questions",
                            "arguments": json.dumps({
                                "questions": [{
                                    "id": "scope",
                                    "prompt": "What scope?",
                                    "allow_multiple": False,
                                    "options": [
                                        {"id": "small", "label": "Small"},
                                        {"id": "large", "label": "Large"},
                                    ],
                                }],
                            }),
                        },
                    }],
                },
            }],
        }
        draft_response = {
            "choices": [{
                "message": {
                    "content": "Creating the plan.",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_d",
                        "function": {
                            "name": "plan_write_draft",
                            "arguments": json.dumps({
                                "goal": "Test decision plan",
                                "assumptions": ["User chose small plus Other note"],
                                "research_notes": "none",
                                "steps": [{"id": "s1", "title": "Step 1", "details": "", "depends_on": []}],
                                "todos": [{"id": "t1", "title": "Todo 1", "acceptance_criteria": "works", "depends_on": []}],
                                "risks": [],
                                "verification": [],
                                "markdown_body": "# Test decision plan\n\nTest content.",
                            }),
                        },
                    }],
                },
            }],
        }
        streams = [_make_stream_mock(ask_response), _make_stream_mock(draft_response)]

        async def stream_sequence(*args, **kwargs):
            stream = streams.pop(0)
            async for event in stream(*args, **kwargs):
                yield event

        with patch("app.agent.ModelRouter.chat_completion_stream", stream_sequence):
            with client.websocket_connect(f"/ws/test_plan_submit_ws_{uuid.uuid4().hex}") as ws:
                ws.send_json({
                    "type": "chat",
                    "text": "plan this with a question",
                    "model_id": "gpt-4o",
                    "chat_mode": "plan",
                })
                first_types = []
                for _ in range(30):
                    msg = ws.receive_json()
                    first_types.append(msg["type"])
                    if msg.get("type") == "done":
                        break
                assert "plan_questions" in first_types

                ws.send_json({
                    "type": "submit_plan_decisions",
                    "answers": [{
                        "question_id": "scope",
                        "selected": ["small"],
                        "other_text": "Keep an escape hatch",
                        "skipped": False,
                    }],
                })
                second_types = []
                for _ in range(40):
                    msg = ws.receive_json()
                    second_types.append(msg["type"])
                    if msg.get("type") == "done":
                        break
                assert "plan_status" in second_types
                assert "plan_draft" in second_types

    def test_websocket_plan_approve_then_build(self, client):
        from unittest.mock import patch
        from app.agent import PLAN_CONTINUE_MARKER
        from .conftest import _make_stream_mock

        plan_response = {
            "choices": [{
                "message": {
                    "content": "Here is the plan.",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "plan_write_draft",
                            "arguments": json.dumps({
                                "goal": "Test plan",
                                "assumptions": [],
                                "research_notes": "none",
                                "steps": [{"id": "s1", "title": "Step 1", "details": "", "depends_on": []}],
                                "todos": [{"id": "t1", "title": "Todo 1", "acceptance_criteria": "works", "depends_on": []}],
                                "risks": [],
                                "verification": [],
                                "markdown_body": "# Test Plan\n\nTest content.",
                            })
                        }
                    }]
                }
            }]
        }
        # Second LLM call (build_plan → PLAN_CONTINUE_MARKER): simple text response
        build_response = {
            "choices": [{
                "message": {
                    "content": "Task completed.",
                    "role": "assistant",
                    "tool_calls": None
                }
            }]
        }

        streams = [_make_stream_mock(plan_response), _make_stream_mock(build_response)]

        async def stream_sequence(*args, **kwargs):
            stream = streams.pop(0)
            async for event in stream(*args, **kwargs):
                yield event

        with patch("app.agent.ModelRouter.chat_completion_stream", stream_sequence):
            with client.websocket_connect(f"/ws/test_plan_build_ws_{uuid.uuid4().hex}") as ws:
                ws.send_json({
                    "type": "chat",
                    "text": "plan this work",
                    "model_id": "gpt-4o",
                    "chat_mode": "plan",
                })
                for _ in range(25):
                    msg = ws.receive_json()
                    if msg.get("type") == "done":
                        break

                # approve_plan sends 2 events: plan_approved_waiting_build + plan_status
                ws.send_json({"type": "approve_plan"})
                msg = ws.receive_json()
                assert msg["type"] == "plan_approved_waiting_build"
                msg = ws.receive_json()
                assert msg["type"] == "plan_status"

                ws.send_json({"type": "build_plan"})
                build_types = []
                for _ in range(20):
                    msg = ws.receive_json()
                    build_types.append(msg["type"])
                    if msg.get("type") == "done":
                        break
                assert "build_started" in build_types
                assert "done" in build_types

    def test_websocket_build_recovers_from_plan_snapshot(self, client):
        from unittest.mock import patch
        from .conftest import _make_stream_mock

        build_response = {
            "choices": [{
                "message": {
                    "content": "Task completed.",
                    "role": "assistant",
                    "tool_calls": None,
                }
            }]
        }
        plan_state = {
            "mode": "plan",
            "phase": "awaiting_approval",
            "goal": "Snapshot plan",
            "draft": "# Snapshot plan",
            "structured_plan": None,
            "questions": [],
            "todos": [{"id": "t1", "title": "First todo", "status": "pending"}],
            "decisions": {},
            "decision_notes": {},
            "approved": False,
            "pending_clarification": False,
            "plan_file_path": None,
            "research_notes": "",
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(build_response)):
            with client.websocket_connect(f"/ws/test_plan_snapshot_build_ws_{uuid.uuid4().hex}") as ws:
                ws.send_json({"type": "build_plan", "plan_state": plan_state})
                build_types = []
                for _ in range(20):
                    msg = ws.receive_json()
                    build_types.append(msg["type"])
                    if msg.get("type") == "done":
                        break
                assert "build_started" in build_types
                assert "error" not in build_types

    def test_websocket_clear(self, client):
        """WebSocket clear message type"""
        with client.websocket_connect("/ws/test_clear") as ws:
            ws.send_json({"type": "clear"})
            msg = receive_until(ws, "cleared")
            assert msg["type"] == "cleared"

    def test_websocket_tool_direct(self, client):
        """WebSocket tool_direct message type"""
        with client.websocket_connect("/ws/test_tool") as ws:
            ws.send_json({
                "type": "tool_direct",
                "tool_name": "get_screen_size",
                "args": {}
            })
            msg = receive_until(ws, "tool_result")
            assert msg["type"] == "tool_result"
            assert msg["data"]["name"] == "get_screen_size"

    def test_websocket_unknown_tool(self, client):
        """WebSocket returns error for unknown tool"""
        with client.websocket_connect("/ws/test_unknown") as ws:
            ws.send_json({
                "type": "tool_direct",
                "tool_name": "nonexistent_tool",
                "args": {}
            })
            msg = receive_until(ws, "error")
            assert msg["type"] == "error"

    def test_websocket_tool_direct_reports_execution_error(self, client):
        """WebSocket tool_direct returns tool_result errors instead of closing."""
        with client.websocket_connect("/ws/test_tool_error") as ws:
            ws.send_json({
                "type": "tool_direct",
                "tool_name": "browser_navigate",
                "args": {}
            })
            msg = receive_until(ws, "tool_result")
            assert msg["type"] == "tool_result"
            assert msg["data"]["name"] == "browser_navigate"
            assert "Tool execution failed" in msg["data"]["error"]

    def test_websocket_tool_direct_blocks_disallowed_tool(self, client):
        """tool_direct rejects tools not in SAFE_DIRECT_TOOLS, even if they exist."""
        with client.websocket_connect("/ws/test_tool_blocked") as ws:
            ws.send_json({
                "type": "tool_direct",
                "tool_name": "shell_execute",
                "args": {"cmd": "echo hi"}
            })
            msg = receive_until(ws, "error")
            assert msg["type"] == "error"
            assert "not allowed" in msg["data"]["message"].lower()

    def test_websocket_tool_direct_blocks_file_write(self, client):
        """file_write must not be reachable through tool_direct."""
        with client.websocket_connect("/ws/test_tool_block_write") as ws:
            ws.send_json({
                "type": "tool_direct",
                "tool_name": "file_write",
                "args": {"path": "/tmp/x", "content": "x"}
            })
            msg = receive_until(ws, "error")
            assert msg["type"] == "error"
            assert "not allowed" in msg["data"]["message"].lower()

    def test_websocket_set_chat_mode_persists(self, client):
        """set_chat_mode updates session, echoes chat_mode, and persists to snapshot."""
        sid = "test_ws_set_chat_mode_persist"
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "set_chat_mode", "chat_mode": "plan"})
            msg = receive_until(ws, "chat_mode")
            assert msg["type"] == "chat_mode"
            assert msg["data"]["chat_mode"] == "plan"
        snap = client.get(f"/api/sessions/{sid}").json()
        assert snap.get("chat_mode") == "plan"

    def test_websocket_set_chat_mode_invalid(self, client):
        sid = "test_ws_set_chat_mode_invalid"
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "set_chat_mode", "chat_mode": "bogus"})
            msg = receive_until(ws, "error")
            assert msg["type"] == "error"
            assert "invalid" in msg["data"]["message"].lower()

    def test_websocket_set_thinking_intensity_persists(self, client):
        sid = "test_ws_set_thinking_intensity_persist"
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "set_thinking_intensity", "thinking_intensity": "high"})
            msg = receive_until(ws, "thinking_intensity")
            assert msg["type"] == "thinking_intensity"
            assert msg["data"]["thinking_intensity"] == "high"
        snap = client.get(f"/api/sessions/{sid}").json()
        assert snap.get("thinking_intensity") == "high"

    def test_websocket_set_thinking_intensity_invalid(self, client):
        sid = "test_ws_set_thinking_intensity_invalid"
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "set_thinking_intensity", "thinking_intensity": "extreme"})
            msg = receive_until(ws, "error")
            assert msg["type"] == "error"
            assert "invalid" in msg["data"]["message"].lower()

    def test_delete_session_cancels_running_runtime(self, client, monkeypatch):
        """Deleting a historical session permanently terminates its live run."""
        import asyncio
        from app.agent import AgentSession

        markers = {"cancelled": False}

        async def slow_run(self, *args, **kwargs):
            yield {"type": "status", "data": {"status": "thinking"}}
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                markers["cancelled"] = True
                raise

        monkeypatch.setattr(AgentSession, "run", slow_run)
        sid = f"test_delete_cancels_runtime_{uuid.uuid4().hex}"

        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "chat", "text": "slow", "model_id": "gpt-4o"})
            receive_until(ws, "status")
            response = client.delete(f"/api/sessions/{sid}")

        assert response.status_code == 200
        assert response.json()["runtime_terminated"] is True
        assert markers["cancelled"] is True


class TestProjectAPI:
    def test_get_projects_empty(self, client):
        """GET /api/projects returns empty when no project open"""
        response = client.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert "projects" in data
        assert "current" in data
        assert data["current"] is None

    def test_create_project(self, client, temp_dir):
        """POST /api/projects/create creates a new project"""
        response = client.post("/api/projects/create", json={
            "parent_path": str(temp_dir),
            "name": "test-proj",
            "template": "empty"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-proj"
        assert data["path"] == str(temp_dir / "test-proj")

    def test_create_project_duplicate(self, client, temp_dir):
        """Creating duplicate project returns error"""
        client.post("/api/projects/create", json={
            "parent_path": str(temp_dir),
            "name": "dup-proj",
            "template": "empty"
        })
        response = client.post("/api/projects/create", json={
            "parent_path": str(temp_dir),
            "name": "dup-proj",
            "template": "empty"
        })
        assert response.status_code == 200
        assert "error" in response.json()

    def test_open_and_close_project(self, client, temp_dir):
        """POST /api/projects/open and /close lifecycle"""
        proj_dir = temp_dir / "openme"
        proj_dir.mkdir()
        # Open
        response = client.post("/api/projects/open", json={"path": str(proj_dir)})
        assert response.status_code == 200
        assert response.json()["name"] == "openme"
        # Current
        response = client.get("/api/projects/current")
        assert response.status_code == 200
        assert response.json()["name"] == "openme"
        # Close
        response = client.post("/api/projects/close")
        assert response.status_code == 200
        assert response.json()["status"] == "closed"
        response = client.get("/api/projects/current")
        assert response.json() is None

    def test_get_project_tree(self, client, temp_dir):
        """GET /api/projects/tree returns file tree"""
        proj_dir = temp_dir / "treeproj"
        proj_dir.mkdir()
        (proj_dir / "src").mkdir()
        (proj_dir / "src" / "main.py").write_text("x")
        (proj_dir / "README.md").write_text("x")
        client.post("/api/projects/open", json={"path": str(proj_dir)})
        response = client.get("/api/projects/tree")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        names = [n["name"] for n in data["nodes"]]
        assert "README.md" in names
        assert "src" in names

    def test_refresh_project_returns_latest_tree(self, client, temp_dir):
        """POST /api/projects/refresh returns refreshed project metadata and tree."""
        proj_dir = temp_dir / "refreshproj"
        proj_dir.mkdir()
        (proj_dir / "README.md").write_text("x", encoding="utf-8")
        client.post("/api/projects/open", json={"path": str(proj_dir)})

        (proj_dir / "new_file.py").write_text("print('new')\n", encoding="utf-8")
        response = client.post("/api/projects/refresh")

        assert response.status_code == 200
        data = response.json()
        assert data["project"]["name"] == "refreshproj"
        names = [n["name"] for n in data["nodes"]]
        assert "README.md" in names
        assert "new_file.py" in names

    def test_refresh_project_without_current_project(self, client):
        """POST /api/projects/refresh is safe when no project is open."""
        client.post("/api/projects/close")

        response = client.post("/api/projects/refresh")

        assert response.status_code == 200
        assert response.json() == {
            "project": None,
            "nodes": [],
            "error": "No current project",
        }

    def test_get_project_tree_loads_deep_path_on_demand(self, client, temp_dir):
        """GET /api/projects/tree?path=... returns children beyond initial tree depth."""
        proj_dir = temp_dir / "outer"
        deep_dir = proj_dir / "OPEN AGENT" / "src" / "open_agent"
        (deep_dir / "cli").mkdir(parents=True)
        (deep_dir / "__init__.py").write_text("", encoding="utf-8")
        (deep_dir / "cli" / "__init__.py").write_text("", encoding="utf-8")
        client.post("/api/projects/open", json={"path": str(proj_dir)})

        root_response = client.get("/api/projects/tree")
        root_nodes = root_response.json()["nodes"]
        outer_node = next(n for n in root_nodes if n["name"] == "OPEN AGENT")
        src_node = next(n for n in outer_node["children"] if n["name"] == "src")
        package_node = next(n for n in src_node["children"] if n["name"] == "open_agent")
        assert package_node["has_children"] is True
        assert "children" not in package_node

        response = client.get("/api/projects/tree", params={"path": "OPEN AGENT/src/open_agent"})

        assert response.status_code == 200
        names = [n["name"] for n in response.json()["nodes"]]
        assert "cli" in names
        assert "__init__.py" in names

    def test_get_project_tree_blocks_path_escape(self, client, temp_dir):
        """GET /api/projects/tree rejects sibling prefix/path traversal escapes."""
        proj_dir = temp_dir / "treeproj"
        sibling = temp_dir / "treeproj_evil"
        proj_dir.mkdir()
        sibling.mkdir()
        (sibling / "secret.txt").write_text("secret", encoding="utf-8")
        client.post("/api/projects/open", json={"path": str(proj_dir)})

        response = client.get("/api/projects/tree", params={"path": "../treeproj_evil"})

        assert response.status_code == 200
        assert response.json()["nodes"] == []

    def test_file_read_write_are_limited_to_current_project(self, client, temp_dir):
        """Editor file API can write/read current project files only."""
        proj_dir = temp_dir / "editorproj"
        sibling = temp_dir / "editorproj_evil"
        proj_dir.mkdir()
        sibling.mkdir()
        client.post("/api/projects/open", json={"path": str(proj_dir)})

        write_response = client.post("/api/file/write", json={
            "path": "notes.txt",
            "content": "hello",
        })
        assert write_response.status_code == 200
        assert write_response.json()["status"] == "ok"
        assert (proj_dir / "notes.txt").read_text(encoding="utf-8") == "hello"

        read_response = client.get("/api/file/read", params={"path": str(proj_dir / "notes.txt")})
        assert read_response.status_code == 200
        assert read_response.json()["content"] == "hello"

        escape_response = client.get("/api/file/read", params={"path": str(sibling / "secret.txt")})
        assert escape_response.status_code == 200
        assert "error" in escape_response.json()

    def test_clone_project_api_opens_cloned_repo(self, client, temp_dir):
        """POST /api/projects/clone clones a local repo and opens the target."""
        if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
            pytest.skip("git is not available")

        source = temp_dir / "source"
        target = temp_dir / "cloned"
        source.mkdir()
        subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
        (source / "README.md").write_text("# Source\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=source, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
            cwd=source,
            check=True,
            capture_output=True,
        )

        response = client.post("/api/projects/clone", json={"url": str(source), "path": str(target)})

        assert response.status_code == 200
        data = response.json()
        assert data["path"] == str(target)
        assert (target / "README.md").exists()

    def test_open_nonexistent(self, client):
        """Opening nonexistent path returns error"""
        response = client.post("/api/projects/open", json={"path": "/nonexistent/path"})
        assert response.status_code == 200
        assert "error" in response.json()


class TestSkillsAPI:
    def test_list_skills(self, client, monkeypatch, tmp_path):
        """GET /api/skills returns available skills"""
        import app.skills as skills_module
        monkeypatch.setattr(skills_module, "SKILL_PREFS_PATH", tmp_path / "skill_preferences.json")
        skills_module.SkillManager.reload_skills()

        response = client.get("/api/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data
        assert "preferences" in data
        assert "defaults" in data
        assert "presets" in data
        assert len(data["skills"]) > 0
        names = [s["name"] for s in data["skills"]]
        assert "using-superpowers" in names
        assert "brainstorming" in names
        skill_ids = {s["id"] for s in data["skills"]}
        for preset in data["presets"]:
            assert set(preset["skillIds"]).issubset(skill_ids)

    def test_update_skill_preferences(self, client, monkeypatch, tmp_path):
        """PUT /api/skills/preferences persists known IDs and ignores unknown IDs."""
        import app.skills as skills_module
        monkeypatch.setattr(skills_module, "SKILL_PREFS_PATH", tmp_path / "skill_preferences.json")
        skills_module.SkillManager.reload_skills()

        response = client.put("/api/skills/preferences", json={
            "coding": {
                "test-driven-development": False,
                "unknown-skill": True,
            }
        })

        assert response.status_code == 200
        data = response.json()
        assert data["ignored"] == ["unknown-skill"]
        assert data["preferences"]["coding"]["test-driven-development"] is False


@pytest.mark.usefixtures("isolate_projects")
class TestCredentialsAPI:
    def test_list_credentials_empty(self, client):
        """GET /api/credentials returns empty initially"""
        response = client.get("/api/credentials")
        assert response.status_code == 200
        data = response.json()
        assert data["hosts"] == []

    def test_store_and_list_credentials(self, client):
        """POST /api/credentials stores token"""
        response = client.post("/api/credentials", json={
            "host": "github.com",
            "username": "testuser",
            "token": "ghp_12345"
        })
        assert response.status_code == 200
        assert response.json()["status"] == "stored"
        # List
        response = client.get("/api/credentials")
        assert "github.com" in response.json()["hosts"]

    def test_delete_credentials(self, client):
        """DELETE /api/credentials/{host} removes token"""
        client.post("/api/credentials", json={
            "host": "gitlab.com",
            "username": "u",
            "token": "t"
        })
        response = client.delete("/api/credentials/gitlab.com")
        assert response.status_code == 200
        response = client.get("/api/credentials")
        assert "gitlab.com" not in response.json()["hosts"]
