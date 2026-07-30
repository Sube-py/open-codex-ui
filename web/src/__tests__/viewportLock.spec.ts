import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useViewportLock } from '../composables/useViewportLock'

const ViewportLockedComponent = defineComponent({
  setup() {
    useViewportLock()
    return () => h('main')
  },
})

describe('useViewportLock', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    document.documentElement.classList.remove('yier-viewport-lock')
    document.body.classList.remove('yier-viewport-lock')
    document.documentElement.style.removeProperty('--yier-viewport-height')
  })

  it('locks outer viewport scrolling until the final workspace unmounts', () => {
    const first = mount(ViewportLockedComponent)
    const second = mount(ViewportLockedComponent)

    expect(document.documentElement.classList.contains('yier-viewport-lock')).toBe(true)
    expect(document.body.classList.contains('yier-viewport-lock')).toBe(true)

    first.unmount()
    expect(document.body.classList.contains('yier-viewport-lock')).toBe(true)

    second.unmount()
    expect(document.documentElement.classList.contains('yier-viewport-lock')).toBe(false)
    expect(document.body.classList.contains('yier-viewport-lock')).toBe(false)
  })

  it('tracks the real visual viewport height', () => {
    const visualViewport = new EventTarget()
    Object.defineProperties(visualViewport, {
      height: { configurable: true, value: 612 },
      scale: { configurable: true, value: 1 },
    })
    vi.stubGlobal('visualViewport', visualViewport)

    const wrapper = mount(ViewportLockedComponent)
    expect(document.documentElement.style.getPropertyValue('--yier-viewport-height')).toBe(
      '612px',
    )

    Object.defineProperty(visualViewport, 'height', { configurable: true, value: 418 })
    visualViewport.dispatchEvent(new Event('resize'))
    expect(document.documentElement.style.getPropertyValue('--yier-viewport-height')).toBe(
      '418px',
    )

    wrapper.unmount()
    expect(document.documentElement.style.getPropertyValue('--yier-viewport-height')).toBe('')
  })
})
