import React, { useEffect, useMemo, useRef, useState } from 'react';
import { File, Folder, GitBranch, BookOpen, Code2 } from 'lucide-react';
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
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  // Build items from project context
  useEffect(() => {
    const items: MentionItem[] = [];

    items.push({
      id: 'coding agent',
      label: 'Coding Agent',
      detail: 'Delegate this message to the engineering specialist',
      category: 'agent',
    });

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
  const filtered = useMemo(
    () => allItems.filter(
      (item) =>
        !q ||
        item.label.toLowerCase().includes(q) ||
        item.detail.toLowerCase().includes(q) ||
        item.category.includes(q)
    ),
    [allItems, q]
  );

  // Group by category
  const groupedEntries = useMemo(() => {
    const grouped: Record<string, MentionItem[]> = {};
    for (const item of filtered) {
      if (!grouped[item.category]) grouped[item.category] = [];
      grouped[item.category].push(item);
    }
    return Object.entries(grouped);
  }, [filtered]);

  const visibleItems = useMemo(
    () => groupedEntries.flatMap(([, items]) => items),
    [groupedEntries]
  );

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    setSelectedIndex((idx) => {
      if (visibleItems.length === 0) return 0;
      return Math.min(idx, visibleItems.length - 1);
    });
  }, [visibleItems.length]);

  useEffect(() => {
    itemRefs.current[selectedIndex]?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        setSelectedIndex((i) => Math.min(i + 1, visibleItems.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === 'Enter' && visibleItems.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        onSelect(visibleItems[Math.min(selectedIndex, visibleItems.length - 1)]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    const el = inputRef.current;
    el?.addEventListener('keydown', handler);
    return () => el?.removeEventListener('keydown', handler);
  }, [visibleItems, selectedIndex, onSelect, onClose, inputRef]);

  if (visibleItems.length === 0) return null;

  const categoryIcons: Record<string, React.ReactNode> = {
    agent: <Code2 className="w-3 h-3" />,
    file: <File className="w-3 h-3" />,
    folder: <Folder className="w-3 h-3" />,
    git: <GitBranch className="w-3 h-3" />,
    knowledge: <BookOpen className="w-3 h-3" />,
  };
  const categoryLabels: Record<string, string> = {
    agent: 'Agent',
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
      {groupedEntries.map(([category, items]) => (
        <div key={category}>
          <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] text-fg-muted uppercase tracking-wide">
            {categoryIcons[category]}
            {categoryLabels[category] || category}
          </div>
          {items.map((item) => {
            const globalIdx = visibleItems.indexOf(item);
            const isSelected = globalIdx === selectedIndex;
            return (
              <button
                key={item.id}
                ref={(node) => { itemRefs.current[globalIdx] = node; }}
                type="button"
                onClick={() => onSelect(item)}
                onMouseEnter={() => setSelectedIndex(globalIdx)}
                aria-selected={isSelected}
                data-mention-id={item.id}
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
