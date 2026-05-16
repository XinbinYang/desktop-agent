import React, { useEffect, useState, useCallback, useRef } from 'react';
import { File, Folder, GitBranch, BookOpen, Search, Loader } from 'lucide-react';
import { API_BASE, withAuthQuery } from '../config';
import type { FileNode } from '../types';

interface MentionItem {
  id: string;
  label: string;
  detail: string;
  category: string;
}

interface AtMentionMenuProps {
  query: string;
  onSelect: (item: MentionItem) => void;
  onClose: () => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  projectOpen: boolean;
  fileTree: FileNode[];
}

export const AtMentionMenu: React.FC<AtMentionMenuProps> = ({
  query,
  onSelect,
  onClose,
  inputRef,
  projectOpen,
  fileTree,
}) => {
  const [allItems, setAllItems] = useState<MentionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);

  // Build items from project context
  useEffect(() => {
    const items: MentionItem[] = [];

    if (projectOpen) {
      // Add git reference
      items.push({
        id: 'git',
        label: 'Git',
        detail: '当前 Git 仓库状态',
        category: 'git',
      });

      // Add knowledge reference
      items.push({
        id: 'knowledge',
        label: 'Knowledge',
        detail: '知识库检索',
        category: 'knowledge',
      });

      // Flatten file tree for @file references (top N files)
      const flatten = (nodes: FileNode[], prefix: string = ''): void => {
        for (const n of nodes.slice(0, 50)) {
          if (n.type === 'file') {
            items.push({
              id: `file:${n.path}`,
              label: n.name,
              detail: n.path,
              category: 'file',
            });
          } else if (n.type === 'dir' && n.children) {
            items.push({
              id: `folder:${n.path}`,
              label: `${n.name}/`,
              detail: n.path,
              category: 'folder',
            });
            flatten(n.children, n.path);
          }
        }
      };
      flatten(fileTree);
    }

    setAllItems(items);
  }, [projectOpen, fileTree]);

  const q = query.replace('@', '').toLowerCase();
  const filtered = allItems.filter(
    (item) =>
      !q ||
      item.label.toLowerCase().includes(q) ||
      item.detail.toLowerCase().includes(q) ||
      item.category.includes(q)
  );

  // Group by category
  const grouped: Record<string, MentionItem[]> = {};
  for (const item of filtered) {
    if (!grouped[item.category]) grouped[item.category] = [];
    grouped[item.category].push(item);
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

  const categoryIcons: Record<string, React.ReactNode> = {
    file: <File className="w-3 h-3" />,
    folder: <Folder className="w-3 h-3" />,
    git: <GitBranch className="w-3 h-3" />,
    knowledge: <BookOpen className="w-3 h-3" />,
  };
  const categoryLabels: Record<string, string> = {
    file: '文件',
    folder: '目录',
    git: 'Git',
    knowledge: '知识库',
  };

  const rect = inputRef.current?.getBoundingClientRect();
  const style: React.CSSProperties = rect
    ? {
        position: 'fixed',
        left: `${rect.left}px`,
        bottom: `${window.innerHeight - rect.top + 8}px`,
        width: `${Math.max(rect.width, 300)}px`,
        maxHeight: '280px',
        overflowY: 'auto',
        zIndex: 100,
      }
    : {};

  return (
    <div ref={menuRef} style={style} className="bg-surface border border-border rounded-lg shadow-xl p-1">
      {Object.entries(grouped).map(([category, items]) => (
        <div key={category}>
          <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] text-fg-muted uppercase tracking-wide">
            {categoryIcons[category]}
            {categoryLabels[category] || category}
          </div>
          {items.map((item, idx) => {
            const globalIdx = filtered.indexOf(item);
            const isSelected = globalIdx === selectedIndex;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelect(item)}
                onMouseEnter={() => setSelectedIndex(globalIdx)}
                className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded text-xs text-left transition-colors ${
                  isSelected ? 'bg-accent/10 text-accent' : 'text-fg hover:bg-surface-hover'
                }`}
              >
                <span className="shrink-0">{categoryIcons[item.category]}</span>
                <span className="font-medium truncate">{item.label}</span>
                <span className="text-fg-muted text-[10px] truncate ml-auto">{item.detail}</span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
};
