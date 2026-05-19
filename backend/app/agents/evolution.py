"""EVOLUTION Engine — self-improvement through skill crystallization.

Implements a self-evolution closed loop:
1. Reflection: principle + procedural reflection from errors and successes
2. Skill Crystallization: analyze successful tasks → generate reusable Skill files
3. Self-Optimization: track skill success rates → adjust AGENTS.md weights
4. Meta-Cognitive Upgrade: promote learnings to SOUL, skills to AGENTS.md instructions

Reference: Hermes Agent self-evolution loop, Hyperagents/DGM meta-cognitive modification.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.manager import AgentManager
from app.agents.learnings import LearningsEngine

logger = logging.getLogger(__name__)

# Trigger thresholds
TASK_COUNT_THRESHOLD = 15
FEEDBACK_COUNT_THRESHOLD = 5

# Skill success rate thresholds
SKILL_NEEDS_IMPROVEMENT = 0.50
SKILL_VERIFIED = 0.80


class EvolutionEngine:
    """Self-evolution engine: watches, learns, and improves over time."""

    _task_count_path = AgentManager._personal_dir() / ".archive" / "task_count.json"

    # ── Trigger Check ──

    @classmethod
    def should_evolve(cls) -> bool:
        """Check if evolution should be triggered."""
        task_count = cls._get_task_count()
        feedback_count = cls._get_feedback_count()
        return task_count >= TASK_COUNT_THRESHOLD or feedback_count >= FEEDBACK_COUNT_THRESHOLD

    @classmethod
    def _get_task_count(cls) -> int:
        try:
            if cls._task_count_path.exists():
                data = json.loads(cls._task_count_path.read_text(encoding="utf-8"))
                return data.get("count", 0)
        except (OSError, json.JSONDecodeError):
            pass
        return 0

    @classmethod
    def _get_feedback_count(cls) -> int:
        learnings_path = AgentManager._personal_dir() / ".learnings" / "LEARNINGS.md"
        if not learnings_path.exists():
            return 0
        try:
            content = learnings_path.read_text(encoding="utf-8")
            return len(re.findall(r"\(recurrence:\s*\d+\)", content))
        except OSError:
            return 0

    @classmethod
    def increment_task_count(cls) -> int:
        """Increment the task counter. Returns new count."""
        count = cls._get_task_count() + 1
        cls._task_count_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cls._task_count_path.write_text(
                json.dumps({"count": count, "updated_at": datetime.now().isoformat()}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
        return count

    # ── Evolution Cycle ──

    @classmethod
    async def run_evolution_cycle(cls) -> Dict[str, Any]:
        """Execute a full evolution cycle.

        Returns a summary of changes made.
        """
        result: Dict[str, Any] = {
            "archive_created": False,
            "skills_crystallized": [],
            "learnings_promoted": [],
            "suggestions": [],
        }

        # ── Step 0: Create archive snapshot ──
        result["archive_created"] = cls._create_archive()

        # ── Step 1: Reflection ──
        errors = cls._load_recent_errors()
        if errors:
            rules = LearningsEngine.principle_reflection(errors)
            result["suggestions"].extend(rules)

        # ── Step 2: Skill Crystallization ──
        new_skills = cls._crystallize_skills()
        result["skills_crystallized"] = new_skills

        # ── Step 3: Self-Optimization ──
        cls._update_skill_stats()

        # ── Step 4: Meta-Cognitive Upgrade ──
        promotable = LearningsEngine.get_learnings_promotable()
        if promotable:
            cls._promote_to_soul(promotable)
            result["learnings_promoted"] = [p["discovery"][:80] for p in promotable]

        # ── Reset task counter ──
        cls._reset_task_count()

        return result

    # ── Archive ──

    @classmethod
    def _create_archive(cls) -> bool:
        """Create a timestamped archive snapshot of current workspace state."""
        archive_dir = AgentManager._personal_dir() / ".archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        snapshot_dir = archive_dir / timestamp

        try:
            snapshot_dir.mkdir(parents=True, exist_ok=True)

            # Copy key mutable workspace files plus the protected Personal rules.
            for filename in ["SOUL.md", "INNER.md", "IDENTITY.md", "MEMORY.md"]:
                src = AgentManager._personal_dir() / filename
                if src.exists():
                    shutil.copy2(src, snapshot_dir / filename)

            protected_rules = AgentManager._personal_system_dir() / "AGENTS.md"
            if protected_rules.exists():
                shutil.copy2(protected_rules, snapshot_dir / "AGENTS.md")

            # Copy skills
            skills_dir = AgentManager._personal_dir() / "skills"
            if skills_dir.exists():
                shutil.copytree(skills_dir, snapshot_dir / "skills", dirs_exist_ok=True)

            return True
        except OSError as e:
            logger.warning("Failed to create archive snapshot: %s", e)
            return False

    @classmethod
    def list_archives(cls) -> List[Dict[str, Any]]:
        """List all archive snapshots."""
        archive_dir = AgentManager._personal_dir() / ".archive"
        if not archive_dir.exists():
            return []

        archives: List[Dict[str, Any]] = []
        for d in sorted(archive_dir.iterdir(), reverse=True):
            if d.is_dir() and d.name != "task_count.json":
                try:
                    mtime = d.stat().st_mtime
                    archives.append({
                        "id": d.name,
                        "timestamp": datetime.fromtimestamp(mtime).isoformat(),
                        "files": [f.name for f in d.rglob("*") if f.is_file()],
                    })
                except OSError:
                    pass

        return archives

    # ── Skill Crystallization ──

    @classmethod
    def _crystallize_skills(cls) -> List[str]:
        """Analyze recent successful tasks and generate skill templates.

        Creates inert skill drafts. Publishing requires user review.
        """
        new_skills: List[str] = []

        # Check for common task patterns in recent diaries
        diary_text = cls._load_recent_summary()
        if not diary_text:
            return new_skills

        draft_patterns = {
            "file-organization": ["整理", "文件", "organize", "file"],
            "web-search": ["搜索", "查找", "search", "find"],
            "data-analysis": ["分析", "数据", "analysis", "data"],
            "code-review": ["审查", "review", "检查代码"],
        }

        try:
            from app.skill_authoring import list_drafts, list_published_entries, save_draft

            existing_names = {
                str(d.get("name", ""))
                for d in list_drafts()
            } | {
                str(e.get("name", ""))
                for e in list_published_entries(include_archived=False).values()
            }
        except Exception as exc:
            logger.warning("Skill draft creation unavailable: %s", exc)
            return new_skills

        diary_lower = diary_text.lower()
        for skill_name, keywords in draft_patterns.items():
            if skill_name in existing_names:
                continue
            if any(kw.lower() in diary_lower for kw in keywords):
                try:
                    save_draft(
                        name=skill_name,
                        description=f"Use when handling recurring tasks related to {', '.join(keywords)}.",
                        body=cls._generate_skill_template(skill_name, keywords),
                        scopes=["personal"],
                        created_from="evolution",
                    )
                    new_skills.append(skill_name)
                except Exception as exc:
                    logger.warning("Failed to create skill draft %s: %s", skill_name, exc)

        return new_skills

        # Simple pattern detection
        patterns = {
            "file_organization": ["整理", "文件", "organize", "file"],
            "web_search": ["搜索", "查找", "search", "find"],
            "data_analysis": ["分析", "数据", "analysis", "data"],
            "code_review": ["审查", "review", "检查代码"],
        }

        for skill_name, keywords in patterns.items():
            skill_path = skills_dir / f"{skill_name}.md"
            if skill_path.exists():
                continue  # Skill already exists

            if any(kw in diary_text.lower() for kw in keywords):
                template = cls._generate_skill_template(skill_name, keywords)
                try:
                    skill_path.write_text(template, encoding="utf-8")
                    new_skills.append(skill_name)
                except OSError:
                    pass

        return new_skills

    @classmethod
    def _generate_skill_template(cls, skill_name: str, keywords: List[str]) -> str:
        """Generate a basic skill Markdown template."""
        now = datetime.now().isoformat()
        return f"""---
name: {skill_name}
created_at: {now}
success_rate: 1.0
usage_count: 0
---

# {skill_name.replace('_', ' ').title()}

Auto-generated skill for handling tasks related to: {', '.join(keywords)}.

## Steps

1. Identify the task scope
2. Execute the core operation
3. Verify the result
4. Report back to user

## Notes

（This skill will be refined through usage.）
"""

    @classmethod
    def _load_recent_summary(cls) -> str:
        """Load recent diary text for pattern detection."""
        from app.agents.dream import DreamEngine
        return DreamEngine._load_all_diary_text()

    @classmethod
    def list_skills(cls) -> List[Dict[str, Any]]:
        """List all crystallized skills with stats."""
        skills_dir = AgentManager._personal_dir() / "skills"
        if not skills_dir.exists():
            return []

        skills: List[Dict[str, Any]] = []
        for f in sorted(skills_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8")
                # Parse frontmatter
                meta: Dict[str, Any] = {"name": f.stem}
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        fm = content[3:end]
                        for line in fm.split("\n"):
                            if ":" in line:
                                key, val = line.split(":", 1)
                                key = key.strip()
                                val = val.strip()
                                if key in ("success_rate", "usage_count"):
                                    try:
                                        meta[key] = float(val)
                                    except ValueError:
                                        meta[key] = val
                                else:
                                    meta[key] = val
                skills.append(meta)
            except OSError:
                pass

        return skills

    @classmethod
    def _update_skill_stats(cls) -> None:
        """Update skill success rates based on recent usage."""
        # This is called during evolution to mark skills
        # In full implementation, success rates would be tracked per-use
        pass

    # ── Promotion ──

    @classmethod
    def _promote_to_soul(cls, promotable: List[Dict[str, Any]]) -> bool:
        """Promote high-recurrence learnings to SOUL.md suggestions."""
        soul_path = AgentManager._personal_dir() / "SOUL.md"
        if not soul_path.exists():
            return False

        try:
            content = soul_path.read_text(encoding="utf-8")
        except OSError:
            return False

        now = datetime.now().strftime("%Y-%m-%d")
        for item in promotable:
            discovery = item.get("discovery", "")
            if discovery and discovery not in content:
                suggestion = f"\n- [{now}] LEARNINGS 升级: {discovery}"
                if "## Learning Style" in content:
                    content = content.replace(
                        "## Learning Style",
                        "## Learning Style" + suggestion,
                    )
                else:
                    content = content.rstrip() + "\n" + suggestion + "\n"

        try:
            soul_path.write_text(content, encoding="utf-8")
            return True
        except OSError:
            return False

    @classmethod
    def _reset_task_count(cls) -> None:
        """Reset the task counter after an evolution cycle."""
        cls._task_count_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cls._task_count_path.write_text(
                json.dumps({"count": 0, "updated_at": datetime.now().isoformat()}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    @classmethod
    def _load_recent_errors(cls) -> List[Dict[str, str]]:
        """Load recent errors from ERRORS.md."""
        errors_path = AgentManager._personal_dir() / ".learnings" / "ERRORS.md"
        if not errors_path.exists():
            return []

        errors: List[Dict[str, str]] = []
        try:
            content = errors_path.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("| ") and "时间" not in line:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if len(parts) >= 4:
                        errors.append({
                            "time": parts[0],
                            "operation": parts[1],
                            "error": parts[2],
                            "correction": parts[3],
                        })
        except OSError:
            pass

        return errors


# Import at bottom to avoid circular imports
import re
