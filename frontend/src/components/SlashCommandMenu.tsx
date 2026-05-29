import React, { useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from '../config';
import { Terminal, FolderOpen, HelpCircle, Camera, Zap } from 'lucide-react';

interface Command {
  name: string;
  description: string;
  args: string;
  category: string;
}

interface SlashCommandMenuProps {
  query: string;
  onSelect: (cmd: Command) => void;
  onClose: () => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  onVisibleCommandsChange?: (count: number) => void;
}

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  session: <Terminal className="w-3.5 h-3.5" />,
  general: <HelpCircle className="w-3.5 h-3.5" />,
  project: <FolderOpen className="w-3.5 h-3.5" />,
  tools: <Camera className="w-3.5 h-3.5" />,
  skills: <Zap className="w-3.5 h-3.5" />,
};

const CATEGORY_LABELS: Record<string, string> = {
  session: '会话',
  general: '通用',
  project: '项目',
  tools: '工具',
  skills: '技能',
};

let cachedCommands: Command[] | null = null;
let commandsRequest: Promise<Command[]> | null = null;

export function __resetSlashCommandCacheForTests() {
  cachedCommands = null;
  commandsRequest = null;
}

function loadCommands(): Promise<Command[]> {
  if (cachedCommands) return Promise.resolve(cachedCommands);
  if (!commandsRequest) {
    commandsRequest = fetch(`${API_BASE}/api/commands`)
      .then((r) => r.json())
      .then((data) => {
        cachedCommands = Array.isArray(data.commands) ? data.commands : [];
        return cachedCommands;
      })
      .catch(() => {
        cachedCommands = [];
        return cachedCommands;
      })
      .finally(() => {
        commandsRequest = null;
      });
  }
  return commandsRequest;
}

export const SlashCommandMenu: React.FC<SlashCommandMenuProps> = ({
  query,
  onSelect,
  onClose,
  inputRef,
  onVisibleCommandsChange,
}) => {
  const [commands, setCommands] = useState<Command[]>(() => cachedCommands || []);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    let cancelled = false;
    loadCommands().then((nextCommands) => {
      if (!cancelled) setCommands(nextCommands);
    });
    return () => { cancelled = true; };
  }, []);

  const queryText = query.replace('/', '').toLowerCase();
  const filtered = useMemo(
    () => commands.filter(
      (c) => c.name.toLowerCase().includes(queryText) ||
             c.description.toLowerCase().includes(queryText)
    ),
    [commands, queryText]
  );

  // Group by category
  const groupedEntries = useMemo(() => {
    const grouped: Record<string, Command[]> = {};
    for (const cmd of filtered) {
      const cat = cmd.category || 'other';
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(cmd);
    }
    return Object.entries(grouped);
  }, [filtered]);

  const visibleCommands = useMemo(
    () => groupedEntries.flatMap(([, cmds]) => cmds),
    [groupedEntries]
  );

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    setSelectedIndex((idx) => {
      if (visibleCommands.length === 0) return 0;
      return Math.min(idx, visibleCommands.length - 1);
    });
  }, [visibleCommands.length]);

  useEffect(() => {
    const menu = menuRef.current;
    const item = itemRefs.current[selectedIndex];
    if (!menu || !item) return;

    const menuTop = menu.scrollTop;
    const menuBottom = menuTop + menu.clientHeight;
    const itemTop = item.offsetTop;
    const itemBottom = itemTop + item.offsetHeight;

    if (itemTop < menuTop) {
      menu.scrollTop = itemTop;
    } else if (itemBottom > menuBottom) {
      menu.scrollTop = itemBottom - menu.clientHeight;
    }
  }, [selectedIndex]);

  useEffect(() => {
    onVisibleCommandsChange?.(visibleCommands.length);
    return () => onVisibleCommandsChange?.(0);
  }, [onVisibleCommandsChange, visibleCommands.length]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        setSelectedIndex((i) => {
          if (visibleCommands.length === 0) return 0;
          return Math.min(i + 1, visibleCommands.length - 1);
        });
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        setSelectedIndex((i) => {
          if (visibleCommands.length === 0) return 0;
          return Math.max(i - 1, 0);
        });
      } else if (e.key === 'Enter' && visibleCommands.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        onSelect(visibleCommands[Math.min(selectedIndex, visibleCommands.length - 1)]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    const el = inputRef.current;
    el?.addEventListener('keydown', handler);
    return () => el?.removeEventListener('keydown', handler);
  }, [visibleCommands, selectedIndex, onSelect, onClose, inputRef]);

  if (visibleCommands.length === 0) return null;

  const style: React.CSSProperties = {
    maxHeight: 'min(320px, calc(100vh - 160px))',
    minWidth: 'min(280px, 100%)',
    scrollbarGutter: 'stable',
    overscrollBehavior: 'contain',
  };

  return (
    <div
      ref={menuRef}
      style={style}
      className="absolute bottom-full left-0 right-0 z-50 mb-2 overflow-y-auto rounded-lg border border-border bg-surface p-1 shadow-xl"
    >
      {groupedEntries.map(([category, cmds]) => (
        <div key={category}>
          <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] text-fg-muted uppercase tracking-wide">
            {CATEGORY_ICONS[category]}
            {CATEGORY_LABELS[category] || category}
          </div>
          {cmds.map((cmd) => {
            const globalIdx = visibleCommands.indexOf(cmd);
            const isSelected = globalIdx === selectedIndex;
            return (
              <button
                key={cmd.name}
                ref={(node) => { itemRefs.current[globalIdx] = node; }}
                type="button"
                onClick={() => onSelect(cmd)}
                onMouseEnter={() => setSelectedIndex(globalIdx)}
                aria-selected={isSelected}
                data-command-name={cmd.name}
                className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded text-xs text-left transition-colors ${
                  isSelected ? 'bg-accent/10 text-accent' : 'text-fg hover:bg-surface-hover'
                }`}
              >
                <span className="font-mono font-semibold shrink-0">/{cmd.name}</span>
                <span className="text-fg-muted truncate">{cmd.description}</span>
                {cmd.args && (
                  <span className="text-[10px] text-fg-muted/50 ml-auto shrink-0">{cmd.args}</span>
                )}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
};
