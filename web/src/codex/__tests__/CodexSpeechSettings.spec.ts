import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiGet, apiPost, apiPut } from '../../lib/api'
import CodexSpeechSettings from '../components/CodexSpeechSettings.vue'

vi.mock('../../lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
}))

const apiGetMock = vi.mocked(apiGet)
const apiPostMock = vi.mocked(apiPost)
const apiPutMock = vi.mocked(apiPut)

const baseConfig = {
  model_dir: '/Users/test/.yier/models/sherpa-onnx',
  provider: 'cpu',
  num_threads: 2,
  status: 'missing' as const,
  detail: 'sherpa-onnx model directory not found',
  model_dir_source: 'settings' as const,
  provider_source: 'settings' as const,
  num_threads_source: 'settings' as const,
}

function mountSettings() {
  return mount(CodexSpeechSettings, {
    global: {
      stubs: {
        Button: {
          props: ['disabled', 'loading'],
          emits: ['click'],
          template:
            '<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\')"><slot />Save</button>',
        },
        InputText: {
          props: ['modelValue', 'disabled'],
          emits: ['update:modelValue'],
          template:
            '<input v-bind="$attrs" :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
        Message: {
          template: '<div><slot /></div>',
        },
        Select: {
          props: ['modelValue', 'options', 'disabled'],
          emits: ['update:modelValue'],
          template:
            '<select v-bind="$attrs" :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>',
        },
      },
    },
  })
}

describe('CodexSpeechSettings', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    apiPostMock.mockReset()
    apiPutMock.mockReset()
    apiGetMock.mockResolvedValue({ ...baseConfig })
  })

  it('loads and saves sherpa-onnx model settings', async () => {
    apiPutMock.mockResolvedValue({
      ...baseConfig,
      model_dir: '/models/zh-en',
      provider: 'coreml',
      num_threads: 4,
      status: 'ready',
      detail: 'Model files are ready.',
    })
    const wrapper = mountSettings()
    await flushPromises()

    await wrapper.get('[data-codex-speech-model-dir]').setValue('/models/zh-en')
    await wrapper.get('[data-codex-speech-provider]').setValue('coreml')
    await wrapper.get('[data-codex-speech-threads]').setValue('4')
    await wrapper.get('[data-codex-save-speech]').trigger('click')
    await flushPromises()

    expect(apiGetMock).toHaveBeenCalledWith('/api/config/speech')
    expect(apiPutMock).toHaveBeenCalledWith('/api/config/speech', {
      model_dir: '/models/zh-en',
      provider: 'coreml',
      num_threads: 4,
    })
    expect(wrapper.get('[data-codex-speech-model-status]').text()).toBe('Ready')
    expect(wrapper.find('[data-codex-speech-success]').exists()).toBe(true)
  })

  it('disables fields managed by environment variables', async () => {
    apiGetMock.mockResolvedValue({
      ...baseConfig,
      model_dir_source: 'environment',
      provider_source: 'environment',
      num_threads_source: 'environment',
    })
    const wrapper = mountSettings()
    await flushPromises()

    expect(wrapper.get('[data-codex-speech-model-dir]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-codex-speech-provider]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-codex-speech-threads]').attributes('disabled')).toBeDefined()
    expect(wrapper.text().match(/Environment/g)).toHaveLength(3)
  })

  it('selects a model directory through the system picker', async () => {
    apiPostMock.mockResolvedValue({
      selected: true,
      project_path: '/models/selected',
    })
    const wrapper = mountSettings()
    await flushPromises()

    await wrapper.get('[data-codex-select-speech-model-dir]').trigger('click')
    await flushPromises()

    expect(apiPostMock).toHaveBeenCalledWith('/api/system/select-directory', {
      initial_path: baseConfig.model_dir,
    })
    expect((wrapper.get('[data-codex-speech-model-dir]').element as HTMLInputElement).value).toBe(
      '/models/selected',
    )
  })
})
