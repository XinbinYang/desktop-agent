import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatPanel } from './components/ChatPanel';
import { TerminalPanel } from './components/TerminalPanel';
import { ToolCallView } from './components/ToolCallView';
import { PreviewPanel } from './components/PreviewPanel';
import { ModelInfo, ToolCall, ChatMessage, WS_EVENT } from './types';
import { API_BASE, WS_BASE } from './config';

export default function App() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [currentModel, setCurrentModel] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [showTerminal, setShowTerminal] = useState(true);
  const [sessionId, setSessionId] = useState(() => `session_${Date.now()}`);
  const [rightTab, setRightTab] = useState<'tools' | 'preview'>('tools');
  const [previewUrl, setPreviewUrl] = useState<string>('');
  const [previewOutput, setPreviewOutput] = useState<string>('');
  const [rightWidth, setRightWidth] = useState(320);
  const isResizing = useRef(false);
  const [sessions, setSessions] = useState<{id: string; model_id: string; message_count: number}[]>([]);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempt = useRef(0);
  const MAX_RECONNECT_DELAY = 30000;

  // 获取模型列表和会话列表
  useEffect(() => {
    fetch(`${API_BASE}/api/models`)
      .then(r => r.json())
      .then(data => {
        setModels(data.models || []);
        setCurrentModel(data.default || '');
      })
      .catch(console.error);
    loadSessions();
  }, []);

  const loadSessions = () => {
    fetch(`${API_BASE}/api/sessions`)
      .then(r => r.json())
      .then(data => setSessions(data.sessions || []))
      .catch(console.error);
  };

  // 连接 WebSocket
  const connectWS = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    
    const ws = new WebSocket(`${WS_BASE}/ws/${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      reconnectAttempt.current = 0;
      addTerminalLog('[系统] WebSocket 已连接');
    };

    ws.onmessage = (event) => {
      const msg: WS_EVENT = JSON.parse(event.data);
      handleWSEvent(msg);
    };

    ws.onclose = () => {
      setIsConnected(false);
      addTerminalLog('[系统] WebSocket 已断开，尝试重连...');
      const delay = Math.min(1000 * 2 ** reconnectAttempt.current, MAX_RECONNECT_DELAY);
      reconnectAttempt.current += 1;
      reconnectTimer.current = setTimeout(connectWS, delay);
    };

    ws.onerror = (err) => {
      console.error('WS error:', err);
      addTerminalLog('[错误] WebSocket 连接错误');
    };
  }, [sessionId]);

  useEffect(() => {
    connectWS();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connectWS]);

  // 监听 Electron 菜单事件
  useEffect(() => {
    if (typeof window !== 'undefined' && (window as any).electronAPI?.onNewSession) {
      const handler = () => newSession();
      (window as any).electronAPI.onNewSession(handler);
      return () => {
        (window as any).electronAPI.removeAllListeners('menu-new-session');
      };
    }
  }, []);

  const switchSession = (newSessionId: string) => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    wsRef.current?.close();
    setMessages([]);
    setToolCalls([]);
    setSessionId(newSessionId);
  };

  const newSession = () => {
    switchSession(`session_${Date.now()}`);
  };

  const deleteSession = async (id: string) => {
    await fetch(`${API_BASE}/api/sessions/${id}`, { method: 'DELETE' });
    loadSessions();
    if (id === sessionId) {
      newSession();
    }
  };

  const handleWSEvent = (event: WS_EVENT) => {
    switch (event.type) {
      case 'content':
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last && last.role === 'assistant' && !last.isTool) {
            const updated = [...prev];
            updated[updated.length - 1] = { ...last, content: last.content + event.data.text };
            return updated;
          }
          return [...prev, { role: 'assistant', content: event.data.text, isTool: false }];
        });
        break;
      
      case 'reasoning':
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last && last.role === 'assistant' && !last.isTool) {
            const updated = [...prev];
            updated[updated.length - 1] = { ...last, reasoning: (last.reasoning || '') + event.data.text };
            return updated;
          }
          return [...prev, { role: 'assistant', content: '', isTool: false, reasoning: event.data.text }];
        });
        break;
      
      case 'tool_call':
        setToolCalls(prev => [...prev, {
          name: event.data.name,
          args: event.data.args,
          result: event.data.result,
          timestamp: Date.now(),
        }]);
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: `\`\`\`tool\n${event.data.name}: ${JSON.stringify(event.data.args)}\n→ ${event.data.result}\n\`\`\``,
          isTool: true,
        }]);
        addTerminalLog(`[工具] ${event.data.name}: ${event.data.result}`);
        // Codex 预览检测
        if (event.data.name === 'file_write') {
          const path = event.data.args?.path || '';
          if (path.startsWith('preview/') && path.endsWith('.html')) {
            setPreviewUrl(`${API_BASE}/preview/${path.replace('preview/', '')}`);
            setRightTab('preview');
          }
        }
        if (event.data.name === 'shell_execute') {
          setPreviewOutput(prev => prev + `\n$ ${event.data.args?.command || ''}\n${event.data.result}`);
        }
        break;
      
      case 'image':
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: '',
          imageBase64: event.data.base64,
          isTool: false,
        }]);
        break;
      
      case 'status':
        if (event.data.status === 'completed' || event.data.status === 'max_iterations_reached') {
          setIsRunning(false);
        }
        addTerminalLog(`[状态] ${event.data.status} (迭代: ${event.data.iteration})`);
        break;
      
      case 'error':
        setMessages(prev => [...prev, { role: 'system', content: `错误: ${event.data.message}`, isTool: false }]);
        setIsRunning(false);
        addTerminalLog(`[错误] ${event.data.message}`);
        break;
      
      case 'done':
        setIsRunning(false);
        break;
      
      case 'cleared':
        setMessages([]);
        setToolCalls([]);
        addTerminalLog('[系统] 会话已清空');
        break;
    }
  };

  const addTerminalLog = (log: string) => {
    setTerminalLogs(prev => [...prev.slice(-200), `[${new Date().toLocaleTimeString()}] ${log}`]);
  };

  const sendMessage = (text: string, imageBase64?: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addTerminalLog('[错误] 未连接到后端服务');
      return;
    }
    
    setIsRunning(true);
    setMessages(prev => [...prev, { role: 'user', content: text, imageBase64, isTool: false }]);
    
    wsRef.current.send(JSON.stringify({
      type: 'chat',
      text,
      model_id: currentModel,
      image_base64: imageBase64,
    }));
  };

  const clearSession = () => {
    wsRef.current?.send(JSON.stringify({ type: 'clear' }));
  };

  const stopRunning = () => {
    wsRef.current?.send(JSON.stringify({ type: 'stop' }));
  };

  const retryLast = () => {
    wsRef.current?.send(JSON.stringify({ type: 'retry', model_id: currentModel }));
    setIsRunning(true);
  };

  const executeToolDirect = async (toolName: string, args: any) => {
    wsRef.current?.send(JSON.stringify({ type: 'tool_direct', tool_name: toolName, args }));
  };

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-gray-100 overflow-hidden">
      {/* 顶部标题栏 */}
      <div className="h-10 bg-gray-800 border-b border-gray-700 flex items-center px-4 justify-between select-none app-drag">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm font-medium">Desktop Agent</span>
          <span className="text-xs text-gray-500 ml-2">{isRunning ? '● 运行中' : '○ 就绪'}</span>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={currentModel}
            onChange={(e) => setCurrentModel(e.target.value)}
            className="text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1 outline-none focus:border-agent-500"
          >
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.name} ({m.provider})</option>
            ))}
          </select>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧边栏 */}
        <Sidebar
          models={models}
          currentModel={currentModel}
          onModelChange={setCurrentModel}
          onClear={clearSession}
          onToggleTerminal={() => setShowTerminal(v => !v)}
          onExecuteTool={executeToolDirect}
          isConnected={isConnected}
          sessions={sessions}
          currentSession={sessionId}
          onNewSession={newSession}
          onSwitchSession={switchSession}
          onDeleteSession={deleteSession}
        />

        {/* 中间 + 底部面板 */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0">
            <ChatPanel
              messages={messages}
              onSend={sendMessage}
              onStop={stopRunning}
              onRetry={retryLast}
              isRunning={isRunning}
            />
          </div>
          
          {showTerminal && (
            <div className="h-48 border-t border-gray-700">
              <TerminalPanel logs={terminalLogs} />
            </div>
          )}
        </div>

        {/* 右侧 Tab 面板（工具调用 / 预览） */}
        <div
          className="border-l border-gray-700 bg-gray-800/50 flex flex-col relative"
          style={{ width: rightWidth, minWidth: 200, maxWidth: 1400 }}
        >
          {/* 拖拽分隔条 */}
          <div
            className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-agent-500/30 z-10"
            onMouseDown={(e) => {
              isResizing.current = true;
              const startX = e.clientX;
              const startWidth = rightWidth;
              const handleMove = (moveEvent: MouseEvent) => {
                if (!isResizing.current) return;
                const delta = startX - moveEvent.clientX;
                setRightWidth(Math.max(200, Math.min(600, startWidth + delta)));
              };
              const handleUp = () => {
                isResizing.current = false;
                document.removeEventListener('mousemove', handleMove);
                document.removeEventListener('mouseup', handleUp);
              };
              document.addEventListener('mousemove', handleMove);
              document.addEventListener('mouseup', handleUp);
            }}
          />
          <div className="flex border-b border-gray-700">
            <button
              onClick={() => setRightTab('tools')}
              className={`flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
                rightTab === 'tools' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              工具调用
            </button>
            <button
              onClick={() => setRightTab('preview')}
              className={`flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
                rightTab === 'preview' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              预览
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-hidden">
            {rightTab === 'tools' && (
              <div className="h-full overflow-y-auto p-2">
                {toolCalls.length === 0 && (
                  <div className="text-xs text-gray-500 text-center mt-4">暂无工具调用</div>
                )}
                {toolCalls.map((tc, i) => (
                  <ToolCallView key={i} toolCall={tc} />
                ))}
              </div>
            )}
            {rightTab === 'preview' && (
              <PreviewPanel url={previewUrl} terminalOutput={previewOutput} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}