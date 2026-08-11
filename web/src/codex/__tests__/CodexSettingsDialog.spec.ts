import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { COLOR_SCHEME_STORAGE_KEY, initializeColorScheme } from '../../composables/useColorScheme'
import CodexSettingsDialog from '../components/CodexSettingsDialog.vue'
import type { CodexWorkspaceResponse } from '../types'

const workspace: CodexWorkspaceResponse = {
  projects: [],
  recent_threads: [],
  remote_connections: [],
}

function mountDialog() {
  return mount(CodexSettingsDialog, {
    props: {
      visible: true,
      workspace,
    },
    global: {
      stubs: {
        Dialog: {
          props: ['visible'],
          emits: ['update:visible'],
          template: '<section v-if="visible"><slot /></section>',
        },
        SelectButton: {
          props: ['modelValue', 'options'],
          emits: ['update:modelValue'],
          template:
            '<div v-bind="$attrs"><button v-for="option in options" :key="option.value" :data-theme-option="option.value" :aria-pressed="modelValue === option.value" @click="$emit(\'update:modelValue\', option.value)">{{ option.label }}</button></div>',
        },
        CodexRemoteConnections: {
          template: '<div data-remote-connections />',
        },
        CodexAuthenticationSettings: {
          template: '<div data-codex-auth-settings />',
        },
        CodexSpeechSettings: {
          template: '<div data-codex-speech-settings />',
        },
      },
    },
  })
}

describe('CodexSettingsDialog', () => {
  beforeEach(() => {
    localStorage.clear()
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    })
    initializeColorScheme()
  })

  it('changes and persists the color scheme from appearance settings', async () => {
    const wrapper = mountDialog()

    await wrapper.get('[data-codex-settings-appearance]').trigger('click')
    await wrapper.get('[data-theme-option="dark"]').trigger('click')

    expect(localStorage.getItem(COLOR_SCHEME_STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.classList.contains('app-dark')).toBe(true)
    expect(wrapper.get('[data-theme-option="dark"]').attributes('aria-pressed')).toBe('true')
  })

  it('keeps connection settings in their own section', async () => {
    const wrapper = mountDialog()

    expect(wrapper.find('[data-codex-appearance-settings]').exists()).toBe(false)
    expect(wrapper.find('[data-remote-connections]').exists()).toBe(true)

    await wrapper.get('[data-codex-settings-appearance]').trigger('click')

    expect(wrapper.find('[data-codex-appearance-settings]').exists()).toBe(true)
    expect(wrapper.find('[data-remote-connections]').exists()).toBe(false)
  })

  it('opens authentication settings in its own section', async () => {
    const wrapper = mountDialog()

    await wrapper.get('[data-codex-settings-authentication]').trigger('click')

    expect(wrapper.find('[data-codex-auth-settings]').exists()).toBe(true)
    expect(wrapper.find('[data-remote-connections]').exists()).toBe(false)
  })

  it('opens voice settings in its own section', async () => {
    const wrapper = mountDialog()

    await wrapper.get('[data-codex-settings-speech]').trigger('click')

    expect(wrapper.find('[data-codex-speech-settings]').exists()).toBe(true)
    expect(wrapper.find('[data-remote-connections]').exists()).toBe(false)
  })
})
