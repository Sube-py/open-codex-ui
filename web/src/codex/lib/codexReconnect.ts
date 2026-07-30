import type { CodexSocketStatus } from '../types'

const INITIAL_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 15_000

type CodexReconnectOptions = {
  reconnect: () => Promise<void>
}

export class CodexReconnectController {
  private status: CodexSocketStatus = 'idle'
  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnecting = false
  private started = false

  constructor(private readonly options: CodexReconnectOptions) {}

  start() {
    if (this.started || typeof window === 'undefined' || typeof document === 'undefined') {
      return
    }
    this.started = true
    document.addEventListener('visibilitychange', this.handleVisibilityChange)
    window.addEventListener('pageshow', this.handleForeground)
    window.addEventListener('online', this.handleForeground)
  }

  stop() {
    this.started = false
    this.clearReconnectTimer()
    if (typeof window === 'undefined' || typeof document === 'undefined') {
      return
    }
    document.removeEventListener('visibilitychange', this.handleVisibilityChange)
    window.removeEventListener('pageshow', this.handleForeground)
    window.removeEventListener('online', this.handleForeground)
  }

  handleStatus(status: CodexSocketStatus) {
    this.status = status
    if (status === 'open') {
      this.reconnectAttempt = 0
      this.clearReconnectTimer()
      return
    }
    if (status === 'closed' || status === 'error') {
      this.scheduleReconnect()
    }
  }

  private readonly handleVisibilityChange = () => {
    if (document.visibilityState === 'visible') {
      this.reconnectImmediately()
    }
  }

  private readonly handleForeground = () => {
    this.reconnectImmediately()
  }

  private reconnectImmediately() {
    if (!this.shouldReconnect()) {
      return
    }
    this.clearReconnectTimer()
    void this.runReconnect()
  }

  private scheduleReconnect() {
    if (!this.shouldReconnect() || this.reconnectTimer) {
      return
    }
    const delay = Math.min(
      INITIAL_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempt,
      MAX_RECONNECT_DELAY_MS,
    )
    this.reconnectAttempt += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.runReconnect()
    }, delay)
  }

  private async runReconnect() {
    if (this.reconnecting || !this.shouldReconnect()) {
      return
    }
    this.reconnecting = true
    try {
      await this.options.reconnect()
    } catch {
      this.scheduleReconnect()
    } finally {
      this.reconnecting = false
    }
  }

  private shouldReconnect() {
    if (!this.started || this.status === 'open' || this.status === 'connecting') {
      return false
    }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      return false
    }
    return typeof document === 'undefined' || document.visibilityState !== 'hidden'
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }
}
