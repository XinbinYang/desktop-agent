"""Anti-hallucination tests: verify that context-escape tools are blocked
when the user did not explicitly ask for external resources.
"""
import json
import pytest
from unittest.mock import patch
from app.agent import AgentSession
from .conftest import _make_stream_mock


class TestHallucinationGuard:
    @pytest.fixture
    def session(self):
        return AgentSession(model_id="gpt-4o", session_id="test_hallucination")

    @pytest.mark.asyncio
    async def test_git_clone_blocked_without_external_intent(self, session):
        """User asks to familiarize with codebase; model hallucinates git_clone -> blocked."""
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_clone",
                        "type": "function",
                        "function": {
                            "name": "git_clone",
                            "arguments": json.dumps({"url": "https://github.com/XinbinYang/cursor-template.git"})
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            events = []
            async for event in session.run("熟悉代码库"):
                events.append(event)
                if len(events) > 20:
                    break

        tool_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_events) >= 1
        assert tool_events[0]["data"]["name"] == "git_clone"
        assert "[INTENT_BLOCKED]" in tool_events[0]["data"]["result"]

    @pytest.mark.asyncio
    async def test_git_clone_allowed_with_explicit_intent(self, session):
        """User explicitly asks to clone a GitHub repo -> allowed."""
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_clone2",
                        "type": "function",
                        "function": {
                            "name": "git_clone",
                            "arguments": json.dumps({"url": "https://github.com/user/repo.git"})
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            events = []
            async for event in session.run("帮我 clone 这个 github 仓库"):
                events.append(event)
                if len(events) > 20:
                    break

        tool_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_events) >= 1
        assert tool_events[0]["data"]["name"] == "git_clone"
        # Should NOT be blocked
        assert "[INTENT_BLOCKED]" not in tool_events[0]["data"]["result"]

    @pytest.mark.asyncio
    async def test_browser_navigate_external_blocked_without_intent(self, session):
        """User asks about local files; model hallucinates browsing external site -> blocked."""
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_nav",
                        "type": "function",
                        "function": {
                            "name": "browser_navigate",
                            "arguments": json.dumps({"url": "https://example.com"})
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            events = []
            async for event in session.run("查看本地文件"):
                events.append(event)
                if len(events) > 20:
                    break

        tool_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_events) >= 1
        assert tool_events[0]["data"]["name"] == "browser_navigate"
        assert "[INTENT_BLOCKED]" in tool_events[0]["data"]["result"]

    @pytest.mark.asyncio
    async def test_browser_navigate_localhost_always_allowed(self, session):
        """Localhost navigations should never be blocked, even without explicit intent."""
        mock_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_nav_local",
                        "type": "function",
                        "function": {
                            "name": "browser_navigate",
                            "arguments": json.dumps({"url": "http://localhost:5173"})
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            events = []
            async for event in session.run("打开前端页面"):
                events.append(event)
                if len(events) > 20:
                    break

        tool_events = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_events) >= 1
        assert tool_events[0]["data"]["name"] == "browser_navigate"
        assert "[INTENT_BLOCKED]" not in tool_events[0]["data"]["result"]
