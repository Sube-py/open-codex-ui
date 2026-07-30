import { onBeforeUnmount, onMounted } from 'vue'

const VIEWPORT_LOCK_CLASS = 'yier-viewport-lock'
const VIEWPORT_HEIGHT_PROPERTY = '--yier-viewport-height'
let activeViewportLocks = 0
let trackedVisualViewport: VisualViewport | null = null

function syncViewportHeight() {
  const visualViewport = window.visualViewport
  const height =
    visualViewport && visualViewport.scale <= 1.01
      ? visualViewport.height
      : window.innerHeight
  document.documentElement.style.setProperty(VIEWPORT_HEIGHT_PROPERTY, `${height}px`)
}

function startViewportTracking() {
  trackedVisualViewport = window.visualViewport
  window.addEventListener('resize', syncViewportHeight)
  trackedVisualViewport?.addEventListener('resize', syncViewportHeight)
  trackedVisualViewport?.addEventListener('scroll', syncViewportHeight)
  syncViewportHeight()
}

function stopViewportTracking() {
  window.removeEventListener('resize', syncViewportHeight)
  trackedVisualViewport?.removeEventListener('resize', syncViewportHeight)
  trackedVisualViewport?.removeEventListener('scroll', syncViewportHeight)
  trackedVisualViewport = null
  document.documentElement.style.removeProperty(VIEWPORT_HEIGHT_PROPERTY)
}

export function useViewportLock() {
  let isActive = false

  onMounted(() => {
    if (isActive) {
      return
    }
    isActive = true
    activeViewportLocks += 1
    if (activeViewportLocks === 1) {
      document.documentElement.classList.add(VIEWPORT_LOCK_CLASS)
      document.body.classList.add(VIEWPORT_LOCK_CLASS)
      startViewportTracking()
    }
  })

  onBeforeUnmount(() => {
    if (!isActive) {
      return
    }
    isActive = false
    activeViewportLocks = Math.max(0, activeViewportLocks - 1)
    if (activeViewportLocks === 0) {
      document.documentElement.classList.remove(VIEWPORT_LOCK_CLASS)
      document.body.classList.remove(VIEWPORT_LOCK_CLASS)
      stopViewportTracking()
    }
  })
}
