import { ref } from 'vue'

const TARGET_SAMPLE_RATE = 16_000
const AUDIO_BUFFER_SIZE = 4096
const FINAL_RESULT_TIMEOUT_MS = 4_000

export type StreamingSpeechState = 'idle' | 'connecting' | 'recording' | 'stopping'

type SpeechServerMessage = {
  type?: string
  text?: string
  message?: string
}

type UseStreamingSpeechOptions = {
  onTranscript: (text: string, isFinal: boolean) => void
}

type PendingReady = {
  socket: WebSocket
  resolve: () => void
  reject: (error: Error) => void
}

type AudioContextConstructor = new (contextOptions?: AudioContextOptions) => AudioContext

export class PcmResampler {
  private readonly ratio: number
  private tail = new Float32Array()
  private position = 0

  constructor(inputSampleRate: number, outputSampleRate = TARGET_SAMPLE_RATE) {
    if (inputSampleRate <= 0 || outputSampleRate <= 0) {
      throw new Error('Audio sample rates must be positive.')
    }
    this.ratio = inputSampleRate / outputSampleRate
  }

  push(input: Float32Array): Float32Array {
    if (!input.length) {
      return new Float32Array()
    }

    const combined = new Float32Array(this.tail.length + input.length)
    combined.set(this.tail)
    combined.set(input, this.tail.length)
    const output: number[] = []

    while (this.position + 1 < combined.length) {
      const leftIndex = Math.floor(this.position)
      const fraction = this.position - leftIndex
      const left = combined[leftIndex] ?? 0
      const right = combined[leftIndex + 1] ?? left
      output.push(left + (right - left) * fraction)
      this.position += this.ratio
    }

    const consumed = Math.min(Math.floor(this.position), Math.max(0, combined.length - 1))
    this.tail = combined.slice(consumed)
    this.position -= consumed
    return Float32Array.from(output)
  }
}

export function appendSpeechTranscript(base: string, transcript: string): string {
  const normalizedTranscript = transcript.trim()
  if (!normalizedTranscript) {
    return base
  }
  if (!base || /\s$/.test(base)) {
    return `${base}${normalizedTranscript}`
  }

  const lastBaseCharacter = base[base.length - 1] ?? ''
  const firstTranscriptCharacter = normalizedTranscript[0] ?? ''
  if (
    isCjk(lastBaseCharacter) ||
    isCjk(firstTranscriptCharacter) ||
    /^[,.;:!?，。；：！？、)\]}]/.test(normalizedTranscript)
  ) {
    return `${base}${normalizedTranscript}`
  }
  return `${base} ${normalizedTranscript}`
}

export function useStreamingSpeech(options: UseStreamingSpeechOptions) {
  const state = ref<StreamingSpeechState>('idle')
  const error = ref('')

  let socket: WebSocket | null = null
  let mediaStream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let audioSource: MediaStreamAudioSourceNode | null = null
  let audioProcessor: ScriptProcessorNode | null = null
  let silentOutput: GainNode | null = null
  let pendingReady: PendingReady | null = null
  let finalResultTimer: ReturnType<typeof setTimeout> | null = null
  let operationId = 0

  async function start() {
    if (state.value !== 'idle') {
      return
    }

    const currentOperation = ++operationId
    state.value = 'connecting'
    error.value = ''

    try {
      audioContext = createAudioContext()
      const resumePromise = audioContext.resume()
      await connectSocket()
      await resumePromise
      if (operationId !== currentOperation) {
        return
      }
      await startMicrophone(audioContext)
      if (operationId !== currentOperation) {
        cleanupAudio()
        return
      }
      state.value = 'recording'
    } catch (reason) {
      if (operationId !== currentOperation) {
        return
      }
      error.value = speechErrorMessage(reason)
      cancelConnection()
      cleanupAudio()
      state.value = 'idle'
    }
  }

  function stop() {
    if (state.value === 'idle') {
      return
    }
    if (state.value === 'connecting') {
      operationId += 1
      cancelConnection()
      cleanupAudio()
      state.value = 'idle'
      return
    }
    if (state.value === 'stopping') {
      return
    }

    state.value = 'stopping'
    cleanupAudio()
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'finish' }))
      finalResultTimer = setTimeout(() => {
        error.value = 'Timed out while finishing voice input.'
        closeSocket()
        state.value = 'idle'
      }, FINAL_RESULT_TIMEOUT_MS)
      return
    }
    closeSocket()
    state.value = 'idle'
  }

  function clearError() {
    error.value = ''
  }

  function dispose() {
    operationId += 1
    cleanupAudio()
    cancelConnection()
    state.value = 'idle'
  }

  function connectSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const nextSocket = new WebSocket(speechWebSocketUrl())
      nextSocket.binaryType = 'arraybuffer'
      socket = nextSocket
      pendingReady = { socket: nextSocket, resolve, reject }

      nextSocket.addEventListener('message', handleServerMessage)
      nextSocket.addEventListener('error', () => {
        if (pendingReady?.socket === nextSocket) {
          pendingReady.reject(new Error('Unable to connect to voice recognition.'))
          pendingReady = null
        }
      })
      nextSocket.addEventListener('close', () => {
        if (socket !== nextSocket) {
          return
        }
        const wasActive = state.value === 'recording'
        if (pendingReady?.socket === nextSocket) {
          pendingReady.reject(new Error('Voice recognition connection closed.'))
          pendingReady = null
        }
        clearFinalResultTimer()
        cleanupAudio()
        if (wasActive) {
          error.value = 'Voice recognition connection closed.'
        }
        socket = null
        state.value = 'idle'
      })
    })
  }

  function handleServerMessage(event: MessageEvent) {
    if (event.currentTarget !== socket) {
      return
    }
    let message: SpeechServerMessage
    try {
      message = JSON.parse(String(event.data)) as SpeechServerMessage
    } catch {
      return
    }

    if (message.type === 'ready') {
      pendingReady?.resolve()
      pendingReady = null
      return
    }
    if (message.type === 'partial' || message.type === 'final') {
      options.onTranscript(message.text ?? '', message.type === 'final')
      if (message.type === 'final') {
        clearFinalResultTimer()
        state.value = 'idle'
      }
      return
    }
    if (message.type === 'error') {
      const messageText = message.message?.trim() || 'Voice recognition failed.'
      pendingReady?.reject(new Error(messageText))
      pendingReady = null
      error.value = messageText
      clearFinalResultTimer()
      cleanupAudio()
      state.value = 'idle'
    }
  }

  async function startMicrophone(context: AudioContext) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Microphone access is not supported in this browser.')
    }

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    })

    const resampler = new PcmResampler(context.sampleRate)
    audioSource = context.createMediaStreamSource(mediaStream)
    audioProcessor = context.createScriptProcessor(AUDIO_BUFFER_SIZE, 1, 1)
    silentOutput = context.createGain()
    silentOutput.gain.value = 0
    audioProcessor.addEventListener('audioprocess', (event: AudioProcessingEvent) => {
      const input = event.inputBuffer.getChannelData(0)
      const samples = resampler.push(input)
      if (samples.length && socket?.readyState === WebSocket.OPEN) {
        socket.send(samples)
      }
    })
    audioSource.connect(audioProcessor)
    audioProcessor.connect(silentOutput)
    silentOutput.connect(context.destination)
  }

  function cleanupAudio() {
    if (audioProcessor) {
      audioProcessor.disconnect()
      audioProcessor = null
    }
    if (audioSource) {
      audioSource.disconnect()
      audioSource = null
    }
    if (silentOutput) {
      silentOutput.disconnect()
      silentOutput = null
    }
    mediaStream?.getTracks().forEach((track) => track.stop())
    mediaStream = null
    if (audioContext) {
      void audioContext.close()
      audioContext = null
    }
  }

  function cancelConnection() {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'cancel' }))
    }
    closeSocket()
  }

  function closeSocket() {
    pendingReady?.reject(new Error('Voice input cancelled.'))
    pendingReady = null
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close()
    }
    socket = null
    clearFinalResultTimer()
  }

  function clearFinalResultTimer() {
    if (finalResultTimer) {
      clearTimeout(finalResultTimer)
      finalResultTimer = null
    }
  }

  return {
    state,
    error,
    start,
    stop,
    clearError,
    dispose,
  }
}

function createAudioContext(): AudioContext {
  const browserWindow = window as typeof window & {
    webkitAudioContext?: AudioContextConstructor
  }
  const Context = browserWindow.AudioContext ?? browserWindow.webkitAudioContext
  if (!Context) {
    throw new Error('Voice input is not supported in this browser.')
  }
  return new Context({ latencyHint: 'interactive' })
}

function speechWebSocketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/speech/ws`
}

function speechErrorMessage(reason: unknown): string {
  if (reason instanceof DOMException && reason.name === 'NotAllowedError') {
    return 'Microphone access was denied.'
  }
  return reason instanceof Error ? reason.message : 'Unable to start voice input.'
}

function isCjk(character: string): boolean {
  return /[\u3400-\u9fff]/.test(character)
}
