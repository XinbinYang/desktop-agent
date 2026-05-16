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
    // Provider names appear in both cards and dropdowns
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

    expect(await screen.findByText('sk-...BwOW')).toBeInTheDocument();
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

    expect(await screen.findByText('2 个模型')).toBeInTheDocument();
    expect(screen.getByText('1 个模型')).toBeInTheDocument();
  });

  it('default provider has "默认" badge', async () => {
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

    expect(await screen.findByText('默认')).toBeInTheDocument();
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
    // "openai" appears in multiple places (dropdown + card)
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
});
