"""ExpertRegistry — central registry of specialist agent profiles.

Each expert has a name, display name, description, allowed tools, model key,
and capability flags (can_be_critic, can_be_executor).

New experts (e.g. qa, research, refactor) can be added here without touching
any other code.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel


class ExpertProfile(BaseModel):
    name: str
    display_name: str
    description: str
    allowed_tools: List[str]
    model_key: str
    can_be_critic: bool = False
    can_be_executor: bool = True
    worker_profile: str = "code"


# ---------------------------------------------------------------------------
# All Coding Agent tools available in the Personal Agent tool set.
# ---------------------------------------------------------------------------
_CODING_TOOLS: List[str] = [
    "repo_map", "code_search", "file_outline", "file_read", "file_list",
    "file_search", "file_write", "file_edit", "file_patch", "file_delete",
    "shell_execute", "shell_start", "git_diff", "git_status",
    "run_tests", "verify_project", "run_review",
    "web_search", "web_fetch", "browser_screenshot",
    "request_personal_context",
]

EXPERT_REGISTRY: dict[str, ExpertProfile] = {
    "coding": ExpertProfile(
        name="coding",
        display_name="Coding Agent",
        description="Engineering specialist: reads and writes code, runs verification, performs code review.",
        allowed_tools=list(_CODING_TOOLS),
        model_key="coding",
        can_be_critic=True,
        can_be_executor=True,
    ),
    "research": ExpertProfile(
        name="research",
        display_name="Research Agent",
        description="Research specialist: searches codebase and web for information without editing files.",
        allowed_tools=[
            "repo_map", "code_search", "file_outline", "file_read", "file_list",
            "file_search", "git_diff", "git_status",
            "web_search", "web_fetch",
        ],
        model_key="coding",
        can_be_critic=False,
        can_be_executor=False,
        worker_profile="explorer",
    ),
}


def get_expert(name: str) -> ExpertProfile:
    """Return the ExpertProfile for *name*, or raise KeyError if unknown."""
    if name not in EXPERT_REGISTRY:
        raise KeyError(f"Unknown expert: {name!r}. Available: {list(EXPERT_REGISTRY)}")
    return EXPERT_REGISTRY[name]


def list_experts() -> List[str]:
    """Return the names of all registered experts."""
    return list(EXPERT_REGISTRY)


def filter_tools_by_base(base_tools: List[str], allowed: List[str]) -> List[str]:
    """Intersect *base_tools* with the *allowed* list; if *allowed* is empty return *base_tools*."""
    if not allowed:
        return list(base_tools)
    allowed_set = frozenset(allowed)
    return [t for t in base_tools if t in allowed_set]
