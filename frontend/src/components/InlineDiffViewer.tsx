import React, { useEffect, useRef, useState } from "react";
import { DiffEditor } from "@monaco-editor/react";
import { FileEdit } from "../types";
import { getLangFromFilename } from "../lib/language";
import { ensureMonacoThemes, getMonacoThemeName } from "../lib/monacoTheme";
import { useTheme } from "../hooks/useTheme";
import { UnifiedDiffFallback } from "./UnifiedDiffFallback";

interface InlineDiffViewerProps {
  edit: FileEdit;
}

const MONACO_OPTIONS = {
  readOnly: true,
  renderSideBySide: false,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  automaticLayout: true,
  fontSize: 12,
  wordWrap: "on" as const,
  lineNumbers: "on" as const,
};

export const InlineDiffViewer: React.FC<InlineDiffViewerProps> = ({ edit }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isClipped, setIsClipped] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const { resolved } = useTheme();
  const monacoTheme = getMonacoThemeName(resolved);

  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    if (el.scrollHeight > 242) {
      setIsClipped(true);
    } else {
      setIsClipped(false);
    }
  }, [edit]);

  const showMonaco =
    edit.old_text != null && edit.new_text != null && !edit.truncated;

  const language = getLangFromFilename(edit.path, "monaco");

  return (
    <div className="relative">
      <div
        ref={containerRef}
        className="overflow-hidden"
        style={{
          maxHeight: expanded ? undefined : "240px",
          backgroundColor: "var(--bg-app)",
        }}
      >
        {showMonaco ? (
          <DiffEditor
            original={edit.old_text!}
            modified={edit.new_text!}
            language={language}
            theme={monacoTheme}
            beforeMount={ensureMonacoThemes}
            options={MONACO_OPTIONS}
            height={expanded ? "auto" : "240px"}
          />
        ) : (
          <UnifiedDiffFallback diff={edit.unified_diff || "(no diff available)"} />
        )}
      </div>

      {isClipped && !expanded && (
        <>
          <div
            className="absolute bottom-0 left-0 right-0 h-12 pointer-events-none"
            style={{
              background: "linear-gradient(to bottom, transparent, var(--bg-app))",
            }}
          />
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="absolute bottom-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded text-xs font-medium bg-surface text-fg border border-border hover:bg-surface-hover"
          >
            Click to expand
          </button>
        </>
      )}

      {expanded && isClipped && (
        <div className="flex justify-center pt-2 pb-1 bg-app">
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="px-3 py-1 rounded text-xs font-medium bg-surface text-fg border border-border hover:bg-surface-hover"
          >
            Show less
          </button>
        </div>
      )}
    </div>
  );
};
