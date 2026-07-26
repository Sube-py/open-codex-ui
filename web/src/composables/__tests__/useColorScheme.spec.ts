import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  COLOR_SCHEME_STORAGE_KEY,
  initializeColorScheme,
  setColorScheme,
  useColorScheme,
} from '../useColorScheme'

function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches
  let listener: ((event: MediaQueryListEvent) => void) | undefined
  const query = {
    get matches() {
      return matches
    },
    media: '(prefers-color-scheme: dark)',
    onchange: null,
    addEventListener: vi.fn((_type: string, nextListener: (event: MediaQueryListEvent) => void) => {
      listener = nextListener
    }),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList

  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => query),
  })

  return {
    change(nextMatches: boolean) {
      matches = nextMatches
      listener?.({ matches: nextMatches } as MediaQueryListEvent)
    },
  }
}

describe('useColorScheme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('app-dark')
    delete document.documentElement.dataset.colorScheme
  })

  it('restores a saved dark preference before the app renders', () => {
    installMatchMedia(false)
    localStorage.setItem(COLOR_SCHEME_STORAGE_KEY, 'dark')

    initializeColorScheme()

    expect(useColorScheme().colorScheme.value).toBe('dark')
    expect(document.documentElement.classList.contains('app-dark')).toBe(true)
    expect(document.documentElement.dataset.colorScheme).toBe('dark')
  })

  it('persists an explicit light preference', () => {
    installMatchMedia(true)
    initializeColorScheme()

    setColorScheme('light')

    expect(localStorage.getItem(COLOR_SCHEME_STORAGE_KEY)).toBe('light')
    expect(document.documentElement.classList.contains('app-dark')).toBe(false)
    expect(document.documentElement.dataset.colorScheme).toBe('light')
  })

  it('tracks system color scheme changes', () => {
    const media = installMatchMedia(false)
    initializeColorScheme()
    setColorScheme('system')

    media.change(true)

    expect(useColorScheme().resolvedColorScheme.value).toBe('dark')
    expect(document.documentElement.classList.contains('app-dark')).toBe(true)
  })
})
