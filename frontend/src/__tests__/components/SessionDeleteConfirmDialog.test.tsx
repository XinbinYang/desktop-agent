import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { SessionDeleteConfirmDialog } from '../../components/SessionDeleteConfirmDialog';
import type { SessionHistoryItem } from '../../types';

const session: SessionHistoryItem = {
  id: 'session_coding_abc123',
  title: 'Fix failing tests',
  project_path: 'C:/repo',
  model_id: 'gpt-4o',
  role_id: 'code-expert',
  agent_type: 'coding',
  message_count: 3,
  updated_at: 1779116000,
  is_primary: false,
  is_running: false,
  active_connections: 0,
  activity_state: 'idle',
};

describe('SessionDeleteConfirmDialog', () => {
  it('uses the app dialog style and confirms deletion without native confirm', () => {
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm');

    render(
      <SessionDeleteConfirmDialog
        isOpen
        session={session}
        onClose={onClose}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('删除会话')).toBeInTheDocument();
    expect(screen.getByText('Fix failing tests')).toBeInTheDocument();
    expect(screen.getByText('C:/repo')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    expect(onConfirm).toHaveBeenCalled();
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});
