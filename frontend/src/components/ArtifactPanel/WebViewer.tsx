import React, { useRef, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';

interface WebViewerProps {
  url: string;
}

export const WebViewer: React.FC<WebViewerProps> = ({ url }) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    setRefreshKey((k) => k + 1);
  }, [url]);

  const fullUrl = url ? `${url}?t=${refreshKey}` : '';

  if (!fullUrl) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-500">
        <div className="text-sm">暂无网页预览</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-white">
      <div className="flex items-center gap-2 px-2 py-1 bg-gray-100 border-b border-gray-200">
        <span className="text-[10px] text-gray-500 truncate flex-1">{url}</span>
        <button
          onClick={() => setRefreshKey((k) => k + 1)}
          className="p-1 text-gray-500 hover:text-gray-700"
          title="刷新"
        >
          <RefreshCw className="w-3 h-3" />
        </button>
      </div>
      <iframe
        ref={iframeRef}
        src={fullUrl}
        className="flex-1 w-full border-0"
        sandbox="allow-scripts allow-same-origin"
        title="web-preview"
      />
    </div>
  );
};
