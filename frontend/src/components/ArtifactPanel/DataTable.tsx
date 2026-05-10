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
      <div className="h-full flex items-center justify-center text-gray-500 text-sm">
        无数据
      </div>
    );
  }

  const headers = rows[0];
  const dataRows = rows.slice(1);

  return (
    <div className="h-full overflow-auto bg-gray-950">
      <table className="w-full text-xs border-collapse">
        <thead className="sticky top-0 bg-gray-800">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="text-left px-3 py-2 text-gray-300 font-medium border-b border-gray-700 whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dataRows.map((row, ri) => (
            <tr key={ri} className="border-b border-gray-800 hover:bg-gray-900/50">
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-1.5 text-gray-400 whitespace-nowrap">
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
