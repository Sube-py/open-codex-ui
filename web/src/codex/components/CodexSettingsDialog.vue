<script setup lang="ts">
import Dialog from 'primevue/dialog'

import type { CodexWorkspaceResponse } from '../types'
import CodexRemoteConnections from './CodexRemoteConnections.vue'

const visible = defineModel<boolean>('visible', { required: true })

defineProps<{
  workspace: CodexWorkspaceResponse
  busy?: boolean
}>()

const emit = defineEmits<{
  remoteConnectionChanged: []
}>()
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    header="Settings"
    class="h-[min(44rem,calc(100dvh-2rem))] w-[min(58rem,calc(100vw-2rem))]"
    :draggable="false"
    :content-props="{ class: 'min-h-0 overflow-hidden !p-0' }"
    data-codex-settings-dialog
  >
    <div class="grid h-full min-h-0 grid-cols-[12rem_minmax(0,1fr)] max-sm:grid-cols-1">
      <nav
        class="border-r border-[color:var(--app-border)] bg-[rgba(248,248,246,0.8)] p-3 max-sm:border-b max-sm:border-r-0"
        aria-label="Settings sections"
      >
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-md bg-[rgba(21,94,99,0.09)] px-3 py-2 text-left text-sm font-semibold text-[color:var(--app-text)]"
          aria-current="page"
        >
          <i class="pi pi-server text-xs"></i>
          <span>Connections</span>
        </button>
      </nav>

      <div class="min-h-0 overflow-y-auto p-5 max-sm:p-4">
        <CodexRemoteConnections
          :workspace="workspace"
          :busy="busy"
          @remote-connection-changed="emit('remoteConnectionChanged')"
        />
      </div>
    </div>
  </Dialog>
</template>
