import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConnectionsPanel } from '../../components/ConnectionsPanel';

const connectorResponse = {
  connectors: [
    {
      name: 'discord',
      display_name: 'Discord',
      description: 'Discord connector',
      status: 'stopped',
      status_message: '',
      enabled: false,
      uptime_seconds: 0,
      config: { bot_token: 'masked', target_agent: 'personal' },
      config_schema: {
        type: 'object',
        properties: {
          bot_token: {
            type: 'string',
            label: 'Bot Token',
            sensitive: true,
          },
          target_agent: {
            type: 'string',
            label: 'Target Agent',
            enum: ['personal', 'coding'],
            enumLabels: {
              personal: 'Personal / Main Agent',
              coding: 'Coding Agent',
            },
            default: 'personal',
          },
        },
        required: ['bot_token'],
      },
    },
  ],
};

function mockFetchResponse(data: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  }) as Promise<Response>;
}

describe('ConnectionsPanel', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (String(url).endsWith('/api/connectors') && init?.method === 'PUT') {
        return mockFetchResponse({ status: 'updated' });
      }
      if (String(url).includes('/api/connectors')) {
        return mockFetchResponse(connectorResponse);
      }
      return mockFetchResponse({});
    });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('renders target Agent as a select and saves it', async () => {
    const { container } = render(<ConnectionsPanel />);

    expect(await screen.findByText('Discord')).toBeInTheDocument();
    fireEvent.click(screen.getByText('配置凭据'));

    const select = container.querySelector('select');
    expect(select).not.toBeNull();
    expect(select?.value).toBe('personal');

    fireEvent.change(select!, { target: { value: 'coding' } });
    fireEvent.click(screen.getByText('保存'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/connectors/discord'),
        expect.objectContaining({ method: 'PUT' }),
      );
    });

    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT');
    expect(JSON.parse(String(putCall?.[1]?.body))).toMatchObject({
      config: {
        target_agent: 'coding',
      },
    });
  });
});
