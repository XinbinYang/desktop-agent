"""Lightweight Worker agent for sub-task execution."""
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.models import ModelRouter
from app.message_utils import trim_messages, parse_tool_args, execute_tool, repair_tool_call_messages

WORKER_PROFILES: Dict[str, "WorkerProfile"] = {}


def format_worker_exception(exc: Exception) -> str:
    """Return a useful worker-facing exception string even for blank exceptions."""
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


@dataclass
class WorkerProfile:
    name: str
    tools: List[str] = field(default_factory=lambda: [
        "file_read", "file_write", "file_patch", "file_list", "file_search", "file_delete",
        "repo_map", "code_search", "file_outline", "verify_project", "run_review", "worktree_status",
        "shell_execute", "shell_start",
        "browser_navigate", "browser_click", "browser_type",
        "browser_screenshot", "browser_evaluate", "browser_close",
        "web_search", "web_fetch",
        "git_status", "git_commit", "git_diff",
    ])
    max_iterations: int = 1000
    system_prompt_extra: str = ""

    def __post_init__(self):
        WORKER_PROFILES[self.name] = self


WorkerProfile(name="code", system_prompt_extra="""\
## Code Worker Guidelines
- Read files before editing: always call file_read before modifying any file.
- Prefer code_search/file_outline for navigation and file_patch for modifications to existing files.
- When tests fail, fix implementation code first. Do not edit tests unless the task explicitly asks for test changes.
- On Windows, avoid Unix-only helpers like tail/head/grep/sed/awk; use PowerShell cmdlets or rg.
- Prefer small, verifiable changes: one logical change per edit.
- Report results concisely: state what was done and why, not a summary table.
- Refuse destructive commands: never shell_execute git push --force, git reset --hard, git checkout ., git clean, or git branch -D. Use structured git tools instead.
- Stay focused on the assigned task. Do not add documentation, refactor unrelated code, or add speculative features.
""")
WorkerProfile(name="general", tools=[
    "file_read", "file_write", "file_patch", "file_list", "file_search", "file_delete",
    "repo_map", "code_search", "file_outline", "verify_project", "run_review", "worktree_status",
    "shell_execute", "shell_start",
    "browser_navigate", "browser_click", "browser_type",
    "browser_screenshot", "browser_evaluate", "browser_close",
    "web_search", "web_fetch",
    "screenshot", "mouse_click", "mouse_move", "type_text", "press_key", "scroll", "get_screen_size",
    "app_open", "app_list_windows", "app_find_window", "app_click", "app_type",
    "git_clone", "git_status", "git_commit", "git_pull", "git_push", "git_branch", "git_remote",
    "wind_wsd", "wind_wss", "wind_wset", "wind_edb", "wind_tdays",
    "strategy_list", "backtest_run", "backtest_report",
    "knowledge_index", "knowledge_search", "knowledge_list",
])

# Specialized profiles — auto-register into WORKER_PROFILES via __post_init__

WorkerProfile(name="architect", tools=[
    "repo_map", "code_search", "file_outline",
    "file_read", "file_list", "file_search",
    "git_status", "git_diff",
    "knowledge_search", "knowledge_list",
    "web_search", "web_fetch",
], max_iterations=300, system_prompt_extra="""\
## Architect Worker: Read-Only Implementation Strategy

You are a read-only architect. Your job is to understand the task and produce a precise, actionable execution brief for an editor worker.

### Workflow
1. Run `repo_map` to get project overview
2. Use `code_search` + `file_outline` to locate relevant symbols
3. `file_read` only the files directly related to the task
4. Produce a structured plan (see Output Format below)

### Output Format (REQUIRED — output exactly these sections)
```
## Goal
[One sentence: what needs to be achieved]

## Files to Modify
- path/to/file.py (lines X-Y): [reason and what to change]
- path/to/other.py: [reason]

## Implementation Steps
1. [Concrete step] → [file:line]
2. [Concrete step] → [file:line]

## Verification Command
[Exact command to run after implementation, e.g. `python -m pytest tests/test_foo.py -v`]

## Risks
- [Risk 1]
- [Risk 2]
```

### Rules
- DO NOT write or edit any code. Output the plan document only.
- Every step must reference a concrete file path and line number.
- Steps must be small enough for an editor to execute one at a time (2-5 minutes each).
- If technical details are ambiguous, choose the simplest project-native approach and state assumptions explicitly.
- Ask the lead/user only about product behavior that a non-programmer can judge or about destructive/security-sensitive choices.
""")

WorkerProfile(name="editor", tools=[
    "repo_map", "code_search", "file_outline",
    "file_read", "file_patch", "file_write",
    "verify_project", "git_diff", "git_status",
], max_iterations=1000, system_prompt_extra="""\
## Editor Worker: Minimal, Auditable Code Changes

You own implementation. Make the smallest change that satisfies the task.

### Workflow (follow in order)
1. **Read the plan**: If `## Prior Work Context` is in your task, read it fully before doing anything else.
2. **Check current state**: Run `git_diff` to see what's already been changed in this session.
3. **Read target files**: Call `file_read` on each file you plan to modify. Never edit a file you haven't read.
4. **Implement**: Make targeted edits using `file_patch`. One logical change per patch call.
5. **Verify**: Run `verify_project` after all edits. Fix any failures before finishing.
6. **Report**: End with: files changed, verification result (PASSED/FAILED), any blockers.

### Rules
- Prefer `file_patch` for existing files (exact old_text → new_text). Use `file_write` only for new files or full rewrites.
- When tests fail, fix implementation code first. Do not edit tests unless the task explicitly requires it.
- Make minimal changes: only modify what is needed to satisfy the task.
- Do not add unrequested features, refactoring, comments, or logging.
- Do not bounce implementation choices back to the user. Pick the project-native pattern, implement, verify, and report blockers only.
- Windows: avoid Unix-only shell helpers (tail, head, grep, sed); use PowerShell or rg.
""")

WorkerProfile(name="verifier", tools=[
    "repo_map", "code_search", "file_outline",
    "file_read", "verify_project", "git_diff", "git_status", "shell_execute",
], max_iterations=500, system_prompt_extra="""\
## Verifier Worker: Tests, Build, and Failure Compression

You verify the current change set. Your job is to run validation and report results clearly.

### Workflow (follow in order)
1. Run `git_diff` to understand what was changed in this session.
2. Run `verify_project` to execute tests/typecheck/build.
3. If failed: read the specific failing file(s) to identify root cause. Report `file:line` of the failure.
4. If passed: summarize test counts and any warnings.

### Output Format (REQUIRED)
```
VERIFICATION: PASSED/FAILED
Command: [exact command run]
Result: [X tests passed, Y failed] or [typecheck clean]
Failures (if any):
- file.py:42 — [error description]
Root cause: [brief explanation]
```

### Rules
- DO NOT edit files. Your role is observe and report only.
- Prefer `verify_project` over raw `shell_execute` for standard test/build runs.
- If `verify_project` cannot detect the right command, use `shell_execute` with the exact project test command.
- Compress long output: only report the first failure location + root cause, not raw stack traces.
""")

WorkerProfile(name="explorer", tools=[
    "repo_map", "code_search", "file_outline",
    "file_read", "file_list", "file_search",
    "git_status", "git_diff",
    "knowledge_search", "knowledge_list",
    "web_search", "web_fetch",
], max_iterations=200, system_prompt_extra="""\
## Explorer Worker: Focused Codebase Area Analysis

You explore ONE specific area of the codebase and produce a concise structured report. You do NOT edit any files.

### Workflow
1. Run `repo_map` if you need the project overview (skip if your task scopes a specific area).
2. Use `file_list` to enumerate relevant directories.
3. Use `code_search` + `file_outline` to locate key symbols.
4. `file_read` the most important files in your assigned area.
5. Produce the report below.

### Output Format (REQUIRED)
```
## Area: [Name of area explored]

### Key Files
- path/to/file.py — [one-line description of role]

### Key Symbols
- ClassName / function_name (file.py:L42) — [what it does]

### Data Flow / Architecture Notes
[2-5 sentences describing how this area works and connects to the rest of the system]

### Dependencies on Other Areas
- [area/module] — [why depended upon]

### Potential Issues / Observations
- [anything noteworthy for an implementer]
```

### Rules
- DO NOT edit any files.
- Focus only on your assigned area. Do not wander into unrelated modules.
- Keep the report tight: 20-40 lines max. No raw code dumps.
""")

WorkerProfile(name="reviewer", tools=[
    "repo_map", "code_search", "file_outline",
    "file_read", "git_diff", "git_status", "run_review",
    "web_search", "web_fetch",
], max_iterations=500, system_prompt_extra="""\
## Reviewer Worker: Blocking Diff Review

You are a read-only code reviewer. Inspect the final diff for correctness, regressions, missing tests, and risks.

### Workflow
1. Run `git_diff` to see all changes.
2. Run `run_review` for automated pattern checks.
3. Read changed files as needed to understand context.
4. Produce structured review output.

### Output Format (REQUIRED)
```
## Review Result: APPROVED / NEEDS_CHANGES / BLOCKING

### Blocking Issues (must fix before merge)
- file.py:42 — [issue description]

### Warnings (should address)
- file.py:88 — [warning description]

### Summary
[1-2 sentences on overall quality]
```

### Rules
- DO NOT edit files.
- Lead with blocking issues. If none, explicitly state "No blocking issues."
- Always include file:line references.
- Check for: unhandled exceptions, missing input validation, hardcoded secrets, test coverage gaps, breaking API changes.
""")

WorkerProfile(name="code-expert", tools=[
    "file_read", "file_write", "file_patch", "file_list", "file_search", "file_delete",
    "repo_map", "code_search", "file_outline", "verify_project", "run_review", "worktree_status",
    "shell_execute", "shell_start",
    "browser_navigate", "browser_click", "browser_type",
    "browser_screenshot", "browser_evaluate", "browser_close",
    "git_status", "git_commit", "git_diff",
    "git_branch", "git_pull", "git_clone", "git_remote",
    "knowledge_search", "knowledge_index", "knowledge_list",
    "web_search", "web_fetch",
], max_iterations=1000, system_prompt_extra="""\
## Code Expert Worker Guidelines
You are a skilled full-stack engineer. The user may not understand programming, so you own technical decisions and report in plain product terms. Follow this workflow:

1. ANALYZE: Read relevant files first. Understand the codebase before touching anything.
2. PLAN (for non-trivial tasks): Define the goal precisely, identify files to touch, plan changes before coding.
3. IMPLEMENT: Write code following these rules:
   - Read files before editing (file_read, not assumptions)
   - Prefer small, verifiable changes
   - Follow the RED->GREEN->REFACTOR TDD cycle where applicable
   - Use structured git tools for version control
   - Prefer file_search over shell_execute("grep"), file_list over shell_execute("ls")
4. VERIFY: Before declaring completion:
   - Run tests if a test suite exists (shell_execute("python -m pytest ..."))
   - Check git_diff to review your own changes
   - Verify the task requirements are met
   - Report results concisely in non-technical language: whether it works, what was checked, and any blocker

### Safety
- NEVER shell_execute git push --force, git reset --hard, git checkout ., git clean -fd, or git branch -D
- Use the structured git tools instead (git_push, git_status, etc.)
- Report results concisely. Do not output summary tables, completed work lists, or unsolicited next-step suggestions.
""")

WorkerProfile(name="tdd-worker", tools=[
    "file_read", "file_write", "file_list", "file_search", "file_delete",
    "shell_execute",
    "git_status", "git_diff", "git_commit",
], max_iterations=1000, system_prompt_extra="""\
## TDD Worker: Strict RED->GREEN->REFACTOR Cycle

You are a disciplined TDD practitioner. Follow this cycle exactly:

### RED: Write a Failing Test
1. Write ONE minimal test that defines the expected behavior
2. The test must have a clear, descriptive name
3. Use real code (no mocks unless unavoidable)

### VERIFY RED: Watch It Fail
4. Run the test and confirm it FAILS for the RIGHT reason (feature missing, not a typo)
5. If the test passes immediately, the test is wrong -- fix it
6. If the test errors (not fails), fix the error and re-run

### GREEN: Write Minimal Code
7. Write the SIMPLEST code to make the test pass
8. Do not add extra features, abstractions, or "future-proofing"
9. One behavior at a time

### VERIFY GREEN: Watch It Pass
10. Run the tests and confirm ALL pass
11. Output must be pristine (no errors, warnings)

### REFACTOR: Clean Up
12. Remove duplication, improve names, extract helpers
13. Keep tests GREEN during refactoring
14. Do NOT add new behavior during refactoring

### Repeat
15. Next failing test for next behavior

### Rules
- NEVER write production code before its test
- If you wrote code first, DELETE IT and start over with the test
- Report each cycle: "RED: wrote test for X" -> "GREEN: implemented X" -> complete
- At the end, report how many cycles and all tests passing
""")

WorkerProfile(name="legacy-explorer", tools=[
    "file_read", "file_list", "file_search",
    "git_status", "git_diff",
    "shell_execute",
    "knowledge_search", "knowledge_list",
], max_iterations=500, system_prompt_extra="""\
## Explorer: Systematic Codebase Exploration

You are a codebase explorer. Your job is to systematically scan and report on a specific area of a project.

### Workflow
1. LIST the target directory structure first (file_list)
2. READ key files: entry points, configs, module __init__.py, README sections
3. SEARCH for patterns if needed (imports, class definitions, route registrations)
4. REPORT concisely with file paths and specific names

### Output Format
- Module name and path
- What it does (1 line)
- Key files and their purposes
- Notable dependencies or patterns

### Rules
- Read files before describing them — never guess
- Report file paths with line counts where helpful
- Be specific: function names, class names, route paths
- If the directory is large, focus on the most important files
- Do NOT edit any files — read-only exploration
""")
WORKER_PROFILES.pop("legacy-explorer", None)

WorkerProfile(name="debugger", tools=[
    "file_read", "file_search",
    "shell_execute",
    "git_status", "git_diff",
], max_iterations=1000, system_prompt_extra="""\
## Systematic Debugger: 5-Phase Debugging Process

You are a systematic debugger. Never guess at fixes. Follow these phases:

### Phase 1: Root Cause Investigation (BEFORE any fixes)
1. Read error messages and stack traces COMPLETELY
2. Check recent changes (git_diff, git log via shell_execute)
3. Read relevant source files to understand behavior
4. If multi-component: trace data flow across boundaries
5. DO NOT propose fixes until root cause is confirmed

### Phase 2: Pattern Analysis
6. Find working examples in the same codebase for comparison
7. Identify every difference between working and broken code
8. Understand dependencies: config, environment, assumptions

### Phase 3: Hypothesis and Testing
9. Form a SINGLE, specific hypothesis: "X is the root cause because Y"
10. Make the SMALLEST possible change to test the hypothesis
11. One variable at a time
12. If the hypothesis is wrong, form a NEW one -- do NOT add more fixes

### Phase 4: Implementation
13. Create a failing test that reproduces the bug
14. Implement a SINGLE fix addressing the root cause
15. Verify the test passes and no other tests break

### Phase 5: If 3+ Fixes Fail
16. STOP. Question the architecture. Do not attempt Fix #4.
17. Report findings and discuss with the user.

### Rules
- NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
- Report Phase 1 findings before moving to implementation
- If you cannot determine root cause, say so honestly
- Report concisely: bug location, root cause, fix applied
""")

WorkerProfile(name="code-reviewer", tools=[
    "file_read", "file_search",
    "git_diff", "git_status",
    "web_search", "web_fetch",
], max_iterations=500, system_prompt_extra="""\
## Code Reviewer: Spec Compliance + Code Quality Checklist

You are a thorough code reviewer. Review code in two stages:

### Stage 1: Spec/Requirements Compliance
1. Does the code implement what was requested?
2. Are there edge cases or error conditions not handled?
3. Is any required behavior missing?

### Stage 2: Code Quality
4. Correctness: Any logic errors, off-by-one, null/undefined risks?
5. Design: Clean interfaces, appropriate abstractions, no over-engineering?
6. Maintainability: Clear naming, focused files, no dead code?
7. Tests: Do tests exist? Do they test behavior (not mocks)? Do they cover edge cases?
8. Performance: Any obvious N+1 queries, unnecessary allocations, blocking calls?
9. Security: Credential exposure, injection risks, unsafe shell commands?

### Output Format
- Strengths (1-3 bullet points)
- Issues by severity:
  - Critical: must fix before merge (security, data loss, regression)
  - Important: should fix before next task
  - Minor: note for later
- Assessment: Ready to proceed / Needs fixes / Needs major rework

### Rules
- Report findings concisely with file:line references
- This is READ-ONLY review -- you have no file_write access
- Do not rewrite or suggest massive re-architecture unless truly necessary
""")


class WorkerSession:
    MAX_HISTORY_MESSAGES = 20
    STALE_THRESHOLD = 3

    def __init__(
        self,
        worker_id: str,
        task: str,
        profile_name: str,
        model_id: str,
        context_files: Optional[List[str]] = None,
        run_id: str = "",
        parent_tool_call_id: str = "",
        agent_type: str = "coding",
        active_skill_ids: Optional[List[str]] = None,
        tool_allowlist: Optional[List[str]] = None,
        team_role: str = "",
    ):
        self.worker_id = worker_id
        self.task = task
        self.profile = WORKER_PROFILES.get(profile_name, WORKER_PROFILES["general"])
        self.model_id = model_id
        self.agent_type = agent_type if agent_type in ("coding", "personal") else "coding"
        self.run_id = run_id
        self.parent_tool_call_id = parent_tool_call_id
        self.tool_allowlist: Optional[frozenset] = frozenset(tool_allowlist) if tool_allowlist else None
        self.team_role = team_role
        self.router = ModelRouter(model_id)
        self.messages: List[Dict[str, Any]] = []
        self.iteration = 0
        self._cancelled = False
        self._cancel_event_emitted = False
        self._context_files = context_files or []
        self._stale_count = 0
        self._started_at = time.time()
        self.matched_skills = self._resolve_matched_skills(active_skill_ids)
        self._tool_schemas_cache = self._build_tool_schemas()
        self._build_system_prompt()
        self._add_task_message()

    def _resolve_matched_skills(self, active_skill_ids: Optional[List[str]] = None) -> List[str]:
        """Resolve enabled skills for this worker's subtask.

        Workers are subagents, so skip the meta "using-superpowers" skill and
        inject the concrete workflow skills that should shape execution.
        """
        try:
            from app.project_manager import ProjectManager
            from app.skills import SkillManager

            role_id = "code-expert" if self.agent_type == "coding" else "desktop-agent"
            if active_skill_ids is None:
                project = ProjectManager.get_current()
                skill_ids = SkillManager.match_skills(
                    self.task,
                    role_id,
                    project is not None,
                    agent_type=self.agent_type,
                )
            else:
                skill_ids = [
                    skill_id
                    for skill_id in active_skill_ids
                    if SkillManager.is_skill_enabled(skill_id, self.agent_type, role_id)
                ]
            return [skill_id for skill_id in skill_ids if skill_id != "using-superpowers"]
        except Exception:
            return []

    def _build_skill_prompt(self) -> str:
        if not self.matched_skills:
            return ""
        try:
            from app.skills import SkillManager

            skill_prompt = SkillManager.build_skill_prompt(self.matched_skills)
        except Exception:
            return ""
        if not skill_prompt:
            return ""
        return (
            "\n## Worker Active Skills\n"
            "These skills matched this worker's subtask and are enabled for the agent. "
            "Follow them where they apply, while keeping the assigned worker scope narrow.\n"
            f"{skill_prompt}\n"
        )

    def _build_system_prompt(self):
        from app.tools import get_static_tool, list_static_tool_names
        tool_names = self.profile.tools
        tools_desc_lines = []
        for name in tool_names:
            if name in list_static_tool_names():
                t = get_static_tool(name)
                tools_desc_lines.append(f"- {name}: {t.description}")
        tools_desc = "\n".join(tools_desc_lines)

        prompt = f"""You are a focused task execution agent. Complete the assigned task using available tools.

## Available Tools
{tools_desc}

## Rules
1. Stay focused on the assigned task. Do not do extra work.
2. Report your result clearly when done.
3. If you cannot complete the task, explain why.
4. Max {self.profile.max_iterations} steps.
"""
        if self.profile.system_prompt_extra:
            prompt += f"\n{self.profile.system_prompt_extra}\n"
        skill_prompt = self._build_skill_prompt()
        if skill_prompt:
            prompt += skill_prompt
        self.messages.append({"role": "system", "content": prompt})

    def _add_task_message(self):
        content = f"Task: {self.task}"
        if self._context_files:
            content += "\n\nContext files provided:\n"
            for f in self._context_files:
                content += f"- {f}\n"
        self.messages.append({"role": "user", "content": content})

    def cancel(self):
        self._cancelled = True

    def _worker_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        event_data = {
            **data,
            "worker_id": self.worker_id,
            "run_id": self.run_id,
            "parent_tool_call_id": self.parent_tool_call_id,
            "timestamp": time.time(),
        }
        if self.team_role:
            event_data["team_role"] = self.team_role
        if self.run_id:
            try:
                from app.coding_runs import record_event

                record_event(self.run_id, event_type, event_data)
            except Exception:
                pass
        return {"type": event_type, "data": event_data}

    def cancel_event(self) -> Optional[Dict[str, Any]]:
        if self._cancel_event_emitted:
            return None
        self._cancel_event_emitted = True
        return self._worker_event("worker_done", {
            "status": "cancelled",
            "result": "[Worker cancelled]",
            "iterations": self.iteration,
            "duration_ms": round((time.time() - self._started_at) * 1000),
        })

    async def run(self) -> AsyncGenerator[Dict[str, Any], None]:
        yield self._worker_event("worker_start", {
            "task": self.task,
            "profile": self.profile.name,
            "model_id": self.model_id,
            "agent_type": self.agent_type,
            "skills": self.matched_skills,
            "status": "running",
        })

        while self.iteration < self.profile.max_iterations:
            if self._cancelled:
                event = self.cancel_event()
                if event:
                    yield event
                return

            self.iteration += 1

            if self.run_id:
                try:
                    from app.collaboration.bus import poll_directive

                    directive = await poll_directive(self.run_id)
                except Exception:
                    directive = None
                if directive:
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "[COLLABORATION DIRECTIVE]\n"
                            "The Personal Agent/user sent this while you were working. "
                            "Treat it as high-priority guidance for the current delegated task.\n\n"
                            f"{directive}"
                        ),
                    })
                    yield self._worker_event("collab_directive_applied", {"directive": directive})

            try:
                response = await self.router.chat_completion_non_stream(
                    messages=repair_tool_call_messages(self.messages),
                    tools=self._tool_schemas_cache,
                    temperature=0.5,
                    max_tokens=8192,
                )
            except Exception as e:
                yield self._worker_event("worker_done", {
                    "status": "failed",
                    "result": f"[Worker model error: {format_worker_exception(e)}]",
                    "iterations": self.iteration,
                    "duration_ms": round((time.time() - self._started_at) * 1000),
                })
                return

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})

            assistant_msg = {
                "role": "assistant",
                "content": message.get("content") or "",
            }
            if message.get("tool_calls"):
                assistant_msg["tool_calls"] = message["tool_calls"]
            if message.get("reasoning_content"):
                assistant_msg["reasoning_content"] = message["reasoning_content"]
            self.messages.append(assistant_msg)

            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            if not content and not tool_calls:
                self._stale_count += 1
                if self._stale_count >= self.STALE_THRESHOLD:
                    yield self._worker_event("worker_done", {
                        "status": "failed",
                        "result": "[Worker stalled: no output for 3 iterations]",
                        "iterations": self.iteration,
                        "duration_ms": round((time.time() - self._started_at) * 1000),
                    })
                    return
            else:
                self._stale_count = 0

            if content:
                yield self._worker_event("worker_content", {
                    "text": content,
                })

            if not tool_calls:
                self._trim_messages()
                yield self._worker_event("worker_done", {
                    "status": "completed",
                    "result": content,
                    "iterations": self.iteration,
                    "duration_ms": round((time.time() - self._started_at) * 1000),
                })
                return

            tool_results = []
            # 工具白名单过滤：allowlist 非空时，跳过不在白名单内的工具调用
            if self.tool_allowlist is not None:
                filtered = []
                for tc in tool_calls:
                    name = tc.get("function", {}).get("name", "")
                    if name in self.tool_allowlist:
                        filtered.append(tc)
                    else:
                        tool_id = tc.get("id", "")
                        msg = f"Tool '{name}' is not in the allowed tool list for this task."
                        yield self._worker_event("worker_tool_call", {
                            "name": name,
                            "args": {},
                            "result": msg,
                            "duration_ms": 0,
                            "tool_call_id": tool_id,
                        })
                        tool_results.append({
                            "tool_call_id": tool_id,
                            "role": "tool",
                            "name": name,
                            "content": msg,
                        })
                tool_calls = filtered
            from app.tools import get_static_tool
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments") or "{}"
                tool_id = tc.get("id", "")

                tool_args, parse_error = parse_tool_args(raw_args)
                if parse_error:
                    yield self._worker_event("worker_tool_call", {
                        "name": tool_name,
                        "args": {},
                        "result": parse_error,
                        "duration_ms": 0,
                        "tool_call_id": tool_id,
                    })
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": parse_error,
                    })
                    continue

                tc_result = await execute_tool(
                    tool_name, tool_args, self.profile.tools, self.worker_id,
                    run_id=self.run_id,
                    tool_call_id=tool_id,
                    worker_id=self.worker_id,
                    parent_tool_call_id=self.parent_tool_call_id,
                    agent_type=self.agent_type,
                    session_model_id=self.model_id,
                    get_tool_fn=get_static_tool,
                )

                if tc_result.metadata.get("file_edit"):
                    yield self._worker_event("file_edit", tc_result.metadata["file_edit"])

                for decision in tc_result.metadata.get("guardrail_decisions", []):
                    yield self._worker_event("guardrail_decision", decision)
                    if decision.get("requires_approval"):
                        yield self._worker_event("approval_required", decision)

                if tc_result.metadata.get("verification"):
                    yield self._worker_event("verification_result", tc_result.metadata["verification"])

                if tc_result.metadata.get("review"):
                    for finding in tc_result.metadata["review"].get("findings", []):
                        yield self._worker_event("review_finding", finding)

                yield self._worker_event("worker_tool_call", {
                    "name": tool_name,
                    "args": tool_args,
                    "result": tc_result.result_text,
                    "duration_ms": tc_result.duration_ms,
                    "tool_call_id": tool_id,
                })

                tool_results.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": tc_result.result_text,
                })

            self.messages.extend(tool_results)
            self._trim_messages()

        yield self._worker_event("worker_done", {
            "status": "max_iterations_reached",
            "result": f"[Worker stopped: max {self.profile.max_iterations} iterations]",
            "iterations": self.iteration,
            "duration_ms": round((time.time() - self._started_at) * 1000),
        })

    def _trim_messages(self):
        self.messages = trim_messages(repair_tool_call_messages(self.messages), self.MAX_HISTORY_MESSAGES)

    def _build_tool_schemas(self) -> List[Dict[str, Any]]:
        from app.tools import get_static_tool, list_static_tool_names
        schemas = []
        for name in self.profile.tools:
            if name in list_static_tool_names():
                schemas.append(get_static_tool(name).get_openai_schema())
        return schemas
