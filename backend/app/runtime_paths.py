import os
import shutil
import sys
from pathlib import Path


USER_DATA_ENV = "DESKTOP_AGENT_USER_DATA_DIR"


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


def agents_dir() -> Path:
    """Mutable Agent workspace under the runtime data directory.

    The repository keeps seed templates in ``AGENTS/``. Runtime persona,
    memory, skills, and handoff files live in user data so normal app usage and
    tests do not dirty the git worktree.
    """
    target = runtime_root() / "AGENTS"
    _copy_missing_tree(bundled_agents_dir(), target)
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
