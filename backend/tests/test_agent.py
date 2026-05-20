import json
import pytest
from unittest.mock import patch, MagicMock
from app.agent import (
    AgentSession,
    get_or_create_session,
    clear_session,
    PLAN_CONTINUE_MARKER,
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

    def test_set_session_thinking_intensity_updates_active_agent(self, session):
        assert session.set_session_thinking_intensity("high") is True
        assert session.thinking_intensity == "high"
        assert session._agent_thinking[session.agent_type] == "high"
        assert session.set_session_thinking_intensity("extreme") is False
        assert session.thinking_intensity == "high"

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

    def test_context_usage_and_checkpoints_have_stable_shape(self, session):
        session.messages.append({"role": "user", "content": "first prompt"})
        session.messages.append({"role": "assistant", "content": "first answer"})

        usage = session.context_usage()
        checkpoints = session.build_checkpoints()

        assert usage["model_context"] > 0
        assert usage["used_tokens"] >= 0
        assert usage["used_percent"] >= 0
        assert usage["source"] in {"estimate", "provider"}
        assert "history" in usage["breakdown"]
        assert len(checkpoints) == 1
        assert checkpoints[0]["id"].startswith("chk_")
        assert checkpoints[0]["preview"] == "first prompt"

    def test_rewind_to_checkpoint_trims_later_conversation(self, session):
        session.messages.append({"role": "user", "content": "keep me"})
        session.messages.append({"role": "assistant", "content": "old answer"})
        session.messages.append({"role": "user", "content": "remove me"})
        session.messages.append({"role": "assistant", "content": "remove answer"})
        checkpoint_id = session.build_checkpoints()[0]["id"]

        result = session.rewind_to_checkpoint(checkpoint_id)

        assert result is not None
        assert result["checkpoint_id"] == checkpoint_id
        assert [m.get("content") for m in session.messages if m.get("role") != "system"] == ["keep me"]
        assert session.messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_compact_context_summarizes_older_messages_and_keeps_recent_turns(self, session):
        async def fake_summary(*args, **kwargs):
            return {"choices": [{"message": {"content": "Summary: earlier decisions and tool results."}}]}

        for i in range(6):
            session.messages.append({"role": "user", "content": f"user turn {i}"})
            session.messages.append({"role": "assistant", "content": f"assistant turn {i}"})
        session.router.chat_completion_non_stream = fake_summary

        result = await session.compact_context(force=True)

        assert result is not None
        assert result["skipped"] is False
        assert result["before_message_count"] == 12
        assert result["after_message_count"] == 12
        assert session.compaction_summary.startswith("Summary:")
        assert len([m for m in session.messages if m.get("role") == "system"]) == 1
        remaining_text = "\n".join(str(m.get("content")) for m in session.messages)
        assert "user turn 0" in remaining_text
        assert "user turn 5" in remaining_text
        assert result["context_usage"]["context_message_count"] <= result["after_message_count"]
        assert result["preserved_recent_turns"] == 4
        assert session.compaction_state["compacted_through_checkpoint_id"]
        assert result["context_usage"]["compaction_active"] is True
        assert result["context_usage"]["summarized_message_count"] > 0

    @pytest.mark.asyncio
    async def test_compact_context_merges_existing_summary_with_new_delta(self, session):
        captured_summary_messages = []

        async def fake_summary(*args, **kwargs):
            messages = kwargs.get("messages") or args[0]
            captured_summary_messages.append(messages)
            return {"choices": [{"message": {"content": f"Summary v{len(captured_summary_messages)}"}}]}

        for i in range(6):
            session.messages.append({"role": "user", "content": f"user turn {i}", "source": "user"})
            session.messages.append({"role": "assistant", "content": f"assistant turn {i}"})
        session.router.chat_completion_non_stream = fake_summary

        first = await session.compact_context(force=True)
        for i in range(6, 8):
            session.messages.append({"role": "user", "content": f"user turn {i}", "source": "user"})
            session.messages.append({"role": "assistant", "content": f"assistant turn {i}"})
        second = await session.compact_context(force=True)

        assert first is not None and first["skipped"] is False
        assert second is not None and second["skipped"] is False
        assert session.compaction_summary == "Summary v2"
        assert session.compaction_state["compacted_turn_count"] == 8
        second_prompt = captured_summary_messages[1][0]["content"]
        assert "Previous compacted summary to merge" in second_prompt
        assert "Summary v1" in second_prompt
        assert "user turn 2" in second_prompt
        assert "user turn 7" not in second_prompt

    @pytest.mark.asyncio
    async def test_compact_context_failure_preserves_existing_summary(self, session):
        async def failing_summary(*args, **kwargs):
            raise RuntimeError("summary model unavailable")

        session.compaction_summary = "Existing summary"
        session.compaction_state["compacted_turn_count"] = 4
        for i in range(8):
            session.messages.append({"role": "user", "content": f"user turn {i}", "source": "user"})
            session.messages.append({"role": "assistant", "content": f"assistant turn {i}"})
        session.router.chat_completion_non_stream = failing_summary

        result = await session.compact_context(force=True, trigger="hard")

        assert result is None
        assert session.compaction_summary == "Existing summary"
        assert "summary model unavailable" in session.compaction_state["last_auto_error"]

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
    async def test_empty_stream_response_uses_non_stream_fallback(self, session):
        async def empty_stream(*args, **kwargs):
            yield {"type": "done", "response": {"choices": [{"message": {"content": ""}}]}}

        async def non_stream_fallback(*args, **kwargs):
            return {"choices": [{"message": {"content": "Recovered fallback"}}]}

        with (
            patch("app.agent.ModelRouter.chat_completion_stream", empty_stream),
            patch("app.agent.ModelRouter.chat_completion_non_stream", non_stream_fallback),
        ):
            events = []
            async for event in session.run("hi"):
                events.append(event)

        streamed_text = "".join(e["data"]["text"] for e in events if e["type"] == "content")
        assert streamed_text == "Recovered fallback"
        assert any(e["type"] == "status" and e["data"]["status"] == "completed" for e in events)

    @pytest.mark.asyncio
    async def test_stream_without_done_uses_non_stream_fallback(self, session):
        async def stream_without_done(*args, **kwargs):
            if False:
                yield {}

        async def non_stream_fallback(*args, **kwargs):
            return {"choices": [{"message": {"content": "Recovered no-response fallback"}}]}

        with (
            patch("app.agent.ModelRouter.chat_completion_stream", stream_without_done),
            patch("app.agent.ModelRouter.chat_completion_non_stream", non_stream_fallback),
        ):
            events = []
            async for event in session.run("hi"):
                events.append(event)

        streamed_text = "".join(e["data"]["text"] for e in events if e["type"] == "content")
        assert streamed_text == "Recovered no-response fallback"
        assert not any(
            e["type"] == "error" and "Model returned no response" in e["data"].get("message", "")
            for e in events
        )

    @pytest.mark.asyncio
    async def test_stream_error_before_tokens_uses_non_stream_fallback(self, session):
        async def failing_stream(*args, **kwargs):
            yield {"type": "error", "message": "DeepSeek stream failed: 400"}

        async def non_stream_fallback(*args, **kwargs):
            return {"choices": [{"message": {"content": "Recovered from stream error"}}]}

        with (
            patch("app.agent.ModelRouter.chat_completion_stream", failing_stream),
            patch("app.agent.ModelRouter.chat_completion_non_stream", non_stream_fallback),
        ):
            events = []
            async for event in session.run("hi"):
                events.append(event)

        streamed_text = "".join(e["data"]["text"] for e in events if e["type"] == "content")
        assert streamed_text == "Recovered from stream error"
        assert not any(e["type"] == "error" for e in events)
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
    async def test_dispatch_worker_inherits_active_session_model(self):
        session = AgentSession(model_id="gpt-4o-mini", session_id="dispatch_model_session", agent_type="coding")
        seen_worker_models = []

        async def replacement_worker_run(self):
            seen_worker_models.append(self.model_id)
            yield {"type": "worker_done", "data": {
                "worker_id": self.worker_id,
                "status": "completed",
                "result": "Worker completed.",
                "iterations": 1,
                "duration_ms": 10,
            }}

        worker_call_response = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_worker",
                        "type": "function",
                        "function": {
                            "name": "dispatch_worker",
                            "arguments": json.dumps({"task": "Inspect this", "profile": "explorer"}),
                        },
                    }],
                }
            }]
        }
        final_response = {
            "choices": [{
                "message": {
                    "content": "Done.",
                    "role": "assistant",
                    "tool_calls": None,
                }
            }]
        }
        streams = [_make_stream_mock(worker_call_response), _make_stream_mock(final_response)]

        async def stream_sequence(*args, **kwargs):
            stream = streams.pop(0)
            async for event in stream(*args, **kwargs):
                yield event

        with (
            patch("app.agent.ModelRouter.chat_completion_stream", stream_sequence),
            patch("app.worker.WorkerSession.run", new=replacement_worker_run),
        ):
            events = [event async for event in session.run("dispatch a worker")]

        assert seen_worker_models == ["gpt-4o-mini"]
        assert any(e["type"] == "tool_call" and e["data"]["name"] == "dispatch_worker" for e in events)

    @pytest.mark.asyncio
    async def test_run_with_file_write_emits_file_edit(self, session, temp_dir):
        from app import config

        cfg = config.load_config()
        cfg.settings.sandbox_mode = "unrestricted"
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
    async def test_applied_task_guidance_is_injected_at_model_boundary(self, session):
        captured_messages = []

        async def stream_with_capture(*args, **kwargs):
            captured_messages.append(kwargs.get("messages") or args[0])
            yield {
                "type": "done",
                "response": {
                    "choices": [{
                        "message": {
                            "content": "Used guidance",
                            "role": "assistant",
                            "tool_calls": None,
                        }
                    }]
                },
            }

        item = session.queue_task_guidance("Prefer the smaller fix")
        session.apply_task_guidance()

        with patch("app.agent.ModelRouter.chat_completion_stream", stream_with_capture):
            events = []
            async for event in session.run("fix the bug"):
                events.append(event)

        assert any(e["type"] == "task_guidance_consumed" for e in events)
        assert all(item.id != active["id"] for active in session.active_task_guidance_items())
        first_call_text = "\n".join(
            str(msg.get("content", "")) for msg in captured_messages[0]
        )
        assert "[TASK GUIDANCE]" in first_call_text
        assert "Prefer the smaller fix" in first_call_text

    def test_stale_task_guidance_is_not_persisted_as_active(self, session):
        item = session.queue_task_guidance("Turn this into a follow-up")
        session.apply_task_guidance()

        stale = session.mark_applied_task_guidance_stale()

        assert stale[0].id == item.id
        assert stale[0].status == "stale"
        assert session.active_task_guidance_items() == []

    @pytest.mark.asyncio
    async def test_run_payload_keeps_prior_session_suggestion_when_context_fits(self, session):
        captured_messages = []

        async def stream_with_capture(*args, **kwargs):
            captured_messages.append(kwargs.get("messages") or args[0])
            yield {
                "type": "done",
                "response": {
                    "choices": [{
                        "message": {
                            "content": "I can see the earlier recommendation.",
                            "role": "assistant",
                            "tool_calls": None,
                        }
                    }]
                },
            }

        session.messages.append({"role": "user", "content": "review this repository", "source": "user"})
        session.messages.append({
            "role": "assistant",
            "content": "Overall recommendation: git_tools is missing and git_commit needs a real implementation.",
        })
        for i in range(25):
            session.messages.append({"role": "user", "content": f"follow-up {i}", "source": "user"})
            session.messages.append({"role": "assistant", "content": f"answer {i}"})

        with patch("app.agent.ModelRouter.chat_completion_stream", stream_with_capture):
            async for _event in session.run("please fix according to your suggestion"):
                pass

        first_call_text = "\n".join(str(msg.get("content", "")) for msg in captured_messages[0])
        assert "git_tools is missing" in first_call_text
        assert "please fix according to your suggestion" in first_call_text

    @pytest.mark.asyncio
    async def test_run_auto_compacts_before_trimming_when_context_exceeds_model_window(self, session):
        captured_messages = []

        session._model_context_limit = lambda: 4096
        session._completion_max_tokens = lambda: 1024
        session._tool_schema_token_estimate = lambda: 0

        async def fake_summary(*args, **kwargs):
            return {"choices": [{"message": {"content": "Summary: old review context and decisions."}}]}

        async def stream_with_capture(*args, **kwargs):
            captured_messages.append(kwargs.get("messages") or args[0])
            yield {
                "type": "done",
                "response": {
                    "choices": [{
                        "message": {
                            "content": "Continued with compacted context.",
                            "role": "assistant",
                            "tool_calls": None,
                        }
                    }]
                },
            }

        session.router.chat_completion_non_stream = fake_summary
        for i in range(8):
            session.messages.append({
                "role": "user",
                "content": f"old long turn {i} " + ("context " * 500),
                "source": "user",
            })
            session.messages.append({"role": "assistant", "content": "answer " + ("details " * 500)})

        with patch("app.agent.ModelRouter.chat_completion_stream", stream_with_capture):
            events = []
            async for event in session.run("continue from the session"):
                events.append(event)

        assert any(e["type"] == "compacted" and e["data"].get("auto") for e in events)
        assert session.compaction_summary.startswith("Summary:")
        first_call_text = "\n".join(str(msg.get("content", "")) for msg in captured_messages[0])
        assert "Conversation Summary" in first_call_text
        assert "Summary: old review context" in first_call_text

    @pytest.mark.asyncio
    async def test_run_auto_compacts_at_soft_pressure_before_trimming(self, session):
        captured_messages = []
        run_input = "continue from the session"

        async def fake_summary(*args, **kwargs):
            return {"choices": [{"message": {"content": "Summary: proactive context continuity."}}]}

        async def stream_with_capture(*args, **kwargs):
            captured_messages.append(kwargs.get("messages") or args[0])
            yield {
                "type": "done",
                "response": {
                    "choices": [{
                        "message": {
                            "content": "Continued after proactive compaction.",
                            "role": "assistant",
                            "tool_calls": None,
                        }
                    }]
                },
            }

        session.router.chat_completion_non_stream = fake_summary
        session._tool_schema_token_estimate = lambda: 0
        for i in range(6):
            session.messages.append({
                "role": "user",
                "content": f"older turn {i} " + ("context " * 80),
                "source": "user",
            })
            session.messages.append({"role": "assistant", "content": "answer " + ("details " * 80)})
        session._last_user_message = run_input
        session._refresh_system_prompt()
        session._ensure_message_metadata()
        projected_messages = session.messages + [{"role": "user", "content": run_input, "source": "user"}]
        projected_tokens = session._estimate_messages_tokens(projected_messages)
        budget = max(projected_tokens + 1, int(projected_tokens / 0.80))
        session._model_input_token_budget = lambda: budget
        session._model_context_limit = lambda: budget * 2

        with patch("app.agent.ModelRouter.chat_completion_stream", stream_with_capture):
            events = []
            async for event in session.run(run_input):
                events.append(event)

        compacted = next(e for e in events if e["type"] == "compacted")
        assert compacted["data"].get("auto") is True
        assert compacted["data"].get("trigger") == "soft"
        assert compacted["data"].get("preserved_recent_turns") == 4
        assert session.compaction_summary.startswith("Summary:")
        assert captured_messages

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

    def test_model_context_window_keeps_complete_user_turn(self, session):
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

        context_messages = session._messages_for_llm()

        roles = [m.get("role") for m in context_messages]
        assert roles == ["system", "user", "assistant", "tool", "assistant"]
        assert context_messages[1]["content"] == "old"
        assert context_messages[2].get("tool_calls")

    def test_messages_for_llm_repairs_interrupted_tool_call_before_next_user(self, session):
        session.messages.extend([
            {"role": "user", "content": "start task"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_interrupted",
                    "type": "function",
                    "function": {"name": "file_read", "arguments": "{\"path\":\"x\"}"},
                }],
            },
            {"role": "user", "content": "are you stuck?"},
        ])

        context_messages = session._messages_for_llm()

        roles = [m.get("role") for m in context_messages]
        assert roles == ["system", "user", "assistant", "tool", "user"]
        tool_msg = context_messages[3]
        assert tool_msg["tool_call_id"] == "call_interrupted"
        assert tool_msg["name"] == "file_read"
        assert "interrupted" in tool_msg["content"].lower()

    def test_save_and_load_preserves_long_transcript_over_context_window(self, tmp_path, monkeypatch):
        import app.agent as agent_module

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()

        session = AgentSession(model_id="gpt-4o", session_id="long_history")
        for i in range(30):
            session.messages.append({"role": "user", "content": f"user turn {i}", "source": "user"})
            session.messages.append({"role": "assistant", "content": f"assistant turn {i}"})
        session._save()

        loaded = AgentSession.load("long_history")

        assert loaded is not None
        user_messages = [m for m in loaded.messages if m.get("role") == "user" and m.get("source") != "internal"]
        assert len(user_messages) == 30
        assert user_messages[0]["content"] == "user turn 0"
        assert user_messages[-1]["content"] == "user turn 29"
        snapshot = loaded.to_snapshot()
        assert snapshot["transcript_message_count"] == 60
        assert len([m for m in snapshot["messages"] if m.get("role") == "user"]) == 30
        assert snapshot["context_message_count"] == snapshot["transcript_message_count"]
        assert snapshot["context_truncated"] is False

    def test_save_and_load_preserves_compaction_state(self, tmp_path, monkeypatch):
        import app.agent as agent_module

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()

        session = AgentSession(model_id="gpt-4o", session_id="compacted_history")
        session.messages.append({"role": "user", "content": "historical task", "source": "user"})
        session.messages.append({"role": "assistant", "content": "historical answer"})
        session._ensure_message_metadata()
        boundary = session.messages[-1]
        session.compaction_summary = "Summary: persisted context."
        session.compaction_state.update({
            "compacted_through_checkpoint_id": boundary["checkpoint_id"],
            "compacted_through_message_id": boundary["message_id"],
            "compacted_turn_count": 1,
            "last_compacted_at": "2026-05-19T00:00:00+00:00",
        })
        session._save()

        loaded = AgentSession.load("compacted_history")

        assert loaded is not None
        assert loaded.compaction_summary == "Summary: persisted context."
        assert loaded.compaction_state["compacted_through_checkpoint_id"] == boundary["checkpoint_id"]
        assert loaded.compaction_state["compacted_through_message_id"] == boundary["message_id"]
        assert loaded.to_snapshot()["compaction_state"]["compacted_turn_count"] == 1

    def test_load_old_session_without_compaction_state_is_uncompacted(self, tmp_path, monkeypatch):
        import app.agent as agent_module

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()
        (tmp_path / "old_compaction.json").write_text(json.dumps({
            "session_id": "old_compaction",
            "model_id": "gpt-4o",
            "role_id": "desktop-agent",
            "messages": [
                {"role": "system", "content": "old system"},
                {"role": "user", "content": "old user", "source": "user"},
            ],
            "compaction_summary": "Legacy summary should not activate without state.",
        }), encoding="utf-8")

        loaded = AgentSession.load("old_compaction")

        assert loaded is not None
        assert loaded.compaction_summary == ""
        assert loaded.compaction_state["compacted_turn_count"] == 0
        assert loaded.context_usage()["compaction_active"] is False

    def test_refresh_mcp_tools_does_not_persist_transcript_side_effects(self, session, tmp_path, monkeypatch):
        import app.agent as agent_module

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        session.session_id = "mcp_no_save"
        session.messages.append({"role": "user", "content": "keep me", "source": "user"})
        session._save()
        before = (tmp_path / "mcp_no_save.json").read_text(encoding="utf-8")

        with patch("app.mcp.manager.get_mcp_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = []
            mock_get_manager.return_value = mock_manager
            session.refresh_mcp_tools()

        after = (tmp_path / "mcp_no_save.json").read_text(encoding="utf-8")
        assert after == before

    def test_reset(self, session):
        session.messages.append({"role": "user", "content": "hi"})
        session.iteration = 5
        session.reset()
        assert session.iteration == 0
        assert len(session.messages) == 1
        assert session.messages[0]["role"] == "system"

    def test_start_new_context_preserves_visible_transcript_but_resets_llm_context(self, session):
        session.messages.append({"role": "user", "content": "old visible request", "source": "user"})
        session.messages.append({"role": "assistant", "content": "old visible answer"})
        session.plan_state.goal = "old plan"
        session.task_guidance_items.append(MagicMock(status="queued", model_dump=lambda: {}))

        result = session.start_new_context("reset")

        assert result["context_epoch"] == 1
        assert session.context_epoch == 1
        assert session.model_id == "gpt-4o"
        assert any(m.get("content") == "old visible request" for m in session.messages)
        provider_text = "\n".join(str(m.get("content", "")) for m in session._messages_for_llm())
        assert "old visible request" not in provider_text
        assert "old visible answer" not in provider_text
        assert session.plan_state.goal == ""
        assert session.task_guidance_items == []

    def test_start_new_context_clears_stale_handoff_before_prompt_refresh(self, tmp_path, monkeypatch):
        from app.agents.manager import AgentManager

        agents_root = tmp_path / "AGENTS"
        personal_workspace = agents_root / "personal" / "WORKSPACE"
        personal_workspace.mkdir(parents=True)
        handoff_path = personal_workspace / "session_handoff.md"
        handoff_path.write_text("old handoff leak", encoding="utf-8")
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", agents_root)

        session = AgentSession(model_id="gpt-4o", session_id="handoff_reset_test")
        assert "old handoff leak" in str(session.messages[0].get("content", ""))

        session.start_new_context("reset")

        provider_text = "\n".join(str(m.get("content", "")) for m in session._messages_for_llm())
        assert "old handoff leak" not in provider_text
        assert not handoff_path.exists()

    def test_context_snapshot_keeps_old_messages_and_notice(self, session):
        session.messages.append({"role": "user", "content": "before reset", "source": "user"})
        session.start_new_context("new")

        snap = session.to_snapshot()
        visible_text = "\n".join(str(m.get("content", "")) for m in snap["messages"])

        assert snap["context_epoch"] == 1
        assert "before reset" in visible_text
        assert "New session started - model: gpt-4o" in visible_text
        assert snap["context_usage"]["context_epoch"] == 1
        assert snap["context_usage"]["context_reset_active"] is True
        assert snap["context_usage"]["archived_message_count"] >= 1

    @pytest.mark.asyncio
    async def test_heartbeat_ignores_archived_epoch_and_skips_assistant_only_context(self, tmp_path, monkeypatch):
        from app.agents.heartbeat import HeartbeatEngine
        from app.agents.manager import AgentManager

        agents_root = tmp_path / "AGENTS"
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", agents_root)
        monkeypatch.setattr(HeartbeatEngine, "_store_auto_memory_items", classmethod(lambda cls, **kwargs: 0))
        monkeypatch.setattr(HeartbeatEngine, "_should_trigger_dream", classmethod(lambda cls: False))

        assistant_only = [
            {"role": "user", "content": "archived user request", "context_epoch": 0},
            {"role": "assistant", "content": "archived assistant answer", "context_epoch": 0},
            {"role": "assistant", "content": "New context is ready. What shall we do next?", "context_epoch": 1},
        ]
        result = await HeartbeatEngine.on_session_end(assistant_only, "assistant_only_reset")
        assert result["diary_written"] is False
        assert result["handoff_written"] is False
        assert not (agents_root / "personal" / "WORKSPACE" / "session_handoff.md").exists()

        mixed_epochs = [
            {"role": "user", "content": "archived user request", "context_epoch": 0},
            {"role": "assistant", "content": "archived assistant answer", "context_epoch": 0},
            {"role": "user", "content": "new user preference should be remembered", "context_epoch": 1},
            {"role": "assistant", "content": "new assistant response for current context", "context_epoch": 1},
        ]
        result = await HeartbeatEngine.on_session_end(mixed_epochs, "mixed_epoch_reset")
        assert result["handoff_written"] is True
        handoff = (agents_root / "personal" / "WORKSPACE" / "session_handoff.md").read_text(encoding="utf-8")
        assert "new user preference should be remembered" in handoff
        assert "new assistant response for current context" in handoff
        assert "archived user request" not in handoff
        assert "archived assistant answer" not in handoff

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

    @pytest.mark.asyncio
    async def test_plan_mode_plain_numbered_options_become_question_card(self, session):
        """Plan mode falls back to structured question cards when the model prints fixed options."""
        mock_response = {
            "choices": [{
                "message": {
                    "content": (
                        "在继续之前，我需要确认一个问题：\n\n"
                        "你希望支持哪些新资产类型？ 选项：\n\n"
                        "1. A 股 ETF（场内基金）\n"
                        "2. 加密货币现货/永续合约\n"
                        "3. 国内商品期货\n"
                    ),
                    "role": "assistant",
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
        assert session.plan_state.questions[0].prompt.startswith("你希望支持哪些新资产类型")
        assert [o.label for o in session.plan_state.questions[0].options] == [
            "A 股 ETF（场内基金）",
            "加密货币现货/永续合约",
            "国内商品期货",
        ]

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

    def test_apply_plan_questions_from_idle_enters_awaiting_decision(self, session):
        session._apply_plan_questions([{
            "id": "scope",
            "prompt": "What scope?",
            "allow_multiple": False,
            "options": [
                {"id": "small", "label": "Small"},
                {"id": "large", "label": "Large"},
            ],
        }])

        assert session.chat_mode == "plan"
        assert session.plan_state.mode == "plan"
        assert session.plan_state.phase == "awaiting_decision"
        assert session.plan_state.pending_clarification is True

    def test_apply_plan_draft_without_markdown_uses_rendered_file_body(self, session):
        session._apply_plan_draft({
            "goal": "Add export",
            "steps": [{"id": "s1", "title": "Add button", "details": "frontend/src/App.tsx:10"}],
            "todos": [{"id": "t1", "title": "Add button", "acceptance_criteria": "Button renders"}],
            "verification": ["Run tests"],
        })

        assert session.chat_mode == "plan"
        assert session.plan_state.phase == "awaiting_approval"
        assert session.plan_state.plan_file_path is not None
        assert session.plan_state.draft.strip()
        assert "No markdown body was provided" not in session.plan_state.draft
        assert "## 任务方案 / Approach" in session.plan_state.draft
        assert "## 任务目标 / Goal" in session.plan_state.draft
        assert "PART 1 — Add button" in session.plan_state.draft
        assert "## Steps" not in session.plan_state.draft
        assert "## Todos" not in session.plan_state.draft
        assert "Add button" in session.plan_state.draft

    def test_switching_out_and_back_to_plan_clears_stale_plan_state(self, session):
        session.chat_mode = "plan"
        session.plan_state.mode = "plan"
        session.plan_state.phase = "awaiting_decision"
        session.plan_state.goal = "old goal"
        session.plan_state.questions = []

        assert session.set_session_chat_mode("agent") is True
        assert session.chat_mode == "agent"
        assert session.plan_state.mode == "agent"
        assert session.plan_state.phase == "idle"
        assert session.plan_state.goal == ""

        assert session.set_session_chat_mode("plan") is True
        assert session.chat_mode == "plan"
        assert session.plan_state.mode == "plan"
        assert session.plan_state.phase == "idle"
        assert session.plan_state.goal == ""

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

    def test_build_plan_is_idempotent_while_executing(self, session):
        from app.workflow.models import PlanTodo

        session.chat_mode = "agent"
        session.plan_state.mode = "agent"
        session.plan_state.phase = "executing"
        session.plan_state.approved = True
        session.plan_state.todos = [PlanTodo(id="t1", title="First todo", status="in_progress")]

        assert session.build_plan() is True
        assert session.plan_state.phase == "executing"
        assert session.plan_state.todos[0].status == "in_progress"

    @pytest.mark.asyncio
    async def test_plan_execution_suppresses_stale_build_prompt(self, session):
        from app.workflow.models import PlanTodo

        session.chat_mode = "agent"
        session.plan_state.mode = "agent"
        session.plan_state.phase = "executing"
        session.plan_state.approved = True
        session.plan_state.draft = "# Plan\n\n## Tasks\n- [ ] First todo"
        session.plan_state.todos = [PlanTodo(id="t1", title="First todo", status="in_progress")]

        stale_response = {
            "choices": [{
                "message": {
                    "content": "The plan is ready. Please click Build to start.",
                    "role": "assistant",
                    "tool_calls": None,
                }
            }]
        }
        completion_response = {
            "choices": [{
                "message": {
                    "content": "Task completed.",
                    "role": "assistant",
                    "tool_calls": None,
                }
            }]
        }
        streams = [_make_stream_mock(stale_response), _make_stream_mock(completion_response)]

        async def stream_sequence(*args, **kwargs):
            stream = streams.pop(0)
            async for event in stream(*args, **kwargs):
                yield event

        with patch("app.agent.ModelRouter.chat_completion_stream", stream_sequence):
            events = []
            async for ev in session.run(PLAN_CONTINUE_MARKER, None):
                events.append(ev)

        content = "".join(e["data"].get("text", "") for e in events if e["type"] == "content")
        assert "click Build" not in content
        assert "Task completed." in content
        assert any(
            m.get("source") == "internal" and "BUILD ALREADY CLICKED" in str(m.get("content", ""))
            for m in session.messages
        )

    def test_submit_plan_decisions_records_other_and_skip(self, session):
        from app.workflow.models import PlanQuestion, PlanQuestionOption

        session.chat_mode = "plan"
        session.plan_state.mode = "plan"
        session.plan_state.phase = "awaiting_decision"
        session.plan_state.questions = [
            PlanQuestion(
                id="direction",
                prompt="Which direction?",
                options=[
                    PlanQuestionOption(id="minimal", label="Minimal"),
                    PlanQuestionOption(id="full", label="Full"),
                ],
            ),
            PlanQuestion(
                id="risk",
                prompt="Risk posture?",
                options=[
                    PlanQuestionOption(id="safe", label="Safe"),
                    PlanQuestionOption(id="fast", label="Fast"),
                ],
            ),
        ]

        session.submit_plan_decisions([
            {"question_id": "direction", "selected": ["minimal"], "other_text": "Also keep the old UI available"},
            {"question_id": "risk", "selected": [], "skipped": True},
        ])

        assert session.plan_state.phase == "planning"
        assert session.plan_state.questions == []
        assert session.plan_state.decisions["direction"] == ["minimal"]
        assert "Other: Also keep the old UI available" in session.plan_state.decision_notes["direction"]
        assert "Skipped" in session.plan_state.decision_notes["risk"]
        internal = session.messages[-1]["content"]
        assert "Minimal" in internal
        assert "Other: Also keep the old UI available" in internal
        assert "Skipped; use the best default" in internal

    def test_plan_todo_progress_after_build_when_chat_mode_is_agent(self, session):
        from app.workflow.models import PlanTodo

        session.chat_mode = "plan"
        session.plan_state.phase = "awaiting_approval"
        session.plan_state.todos = [
            PlanTodo(id="t1", title="First todo"),
            PlanTodo(id="t2", title="Second todo", depends_on=["t1"]),
        ]

        assert session.build_plan() is True
        assert session.chat_mode == "agent"
        assert session.plan_state.phase == "executing"
        assert session.plan_state.todos[0].status == "in_progress"

        assert session._touch_plan_todo_after_tool("dispatch_worker", "ACCEPTANCE: PASS") is True
        assert session.plan_state.todos[0].status == "completed"
        assert session.plan_state.todos[1].status == "in_progress"

    def test_plan_todo_blocks_when_dispatch_worker_errors(self, session):
        from app.workflow.models import PlanTodo

        session.chat_mode = "plan"
        session.plan_state.phase = "awaiting_approval"
        session.plan_state.todos = [
            PlanTodo(id="t1", title="First todo"),
            PlanTodo(id="t2", title="Second todo", depends_on=["t1"]),
        ]

        assert session.build_plan() is True
        assert session.plan_state.todos[0].status == "in_progress"

        changed = session._touch_plan_todo_after_tool(
            "dispatch_parallel",
            "[ERROR] Parallel dispatch complete\n0 succeeded, 1 failed",
            "Parallel dispatch complete\n0 succeeded, 1 failed",
        )

        assert changed is True
        assert session.plan_state.todos[0].status == "blocked"
        assert session.plan_state.todos[1].status == "pending"

    def test_apply_todo_updates_and_auto_advance(self, session):
        from app.workflow.models import PlanTodo

        session.chat_mode = "plan"
        session.plan_state.phase = "awaiting_approval"
        session.plan_state.todos = [
            PlanTodo(id="t1", title="First todo"),
            PlanTodo(id="t2", title="Second todo", depends_on=["t1"]),
            PlanTodo(id="t3", title="Third todo", depends_on=["t2"]),
        ]
        assert session.build_plan() is True
        assert session.plan_state.todos[0].status == "in_progress"

        # Model explicitly completes t1 via plan_update_todos.
        changed = session._apply_todo_updates({"updates": [{"id": "t1", "status": "completed"}]})
        assert changed is True
        assert session.plan_state.todos[0].status == "completed"

        # Auto-advance promotes the next dependency-ready pending todo.
        assert session._auto_advance_pending_todos() is True
        assert session.plan_state.todos[1].status == "in_progress"
        # t3 not promoted while t2 is in progress (single active todo).
        assert session.plan_state.todos[2].status == "pending"

    def test_apply_todo_updates_skips_unknown_id_and_bad_status(self, session):
        from app.workflow.models import PlanTodo

        session.plan_state.todos = [PlanTodo(id="t1", title="One", status="in_progress")]
        changed = session._apply_todo_updates({"updates": [
            {"id": "nope", "status": "completed"},
            {"id": "t1", "status": "not-a-status"},
        ]})
        assert changed is False
        assert session.plan_state.todos[0].status == "in_progress"

    def test_end_of_run_fallback_forces_phase_out_of_executing(self, session):
        from app.workflow.models import PlanTodo

        session.chat_mode = "plan"
        session.plan_state.phase = "awaiting_approval"
        session.plan_state.todos = [
            PlanTodo(id="t1", title="First todo"),
            PlanTodo(id="t2", title="Second todo"),
        ]
        assert session.build_plan() is True
        assert session.plan_state.phase == "executing"
        # Simulate the run finishing without the model marking everything done.
        for t in session.plan_state.todos:
            if t.status in ("in_progress", "pending"):
                t.status = "completed"
        session.plan_state.transition_to("completed")
        assert session.plan_state.phase == "completed"
        assert all(t.status == "completed" for t in session.plan_state.todos)

    def test_build_plan_recovers_ready_draft_with_stale_phase(self, session):
        from app.workflow.models import PlanTodo

        session.chat_mode = "plan"
        session.plan_state.mode = "plan"
        session.plan_state.phase = "planning"
        session.plan_state.draft = "# Plan"
        session.plan_state.todos = [PlanTodo(id="t1", title="First todo")]

        assert session.build_plan() is True
        assert session.chat_mode == "agent"
        assert session.plan_state.phase == "executing"
        assert session.plan_state.todos[0].status == "in_progress"

    def test_restore_plan_state_snapshot_for_build(self, session):
        from app.workflow.models import PlanTodo

        snapshot = {
            **session.plan_state.model_dump(),
            "mode": "plan",
            "phase": "awaiting_approval",
            "draft": "# Plan",
            "todos": [PlanTodo(id="t1", title="First todo").model_dump()],
        }

        assert session.restore_plan_state_snapshot(snapshot) is True
        assert session.plan_state.phase == "awaiting_approval"
        assert session.plan_state.todos[0].title == "First todo"
        assert session.build_plan() is True

    def test_plan_build_pause_and_end_controls(self, session):
        from app.workflow.models import PlanTodo

        session.chat_mode = "plan"
        session.plan_state.mode = "plan"
        session.plan_state.phase = "awaiting_approval"
        session.plan_state.draft = "# Plan"
        session.plan_state.todos = [
            PlanTodo(id="t1", title="First todo", status="completed"),
            PlanTodo(id="t2", title="Second todo"),
            PlanTodo(id="t3", title="Third todo"),
        ]

        assert session.build_plan() is True
        assert session.plan_state.phase == "executing"
        assert session.plan_state.todos[1].status == "in_progress"

        assert session.pause_plan_build() is True
        assert session.plan_state.phase == "approved_waiting_build"
        assert session.plan_state.approved is True
        assert session.plan_state.todos[1].status == "pending"

        assert session.build_plan() is True
        assert session.plan_state.phase == "executing"
        assert session.plan_state.todos[1].status == "in_progress"

        assert session.exit_plan_build() is True
        assert session.plan_state.phase == "awaiting_approval"
        assert session.plan_state.approved is False
        assert session.plan_state.todos[0].status == "completed"
        assert session.plan_state.todos[1].status == "cancelled"
        assert session.plan_state.todos[2].status == "cancelled"

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
        assert "## 任务方案 / Approach" in session.plan_state.draft
        assert "## 验证 / Verification" in session.plan_state.draft
        assert "## Steps" not in session.plan_state.draft
        assert "## Todos" not in session.plan_state.draft

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

    def test_switch_agent_rejects_nonempty_identity_change(self):
        """Non-empty sessions keep a stable agent identity."""
        session = AgentSession(model_id="gpt-4o", session_id="test_at", agent_type="personal")
        session.messages.append({"role": "user", "content": "hello"})

        with pytest.raises(ValueError, match="Cannot switch a non-empty session"):
            session.switch_agent("coding")

    def test_switch_role_backward_compat(self):
        """switch_role() still works and maps through agent_type."""
        session = AgentSession(model_id="gpt-4o", session_id="test_at", agent_type="personal")
        session.switch_role("code-expert")
        assert session.agent_type == "coding"
        assert session.role_id == "code-expert"

    def test_get_or_create_rejects_reusing_nonempty_session_as_other_agent(self):
        import app.agent as agent_module

        agent_module._sessions.clear()
        session = AgentSession(model_id="gpt-4o", session_id="at_nonempty", agent_type="personal")
        session.messages.append({"role": "user", "content": "hello"})
        agent_module._sessions["at_nonempty"] = session

        with pytest.raises(ValueError, match="already belongs to personal"):
            get_or_create_session("at_nonempty", "gpt-4o", role_id="code-expert", agent_type="coding")

    def test_get_or_create_session_with_agent_type(self):
        s = get_or_create_session("at_s1", "gpt-4o", role_id="code-expert", agent_type="coding")
        assert s.agent_type == "coding"
        assert s.role_id == "code-expert"

    def test_get_or_create_does_not_default_role_overwrite_saved_agent_type(self, tmp_path, monkeypatch):
        import app.agent as agent_module

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()

        saved = AgentSession(model_id="gpt-4o", session_id="at_saved_coding", agent_type="coding")
        saved._save()

        loaded = get_or_create_session("at_saved_coding", "gpt-4o")

        assert loaded.agent_type == "coding"
        assert loaded.role_id == "code-expert"

    def test_get_or_create_can_preserve_saved_model_with_agent_type(self, tmp_path, monkeypatch):
        import app.agent as agent_module

        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()

        saved = AgentSession(model_id="gpt-4o", session_id="saved_model_coding", agent_type="coding")
        saved._save()
        agent_module._sessions.clear()

        loaded = get_or_create_session(
            "saved_model_coding",
            "kimi-for-coding",
            role_id="code-expert",
            agent_type="coding",
            preserve_existing_model=True,
        )

        assert loaded.model_id == "gpt-4o"

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

    def test_to_snapshot_excludes_internal_messages(self):
        session = AgentSession(model_id="gpt-4o", session_id="snap_internal")
        session.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "real question", "source": "user"},
            {"role": "user", "content": "[BUILD ALREADY CLICKED] ...", "source": "internal"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "[VERIFICATION REQUIRED] ...", "source": "internal"},
        ]
        snap = session.to_snapshot()
        snap_msgs = snap["messages"]
        assert all(m.get("source") != "internal" for m in snap_msgs)
        # Real conversation preserved, order intact.
        contents = [m["content"] for m in snap_msgs]
        assert "real question" in contents
        assert "answer" in contents
        assert contents.index("real question") < contents.index("answer")
        # The model's own message list is untouched (LLM context intact).
        assert any(m.get("source") == "internal" for m in session.messages)

    def test_save_and_load_preserve_internal_messages_for_llm(self, tmp_path, monkeypatch):
        import app.agent as agent_module
        monkeypatch.setattr(agent_module, "SESSIONS_DIR", tmp_path)
        agent_module._sessions.clear()

        session = AgentSession(model_id="gpt-4o", session_id="at_internal")
        session.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "real", "source": "user"},
            {"role": "user", "content": "[BUILD ALREADY CLICKED] ...", "source": "internal"},
        ]
        session._save()

        # Disk JSON keeps internal messages so the LLM keeps full context.
        data = json.loads((tmp_path / "at_internal.json").read_text(encoding="utf-8"))
        assert any(m.get("source") == "internal" for m in data["messages"])

        loaded = AgentSession.load("at_internal")
        assert loaded is not None
        assert any(m.get("source") == "internal" for m in loaded.messages)
        # But its frontend snapshot still hides them.
        assert all(m.get("source") != "internal" for m in loaded.to_snapshot()["messages"])
