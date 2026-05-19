import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


USER_DATA_ENV = "DESKTOP_AGENT_USER_DATA_DIR"
AGENT_HOME_MIGRATION_MARKER = ".personal-home-migration-v1"


def backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    """Canonical project workspace root for regular file-tool operations."""
    return repo_root()


def _default_user_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return (Path(base) / "Desktop Agent").expanduser().resolve()


def bundled_agents_dir() -> Path:
    return bundled_root() / "AGENTS"


def _copy_missing_tree(source: Path, target: Path) -> None:
    if not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return

    for src in source.rglob("*"):
        rel = src.relative_to(source)
        dst = target / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


_AGENT_HOME_REPLACEMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "_shared/base_rules.md": (
        (
            "## 运行环境锚定\n\n"
            "- 你当前就运行在本项目（`desktop-agent`）的代码库中。工作目录即项目根目录。\n"
            "- **禁止主动克隆外部仓库、搜索外部模板、或访问与当前任务无关的外部资源。**\n"
            "- 只有当用户**明确要求**时，才使用 `git_clone` 或访问外部网站（`browser_navigate`）。\n"
            "- 用户让你\"熟悉代码库\"\"了解项目\"时，应直接读取当前目录下的文件，而不是去外部搜索。",
            "## 运行环境锚定\n\n"
            "- Personal Agent 的默认身份不绑定任何代码项目；它的身份、记忆、日记和技能位于 runtime `AGENTS/personal/`。\n"
            "- Coding Agent 才绑定当前打开的项目；涉及项目代码、测试、Git 和 repo 规则时，以 Coding Agent 收到的项目路径为准。\n"
            "- **禁止主动克隆外部仓库、搜索外部模板、或访问与当前任务无关的外部资源。**\n"
            "- 只有当用户**明确要求**时，才使用 `git_clone` 或访问外部网站（`browser_navigate`）。\n"
            "- 用户让你\"熟悉代码库\"\"了解项目\"时，如果你是 Coding Agent，应读取当前任务绑定项目；如果你是 Personal Agent，应先确认用户要查看哪个项目，或委派 Coding Agent。",
        ),
    ),
    "personal/AGENTS.md": (
        (
            "> - 工作区根 = 项目仓库根目录（即 `desktop-agent` 所在的目录）。\n"
            "> - 你的身份与记忆文件统一位于运行时 `AGENTS/personal/`。",
            "> - Personal home = 运行时 `AGENTS/personal/`；这是你的身份、记忆、日记、心情、技能和 handoff 的家。\n"
            "> - 当前打开的代码项目只是用户可能正在处理的工作目标，不是你的身份、家或源码位置。",
        ),
    ),
    "personal/BOOTSTRAP.md": (
        (
            "> - 工作区根 = 项目仓库根目录（即 `desktop-agent` 所在的目录）。\n"
            "> - 你的身份与记忆文件统一位于 `AGENTS/personal/`。",
            "> - Personal home = 运行时 `AGENTS/personal/`；这是你的身份、记忆、日记、心情、技能和 handoff 的家。\n"
            "> - 当前打开的代码项目只是用户可能正在处理的工作目标，不是你的身份、家或源码位置。",
        ),
        (
            ">   相对路径如 `AGENTS/personal/USER.md` 会相对工作区根解析。",
            ">   相对路径如 `AGENTS/personal/USER.md` 会被解析到 runtime AGENTS workspace。",
        ),
    ),
    "coding/AGENTS.md": (
        (
            "- 你当前就运行在本项目（`desktop-agent`）的代码库中。工作目录即项目根目录。",
            "- 你当前运行在本次 Coding 会话绑定的项目代码库中；工作目录由 session/run context 提供（当前项目或 worktree），不要假定项目名是 `desktop-agent`。",
        ),
    ),
}


def _backup_agents_before_migration(target: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = target.parent / f"AGENTS-personal-home-migration-{timestamp}"
    suffix = 1
    while backup.exists():
        backup = target.parent / f"AGENTS-personal-home-migration-{timestamp}-{suffix}"
        suffix += 1
    shutil.copytree(target, backup)
    return backup


def _migrate_agent_home_context(target: Path) -> None:
    """Patch old runtime AGENTS templates that described Personal as project-bound.

    Runtime AGENTS files are user-owned after first launch, so this migration
    only replaces exact legacy seed text and leaves all custom content intact.
    """
    if not target.exists():
        return

    updates: list[tuple[Path, str]] = []
    for rel, replacements in _AGENT_HOME_REPLACEMENTS.items():
        path = target / Path(rel)
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        patched = text
        for old, new in replacements:
            patched = patched.replace(old, new)
        if patched != text:
            updates.append((path, patched))

    if not updates:
        return

    backup = _backup_agents_before_migration(target)
    for path, patched in updates:
        try:
            path.write_text(patched, encoding="utf-8")
        except OSError:
            continue

    try:
        (target / AGENT_HOME_MIGRATION_MARKER).write_text(
            f"migrated_at={datetime.now().isoformat()}\nbackup={backup}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def agents_dir() -> Path:
    """Mutable Agent workspace under the runtime data directory.

    The repository keeps seed templates in ``AGENTS/``. Runtime persona,
    memory, skills, and handoff files live in user data so normal app usage and
    tests do not dirty the git worktree.
    """
    target = runtime_root() / "AGENTS"
    _copy_missing_tree(bundled_agents_dir(), target)
    _migrate_agent_home_context(target)
    return target


def bundled_root() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):  # type: ignore[attr-defined]
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return repo_root()


def bundled_config_path() -> Path:
    return bundled_root() / "config" / "models.yaml"


def user_data_dir() -> Path:
    raw = os.environ.get(USER_DATA_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _default_user_data_dir()


def runtime_root() -> Path:
    root = user_data_dir()
    return root / "backend"


def runtime_dir(name: str) -> Path:
    path = runtime_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_file(*parts: str) -> Path:
    """Return a path under the runtime root, creating parent directories.

    Despite the name, this returns a Path, not an open file handle.
    Parent directories are created as a side effect.
    """
    path = runtime_root().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def default_config_path() -> Path:
    target = runtime_file("config", "models.yaml")
    if target.exists():
        return target

    source = bundled_config_path()
    if not source.exists():
        raise FileNotFoundError(f"Default model config template not found: {source}")

    try:
        shutil.copy2(source, target)
    except shutil.SameFileError:
        pass
    return target
