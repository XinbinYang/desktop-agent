"""LEARNINGS Engine — self-learning iteration system.

Detects user corrections, records errors, identifies capability gaps.
Implements principle-based reflection and procedural reflection.

Reference: Hermes Agent self-evolution loop, MARS meta-cognitive reflection.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.manager import AgentManager

logger = logging.getLogger(__name__)

# Patterns that indicate user correction
CORRECTION_PATTERNS = [
    r"(不对|不是这样|错了|不应该|不要这样|别这样)",
    r"(应该是|正确的是|正确的是|正确的是)",
    r"(纠正|修正|改正)",
    r"(你搞错了|你弄错了|你理解错了|你误会了)",
    r"(no[,!]|wrong[,!]|incorrect|don't do that|stop)",
    r"(that's not what I|you misunderstood|you got it wrong)",
]

# Patterns that indicate capability gaps
CAPABILITY_GAP_PATTERNS = [
    r"(你能不能|你可以不可以|你能否|你能)",
    r"(为什么不能|为什么不支持|为什么没有)",
    r"(要是你能|如果你能|我希望你能)",
    r"(can you|could you|would you be able to)",
    r"(why can't you|why don't you support)",
    r"(I wish you could|if only you could)",
]


class LearningsEngine:
    """Self-learning system that detects patterns and tracks improvements."""

    # ── Correction Detection ──

    @classmethod
    def detect_corrections(
        cls, user_message: str, assistant_message: str
    ) -> Optional[Dict[str, Any]]:
        """Detect if the user's message contains a correction of the assistant.

        Returns a correction record if detected, None otherwise.
        """
        is_correction = any(
            re.search(p, user_message, re.IGNORECASE) for p in CORRECTION_PATTERNS
        )
        if not is_correction:
            return None

        return {
            "timestamp": datetime.now().isoformat(),
            "user_message": user_message[:300],
            "assistant_context": assistant_message[:300],
            "type": "correction",
        }

    # ── LEARNINGS Management ──

    @classmethod
    def record_learning(cls, discovery: str) -> bool:
        """Record a new learning or increment recurrence of an existing one."""
        learnings_path = AgentManager._personal_dir() / ".learnings" / "LEARNINGS.md"
        try:
            existing = ""
            if learnings_path.exists():
                existing = learnings_path.read_text(encoding="utf-8")

            # Check if this learning already exists
            discovery_key = discovery[:60].lower()
            if discovery_key in existing.lower():
                # Increment recurrence
                updated_lines: List[str] = []
                for line in existing.split("\n"):
                    if discovery_key in line.lower() and line.startswith("- "):
                        # Try to increment recurrence count
                        rec_match = re.search(r"\(recurrence:\s*(\d+)\)", line)
                        if rec_match:
                            count = int(rec_match.group(1)) + 1
                            line = re.sub(
                                r"\(recurrence:\s*\d+\)",
                                f"(recurrence: {count})",
                                line,
                            )
                            if count >= 3:
                                line += " [建议升级到 SOUL.md]"
                    updated_lines.append(line)
                learnings_path.write_text("\n".join(updated_lines), encoding="utf-8")
                return True

            # New learning
            now = datetime.now().strftime("%Y-%m-%d")
            new_entry = f"- [{now}] {discovery} (recurrence: 1)\n"

            if existing.strip():
                # Insert after ## 活跃发现 header or append
                if "## 活跃发现" in existing:
                    before, _, after = existing.partition("## 活跃发现")
                    lines = after.split("\n")
                    lines.insert(1, new_entry)
                    new_content = before + "## 活跃发现" + "\n".join(lines)
                else:
                    new_content = existing.rstrip() + "\n" + new_entry
            else:
                new_content = (
                    "# LEARNINGS.md — 发现与模式\n\n"
                    "## 活跃发现\n\n" + new_entry + "\n"
                    "## 已升级\n\n（暂无）\n"
                )

            learnings_path.parent.mkdir(parents=True, exist_ok=True)
            learnings_path.write_text(new_content, encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to record learning: %s", e)
            return False

    @classmethod
    def get_learnings_promotable(cls) -> List[Dict[str, Any]]:
        """Get learnings with recurrence ≥ 3 (ready for SOUL promotion)."""
        learnings_path = AgentManager._personal_dir() / ".learnings" / "LEARNINGS.md"
        if not learnings_path.exists():
            return []

        promotable: List[Dict[str, Any]] = []
        try:
            content = learnings_path.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if "[建议升级到 SOUL.md]" in line:
                    rec_match = re.search(r"recurrence:\s*(\d+)", line)
                    count = int(rec_match.group(1)) if rec_match else 0
                    # Extract the discovery text
                    text = re.sub(r"\s*\(recurrence:\s*\d+\)\s*\[建议升级.*", "", line)
                    text = text.lstrip("- []() ").strip()
                    promotable.append({"discovery": text, "recurrence": count})
        except OSError:
            pass

        return promotable

    # ── ERRORS Recording ──

    @classmethod
    def record_error(cls, operation: str, error: str, correction: str) -> bool:
        """Record an operational error."""
        errors_path = AgentManager._personal_dir() / ".learnings" / "ERRORS.md"
        now = datetime.now().isoformat()
        entry = (
            f"| {now[:19]} | {operation[:50]} | {error[:100]} | {correction[:100]} |\n"
        )

        try:
            existing = ""
            if errors_path.exists():
                existing = errors_path.read_text(encoding="utf-8")

            if existing.strip():
                if "| 时间 |" in existing:
                    # Append to existing table
                    new_content = existing.rstrip() + "\n" + entry
                else:
                    new_content = existing.rstrip() + "\n\n" + entry
            else:
                header = (
                    "# ERRORS.md — 操作失误记录\n\n"
                    "| 时间 | 操作 | 错误 | 修正 |\n"
                    "|------|------|------|------|\n"
                )
                new_content = header + entry

            errors_path.parent.mkdir(parents=True, exist_ok=True)
            errors_path.write_text(new_content, encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to record error: %s", e)
            return False

    # ── FEATURE REQUESTS Detection ──

    @classmethod
    def detect_capability_gap(cls, user_message: str) -> Optional[str]:
        """Detect if the user message indicates a capability gap."""
        for pattern in CAPABILITY_GAP_PATTERNS:
            match = re.search(pattern, user_message, re.IGNORECASE)
            if match:
                # Extract the full ask
                start = max(0, match.start() - 10)
                end = min(len(user_message), match.end() + 100)
                return user_message[start:end].strip()
        return None

    @classmethod
    def record_feature_request(cls, request: str) -> bool:
        """Record a user feature request / capability gap."""
        req_path = AgentManager._personal_dir() / ".learnings" / "FEATURE_REQUESTS.md"
        now = datetime.now().strftime("%Y-%m-%d")
        entry = f"- [{now}] {request[:200]}\n"

        try:
            existing = ""
            if req_path.exists():
                existing = req_path.read_text(encoding="utf-8")

            if "## 待实现" in existing:
                before, _, after = existing.partition("## 待实现")
                lines = after.split("\n")
                insert_pos = 0
                for i, line in enumerate(lines):
                    if line.strip() and not line.startswith("#"):
                        insert_pos = i + 1
                        break
                lines.insert(max(insert_pos, 0), entry)
                new_content = before + "## 待实现" + "\n".join(lines)
            elif existing.strip():
                new_content = existing.rstrip() + "\n" + entry
            else:
                new_content = (
                    "# FEATURE_REQUESTS.md — 用户期望与能力缺口\n\n"
                    "## 待实现\n\n" + entry + "\n"
                    "## 已解决\n\n（暂无）\n"
                )

            req_path.parent.mkdir(parents=True, exist_ok=True)
            req_path.write_text(new_content, encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to record feature request: %s", e)
            return False

    # ── Reflection ──

    @classmethod
    def principle_reflection(cls, errors: List[Dict[str, str]]) -> List[str]:
        """Abstract rules from errors: 'Next time I encounter X, do Y first.'"""
        rules: List[str] = []
        for err in errors:
            operation = err.get("operation", "")
            correction = err.get("correction", "")
            if operation and correction:
                rules.append(f"When {operation}, remember to {correction} first.")
        return rules

    @classmethod
    def procedural_reflection(cls, successes: List[str]) -> List[str]:
        """Derive strategies from successes: 'Method Z is 3x faster than method W.'"""
        # Simplified: extract key patterns from successful task descriptions
        strategies: List[str] = []
        for success in successes:
            if len(success) > 20:
                strategies.append(f"Successful pattern: {success[:200]}")
        return strategies
