import React, { useState, useRef, useEffect } from 'react';
import { Send, Image, Loader2, Square, ChevronDown, ChevronRight, RotateCcw } from 'lucide-react';
import { ChatMessage } from '../types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (text: string, imageBase64?: string) => void;
  onStop?: () => void;
  onRetry?: () => void;
  isRunning: boolean;
}

/** 可折叠、可调整高度的思考过程展示组件 */
const ReasoningBlock: React.FC<{ text: string }> = ({ text }) => {
  const [expanded, setExpanded] = useState(true);
  const lineCount = text.split('\n').length;
  const previewLines = text.split('\n').slice(0, 3).join('\n');

  return (
    <div className="mb-2 rounded border border-gray-700/60 bg-gray-900/60 overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-400 hover:text-gray-300 hover:bg-gray-800/50 transition-colors"
      >
        {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        <span className="font-medium">💭 思考过程</span>
        <span className="text-gray-500 ml-1">({lineCount} 行)</span>
      </button>
      {expanded && (
        <div
          className="px-3 py-2 text-xs font-mono text-gray-400 whitespace-pre-wrap overflow-auto"
          style={{
            resize: 'vertical',
            minHeight: '60px',
            maxHeight: '320px',
            lineHeight: '1.5',
          }}
        >
          {text}
        </div>
      )}
    </div>
  );
};

export const ChatPanel: React.FC<ChatPanelProps> = ({ messages, onSend, onStop, onRetry, isRunning }) => {
  const [input, setInput] = useState('');
  const [attachedImage, setAttachedImage] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustTextareaHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = () => {
    if (!input.trim() && !attachedImage) return;
    onSend(input.trim(), attachedImage || undefined);
    setInput('');
    setAttachedImage(null);
    if (textareaRef.current) {
      textareaRef.current.style.height = '40px';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = (ev) => {
      const base64 = (ev.target?.result as string)?.split(',')[1];
      if (base64) setAttachedImage(base64);
    };
    reader.readAsDataURL(file);
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = (ev) => {
            const base64 = (ev.target?.result as string)?.split(',')[1];
            if (base64) setAttachedImage(base64);
          };
          reader.readAsDataURL(file);
        }
      }
    }
  };

  return (
    <div className="h-full flex flex-col bg-gray-900">
      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <div className="text-4xl mb-4">🖥️</div>
            <div className="text-lg font-medium mb-2">Desktop Agent 就绪</div>
            <div className="text-sm text-center max-w-md">
              我可以帮你操控电脑：管理文件、执行命令、控制浏览器、<br/>
              操作桌面键鼠、与其他应用交互。支持多模型切换。
            </div>
            <div className="mt-6 grid grid-cols-2 gap-2 text-xs">
              <div className="bg-gray-800 px-3 py-2 rounded border border-gray-700">📁 读取/写入文件</div>
              <div className="bg-gray-800 px-3 py-2 rounded border border-gray-700">🌐 浏览器自动化</div>
              <div className="bg-gray-800 px-3 py-2 rounded border border-gray-700">🖱️ 键鼠控制</div>
              <div className="bg-gray-800 px-3 py-2 rounded border border-gray-700">🪟 应用窗口操作</div>
            </div>
          </div>
        )}

        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-lg px-4 py-2.5 relative group ${
              msg.role === 'user' 
                ? 'bg-agent-700 text-white' 
                : msg.role === 'system'
                ? 'bg-red-900/30 border border-red-800 text-red-200'
                : 'bg-gray-800 border border-gray-700 text-gray-100'
            }`}>
              {/* 重试按钮 - 仅对 assistant 非工具消息显示 */}
              {msg.role === 'assistant' && !msg.isTool && onRetry && !isRunning && idx === messages.length - 1 && (
                <button
                  onClick={onRetry}
                  title="重新生成"
                  className="absolute -top-2 -right-2 w-6 h-6 bg-gray-700 hover:bg-gray-600 border border-gray-600 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <RotateCcw className="w-3 h-3 text-gray-300" />
                </button>
              )}

              {msg.imageBase64 && (
                <img 
                  src={`data:image/png;base64,${msg.imageBase64}`} 
                  alt="attached" 
                  className="max-w-full max-h-64 rounded mb-2 object-contain"
                />
              )}
              
              {/* 思考过程 - 可折叠、可调整高度 */}
              {msg.reasoning && (
                <ReasoningBlock text={msg.reasoning} />
              )}
              
              {msg.isTool ? (
                <div className="text-xs font-mono text-gray-400 whitespace-pre-wrap">{msg.content}</div>
              ) : (
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          </div>
        ))}

        {isRunning && messages[messages.length - 1]?.role !== 'assistant' && (
          <div className="flex justify-start">
            <div className="bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-agent-400" />
              <span className="text-sm text-gray-400">Agent 思考中...</span>
            </div>
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="border-t border-gray-700 p-3 bg-gray-800">
        {attachedImage && (
          <div className="mb-2 flex items-center gap-2">
            <div className="relative inline-block">
              <img 
                src={`data:image/png;base64,${attachedImage}`} 
                alt="preview" 
                className="h-16 rounded border border-gray-600"
              />
              <button 
                onClick={() => setAttachedImage(null)}
                className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-500 rounded-full text-white text-xs flex items-center justify-center"
              >
                ×
              </button>
            </div>
            <span className="text-xs text-gray-400">图片已附加（将发送给支持视觉的模型）</span>
          </div>
        )}
        
        <div className="flex items-end gap-2">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="p-2 text-gray-400 hover:text-gray-200 hover:bg-gray-700 rounded-lg transition-colors"
            title="上传图片"
          >
            <Image className="w-5 h-5" />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileSelect}
          />
          
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                adjustTextareaHeight();
              }}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder="输入指令... (Shift+Enter 换行)"
              rows={1}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 pr-10 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-agent-500 resize-none max-h-32"
              style={{ minHeight: '40px' }}
            />
          </div>
          
          <button
            onClick={isRunning ? onStop : handleSend}
            disabled={!isRunning && !input.trim() && !attachedImage}
            aria-label={isRunning ? "停止" : "发送"}
            className={`p-2 rounded-lg transition-colors ${
              isRunning
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-agent-600 hover:bg-agent-500 text-white disabled:bg-gray-700 disabled:text-gray-500'
            }`}
          >
            {isRunning ? <Square className="w-5 h-5" /> : <Send className="w-5 h-5" />}
          </button>
        </div>
      </div>
    </div>
  );
};