import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Globe, Terminal, RefreshCw, ExternalLink, Pencil, X, Send } from 'lucide-react';

export interface Annotation {
  rect: { x: number; y: number; w: number; h: number }; // percentages 0-100
  note: string;
  url?: string;
  base64?: string; // screenshot of the selected region
}

interface WorkspaceBrowserProps {
  url?: string;
  terminalOutput?: string;
  onAnnotate?: (annotation: Annotation) => void;
}

export const WorkspaceBrowser: React.FC<WorkspaceBrowserProps> = ({ url, terminalOutput, onAnnotate }) => {
  const [activeTab, setActiveTab] = useState<'web' | 'terminal'>('web');
  const [refreshKey, setRefreshKey] = useState(0);
  const [addressUrl, setAddressUrl] = useState('');
  const userEdited = useRef(false);

  // Annotation state
  const [annotating, setAnnotating] = useState(false);
  const [selection, setSelection] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [noteInput, setNoteInput] = useState('');
  const [notePos, setNotePos] = useState<{ left: number; top: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; startY: number } | null>(null);

  useEffect(() => {
    if (!userEdited.current && url) {
      setAddressUrl(url);
    }
    setRefreshKey((k) => k + 1);
  }, [url]);

  const effectiveUrl = addressUrl
    ? `${addressUrl}${addressUrl.includes('?') ? '&' : '?'}t=${refreshKey}`
    : '';

  const handleAddressKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      userEdited.current = true;
      setRefreshKey((k) => k + 1);
    }
  };

  const handleAddressChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    userEdited.current = true;
    setAddressUrl(e.target.value);
  };

  const handleRefresh = () => setRefreshKey((k) => k + 1);

  // ---- Annotation: pointer events on overlay ----

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (!annotating) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    dragRef.current = { startX: x, startY: y };
    setSelection({ x, y, w: 0, h: 0 });
    setNotePos(null);
    setNoteInput('');
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }, [annotating]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current || !annotating) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const { startX, startY } = dragRef.current;
    setSelection({
      x: Math.min(startX, x),
      y: Math.min(startY, y),
      w: Math.abs(x - startX),
      h: Math.abs(y - startY),
    });
  }, [annotating]);

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current || !annotating) return;
    dragRef.current = null;
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
    // Show note input popup if selection is large enough
    setSelection((prev) => {
      if (!prev || prev.w < 8 || prev.h < 8) return null;
      return prev;
    });
    if (selection && selection.w >= 8 && selection.h >= 8 && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      setNotePos({
        left: selection.x + selection.w / 2 - 60,
        top: selection.y + selection.h + 8,
      });
    }
  }, [annotating, selection]);

  const submitAnnotation = useCallback(async () => {
    if (!selection || !containerRef.current || !onAnnotate) return;
    const containerRect = containerRef.current.getBoundingClientRect();

    // Calculate absolute page coordinates for Electron capturePage
    const absRect = {
      x: Math.round(containerRect.left + selection.x),
      y: Math.round(containerRect.top + selection.y),
      width: Math.round(selection.w),
      height: Math.round(selection.h),
    };

    // Percentage coords for the text description
    const pct = {
      x: Math.round((selection.x / containerRect.width) * 100),
      y: Math.round((selection.y / containerRect.height) * 100),
      w: Math.round((selection.w / containerRect.width) * 100),
      h: Math.round((selection.h / containerRect.height) * 100),
    };

    // Try to capture screenshot of the region
    let base64: string | undefined;
    try {
      base64 = await window.electronAPI?.captureRegion(absRect) ?? undefined;
    } catch {
      // capturePage not available (web mode / dev without Electron)
    }

    onAnnotate({ rect: pct, note: noteInput || '标注区域', url: addressUrl || undefined, base64 });
    // Reset
    setSelection(null);
    setNotePos(null);
    setNoteInput('');
    setAnnotating(false);
  }, [selection, noteInput, addressUrl, onAnnotate]);

  const cancelAnnotation = useCallback(() => {
    setSelection(null);
    setNotePos(null);
    setNoteInput('');
    setAnnotating(false);
  }, []);

  return (
    <div className="h-full flex flex-col bg-app">
      {/* Address bar */}
      {activeTab === 'web' && (
        <div className="flex items-center gap-1 px-2 py-1 border-b border-border bg-surface shrink-0">
          <Globe className="w-3 h-3 text-fg-muted shrink-0" />
          <input
            value={addressUrl}
            onChange={handleAddressChange}
            onKeyDown={handleAddressKeyDown}
            placeholder="输入预览地址..."
            className="flex-1 text-[11px] bg-transparent border-none outline-none text-fg font-mono px-1"
          />
          <button onClick={handleRefresh} className="p-0.5 text-fg-secondary hover:text-fg rounded" title="刷新">
            <RefreshCw className="w-3 h-3" />
          </button>
          {effectiveUrl && (
            <button
              onClick={() => window.open(effectiveUrl, '_blank')}
              className="p-0.5 text-fg-secondary hover:text-fg rounded"
              title="在浏览器中打开"
            >
              <ExternalLink className="w-3 h-3" />
            </button>
          )}
          {onAnnotate && effectiveUrl && (
            <button
              onClick={() => { setAnnotating((v) => !v); setSelection(null); setNotePos(null); }}
              className={`p-0.5 rounded text-[11px] font-medium transition-colors ${
                annotating ? 'bg-accent/20 text-accent' : 'text-fg-secondary hover:text-fg'
              }`}
              title={annotating ? '退出标注' : '标注模式'}
            >
              <Pencil className="w-3 h-3" />
            </button>
          )}
        </div>
      )}

      {/* Tab switcher */}
      <div className="flex border-b border-border shrink-0">
        <button
          onClick={() => setActiveTab('web')}
          className={`flex items-center gap-1 px-3 py-1 text-[11px] font-medium ${
            activeTab === 'web' ? 'text-fg border-b-2 border-accent -mb-px' : 'text-fg-secondary hover:text-fg'
          }`}
        >
          <Globe className="w-3 h-3" />
          预览
        </button>
        <button
          onClick={() => setActiveTab('terminal')}
          className={`flex items-center gap-1 px-3 py-1 text-[11px] font-medium ${
            activeTab === 'terminal' ? 'text-fg border-b-2 border-accent -mb-px' : 'text-fg-secondary hover:text-fg'
          }`}
        >
          <Terminal className="w-3 h-3" />
          终端
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0">
        {activeTab === 'web' && (
          <div className="h-full relative" ref={containerRef}>
            {effectiveUrl ? (
              <>
                <iframe
                  src={effectiveUrl}
                  className={`w-full h-full border-0 bg-white ${annotating ? 'pointer-events-none' : ''}`}
                  sandbox="allow-scripts allow-same-origin"
                  title="preview"
                />
                {/* Annotation overlay */}
                {annotating && (
                  <div
                    className="absolute inset-0 z-10 cursor-crosshair"
                    onPointerDown={handlePointerDown}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                  />
                )}
                {/* Selection rect */}
                {selection && selection.w > 0 && (
                  <div
                    className="absolute z-20 border-2 border-accent bg-accent/15 pointer-events-none"
                    style={{ left: selection.x, top: selection.y, width: selection.w, height: selection.h }}
                  />
                )}
                {/* Note input popover */}
                {notePos && selection && (
                  <div
                    className="absolute z-30 bg-surface border border-border rounded shadow-lg p-2 flex gap-1 items-center"
                    style={{ left: Math.max(4, notePos.left), top: Math.min(notePos.top, (containerRef.current?.getBoundingClientRect().height ?? 400) - 50) }}
                  >
                    <input
                      autoFocus
                      value={noteInput}
                      onChange={(e) => setNoteInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') submitAnnotation(); if (e.key === 'Escape') cancelAnnotation(); }}
                      placeholder="描述修改意图..."
                      className="text-[11px] bg-surface-alt border border-border rounded px-2 py-1 outline-none text-fg w-40"
                    />
                    <button onClick={submitAnnotation} className="p-1 text-accent hover:bg-accent/10 rounded" title="发送给 Agent">
                      <Send className="w-3 h-3" />
                    </button>
                    <button onClick={cancelAnnotation} className="p-1 text-fg-muted hover:text-fg rounded" title="取消">
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-fg-muted">
                <Globe className="w-8 h-8 mb-3 opacity-50" />
                <div className="text-sm">暂无预览内容</div>
                <div className="text-xs mt-1 max-w-[240px] text-center">
                  让 Agent 写入 preview/index.html 即可在此预览
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'terminal' && (
          <div className="h-full overflow-auto">
            {terminalOutput ? (
              <pre className="p-3 text-xs font-mono text-fg-secondary whitespace-pre-wrap">{terminalOutput}</pre>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-fg-muted">
                <Terminal className="w-8 h-8 mb-3 opacity-50" />
                <div className="text-sm">暂无终端输出</div>
                <div className="text-xs mt-1 max-w-[240px] text-center">
                  运行 Python/Shell 脚本后输出将显示在这里
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
