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

interface FileEditViewProps {
  edit: FileEdit;
  compact?: boolean;
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
}) => {
  const [expanded, setExpanded] = useState(!compact);

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

  return (
    <div className="my-2 rounded-lg border border-border bg-surface/50 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-surface-hover transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-fg-muted shrink-0 mt-0.5" />
        ) : (
          <ChevronRight className="w-4 h-4 text-fg-muted shrink-0 mt-0.5" />
        )}
        <div className={`w-2 h-2 rounded-full shrink-0 mt-1.5 ${config.dot}`} />
        <Icon className="w-4 h-4 text-fg-muted shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="text-sm truncate">
            <span className="font-medium text-fg">{config.label}</span>{" "}
            <span className="text-fg-secondary">{basename(edit.path)}</span>
          </div>
          <div className="text-xs text-fg-muted truncate">
            {statsText} • {dirname(edit.path)}
          </div>
        </div>
      </button>
      {expanded && (
        <div className="border-t border-border">
          <InlineDiffViewer edit={edit} />
        </div>
      )}
    </div>
  );
};
