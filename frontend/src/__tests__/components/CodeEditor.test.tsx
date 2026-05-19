import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CodeEditor } from '../../components/EditorPanel/CodeEditor'

vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange, options }: any) => (
    <textarea
      aria-label="monaco-editor"
      readOnly={!!options?.readOnly}
      value={value}
      onChange={(event) => onChange?.((event.target as HTMLTextAreaElement).value)}
    />
  ),
}))

describe('CodeEditor', () => {
  it('does not emit edits for read-only files', () => {
    const onChange = vi.fn()
    const onSave = vi.fn()

    render(
      <CodeEditor
        content="# Plan"
        filename="plan.md"
        isModified
        readOnly
        onChange={onChange}
        onSave={onSave}
      />,
    )

    expect(screen.getByText('Read-only')).toBeInTheDocument()
    const editor = screen.getByLabelText('monaco-editor')
    expect(editor).toHaveAttribute('readonly')

    fireEvent.change(editor, { target: { value: '# Changed' } })
    expect(onChange).not.toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()
  })
})
