import React, { useMemo } from 'react';

interface DataTableProps {
  content: string;
}

function parseCSV(text: string): string[][] {
  const lines = text.trim().split('\n');
  return lines.map((line) => {
    const result: string[] = [];
    let current = '';
    let inQuotes = false;
    for (const ch of line) {
      if (ch === '"') {
        inQuotes = !inQuotes;
      } else if (ch === ',' && !inQuotes) {
        result.push(current.trim());
        current = '';
      } else {
        current += ch;
      }
    }
    result.push(current.trim());
    return result;
  });
}

export const DataTable: React.FC<DataTableProps> = ({ content }) => {
  const rows = useMemo(() => parseCSV(content), [content]);
  if (rows.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-fg-muted text-sm">
        无数据
      </div>
    );
  }

  const headers = rows[0];
  const dataRows = rows.slice(1);

  return (
    <div className="h-full overflow-auto bg-app">
      <table className="w-full text-xs border-collapse">
        <thead className="sticky top-0 bg-surface">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="text-left px-3 py-2 text-fg-secondary font-medium border-b border-border whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dataRows.map((row, ri) => (
            <tr key={ri} className="border-b border-border hover:bg-app/50">
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-1.5 text-fg-secondary whitespace-nowrap">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
