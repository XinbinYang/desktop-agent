import re
from pathlib import Path
from typing import Any, Dict, List, Optional

SKILL_DIR = Path(__file__).parent.parent / "prompts" / "skills"

# Skill 匹配规则：根据用户消息关键词和角色匹配适用的 skills
MATCH_RULES = [
    # 编程开发任务
    {
        "patterns": ["实现", "开发", "构建", "添加功能", "新功能", "写一个", "创建",
                     "implement", "develop", "build", "create", "add feature",
                     "编写", "写个", "做个", "开发一个"],
        "roles": ["code-expert"],
        "skills": ["using-superpowers", "brainstorming", "writing-plans"],
    },
    # Bug 修复
    {
        "patterns": ["bug", "修复", "调试", "报错", "错误", "fix", "debug",
                     "troubleshoot", "broken", "not working"],
        "roles": ["code-expert"],
        "skills": ["using-superpowers", "systematic-debugging", "test-driven-development"],
    },
    # 重构
    {
        "patterns": ["重构", "优化", "改进", "refactor", "optimize", "improve",
                     "cleanup", "clean up"],
        "roles": ["code-expert"],
        "skills": ["using-superpowers", "test-driven-development", "verification-before-completion"],
    },
    # 测试
    {
        "patterns": ["测试", "test", "unit test", "写测试", "TDD"],
        "roles": ["code-expert"],
        "skills": ["test-driven-development"],
    },
    # 代码审查
    {
        "patterns": ["审查", "review", "code review", "检查代码"],
        "roles": ["code-expert"],
        "skills": ["requesting-code-review"],
    },
    # Git 操作
    {
        "patterns": ["git", "分支", "branch", "合并", "merge", "commit", "push", "pull"],
        "roles": ["code-expert"],
        "skills": ["using-git-worktrees"],
    },
    # 计划/方案
    {
        "patterns": ["计划", "方案", "plan", "roadmap", "怎么实现"],
        "roles": ["code-expert"],
        "skills": ["writing-plans"],
    },
    # 并行任务
    {
        "patterns": ["并行", "同时", "parallel", "并发", "多个任务"],
        "roles": ["code-expert"],
        "skills": ["dispatching-parallel-agents", "subagent-driven-development"],
    },
    # 分支收尾
    {
        "patterns": ["完成", "收尾", "finish", "done", "finalize", "changelog",
                     "release notes", "发布", "合并到主干", "merge to main"],
        "roles": ["code-expert"],
        "skills": ["finishing-a-development-branch", "verification-before-completion"],
    },
    # 代码审查反馈
    {
        "patterns": ["审查反馈", "review feedback", "根据评审", "按照建议",
                     "address review", "PR feedback", "fix review", "code review feedback"],
        "roles": ["code-expert"],
        "skills": ["receiving-code-review"],
    },
    # 按计划执行
    {
        "patterns": ["按计划", "执行计划", "run the plan", "start implementing",
                     "execute plan", "implement the plan"],
        "roles": ["code-expert"],
        "skills": ["executing-plans", "subagent-driven-development"],
    },
    # 项目熟悉 / 代码探索
    {
        "patterns": ["熟悉", "了解", "familiarize", "understand the project",
                     "explore the codebase", "项目概览", "overview",
                     "介绍一下项目", "这个项目", "代码结构", "explore the project",
                     "understand the codebase", "familiarize yourself"],
        "roles": ["code-expert", "desktop-agent"],
        "skills": ["project-familiarization", "dispatching-parallel-agents"],
    },
]

SKILL_PRIORITY = [
    "using-superpowers",
    "output-formatting",
    "writing-plans",
    "executing-plans",
    "systematic-debugging",
    "test-driven-development",
    "verification-before-completion",
    "subagent-driven-development",
    "dispatching-parallel-agents",
    "requesting-code-review",
    "receiving-code-review",
    "finishing-a-development-branch",
    "using-git-worktrees",
]


class SkillManager:
    """管理 Superpowers skills 的扫描、匹配和加载"""

    _skills_cache: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def _parse_skill_md(cls, path: Path) -> Optional[Dict[str, Any]]:
        """解析 SKILL.md 文件，提取 YAML frontmatter 和正文"""
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        frontmatter: Dict[str, str] = {}
        body = content

        # 解析 YAML frontmatter: ---\n...\n---
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                fm_text = content[3:end].strip()
                body = content[end + 3:].strip()
                for line in fm_text.split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        frontmatter[key.strip()] = val.strip()

        return {
            "name": frontmatter.get("name", path.parent.name),
            "description": frontmatter.get("description", ""),
            "body": body,
            "path": str(path),
        }

    @classmethod
    def load_skills(cls) -> Dict[str, Dict[str, Any]]:
        """扫描所有 skills，返回 {skill_name: skill_data}"""
        if cls._skills_cache is not None:
            return cls._skills_cache

        skills: Dict[str, Dict[str, Any]] = {}
        if SKILL_DIR.exists():
            for skill_dir in SKILL_DIR.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    parsed = cls._parse_skill_md(skill_md)
                    if parsed:
                        skills[parsed["name"]] = parsed

        cls._skills_cache = skills
        return skills

    @classmethod
    def reload_skills(cls) -> None:
        """强制重新加载 skills"""
        cls._skills_cache = None

    @classmethod
    def list_skills(cls) -> List[Dict[str, str]]:
        """返回所有可用 skill 的简要信息"""
        return [
            {"name": s["name"], "description": s["description"]}
            for s in cls.load_skills().values()
        ]

    @classmethod
    def get_skill(cls, name: str) -> Optional[str]:
        """获取指定 skill 的完整内容（含 frontmatter + 正文）"""
        skills = cls.load_skills()
        skill = skills.get(name)
        if skill:
            return f"---\nname: {skill['name']}\ndescription: {skill['description']}\n---\n\n{skill['body']}"
        return None

    @classmethod
    def get_skill_body(cls, name: str) -> Optional[str]:
        """获取指定 skill 的正文内容（不含 frontmatter）"""
        skills = cls.load_skills()
        skill = skills.get(name)
        return skill["body"] if skill else None

    @classmethod
    def match_skills(cls, user_message: str, role_id: str, has_project: bool) -> List[str]:
        """根据用户消息、角色、项目状态匹配适用的 skill 名称列表"""
        matched: set = set()
        msg_lower = user_message.lower()

        for rule in MATCH_RULES:
            # 检查角色匹配
            if rule["roles"] and role_id not in rule["roles"]:
                continue

            # 检查关键词匹配
            for pattern in rule["patterns"]:
                if pattern.lower() in msg_lower:
                    matched.update(rule["skills"])
                    break

        # 如果有项目打开，且是编码角色，总是包含 using-superpowers
        if has_project and role_id in ("code-expert",):
            matched.add("using-superpowers")
        # code-expert 角色：永远包含验证技能（任何代码改动都要 verification）
        if role_id in ("code-expert",):
            matched.add("verification-before-completion")
        # Personal agent (desktop-agent): always include using-superpowers for skill discovery
        if role_id in ("desktop-agent", "general-assistant", "quant-analyst"):
            matched.add("using-superpowers")

        # 总是包含输出格式规范（如果 skill 存在）
        if "output-formatting" in cls.load_skills():
            matched.add("output-formatting")

        priority_index = {name: i for i, name in enumerate(SKILL_PRIORITY)}
        return sorted(matched, key=lambda name: (priority_index.get(name, 999), name))

    @classmethod
    def build_skill_prompt(cls, skill_names: List[str]) -> str:
        """将多个 skill 内容合并为一个 prompt 字符串"""
        parts = []
        for name in skill_names:
            content = cls.get_skill(name)
            if content:
                parts.append(f"\n## Skill: {name}\n{content}\n")
        return "\n".join(parts)
