import { computed, readonly, ref } from 'vue'

export type ColorSchemePreference = 'system' | 'light' | 'dark'
export type ResolvedColorScheme = Exclude<ColorSchemePreference, 'system'>

export const COLOR_SCHEME_STORAGE_KEY = 'yier.color-scheme'

const preference = ref<ColorSchemePreference>('system')
const systemPrefersDark = ref(false)
const resolvedColorScheme = computed<ResolvedColorScheme>(() =>
  preference.value === 'system' ? (systemPrefersDark.value ? 'dark' : 'light') : preference.value,
)

let mediaQuery: MediaQueryList | null = null

function isColorSchemePreference(value: string | null): value is ColorSchemePreference {
  return value === 'system' || value === 'light' || value === 'dark'
}

function readStoredPreference(): ColorSchemePreference {
  if (typeof localStorage === 'undefined') {
    return 'system'
  }

  const stored = localStorage.getItem(COLOR_SCHEME_STORAGE_KEY)
  return isColorSchemePreference(stored) ? stored : 'system'
}

function applyResolvedColorScheme() {
  if (typeof document === 'undefined') {
    return
  }

  const isDark = resolvedColorScheme.value === 'dark'
  document.documentElement.classList.toggle('app-dark', isDark)
  document.documentElement.dataset.colorScheme = resolvedColorScheme.value
}

function handleSystemColorSchemeChange(event: MediaQueryListEvent) {
  systemPrefersDark.value = event.matches
  if (preference.value === 'system') {
    applyResolvedColorScheme()
  }
}

function bindSystemColorScheme() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    systemPrefersDark.value = false
    return
  }

  const nextMediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  if (mediaQuery !== nextMediaQuery) {
    mediaQuery?.removeEventListener?.('change', handleSystemColorSchemeChange)
    mediaQuery = nextMediaQuery
    mediaQuery.addEventListener?.('change', handleSystemColorSchemeChange)
  }
  systemPrefersDark.value = nextMediaQuery.matches
}

export function initializeColorScheme() {
  preference.value = readStoredPreference()
  bindSystemColorScheme()
  applyResolvedColorScheme()
}

export function setColorScheme(nextPreference: ColorSchemePreference) {
  preference.value = nextPreference
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(COLOR_SCHEME_STORAGE_KEY, nextPreference)
  }
  bindSystemColorScheme()
  applyResolvedColorScheme()
}

export function useColorScheme() {
  return {
    colorScheme: readonly(preference),
    resolvedColorScheme: readonly(resolvedColorScheme),
    setColorScheme,
  }
}
