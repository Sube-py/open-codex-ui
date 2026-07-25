<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Popover from 'primevue/popover'

import type {
  CodexConversationState,
  CodexPromptSubmission,
  CodexQueuedFollowup,
  CodexSkillSummary,
  CodexThreadGoal,
  CodexThreadGoalStatus,
  CodexWorkMode,
  JsonRecord,
} from '../types'
import { isRecord } from '../lib/format'
import {
  buildSlashCommands,
  clearSlashQuery,
  CODEX_INIT_PROMPT,
  filterSlashCommands,
  isSlashOnlyComposerText,
  parseSlashQuery,
  type CodexSlashCommandDefinition,
  type CodexSlashQueryMatch,
} from '../lib/slashCommands'
import CodexHostPathPicker from './CodexHostPathPicker.vue'
import CodexSlashCommandMenu from './CodexSlashCommandMenu.vue'

const draft = defineModel<string>({ required: true })

type PermissionMode = 'ask' | 'guardian' | 'full'
type PermissionOption = {
  value: PermissionMode
  label: string
  mobileLabel: string
  description: string
  icon: string
  tone: PermissionMode
  approvalPolicy: 'on-request' | 'never'
  approvalsReviewer: 'user' | 'guardian_subagent'
  sandboxPolicy: JsonRecord
}
type PopoverRef = {
  toggle: (event: Event) => void
  hide: () => void
}

const props = defineProps<{
  disabled?: boolean
  busy?: boolean
  isWorking?: boolean
  mode: CodexWorkMode
  queuedFollowups: CodexQueuedFollowup[]
  state: CodexConversationState | null
  listSkills?: () => Promise<CodexSkillSummary[]>
}>()

const emit = defineEmits<{
  sendPrompt: [submission: CodexPromptSubmission]
  steerPrompt: [prompt: string]
  enqueueFollowup: [prompt: string]
  removeFollowup: [messageId: string]
  interruptTurn: []
  setMode: [mode: CodexWorkMode]
  setThreadGoal: [objective: string, tokenBudget?: number | null]
  updateThreadGoalStatus: [status: CodexThreadGoalStatus]
  clearThreadGoal: []
  compactThread: []
  forkThread: []
}>()

const baseModelOptions = ['gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2']
const baseReasoningOptions = ['low', 'medium', 'high', 'xhigh']
const supportedReasoningOptions = new Set(baseReasoningOptions)
const selectedModel = ref('')
const selectedReasoningEffort = ref('')
const goalTokenBudgetDraft = ref('')
const isGoalComposeMode = ref(false)
const imageAttachments = ref<JsonRecord[]>([])
const fileAttachments = ref<JsonRecord[]>([])
const skillAttachments = ref<JsonRecord[]>([])
const availableSkills = ref<CodexSkillSummary[]>([])
const skillsLoading = ref(false)
const skillsLoadedFor = ref('')
const filePickerOpen = ref(false)
const addMenuTrigger = ref<HTMLElement | null>(null)
const composerShell = ref<HTMLElement | null>(null)
const composerTextarea = ref<HTMLTextAreaElement | null>(null)
const intelligencePopover = ref<PopoverRef | null>(null)
const permissionPopover = ref<PopoverRef | null>(null)
const addMenuOpen = ref(false)
const addMenuStyle = ref<Record<string, string>>({})
const slashMenuStyle = ref<Record<string, string>>({})
const slashMenuOpen = ref(false)
const slashSelectedIndex = ref(0)
const slashMatch = ref<CodexSlashQueryMatch | null>(null)
/** After Esc, keep the menu closed for the current `/…` token until it is removed. */
const slashMenuSuppressed = ref(false)
const statusPanelOpen = ref(false)
const selectedPermissionMode = ref<PermissionMode>('full')
const todoExpanded = ref(false)

const permissionOptions: PermissionOption[] = [
  {
    value: 'ask',
    label: 'Ask for approval',
    mobileLabel: 'Ask',
    description: 'Always ask to edit external files and use the internet',
    icon: 'pi pi-question-circle',
    tone: 'ask',
    approvalPolicy: 'on-request',
    approvalsReviewer: 'user',
    sandboxPolicy: { type: 'workspaceWrite' },
  },
  {
    value: 'guardian',
    label: 'Approve for me',
    mobileLabel: 'Approve',
    description: 'Only ask for actions detected as potentially unsafe',
    icon: 'pi pi-shield',
    tone: 'guardian',
    approvalPolicy: 'on-request',
    approvalsReviewer: 'guardian_subagent',
    sandboxPolicy: { type: 'workspaceWrite' },
  },
  {
    value: 'full',
    label: 'Full access',
    mobileLabel: 'Full',
    description: 'Unrestricted access to the internet and any file on your computer',
    icon: 'pi pi-exclamation-triangle',
    tone: 'full',
    approvalPolicy: 'never',
    approvalsReviewer: 'user',
    sandboxPolicy: { type: 'dangerFullAccess' },
  },
]
const fallbackPermissionOption = permissionOptions[2] as PermissionOption

const latestModel = computed(() => props.state?.latestModel?.trim() || 'gpt-5.4')
const latestReasoningEffort = computed(() =>
  normalizeReasoningEffort(props.state?.latestReasoningEffort?.trim()),
)
const modelOptions = computed(() =>
  optionItems([latestModel.value, ...baseModelOptions]).map((option) => ({
    ...option,
    label: compactModelLabel(option.value),
  })),
)
const reasoningOptions = computed(() =>
  optionItems([latestReasoningEffort.value, ...baseReasoningOptions]).map((option) => ({
    ...option,
    label: reasoningLabel(option.value),
  })),
)
const activeModel = computed(() => selectedModel.value || latestModel.value)
const activeReasoningEffort = computed(() => selectedReasoningEffort.value || latestReasoningEffort.value)
const intelligenceTriggerLabel = computed(
  () => `${buttonModelLabel(activeModel.value)} ${compactReasoningLabel(activeReasoningEffort.value)}`,
)
const activePermissionOption = computed<PermissionOption>(
  () =>
    permissionOptions.find((option) => option.value === selectedPermissionMode.value) ??
    fallbackPermissionOption,
)
const hasDraft = computed(() => draft.value.trim().length > 0)
const hasPromptInput = computed(
  () =>
    hasDraft.value ||
    imageAttachments.value.length > 0 ||
    fileAttachments.value.length > 0 ||
    skillAttachments.value.length > 0,
)
const canSubmitText = computed(() => hasPromptInput.value && !props.disabled && !props.busy)
const primaryAction = computed(() => {
  if (props.isWorking && !hasDraft.value) {
    return 'stop'
  }
  if (props.isWorking) {
    return 'queue'
  }
  return 'send'
})
const primaryLabel = computed(() => {
  if (primaryAction.value === 'stop') {
    return 'Stop'
  }
  if (isGoalComposeMode.value && !props.isWorking) {
    return 'Start goal'
  }
  return 'Send'
})
const primaryIcon = computed(() => {
  if (primaryAction.value === 'stop') {
    return 'pi pi-stop'
  }
  return 'pi pi-arrow-up'
})
const primaryTitle = computed(() => {
  if (primaryAction.value === 'stop') {
    return 'Stop the active response'
  }
  if (primaryAction.value === 'queue') {
    return 'Send after the active response'
  }
  if (isGoalComposeMode.value) {
    return 'Start goal'
  }
  return 'Send'
})
const primaryDisabled = computed(() => {
  if (primaryAction.value === 'stop') {
    return props.disabled || props.busy
  }
  if (isGoalComposeMode.value && !props.isWorking) {
    return !canSubmitGoal.value
  }
  return !canSubmitText.value
})
const context = computed(() => contextWindowState(props.state))
const contextRingStyle = computed(() => {
  const percent = Math.max(0, Math.min(context.value.percent, 100))
  return {
    background: `conic-gradient(var(--app-accent) ${percent}%, rgba(21,94,99,0.14) 0)`,
  }
})
const contextHoverTitle = computed(() => {
  const suffix = context.value.estimated ? ' estimated' : ''
  if (context.value.label === '--') {
    return `${context.value.detail}${suffix}`
  }
  return `${context.value.label} used · ${context.value.detail}${suffix}`
})
const threadGoal = computed(() => props.state?.threadGoal ?? null)
const hasThreadGoal = computed(() => Boolean(threadGoal.value))
const goalObjective = computed(() => threadGoal.value?.objective?.trim() ?? '')
const canSubmitGoal = computed(() => hasDraft.value && !props.disabled && !props.busy)
const goalStatus = computed(() => String(threadGoal.value?.status ?? ''))
const goalStatusLabel = computed(() => goalStatusText(threadGoal.value))
const goalDetail = computed(() => goalProgressText(threadGoal.value))
const canResumeGoal = computed(() =>
  ['paused', 'blocked', 'usageLimited'].includes(goalStatus.value),
)
const latestTodoList = computed(() => latestTodoListItem(props.state))
const latestTodoItems = computed(() => todoItems(latestTodoList.value))
const latestTodoSummary = computed(() => todoSummary(latestTodoList.value))
const latestTodoCompletedCount = computed(() =>
  latestTodoItems.value.filter((todo) => isTodoComplete(todo.status)).length,
)
const composerPlaceholder = computed(() => {
  if (isGoalComposeMode.value) {
    return 'Describe a goal for this thread...'
  }
  if (props.mode === 'plan') {
    return 'Describe your task to generate a plan...'
  }
  return props.isWorking ? 'Add a follow-up for the queue...' : 'Ask Codex to work in this thread...'
})
const slashCommands = computed(() =>
  buildSlashCommands({
    mode: props.mode,
    isWorking: Boolean(props.isWorking),
    hasThreadGoal: hasThreadGoal.value,
    hasThread: Boolean(props.state?.id),
    contextPercent: context.value.percent,
    activeModel: activeModel.value,
    activeReasoningEffort: activeReasoningEffort.value,
    threadId: typeof props.state?.id === 'string' ? props.state.id : null,
    cwd: typeof props.state?.cwd === 'string' ? props.state.cwd : null,
    skills: availableSkills.value,
  }),
)
const filteredSlashCommands = computed(() => {
  const match = slashMatch.value
  if (!match) {
    return [] as CodexSlashCommandDefinition[]
  }
  return filterSlashCommands(slashCommands.value, match.query, {
    composerIsEmptyLike: isSlashOnlyComposerText(draft.value),
  })
})
const statusDetails = computed(() => {
  const threadId = typeof props.state?.id === 'string' ? props.state.id : ''
  const cwd = typeof props.state?.cwd === 'string' ? props.state.cwd : ''
  return {
    threadId,
    cwd,
    model: activeModel.value,
    reasoning: activeReasoningEffort.value,
    mode: props.mode,
    contextLabel: context.value.label,
    contextDetail: context.value.detail,
    contextPercent: context.value.percent,
  }
})

watch(
  () => props.state?.id,
  () => {
    selectedModel.value = ''
    selectedReasoningEffort.value = ''
    addMenuOpen.value = false
    todoExpanded.value = false
    closeSlashMenu()
    statusPanelOpen.value = false
  },
)

watch(
  () => props.state?.id,
  () => {
    goalTokenBudgetDraft.value = ''
    isGoalComposeMode.value = false
    imageAttachments.value = []
    fileAttachments.value = []
    skillAttachments.value = []
    availableSkills.value = []
    skillsLoadedFor.value = ''
    addMenuOpen.value = false
  },
)

watch(draft, () => {
  syncSlashMenuFromDraft()
})

watch(filteredSlashCommands, (commands) => {
  if (!commands.length) {
    slashSelectedIndex.value = 0
    return
  }
  if (slashSelectedIndex.value >= commands.length) {
    slashSelectedIndex.value = 0
  }
})

function sendSubmission() {
  if (!canSubmitText.value || props.isWorking) {
    return
  }
  const attachments = [
    ...skillAttachments.value.map((attachment) => ({ ...attachment })),
    ...fileAttachments.value.map((attachment) => ({ ...attachment })),
    ...imageAttachments.value.map((attachment) => ({ ...attachment })),
  ]
  emit('sendPrompt', {
    prompt: draft.value,
    model: activeModel.value,
    reasoningEffort: activeReasoningEffort.value,
    approvalPolicy: activePermissionOption.value.approvalPolicy,
    approvalsReviewer: activePermissionOption.value.approvalsReviewer,
    sandboxPolicy: { ...activePermissionOption.value.sandboxPolicy },
    ...(attachments.length ? { attachments } : {}),
  })
  draft.value = ''
  imageAttachments.value = []
  fileAttachments.value = []
  skillAttachments.value = []
}

function submitGoal() {
  if (!canSubmitGoal.value) {
    return
  }
  emit('setThreadGoal', draft.value, parsedGoalTokenBudget())
  draft.value = ''
  goalTokenBudgetDraft.value = ''
  isGoalComposeMode.value = false
}

function parsedGoalTokenBudget() {
  const value = Number(goalTokenBudgetDraft.value)
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : null
}

function submitQueue() {
  if (!hasDraft.value || props.disabled || props.busy) {
    return
  }
  emit('enqueueFollowup', draft.value)
  draft.value = ''
}

function submitPrimary() {
  if (primaryAction.value === 'stop') {
    if (!primaryDisabled.value) {
      emit('interruptTurn')
    }
    return
  }
  if (isGoalComposeMode.value && !props.isWorking) {
    submitGoal()
    return
  }
  if (primaryAction.value === 'queue') {
    submitQueue()
    return
  }
  sendSubmission()
}

function toggleGoalComposeMode() {
  if (props.busy || props.disabled || props.isWorking || hasThreadGoal.value) {
    return
  }
  isGoalComposeMode.value = !isGoalComposeMode.value
  if (isGoalComposeMode.value) {
    emit('setMode', 'build')
  }
  addMenuOpen.value = false
}

function toggleMode() {
  if (props.busy || props.disabled) {
    return
  }
  emit('setMode', props.mode === 'plan' ? 'build' : 'plan')
}

function startPlanMode() {
  if (props.busy || props.disabled) {
    return
  }
  isGoalComposeMode.value = false
  // Match slash `/plan-mode`: toggle plan on/off from the add menu too.
  emit('setMode', props.mode === 'plan' ? 'build' : 'plan')
  addMenuOpen.value = false
}

function startGoalMode() {
  toggleGoalComposeMode()
}

async function toggleAddMenu() {
  if (props.busy || props.disabled) {
    return
  }
  addMenuOpen.value = !addMenuOpen.value
  if (addMenuOpen.value) {
    await nextTick()
    updateFloatingMenuPosition(addMenuTrigger.value, addMenuStyle, 320)
  }
}

function closeFloatingMenus() {
  addMenuOpen.value = false
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof Element)) {
    closeFloatingMenus()
    closeSlashMenu()
    statusPanelOpen.value = false
    return
  }
  if (
    target.closest('[data-codex-add-menu]') ||
    target.closest('[data-codex-add-menu-trigger]')
  ) {
    // keep add menu
  } else {
    closeFloatingMenus()
  }
  if (
    !target.closest('[data-codex-slash-menu]') &&
    !target.closest('[data-codex-composer-textarea]')
  ) {
    closeSlashMenu()
  }
  if (
    !target.closest('[data-codex-status-panel]') &&
    !target.closest('[data-codex-context-window]')
  ) {
    // status panel closes only via its own control or Escape unless opened from slash
  }
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (handleSlashMenuKeydown(event)) {
    return
  }
  if (event.key === 'Escape' || event.code === 'Escape') {
    // Fallback path when the slash menu already closed itself mid-handler.
    if (slashMenuOpen.value) {
      event.preventDefault()
      dismissSlashMenu()
    }
    closeFloatingMenus()
    statusPanelOpen.value = false
  }
}

function repositionOpenMenus() {
  if (addMenuOpen.value) {
    updateFloatingMenuPosition(addMenuTrigger.value, addMenuStyle, 320)
  }
  if (slashMenuOpen.value) {
    updateSlashMenuPosition()
  }
}

function updateFloatingMenuPosition(
  trigger: HTMLElement | null,
  target: typeof addMenuStyle,
  width: number,
) {
  if (!trigger || typeof window === 'undefined') {
    target.value = {}
    return
  }
  const rect = trigger.getBoundingClientRect()
  const viewportPadding = 12
  const left = Math.min(
    Math.max(rect.left, viewportPadding),
    Math.max(viewportPadding, window.innerWidth - width - viewportPadding),
  )
  target.value = {
    left: `${left}px`,
    bottom: `${Math.max(viewportPadding, window.innerHeight - rect.top + 8)}px`,
  }
}

function chooseModel(model: string) {
  if (props.busy || props.disabled) {
    return
  }
  selectedModel.value = model === latestModel.value ? '' : model
  intelligencePopover.value?.hide()
}

function chooseReasoningEffort(reasoningEffort: string) {
  if (props.busy || props.disabled) {
    return
  }
  selectedReasoningEffort.value = reasoningEffort === latestReasoningEffort.value ? '' : reasoningEffort
  intelligencePopover.value?.hide()
}

function choosePermissionMode(mode: PermissionMode) {
  if (props.busy || props.disabled) {
    return
  }
  selectedPermissionMode.value = mode
  permissionPopover.value?.hide()
}

function toggleIntelligenceMenu(event: Event) {
  if (props.busy || props.disabled) {
    return
  }
  addMenuOpen.value = false
  intelligencePopover.value?.toggle(event)
}

function togglePermissionMenu(event: Event) {
  if (props.busy || props.disabled) {
    return
  }
  addMenuOpen.value = false
  permissionPopover.value?.toggle(event)
}

function onKeydown(event: KeyboardEvent) {
  if (handleSlashMenuKeydown(event)) {
    return
  }

  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    submitPrimary()
    return
  }
  if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === 'p') {
    event.preventDefault()
    toggleMode()
    return
  }
  if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === 'g') {
    event.preventDefault()
    toggleGoalComposeMode()
  }
}

function handleSlashMenuKeydown(event: KeyboardEvent) {
  if (event.isComposing) {
    return false
  }

  const key = event.key
  const code = event.code
  const isArrowDown = key === 'ArrowDown' || code === 'ArrowDown'
  const isArrowUp = key === 'ArrowUp' || code === 'ArrowUp'
  const isEnter =
    (key === 'Enter' || code === 'Enter') && !event.metaKey && !event.ctrlKey && !event.shiftKey
  const isTab = key === 'Tab' || code === 'Tab'
  const isEscape = key === 'Escape' || code === 'Escape'

  // Esc should dismiss even if a concurrent handler already flipped open=false.
  if (isEscape && (slashMenuOpen.value || slashMatch.value)) {
    event.preventDefault()
    event.stopPropagation()
    dismissSlashMenu()
    return true
  }

  if (!slashMenuOpen.value) {
    return false
  }

  if (isArrowDown) {
    event.preventDefault()
    event.stopPropagation()
    moveSlashSelection(1)
    return true
  }
  if (isArrowUp) {
    event.preventDefault()
    event.stopPropagation()
    moveSlashSelection(-1)
    return true
  }
  if (isEnter || isTab) {
    const command = filteredSlashCommands.value[slashSelectedIndex.value]
    if (command) {
      event.preventDefault()
      event.stopPropagation()
      void selectSlashCommand(command)
      return true
    }
  }
  return false
}

function syncSlashMenuFromDraft(caret?: number) {
  if (props.disabled || props.busy) {
    closeSlashMenu()
    return
  }
  const selectionStart = resolveSlashCaret(caret)
  const match = parseSlashQuery(draft.value, selectionStart)
  if (!match) {
    // Only clear Esc-suppression once the current `/…` token is gone.
    // Match Codex: after Esc, continue typing in the same token must not reopen.
    if (!draftHasSlashToken(draft.value)) {
      slashMenuSuppressed.value = false
    }
    closeSlashMenu()
    return
  }
  if (slashMenuSuppressed.value) {
    slashMenuOpen.value = false
    slashMatch.value = match
    return
  }
  const wasOpen = slashMenuOpen.value
  slashMatch.value = match
  slashMenuOpen.value = true
  if (!wasOpen) {
    slashSelectedIndex.value = 0
  }
  void ensureSkillsLoaded()
  void nextTick(() => updateSlashMenuPosition())
}

function resolveSlashCaret(caret?: number) {
  if (typeof caret === 'number') {
    return caret
  }
  const selectionStart = composerTextarea.value?.selectionStart
  if (typeof selectionStart === 'number') {
    // jsdom/setValue often leaves the caret at 0; if the draft itself is a slash
    // token, treat the caret as being at the end so filtering keeps working.
    if (selectionStart === 0 && draft.value.length > 0 && draftHasSlashToken(draft.value)) {
      return draft.value.length
    }
    return selectionStart
  }
  return draft.value.length
}

function draftHasSlashToken(value: string) {
  return parseSlashQuery(value, value.length) != null
}

async function ensureSkillsLoaded(force = false) {
  if (!props.listSkills || props.disabled) {
    return
  }
  const threadId = typeof props.state?.id === 'string' ? props.state.id : ''
  const cwd = typeof props.state?.cwd === 'string' ? props.state.cwd : ''
  const cacheKey = `${threadId}::${cwd}`
  if (!force && skillsLoadedFor.value === cacheKey) {
    return
  }
  if (skillsLoading.value) {
    return
  }
  skillsLoading.value = true
  try {
    const skills = await props.listSkills()
    availableSkills.value = Array.isArray(skills) ? skills : []
    skillsLoadedFor.value = cacheKey
    if (slashMenuOpen.value) {
      await nextTick()
      updateSlashMenuPosition()
    }
  } catch {
    if (force || skillsLoadedFor.value !== cacheKey) {
      availableSkills.value = []
    }
  } finally {
    skillsLoading.value = false
  }
}

function dismissSlashMenu() {
  slashMenuSuppressed.value = true
  closeSlashMenu()
}

function closeSlashMenu() {
  slashMenuOpen.value = false
  slashMatch.value = null
  slashSelectedIndex.value = 0
}

function moveSlashSelection(delta: number) {
  const total = filteredSlashCommands.value.length
  if (!total) {
    slashSelectedIndex.value = 0
    return
  }
  const next = (slashSelectedIndex.value + delta + total) % total
  if (next === slashSelectedIndex.value) {
    return
  }
  slashSelectedIndex.value = next
}

function updateSlashMenuPosition() {
  if (!slashMenuOpen.value || typeof window === 'undefined') {
    slashMenuStyle.value = {}
    return
  }
  const anchor =
    (composerShell.value?.querySelector('[data-codex-composer]') as HTMLElement | null) ??
    composerTextarea.value ??
    composerShell.value
  if (!anchor) {
    slashMenuStyle.value = {}
    return
  }
  const rect = anchor.getBoundingClientRect()
  const viewportPadding = 12
  // Match the composer card width so the popup sits flush above the input.
  const width = Math.min(Math.max(rect.width, 240), window.innerWidth - viewportPadding * 2)
  const left = Math.min(
    Math.max(rect.left, viewportPadding),
    Math.max(viewportPadding, window.innerWidth - width - viewportPadding),
  )
  slashMenuStyle.value = {
    left: `${left}px`,
    bottom: `${Math.max(viewportPadding, window.innerHeight - rect.top + 8)}px`,
    width: `${width}px`,
  }
}

function clearActiveSlashToken() {
  const match = slashMatch.value
  if (!match) {
    return
  }
  draft.value = clearSlashQuery(draft.value, match)
  closeSlashMenu()
}

async function selectSlashCommand(command: CodexSlashCommandDefinition) {
  if (props.disabled || props.busy) {
    return
  }
  clearActiveSlashToken()
  addMenuOpen.value = false

  switch (command.action.type) {
    case 'compact':
      if (props.isWorking) {
        return
      }
      emit('compactThread')
      return
    case 'fork':
      emit('forkThread')
      return
    case 'goal':
      if (!hasThreadGoal.value && !props.isWorking) {
        isGoalComposeMode.value = true
        emit('setMode', 'build')
        await nextTick()
        composerTextarea.value?.focus()
      }
      return
    case 'init':
      if (props.isWorking) {
        return
      }
      emit('sendPrompt', {
        prompt: CODEX_INIT_PROMPT,
        model: activeModel.value,
        reasoningEffort: activeReasoningEffort.value,
        approvalPolicy: activePermissionOption.value.approvalPolicy,
        approvalsReviewer: activePermissionOption.value.approvalsReviewer,
        sandboxPolicy: { ...activePermissionOption.value.sandboxPolicy },
      })
      return
    case 'model':
      await openIntelligenceMenu('model')
      return
    case 'plan-mode':
      emit('setMode', props.mode === 'plan' ? 'build' : 'plan')
      return
    case 'reasoning':
      await openIntelligenceMenu('reasoning')
      return
    case 'status':
      statusPanelOpen.value = !statusPanelOpen.value
      return
    case 'skill':
      addSkillAttachment(command.action.skill)
      return
  }
}

function addSkillAttachment(skill: {
  name: string
  path: string
  displayName?: string | null
  description?: string | null
  scope?: string | null
}) {
  const path = skill.path.trim()
  const name = skill.name.trim()
  if (!path || !name) {
    return
  }
  const attachment = {
    type: 'skill',
    name,
    path,
    display_name: skill.displayName?.trim() || name,
    description: skill.description?.trim() || '',
    scope: skill.scope?.trim() || '',
  }
  skillAttachments.value = [
    ...skillAttachments.value.filter((item) => item.path !== path && item.name !== name),
    attachment,
  ]
}

function removeSkillAttachment(index: number) {
  skillAttachments.value = skillAttachments.value.filter((_, itemIndex) => itemIndex !== index)
}

function skillAttachmentLabel(attachment: JsonRecord) {
  const displayName = attachment.display_name
  if (typeof displayName === 'string' && displayName.trim()) {
    return displayName.trim()
  }
  const name = attachment.name
  return typeof name === 'string' && name.trim() ? name.trim() : 'Skill'
}

function skillAttachmentScope(attachment: JsonRecord) {
  const scope = attachment.scope
  return typeof scope === 'string' ? scope.trim() : ''
}

async function openIntelligenceMenu(section: 'model' | 'reasoning') {
  await nextTick()
  const trigger = composerShell.value?.querySelector(
    '[data-codex-intelligence-trigger]',
  ) as HTMLElement | null
  if (trigger) {
    intelligencePopover.value?.toggle({ currentTarget: trigger } as unknown as Event)
  }
  await nextTick()
  const selector =
    section === 'model' ? '[data-codex-model-section]' : '[data-codex-reasoning-section]'
  document.body.querySelector(selector)?.scrollIntoView?.({ block: 'nearest' })
}

function onComposerInput() {
  syncSlashMenuFromDraft()
}

function onComposerClick() {
  syncSlashMenuFromDraft()
}

function onComposerSelect() {
  syncSlashMenuFromDraft()
}

function openFileAttachmentPicker() {
  if (props.busy || props.disabled || props.isWorking) {
    return
  }
  filePickerOpen.value = true
  addMenuOpen.value = false
}

function addFileAttachment(path: string) {
  const normalizedPath = path.trim()
  if (!normalizedPath) {
    return
  }
  const attachment = {
    type: 'mention',
    name: pathName(normalizedPath),
    path: normalizedPath,
  }
  fileAttachments.value = [
    ...fileAttachments.value.filter((item) => item.path !== normalizedPath),
    attachment,
  ]
}

function removeFileAttachment(index: number) {
  fileAttachments.value = fileAttachments.value.filter((_, itemIndex) => itemIndex !== index)
}

onMounted(() => {
  window.addEventListener('resize', repositionOpenMenus)
  window.addEventListener('scroll', repositionOpenMenus, true)
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onDocumentKeydown, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', repositionOpenMenus)
  window.removeEventListener('scroll', repositionOpenMenus, true)
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown, true)
})

async function onPaste(event: ClipboardEvent) {
  if (props.busy || props.disabled || props.isWorking) {
    return
  }
  const files = imageFilesFromClipboard(event.clipboardData)
  if (!files.length) {
    return
  }
  event.preventDefault()
  const loaded = await Promise.all(files.map(imageAttachmentFromFile))
  imageAttachments.value = [...imageAttachments.value, ...loaded]
}

function imageFilesFromClipboard(data: DataTransfer | null) {
  if (!data) {
    return []
  }
  const files = Array.from(data.files).filter((file) => file.type.startsWith('image/'))
  if (files.length) {
    return files
  }
  return Array.from(data.items ?? [])
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter((file): file is File => Boolean(file))
}

function imageAttachmentFromFile(file: File): Promise<JsonRecord> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener('load', () => {
      resolve({
        type: 'image',
        imageUrl: typeof reader.result === 'string' ? reader.result : '',
        name: file.name,
        mimeType: file.type,
      })
    })
    reader.addEventListener('error', () => reject(reader.error ?? new Error('Unable to read image.')))
    reader.readAsDataURL(file)
  })
}

function removeImageAttachment(index: number) {
  imageAttachments.value = imageAttachments.value.filter((_, itemIndex) => itemIndex !== index)
}

function imageAttachmentName(attachment: JsonRecord, index: number) {
  return typeof attachment.name === 'string' && attachment.name.trim()
    ? attachment.name
    : `Image ${index + 1}`
}

function imageAttachmentSrc(attachment: JsonRecord) {
  const src = attachment.imageUrl ?? attachment.image_url ?? attachment.url ?? attachment.src
  if (typeof src === 'string' && src) {
    return src
  }
  return codexImagePathUrl(fileAttachmentPath(attachment))
}

function codexImagePathUrl(path: string) {
  if (!path) {
    return ''
  }
  const query = new URLSearchParams({ path })
  return `/api/codex/image?${query.toString()}`
}

function fileAttachmentName(attachment: JsonRecord, index: number) {
  return typeof attachment.name === 'string' && attachment.name.trim()
    ? attachment.name
    : `File ${index + 1}`
}

function fileAttachmentPath(attachment: JsonRecord) {
  const path = attachment.path ?? attachment.fsPath ?? attachment.fs_path
  return typeof path === 'string' ? path : ''
}

function pathName(path: string) {
  const normalized = path.replace(/\\/g, '/').replace(/\/$/, '')
  return normalized.split('/').filter(Boolean).pop() || normalized || path
}

function followupText(followup: CodexQueuedFollowup) {
  const text = typeof followup.text === 'string' ? followup.text : followup.prompt
  return typeof text === 'string' ? text : ''
}

function followupId(followup: CodexQueuedFollowup, index: number) {
  return followup.id || `followup-${index}`
}

function steerFollowup(followup: CodexQueuedFollowup, index: number) {
  if (!props.isWorking || props.busy || props.disabled) {
    return
  }
  const prompt = followupText(followup).trim()
  if (!prompt) {
    return
  }
  emit('steerPrompt', prompt)
  emit('removeFollowup', followupId(followup, index))
}

function optionItems(values: string[]) {
  return [...new Set(values.filter(Boolean))].map((value) => ({
    label: value,
    value,
  }))
}

function compactModelLabel(model: string) {
  return model
    .split('-')
    .filter(Boolean)
    .map((part, index) => {
      if (index === 0 && part.toLowerCase() === 'gpt') {
        return 'GPT'
      }
      return `${part.charAt(0).toUpperCase()}${part.slice(1).toLowerCase()}`
    })
    .join('-')
}

function buttonModelLabel(model: string) {
  return model.split('-').filter(Boolean).slice(1).join('-') || compactModelLabel(model)
}

function reasoningLabel(reasoningEffort: string) {
  const labels: Record<string, string> = {
    low: 'Light',
    medium: 'Medium',
    high: 'High',
    xhigh: 'Extra High',
  }
  return labels[reasoningEffort] ?? titleCase(reasoningEffort)
}

function compactReasoningLabel(reasoningEffort: string) {
  const labels: Record<string, string> = {
    low: 'Light',
    medium: 'Med',
    high: 'High',
    xhigh: 'Extra',
  }
  return labels[reasoningEffort] ?? reasoningEffort
}

function normalizeReasoningEffort(reasoningEffort?: string) {
  const normalized = reasoningEffort?.trim().toLowerCase() ?? ''
  return supportedReasoningOptions.has(normalized) ? normalized : 'medium'
}

function titleCase(value: string) {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ')
}

function latestTodoListItem(state: CodexConversationState | null) {
  const turns = state?.turns
  if (!Array.isArray(turns)) {
    return null
  }
  for (let turnIndex = turns.length - 1; turnIndex >= 0; turnIndex -= 1) {
    const items = turns[turnIndex]?.items
    if (!Array.isArray(items)) {
      continue
    }
    for (let itemIndex = items.length - 1; itemIndex >= 0; itemIndex -= 1) {
      const item = items[itemIndex]
      if (isRecord(item) && isTodoListItem(item)) {
        return item
      }
    }
  }
  return null
}

function isTodoListItem(item: JsonRecord) {
  return ['todo-list', 'todoList', 'todo_list'].includes(String(item.type ?? ''))
}

function todoItems(item: JsonRecord | null) {
  const plan = Array.isArray(item?.plan)
    ? item.plan
    : Array.isArray(item?.items)
      ? item.items
      : Array.isArray(item?.todos)
        ? item.todos
        : []
  return plan
    .filter(isRecord)
    .map((todo, index) => ({
      id: firstString(todo.id) || `${index}`,
      step: firstString(todo.step, todo.text, todo.content, todo.title) || `Task ${index + 1}`,
      status: firstString(todo.status, todo.state).toLowerCase() || 'pending',
    }))
}

function todoSummary(item: JsonRecord | null) {
  const todos = todoItems(item)
  const completed = todos.filter((todo) => isTodoComplete(todo.status)).length
  if (!todos.length) {
    return 'To do list'
  }
  if (completed === 0) {
    return `To do list created with ${todos.length} ${todos.length === 1 ? 'task' : 'tasks'}`
  }
  return `${completed} out of ${todos.length} ${todos.length === 1 ? 'task' : 'tasks'} completed`
}

function isTodoComplete(status: string) {
  return status === 'completed' || status === 'complete'
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }
  return ''
}

function contextWindowState(state: CodexConversationState | null) {
  const explicit = explicitContextWindow(state)
  if (explicit) {
    return explicit
  }

  return {
    label: '--',
    detail: 'Token usage unavailable',
    percent: 0,
    estimated: false,
  }
}

function explicitContextWindow(state: CodexConversationState | null) {
  const candidates = [
    state?.latestTokenUsageInfo?.tokenUsage,
    state?.latestTokenUsageInfo,
    state?.contextWindow,
    state?.context_window,
    state?.context,
    state?.tokenUsage,
    state?.token_usage,
  ]
  for (const candidate of candidates) {
    if (!isRecord(candidate)) {
      continue
    }
    const tokenUsage = recordFromRecord(candidate, ['tokenUsage', 'token_usage'])
    const usage = tokenUsage ?? candidate
    const lastBreakdown = recordFromRecord(usage, ['last'])
    const used = lastBreakdown
      ? numberFromRecord(lastBreakdown, ['totalTokens', 'total_tokens'])
      : numberFromRecord(usage, ['usedTokens', 'used_tokens', 'inputTokens', 'input_tokens', 'used', 'totalTokens', 'total_tokens'])
    const total = numberFromRecord(usage, ['modelContextWindow', 'model_context_window', 'totalTokens', 'total_tokens', 'limit', 'maxTokens', 'max_tokens'])
    const percent = numberFromRecord(candidate, ['percent', 'ratio'])
    if (used != null && total != null && total > 0) {
      const clampedUsed = Math.min(used, total)
      const computedPercent = Math.min(Math.round((clampedUsed / total) * 100), 100)
      return {
        label: `${computedPercent}%`,
        detail: `${formatTokenCount(clampedUsed)} / ${formatTokenCount(total)} tokens`,
        percent: computedPercent,
        estimated: false,
      }
    }
    if (percent != null) {
      const normalized = percent <= 1 ? percent * 100 : percent
      return {
        label: `${Math.round(normalized)}%`,
        detail: 'Context window',
        percent: Math.min(Math.round(normalized), 100),
        estimated: false,
      }
    }
  }
  return null
}

function recordFromRecord(record: JsonRecord, keys: string[]) {
  for (const key of keys) {
    const value = record[key]
    if (isRecord(value)) {
      return value
    }
  }
  return null
}

function numberFromRecord(record: JsonRecord, keys: string[]) {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value
    }
  }
  return null
}

function formatTokenCount(value: number) {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`
  }
  if (value >= 1000) {
    return `${Math.round(value / 1000)}k`
  }
  return String(value)
}

function goalStatusText(goal: CodexThreadGoal | null) {
  if (!goal) {
    return 'Goal'
  }
  const status = String(goal.status)
  if (status === 'active') {
    return 'Pursuing goal'
  }
  if (status === 'paused') {
    return 'Paused goal'
  }
  if (status === 'blocked') {
    return 'Goal blocked'
  }
  if (status === 'usageLimited') {
    return 'Goal usage limited'
  }
  if (status === 'budgetLimited') {
    return 'Goal limited'
  }
  if (status === 'complete') {
    return 'Goal achieved'
  }
  return 'Goal'
}

function goalProgressText(goal: CodexThreadGoal | null) {
  if (!goal) {
    return ''
  }
  const seconds = typeof goal.timeUsedSeconds === 'number' ? goal.timeUsedSeconds : 0
  const minutes = Math.floor(seconds / 60)
  const time = minutes > 0 ? `${minutes}m` : `${seconds}s`
  if (typeof goal.tokenBudget === 'number' && goal.tokenBudget > 0) {
    const used = typeof goal.tokensUsed === 'number' ? goal.tokensUsed : 0
    return `${formatTokenCount(used)} / ${formatTokenCount(goal.tokenBudget)} tokens · ${time}`
  }
  return time
}
</script>

<template>
  <section
    class="sticky bottom-0 z-10 mt-auto w-full pb-[calc(1rem+env(safe-area-inset-bottom))] pt-4"
    ref="composerShell"
    data-codex-composer-shell
  >
    <div class="pointer-events-none absolute inset-x-0 bottom-0 z-0 h-full bg-gradient-to-t from-[rgba(255,253,247,1)] via-[rgba(255,253,247,0.96)] to-transparent"></div>
    <div
      class="relative z-10 mx-auto flex w-full max-w-[var(--thread-content-max-width,64rem)] flex-col px-4 max-sm:px-2.5"
      data-pip-obstacle="thread-footer"
    >
      <div
        v-if="latestTodoList"
        class="relative z-10 mb-2 w-fit max-w-(--thread-content-max-width) min-w-0 overflow-hidden rounded-3xl border border-[color:var(--app-border)] bg-white/95 px-3 py-2 text-sm shadow-[0_10px_26px_rgba(24,44,48,0.1)] backdrop-blur-sm"
        data-codex-floating-todo-list
      >
        <button
          type="button"
          class="group flex max-w-full min-w-0 cursor-default items-center justify-between gap-3 text-left"
          :aria-expanded="todoExpanded"
          data-codex-floating-todo-toggle
          @click="todoExpanded = !todoExpanded"
        >
          <span class="min-w-0 truncate text-[color:var(--app-text-soft)]">
            {{ latestTodoSummary }}
          </span>
          <span
            v-if="latestTodoItems.length"
            class="shrink-0 text-xs font-semibold text-[color:var(--app-text-soft)]/70"
          >
            {{ latestTodoCompletedCount }}/{{ latestTodoItems.length }}
          </span>
          <i
            class="pi pi-chevron-down shrink-0 text-[0.62rem] text-[color:var(--app-text-soft)] opacity-0 transition-all duration-300 group-hover:opacity-100"
            :class="todoExpanded ? 'rotate-180 opacity-100' : ''"
          ></i>
        </button>
        <div
          v-if="todoExpanded"
          class="vertical-scroll-fade-mask mt-2 max-h-40 space-y-1 overflow-y-auto [--edge-fade-distance:2rem]"
          data-codex-floating-todo-items
        >
          <div
            v-for="(todo, todoIndex) in latestTodoItems"
            :key="todo.id"
            class="flex min-w-0 items-center gap-2"
            data-codex-floating-todo-item
          >
            <i
              class="pi shrink-0 text-[0.64rem]"
              :class="isTodoComplete(todo.status) ? 'pi-check text-emerald-700' : 'pi-circle text-[color:var(--app-text-soft)]'"
            ></i>
            <span class="shrink-0 text-[color:var(--app-text-soft)]/80">
              {{ todoIndex + 1 }}.
            </span>
            <span
              class="min-w-0 text-[color:var(--app-text-soft)]/80 [overflow-wrap:anywhere]"
              :class="isTodoComplete(todo.status) ? 'line-through' : ''"
            >
              {{ todo.step }}
            </span>
          </div>
        </div>
      </div>
      <div
        class="grid min-w-0 gap-2 rounded-xl border border-[color:var(--app-border)] bg-white/95 p-2 shadow-[0_8px_22px_rgba(24,44,48,0.08)] transition"
        data-codex-composer
      >
        <div
          v-if="hasThreadGoal || isGoalComposeMode"
          class="-mb-1 flex min-w-0 flex-wrap items-center gap-1.5 px-1 text-xs"
          data-codex-goal-panel
        >
          <template v-if="hasThreadGoal">
            <span
              class="inline-flex h-7 min-w-0 max-w-full items-center gap-1.5 rounded-lg bg-[rgba(21,94,99,0.08)] px-2 font-bold text-[color:var(--app-accent)]"
              data-codex-goal-status
            >
              <i class="pi pi-flag text-[0.62rem]"></i>
              <span class="truncate">{{ goalStatusLabel }}</span>
            </span>
            <span class="min-w-0 flex-1 truncate font-semibold text-[color:var(--app-text)]">
              {{ goalObjective }}
            </span>
            <span class="shrink-0 text-[color:var(--app-text-soft)]">
              {{ goalDetail }}
            </span>
            <button
              v-if="canResumeGoal"
              type="button"
              class="inline-flex h-7 w-7 items-center justify-center rounded-md text-[color:var(--app-text-soft)] transition hover:bg-[rgba(21,94,99,0.07)] hover:text-[color:var(--app-text)] disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="Resume goal"
              :disabled="busy || disabled"
              data-codex-goal-resume
              @click="emit('updateThreadGoalStatus', 'active')"
            >
              <i class="pi pi-play text-[0.62rem]"></i>
            </button>
            <button
              v-else-if="goalStatus === 'active'"
              type="button"
              class="inline-flex h-7 w-7 items-center justify-center rounded-md text-[color:var(--app-text-soft)] transition hover:bg-[rgba(21,94,99,0.07)] hover:text-[color:var(--app-text)] disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="Pause goal"
              :disabled="busy || disabled"
              data-codex-goal-pause
              @click="emit('updateThreadGoalStatus', 'paused')"
            >
              <i class="pi pi-pause text-[0.62rem]"></i>
            </button>
            <button
              type="button"
              class="inline-flex h-7 w-7 items-center justify-center rounded-md text-[color:var(--app-text-soft)] transition hover:bg-[rgba(21,94,99,0.07)] hover:text-[color:var(--app-text)] disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="Complete goal"
              :disabled="busy || disabled"
              data-codex-goal-complete
              @click="emit('updateThreadGoalStatus', 'complete')"
            >
              <i class="pi pi-check text-[0.62rem]"></i>
            </button>
            <button
              type="button"
              class="inline-flex h-7 w-7 items-center justify-center rounded-md text-[color:var(--app-text-soft)] transition hover:bg-[rgba(21,94,99,0.07)] hover:text-[color:var(--app-text)] disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="Mark goal blocked"
              :disabled="busy || disabled"
              data-codex-goal-blocked
              @click="emit('updateThreadGoalStatus', 'blocked')"
            >
              <i class="pi pi-ban text-[0.62rem]"></i>
            </button>
            <button
              type="button"
              class="inline-flex h-7 w-7 items-center justify-center rounded-md text-[color:var(--app-text-soft)] transition hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="Clear goal"
              :disabled="busy || disabled"
              data-codex-goal-clear
              @click="emit('clearThreadGoal')"
            >
              <i class="pi pi-times text-[0.62rem]"></i>
            </button>
          </template>
          <template v-else>
            <span
              class="inline-flex h-7 items-center gap-1.5 rounded-lg bg-[rgba(21,94,99,0.08)] px-2 font-bold text-[color:var(--app-accent)]"
              data-codex-goal-status
            >
              <i class="pi pi-flag text-[0.62rem]"></i>
              New goal
            </span>
          </template>
        </div>

        <div
          v-if="queuedFollowups.length"
          class="vertical-scroll-fade-mask hide-scrollbar -mx-1 -mt-1 flex max-h-[30dvh] flex-col gap-px overflow-x-hidden overflow-y-auto rounded-t-xl border-b border-[rgba(34,66,72,0.1)] px-3 py-2 max-sm:px-2"
          data-codex-queued-followups
        >
          <article
            v-for="(followup, index) in queuedFollowups"
            :key="followupId(followup, index)"
            class="group flex min-w-0 items-center justify-between gap-2 py-0.5 text-sm"
          >
            <div class="flex min-w-0 flex-1 items-start gap-1.5">
              <span
                class="relative -ml-3 flex h-4 shrink-0 cursor-default items-center justify-center pl-3 text-[color:var(--app-text-soft)]/70"
                aria-hidden="true"
              >
                <i
                  class="pi pi-bars pointer-events-none absolute left-0 top-1/2 -translate-y-1/2 text-[0.56rem] opacity-0 transition-opacity group-hover:opacity-100"></i>
                <i class="pi pi-clock text-[0.62rem]"></i>
              </span>
              <span class="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap leading-4 text-[color:var(--app-text-soft)]">
                {{ followupText(followup) }}
              </span>
            </div>
            <div
              class="flex shrink-0 items-center gap-1 opacity-80 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 sm:opacity-0"
            >
              <button
                type="button"
                class="inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2 text-xs font-semibold text-[color:var(--app-text)] transition hover:bg-[rgba(21,94,99,0.07)] disabled:cursor-not-allowed disabled:opacity-45"
                aria-label="Steer queued follow-up"
                title="Submit without interrupting the model"
                :disabled="!isWorking || busy || disabled"
                data-codex-queued-steer
                @click="steerFollowup(followup, index)"
              >
                <i class="pi pi-directions text-[0.68rem]"></i>
                <span>Steer</span>
              </button>
              <button
                type="button"
                class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[color:var(--app-text-soft)] transition hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-45"
                aria-label="Remove queued follow-up"
                :disabled="busy"
                data-codex-queued-remove
                @click="emit('removeFollowup', followupId(followup, index))"
              >
                <i class="pi pi-times text-[0.62rem]"></i>
              </button>
            </div>
          </article>
        </div>

        <div
          v-if="skillAttachments.length"
          class="grid min-w-0 gap-1 px-1 pb-1"
          data-codex-skill-attachments
        >
          <article
            v-for="(attachment, index) in skillAttachments"
            :key="`${skillAttachmentLabel(attachment)}-${index}`"
            class="group grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)_1.5rem] items-center gap-2 rounded-lg border border-[rgba(34,66,72,0.1)] bg-[rgba(255,253,247,0.82)] px-2 py-1.5 text-sm"
            data-codex-skill-attachment
          >
            <i class="pi pi-sparkles text-[0.72rem] text-[color:var(--app-text-soft)]"></i>
            <span class="min-w-0">
              <span class="block truncate font-semibold text-[color:var(--app-text)]">
                {{ skillAttachmentLabel(attachment) }}
              </span>
              <span class="block truncate text-[0.68rem] text-[color:var(--app-text-soft)]">
                {{ skillAttachmentScope(attachment) || 'Skill' }}
              </span>
            </span>
            <button
              type="button"
              class="inline-flex h-6 w-6 items-center justify-center rounded-md text-[0.6rem] text-[color:var(--app-text-soft)] opacity-80 transition hover:bg-red-50 hover:text-red-700 group-hover:opacity-100"
              :aria-label="`Remove ${skillAttachmentLabel(attachment)}`"
              data-codex-skill-remove
              @click="removeSkillAttachment(index)"
            >
              <i class="pi pi-times"></i>
            </button>
          </article>
        </div>

        <div
          v-if="fileAttachments.length"
          class="grid min-w-0 gap-1 px-1 pb-1"
          data-codex-file-attachments
        >
          <article
            v-for="(attachment, index) in fileAttachments"
            :key="`${fileAttachmentPath(attachment)}-${index}`"
            class="group grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)_1.5rem] items-center gap-2 rounded-lg border border-[rgba(34,66,72,0.1)] bg-[rgba(255,253,247,0.82)] px-2 py-1.5 text-sm"
            data-codex-file-attachment
          >
            <i class="pi pi-paperclip text-[0.72rem] text-[color:var(--app-text-soft)]"></i>
            <span class="min-w-0">
              <span class="block truncate font-semibold text-[color:var(--app-text)]">{{ fileAttachmentName(attachment, index) }}</span>
              <span class="block truncate text-[0.68rem] text-[color:var(--app-text-soft)]">{{ fileAttachmentPath(attachment) }}</span>
            </span>
            <button
              type="button"
              class="inline-flex h-6 w-6 items-center justify-center rounded-md text-[0.6rem] text-[color:var(--app-text-soft)] opacity-80 transition hover:bg-red-50 hover:text-red-700 group-hover:opacity-100"
              :aria-label="`Remove ${fileAttachmentName(attachment, index)}`"
              data-codex-file-remove
              @click="removeFileAttachment(index)"
            >
              <i class="pi pi-times"></i>
            </button>
          </article>
        </div>

        <div
          v-if="imageAttachments.length"
          class="flex min-w-0 gap-2 overflow-x-auto px-1 pb-1"
          data-codex-image-attachments
        >
          <article
            v-for="(attachment, index) in imageAttachments"
            :key="`${imageAttachmentName(attachment, index)}-${index}`"
            class="group relative h-16 w-16 shrink-0 overflow-hidden rounded-lg border border-[color:var(--app-border)] bg-[rgba(255,253,247,0.86)]"
            data-codex-image-attachment
          >
            <img
              v-if="imageAttachmentSrc(attachment)"
              class="h-full w-full object-cover"
              :src="imageAttachmentSrc(attachment)"
              :alt="imageAttachmentName(attachment, index)"
            />
            <button
              type="button"
              class="absolute right-1 top-1 inline-flex h-5 w-5 items-center justify-center rounded-md bg-white/90 text-[0.56rem] text-[color:var(--app-text-soft)] opacity-0 shadow-sm transition hover:text-red-700 group-hover:opacity-100 group-focus-within:opacity-100"
              :aria-label="`Remove ${imageAttachmentName(attachment, index)}`"
              data-codex-image-remove
              @click="removeImageAttachment(index)"
            >
              <i class="pi pi-times"></i>
            </button>
          </article>
        </div>

        <textarea
          ref="composerTextarea"
          v-model="draft"
          class="max-h-52 min-h-16 w-full min-w-0 resize-none rounded-lg border-0 bg-transparent px-2 py-2 text-sm leading-6 text-[color:var(--app-text)] outline-none placeholder:text-[color:var(--app-text-soft)] max-sm:min-h-14"
          :disabled="disabled"
          :placeholder="composerPlaceholder"
          data-codex-composer-textarea
          @keydown="onKeydown"
          @input="onComposerInput"
          @click="onComposerClick"
          @select="onComposerSelect"
          @keyup="onComposerSelect"
          @paste="onPaste"
        ></textarea>

        <div
          v-if="statusPanelOpen"
          class="mx-2 mb-2 grid gap-1 rounded-lg border border-[color:var(--app-border)] bg-[rgba(255,253,247,0.96)] px-3 py-2 text-xs text-[color:var(--app-text-soft)]"
          data-codex-status-panel
        >
          <div class="flex items-center justify-between gap-2">
            <p class="m-0 text-sm font-semibold text-[color:var(--app-text)]">Thread status</p>
            <button
              type="button"
              class="inline-flex h-6 w-6 items-center justify-center rounded-md text-[color:var(--app-text-soft)] transition hover:bg-[rgba(21,94,99,0.06)] hover:text-[color:var(--app-text)]"
              aria-label="Close status"
              data-codex-status-close
              @click="statusPanelOpen = false"
            >
              <i class="pi pi-times text-[0.65rem]"></i>
            </button>
          </div>
          <p class="m-0" data-codex-status-thread>
            <span class="font-semibold text-[color:var(--app-text)]">Thread</span>
            {{ statusDetails.threadId || '—' }}
          </p>
          <p class="m-0" data-codex-status-cwd>
            <span class="font-semibold text-[color:var(--app-text)]">Cwd</span>
            {{ statusDetails.cwd || '—' }}
          </p>
          <p class="m-0" data-codex-status-model>
            <span class="font-semibold text-[color:var(--app-text)]">Model</span>
            {{ statusDetails.model }} · {{ statusDetails.reasoning }} · {{ statusDetails.mode }}
          </p>
          <p class="m-0" data-codex-status-context>
            <span class="font-semibold text-[color:var(--app-text)]">Context</span>
            {{ statusDetails.contextLabel }} · {{ statusDetails.contextDetail }}
            <span v-if="statusDetails.contextPercent != null">
              ({{ statusDetails.contextPercent }}%)
            </span>
          </p>
        </div>

        <CodexSlashCommandMenu
          :open="slashMenuOpen"
          :commands="filteredSlashCommands"
          :selected-index="slashSelectedIndex"
          :query="slashMatch?.query ?? ''"
          :loading="skillsLoading"
          :anchor-style="slashMenuStyle"
          @select="selectSlashCommand"
          @hover="slashSelectedIndex = $event"
        />

        <div
          class="composer-footer flex min-w-0 items-center justify-between gap-2 max-sm:gap-1"
          data-codex-composer-footer
        >
          <div
            class="hide-scrollbar flex min-w-0 flex-1 items-center gap-1 overflow-visible max-sm:gap-0.5"
            data-codex-composer-controls
          >
            <div class="relative shrink-0">
              <button
                ref="addMenuTrigger"
                type="button"
                class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-xl font-light leading-none text-[color:var(--app-text-soft)] transition hover:bg-[rgba(21,94,99,0.06)] hover:text-[color:var(--app-text)] disabled:cursor-not-allowed disabled:opacity-45 max-sm:h-7 max-sm:w-7 max-sm:text-lg"
                :disabled="busy || disabled"
                :aria-expanded="addMenuOpen"
                aria-label="Open composer actions"
                title="Open composer actions"
                data-codex-add-menu-trigger
                @click="toggleAddMenu"
              >
                +
              </button>
              <div
                v-if="addMenuOpen"
                class="fixed z-[100] grid w-80 max-w-[calc(100vw-1.5rem)] gap-1 rounded-xl border border-[color:var(--app-border)] bg-white p-1.5 text-sm shadow-xl"
                :style="addMenuStyle"
                data-codex-add-menu
              >
                <p class="m-0 px-2 py-1 text-xs font-semibold text-[color:var(--app-text-soft)]">Add</p>
                <button
                  type="button"
                  class="grid grid-cols-[1rem_minmax(0,1fr)] items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[color:var(--app-text)] transition hover:bg-[rgba(21,94,99,0.06)] disabled:cursor-not-allowed disabled:opacity-45"
                  :disabled="busy || disabled || isWorking"
                  data-codex-files-attach
                  @click="openFileAttachmentPicker"
                >
                  <i class="pi pi-paperclip text-[0.72rem] text-[color:var(--app-text-soft)]"></i>
                  <span>Files and folders</span>
                </button>
                <button
                  type="button"
                  class="grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-2 rounded-lg px-2 py-1.5 text-left text-[color:var(--app-text)] transition hover:bg-[rgba(21,94,99,0.06)] disabled:cursor-not-allowed disabled:opacity-45"
                  :disabled="busy || disabled || isWorking || hasThreadGoal"
                  data-codex-menu-goal
                  @click="startGoalMode"
                >
                  <i class="pi pi-flag mt-1 text-[0.72rem] text-[color:var(--app-text-soft)]"></i>
                  <span>
                    <span class="block">Goal</span>
                    <span class="block text-[0.68rem] leading-4 text-[color:var(--app-text-soft)]">
                      Set a goal that Codex will keep working towards
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  class="grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-2 rounded-lg px-2 py-1.5 text-left text-[color:var(--app-text)] transition hover:bg-[rgba(21,94,99,0.06)] disabled:cursor-not-allowed disabled:opacity-45"
                  :disabled="busy || disabled"
                  data-codex-menu-plan
                  @click="startPlanMode"
                >
                  <i class="pi pi-list-check mt-1 text-[0.72rem] text-[color:var(--app-text-soft)]"></i>
                  <span>
                    <span class="block">Plan mode</span>
                    <span class="block text-[0.68rem] leading-4 text-[color:var(--app-text-soft)]">
                      {{ mode === 'plan' ? 'Turn plan mode off' : 'Turn plan mode on' }}
                    </span>
                  </span>
                </button>
              </div>
            </div>

            <div
              class="relative shrink-0"
              data-codex-permission-pill
            >
              <button
                type="button"
                :class="[
                  'codex-permission-trigger inline-flex h-8 max-w-44 items-center gap-1.5 rounded-lg px-2 text-sm font-semibold transition hover:bg-[rgba(21,94,99,0.06)] disabled:cursor-not-allowed disabled:opacity-45 max-sm:h-7 max-sm:max-w-28 max-sm:gap-1 max-sm:px-1.5 max-sm:text-xs',
                  `codex-permission-tone-${selectedPermissionMode}`,
                ]"
                :disabled="busy || disabled"
                aria-label="Change permissions"
                data-codex-permission-trigger
                data-codex-permission-select
                @click="togglePermissionMenu"
              >
                <i :class="activePermissionOption.icon" class="text-[0.58rem] max-sm:text-[0.5rem]"></i>
                <span class="min-w-0 truncate max-sm:hidden">{{ activePermissionOption.label }}</span>
                <span class="hidden min-w-0 truncate max-sm:inline">{{ activePermissionOption.mobileLabel }}</span>
                <i class="pi pi-chevron-down text-[0.4rem] text-[color:var(--app-text-soft)] max-sm:text-[0.36rem]"></i>
              </button>
              <Popover
                ref="permissionPopover"
                append-to="body"
                class="codex-permission-popover"
                data-codex-permission-menu
              >
                <div class="grid gap-1" aria-label="Permission settings">
                  <button
                    v-for="option in permissionOptions"
                    :key="option.value"
                    type="button"
                    class="codex-permission-choice"
                    :class="selectedPermissionMode === option.value ? 'codex-permission-choice-active' : ''"
                    data-codex-permission-option
                    @click="choosePermissionMode(option.value)"
                  >
                    <i :class="option.icon" class="mt-1 text-[0.72rem]" :data-permission-tone="option.tone"></i>
                    <span class="min-w-0">
                      <span class="block truncate text-sm font-semibold text-[color:var(--app-text)]">{{ option.label }}</span>
                      <span class="block text-[0.68rem] font-normal leading-4 text-[color:var(--app-text-soft)]">
                        {{ option.description }}
                      </span>
                    </span>
                    <i v-if="selectedPermissionMode === option.value" class="pi pi-check text-[0.68rem] text-[color:var(--app-text-soft)]"></i>
                  </button>
                </div>
              </Popover>
            </div>

            <input
              v-if="isGoalComposeMode && !hasThreadGoal"
              v-model="goalTokenBudgetDraft"
              class="h-8 w-20 shrink-0 rounded-lg bg-[rgba(34,66,72,0.06)] px-2 text-sm text-[color:var(--app-text)] outline-none placeholder:text-[color:var(--app-text-soft)]"
              :disabled="busy || disabled"
              inputmode="numeric"
              placeholder="Tokens"
              aria-label="Goal token budget"
              data-codex-goal-token-budget
              @keydown.enter.prevent="submitGoal"
            />

          </div>

          <div class="flex shrink-0 items-center justify-end gap-1 max-sm:gap-0.5">
            <div
              class="group/context relative inline-flex h-8 w-8 max-w-full shrink-0 items-center justify-center rounded-lg px-2 text-xs text-[color:var(--app-text-soft)] outline-none transition hover:bg-[rgba(21,94,99,0.06)] focus-visible:bg-[rgba(21,94,99,0.06)] focus-visible:ring-2 focus-visible:ring-[rgba(21,94,99,0.18)] max-sm:h-7 max-sm:w-7 max-sm:px-1"
              :aria-label="contextHoverTitle"
              tabindex="0"
              data-codex-context-window
            >
              <span
                class="relative h-3.5 w-3.5 shrink-0 rounded-full"
                :style="contextRingStyle"
                aria-hidden="true"
                data-codex-context-ring
              >
                <span class="absolute inset-[3px] rounded-full bg-white"></span>
              </span>
              <span
                class="pointer-events-none absolute bottom-full right-0 z-50 mb-2 w-max max-w-[16rem] rounded-lg border border-[color:var(--app-border)] bg-white px-2.5 py-1.5 text-xs font-semibold text-[color:var(--app-text)] opacity-0 shadow-xl transition-opacity group-hover/context:opacity-100 group-focus-within/context:opacity-100"
                data-codex-context-tooltip
              >
                {{ contextHoverTitle }}
              </span>
            </div>
            <div class="relative min-w-0 shrink-0">
              <button
                type="button"
                class="codex-intelligence-trigger inline-flex h-8 max-w-44 items-center gap-1.5 rounded-lg px-2 text-sm font-semibold text-[color:var(--app-text)] transition hover:bg-[rgba(21,94,99,0.06)] disabled:cursor-not-allowed disabled:opacity-45 max-sm:h-7 max-sm:max-w-28 max-sm:gap-1 max-sm:px-1.5 max-sm:text-xs"
                :disabled="busy || disabled"
                aria-label="Select model and reasoning effort"
                :title="`${activeModel} · ${activeReasoningEffort}`"
                data-codex-intelligence-trigger
                @click="toggleIntelligenceMenu"
              >
                <span class="min-w-0 truncate">{{ intelligenceTriggerLabel }}</span>
                <i class="pi pi-chevron-down text-[0.48rem] text-[color:var(--app-text-soft)] max-sm:text-[0.42rem]"></i>
              </button>
              <Popover
                ref="intelligencePopover"
                append-to="body"
                class="codex-intelligence-popover"
                data-codex-intelligence-popover
              >
                <div class="grid gap-3" aria-label="Model and reasoning settings" data-codex-intelligence-menu>
                  <section class="grid gap-1.5" data-codex-reasoning-section>
                    <p class="codex-intelligence-section-title">Reasoning</p>
                    <div class="grid gap-1">
                      <button
                        v-for="option in reasoningOptions"
                        :key="option.value"
                        type="button"
                        class="codex-intelligence-choice"
                        :class="activeReasoningEffort === option.value ? 'codex-intelligence-choice-active' : ''"
                        data-codex-reasoning-option
                        @click="chooseReasoningEffort(option.value)"
                      >
                        <span class="min-w-0 truncate">{{ option.label }}</span>
                        <i v-if="activeReasoningEffort === option.value" class="pi pi-check"></i>
                      </button>
                    </div>
                  </section>

                  <section class="grid gap-1.5" data-codex-model-section>
                    <p class="codex-intelligence-section-title">Model</p>
                    <div class="grid gap-1">
                      <button
                        v-for="option in modelOptions"
                        :key="option.value"
                        type="button"
                        class="codex-intelligence-choice"
                        :class="activeModel === option.value ? 'codex-intelligence-choice-active' : ''"
                        data-codex-model-option
                        @click="chooseModel(option.value)"
                      >
                        <span class="min-w-0 truncate">{{ option.label }}</span>
                        <i v-if="activeModel === option.value" class="pi pi-check"></i>
                      </button>
                    </div>
                  </section>
                </div>
              </Popover>
            </div>
            <button
              type="button"
              class="inline-flex h-10 min-w-10 items-center justify-center rounded-full px-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-45 max-sm:h-9 max-sm:min-w-9 max-sm:px-2.5"
              :class="primaryAction === 'stop'
                ? 'border border-red-200 bg-white text-red-700 hover:bg-red-50'
                : 'bg-[color:var(--app-accent)] text-white hover:brightness-95'
                "
              :disabled="primaryDisabled"
              :aria-label="primaryLabel"
              :title="primaryTitle"
              data-codex-primary-submit
              @click="submitPrimary"
            >
              <i
                :class="primaryIcon"
                class="text-xs"
              ></i>
              <span class="sr-only">{{ primaryLabel }}</span>
            </button>
          </div>
        </div>

      </div>
    </div>
    <CodexHostPathPicker
      v-model:visible="filePickerOpen"
      title="Add files and folders"
      confirm-label="Use this folder"
      :selected-path="typeof state?.cwd === 'string' ? state.cwd : ''"
      :disabled="busy || disabled"
      allow-files
      :allow-current-folder="true"
      @select="addFileAttachment"
    />
  </section>
</template>
