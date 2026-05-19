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
          <p>Heartbeat runs automatically after each session ends:</p>
          <ul className="list-disc list-inside space-y-0.5 ml-1">
            <li>Writes daily diary entries</li>
            <li>Scans for pending todos</li>
            <li>Updates mood based on conversation sentiment</li>
            <li>Checks if DREAM should be triggered</li>
            <li>Cleans expired memories (90+ days)</li>
          </ul>
          <p className="mt-2 text-[10px]">DREAM triggers when: diary {'>'} 5KB or {'≥'} 5 sessions since last consolidation.</p>
          <p className="text-[10px]">SELF-EVOLUTION triggers when: {'≥'} 15 tasks complete or {'≥'} 5 user feedback items.</p>
        </div>
      </div>
    </div>
  );
};
