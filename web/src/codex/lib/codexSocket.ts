import type {
  CodexAckEnvelope,
  CodexClientCommand,
  CodexErrorEnvelope,
  CodexServerEvent,
  CodexSocketMessage,
  CodexSocketStatus,
  JsonRecord,
} from '../types'
import { gunzipSync, strFromU8, strToU8 } from 'fflate'

export const CODEX_GZIP_FRAME_PREFIX = strToU8('YIER_GZIP_V1\0')

export class CodexSocketError extends Error {
  constructor(
    message: string,
    readonly code = 'socket_error',
  ) {
    super(message)
  }
}

type PendingCommand = {
  resolve: (payload: unknown) => void
  reject: (error: Error) => void
}

export type CodexSocketEventListener = (
  event: CodexServerEvent | CodexErrorEnvelope,
) => void

export type CodexSocketStatusListener = (status: CodexSocketStatus) => void

function createCommandId() {
  const cryptoApi = globalThis.crypto
  if (typeof cryptoApi?.randomUUID === 'function') {
    return cryptoApi.randomUUID()
  }
  return `codex-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function defaultSocketUrl(path = '/api/codex/ws') {
  if (typeof window === 'undefined') {
    return path
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

export function codexSocketUrl(path = '/api/codex/ws') {
  return defaultSocketUrl(path)
}

function binarySocketData(raw: unknown) {
  if (raw instanceof ArrayBuffer) {
    return new Uint8Array(raw)
  }
  if (ArrayBuffer.isView(raw)) {
    return new Uint8Array(raw.buffer, raw.byteOffset, raw.byteLength)
  }
  return null
}

function hasPrefix(value: Uint8Array, prefix: Uint8Array) {
  return value.length >= prefix.length && prefix.every((byte, index) => value[index] === byte)
}

function socketMessageText(raw: unknown) {
  if (typeof raw === 'string') {
    return raw
  }
  const binary = binarySocketData(raw)
  if (!binary || !hasPrefix(binary, CODEX_GZIP_FRAME_PREFIX)) {
    return ''
  }
  return strFromU8(gunzipSync(binary.subarray(CODEX_GZIP_FRAME_PREFIX.length)))
}

function parseSocketMessage(raw: unknown): CodexSocketMessage | null {
  try {
    const text = socketMessageText(raw)
    if (!text) {
      return null
    }
    const parsed = JSON.parse(text) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return null
    }
    return parsed as CodexSocketMessage
  } catch {
    return null
  }
}

function isAck(message: CodexSocketMessage): message is CodexAckEnvelope {
  return message.type === 'ack'
}

function isError(message: CodexSocketMessage): message is CodexErrorEnvelope {
  return message.type === 'error'
}

export class CodexSocket {
  private socket: WebSocket | null = null
  private connectPromise: Promise<void> | null = null
  private readonly pending = new Map<string, PendingCommand>()
  private readonly eventListeners = new Set<CodexSocketEventListener>()
  private readonly statusListeners = new Set<CodexSocketStatusListener>()

  constructor(private readonly url = defaultSocketUrl()) {}

  onEvent(listener: CodexSocketEventListener) {
    this.eventListeners.add(listener)
    return () => this.eventListeners.delete(listener)
  }

  onStatus(listener: CodexSocketStatusListener) {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  async connect() {
    if (this.socket?.readyState === WebSocket.OPEN) {
      return
    }
    if (this.connectPromise) {
      return this.connectPromise
    }

    this.setStatus('connecting')
    this.socket = new WebSocket(this.url)
    this.socket.binaryType = 'arraybuffer'
    this.connectPromise = new Promise<void>((resolve, reject) => {
      const socket = this.socket
      if (!socket) {
        reject(new CodexSocketError('Codex socket could not be created.'))
        return
      }

      let opened = false

      socket.onopen = () => {
        opened = true
        this.connectPromise = null
        this.setStatus('open')
        resolve()
      }

      socket.onerror = () => {
        const error = new CodexSocketError('Codex socket connection failed.')
        this.setStatus('error')
        if (!opened) {
          this.connectPromise = null
          reject(error)
        }
      }

      socket.onclose = () => {
        this.connectPromise = null
        this.socket = null
        this.rejectPending(new CodexSocketError('Codex socket closed.', 'socket_closed'))
        this.setStatus(opened ? 'closed' : 'error')
      }

      socket.onmessage = (message) => {
        this.handleMessage(message.data)
      }
    })

    return this.connectPromise
  }

  close() {
    const socket = this.socket
    this.socket = null
    this.connectPromise = null
    this.rejectPending(new CodexSocketError('Codex socket closed.', 'socket_closed'))
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      socket.close()
    }
    this.setStatus('closed')
  }

  sendCommand<TPayload = unknown>(
    type: CodexClientCommand,
    payload: JsonRecord = {},
  ): Promise<TPayload> {
    const socket = this.socket
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new CodexSocketError('Codex socket is not connected.'))
    }

    const id = createCommandId()
    const envelope = { id, type, payload }
    socket.send(JSON.stringify(envelope))

    return new Promise<TPayload>((resolve, reject) => {
      this.pending.set(id, {
        resolve: (value) => resolve(value as TPayload),
        reject,
      })
    })
  }

  private handleMessage(raw: unknown) {
    const message = parseSocketMessage(raw)
    if (!message) {
      return
    }

    if (isAck(message)) {
      const pending = this.pending.get(message.id)
      if (pending) {
        this.pending.delete(message.id)
        pending.resolve(message.payload)
      }
      return
    }

    if (isError(message) && message.id) {
      const pending = this.pending.get(message.id)
      if (pending) {
        this.pending.delete(message.id)
        pending.reject(new CodexSocketError(message.message, message.code))
        return
      }
    }

    for (const listener of this.eventListeners) {
      listener(message as CodexServerEvent | CodexErrorEnvelope)
    }
  }

  private rejectPending(error: Error) {
    for (const pending of this.pending.values()) {
      pending.reject(error)
    }
    this.pending.clear()
  }

  private setStatus(status: CodexSocketStatus) {
    for (const listener of this.statusListeners) {
      listener(status)
    }
  }
}
