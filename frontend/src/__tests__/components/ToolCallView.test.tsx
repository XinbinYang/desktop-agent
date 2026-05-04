import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolCallView } from '../../components/ToolCallView'
import type { ToolCall } from '../../types'

describe('ToolCallView', () => {
  it('renders tool call name', () => {
    const toolCall: ToolCall = {
      name: 'file_read',
      args: { path: 'test.txt' },
      result: 'file contents here',
      timestamp: Date.now(),
    }
    render(<ToolCallView toolCall={toolCall} />)
    expect(screen.getByText('file_read')).toBeInTheDocument()
    expect(screen.getByText('成功')).toBeInTheDocument()
  })

  it('shows error status for error results', () => {
    const toolCall: ToolCall = {
      name: 'dangerous_op',
      args: {},
      result: '[ERROR] Something failed',
      timestamp: Date.now(),
    }
    render(<ToolCallView toolCall={toolCall} />)
    expect(screen.getByText('失败')).toBeInTheDocument()
  })

  it('expands to show args and result on click', () => {
    const toolCall: ToolCall = {
      name: 'file_read',
      args: { path: 'test.txt' },
      result: 'file contents here',
      timestamp: Date.now(),
    }
    render(<ToolCallView toolCall={toolCall} />)
    fireEvent.click(screen.getByLabelText('展开工具调用详情'))
    expect(screen.getByText('参数:')).toBeInTheDocument()
    expect(screen.getByText('结果:')).toBeInTheDocument()
    expect(screen.getByText('file contents here')).toBeInTheDocument()
  })

  it('shows runId and toolCallId when present', () => {
    const toolCall: ToolCall = {
      name: 'file_read',
      args: {},
      result: 'ok',
      timestamp: Date.now(),
      runId: 'run-123',
      toolCallId: 'call-456',
    }
    render(<ToolCallView toolCall={toolCall} />)
    fireEvent.click(screen.getByLabelText('展开工具调用详情'))
    expect(screen.getByText(/run-123/)).toBeInTheDocument()
    expect(screen.getByText(/call-456/)).toBeInTheDocument()
  })

  it('renders WorkerCard for dispatch_worker tool calls', () => {
    const toolCall = {
      name: 'dispatch_worker',
      args: { task: 'Write tests', profile: 'code' },
      result: 'Worker completed',
      timestamp: Date.now(),
      workerEvents: [
        { workerId: 'w1', type: 'worker_start', status: 'running' },
        { workerId: 'w1', type: 'worker_content', text: 'Writing tests...' },
        {
          workerId: 'w1', type: 'worker_tool_call',
          toolName: 'file_write', toolResult: 'File written',
        },
        {
          workerId: 'w1', type: 'worker_done',
          status: 'completed', result: 'All done', iterations: 3, durationMs: 5000,
        },
      ],
    };
    render(<ToolCallView toolCall={toolCall} />);
    fireEvent.click(screen.getByLabelText('展开工具调用详情'));
    expect(screen.getByText('Worker: w1')).toBeInTheDocument();
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.getByText('file_write')).toBeInTheDocument();
    expect(screen.getByText('All done')).toBeInTheDocument();
  });

  it('renders multiple WorkerCards for dispatch_parallel', () => {
    const toolCall = {
      name: 'dispatch_parallel',
      args: { tasks: [{ task: 'A' }, { task: 'B' }] },
      result: '2 succeeded',
      timestamp: Date.now(),
      workerEvents: [
        { workerId: 'w1', type: 'worker_done', status: 'completed', result: 'Done A' },
        { workerId: 'w2', type: 'worker_done', status: 'completed', result: 'Done B' },
      ],
    };
    render(<ToolCallView toolCall={toolCall} />);
    expect(screen.getByText('2 worker(s)')).toBeInTheDocument();
  });

  it('shows error status for failed workers', () => {
    const toolCall = {
      name: 'dispatch_worker',
      args: { task: 'Bad task', profile: 'code' },
      result: 'Worker failed',
      timestamp: Date.now(),
      workerEvents: [
        { workerId: 'w1', type: 'worker_done', status: 'failed', result: 'Error occurred' },
      ],
    };
    render(<ToolCallView toolCall={toolCall} />);
    fireEvent.click(screen.getByLabelText('展开工具调用详情'));
    expect(screen.getByText('failed')).toBeInTheDocument();
  });
})
