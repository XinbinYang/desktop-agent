from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import psutil
import websockets
import win32con
import win32gui
import win32process
from PIL import ImageGrab, ImageStat


class AcceptanceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_token(user_data_dir: Path) -> str | None:
    token_file = user_data_dir / "local-auth.json"
    if not token_file.exists():
        return None
    try:
        data = json.loads(token_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AcceptanceError(f"Unable to read local auth token file: {exc}") from exc
    token = data.get("token")
    if not isinstance(token, str) or len(token) < 32:
        raise AcceptanceError("Local auth token file exists but does not contain a valid token")
    return token


def get_process_exe(pid: int) -> Path | None:
    try:
        exe = psutil.Process(pid).exe()
    except (psutil.Error, OSError):
        return None
    return Path(exe).resolve() if exe else None


def matching_process_ids(exe_path: Path) -> list[int]:
    expected = exe_path.resolve()
    matches: list[int] = []
    for proc in psutil.process_iter(["pid", "exe"]):
        try:
            exe = proc.info.get("exe")
            if exe and Path(exe).resolve() == expected:
                matches.append(int(proc.info["pid"]))
        except (psutil.Error, OSError):
            continue
    return sorted(matches)


def check_icon_resource(target: Path, key: str, report: dict[str, Any]) -> None:
    large_icons: list[int] = []
    small_icons: list[int] = []
    try:
        large_icons, small_icons = win32gui.ExtractIconEx(str(target), 0)
        icon_count = len(large_icons) + len(small_icons)
        report["checks"][f"{key}_icon_count"] = icon_count
        if icon_count <= 0:
            raise AcceptanceError(f"No icon resource could be extracted from {target}")
    finally:
        for icon_handle in [*large_icons, *small_icons]:
            try:
                win32gui.DestroyIcon(icon_handle)
            except Exception:
                pass


def wait_for_health(base_url: str, user_data_dir: Path, timeout_seconds: int) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    last_error = "backend did not respond"

    while time.monotonic() < deadline:
        token = read_token(user_data_dir)
        if token:
            try:
                with httpx.Client(timeout=3.0) as client:
                    response = client.get(
                        f"{base_url}/api/health",
                        headers={"X-Desktop-Agent-Token": token},
                    )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "ok":
                        return token, data
                    last_error = f"health returned unexpected payload: {data}"
                else:
                    last_error = f"health returned HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001 - this is diagnostics code
                last_error = str(exc)
        time.sleep(0.5)

    raise AcceptanceError(f"Backend health check timed out after {timeout_seconds}s: {last_error}")


def check_rest_api(base_url: str, token: str, report: dict[str, Any]) -> None:
    headers = {"X-Desktop-Agent-Token": token}
    with httpx.Client(timeout=10.0) as client:
        no_auth = client.get(f"{base_url}/api/health")
        report["checks"]["rest_without_token_status"] = no_auth.status_code
        if no_auth.status_code != 401:
            raise AcceptanceError(f"Expected unauthenticated REST health to return 401, got {no_auth.status_code}")

        health = client.get(f"{base_url}/api/health", headers=headers)
        report["checks"]["rest_with_token_status"] = health.status_code
        if health.status_code != 200 or health.json().get("status") != "ok":
            raise AcceptanceError(f"Authenticated health failed: HTTP {health.status_code}")
        report["checks"]["tool_count"] = health.json().get("tools")


async def check_websocket(ws_url: str, token: str, report: dict[str, Any]) -> None:
    no_token_failed = False
    try:
        async with websockets.connect(f"{ws_url}/ws/gui-acceptance-no-token", open_timeout=5) as ws:
            await ws.send(json.dumps({"type": "clear"}))
            await asyncio.wait_for(ws.recv(), timeout=2)
    except Exception:  # noqa: BLE001 - any failure here means auth rejected the connection
        no_token_failed = True

    report["checks"]["ws_without_token_failed"] = no_token_failed
    if not no_token_failed:
        raise AcceptanceError("Expected unauthenticated WebSocket connection to fail")

    async with websockets.connect(
        f"{ws_url}/ws/gui-acceptance?token={token}",
        open_timeout=5,
        origin="file://",
    ) as ws:
        await ws.send(json.dumps({"type": "clear"}))
        seen_types: list[str] = []
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AcceptanceError(f"Timed out waiting for WebSocket cleared response; saw {seen_types}")
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            message_type = message.get("type")
            if isinstance(message_type, str):
                seen_types.append(message_type)
            if message_type == "cleared":
                report["checks"]["ws_clear_response"] = message_type
                report["checks"]["ws_events_before_clear"] = seen_types
                return


def check_project_file_api(base_url: str, token: str, report: dict[str, Any]) -> None:
    headers = {"X-Desktop-Agent-Token": token}
    root = Path(tempfile.gettempdir()) / f"desktop-agent-gui-acceptance-{int(time.time())}"
    project_dir = root / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    outside = root / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    try:
        with httpx.Client(timeout=10.0) as client:
            opened = client.post(f"{base_url}/api/projects/open", headers=headers, json={"path": str(project_dir)})
            opened_json = opened.json()
            report["checks"]["project_open_status"] = opened.status_code
            report["checks"]["project_open_has_error"] = "error" in opened_json
            if opened.status_code != 200 or "error" in opened_json:
                raise AcceptanceError(f"Project open failed: {opened_json}")
            if opened_json.get("path") != str(project_dir.resolve()):
                raise AcceptanceError(f"Project open returned wrong path: {opened_json.get('path')}")

            file_path = project_dir / "acceptance.txt"
            write = client.post(
                f"{base_url}/api/file/write",
                headers=headers,
                json={"path": str(file_path), "content": "gui acceptance ok"},
            )
            write_json = write.json()
            report["checks"]["file_write_status"] = write_json.get("status")
            if write.status_code != 200 or write_json.get("status") != "ok":
                raise AcceptanceError(f"Project file write failed: {write_json}")

            read = client.get(f"{base_url}/api/file/read", headers=headers, params={"path": str(file_path)})
            read_json = read.json()
            report["checks"]["file_read_content"] = read_json.get("content")
            if read.status_code != 200 or read_json.get("content") != "gui acceptance ok":
                raise AcceptanceError(f"Project file read failed: {read_json}")

            denied = client.get(f"{base_url}/api/file/read", headers=headers, params={"path": str(outside)})
            denied_json = denied.json()
            report["checks"]["outside_read_denied"] = "error" in denied_json
            if denied.status_code != 200 or "error" not in denied_json:
                raise AcceptanceError(f"Outside project file read was not denied: {denied_json}")

            closed = client.post(f"{base_url}/api/projects/close", headers=headers)
            report["checks"]["project_close_status"] = closed.json().get("status")
            if closed.status_code != 200 or closed.json().get("status") != "closed":
                raise AcceptanceError(f"Project close failed: HTTP {closed.status_code}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def enum_target_windows(exe_path: Path) -> list[dict[str, Any]]:
    expected = exe_path.resolve()
    windows: list[dict[str, Any]] = []

    def callback(hwnd: int, _: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_exe = get_process_exe(pid)
            if proc_exe != expected:
                return
            title = win32gui.GetWindowText(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 100 or height <= 100:
                return
            windows.append({
                "hwnd": hwnd,
                "pid": pid,
                "title": title,
                "rect": rect,
                "class": win32gui.GetClassName(hwnd),
            })
        except Exception:
            return

    win32gui.EnumWindows(callback, None)
    windows.sort(key=lambda item: (item["title"] != "Desktop Agent", item["pid"]))
    return windows


def wait_for_window(exe_path: Path, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        windows = enum_target_windows(exe_path)
        if windows:
            return windows[0]
        time.sleep(0.5)
    raise AcceptanceError(f"No visible Desktop Agent window appeared within {timeout_seconds}s")


def capture_window(window: dict[str, Any], screenshot_path: Path) -> dict[str, Any]:
    hwnd = int(window["hwnd"])
    title = str(window["title"])
    if title.lower() == "error":
        raise AcceptanceError("Desktop Agent opened an Error dialog instead of the main window")
    if title != "Desktop Agent":
        raise AcceptanceError(f"Unexpected window title: {title!r}")

    left, top, right, bottom = window["rect"]
    width = min(max(right - left, 1000), 1500)
    height = min(max(bottom - top, 600), 900)

    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOPMOST,
        80,
        80,
        width,
        height,
        win32con.SWP_SHOWWINDOW,
    )
    time.sleep(1.0)

    rect = win32gui.GetWindowRect(hwnd)
    image = ImageGrab.grab(bbox=rect)
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(screenshot_path)

    stat = ImageStat.Stat(image.convert("L"))
    extrema = stat.extrema[0]
    if image.width < 100 or image.height < 100 or extrema[0] == extrema[1]:
        raise AcceptanceError("Window screenshot appears blank")

    return {
        "hwnd": hwnd,
        "pid": int(window["pid"]),
        "title": title,
        "rect": list(rect),
        "size": [image.width, image.height],
        "grayscale_extrema": list(extrema),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    exe_path = Path(args.exe).resolve()
    backend_exe = Path(args.backend_exe).resolve()
    installer_path = Path(args.installer).resolve()
    user_data_dir = Path(args.user_data_dir).resolve()
    screenshot_path = Path(args.screenshot).resolve()

    report: dict[str, Any] = {
        "ok": False,
        "started_at": utc_now(),
        "release_dir": str(Path(args.release_dir).resolve()),
        "electron_exe": str(exe_path),
        "backend_exe": str(backend_exe),
        "installer": str(installer_path),
        "user_data_dir": str(user_data_dir),
        "checks": {},
        "artifacts": {"screenshot": str(screenshot_path)},
    }

    if not installer_path.exists():
        raise AcceptanceError(f"Packaged installer is missing: {installer_path}")
    check_icon_resource(exe_path, "electron_exe", report)
    check_icon_resource(installer_path, "installer", report)

    token, health = wait_for_health(args.base_url, user_data_dir, args.timeout_seconds)
    report["checks"]["health_status"] = health.get("status")
    report["checks"]["health_tool_count"] = health.get("tools")

    backend_pids = matching_process_ids(backend_exe)
    report["checks"]["backend_process_count"] = len(backend_pids)
    report["checks"]["backend_pids"] = backend_pids
    if not backend_pids:
        raise AcceptanceError(f"No backend process found at expected path: {backend_exe}")

    check_rest_api(args.base_url, token, report)
    asyncio.run(check_websocket(args.ws_url, token, report))
    check_project_file_api(args.base_url, token, report)

    window = wait_for_window(exe_path, timeout_seconds=30)
    report["checks"]["window"] = capture_window(window, screenshot_path)

    report["ok"] = True
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Desktop Agent packaged GUI acceptance helper")
    parser.add_argument("--release-dir", required=True)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--backend-exe", required=True)
    parser.add_argument("--installer", required=True)
    parser.add_argument("--user-data-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--screenshot", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8765")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        report = run(args)
        return_code = 0
    except Exception as exc:  # noqa: BLE001 - report the failing acceptance check
        report = {
            "ok": False,
            "started_at": utc_now(),
            "finished_at": utc_now(),
            "error": str(exc),
            "checks": {},
            "artifacts": {"screenshot": str(Path(args.screenshot).resolve())},
        }
        return_code = 1

    report["finished_at"] = utc_now()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": report.get("ok"),
        "report": str(report_path),
        "screenshot": report.get("artifacts", {}).get("screenshot"),
        "error": report.get("error"),
    }, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    sys.exit(main())
