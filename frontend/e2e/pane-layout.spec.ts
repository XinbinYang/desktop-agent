import { expect, test } from '@playwright/test';

const paneTree = {
  version: 2,
  focusedLeafId: 'leaf-a',
  paneRoot: {
    type: 'split',
    id: 'root',
    direction: 'horizontal',
    children: [
      {
        type: 'leaf',
        id: 'leaf-a',
        pane: { id: 'pane-a', sessionId: 'session-a', model: 'gpt-test', role: 'desktop-agent' },
      },
      {
        type: 'split',
        id: 'nested',
        direction: 'vertical',
        children: [
          {
            type: 'leaf',
            id: 'leaf-b',
            pane: { id: 'pane-b', sessionId: 'session-b', model: 'gpt-test', role: 'desktop-agent' },
          },
          {
            type: 'leaf',
            id: 'leaf-c',
            pane: { id: 'pane-c', sessionId: 'session-c', model: 'gpt-test', role: 'desktop-agent' },
          },
        ],
        sizes: [35, 65],
      },
    ],
    sizes: [48, 52],
  },
};

async function mockBackend(page: import('@playwright/test').Page) {
  await page.route('**/api/models', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      models: [{ id: 'gpt-test', name: 'GPT Test', provider: 'test', vision: false, context: 1000 }],
      default: 'gpt-test',
    }),
  }));
  await page.route('**/api/roles', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ roles: [{ id: 'desktop-agent', name: 'Desktop Agent', description: '', builtin: true }] }),
  }));
  await page.route('**/api/sessions', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ sessions: [] }),
  }));
  await page.route('**/api/session-history', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ current_project_path: null, projects: [], standalone_sessions: [] }),
  }));
  await page.route('**/api/settings', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      providers: {
        test: {
          name: 'test',
          base_url: 'http://127.0.0.1/test',
          api_key_configured: true,
          models: [{ id: 'gpt-test', name: 'GPT Test', provider: 'test', vision: false, context: 1000 }],
        },
      },
      settings: { default_model: 'gpt-test', default_provider: 'test' },
    }),
  }));
}

test.describe('pane layout', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackend(page);
    await page.addInitScript((tree) => {
      localStorage.clear();
      localStorage.setItem('desktop-agent-pane-tree', JSON.stringify(tree));
      localStorage.setItem('desktop-agent-layout', JSON.stringify({
        activeSection: 'tools',
        activeAgent: 'coding',
        showTerminal: true,
        rightZone: 'workspace',
        rightPanelVisible: true,
        sidebarCollapsed: true,
        mainLayout: { center: 70, right: 30 },
        terminalLayout: { conversation: 78, terminal: 22 },
      }));
    }, paneTree);
  });

  test('closes nested panes and persists the updated tree', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByLabel('Close pane')).toHaveCount(3);
    await page.getByLabel('Close pane').nth(1).click();

    await expect(page.getByLabel('Close pane')).toHaveCount(2);
    await page.waitForFunction(() => {
      const raw = localStorage.getItem('desktop-agent-pane-tree');
      return raw && !raw.includes('leaf-b') && !raw.includes('session-b');
    });
  });

  test('reset layout keeps sessions while resetting split sizes', async ({ page }) => {
    await page.goto('/');

    await page.getByLabel('Reset Layout').click();

    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('desktop-agent-pane-tree') || '{}'));
    expect(JSON.stringify(stored)).toContain('session-a');
    expect(JSON.stringify(stored)).toContain('session-b');
    expect(stored.paneRoot.sizes).toEqual([50, 50]);
  });
});
