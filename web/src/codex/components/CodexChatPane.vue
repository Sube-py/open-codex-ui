<script setup lang="ts">
import { computed, ref } from 'vue'

import CodexComposer from './CodexComposer.vue'
import CodexConversation from './CodexConversation.vue'
import CodexRequestPanel from './CodexRequestPanel.vue'
import CodexThreadToolbar from './CodexThreadToolbar.vue'
import type { CodexReconnectState } from '../lib/codexReconnect'
import type {
  CodexConversationState,
  CodexPendingRequest,
  CodexPromptSubmission,
  CodexQueuedFollowup,
  CodexSkillSummary,
  CodexSocketStatus,
  CodexThreadGoalStatus,
  CodexWorkMode,
  JsonRecord,
} from '../types'

const composerText = ref('')

const props = defineProps<{
  activeThreadId: string
  activeThreadState: CodexConversationState | null
  activeUserInputRequest: CodexPendingRequest | null
  activeStatus: string
  activeMode: CodexWorkMode
  queuedFollowups: CodexQueuedFollowup[]
  socketStatus: CodexSocketStatus
  reconnectState: CodexReconnectState
  errorMessage?: string
  successMessage?: string
  isCommandBusy?: boolean
  isRenaming?: boolean
  isArchiving?: boolean
  isThreadLoading?: boolean
  isActiveTurnInProgress?: boolean
  emptyEyebrow?: string
  emptyTitle?: string
  showEmptyHeader?: boolean
  listSkills?: () => Promise<CodexSkillSummary[]>
}>()

const emit = defineEmits<{
  renameThread: [name: string]
  archiveThread: []
  compactThread: []
  interruptTurn: []
  setMode: [mode: CodexWorkMode]
  setThreadGoal: [objective: string, tokenBudget?: number | null]
  updateThreadGoalStatus: [status: CodexThreadGoalStatus]
  clearThreadGoal: []
  refresh: []
  submitUserInputResponse: [requestId: string, response: JsonRecord]
  sendPrompt: [submission: CodexPromptSubmission]
  steerPrompt: [prompt: string]
  enqueueFollowup: [prompt: string]
  removeFollowup: [messageId: string]
  forkThread: [threadId: string]
  copyError: [message: string]
}>()

function submitUserInputResponse(requestId: string, response: JsonRecord) {
  emit('submitUserInputResponse', requestId, response)
}

const gitInfo = computed(() => {
  const value = props.activeThreadState?.gitInfo
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonRecord) : null
})
const gitBranch = computed(() => stringValue(gitInfo.value?.branch))
const gitSha = computed(() => stringValue(gitInfo.value?.sha))
const gitOriginUrl = computed(() =>
  stringValue(gitInfo.value?.originUrl ?? gitInfo.value?.origin_url),
)
const gitShortSha = computed(() => (gitSha.value ? gitSha.value.slice(0, 7) : ''))
const reconnectNotice = computed(() => {
  const state = props.reconnectState
  if (state.phase === 'offline') {
    return "You're offline. Reconnection will resume when online."
  }
  if (state.phase === 'connecting') {
    return `Connection lost. Reconnecting (attempt ${state.attempt})...`
  }
  if (state.phase === 'scheduled') {
    const delay = state.nextDelayMs == null ? '' : ` in ${formatReconnectDelay(state.nextDelayMs)}`
    return `Connection lost. Reconnecting (attempt ${state.attempt})${delay}...`
  }
  return ''
})

function formatReconnectDelay(delayMs: number) {
  const seconds = Math.max(Math.ceil(delayMs / 1_000), 1)
  return `${seconds}s`
}

function stringValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}
</script>

<template>
  <section class="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
    <CodexThreadToolbar
      v-if="false && activeThreadId"
      :thread-id="activeThreadId"
      :state="activeThreadState"
      :status="activeStatus"
      :busy="isCommandBusy"
      :renaming="isRenaming"
      @rename-thread="emit('renameThread', $event)"
    />
    <header
      v-else-if="showEmptyHeader !== false"
      class="grid gap-1 border-b border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-4 max-sm:px-3"
    >
      <p
        class="m-0 text-xs font-bold uppercase tracking-[0.14em] text-[color:var(--app-text-soft)]"
      >
        {{ emptyEyebrow || 'Codex workspace' }}
      </p>
      <h2 class="m-0 text-xl font-semibold text-[color:var(--app-text)]">
        {{ emptyTitle || 'Select or start a thread' }}
      </h2>
    </header>

    <div v-if="errorMessage || successMessage" class="grid gap-2 px-4 pt-3 max-sm:px-3">
      <p
        v-if="errorMessage"
        class="m-0 rounded-lg border border-[color:var(--app-danger-border)] bg-[color:var(--app-danger-bg)] px-3 py-2 text-sm font-semibold text-[color:var(--app-danger-text)]"
      >
        {{ errorMessage }}
      </p>
      <p
        v-else-if="successMessage"
        class="m-0 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-success-bg)] px-3 py-2 text-sm font-semibold text-[color:var(--app-success-text)]"
      >
        {{ successMessage }}
      </p>
    </div>

    <div
      v-if="gitInfo"
      class="flex min-w-0 items-center gap-2 border-b border-[color:var(--app-border)] bg-[color:var(--app-surface-translucent)] px-4 py-1.5 text-xs text-[color:var(--app-text-soft)] max-sm:px-3"
      data-codex-git-info
    >
      <i class="pi pi-code-branch shrink-0 text-[0.68rem]"></i>
      <span v-if="gitBranch" class="min-w-0 truncate font-semibold text-[color:var(--app-text)]">
        {{ gitBranch }}
      </span>
      <code
        v-if="gitShortSha"
        class="shrink-0 rounded bg-[color:var(--app-surface-muted)] px-1.5 py-0.5 text-[0.68rem]"
      >
        {{ gitShortSha }}
      </code>
      <span v-if="gitOriginUrl" class="min-w-0 truncate" :title="gitOriginUrl">
        {{ gitOriginUrl }}
      </span>
    </div>

    <div class="relative flex min-h-0 min-w-0 flex-1 flex-col">
      <CodexConversation
        :state="activeThreadState"
        @fork-thread="emit('forkThread', $event)"
        @copy-error="emit('copyError', $event)"
      />
      <div
        v-if="isThreadLoading"
        class="absolute inset-0 z-10 grid place-items-center bg-[color:var(--app-surface-overlay)] backdrop-blur-[2px]"
        data-codex-thread-loading
      >
        <div
          class="inline-flex items-center gap-2 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-panel-strong)] px-3 py-2 text-sm font-semibold text-[color:var(--app-text-soft)] shadow-[0_14px_34px_var(--app-shadow-color)]"
        >
          <i class="pi pi-spinner pi-spin text-[0.8rem]"></i>
          <span>Loading conversation</span>
        </div>
      </div>
    </div>

    <div
      v-if="reconnectNotice"
      class="flex min-w-0 items-center gap-2 border-t border-[color:var(--app-border)] bg-[color:var(--app-warning-bg)] px-4 py-2 text-xs text-[color:var(--app-warning-text)] max-sm:px-3"
      role="status"
      aria-live="polite"
      data-codex-reconnect-notice
      :data-codex-reconnect-phase="reconnectState.phase"
    >
      <i
        class="pi shrink-0 text-[0.72rem]"
        :class="reconnectState.phase === 'connecting' ? 'pi-spinner pi-spin' : 'pi-wifi'"
        aria-hidden="true"
      ></i>
      <span class="min-w-0 [overflow-wrap:anywhere]">{{ reconnectNotice }}</span>
    </div>

    <CodexRequestPanel
      :request="activeUserInputRequest"
      :disabled="isCommandBusy"
      @submit-response="submitUserInputResponse"
    />

    <CodexComposer
      v-if="!activeUserInputRequest"
      v-model="composerText"
      :disabled="socketStatus !== 'open' || isThreadLoading"
      :busy="isCommandBusy"
      :is-working="isActiveTurnInProgress"
      :mode="activeMode"
      :queued-followups="queuedFollowups"
      :state="activeThreadState"
      :list-skills="listSkills"
      @send-prompt="emit('sendPrompt', $event)"
      @steer-prompt="emit('steerPrompt', $event)"
      @enqueue-followup="emit('enqueueFollowup', $event)"
      @remove-followup="emit('removeFollowup', $event)"
      @interrupt-turn="emit('interruptTurn')"
      @set-mode="emit('setMode', $event)"
      @set-thread-goal="(objective, tokenBudget) => emit('setThreadGoal', objective, tokenBudget)"
      @update-thread-goal-status="emit('updateThreadGoalStatus', $event)"
      @clear-thread-goal="emit('clearThreadGoal')"
      @compact-thread="emit('compactThread')"
      @fork-thread="activeThreadId ? emit('forkThread', activeThreadId) : undefined"
    />
  </section>
</template>
