import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, Activity } from 'lucide-react';
import { API_BASE } from '../../config';

interface MoodData {
  current: string;
  baseline: string;
  updated_at?: string;
  history?: Array<{ mood: string; timestamp: string }>;
}

export const HeartbeatConfig: React.FC = () => {
  const [mood, setMood] = useState<MoodData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadMood = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/mood`);
      const data = await res.json();
      setMood(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadMood(); }, [loadMood]);

  const moodColor = (m: string) => {
    switch (m) {
      case 'positive': return 'text-green-400';
      case 'negative': return 'text-red-400';
      default: return 'text-fg-muted';
    }
  };

  const moodEmoji = (m: string) => {
    switch (m) {
      case 'positive': return '\u{1F60A}';
      case 'negative': return '\u{1F614}';
      default: return '\u{1F610}';
    }
  };

  return (
    <div className="flex flex-col h-full p-4 space-y-4">
      <div className="-mx-1 rounded border border-border bg-surface-alt px-3 py-2 text-[11px] leading-relaxed text-fg-muted">
        自动维护由 Agent 在会话结束后运行。用户只需要查看状态，不需要配置或手动触发这些后台任务。
      </div>

      {/* Mood dashboard */}
      <div>
        <div className="flex items-center gap-1.5 mb-3">
          <Activity className="w-3.5 h-3.5 text-fg-muted" />
          <span className="text-xs font-medium">Mood</span>
        </div>
        {loading ? (
          <div className="text-xs text-fg-muted"><Loader2 className="w-3 h-3 animate-spin inline mr-1" />Loading...</div>
        ) : error ? (
          <div className="text-[11px] text-danger">{error}</div>
        ) : mood ? (
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-2xl">{moodEmoji(mood.current)}</span>
              <div>
                <div className={moodColor(mood.current)} style={{ fontSize: 14, fontWeight: 600, textTransform: 'capitalize' }}>
                  {mood.current}
                </div>
                <div className="text-[10px] text-fg-muted">
                  Baseline: <span className={moodColor(mood.baseline)}>{mood.baseline}</span>
                </div>
              </div>
            </div>
            {mood.history && mood.history.length > 0 && (
              <div className="flex items-end gap-0.5 h-8 mt-2">
                {mood.history.slice(-20).map((h, i) => (
                  <div
                    key={i}
                    title={`${h.mood} — ${h.timestamp?.slice(0, 16)}`}
                    className="w-2 rounded-t"
                    style={{
                      height: `${h.mood === 'positive' ? 100 : h.mood === 'negative' ? 40 : 60}%`,
                      backgroundColor: h.mood === 'positive' ? '#4ade80' : h.mood === 'negative' ? '#f87171' : '#9ca3af',
                      opacity: 0.7,
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        ) : null}
      </div>

      {/* Heartbeat info */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Activity className="w-3.5 h-3.5 text-fg-muted" />
          <span className="text-xs font-medium">HEARTBEAT</span>
        </div>
        <div className="text-[11px] text-fg-muted space-y-1">
          <p>Heartbeat 会在每次会话结束后自动运行：</p>
          <ul className="list-disc list-inside space-y-0.5 ml-1">
            <li>写入日记摘要</li>
            <li>扫描未完成事项</li>
            <li>根据对话更新状态</li>
            <li>判断是否需要触发记忆整理</li>
            <li>清理过期记忆</li>
          </ul>
          <p className="mt-2 text-[10px]">记忆整理触发条件：上次整理后日记 {'>'} 5KB，或累计 {'≥'} 5 次会话。</p>
          <p className="text-[10px]">能力进化触发条件：累计 {'≥'} 15 个任务，或 {'≥'} 5 条用户反馈。</p>
        </div>
      </div>
    </div>
  );
};
