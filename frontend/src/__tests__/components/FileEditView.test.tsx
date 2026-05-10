import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FileEditView } from '../../components/FileEditView'

const edit = {
  path: 'src/example.ts',
  operation: 'modify',
  old_text: 'old',
  new_text: 'new',
  unified_diff: '--- a/example.ts\n+++ b/example.ts\n-old\n+new\n',
  stats: { added: 1, removed: 1 },
  truncated: false,
}

describe('FileEditView', () => {
  it('renders edit stats and expands diff', () => {
    render(<FileEditView edit={edit} compact />)
    expect(screen.getByText('Edit example.ts')).toBeInTheDocument()
    expect(screen.getByText('+1')).toBeInTheDocument()
    expect(screen.getByText('-1')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Edit example.ts').closest('button')!)
    expect(screen.getByText(/old/)).toBeInTheDocument()
  })
})
