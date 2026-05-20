import base64
from unittest.mock import patch

import pytest

from app.agent import AgentSession
from app.automation_runtime import save_snapshot, save_trace
from app.tools.automation_tool import _click_browser
from app.tools.base import ToolResult


ONE_BY_ONE_PNG = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
).decode("utf-8")


def test_automation_snapshot_and_trace_store_runtime_files():
    snapshot = save_snapshot("pytest-auto", {
        "source": "browser",
        "viewport": {"width": 1, "height": 1},
        "screenshot": {"base64": ONE_BY_ONE_PNG, "width": 1, "height": 1},
        "elements": [],
    })

    trace = save_trace("pytest-auto", {
        "source": "browser",
        "actions": [{
            "action_id": "act-test",
            "type": "click",
            "status": "success",
            "before_snapshot": snapshot,
        }],
    })

    assert snapshot["snapshot_id"].startswith("snap_")
    assert snapshot["screenshot"]["path"].endswith(".png")
    assert trace["trace_id"].startswith("trace_")
    assert trace["path"].endswith(".json")


@pytest.mark.asyncio
async def test_browser_semantic_locator_prefers_selector(monkeypatch):
    calls = []

    class FakeLocator:
        async def click(self, **kwargs):
            calls.append(kwargs)

    class FakePage:
        def locator(self, selector):
            calls.append({"selector": selector})
            return self

        @property
        def first(self):
            return FakeLocator()

    async def fake_get_browser_page(launch=True):
        return FakePage()

    monkeypatch.setattr("app.tools.automation_tool.get_browser_page", fake_get_browser_page)

    element, chain = await _click_browser("pytest-browser", selector="#submit", button="left", clicks=2)

    assert element is None
    assert chain == ["selector:#submit"]
    assert calls[0] == {"selector": "#submit"}
    assert calls[1]["click_count"] == 2


@pytest.mark.asyncio
async def test_agent_emits_automation_events(monkeypatch):
    snapshot = {
        "snapshot_id": "snap-test",
        "source": "browser",
        "timestamp": 1,
        "viewport": {"width": 100, "height": 100},
        "screenshot": {"base64": ONE_BY_ONE_PNG, "width": 1, "height": 1},
        "elements": [],
        "element_count": 0,
    }

    async def fake_execute(self, **kwargs):
        return ToolResult(output="observed", metadata={"automation_snapshot": snapshot})

    monkeypatch.setattr("app.tools.automation_tool.AutomationObserveTool.execute", fake_execute)

    responses = iter([
        {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_auto",
                        "type": "function",
                        "function": {"name": "automation_observe", "arguments": "{}"},
                    }],
                }
            }]
        },
        {
            "choices": [{
                "message": {"content": "done", "role": "assistant", "tool_calls": None}
            }]
        },
    ])

    async def stream_sequence(*args, **kwargs):
        yield {"type": "done", "response": next(responses)}

    session = AgentSession(model_id="gpt-4o", session_id="auto-events", agent_type="coding")
    with patch("app.agent.ModelRouter.chat_completion_stream", stream_sequence):
        events = []
        async for event in session.run("inspect ui"):
            events.append(event)

    assert any(event["type"] == "automation_snapshot" for event in events)
    assert any(event["type"] == "tool_call" and event["data"]["name"] == "automation_observe" for event in events)
