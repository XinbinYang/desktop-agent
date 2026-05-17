export type ThemePreference = 'dark' | 'light' | 'system';
export type ResolvedTheme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'desktop-agent-theme';
export const THEME_CHANGE_EVENT = 'desktop-agent-theme-change';

export function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'dark' || value === 'light' || value === 'system';
}

export function resolveTheme(preference: ThemePreference, systemTheme = getSystemTheme()): ResolvedTheme {
  return preference === 'system' ? systemTheme : preference;
}

export function getStoredTheme(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemePreference(stored)) return stored;
  } catch {
    // localStorage may be unavailable in restricted contexts.
  }
  return 'dark';
}

export function applyResolvedTheme(theme: ResolvedTheme) {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.colorScheme = theme;
  }

  if (typeof window !== 'undefined') {
    void window.electronAPI?.setTheme?.(theme);
  }
}

export function broadcastThemePreference(theme: ThemePreference) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: { theme } }));
}
