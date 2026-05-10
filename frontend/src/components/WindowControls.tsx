import React from 'react';
import { Terminal, PanelRightOpen, PanelRightClose, LayoutGrid } from 'lucide-react';
import { cn } from './ui/cn';
import { Tooltip } from './ui/Tooltip';

interface WindowControlsProps {
  showTerminal: boolean;
  rightPanelVisible: boolean;
  onToggleTerminal: () => void;
  onToggleRightPanel: () => void;
  onResetLayout: () => void;
}

export const WindowControls: React.FC<WindowControlsProps> = ({
  showTerminal,
  rightPanelVisible,
  onToggleTerminal,
  onToggleRightPanel,
  onResetLayout,
}) => {
  return (
    <div className="flex items-center gap-0.5">
      <Tooltip content={<span className="text-[11px]">Toggle Terminal (Ctrl+J)</span>}>
        <button
          type="button"
          onClick={onToggleTerminal}
          className={cn(
            'w-7 h-7 rounded flex items-center justify-center transition-colors',
            showTerminal
              ? 'text-fg bg-surface-hover'
              : 'text-fg-muted hover:text-fg-secondary'
          )}
          aria-label="Toggle Terminal"
        >
          <Terminal className="w-3.5 h-3.5" />
        </button>
      </Tooltip>

      <Tooltip content={<span className="text-[11px]">Toggle Right Panel (Ctrl+\)</span>}>
        <button
          type="button"
          onClick={onToggleRightPanel}
          className={cn(
            'w-7 h-7 rounded flex items-center justify-center transition-colors',
            rightPanelVisible
              ? 'text-fg bg-surface-hover'
              : 'text-fg-muted hover:text-fg-secondary'
          )}
          aria-label="Toggle Right Panel"
        >
          {rightPanelVisible ? (
            <PanelRightClose className="w-3.5 h-3.5" />
          ) : (
            <PanelRightOpen className="w-3.5 h-3.5" />
          )}
        </button>
      </Tooltip>

      <Tooltip content={<span className="text-[11px]">Reset Layout</span>}>
        <button
          type="button"
          onClick={onResetLayout}
          className="w-7 h-7 rounded flex items-center justify-center text-fg-secondary hover:text-fg hover:bg-surface-hover transition-colors"
          aria-label="Reset Layout"
        >
          <LayoutGrid className="w-3.5 h-3.5" />
        </button>
      </Tooltip>
    </div>
  );
};
