"""Integration test for ``app.gateway.runner.dispatch``.

This test stubs out the agent / session_runtime layer and verifies that
dispatch correctly:
  - resolves the connector's target agent
  - builds a thread-aware session id
  - publishes events from session.run() into the translator
  - flushes a final aggregate to the translator on `done`
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List

import pytest

from app.connectors.base import ConnectorConfig, PlatformConnector
from app.gateway import MessageEnvelope, dispatch
from app.gateway.translators.base import Translator


class _RecorderTranslator(Translator):
    def __init__(self) -> None:
        super().__init__(min_flush_chars=1, min_flush_interval=0, tool_visibility="debug")
        self.partials: List[str] = []
        self.completed: List[tuple[str, str]] = []
        self.errors: List[BaseException] = []
        self.tool_calls: List[str] = []

    async def _render_partial(self, text: str, *, final: bool) -> None:
        self.partials.append(text)

    async def on_complete(self, full_text: str, *, status: str) -> None:
        self.completed.append((full_text, status))

    async def on_error(self, exc: BaseException) -> None:
        self.errors.append(exc)

    async def on_tool_call(self, tool):
        self.tool_calls.append(tool.name)


class _StubConnector(PlatformConnector):
    name = "stub"
    display_name = "Stub"

    def __init__(self) -> None:
        super().__init__(ConnectorConfig(name="stub", display_name="Stub"))
        self._status_value = "running"

    @property
    def status(self) -> str:
        return self._status_value

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def resolve_agent_target(self):  # type: ignore[override]
        return ("personal", "desktop-agent", "stub-model")


@pytest.fixture
def stub_session_layer(monkeypatch):
    """Replace session/runtime singletons with stand-ins that emit a fixed event sequence."""
    events_to_yield: List[List[Dict[str, Any]]] = []

    class FakeSession:
        def __init__(self, *, events: List[Dict[str, Any]]):
            self._events = events
            self.cancel_calls = 0

        def cancel(self) -> None:
            self.cancel_calls += 1

        def run(self, prompt: str, _image) -> AsyncIterator[Dict[str, Any]]:
            evs = list(self._events)

            async def _gen():
                for ev in evs:
                    yield ev

            return _gen()

    sessions: Dict[str, FakeSession] = {}

    def fake_get_or_create_session(session_id, model_id, role_id=None, agent_type=None, **_):
        sessions.setdefault(session_id, FakeSession(events=events_to_yield[-1] if events_to_yield else []))
        return sessions[session_id]

    monkeypatch.setattr(
        "app.agent.get_or_create_session", fake_get_or_create_session,
    )

    # SessionRuntime is exercised for real — that's the whole point of the test
    # (we verify our consumer sees the events runtime publishes).
    return {
        "set_events": lambda evs: events_to_yield.append(evs),
        "sessions": sessions,
    }


@pytest.mark.asyncio
async def test_dispatch_streams_events_to_translator(stub_session_layer):
    stub_session_layer["set_events"]([
        {"type": "content", "data": {"text": "Hello "}},
        {"type": "content", "data": {"text": "world"}},
        {"type": "tool_call", "data": {"name": "search", "args": {}, "result": "ok", "duration_ms": 1.0}},
        {"type": "run_completed", "data": {"status": "completed"}},
    ])

    connector = _StubConnector()
    translator = _RecorderTranslator()
    envelope = MessageEnvelope(
        platform="stub", channel_id="c1", user_id="u1",
        text="hi", thread_id="thr-9",
    )

    session_id = await dispatch(connector, envelope, translator, timeout_s=5)

    assert session_id.startswith("stub_personal_u1_c1")
    assert "_tthr-9" in session_id
    assert translator.completed, "on_complete must fire"
    full_text, status = translator.completed[-1]
    assert full_text == "Hello world"
    assert status == "completed"
    assert translator.tool_calls == ["search"]
    assert not translator.errors


@pytest.mark.asyncio
async def test_dispatch_marks_translator_error_on_runtime_error(stub_session_layer):
    stub_session_layer["set_events"]([
        {"type": "error", "data": {"message": "boom"}},
    ])

    connector = _StubConnector()
    translator = _RecorderTranslator()
    envelope = MessageEnvelope(platform="stub", channel_id="c2", user_id="u2", text="hi")

    await dispatch(connector, envelope, translator, timeout_s=5)

    assert translator.errors, "on_error must fire when agent yields error event"
    assert "boom" in str(translator.errors[-1])


@pytest.mark.asyncio
async def test_dispatch_thread_isolates_sessions(stub_session_layer):
    stub_session_layer["set_events"]([
        {"type": "content", "data": {"text": "A"}},
        {"type": "run_completed", "data": {"status": "completed"}},
    ])

    connector = _StubConnector()

    envelope_a = MessageEnvelope(platform="stub", channel_id="c", user_id="u", text="t", thread_id="t1")
    envelope_b = MessageEnvelope(platform="stub", channel_id="c", user_id="u", text="t", thread_id="t2")
    envelope_no_thread = MessageEnvelope(platform="stub", channel_id="c", user_id="u", text="t")

    sid_a = await dispatch(connector, envelope_a, _RecorderTranslator(), timeout_s=5)
    sid_b = await dispatch(connector, envelope_b, _RecorderTranslator(), timeout_s=5)
    sid_n = await dispatch(connector, envelope_no_thread, _RecorderTranslator(), timeout_s=5)

    assert sid_a != sid_b
    assert sid_n != sid_a and sid_n != sid_b
    # back-compat: without a thread the id remains the legacy layout.
    assert sid_n == "stub_personal_u_c"
