import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  appendSpeechTranscript,
  PcmResampler,
  useStreamingSpeech,
} from '../composables/useStreamingSpeech'

class MockWebSocket extends EventTarget {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static instances: MockWebSocket[] = []

  readonly sent: unknown[] = []
  readyState = MockWebSocket.OPEN
  binaryType = ''

  constructor(readonly url: string) {
    super()
    MockWebSocket.instances.push(this)
  }

  send(payload: unknown) {
    this.sent.push(payload)
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
    this.dispatchEvent(new Event('close'))
  }

  serverMessage(message: object) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(message) }))
  }
}

class MockAudioNode {
  connect = vi.fn()
  disconnect = vi.fn()
}

class MockAudioProcessor extends EventTarget {
  connect = vi.fn()
  disconnect = vi.fn()
}

class MockAudioContext {
  static lastProcessor: MockAudioProcessor | null = null

  readonly sampleRate = 48_000
  readonly destination = new MockAudioNode()
  readonly resume = vi.fn().mockResolvedValue(undefined)
  readonly close = vi.fn().mockResolvedValue(undefined)

  createMediaStreamSource() {
    return new MockAudioNode()
  }

  createScriptProcessor() {
    const processor = new MockAudioProcessor()
    MockAudioContext.lastProcessor = processor
    return processor
  }

  createGain() {
    return Object.assign(new MockAudioNode(), { gain: { value: 1 } })
  }
}

describe('streaming speech utilities', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    MockAudioContext.lastProcessor = null
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('AudioContext', MockAudioContext)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('resamples consecutive chunks without dropping their boundary', () => {
    const resampler = new PcmResampler(48_000, 16_000)

    expect(Array.from(resampler.push(Float32Array.from([0, 1, 2, 3, 4, 5])))).toEqual([0, 3])
    expect(Array.from(resampler.push(Float32Array.from([6, 7, 8, 9, 10, 11])))).toEqual([6, 9])
  })

  it('keeps Chinese transcript text compact and separates English words', () => {
    expect(appendSpeechTranscript('请检查', '这个文件')).toBe('请检查这个文件')
    expect(appendSpeechTranscript('Review', 'this file')).toBe('Review this file')
    expect(appendSpeechTranscript('Review ', 'this file')).toBe('Review this file')
    expect(appendSpeechTranscript('完成', '。')).toBe('完成。')
  })

  it('streams resampled audio and applies partial and final transcripts', async () => {
    const stopTrack = vi.fn()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: stopTrack }],
        }),
      },
    })
    const onTranscript = vi.fn()
    const speech = useStreamingSpeech({ onTranscript })

    const startPromise = speech.start()
    const socket = MockWebSocket.instances[0]!
    socket.serverMessage({ type: 'ready' })
    await startPromise

    expect(socket.url).toContain('/api/speech/ws')
    expect(speech.state.value).toBe('recording')

    const audioEvent = new Event('audioprocess')
    Object.defineProperty(audioEvent, 'inputBuffer', {
      value: {
        getChannelData: () => Float32Array.from([0, 1, 2, 3, 4, 5]),
      },
    })
    MockAudioContext.lastProcessor?.dispatchEvent(audioEvent)
    expect(socket.sent[0]).toBeInstanceOf(Float32Array)

    socket.serverMessage({ type: 'partial', text: '你好' })
    expect(onTranscript).toHaveBeenLastCalledWith('你好', false)

    speech.stop()
    expect(socket.sent).toContain(JSON.stringify({ type: 'finish' }))
    expect(stopTrack).toHaveBeenCalled()

    socket.serverMessage({ type: 'final', text: '你好世界' })
    expect(onTranscript).toHaveBeenLastCalledWith('你好世界', true)
    expect(speech.state.value).toBe('idle')
    speech.dispose()
  })
})
