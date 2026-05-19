# Inline Diff in Chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move code diff visualization from the right-side ChangesPanel into the chat message stream, styled like Claude Code in VS Code, with collapsible "Click to expand" support.

**Architecture:** Replace the plain-text `<pre>` diff in `FileEditView` with a height-limited Monaco `DiffEditor` (for non-truncated edits with `old_text`/`new_text`) and a lightweight colorized unified-diff fallback (for truncated edits). Remove the auto-popup behavior of the right-side Changes panel so edits live inline in the chat flow. Keep the ChangesPanel as a manual browsing view.

**Tech Stack:** React 18, TypeScript, TailwindCSS, `@monaco-editor/react`, existing `FileEdit` type

---

## File Map

| File | Responsibility |
|------|---------------|
| `src/components/InlineDiffViewer.tsx` | **New.** Renders a Monaco DiffEditor with a max-height wrapper + "Click to expand" overlay. Falls back to a colorized unified-diff `<pre>` when `old_text`/`new_text` are unavailable. |
| `src/components/FileEditView.tsx` | **Rewrite.** Chat-inline file-edit card. Header (file path, stats, expand chevron) + body (lazy-mount `InlineDiffViewer` when expanded). |
| `src/App.tsx` | **Modify.** Remove `layout.setRightTab('changes')` and `layout.setRightPanelVisible(true)` from `onFileEditRef` so edits no longer hijack the right panel. |
| `src/components/ChangesPanel.tsx` | **Modify (optional styling).** Keep as-is functionally; add a subtle hint that diffs are now inline in chat. |
| `src/__tests__/components/FileEditView.test.tsx` | **New.** Tests for expand/collapse, truncated fallback, and header rendering. |

---

## Task 1: Create `InlineDiffViewer` Component

**Files:**
- Create: `src/components/InlineDiffViewer.tsx`
- Create: `src/components/UnifiedDiffFallback.tsx` (lightweight colorized unified diff)

**Design Notes:**
- When `old_text != null && new_text != null && !truncated` → render Monaco `DiffEditor`.
- Otherwise → render `UnifiedDiffFallback` parsing `unified_diff` string.
- Default visible height: `240px`. If content is taller, show a bottom gradient overlay + "Click to expand" button.
- Expanded state removes the height cap and hides the overlay.
- Monaco options: `readOnly: true`, `renderSideBySide: false` (inline diff saves horizontal space in chat), `minimap: { enabled: false }`, `scrollBeyondLastLine: false`, `automaticLayout: true`, `fontSize: 12`, `wordWrap: 'on'`.
- Theme: `vs-dark` to match the dark app theme.
- Language detection: reuse `getLangFromFilename` from `src/lib/language`.

**Important:** Monaco DiffEditor can be heavy. Only mount it when the parent `FileEditView` is expanded (lazy render). For the initial collapsed state, do not render Monaco at all.

- [ ] **Step 1: Write `UnifiedDiffFallback.tsx`**

```tsx
import React from 'react';

interface Props {
  diff: string;
}

export const UnifiedDiffFallback: React.FC<Props> = ({ diff }) => {
  const lines = diff.split('\n');
  return (
    <pre
      className="font-mono text-xs leading-5 overflow-auto"
      style={{ background: '#1e1e1e' }}
    >
      {lines.map((line, i) => {
        let bg = 'transparent';
        let color = '#d4d4d4';
        if (line.startsWith('+') && !line.startsWith('+++')) {
          bg = '#2d4a3e';
          color = '#7ee787';
        } else if (line.startsWith('-') && !line.startsWith('---')) {
          bg = '#4a2d2d';
          color = '#ffa198';
        } else if (line.startsWith('@@')) {
          color = '#79c0ff';
        }
        return (
          <div key={i} style={{ backgroundColor: bg, color, padding: '0 8px' }}>
            <span className="select-none opacity-40 mr-2">{i + 1}</span>
            {line}
          </div>
        );
      })}
    </pre>
  );
};
```

- [ ] **Step 2: Write `InlineDiffViewer.tsx`**

```tsx
import React, { useState, useRef, useEffect } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { FileEdit } from '../types';
import { getLangFromFilename } from '../lib/language';
import { UnifiedDiffFallback } from './UnifiedDiffFallback';

const DEFAULT_HEIGHT = 240;

interface Props {
  edit: FileEdit;
}

export const InlineDiffViewer: React.FC<Props> = ({ edit }) => {
  const [expanded, setExpanded] = useState(false);
  const [needsExpand, setNeedsExpand] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!expanded && containerRef.current) {
      const el = containerRef.current;
      setNeedsExpand(el.scrollHeight > DEFAULT_HEIGHT + 2);
    }
  }, [expanded]);

  const hasFullText = edit.old_text != null && edit.new_text != null && !edit.truncated;

  return (
    <div className="relative">
      <div
        ref={containerRef}
        className="overflow-hidden"
        style={{ maxHeight: expanded ? undefined : DEFAULT_HEIGHT }}
      >
        {hasFullText ? (
          <DiffEditor
            height={expanded ? '100%' : `${DEFAULT_HEIGHT}px`}
            language={getLangFromFilename(edit.path, 'monaco')}
            original={edit.old_text}
            modified={edit.new_text}
            theme="vs-dark"
            options={{
              readOnly: true,
              renderSideBySide: false,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              automaticLayout: true,
              fontSize: 12,
              wordWrap: 'on',
              lineNumbers: 'on',
            }}
          />
        ) : (
          <UnifiedDiffFallback diff={edit.unified_diff || '(no diff available)'} />
        )}
      </div>

      {!expanded && needsExpand && (
        <div className="absolute bottom-0 left-0 right-0 h-16 flex items-end justify-center bg-gradient-to-t from-[#1e1e1e] to-transparent">
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="mb-2 px-3 py-1 text-xs rounded bg-surface-hover hover:bg-surface text-fg-secondary border border-border transition-colors"
          >
            Click to expand
          </button>
        </div>
      )}

      {expanded && needsExpand && (
        <div className="flex justify-center py-2">
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="px-3 py-1 text-xs rounded bg-surface-hover hover:bg-surface text-fg-secondary border border-border transition-colors"
          >
            Show less
          </button>
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 3: Verify types compile**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors from the new files.

---

## Task 2: Rewrite `FileEditView.tsx`

**Files:**
- Modify: `src/components/FileEditView.tsx`

**Design Notes:**
- Keep the collapsible header pattern but improve styling to match Claude Code aesthetic.
- Use a green dot for "Edit" actions, red dot for "Delete", blue dot for "Create".
- Show `Added X lines` / `Modified` / `Deleted` in the header subtitle (from `stats`).
- Only render `InlineDiffViewer` when `expanded === true` (lazy mount).
- Keep `compact` prop: when `compact=true` (used in chat), start collapsed. When `compact=false` (used in ChangesPanel fallback), start expanded.

- [ ] **Step 1: Replace `FileEditView.tsx` content**

```tsx
import React, { useState } from 'react';
import { ChevronDown, ChevronRight, FilePlus, FileMinus, FilePenLine } from 'lucide-react';
import { FileEdit } from '../types';
import { InlineDiffViewer } from './InlineDiffViewer';

interface FileEditViewProps {
  edit: FileEdit;
  compact?: boolean;
}

function basename(path: string): string {
  return path.replace(/\\/g, '/').split('/').pop() || path;
}

function dirname(path: string): string {
  const normalized = path.replace(/\\/g, '/');
  const parts = normalized.split('/');
  parts.pop();
  return parts.join('/') || '.';
}

export const FileEditView: React.FC<FileEditViewProps> = ({ edit, compact = false }) => {
  const [expanded, setExpanded] = useState(!compact);
  const added = edit.stats?.added || 0;
  const removed = edit.stats?.removed || 0;

  const operationConfig = {
    create: { icon: FilePlus, dotColor: 'bg-blue-400', label: 'Created' },
    modify: { icon: FilePenLine, dotColor: 'bg-green-400', label: 'Edit' },
    delete: { icon: FileMinus, dotColor: 'bg-red-400', label: 'Deleted' },
  };
  const op = operationConfig[(edit.operation as keyof typeof operationConfig) || 'modify'];
  const Icon = op.icon;

  const lineSummary = [];
  if (added) lineSummary.push(`Added ${added} lines`);
  if (removed) lineSummary.push(`Removed ${removed} lines`);
  if (!added && !removed) lineSummary.push('Modified');

  return (
    <div className="my-2 rounded-lg border border-border bg-surface/50 overflow-hidden">
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-surface-hover transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-fg-muted mt-1 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-fg-muted mt-1 shrink-0" />
        )}

        <div className="flex items-center gap-2 mt-0.5 shrink-0">
          <div className={`w-2 h-2 rounded-full ${op.dotColor}`} />
          <Icon className="w-3.5 h-3.5 text-fg-secondary" />
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-sm text-fg font-medium truncate">
            {op.label} <span className="text-fg-secondary font-normal">{basename(edit.path)}</span>
          </div>
          <div className="text-xs text-fg-muted truncate mt-0.5">
            {lineSummary.join(', ')} • {dirname(edit.path)}
          </div>
        </div>
      </button>

      {/* Body */}
      {expanded && (
        <div className="border-t border-border">
          <InlineDiffViewer edit={edit} />
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 2: Verify `ChatPanel.tsx` import still works**

`ChatPanel.tsx` imports `FileEditView` and passes `compact` prop. The new component accepts the same props, so no change is needed in `ChatPanel.tsx`.

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 3: Remove Auto-Popup of Right Changes Panel

**Files:**
- Modify: `src/App.tsx` (around lines 572–611)

**Design Notes:**
- Remove the two lines that force the right panel to open on every file edit.
- Keep the editor auto-update logic (open files that match the edited path should reflect changes/conflicts).
- Keep the truncated log message.

- [ ] **Step 1: Edit `onFileEditRef` in `App.tsx`**

Find this block inside `useEffect`:

```ts
layout.setRightTab('changes');
layout.setRightPanelVisible(true);
```

Replace with nothing (delete both lines). The remaining logic in that callback stays exactly the same.

The callback should now look like:

```ts
onFileEditRef.current = (edit: FileEdit) => {
  const editPath = normalizePath(edit.path);
  const projectRoot = currentProject ? normalizePath(currentProject.path) : '';
  const relativePath = projectRoot && editPath.startsWith(projectRoot + '/')
    ? edit.path.replace(/\\/g, '/').slice(currentProject!.path.replace(/\\/g, '/').length + 1)
    : edit.path.replace(/\\/g, '/');

  setEditorGroups((prev) =>
    prev.map((g) => ({
      ...g,
      openFiles: g.openFiles.map((f) => {
        const filePath = normalizePath(f.path);
        const matches = filePath === normalizePath(relativePath) || editPath.endsWith('/' + filePath);
        if (!matches) return f;

        const hasLocalConflict = !!f.isModified && edit.old_text != null && f.content !== edit.old_text;
        if (hasLocalConflict) {
          return { ...f, hasConflict: true, isModified: true };
        }
        return {
          ...f,
          content: edit.new_text ?? f.content,
          isModified: false,
          hasConflict: false,
        };
      }),
    }))
  );

  if (edit.truncated) {
    addTerminalLog(`[Edit] ${edit.path} changed; full text was too large for inline diff`);
  }
};
```

- [ ] **Step 2: Verify no TypeScript errors**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 4: Optional — Update `ChangesPanel` Header Hint

**Files:**
- Modify: `src/components/ChangesPanel.tsx`

**Design Notes:**
- Since diffs now appear inline in chat, the ChangesPanel is a secondary "all edits" browser. Add a small hint at the top so users know why it no longer auto-opens.

- [ ] **Step 1: Add a subtle hint to `ChangesPanel`**

Inside the `edits.length > 0` branch, above the flex container, add:

```tsx
<div className="px-3 py-1.5 text-[11px] text-fg-muted border-b border-border bg-surface/30">
  Diffs are shown inline in chat. This panel lists all edits in the session.
</div>
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

## Task 5: Add Frontend Tests

**Files:**
- Create: `src/__tests__/components/FileEditView.test.tsx`

**Design Notes:**
- Mock `@monaco-editor/react` because Monaco cannot run in jsdom.
- Test header rendering (operation label, file name, stats).
- Test expand/collapse toggle.
- Test truncated fallback (unified diff fallback path).

- [ ] **Step 1: Write test file**

```tsx
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { FileEditView } from '../../components/FileEditView';
import { FileEdit } from '../../types';

// Mock Monaco DiffEditor
jest.mock('@monaco-editor/react', () => ({
  DiffEditor: ({ original, modified }: any) => (
    <div data-testid="monaco-diff">{original} → {modified}</div>
  ),
}));

const baseEdit: FileEdit = {
  path: 'src/App.tsx',
  operation: 'modify',
  old_text: 'const a = 1;',
  new_text: 'const a = 2;',
  unified_diff: '-const a = 1;\n+const a = 2;',
  stats: { added: 1, removed: 1 },
  truncated: false,
};

describe('FileEditView', () => {
  it('renders header with file name and stats', () => {
    render(<FileEditView edit={baseEdit} compact={false} />);
    expect(screen.getByText(/Edit/i)).toBeInTheDocument();
    expect(screen.getByText(/App.tsx/)).toBeInTheDocument();
    expect(screen.getByText(/Added 1 lines/)).toBeInTheDocument();
  });

  it('starts collapsed in compact mode and expands on click', () => {
    render(<FileEditView edit={baseEdit} compact />);
    expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByTestId('monaco-diff')).toBeInTheDocument();
  });

  it('shows unified diff fallback when truncated', () => {
    const truncated: FileEdit = { ...baseEdit, truncated: true, old_text: undefined, new_text: undefined };
    render(<FileEditView edit={truncated} compact={false} />);
    expect(screen.getByText('+const a = 2;')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests**

Run: `cd frontend && npx vitest run src/__tests__/components/FileEditView.test.tsx`
Expected: All tests pass.

---

## Task 6: Build & Smoke Test

- [ ] **Step 1: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: Zero errors.

- [ ] **Step 2: Build**

Run: `cd frontend && npm run build`
Expected: Build completes successfully.

- [ ] **Step 3: Start backend and frontend**

Run: `.\start-all.ps1` (or manually start backend + `npm run dev`)
Expected: App loads.

- [ ] **Step 4: Manual smoke test**

1. Send a message that causes a file write (e.g., "create a hello.py file").
2. Observe the chat bubble: a file-edit card appears inline.
3. Card should show header with green dot, filename, and stats.
4. Click the header to expand: Monaco inline diff should render.
5. If the diff is tall, verify "Click to expand" appears and works.
6. Verify the right panel does **not** auto-open.
7. Open the right panel manually → Changes tab should still list all edits.

---

## Self-Review

**1. Spec coverage:**
- ✅ Inline diff in chat message stream — `FileEditView` rewrite + `InlineDiffViewer`.
- ✅ Claude Code style header — green dot, filename, operation label, line stats.
- ✅ "Click to expand" — `InlineDiffViewer` height cap + overlay button.
- ✅ No right-panel popup — removed from `App.tsx` `onFileEditRef`.
- ✅ Side-by-side or inline diff — uses Monaco `renderSideBySide: false` (inline) to fit narrow chat width; this matches the screenshot aesthetic where diffs are shown inline with red/green backgrounds.
- ✅ Fallback for truncated/large files — `UnifiedDiffFallback` colorizes `unified_diff`.

**2. Placeholder scan:**
- No TBD/TODO/fill-in-later found.
- All code blocks contain complete, copy-pasteable code.

**3. Type consistency:**
- `FileEdit` type is unchanged; all props (`old_text`, `new_text`, `unified_diff`, `stats`, `truncated`, `path`, `operation`) match existing `src/types.ts`.
- `compact` prop behavior preserved (`compact=true` starts collapsed).
- `getLangFromFilename` signature unchanged.
