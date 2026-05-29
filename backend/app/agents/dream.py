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
import hashlib
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

# Streaming read limits — prevent unbounded in-memory text during scoring.
_MAX_SCORING_DIARY_FILES = 30   # most recent N diary files
_MAX_SCORING_TEXT_BYTES = 2 * 1024 * 1024  # 2 MB hard cap per text load


class DreamEngine:
    """Three-stage memory consolidation inspired by human REM sleep."""

    @classmethod
    async def run(cls, *, force: bool = False) -> Dict[str, Any]:
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
            "skipped": False,
            "force": force,
        }

        # ── Stage 1: Light Sleep — scan + dedup ──
        candidates = cls._light_sleep(force=force)
        result["light_sleep"] = {
            "scanned_sessions": len(cls._list_recent_diaries(5)),
            "candidates_found": len(candidates),
            "discarded": "N/A — logged in candidates file",
        }
        if not candidates:
            result["deep_sleep"] = {"passed": 0, "failed": 0, "scores": {}}
            result["rem"] = {"patterns": [], "suggestions": []}
            result["skipped"] = not force
            cls._mark_dream_checkpoint()
            return result

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
        cls._mark_dream_checkpoint()

        return result

    # ── Stage 1: Light Sleep ──

    @classmethod
    def _light_sleep(cls, *, force: bool = False) -> List[str]:
        """Scan recent diaries and learnings, produce candidate memory list."""
        candidates: List[str] = []

        # Scan new diary segments by checkpoint; force scans recent diaries but output remains idempotent.
        for content in cls._diary_segments(force=force):
            for line in content.split("\n"):
                line = line.strip()
                if cls._skip_light_sleep_line(line):
                    continue
                candidates.append(line)

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
    def _diary_segments(cls, *, force: bool = False) -> List[str]:
        if force:
            paths = cls._list_recent_diaries(5)
            segments: List[str] = []
            for diary_path in paths:
                try:
                    segments.append(diary_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    continue
            return segments

        try:
            from app.agents.heartbeat import HeartbeatEngine
            state = HeartbeatEngine._read_heartbeat_state()
            checkpoints = state.get("dream_checkpoints")
            if not isinstance(checkpoints, dict):
                checkpoints = {}
        except Exception:
            checkpoints = {}

        mem_dir = AgentManager._memory_dir()
        if not mem_dir.exists():
            return []
        segments = []
        for diary_path in sorted(mem_dir.glob("*.md")):
            checkpoint = checkpoints.get(diary_path.name) if isinstance(checkpoints.get(diary_path.name), dict) else {}
            processed_size = int(checkpoint.get("size") or 0)
            try:
                raw = diary_path.read_bytes()
            except OSError:
                continue
            if processed_size >= len(raw):
                continue
            if processed_size < 0 or processed_size > len(raw):
                processed_size = 0
            segments.append(raw[processed_size:].decode("utf-8", errors="ignore"))
        return segments

    @classmethod
    def _skip_light_sleep_line(cls, line: str) -> bool:
        if len(line) < 20 or len(line) > 500:
            return True
        if line.startswith(("$", "#", "- [", "```", "http", "|", "---")):
            return True
        if re.match(r"^(Error|Warning|INFO|DEBUG|Traceback)", line):
            return True
        lowered = line.lower()
        noisy_fragments = (
            "tool_call",
            "plan_write_draft",
            "please synthesize these decisions",
            "user answered the plan clarification",
            "memory search results",
            "完整的工具清单",
            "可调用的工具",
            "作为 personal agent",
            "温暖、友好",
            "全能数字伙伴",
        )
        if any(fragment in lowered for fragment in noisy_fragments):
            return True
        if line.startswith(("- Assistant:", "- User:")) and not any(
            token in line for token in ("记住", "偏好", "决定", "确认", "不喜欢", "不要", "以后", "原则", "纠正", "错误")
        ):
            return True
        return False

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

        # Build context for scoring (capped — see _MAX_SCORING_* constants)
        all_diary_text = cls._load_all_diary_text()
        learnings_text = cls._load_learnings_text()

        # Pre-load recent diary content once so _compute_six_dim_score doesn't
        # re-read the same files once per candidate (was O(candidates × 30 files)).
        recent_diary_lowers: List[str] = []
        for diary in cls._list_recent_diaries(_MAX_SCORING_DIARY_FILES):
            try:
                recent_diary_lowers.append(diary.read_text(encoding="utf-8", errors="ignore").lower())
            except OSError:
                pass

        for entry in candidates:
            score = cls._compute_six_dim_score(entry, all_diary_text, learnings_text, recent_diary_lowers)
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
    def _compute_six_dim_score(
        cls,
        entry: str,
        diary_text: str,
        learnings_text: str,
        recent_diary_lowers: List[str],
    ) -> float:
        """Compute a weighted score across six dimensions.

        recent_diary_lowers: pre-loaded diary texts (lowercased) for recency/integration
        checks, so callers avoid per-candidate file I/O.
        """
        entry_lower = entry.lower()
        words = set(entry_lower.split())

        # Relevance (30%): how often entry words appear in diary context
        relevance = sum(1 for w in words if w in diary_text.lower()) / max(len(words), 1)

        # Frequency (24%): count of similar mentions
        frequency = min(diary_text.lower().count(entry_lower[:30]), 10) / 10.0

        # Query diversity (15%): unique day contexts
        query_div = cls._count_unique_contexts(entry, diary_text) / max(UNIQUE_QUERY_THRESHOLD, 1)

        # Recency (15%): appears in any of the 3 most recent diaries
        recency = 1.0 if any(entry_lower[:30] in dl for dl in recent_diary_lowers[:3]) else 0.0

        # Integration (10%): appears across multiple days
        days_with_entry = sum(1 for dl in recent_diary_lowers if entry_lower[:30] in dl)
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
        """Load recent diary text for scoring context (capped by file count and byte size)."""
        mem_dir = AgentManager._memory_dir()
        if not mem_dir.exists():
            return ""
        files = sorted(mem_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        files = files[:_MAX_SCORING_DIARY_FILES]
        parts: List[str] = []
        total = 0
        for f in reversed(files):  # chronological order for scoring context
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            remaining = _MAX_SCORING_TEXT_BYTES - total
            if len(text) >= remaining:
                parts.append(text[:remaining])
                break
            parts.append(text)
            total += len(text)
        return "\n".join(parts)

    @classmethod
    def _load_learnings_text(cls) -> str:
        """Load learnings text for scoring context (capped by byte size)."""
        learnings_dir = AgentManager._personal_dir() / ".learnings"
        if not learnings_dir.exists():
            return ""
        parts: List[str] = []
        total = 0
        for f in sorted(learnings_dir.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            remaining = _MAX_SCORING_TEXT_BYTES - total
            if len(text) >= remaining:
                parts.append(text[:remaining])
                break
            parts.append(text)
            total += len(text)
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
        index_path = AgentManager._memory_dir() / ".dreams" / "forgotten_index.json"
        entry_hash = cls._entry_hash(entry)
        now = datetime.now().isoformat()
        index: Dict[str, Any] = {}
        try:
            if index_path.exists():
                loaded = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    index = loaded
        except (OSError, json.JSONDecodeError):
            index = {}
        if entry_hash in index:
            item = index[entry_hash] if isinstance(index[entry_hash], dict) else {}
            item["repeat_count"] = int(item.get("repeat_count") or 1) + 1
            item["last_seen_at"] = now
            item["reason"] = reason
            index[entry_hash] = item
            try:
                index_path.parent.mkdir(parents=True, exist_ok=True)
                index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
            return

        log_line = f"[{now}] REASON: {reason} | ENTRY: {entry[:200]}\n"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_line)
            index[entry_hash] = {
                "first_seen_at": now,
                "last_seen_at": now,
                "repeat_count": 1,
                "reason": reason,
                "entry_preview": entry[:200],
            }
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _entry_hash(text: str) -> str:
        compact = re.sub(r"\s+", " ", text.strip()).lower()
        return hashlib.sha256(compact.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def _mark_dream_checkpoint(cls) -> None:
        try:
            from app.agents.heartbeat import HeartbeatEngine
            HeartbeatEngine.mark_dream_complete()
        except Exception as e:
            logger.warning("DREAM: failed to mark checkpoint: %s", e)

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
