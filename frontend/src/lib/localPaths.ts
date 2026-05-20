export interface LocalPathResolveOptions {
  projectPath?: string | null;
  allowProjectRelative?: boolean;
}

const AGENTS_PREFIX_RE = /^agents(?:[\\/]|$)/i;
const WINDOWS_ABSOLUTE_RE = /^[a-zA-Z]:[\\/]/;
const WINDOWS_UNC_RE = /^\\\\[^\\/]+[\\/][^\\/]+/;
const URL_RE = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//;

function cleanCandidate(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value
    .trim()
    .replace(/^["'`]+|["'`.,;:]+$/g, '')
    .trim();
}

export function canRevealLocalPaths(): boolean {
  if (typeof window === 'undefined') return false;
  return !!(window.electronAPI?.revealPath || window.electronAPI?.openPath);
}

export function isAbsoluteLocalPath(value: string): boolean {
  const candidate = cleanCandidate(value);
  if (!candidate || URL_RE.test(candidate)) return false;
  return (
    WINDOWS_ABSOLUTE_RE.test(candidate) ||
    WINDOWS_UNC_RE.test(candidate) ||
    candidate.startsWith('/')
  );
}

export function isAgentsLogicalPath(value: string): boolean {
  const candidate = cleanCandidate(value).replace(/^\.[\\/]/, '');
  return AGENTS_PREFIX_RE.test(candidate);
}

function hasLikelyPathShape(value: string): boolean {
  const candidate = cleanCandidate(value);
  if (!candidate || URL_RE.test(candidate) || /[\r\n]/.test(candidate)) return false;
  if (candidate.includes('*') || candidate.includes('?')) return false;
  return /[\\/]/.test(candidate) && !/^\s*(?:npm|python|pytest|git|cd|ls|dir)\s+/i.test(candidate);
}

function joinProjectPath(projectPath: string, relativePath: string): string {
  const separator = projectPath.includes('\\') || WINDOWS_ABSOLUTE_RE.test(projectPath) ? '\\' : '/';
  const root = projectPath.replace(/[\\/]+$/, '');
  const rel = relativePath
    .replace(/^\.[\\/]/, '')
    .replace(/^[\\/]+/, '')
    .replace(/[\\/]+/g, separator);
  return `${root}${separator}${rel}`;
}

export function resolveLocalPathCandidate(
  value: unknown,
  options: LocalPathResolveOptions = {},
): string | null {
  const candidate = cleanCandidate(value);
  if (!candidate || URL_RE.test(candidate) || /[\r\n]/.test(candidate)) return null;
  if (isAbsoluteLocalPath(candidate) || isAgentsLogicalPath(candidate)) return candidate;
  if (options.allowProjectRelative && options.projectPath && hasLikelyPathShape(candidate)) {
    return joinProjectPath(options.projectPath, candidate);
  }
  return null;
}

export function extractPathFromToolResult(result?: string | null): string | null {
  if (!result) return null;
  const match = result.match(/\b(?:File written|Patched|Deleted|Created|Updated):\s*([^\r\n]+)/i);
  if (!match) return null;
  return cleanCandidate(match[1].replace(/\s+\(matched via .+\)$/i, ''));
}

function firstStringArg(args: Record<string, any> | undefined, keys: string[]): string {
  for (const key of keys) {
    const value = args?.[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}

export function resolveToolCallLocalPath(
  name: string,
  args: Record<string, any> | undefined,
  result: string | undefined,
  options: LocalPathResolveOptions = {},
): string | null {
  const n = (name || '').toLowerCase();
  const isPathTool =
    n.includes('file') ||
    n.includes('path') ||
    n.includes('read') ||
    n.includes('write') ||
    n.includes('patch') ||
    n.includes('delete') ||
    n.includes('list');
  if (!isPathTool) return null;

  const fromResult = resolveLocalPathCandidate(extractPathFromToolResult(result), {
    ...options,
    allowProjectRelative: true,
  });
  if (fromResult) return fromResult;

  return resolveLocalPathCandidate(firstStringArg(args, ['path', 'file', 'file_path']), {
    ...options,
    allowProjectRelative: true,
  });
}

export async function revealLocalPath(targetPath: string): Promise<string | null> {
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api?.revealPath && !api?.openPath) return 'Electron path actions unavailable';

  try {
    const revealError = api.revealPath ? await api.revealPath(targetPath) : 'Reveal path unavailable';
    if (revealError && api.openPath) {
      const openError = await api.openPath(targetPath);
      return openError || null;
    }
    return revealError || null;
  } catch (error) {
    return String(error);
  }
}
