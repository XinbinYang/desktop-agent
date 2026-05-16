import json
import subprocess

import pytest
from starlette.websockets import WebSocketDisconnect


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

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/auth_missing"):
                pass

    def test_websocket_accepts_valid_query_token(self, client, monkeypatch):
        monkeypatch.setenv("DESKTOP_AGENT_AUTH_TOKEN", "test-token")

        with client.websocket_connect("/ws/auth_ok?token=test-token") as ws:
            ws.send_json({"type": "clear"})
            msg = ws.receive_json()

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
            for _ in range(10):
                msg = ws.receive_json()
                msgs.append(msg)
                if msg.get("type") == "done":
                    break

            types = [m["type"] for m in msgs]
            assert "status" in types
            assert "done" in types

    def test_websocket_plan_chat_emits_plan_draft(self, client):
        """Plan mode: LLM calls plan_write_draft → frontend receives plan_draft."""
        from unittest.mock import patch, AsyncMock
        from app.agent import PLAN_CONTINUE_MARKER

        mock_llm = AsyncMock(return_value={
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
        })

        with patch("app.agent.ModelRouter.chat_completion_non_stream", mock_llm):
            with client.websocket_connect("/ws/test_plan_ws") as ws:
                ws.send_json({
                    "type": "chat",
                    "text": "plan this",
                    "model_id": "gpt-4o",
                    "chat_mode": "plan",
                    "thinking_intensity": "medium",
                })
                types = []
                for _ in range(20):
                    msg = ws.receive_json()
                    types.append(msg["type"])
                    if msg.get("type") == "done":
                        break
                assert "plan_draft" in types
                assert "plan_status" in types
                assert "done" in types

    def test_websocket_plan_approve_then_build(self, client):
        from unittest.mock import patch, AsyncMock
        from app.agent import PLAN_CONTINUE_MARKER

        mock_llm = AsyncMock(return_value={
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
        })

        with patch("app.agent.ModelRouter.chat_completion_non_stream", mock_llm):
            with client.websocket_connect("/ws/test_plan_build_ws") as ws:
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

                ws.send_json({"type": "approve_plan"})
                approve_types = []
                for _ in range(10):
                    msg = ws.receive_json()
                    approve_types.append(msg["type"])
                assert "plan_approved_waiting_build" in approve_types

                ws.send_json({"type": "build_plan"})
                build_types = []
                for _ in range(20):
                    msg = ws.receive_json()
                    build_types.append(msg["type"])
                    if msg.get("type") == "done":
                        break
                assert "build_started" in build_types
                assert "done" in build_types

    def test_websocket_clear(self, client):
        """WebSocket clear message type"""
        with client.websocket_connect("/ws/test_clear") as ws:
            ws.send_json({"type": "clear"})
            msg = ws.receive_json()
            assert msg["type"] == "cleared"

    def test_websocket_tool_direct(self, client):
        """WebSocket tool_direct message type"""
        with client.websocket_connect("/ws/test_tool") as ws:
            ws.send_json({
                "type": "tool_direct",
                "tool_name": "get_screen_size",
                "args": {}
            })
            msg = ws.receive_json()
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
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_websocket_tool_direct_reports_execution_error(self, client):
        """WebSocket tool_direct returns tool_result errors instead of closing."""
        with client.websocket_connect("/ws/test_tool_error") as ws:
            ws.send_json({
                "type": "tool_direct",
                "tool_name": "browser_navigate",
                "args": {}
            })
            msg = ws.receive_json()
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
            msg = ws.receive_json()
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
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "not allowed" in msg["data"]["message"].lower()

    def test_websocket_set_chat_mode_persists(self, client):
        """set_chat_mode updates session, echoes chat_mode, and persists to snapshot."""
        sid = "test_ws_set_chat_mode_persist"
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "set_chat_mode", "chat_mode": "plan"})
            msg = ws.receive_json()
            assert msg["type"] == "chat_mode"
            assert msg["data"]["chat_mode"] == "plan"
        snap = client.get(f"/api/sessions/{sid}").json()
        assert snap.get("chat_mode") == "plan"

    def test_websocket_set_chat_mode_invalid(self, client):
        sid = "test_ws_set_chat_mode_invalid"
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "set_chat_mode", "chat_mode": "bogus"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "invalid" in msg["data"]["message"].lower()


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
    def test_list_skills(self, client):
        """GET /api/skills returns available skills"""
        response = client.get("/api/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data
        assert len(data["skills"]) > 0
        names = [s["name"] for s in data["skills"]]
        assert "using-superpowers" in names
        assert "brainstorming" in names


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
