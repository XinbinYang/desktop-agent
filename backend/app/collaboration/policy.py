"""DelegationPolicy — intelligent collaboration decision for Personal Agent.

Two-layer decision:
  Layer 1: Hard rule guards (regex, no LLM call)
  Layer 2: Lightweight LLM classification (thinking_intensity=low) for ambiguous cases

Activated when settings.auto_delegate_coding == "policy_v2".
Falls back gracefully to existing behaviour when disabled.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

DelegationMode = str  # "consult" | "plan_then_execute" | "execute" | "critic" | "verify_only"
RiskLevel = str  # "low" | "medium" | "high"


class Decision(BaseModel):
    should_delegate: bool
    mode: DelegationMode = "consult"
    risk: RiskLevel = "low"
    reasoning: str = ""
    confidence: float = 1.0
    needs_user_confirmation: bool = False


# ---------------------------------------------------------------------------
# Pattern banks
# ---------------------------------------------------------------------------

# High-risk operations that require explicit user confirmation even when delegating.
_HIGH_RISK_PATTERNS: list[str] = [
    r"git\s+push\s+(--force|-f)\b",
    r"git\s+reset\s+--hard\b",
    r"git\s+checkout\s+\.",
    r"git\s+clean\s+-f",
    r"git\s+branch\s+-D\b",
    r"\brm\s+-rf\b",
    r"\bdel\s+/[qsf]",
    r"\.env\b",
    r"credentials?\.(json|yaml|yml)\b",
    r"覆盖.*未提交",
    r"强制.*(推送|删除|重置)",
]

# Write/modify patterns → mode = "execute"
# Note: "run tests/pytest/vitest" is intentionally NOT here; those go to verify_only.
_EXECUTE_PATTERNS: list[str] = [
    r"(写|帮我写|编写|实现|开发|新建|创建).*(代码|程序|脚本|功能|模块|组件|页面|API|接口)",
    r"(修复|修|fix|debug|调试).*(bug|问题|错误|报错|异常)",
    r"(重构|refactor|重写|rewrite|优化|optimize).*(代码|函数|方法|模块|这个|the\s+code|the\s+module)",
    r"(添加|增加|新增|add).*(功能|feature|单元测试|unit\s+test)",
    r"(修改|改|modify|change|update).*(代码|文件|配置|逻辑|实现|code|file|config|logic)",
    r"(write|create|build|implement|develop|make)\s+(a|an|the|some)?\s*(function|module|component|feature|script|class|endpoint|service|API)",
    r"(fix|debug|resolve|patch|repair).*(bug|issue|error|problem|exception|crash)",
    r"(refactor|rewrite|optimize|improve|clean\s*up).*(code|function|module|class|the\s+\w+)",
    r"(add|implement|create)\s+(a|an|the|some)?\s*(feature|endpoint|API)",
    r"(modify|change|update|edit)\s+(the|this)\s+(code|file|config|logic|implementation)",
    r"^(fix|write|create|build|add|update|refactor|implement)\b",
    r"git\s+(commit|push|merge)\b",
]

# Read-only / analysis patterns → mode = "consult"
_CONSULT_PATTERNS: list[str] = [
    r"(看一下|诊断|分析|解释|为什么|怎么)",
    r"(review|explain|diagnose|inspect|analy[sz]e|what\s+is|how\s+does|why\s+is)",
    r"(read|look\s+at|show\s+me|describe)\s+(the|this|a)?\s*(code|file|function|class|module)",
]

# Pure verification patterns — always take verify_only priority over execute.
# These explicitly describe running tests/build without any write intent.
_VERIFY_ONLY_PATTERNS: list[str] = [
    r"(run|执行|跑)\s*(the\s+)?(pytest|vitest|npm\s+test|cargo\s+test|go\s+test)",
    r"(run|执行|跑)\s+tests?\b",
    r"(verify|check|确认|验证)\s*(if|whether|是否|that)?.*(build\s+passes|tests?\s+pass|works\s+correctly|failing)",
    r"(是否通过|有没有报错|测试通过了吗)",
    r"check\s+(if|whether)\s+.*(build|test|work|pass)",
]

# Complex/broad-scope patterns → upgrade to "plan_then_execute"
_PLAN_THEN_EXECUTE_SIGNALS: list[str] = [
    r"(新功能|new\s+feature)\b",
    r"(重构|refactor).*(整个|entire|whole|all|所有)",
    r"整个.*(重构|refactor|rewrite|优化)",
    r"(架构|architecture|设计|redesign).*(变更|change|migration|迁移)",
    r"(多个|multiple|several)\s*(文件|files|模块|modules|组件|components)",
    r"(从头|from\s+scratch|全新)",
    r"(migration|数据库迁移|schema\s+change)",
]

# ---------------------------------------------------------------------------
# DelegationPolicy
# ---------------------------------------------------------------------------


class DelegationPolicy:
    """Two-layer delegation decision engine for the Personal Agent.

    Usage::

        policy = DelegationPolicy()
        decision = await policy.decide(user_input, {}, model_id=model_id)
        if decision.should_delegate:
            # route to coding agent with decision.mode
    """

    def _match_any(self, text: str, patterns: list[str]) -> bool:
        low = text.lower()
        for p in patterns:
            if re.search(p, text, re.IGNORECASE) or re.search(p, low, re.IGNORECASE):
                return True
        return False

    def _hard_rules(self, user_input: str) -> Optional[Decision]:
        """Layer 1: deterministic, no LLM call.

        Returns a Decision when the input clearly matches known patterns.
        Returns None when ambiguous (hand off to LLM layer).
        """
        # High-risk → must delegate execute, needs confirmation
        if self._match_any(user_input, _HIGH_RISK_PATTERNS):
            return Decision(
                should_delegate=True,
                mode="execute",
                risk="high",
                reasoning="Detected high-risk operation pattern (destructive git/file/env command).",
                confidence=0.95,
                needs_user_confirmation=True,
            )

        # Verify-only: run tests / check build — no code writes
        if self._match_any(user_input, _VERIFY_ONLY_PATTERNS) and not self._match_any(
            user_input, _EXECUTE_PATTERNS
        ):
            return Decision(
                should_delegate=True,
                mode="verify_only",
                risk="low",
                reasoning="User wants to run tests or verify output without code changes.",
                confidence=0.85,
            )

        is_execute = self._match_any(user_input, _EXECUTE_PATTERNS)
        is_plan = self._match_any(user_input, _PLAN_THEN_EXECUTE_SIGNALS)

        if is_execute:
            mode: DelegationMode = "plan_then_execute" if is_plan else "execute"
            risk: RiskLevel = "medium" if is_plan else "low"
            return Decision(
                should_delegate=True,
                mode=mode,
                risk=risk,
                reasoning="Detected write/modify/execute code intent.",
                confidence=0.80,
            )

        if self._match_any(user_input, _CONSULT_PATTERNS):
            return Decision(
                should_delegate=True,
                mode="consult",
                risk="low",
                reasoning="Detected read-only analysis intent.",
                confidence=0.75,
            )

        return None  # ambiguous — fall through to LLM layer

    async def _llm_classify(
        self,
        user_input: str,
        session_context: Dict[str, Any],
        model_id: str,
    ) -> Decision:
        """Layer 2: one lightweight LLM call for ambiguous cases."""
        from litellm import acompletion

        system_prompt = (
            "You are a delegation router for a Personal AI Assistant. "
            "Decide if the user's message requires a Coding Agent and, if so, which mode.\n\n"
            "Modes:\n"
            "- consult: read-only analysis, explain code, diagnose issues (no file writes)\n"
            "- execute: make code changes, fix bugs, add features (writes files)\n"
            "- plan_then_execute: large/complex change that needs a plan approved first\n"
            "- critic: execute then independently review the change for quality/safety\n"
            "- verify_only: run tests/build without writing code\n\n"
            "Risk levels:\n"
            "- low: safe, reversible\n"
            "- medium: moderate impact, can be reviewed\n"
            "- high: destructive or irreversible\n\n"
            "Reply ONLY with valid JSON matching this schema (no markdown):\n"
            '{"should_delegate": bool, "mode": str, "risk": str, "reasoning": str, "confidence": float}'
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input[:1000]},
        ]
        try:
            resp = await acompletion(
                model=model_id,
                messages=messages,
                max_tokens=200,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content or ""
            # strip markdown code fences if present
            raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
            data = json.loads(raw)
            return Decision(
                should_delegate=bool(data.get("should_delegate", False)),
                mode=str(data.get("mode", "consult")),
                risk=str(data.get("risk", "low")),
                reasoning=str(data.get("reasoning", "")),
                confidence=float(data.get("confidence", 0.5)),
                needs_user_confirmation=data.get("risk", "low") == "high",
            )
        except Exception as exc:
            logger.debug("DelegationPolicy LLM call failed: %s", exc)
            # Safe fallback: don't delegate, let Personal handle it
            return Decision(
                should_delegate=False,
                mode="consult",
                risk="low",
                reasoning=f"LLM classification failed ({exc}); deferring to Personal Agent.",
                confidence=0.0,
            )

    async def decide(
        self,
        user_input: str,
        session_context: Dict[str, Any],
        *,
        model_id: str,
        thinking_intensity: str = "low",
    ) -> Decision:
        """Decide whether and how to delegate to the Coding Agent.

        Args:
            user_input: The raw user message.
            session_context: Optional context dict (project_path, recent_history, etc.).
            model_id: Model ID to use for the LLM classification layer.
            thinking_intensity: Passed through; kept low by default to minimise latency.

        Returns:
            A Decision instance. If confidence < 0.6, needs_user_confirmation is set True.
        """
        # Layer 1 — hard rules
        decision = self._hard_rules(user_input)
        if decision is not None:
            if decision.confidence < 0.6:
                decision = decision.model_copy(update={"needs_user_confirmation": True})
            return decision

        # Layer 2 — LLM classification (only when model_id is available)
        if model_id:
            decision = await self._llm_classify(user_input, session_context, model_id)
        else:
            decision = Decision(
                should_delegate=False,
                mode="consult",
                risk="low",
                reasoning="No model_id provided; deferring to Personal Agent.",
                confidence=0.0,
            )

        if decision.confidence < 0.6:
            decision = decision.model_copy(update={"needs_user_confirmation": True})
        return decision
