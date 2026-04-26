import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import App from '../App'

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset fetch mock
    global.fetch = vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({
          models: [
            { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
          ],
          default: 'gpt-4o',
        }),
      })
    ) as any
  })

  it('renders without crashing', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Desktop Agent')).toBeInTheDocument()
    })
  })

  it('fetches models on mount', async () => {
    render(<App />)
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('http://127.0.0.1:8765/api/models')
    })
  })

  it('shows connection status', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Desktop Agent')).toBeInTheDocument()
    })
    // Initially disconnected until WS connects
    expect(screen.getByText('○ 就绪')).toBeInTheDocument()
  })
})
