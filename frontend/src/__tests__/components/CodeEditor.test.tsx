import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { EditorPanel } from '../../components/EditorPanel/EditorPanel'
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

vi.mock('../../components/ArtifactPanel/OfficeViewer', () => ({
  OfficeViewer: ({ item }: any) => <div data-testid="office-viewer">{item.title}</div>,
}))

vi.mock('../../components/ArtifactPanel/ImageViewer', () => ({
  ImageViewer: ({ url }: any) => <div data-testid="image-viewer">{url}</div>,
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

  it('renders office project files with the office viewer instead of Monaco', () => {
    render(
      <EditorPanel
        groups={[{
          id: 'main',
          activeFileId: 'file-1',
          openFiles: [{
            id: 'file-1',
            path: '交易流水.xlsx',
            name: '交易流水.xlsx',
            content: '',
            language: 'excel',
            viewerType: 'office',
            readOnly: true,
            artifact: {
              id: 'artifact_excel',
              type: 'office',
              title: '交易流水.xlsx',
              timestamp: 1,
              sourceTool: 'project_file_open',
              workbook: { sheets: [{ name: 'Sheet1', rows: [] }] },
            },
          }],
        }]}
        activeGroupId="main"
        projectName="repo"
        onSelectFile={vi.fn()}
        onCloseFile={vi.fn()}
        onMoveToGroup={vi.fn()}
        onSplitEditor={vi.fn()}
        onCloseSplit={vi.fn()}
        onSetActiveGroup={vi.fn()}
      />,
    )

    expect(screen.getByTestId('office-viewer')).toHaveTextContent('交易流水.xlsx')
    expect(screen.queryByLabelText('monaco-editor')).not.toBeInTheDocument()
  })

  it('renders binary project files with a fallback notice instead of Monaco', () => {
    render(
      <EditorPanel
        groups={[{
          id: 'main',
          activeFileId: 'file-1',
          openFiles: [{
            id: 'file-1',
            path: 'payload.bin',
            name: 'payload.bin',
            content: '',
            language: 'binary',
            viewerType: 'binary',
            readOnly: true,
            absolutePath: 'C:/repo/payload.bin',
            mimeType: 'application/octet-stream',
            size: 10,
            binaryReason: 'Binary content cannot be edited in the code editor.',
          }],
        }]}
        activeGroupId="main"
        projectName="repo"
        onSelectFile={vi.fn()}
        onCloseFile={vi.fn()}
        onMoveToGroup={vi.fn()}
        onSplitEditor={vi.fn()}
        onCloseSplit={vi.fn()}
        onSetActiveGroup={vi.fn()}
      />,
    )

    expect(screen.getAllByText('payload.bin').length).toBeGreaterThan(0)
    expect(screen.getByText('Binary content cannot be edited in the code editor.')).toBeInTheDocument()
    expect(screen.queryByLabelText('monaco-editor')).not.toBeInTheDocument()
  })
})
