import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, FlaskConical, Archive, Sparkles } from 'lucide-react';
import { API_BASE } from '../../config';

interface SkillInfo {
  name: string;
  success_rate?: number;
  usage_count?: number;
  created_at?: string;
}

interface ArchiveInfo {
  id: string;
  timestamp: string;
  files: string[];
}

export const EvolutionPanel: React.FC = () => {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [archives, setArchives] = useState<ArchiveInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [skillsRes, archiveRes] = await Promise.all([
        fetch(`${API_BASE}/api/agents/personal/skills`),
        fetch(`${API_BASE}/api/agents/personal/archive`),
      ]);
      const skillsData = await skillsRes.json();
      const archiveData = await archiveRes.json();
      setSkills(skillsData.skills || []);
      setArchives(archiveData.archives || []);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const triggerEvolution = useCallback(async () => {
    setTriggering(true);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/evolve/trigger`, { method: 'POST' });
      const data = await res.json();
      setTriggering(false);
      load();
      const skillsCreated = data.skills_crystallized?.length || 0;
      const promoted = data.learnings_promoted?.length || 0;
      window.alert(`Evolution complete. ${skillsCreated} skills crystallized. ${promoted} learnings promoted.`);
    } catch (err) {
      setTriggering(false);
      setError(String(err));
    }
  }, [load]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-1.5">
          <FlaskConical className="w-3.5 h-3.5 text-fg-muted" />
          <span className="text-xs font-medium">Self-Evolution</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={load}
            className="p-1 rounded text-fg-muted hover:text-fg hover:bg-surface-hover"
            title="Reload"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
          <button
            type="button"
            onClick={triggerEvolution}
            disabled={triggering}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20"
          >
            {triggering ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Sparkles className="w-3 h-3" />
            )}
            Evolve Now
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-4">
        {loading ? (
          <div className="text-xs text-fg-muted"><Loader2 className="w-3 h-3 animate-spin inline mr-1" />Loading...</div>
        ) : error ? (
          <div className="text-[11px] text-danger">{error}</div>
        ) : (
          <>
            {/* Skills */}
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <Sparkles className="w-3 h-3 text-fg-muted" />
                <span className="text-[11px] font-medium">Crystallized Skills</span>
              </div>
              {skills.length === 0 ? (
                <div className="text-[10px] text-fg-muted">No skills yet. They crystallize through task completion.</div>
              ) : (
                <div className="space-y-1">
                  {skills.map((s) => (
                    <div key={s.name} className="flex items-center justify-between px-2 py-1 rounded bg-surface-alt/50 text-[11px]">
                      <span className="text-fg-muted">{s.name.replace(/_/g, ' ')}</span>
                      <span className="text-fg-muted">
                        {(s.success_rate !== undefined) ? `${(s.success_rate * 100).toFixed(0)}%` : 'N/A'}
                        {(s.usage_count !== undefined) ? ` · ${s.usage_count} uses` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Archives */}
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <Archive className="w-3 h-3 text-fg-muted" />
                <span className="text-[11px] font-medium">Version Archives</span>
              </div>
              {archives.length === 0 ? (
                <div className="text-[10px] text-fg-muted">No archives yet. Snapshots are created before each evolution.</div>
              ) : (
                <div className="space-y-1">
                  {archives.slice(0, 10).map((a) => (
                    <div key={a.id} className="px-2 py-1 rounded bg-surface-alt/50 text-[10px] flex items-center justify-between">
                      <span className="text-fg-muted">{a.id}</span>
                      <span className="text-fg-muted">{a.files.length} files</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Trigger info */}
            <div className="text-[10px] text-fg-muted">
              <p>Evolution triggers automatically after 15 completed tasks or 5 user feedback items.</p>
              <p className="mt-1">Before each evolution, a snapshot of SOUL.md, INNER.md, IDENTITY.md, AGENTS.md, and MEMORY.md is archived.</p>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
