<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, proxyRefs, ref } from 'vue'
import { useRoute } from 'vue-router'

import CodexChatPane from '../codex/components/CodexChatPane.vue'
import { useCodexEmbedStateEvents } from '../codex/composables/useCodexEmbedStateEvents'
import { useCodexWorkspace } from '../codex/composables/useCodexWorkspace'
import { codexSocketUrl } from '../codex/lib/codexSocket'
import {
  cloneEmbedMessage,
  embedPositiveInteger,
  embedRecord,
  embedText,
  normalizeEmbedMode,
  normalizeGoalStatus,
  parseEmbedCommand,
  promptSubmissionFromCommand,
  type EmbedCommand,
  type EmbedMessageType,
} from '../codex/lib/embedProtocol'
import { activeThreadTitle } from '../codex/lib/format'
import type { CodexWorkMode, JsonRecord } from '../codex/types'
import { useViewportLock } from '../composables/useViewportLock'

useViewportLock()

const route = useRoute()
const embedToken = queryText('embed_token')
const codex = proxyRefs(
  useCodexWorkspace({
    autoConnect: false,
    persistActiveThread: false,
    selectInitialThread: false,
    socketUrl: codexSocketUrl(`/api/codex/ws?embed_token=${encodeURIComponent(embedToken)}`),
  }),
)
const initError = ref('')
const isInitializing = ref(false)
const hasStarted = ref(false)
const hasConnected = ref(false)

const displayError = computed(() => initError.value || codex.errorMessage)
const pageTitle = computed(() => activeThreadTitle(codex.activeThreadState) || 'Codex embed')

function queryText(key: string) {
  const value = route.query[key]
  if (Array.isArray(value)) {
    return (value[0] ?? '').trim()
  }
  return typeof value === 'string' ? value.trim() : ''
}

function postEmbedMessage(type: EmbedMessageType, payload: JsonRecord = {}) {
  if (typeof window === 'undefined') {
    return
  }
  window.parent.postMessage(cloneEmbedMessage(type, payload), '*')
}

useCodexEmbedStateEvents({
  source: codex,
  hasStarted,
  isInitializing,
  displayError,
  postMessage: postEmbedMessage,
})

function commandMetadata(command: EmbedCommand) {
  return {
    command: command.type,
    commandId: embedText(command.commandId),
  }
}

function postCommandResult(command: EmbedCommand, ok: boolean, payload: JsonRecord = {}) {
  postEmbedMessage('yier:codex-command-result', {
    ...commandMetadata(command),
    ok,
    threadId: codex.activeThreadId,
    mode: codex.activeMode,
    ...payload,
  })
}

function postCommandError(command: EmbedCommand, message: string) {
  initError.value = message
  postEmbedMessage('yier:codex-error', {
    ...commandMetadata(command),
    message,
  })
  postCommandResult(command, false, { message })
}

function ensureEmbedToken() {
  if (embedToken) {
    return true
  }
  initError.value = 'embed_token is required.'
  postEmbedMessage('yier:codex-error', { message: initError.value })
  return false
}

async function ensureConnected() {
  if (hasConnected.value) {
    return
  }
  await codex.connect()
  if (codex.errorMessage) {
    throw new Error(codex.errorMessage)
  }
  hasConnected.value = true
}

function requireActiveThread() {
  if (!codex.activeThreadId) {
    throw new Error('An active thread is required.')
  }
  return codex.activeThreadId
}

async function callWorkspace(action: () => Promise<unknown>) {
  initError.value = ''
  codex.errorMessage = ''
  await action()
  if (codex.errorMessage) {
    throw new Error(codex.errorMessage)
  }
}

function goalRequest(command: EmbedCommand) {
  const goal = embedRecord(command.goal)
  const objective = embedText(
    typeof command.goal === 'string' ? command.goal : null,
    goal?.objective,
    command.objective,
  )
  const tokenBudget = embedPositiveInteger(
    goal?.tokenBudget,
    goal?.token_budget,
    command.tokenBudget,
    command.token_budget,
  )
  return { objective, tokenBudget }
}

async function applyRequestedMode(mode: CodexWorkMode | null) {
  if (!mode) {
    return
  }
  await callWorkspace(() => codex.setMode(mode))
}

async function applyRequestedGoal(command: EmbedCommand) {
  const { objective, tokenBudget } = goalRequest(command)
  if (!objective) {
    if (
      command.goal !== undefined ||
      command.objective !== undefined ||
      command.tokenBudget !== undefined ||
      command.token_budget !== undefined
    ) {
      throw new Error('goal objective is required.')
    }
    return
  }
  await callWorkspace(() => codex.setThreadGoal(objective, tokenBudget))
}

async function sendCommandPrompt(command: EmbedCommand) {
  const submission = promptSubmissionFromCommand(command)
  if (!submission.prompt && !submission.attachments?.length) {
    return false
  }
  await callWorkspace(() => codex.sendPrompt(submission))
  postEmbedMessage('yier:codex-prompt-sent', {
    threadId: codex.activeThreadId,
    cwd: codex.activeThreadState?.cwd ?? '',
    mode: codex.activeMode,
  })
  return true
}

async function startOrResume(command: EmbedCommand) {
  const isStart = command.type === 'yier:codex-start'
  const cwd = isStart ? embedText(command.cwd) : ''
  const threadId = isStart ? '' : embedText(command.threadId, command.thread_id)
  const modeResult = normalizeEmbedMode(command.mode)
  if (modeResult.error) {
    throw new Error(modeResult.error)
  }
  if ((isStart && !cwd) || (!isStart && !threadId)) {
    throw new Error(isStart ? 'cwd is required.' : 'thread_id is required.')
  }

  hasStarted.value = true
  isInitializing.value = true
  try {
    await ensureConnected()
    if (isStart) {
      const payload = await codex.startEmbedThread(cwd)
      if (!payload?.thread_id) {
        throw new Error(codex.errorMessage || 'Codex thread could not be created.')
      }
      await applyRequestedMode(modeResult.mode)
      await applyRequestedGoal(command)
      postEmbedMessage('yier:codex-thread-created', {
        threadId: payload.thread_id,
        cwd: codex.activeThreadState?.cwd ?? cwd,
        mode: codex.activeMode,
      })
    } else {
      const resumed = await codex.resumeEmbedThread(threadId)
      if (!resumed) {
        throw new Error(codex.errorMessage || 'Codex thread could not be resumed.')
      }
      await applyRequestedMode(modeResult.mode)
      await applyRequestedGoal(command)
      postEmbedMessage('yier:codex-thread-resumed', {
        threadId,
        cwd: codex.activeThreadState?.cwd ?? '',
        mode: codex.activeMode,
      })
    }
    await sendCommandPrompt(command)
  } finally {
    isInitializing.value = false
  }
}

async function executeParentCommand(command: EmbedCommand) {
  if (!ensureEmbedToken()) {
    postCommandResult(command, false, { message: initError.value })
    return
  }
  initError.value = ''
  codex.errorMessage = ''
  const previousThreadId = codex.activeThreadId
  try {
    if (command.type === 'yier:codex-start' || command.type === 'yier:codex-resume') {
      await startOrResume(command)
    } else {
      requireActiveThread()
      await executeActiveThreadCommand(command)
    }
    postCommandResult(command, true, {
      threadId: codex.activeThreadId || previousThreadId,
    })
  } catch (error) {
    postCommandError(command, error instanceof Error ? error.message : String(error))
  }
}

async function executeActiveThreadCommand(command: EmbedCommand) {
  switch (command.type) {
    case 'yier:codex-send-prompt':
      if (!(await sendCommandPrompt(command))) {
        throw new Error('prompt or attachments are required.')
      }
      return
    case 'yier:codex-steer-prompt': {
      const prompt = embedText(command.prompt)
      if (!prompt) throw new Error('prompt is required.')
      await callWorkspace(() => codex.steerPrompt(prompt))
      return
    }
    case 'yier:codex-enqueue-followup': {
      const prompt = embedText(command.prompt)
      if (!prompt) throw new Error('prompt is required.')
      await callWorkspace(() => codex.enqueueFollowup(prompt))
      return
    }
    case 'yier:codex-remove-followup': {
      const messageId = embedText(command.messageId, command.message_id)
      if (!messageId) throw new Error('message_id is required.')
      await callWorkspace(() => codex.removeFollowup(messageId))
      return
    }
    case 'yier:codex-interrupt-turn':
      await callWorkspace(() => codex.interruptTurn())
      return
    case 'yier:codex-compact-thread':
      await callWorkspace(() => codex.compactThread())
      return
    case 'yier:codex-set-mode': {
      const result = normalizeEmbedMode(command.mode)
      if (result.error || !result.mode) throw new Error(result.error || 'mode is required.')
      await applyRequestedMode(result.mode)
      return
    }
    case 'yier:codex-set-goal': {
      const { objective, tokenBudget } = goalRequest(command)
      if (!objective) throw new Error('goal objective is required.')
      await callWorkspace(() => codex.setThreadGoal(objective, tokenBudget))
      return
    }
    case 'yier:codex-update-goal-status': {
      const result = normalizeGoalStatus(command.status)
      if (result.error || !result.status) throw new Error(result.error)
      const status = result.status
      await callWorkspace(() => codex.updateThreadGoalStatus(status))
      return
    }
    case 'yier:codex-clear-goal':
      await callWorkspace(() => codex.clearThreadGoal())
      return
    case 'yier:codex-submit-user-input': {
      const requestId = embedText(command.requestId, command.request_id)
      const response = embedRecord(command.response)
      if (!requestId) throw new Error('request_id is required.')
      if (!response) throw new Error('response must be an object.')
      await callWorkspace(() => codex.submitUserInputResponse(requestId, response))
      return
    }
    case 'yier:codex-rename-thread': {
      const name = embedText(command.name)
      if (!name) throw new Error('name is required.')
      await callWorkspace(() => codex.renameThread(name))
      return
    }
    case 'yier:codex-archive-thread':
      await callWorkspace(() => codex.archiveThread())
      return
    case 'yier:codex-fork-thread':
      await callWorkspace(() => codex.forkThread())
      return
    default:
      throw new Error(`Unsupported iframe command: ${command.type}.`)
  }
}

function handleParentMessage(event: MessageEvent<unknown>) {
  if (event.source && event.source !== window.parent) {
    return
  }
  const command = parseEmbedCommand(event.data)
  if (command) {
    void executeParentCommand(command)
  }
}

function submitUserInputResponse(requestId: string, response: JsonRecord) {
  void codex.submitUserInputResponse(requestId, response)
}

function showEmbedError(message: string) {
  initError.value = message
  postEmbedMessage('yier:codex-error', { message })
}

onMounted(() => {
  window.addEventListener('message', handleParentMessage)
  if (ensureEmbedToken()) {
    postEmbedMessage('yier:codex-ready')
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('message', handleParentMessage)
})
</script>

<template>
  <main
    class="flex h-(--yier-viewport-height) min-h-0 flex-col overflow-hidden bg-[color:var(--app-bg)]"
  >
    <div
      class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)] items-center gap-3 border-b border-[color:var(--app-border)] bg-[color:var(--app-panel-strong)] px-4 py-2 pt-[calc(0.5rem+env(safe-area-inset-top))] max-sm:px-3"
    >
      <div class="flex min-w-0 items-center gap-2 justify-self-start">
        <span
          class="h-2.5 w-2.5 shrink-0 rounded-full"
          :class="
            codex.status === 'open'
              ? 'bg-emerald-500'
              : codex.status === 'connecting'
                ? 'bg-amber-500'
                : 'bg-red-500'
          "
        ></span>
        <span class="truncate text-sm font-semibold text-[color:var(--app-text)]">
          Codex {{ isInitializing ? 'starting' : codex.status }}
        </span>
      </div>
      <h1
        class="m-0 min-w-0 truncate text-center text-base font-semibold text-[color:var(--app-text)] max-sm:text-sm"
        :title="pageTitle"
      >
        {{ pageTitle }}
      </h1>
      <div aria-hidden="true"></div>
    </div>

    <CodexChatPane
      :active-thread-id="codex.activeThreadId"
      :active-thread-state="codex.activeThreadState"
      :active-user-input-request="codex.activeUserInputRequest"
      :active-status="codex.activeStatus"
      :active-mode="codex.activeMode"
      :queued-followups="codex.queuedFollowups"
      :socket-status="codex.status"
      :reconnect-state="codex.reconnectState"
      :error-message="displayError"
      :success-message="codex.successMessage"
      :is-command-busy="codex.isCommandBusy || isInitializing"
      :is-renaming="codex.isRenaming"
      :is-archiving="codex.isArchiving"
      :is-thread-loading="codex.isActiveThreadLoading"
      :is-active-turn-in-progress="codex.isActiveTurnInProgress"
      :list-skills="codex.listSkills"
      empty-eyebrow="Codex embed"
      :empty-title="
        isInitializing
          ? 'Starting thread'
          : hasStarted
            ? 'Waiting for thread'
            : 'Waiting for host message'
      "
      @rename-thread="codex.renameThread"
      @archive-thread="codex.archiveThread()"
      @compact-thread="codex.compactThread"
      @interrupt-turn="codex.interruptTurn"
      @set-mode="codex.setMode"
      @set-thread-goal="codex.setThreadGoal"
      @update-thread-goal-status="codex.updateThreadGoalStatus"
      @clear-thread-goal="codex.clearThreadGoal"
      @refresh="codex.refreshWorkspace"
      @submit-user-input-response="submitUserInputResponse"
      @send-prompt="codex.sendPrompt"
      @steer-prompt="codex.steerPrompt"
      @enqueue-followup="codex.enqueueFollowup"
      @remove-followup="codex.removeFollowup"
      @fork-thread="codex.forkThread"
      @copy-error="showEmbedError"
    />
  </main>
</template>
