import type { ResolvedTheme } from './theme';

type MonacoApi = {
  editor: {
    defineTheme: (name: string, theme: unknown) => void;
  };
};

const THEME_NAMES: Record<ResolvedTheme, string> = {
  dark: 'desktop-agent-dark',
  light: 'desktop-agent-light',
};

const FALLBACKS: Record<ResolvedTheme, Record<string, string>> = {
  dark: {
    app: '#0d1117',
    surface: '#161b22',
    surfaceAlt: '#21262d',
    border: '#30363d',
    text: '#e6edf3',
    muted: '#6e7681',
    accent: '#58a6ff',
  },
  light: {
    app: '#ffffff',
    surface: '#f3f3f3',
    surfaceAlt: '#e1e1e1',
    border: '#d4d4d4',
    text: '#1e1e1e',
    muted: '#6b6b6b',
    accent: '#0067b8',
  },
};

const definedSignatures: Partial<Record<ResolvedTheme, string>> = {};

function cssVar(name: string, fallback: string) {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function normalizeHex(value: string, fallback: string) {
  const trimmed = value.trim();
  if (/^#[0-9a-fA-F]{3}$/.test(trimmed)) {
    const [, r, g, b] = trimmed;
    return `#${r}${r}${g}${g}${b}${b}`;
  }
  if (/^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(trimmed)) return trimmed;
  return fallback;
}

function withAlpha(hex: string, alpha: string) {
  const normalized = normalizeHex(hex, hex);
  return normalized.length === 7 ? `${normalized}${alpha}` : normalized;
}

function readThemeTokens(theme: ResolvedTheme) {
  const fallback = FALLBACKS[theme];
  const activeTheme = typeof document === 'undefined'
    ? theme
    : document.documentElement.getAttribute('data-theme');
  const read = (name: string, value: string) => (
    activeTheme === theme ? cssVar(name, value) : value
  );

  const app = normalizeHex(read('--bg-app', fallback.app), fallback.app);
  const surface = normalizeHex(read('--bg-surface', fallback.surface), fallback.surface);
  const surfaceAlt = normalizeHex(read('--bg-surface-alt', fallback.surfaceAlt), fallback.surfaceAlt);
  const border = normalizeHex(read('--border-default', fallback.border), fallback.border);
  const text = normalizeHex(read('--text-primary', fallback.text), fallback.text);
  const muted = normalizeHex(read('--text-muted', fallback.muted), fallback.muted);
  const accent = normalizeHex(read('--text-link', fallback.accent), fallback.accent);

  return { app, surface, surfaceAlt, border, text, muted, accent };
}

export function getMonacoThemeName(theme: ResolvedTheme) {
  return THEME_NAMES[theme];
}

export function ensureMonacoTheme(monaco: MonacoApi, theme: ResolvedTheme) {
  const tokens = readThemeTokens(theme);
  const signature = JSON.stringify(tokens);
  if (definedSignatures[theme] === signature) return;

  monaco.editor.defineTheme(THEME_NAMES[theme], {
    base: theme === 'dark' ? 'vs-dark' : 'vs',
    inherit: true,
    rules: [],
    colors: {
      'editor.background': tokens.app,
      'editor.foreground': tokens.text,
      'editorGutter.background': tokens.app,
      'editorLineNumber.foreground': tokens.muted,
      'editorLineNumber.activeForeground': tokens.text,
      'editorCursor.foreground': tokens.accent,
      'editor.selectionBackground': withAlpha(tokens.accent, theme === 'dark' ? '55' : '33'),
      'editor.inactiveSelectionBackground': withAlpha(tokens.accent, theme === 'dark' ? '2d' : '1f'),
      'editor.lineHighlightBackground': withAlpha(tokens.surfaceAlt, theme === 'dark' ? '66' : 'aa'),
      'editorIndentGuide.background1': tokens.border,
      'editorIndentGuide.activeBackground1': tokens.muted,
      'editorWhitespace.foreground': withAlpha(tokens.muted, '66'),
      'editorWidget.background': tokens.surface,
      'editorWidget.border': tokens.border,
      'editorHoverWidget.background': tokens.surface,
      'editorHoverWidget.border': tokens.border,
      'editorSuggestWidget.background': tokens.surface,
      'editorSuggestWidget.border': tokens.border,
      'editorSuggestWidget.foreground': tokens.text,
      'editorSuggestWidget.selectedBackground': tokens.surfaceAlt,
      'input.background': tokens.surface,
      'input.foreground': tokens.text,
      'input.border': tokens.border,
      focusBorder: withAlpha(tokens.accent, '99'),
    },
  });

  definedSignatures[theme] = signature;
}

export function ensureMonacoThemes(monaco: MonacoApi) {
  ensureMonacoTheme(monaco, 'dark');
  ensureMonacoTheme(monaco, 'light');
}
