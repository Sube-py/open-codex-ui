<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import {
  SLASH_SKILLS_GROUP,
  slashCommandToken,
  type CodexSlashCommandDefinition,
} from '../lib/slashCommands'

const props = defineProps<{
  open: boolean
  commands: CodexSlashCommandDefinition[]
  selectedIndex: number
  query: string
  loading?: boolean
  anchorStyle?: Record<string, string>
}>()

const emit = defineEmits<{
  select: [command: CodexSlashCommandDefinition]
  hover: [index: number]
}>()

const listRef = ref<HTMLElement | null>(null)
let scrollFrame = 0

const hasResults = computed(() => props.commands.length > 0)
const emptyLabel = computed(() => {
  if (props.loading) {
    return 'Loading skills…'
  }
  return props.query.trim() ? 'No matching commands' : 'No commands available'
})

const commandRows = computed(() => {
  const rows: Array<
    | { kind: 'group'; label: string; key: string }
    | { kind: 'command'; command: CodexSlashCommandDefinition; index: number; key: string }
  > = []
  let previousGroup: string | null | undefined = undefined
  props.commands.forEach((command, index) => {
    const group = command.group ?? null
    if (group && group !== previousGroup) {
      rows.push({ kind: 'group', label: group, key: `group:${group}` })
    }
    previousGroup = group
    rows.push({ kind: 'command', command, index, key: command.id })
  })
  return rows
})

watch(
  () => [props.open, props.selectedIndex] as const,
  ([open]) => {
    if (!open) {
      cancelScheduledScroll()
      return
    }
    scheduleEnsureSelectedVisible()
  },
)

onBeforeUnmount(() => {
  cancelScheduledScroll()
})

function scheduleEnsureSelectedVisible() {
  cancelScheduledScroll()
  // Coalesce rapid arrow-key updates into one scroll pass per frame.
  scrollFrame = window.requestAnimationFrame(() => {
    scrollFrame = 0
    ensureSelectedVisible()
  })
}

function cancelScheduledScroll() {
  if (!scrollFrame) {
    return
  }
  window.cancelAnimationFrame(scrollFrame)
  scrollFrame = 0
}

function ensureSelectedVisible() {
  const list = listRef.value
  if (!list) {
    return
  }
  const selected = list.querySelector<HTMLElement>('[data-codex-slash-selected]')
  if (!selected) {
    return
  }

  const listTop = list.scrollTop
  const listBottom = listTop + list.clientHeight
  const itemTop = selected.offsetTop
  const itemBottom = itemTop + selected.offsetHeight

  if (itemTop < listTop) {
    list.scrollTop = itemTop
    return
  }
  if (itemBottom > listBottom) {
    list.scrollTop = itemBottom - list.clientHeight
  }
}
</script>

<template>
  <div
    v-if="open"
    class="fixed z-[120] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-xl border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] shadow-xl"
    :style="anchorStyle"
    role="listbox"
    aria-label="Slash commands"
    data-codex-slash-menu
  >
    <div class="border-b border-[color:var(--app-border)] px-3 py-2">
      <p class="m-0 text-xs font-semibold text-[color:var(--app-text-soft)]">Slash commands</p>
      <p
        v-if="query"
        class="m-0 mt-0.5 truncate text-[0.68rem] text-[color:var(--app-text-soft)]"
        data-codex-slash-query
      >
        /{{ query }}
      </p>
    </div>

    <div
      v-if="hasResults"
      ref="listRef"
      class="max-h-[min(18rem,42vh)] overflow-y-auto p-1.5"
      data-codex-slash-list
    >
      <template v-for="row in commandRows" :key="row.key">
        <p
          v-if="row.kind === 'group'"
          class="m-0 px-2 pb-1 pt-2 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-[color:var(--app-text-soft)]"
          :data-codex-slash-group="row.label"
        >
          {{ row.label }}
        </p>
        <button
          v-else
          type="button"
          class="grid w-full grid-cols-[1rem_minmax(0,1fr)] items-start gap-2 rounded-lg px-2 py-1.5 text-left"
          :class="
            row.index === selectedIndex
              ? 'bg-[color:var(--app-selected)] text-[color:var(--app-text)]'
              : 'text-[color:var(--app-text)] hover:bg-[color:var(--app-hover)]'
          "
          role="option"
          :aria-selected="row.index === selectedIndex"
          :data-codex-slash-option="row.command.id"
          :data-codex-slash-skill="
            row.command.action.type === 'skill' ? row.command.action.skill.name : undefined
          "
          :data-codex-slash-selected="row.index === selectedIndex ? '' : undefined"
          :title="row.command.description"
          @mouseenter="emit('hover', row.index)"
          @mousedown.prevent="emit('select', row.command)"
        >
          <i
            :class="row.command.icon"
            class="mt-1 text-[0.72rem] text-[color:var(--app-text-soft)]"
          ></i>
          <span class="min-w-0 overflow-hidden">
            <span class="flex min-w-0 items-center gap-2">
              <span class="min-w-0 truncate text-sm font-semibold">{{ row.command.title }}</span>
              <span
                v-if="row.command.rightLabel"
                class="ml-auto shrink-0 text-[0.68rem] text-[color:var(--app-text-soft)]"
              >
                {{ row.command.rightLabel }}
              </span>
              <span
                v-else-if="row.command.group !== SLASH_SKILLS_GROUP"
                class="shrink-0 text-[0.68rem] text-[color:var(--app-text-soft)]"
              >
                /{{ slashCommandToken(row.command) }}
              </span>
            </span>
            <span
              class="mt-0.5 block overflow-hidden text-ellipsis whitespace-nowrap text-[0.68rem] leading-4 text-[color:var(--app-text-soft)]"
              data-codex-slash-description
            >
              {{ row.command.description }}
            </span>
          </span>
        </button>
      </template>
    </div>

    <p
      v-else
      class="m-0 px-3 py-4 text-sm text-[color:var(--app-text-soft)]"
      data-codex-slash-empty
    >
      {{ emptyLabel }}
    </p>
  </div>
</template>
