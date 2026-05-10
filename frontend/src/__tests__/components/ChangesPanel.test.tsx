import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChangesPanel } from '../../components/ChangesPanel'

vi.mock('@monaco-editor/react', () => ({
  DiffEditor: ({ original, modified }: any) => (
    <div data-testid="diff-editor">
      <span>{original}</span>
      <span>{modified}</span>
    </div>
  ),
}))

describe('ChangesPanel', () => {
  it('renders Monaco diff for inline text edits', () => {
    render(
      <ChangesPanel
        edits={[{
          path: 'src/a.ts',
          operation: 'modify',
          old_text: 'old',
          new_text: 'new',
          unified_diff: 'diff',
          stats: { added: 1, removed: 1 },
          truncated: false,
        }]}
      />
    )
    expect(screen.getByTestId('diff-editor')).toBeInTheDocument()
    expect(screen.getByText('old')).toBeInTheDocument()
    expect(screen.getByText('new')).toBeInTheDocument()
  })

  it('opens selected edit path', () => {
    const onOpenFile = vi.fn()
    render(
      <ChangesPanel
        onOpenFile={onOpenFile}
        edits={[{
          path: 'src/a.ts',
          operation: 'modify',
          unified_diff: 'diff',
          stats: { added: 1, removed: 0 },
          truncated: true,
        }]}
      />
    )
    fireEvent.click(screen.getByText('Open'))
    expect(onOpenFile).toHaveBeenCalledWith('src/a.ts')
  })
})
