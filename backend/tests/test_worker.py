"""Tests for WorkerSession - lightweight worker agent."""
import pytest

from app.worker import WorkerSession, WORKER_PROFILES


class TestWorkerSession:
    def test_worker_profile_defaults(self):
        profile = WORKER_PROFILES["code"]
        assert profile.name == "code"
        assert "file_read" in profile.tools
        assert "dispatch_worker" not in profile.tools
        assert profile.max_iterations == 1000
        assert len(profile.system_prompt_extra) > 0
        assert "Read files before editing" in profile.system_prompt_extra

    def test_worker_init_builds_system_and_task_messages(self):
        worker = WorkerSession(
            worker_id="w1",
            task="Write a test",
            profile_name="code",
            model_id="gpt-4o",
        )
        assert len(worker.messages) == 2
        assert worker.messages[0]["role"] == "system"
        assert "Task: Write a test" in worker.messages[1]["content"]

    def test_worker_init_with_context_files(self):
        worker = WorkerSession(
            worker_id="w1",
            task="Fix tests",
            profile_name="code",
            model_id="gpt-4o",
            context_files=["src/a.py", "tests/test_a.py"],
        )
        assert "src/a.py" in worker.messages[1]["content"]
        assert "tests/test_a.py" in worker.messages[1]["content"]

    def test_worker_injects_matched_enabled_skills(self, monkeypatch):
        from app.skills import SkillManager

        monkeypatch.setattr(
            SkillManager,
            "match_skills",
            classmethod(lambda cls, *args, **kwargs: ["using-superpowers", "systematic-debugging"]),
        )
        monkeypatch.setattr(
            SkillManager,
            "build_skill_prompt",
            classmethod(lambda cls, skill_ids: "\n".join(f"## Skill: {skill_id}" for skill_id in skill_ids)),
        )

        worker = WorkerSession(
            worker_id="w1",
            task="Fix a crashy bug and add a regression test",
            profile_name="code",
            model_id="gpt-4o",
            agent_type="coding",
        )

        system_prompt = worker.messages[0]["content"]
        assert worker.matched_skills == ["systematic-debugging"]
        assert "## Worker Active Skills" in system_prompt
        assert "systematic-debugging" in system_prompt
        assert "using-superpowers" not in system_prompt

    @pytest.mark.asyncio
    async def test_worker_start_event_reports_matched_skills(self, mock_litellm, monkeypatch):
        from app.skills import SkillManager

        monkeypatch.setattr(
            SkillManager,
            "match_skills",
            classmethod(lambda cls, *args, **kwargs: ["verification-before-completion"]),
        )
        monkeypatch.setattr(
            SkillManager,
            "build_skill_prompt",
            classmethod(lambda cls, skill_ids: "\n".join(f"## Skill: {skill_id}" for skill_id in skill_ids)),
        )
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Task completed successfully.",
                    "role": "assistant",
                }
            }]
        }

        worker = WorkerSession("w1", "Verify the change", "code", "gpt-4o", agent_type="coding")
        events = []
        async for event in worker.run():
            events.append(event)

        assert events[0]["type"] == "worker_start"
        assert events[0]["data"]["agent_type"] == "coding"
        assert events[0]["data"]["skills"] == ["verification-before-completion"]

    @pytest.mark.asyncio
    async def test_worker_completes_with_content(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Task completed successfully.",
                    "role": "assistant",
                }
            }]
        }
        worker = WorkerSession("w1", "Say hello", "code", "gpt-4o")
        events = []
        async for event in worker.run():
            events.append(event)
        assert events[0]["type"] == "worker_start"
        assert events[-1]["type"] == "worker_done"
        assert events[-1]["data"]["status"] == "completed"
        assert "completed" in events[-1]["data"]["result"]

    @pytest.mark.asyncio
    async def test_worker_cancelled(self):
        worker = WorkerSession("w1", "Long task", "code", "gpt-4o")
        worker.cancel()
        events = []
        async for event in worker.run():
            events.append(event)
        assert events[0]["type"] == "worker_start"
        assert events[1]["type"] == "worker_done"
        assert events[1]["data"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_worker_rejects_restricted_tool(self, mock_litellm_with_tool_call):
        mock_litellm_with_tool_call.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "dispatch_worker",
                            "arguments": '{"task": "test"}',
                        }
                    }]
                }
            }]
        }
        worker = WorkerSession("w1", "Try dispatch", "code", "gpt-4o")
        events = []
        async for event in worker.run():
            events.append(event)
        tool_events = [e for e in events if e["type"] == "worker_tool_call"]
        assert len(tool_events) > 0
        assert "Unknown tool" in tool_events[0]["data"]["result"]

    @pytest.mark.asyncio
    async def test_worker_stale_detection(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                }
            }]
        }
        worker = WorkerSession("w1", "Empty task", "code", "gpt-4o")
        worker.STALE_THRESHOLD = 1
        events = []
        async for event in worker.run():
            events.append(event)
        done_event = events[-1]
        assert done_event["type"] == "worker_done"
        assert done_event["data"]["status"] == "failed"
        assert "stalled" in done_event["data"]["result"]

    @pytest.mark.asyncio
    async def test_worker_max_iterations(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Working...",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_screen_size",
                            "arguments": "{}",
                        }
                    }]
                }
            }]
        }
        worker = WorkerSession("w1", "Endless task", "code", "gpt-4o")
        worker.profile.max_iterations = 2
        events = []
        async for event in worker.run():
            events.append(event)
        done = events[-1]
        assert done["type"] == "worker_done"
        assert done["data"]["status"] == "max_iterations_reached"

    def test_code_expert_profile_registered(self):
        profile = WORKER_PROFILES["code-expert"]
        assert profile.name == "code-expert"
        assert profile.max_iterations == 1000
        assert "file_read" in profile.tools
        assert "git_branch" in profile.tools
        assert "git_clone" in profile.tools
        assert "knowledge_search" in profile.tools
        assert "knowledge_index" in profile.tools
        assert "knowledge_list" in profile.tools
        assert "ANALYZE" in profile.system_prompt_extra
        assert "Read files before editing" in profile.system_prompt_extra
        assert "VERIFY" in profile.system_prompt_extra

    def test_tdd_worker_profile_registered(self):
        profile = WORKER_PROFILES["tdd-worker"]
        assert profile.name == "tdd-worker"
        assert profile.max_iterations == 1000
        assert "file_read" in profile.tools
        assert "file_write" in profile.tools
        assert "shell_execute" in profile.tools
        assert "git_status" in profile.tools
        assert "git_diff" in profile.tools
        assert "git_commit" in profile.tools
        assert "browser_navigate" not in profile.tools
        assert "dispatch_worker" not in profile.tools
        assert "RED" in profile.system_prompt_extra
        assert "GREEN" in profile.system_prompt_extra
        assert "REFACTOR" in profile.system_prompt_extra

    def test_debugger_profile_registered(self):
        profile = WORKER_PROFILES["debugger"]
        assert profile.name == "debugger"
        assert profile.max_iterations == 1000
        assert "file_read" in profile.tools
        assert "file_search" in profile.tools
        assert "shell_execute" in profile.tools
        assert "git_status" in profile.tools
        assert "git_diff" in profile.tools
        assert "file_write" not in profile.tools
        assert "file_delete" not in profile.tools
        assert "Phase 1" in profile.system_prompt_extra
        assert "Root Cause" in profile.system_prompt_extra
        assert "NO FIXES WITHOUT ROOT CAUSE" in profile.system_prompt_extra

    def test_code_reviewer_profile_registered(self):
        profile = WORKER_PROFILES["code-reviewer"]
        assert profile.name == "code-reviewer"
        assert profile.max_iterations == 500
        assert "file_read" in profile.tools
        assert "file_search" in profile.tools
        assert "git_diff" in profile.tools
        assert "file_write" not in profile.tools
        assert "file_delete" not in profile.tools
        assert "shell_execute" not in profile.tools
        assert "git_commit" not in profile.tools
        assert "Stage 1" in profile.system_prompt_extra
        assert "Critical" in profile.system_prompt_extra

    def test_code_expert_worker_uses_correct_profile(self):
        worker = WorkerSession(
            worker_id="w1",
            task="Build a login system",
            profile_name="code-expert",
            model_id="gpt-4o",
        )
        assert worker.profile.name == "code-expert"
        assert worker.profile.max_iterations == 1000
        assert "ANALYZE" in worker.profile.system_prompt_extra
