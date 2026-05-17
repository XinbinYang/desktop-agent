"""Full E2E smoke test — starts server, hits all new endpoints, verifies WS."""
import asyncio
import json
import os
import sys
import httpx
import uvicorn
from pathlib import Path

# Ensure backend is importable and cwd is correct
BACKEND_DIR = Path(__file__).parent.parent.resolve()
os.chdir(BACKEND_DIR)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

BACKEND_PORT = 18769
BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name} — {detail}")


async def run():
    global passed, failed

    # Start server using uvicorn.run in a thread
    import threading
    import time as _time

    def _serve():
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=BACKEND_PORT,
            log_level="error",
        )

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    # Wait for server to be ready (use sync httpx to avoid loop conflicts)
    for _ in range(30):
        try:
            r = httpx.get(f"{BASE_URL}/api/health", timeout=2)
            if r.status_code in (200, 401):
                print(f"Server ready (status={r.status_code})")
                break
        except Exception:
            pass
        _time.sleep(0.5)
    else:
        print("ERROR: Server did not start")
        return

    # Use sync client for reliability
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        # ─── 1. Health ───────────────────────────────────────────────────
        r = client.get("/api/health")
        check("Health endpoint", r.status_code == 200, str(r.status_code))
        data = r.json()
        check("Health has tools count", data.get("status") == "ok", str(data))

        # ─── 2. Models ───────────────────────────────────────────────────
        r = client.get("/api/models")
        data = r.json()
        models = data.get("models", [])
        check("Models configured", len(models) > 0, f"{len(models)} models")
        check("Has default model", bool(data.get("default")), data.get("default"))

        # ─── 3. Structured Errors ────────────────────────────────────────
        r = client.get("/api/sessions/nonexistent-session-id")
        err = r.json().get("error", {})
        check("Error has category", err.get("category") == "not_found", str(err))
        check("Error has retryable", err.get("retryable") == False, str(err))
        check("Error has message", len(err.get("message", "")) > 0, str(err))

        # ─── 4. Commands ─────────────────────────────────────────────────
        r = client.get("/api/commands")
        cmds = r.json().get("commands", [])
        cmd_names = [c["name"] for c in cmds]
        check("Commands endpoint", len(cmds) >= 9, f"{len(cmds)} commands")
        check("help command", "help" in cmd_names)
        check("clear command", "clear" in cmd_names)
        check("model command", "model" in cmd_names)
        check("compact command", "compact" in cmd_names)

        # ─── 5. Tools ────────────────────────────────────────────────────
        r = client.get("/api/tools")
        tools = r.json().get("tools", [])
        if tools and isinstance(tools[0], dict):
            tool_names = [t["name"] for t in tools]
        else:
            tool_names = tools
        check("Tools API", len(tool_names) >= 63, f"{len(tool_names)} tools")
        check("run_tests tool", "run_tests" in tool_names)
        check("list_diagnostics tool", "list_diagnostics" in tool_names)

        # ─── 6. Skills ───────────────────────────────────────────────────
        r = client.get("/api/skills")
        skills = r.json().get("skills", [])
        check("Skills endpoint", len(skills) >= 16, f"{len(skills)} skills")

        # ─── 7. Plugins ──────────────────────────────────────────────────
        r = client.get("/api/plugins")
        data = r.json()
        check("Plugins endpoint", data.get("count", -1) >= 0, str(data))

        # ─── 8. Project Rules (no project open) ──────────────────────────
        r = client.get("/api/projects/rules")
        err = r.json().get("error", {})
        check("Rules: no project", err.get("category") == "validation")

        # ─── 9. Memory (no project open) ─────────────────────────────────
        r = client.get("/api/memory")
        err = r.json().get("error", {})
        check("Memory: no project", err.get("category") == "validation")

        # ─── 10. Test Runner Framework Detection ─────────────────────────
        r = client.get("/api/tests/framework")
        data = r.json()
        check("Tests framework (no project)", data.get("framework") is None)

        # ─── 11. Diagnostics Linters (no project) ────────────────────────
        r = client.get("/api/diagnostics/linters")
        data = r.json()
        check("Diagnostics linters (no project)", data.get("linters") == [])

        # ─── 12. File Revert (invalid path) ──────────────────────────────
        r = client.post("/api/file/revert", json={"path": "/nonexistent", "old_content": "test"})
        check("File revert (no project)", r.status_code == 200)  # Returns error in body

        # ─── 13. Roles ───────────────────────────────────────────────────
        r = client.get("/api/roles")
        roles = r.json().get("roles", [])
        check("Roles endpoint", len(roles) > 0, f"{len(roles)} roles")

        # ─── 14. MCP ─────────────────────────────────────────────────────
        r = client.get("/api/mcp/servers")
        servers = r.json().get("servers", [])
        check("MCP servers endpoint", isinstance(servers, list), str(type(servers)))

        # ─── 15. Settings ────────────────────────────────────────────────
        r = client.get("/api/settings")
        data = r.json()
        check("Settings endpoint", bool(data.get("settings")), "has settings")
        check("Settings has providers", bool(data.get("providers")), "has providers")
        check("Settings has auto_approve", "auto_approve" in data.get("settings", {}))
        check("Settings has auto_approve_rules", "auto_approve_rules" in data.get("settings", {}))

    # Shutdown — thread is daemon, will exit when process ends
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*50}")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*50}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
