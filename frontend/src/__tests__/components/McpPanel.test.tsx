import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { McpPanel } from '../../components/McpPanel';

function mockFetchResponse(data: any) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  } as Response);
}

describe('McpPanel', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    global.confirm = vi.fn(() => true);
  });

  it('renders empty state', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({ servers: [] }));
    render(<McpPanel />);
    expect(await screen.findByText('暂无 MCP Server 配置')).toBeInTheDocument();
  });

  it('renders server list with status', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({
      servers: [
        { id: 'fs', config: { transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-filesystem'] }, connected: true, tools: [{ name: 'read_file', description: 'Read a file' }], error: null },
        { id: 'fetch', config: { transport: 'sse', url: 'http://localhost:3001/sse' }, connected: false, tools: [], error: 'Connection refused' },
      ]
    }));
    render(<McpPanel />);
    expect(await screen.findByText('fs')).toBeInTheDocument();
    expect(screen.getByText('fetch')).toBeInTheDocument();
    expect(screen.getByText('(stdio)')).toBeInTheDocument();
    expect(screen.getByText('(sse)')).toBeInTheDocument();
    expect(screen.getByText('read_file')).toBeInTheDocument();
    expect(screen.getByText('Connection refused')).toBeInTheDocument();
  });

  it('connects to a server', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse({
        servers: [{ id: 'test', config: { transport: 'stdio', command: 'echo', args: [] }, connected: false, tools: [], error: null }]
      }))
      .mockResolvedValueOnce(mockFetchResponse({ connected: true }))
      .mockResolvedValueOnce(mockFetchResponse({
        servers: [{ id: 'test', config: { transport: 'stdio', command: 'echo', args: [] }, connected: true, tools: [], error: null }]
      }));

    render(<McpPanel />);
    await screen.findByText('test');

    const connectBtn = screen.getAllByRole('button')[1]; // link/connect button
    fireEvent.click(connectBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/mcp/servers/test/connect'),
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  it('disconnects from a server', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse({
        servers: [{ id: 'test', config: { transport: 'stdio', command: 'echo', args: [] }, connected: true, tools: [], error: null }]
      }))
      .mockResolvedValueOnce(mockFetchResponse({ status: 'disconnected' }))
      .mockResolvedValueOnce(mockFetchResponse({
        servers: [{ id: 'test', config: { transport: 'stdio', command: 'echo', args: [] }, connected: false, tools: [], error: null }]
      }));

    render(<McpPanel />);
    await screen.findByText('test');

    const disconnectBtn = screen.getAllByRole('button')[1]; // unlink button
    fireEvent.click(disconnectBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/mcp/servers/test/disconnect'),
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  it('deletes a server', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse({
        servers: [{ id: 'old', config: { transport: 'stdio', command: 'echo', args: [] }, connected: false, tools: [], error: null }]
      }))
      .mockResolvedValueOnce(mockFetchResponse({ status: 'deleted' }))
      .mockResolvedValueOnce(mockFetchResponse({ servers: [] }));

    render(<McpPanel />);
    await screen.findByText('old');

    const deleteBtn = screen.getAllByRole('button')[2]; // trash button
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/mcp/servers/old'),
        expect.objectContaining({ method: 'DELETE' })
      );
    });
  });

  it('shows add server form', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({ servers: [] }));
    render(<McpPanel />);
    await screen.findByText('暂无 MCP Server 配置');

    const addBtn = screen.getByRole('button'); // plus button in header
    fireEvent.click(addBtn);

    expect(await screen.findByPlaceholderText('Server ID')).toBeInTheDocument();
    expect(screen.getByText('添加')).toBeInTheDocument();
    expect(screen.getByText('取消')).toBeInTheDocument();
  });

  it('adds a new stdio server', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse({ servers: [] }))
      .mockResolvedValueOnce(mockFetchResponse({ status: 'ok', id: 'myserver' }))
      .mockResolvedValueOnce(mockFetchResponse({
        servers: [{ id: 'myserver', config: { transport: 'stdio', command: 'npx', args: ['-y', 'mcp-server'] }, connected: false, tools: [], error: null }]
      }));

    render(<McpPanel />);
    await screen.findByText('暂无 MCP Server 配置');

    fireEvent.click(screen.getByRole('button')); // plus button
    await screen.findByPlaceholderText('Server ID');

    fireEvent.change(screen.getByPlaceholderText('Server ID'), { target: { value: 'myserver' } });
    fireEvent.change(screen.getByPlaceholderText('Command (e.g. npx)'), { target: { value: 'npx' } });
    fireEvent.change(screen.getByPlaceholderText('Args (space separated)'), { target: { value: '-y mcp-server' } });
    fireEvent.click(screen.getByText('添加'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/mcp/servers'),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('myserver'),
        })
      );
    });
  });
});
