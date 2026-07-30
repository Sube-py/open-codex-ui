import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PrimeVue from 'primevue/config'

import type { Ref } from 'vue'

type SpeechSession = {
  state: Ref<'idle' | 'connecting' | 'recording' | 'stopping'>
  level: Ref<number>
  start: ReturnType<typeof vi.fn>
  stop: ReturnType<typeof vi.fn>
  dispose: ReturnType<typeof vi.fn>
}

const speechHarness = vi.hoisted(() => ({
  sessions: [] as SpeechSession[],
}))

vi.mock('../composables/useStreamingSpeech', async (importOriginal) => {
  const actual = await importOriginal<
    typeof import('../composables/useStreamingSpeech')
  >()
  const { ref } = await import('vue')
  return {
    ...actual,
    useStreamingSpeech: () => {
      const state = ref<'idle' | 'connecting' | 'recording' | 'stopping'>('idle')
      const session = {
        state,
        level: ref(0.6),
        error: ref(''),
        start: vi.fn(() => {
          state.value = 'recording'
          return Promise.resolve()
        }),
        stop: vi.fn(() => {
          state.value = 'stopping'
        }),
        clearError: vi.fn(),
        dispose: vi.fn(() => {
          state.value = 'idle'
        }),
      }
      speechHarness.sessions.push(session)
      return session
    },
  }
})

import CodexComposer from '../components/CodexComposer.vue'

function mountComposer() {
  return mount(CodexComposer, {
    props: {
      modelValue: '',
      disabled: false,
      busy: false,
      isWorking: false,
      mode: 'build',
      queuedFollowups: [],
      state: { id: 'thread-1', turns: [] },
    },
    global: {
      plugins: [PrimeVue],
    },
  })
}

function dispatchPointerEvent(
  element: Element,
  type: string,
  options: { button: number; pointerId: number },
) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, {
    button: { value: options.button },
    pointerId: { value: options.pointerId },
  })
  element.dispatchEvent(event)
}

describe('CodexComposer push-to-talk input', () => {
  beforeEach(() => {
    speechHarness.sessions.length = 0
    document.body.innerHTML = ''
    vi.stubGlobal('matchMedia', () => ({
      addEventListener: vi.fn(),
      addListener: vi.fn(),
      dispatchEvent: vi.fn(),
      matches: false,
      media: '',
      onchange: null,
      removeEventListener: vi.fn(),
      removeListener: vi.fn(),
    }))
  })

  it('records while the pointer is held and stops when it is released', async () => {
    const wrapper = mountComposer()
    const session = speechHarness.sessions[0]!
    const button = wrapper.get('[data-codex-speech-input]')
    const setPointerCapture = vi.fn()
    const releasePointerCapture = vi.fn()
    Object.defineProperties(button.element, {
      setPointerCapture: { value: setPointerCapture },
      hasPointerCapture: { value: () => true },
      releasePointerCapture: { value: releasePointerCapture },
    })

    dispatchPointerEvent(button.element, 'pointerdown', { button: 0, pointerId: 7 })
    await wrapper.vm.$nextTick()

    expect(setPointerCapture).toHaveBeenCalledWith(7)
    expect(session.start).toHaveBeenCalledOnce()
    expect(button.attributes('aria-label')).toBe('Release to finish')
    expect(button.attributes('aria-pressed')).toBe('true')
    expect(document.body.querySelector('[data-codex-speech-waveform]')).not.toBeNull()

    dispatchPointerEvent(button.element, 'pointerup', { button: 0, pointerId: 7 })
    await wrapper.vm.$nextTick()

    expect(releasePointerCapture).toHaveBeenCalledWith(7)
    expect(session.stop).toHaveBeenCalledOnce()
    expect(document.body.querySelector('[data-codex-speech-waveform]')).toBeNull()
  })

  it('supports holding Space from the keyboard', async () => {
    const wrapper = mountComposer()
    const session = speechHarness.sessions[0]!
    const button = wrapper.get('[data-codex-speech-input]')

    await button.trigger('keydown', { key: ' ', repeat: false })
    expect(session.start).toHaveBeenCalledOnce()

    await button.trigger('keyup', { key: ' ' })
    expect(session.stop).toHaveBeenCalledOnce()
  })

  it('cancels voice input when the page moves to the background', async () => {
    let visibilityState: DocumentVisibilityState = 'visible'
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibilityState)
    const wrapper = mountComposer()
    const session = speechHarness.sessions[0]!
    const button = wrapper.get('[data-codex-speech-input]')

    dispatchPointerEvent(button.element, 'pointerdown', { button: 0, pointerId: 9 })
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('[data-codex-speech-waveform]')).not.toBeNull()

    visibilityState = 'hidden'
    document.dispatchEvent(new Event('visibilitychange'))
    await wrapper.vm.$nextTick()

    expect(session.dispose).toHaveBeenCalledOnce()
    expect(document.body.querySelector('[data-codex-speech-waveform]')).toBeNull()
  })
})
