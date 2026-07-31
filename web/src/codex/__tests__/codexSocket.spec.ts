import { beforeEach, describe, expect, it, vi } from 'vitest'
import { gzipSync, strToU8 } from 'fflate'

import {
  CODEX_GZIP_FRAME_PREFIX,
  CodexSocket,
  CodexSocketError,
} from '../lib/codexSocket'

class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static instances: MockWebSocket[] = []

  readyState = MockWebSocket.CONNECTING
  binaryType: BinaryType = 'blob'
  sent: string[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: MessageEvent<unknown>) => void) | null = null

  constructor(readonly url: string) {
    MockWebSocket.instances.push(this)
  }

  send(payload: string) {
    this.sent.push(payload)
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }

  open() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.()
  }

  receive(payload: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }))
  }

  receiveRaw(payload: ArrayBuffer) {
    this.onmessage?.(new MessageEvent('message', { data: payload }))
  }
}

describe('CodexSocket', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  it('resolves command acknowledgements and emits server events', async () => {
    const client = new CodexSocket('ws://codex.test/ws')
    const events: unknown[] = []
    client.onEvent((event) => events.push(event))

    const connectPromise = client.connect()
    const rawSocket = MockWebSocket.instances[0]!
    rawSocket.open()
    await connectPromise

    const commandPromise = client.sendCommand('list_threads', {})
    const envelope = JSON.parse(rawSocket.sent[0]!)
    rawSocket.receive({
      id: envelope.id,
      type: 'ack',
      ok: true,
      payload: { projects: [] },
    })

    await expect(commandPromise).resolves.toEqual({ projects: [] })

    rawSocket.receive({
      type: 'workspace',
      payload: { projects: [{ project: 'yier', sessions: [] }] },
    })
    expect(events).toEqual([
      {
        type: 'workspace',
        payload: { projects: [{ project: 'yier', sessions: [] }] },
      },
    ])
  })

  it('rejects a pending command when the server returns an error envelope', async () => {
    const client = new CodexSocket('ws://codex.test/ws')
    const connectPromise = client.connect()
    const rawSocket = MockWebSocket.instances[0]!
    rawSocket.open()
    await connectPromise

    const commandPromise = client.sendCommand('send_prompt', {
      thread_id: 'thread-a',
      prompt: 'hello',
    })
    const envelope = JSON.parse(rawSocket.sent[0]!)
    rawSocket.receive({
      id: envelope.id,
      type: 'error',
      code: 'bad_request',
      message: 'prompt is required.',
    })

    await expect(commandPromise).rejects.toBeInstanceOf(CodexSocketError)
    await expect(commandPromise).rejects.toMatchObject({
      code: 'bad_request',
      message: 'prompt is required.',
    })
  })

  it('decodes negotiated gzip websocket frames', async () => {
    const client = new CodexSocket('ws://codex.test/ws')
    const events: unknown[] = []
    client.onEvent((event) => events.push(event))

    const connectPromise = client.connect()
    const rawSocket = MockWebSocket.instances[0]!
    rawSocket.open()
    await connectPromise

    const encoded = gzipSync(
      strToU8(
        JSON.stringify({
          type: 'thread_state_delta',
          payload: { thread_id: 'thread-a', turn_ids: [], turns: [], turn_patches: [] },
        }),
      ),
    )
    const frame = new Uint8Array(CODEX_GZIP_FRAME_PREFIX.length + encoded.length)
    frame.set(CODEX_GZIP_FRAME_PREFIX)
    frame.set(encoded, CODEX_GZIP_FRAME_PREFIX.length)
    rawSocket.receiveRaw(frame.buffer)

    expect(rawSocket.binaryType).toBe('arraybuffer')
    expect(events).toEqual([
      {
        type: 'thread_state_delta',
        payload: { thread_id: 'thread-a', turn_ids: [], turns: [], turn_patches: [] },
      },
    ])
  })
})
