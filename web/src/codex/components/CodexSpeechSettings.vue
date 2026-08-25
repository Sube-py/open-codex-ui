<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Message from 'primevue/message'
import Select from 'primevue/select'

import { apiGet, apiPost, apiPut } from '../../lib/api'
import type {
  SaveSpeechConfigRequest,
  SelectDirectoryResponse,
  SpeechModelDownloadRequest,
  SpeechModelDownloadResponse,
  SpeechConfigResponse,
} from '../../types/api'

const props = defineProps<{
  busy?: boolean
}>()

const speechConfig = ref<SpeechConfigResponse | null>(null)
const modelDir = ref('')
const provider = ref('cpu')
const numThreads = ref(2)
const isLoading = ref(true)
const isSaving = ref(false)
const isPickingDirectory = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const downloadProxy = ref('')
const downloadStatus = ref<SpeechModelDownloadResponse>({
  state: 'idle',
  downloaded_bytes: 0,
  total_bytes: null,
  error: '',
  model_dir: '',
})
let downloadPollTimer: number | undefined
const providerOptions = [
  { label: 'CPU', value: 'cpu' },
  { label: 'Core ML', value: 'coreml' },
  { label: 'CUDA', value: 'cuda' },
]

const modelDirManagedByEnvironment = computed(
  () => speechConfig.value?.model_dir_source === 'environment',
)
const providerManagedByEnvironment = computed(
  () => speechConfig.value?.provider_source === 'environment',
)
const numThreadsManagedByEnvironment = computed(
  () => speechConfig.value?.num_threads_source === 'environment',
)
const isBusy = computed(
  () =>
    props.busy ||
    isLoading.value ||
    isSaving.value ||
    isPickingDirectory.value ||
    downloadStatus.value.state === 'downloading',
)
const modelReady = computed(() => speechConfig.value?.status === 'ready')
const isDownloading = computed(() => downloadStatus.value.state === 'downloading')
const downloadPercentage = computed(() => {
  const { downloaded_bytes: downloaded, total_bytes: total } = downloadStatus.value
  if (!total) return 0
  return Math.min(100, Math.round((downloaded / total) * 100))
})
const canDownloadModel = computed(
  () =>
    !modelReady.value &&
    !modelDirManagedByEnvironment.value &&
    Boolean(downloadStatus.value.model_dir) &&
    modelDir.value === downloadStatus.value.model_dir,
)

function resetDraft(config: SpeechConfigResponse) {
  speechConfig.value = config
  modelDir.value = config.model_dir
  provider.value = config.provider
  numThreads.value = config.num_threads
}

async function loadSpeechConfig() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    resetDraft(await apiGet<SpeechConfigResponse>('/api/config/speech'))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    isLoading.value = false
  }
}

async function loadDownloadStatus() {
  try {
    downloadStatus.value = await apiGet<SpeechModelDownloadResponse>(
      '/api/config/speech/model-download',
    )
    if (downloadStatus.value.state === 'error' && downloadStatus.value.error) {
      errorMessage.value = downloadStatus.value.error
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
}

function scheduleDownloadPoll() {
  if (downloadPollTimer !== undefined) {
    window.clearTimeout(downloadPollTimer)
  }
  if (!isDownloading.value) return
  downloadPollTimer = window.setTimeout(async () => {
    await loadDownloadStatus()
    if (downloadStatus.value.state === 'ready') {
      await loadSpeechConfig()
      successMessage.value = 'Voice model is ready.'
    }
    scheduleDownloadPoll()
  }, 500)
}

async function downloadModel() {
  if (!canDownloadModel.value || isBusy.value) return
  errorMessage.value = ''
  successMessage.value = ''
  const payload = {
    proxy: downloadProxy.value.trim() || null,
  } satisfies SpeechModelDownloadRequest
  try {
    downloadStatus.value = await apiPost<SpeechModelDownloadResponse>(
      '/api/config/speech/model-download',
      payload,
    )
    scheduleDownloadPoll()
    if (downloadStatus.value.state === 'ready') {
      await loadSpeechConfig()
      successMessage.value = 'Voice model is ready.'
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
}

async function saveSpeechConfig() {
  errorMessage.value = ''
  successMessage.value = ''
  if (!speechConfig.value) {
    return
  }
  if (!modelDir.value.trim()) {
    errorMessage.value = 'Model directory is required.'
    return
  }
  if (!provider.value) {
    errorMessage.value = 'Execution provider is required.'
    return
  }

  isSaving.value = true
  const payload = {
    model_dir: modelDir.value.trim(),
    provider: provider.value,
    num_threads: numThreads.value,
  } satisfies SaveSpeechConfigRequest
  try {
    resetDraft(await apiPut<SpeechConfigResponse>('/api/config/speech', payload))
    successMessage.value = 'Voice settings saved.'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    isSaving.value = false
  }
}

async function pickModelDirectory() {
  isPickingDirectory.value = true
  errorMessage.value = ''
  try {
    const response = await apiPost<SelectDirectoryResponse>('/api/system/select-directory', {
      initial_path: modelDir.value,
    })
    if (response.selected) {
      modelDir.value = response.project_path
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    isPickingDirectory.value = false
  }
}

onMounted(() => {
  void loadSpeechConfig()
  void loadDownloadStatus().then(scheduleDownloadPoll)
})

onUnmounted(() => {
  if (downloadPollTimer !== undefined) {
    window.clearTimeout(downloadPollTimer)
  }
})
</script>

<template>
  <section class="grid gap-5" data-codex-speech-settings>
    <div class="flex items-center justify-between gap-3 border-b border-[color:var(--app-border)] pb-3">
      <h2 class="m-0 text-base font-semibold text-[color:var(--app-text)]">Voice recognition</h2>
      <span
        class="shrink-0 rounded px-1.5 py-0.5 text-[0.68rem] font-semibold"
        :class="
          modelReady
            ? 'bg-[color:var(--app-success-bg)] text-[color:var(--app-success-text)]'
            : 'bg-[color:var(--app-warning-bg)] text-[color:var(--app-warning-text)]'
        "
        data-codex-speech-model-status
      >
        {{ modelReady ? 'Ready' : 'Model missing' }}
      </span>
    </div>

    <Message v-if="errorMessage" severity="error" :closable="false" data-codex-speech-error>
      {{ errorMessage }}
    </Message>
    <Message v-if="successMessage" severity="success" :closable="false" data-codex-speech-success>
      {{ successMessage }}
    </Message>
    <Message
      v-if="speechConfig?.detail"
      :severity="modelReady ? 'success' : 'warn'"
      :closable="false"
      data-codex-speech-model-detail
    >
      {{ speechConfig.detail }}
    </Message>

    <div
      v-if="canDownloadModel"
      class="grid gap-3 rounded-md border border-[color:var(--app-border)] bg-[color:var(--app-surface-muted)] p-3"
      data-codex-speech-download
    >
      <div class="flex items-center justify-between gap-3">
        <div class="grid gap-1">
          <span class="text-sm font-semibold text-[color:var(--app-text)]">Download standard model</span>
          <span class="text-xs text-[color:var(--app-text-muted)]">
            Downloads the bilingual sherpa-onnx model to the default model directory.
          </span>
        </div>
        <Button
          label="Download"
          icon="pi pi-download"
          :loading="isDownloading"
          :disabled="isBusy"
          data-codex-download-speech-model
          @click="downloadModel"
        />
      </div>
      <InputText
        v-model="downloadProxy"
        class="w-full"
        placeholder="HTTP proxy (optional), e.g. http://127.0.0.1:7890"
        :disabled="isBusy"
        autocomplete="url"
        data-codex-speech-download-proxy
      />
      <div v-if="isDownloading" class="grid gap-1.5" data-codex-speech-download-progress>
        <div class="h-1.5 overflow-hidden rounded-full bg-[color:var(--app-border)]">
          <div
            class="h-full rounded-full bg-[color:var(--app-accent)] transition-[width] duration-300"
            :class="downloadStatus.total_bytes ? '' : 'w-1/3 animate-pulse'"
            :style="downloadStatus.total_bytes ? { width: `${downloadPercentage}%` } : undefined"
          ></div>
        </div>
        <span class="text-xs text-[color:var(--app-text-muted)]">
          {{ downloadStatus.total_bytes ? `${downloadPercentage}% downloaded` : 'Downloading model...' }}
        </span>
      </div>
    </div>

    <div class="grid gap-2">
      <div class="flex items-center justify-between gap-3">
        <label for="codex-speech-model-dir" class="text-sm font-semibold text-[color:var(--app-text)]">
          Model directory
        </label>
        <span
          v-if="modelDirManagedByEnvironment"
          class="rounded bg-[color:var(--app-neutral-status-bg)] px-1.5 py-0.5 text-[0.68rem] font-semibold text-[color:var(--app-neutral-status-text)]"
        >
          Environment
        </span>
      </div>
      <div class="flex min-w-0 gap-1.5">
        <InputText
          id="codex-speech-model-dir"
          v-model="modelDir"
          class="min-w-0 flex-1"
          :disabled="isBusy || modelDirManagedByEnvironment"
          autocomplete="off"
          data-codex-speech-model-dir
        />
        <Button
          v-tooltip.top="'Choose model directory'"
          icon="pi pi-folder-open"
          severity="secondary"
          outlined
          :loading="isPickingDirectory"
          :disabled="isBusy || modelDirManagedByEnvironment"
          aria-label="Choose model directory"
          data-codex-select-speech-model-dir
          @click="pickModelDirectory"
        />
      </div>
    </div>

    <div class="grid gap-2">
      <div class="flex items-center justify-between gap-3">
        <label for="codex-speech-provider" class="text-sm font-semibold text-[color:var(--app-text)]">
          Execution provider
        </label>
        <span
          v-if="providerManagedByEnvironment"
          class="rounded bg-[color:var(--app-neutral-status-bg)] px-1.5 py-0.5 text-[0.68rem] font-semibold text-[color:var(--app-neutral-status-text)]"
        >
          Environment
        </span>
      </div>
      <Select
        id="codex-speech-provider"
        v-model="provider"
        :options="providerOptions"
        option-label="label"
        option-value="value"
        class="w-full"
        :disabled="isBusy || providerManagedByEnvironment"
        data-codex-speech-provider
      />
    </div>

    <div class="grid gap-2">
      <div class="flex items-center justify-between gap-3">
        <label for="codex-speech-threads" class="text-sm font-semibold text-[color:var(--app-text)]">
          Recognition threads
        </label>
        <span
          v-if="numThreadsManagedByEnvironment"
          class="rounded bg-[color:var(--app-neutral-status-bg)] px-1.5 py-0.5 text-[0.68rem] font-semibold text-[color:var(--app-neutral-status-text)]"
        >
          Environment
        </span>
      </div>
      <input
        id="codex-speech-threads"
        v-model.number="numThreads"
        type="number"
        min="1"
        step="1"
        class="h-10 w-full rounded-md border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-3 text-sm text-[color:var(--app-text)] outline-none transition focus:border-[color:var(--app-focus)] disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="isBusy || numThreadsManagedByEnvironment"
        data-codex-speech-threads
      />
    </div>

    <div class="flex items-center justify-end gap-1">
      <Button
        v-tooltip.top="'Refresh model status'"
        icon="pi pi-refresh"
        severity="secondary"
        text
        rounded
        :disabled="isBusy"
        aria-label="Refresh model status"
        data-codex-refresh-speech-config
        @click="loadSpeechConfig"
      />
      <Button
        label="Save"
        icon="pi pi-save"
        :loading="isSaving"
        :disabled="isBusy || !speechConfig"
        data-codex-save-speech
        @click="saveSpeechConfig"
      />
    </div>
  </section>
</template>
