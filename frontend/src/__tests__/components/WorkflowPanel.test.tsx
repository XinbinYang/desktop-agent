import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WorkflowPanel } from '../../components/WorkflowPanel';

function mockFetchResponse(data: any) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  } as Response);
}

describe('WorkflowPanel', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    global.confirm = vi.fn(() => true);
  });

  it('renders empty state', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({ workflows: [] }));
    render(<WorkflowPanel />);
    expect(await screen.findByText('暂无工作流')).toBeInTheDocument();
  });

  it('renders workflow list', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({
      workflows: [
        { id: 'wf-1', name: 'Morning Routine', description: 'Daily setup', created_at: '2024-01-01', variables: [], steps: [{ step_id: 's1', tool_name: 'screenshot', args: {} }] },
        { id: 'wf-2', name: 'Data Fetch', description: '', created_at: '2024-01-02', variables: [{ name: 'url', default: 'https://example.com', description: 'Target URL' }], steps: [{ step_id: 's1', tool_name: 'browser_navigate', args: { url: '${url}' }, param_args: { url: '${url}' } }] },
      ]
    }));
    render(<WorkflowPanel />);
    expect(await screen.findByText('Morning Routine')).toBeInTheDocument();
    expect(screen.getByText('Data Fetch')).toBeInTheDocument();
    expect(screen.getAllByText('(1 步)').length).toBe(2);
  });

  it('expands workflow to show steps', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({
      workflows: [
        { id: 'wf-1', name: 'Test', description: 'Test wf', created_at: '2024-01-01', variables: [], steps: [{ step_id: 's1', tool_name: 'screenshot', args: {} }] },
      ]
    }));
    render(<WorkflowPanel />);
    await screen.findByText('Test');

    // Click on the workflow header row to expand
    fireEvent.click(screen.getByText('Test'));

    expect(await screen.findByText('步骤')).toBeInTheDocument();
    expect(screen.getByText('1. screenshot')).toBeInTheDocument();
  });

  it('runs a workflow', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse({
        workflows: [
          { id: 'wf-1', name: 'Test', description: '', created_at: '2024-01-01', variables: [], steps: [{ step_id: 's1', tool_name: 'get_screen_size', args: {} }] },
        ]
      }))
      .mockResolvedValueOnce(mockFetchResponse({
        events: [
          { type: 'step_start', progress: '1/1', tool_name: 'get_screen_size' },
          { type: 'step_end', progress: '1/1', error: '' },
          { type: 'completed' },
        ]
      }));

    render(<WorkflowPanel />);
    await screen.findByText('Test');

    const playBtn = screen.getAllByRole('button').find(b => b.querySelector('.lucide-play'));
    fireEvent.click(playBtn!);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/workflows/wf-1/run'),
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  it('deletes a workflow', async () => {
    fetchMock
      .mockResolvedValueOnce(mockFetchResponse({
        workflows: [{ id: 'wf-1', name: 'ToDelete', description: '', created_at: '2024-01-01', variables: [], steps: [] }]
      }))
      .mockResolvedValueOnce(mockFetchResponse({ status: 'deleted' }))
      .mockResolvedValueOnce(mockFetchResponse({ workflows: [] }));

    render(<WorkflowPanel />);
    await screen.findByText('ToDelete');

    const deleteBtn = screen.getAllByRole('button').find(b => b.querySelector('.lucide-trash2'));
    fireEvent.click(deleteBtn!);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/workflows/wf-1'),
        expect.objectContaining({ method: 'DELETE' })
      );
    });
  });

  it('shows variable inputs for parameterized workflow', async () => {
    fetchMock.mockResolvedValueOnce(mockFetchResponse({
      workflows: [
        { id: 'wf-1', name: 'ParamWf', description: '', created_at: '2024-01-01', variables: [{ name: 'target', default: 'default.com', description: 'Target site' }], steps: [] },
      ]
    }));
    render(<WorkflowPanel />);
    await screen.findByText('ParamWf');

    // Click on the workflow header row to expand
    fireEvent.click(screen.getByText('ParamWf'));

    expect(await screen.findByText('变量')).toBeInTheDocument();
    expect(screen.getByDisplayValue('default.com')).toBeInTheDocument();
  });
});
