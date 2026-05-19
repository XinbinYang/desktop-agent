import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SettingsModal } from '../../components/SettingsModal';
import { ModelInfo, SettingsResponse } from '../../types';

const mockModels: ModelInfo[] = [
  { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
  { id: 'gpt-4o-mini', name: 'GPT-4o Mini', provider: 'openai', vision: true, context: 128000 },
  { id: 'claude-sonnet', name: 'Claude Sonnet', provider: 'anthropic', vision: true, context: 200000 },
];

const mockSettingsResponse: SettingsResponse = {
  providers: {
    openai: {
      name: 'openai',
      base_url: 'https://api.openai.com/v1',
      api_key_masked: 'sk-...BwOW',
      litellm_provider: 'openai',
      models: [
        { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
        { id: 'gpt-4o-mini', name: 'GPT-4o Mini', provider: 'openai', vision: true, context: 128000 },
      ],
    },
    anthropic: {
      name: 'anthropic',
      base_url: 'https://api.anthropic.com/v1',
      api_key_masked: 'ant...KEY',
      litellm_provider: 'anthropic',
      models: [
        { id: 'claude-sonnet', name: 'Claude Sonnet', provider: 'anthropic', vision: true, context: 200000 },
      ],
    },
  },
  settings: {
    default_model: 'gpt-4o',
    default_provider: 'openai',
    max_iterations: 50,
    auto_approve: false,
    screenshot_on_step: true,
    sandbox_mode: 'sandbox',
  },
  personal_agent: { model: 'gpt-4o', thinking_intensity: 'medium' },
  coding_agent: {
    enabled: true,
    default_execution_mode: 'worktree',
    max_fix_rounds: 2,
    max_parallel_workers: 3,
    require_verification: true,
    require_review: true,
    auto_generate_repo_map: true,
    model: 'claude-sonnet',
    thinking_intensity: 'medium',
  },
  web_search: {
    provider: 'auto',
    fallback_enabled: true,
    allow_private_network: false,
    providers: {
      brave: { api_key_masked: 'brv...1234', api_key_configured: true },
      tavily: { api_key_masked: '', api_key_configured: false },
      serpapi: { api_key_masked: '', api_key_configured: false },
    },
  },
};

function mockFetchResponse(data: any) {
  const body = JSON.stringify(data);
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(body),
  });
}

describe('SettingsModal', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('does not render when closed', () => {
    const { container } = render(
      <SettingsModal
        isOpen={false}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders when open and fetches settings', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    expect(await screen.findByText('设置')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Providers'));
    const openaiElements = screen.getAllByText('openai');
    const anthropicElements = screen.getAllByText('anthropic');
    expect(openaiElements.length).toBeGreaterThanOrEqual(1);
    expect(anthropicElements.length).toBeGreaterThanOrEqual(1);
  });

  it('shows provider cards with masked API keys', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    await screen.findByText('设置');
    fireEvent.click(screen.getByText('Providers'));
    expect(await screen.findByText('sk-...BwOW')).toBeInTheDocument();
  });

  it('does not render global default model/provider controls', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    await screen.findByText('设置');
    expect(screen.queryByText('默认模型')).not.toBeInTheDocument();
    expect(screen.queryByText('默认 Provider')).not.toBeInTheDocument();
    expect(screen.queryByText(/使用默认/)).not.toBeInTheDocument();
  });

  it('shows model count badges', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    await screen.findByText('设置');
    fireEvent.click(screen.getByText('Providers'));
    expect(await screen.findByText('2 个模型')).toBeInTheDocument();
    expect(screen.getByText('1 个模型')).toBeInTheDocument();
  });

  it('shows Agent provider badges instead of a global default badge', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    await screen.findByText('设置');
    fireEvent.click(screen.getByText('Providers'));
    expect(await screen.findByText('Personal')).toBeInTheDocument();
    expect(screen.getByText('Coding')).toBeInTheDocument();
    expect(screen.queryByText('默认')).not.toBeInTheDocument();
  });

  it('closes when X button is clicked', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));
    const onClose = vi.fn();

    render(
      <SettingsModal
        isOpen={true}
        onClose={onClose}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    await screen.findByText('设置');

    const closeButtons = screen.getAllByRole('button');
    // The X close button is the first one that contains only an X icon
    const xBtn = closeButtons.find(btn => btn.querySelector('.lucide-x'));
    fireEvent.click(xBtn!);

    expect(onClose).toHaveBeenCalled();
  });

  it('opens edit mode when edit button clicked', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    await screen.findByText('设置');
    fireEvent.click(screen.getByText('Providers'));
    await screen.findByText('sk-...BwOW');
    const editButtons = screen.getAllByTitle('编辑');
    fireEvent.click(editButtons[0]);

    expect(await screen.findByText(/编辑 openai/)).toBeInTheDocument();
  });

  it('keeps provider API key blank when editing without re-entering it', async () => {
    const onSettingsChanged = vi.fn();
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse))
      .mockResolvedValueOnce(mockFetchResponse({ status: 'ok' }))
      .mockResolvedValueOnce(mockFetchResponse({ status: 'ok' }))
      .mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={onSettingsChanged}
      />
    );

    await screen.findByText('设置');
    fireEvent.click(screen.getByText('Providers'));
    await screen.findByText('sk-...BwOW');
    fireEvent.click(screen.getAllByTitle('编辑')[0]);
    await screen.findByText(/编辑 openai/);
    fireEvent.click(screen.getByText('保存 Provider'));

    await waitFor(() => expect(onSettingsChanged).toHaveBeenCalled());
    const updateCall = fetchMock.mock.calls.find(([url, init]) =>
      String(url).includes('/api/providers/openai') && init?.method === 'PUT'
    );
    expect(updateCall).toBeTruthy();
    const body = JSON.parse(updateCall![1].body as string);
    expect(body.api_key).toBe('');
    expect(body.models[0].id).toBe('gpt-4o');
  });

  it('tests provider connection from the edit form', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse))
      .mockResolvedValueOnce(mockFetchResponse({
        ok: true,
        message: '连接成功',
        model_found: true,
        model_count: 2,
      }));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    await screen.findByText('设置');
    fireEvent.click(screen.getByText('Providers'));
    await screen.findByText('sk-...BwOW');
    fireEvent.click(screen.getAllByTitle('编辑')[0]);
    await screen.findByText(/编辑 openai/);
    fireEvent.click(screen.getByTitle('Test connection'));

    expect(await screen.findByText('连接成功')).toBeInTheDocument();
    const testCall = fetchMock.mock.calls.find(([url, init]) =>
      String(url).includes('/api/providers/test') && init?.method === 'POST'
    );
    expect(testCall).toBeTruthy();
    const body = JSON.parse(testCall![1].body as string);
    expect(body.provider_name).toBe('openai');
    expect(body.api_key).toBe('');
    expect(body.model_id).toBe('gpt-4o');
  });

  it('shows error on fetch failure', async () => {
    fetchMock.mockRejectedValueOnce(new Error('Network error'));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    expect(await screen.findByText(/无法连接后端/)).toBeInTheDocument();
  });

  it('cancels from footer calls onClose', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));
    const onClose = vi.fn();

    render(
      <SettingsModal
        isOpen={true}
        onClose={onClose}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    await screen.findByText('设置');
    fireEvent.click(screen.getByText('取消'));
    expect(onClose).toHaveBeenCalled();
  });

  it('displays current model in footer', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    expect(await screen.findByText(/当前模型: GPT-4o/)).toBeInTheDocument();
  });
  it('renders web search settings and preserves existing keys on save', async () => {
    const onSettingsChanged = vi.fn();
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse))
      .mockResolvedValueOnce(mockFetchResponse({ status: 'ok', web_search: mockSettingsResponse.web_search }))
      .mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={onSettingsChanged}
      />
    );

    fireEvent.click(await screen.findByText('Web Search'));
    expect(await screen.findByText('Brave Search API Key')).toBeInTheDocument();
    expect(screen.getByDisplayValue('brv...1234')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Save Web Search'));

    await waitFor(() => expect(onSettingsChanged).toHaveBeenCalled());
    const saveCall = fetchMock.mock.calls.find(([url, init]) =>
      String(url).includes('/api/web-search/settings') && init?.method === 'PUT'
    );
    expect(saveCall).toBeTruthy();
    const body = JSON.parse(saveCall![1].body as string);
    expect(body.provider).toBe('auto');
    expect(body.brave_api_key).toBe('');
    expect(body.fallback_enabled).toBe(true);
  });

  it('tests web search settings from the form', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse(mockSettingsResponse))
      .mockResolvedValueOnce(mockFetchResponse({
        ok: true,
        message: 'Search succeeded via duckduckgo',
        provider: 'duckduckgo',
        result_count: 2,
      }));

    render(
      <SettingsModal
        isOpen={true}
        onClose={vi.fn()}
        models={mockModels}
        currentModel="gpt-4o"
        onSettingsChanged={vi.fn()}
      />
    );

    fireEvent.click(await screen.findByText('Web Search'));
    fireEvent.click(await screen.findByText('Test search'));

    expect(await screen.findByText('Search succeeded via duckduckgo')).toBeInTheDocument();
    const testCall = fetchMock.mock.calls.find(([url, init]) =>
      String(url).includes('/api/web-search/test') && init?.method === 'POST'
    );
    expect(testCall).toBeTruthy();
    const body = JSON.parse(testCall![1].body as string);
    expect(body.query).toBe('OpenAI API documentation');
    expect(body.brave_api_key).toBe('');
  });
});
