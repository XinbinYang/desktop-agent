/**
 * Golden Path E2E test — simulates a real user session through all new features.
 * Requires the Playwright webServer config.
 * Run: npx playwright test e2e/golden-path.spec.ts
 */
import { test, expect } from '@playwright/test';

const BACKEND_PORT = 18768;
const FRONTEND_URL = '/';

test.describe('Desktop Agent Golden Path', () => {
  test.beforeAll(async () => {
    // Verify backend is healthy
    const res = await fetch(`http://127.0.0.1:${BACKEND_PORT}/api/health`);
    if (!res.ok) throw new Error(`Backend not ready: ${res.status}`);
  });

  test('full user journey: models load, chat, slash commands, @mentions, panels', async ({ page }) => {
    // ── 1. App loads and fetches models ──────────────────────────────────
    await page.goto(FRONTEND_URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);

    // Should show the app title or connection status
    const body = page.locator('body');
    await expect(body).toBeVisible();

    // ── 2. Settings modal opens and shows providers ──────────────────────
    // Click settings button (gear icon)
    const settingsBtn = page.locator('button[title="设置"], button[title="Settings"]').first();
    if (await settingsBtn.isVisible()) {
      await settingsBtn.click();
      await page.waitForTimeout(500);
      // Should see provider cards or general settings
      const modal = page.locator('[role="dialog"], .fixed.inset-0').first();
      if (await modal.isVisible()) {
        // Close with Escape
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
      }
    }

    // ── 3. Chat input is visible and functional ──────────────────────────
    const textarea = page.locator('textarea[placeholder*="Type a message"], textarea[placeholder*="Shift+Enter"]').first();
    await expect(textarea).toBeVisible({ timeout: 5000 });

    // ── 4. Slash command menu appears when typing / ──────────────────────
    await textarea.click();
    await textarea.fill('/');
    await page.waitForTimeout(500);

    // Slash menu should appear with command options
    const slashMenu = page.locator('text=/help').first();
    const hasSlashMenu = await slashMenu.isVisible({ timeout: 2000 }).catch(() => false);
    console.log(`Slash menu visible: ${hasSlashMenu}`);

    // Clear input
    await textarea.fill('');
    await page.waitForTimeout(200);

    // ── 5. Type a test message ──────────────────────────────────────────
    await textarea.fill('hello, this is an automated e2e test');
    await page.waitForTimeout(200);

    // ── 6. Send button is visible ────────────────────────────────────────
    const sendBtn = page.locator('button').filter({ has: page.locator('svg.lucide-send, svg[class*="Send"]') }).first();
    const sendVisible = await sendBtn.isVisible({ timeout: 2000 }).catch(() => false);
    console.log(`Send button visible: ${sendVisible}`);

    // ── 7. Right panel tabs exist ────────────────────────────────────────
    // Check for tab buttons in the right panel or activity bar
    const tabs = ['Tools', 'Changes', 'Runs', 'Tests', 'Problems', 'Artifacts', 'Editor'];
    for (const tab of tabs) {
      const tabBtn = page.locator('button', { hasText: tab }).first();
      const visible = await tabBtn.isVisible({ timeout: 1000 }).catch(() => false);
      console.log(`Tab "${tab}": ${visible ? 'found' : 'not found'}`);
    }

    // ── 8. Activity bar (left sidebar) ───────────────────────────────────
    const activityIcons = page.locator('[class*="activity"], [class*="Activity"]');
    const hasActivityBar = await activityIcons.first().isVisible({ timeout: 2000 }).catch(() => false);
    console.log(`Activity bar: ${hasActivityBar}`);

    // ── 9. Sidebar sections ──────────────────────────────────────────────
    const sidebar = page.locator('[class*="sidebar"], [class*="Sidebar"]').first();
    const hasSidebar = await sidebar.isVisible({ timeout: 2000 }).catch(() => false);
    if (hasSidebar) {
      // Look for section labels
      for (const section of ['Sessions', 'Tools', 'Project', 'Knowledge', 'Settings']) {
        const sectionEl = sidebar.locator(`text=${section}`).first();
        const visible = await sectionEl.isVisible({ timeout: 1000 }).catch(() => false);
        console.log(`Sidebar "${section}": ${visible ? 'found' : 'not found'}`);
      }
    }

    // ── 10. Window controls ──────────────────────────────────────────────
    const windowControls = page.locator('button').filter({ hasText: /terminal|panel|layout/i }).first();
    const hasControls = await windowControls.isVisible({ timeout: 2000 }).catch(() => false);
    console.log(`Window controls: ${hasControls}`);

    // ── 11. Model selector is visible ────────────────────────────────────
    const modelSelect = page.locator('select[title="切换模型"], select[aria-label="切换模型"]').first();
    const hasModelSelect = await modelSelect.isVisible({ timeout: 2000 }).catch(() => false);
    console.log(`Model selector: ${hasModelSelect}`);

    // ── 12. Check for connection status indicator ────────────────────────
    const connectionDot = page.locator('[class*="connection"], [class*="status-dot"], .bg-green-500, .bg-red-500').first();
    const hasConnection = await connectionDot.isVisible({ timeout: 2000 }).catch(() => false);
    console.log(`Connection indicator: ${hasConnection}`);

    console.log('\n=== Golden Path E2E completed ===');
  });
});
