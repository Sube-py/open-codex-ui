<script setup lang="ts">
import { computed, proxyRefs, ref } from 'vue'

import CodexChatPane from '../codex/components/CodexChatPane.vue'
import CodexSidebar from '../codex/components/CodexSidebar.vue'
import { useCodexWorkspace } from '../codex/composables/useCodexWorkspace'
import { activeThreadTitle } from '../codex/lib/format'
import type { JsonRecord } from '../codex/types'

const codex = proxyRefs(useCodexWorkspace())
const isMobileThreadDrawerOpen = ref(false)
const pageTitle = computed(() => activeThreadTitle(codex.activeThreadState) || 'Codex')

function submitUserInputResponse(requestId: string, response: JsonRecord) {
  void codex.submitUserInputResponse(requestId, response)
}

function showCodexError(message: string) {
  codex.errorMessage = message
  codex.successMessage = ''
}

async function handleRemoteConnectionChanged() {
  try {
    await codex.refreshRemoteConnections()
  } catch (error) {
    showCodexError(error instanceof Error ? error.message : String(error))
    return
  }
  void codex.refreshWorkspaceAndSelect().catch((error) => {
    showCodexError(error instanceof Error ? error.message : String(error))
  })
}

function openMobileThreadDrawer() {
  isMobileThreadDrawerOpen.value = true
}

function closeMobileThreadDrawer() {
  isMobileThreadDrawerOpen.value = false
}

function selectMobileThread(threadId: string) {
  codex.selectThread(threadId)
  closeMobileThreadDrawer()
}

function startMobileThread(projectPath: string, hostId?: string) {
  if (hostId) {
    codex.startThread(projectPath, hostId)
  } else {
    codex.startThread(projectPath)
  }
  closeMobileThreadDrawer()
}
</script>

<template>
  <div
    class="grid h-dvh grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] overflow-hidden bg-[color:var(--app-bg)] max-lg:grid-cols-1"
  >
    <CodexSidebar
      v-model:project-path="codex.projectPathDraft"
      class="max-lg:hidden"
      :workspace="codex.workspace"
      :active-thread-id="codex.activeThreadId"
      :opening-thread-id="codex.openingThreadId"
      :archiving-thread-id="codex.archivingThreadId"
      :forking-thread-id="codex.forkingThreadId"
      :busy="codex.isBooting || codex.isRenaming || codex.isArchiving"
      @select-thread="codex.selectThread"
      @start-thread="codex.startThread"
      @archive-thread="codex.archiveThread"
      @fork-thread="codex.forkThread"
      @rename-thread="codex.renameThread"
      @copy-error="showCodexError"
      @project-changed="codex.refreshWorkspaceAndSelect"
      @remote-connection-changed="handleRemoteConnectionChanged"
    />

    <main class="flex min-h-0 flex-col overflow-hidden">
      <div
        class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)] items-center gap-2 border-b border-[color:var(--app-border)] bg-[color:var(--app-panel-strong)] px-4 py-2 pt-[calc(0.5rem+env(safe-area-inset-top))] max-sm:px-3"
      >
        <div class="flex min-w-0 items-center gap-2 justify-self-start">
          <button
            type="button"
            class="hidden h-8 shrink-0 items-center gap-2 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-2.5 text-sm font-semibold text-[color:var(--app-text)] max-lg:inline-flex"
            aria-label="Open Codex threads"
            data-codex-mobile-thread-drawer-open
            @click="openMobileThreadDrawer"
          >
            <i class="pi pi-bars text-xs"></i>
            <!-- <span class="max-[380px]:sr-only">Threads</span> -->
          </button>
          <span
            class="h-2.5 w-2.5 shrink-0 rounded-full max-sm:hidden"
            :class="
              codex.status === 'open'
                ? 'bg-emerald-500'
                : codex.status === 'connecting'
                  ? 'bg-amber-500'
                  : 'bg-red-500'
            "
          ></span>
          <span
            class="truncate text-sm font-semibold text-[color:var(--app-text)] max-sm:hidden"
            data-codex-connection-status
          >
            Codex {{ codex.status }}
          </span>
        </div>

        <h1
          class="m-0 min-w-0 truncate text-center text-base font-semibold text-[color:var(--app-text)] max-sm:text-sm"
          data-codex-page-title
          :title="pageTitle"
        >
          {{ pageTitle }}
        </h1>

        <div class="justify-self-end"></div>
      </div>

      <div class="grid min-h-0 flex-1 grid-cols-1 overflow-hidden">
        <CodexChatPane
          :active-thread-id="codex.activeThreadId"
          :active-thread-state="codex.activeThreadState"
          :active-user-input-request="codex.activeUserInputRequest"
          :active-status="codex.activeStatus"
          :active-mode="codex.activeMode"
          :queued-followups="codex.queuedFollowups"
          :socket-status="codex.status"
          :error-message="codex.errorMessage"
          :success-message="codex.successMessage"
          :is-command-busy="codex.isCommandBusy"
          :is-renaming="codex.isRenaming"
          :is-archiving="codex.isArchiving"
          :is-thread-loading="codex.isActiveThreadLoading"
          :is-active-turn-in-progress="codex.isActiveTurnInProgress"
          :list-skills="codex.listSkills"
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
          @copy-error="showCodexError"
        />
      </div>
    </main>

    <Teleport to="body">
      <Transition name="sheet-fade">
        <button
          v-if="isMobileThreadDrawerOpen"
          type="button"
          class="sheet-overlay lg:hidden"
          aria-label="Close Codex threads"
          data-codex-mobile-thread-drawer-overlay
          @click="closeMobileThreadDrawer"
        ></button>
      </Transition>
      <Transition name="drawer-slide">
        <div
          v-if="isMobileThreadDrawerOpen"
          class="drawer-panel lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Codex threads"
          data-codex-mobile-thread-drawer
        >
          <CodexSidebar
            v-model:project-path="codex.projectPathDraft"
            class="min-h-0 flex-1 border-r-0"
            data-codex-mobile-thread-sidebar
            :workspace="codex.workspace"
            :active-thread-id="codex.activeThreadId"
            :opening-thread-id="codex.openingThreadId"
            :archiving-thread-id="codex.archivingThreadId"
            :forking-thread-id="codex.forkingThreadId"
            :busy="codex.isBooting || codex.isRenaming || codex.isArchiving"
            @select-thread="selectMobileThread"
            @start-thread="startMobileThread"
            @archive-thread="codex.archiveThread"
            @fork-thread="codex.forkThread"
            @rename-thread="codex.renameThread"
            @copy-error="showCodexError"
            @project-changed="codex.refreshWorkspaceAndSelect"
            @remote-connection-changed="handleRemoteConnectionChanged"
          />
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
