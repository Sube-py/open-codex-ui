import type { CodexSocketStatus } from '../types'

const INITIAL_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 15_000

export type CodexReconnectPhase = 'idle' | 'open' | 'scheduled' | 'connecting' | 'offline'

export type CodexReconnectState = {
  phase: CodexReconnectPhase
  attempt: number
  nextDelayMs: number | null
}

type CodexReconnectOptions = {
  reconnect: () => Promise<void>
  onStateChange?: (state: CodexReconnectState) => void
}

export class CodexReconnectController {
  private status: CodexSocketStatus = 'idle'
  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnecting = false
  private recovering = false
  private started = false
  private reconnectState: CodexReconnectState = {
    phase: 'idle',
    attempt: 0,
    nextDelayMs: null,
  }

  constructor(private readonly options: CodexReconnectOptions) {}

  start() {
    if (this.started || typeof window === 'undefined' || typeof document === 'undefined') {
      return
    }
    this.started = true
    document.addEventListener('visibilitychange', this.handleVisibilityChange)
    window.addEventListener('pageshow', this.handleForeground)
    window.addEventListener('online', this.handleForeground)
    window.addEventListener('offline', this.handleOffline)
  }

  stop() {
    this.started = false
    this.recovering = false
    this.reconnectAttempt = 0
    this.clearReconnectTimer()
    this.publishState('idle', 0, null)
    if (typeof window === 'undefined' || typeof document === 'undefined') {
      return
    }
    document.removeEventListener('visibilitychange', this.handleVisibilityChange)
    window.removeEventListener('pageshow', this.handleForeground)
    window.removeEventListener('online', this.handleForeground)
    window.removeEventListener('offline', this.handleOffline)
  }

  handleStatus(status: CodexSocketStatus) {
    this.status = status
    if (status === 'open') {
      this.recovering = false
      this.reconnectAttempt = 0
      this.clearReconnectTimer()
      this.publishState('open', 0, null)
      return
    }
    if (status === 'connecting') {
      if (this.recovering) {
        this.publishState('connecting', Math.max(this.reconnectAttempt, 1), null)
      }
      return
    }
    if (status === 'closed' || status === 'error') {
      if (!this.started) {
        return
      }
      this.recovering = true
      this.scheduleReconnect()
    }
  }

  private readonly handleVisibilityChange = () => {
    if (document.visibilityState === 'visible') {
      this.reconnectImmediately()
      return
    }
    if (this.recovering) {
      const pendingAttempt = this.reconnectTimer ? this.reconnectAttempt : undefined
      this.clearReconnectTimer()
      this.publishWaitingState(pendingAttempt)
    }
  }

  private readonly handleForeground = () => {
    this.reconnectImmediately()
  }

  private readonly handleOffline = () => {
    if (!this.recovering) {
      return
    }
    const pendingAttempt = this.reconnectTimer ? this.reconnectAttempt : undefined
    this.clearReconnectTimer()
    this.publishState('offline', pendingAttempt ?? this.waitingAttempt(), null)
  }

  private reconnectImmediately() {
    if (!this.shouldReconnect()) {
      return
    }
    this.clearReconnectTimer()
    void this.runReconnect()
  }

  private scheduleReconnect() {
    if (
      !this.started ||
      !this.recovering ||
      this.status === 'open' ||
      this.status === 'connecting'
    ) {
      return
    }
    if (!this.canReconnectNow()) {
      this.publishWaitingState()
      return
    }
    if (this.reconnectTimer) {
      return
    }
    const delay = Math.min(
      INITIAL_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempt,
      MAX_RECONNECT_DELAY_MS,
    )
    this.reconnectAttempt += 1
    this.publishState('scheduled', this.reconnectAttempt, delay)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.runReconnect()
    }, delay)
  }

  private async runReconnect() {
    if (this.reconnecting || !this.shouldReconnect()) {
      return
    }
    if (this.reconnectAttempt === 0) {
      this.reconnectAttempt = 1
    }
    if (this.reconnectState.attempt > this.reconnectAttempt) {
      this.reconnectAttempt = this.reconnectState.attempt
    }
    this.reconnecting = true
    this.publishState('connecting', this.reconnectAttempt, null)
    try {
      await this.options.reconnect()
    } catch {
      // Socket status events schedule the next attempt when available.
    } finally {
      this.reconnecting = false
      if (this.recovering && (this.status === 'closed' || this.status === 'error')) {
        this.scheduleReconnect()
      }
    }
  }

  private shouldReconnect() {
    if (!this.started || this.status === 'open' || this.status === 'connecting') {
      return false
    }
    return this.canReconnectNow()
  }

  private canReconnectNow() {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      return false
    }
    return typeof document === 'undefined' || document.visibilityState !== 'hidden'
  }

  private publishWaitingState(attempt = this.waitingAttempt()) {
    const phase =
      typeof navigator !== 'undefined' && navigator.onLine === false ? 'offline' : 'scheduled'
    this.publishState(phase, attempt, null)
  }

  private waitingAttempt() {
    if (this.reconnecting) {
      return this.reconnectAttempt + 1
    }
    if (
      (this.reconnectState.phase === 'scheduled' || this.reconnectState.phase === 'offline') &&
      this.reconnectState.attempt > this.reconnectAttempt
    ) {
      return this.reconnectState.attempt
    }
    return Math.max(this.reconnectAttempt + 1, 1)
  }

  private publishState(phase: CodexReconnectPhase, attempt: number, nextDelayMs: number | null) {
    const nextState = { phase, attempt, nextDelayMs }
    if (
      this.reconnectState.phase === nextState.phase &&
      this.reconnectState.attempt === nextState.attempt &&
      this.reconnectState.nextDelayMs === nextState.nextDelayMs
    ) {
      return
    }
    this.reconnectState = nextState
    this.options.onStateChange?.({ ...nextState })
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }
}
