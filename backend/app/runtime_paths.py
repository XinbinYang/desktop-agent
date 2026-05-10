import os
import shutil
import sys
from pathlib import Path


USER_DATA_ENV = "DESKTOP_AGENT_USER_DATA_DIR"


def backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundled_root() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):  # type: ignore[attr-defined]
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return repo_root()


def bundled_config_path() -> Path:
    return bundled_root() / "config" / "models.yaml"


def user_data_dir() -> Path | None:
    raw = os.environ.get(USER_DATA_ENV, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def runtime_root() -> Path:
    root = user_data_dir()
    if root is None:
        return backend_root()
    return root / "backend"


def runtime_dir(name: str) -> Path:
    path = runtime_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_file(*parts: str) -> Path:
    path = runtime_root().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def default_config_path() -> Path:
    if user_data_dir() is None:
        return bundled_config_path()

    target = runtime_file("config", "models.yaml")
    if target.exists():
        return target

    source = bundled_config_path()
    if not source.exists():
        raise FileNotFoundError(f"Default model config template not found: {source}")

    shutil.copyfile(source, target)
    return target
