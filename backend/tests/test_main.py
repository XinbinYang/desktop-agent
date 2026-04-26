import json

import pytest


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
