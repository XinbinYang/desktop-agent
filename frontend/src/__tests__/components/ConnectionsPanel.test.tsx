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
      config: {
        bot_token: { configured: true, masked: 'disc...1234' },
        target_agent: 'personal',
        tool_visibility: 'silent',
        notifications_enabled: false,
        notification_channel_id: '123',
      },
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
          tool_visibility: {
            type: 'string',
            label: 'Tool Visibility',
            enum: ['silent', 'debug'],
            enumLabels: {
              silent: 'Silent (final replies only)',
              debug: 'Debug (show tool cards)',
            },
            default: 'silent',
          },
          notifications_enabled: {
            type: 'boolean',
            label: 'Enable Notifications',
            default: false,
          },
          notification_channel_id: {
            type: 'string',
            label: 'Notification Channel ID',
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
      if (String(url).endsWith('/test-message') && init?.method === 'POST') {
        return mockFetchResponse({ status: 'sent' });
      }
      if (String(url).includes('/api/connectors') && init?.method === 'PUT') {
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
    fireEvent.click(screen.getByTitle('Configure connector'));

    const selects = container.querySelectorAll('select');
    const select = selects[0];
    expect(select).not.toBeNull();
    expect(select?.value).toBe('personal');
    expect(selects[1]?.value).toBe('silent');
    const sensitiveInput = container.querySelector('input[type="password"]') as HTMLInputElement | null;
    expect(sensitiveInput?.value).toBe('');
    expect(sensitiveInput?.placeholder).toBe('disc...1234');

    fireEvent.change(select!, { target: { value: 'coding' } });
    fireEvent.click(screen.getByTitle('Save connector config'));

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

  it('sends a connector test message from the edit form', async () => {
    const { container } = render(<ConnectionsPanel />);

    expect(await screen.findByText('Discord')).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Configure connector'));
    const channelInput = screen.getByDisplayValue('123');
    fireEvent.change(channelInput, { target: { value: '456' } });
    fireEvent.click(screen.getByText('Test message'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/connectors/discord/test-message'),
        expect.objectContaining({ method: 'POST' }),
      );
    });
    const putCallIndex = fetchMock.mock.calls.findIndex(([, init]) => init?.method === 'PUT');
    const postCallIndex = fetchMock.mock.calls.findIndex(
      ([url, init]) => String(url).endsWith('/test-message') && init?.method === 'POST',
    );
    expect(putCallIndex).toBeGreaterThanOrEqual(0);
    expect(postCallIndex).toBeGreaterThan(putCallIndex);
    const putCall = fetchMock.mock.calls[putCallIndex];
    expect(JSON.parse(String(putCall?.[1]?.body))).toMatchObject({
      config: {
        bot_token: '',
        notification_channel_id: '456',
      },
    });
    expect(container.querySelector('select')?.value).toBe('personal');
  });
});
