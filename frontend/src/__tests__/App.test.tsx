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
    expect(screen.getByText('○ Ready')).toBeInTheDocument()
  })
  it('opens settings when the default provider has no configured API key', async () => {
    global.fetch = vi.fn((url: string) => {
      if (url.endsWith('/api/models')) {
        return Promise.resolve({
          json: () => Promise.resolve({
            models: [
              { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
            ],
            default: 'gpt-4o',
          }),
        }) as any
      }
      if (url.endsWith('/api/settings')) {
        return Promise.resolve({
          json: () => Promise.resolve({
            providers: {
              openai: {
                name: 'openai',
                base_url: 'https://api.openai.com/v1',
                api_key_masked: '${OPENAI_API_KEY}',
                api_key_configured: false,
                models: [
                  { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
                ],
              },
            },
            settings: {
              default_model: 'gpt-4o',
              default_provider: 'openai',
              max_iterations: 50,
              auto_approve: false,
              screenshot_on_step: true,
            },
          }),
        }) as any
      }
      if (url.endsWith('/api/roles')) {
        return Promise.resolve({ json: () => Promise.resolve({ roles: [] }) }) as any
      }
      if (url.endsWith('/api/sessions')) {
        return Promise.resolve({ json: () => Promise.resolve({ sessions: [] }) }) as any
      }
      return Promise.resolve({ json: () => Promise.resolve({}) }) as any
    }) as any

    render(<App />)

    expect(await screen.findByText('Providers')).toBeInTheDocument()
  })
})
