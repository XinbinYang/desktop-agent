import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolCallView } from '../../components/ToolCallView'
import type { ToolCall, WorkerEvent } from '../../types'

describe('ToolCallView', () => {
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
})
