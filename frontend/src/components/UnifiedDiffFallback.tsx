import React from "react";

interface UnifiedDiffFallbackProps {
  diff: string;
}

export const UnifiedDiffFallback: React.FC<UnifiedDiffFallbackProps> = ({ diff }) => {
  const lines = diff.split("\n");

  const getLineStyle = (line: string): React.CSSProperties => {
    if (line.startsWith("+++") || line.startsWith("---")) {
      return { color: "var(--text-primary)", backgroundColor: "transparent" };
    }
    if (line.startsWith("+")) {
      return { color: "rgb(var(--success-rgb))", backgroundColor: "rgb(var(--success-rgb) / 0.12)" };
    }
    if (line.startsWith("-")) {
      return { color: "rgb(var(--danger-rgb))", backgroundColor: "rgb(var(--danger-rgb) / 0.12)" };
    }
    if (line.startsWith("@@")) {
      return { color: "var(--text-link)", backgroundColor: "transparent" };
    }
    return { color: "var(--text-primary)", backgroundColor: "transparent" };
  };

  return (
    <div className="overflow-auto bg-app">
      <div className="font-mono text-xs leading-5">
        {lines.map((line, idx) => (
          <div key={idx} className="flex">
            <span
              className="select-none text-right shrink-0 pl-2 pr-3"
              style={{ color: "var(--text-muted)", minWidth: "2.5rem" }}
            >
              {idx + 1}
            </span>
            <pre
              className="flex-1 pr-2 whitespace-pre"
              style={getLineStyle(line)}
            >
              {line}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
};
