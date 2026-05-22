"""Tests for ExpertRegistry and capability-based tool filtering — P4 Eval Harness.

Covers:
- get_expert returns correct ExpertProfile for known experts
- get_expert for unknown expert raises KeyError
- list_experts returns names
- filter_tools_by_base intersection logic
"""
from __future__ import annotations

import pytest

from app.collaboration.registry import (
    EXPERT_REGISTRY,
    ExpertProfile,
    filter_tools_by_base,
    get_expert,
    list_experts,
)


class TestExpertRegistry:
    def test_get_coding_expert(self):
        expert = get_expert("coding")
        assert isinstance(expert, ExpertProfile)
        assert expert.name == "coding"
        assert expert.display_name == "Coding Agent"
        assert expert.can_be_critic is True
        assert expert.can_be_executor is True

    def test_get_research_expert(self):
        expert = get_expert("research")
        assert isinstance(expert, ExpertProfile)
        assert expert.name == "research"
        assert expert.can_be_critic is False
        assert expert.can_be_executor is False

    def test_get_unknown_expert_raises_keyerror(self):
        with pytest.raises(KeyError, match="Unknown expert"):
            get_expert("nonexistent_expert")

    def test_list_experts(self):
        names = list_experts()
        assert "coding" in names
        assert "research" in names

    def test_expert_has_allowed_tools(self):
        expert = get_expert("coding")
        assert len(expert.allowed_tools) > 0
        assert "file_read" in expert.allowed_tools
        assert "shell_execute" in expert.allowed_tools

    def test_research_expert_readonly_tools(self):
        expert = get_expert("research")
        assert "file_read" in expert.allowed_tools
        assert "file_write" not in expert.allowed_tools
        assert "shell_execute" not in expert.allowed_tools


class TestFilterToolsByBase:
    def test_filter_with_non_empty_allowed(self):
        base = ["file_read", "file_write", "shell_execute", "git_diff"]
        allowed = ["file_read", "git_diff"]
        result = filter_tools_by_base(base, allowed)
        assert "file_read" in result
        assert "git_diff" in result
        assert "file_write" not in result
        assert "shell_execute" not in result

    def test_empty_allowed_returns_all(self):
        base = ["file_read", "file_write"]
        result = filter_tools_by_base(base, [])
        assert result == ["file_read", "file_write"]

    def test_allowed_not_in_base_returns_empty(self):
        base = ["file_read"]
        result = filter_tools_by_base(base, ["nonexistent_tool"])
        assert result == []


class TestFilterToolsByPacket:
    def test_from_tools_init(self):
        from app.tools import filter_tools_by_packet

        coding_tools = filter_tools_by_packet("coding", ["file_read", "shell_execute"])
        assert "file_read" in coding_tools
        assert "shell_execute" in coding_tools
        assert len(coding_tools) == 2

    def test_empty_allowed_returns_all_coding_tools(self):
        from app.tools import filter_tools_by_packet

        all_tools = filter_tools_by_packet("coding", [])
        assert len(all_tools) > 10  # coding has many tools
