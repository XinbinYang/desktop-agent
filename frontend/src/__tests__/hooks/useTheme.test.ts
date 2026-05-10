import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTheme } from '../../hooks/useTheme'

// jsdom doesn't implement matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('light') ? false : true,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('defaults to dark theme', () => {
    const { result } = renderHook(() => useTheme())
    expect(result.current.resolved).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('reads stored theme from localStorage', () => {
    localStorage.setItem('desktop-agent-theme', 'light')
    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('light')
    expect(result.current.resolved).toBe('light')
  })

  it('toggle switches between dark and light', () => {
    const { result } = renderHook(() => useTheme())
    expect(result.current.resolved).toBe('dark')

    act(() => result.current.toggle())
    expect(result.current.resolved).toBe('light')

    act(() => result.current.toggle())
    expect(result.current.resolved).toBe('dark')
  })

  it('setTheme sets the theme directly', () => {
    const { result } = renderHook(() => useTheme())

    act(() => result.current.setTheme('light'))
    expect(result.current.theme).toBe('light')
    expect(localStorage.getItem('desktop-agent-theme')).toBe('light')

    act(() => result.current.setTheme('system'))
    expect(result.current.theme).toBe('system')
  })

  it('resolves system theme based on prefers-color-scheme', () => {
    const { result } = renderHook(() => useTheme())
    act(() => result.current.setTheme('system'))
    // Our mock returns dark (query.includes('light') is false → matches = true → dark)
    expect(result.current.resolved).toBe('dark')
  })

  it('applies data-theme attribute', () => {
    renderHook(() => useTheme())
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    const { result } = renderHook(() => useTheme())
    act(() => result.current.setTheme('light'))
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})
