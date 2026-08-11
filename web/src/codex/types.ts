export type JsonRecord = Record<string, unknown>

export type CodexWorkMode = 'build' | 'plan'

export interface CodexPromptSubmission {
  prompt: string
  model?: string | null
  reasoningEffort?: string | null
  attachments?: JsonRecord[]
  approvalPolicy?: string | null
  approvalsReviewer?: string | null
  sandboxPolicy?: JsonRecord | null
}

export interface CodexNativeSessionSummary {
  thread_id: string
  host_id?: string
  hostId?: string
  title: string
  preview: string
  updated_at: number
  started_at: number
  status: string
  cwd: string
  project: string
  project_path: string
  source: string
  model_provider?: string
}

export interface CodexProjectGroup {
  id?: string
  project: string
  project_path: string
  host_id?: string
  hostId?: string
  kind?: 'local' | 'remote'
  root_paths?: string[]
  session_count: number
  sessions: CodexNativeSessionSummary[]
}

export interface CodexWorkspaceResponse {
  projects: CodexProjectGroup[]
  recent_threads?: CodexNativeSessionSummary[]
  recent_threads_next_cursors?: Record<string, string>
  paired_editors?: JsonRecord[]
  remote_connections?: CodexRemoteConnection[]
  active_remote_connection_id?: string
  remote_connection_statuses?: Record<string, CodexRemoteConnectionStatus>
}

export interface CodexRecentThreadsPage {
  threads: CodexNativeSessionSummary[]
  next_cursors: Record<string, string>
}

export interface CodexProjectPayload {
  name: string
  kind: 'local' | 'remote'
  host_id: string
  project_path: string
}

export interface CodexRemoteConnection {
  id: string
  display_name: string
  ssh_host: string
  ssh_username?: string
  ssh_port?: number | null
  ssh_alias: string
  identity_file: string
  auto_connect: boolean
}

export type CodexRemoteConnectionRuntimeStatus =
  | 'connected'
  | 'connecting'
  | 'disconnected'
  | 'error'

export interface CodexRemoteConnectionStatus {
  status: CodexRemoteConnectionRuntimeStatus
  detail?: string
}

export interface CodexRemoteConnectionPayload {
  display_name: string
  ssh_host: string
  ssh_username: string
  ssh_port?: number | null
  ssh_alias: string
  identity_file: string
  auto_connect: boolean
}

export interface CodexRemoteConnectionAutoConnectPayload {
  auto_connect: boolean
}

export interface CodexSshConfigHost {
  alias: string
  hostname: string
  port?: number | null
  identity_file: string
}

export interface CodexSshConfigHostsResponse {
  hosts: CodexSshConfigHost[]
}

export interface CodexRemoteConnectionsResponse {
  connections: CodexRemoteConnection[]
  active_connection_id: string
  statuses?: Record<string, CodexRemoteConnectionStatus>
}

export interface CodexRemoteConnectionResponse {
  connection: CodexRemoteConnection
}

export interface CodexRemoteConnectionTestResponse {
  ok: boolean
  detail: string
}

export type CodexFilesystemEntryKind = 'directory' | 'file' | 'other'

export interface CodexFilesystemEntry {
  name: string
  path: string
  kind: CodexFilesystemEntryKind
  extension: string
  readable: boolean
}

export interface CodexFilesystemResponse {
  path: string
  parent_path?: string | null
  roots: CodexFilesystemEntry[]
  entries: CodexFilesystemEntry[]
}

export interface CodexCollaborationMode extends JsonRecord {
  mode?: string
  settings?: {
    model?: string | null
    reasoning_effort?: string | null
    developer_instructions?: string | null
  } | null
}

export interface CodexTurnState extends JsonRecord {
  turnId?: string | null
  status?: string
  items?: JsonRecord[]
  turnStartedAtMs?: number | null
  firstTurnWorkItemStartedAtMs?: number | null
  finalAssistantStartedAtMs?: number | null
  durationMs?: number | null
  error?: unknown
}

export interface CodexRequestOption {
  label: string
  description?: string
}

export interface CodexRequestQuestion extends JsonRecord {
  id: string
  header?: string
  question?: string
  isOther?: boolean
  isSecret?: boolean
  options?: CodexRequestOption[]
}

export interface CodexPendingRequest extends JsonRecord {
  id: string
  method: string
  params?: {
    threadId?: string
    turnId?: string
    itemId?: string
    questions?: CodexRequestQuestion[]
    [key: string]: unknown
  }
}

export interface CodexQueuedFollowup extends JsonRecord {
  id?: string
  text?: string
  prompt?: string
  createdAt?: number
}

export type CodexThreadGoalStatus =
  | 'active'
  | 'paused'
  | 'blocked'
  | 'usageLimited'
  | 'budgetLimited'
  | 'complete'

export interface CodexThreadGoal extends JsonRecord {
  threadId?: string
  thread_id?: string
  objective: string
  status: CodexThreadGoalStatus | string
  tokenBudget?: number | null
  tokensUsed?: number
  timeUsedSeconds?: number
  createdAt?: number
  updatedAt?: number
}

export interface CodexTokenUsageBreakdown extends JsonRecord {
  cachedInputTokens?: number
  inputTokens?: number
  outputTokens?: number
  reasoningOutputTokens?: number
  totalTokens?: number
}

export interface CodexThreadTokenUsage extends JsonRecord {
  total?: CodexTokenUsageBreakdown | null
  last?: CodexTokenUsageBreakdown | null
  modelContextWindow?: number | null
}

export interface CodexThreadTokenUsageInfo extends JsonRecord {
  threadId?: string
  turnId?: string
  tokenUsage?: CodexThreadTokenUsage | null
}

export interface CodexConversationState extends JsonRecord {
  id?: string
  hostId?: string
  turns?: CodexTurnState[]
  requests?: CodexPendingRequest[]
  createdAt?: number
  updatedAt?: number
  title?: string | null
  latestModel?: string | null
  latestReasoningEffort?: string | null
  latestCollaborationMode?: CodexCollaborationMode | null
  threadRuntimeStatus?: JsonRecord | string | null
  threadGoal?: CodexThreadGoal | null
  completedThreadGoal?: CodexThreadGoal | null
  threadGoalResumeConfirmation?: JsonRecord | null
  gitInfo?: JsonRecord | null
  cwd?: string | null
  source?: string | null
  archived?: boolean
  queuedFollowups?: CodexQueuedFollowup[]
  latestTokenUsageInfo?: CodexThreadTokenUsageInfo | null
}

export interface CodexThreadStatePayload {
  thread_id: string
  host_id?: string
  state: CodexConversationState | null
  stream_role?: JsonRecord | null
  queued_followups?: CodexQueuedFollowup[]
}

export interface CodexThreadStateDeltaPayload {
  thread_id: string
  state: CodexConversationState | null
  turn_ids: string[]
  turns: CodexTurnState[]
  turn_patches: CodexTurnStatePatch[]
  stream_role?: JsonRecord | null
  queued_followups?: CodexQueuedFollowup[]
}

export interface CodexTurnItemPatch extends JsonRecord {
  index: number
  item?: JsonRecord
  append_fields?: Record<string, string>
}

export interface CodexTurnStatePatch extends JsonRecord {
  turn_id: string
  set: JsonRecord
  remove: string[]
  item_count: number
  item_patches: CodexTurnItemPatch[]
}

export interface CodexThreadCreateResponse {
  thread_id: string
  host_id?: string
  state?: CodexConversationState | null
}

export interface CodexThreadForkResponse {
  thread_id: string
  host_id?: string
  state?: CodexConversationState | null
}

export interface CodexSkillSummary {
  name: string
  display_name?: string | null
  description?: string | null
  short_description?: string | null
  path: string
  scope?: string | null
  enabled?: boolean
  interface?: JsonRecord | null
  cwd?: string | null
}

export type CodexClientCommand =
  | 'list_threads'
  | 'list_recent_threads'
  | 'subscribe_thread'
  | 'subscribe_thread_delta'
  | 'unsubscribe_thread'
  | 'start_thread'
  | 'send_prompt'
  | 'steer_prompt'
  | 'enqueue_followup'
  | 'remove_followup'
  | 'interrupt_turn'
  | 'compact_thread'
  | 'set_thread_goal'
  | 'get_thread_goal'
  | 'clear_thread_goal'
  | 'set_collaboration_mode'
  | 'submit_user_input_response'
  | 'rename_thread'
  | 'archive_thread'
  | 'fork_thread'
  | 'unarchive_thread'
  | 'activate_remote_connection'
  | 'list_skills'

export type CodexServerEventType =
  | 'connection_ready'
  | 'workspace'
  | 'codex_session_event'
  | 'thread_snapshot'
  | 'thread_state'
  | 'thread_state_delta'
  | 'thread_archived'
  | 'thread_unarchived'

export interface CodexAckEnvelope<TPayload = unknown> {
  id: string
  type: 'ack'
  ok: true
  payload: TPayload
}

export interface CodexErrorEnvelope {
  id?: string
  type: 'error'
  code: string
  message: string
}

export interface CodexServerEvent<TPayload = unknown> {
  id?: string
  type: CodexServerEventType
  payload: TPayload
}

export type CodexSocketMessage = CodexAckEnvelope | CodexErrorEnvelope | CodexServerEvent

export type CodexSocketStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'
