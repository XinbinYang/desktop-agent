import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FileEditView } from '../../components/FileEditView'

vi.mock('@monaco-editor/react', () => ({
  DiffEditor: ({ original, modified }: any) => (
    <div data-testid="monaco-diff">{original} → {modified}</div>
  ),
}))

const baseEdit = {
  path: 'src/example.ts',
  operation: 'modify',
  old_text: 'old content',
  new_text: 'new content',
  unified_diff: '--- a/example.ts\n+++ b/example.ts\n-old content\n+new content\n',
  stats: { added: 1, removed: 1 },
  truncated: false,
}

describe('FileEditView', () => {
  describe('header rendering', () => {
    it('renders operation label + filename for modify', () => {
      render(<FileEditView edit={baseEdit} compact />)
      expect(screen.getByText(/Edit/)).toBeInTheDocument()
      expect(screen.getByText(/example\.ts/)).toBeInTheDocument()
    })

    it('renders operation label + filename for create', () => {
      render(<FileEditView edit={{ ...baseEdit, operation: 'create' }} compact />)
      expect(screen.getByText(/Create/)).toBeInTheDocument()
      expect(screen.getByText(/example\.ts/)).toBeInTheDocument()
    })

    it('renders operation label + filename for delete', () => {
      render(<FileEditView edit={{ ...baseEdit, operation: 'delete' }} compact />)
      expect(screen.getByText(/Delete/)).toBeInTheDocument()
      expect(screen.getByText(/example\.ts/)).toBeInTheDocument()
    })

    it('renders stats text with added and removed lines', () => {
      render(<FileEditView edit={baseEdit} compact />)
      expect(screen.getByText(/Added 1 lines/)).toBeInTheDocument()
      expect(screen.getByText(/Removed 1 lines/)).toBeInTheDocument()
    })

    it('renders "Modified" fallback when no added or removed lines', () => {
      render(<FileEditView edit={{ ...baseEdit, stats: { added: 0, removed: 0 } }} compact />)
      expect(screen.getByText(/Modified/)).toBeInTheDocument()
    })

    it('renders directory path in subtitle', () => {
      render(<FileEditView edit={baseEdit} compact />)
      expect(screen.getByText(/src/)).toBeInTheDocument()
    })

    it('renders correct basename and dirname for nested paths', () => {
      render(
        <FileEditView
          edit={{ ...baseEdit, path: 'a/b/c/deep/file.tsx' }}
          compact
        />
      )
      expect(screen.getByText(/file\.tsx/)).toBeInTheDocument()
      expect(screen.getByText(/a\/b\/c\/deep/)).toBeInTheDocument()
    })
  })

  describe('expand/collapse', () => {
    it('compact={true} starts collapsed: Monaco diff viewer is not in the document', () => {
      render(<FileEditView edit={baseEdit} compact={true} />)
      expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument()
    })

    it('clicking header expands and shows Monaco diff viewer', () => {
      render(<FileEditView edit={baseEdit} compact={true} />)
      const header = screen.getByRole('button')
      fireEvent.click(header)
      expect(screen.getByTestId('monaco-diff')).toBeInTheDocument()
      expect(screen.getByText(/old content/)).toBeInTheDocument()
    })

    it('compact={false} starts expanded', () => {
      render(<FileEditView edit={baseEdit} compact={false} />)
      expect(screen.getByTestId('monaco-diff')).toBeInTheDocument()
    })

    it('toggles expand/collapse on repeated clicks', () => {
      render(<FileEditView edit={baseEdit} compact={true} />)
      const header = screen.getByRole('button')
      fireEvent.click(header)
      expect(screen.getByTestId('monaco-diff')).toBeInTheDocument()
      fireEvent.click(header)
      expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument()
    })

    it('event-row starts collapsed and expands to a lightweight unified diff', () => {
      render(<FileEditView edit={baseEdit} compact variant="event-row" />)
      expect(screen.getByTestId('file-edit-event-row')).toBeInTheDocument()
      expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument()
      fireEvent.click(screen.getByText('View diff'))
      expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument()
      expect(screen.getByText(/-old content/)).toBeInTheDocument()
    })
  })

  describe('truncated fallback', () => {
    it('shows unified diff text when truncated and no old_text/new_text', () => {
      const truncatedEdit = {
        ...baseEdit,
        old_text: undefined,
        new_text: undefined,
        truncated: true,
      }
      render(<FileEditView edit={truncatedEdit} compact={false} />)
      expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument()
      expect(screen.getByText(/--- a\/example\.ts/)).toBeInTheDocument()
      expect(screen.getByText(/-old content/)).toBeInTheDocument()
      expect(screen.getByText(/\+new content/)).toBeInTheDocument()
    })

    it('shows unified diff text after expanding a truncated edit', () => {
      const truncatedEdit = {
        ...baseEdit,
        old_text: undefined,
        new_text: undefined,
        truncated: true,
      }
      render(<FileEditView edit={truncatedEdit} compact={true} />)
      expect(screen.queryByText(/--- a\/example\.ts/)).not.toBeInTheDocument()
      const header = screen.getByRole('button')
      fireEvent.click(header)
      expect(screen.getByText(/--- a\/example\.ts/)).toBeInTheDocument()
    })
  })
})
