import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useRef } from 'react'
import { __resetSlashCommandCacheForTests, SlashCommandMenu } from '../../components/SlashCommandMenu'

const commands = [
  { name: 'help', description: 'Show help', args: '', category: 'general' },
  { name: 'clear', description: 'Clear session', args: '', category: 'session' },
  { name: 'reset', description: 'Reset context', args: '', category: 'session' },
  { name: 'config', description: 'Open settings', args: '', category: 'general' },
  { name: 'skills', description: 'Open skills', args: '', category: 'general' },
]

function Harness({ onSelect }: { onSelect: (cmd: any) => void }) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  return (
    <>
      <textarea ref={inputRef} aria-label="command-input" />
      <SlashCommandMenu
        query="/"
        onSelect={onSelect}
        onClose={() => {}}
        inputRef={inputRef}
      />
    </>
  )
}

describe('SlashCommandMenu', () => {
  beforeEach(() => {
    __resetSlashCommandCacheForTests()
    Element.prototype.scrollIntoView = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({ commands }),
    })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('uses rendered menu order for arrow navigation and selection', async () => {
    const onSelect = vi.fn()
    const { container } = render(<Harness onSelect={onSelect} />)
    const input = screen.getByLabelText('command-input')

    await screen.findByText('/help')
    expect(screen.getByText('/reset')).toBeInTheDocument()
    const commandButton = (name: string) =>
      container.querySelector(`[data-command-name="${name}"]`) as HTMLElement

    expect(commandButton('help')).toHaveAttribute('aria-selected', 'true')

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    await waitFor(() => expect(commandButton('config')).toHaveAttribute('aria-selected', 'true'))

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    await waitFor(() => expect(commandButton('skills')).toHaveAttribute('aria-selected', 'true'))

    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ name: 'skills' }))
  })

  it('anchors inside the composer and keeps keyboard scrolling local', async () => {
    const scrollIntoView = Element.prototype.scrollIntoView as any
    const { container } = render(<Harness onSelect={() => {}} />)
    const input = screen.getByLabelText('command-input')

    await screen.findByText('/help')

    const menu = container.querySelector('.absolute.bottom-full.left-0.right-0') as HTMLElement
    expect(menu).toBeInTheDocument()
    expect(menu).not.toHaveStyle({ position: 'fixed' })

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(scrollIntoView).not.toHaveBeenCalled()
  })
})
