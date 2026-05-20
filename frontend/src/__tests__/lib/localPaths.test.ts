import { describe, expect, it } from 'vitest';
import {
  extractPathFromToolResult,
  isAgentsLogicalPath,
  isAbsoluteLocalPath,
  resolveLocalPathCandidate,
  resolveToolCallLocalPath,
} from '../../lib/localPaths';

describe('local path helpers', () => {
  it('recognizes Windows absolute paths', () => {
    expect(isAbsoluteLocalPath('C:\\Users\\Harrys\\file.md')).toBe(true);
    expect(resolveLocalPathCandidate('C:\\Users\\Harrys\\file.md')).toBe('C:\\Users\\Harrys\\file.md');
  });

  it('recognizes AGENTS logical paths without resolving them in the renderer', () => {
    expect(isAgentsLogicalPath('AGENTS/personal/memory.md')).toBe(true);
    expect(resolveLocalPathCandidate('AGENTS/personal/memory.md')).toBe('AGENTS/personal/memory.md');
  });

  it('does not treat ordinary inline code as a local path', () => {
    expect(resolveLocalPathCandidate('memory_persistence_audit')).toBeNull();
    expect(resolveLocalPathCandidate('npm run build')).toBeNull();
    expect(resolveLocalPathCandidate('https://example.com/a.md')).toBeNull();
  });

  it('resolves likely relative paths against the project root when allowed', () => {
    expect(resolveLocalPathCandidate('src/App.tsx', {
      projectPath: 'C:\\repo\\desktop-agent',
      allowProjectRelative: true,
    })).toBe('C:\\repo\\desktop-agent\\src\\App.tsx');
  });

  it('extracts tool result paths before falling back to args', () => {
    expect(extractPathFromToolResult('Patched: C:\\repo\\src\\App.tsx (matched via exact)')).toBe('C:\\repo\\src\\App.tsx');
    expect(resolveToolCallLocalPath(
      'file_write',
      { path: 'AGENTS/personal/a.md' },
      'File written: C:\\runtime\\backend\\AGENTS\\personal\\WORKSPACE\\a.md',
    )).toBe('C:\\runtime\\backend\\AGENTS\\personal\\WORKSPACE\\a.md');
  });
});
