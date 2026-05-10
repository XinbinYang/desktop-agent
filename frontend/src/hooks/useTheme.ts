import { useState, useEffect, useCallback } from 'react';

type Theme = 'dark' | 'light' | 'system';

function getSystemTheme(): 'dark' | 'light' {
  if (typeof window === 'undefined') return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function resolveTheme(stored: Theme): 'dark' | 'light' {
  return stored === 'system' ? getSystemTheme() : stored;
}

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem('desktop-agent-theme');
    if (stored === 'dark' || stored === 'light' || stored === 'system') return stored;
  } catch { /* localStorage unavailable */ }
  return 'dark';
}

export function useTheme() {
  const [stored, setStored] = useState<Theme>(getStoredTheme);

  const apply = useCallback((theme: 'dark' | 'light') => {
    document.documentElement.setAttribute('data-theme', theme);
  }, []);

  useEffect(() => {
    const resolved = resolveTheme(stored);
    apply(resolved);
    try {
      localStorage.setItem('desktop-agent-theme', stored);
    } catch { /* ignore */ }
  }, [stored, apply]);

  // Listen for system theme changes when in "system" mode
  useEffect(() => {
    if (stored !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const handler = () => apply(getSystemTheme());
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [stored, apply]);

  const resolved = resolveTheme(stored);

  return {
    theme: stored,
    resolved,
    setTheme: setStored,
    toggle: () => setStored((prev) => {
      const current = resolveTheme(prev);
      return current === 'dark' ? 'light' : 'dark';
    }),
  };
}
