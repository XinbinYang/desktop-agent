"""Shared WindPy runtime discovery and connection helpers."""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


COMMON_WINDPY_DIRS = (
    Path(r"C:\Wind\Wind.NET.Client\WindNET\x64"),
    Path(r"C:\Wind\Wind.NET.Client\WindNET\x86"),
    Path(r"C:\Wind\Wind.NET.Client\WindNET"),
)


@dataclass(frozen=True)
class WindRuntimeInfo:
    import_dir: Path | None
    attempted_paths: tuple[str, ...]
    import_source: str


class WindRuntimeError(RuntimeError):
    def __init__(self, message: str, *, attempted_paths: list[str] | tuple[str, ...] = ()) -> None:
        self.attempted_paths = tuple(attempted_paths)
        super().__init__(_format_wind_error(message, self.attempted_paths))


_wind_client = None
_wind_info: WindRuntimeInfo | None = None
_dll_handles: list[object] = []


def _format_wind_error(message: str, attempted_paths: tuple[str, ...]) -> str:
    attempted = ", ".join(attempted_paths) if attempted_paths else "(installed Python module lookup only)"
    return (
        f"{message}\n"
        f"Current CWD: {os.getcwd()}\n"
        f"Attempted WindPy paths: {attempted}\n"
        "Set WINDPY_PATH to the directory containing WindPy.py, for example "
        r"C:\Wind\Wind.NET.Client\WindNET\x64, or set WIND_HOME to the Wind install root."
    )


def _env_candidates() -> list[Path]:
    candidates: list[Path] = []
    for name in ("WINDPY_PATH",):
        raw = os.environ.get(name, "").strip().strip('"')
        if raw:
            candidates.append(Path(raw))

    raw_home = os.environ.get("WIND_HOME", "").strip().strip('"')
    if raw_home:
        home = Path(raw_home)
        candidates.extend(
            [
                home,
                home / "Wind.NET.Client" / "WindNET" / "x64",
                home / "Wind.NET.Client" / "WindNET" / "x86",
                home / "Wind.NET.Client" / "WindNET",
            ]
        )
    return candidates


def candidate_windpy_dirs() -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in [*_env_candidates(), *COMMON_WINDPY_DIRS]:
        directory = candidate.parent if candidate.suffix.lower() == ".py" else candidate
        key = str(directory)
        if key in seen:
            continue
        seen.add(key)
        result.append(directory)
    return result


def _looks_like_windpy_dir(path: Path) -> bool:
    return path.is_dir() and ((path / "WindPy.py").exists() or (path / "WindPy.pth").exists())


def resolve_wind_runtime() -> WindRuntimeInfo:
    attempted: list[str] = []
    for directory in candidate_windpy_dirs():
        attempted.append(str(directory))
        if not _looks_like_windpy_dir(directory):
            continue
        _configure_import_dir(directory)
        return WindRuntimeInfo(directory.resolve(), tuple(attempted), "path")

    if importlib.util.find_spec("WindPy") is not None:
        return WindRuntimeInfo(None, tuple(attempted), "module")

    raise WindRuntimeError("WindPy module was not found.", attempted_paths=attempted)


def _configure_import_dir(directory: Path) -> None:
    path_text = str(directory)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if callable(add_dll_directory):
        try:
            _dll_handles.append(add_dll_directory(path_text))
        except OSError:
            pass


@contextlib.contextmanager
def _wind_cwd(directory: Path | None) -> Iterator[None]:
    if directory is None:
        yield
        return
    old_cwd = os.getcwd()
    try:
        os.chdir(str(directory))
        yield
    finally:
        os.chdir(old_cwd)


def get_wind_client():
    """Return a connected WindPy ``w`` client with helpful diagnostics."""
    global _wind_client, _wind_info
    if _wind_client is not None:
        try:
            if _wind_client.isconnected():
                return _wind_client
        except Exception:
            _wind_client = None

    info = resolve_wind_runtime()
    try:
        with _wind_cwd(info.import_dir):
            module = importlib.import_module("WindPy")
            w = module.w
            if not w.isconnected():
                result = w.start()
                if getattr(result, "ErrorCode", 0) != 0:
                    raise WindRuntimeError(
                        f"Wind connection failed: {getattr(result, 'Data', '')}",
                        attempted_paths=info.attempted_paths,
                    )
    except WindRuntimeError:
        raise
    except Exception as exc:
        raise WindRuntimeError(f"WindPy import/start failed: {exc}", attempted_paths=info.attempted_paths) from exc

    _wind_client = w
    _wind_info = info
    return w


def reset_wind_runtime_for_tests() -> None:
    global _wind_client, _wind_info
    _wind_client = None
    _wind_info = None
