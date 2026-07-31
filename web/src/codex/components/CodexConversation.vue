<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Dialog from 'primevue/dialog'
import Galleria from 'primevue/galleria'

import type { CodexConversationState, CodexTurnState, JsonRecord } from '../types'
import {
  compactJson,
  formatTimestamp,
  isRecord,
  isWorkingStatus,
  statusLabel,
  textFromInput,
} from '../lib/format'
import { useCodexMarkdown } from '../lib/markdown'
import { summarizeToolActivity, type ToolActivitySummary } from '../lib/toolActivitySummary'
import { userMessageDisplayText } from '../lib/userMessage'
import CodexThinkingShimmer from './CodexThinkingShimmer.vue'
import CodexWorkedLabel from './CodexWorkedLabel.vue'

const props = defineProps<{
  state: CodexConversationState | null
}>()

const emit = defineEmits<{
  forkThread: [threadId: string]
  copyError: [message: string]
}>()

type ConversationItemKind = 'user' | 'assistant' | 'work' | 'system' | 'unknown'
type TurnBlockKind = 'user' | 'work' | 'assistant' | 'system' | 'unknown'
type WorkRenderUnitKind = 'message' | 'activity' | 'todo' | 'context' | 'image'

interface ConversationItemView {
  id: string
  item: JsonRecord
  kind: ConversationItemKind
}

interface TurnBlockView {
  id: string
  kind: TurnBlockKind
  items: ConversationItemView[]
  workUnits?: WorkRenderUnit[]
}

interface WorkRenderUnit {
  id: string
  kind: WorkRenderUnitKind
  items: ConversationItemView[]
  summary?: ToolActivitySummary
}

interface TurnView {
  key: string
  turn: CodexTurnState
  blocks: TurnBlockView[]
  workItems: ConversationItemView[]
  finalResponseItems: ConversationItemView[]
  report: TurnReport
}

interface TurnReport {
  summary: string
  changedFileCount: number
  linesAdded: number
  linesRemoved: number
  commandCount: number
  toolCount: number
  changedFiles: FileChangeView[]
}

interface VirtualTurnView {
  turnView: TurnView
  originalIndex: number
}

interface FileChangeView {
  path: string
  action: 'created' | 'edited' | 'deleted' | 'renamed' | 'changed'
  linesAdded: number
  linesRemoved: number
}

const workItemTypes = new Set([
  'hookPrompt',
  'reasoning',
  'commandExecution',
  'fileChange',
  'webSearch',
  'search',
  'git',
  'dynamicToolCall',
  'mcpToolCall',
  'collabAgentToolCall',
  'subAgentActivity',
  'userInputResponse',
  'sleep',
  'imageGeneration',
  'imageView',
  'steer',
  'steered',
  'steeringUserMessage',
  'contextCompaction',
  'context-compaction',
  'todo-list',
  'todoList',
  'todo_list',
])

const responseItemTypes = new Set(['agentMessage', 'plan'])
const userItemTypes = new Set(['userMessage'])
const turnVirtualizationThreshold = 30
const initialHydratedTurnCount = 12
const estimatedTurnHeightPx = 720
const virtualTurnGapPx = 24
const virtualOverscanPx = 2400

const turns = computed<CodexTurnState[]>(() =>
  Array.isArray(props.state?.turns) ? props.state.turns : [],
)
const hydratedTurnStartIndex = ref(0)
const turnViews = computed<TurnView[]>(() =>
  turns.value
    .slice(hydratedTurnStartIndex.value)
    .map((turn, offset) => turnView(turn, hydratedTurnStartIndex.value + offset)),
)
const hiddenHydratedTurnHeight = computed(() =>
  hydratedTurnStartIndex.value > 0
    ? hydratedTurnStartIndex.value * (estimatedTurnHeightPx + virtualTurnGapPx)
    : 0,
)
const isTurnVirtualized = computed(() => turns.value.length > turnVirtualizationThreshold)
const { renderMarkdown, onMarkdownClick } = useCodexMarkdown()
const conversationBody = ref<HTMLElement | null>(null)
const shouldStickToBottom = ref(true)
const expandedWorkByTurnKey = ref<Record<string, boolean>>({})
const expandedItemById = ref<Record<string, boolean>>({})
const imagePreviewByItemId = ref<Record<string, boolean>>({})
const measuredTurnHeights = ref<Record<string, number>>({})
const virtualScrollTop = ref(0)
const virtualViewportHeight = ref(900)
const bottomThreshold = 72
let measureFrame: number | null = null
let resizeObserver: ResizeObserver | null = null
let hydrationTimer: number | null = null

function turnMeasuredHeight(turnView: TurnView) {
  return measuredTurnHeights.value[turnView.key] ?? estimatedTurnHeightPx
}

const virtualTurnMetrics = computed(() => {
  let offset = 0
  const metrics = turnViews.value.map((turnView, index) => {
    const height = turnMeasuredHeight(turnView)
    const start = offset
    const end = start + height
    offset = end + (index === turnViews.value.length - 1 ? 0 : virtualTurnGapPx)
    return {
      start,
      end,
      height,
    }
  })
  return {
    metrics,
    totalHeight: hiddenHydratedTurnHeight.value + offset,
  }
})

const virtualTurnWindow = computed(() => {
  if (!isTurnVirtualized.value) {
    return {
      startIndex: 0,
      endIndex: Math.max(turnViews.value.length - 1, 0),
      topSpacerHeight: 0,
      bottomSpacerHeight: 0,
    }
  }

  const { metrics, totalHeight } = virtualTurnMetrics.value
  if (!metrics.length) {
    return {
      startIndex: 0,
      endIndex: -1,
      topSpacerHeight: 0,
      bottomSpacerHeight: 0,
    }
  }

  const viewportStart = Math.max(virtualScrollTop.value - virtualOverscanPx, 0)
  const viewportEnd = virtualScrollTop.value + virtualViewportHeight.value + virtualOverscanPx
  let startIndex = metrics.findIndex((metric) => metric.end >= viewportStart)
  if (startIndex < 0) {
    startIndex = metrics.length - 1
  }
  let endIndex = metrics.findIndex((metric) => metric.start > viewportEnd)
  if (endIndex < 0) {
    endIndex = metrics.length - 1
  } else {
    endIndex = Math.max(endIndex - 1, startIndex)
  }

  return {
    startIndex,
    endIndex,
    topSpacerHeight: hiddenHydratedTurnHeight.value + (metrics[startIndex]?.start ?? 0),
    bottomSpacerHeight: Math.max(
      totalHeight - (hiddenHydratedTurnHeight.value + (metrics[endIndex]?.end ?? totalHeight)),
      0,
    ),
  }
})

const visibleTurnViews = computed<VirtualTurnView[]>(() => {
  if (!isTurnVirtualized.value) {
    return turnViews.value.map((turnView, originalIndex) => ({ turnView, originalIndex }))
  }

  const { startIndex, endIndex } = virtualTurnWindow.value
  if (endIndex < startIndex) {
    return []
  }

  return turnViews.value.slice(startIndex, endIndex + 1).map((turnView, offset) => ({
    turnView,
    originalIndex: hydratedTurnStartIndex.value + startIndex + offset,
  }))
})

const virtualTopSpacerHeight = computed(() => virtualTurnWindow.value.topSpacerHeight)
const virtualBottomSpacerHeight = computed(() => virtualTurnWindow.value.bottomSpacerHeight)

function isNearBottom(element: HTMLElement) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= bottomThreshold
}

function updateVirtualViewport() {
  const element = conversationBody.value
  if (!element) {
    return
  }
  virtualScrollTop.value = element.scrollTop
  virtualViewportHeight.value = element.clientHeight || virtualViewportHeight.value
}

function scheduleTurnMeasurement() {
  if (measureFrame != null || typeof window === 'undefined') {
    return
  }
  measureFrame = window.requestAnimationFrame(() => {
    measureFrame = null
    measureVisibleTurns()
  })
}

function measureVisibleTurns() {
  const element = conversationBody.value
  if (!element) {
    return
  }

  const nextHeights = { ...measuredTurnHeights.value }
  let changed = false
  element.querySelectorAll<HTMLElement>('[data-codex-turn-key]').forEach((turnElement) => {
    const key = turnElement.dataset.codexTurnKey
    if (!key) {
      return
    }
    const height = Math.ceil(turnElement.getBoundingClientRect().height)
    if (height <= 0) {
      return
    }
    const previousHeight = nextHeights[key] ?? estimatedTurnHeightPx
    if (previousHeight !== height) {
      nextHeights[key] = height
      changed = true
    }
  })

  if (changed) {
    measuredTurnHeights.value = nextHeights
  }
}

function resetTurnMeasurements() {
  measuredTurnHeights.value = {}
}

function cancelTurnHydration() {
  if (hydrationTimer != null && typeof window !== 'undefined') {
    window.clearTimeout(hydrationTimer)
  }
  hydrationTimer = null
}

function scheduleFullTurnHydration() {
  cancelTurnHydration()
  if (hydratedTurnStartIndex.value === 0 || typeof window === 'undefined') {
    return
  }
  const hydrate = async () => {
    hydrationTimer = null
    hydratedTurnStartIndex.value = 0
    await scrollToBottomIfNeeded()
  }
  hydrationTimer = window.setTimeout(() => {
    void hydrate()
  }, 900)
}

function resetProgressiveTurnHydration() {
  cancelTurnHydration()
  hydratedTurnStartIndex.value =
    turns.value.length > turnVirtualizationThreshold
      ? Math.max(turns.value.length - initialHydratedTurnCount, 0)
      : 0
  scheduleFullTurnHydration()
}

function onConversationScroll() {
  if (!conversationBody.value) {
    return
  }
  updateVirtualViewport()
  shouldStickToBottom.value = isNearBottom(conversationBody.value)
  scheduleTurnMeasurement()
}

async function scrollToBottomIfNeeded() {
  await nextTick()
  updateVirtualViewport()
  scheduleTurnMeasurement()
  if (!conversationBody.value || !shouldStickToBottom.value) {
    return
  }
  conversationBody.value.scrollTop = conversationBody.value.scrollHeight
  updateVirtualViewport()
  await nextTick()
  scheduleTurnMeasurement()
}

async function resetBottomStickiness() {
  shouldStickToBottom.value = true
  expandedWorkByTurnKey.value = {}
  expandedItemById.value = {}
  resetTurnMeasurements()
  await scrollToBottomIfNeeded()
}

function itemKind(item: JsonRecord): ConversationItemKind {
  const type = itemType(item)
  if (isReviewModeItem(item)) {
    return 'system'
  }
  if (userItemTypes.has(type)) {
    return 'user'
  }
  if (responseItemTypes.has(type)) {
    return 'assistant'
  }
  if (workItemTypes.has(type)) {
    return 'work'
  }
  return 'unknown'
}

function turnItems(turn: CodexTurnState) {
  return Array.isArray(turn.items) ? turn.items.filter(isRecord) : []
}

function turnView(turn: CodexTurnState, index: number): TurnView {
  const rawItems = turnItems(turn)
  const finalAssistantIndex = finalAssistantItemIndex(rawItems)
  const hasReviewMode = rawItems.some(isReviewModeItem)
  const blocks: TurnBlockView[] = []
  const allWorkItems: ConversationItemView[] = []
  const finalResponseItems: ConversationItemView[] = []
  let pendingWork: ConversationItemView[] = []
  let workBlockIndex = 0

  function flushWork() {
    if (!pendingWork.length) {
      return
    }
    const items = pendingWork
    blocks.push({
      id: `${turnKey(turn, index)}-work-${workBlockIndex}`,
      kind: 'work',
      items,
      workUnits: workRenderUnits(items),
    })
    pendingWork = []
    workBlockIndex += 1
  }

  const inputUserMessage = hasReviewMode ? null : turnInputUserMessage(turn, index)
  if (inputUserMessage) {
    blocks.push({
      id: inputUserMessage.id,
      kind: 'user',
      items: [inputUserMessage],
    })
  }

  rawItems.forEach((item, itemIndex) => {
    const baseKind = itemKind(item)
    const view: ConversationItemView = {
      id: `${turnKey(turn, index)}-item-${itemIndex}-${itemId(item, itemIndex)}`,
      item,
      kind: baseKind,
    }

    if (baseKind === 'user') {
      if (hasReviewMode) {
        return
      }
      flushWork()
      blocks.push({ id: view.id, kind: 'user', items: [view] })
      return
    }

    if (baseKind === 'system') {
      flushWork()
      blocks.push({ id: view.id, kind: 'system', items: [view] })
      return
    }

    if (baseKind === 'assistant' && itemIndex === finalAssistantIndex) {
      flushWork()
      finalResponseItems.push(view)
      blocks.push({ id: view.id, kind: 'assistant', items: [view] })
      return
    }

    if (baseKind === 'assistant' || baseKind === 'work') {
      pendingWork.push(view)
      allWorkItems.push(view)
      return
    }

    flushWork()
    blocks.push({ id: view.id, kind: 'unknown', items: [view] })
  })
  flushWork()

  return {
    key: turnKey(turn, index),
    turn,
    blocks,
    workItems: allWorkItems,
    finalResponseItems,
    report: finalTurnReport(allWorkItems.map((workItem) => workItem.item)),
  }
}

function turnInputUserMessage(turn: CodexTurnState, index: number): ConversationItemView | null {
  if (turnItems(turn).some((item) => itemKind(item) === 'user')) {
    return null
  }
  const params = isRecord(turn.params) ? turn.params : null
  const text = outputText(params?.input)
  if (!text) {
    return null
  }
  const isGoal = isGoalCommandText(userMessageDisplayText(text))
  return {
    id: `${turnKey(turn, index)}-params-input-user-message`,
    item: {
      id: `${turnKey(turn, index)}-params-input`,
      type: 'userMessage',
      content: text,
      goal: isGoal,
      sentAsGoal: isGoal,
      createdAt: turn.turnStartedAtMs ?? undefined,
    },
    kind: 'user',
  }
}

function finalAssistantItemIndex(items: JsonRecord[]) {
  const explicitIndex = findLastIndex(items, (item) => {
    const phase = firstString(item.phase)
    return itemType(item) === 'agentMessage' && phase === 'final_answer'
  })
  if (explicitIndex >= 0) {
    return explicitIndex
  }
  return findLastIndex(
    items,
    (item) => responseItemTypes.has(itemType(item)) && !firstString(item.phase),
  )
}

function findLastIndex<T>(items: T[], predicate: (item: T, index: number) => boolean) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index] as T, index)) {
      return index
    }
  }
  return -1
}

function itemType(item: JsonRecord) {
  return typeof item.type === 'string' && item.type ? item.type : 'unknown'
}

function isSteeringMessageType(type: string) {
  return type === 'steer' || type === 'steeringUserMessage'
}

function itemId(item: JsonRecord, index: number) {
  return typeof item.id === 'string' && item.id ? item.id : `${itemType(item)}-${index}`
}

function outputText(value: unknown) {
  const text = textFromInput(value)
  return text.trim()
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }
  return ''
}

function firstNumber(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value
    }
  }
  return null
}

function coerceMs(value: number | null | undefined) {
  if (!value) {
    return null
  }
  return value > 10_000_000_000 ? value : value * 1000
}

function formatDuration(ms: number | null | undefined) {
  if (!ms || ms <= 0) {
    return ''
  }
  if (ms < 1000) {
    return `${Math.max(1, Math.round(ms))}ms`
  }
  const seconds = Math.max(1, Math.round(ms / 1000))
  if (seconds < 60) {
    return `${seconds}s`
  }
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes < 60) {
    return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`
  }
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`
}

function firstTurnWorkItemStartedAtMsFromItems(turn: CodexTurnState) {
  const items = turnItems(turn)
  for (const item of items) {
    if (!workItemTypes.has(itemType(item))) {
      continue
    }
    const startedAtMs = firstNumber(item.startedAtMs, item.started_at_ms)
    if (startedAtMs != null) {
      return startedAtMs
    }
  }
  return null
}

function isTurnInProgress(turn: CodexTurnState) {
  return isWorkingStatus(turn.status)
}

function isItemInProgress(item: JsonRecord) {
  if (item.completed === false) {
    return true
  }
  const status = firstString(item.status, item.executionStatus).toLowerCase()
  return ['active', 'inprogress', 'in_progress', 'running', 'working'].includes(status)
}

function isWorkExpanded(turnView: TurnView) {
  const override = expandedWorkByTurnKey.value[turnView.key]
  return override ?? isTurnInProgress(turnView.turn)
}

function toggleWork(turnView: TurnView) {
  expandedWorkByTurnKey.value = {
    ...expandedWorkByTurnKey.value,
    [turnView.key]: !isWorkExpanded(turnView),
  }
}

function isItemExpanded(itemId: string) {
  return expandedItemById.value[itemId] ?? false
}

function toggleItem(itemId: string) {
  expandedItemById.value = {
    ...expandedItemById.value,
    [itemId]: !isItemExpanded(itemId),
  }
}

function isImagePreviewVisible(itemId: string) {
  return imagePreviewByItemId.value[itemId] ?? false
}

function setImagePreviewVisible(itemId: string, visible: boolean) {
  imagePreviewByItemId.value = {
    ...imagePreviewByItemId.value,
    [itemId]: visible,
  }
}

function workRenderUnits(items: ConversationItemView[]): WorkRenderUnit[] {
  const units: WorkRenderUnit[] = []
  let activityItems: ConversationItemView[] = []
  let activityIndex = 0

  function flushActivity() {
    if (!activityItems.length) {
      return
    }
    units.push({
      id: `${activityItems[0]?.id ?? 'activity'}-activity-${activityIndex}`,
      kind: 'activity',
      items: activityItems,
      summary: summarizeToolActivity(activityItems.map((item) => item.item)),
    })
    activityItems = []
    activityIndex += 1
  }

  for (const item of items) {
    const type = itemType(item.item)
    if (type === 'reasoning') {
      continue
    }
    if (type === 'agentMessage' || type === 'plan') {
      flushActivity()
      units.push({ id: item.id, kind: 'message', items: [item] })
      continue
    }
    if (type === 'imageView') {
      flushActivity()
      units.push({ id: item.id, kind: 'image', items: [item] })
      continue
    }
    if (isTodoListItem(item.item)) {
      continue
    }
    if (isContextCompactionItem(item.item)) {
      flushActivity()
      units.push({ id: item.id, kind: 'context', items: [item] })
      continue
    }
    activityItems.push(item)
  }
  flushActivity()
  return units
}

function workUnitsForBlock(block: TurnBlockView) {
  return block.workUnits ?? workRenderUnits(block.items)
}

function hasFinalAssistantResponse(turnView: TurnView) {
  return turnView.finalResponseItems.some((item) => itemText(item.item))
}

function shouldShowStandaloneThinking(turnView: TurnView) {
  return isTurnInProgress(turnView.turn) && !hasFinalAssistantResponse(turnView)
}

function isTodoListItem(item: JsonRecord) {
  return ['todo-list', 'todoList', 'todo_list'].includes(itemType(item))
}

function isContextCompactionItem(item: JsonRecord) {
  return ['contextCompaction', 'context-compaction'].includes(itemType(item))
}

function isReviewModeItem(item: JsonRecord) {
  return ['enteredReviewMode', 'exitedReviewMode'].includes(itemType(item))
}

function itemText(item: JsonRecord) {
  const type = itemType(item)
  if (type === 'userMessage') {
    return goalDisplayText(userMessageDisplayText(rawUserMessageText(item)))
  }
  if (isSteeringMessageType(type)) {
    return firstString(
      outputText(item.input),
      outputText(item.content),
      item.message,
      item.prompt,
      item.text,
    )
  }
  if (type === 'agentMessage') {
    return firstString(item.text, outputText(item.content))
  }
  if (type === 'plan') {
    return firstString(item.text, item.content)
  }
  if (type === 'reasoning') {
    return firstString(outputText(item.summary), outputText(item.content), item.text)
  }
  if (type === 'commandExecution') {
    return commandOutput(item)
  }
  if (type === 'dynamicToolCall') {
    return firstString(
      item.aggregatedOutput,
      outputText(item.contentItems),
      outputText(item.result),
    )
  }
  if (type === 'mcpToolCall') {
    return firstString(
      item.aggregatedOutput,
      outputText(item.result),
      outputText(item.contentItems),
    )
  }
  if (type === 'collabAgentToolCall') {
    return firstString(item.prompt, item.aggregatedOutput, outputText(item.result))
  }
  if (type === 'subAgentActivity') {
    return firstString(item.summary, item.text, outputText(item.content), outputText(item.items))
  }
  if (type === 'hookPrompt') {
    return firstString(item.prompt, item.text, outputText(item.content), outputText(item.input))
  }
  if (type === 'fileChange') {
    return fileChangePaths(item).join('\n')
  }
  if (type === 'userInputResponse') {
    return compactJson(item.answers ?? {})
  }
  if (isContextCompactionItem(item)) {
    return 'Context compacted.'
  }
  if (isReviewModeItem(item)) {
    return reviewModeLabel(item)
  }
  if (type === 'webSearch' || type === 'search') {
    return webSearchDetail(item)
  }
  if (type === 'git') {
    return gitDetail(item)
  }
  if (type === 'imageView') {
    return imageViewPath(item)
  }
  if (type === 'imageGeneration') {
    return firstString(
      item.prompt,
      item.text,
      item.path,
      outputText(item.content),
      outputText(item.result),
    )
  }
  if (type === 'sleep') {
    return 'Sleeping'
  }
  return firstString(item.text, outputText(item.content), outputText(item.input))
}

function rawUserMessageText(item: JsonRecord) {
  return outputText(item.content || item.input)
}

function isGoalCommandText(text: string) {
  return /^\/goal(?:\s|$)/.test(text)
}

function goalDisplayText(text: string) {
  return isGoalCommandText(text) ? text.replace(/^\/goal(?:\s+|$)/, '').trim() : text
}

function itemImages(item: JsonRecord) {
  const candidates = [item.content, item.input, item.attachments, item.imageAttachments].flatMap(
    (value) => (Array.isArray(value) ? value : []),
  )
  return candidates
    .filter(isRecord)
    .map((value) => {
      const directSrc = firstString(value.url, value.imageUrl, value.image_url, value.src)
      const path = firstString(value.path, value.filePath, value.file_path)
      return {
        src: directSrc || codexImagePathUrl(path),
        alt: firstString(value.name, value.filename, value.alt) || 'Image',
      }
    })
    .filter((image) => image.src)
}

function codexImagePathUrl(path: string, download = false) {
  if (!path) {
    return ''
  }
  const query = new URLSearchParams({ path })
  if (download) {
    query.set('download', 'true')
  }
  return `/api/codex/image?${query.toString()}`
}

function imageViewPath(item: JsonRecord) {
  return firstString(item.path, item.filePath, item.file_path)
}

function imageViewName(item: JsonRecord) {
  const path = imageViewPath(item)
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || path || 'Image'
}

function codexImageUrl(item: JsonRecord, download = false) {
  const path = imageViewPath(item)
  return codexImagePathUrl(path, download)
}

function imageGalleryItems(item: JsonRecord) {
  const imageUrl = codexImageUrl(item)
  if (!imageUrl) {
    return []
  }
  return [
    {
      itemImageSrc: imageUrl,
      thumbnailImageSrc: imageUrl,
      alt: imageViewName(item),
      title: imageViewName(item),
      path: imageViewPath(item),
      downloadUrl: codexImageUrl(item, true),
    },
  ]
}

async function copyMessageText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    emit('copyError', 'Unable to copy message.')
  }
}

function messageTimestamp(item: JsonRecord, turn: CodexTurnState) {
  return formatTimestamp(
    firstNumber(item.createdAt, item.created_at, item.startedAt, item.started_at) ??
      turn.turnStartedAtMs ??
      null,
  )
}

function absoluteTime(value: number | null | undefined) {
  const ms = coerceMs(value)
  return ms ? new Date(ms).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : ''
}

function isGoalUserMessage(item: JsonRecord) {
  return Boolean(
    item.goal === true ||
    item.sentAsGoal === true ||
    item.isGoal === true ||
    item.asGoal === true ||
    isGoalCommandText(userMessageDisplayText(rawUserMessageText(item))),
  )
}

function reviewModeLabel(item: JsonRecord) {
  const review = firstString(item.review)
  if (itemType(item) === 'enteredReviewMode') {
    return review ? `Code review started: ${review}` : 'Code review started'
  }
  return 'Code review finished'
}

function goalAchievementLabel(turn: CodexTurnState) {
  const goal = props.state?.completedThreadGoal
  if (!goal || goal.status !== 'complete' || isTurnInProgress(turn)) {
    return ''
  }
  const seconds = firstNumber(goal.timeUsedSeconds)
  const duration = seconds != null ? formatDuration(seconds * 1000) : ''
  const completedAt = firstNumber(
    goal.updatedAt,
    turn.finalAssistantStartedAtMs,
    turn.turnStartedAtMs,
  )
  const time = absoluteTime(completedAt)
  if (duration && time) {
    return `Goal achieved in ${duration} ${time}`
  }
  return duration ? `Goal achieved in ${duration}` : 'Goal achieved'
}

function commandText(item: JsonRecord) {
  return cleanShellCommand(firstString(item.command, item.cmd))
}

function commandOutput(item: JsonRecord) {
  const output = item.output
  if (isRecord(output)) {
    return firstString(output.aggregatedOutput, output.stdout, output.stderr, output.text)
  }
  return firstString(item.aggregatedOutput, outputText(output))
}

function commandExitCode(item: JsonRecord) {
  const output = item.output
  if (isRecord(output)) {
    return firstNumber(output.exitCode, output.exit_code)
  }
  return firstNumber(item.exitCode, item.exit_code)
}

function commandSucceeded(item: JsonRecord) {
  const exitCode = commandExitCode(item)
  return exitCode === 0 || item.success === true
}

function commandWasInterrupted(item: JsonRecord) {
  const status = firstString(item.executionStatus, item.status).toLowerCase()
  return status === 'interrupted' || status === 'stopped'
}

function commandFooterText(item: JsonRecord) {
  if (isItemInProgress(item)) {
    return ''
  }
  if (commandWasInterrupted(item)) {
    return 'Stopped'
  }
  if (commandSucceeded(item)) {
    return 'Success'
  }
  const exitCode = commandExitCode(item)
  return `Exit code ${exitCode ?? 'unknown'}`
}

function cleanShellCommand(command: string) {
  let text = command.trim().replace(/^\$\s+/, '')
  const shellMatch = text.match(/^(?:\/bin\/)?(?:zsh|bash|sh)\s+-lc\s+([\s\S]+)$/)
  if (shellMatch?.[1]) {
    text = shellMatch[1].trim()
  }
  if (
    (text.startsWith('"') && text.endsWith('"')) ||
    (text.startsWith("'") && text.endsWith("'"))
  ) {
    text = text.slice(1, -1)
  }
  return text.replace(/\\"/g, '"').replace(/\\'/g, "'").trim()
}

function fileChangePaths(item: JsonRecord) {
  return fileChangeViews(item).map((change) => change.path)
}

function fileChangeViews(item: JsonRecord): FileChangeView[] {
  const changes = item.changes
  if (Array.isArray(changes)) {
    return changes
      .map((change) => (isRecord(change) ? fileChangeView(change) : null))
      .filter((change): change is FileChangeView => Boolean(change?.path))
  }
  if (isRecord(changes)) {
    return Object.entries(changes).map(([path, change]) =>
      fileChangeView(isRecord(change) ? { path, ...change } : { path }),
    )
  }
  return []
}

function fileChangeView(change: JsonRecord): FileChangeView {
  const diffStats = diffLineStats(firstString(change.diff, change.unifiedDiff, change.patch))
  return {
    path: firstString(change.path, change.file, change.filePath, change.target) || 'unknown',
    action: fileChangeAction(change),
    linesAdded:
      firstNumber(change.linesAdded, change.added, change.additions) ?? diffStats.linesAdded,
    linesRemoved:
      firstNumber(change.linesRemoved, change.removed, change.deletions) ?? diffStats.linesRemoved,
  }
}

function diffLineStats(diff: string) {
  let linesAdded = 0
  let linesRemoved = 0
  for (const line of diff.split('\n')) {
    if (line.startsWith('+++') || line.startsWith('---')) {
      continue
    }
    if (line.startsWith('+')) {
      linesAdded += 1
    } else if (line.startsWith('-')) {
      linesRemoved += 1
    }
  }
  return { linesAdded, linesRemoved }
}

function fileChangeAction(change: JsonRecord): FileChangeView['action'] {
  const raw = firstString(change.type, change.kind, change.action, change.status).toLowerCase()
  if (['add', 'added', 'create', 'created', 'new'].includes(raw)) {
    return 'created'
  }
  if (['delete', 'deleted', 'remove', 'removed'].includes(raw)) {
    return 'deleted'
  }
  if (['rename', 'renamed', 'move', 'moved'].includes(raw)) {
    return 'renamed'
  }
  if (['edit', 'edited', 'modify', 'modified', 'update', 'updated'].includes(raw)) {
    return 'edited'
  }
  return 'changed'
}

function fileChangeActionLabel(action: FileChangeView['action']) {
  switch (action) {
    case 'created':
      return 'Created'
    case 'deleted':
      return 'Deleted'
    case 'renamed':
      return 'Renamed'
    case 'edited':
      return 'Edited'
    default:
      return 'Changed'
  }
}

function primaryFileChange(item: JsonRecord) {
  return fileChangeViews(item)[0] ?? null
}

function toolName(item: JsonRecord) {
  return firstString(item.tool, item.name, item.serverName, item.server) || itemType(item)
}

function humanizeName(value: string) {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function workItemTitle(item: JsonRecord) {
  const type = itemType(item)
  if (type === 'commandExecution') {
    return `${isItemInProgress(item) ? 'Running' : 'Ran'} ${commandText(item) || 'command'}`
  }
  if (type === 'fileChange') {
    const changes = fileChangeViews(item)
    if (changes.length === 1) {
      return fileChangeActionLabel(changes[0]?.action ?? 'changed')
    }
    return `Changed ${changes.length} files`
  }
  if (type === 'webSearch' || type === 'search') {
    return isItemInProgress(item) ? 'Searching the web' : 'Searched the web'
  }
  if (type === 'git') {
    return 'Checked git'
  }
  if (type === 'dynamicToolCall') {
    return `${isItemInProgress(item) ? 'Calling' : 'Called'} ${humanizeName(toolName(item))}`
  }
  if (type === 'mcpToolCall') {
    const server = firstString(item.server, item.serverName)
    const name = humanizeName(toolName(item))
    return `${isItemInProgress(item) ? 'Calling' : 'Called'} ${server ? `${server} / ${name}` : name}`
  }
  if (type === 'collabAgentToolCall') {
    return `${isItemInProgress(item) ? 'Starting' : 'Used'} ${humanizeName(toolName(item))}`
  }
  if (type === 'subAgentActivity') {
    return firstString(item.title, item.name) || 'Used subagent'
  }
  if (type === 'userInputResponse') {
    return 'Answered request'
  }
  if (type === 'hookPrompt') {
    return 'Received hook prompt'
  }
  if (type === 'sleep') {
    return isItemInProgress(item) ? 'Sleeping' : 'Slept'
  }
  if (type === 'imageGeneration') {
    return isItemInProgress(item) ? 'Generating image' : 'Generated image'
  }
  if (type === 'imageView') {
    return 'Viewed image'
  }
  if (isSteeringMessageType(type) || type === 'steered') {
    return 'Steered conversation'
  }
  return humanizeName(type)
}

function hasExpandableWorkDetail(item: JsonRecord) {
  return Boolean(workItemDetail(item))
}

function workItemSubject(item: JsonRecord) {
  const type = itemType(item)
  if (type === 'commandExecution') {
    return ''
  }
  if (type === 'fileChange') {
    const primary = primaryFileChange(item)
    if (!primary) {
      return ''
    }
    const extraCount = fileChangeViews(item).length - 1
    return extraCount > 0 ? `${primary.path} +${extraCount}` : primary.path
  }
  if (type === 'webSearch' || type === 'search') {
    return webSearchSubject(item)
  }
  if (type === 'git') {
    return firstString(item.branch, item.sha, item.action)
  }
  if (type === 'dynamicToolCall' || type === 'mcpToolCall' || type === 'collabAgentToolCall') {
    return toolName(item)
  }
  if (type === 'subAgentActivity') {
    return firstString(item.name, item.agentName, item.agent_name)
  }
  if (type === 'imageView') {
    return imageViewName(item)
  }
  if (type === 'imageGeneration') {
    return firstString(item.prompt, item.path)
  }
  if (isSteeringMessageType(type)) {
    return firstString(itemText(item))
  }
  return ''
}

function workItemDetail(item: JsonRecord) {
  const type = itemType(item)
  if (type === 'commandExecution') {
    return commandOutput(item)
  }
  if (type === 'fileChange') {
    return fileChangeViews(item)
      .map((change) => {
        const lineParts = []
        if (change.linesAdded) {
          lineParts.push(`+${change.linesAdded}`)
        }
        if (change.linesRemoved) {
          lineParts.push(`-${change.linesRemoved}`)
        }
        return `${fileChangeActionLabel(change.action)} ${change.path}${lineParts.length ? ` (${lineParts.join(' / ')})` : ''}`
      })
      .join('\n')
  }
  if (type === 'webSearch' || type === 'search') {
    return webSearchDetail(item)
  }
  if (type === 'git') {
    return gitDetail(item)
  }
  if (type === 'steered') {
    return ''
  }
  return itemText(item)
}

function webSearchSubject(item: JsonRecord) {
  const action = isRecord(item.action) ? item.action : null
  const queries = action?.queries
  if (Array.isArray(queries) && queries.length) {
    return queries.filter((query): query is string => typeof query === 'string').join(', ')
  }
  return firstString(item.query, item.searchTerm, item.search_term, action?.query, action?.url)
}

function webSearchDetail(item: JsonRecord) {
  const action = isRecord(item.action) ? item.action : null
  const actionType = firstString(action?.type, item.actionType, item.action_type)
  const subject = webSearchSubject(item)
  if (actionType === 'openPage' || actionType === 'open_page') {
    return subject ? `Opened ${subject}` : 'Opened a web page'
  }
  if (actionType === 'findInPage' || actionType === 'find_in_page') {
    const pattern = firstString(action?.pattern, item.pattern)
    return [subject ? `Searched ${subject}` : 'Searched a page', pattern].filter(Boolean).join('\n')
  }
  return subject ? `Searched for ${subject}` : firstString(item.text, outputText(item.content))
}

function gitDetail(item: JsonRecord) {
  const parts = [
    firstString(item.branch) ? `branch ${firstString(item.branch)}` : '',
    firstString(item.sha) ? `sha ${firstString(item.sha)}` : '',
    firstString(item.originUrl, item.origin_url)
      ? `origin ${firstString(item.originUrl, item.origin_url)}`
      : '',
    firstString(item.diff) ? firstString(item.diff) : '',
  ]
  return parts.filter(Boolean).join('\n')
}

function todoItems(item: JsonRecord) {
  const plan = Array.isArray(item.plan)
    ? item.plan
    : Array.isArray(item.items)
      ? item.items
      : Array.isArray(item.todos)
        ? item.todos
        : []
  return plan.filter(isRecord).map((todo, index) => ({
    id: firstString(todo.id) || `${index}`,
    step: firstString(todo.step, todo.text, todo.content, todo.title) || `Task ${index + 1}`,
    status: firstString(todo.status, todo.state).toLowerCase() || 'pending',
  }))
}

function todoCompletedCount(item: JsonRecord) {
  return todoItems(item).filter((todo) => todo.status === 'completed' || todo.status === 'complete')
    .length
}

function todoSummary(item: JsonRecord) {
  const todos = todoItems(item)
  const completed = todoCompletedCount(item)
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

function contextCompactionLabel(item: JsonRecord) {
  const completed = item.completed !== false && !isItemInProgress(item)
  const source = firstString(item.source).toLowerCase()
  if (completed) {
    return source === 'manual' ? 'Context compacted' : 'Context automatically compacted'
  }
  return source === 'manual' ? 'Compacting context' : 'Automatically compacting context'
}

function finalTurnReport(items: JsonRecord[]): TurnReport {
  const changedFilesByPath = new Map<string, FileChangeView>()
  let linesAdded = 0
  let linesRemoved = 0
  let commandCount = 0
  let toolCount = 0

  for (const item of items) {
    const type = itemType(item)
    if (type === 'commandExecution') {
      commandCount += 1
    }
    if (['dynamicToolCall', 'mcpToolCall', 'collabAgentToolCall'].includes(type)) {
      toolCount += 1
    }
    if (type === 'fileChange') {
      for (const change of fileChangeViews(item)) {
        const previous = changedFilesByPath.get(change.path)
        const merged = previous
          ? {
              ...change,
              linesAdded: previous.linesAdded + change.linesAdded,
              linesRemoved: previous.linesRemoved + change.linesRemoved,
            }
          : change
        changedFilesByPath.set(change.path, merged)
        linesAdded += change.linesAdded
        linesRemoved += change.linesRemoved
      }
    }
  }

  const changedFiles = [...changedFilesByPath.values()].sort((left, right) =>
    left.path.localeCompare(right.path),
  )
  const parts: string[] = []
  if (changedFiles.length > 0) {
    parts.push(`${changedFiles.length} ${changedFiles.length === 1 ? 'file' : 'files'} changed`)
  }
  if (linesAdded || linesRemoved) {
    const lineParts = []
    if (linesAdded) {
      lineParts.push(`+${linesAdded}`)
    }
    if (linesRemoved) {
      lineParts.push(`-${linesRemoved}`)
    }
    parts.push(lineParts.join(' / '))
  }
  if (commandCount > 0) {
    parts.push(`${commandCount} ${commandCount === 1 ? 'command' : 'commands'}`)
  }
  if (toolCount > 0) {
    parts.push(`${toolCount} ${toolCount === 1 ? 'tool call' : 'tool calls'}`)
  }

  return {
    summary: parts.join(' · '),
    changedFileCount: changedFiles.length,
    linesAdded,
    linesRemoved,
    commandCount,
    toolCount,
    changedFiles,
  }
}

function hasTurnReport(turnView: TurnView) {
  return Boolean(turnView.finalResponseItems.length && turnView.report.summary)
}

function reportStatLabel(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`
}

function reportLinesLabel(report: TurnReport) {
  const parts = []
  if (report.linesAdded) {
    parts.push(`+${report.linesAdded}`)
  }
  if (report.linesRemoved) {
    parts.push(`-${report.linesRemoved}`)
  }
  return parts.join(' / ')
}

function shouldRenderMarkdown(item: JsonRecord) {
  return ['userMessage', 'agentMessage', 'plan'].includes(itemType(item))
}

function shouldShowUnknownJson(item: JsonRecord) {
  return itemKind(item) === 'unknown' || !itemText(item)
}

function responseTone(item: JsonRecord) {
  return itemType(item) === 'plan'
    ? 'border-l-[3px] border-emerald-300/70 pl-3'
    : 'border-l-[3px] border-transparent pl-3'
}

function turnKey(turn: CodexTurnState, index: number) {
  return turn.turnId || `turn-${index}`
}

onMounted(async () => {
  updateVirtualViewport()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      updateVirtualViewport()
      scheduleTurnMeasurement()
    })
    if (conversationBody.value) {
      resizeObserver.observe(conversationBody.value)
    }
  }
  await scrollToBottomIfNeeded()
})

onBeforeUnmount(() => {
  if (measureFrame != null) {
    window.cancelAnimationFrame(measureFrame)
    measureFrame = null
  }
  cancelTurnHydration()
  resizeObserver?.disconnect()
  resizeObserver = null
})

watch(
  () => props.state?.id,
  () => {
    resetProgressiveTurnHydration()
  },
  { immediate: true, flush: 'sync' },
)

watch(
  () => props.state?.id,
  async () => {
    await resetBottomStickiness()
  },
  { flush: 'post' },
)

watch(
  () => props.state?.turns,
  async () => {
    const validKeys = new Set(turnViews.value.map((turnView) => turnView.key))
    const nextHeights = Object.fromEntries(
      Object.entries(measuredTurnHeights.value).filter(([key]) => validKeys.has(key)),
    )
    if (Object.keys(nextHeights).length !== Object.keys(measuredTurnHeights.value).length) {
      measuredTurnHeights.value = nextHeights
    }
    await scrollToBottomIfNeeded()
  },
  { deep: true, flush: 'post' },
)

const justDebug = false
</script>

<template>
  <section
    ref="conversationBody"
    class="codex-scrollbar min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-clip bg-[color:var(--app-bg)] px-5 py-4 [overflow-anchor:none] max-sm:px-2.5"
    data-codex-conversation-body
    @scroll="onConversationScroll"
  >
    <div
      v-if="!state"
      class="grid h-full min-h-72 place-items-center text-center text-[color:var(--app-text-soft)]"
    >
      <div class="grid gap-2">
        <i class="pi pi-comments text-xl"></i>
        <p class="m-0 text-sm">Select or start a thread.</p>
      </div>
    </div>

    <div
      v-else-if="!turnViews.length"
      class="grid h-full min-h-72 place-items-center text-center text-[color:var(--app-text-soft)]"
    >
      <div class="grid gap-2">
        <i class="pi pi-sparkles text-xl"></i>
        <p class="m-0 text-sm">Ready for a prompt.</p>
      </div>
    </div>

    <div
      v-else
      class="mx-auto grid w-full max-w-5xl min-w-0 gap-6 overflow-x-clip max-sm:gap-5"
      :data-codex-virtualized-turns="isTurnVirtualized ? 'true' : undefined"
    >
      <div
        v-if="virtualTopSpacerHeight > 0"
        :style="{ height: `${virtualTopSpacerHeight}px` }"
        aria-hidden="true"
        data-codex-turn-top-spacer
      ></div>
      <section
        v-for="{ turnView, originalIndex } in visibleTurnViews"
        :key="turnView.key"
        class="grid min-w-0 gap-3 overflow-x-clip border-b border-[color:var(--app-border)] pb-6 [contain-intrinsic-size:auto_720px] [content-visibility:auto] last:border-b-0"
        data-codex-turn
        :data-codex-turn-key="turnView.key"
        :data-codex-turn-index="originalIndex"
      >
        <div
          class="flex min-w-0 flex-wrap items-center gap-2 text-[0.74rem] text-[color:var(--app-text-soft)]"
        >
          <span class="font-semibold text-[color:var(--app-text)]">
            Turn {{ originalIndex + 1 }}
          </span>
          <span v-if="justDebug">{{ statusLabel(turnView.turn.status) }}</span>
          <code v-if="justDebug && turnView.turn.turnId" class="truncate">{{
            turnView.turn.turnId
          }}</code>
          <span v-if="turnView.turn.turnStartedAtMs">
            {{ formatTimestamp(turnView.turn.turnStartedAtMs) }}
          </span>
        </div>

        <template v-for="block in turnView.blocks" :key="block.id">
          <article
            v-if="block.kind === 'user'"
            class="group/message flex min-w-0 w-full justify-end"
            data-codex-user-message
          >
            <div
              v-for="userItem in block.items"
              :key="userItem.id"
              class="flex min-w-0 w-fit max-w-[min(40rem,88%)] flex-col items-end max-sm:max-w-[96%]"
              data-codex-user-message-shell
            >
              <div
                class="relative min-w-0 w-full overflow-hidden rounded-2xl border border-[color:var(--app-focus)] bg-[color:var(--app-accent-soft)] px-3.5 py-2.5 shadow-[0_10px_28px_var(--app-shadow-color)]"
                data-codex-bubble
              >
                <div
                  class="markdown-prose markdown-prose-compact min-w-0 [overflow-wrap:anywhere] [&>:first-child]:mt-0 [&>:last-child]:mb-0"
                  v-html="renderMarkdown(itemText(userItem.item))"
                  @click="onMarkdownClick"
                ></div>
                <div
                  v-if="itemImages(userItem.item).length"
                  class="mt-2 grid grid-cols-[repeat(auto-fit,minmax(5rem,1fr))] gap-2"
                  data-codex-message-images
                >
                  <img
                    v-for="image in itemImages(userItem.item)"
                    :key="image.src"
                    class="max-h-64 min-h-20 w-full rounded-lg border border-[color:var(--app-border)] object-cover"
                    :src="image.src"
                    :alt="image.alt"
                    data-codex-message-image
                  />
                </div>
              </div>
              <div
                class="mt-1 flex min-w-0 items-center justify-end gap-1 pr-1 text-[0.68rem] text-[color:var(--app-text-soft)] opacity-0 transition-opacity group-hover/message:opacity-100 group-focus-within/message:opacity-100"
                data-codex-user-message-actions
              >
                <span
                  v-if="isGoalUserMessage(userItem.item)"
                  class="inline-flex min-w-0 items-center gap-1 font-semibold text-[color:var(--app-accent)]"
                  data-codex-sent-as-goal
                >
                  <i class="pi pi-flag text-[0.56rem]"></i>
                  <span>sent as goal</span>
                </span>
                <span v-if="messageTimestamp(userItem.item, turnView.turn)">
                  {{ messageTimestamp(userItem.item, turnView.turn) }}
                </span>
                <button
                  type="button"
                  class="inline-flex h-6 w-6 items-center justify-center rounded-md transition hover:bg-[color:var(--app-hover)] hover:text-[color:var(--app-text)]"
                  aria-label="Copy message"
                  title="Copy"
                  data-codex-copy-message
                  @click="copyMessageText(itemText(userItem.item))"
                >
                  <i class="pi pi-copy text-[0.62rem]"></i>
                </button>
              </div>
            </div>
          </article>

          <div
            v-else-if="block.kind === 'system'"
            class="my-2 flex max-w-[min(52rem,100%)] items-center gap-2 text-sm text-[color:var(--app-text-soft)]"
            data-codex-system-message
          >
            <span class="h-px min-w-0 flex-1 bg-current opacity-20"></span>
            <span
              v-for="systemItem in block.items"
              :key="systemItem.id"
              class="inline-flex min-w-0 shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5"
              data-codex-review-mode
            >
              <i
                class="pi text-[0.62rem]"
                :class="
                  itemType(systemItem.item) === 'enteredReviewMode' ? 'pi-search' : 'pi-check'
                "
              ></i>
              <span class="min-w-0 truncate">{{ reviewModeLabel(systemItem.item) }}</span>
            </span>
            <span class="h-px min-w-0 flex-1 bg-current opacity-20"></span>
          </div>

          <div v-else-if="block.kind === 'work'" class="grid min-w-0 gap-2" data-codex-work-section>
            <div class="flex min-w-0 items-center gap-2 text-sm text-[color:var(--app-text-soft)]">
              <button
                type="button"
                class="group inline-flex max-w-full shrink-0 items-center gap-1.5 rounded-md border border-transparent px-1 py-0.5 text-left transition hover:bg-[color:var(--app-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--app-focus)]"
                :aria-expanded="isWorkExpanded(turnView)"
                data-codex-work-toggle
                @click="toggleWork(turnView)"
              >
                <CodexWorkedLabel
                  class="truncate"
                  :status="turnView.turn.status"
                  :work-started-at-ms="
                    turnView.turn.firstTurnWorkItemStartedAtMs ??
                    firstTurnWorkItemStartedAtMsFromItems(turnView.turn)
                  "
                  :turn-started-at-ms="turnView.turn.turnStartedAtMs"
                  :final-assistant-started-at-ms="turnView.turn.finalAssistantStartedAtMs"
                  :duration-ms="turnView.turn.durationMs"
                />
                <i
                  class="pi pi-chevron-right text-[0.65rem] opacity-50 transition-transform"
                  :class="isWorkExpanded(turnView) ? 'rotate-90' : ''"
                ></i>
              </button>
              <span class="h-px min-w-0 flex-1 bg-[color:var(--app-border-strong)]"></span>
            </div>

            <div
              v-if="isWorkExpanded(turnView)"
              class="grid min-w-0 gap-1.5 border-l border-[color:var(--app-border)] pl-3 max-sm:pl-2"
              data-codex-work-items
            >
              <template v-for="unit in workUnitsForBlock(block)" :key="unit.id">
                <div
                  v-if="unit.kind === 'message'"
                  class="markdown-prose markdown-prose-conversation min-w-0 py-1 [overflow-wrap:anywhere] [&>:first-child]:mt-0 [&>:last-child]:mb-0"
                  data-codex-work-message
                  v-html="renderMarkdown(itemText(unit.items[0]?.item ?? {}))"
                  @click="onMarkdownClick"
                ></div>

                <div
                  v-else-if="unit.kind === 'activity'"
                  class="grid min-w-0 gap-1 py-0.5 text-sm text-[color:var(--app-text-soft)]"
                  data-codex-work-activity
                >
                  <button
                    type="button"
                    class="group inline-flex min-w-0 items-center gap-1 rounded-md px-1 py-0.5 text-left transition hover:bg-[color:var(--app-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--app-focus)]"
                    :aria-expanded="isItemExpanded(unit.id)"
                    data-codex-activity-toggle
                    @click="toggleItem(unit.id)"
                  >
                    <i
                      class="pi shrink-0 text-[0.72rem] opacity-70"
                      :class="unit.summary?.icon ?? 'pi-sparkles'"
                      aria-hidden="true"
                      data-codex-activity-icon
                    ></i>
                    <CodexThinkingShimmer
                      v-if="unit.summary?.active"
                      class="min-w-0"
                      :message="unit.summary.text"
                    />
                    <span v-else class="min-w-0 truncate">
                      {{ unit.summary?.text ?? 'Worked' }}
                    </span>
                    <i
                      class="pi pi-chevron-right shrink-0 text-[0.56rem] opacity-50 transition-transform"
                      :class="isItemExpanded(unit.id) ? 'rotate-90' : ''"
                    ></i>
                  </button>

                  <div
                    v-if="isItemExpanded(unit.id)"
                    class="grid max-h-56 min-w-0 gap-1 overflow-y-auto pr-1 pl-2"
                    data-codex-work-detail
                  >
                    <div
                      v-for="workItem in unit.items"
                      :key="workItem.id"
                      class="grid min-w-0 gap-1 rounded-md px-1 py-0.5"
                      data-codex-work-item
                    >
                      <button
                        type="button"
                        class="group flex min-w-0 items-center gap-1 rounded-md px-1 py-0.5 text-left text-xs text-[color:var(--app-text-soft)] transition hover:bg-[color:var(--app-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--app-focus)]"
                        :aria-expanded="isItemExpanded(workItem.id)"
                        data-codex-work-row
                        @click="hasExpandableWorkDetail(workItem.item) && toggleItem(workItem.id)"
                      >
                        <span class="min-w-0 truncate">{{ workItemTitle(workItem.item) }}</span>
                        <span v-if="workItemSubject(workItem.item)" class="min-w-0 truncate">
                          · {{ workItemSubject(workItem.item) }}
                        </span>
                        <i
                          v-if="hasExpandableWorkDetail(workItem.item)"
                          class="pi pi-chevron-right ml-auto shrink-0 text-[0.52rem] opacity-50 transition-transform"
                          :class="isItemExpanded(workItem.id) ? 'rotate-90' : ''"
                        ></i>
                      </button>

                      <div v-if="isItemExpanded(workItem.id)" class="min-w-0 pl-2">
                        <div
                          v-if="itemType(workItem.item) === 'commandExecution'"
                          class="group/shell min-w-0 overflow-hidden rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-translucent)] text-[color:var(--app-text)]"
                          :class="
                            !isItemInProgress(workItem.item) && !commandSucceeded(workItem.item)
                              ? 'border-[color:var(--app-danger-border)] bg-[color:var(--app-danger-bg)]'
                              : ''
                          "
                          data-codex-command-output
                        >
                          <div
                            class="flex min-w-0 items-center justify-between gap-2 bg-[color:var(--app-hover)] px-2 py-1 font-sans text-sm text-[color:var(--app-text-soft)] select-none"
                            data-codex-command-header
                          >
                            <span>Shell</span>
                          </div>
                          <div class="relative min-w-0">
                            <div
                              v-if="commandText(workItem.item)"
                              class="px-2 pt-2"
                              data-codex-command-line
                            >
                              <div class="group/command relative min-w-0 pr-7">
                                <code
                                  class="block min-w-0 whitespace-pre-wrap break-words font-mono text-[0.8rem] leading-5 text-[color:var(--app-text-soft)] line-clamp-2"
                                  data-codex-command-text
                                  role="button"
                                  tabindex="0"
                                  @click="copyMessageText(commandText(workItem.item))"
                                  @keydown.enter.prevent="
                                    copyMessageText(commandText(workItem.item))
                                  "
                                  @keydown.space.prevent="
                                    copyMessageText(commandText(workItem.item))
                                  "
                                >
                                  $ {{ commandText(workItem.item) }}
                                </code>
                                <button
                                  type="button"
                                  class="absolute right-0 top-0 inline-flex h-6 w-6 items-center justify-center rounded-md text-[color:var(--app-text-soft)] opacity-0 transition hover:bg-[color:var(--app-hover)] hover:text-[color:var(--app-text)] group-hover/command:opacity-100 focus-visible:opacity-100"
                                  aria-label="Copy command"
                                  title="Copy command"
                                  data-codex-copy-command
                                  @click.stop="copyMessageText(commandText(workItem.item))"
                                >
                                  <i class="pi pi-copy text-[0.62rem]"></i>
                                </button>
                              </div>
                            </div>

                            <div
                              class="group/output relative min-h-5 pr-0"
                              data-codex-shell-content
                            >
                              <pre
                                class="m-0 flex max-h-[140px] max-w-full flex-col-reverse overflow-x-auto overflow-y-auto whitespace-pre p-2 font-mono text-[0.78rem] font-medium leading-5 text-[color:var(--app-text-soft)]"
                                data-codex-command-output-text
                              ><code>{{ workItemDetail(workItem.item) || 'No output' }}</code></pre>
                              <button
                                type="button"
                                class="absolute right-2.5 top-0 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[color:var(--app-text-soft)] opacity-0 transition hover:bg-[color:var(--app-hover)] hover:text-[color:var(--app-text)] group-hover/output:opacity-100 focus-visible:opacity-100"
                                aria-label="Copy output"
                                title="Copy output"
                                data-codex-copy-output
                                @click.stop="copyMessageText(workItemDetail(workItem.item))"
                              >
                                <i class="pi pi-copy text-[0.62rem]"></i>
                              </button>
                            </div>
                          </div>
                          <div
                            class="flex min-h-6 items-center gap-2 px-2.5 pb-1 pt-0.5 text-xs text-[color:var(--app-text-soft)]"
                            data-codex-command-footer
                          >
                            <span class="ml-auto inline-flex items-center gap-1">
                              <i
                                v-if="commandFooterText(workItem.item) === 'Success'"
                                class="pi pi-check text-[0.56rem]"
                              ></i>
                              {{ commandFooterText(workItem.item) }}
                            </span>
                          </div>
                        </div>

                        <pre
                          v-else-if="workItemDetail(workItem.item)"
                          class="m-0 max-h-56 max-w-full overflow-auto overscroll-contain rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface)] p-2.5 text-xs leading-5 text-[color:var(--app-text-soft)]"
                          data-codex-raw
                          >{{ workItemDetail(workItem.item) }}</pre
                        >
                      </div>
                    </div>
                  </div>
                </div>

                <div v-else-if="unit.kind === 'image'" class="min-w-0 py-1" data-codex-image-view>
                  <button
                    v-if="codexImageUrl(unit.items[0]?.item ?? {})"
                    type="button"
                    class="group block max-w-[min(18rem,100%)] min-w-0 overflow-hidden rounded-md text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--app-focus)]"
                    aria-label="Preview image"
                    data-codex-image-preview-link
                    @click="setImagePreviewVisible(unit.items[0]?.id ?? unit.id, true)"
                  >
                    <span class="relative block min-w-0">
                      <img
                        class="max-h-44 w-full object-contain"
                        :src="codexImageUrl(unit.items[0]?.item ?? {})"
                        :alt="imageViewName(unit.items[0]?.item ?? {})"
                        loading="lazy"
                        data-codex-image-preview
                      />
                      <span
                        class="absolute inset-0 bg-black/0 transition group-hover:bg-black/10 group-focus-visible:bg-black/10"
                      >
                      </span>
                    </span>
                  </button>
                  <Dialog
                    v-if="codexImageUrl(unit.items[0]?.item ?? {})"
                    :visible="isImagePreviewVisible(unit.items[0]?.id ?? unit.id)"
                    :modal="true"
                    :dismissable-mask="true"
                    :style="{ width: 'min(92vw, 72rem)' }"
                    :content-style="{ padding: '0' }"
                    :pt="{
                      root: { class: 'codex-image-gallery-dialog', 'data-codex-image-gallery': '' },
                      header: { class: 'codex-image-gallery-toolbar' },
                      content: { class: 'codex-image-gallery-content' },
                    }"
                    data-codex-image-gallery
                    @update:visible="setImagePreviewVisible(unit.items[0]?.id ?? unit.id, $event)"
                  >
                    <template #header>
                      <div class="flex min-w-0 flex-1 items-center gap-2">
                        <i class="pi pi-image shrink-0 text-[0.82rem]"></i>
                        <span class="min-w-0 truncate font-medium">
                          {{ imageViewName(unit.items[0]?.item ?? {}) }}
                        </span>
                      </div>
                      <a
                        class="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md px-3 text-sm font-medium text-white transition hover:bg-white/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40"
                        :href="codexImageUrl(unit.items[0]?.item ?? {}, true)"
                        :download="imageViewName(unit.items[0]?.item ?? {})"
                        data-codex-image-gallery-download
                        @click.stop
                      >
                        <i class="pi pi-download text-[0.78rem]"></i>
                        <span>Download</span>
                      </a>
                    </template>
                    <Galleria
                      :value="imageGalleryItems(unit.items[0]?.item ?? {})"
                      :active-index="0"
                      :show-thumbnails="false"
                      :show-item-navigators="false"
                      :circular="false"
                      :container-style="{ width: '100%' }"
                      :pt="{
                        root: { class: 'codex-image-gallery-root' },
                        item: { class: 'codex-image-gallery-item' },
                      }"
                    >
                      <template #item="{ item: galleryItem }">
                        <img
                          class="max-h-[78vh] max-w-[90vw] object-contain"
                          :src="galleryItem.itemImageSrc"
                          :alt="galleryItem.alt"
                          data-codex-image-gallery-image
                        />
                      </template>
                    </Galleria>
                  </Dialog>
                </div>

                <div
                  v-else-if="unit.kind === 'todo'"
                  class="min-w-0 rounded-lg bg-[color:var(--app-surface-translucent)] px-2.5 py-2 text-sm text-[color:var(--app-text-soft)]"
                  data-codex-todo-list
                >
                  <button
                    type="button"
                    class="group flex w-full min-w-0 items-center justify-between gap-2 text-left"
                    :aria-expanded="isItemExpanded(unit.id)"
                    data-codex-todo-toggle
                    @click="toggleItem(unit.id)"
                  >
                    <span class="min-w-0 truncate">{{
                      todoSummary(unit.items[0]?.item ?? {})
                    }}</span>
                    <i
                      class="pi pi-chevron-down shrink-0 text-[0.62rem] opacity-0 transition-all group-hover:opacity-60"
                      :class="isItemExpanded(unit.id) ? 'rotate-180 opacity-80' : ''"
                    ></i>
                  </button>
                  <div
                    v-if="isItemExpanded(unit.id)"
                    class="mt-2 grid max-h-40 gap-1 overflow-y-auto"
                    data-codex-todo-items
                  >
                    <div
                      v-for="(todo, todoIndex) in todoItems(unit.items[0]?.item ?? {})"
                      :key="todo.id"
                      class="flex min-w-0 items-center gap-2"
                      data-codex-todo-item
                    >
                      <i
                        class="pi shrink-0 text-[0.64rem]"
                        :class="
                          isTodoComplete(todo.status)
                            ? 'pi-check text-[color:var(--app-success-text)]'
                            : 'pi-circle text-[color:var(--app-text-soft)]'
                        "
                      ></i>
                      <span class="shrink-0 text-[color:var(--app-text-soft)]">
                        {{ todoIndex + 1 }}.
                      </span>
                      <span
                        class="min-w-0 [overflow-wrap:anywhere]"
                        :class="isTodoComplete(todo.status) ? 'line-through' : ''"
                      >
                        {{ todo.step }}
                      </span>
                    </div>
                  </div>
                </div>

                <div
                  v-else-if="unit.kind === 'context'"
                  class="my-2 flex items-center gap-2 text-sm text-[color:var(--app-text-soft)]"
                  data-codex-context-compaction
                >
                  <span class="h-px min-w-0 flex-1 bg-current opacity-20"></span>
                  <span class="inline-flex shrink-0 items-center gap-1">
                    <i
                      v-if="!isItemInProgress(unit.items[0]?.item ?? {})"
                      class="pi pi-check text-[0.62rem]"
                    ></i>
                    {{ contextCompactionLabel(unit.items[0]?.item ?? {}) }}
                  </span>
                  <span class="h-px min-w-0 flex-1 bg-current opacity-20"></span>
                </div>
              </template>
            </div>
          </div>

          <article
            v-else-if="block.kind === 'assistant'"
            class="group/message min-w-0 max-w-[min(52rem,100%)]"
            :class="responseTone(block.items[0]?.item ?? {})"
            data-codex-assistant-message
          >
            <template v-for="responseItem in block.items" :key="responseItem.id">
              <div
                v-if="shouldRenderMarkdown(responseItem.item)"
                class="markdown-prose markdown-prose-conversation min-w-0 [overflow-wrap:anywhere] [&>:first-child]:mt-0 [&>:last-child]:mb-0"
                v-html="renderMarkdown(itemText(responseItem.item))"
                @click="onMarkdownClick"
              ></div>
              <div
                class="mt-1.5 flex min-w-0 items-center gap-1 text-[0.68rem] text-[color:var(--app-text-soft)] opacity-0 transition-opacity group-hover/message:opacity-100 group-focus-within/message:opacity-100"
                data-codex-assistant-message-actions
              >
                <span v-if="goalAchievementLabel(turnView.turn)" data-codex-goal-achieved>
                  {{ goalAchievementLabel(turnView.turn) }}
                </span>
                <button
                  type="button"
                  class="inline-flex h-6 w-6 items-center justify-center rounded-md transition hover:bg-[color:var(--app-hover)] hover:text-[color:var(--app-text)]"
                  aria-label="Copy message"
                  title="Copy"
                  data-codex-copy-message
                  @click="copyMessageText(itemText(responseItem.item))"
                >
                  <i class="pi pi-copy text-[0.62rem]"></i>
                </button>
                <button
                  v-if="state?.id"
                  type="button"
                  class="inline-flex h-6 w-6 items-center justify-center rounded-md transition hover:bg-[color:var(--app-hover)] hover:text-[color:var(--app-text)]"
                  aria-label="Fork from here"
                  title="Fork"
                  data-codex-fork-message
                  @click="emit('forkThread', state.id)"
                >
                  <i class="pi pi-share-alt text-[0.62rem]"></i>
                </button>
              </div>
            </template>
          </article>

          <article
            v-else
            class="min-w-0 max-w-[min(52rem,100%)] rounded-xl border border-[color:var(--app-border)] bg-[color:var(--app-surface-translucent)] p-3"
            data-codex-unknown-item
          >
            <pre
              v-for="unknownItem in block.items"
              :key="unknownItem.id"
              class="m-0 max-h-80 max-w-full overflow-auto overscroll-contain rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface)] p-3 text-xs leading-5 text-[color:var(--app-text-soft)]"
              data-codex-raw
              >{{
                shouldShowUnknownJson(unknownItem.item)
                  ? compactJson(unknownItem.item)
                  : itemText(unknownItem.item)
              }}</pre
            >
          </article>
        </template>

        <div
          v-if="shouldShowStandaloneThinking(turnView)"
          class="inline-flex max-w-[min(52rem,100%)] items-center gap-2 text-sm text-[color:var(--app-text-soft)]"
          data-codex-thinking-placeholder
        >
          <CodexThinkingShimmer />
        </div>

        <div
          v-if="hasTurnReport(turnView)"
          class="group/turn-diff-header flex max-w-full flex-col overflow-hidden rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-translucent)] text-xs text-[color:var(--app-text-soft)] shadow-[0_10px_24px_var(--app-shadow-color)] [--thread-resource-card-row-padding-x:0.75rem] [--turn-diff-row-padding-y:0.25rem]"
          data-codex-turn-summary
          data-codex-turn-report
        >
          <div
            class="flex min-w-0 items-center gap-2 border-b border-[color:var(--app-border)] px-[var(--thread-resource-card-row-padding-x)] py-2 font-semibold text-[color:var(--app-text)]"
          >
            <i
              class="pi pi-check-circle shrink-0 text-[0.72rem] text-[color:var(--app-success-text)]"
            ></i>
            <span class="min-w-0 truncate">Turn report</span>
            <span class="ml-auto min-w-0 truncate text-[color:var(--app-text-soft)]">
              {{ turnView.report.summary }}
            </span>
          </div>
          <div class="grid min-w-0 gap-px p-1.5">
            <div
              v-for="file in turnView.report.changedFiles"
              :key="file.path"
              class="grid min-w-0 grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-2 rounded-md px-[var(--thread-resource-card-row-padding-x)] py-[var(--turn-diff-row-padding-y)]"
              data-codex-turn-report-files
            >
              <i class="pi pi-file-edit text-[0.68rem] text-[color:var(--app-text-soft)]"></i>
              <span class="min-w-0 truncate">
                {{ file.path }}
              </span>
              <span class="font-mono font-semibold text-[color:var(--app-text)]">
                <span v-if="file.linesAdded" class="text-[color:var(--app-success-text)]"
                  >+{{ file.linesAdded }}</span
                >
                <span v-if="file.linesAdded && file.linesRemoved"> / </span>
                <span v-if="file.linesRemoved" class="text-[color:var(--app-danger-text)]"
                  >-{{ file.linesRemoved }}</span
                >
              </span>
            </div>
            <div
              v-if="reportLinesLabel(turnView.report)"
              class="grid min-w-0 grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-2 rounded-md px-[var(--thread-resource-card-row-padding-x)] py-[var(--turn-diff-row-padding-y)]"
              data-codex-turn-report-lines
            >
              <i class="pi pi-code text-[0.68rem] text-[color:var(--app-text-soft)]"></i>
              <span class="min-w-0 truncate">Diff</span>
              <span class="font-mono font-semibold text-[color:var(--app-text)]">
                {{ reportLinesLabel(turnView.report) }}
              </span>
            </div>
            <div
              v-if="turnView.report.commandCount"
              class="grid min-w-0 grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-2 rounded-md px-[var(--thread-resource-card-row-padding-x)] py-[var(--turn-diff-row-padding-y)]"
              data-codex-turn-report-commands
            >
              <i class="pi pi-terminal text-[0.68rem] text-[color:var(--app-text-soft)]"></i>
              <span class="min-w-0 truncate">Commands</span>
              <span class="font-semibold text-[color:var(--app-text)]">
                {{ reportStatLabel(turnView.report.commandCount, 'command') }}
              </span>
            </div>
            <div
              v-if="turnView.report.toolCount"
              class="grid min-w-0 grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-2 rounded-md px-[var(--thread-resource-card-row-padding-x)] py-[var(--turn-diff-row-padding-y)]"
              data-codex-turn-report-tools
            >
              <i class="pi pi-wrench text-[0.68rem] text-[color:var(--app-text-soft)]"></i>
              <span class="min-w-0 truncate">Tools</span>
              <span class="font-semibold text-[color:var(--app-text)]">
                {{ reportStatLabel(turnView.report.toolCount, 'tool call') }}
              </span>
            </div>
          </div>
        </div>
      </section>
      <div
        v-if="virtualBottomSpacerHeight > 0"
        :style="{ height: `${virtualBottomSpacerHeight}px` }"
        aria-hidden="true"
        data-codex-turn-bottom-spacer
      ></div>
    </div>
  </section>
</template>
