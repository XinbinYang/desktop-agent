import React, { useEffect, useState, useCallback, useRef } from 'react';
import { API_BASE } from '../config';
import { Terminal, X, FolderOpen, HelpCircle, Settings, Camera, Zap, FileText, User } from 'lucide-react';

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

export const SlashCommandMenu: React.FC<SlashCommandMenuProps> = ({ query, onSelect, onClose, inputRef }) => {
  const [commands, setCommands] = useState<Command[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/commands`)
      .then((r) => r.json())
      .then((data) => setCommands(data.commands || []))
      .catch(() => setCommands([]));
  }, []);

  const filtered = commands.filter(
    (c) => c.name.includes(query.replace('/', '').toLowerCase()) ||
           c.description.toLowerCase().includes(query.replace('/', '').toLowerCase())
  );

  // Group by category
  const grouped: Record<string, Command[]> = {};
  for (const cmd of filtered) {
    const cat = cmd.category || 'other';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(cmd);
  }

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === 'Enter' && filtered.length > 0) {
        e.preventDefault();
        onSelect(filtered[selectedIndex]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    const el = inputRef.current;
    el?.addEventListener('keydown', handler);
    return () => el?.removeEventListener('keydown', handler);
  }, [filtered, selectedIndex, onSelect, onClose, inputRef]);

  if (filtered.length === 0) return null;

  // Calculate position relative to textarea
  const rect = inputRef.current?.getBoundingClientRect();
  const style: React.CSSProperties = rect ? {
    position: 'fixed',
    left: `${rect.left}px`,
    bottom: `${window.innerHeight - rect.top + 8}px`,
    width: `${Math.max(rect.width, 280)}px`,
    maxHeight: '320px',
    overflowY: 'auto',
    zIndex: 100,
  } : {};

  return (
    <div ref={menuRef} style={style} className="bg-surface border border-border rounded-lg shadow-xl p-1">
      {Object.entries(grouped).map(([category, cmds]) => (
        <div key={category}>
          <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] text-fg-muted uppercase tracking-wide">
            {CATEGORY_ICONS[category]}
            {CATEGORY_LABELS[category] || category}
          </div>
          {cmds.map((cmd, idx) => {
            const globalIdx = filtered.indexOf(cmd);
            const isSelected = globalIdx === selectedIndex;
            return (
              <button
                key={cmd.name}
                type="button"
                onClick={() => onSelect(cmd)}
                onMouseEnter={() => setSelectedIndex(globalIdx)}
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
