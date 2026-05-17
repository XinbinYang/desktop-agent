import { useState, useEffect, useCallback } from 'react';
import {
  THEME_CHANGE_EVENT,
  THEME_STORAGE_KEY,
  applyResolvedTheme,
  broadcastThemePreference,
  getStoredTheme,
  getSystemTheme,
  isThemePreference,
  resolveTheme,
  type ThemePreference,
} from '../lib/theme';

export function useTheme() {
  const [stored, setStoredState] = useState<ThemePreference>(getStoredTheme);
  const [systemTheme, setSystemTheme] = useState(getSystemTheme);

  const resolved = resolveTheme(stored, systemTheme);

  const setTheme = useCallback((theme: ThemePreference) => {
    setStoredState((current) => (current === theme ? current : theme));
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // ignore
    }
    broadcastThemePreference(theme);
  }, []);

  useEffect(() => {
    applyResolvedTheme(resolved);
  }, [resolved]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const handler = () => setSystemTheme(getSystemTheme());
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  useEffect(() => {
    const syncPreference = (theme: ThemePreference) => {
      setStoredState((current) => (current === theme ? current : theme));
    };

    const onThemeChange = (event: Event) => {
      const theme = (event as CustomEvent<{ theme?: unknown }>).detail?.theme;
      if (isThemePreference(theme)) syncPreference(theme);
    };

    const onStorage = (event: StorageEvent) => {
      if (event.key !== THEME_STORAGE_KEY) return;
      if (isThemePreference(event.newValue)) syncPreference(event.newValue);
    };

    window.addEventListener(THEME_CHANGE_EVENT, onThemeChange);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(THEME_CHANGE_EVENT, onThemeChange);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  return {
    theme: stored,
    resolved,
    setTheme,
    toggle: () => setTheme(resolved === 'dark' ? 'light' : 'dark'),
  };
}
