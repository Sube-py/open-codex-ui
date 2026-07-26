<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { CodexConversationState } from '../types'
import { activeThreadTitle, displayPath, shortId, statusLabel, statusTone } from '../lib/format'

const props = defineProps<{
  threadId: string
  state: CodexConversationState | null
  status: string
  busy?: boolean
  renaming?: boolean
}>()

const emit = defineEmits<{
  renameThread: [name: string]
}>()

const renameDraft = ref('')

const title = computed(
  () => activeThreadTitle(props.state) || shortId(props.threadId) || 'No thread selected',
)
const cwd = computed(() => props.state?.cwd ?? '')
const modelLabel = computed(() => props.state?.latestModel ?? 'default')
const effortLabel = computed(() => props.state?.latestReasoningEffort ?? 'default')
const canSubmitName = computed(
  () => renameDraft.value.trim().length > 0 && renameDraft.value.trim() !== title.value,
)

watch(
  () => props.state?.title,
  () => {
    renameDraft.value = title.value
  },
  { immediate: true },
)

function submitRename() {
  if (!canSubmitName.value) {
    return
  }
  emit('renameThread', renameDraft.value)
}
</script>

<template>
  <header
    class="grid gap-2 border-b border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-2.5 max-sm:px-3"
  >
    <div class="min-w-0">
      <p
        class="m-0 text-xs font-bold uppercase tracking-[0.14em] text-[color:var(--app-text-soft)]"
      >
        {{ displayPath(cwd) || 'Codex workspace' }}
      </p>
      <div
        class="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-[0.76rem] text-[color:var(--app-text-soft)]"
      >
        <span
          class="inline-flex items-center rounded-full border px-2 py-0.5 font-semibold"
          :class="statusTone(status)"
        >
          {{ statusLabel(status) }}
        </span>
        <code v-if="threadId" class="truncate">{{ shortId(threadId, 12) }}</code>
        <span class="truncate">model {{ modelLabel }}</span>
        <span class="truncate">effort {{ effortLabel }}</span>
      </div>
    </div>

    <form
      v-if="false"
      class="grid grid-cols-[minmax(0,1fr)_auto] gap-2 max-sm:grid-cols-1"
      data-codex-rename-form
      @submit.prevent="submitRename"
    >
      <input
        v-model="renameDraft"
        class="h-9 min-w-0 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-3 text-sm outline-none transition focus:border-[color:var(--app-accent)]"
        :disabled="busy || !threadId"
        placeholder="Thread name"
      />
      <button
        type="submit"
        class="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-3 text-sm font-semibold text-[color:var(--app-text)] transition hover:border-[color:var(--app-accent)] disabled:cursor-not-allowed disabled:opacity-45"
        :disabled="busy || renaming || !canSubmitName"
      >
        <i class="pi pi-check text-xs"></i>
        <span>Rename</span>
      </button>
    </form>
  </header>
</template>
