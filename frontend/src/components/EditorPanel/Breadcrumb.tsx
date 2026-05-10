import React from 'react';

interface BreadcrumbProps {
  projectName: string;
  filePath: string;
}

export const Breadcrumb: React.FC<BreadcrumbProps> = ({ projectName, filePath }) => {
  if (!filePath) {
    return (
      <div className="h-7 bg-gray-800 border-b border-gray-700 flex items-center px-3 text-[11px] text-gray-500">
        <span>{projectName}</span>
      </div>
    );
  }

  const parts = filePath.split('/');

  return (
    <div className="h-7 bg-gray-800 border-b border-gray-700 flex items-center px-3 text-[11px] text-gray-400 overflow-hidden">
      <span className="text-gray-300 font-medium shrink-0">{projectName}</span>
      {parts.map((part, idx) => (
        <React.Fragment key={idx}>
          <span className="mx-1.5 text-gray-600 shrink-0">/</span>
          <span
            className={`shrink-0 ${idx === parts.length - 1 ? 'text-gray-200 font-medium' : ''}`}
            title={part}
          >
            {part}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
};
