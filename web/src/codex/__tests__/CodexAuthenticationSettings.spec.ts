import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiGet, apiPut } from '../../lib/api'
import CodexAuthenticationSettings from '../components/CodexAuthenticationSettings.vue'

vi.mock('../../lib/api', () => ({
  apiGet: vi.fn(),
  apiPut: vi.fn(),
}))

const apiGetMock = vi.mocked(apiGet)
const apiPutMock = vi.mocked(apiPut)

const baseConfig = {
  enabled: false,
  has_password: false,
  has_secret: false,
  session_ttl_hours: 168,
  password_source: 'default' as const,
  secret_source: 'default' as const,
  session_ttl_source: 'default' as const,
}

function mountSettings() {
  return mount(CodexAuthenticationSettings, {
    global: {
      stubs: {
        Button: {
          props: ['disabled', 'loading'],
          template:
            '<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\')"><slot />Save</button>',
        },
        InputText: {
          props: ['modelValue', 'placeholder', 'disabled'],
          emits: ['update:modelValue'],
          template:
            '<input v-bind="$attrs" :value="modelValue" :placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
        Message: {
          template: '<div><slot /></div>',
        },
        ToggleSwitch: {
          props: ['modelValue', 'disabled'],
          emits: ['update:modelValue'],
          template:
            '<input v-bind="$attrs" type="checkbox" :checked="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
        },
      },
    },
  })
}

describe('CodexAuthenticationSettings', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    apiPutMock.mockReset()
    apiGetMock.mockResolvedValue({ ...baseConfig })
  })

  it('loads and saves authentication settings without returning secrets', async () => {
    const savedConfig = {
      ...baseConfig,
      enabled: true,
      has_password: true,
      has_secret: true,
      session_ttl_hours: 12,
      password_source: 'settings' as const,
      secret_source: 'settings' as const,
      session_ttl_source: 'settings' as const,
    }
    apiPutMock.mockResolvedValue(savedConfig)
    const wrapper = mountSettings()
    await flushPromises()

    await wrapper.get('[data-codex-auth-enabled]').setValue(true)
    await wrapper.get('[data-codex-auth-password]').setValue('new-password')
    await wrapper.get('[data-codex-auth-secret]').setValue('new-session-secret')
    await wrapper.get('[data-codex-auth-ttl]').setValue('12')
    await wrapper.get('[data-codex-save-auth]').trigger('click')
    await flushPromises()

    expect(apiGetMock).toHaveBeenCalledWith('/api/config/auth')
    expect(apiPutMock).toHaveBeenCalledWith('/api/config/auth', {
      enabled: true,
      password: 'new-password',
      secret: 'new-session-secret',
      session_ttl_hours: 12,
    })
    expect(wrapper.find('[data-codex-auth-success]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('new-password')
    expect(wrapper.text()).not.toContain('new-session-secret')
  })

  it('disables values managed by environment variables', async () => {
    apiGetMock.mockResolvedValue({
      ...baseConfig,
      enabled: true,
      has_password: true,
      has_secret: true,
      password_source: 'environment',
      secret_source: 'environment',
      session_ttl_source: 'environment',
    })
    const wrapper = mountSettings()
    await flushPromises()

    expect(wrapper.get('[data-codex-auth-enabled]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-codex-auth-password]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-codex-auth-secret]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-codex-auth-ttl]').attributes('disabled')).toBeDefined()
    expect(wrapper.text().match(/Environment/g)).toHaveLength(4)
  })
})
