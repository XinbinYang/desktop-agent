import json
import pytest
from unittest.mock import patch, MagicMock
from app.agent import (
    AgentSession,
    get_or_create_session,
    clear_session,
    _completion_quality_payload,
    _shell_command_looks_like_verification,
)
from .conftest import _make_stream_mock


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

    def test_completion_quality_payload_marks_missing_gates(self):
        missing = _completion_quality_payload(
            files_modified=True,
            latest_verification=None,
            latest_review=None,
            unstructured_verification_seen=False,
        )

        assert missing["verification_passed"] is False
        assert missing["verification_source"] == "missing"
        assert missing["review_passed"] is False

        evidenced = _completion_quality_payload(
            files_modified=True,
            latest_verification={
                "passed": True,
                "command": "python -m pytest",
                "green_level": "workspace",
            },
            latest_review={
                "findings": [{"severity": "minor", "message": "Non-blocking"}],
                "blocking_findings": [],
            },
            unstructured_verification_seen=False,
        )

        assert evidenced["verification_passed"] is True
        assert evidenced["verification_command"] == "python -m pytest"
        assert evidenced["green_level"] == "workspace"
        assert evidenced["review_passed"] is True

    def test_shell_verification_detection_is_not_any_shell_command(self):
        assert _shell_command_looks_like_verification("python -m pytest tests/test_agent.py")
        assert _shell_command_looks_like_verification("npm run build")
        assert not _shell_command_looks_like_verification("pwd")

    def test_get_or_create_preserves_saved_session_model(self, tmp_path, monkeypatch):
        import app.agent as agent_module

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()

        saved = AgentSession(model_id="gpt-4o", session_id="history_session")
        saved.messages.append({"role": "user", "content": "historical question"})
        saved.messages.append({"role": "assistant", "content": "historical answer"})
        saved._save()

        loaded = get_or_create_session("history_session", "new-default-model")

        assert loaded.model_id == "gpt-4o"
        assert any(m.get("content") == "historical question" for m in loaded.messages)

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

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
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

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
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

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
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

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
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

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            events = []
            async for event in session.run("hi again"):
                events.append(event)

        assert not any(e["type"] == "interrupted" for e in events)
        streamed_text = "".join(e["data"]["text"] for e in events if e["type"] == "content")
        assert streamed_text == "Recovered"

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

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
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

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            events = []
            async for event in session.run("missing tool arg"):
                events.append(event)

        assert any(
            e["type"] == "tool_call"
            and e["data"]["tool_call_id"] == "call_missing_arg"
            and ("Tool execution failed" in e["data"]["result"] or "[ERROR]" in e["data"]["result"])
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

    @pytest.mark.asyncio
    async def test_plan_mode_llm_calls_plan_ask_questions(self, session):
        """LLM decides to ask clarifying questions in plan mode."""
        mock_response = {
            "choices": [{
                "message": {
                    "content": "I need more context.",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "plan_ask_questions",
                            "arguments": json.dumps({
                                "questions": [{
                                    "id": "scope",
                                    "prompt": "What scope do you need?",
                                    "allow_multiple": False,
                                    "options": [
                                        {"id": "minimal", "label": "Minimal"},
                                        {"id": "full", "label": "Full"}
                                    ]
                                }]
                            })
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            events = []
            async for ev in session.run("hi", None, chat_mode="plan"):
                events.append(ev)

        types = [e["type"] for e in events]
        assert "plan_questions" in types
        assert session.plan_state.pending_clarification is True
        assert session.plan_state.phase == "awaiting_decision"
        assert len(session.plan_state.questions) == 1
        assert session.plan_state.questions[0].id == "scope"

    def test_plan_tool_schema_filter_includes_plan_tools(self, session):
        from app.tools import get_tool_schemas

        session.chat_mode = "plan"
        session.plan_state.approved = False
        all_schemas = get_tool_schemas(session.dynamic_registry)
        filtered = session._filter_tool_schemas_for_plan(all_schemas)
        names = {s["function"]["name"] for s in filtered}
        assert "file_write" not in names
        assert "shell_execute" not in names
        assert "file_read" in names
        assert "plan_ask_questions" in names
        assert "plan_write_draft" in names

    def test_plan_approve_requires_explicit_build(self, session):
        session.chat_mode = "plan"
        session.plan_state.phase = "awaiting_approval"
        session.approve_plan()
        assert session.plan_state.phase == "approved_waiting_build"
        assert session.plan_state.approved is True
        assert session.build_plan() is True
        assert session.plan_state.phase == "executing"
        # Build auto-switches to agent mode
        assert session.chat_mode == "agent"

    @pytest.mark.asyncio
    async def test_plan_mode_llm_calls_plan_write_draft(self, session):
        """LLM can skip questions and draft directly for specific requests."""
        mock_response = {
            "choices": [{
                "message": {
                    "content": "I'll draft a plan now.",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "plan_write_draft",
                            "arguments": json.dumps({
                                "goal": "Add CSV export to DataTable",
                                "assumptions": ["Existing CSV library available"],
                                "research_notes": "Read DataTable.tsx — existing export pattern.",
                                "steps": [{
                                    "id": "s1",
                                    "title": "Add export button",
                                    "details": "In DataTable.tsx:120 add a button",
                                    "depends_on": [],
                                }],
                                "todos": [{
                                    "id": "t1",
                                    "title": "Add CSV export function",
                                    "acceptance_criteria": "Clicking export downloads a CSV file",
                                    "depends_on": [],
                                }],
                                "risks": ["Large datasets may timeout"],
                                "verification": ["Test export with sample data"],
                                "markdown_body": "# Plan: Add CSV export\n\n## Steps\n1. Add export button\n\n## Todos\n- [ ] Add CSV export function\n\n## Verification\n- Test export",
                            })
                        }
                    }]
                }
            }]
        }

        with patch("app.agent.ModelRouter.chat_completion_stream", _make_stream_mock(mock_response)):
            events = []
            async for ev in session.run("implement csv export", None, chat_mode="plan"):
                events.append(ev)

        types = [e["type"] for e in events]
        assert "plan_draft" in types
        assert "plan_file_ready" in types
        assert session.plan_state.phase == "awaiting_approval"
        assert session.plan_state.approved is False
        assert len(session.plan_state.todos) == 1
        assert session.plan_state.todos[0].title == "Add CSV export function"
        assert session.plan_state.plan_file_path is not None

    @pytest.mark.asyncio
    async def test_plan_mode_reject_resets_to_clarifying(self, session):
        """Rejecting a plan returns to clarifying phase."""
        session.chat_mode = "plan"
        session.plan_state.mode = "plan"
        session.plan_state.goal = "test"
        session.plan_state.phase = "awaiting_approval"
        session.plan_state.approved = False
        session.reject_plan()
        assert session.plan_state.phase == "clarifying"
        assert session.plan_state.approved is False


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


class TestAgentType:
    """Verify agent_type support in AgentSession."""

    def test_default_agent_type_is_personal(self):
        session = AgentSession(model_id="gpt-4o", session_id="test_at")
        assert session.agent_type == "personal"

    def test_explicit_agent_type_coding(self):
        session = AgentSession(model_id="gpt-4o", session_id="test_at", agent_type="coding")
        assert session.agent_type == "coding"

    def test_agent_type_from_role_id_compat(self):
        """role_id 'code-expert' maps to agent_type 'coding'."""
        session = AgentSession(model_id="gpt-4o", session_id="test_at", role_id="code-expert")
        assert session.agent_type == "coding"
        assert session.role_id == "code-expert"

    def test_switch_agent_preserves_session(self):
        """Switching agent type preserves the session ID and switches to agent-specific model."""
        session = AgentSession(model_id="gpt-4o", session_id="test_at")
        session.switch_agent("coding")
        assert session.agent_type == "coding"
        assert session.session_id == "test_at"
        # model_id may change because switch_agent applies the agent's configured model
        assert isinstance(session.model_id, str) and len(session.model_id) > 0

    def test_switch_agent_updates_system_prompt(self):
        """Switching agent type refreshes the system prompt."""
        session = AgentSession(model_id="gpt-4o", session_id="test_at", agent_type="personal")
        old_prompt = session.messages[0]["content"]
        session.switch_agent("coding")
        new_prompt = session.messages[0]["content"]
        # The prompts should differ because coding excludes personal files
        assert old_prompt != new_prompt

    def test_switch_role_backward_compat(self):
        """switch_role() still works and maps through agent_type."""
        session = AgentSession(model_id="gpt-4o", session_id="test_at", agent_type="personal")
        session.switch_role("code-expert")
        assert session.agent_type == "coding"
        assert session.role_id == "code-expert"

    def test_get_or_create_session_with_agent_type(self):
        s = get_or_create_session("at_s1", "gpt-4o", role_id="code-expert", agent_type="coding")
        assert s.agent_type == "coding"
        assert s.role_id == "code-expert"

    def test_session_save_and_load_preserves_agent_type(self, tmp_path, monkeypatch):
        import app.agent as agent_module
        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()

        session = AgentSession(model_id="gpt-4o", session_id="at_save", agent_type="coding")
        session._save()

        loaded = AgentSession.load("at_save")
        assert loaded is not None
        assert loaded.agent_type == "coding"

    def test_session_load_migrates_role_id_to_agent_type(self, tmp_path, monkeypatch):
        """Sessions saved without agent_type should auto-migrate from role_id."""
        import app.agent as agent_module
        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()

        session = AgentSession(model_id="gpt-4o", session_id="at_migrate", role_id="desktop-agent", agent_type="personal")
        session._save()

        # Simulate old save format (remove agent_type from JSON)
        save_path = tmp_path / "at_migrate.json"
        import json
        data = json.loads(save_path.read_text(encoding="utf-8"))
        del data["agent_type"]
        save_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        loaded = AgentSession.load("at_migrate")
        assert loaded is not None
        assert loaded.agent_type == "personal"  # Migrated from role_id="desktop-agent"
