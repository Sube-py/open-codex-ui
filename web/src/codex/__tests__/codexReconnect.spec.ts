import { afterEach, describe, expect, it, vi } from 'vitest'

import { CodexReconnectController, type CodexReconnectState } from '../lib/codexReconnect'

describe('CodexReconnectController', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('reports a scheduled attempt and clears it when the socket reopens', async () => {
    vi.useFakeTimers()
    const states: CodexReconnectState[] = []
    const reconnect = vi.fn(async () => {
      controller.handleStatus('open')
    })
    const controller = new CodexReconnectController({
      reconnect,
      onStateChange: (state) => states.push(state),
    })

    controller.start()
    controller.handleStatus('closed')

    expect(states[states.length - 1]).toEqual({
      phase: 'scheduled',
      attempt: 1,
      nextDelayMs: 1_000,
    })

    await vi.advanceTimersByTimeAsync(1_000)

    expect(reconnect).toHaveBeenCalledTimes(1)
    expect(states).toContainEqual({ phase: 'connecting', attempt: 1, nextDelayMs: null })
    expect(states[states.length - 1]).toEqual({ phase: 'open', attempt: 0, nextDelayMs: null })
    controller.stop()
  })

  it('increases the attempt and backs off after a failed reconnect', async () => {
    vi.useFakeTimers()
    const states: CodexReconnectState[] = []
    const controller = new CodexReconnectController({
      reconnect: vi.fn().mockRejectedValue(new Error('still disconnected')),
      onStateChange: (state) => states.push(state),
    })

    controller.start()
    controller.handleStatus('error')
    await vi.advanceTimersByTimeAsync(1_000)

    expect(states[states.length - 1]).toEqual({
      phase: 'scheduled',
      attempt: 2,
      nextDelayMs: 2_000,
    })
    controller.stop()
  })

  it('waits while offline and reconnects immediately when the browser returns online', async () => {
    vi.useFakeTimers()
    let online = false
    vi.spyOn(navigator, 'onLine', 'get').mockImplementation(() => online)
    const states: CodexReconnectState[] = []
    const reconnect = vi.fn(async () => {
      controller.handleStatus('open')
    })
    const controller = new CodexReconnectController({
      reconnect,
      onStateChange: (state) => states.push(state),
    })

    controller.start()
    controller.handleStatus('closed')

    expect(states[states.length - 1]).toEqual({ phase: 'offline', attempt: 1, nextDelayMs: null })
    await vi.advanceTimersByTimeAsync(15_000)
    expect(reconnect).not.toHaveBeenCalled()

    online = true
    window.dispatchEvent(new Event('online'))
    await vi.runAllTicks()

    expect(reconnect).toHaveBeenCalledTimes(1)
    expect(states[states.length - 1]).toEqual({ phase: 'open', attempt: 0, nextDelayMs: null })
    controller.stop()
  })

  it('does not reconnect or retain a disconnect notice after being stopped', async () => {
    vi.useFakeTimers()
    const states: CodexReconnectState[] = []
    const reconnect = vi.fn().mockResolvedValue(undefined)
    const controller = new CodexReconnectController({
      reconnect,
      onStateChange: (state) => states.push(state),
    })

    controller.start()
    controller.handleStatus('closed')
    controller.stop()
    await vi.advanceTimersByTimeAsync(15_000)

    expect(reconnect).not.toHaveBeenCalled()
    expect(states[states.length - 1]).toEqual({ phase: 'idle', attempt: 0, nextDelayMs: null })
  })
})
