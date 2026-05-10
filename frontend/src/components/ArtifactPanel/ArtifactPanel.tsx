import React, { useState, useRef, useEffect } from 'react';
import { ArtifactItem } from '../../types';
import { ArtifactList } from './ArtifactList';
import { ImageViewer } from './ImageViewer';
import { CodeViewer } from './CodeViewer';
import { DataTable } from './DataTable';
import { TerminalOutput } from './TerminalOutput';
import { WebViewer } from './WebViewer';
import { AIMouseCursor } from './AIMouseCursor';
import { ToolCall } from '../../types';

interface ArtifactPanelProps {
  artifacts: ArtifactItem[];
  isRunning: boolean;
  latestToolCall?: ToolCall | null;
}

export const ArtifactPanel: React.FC<ArtifactPanelProps> = ({
  artifacts,
  isRunning,
  latestToolCall,
}) => {
  const [activeId, setActiveId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

  // 当有新成果时自动选中最新项
  useEffect(() => {
    if (artifacts.length > 0) {
      const latest = artifacts[artifacts.length - 1];
      setActiveId(latest.id);
    }
  }, [artifacts.length]);

  // 监听容器尺寸变化
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

  const activeItem = artifacts.find((a) => a.id === activeId);

  const handleDelete = (id: string) => {
    if (activeId === id) {
      const idx = artifacts.findIndex((a) => a.id === id);
      const next = artifacts[idx + 1] || artifacts[idx - 1];
      setActiveId(next?.id || null);
    }
  };

  const renderContent = () => {
    if (!activeItem) {
      return (
        <div className="h-full flex flex-col items-center justify-center text-gray-500">
          <div className="text-sm">选择一个成果查看</div>
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
          ? <pre className="h-full overflow-auto p-4 text-xs font-mono text-gray-300">{activeItem.content}</pre>
          : <DataTable content={activeItem.content || ''} />;
      case 'terminal':
        return <TerminalOutput content={activeItem.content || ''} />;
      case 'video':
        return (
          <div className="h-full flex items-center justify-center bg-gray-950 p-4">
            <video
              src={activeItem.url}
              controls
              className="max-w-full max-h-full rounded"
            />
          </div>
        );
      default:
        return <TerminalOutput content={activeItem.content || ''} />;
    }
  };

  return (
    <div ref={containerRef} className="h-full flex bg-gray-900 relative">
      {/* 左侧成果列表 */}
      <div className="w-44 border-r border-gray-700 shrink-0">
        <ArtifactList
          artifacts={artifacts}
          activeId={activeId}
          onSelect={setActiveId}
          onDelete={handleDelete}
          onClear={() => setActiveId(null)}
        />
      </div>

      {/* 右侧内容区 */}
      <div className="flex-1 min-w-0 relative">
        {renderContent()}

        {/* AI 鼠标指针叠加层 */}
        <AIMouseCursor
          isRunning={isRunning}
          latestToolCall={latestToolCall}
          containerWidth={containerSize.width}
          containerHeight={containerSize.height}
        />
      </div>
    </div>
  );
};
