"""Browser-based E2E test — simulates a user in the Desktop Agent UI."""
import subprocess, sys, time, os, signal
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.resolve()
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

# Kill leftover node processes from previous tests
subprocess.run("taskkill /f /im node.exe", shell=True, capture_output=True)
time.sleep(1)

# Start backend (reuse the one from e2e_smoke if still running)
# Start frontend
print("Starting Vite dev server...")
# Find node/npm path
import shutil
node_dir = str(Path(shutil.which("node") or "").parent) if shutil.which("node") else ""
npm_cmd = str(Path(shutil.which("npm") or shutil.which("npm.cmd") or ""))
print(f"Node: {node_dir}, npm: {npm_cmd}")

vite = subprocess.Popen(
    f'"{npm_cmd}" exec vite -- --port 15177 --strictPort',
    cwd=str(FRONTEND_DIR), shell=True,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)

# Wait for Vite with retries
import urllib.request
for i in range(20):
    time.sleep(1.5)
    try:
        resp = urllib.request.urlopen("http://localhost:15177", timeout=3)
        print(f"Frontend ready: HTTP {resp.status} (after {i+1} retries)")
        break
    except Exception:
        if i == 19:
            print(f"Frontend did not start after 30s")
            # Check for errors
            try:
                _, stderr = vite.communicate(timeout=1)
                print(f"Vite stderr: {stderr.decode()[:500] if stderr else 'none'}")
            except:
                pass
            vite.kill()
            sys.exit(1)

# Run Playwright browser test
from playwright.sync_api import sync_playwright
import json

PASSED = 0
FAILED = 0

def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name} - {detail}")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    print("\n=== Opening Desktop Agent ===")
    page.goto("http://localhost:15177", wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(2000)

    # Take screenshot for reference
    page.screenshot(path=str(BACKEND_DIR / "tests" / "e2e_screenshot_initial.png"))
    print("Screenshot saved: tests/e2e_screenshot_initial.png")

    # ── 1. App rendered ──────────────────────────────────────────────────
    body_text = page.locator("body").inner_text()
    check("App renders", len(body_text) > 10, f"Body length: {len(body_text)}")

    # ── 2. Chat textarea ─────────────────────────────────────────────────
    textarea = page.locator("textarea").first
    if textarea.is_visible(timeout=3000):
        check("Chat textarea visible", True)
        textarea.click()
        textarea.fill("/")
        page.wait_for_timeout(500)
        # Should see slash command menu
        menu_visible = page.locator("text=help").first.is_visible(timeout=2000)
        check("Slash menu appears for /", menu_visible)
    else:
        check("Chat textarea visible", False, "textarea not found")

    # ── 3. Sidebar ───────────────────────────────────────────────────────
    sidebar_buttons = page.locator("button").all()
    check("Has buttons in UI", len(sidebar_buttons) > 3, f"{len(sidebar_buttons)} buttons")

    # ── 4. Look for key UI strings ───────────────────────────────────────
    for keyword in ["Send", "Tools", "Settings", "Sessions", "Model"]:
        found = page.locator(f"text={keyword}").first.is_visible(timeout=1000)
        check(f"UI has '{keyword}'", found)

    # ── 5. Type a message and check send button ─────────────────────────
    textarea = page.locator("textarea").first
    if textarea.is_visible():
        textarea.fill("hello e2e test")
        page.wait_for_timeout(300)
        val = textarea.input_value()
        check("Input accepts text", val == "hello e2e test", val)

    # ── 6. Screenshot final state ────────────────────────────────────────
    page.screenshot(path=str(BACKEND_DIR / "tests" / "e2e_screenshot_final.png"))
    print("Screenshot saved: tests/e2e_screenshot_final.png")

    browser.close()

# Cleanup
vite.kill()
vite.wait(timeout=5)

print(f"\n{'='*50}")
print(f"Browser E2E: {PASSED} passed, {FAILED} failed, {PASSED+FAILED} total")
print(f"{'='*50}")

if FAILED > 0:
    sys.exit(1)
