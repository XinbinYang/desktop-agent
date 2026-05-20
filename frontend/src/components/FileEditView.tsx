import React, { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FilePlus,
  FilePenLine,
  FileMinus,
} from "lucide-react";
import { FileEdit } from "../types";
import { InlineDiffViewer } from "./InlineDiffViewer";
import { UnifiedDiffFallback } from "./UnifiedDiffFallback";
import { RevealPathButton } from "./RevealPathAction";

interface FileEditViewProps {
  edit: FileEdit;
  compact?: boolean;
  variant?: "full" | "event-row";
  projectPath?: string | null;
}

function basename(path: string): string {
  return path.replace(/\\/g, "/").split("/").pop() || path;
}

function dirname(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/");
  parts.pop();
  return parts.join("/") || ".";
}

const OPERATION_CONFIG: Record<
  string,
  { label: string; dot: string; icon: React.ElementType }
> = {
  create: { label: "Create", dot: "bg-blue-400", icon: FilePlus },
  modify: { label: "Edit", dot: "bg-green-400", icon: FilePenLine },
  delete: { label: "Delete", dot: "bg-red-400", icon: FileMinus },
};

export const FileEditView: React.FC<FileEditViewProps> = ({
  edit,
  compact = false,
  variant = "full",
  projectPath,
}) => {
  const [expanded, setExpanded] = useState(variant === "event-row" ? false : !compact);

  const added = edit.stats?.added ?? 0;
  const removed = edit.stats?.removed ?? 0;

  const config = OPERATION_CONFIG[edit.operation] || {
    label:
      edit.operation.charAt(0).toUpperCase() + edit.operation.slice(1),
    dot: "bg-gray-400",
    icon: FilePenLine,
  };

  const statsParts: string[] = [];
  if (added > 0) statsParts.push(`Added ${added} lines`);
  if (removed > 0) statsParts.push(`Removed ${removed} lines`);
  const statsText = statsParts.length > 0 ? statsParts.join(", ") : "Modified";

  const Icon = config.icon;
  const isEventRow = variant === "event-row";

  return (
    <div
      className={`${isEventRow ? "my-[var(--chat-space-xs)] rounded-md border-border-subtle bg-surface/45" : "my-2 rounded-lg border-border bg-surface/50"} border overflow-hidden`}
      data-testid={isEventRow ? "file-edit-event-row" : undefined}
    >
      <div className="w-full flex min-w-0 items-start hover:bg-surface-hover transition-colors">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={`flex min-w-0 flex-1 items-start gap-2 text-left ${isEventRow ? "px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)]" : "px-3 py-2"}`}
      >
        {expanded ? (
          <ChevronDown className={`${isEventRow ? "w-3.5 h-3.5" : "w-4 h-4"} text-fg-muted shrink-0 mt-0.5`} />
        ) : (
          <ChevronRight className={`${isEventRow ? "w-3.5 h-3.5" : "w-4 h-4"} text-fg-muted shrink-0 mt-0.5`} />
        )}
        <div className={`w-2 h-2 rounded-full shrink-0 mt-1.5 ${config.dot}`} />
        <Icon className={`${isEventRow ? "w-3.5 h-3.5" : "w-4 h-4"} text-fg-muted shrink-0 mt-0.5`} />
        <div className="flex-1 min-w-0">
          <div className={`${isEventRow ? "chat-text-xs" : "text-sm"} truncate`}>
            <span className="font-medium text-fg">{config.label}</span>{" "}
            <span className="text-fg-secondary">{basename(edit.path)}</span>
          </div>
          <div className={`${isEventRow ? "chat-text-xs" : "text-xs"} text-fg-muted truncate`}>
            {statsText} • {dirname(edit.path)}
          </div>
        </div>
        {isEventRow && (
          <span className="mt-0.5 shrink-0 chat-text-xs text-accent">
            View diff
          </span>
        )}
      </button>
        <RevealPathButton
          path={edit.path}
          projectPath={projectPath}
          className={isEventRow ? "mr-2 mt-1 h-6 w-6" : "mr-2 mt-2 h-7 w-7"}
        />
      </div>
      {expanded && (
        <div className="border-t border-border">
          {isEventRow ? (
            <div className="max-h-72 overflow-auto bg-app">
              <UnifiedDiffFallback diff={edit.unified_diff || "(no diff available)"} />
            </div>
          ) : (
            <InlineDiffViewer edit={edit} />
          )}
        </div>
      )}
    </div>
  );
};
