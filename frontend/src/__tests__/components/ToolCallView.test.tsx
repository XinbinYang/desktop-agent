import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ToolCallView } from '../../components/ToolCallView'
import type { ToolCall, WorkerEvent } from '../../types'

describe('ToolCallView', () => {
  afterEach(() => {
    delete (window as any).electronAPI
  })

  it('renders tool call name', () => {
    const toolCall: ToolCall = {
      name: 'file_read',
      args: { path: 'test.txt' },
      result: 'file contents here',
      timestamp: Date.now(),
    }
    render(<ToolCallView name={toolCall.name} args={toolCall.args} result={toolCall.result} status="success" />)
    expect(screen.getByText('file_read')).toBeInTheDocument()
  })

  it('shows error styling for error status', () => {
    const toolCall: ToolCall = {
      name: 'dangerous_op',
      args: {},
      result: '[ERROR] Something failed',
      timestamp: Date.now(),
    }
    const { container } = render(
      <ToolCallView name={toolCall.name} args={toolCall.args} result={toolCall.result} status="error" />,
    )
    expect(container.querySelector('button .text-danger')).toBeTruthy()
  })

  it('expands to show args and result on click', () => {
    const toolCall: ToolCall = {
      name: 'file_read',
      args: { path: 'test.txt' },
      result: 'file contents here',
      timestamp: Date.now(),
    }
    render(<ToolCallView name={toolCall.name} args={toolCall.args} result={toolCall.result} status="success" />)
    fireEvent.click(screen.getByLabelText('Expand tool call details'))
    expect(screen.getByText(/"path":\s*"test.txt"/)).toBeInTheDocument()
    expect(screen.getByText('file contents here')).toBeInTheDocument()
  })

  it('does not surface runId or toolCallId in header-only layout', () => {
    const toolCall: ToolCall = {
      name: 'file_read',
      args: {},
      result: 'ok',
      timestamp: Date.now(),
      runId: 'run-123',
      toolCallId: 'call-456',
    }
    render(<ToolCallView name={toolCall.name} args={toolCall.args} result={toolCall.result} status="success" />)
    fireEvent.click(screen.getByLabelText('Expand tool call details'))
    expect(screen.queryByText(/run-123/)).not.toBeInTheDocument()
    expect(screen.queryByText(/call-456/)).not.toBeInTheDocument()
  })

  it('renders WorkerCard for dispatch_worker tool calls', () => {
    const toolCall = {
      name: 'dispatch_worker',
      args: { task: 'Write tests', profile: 'code' },
      result: 'Worker completed',
      timestamp: Date.now(),
      workerEvents: [
        { workerId: 'w1', type: 'worker_start', status: 'running', task: 'Write tests' },
        { workerId: 'w1', type: 'worker_content', text: 'Writing tests...' },
        {
          workerId: 'w1',
          type: 'worker_tool_call',
          toolName: 'file_write',
          toolResult: 'File written',
        },
        {
          workerId: 'w1',
          type: 'worker_done',
          status: 'completed',
          result: 'All done',
          iterations: 3,
          durationMs: 5000,
        },
      ] as WorkerEvent[],
    }
    render(
      <ToolCallView
        name={toolCall.name}
        args={toolCall.args}
        result={toolCall.result}
        status="success"
        workerEvents={toolCall.workerEvents}
      />,
    )
    fireEvent.click(screen.getByLabelText('Expand tool call details'))
    expect(screen.getByText(/Agent: Write tests/)).toBeInTheDocument()
    fireEvent.click(screen.getByText(/Agent: Write tests/).closest('button')!)
    expect(screen.getByText('file_write')).toBeInTheDocument()
    expect(screen.getByText('All done')).toBeInTheDocument()
  })

  it('renders multiple workers for dispatch_parallel', () => {
    const toolCall = {
      name: 'dispatch_parallel',
      args: { tasks: [{ task: 'A' }, { task: 'B' }] },
      result: '2 succeeded',
      timestamp: Date.now(),
      workerEvents: [
        { workerId: 'w1', type: 'worker_done', status: 'completed', result: 'Done A' },
        { workerId: 'w2', type: 'worker_done', status: 'completed', result: 'Done B' },
      ] as WorkerEvent[],
    }
    render(
      <ToolCallView
        name={toolCall.name}
        args={toolCall.args}
        result={toolCall.result}
        status="success"
        workerEvents={toolCall.workerEvents}
      />,
    )
    expect(screen.getByText('2 agents')).toBeInTheDocument()
  })

  it('shows failed worker result when expanded', () => {
    const toolCall = {
      name: 'dispatch_worker',
      args: { task: 'Bad task', profile: 'code' },
      result: 'Worker failed',
      timestamp: Date.now(),
      workerEvents: [{ workerId: 'w1', type: 'worker_done', status: 'failed', result: 'Error occurred' }] as WorkerEvent[],
    }
    render(
      <ToolCallView
        name={toolCall.name}
        args={toolCall.args}
        result={toolCall.result}
        status="error"
        workerEvents={toolCall.workerEvents}
      />,
    )
    fireEvent.click(screen.getByLabelText('Expand tool call details'))
    fireEvent.click(screen.getByText(/Agent: w1/).closest('button')!)
    expect(screen.getByText('Error occurred')).toBeInTheDocument()
  })

  it('renders a compact event-row and truncates details until expanded', () => {
    render(
      <ToolCallView
        name="file_read"
        args={{ path: 'src/App.tsx' }}
        result="file contents here"
        status="success"
        variant="event-row"
      />,
    )

    expect(screen.getByTestId('tool-event-row')).toBeInTheDocument()
    expect(screen.getByText('Read')).toBeInTheDocument()
    expect(screen.getByText('src/App.tsx')).toBeInTheDocument()
    expect(screen.queryByText('file contents here')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Expand tool call details'))
    expect(screen.getByText('file contents here')).toBeInTheDocument()
  })

  it('reveals the path extracted from a successful file tool result', async () => {
    const revealPath = vi.fn(() => Promise.resolve(null))
    ;(window as any).electronAPI = { revealPath }
    render(
      <ToolCallView
        name="file_write"
        args={{ path: 'AGENTS/personal/audit.md' }}
        result={'File written: C:\\runtime\\backend\\AGENTS\\personal\\WORKSPACE\\audit.md'}
        status="success"
        variant="event-row"
      />,
    )

    fireEvent.click(screen.getByLabelText(/Show in folder:/))

    await waitFor(() => {
      expect(revealPath).toHaveBeenCalledWith('C:\\runtime\\backend\\AGENTS\\personal\\WORKSPACE\\audit.md')
    })
  })

  it('renders compact worker agents inline instead of hiding them behind Activity', () => {
    render(
      <ToolCallView
        name="dispatch_parallel"
        args={{ tasks: [{ task: 'Explore plan flow' }, { task: 'Check frontend build button' }] }}
        result="2 succeeded"
        status="success"
        variant="event-row"
        workerEvents={[
          { workerId: 'w1', type: 'worker_start', status: 'running', task: 'Explore plan flow' },
          { workerId: 'w1', type: 'worker_done', status: 'completed', result: 'Found the plan flow.', durationMs: 1200 },
          { workerId: 'w2', type: 'worker_start', status: 'running', task: 'Check frontend build button' },
          { workerId: 'w2', type: 'worker_done', status: 'completed', result: 'BUILD button is in ChatPanel.', durationMs: 900 },
        ] as WorkerEvent[]}
      />,
    )

    expect(screen.getByText('Agent')).toBeInTheDocument()
    expect(screen.getByText('2 agents')).toBeInTheDocument()
    expect(screen.getAllByText('Agent:').length).toBe(2)
    expect(screen.getAllByText('Explore plan flow').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Found the plan flow.')).toBeInTheDocument()
    expect(screen.queryByText('2 succeeded')).not.toBeInTheDocument()
    expect(screen.queryByText(/Open Activity/)).not.toBeInTheDocument()
  })

  it('auto-expands compact worker details when streamed worker events arrive later', () => {
    const { rerender } = render(
      <ToolCallView
        name="dispatch_parallel"
        args={{ tasks: [{ task: 'Explore later' }] }}
        status="running"
        variant="event-row"
      />,
    )

    expect(screen.queryByText('Agent:')).not.toBeInTheDocument()

    rerender(
      <ToolCallView
        name="dispatch_parallel"
        args={{ tasks: [{ task: 'Explore later' }] }}
        status="running"
        variant="event-row"
        workerEvents={[
          { workerId: 'w1', type: 'worker_start', status: 'running', task: 'Explore later' },
        ] as WorkerEvent[]}
      />,
    )

    expect(screen.getByText('Agent:')).toBeInTheDocument()
    expect(screen.getAllByText('Explore later').length).toBeGreaterThanOrEqual(1)
  })
})
