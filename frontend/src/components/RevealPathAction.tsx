import React from 'react';
import { FolderOpen } from 'lucide-react';
import {
  canRevealLocalPaths,
  resolveLocalPathCandidate,
  revealLocalPath,
  type LocalPathResolveOptions,
} from '../lib/localPaths';

function logRevealError(path: string, error: string | null) {
  if (error) console.warn(`[Path] Reveal failed for ${path}: ${error}`);
}

interface RevealPathButtonProps extends LocalPathResolveOptions {
  path?: string | null;
  className?: string;
  iconClassName?: string;
  title?: string;
  ariaLabel?: string;
}

export const RevealPathButton: React.FC<RevealPathButtonProps> = ({
  path,
  projectPath,
  allowProjectRelative = true,
  className = '',
  iconClassName = 'h-3.5 w-3.5',
  title,
  ariaLabel,
}) => {
  const targetPath = resolveLocalPathCandidate(path, { projectPath, allowProjectRelative });
  if (!targetPath || !canRevealLocalPaths()) return null;

  return (
    <button
      type="button"
      aria-label={ariaLabel || `Show in folder: ${targetPath}`}
      title={title || `Show in folder: ${targetPath}`}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        void revealLocalPath(targetPath).then((error) => logRevealError(targetPath, error));
      }}
      className={`inline-flex shrink-0 items-center justify-center rounded text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg-secondary focus:outline-none focus:ring-2 focus:ring-accent/50 ${className}`}
    >
      <FolderOpen className={iconClassName} />
    </button>
  );
};

interface RevealableInlineCodeProps extends LocalPathResolveOptions {
  value: string;
  className?: string;
  children?: React.ReactNode;
}

export const RevealableInlineCode: React.FC<RevealableInlineCodeProps> = ({
  value,
  projectPath,
  allowProjectRelative = true,
  className = '',
  children,
}) => {
  const targetPath = resolveLocalPathCandidate(value, { projectPath, allowProjectRelative });
  const content = children ?? value;

  if (!targetPath || !canRevealLocalPaths()) {
    return <code className={className}>{content}</code>;
  }

  return (
    <button
      type="button"
      aria-label={`Show in folder: ${targetPath}`}
      title={`Show in folder: ${targetPath}`}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        void revealLocalPath(targetPath).then((error) => logRevealError(targetPath, error));
      }}
      className={`${className} inline-flex max-w-full items-center gap-1 align-baseline font-mono hover:text-fg focus:outline-none focus:ring-2 focus:ring-accent/50`}
    >
      <span className="truncate">{content}</span>
      <FolderOpen className="h-3 w-3 shrink-0 opacity-70" />
    </button>
  );
};
