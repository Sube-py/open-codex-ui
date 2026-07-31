<script setup lang="ts">
import { computed, ref } from 'vue'

import { compactJson, isRecord } from '../lib/format'
import type { JsonRecord } from '../types'

const props = defineProps<{
  item: JsonRecord
}>()

const expanded = ref(false)

const willRetry = computed(() => props.item.willRetry === true)
const isServerOverloaded = computed(() => {
  const errorInfo = props.item.errorInfo
  if (errorInfo === 'serverOverloaded') {
    return true
  }
  if (!isRecord(errorInfo)) {
    return false
  }
  const disconnected = errorInfo.responseStreamDisconnected
  return isRecord(disconnected) && disconnected.httpStatusCode === 429
})

const progress = computed(() => {
  const attempt = positiveInteger(props.item.reconnectAttempt)
  const maxAttempts = positiveInteger(props.item.reconnectMaxAttempts)
  return attempt != null && maxAttempts != null ? `${attempt}/${maxAttempts}` : ''
})

const summary = computed(() => {
  if (willRetry.value) {
    const message = isServerOverloaded.value ? 'Server is busy, reconnecting' : 'Reconnecting'
    return progress.value ? `${message} ${progress.value}` : message
  }

  const message = firstString(props.item.message, props.item.content)
  if (message) {
    return message
  }
  if (props.item.errorInfo === 'usageLimitExceeded') {
    return 'You have reached your usage limit. Please try again later.'
  }
  return 'Something went wrong. Please try again.'
})

const additionalDetails = computed(() => {
  const value = props.item.additionalDetails
  if (typeof value === 'string') {
    return value.trim()
  }
  return value == null ? '' : compactJson(value)
})

function positiveInteger(value: unknown) {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }
  return ''
}
</script>

<template>
  <article
    class="flex max-w-[min(52rem,100%)] min-w-0 items-start gap-2 py-1 text-sm"
    :class="willRetry ? 'text-[color:var(--app-text-soft)]' : 'text-[color:var(--app-danger-text)]'"
    data-codex-conversation-error
    :data-codex-error-retrying="willRetry || undefined"
  >
    <i
      class="pi mt-0.5 shrink-0 text-[0.78rem]"
      :class="willRetry ? 'pi-wifi' : 'pi-exclamation-circle'"
      aria-hidden="true"
    ></i>
    <div class="min-w-0">
      <p class="m-0 whitespace-pre-wrap [overflow-wrap:anywhere]" data-codex-error-summary>
        {{ summary }}
      </p>
      <button
        v-if="additionalDetails"
        type="button"
        class="mt-1 inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-xs text-[color:var(--app-text-soft)] transition hover:bg-[color:var(--app-hover)] hover:text-[color:var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--app-focus)]"
        :aria-expanded="expanded"
        data-codex-error-details-toggle
        @click="expanded = !expanded"
      >
        <span>Details</span>
        <i
          class="pi pi-chevron-right text-[0.52rem] opacity-60 transition-transform"
          :class="expanded ? 'rotate-90' : ''"
          aria-hidden="true"
        ></i>
      </button>
      <pre
        v-if="expanded && additionalDetails"
        class="m-0 mt-1 max-h-48 max-w-full overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-[color:var(--app-text-soft)]"
        data-codex-error-details
        >{{ additionalDetails }}</pre
      >
    </div>
  </article>
</template>
