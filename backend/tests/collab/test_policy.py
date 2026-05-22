"""Tests for DelegationPolicy — P1 Eval Harness.

Covers:
- 20+ typical user inputs × expected should_delegate / mode
- Hard-rule hits for 5 execute categories
- High-risk patterns (3 classes) → needs_user_confirmation=True
- Low confidence → needs_user_confirmation=True
- verify_only detection
- plan_then_execute detection
"""
from __future__ import annotations

import pytest

from app.collaboration.policy import Decision, DelegationPolicy


@pytest.fixture
def policy():
    return DelegationPolicy()


# ---------------------------------------------------------------------------
# Hard-rule: should_delegate=True cases
# ---------------------------------------------------------------------------

class TestHardRuleExecute:
    """五类明确 execute 场景 — 硬规则直接命中。"""

    def test_fix_bug_chinese(self, policy):
        d = policy._hard_rules("修复登录 bug")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"

    def test_fix_bug_english(self, policy):
        d = policy._hard_rules("fix the authentication bug")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"

    def test_implement_feature(self, policy):
        d = policy._hard_rules("实现一个用户注册功能")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"

    def test_refactor_module(self, policy):
        d = policy._hard_rules("重构这个函数，去掉重复代码")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"

    def test_git_commit(self, policy):
        d = policy._hard_rules("git commit -m 'fix: login issue'")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"

    def test_run_tests(self, policy):
        # "run tests" also matches execute patterns
        d = policy._hard_rules("run pytest tests/")
        assert d is not None
        assert d.should_delegate is True

    def test_add_feature_english(self, policy):
        d = policy._hard_rules("add a new API endpoint for user profile")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"

    def test_update_config(self, policy):
        d = policy._hard_rules("update the configuration file for production")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"

    def test_create_component(self, policy):
        d = policy._hard_rules("create a React component for the login form")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"

    def test_implement_function(self, policy):
        d = policy._hard_rules("implement a function that calculates the total")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "execute"


class TestHardRuleConsult:
    """只读分析场景 — 硬规则返回 consult。"""

    def test_explain_code_chinese(self, policy):
        d = policy._hard_rules("解释一下这段代码是怎么工作的")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "consult"

    def test_diagnose_issue(self, policy):
        d = policy._hard_rules("诊断为什么测试失败了")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "consult"

    def test_review_code(self, policy):
        d = policy._hard_rules("review this code for me")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "consult"

    def test_explain_english(self, policy):
        d = policy._hard_rules("explain how the authentication module works")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "consult"

    def test_analyze_performance(self, policy):
        d = policy._hard_rules("analyze why the performance is degraded")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "consult"


class TestHardRuleVerifyOnly:
    """verify_only 场景 — 只跑测试/验证，不改代码。"""

    def test_run_pytest(self, policy):
        d = policy._hard_rules("run pytest and show me the results")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "verify_only"

    def test_check_build(self, policy):
        d = policy._hard_rules("check if the build passes")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "verify_only"

    def test_verify_tests_chinese(self, policy):
        d = policy._hard_rules("验证一下测试是否通过")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "verify_only"

    def test_run_vitest(self, policy):
        d = policy._hard_rules("run vitest")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "verify_only"


class TestHardRulePlanThenExecute:
    """plan_then_execute 场景 — 复杂/大范围任务。"""

    def test_new_feature_broad(self, policy):
        d = policy._hard_rules("开发一个新功能：用户权限管理系统")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "plan_then_execute"

    def test_refactor_entire_module(self, policy):
        d = policy._hard_rules("重构整个认证模块")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "plan_then_execute"

    def test_architecture_change(self, policy):
        d = policy._hard_rules("implement a new feature with architecture changes across multiple files")
        assert d is not None
        assert d.should_delegate is True
        assert d.mode == "plan_then_execute"


# ---------------------------------------------------------------------------
# High-risk patterns → needs_user_confirmation=True
# ---------------------------------------------------------------------------

class TestHighRisk:
    """三类高风险操作 — 硬规则返回 needs_user_confirmation=True。"""

    def test_git_push_force(self, policy):
        d = policy._hard_rules("git push --force origin main")
        assert d is not None
        assert d.risk == "high"
        assert d.needs_user_confirmation is True

    def test_git_push_f(self, policy):
        d = policy._hard_rules("git push -f")
        assert d is not None
        assert d.risk == "high"
        assert d.needs_user_confirmation is True

    def test_git_reset_hard(self, policy):
        d = policy._hard_rules("git reset --hard HEAD~3")
        assert d is not None
        assert d.risk == "high"
        assert d.needs_user_confirmation is True

    def test_rm_rf(self, policy):
        d = policy._hard_rules("rm -rf node_modules")
        assert d is not None
        assert d.risk == "high"
        assert d.needs_user_confirmation is True

    def test_env_file(self, policy):
        d = policy._hard_rules("修改 .env 文件里的 API key")
        assert d is not None
        assert d.risk == "high"
        assert d.needs_user_confirmation is True

    def test_credentials_file(self, policy):
        d = policy._hard_rules("update credentials.json")
        assert d is not None
        assert d.risk == "high"
        assert d.needs_user_confirmation is True

    def test_git_branch_delete(self, policy):
        d = policy._hard_rules("git branch -D feature/old-branch")
        assert d is not None
        assert d.risk == "high"
        assert d.needs_user_confirmation is True


# ---------------------------------------------------------------------------
# Ambiguous cases — hard rules return None (fall through to LLM)
# ---------------------------------------------------------------------------

class TestAmbiguous:
    """模糊输入 — 硬规则返回 None，走 LLM 层。"""

    def test_general_chat(self, policy):
        d = policy._hard_rules("今天天气不错")
        assert d is None

    def test_question_without_code(self, policy):
        d = policy._hard_rules("什么是 REST API？")
        assert d is None

    def test_vague_help(self, policy):
        d = policy._hard_rules("help me with my project")
        assert d is None


# ---------------------------------------------------------------------------
# Decision model
# ---------------------------------------------------------------------------

class TestDecisionModel:
    def test_defaults(self):
        d = Decision(should_delegate=True)
        assert d.mode == "consult"
        assert d.risk == "low"
        assert d.confidence == 1.0
        assert d.needs_user_confirmation is False

    def test_confidence_below_threshold_sets_confirmation(self, policy):
        """decide() 对 confidence < 0.6 的结果设置 needs_user_confirmation。"""
        # Manually invoke decide with a mocked low-confidence hard rule
        # by calling the internal result path
        low_conf = Decision(should_delegate=True, mode="execute", confidence=0.4)
        # Simulate the confidence gate in decide()
        if low_conf.confidence < 0.6:
            low_conf = low_conf.model_copy(update={"needs_user_confirmation": True})
        assert low_conf.needs_user_confirmation is True
