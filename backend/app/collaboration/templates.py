"""Preset TaskPacket templates for common delegation modes.

Each template pre-fills acceptance_criteria, constraints, and budget
so the Personal Agent can delegate with minimal parameter assembly.
"""

from __future__ import annotations

from app.collaboration.models import TaskBudget, TaskMode, TaskPacket

TEMPLATES: dict[str, dict] = {}


def _register(key: str, packet: dict):
    TEMPLATES[key] = packet
    return packet


_register(
    "bugfix",
    {
        "mode": "execute",
        "acceptance_criteria": [
            "The bug reproduces before the fix and does not after.",
            "At least one targeted test covers the fix path.",
            "No unrelated files were changed.",
            "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
        ],
        "constraints": [
            "Fix only the reported bug. Do not refactor surrounding code.",
            "If the root cause is unclear, call request_personal_clarification.",
        ],
        "budget": TaskBudget(max_iterations=20, max_seconds=300),
    },
)

_register(
    "feature",
    {
        "mode": "plan_then_execute",
        "acceptance_criteria": [
            "The feature works end-to-end as described in the goal.",
            "Existing tests still pass (no regressions).",
            "New code follows project conventions.",
            "Verification evidence is reported.",
            "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
        ],
        "constraints": [
            "Do not change the public API without calling request_personal_clarification.",
            "Keep the implementation as simple as possible.",
        ],
        "budget": TaskBudget(max_iterations=60, max_seconds=1200),
    },
)

_register(
    "refactor",
    {
        "mode": "plan_then_execute",
        "acceptance_criteria": [
            "All existing tests pass after the refactor.",
            "No public API or user-visible behavior changes.",
            "The refactored code follows project conventions.",
            "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
        ],
        "constraints": [
            "Do not change tests to make failures pass.",
            "If a behavioral change is unavoidable, call request_personal_clarification.",
        ],
        "budget": TaskBudget(max_iterations=40, max_seconds=900),
    },
)

_register(
    "consult_diag",
    {
        "mode": "consult",
        "acceptance_criteria": [
            "Provide a concise technical diagnosis.",
            "State whether code changes are needed and what the safest option is.",
            "List any information gaps that prevent a confident answer.",
            "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
        ],
        "constraints": [
            "Read-only. Do not edit any files.",
            "Focus on diagnosis, not speculation.",
        ],
        "allowed_tools": [
            "repo_map", "code_search", "file_outline",
            "file_read", "file_list", "file_search",
            "git_status", "git_diff",
            "web_search", "web_fetch",
        ],
    },
)

_register(
    "verify_only",
    {
        "mode": "verify_only",
        "acceptance_criteria": [
            "Run verification tools and report pass/fail with command output.",
            "If tests fail, report the failing test names and the first error.",
            "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
        ],
        "constraints": [
            "Verification only. Do not edit any files.",
            "Report failures but do not attempt to fix them.",
        ],
        "allowed_tools": [
            "repo_map", "code_search", "file_outline",
            "file_read", "file_list", "file_search",
            "git_status", "git_diff", "verify_project",
            "run_tests", "shell_execute",
        ],
    },
)


def apply_template(packet: TaskPacket, template_name: str) -> TaskPacket:
    """Mutate *packet* in-place with template presets, then return it.

    Fields are overridden only when the caller did NOT provide them, so users
    can always specialize a template. ``budget`` is gated on the explicit
    ``packet.budget_explicit`` flag rather than sniffing the default value —
    the latter silently breaks if ``TaskBudget`` defaults ever shift.
    """
    preset = TEMPLATES.get(template_name)
    if not preset:
        return packet
    if not packet.acceptance_criteria:
        packet.acceptance_criteria = list(preset.get("acceptance_criteria") or [])
    if not packet.constraints:
        packet.constraints = list(preset.get("constraints") or [])
    if not packet.allowed_tools:
        tools = preset.get("allowed_tools")
        if tools:
            packet.allowed_tools = list(tools)
    if preset.get("budget") and not packet.budget_explicit:
        packet.budget = preset["budget"]
    return packet


def template_names() -> list[str]:
    return sorted(TEMPLATES.keys())
