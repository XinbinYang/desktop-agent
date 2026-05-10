import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { initApiAuth } from './config';
import './i18n';
import './index.css';

function initTheme() {
  try {
    const stored = localStorage.getItem('desktop-agent-theme') || 'dark';
    const theme =
      stored === 'system'
        ? window.matchMedia('(prefers-color-scheme: light)').matches
          ? 'light'
          : 'dark'
        : stored;
    document.documentElement.setAttribute('data-theme', theme);
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
