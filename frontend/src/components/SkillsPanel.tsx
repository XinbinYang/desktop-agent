import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Archive, CheckCircle2, ChevronDown, ChevronRight, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { API_BASE } from '../config';
import type { AgentType, SkillCatalogItem, SkillCatalogResponse, SkillDraftItem, SkillPreferences, SkillPreset } from '../types';
import { AGENT_LABEL } from '../lib/agentProfiles';
import { cn } from './ui/cn';

interface SkillsPanelProps {
  activeAgent: AgentType;
}

interface SkillCategory {
  id: string;
  label: string;
  skills: SkillCatalogItem[];
}

const CATEGORY_ORDER = [
  'core',
  'explore-plan',
  'build-debug',
  'quality-review',
  'multi-agent',
  'workspace-release',
  'writing',
  'user',
  'personal',
  'other',
];

const CATEGORY_LABELS: Record<string, string> = {
  core: 'Core',
  'explore-plan': 'Explore & Plan',
  'build-debug': 'Build & Debug',
  'quality-review': 'Quality & Review',
  'multi-agent': 'Multi-Agent',
  'workspace-release': 'Workspace & Release',
  writing: 'Writing',
  user: 'User Skills',
  personal: 'Personal',
  other: 'Other',
};

const SKILL_CATEGORY_BY_ID: Record<string, string> = {
  'using-superpowers': 'core',
  'project-familiarization': 'explore-plan',
  brainstorming: 'explore-plan',
  'writing-plans': 'explore-plan',
  'executing-plans': 'explore-plan',
  'systematic-debugging': 'build-debug',
  'test-driven-development': 'quality-review',
  'verification-before-completion': 'quality-review',
  'requesting-code-review': 'quality-review',
  'receiving-code-review': 'quality-review',
  'dispatching-parallel-agents': 'multi-agent',
  'subagent-driven-development': 'multi-agent',
  'using-git-worktrees': 'workspace-release',
  'finishing-a-development-branch': 'workspace-release',
  'output-formatting': 'writing',
  'writing-skills': 'writing',
};

const emptyPreferences = (): SkillPreferences => ({ personal: {}, coding: {} });

function normalizePreferences(value?: Partial<SkillPreferences>): SkillPreferences {
  return {
    personal: { ...(value?.personal || {}) },
    coding: { ...(value?.coding || {}) },
  };
}

function isEnabled(skill: SkillCatalogItem, preferences: SkillPreferences, agent: AgentType): boolean {
  return preferences[agent]?.[skill.id] ?? skill.enabledByAgent?.[agent] ?? false;
}

function getCategoryId(skill: SkillCatalogItem): string {
  if (skill.source === 'user') return 'user';
  if (skill.source === 'personal') return 'personal';
  return SKILL_CATEGORY_BY_ID[skill.id] || skill.category || 'other';
}

function getCategoryLabel(categoryId: string): string {
  return CATEGORY_LABELS[categoryId] || categoryId.replace(/[-_]/g, ' ');
}

function expandedStorageKey(agent: AgentType): string {
  return `desktop-agent-skills-expanded:${agent}`;
}

function loadExpandedCategories(agent: AgentType): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(expandedStorageKey(agent));
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function saveExpandedCategories(agent: AgentType, value: Record<string, boolean>): void {
  try {
    localStorage.setItem(expandedStorageKey(agent), JSON.stringify(value));
  } catch {
    // Collapse state is a convenience preference only.
  }
}

function Badge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'accent' | 'success' | 'neutral' }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] leading-none',
        tone === 'accent' && 'border-accent/30 bg-accent/10 text-accent',
        tone === 'success' && 'border-success/30 bg-success/10 text-success',
        tone === 'neutral' && 'border-border bg-surface-alt text-fg-muted'
      )}
    >
      {children}
    </span>
  );
}

function CategoryCheckbox({
  checked,
  indeterminate,
  disabled,
  label,
  onChange,
}: {
  checked: boolean;
  indeterminate: boolean;
  disabled: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={(event) => onChange(event.target.checked)}
      className="h-3.5 w-3.5 rounded border-border bg-surface accent-accent"
      aria-label={label}
    />
  );
}

export const SkillsPanel: React.FC<SkillsPanelProps> = ({ activeAgent }) => {
  const [skills, setSkills] = useState<SkillCatalogItem[]>([]);
  const [drafts, setDrafts] = useState<SkillDraftItem[]>([]);
  const [presets, setPresets] = useState<SkillPreset[]>([]);
  const [preferences, setPreferences] = useState<SkillPreferences>(emptyPreferences);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [expandedCategories, setExpandedCategories] = useState<Record<string, boolean>>(() => loadExpandedCategories(activeAgent));

  const loadCatalog = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [response, draftsResponse] = await Promise.all([
        fetch(`${API_BASE}/api/skills`, { signal }),
        fetch(`${API_BASE}/api/skills/drafts`, { signal }),
      ]);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = (await response.json()) as SkillCatalogResponse;
      setSkills(data.skills || []);
      setPresets(data.presets || []);
      setPreferences(normalizePreferences(data.preferences));
      if (draftsResponse.ok) {
        const draftsData = (await draftsResponse.json()) as { drafts?: SkillDraftItem[] };
        setDrafts(draftsData.drafts || []);
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError('Failed to load skills');
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadCatalog(controller.signal);
    return () => controller.abort();
  }, [loadCatalog]);

  useEffect(() => {
    setExpandedCategories(loadExpandedCategories(activeAgent));
  }, [activeAgent]);

  const categories = useMemo<SkillCategory[]>(() => {
    const grouped = new Map<string, SkillCatalogItem[]>();
    for (const skill of skills) {
      const categoryId = getCategoryId(skill);
      grouped.set(categoryId, [...(grouped.get(categoryId) || []), skill]);
    }

    return Array.from(grouped.entries())
      .sort(([a], [b]) => {
        const aIndex = CATEGORY_ORDER.indexOf(a);
        const bIndex = CATEGORY_ORDER.indexOf(b);
        return (aIndex === -1 ? 999 : aIndex) - (bIndex === -1 ? 999 : bIndex);
      })
      .map(([id, items]) => ({
        id,
        label: getCategoryLabel(id),
        skills: items.sort((a, b) => {
          const aRecommended = a.recommendedFor.includes(activeAgent) ? 0 : 1;
          const bRecommended = b.recommendedFor.includes(activeAgent) ? 0 : 1;
          return aRecommended - bRecommended || a.name.localeCompare(b.name);
        }),
      }));
  }, [activeAgent, skills]);

  const activePresets = useMemo(
    () => presets.filter((preset) => (preset.agentTypes || []).includes(activeAgent)),
    [activeAgent, presets],
  );

  const savePreferences = async (next: SkillPreferences, previous: SkillPreferences, pending: string) => {
    setPreferences(next);
    setPendingKey(pending);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/skills/preferences`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = (await response.json()) as SkillCatalogResponse;
      setSkills(data.skills || []);
      setPresets(data.presets || []);
      setPreferences(normalizePreferences(data.preferences));
    } catch {
      setPreferences(previous);
      setError('Skill preference was not saved');
    } finally {
      setPendingKey(null);
    }
  };

  const validateDraft = async (draft: SkillDraftItem) => {
    setPendingKey(`draft:${draft.draft_id}:validate`);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/skills/drafts/${encodeURIComponent(draft.draft_id)}/validate`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await loadCatalog();
    } catch {
      setError('Skill draft validation failed');
    } finally {
      setPendingKey(null);
    }
  };

  const publishDraft = async (draft: SkillDraftItem) => {
    setPendingKey(`draft:${draft.draft_id}:publish`);
    setError(null);
    try {
      const enableFor = (draft.scopes || []).includes(activeAgent) ? [activeAgent] : ['personal'];
      const response = await fetch(`${API_BASE}/api/skills/drafts/${encodeURIComponent(draft.draft_id)}/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable_for: enableFor, allow_risky: false }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = (await response.json()) as SkillCatalogResponse;
      setSkills(data.skills || []);
      setPresets(data.presets || []);
      setPreferences(normalizePreferences(data.preferences));
      await loadCatalog();
    } catch {
      setError('Skill draft was not published');
    } finally {
      setPendingKey(null);
    }
  };

  const archiveUserSkill = async (skill: SkillCatalogItem) => {
    setPendingKey(`archive:${skill.id}`);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/skills/${encodeURIComponent(skill.id)}/archive`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await loadCatalog();
    } catch {
      setError('Skill was not archived');
    } finally {
      setPendingKey(null);
    }
  };

  const updatePreference = (skill: SkillCatalogItem, nextEnabled: boolean) => {
    const previous = preferences;
    const next = normalizePreferences(previous);
    next[activeAgent][skill.id] = nextEnabled;
    void savePreferences(next, previous, skill.id);
  };

  const updateCategory = (category: SkillCategory, nextEnabled: boolean) => {
    const previous = preferences;
    const next = normalizePreferences(previous);
    for (const skill of category.skills) {
      next[activeAgent][skill.id] = nextEnabled;
    }
    void savePreferences(next, previous, `category:${category.id}`);
  };

  const applyPreset = (preset: SkillPreset) => {
    const previous = preferences;
    const next = normalizePreferences(previous);
    for (const skillId of preset.skillIds) {
      next[activeAgent][skillId] = true;
    }
    void savePreferences(next, previous, `preset:${preset.id}`);
  };

  const toggleCategoryExpanded = (categoryId: string) => {
    setExpandedCategories((previous) => {
      const next = {
        ...previous,
        [categoryId]: !(previous[categoryId] ?? false),
      };
      saveExpandedCategories(activeAgent, next);
      return next;
    });
  };

  const setAllCategoriesExpanded = (expanded: boolean) => {
    const next = Object.fromEntries(categories.map((category) => [category.id, expanded]));
    saveExpandedCategories(activeAgent, next);
    setExpandedCategories(next);
  };

  const renderSkill = (skill: SkillCatalogItem, categoryPending: boolean) => {
    const enabled = isEnabled(skill, preferences, activeAgent);
    const pending = pendingKey === skill.id || categoryPending;
    const archivePending = pendingKey === `archive:${skill.id}`;
    const sourceLabel = skill.source === 'personal'
      ? 'Personal'
      : skill.source === 'superpowers'
        ? 'Local'
        : skill.source === 'user'
          ? 'User'
          : skill.source;

    return (
      <div
        key={skill.id}
        className={cn(
          'flex items-center gap-1.5 rounded border border-border bg-surface px-2 py-1.5 transition-colors',
          enabled ? 'border-accent/25 bg-accent/5' : 'hover:bg-surface-hover'
        )}
        title={skill.description || skill.name}
      >
        <label className="flex min-w-0 flex-1 items-center gap-2">
          <span className="relative flex h-4 w-4 items-center justify-center">
            <input
              type="checkbox"
              checked={enabled}
              disabled={pending || archivePending}
              onChange={(event) => updatePreference(skill, event.target.checked)}
              className="h-3.5 w-3.5 rounded border-border bg-surface accent-accent"
              aria-label={`${enabled ? 'Disable' : 'Enable'} ${skill.name} for ${AGENT_LABEL[activeAgent]}`}
            />
            {pending && <Loader2 className="absolute h-3 w-3 animate-spin text-accent" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium text-fg">{skill.name}</span>
            <span className="mt-1 flex flex-wrap gap-1">
              <Badge tone={enabled ? 'success' : 'neutral'}>{enabled ? 'Auto' : 'Off'}</Badge>
              {skill.recommendedFor.includes(activeAgent) && <Badge tone="accent">Rec</Badge>}
              <Badge>{sourceLabel}</Badge>
              {skill.version && <Badge>{skill.version}</Badge>}
            </span>
          </span>
        </label>
        {skill.source === 'user' && (
          <button
            type="button"
            disabled={archivePending}
            onClick={() => archiveUserSkill(skill)}
            className="shrink-0 rounded p-1 text-fg-muted hover:bg-surface-hover hover:text-danger disabled:opacity-60"
            title="Archive skill"
            aria-label={`Archive ${skill.name}`}
          >
            {archivePending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Archive className="h-3 w-3" />}
          </button>
        )}
      </div>
    );
  };

  const renderCategory = (category: SkillCategory) => {
    const enabledCount = category.skills.filter((skill) => isEnabled(skill, preferences, activeAgent)).length;
    const allEnabled = enabledCount === category.skills.length;
    const noneEnabled = enabledCount === 0;
    const categoryPending = pendingKey === `category:${category.id}`;
    const expanded = expandedCategories[category.id] ?? false;

    return (
      <div key={category.id} className="rounded border border-border bg-surface-alt">
        <div className={cn('flex items-center gap-2 px-2 py-2', expanded && 'border-b border-border')}>
          <CategoryCheckbox
            checked={allEnabled}
            indeterminate={!allEnabled && !noneEnabled}
            disabled={categoryPending}
            label={`${allEnabled ? 'Disable' : 'Enable'} all ${category.label} for ${AGENT_LABEL[activeAgent]}`}
            onChange={(checked) => updateCategory(category, checked)}
          />
          <button
            type="button"
            onClick={() => toggleCategoryExpanded(category.id)}
            className="min-w-0 flex flex-1 items-center gap-1.5 text-left"
            aria-expanded={expanded}
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${category.label}`}
          >
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-fg-muted" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-fg-muted" />
            )}
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium text-fg">{category.label}</span>
              <span className="text-[10px] text-fg-muted">{enabledCount}/{category.skills.length}</span>
            </span>
          </button>
          {categoryPending && <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />}
        </div>
        {expanded && (
          <div className="space-y-1 p-1.5">
            {category.skills.map((skill) => renderSkill(skill, categoryPending))}
          </div>
        )}
      </div>
    );
  };

  const renderDraft = (draft: SkillDraftItem) => {
    const validation = draft.validation || {};
    const issueCount = (validation.issues || []).length;
    const riskCount = (validation.risks || []).length;
    const warningCount = (validation.warnings || []).length;
    const validating = pendingKey === `draft:${draft.draft_id}:validate`;
    const publishing = pendingKey === `draft:${draft.draft_id}:publish`;
    const canPublish = validation.passed === true;

    return (
      <div key={draft.draft_id} className="rounded border border-border bg-surface px-2 py-1.5">
        <div className="flex items-start gap-2">
          <span className="mt-0.5 shrink-0 text-accent">
            {canPublish ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium text-fg">{draft.name}</span>
            <span className="mt-0.5 block line-clamp-2 text-[10px] leading-snug text-fg-muted">
              {draft.description}
            </span>
            <span className="mt-1 flex flex-wrap gap-1">
              <Badge tone={canPublish ? 'success' : 'neutral'}>{canPublish ? 'Validated' : 'Draft'}</Badge>
              {issueCount > 0 && <Badge>{issueCount} errors</Badge>}
              {riskCount > 0 && <Badge>{riskCount} risks</Badge>}
              {warningCount > 0 && <Badge>{warningCount} warnings</Badge>}
            </span>
          </span>
        </div>
        <div className="mt-2 flex items-center gap-1">
          <button
            type="button"
            disabled={!!pendingKey}
            onClick={() => validateDraft(draft)}
            className="inline-flex items-center gap-1 rounded border border-border bg-surface-alt px-2 py-1 text-[10px] text-fg-secondary hover:bg-surface-hover disabled:opacity-60"
          >
            {validating ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            Validate
          </button>
          <button
            type="button"
            disabled={!!pendingKey || !canPublish}
            onClick={() => publishDraft(draft)}
            className="inline-flex items-center gap-1 rounded border border-accent/30 bg-accent/10 px-2 py-1 text-[10px] text-accent hover:bg-accent/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {publishing ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
            Publish
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-1.5 text-xs font-medium text-fg">
          <Sparkles className="h-3.5 w-3.5 text-accent" />
          Skills
        </div>
        <div className="mt-1 text-[10px] leading-snug text-fg-muted">
          {AGENT_LABEL[activeAgent]} capability set
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-1.5 rounded border border-danger/30 bg-danger/10 px-2 py-1.5 text-[10px] text-danger">
          <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 px-2 py-3 text-xs text-fg-muted">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading skills
        </div>
      ) : skills.length === 0 && drafts.length === 0 ? (
        <div className="rounded border border-border bg-surface-alt px-2 py-3 text-center text-xs text-fg-muted">
          No local skills found.
        </div>
      ) : (
        <>
          {drafts.length > 0 && (
            <div className="space-y-1 rounded border border-border bg-surface-alt p-1.5">
              <div className="px-1 text-[10px] font-medium text-fg-muted">Drafts awaiting review</div>
              <div className="space-y-1">
                {drafts.map(renderDraft)}
              </div>
            </div>
          )}
          {activePresets.length > 0 && (
            <div className="space-y-1 rounded border border-border bg-surface-alt p-1.5">
              <div className="px-1 text-[10px] font-medium text-fg-muted">Task presets</div>
              <div className="space-y-1">
                {activePresets.map((preset) => {
                  const pending = pendingKey === `preset:${preset.id}`;
                  return (
                    <button
                      key={preset.id}
                      type="button"
                      disabled={!!pendingKey}
                      onClick={() => applyPreset(preset)}
                      className="flex w-full items-start gap-2 rounded border border-border bg-surface px-2 py-1.5 text-left hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-70"
                      title={preset.description}
                      aria-label={`Apply ${preset.name} preset`}
                    >
                      {pending ? (
                        <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
                      ) : (
                        <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium text-fg">{preset.name}</span>
                        <span className="mt-0.5 block line-clamp-2 text-[10px] leading-snug text-fg-muted">
                          {preset.description}
                        </span>
                      </span>
                      <Badge tone="accent">{preset.skillIds.length}</Badge>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setAllCategoriesExpanded(true)}
              className="rounded border border-border bg-surface px-2 py-1 text-[10px] text-fg-secondary hover:bg-surface-hover"
            >
              Expand all
            </button>
            <button
              type="button"
              onClick={() => setAllCategoriesExpanded(false)}
              className="rounded border border-border bg-surface px-2 py-1 text-[10px] text-fg-secondary hover:bg-surface-hover"
            >
              Collapse all
            </button>
          </div>
          <div className="space-y-2">
            {categories.map(renderCategory)}
          </div>
        </>
      )}
    </div>
  );
};
