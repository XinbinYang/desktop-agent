import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PersonalWorkspacePanel } from '../../components/PersonalWorkspace/PersonalWorkspacePanel';
import { MemoryManager } from '../../components/PersonalWorkspace/MemoryManager';
import { EvolutionPanel } from '../../components/PersonalWorkspace/EvolutionPanel';

function mockFetchResponse(data: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: async () => data,
  } as Response);
}

const memoryItem = {
  id: 'mem-1',
  memory_type: 'semantic',
  content: '用户希望认知系统自动维护，普通用户只负责查看和纠错。',
  summary: '认知系统应自动维护',
  source: 'dream',
  source_ref: 'DREAM:2026-05-19',
  scope: 'personal',
  tier: 'hot',
  confidence: 0.95,
  created_by: 'dream',
  created_at: 1779200000,
  updated_at: 1779200300,
  last_verified_at: 1779200300,
  metadata: {},
  score: 0.8,
};

afterEach(() => {
  vi.restoreAllMocks();
});

function setupPersonalFetch() {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const textUrl = String(url);

    if (textUrl.endsWith('/api/agents/personal/memory/status')) {
      return mockFetchResponse({
        status: 'ok',
        total_items: 1,
        counts_by_type: { semantic: 1 },
        counts_by_tier: { hot: 1 },
        pending_candidates: 0,
        vector_available: true,
      });
    }

    if (textUrl.endsWith('/api/agents/personal/memory/search')) {
      return mockFetchResponse({ items: [memoryItem], count: 1, query: '' });
    }

    if (textUrl.endsWith('/api/agents/personal/files/MEMORY.md')) {
      return mockFetchResponse({ filename: 'MEMORY.md', content: '# MEMORY' });
    }

    if (textUrl.endsWith('/api/agents/personal/diaries')) {
      return mockFetchResponse({ diaries: [] });
    }

    if (textUrl.includes('/api/agents/personal/memory/items/') && init?.method === 'DELETE') {
      return mockFetchResponse({ status: 'ok', deleted: 'mem-1' });
    }

    if (textUrl.includes('/api/agents/personal/memory/items/') && init?.method === 'PATCH') {
      return mockFetchResponse({ item: memoryItem });
    }

    if (textUrl.endsWith('/api/agents/personal/memory/rebuild')) {
      return mockFetchResponse({ indexed: 1 });
    }

    if (textUrl.endsWith('/api/agents/personal/dream/trigger')) {
      return mockFetchResponse({ dream_id: 'dream-1' });
    }

    if (textUrl.endsWith('/api/agents/personal/skills')) {
      return mockFetchResponse({ skills: [] });
    }

    if (textUrl.endsWith('/api/agents/personal/archive')) {
      return mockFetchResponse({ archives: [] });
    }

    if (textUrl.endsWith('/api/agents/personal/evolve/trigger')) {
      return mockFetchResponse({ skills_crystallized: [], learnings_promoted: [] });
    }

    if (textUrl.includes('/api/agents/personal/files/')) {
      return mockFetchResponse({ filename: 'SOUL.md', content: '# SOUL' });
    }

    return mockFetchResponse({});
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

describe('PersonalWorkspacePanel', () => {
  beforeEach(() => {
    setupPersonalFetch();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.spyOn(window, 'alert').mockImplementation(() => undefined);
  });

  it('renders user-facing cognitive system tabs', () => {
    render(<PersonalWorkspacePanel />);

    expect(screen.getByText('身份与偏好')).toBeInTheDocument();
    expect(screen.getByText('记忆')).toBeInTheDocument();
    expect(screen.getByText('学习记录')).toBeInTheDocument();
    expect(screen.getByText('自动维护')).toBeInTheDocument();
    expect(screen.getByText('记忆整理')).toBeInTheDocument();
    expect(screen.getByText('能力进化')).toBeInTheDocument();
  });
});

describe('MemoryManager', () => {
  beforeEach(() => {
    setupPersonalFetch();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  it('keeps maintenance controls out of the default memory view', async () => {
    render(<MemoryManager />);

    expect(await screen.findByText('认知系统应自动维护')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('查找 Agent 记住的内容')).toBeInTheDocument();
    expect(screen.getByTitle('Delete memory')).toBeInTheDocument();
    expect(screen.queryByTitle('Rebuild index')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Trigger DREAM')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Edit memory type')).not.toBeInTheDocument();
    expect(screen.queryByText('Confidence')).not.toBeInTheDocument();
    expect(screen.queryByText('Save')).not.toBeInTheDocument();
  });

  it('reveals memory maintenance controls only in advanced mode', async () => {
    render(<MemoryManager />);

    expect(await screen.findByText('认知系统应自动维护')).toBeInTheDocument();
    fireEvent.click(screen.getByText('高级维护'));

    expect(screen.getByTitle('Rebuild index')).toBeInTheDocument();
    expect(screen.getByTitle('Trigger DREAM')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit memory type')).toBeInTheDocument();
    expect(screen.getByLabelText('Edit memory tier')).toBeInTheDocument();
    expect(screen.getByText('Confidence')).toBeInTheDocument();
    expect(screen.getByText('Save')).toBeInTheDocument();
  });

  it('keeps deletion available with confirmation', async () => {
    const fetchMock = setupPersonalFetch();
    render(<MemoryManager />);

    fireEvent.click(await screen.findByTitle('Delete memory'));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalledWith('Delete this memory item from active recall?');
      expect(fetchMock.mock.calls.some(([url, init]) => (
        String(url).includes('/api/agents/personal/memory/items/mem-1') && init?.method === 'DELETE'
      ))).toBe(true);
    });
  });
});

describe('EvolutionPanel', () => {
  beforeEach(() => {
    setupPersonalFetch();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.spyOn(window, 'alert').mockImplementation(() => undefined);
  });

  it('moves manual evolution behind advanced maintenance and confirms before running', async () => {
    const fetchMock = setupPersonalFetch();
    render(<EvolutionPanel />);

    expect(await screen.findByText('Self-Evolution')).toBeInTheDocument();
    expect(screen.queryByText('立即进化')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('高级维护'));
    fireEvent.click(screen.getByText('立即进化'));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalledWith(
        '能力进化会创建快照，并可能沉淀长期规则或生成技能草稿。确认现在手动运行吗？'
      );
      expect(fetchMock.mock.calls.some(([url, init]) => (
        String(url).endsWith('/api/agents/personal/evolve/trigger') && init?.method === 'POST'
      ))).toBe(true);
    });
  });
});
