import React from "react";

interface UnifiedDiffFallbackProps {
  diff: string;
}

export const UnifiedDiffFallback: React.FC<UnifiedDiffFallbackProps> = ({ diff }) => {
  const lines = diff.split("\n");

  const getLineStyle = (line: string): React.CSSProperties => {
    if (line.startsWith("+++") || line.startsWith("---")) {
      return { color: "#d4d4d4", backgroundColor: "transparent" };
    }
    if (line.startsWith("+")) {
      return { color: "#7ee787", backgroundColor: "#2d4a3e" };
    }
    if (line.startsWith("-")) {
      return { color: "#ffa198", backgroundColor: "#4a2d2d" };
    }
    if (line.startsWith("@@")) {
      return { color: "#79c0ff", backgroundColor: "transparent" };
    }
    return { color: "#d4d4d4", backgroundColor: "transparent" };
  };

  return (
    <div className="overflow-auto" style={{ backgroundColor: "#1e1e1e" }}>
      <div className="font-mono text-xs leading-5">
        {lines.map((line, idx) => (
          <div key={idx} className="flex">
            <span
              className="select-none text-right shrink-0 pl-2 pr-3"
              style={{ color: "#6e7681", minWidth: "2.5rem" }}
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
