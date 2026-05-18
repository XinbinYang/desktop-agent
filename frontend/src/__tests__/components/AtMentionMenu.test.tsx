import React, { useRef } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AtMentionMenu } from '../../components/AtMentionMenu';

interface HarnessProps {
  onSelect?: (item: { id: string; label: string; detail: string; category: string }) => void;
  query?: string;
  projectOpen?: boolean;
}

function Harness({ onSelect = vi.fn(), query = '@cod', projectOpen = false }: HarnessProps) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  return (
    <div>
      <textarea ref={inputRef} />
      <AtMentionMenu
        query={query}
        onSelect={onSelect}
        onClose={vi.fn()}
        inputRef={inputRef}
        projectOpen={projectOpen}
        fileTree={[]}
      />
    </div>
  );
}

describe('AtMentionMenu', () => {
  it('shows Coding Agent as an always-available @mention', async () => {
    render(<Harness />);

    expect(await screen.findByText('Coding Agent')).toBeInTheDocument();
    expect(screen.getByText('Delegate this message to the engineering specialist')).toBeInTheDocument();
  });

  it('selects the structured @coding agent mention id', async () => {
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);

    fireEvent.click(await screen.findByText('Coding Agent'));

    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({
      id: 'coding agent',
      category: 'agent',
    }));
  });
});
