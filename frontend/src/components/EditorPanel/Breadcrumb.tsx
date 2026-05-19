import React from 'react';

interface BreadcrumbProps {
  projectName: string;
  filePath: string;
}

export const Breadcrumb: React.FC<BreadcrumbProps> = ({ projectName, filePath }) => {
  if (!filePath) {
    return (
      <div className="h-7 bg-surface border-b border-border flex items-center px-3 text-[11px] text-fg-muted">
        <span>{projectName}</span>
      </div>
    );
  }

  const parts = filePath.split('/');

  return (
    <div className="h-7 bg-surface border-b border-border flex items-center px-3 text-[11px] text-fg-secondary overflow-hidden">
      <span className="text-fg-secondary font-medium shrink-0">{projectName}</span>
      {parts.map((part, idx) => (
        <React.Fragment key={idx}>
          <span className="mx-1.5 text-fg-muted shrink-0">/</span>
          <span
            className={`shrink-0 ${idx === parts.length - 1 ? 'text-fg font-medium' : ''}`}
            title={part}
          >
            {part}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
};
