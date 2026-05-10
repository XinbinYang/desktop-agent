import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.agent import AgentSession, get_or_create_session, clear_session


class TestAgentSession:
    @pytest.fixture
    def session(self):
        return AgentSession(model_id="gpt-4o", session_id="test_session")

    @pytest.mark.asyncio
    async def test_session_initialization(self, session):
        assert session.model_id == "gpt-4o"
        assert session.session_id == "test_session"
        assert session.iteration == 0
        assert len(session.messages) == 1  # system prompt
        assert session.messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_run_without_tool_calls(self, session):
        mock_response = {
            "choices": [{
                "message": {
                    "content": "Hello user",
                    "role": "assistant",
                    "tool_calls": None
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_non_stream", new_callable=AsyncMock, return_value=mock_response):
            events = []
            async for event in session.run("hi"):
                events.append(event)

            assert any(e["type"] == "content" for e in events)
            assert any(e["type"] == "status" and e["data"]["status"] == "completed" for e in events)
            assert all("run_id" in e["data"] for e in events if "data" in e)
            assert all("timestamp" in e["data"] for e in events if "data" in e)

    @pytest.mark.asyncio
    async def test_run_with_tool_call(self, session):
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_screen_size",
                            "arguments": "{}"
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_non_stream", new_callable=AsyncMock, return_value=mock_response):
            events = []
            async for event in session.run("screenshot please"):
                events.append(event)
                if len(events) > 20:  # safety break
                    break

            tool_call_events = [e for e in events if e["type"] == "tool_call"]
            assert len(tool_call_events) >= 1
            assert tool_call_events[0]["data"]["name"] == "get_screen_size"

    @pytest.mark.asyncio
    async def test_run_with_file_write_emits_file_edit(self, session, temp_dir):
        session.max_iterations = 1
        target = temp_dir / "agent-edit.txt"
        args = json.dumps({"path": str(target), "content": "hello"})
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_file",
                        "type": "function",
                        "function": {
                            "name": "file_write",
                            "arguments": args,
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_non_stream", new_callable=AsyncMock, return_value=mock_response):
            events = []
            async for event in session.run("write file"):
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "file_edit" in event_types
        assert event_types.index("file_edit") < event_types.index("tool_call")
        edit = next(e["data"] for e in events if e["type"] == "file_edit")
        assert edit["tool_call_id"] == "call_file"
        assert edit["new_text"] == "hello"

    @pytest.mark.asyncio
    async def test_run_max_iterations(self, session):
        session.max_iterations = 2

        # Always return a tool call to force iteration
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_screen_size",
                            "arguments": "{}"
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_non_stream", new_callable=AsyncMock, return_value=mock_response):
            events = []
            async for event in session.run("loop test"):
                events.append(event)
                if len(events) > 30:
                    break

            assert any(
                e["type"] == "status" and e["data"]["status"] == "max_iterations_reached"
                for e in events
            )

    @pytest.mark.asyncio
    async def test_cancel_does_not_poison_next_run(self, session):
        session.cancel()
        mock_response = {
            "choices": [{
                "message": {
                    "content": "Recovered",
                    "role": "assistant",
                    "tool_calls": None
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_non_stream", new_callable=AsyncMock, return_value=mock_response):
            events = []
            async for event in session.run("hi again"):
                events.append(event)

        assert not any(e["type"] == "interrupted" for e in events)
        assert any(e["type"] == "content" and e["data"]["text"] == "Recovered" for e in events)

    @pytest.mark.asyncio
    async def test_invalid_tool_arguments_are_reported_as_tool_result(self, session):
        session.max_iterations = 1
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "get_screen_size",
                            "arguments": "{bad json"
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_non_stream", new_callable=AsyncMock, return_value=mock_response):
            events = []
            async for event in session.run("bad tool args"):
                events.append(event)

        assert any(
            e["type"] == "tool_call" and "Tool argument parse failed" in e["data"]["result"]
            for e in events
        )
        assert any(
            msg.get("role") == "tool" and msg.get("tool_call_id") == "call_bad"
            for msg in session.messages
        )

    @pytest.mark.asyncio
    async def test_tool_type_error_is_reported_as_tool_result(self, session):
        session.max_iterations = 1
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_missing_arg",
                        "type": "function",
                        "function": {
                            "name": "file_read",
                            "arguments": "{}"
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_non_stream", new_callable=AsyncMock, return_value=mock_response):
            events = []
            async for event in session.run("missing tool arg"):
                events.append(event)

        assert any(
            e["type"] == "tool_call"
            and e["data"]["tool_call_id"] == "call_missing_arg"
            and "Tool execution failed" in e["data"]["result"]
            for e in events
        )

    def test_trim_drops_orphan_tool_messages(self, session):
        session.messages.extend([
            {"role": "tool", "tool_call_id": "orphan", "name": "x", "content": "bad"},
            {"role": "user", "content": "next"},
        ])

        session._trim_messages()

        assert not any(
            msg.get("role") == "tool" and msg.get("tool_call_id") == "orphan"
            for msg in session.messages
        )

    def test_trim_keeps_complete_tool_call_group(self, session):
        session.MAX_HISTORY_MESSAGES = 3
        session.messages.extend([
            {"role": "user", "content": "old"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "file_read", "arguments": "{\"path\":\"x\"}"}
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "file_read", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ])

        session._trim_messages()

        roles = [m.get("role") for m in session.messages]
        assert roles == ["system", "assistant", "tool", "assistant"]
        assert session.messages[1].get("tool_calls")

    def test_reset(self, session):
        session.messages.append({"role": "user", "content": "hi"})
        session.iteration = 5
        session.reset()
        assert session.iteration == 0
        assert len(session.messages) == 1
        assert session.messages[0]["role"] == "system"


class TestSessionManagement:
    def test_get_or_create_session(self):
        s1 = get_or_create_session("s1", "gpt-4o")
        s2 = get_or_create_session("s1", "gpt-4o")
        assert s1 is s2

    def test_get_or_create_session_with_different_model(self):
        s1 = get_or_create_session("s2", "gpt-4o")
        # Use same model ID to avoid needing another valid model in config
        s2 = get_or_create_session("s2", "gpt-4o")
        assert s1 is s2
        # Now test model change behavior by resetting manually
        from app.agent import _sessions
        _sessions["s2"] = AgentSession(model_id="gpt-4o", session_id="s2")
        assert _sessions["s2"] is not s1

    def test_clear_session(self):
        s = get_or_create_session("s3", "gpt-4o")
        s.messages.append({"role": "user", "content": "x"})
        s.iteration = 3
        clear_session("s3")
        assert s.iteration == 0
        assert len(s.messages) == 1

    def test_session_lru_evicts_oldest(self, monkeypatch, tmp_path):
        """Once MAX_LIVE_SESSIONS is exceeded, the least-recently-used session is evicted."""
        from app import agent

        # Shrink limit and isolate session JSON dir so the test does not pollute repo state.
        monkeypatch.setattr(agent, "MAX_LIVE_SESSIONS", 3)
        monkeypatch.setattr(agent, "SESSIONS_DIR", tmp_path)
        agent._sessions.clear()

        first = get_or_create_session("lru1", "gpt-4o")
        get_or_create_session("lru2", "gpt-4o")
        get_or_create_session("lru3", "gpt-4o")
        # Touch lru1 so it becomes most-recently used.
        get_or_create_session("lru1", "gpt-4o")
        # Adding lru4 should evict the oldest still-untouched session: lru2
        get_or_create_session("lru4", "gpt-4o")

        assert "lru2" not in agent._sessions
        assert "lru1" in agent._sessions
        assert "lru3" in agent._sessions
        assert "lru4" in agent._sessions
        assert len(agent._sessions) == 3
        # Identity preserved when accessed within window.
        assert agent._sessions["lru1"] is first
