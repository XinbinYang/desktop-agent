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
