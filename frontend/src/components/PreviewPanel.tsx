import React, { useState, useEffect, useRef } from 'react';
import { Globe, Terminal, RefreshCw } from 'lucide-react';

interface PreviewPanelProps {
  url?: string;
  terminalOutput?: string;
}

export const PreviewPanel: React.FC<PreviewPanelProps> = ({ url, terminalOutput }) => {
  const [activeTab, setActiveTab] = useState<'web' | 'terminal'>('web');
  const [refreshKey, setRefreshKey] = useState(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // 当 url 变化时自动刷新 iframe
  useEffect(() => {
    setRefreshKey(k => k + 1);
  }, [url]);

  const fullUrl = url ? `${url}?t=${refreshKey}` : '';

  return (
    <div className="h-full flex flex-col bg-app">
      {/* Tab 切换 */}
      <div className="flex border-b border-border">
        <button
          onClick={() => setActiveTab('web')}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
            activeTab === 'web' ? 'bg-surface-alt text-fg border-accent -mb-px' : 'text-fg-secondary hover:text-fg border-transparent'
          }`}
        >
          <Globe className="w-3.5 h-3.5" />
          网页预览
        </button>
        <button
          onClick={() => setActiveTab('terminal')}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
            activeTab === 'terminal' ? 'bg-surface-alt text-fg border-accent -mb-px' : 'text-fg-secondary hover:text-fg border-transparent'
          }`}
        >
          <Terminal className="w-3.5 h-3.5" />
          终端输出
        </button>
        {fullUrl && (
          <button
            onClick={() => setRefreshKey(k => k + 1)}
            className="ml-auto px-2 py-1.5 text-fg-secondary hover:text-fg"
            title="刷新"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* 内容区 */}
      <div className="flex-1 min-h-0">
        {activeTab === 'web' && (
          <div className="h-full">
            {fullUrl ? (
              <iframe
                ref={iframeRef}
                src={fullUrl}
                className="w-full h-full border-0 bg-white"
                sandbox="allow-scripts allow-same-origin"
                title="preview"
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-fg-muted">
                <Globe className="w-8 h-8 mb-3 opacity-50" />
                <div className="text-sm">暂无预览内容</div>
                <div className="text-xs mt-1 max-w-[200px] text-center">
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
                <div className="text-xs mt-1 max-w-[200px] text-center">
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
