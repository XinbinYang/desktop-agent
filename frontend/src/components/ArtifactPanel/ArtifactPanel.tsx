import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Boxes, Eye, Image as ImageIcon, ListTree, Play, RefreshCw, Search, TerminalSquare } from 'lucide-react';
import {
  ArtifactItem,
  AutomationAction,
  AutomationElement,
  AutomationReplayStatus,
  AutomationSnapshot,
  AutomationTrace,
  ToolCall,
} from '../../types';
import { ArtifactList } from './ArtifactList';
import { ImageViewer } from './ImageViewer';
import { CodeViewer } from './CodeViewer';
import { DataTable } from './DataTable';
import { TerminalOutput } from './TerminalOutput';
import { WebViewer } from './WebViewer';
import { AIMouseCursor } from './AIMouseCursor';

interface ArtifactPanelProps {
  artifacts: ArtifactItem[];
  isRunning: boolean;
  latestToolCall?: ToolCall | null;
  automationSnapshots?: AutomationSnapshot[];
  automationActions?: AutomationAction[];
  automationTraces?: AutomationTrace[];
  automationReplayStatus?: AutomationReplayStatus | null;
  onAutomationObserve?: (source?: string) => void;
  onAutomationReplay?: (traceId: string) => void;
}

type InspectorTab = 'inspect' | 'trace' | 'outputs';

function elementLabel(element: AutomationElement): string {
  return element.name || element.text || element.selector || element.role || element.id;
}

function formatTime(value?: number): string {
  if (!value) return '';
  return new Date(value).toLocaleTimeString();
}

export const ArtifactPanel: React.FC<ArtifactPanelProps> = ({
  artifacts,
  isRunning,
  latestToolCall,
  automationSnapshots = [],
  automationActions = [],
  automationTraces = [],
  automationReplayStatus = null,
  onAutomationObserve,
  onAutomationReplay,
}) => {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<InspectorTab>('inspect');
  const [selectedElementId, setSelectedElementId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (artifacts.length > 0) {
      const latest = artifacts[artifacts.length - 1];
      setActiveId(latest.id);
    }
  }, [artifacts.length]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const snapshot = automationSnapshots[automationSnapshots.length - 1] || null;
  const selectedElement = useMemo(
    () => snapshot?.elements.find((element) => element.id === selectedElementId) || null,
    [selectedElementId, snapshot],
  );

  const filteredElements = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const elements = snapshot?.elements || [];
    if (!needle) return elements;
    return elements.filter((element) =>
      [
        element.id,
        element.role,
        element.name,
        element.text,
        element.selector,
        element.attributes?.control_type,
        element.attributes?.window_title,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [query, snapshot]);

  const activeItem = artifacts.find((a) => a.id === activeId);

  const handleDelete = (id: string) => {
    if (activeId === id) {
      const idx = artifacts.findIndex((a) => a.id === id);
      const next = artifacts[idx + 1] || artifacts[idx - 1];
      setActiveId(next?.id || null);
    }
  };

  const renderOutputContent = () => {
    if (!activeItem) {
      return (
        <div className="h-full flex flex-col items-center justify-center text-fg-muted">
          <TerminalSquare className="w-8 h-8 mb-2 opacity-50" />
          <div className="text-sm">暂无成果</div>
        </div>
      );
    }

    switch (activeItem.type) {
      case 'web':
        return <WebViewer url={activeItem.url || ''} />;
      case 'image':
        return <ImageViewer url={activeItem.url} base64={activeItem.base64} />;
      case 'code':
        return <CodeViewer content={activeItem.content || ''} filename={activeItem.title} />;
      case 'data':
        return activeItem.title.endsWith('.json')
          ? <pre className="h-full overflow-auto p-4 text-xs font-mono text-fg-secondary">{activeItem.content}</pre>
          : <DataTable content={activeItem.content || ''} />;
      case 'terminal':
        return <TerminalOutput content={activeItem.content || ''} />;
      case 'video':
        return (
          <div className="h-full flex items-center justify-center bg-app p-4">
            <video src={activeItem.url} controls className="max-w-full max-h-full rounded" />
          </div>
        );
      default:
        return <TerminalOutput content={activeItem.content || ''} />;
    }
  };

  const renderInspector = () => {
    if (!snapshot) {
      return (
        <div className="h-full flex flex-col items-center justify-center text-fg-muted px-6">
          <Bot className="w-10 h-10 mb-3 opacity-50" />
          <div className="text-sm font-medium text-fg-secondary">等待自动化观测</div>
          <button
            type="button"
            onClick={() => onAutomationObserve?.('auto')}
            className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-border bg-surface hover:bg-surface-hover text-xs text-fg"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            立即观察
          </button>
        </div>
      );
    }

    const image = snapshot.screenshot?.base64
      ? `data:image/png;base64,${snapshot.screenshot.base64}`
      : '';
    const imageWidth = snapshot.screenshot?.width || snapshot.viewport?.width || 1;
    const imageHeight = snapshot.screenshot?.height || snapshot.viewport?.height || 1;

    return (
      <div className="h-full grid grid-cols-[minmax(0,1fr)_280px] bg-app">
        <div className="min-w-0 min-h-0 flex flex-col">
          <div className="shrink-0 flex items-center justify-between gap-2 px-3 py-2 border-b border-border bg-surface">
            <div className="min-w-0">
              <div className="text-xs font-semibold text-fg truncate">
                {snapshot.title || snapshot.url || 'Automation Snapshot'}
              </div>
              <div className="text-[10px] text-fg-muted truncate">
                {snapshot.source} · {snapshot.element_count ?? snapshot.elements.length} elements · {formatTime(snapshot.timestamp)}
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onAutomationObserve?.('browser')}
                className="px-2 py-1 text-[11px] rounded border border-border text-fg-secondary hover:text-fg hover:bg-surface-hover"
              >
                Browser
              </button>
              <button
                type="button"
                onClick={() => onAutomationObserve?.('desktop')}
                className="px-2 py-1 text-[11px] rounded border border-border text-fg-secondary hover:text-fg hover:bg-surface-hover"
              >
                Desktop
              </button>
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-auto flex items-center justify-center p-3 bg-black/20">
            {image ? (
              <div className="relative inline-block max-w-full max-h-full">
                <img
                  src={image}
                  alt="automation snapshot"
                  className="block max-w-full max-h-full object-contain rounded border border-border bg-white"
                />
                <div className="absolute inset-0 pointer-events-none">
                  {filteredElements.slice(0, 160).map((element) => {
                    const selected = element.id === selectedElementId;
                    const bbox = element.bbox;
                    return (
                      <button
                        key={element.id}
                        type="button"
                        className={`absolute pointer-events-auto border ${
                          selected ? 'border-accent bg-accent/20' : 'border-sky-400/70 hover:border-accent hover:bg-accent/15'
                        }`}
                        title={elementLabel(element)}
                        onClick={() => setSelectedElementId(element.id)}
                        style={{
                          left: `${(bbox.x / imageWidth) * 100}%`,
                          top: `${(bbox.y / imageHeight) * 100}%`,
                          width: `${Math.max(0.6, (bbox.width / imageWidth) * 100)}%`,
                          height: `${Math.max(0.6, (bbox.height / imageHeight) * 100)}%`,
                        }}
                      />
                    );
                  })}
                </div>
                <AIMouseCursor
                  isRunning={isRunning}
                  latestToolCall={latestToolCall}
                  containerWidth={containerSize.width}
                  containerHeight={containerSize.height}
                />
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-fg-muted">
                <ImageIcon className="w-8 h-8 mb-2 opacity-50" />
                <div className="text-sm">当前 snapshot 没有截图</div>
              </div>
            )}
          </div>
        </div>

        <div className="min-w-0 min-h-0 border-l border-border flex flex-col bg-surface/40">
          <div className="p-2 border-b border-border">
            <div className="flex items-center gap-1.5 px-2 py-1 rounded border border-border bg-app">
              <Search className="w-3.5 h-3.5 text-fg-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="筛选元素..."
                className="min-w-0 flex-1 bg-transparent outline-none text-xs text-fg"
              />
            </div>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto">
            {filteredElements.map((element) => {
              const selected = element.id === selectedElementId;
              return (
                <button
                  key={element.id}
                  type="button"
                  onClick={() => setSelectedElementId(element.id)}
                  className={`w-full text-left px-3 py-2 border-b border-border/70 hover:bg-surface-hover ${
                    selected ? 'bg-accent/10' : ''
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-fg truncate">{elementLabel(element)}</span>
                    <span className="text-[10px] text-fg-muted shrink-0">{element.role}</span>
                  </div>
                  <div className="mt-1 text-[10px] text-fg-muted truncate">{element.id}</div>
                </button>
              );
            })}
          </div>
          {selectedElement && (
            <div className="shrink-0 border-t border-border p-3 bg-app">
              <div className="text-xs font-semibold text-fg mb-1">{elementLabel(selectedElement)}</div>
              <div className="text-[10px] text-fg-muted leading-5">
                <div>id: {selectedElement.id}</div>
                <div>role: {selectedElement.role}</div>
                {selectedElement.selector && <div className="truncate">selector: {selectedElement.selector}</div>}
                <div>
                  bbox: {selectedElement.bbox.x},{selectedElement.bbox.y},{selectedElement.bbox.width}x{selectedElement.bbox.height}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderTrace = () => (
    <div className="h-full grid grid-cols-[280px_minmax(0,1fr)] bg-app">
      <div className="border-r border-border overflow-y-auto">
        {automationTraces.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-fg-muted px-4">
            <Boxes className="w-8 h-8 mb-2 opacity-50" />
            <div className="text-xs text-center">暂无自动化 trace</div>
          </div>
        ) : (
          automationTraces.slice().reverse().map((trace) => (
            <div key={trace.trace_id} className="border-b border-border p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-semibold text-fg truncate">{trace.trace_id}</div>
                <button
                  type="button"
                  onClick={() => onAutomationReplay?.(trace.trace_id)}
                  className="p-1 rounded text-accent hover:bg-accent/10"
                  title="Replay trace"
                >
                  <Play className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="text-[10px] text-fg-muted mt-1">
                {trace.source || 'auto'} · {trace.actions?.length || 0} step(s) · {formatTime(trace.updated_at || trace.created_at)}
              </div>
            </div>
          ))
        )}
      </div>
      <div className="min-w-0 overflow-y-auto p-4">
        {automationReplayStatus && (
          <div className={`mb-3 rounded border px-3 py-2 text-xs ${
            automationReplayStatus.status === 'error'
              ? 'border-danger/40 bg-danger/10 text-danger'
              : 'border-accent/30 bg-accent/10 text-fg'
          }`}>
            Replay {automationReplayStatus.status}: {automationReplayStatus.trace_id}
            {automationReplayStatus.error && <div className="mt-1 text-[11px]">{automationReplayStatus.error}</div>}
          </div>
        )}
        {automationActions.slice().reverse().map((action) => (
          <div key={action.action_id} className="mb-3 rounded border border-border bg-surface p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-semibold text-fg">{action.type}</div>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                action.status === 'error' ? 'bg-danger/15 text-danger' : 'bg-success/15 text-success'
              }`}>
                {action.status}
              </span>
            </div>
            <div className="mt-1 text-[11px] text-fg-muted">
              {action.source} · {action.duration_ms ?? 0}ms · {formatTime(action.started_at)}
            </div>
            {action.locator_chain && action.locator_chain.length > 0 && (
              <div className="mt-2 text-[11px] text-fg-secondary">
                {action.locator_chain.join(' → ')}
              </div>
            )}
            {action.error && <div className="mt-2 text-xs text-danger">{action.error}</div>}
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div ref={containerRef} className="h-full flex flex-col bg-app relative">
      <div className="shrink-0 flex items-center border-b border-border bg-surface">
        {[
          { key: 'inspect' as const, label: '检查', icon: Eye },
          { key: 'trace' as const, label: '回放', icon: ListTree },
          { key: 'outputs' as const, label: '输出', icon: TerminalSquare },
        ].map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 ${
                active
                  ? 'border-accent text-fg bg-surface-alt'
                  : 'border-transparent text-fg-secondary hover:text-fg hover:bg-surface-hover'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      <div className="flex-1 min-h-0">
        {activeTab === 'inspect' && renderInspector()}
        {activeTab === 'trace' && renderTrace()}
        {activeTab === 'outputs' && (
          <div className="h-full flex bg-app">
            <div className="w-44 border-r border-border shrink-0">
              <ArtifactList
                artifacts={artifacts}
                activeId={activeId}
                onSelect={setActiveId}
                onDelete={handleDelete}
                onClear={() => setActiveId(null)}
              />
            </div>
            <div className="flex-1 min-w-0 relative">
              {renderOutputContent()}
              <AIMouseCursor
                isRunning={isRunning}
                latestToolCall={latestToolCall}
                containerWidth={containerSize.width}
                containerHeight={containerSize.height}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
