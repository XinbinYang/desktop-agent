import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { getAuthUnavailableReason, initApiAuth } from './config';
import { applyResolvedTheme, getStoredTheme, getSystemTheme, resolveTheme } from './lib/theme';
import './i18n';
import './index.css';

function initTheme() {
  try {
    const theme = resolveTheme(getStoredTheme(), getSystemTheme());
    applyResolvedTheme(theme);
  } catch { /* localStorage unavailable */ }
}

function getRootElement(): HTMLElement {
  const root = document.getElementById('root');
  if (!root) {
    throw new Error('Missing #root element');
  }
  return root;
}

function renderFatalStartupError(error: unknown) {
  console.error('[Desktop Agent] Renderer bootstrap failed:', error);
  const root = document.getElementById('root');
  if (!root) return;

  const container = document.createElement('div');
  container.className = 'h-screen flex items-center justify-center bg-app text-fg px-6';

  const panel = document.createElement('div');
  panel.className = 'max-w-lg rounded-md border border-border bg-surface p-5 shadow-lg';

  const title = document.createElement('h1');
  title.className = 'text-base font-semibold text-danger mb-2';
  title.textContent = 'Desktop Agent 启动失败';

  const message = document.createElement('p');
  message.className = 'text-sm text-fg-secondary whitespace-pre-wrap';
  message.textContent = error instanceof Error ? error.message : String(error || '未知错误');

  const hint = document.createElement('p');
  hint.className = 'mt-3 text-xs text-fg-muted';
  hint.textContent = '请查看 Electron 控制台日志，或刷新窗口重试。';

  panel.append(title, message, hint);
  container.append(panel);
  root.replaceChildren(container);
}

async function bootstrap() {
  initTheme();
  await initApiAuth();
  const authUnavailableReason = getAuthUnavailableReason();
  if (authUnavailableReason) {
    throw new Error(authUnavailableReason);
  }
  ReactDOM.createRoot(getRootElement()).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>
  );
}

bootstrap().catch(renderFatalStartupError);
