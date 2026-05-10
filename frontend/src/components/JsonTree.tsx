import React, { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';

interface JsonTreeProps {
  data: any;
  level?: number;
}

const PRIMITIVE_COLORS: Record<string, string> = {
  string: 'text-green-400',
  number: 'text-yellow-400',
  boolean: 'text-purple-400',
  null: 'text-gray-500',
  undefined: 'text-gray-500',
};

function getType(value: any): string {
  if (value === null) return 'null';
  if (value === undefined) return 'undefined';
  return typeof value;
}

function PrimitiveView({ value }: { value: any }) {
  const type = getType(value);
  const color = PRIMITIVE_COLORS[type] || 'text-gray-300';
  let display = String(value);
  if (type === 'string') display = `"${display}"`;
  if (type === 'null' || type === 'undefined') display = String(value);
  return <span className={color}>{display}</span>;
}

export const JsonTree: React.FC<JsonTreeProps> = ({ data, level = 0 }) => {
  const type = getType(data);
  const isObject = type === 'object' && data !== null;
  const isArray = Array.isArray(data);
  const keys = isObject ? Object.keys(data) : [];
  const [expanded, setExpanded] = useState(level < 2);

  if (!isObject) {
    return <PrimitiveView value={data} />;
  }

  const isEmpty = keys.length === 0;
  const openBrace = isArray ? '[' : '{';
  const closeBrace = isArray ? ']' : '}';

  return (
    <span className="text-gray-300">
      {isEmpty ? (
        <span className="text-gray-500">
          {openBrace}
          {closeBrace}
        </span>
      ) : (
        <>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center hover:text-white transition-colors"
            aria-label={expanded ? '折叠' : '展开'}
          >
            {expanded ? (
              <ChevronDown className="w-3 h-3 mr-0.5 text-gray-500" />
            ) : (
              <ChevronRight className="w-3 h-3 mr-0.5 text-gray-500" />
            )}
            <span className="text-gray-500">{openBrace}</span>
            {!expanded && (
              <span className="text-gray-500 ml-1">...{closeBrace}</span>
            )}
          </button>
          {expanded && (
            <div className="pl-3 border-l border-gray-700/50 ml-1">
              {keys.map((key, i) => (
                <div key={key} className="my-0.5">
                  {!isArray && (
                    <span className="text-blue-400 mr-1.5">{key}:</span>
                  )}
                  <JsonTree data={data[key]} level={level + 1} />
                  {i < keys.length - 1 && <span className="text-gray-600">,</span>}
                </div>
              ))}
              <span className="text-gray-500">{closeBrace}</span>
            </div>
          )}
        </>
      )}
    </span>
  );
};
