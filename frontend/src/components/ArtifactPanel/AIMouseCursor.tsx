import React, { useEffect, useRef, useState } from 'react';
import { ToolCall } from '../../types';

type CursorState = 'hidden' | 'idle' | 'moving' | 'clicking' | 'typing' | 'scrolling';

interface CursorPosition {
  x: number;
  y: number;
}

interface AIMouseCursorProps {
  isRunning: boolean;
  latestToolCall?: ToolCall | null;
  containerWidth: number;
  containerHeight: number;
}

export const AIMouseCursor: React.FC<AIMouseCursorProps> = ({
  isRunning,
  latestToolCall,
  containerWidth,
  containerHeight,
}) => {
  const [state, setState] = useState<CursorState>('hidden');
  const [pos, setPos] = useState<CursorPosition>({ x: 0.5, y: 0.5 });
  const [targetPos, setTargetPos] = useState<CursorPosition>({ x: 0.5, y: 0.5 });
  const [ripple, setRipple] = useState(false);
  const [inputText, setInputText] = useState('');
  const animRef = useRef<number>();
  const idleRef = useRef<number>();

  // 解析 tool_call 坐标
  useEffect(() => {
    if (!latestToolCall || !isRunning) return;

    const { name, args } = latestToolCall;

    if (name === 'mouse_click' || name === 'mouse_move') {
      const x = args?.x ?? args?.screenX;
      const y = args?.y ?? args?.screenY;
      if (typeof x === 'number' && typeof y === 'number') {
        // 映射屏幕坐标到容器比例（假设屏幕 1920x1080）
        const nx = Math.min(1, Math.max(0, x / 1920));
        const ny = Math.min(1, Math.max(0, y / 1080));
        setTargetPos({ x: nx, y: ny });
        setState('moving');
      }
    } else if (name === 'browser_click') {
      // 尝试从 selector 获取位置（简化为中央）
      setState('clicking');
      setRipple(true);
      setTimeout(() => setRipple(false), 600);
    } else if (name === 'type_text' || name === 'browser_type') {
      const text = args?.text || args?.content || '';
      setInputText(text.slice(0, 20));
      setState('typing');
      setTimeout(() => setInputText(''), 1500);
    } else if (name === 'scroll') {
      setState('scrolling');
    }
  }, [latestToolCall, isRunning]);

  // 移动动画
  useEffect(() => {
    if (state !== 'moving') return;
    const start = { ...pos };
    const startTime = performance.now();
    const duration = 500;

    const animate = (time: number) => {
      const elapsed = time - startTime;
      const progress = Math.min(1, elapsed / duration);
      const ease = 1 - Math.pow(1 - progress, 3);

      setPos({
        x: start.x + (targetPos.x - start.x) * ease,
        y: start.y + (targetPos.y - start.y) * ease,
      });

      if (progress < 1) {
        animRef.current = requestAnimationFrame(animate);
      } else {
        setState('clicking');
        setRipple(true);
        setTimeout(() => setRipple(false), 600);
        setTimeout(() => setState('idle'), 600);
      }
    };

    animRef.current = requestAnimationFrame(animate);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [state, targetPos]);

  // idle 微动
  useEffect(() => {
    if (state !== 'idle' || !isRunning) return;

    const jitter = () => {
      setPos((p) => ({
        x: Math.min(1, Math.max(0, p.x + (Math.random() - 0.5) * 0.02)),
        y: Math.min(1, Math.max(0, p.y + (Math.random() - 0.5) * 0.02)),
      }));
      idleRef.current = window.setTimeout(jitter, 800 + Math.random() * 1000);
    };

    idleRef.current = window.setTimeout(jitter, 500);
    return () => {
      if (idleRef.current) clearTimeout(idleRef.current);
    };
  }, [state, isRunning]);

  // 状态流转
  useEffect(() => {
    if (!isRunning) {
      setState('hidden');
      return;
    }
    if (state === 'hidden') {
      setState('idle');
      setPos({ x: 0.5, y: 0.5 });
    }
  }, [isRunning]);

  if (state === 'hidden') return null;

  const left = pos.x * containerWidth;
  const top = pos.y * containerHeight;

  return (
    <div
      className="absolute inset-0 pointer-events-none z-50 overflow-hidden"
      style={{ width: containerWidth, height: containerHeight }}
    >
      {/* 光标 */}
      <div
        className="absolute transition-none"
        style={{
          left: left - 8,
          top: top - 2,
          transform: `rotate(${state === 'typing' ? -10 : 0}deg)`,
          transition: state === 'idle' ? 'left 0.8s ease, top 0.8s ease' : 'none',
        }}
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <defs>
            <filter id="glow">
              <feGaussianBlur stdDeviation="2" result="coloredBlur" />
              <feMerge>
                <feMergeNode in="coloredBlur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <path
            d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87a.5.5 0 0 0 .35-.85L6.35 2.86a.5.5 0 0 0-.85.35z"
            fill="#60a5fa"
            stroke="#3b82f6"
            strokeWidth="1"
            filter="url(#glow)"
          />
        </svg>

        {/* 点击涟漪 */}
        {ripple && (
          <div
            className="absolute -left-3 -top-3 w-12 h-12 rounded-full border-2 border-accent animate-ping"
            style={{ animationDuration: '0.6s' }}
          />
        )}

        {/* 输入气泡 */}
        {inputText && (
          <div className="absolute left-5 top-4 bg-surface text-fg text-[10px] px-2 py-1 rounded shadow-lg whitespace-nowrap border border-border-subtle">
            {inputText}...
          </div>
        )}

        {/* 滚动指示 */}
        {state === 'scrolling' && (
          <div className="absolute left-4 top-0">
            <div className="w-4 h-6 border border-accent rounded-full flex justify-center pt-1">
              <div className="w-1 h-1 bg-accent rounded-full animate-bounce" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
