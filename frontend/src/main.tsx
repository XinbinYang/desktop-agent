import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { initApiAuth } from './config';
import { applyResolvedTheme, getStoredTheme, getSystemTheme, resolveTheme } from './lib/theme';
import './i18n';
import './index.css';

function initTheme() {
  try {
    const theme = resolveTheme(getStoredTheme(), getSystemTheme());
    applyResolvedTheme(theme);
  } catch { /* localStorage unavailable */ }
}

async function bootstrap() {
  initTheme();
  await initApiAuth();
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>
  );
}

bootstrap();
