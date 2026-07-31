import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { apiGet } from '../../lib/api'
import { CodexReconnectController, type CodexReconnectState } from '../lib/codexReconnect'
import { CodexSocket } from '../lib/codexSocket'
import type { CodexTurnCache } from '../lib/codexTurnCache'
import { CodexTurnSync, normalizeThreadDeltaPayload } from '../lib/codexTurnSync'
import { isRecord, isWorkingStatus } from '../lib/format'
import type {
  CodexCollaborationMode,
  CodexConversationState,
  CodexNativeSessionSummary,
  CodexPendingRequest,
  CodexPromptSubmission,
  CodexQueuedFollowup,
  CodexRemoteConnectionsResponse,
  CodexSkillSummary,
  CodexSocketStatus,
  CodexThreadGoal,
  CodexThreadGoalStatus,
  CodexThreadCreateResponse,
  CodexThreadForkResponse,
  CodexThreadStateDeltaPayload,
  CodexThreadStatePayload,
  CodexWorkMode,
  CodexWorkspaceResponse,
  JsonRecord,
} from '../types'

const ACTIVE_THREAD_STORAGE_KEY = 'yier.codex.active-thread-id'
const PLAN_IMPLEMENTATION_REQUEST_METHOD = 'item/plan/requestImplementation'
const IMPLEMENT_PLAN_PROMPT_PREFIX = 'PLEASE IMPLEMENT THIS PLAN:'

export interface CodexRealtimeClient {
  connect: () => Promise<void>
  close: () => void
  sendCommand: <TPayload = unknown>(
    type: Parameters<CodexSocket['sendCommand']>[0],
    payload?: JsonRecord,
  ) => Promise<TPayload>
  onEvent: CodexSocket['onEvent']
  onStatus: CodexSocket['onStatus']
}

export interface UseCodexWorkspaceOptions {
  autoConnect?: boolean
  persistActiveThread?: boolean
  selectInitialThread?: boolean
  socket?: CodexRealtimeClient
  socketUrl?: string
  turnCache?: CodexTurnCache
}

function readActiveThreadId(enabled = true) {
  if (!enabled) {
    return ''
  }
  if (typeof localStorage === 'undefined') {
    return ''
  }
  return localStorage.getItem(ACTIVE_THREAD_STORAGE_KEY) ?? ''
}

function persistActiveThreadId(threadId: string, enabled = true) {
  if (!enabled) {
    return
  }
  if (typeof localStorage === 'undefined') {
    return
  }
  if (!threadId) {
    localStorage.removeItem(ACTIVE_THREAD_STORAGE_KEY)
    return
  }
  localStorage.setItem(ACTIVE_THREAD_STORAGE_KEY, threadId)
}

function emptyWorkspace(): CodexWorkspaceResponse {
  return {
    projects: [],
    recent_threads: [],
    paired_editors: [],
    remote_connection_statuses: {},
  }
}

function normalizeWorkspace(value: unknown): CodexWorkspaceResponse {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return emptyWorkspace()
  }
  const record = value as Partial<CodexWorkspaceResponse>
  return {
    projects: Array.isArray(record.projects) ? record.projects : [],
    recent_threads: Array.isArray(record.recent_threads) ? record.recent_threads : [],
    paired_editors: Array.isArray(record.paired_editors) ? record.paired_editors : [],
    remote_connections: Array.isArray(record.remote_connections) ? record.remote_connections : [],
    active_remote_connection_id:
      typeof record.active_remote_connection_id === 'string'
        ? record.active_remote_connection_id
        : '',
    remote_connection_statuses:
      record.remote_connection_statuses &&
      typeof record.remote_connection_statuses === 'object' &&
      !Array.isArray(record.remote_connection_statuses)
        ? record.remote_connection_statuses
        : {},
  }
}

function normalizeThreadPayload(
  value: unknown,
  fallbackThreadId: string,
): CodexThreadStatePayload | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const record = value as Partial<CodexThreadStatePayload>
  const state =
    record.state && typeof record.state === 'object' && !Array.isArray(record.state)
      ? (record.state as CodexConversationState)
      : null
  const threadId =
    typeof record.thread_id === 'string' && record.thread_id.trim()
      ? record.thread_id.trim()
      : fallbackThreadId
  if (!threadId) {
    return null
  }
  return {
    thread_id: threadId,
    host_id:
      typeof record.host_id === 'string'
        ? record.host_id
        : typeof state?.hostId === 'string'
          ? state.hostId
          : undefined,
    state,
    stream_role:
      record.stream_role && typeof record.stream_role === 'object'
        ? (record.stream_role as JsonRecord)
        : null,
    queued_followups: Array.isArray(record.queued_followups) ? record.queued_followups : [],
  }
}

function threadStatus(state: CodexConversationState | null) {
  const turns = Array.isArray(state?.turns) ? state.turns : []
  const latestTurn = turns[turns.length - 1]
  if (latestTurn?.status) {
    return latestTurn.status
  }
  const runtime = state?.threadRuntimeStatus
  if (typeof runtime === 'string') {
    return runtime
  }
  if (runtime && typeof runtime === 'object') {
    const type = runtime.type
    if (typeof type === 'string' && type) {
      return type
    }
  }
  return 'idle'
}

function threadHostId(thread: CodexNativeSessionSummary | null | undefined) {
  return thread?.host_id || thread?.hostId || 'local'
}

function toErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function isPendingUserInputRequest(value: unknown): value is CodexPendingRequest {
  return (
    Boolean(value) &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    (value as CodexPendingRequest).method === 'item/tool/requestUserInput' &&
    typeof (value as CodexPendingRequest).id === 'string' &&
    Boolean((value as CodexPendingRequest).id)
  )
}

function isPendingPlanImplementationRequest(value: unknown): value is CodexPendingRequest {
  return (
    Boolean(value) &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    (value as CodexPendingRequest).method === PLAN_IMPLEMENTATION_REQUEST_METHOD &&
    typeof (value as CodexPendingRequest).id === 'string' &&
    Boolean((value as CodexPendingRequest).id)
  )
}

function isPendingComposerRequest(value: unknown): value is CodexPendingRequest {
  return isPendingUserInputRequest(value) || isPendingPlanImplementationRequest(value)
}

function promptSubmissionFromInput(input: string | CodexPromptSubmission): CodexPromptSubmission {
  return typeof input === 'string' ? { prompt: input } : input
}

function defaultCollaborationMode(
  state: CodexConversationState | null,
  submission: Partial<CodexPromptSubmission> = {},
): CodexCollaborationMode {
  return {
    mode: 'default',
    settings: {
      model: submission.model ?? state?.latestModel ?? '',
      reasoning_effort: submission.reasoningEffort ?? state?.latestReasoningEffort ?? null,
      developer_instructions: null,
    },
  }
}

function planCollaborationMode(
  state: CodexConversationState | null,
  submission: Partial<CodexPromptSubmission> = {},
): CodexCollaborationMode {
  return {
    mode: 'plan',
    settings: {
      model: submission.model ?? state?.latestModel ?? '',
      reasoning_effort: submission.reasoningEffort ?? state?.latestReasoningEffort ?? null,
      developer_instructions: null,
    },
  }
}

function buildCollaborationPayload(
  mode: CodexWorkMode,
  state: CodexConversationState | null,
  submission: Partial<CodexPromptSubmission> = {},
) {
  return mode === 'plan'
    ? planCollaborationMode(state, submission)
    : defaultCollaborationMode(state, submission)
}

function promptPermissionPayload(submission: Partial<CodexPromptSubmission>): JsonRecord {
  const payload: JsonRecord = {}
  if (submission.approvalPolicy) {
    payload.approval_policy = submission.approvalPolicy
  }
  if (submission.approvalsReviewer) {
    payload.approvals_reviewer = submission.approvalsReviewer
  }
  if (submission.sandboxPolicy) {
    payload.sandbox_policy = submission.sandboxPolicy
  }
  return payload
}

function normalizeGoal(value: unknown): CodexThreadGoal | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const record = value as JsonRecord
  const objective = typeof record.objective === 'string' ? record.objective.trim() : ''
  if (!objective) {
    return null
  }
  const status = typeof record.status === 'string' ? record.status : 'active'
  return {
    ...(record as Partial<CodexThreadGoal>),
    threadId:
      typeof record.threadId === 'string'
        ? record.threadId
        : typeof record.thread_id === 'string'
          ? record.thread_id
          : undefined,
    thread_id:
      typeof record.thread_id === 'string'
        ? record.thread_id
        : typeof record.threadId === 'string'
          ? record.threadId
          : undefined,
    objective,
    status,
    tokenBudget: numberOrNull(record.tokenBudget, record.token_budget),
    tokensUsed: numberOrUndefined(record.tokensUsed, record.tokens_used),
    timeUsedSeconds: numberOrUndefined(record.timeUsedSeconds, record.time_used_seconds),
    createdAt: numberOrUndefined(record.createdAt, record.created_at),
    updatedAt: numberOrUndefined(record.updatedAt, record.updated_at),
  }
}

function normalizeGoalResponse(value: unknown): CodexThreadGoal | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as JsonRecord
    return normalizeGoal(record.goal) ?? normalizeGoal(record)
  }
  return null
}

function numberOrUndefined(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value
    }
  }
  return undefined
}

function numberOrNull(...values: unknown[]) {
  return numberOrUndefined(...values) ?? null
}

function mergePersistedGoalState(
  incoming: CodexConversationState,
  previous: CodexConversationState | null | undefined,
) {
  const incomingGoal =
    incoming.threadGoal === undefined ? undefined : normalizeGoal(incoming.threadGoal)
  const previousGoal = normalizeGoal(previous?.threadGoal)
  const incomingCompletedGoal =
    incoming.completedThreadGoal === undefined
      ? undefined
      : normalizeGoal(incoming.completedThreadGoal)
  const previousCompletedGoal = normalizeGoal(previous?.completedThreadGoal)
  const goal = incomingGoal === undefined ? previousGoal : incomingGoal
  const completedGoal =
    incomingCompletedGoal === undefined ? previousCompletedGoal : incomingCompletedGoal
  return {
    ...incoming,
    threadGoal: goal,
    completedThreadGoal: completedGoal,
  }
}

export function useCodexWorkspace(options: UseCodexWorkspaceOptions = {}) {
  const persistThreadSelection = options.persistActiveThread !== false
  const socket = options.socket ?? new CodexSocket(options.socketUrl)
  const turnSync = new CodexTurnSync(options.turnCache)
  const status = ref<CodexSocketStatus>('idle')
  const reconnectState = ref<CodexReconnectState>({
    phase: 'idle',
    attempt: 0,
    nextDelayMs: null,
  })
  const workspace = ref<CodexWorkspaceResponse>(emptyWorkspace())
  const threadPayloads = ref<Record<string, CodexThreadStatePayload>>({})
  const activeThreadId = ref(readActiveThreadId(persistThreadSelection))
  const activeSubscriptionId = ref('')
  const openingThreadId = ref('')
  const errorMessage = ref('')
  const successMessage = ref('')
  const isBooting = ref(true)
  const isCommandBusy = ref(false)
  const isRenaming = ref(false)
  const isArchiving = ref(false)
  const archivingThreadId = ref('')
  const forkingThreadId = ref('')
  const projectPathDraft = ref('')
  const reconnectController = new CodexReconnectController({
    reconnect: restoreSocketConnection,
    onStateChange: (state) => {
      reconnectState.value = state
    },
  })
  let unsubscribeSocketEvent: (() => void) | null = null
  let unsubscribeSocketStatus: (() => void) | null = null

  const flatThreads = computed<CodexNativeSessionSummary[]>(() =>
    [
      ...workspace.value.projects.flatMap((project) => project.sessions),
      ...(workspace.value.recent_threads ?? []),
    ].sort(
      (left, right) =>
        right.updated_at - left.updated_at ||
        right.started_at - left.started_at ||
        right.thread_id.localeCompare(left.thread_id),
    ),
  )

  const activeThreadPayload = computed(() =>
    activeThreadId.value ? (threadPayloads.value[activeThreadId.value] ?? null) : null,
  )
  const activeThreadState = computed(() => activeThreadPayload.value?.state ?? null)
  const activeThread = computed(
    () => flatThreads.value.find((thread) => thread.thread_id === activeThreadId.value) ?? null,
  )
  const activeThreadHostId = computed(() => {
    const summaryHostId = activeThread.value ? threadHostId(activeThread.value) : ''
    const stateHostId = activeThreadState.value?.hostId
    return (
      summaryHostId ||
      activeThreadPayload.value?.host_id ||
      (typeof stateHostId === 'string' ? stateHostId : '') ||
      'local'
    )
  })
  const activeStatus = computed(() => threadStatus(activeThreadState.value))
  const isActiveThreadLoading = computed(
    () =>
      Boolean(activeThreadId.value) &&
      (openingThreadId.value === activeThreadId.value || !activeThreadState.value),
  )
  const isActiveTurnInProgress = computed(() => isWorkingStatus(activeStatus.value))
  const activeMode = computed<CodexWorkMode>(() =>
    activeThreadState.value?.latestCollaborationMode?.mode === 'plan' ? 'plan' : 'build',
  )
  const pendingUserInputRequests = computed(() =>
    (Array.isArray(activeThreadState.value?.requests)
      ? activeThreadState.value.requests
      : []
    ).filter(isPendingUserInputRequest),
  )
  const activeComposerRequest = computed(
    () =>
      (Array.isArray(activeThreadState.value?.requests)
        ? activeThreadState.value.requests
        : []
      ).find(isPendingComposerRequest) ?? null,
  )
  const queuedFollowups = computed<CodexQueuedFollowup[]>(() => {
    const fromPayload = activeThreadPayload.value?.queued_followups
    if (Array.isArray(fromPayload) && fromPayload.length) {
      return fromPayload
    }
    return Array.isArray(activeThreadState.value?.queuedFollowups)
      ? activeThreadState.value.queuedFollowups
      : []
  })

  function setThreadPayload(payload: CodexThreadStatePayload) {
    const previousState = threadPayloads.value[payload.thread_id]?.state
    const state = payload.state
      ? mergePersistedGoalState(payload.state, previousState)
      : payload.state
    threadPayloads.value = {
      ...threadPayloads.value,
      [payload.thread_id]: {
        ...payload,
        state,
      },
    }
    syncWorkspaceThreadStatus(payload.thread_id, state)
  }

  function applyThreadDelta(payload: CodexThreadStateDeltaPayload) {
    const currentState = threadPayloads.value[payload.thread_id]?.state
    const currentTurns = Array.isArray(currentState?.turns) ? currentState.turns : []
    setThreadPayload(turnSync.applyDelta(payload, currentTurns))
  }

  function syncWorkspaceThreadStatus(threadId: string, state: CodexConversationState | null) {
    if (!state) {
      return
    }
    const status = threadStatus(state)
    let changed = false
    const projects = workspace.value.projects.map((project) => {
      let projectChanged = false
      const sessions = project.sessions.map((thread) => {
        if (thread.thread_id !== threadId || thread.status === status) {
          return thread
        }
        projectChanged = true
        changed = true
        return { ...thread, status }
      })
      return projectChanged ? { ...project, sessions } : project
    })
    const recentThreads = (workspace.value.recent_threads ?? []).map((thread) => {
      if (thread.thread_id !== threadId || thread.status === status) {
        return thread
      }
      changed = true
      return { ...thread, status }
    })
    if (changed) {
      workspace.value = { ...workspace.value, projects, recent_threads: recentThreads }
    }
  }

  function updateActiveState(patch: Partial<CodexConversationState>) {
    const threadId = activeThreadId.value
    if (!threadId) {
      return
    }
    const current = threadPayloads.value[threadId]
    const state = current?.state
    if (!state) {
      return
    }
    const nextState = {
      ...state,
      ...patch,
    }
    setThreadPayload({
      ...current,
      thread_id: threadId,
      state: nextState,
    })
  }

  function removeThreadPayload(threadId: string) {
    const next = { ...threadPayloads.value }
    delete next[threadId]
    threadPayloads.value = next
  }

  function handleSocketEvent(event: { type: string; payload?: unknown; message?: string }) {
    if (event.type === 'connection_ready') {
      status.value = 'open'
      return
    }
    if (event.type === 'workspace') {
      workspace.value = normalizeWorkspace(event.payload)
      return
    }
    if (event.type === 'thread_snapshot' || event.type === 'thread_state') {
      const payload = normalizeThreadPayload(event.payload, '')
      if (payload) {
        setThreadPayload(payload)
        turnSync.rememberFull(payload)
      }
      return
    }
    if (event.type === 'thread_state_delta') {
      const payload = normalizeThreadDeltaPayload(event.payload, '')
      if (payload) {
        applyThreadDelta(payload)
      }
      return
    }
    if (event.type === 'thread_archived') {
      const threadId = threadIdFromEvent(event.payload)
      if (threadId) {
        removeThreadPayload(threadId)
        turnSync.remove(threadId)
        if (activeThreadId.value === threadId) {
          activeThreadId.value = ''
          persistActiveThreadId('', persistThreadSelection)
        }
      }
      void refreshWorkspaceAndSelect()
      return
    }
    if (event.type === 'thread_unarchived') {
      void refreshWorkspace()
      return
    }
    if (event.type === 'error') {
      errorMessage.value = event.message ?? 'Codex socket error.'
    }
  }

  function threadIdFromEvent(payload: unknown) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      return ''
    }
    const threadId = (payload as { thread_id?: unknown }).thread_id
    return typeof threadId === 'string' ? threadId : ''
  }

  async function runCommand<T>(operation: () => Promise<T>) {
    isCommandBusy.value = true
    errorMessage.value = ''
    successMessage.value = ''
    try {
      return await operation()
    } catch (error) {
      errorMessage.value = toErrorMessage(error)
      return null
    } finally {
      isCommandBusy.value = false
    }
  }

  async function connect() {
    isBooting.value = true
    errorMessage.value = ''
    attachSocketListeners()
    reconnectController.start()
    try {
      await restoreSocketConnection()
    } catch (error) {
      if (!['scheduled', 'connecting', 'offline'].includes(reconnectState.value.phase)) {
        errorMessage.value = toErrorMessage(error)
      }
    } finally {
      isBooting.value = false
    }
  }

  function attachSocketListeners() {
    if (unsubscribeSocketEvent || unsubscribeSocketStatus) {
      return
    }
    unsubscribeSocketEvent = socket.onEvent(handleSocketEvent)
    unsubscribeSocketStatus = socket.onStatus((nextStatus) => {
      status.value = nextStatus
      reconnectController.handleStatus(nextStatus)
    })
  }

  async function restoreSocketConnection() {
    await socket.connect()
    errorMessage.value = ''
    if (options.selectInitialThread !== false) {
      await refreshWorkspaceAndSelect()
      return
    }
    if (activeThreadId.value) {
      await selectThread(activeThreadId.value, activeThreadHostId.value)
    }
  }

  function teardownSocketConnection() {
    reconnectController.stop()
    unsubscribeSocketEvent?.()
    unsubscribeSocketStatus?.()
    unsubscribeSocketEvent = null
    unsubscribeSocketStatus = null
  }

  async function refreshWorkspace() {
    const payload = await socket.sendCommand<CodexWorkspaceResponse>('list_threads')
    workspace.value = normalizeWorkspace(payload)
    return workspace.value
  }

  async function refreshRemoteConnections() {
    const payload = await apiGet<CodexRemoteConnectionsResponse>('/api/codex/remote-connections')
    workspace.value = {
      ...workspace.value,
      remote_connections: payload.connections,
      active_remote_connection_id: payload.active_connection_id,
      remote_connection_statuses: payload.statuses ?? {},
    }
    return payload
  }

  async function refreshWorkspaceAndSelect() {
    await refreshWorkspace()
    const currentThread = activeThreadId.value
    const nextThread =
      flatThreads.value.find((thread) => thread.thread_id === currentThread) ??
      flatThreads.value[0] ??
      null
    if (!nextThread) {
      activeThreadId.value = ''
      persistActiveThreadId('', persistThreadSelection)
      return
    }
    await selectThread(nextThread.thread_id, threadHostId(nextThread))
  }

  async function selectThread(threadId: string, hostId?: string) {
    const normalizedThreadId = threadId.trim()
    if (!normalizedThreadId) {
      return false
    }
    const resolvedHostId =
      hostId?.trim() ||
      threadHostId(flatThreads.value.find((thread) => thread.thread_id === normalizedThreadId))

    openingThreadId.value = normalizedThreadId
    try {
      if (activeSubscriptionId.value && activeSubscriptionId.value !== normalizedThreadId) {
        await socket
          .sendCommand('unsubscribe_thread', {
            thread_id: activeSubscriptionId.value,
          })
          .catch(() => null)
      }
      activeThreadId.value = normalizedThreadId
      activeSubscriptionId.value = normalizedThreadId
      persistActiveThreadId(normalizedThreadId, persistThreadSelection)
      const cachedTurns = await turnSync.subscriptionCache(normalizedThreadId)
      const payload = await socket.sendCommand<CodexThreadStateDeltaPayload>(
        'subscribe_thread_delta',
        {
          thread_id: normalizedThreadId,
          cached_turn_ids: cachedTurns.cached_turn_ids,
          compression: 'gzip',
          ...(cachedTurns.refresh_turn_ids.length
            ? { refresh_turn_ids: cachedTurns.refresh_turn_ids }
            : {}),
          ...(resolvedHostId !== 'local' ? { host_id: resolvedHostId } : {}),
        },
      )
      const normalizedPayload = normalizeThreadDeltaPayload(payload, normalizedThreadId)
      if (normalizedPayload) {
        applyThreadDelta(normalizedPayload)
      }
      void hydrateThreadGoal(normalizedThreadId)
      return true
    } catch (error) {
      errorMessage.value = toErrorMessage(error)
      return false
    } finally {
      openingThreadId.value = ''
    }
  }

  async function startThread(projectPath?: string, hostId = 'local') {
    return await runCommand(async () => {
      const payload = await socket.sendCommand<CodexThreadCreateResponse>('start_thread', {
        project_path: projectPath?.trim() || projectPathDraft.value.trim() || undefined,
        ...((hostId.trim() || 'local') !== 'local' ? { host_id: hostId.trim() } : {}),
      })
      const threadId = payload.thread_id
      if (payload.state) {
        const threadPayload = {
          thread_id: threadId,
          host_id: payload.host_id || hostId,
          state: payload.state,
          stream_role: null,
          queued_followups: [],
        }
        setThreadPayload(threadPayload)
        turnSync.rememberFull(threadPayload)
      }
      await refreshWorkspace()
      await selectThread(threadId, payload.host_id || hostId)
      successMessage.value = 'Thread started.'
      return payload
    })
  }

  async function sendPrompt(input: string | CodexPromptSubmission) {
    const threadId = activeThreadId.value
    const submission = promptSubmissionFromInput(input)
    const message = submission.prompt.trim()
    const attachments = Array.isArray(submission.attachments) ? submission.attachments : []
    if (!threadId || (!message && !attachments.length)) {
      return
    }
    await runCommand(async () => {
      await socket.sendCommand('send_prompt', {
        thread_id: threadId,
        prompt: message,
        ...(attachments.length ? { attachments } : {}),
        ...promptPermissionPayload(submission),
        collaboration_mode: buildCollaborationPayload(
          activeMode.value,
          activeThreadState.value,
          submission,
        ),
      })
    })
  }

  async function steerPrompt(prompt: string) {
    const threadId = activeThreadId.value
    const message = prompt.trim()
    if (!threadId || !message) {
      return
    }
    await runCommand(async () => {
      await socket.sendCommand('steer_prompt', {
        thread_id: threadId,
        prompt: message,
      })
    })
  }

  async function enqueueFollowup(prompt: string) {
    const threadId = activeThreadId.value
    const message = prompt.trim()
    if (!threadId || !message) {
      return
    }
    await runCommand(async () => {
      const followup = await socket.sendCommand<CodexQueuedFollowup>('enqueue_followup', {
        thread_id: threadId,
        prompt: message,
      })
      const current = activeThreadPayload.value
      if (current) {
        setThreadPayload({
          ...current,
          queued_followups: [...(current.queued_followups ?? []), followup],
        })
      }
      successMessage.value = 'Follow-up queued.'
    })
  }

  async function removeFollowup(messageId: string) {
    const threadId = activeThreadId.value
    if (!threadId || !messageId) {
      return
    }
    await runCommand(async () => {
      await socket.sendCommand('remove_followup', {
        thread_id: threadId,
        message_id: messageId,
      })
      const current = activeThreadPayload.value
      if (current) {
        setThreadPayload({
          ...current,
          queued_followups: (current.queued_followups ?? []).filter(
            (followup) => followup.id !== messageId,
          ),
        })
      }
    })
  }

  async function interruptTurn() {
    const threadId = activeThreadId.value
    if (!threadId) {
      return
    }
    await runCommand(async () => {
      await socket.sendCommand('interrupt_turn', { thread_id: threadId })
      successMessage.value = 'Interrupt sent.'
    })
  }

  async function compactThread() {
    const threadId = activeThreadId.value
    if (!threadId) {
      return
    }
    await runCommand(async () => {
      await socket.sendCommand('compact_thread', { thread_id: threadId })
      successMessage.value = 'Compact requested.'
    })
  }

  async function listSkills(options?: {
    threadId?: string | null
    cwd?: string | null
    forceReload?: boolean
  }) {
    const threadId = options?.threadId ?? activeThreadId.value
    const cwd =
      options?.cwd ??
      (typeof activeThreadState.value?.cwd === 'string' ? activeThreadState.value.cwd : null)
    const response = await socket.sendCommand<{ skills?: CodexSkillSummary[] }>('list_skills', {
      ...(threadId ? { thread_id: threadId } : {}),
      ...(threadId && activeThreadHostId.value !== 'local'
        ? { host_id: activeThreadHostId.value }
        : {}),
      ...(cwd ? { cwd } : {}),
      ...(options?.forceReload ? { force_reload: true } : {}),
    })
    const skills = Array.isArray(response?.skills) ? response.skills : []
    return skills
      .filter((skill) => typeof skill?.name === 'string' && typeof skill?.path === 'string')
      .map((skill) => ({
        name: skill.name,
        display_name:
          typeof skill.display_name === 'string' && skill.display_name.trim()
            ? skill.display_name
            : skill.name,
        description: typeof skill.description === 'string' ? skill.description : '',
        short_description:
          typeof skill.short_description === 'string' ? skill.short_description : '',
        path: skill.path,
        scope: typeof skill.scope === 'string' ? skill.scope : '',
        enabled: skill.enabled !== false,
        interface: isRecord(skill.interface) ? skill.interface : null,
        cwd: typeof skill.cwd === 'string' ? skill.cwd : null,
      }))
  }

  async function hydrateThreadGoal(threadId: string) {
    try {
      const response = await socket.sendCommand<{ goal?: CodexThreadGoal | null }>(
        'get_thread_goal',
        { thread_id: threadId },
      )
      const goal = normalizeGoalResponse(response)
      if (goal) {
        patchThreadState(threadId, { threadGoal: goal })
      }
    } catch {
      return
    }
  }

  function patchThreadState(threadId: string, patch: Partial<CodexConversationState>) {
    const current = threadPayloads.value[threadId]
    const state = current?.state
    if (!current || !state) {
      return
    }
    const nextState = {
      ...state,
      ...patch,
    }
    setThreadPayload({
      ...current,
      thread_id: threadId,
      state: nextState,
    })
  }

  async function setThreadGoal(objective: string, tokenBudget?: number | null) {
    const threadId = activeThreadId.value
    const trimmedObjective = objective.trim()
    if (!threadId || !trimmedObjective) {
      return
    }
    await runCommand(async () => {
      const response = await socket.sendCommand<{ goal?: CodexThreadGoal }>('set_thread_goal', {
        thread_id: threadId,
        objective: trimmedObjective,
        status: 'active',
        token_budget: tokenBudget ?? undefined,
      })
      const goal = normalizeGoal(response.goal) ?? normalizeGoalResponse(response)
      if (goal) {
        updateActiveState({
          threadGoal: goal,
          threadGoalResumeConfirmation: null,
        })
      }
      successMessage.value = 'Goal started.'
    })
  }

  async function updateThreadGoalStatus(status: CodexThreadGoalStatus) {
    const threadId = activeThreadId.value
    if (!threadId) {
      return
    }
    await runCommand(async () => {
      const response = await socket.sendCommand<{ goal?: CodexThreadGoal }>('set_thread_goal', {
        thread_id: threadId,
        status,
      })
      const goal = normalizeGoal(response.goal) ?? normalizeGoalResponse(response)
      if (goal) {
        updateActiveState({
          threadGoal: goal,
          completedThreadGoal:
            goal.status === 'complete' ? goal : activeThreadState.value?.completedThreadGoal,
          threadGoalResumeConfirmation: ['paused', 'blocked', 'usageLimited'].includes(
            String(goal.status),
          )
            ? (activeThreadState.value?.threadGoalResumeConfirmation ?? null)
            : null,
        })
      }
      successMessage.value = goalStatusSuccessMessage(status)
    })
  }

  async function clearThreadGoal() {
    const threadId = activeThreadId.value
    if (!threadId) {
      return
    }
    await runCommand(async () => {
      await socket.sendCommand('clear_thread_goal', { thread_id: threadId })
      updateActiveState({
        threadGoal: null,
        threadGoalResumeConfirmation: null,
      })
      successMessage.value = 'Goal cleared.'
    })
  }

  function goalStatusSuccessMessage(status: CodexThreadGoalStatus) {
    if (status === 'complete') {
      return 'Goal achieved.'
    }
    if (status === 'blocked') {
      return 'Goal marked blocked.'
    }
    if (status === 'paused') {
      return 'Goal paused.'
    }
    return 'Goal updated.'
  }

  async function setMode(mode: CodexWorkMode) {
    const threadId = activeThreadId.value
    if (!threadId || activeMode.value === mode) {
      return true
    }
    const result = await runCommand(async () => {
      const collaborationMode = buildCollaborationPayload(mode, activeThreadState.value)
      await socket.sendCommand('set_collaboration_mode', {
        thread_id: threadId,
        collaboration_mode: collaborationMode,
      })
      updateActiveState({
        latestCollaborationMode:
          collaborationMode ?? defaultCollaborationMode(activeThreadState.value),
      })
      return true
    })
    return result === true
  }

  async function renameThread(name: string): Promise<void>
  async function renameThread(threadId: string, name: string): Promise<void>
  async function renameThread(threadIdOrName: string, name?: string) {
    const hasExplicitThreadId = name !== undefined
    const threadId = hasExplicitThreadId ? threadIdOrName.trim() : activeThreadId.value
    const trimmedName = (hasExplicitThreadId ? (name ?? '') : threadIdOrName).trim()
    if (!threadId || !trimmedName) {
      return
    }
    isRenaming.value = true
    try {
      await runCommand(async () => {
        await socket.sendCommand('rename_thread', {
          thread_id: threadId,
          name: trimmedName,
        })
        if (activeThreadId.value === threadId) {
          updateActiveState({ title: trimmedName })
        }
        await refreshWorkspace()
        successMessage.value = 'Thread renamed.'
      })
    } finally {
      isRenaming.value = false
    }
  }

  async function archiveThread(threadId = activeThreadId.value) {
    const normalizedThreadId = threadId.trim()
    if (!normalizedThreadId) {
      return
    }
    isArchiving.value = true
    archivingThreadId.value = normalizedThreadId
    await runCommand(async () => {
      await socket.sendCommand('archive_thread', { thread_id: normalizedThreadId })
      removeThreadPayload(normalizedThreadId)
      if (activeThreadId.value === normalizedThreadId) {
        activeThreadId.value = ''
        activeSubscriptionId.value = ''
        persistActiveThreadId('', persistThreadSelection)
      }
      await refreshWorkspaceAndSelect()
      successMessage.value = 'Thread archived.'
    })
    isArchiving.value = false
    archivingThreadId.value = ''
  }

  async function forkThread(threadId = activeThreadId.value) {
    const normalizedThreadId = threadId.trim()
    if (!normalizedThreadId) {
      return
    }
    forkingThreadId.value = normalizedThreadId
    const sourceThread = flatThreads.value.find((thread) => thread.thread_id === normalizedThreadId)
    const sourceHostId = sourceThread
      ? threadHostId(sourceThread)
      : normalizedThreadId === activeThreadId.value
        ? activeThreadHostId.value
        : 'local'
    errorMessage.value = ''
    successMessage.value = ''
    try {
      const payload = await socket.sendCommand<CodexThreadForkResponse>('fork_thread', {
        thread_id: normalizedThreadId,
        ...(sourceHostId !== 'local' ? { host_id: sourceHostId } : {}),
      })
      const forkedThreadId = payload.thread_id.trim()
      if (!forkedThreadId) {
        throw new Error('Codex did not return a forked thread id.')
      }
      if (payload.state) {
        const threadPayload = {
          thread_id: forkedThreadId,
          host_id: payload.host_id || sourceHostId,
          state: payload.state,
          stream_role: null,
          queued_followups: [],
        }
        setThreadPayload(threadPayload)
        turnSync.rememberFull(threadPayload)
      }
      await refreshWorkspace()
      const selected = await selectThread(
        forkedThreadId,
        payload.host_id || activeThreadHostId.value,
      )
      if (selected) {
        successMessage.value = 'Thread forked.'
      }
    } catch (error) {
      errorMessage.value = toErrorMessage(error)
    } finally {
      forkingThreadId.value = ''
    }
  }

  async function unarchiveThread(threadId: string) {
    const normalizedThreadId = threadId.trim()
    if (!normalizedThreadId) {
      return
    }
    await runCommand(async () => {
      await socket.sendCommand('unarchive_thread', { thread_id: normalizedThreadId })
      await refreshWorkspace()
      successMessage.value = 'Thread unarchived.'
    })
  }

  async function startEmbedThread(projectPath: string) {
    const normalizedProjectPath = projectPath.trim()
    if (!normalizedProjectPath) {
      errorMessage.value = 'cwd is required.'
      return null
    }
    const payload = await startThread(normalizedProjectPath)
    return payload
  }

  async function resumeEmbedThread(threadId: string) {
    const normalizedThreadId = threadId.trim()
    if (!normalizedThreadId) {
      errorMessage.value = 'thread_id is required.'
      return false
    }
    return await selectThread(normalizedThreadId)
  }

  async function submitUserInputResponse(requestId: string, response: JsonRecord) {
    const threadId = activeThreadId.value
    if (!threadId || !requestId) {
      return
    }
    const state = activeThreadState.value
    const request = Array.isArray(state?.requests)
      ? (state.requests.find((request) => request.id === requestId) ?? null)
      : null
    if (isPendingPlanImplementationRequest(request)) {
      await submitPlanImplementationRequest(request, response)
      return
    }
    await runCommand(async () => {
      await socket.sendCommand('submit_user_input_response', {
        thread_id: threadId,
        request_id: requestId,
        response,
      })
      const state = activeThreadState.value
      if (state && Array.isArray(state.requests)) {
        updateActiveState({
          requests: state.requests.filter((request) => request.id !== requestId),
        })
      }
    })
  }

  async function submitPlanImplementationRequest(
    request: CodexPendingRequest,
    response: JsonRecord,
  ) {
    const threadId = activeThreadId.value
    if (!threadId || response.decision !== 'accept') {
      removeRequest(request.id)
      return
    }
    await runCommand(async () => {
      const state = activeThreadState.value
      const collaborationMode = defaultCollaborationMode(state)
      const planContent =
        typeof response.planContent === 'string'
          ? response.planContent
          : typeof request.params?.planContent === 'string'
            ? request.params.planContent
            : ''
      const followupMessage =
        typeof response.followupMessage === 'string' ? response.followupMessage.trim() : ''
      const message = followupMessage || `${IMPLEMENT_PLAN_PROMPT_PREFIX}\n${planContent}`.trim()

      await socket.sendCommand('set_collaboration_mode', {
        thread_id: threadId,
        collaboration_mode: collaborationMode,
      })
      updateActiveState({
        latestCollaborationMode: collaborationMode,
        requests: Array.isArray(state?.requests)
          ? state.requests.filter((requestItem) => requestItem.id !== request.id)
          : [],
      })

      if (!message) {
        return
      }
      await socket.sendCommand('send_prompt', {
        thread_id: threadId,
        prompt: message,
        collaboration_mode: collaborationMode,
      })
    })
  }

  function removeRequest(requestId: string) {
    const state = activeThreadState.value
    if (state && Array.isArray(state.requests)) {
      updateActiveState({
        requests: state.requests.filter((request) => request.id !== requestId),
      })
    }
  }

  onMounted(async () => {
    if (options.autoConnect === false) {
      isBooting.value = false
      return
    }
    await connect()
  })

  onBeforeUnmount(() => {
    teardownSocketConnection()
    socket.close()
  })

  return {
    activeMode,
    activeStatus,
    activeThread,
    activeThreadId,
    activeThreadPayload,
    activeThreadState,
    activeUserInputRequest: activeComposerRequest,
    archivingThreadId,
    archiveThread,
    compactThread,
    connect,
    enqueueFollowup,
    errorMessage,
    flatThreads,
    forkingThreadId,
    forkThread,
    listSkills,
    isActiveThreadLoading,
    isActiveTurnInProgress,
    isArchiving,
    isBooting,
    isCommandBusy,
    isRenaming,
    openingThreadId,
    pendingUserInputRequests,
    projectPathDraft,
    queuedFollowups,
    refreshRemoteConnections,
    reconnectState,
    refreshWorkspace,
    refreshWorkspaceAndSelect,
    removeFollowup,
    renameThread,
    selectThread,
    sendPrompt,
    setMode,
    setThreadGoal,
    startEmbedThread,
    startThread,
    status,
    steerPrompt,
    submitUserInputResponse,
    successMessage,
    resumeEmbedThread,
    unarchiveThread,
    updateThreadGoalStatus,
    clearThreadGoal,
    workspace,
    interruptTurn,
  }
}
