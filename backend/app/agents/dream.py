"""DREAM Engine — three-stage sleep memory consolidation.

Inspired by Claude Code Auto Dream (KAIROS) and OpenClaw Dream (2026.4).

Three-stage sleep architecture:
1. Light Sleep: scan diaries + learnings → candidate list
2. Deep Sleep: six-dimension weighted scoring + triple hard threshold → MEMORY.md
3. REM: association discovery + pattern building + SOUL micro-adjustment suggestions

Also implements:
- Attention decay: HOT/WARM/COLD tiers with daily decay factor
- Forgotten log: discarded entries archived with reasons
- DREAMS.md: human-readable dream diary
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agents.manager import AgentManager

logger = logging.getLogger(__name__)

# Attention tier thresholds
ATTENTION_HOT_DAYS = 3
ATTENTION_HOT_MIN_REFERENCES = 3
ATTENTION_WARM_DAYS = 7
ATTENTION_WARM_MIN_REFERENCES = 1
ATTENTION_DECAY_FACTOR = 0.9

# DREAM scoring weights (sum to 1.0)
WEIGHT_RELEVANCE = 0.30
WEIGHT_FREQUENCY = 0.24
WEIGHT_QUERY_DIVERSITY = 0.15
WEIGHT_RECENCY = 0.15
WEIGHT_INTEGRATION = 0.10
WEIGHT_CONCEPT_RICHNESS = 0.06

# Hard thresholds for Deep Sleep
SCORE_THRESHOLD = 0.8
RECALL_THRESHOLD = 3
UNIQUE_QUERY_THRESHOLD = 3


class DreamEngine:
    """Three-stage memory consolidation inspired by human REM sleep."""

    @classmethod
    async def run(cls) -> Dict[str, Any]:
        """Execute the full DREAM cycle.

        Returns a summary suitable for DREAMS.md and event emission.
        """
        dream_id = datetime.now().strftime("%Y-%m-%d %H:%M")
        result: Dict[str, Any] = {
            "dream_id": dream_id,
            "light_sleep": {},
            "deep_sleep": {},
            "rem": {},
            "forgotten": [],
        }

        # ── Stage 1: Light Sleep — scan + dedup ──
        candidates = cls._light_sleep()
        result["light_sleep"] = {
            "scanned_sessions": len(cls._list_recent_diaries(5)),
            "candidates_found": len(candidates),
            "discarded": "N/A — logged in candidates file",
        }

        # ── Stage 2: Deep Sleep — score + filter ──
        passed, failed = cls._deep_sleep(candidates)
        result["deep_sleep"] = {
            "passed": len(passed),
            "failed": len(failed),
            "scores": {e[:40]: round(s, 2) for e, s in list(passed)[:5]},
        }

        # Write passed entries to MEMORY.md
        if passed:
            entries = [e for e, _ in passed]
            try:
                from app.agents.memory_os import get_memory_os
                score_map = {e: s for e, s in passed}
                get_memory_os().record_dream_entries(entries, score_map)
            except Exception as e:
                logger.warning("DREAM: failed to write Memory OS entries: %s", e)
            AgentManager.consolidate_memory(entries)

        # ── Stage 3: REM — associate + reflect (via isolated background session) ──
        rem_result = await cls._rem_async(passed, candidates)
        result["rem"] = rem_result

        # ── Forgotten log ──
        for entry, reason in failed:
            cls._log_forgotten(entry, reason)
            result["forgotten"].append({"entry": entry[:80], "reason": reason})

        # ── Write DREAMS.md ──
        cls._write_dream_diary(result)

        # ── Update attention tiers ──
        cls._decay_attention()

        return result

    # ── Stage 1: Light Sleep ──

    @classmethod
    def _light_sleep(cls) -> List[str]:
        """Scan recent diaries and learnings, produce candidate memory list."""
        candidates: List[str] = []

        # Scan recent 5 session diaries
        recent_diaries = cls._list_recent_diaries(5)
        for diary_path in recent_diaries:
            try:
                content = diary_path.read_text(encoding="utf-8")
                # Extract significant lines (skip tool logs, short lines)
                for line in content.split("\n"):
                    line = line.strip()
                    if len(line) < 20 or len(line) > 500:
                        continue
                    if line.startswith(("$", "#", "- [", "```", "http")):
                        continue
                    # Skip pure tool output markers
                    if re.match(r"^(Error|Warning|INFO|DEBUG|Traceback)", line):
                        continue
                    candidates.append(line)
            except (OSError, UnicodeDecodeError):
                continue

        # Scan learnings
        learnings_dir = AgentManager._personal_dir() / ".learnings"
        if learnings_dir.exists():
            for f in learnings_dir.glob("*.md"):
                try:
                    content = f.read_text(encoding="utf-8")
                    for line in content.split("\n"):
                        line = line.strip()
                        if line.startswith("- ") and len(line) > 10:
                            candidates.append(line)
                except (OSError, UnicodeDecodeError):
                    continue

        # Dedup: remove near-duplicates (Jaccard-like word overlap)
        deduped = cls._dedup_candidates(candidates)

        # Write candidates to .dreams/candidates.md
        cls._write_candidates_file(deduped)

        return deduped

    @classmethod
    def _dedup_candidates(cls, candidates: List[str]) -> List[str]:
        """Remove near-duplicate candidates using word overlap."""
        if len(candidates) <= 1:
            return candidates

        result: List[str] = []
        for c in candidates:
            c_words = set(c.lower().split())
            is_dup = False
            for r in result:
                r_words = set(r.lower().split())
                if not c_words or not r_words:
                    continue
                overlap = len(c_words & r_words) / min(len(c_words), len(r_words))
                if overlap > 0.7:
                    is_dup = True
                    break
            if not is_dup:
                result.append(c)

        return result

    @classmethod
    def _list_recent_diaries(cls, count: int) -> List[Path]:
        """Get the most recent N diary files."""
        mem_dir = AgentManager._memory_dir()
        if not mem_dir.exists():
            return []
        files = sorted(mem_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:count]

    # ── Stage 2: Deep Sleep ──

    @classmethod
    def _deep_sleep(
        cls, candidates: List[str]
    ) -> Tuple[List[Tuple[str, float]], List[Tuple[str, str]]]:
        """Score candidates with six dimensions + triple hard threshold."""
        passed: List[Tuple[str, float]] = []
        failed: List[Tuple[str, str]] = []

        # Build context for scoring
        all_diary_text = cls._load_all_diary_text()
        learnings_text = cls._load_learnings_text()

        for entry in candidates:
            score = cls._compute_six_dim_score(entry, all_diary_text, learnings_text)
            recall_count = cls._count_recalls(entry, all_diary_text)
            query_diversity = cls._count_unique_contexts(entry, all_diary_text)

            reasons: List[str] = []
            if score < SCORE_THRESHOLD:
                reasons.append(f"score {score:.2f} < {SCORE_THRESHOLD}")
            if recall_count < RECALL_THRESHOLD:
                reasons.append(f"recall {recall_count} < {RECALL_THRESHOLD}")
            if query_diversity < UNIQUE_QUERY_THRESHOLD:
                reasons.append(f"diversity {query_diversity} < {UNIQUE_QUERY_THRESHOLD}")

            if not reasons:
                passed.append((entry, score))
            else:
                failed.append((entry, "; ".join(reasons)))

        return passed, failed

    @classmethod
    def _compute_six_dim_score(cls, entry: str, diary_text: str, learnings_text: str) -> float:
        """Compute a weighted score across six dimensions."""
        entry_lower = entry.lower()
        words = set(entry_lower.split())

        # Relevance (30%): how often entry words appear in diary context
        relevance = sum(1 for w in words if w in diary_text.lower()) / max(len(words), 1)

        # Frequency (24%): count of similar mentions
        frequency = min(diary_text.lower().count(entry_lower[:30]), 10) / 10.0

        # Query diversity (15%): unique day contexts
        query_div = cls._count_unique_contexts(entry, diary_text) / max(UNIQUE_QUERY_THRESHOLD, 1)

        # Recency (15%): weighted by date — entries in recent diaries score higher
        recent_diaries = cls._list_recent_diaries(3)
        recency = 0.0
        for diary in recent_diaries:
            try:
                if entry_lower[:30] in diary.read_text(encoding="utf-8").lower():
                    recency = 1.0
                    break
            except (OSError, UnicodeDecodeError):
                pass

        # Integration (10%): appears across multiple days
        all_diaries = cls._list_recent_diaries(30)
        days_with_entry = sum(
            1 for d in all_diaries
            if entry_lower[:30] in (d.read_text(encoding="utf-8").lower() if d.exists() else "")
        )
        integration = min(days_with_entry / 5.0, 1.0)

        # Concept richness (6%): number of distinct concept words
        concept_words = {w for w in words if len(w) > 3}
        concept_richness = min(len(concept_words) / 10.0, 1.0)

        score = (
            WEIGHT_RELEVANCE * relevance
            + WEIGHT_FREQUENCY * frequency
            + WEIGHT_QUERY_DIVERSITY * min(query_div, 1.0)
            + WEIGHT_RECENCY * recency
            + WEIGHT_INTEGRATION * integration
            + WEIGHT_CONCEPT_RICHNESS * concept_richness
        )
        return score

    @classmethod
    def _count_recalls(cls, entry: str, diary_text: str) -> int:
        """Count how many times this entry is referenced."""
        return diary_text.lower().count(entry.lower()[:30])

    @classmethod
    def _count_unique_contexts(cls, entry: str, diary_text: str) -> int:
        """Count unique daily contexts where this entry appears."""
        entry_lower = entry.lower()[:30]
        count = 0
        # Split by diary date markers
        sections = re.split(r"# \d{4}-\d{2}-\d{2}", diary_text)
        for section in sections:
            if entry_lower in section.lower():
                count += 1
        return count

    @classmethod
    def _load_all_diary_text(cls) -> str:
        """Load all diary text for scoring context."""
        mem_dir = AgentManager._memory_dir()
        if not mem_dir.exists():
            return ""
        parts: List[str] = []
        for f in sorted(mem_dir.glob("*.md")):
            try:
                parts.append(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
        return "\n".join(parts)

    @classmethod
    def _load_learnings_text(cls) -> str:
        """Load learnings text for scoring context."""
        learnings_dir = AgentManager._personal_dir() / ".learnings"
        if not learnings_dir.exists():
            return ""
        parts: List[str] = []
        for f in sorted(learnings_dir.glob("*.md")):
            try:
                parts.append(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
        return "\n".join(parts)

    # ── Stage 3: REM ──

    @classmethod
    async def _rem_async(
        cls, passed: List[Tuple[str, float]], candidates: List[str]
    ) -> Dict[str, Any]:
        """REM phase: use isolated background session for LLM-powered association discovery.

        Falls back to synchronous _rem() if CognitiveTaskRunner is unavailable or returns no results.
        """
        passed_entries = [e for e, _ in passed]
        if not passed_entries:
            return {"patterns": [], "suggestions": []}

        # Try LLM-powered REM via isolated session
        try:
            from app.agents.runner import CognitiveTaskRunner
            llm_result = await CognitiveTaskRunner.run_dream_rem(passed_entries, candidates)
            if llm_result.get("result"):
                return cls._parse_rem_llm_output(llm_result["result"])
        except Exception as e:
            logger.warning("CognitiveTaskRunner REM failed, falling back to sync: %s", e)

        # Fallback to synchronous word-frequency analysis
        return cls._rem(passed, candidates)

    @classmethod
    def _rem(
        cls, passed: List[Tuple[str, float]], candidates: List[str]
    ) -> Dict[str, Any]:
        """Synchronous fallback: associate passed entries via word co-occurrence."""
        result: Dict[str, Any] = {
            "patterns": [],
            "suggestions": [],
        }

        passed_entries = [e for e, _ in passed]
        if not passed_entries:
            return result

        # Pattern discovery: look for co-occurring concepts
        all_words: Counter = Counter()
        for entry in passed_entries:
            words = [w.lower() for w in entry.split() if len(w) > 3]
            all_words.update(set(words))

        # Words appearing in multiple passed entries suggest a theme
        for word, count in all_words.most_common(10):
            if count >= 2:
                affected = [e[:60] for e in passed_entries if word in e.lower()]
                result["patterns"].append({
                    "theme": word,
                    "frequency": count,
                    "entries": affected[:3],
                })

        # Generate SOUL micro-adjustment suggestions
        if any("偏好" in e or "喜欢" in e or "prefer" in e.lower() for e in passed_entries):
            result["suggestions"].append("Consider updating USER.md with detected preferences.")

        if any("不要" in e or "禁止" in e or "don't" in e.lower() for e in passed_entries):
            result["suggestions"].append("Consider adding a boundary to SOUL.md Boundaries section.")

        return result

    @classmethod
    def _parse_rem_llm_output(cls, llm_text: str) -> Dict[str, Any]:
        """Parse LLM output from CognitiveTaskRunner REM into structured results."""
        result: Dict[str, Any] = {"patterns": [], "suggestions": []}
        current_section = None
        for line in llm_text.split("\n"):
            line = line.strip()
            if line.upper().startswith("PATTERNS"):
                current_section = "patterns"
            elif line.upper().startswith("SUGGESTIONS"):
                current_section = "suggestions"
            elif line.startswith("- ") and current_section:
                entry = line[2:].strip()
                if current_section == "patterns":
                    result["patterns"].append({"theme": entry, "frequency": 1, "entries": []})
                else:
                    result["suggestions"].append(entry)
        return result

    # ── Attention Tiers ──

    @classmethod
    def _decay_attention(cls) -> None:
        """Apply daily decay to MEMORY.md attention tiers. Demote HOT→WARM→COLD."""
        mem_path = AgentManager._personal_dir() / "MEMORY.md"
        if not mem_path.exists():
            return

        try:
            content = mem_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        now = datetime.now()
        new_lines: List[str] = []
        for line in content.split("\n"):
            if line.startswith("- [HOT]") or line.startswith("- [WARM]") or line.startswith("- [COLD]"):
                # Parse date from entry
                date_match = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", line)
                if date_match:
                    try:
                        entry_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                        days_old = (now - entry_date).days

                        if "[HOT]" in line and days_old > ATTENTION_HOT_DAYS:
                            line = line.replace("[HOT]", "[WARM]")
                        elif "[WARM]" in line and days_old > ATTENTION_WARM_DAYS:
                            line = line.replace("[WARM]", "[COLD]")
                    except ValueError:
                        pass
            new_lines.append(line)

        try:
            mem_path.write_text("\n".join(new_lines), encoding="utf-8")
        except OSError:
            pass

    # ── Forgotten Log ──

    @classmethod
    def _log_forgotten(cls, entry: str, reason: str) -> None:
        """Log a forgotten entry to forgotten.log."""
        log_path = AgentManager._personal_dir() / "forgotten.log"
        now = datetime.now().isoformat()
        log_line = f"[{now}] REASON: {reason} | ENTRY: {entry[:200]}\n"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_line)
        except OSError:
            pass

    # ── Candidates file ──

    @classmethod
    def _write_candidates_file(cls, candidates: List[str]) -> None:
        """Write light sleep candidates to .dreams/candidates.md."""
        dreams_dir = AgentManager._memory_dir() / ".dreams"
        dreams_dir.mkdir(parents=True, exist_ok=True)
        path = dreams_dir / "candidates.md"
        now = datetime.now().isoformat()
        content = f"# Light Sleep Candidates — {now}\n\n"
        for i, c in enumerate(candidates, 1):
            content += f"{i}. {c}\n"
        try:
            path.write_text(content, encoding="utf-8")
        except OSError:
            pass

    # ── DREAMS.md ──

    @classmethod
    def _write_dream_diary(cls, result: Dict[str, Any]) -> None:
        """Append dream results to DREAMS.md."""
        path = AgentManager._personal_dir() / "DREAMS.md"
        now = datetime.now().isoformat()
        dream_id = result.get("dream_id", now)

        entry = f"""
## Dream — {dream_id}

### 浅睡扫描 (Light Sleep)
- 扫描了 {result['light_sleep'].get('scanned_sessions', 0)} 个会话
- 候选记忆：{result['light_sleep'].get('candidates_found', 0)} 条

### 深睡筛选 (Deep Sleep)
- 通过门槛：{result['deep_sleep'].get('passed', 0)} 条
- 未通过：{result['deep_sleep'].get('failed', 0)} 条

### REM 关联
"""
        for pattern in result.get("rem", {}).get("patterns", []):
            entry += f"- 模式「{pattern['theme']}」出现 {pattern['frequency']} 次\n"

        suggestions = result.get("rem", {}).get("suggestions", [])
        if suggestions:
            entry += "\n### 建议\n"
            for s in suggestions:
                entry += f"- {s}\n"

        forgotten = result.get("forgotten", [])
        if forgotten:
            entry += f"\n### 遗忘\n- {len(forgotten)} 条记忆移入 forgotten.log\n"

        try:
            existing = ""
            if path.exists():
                existing = path.read_text(encoding="utf-8")
            path.write_text(existing.rstrip() + "\n" + entry + "\n", encoding="utf-8")
        except OSError:
            pass
