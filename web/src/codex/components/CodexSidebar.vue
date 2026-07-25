<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Menu from 'primevue/menu'
import ScrollPanel from 'primevue/scrollpanel'

import type { CodexNativeSessionSummary, CodexProjectGroup, CodexWorkspaceResponse } from '../types'
import { displayPath, isWorkingStatus } from '../lib/format'
import CodexAddProjectDialog from './CodexAddProjectDialog.vue'
import CodexProjectIdentity from './CodexProjectIdentity.vue'
import CodexSettingsDialog from './CodexSettingsDialog.vue'

const EXPANDED_PROJECTS_STORAGE_KEY = 'yier.codex.sidebar.expanded-projects'
const PROJECT_THREAD_PAGE_SIZE = 10
const CHATS_THREAD_PAGE_SIZE = 50

const projectPath = defineModel<string>('projectPath', { required: true })

const props = defineProps<{
  workspace: CodexWorkspaceResponse
  activeThreadId: string
  openingThreadId?: string
  archivingThreadId?: string
  forkingThreadId?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  selectThread: [threadId: string]
  startThread: [projectPath: string, hostId: string]
  archiveThread: [threadId: string]
  forkThread: [threadId: string]
  renameThread: [threadId: string, name: string]
  copyError: [message: string]
  remoteConnectionChanged: []
}>()

type ProjectWithKey = CodexProjectGroup & {
  key: string
  isChats?: boolean
}

type MenuRef = {
  toggle: (event: Event) => void
}

const copiedThreadId = ref('')
const editingThreadId = ref('')
const addProjectVisible = ref(false)
const settingsVisible = ref(false)
const renameDraft = ref('')
const threadActionMenu = ref<MenuRef | null>(null)
const threadActionTarget = ref<CodexNativeSessionSummary | null>(null)
const userExpandedProjects = ref<Record<string, boolean>>(readExpandedProjects())
const visibleThreadLimits = ref<Record<string, number>>({})

const projects = computed<ProjectWithKey[]>(() =>
  props.workspace.projects
    .map((project) => ({
      ...project,
      key: projectKey(project),
      sessions: [...project.sessions].sort(
        (left, right) =>
          usedAt(right) - usedAt(left) ||
          right.started_at - left.started_at ||
          right.thread_id.localeCompare(left.thread_id),
      ),
    }))
    .sort(compareProjects),
)
const recentThreads = computed(() =>
  [...(props.workspace.recent_threads ?? [])].sort(
    (left, right) =>
      usedAt(right) - usedAt(left) ||
      right.started_at - left.started_at ||
      right.thread_id.localeCompare(left.thread_id),
  ),
)
const sections = computed<ProjectWithKey[]>(() => {
  const recent = recentThreads.value.length
    ? [
        {
          id: 'chats',
          project: 'Chats',
          project_path: '',
          host_id: 'local',
          kind: 'local' as const,
          root_paths: [],
          session_count: recentThreads.value.length,
          sessions: recentThreads.value,
          key: 'chats',
          isChats: true,
        },
      ]
    : []
  return [...projects.value, ...recent]
})

const latestProjectKey = computed(() => projects.value[0]?.key ?? '')
const activeProjectKey = computed(() => {
  if (!props.activeThreadId) {
    return ''
  }
  return (
    sections.value.find((project) =>
      project.sessions.some((thread) => thread.thread_id === props.activeThreadId),
    )?.key ?? ''
  )
})
const threadActionItems = computed(() => {
  const thread = threadActionTarget.value
  return [
    {
      label: 'Fork',
      icon: 'pi pi-sitemap',
      disabled:
        !thread ||
        props.busy ||
        props.forkingThreadId === thread.thread_id ||
        isThreadWorking(thread),
      command: () => {
        if (thread) {
          emit('forkThread', thread.thread_id)
        }
      },
    },
    {
      label: thread && copiedThreadId.value === thread.thread_id ? 'Copied ID' : 'Copy ID',
      icon: thread && copiedThreadId.value === thread.thread_id ? 'pi pi-check' : 'pi pi-copy',
      disabled: !thread,
      command: () => {
        if (thread) {
          void copyThreadId(thread.thread_id)
        }
      },
    },
  ]
})

watch(
  userExpandedProjects,
  (value) => {
    persistExpandedProjects(value)
  },
  { deep: true },
)

watch(copiedThreadId, (threadId) => {
  if (!threadId) {
    return
  }
  window.setTimeout(() => {
    if (copiedThreadId.value === threadId) {
      copiedThreadId.value = ''
    }
  }, 1400)
})

function readExpandedProjects() {
  if (typeof localStorage === 'undefined') {
    return {}
  }
  try {
    const value = JSON.parse(localStorage.getItem(EXPANDED_PROJECTS_STORAGE_KEY) ?? '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return {}
    }
    return Object.fromEntries(
      Object.entries(value).filter(
        (entry): entry is [string, boolean] =>
          typeof entry[0] === 'string' && typeof entry[1] === 'boolean',
      ),
    )
  } catch {
    return {}
  }
}

function persistExpandedProjects(value: Record<string, boolean>) {
  if (typeof localStorage === 'undefined') {
    return
  }
  localStorage.setItem(EXPANDED_PROJECTS_STORAGE_KEY, JSON.stringify(value))
}

function usedAt(thread: { updated_at: number; started_at: number }) {
  return thread.updated_at || thread.started_at || 0
}

function latestProjectTime(project: CodexProjectGroup) {
  return project.sessions.reduce((latest, session) => Math.max(latest, usedAt(session)), 0)
}

function compareProjects(left: CodexProjectGroup, right: CodexProjectGroup) {
  return (
    latestProjectTime(right) - latestProjectTime(left) ||
    (left.project || left.project_path).localeCompare(right.project || right.project_path)
  )
}

function projectKey(project: CodexProjectGroup) {
  return `${projectHostId(project)}::${project.project_path || project.project || 'unknown'}`
}

function projectTitle(project: CodexProjectGroup) {
  return project.project || displayPath(project.project_path) || 'Untitled project'
}

function projectHostId(project: CodexProjectGroup) {
  const explicit = project.host_id || project.hostId
  if (explicit) {
    return explicit
  }
  return threadHostId(project.sessions[0])
}

function threadHostId(thread: CodexNativeSessionSummary | undefined) {
  return thread?.host_id || thread?.hostId || 'local'
}

function threadTitle(thread: CodexNativeSessionSummary) {
  return thread.title || thread.preview || thread.thread_id
}

function compactTimestamp(value: number | null | undefined) {
  if (!value) {
    return ''
  }
  const milliseconds = value > 10_000_000_000 ? value : value * 1000
  const deltaSeconds = Math.max(0, Math.floor((Date.now() - milliseconds) / 1000))
  if (deltaSeconds < 60) {
    return 'now'
  }
  if (deltaSeconds < 3600) {
    return `${Math.floor(deltaSeconds / 60)}m`
  }
  if (deltaSeconds < 86400) {
    return `${Math.floor(deltaSeconds / 3600)}h`
  }
  if (deltaSeconds < 604800) {
    return `${Math.floor(deltaSeconds / 86400)}d`
  }
  if (deltaSeconds < 2_592_000) {
    return `${Math.floor(deltaSeconds / 604800)}w`
  }
  if (deltaSeconds < 31_536_000) {
    return `${Math.floor(deltaSeconds / 2_592_000)}mo`
  }
  return `${Math.floor(deltaSeconds / 31_536_000)}y`
}

function isThreadWorking(thread: CodexNativeSessionSummary) {
  return isWorkingStatus(thread.status)
}

function isProjectExpanded(project: ProjectWithKey) {
  if (project.key in userExpandedProjects.value) {
    return userExpandedProjects.value[project.key] ?? false
  }
  return (
    project.isChats === true ||
    project.key === activeProjectKey.value ||
    project.key === latestProjectKey.value
  )
}

function toggleProject(project: ProjectWithKey) {
  userExpandedProjects.value = {
    ...userExpandedProjects.value,
    [project.key]: !isProjectExpanded(project),
  }
}

function threadPageSize(project: ProjectWithKey) {
  return project.isChats ? CHATS_THREAD_PAGE_SIZE : PROJECT_THREAD_PAGE_SIZE
}

function visibleThreads(project: ProjectWithKey) {
  const limit = visibleThreadLimits.value[project.key] ?? threadPageSize(project)
  return project.sessions.filter(
    (thread, index) => index < limit || thread.thread_id === props.activeThreadId,
  )
}

function hiddenThreadCount(project: ProjectWithKey) {
  return project.sessions.length - visibleThreads(project).length
}

function showMoreThreads(project: ProjectWithKey) {
  const currentLimit = visibleThreadLimits.value[project.key] ?? threadPageSize(project)
  visibleThreadLimits.value = {
    ...visibleThreadLimits.value,
    [project.key]: Math.min(project.sessions.length, currentLimit + threadPageSize(project)),
  }
}

function startProjectThread(project: ProjectWithKey) {
  const normalizedProjectPath = project.project_path.trim()
  if (!normalizedProjectPath || props.busy) {
    return
  }
  projectPath.value = normalizedProjectPath
  emit('startThread', normalizedProjectPath, projectHostId(project))
}

function toggleThreadMenu(event: Event, thread: CodexNativeSessionSummary) {
  threadActionTarget.value = thread
  threadActionMenu.value?.toggle(event)
}

async function beginRename(thread: CodexNativeSessionSummary) {
  if (props.busy) {
    return
  }
  editingThreadId.value = thread.thread_id
  renameDraft.value = threadTitle(thread)
  await nextTick()
  const input = document.querySelector<HTMLInputElement>('[data-codex-thread-rename-input]')
  input?.focus()
  input?.select()
}

function cancelRename() {
  editingThreadId.value = ''
  renameDraft.value = ''
}

function submitRename(thread: CodexNativeSessionSummary) {
  if (editingThreadId.value !== thread.thread_id) {
    return
  }
  const nextName = renameDraft.value.trim()
  if (!nextName || nextName === threadTitle(thread).trim()) {
    cancelRename()
    return
  }
  emit('renameThread', thread.thread_id, nextName)
  cancelRename()
}

async function copyThreadId(threadId: string) {
  try {
    await navigator.clipboard.writeText(threadId)
    copiedThreadId.value = threadId
  } catch {
    emit('copyError', 'Unable to copy thread id.')
  }
}
</script>

<template>
  <aside
    class="flex min-h-0 flex-col border-r border-[color:var(--app-border)] bg-[rgba(255,253,247,0.82)]"
  >
    <header
      class="flex items-center justify-between gap-3 border-b border-[color:var(--app-border)] px-4 py-3"
    >
      <div class="flex min-w-0 items-center gap-3">
        <img src="/brand/yier-icon.svg" alt="" class="h-9 w-9 shrink-0 rounded-xl" />
        <div class="min-w-0">
          <h1 class="m-0 truncate text-base font-semibold text-[color:var(--app-text)]">Yier</h1>
          <p class="m-0 mt-0.5 truncate text-[0.72rem] text-[color:var(--app-text-soft)]">
            Codex anywhere
          </p>
        </div>
      </div>
      <Button
        icon="pi pi-folder-plus"
        severity="secondary"
        text
        rounded
        aria-label="Add Codex project"
        data-codex-add-project
        :disabled="busy"
        @click="addProjectVisible = true"
      />
    </header>

    <ScrollPanel class="min-h-0 flex-1">
      <div class="p-3">
        <div
          v-if="!sections.length"
          class="grid place-items-center gap-2 p-6 text-center text-sm text-[color:var(--app-text-soft)]"
        >
          <i class="pi pi-inbox text-lg"></i>
          <p class="m-0">Add a project to get started.</p>
        </div>

        <section
          v-for="project in sections"
          :key="project.key"
          class="mb-2 grid gap-1"
          :data-codex-section-key="project.key"
        >
          <div
            class="group/project relative flex items-center rounded-lg transition hover:bg-white/65 focus-within:bg-white/65"
            data-codex-project-row
          >
            <button
              type="button"
              class="flex w-full min-w-0 items-center px-2 py-1.5 text-left"
              data-codex-project-toggle
              :aria-expanded="isProjectExpanded(project)"
              @click="toggleProject(project)"
            >
              <CodexProjectIdentity
                v-if="!project.isChats"
                :expanded="isProjectExpanded(project)"
                :host-id="projectHostId(project)"
                :workspace="workspace"
              >
                <span class="truncate text-sm font-semibold text-[color:var(--app-text)]">
                  {{ projectTitle(project) }}
                </span>
              </CodexProjectIdentity>
              <span
                v-else
                class="flex min-w-0 items-center gap-2 text-sm font-semibold text-[color:var(--app-text)]"
              >
                <i
                  class="pi pi-comments w-4 shrink-0 text-center text-[color:var(--app-text-soft)]"
                ></i>
                <span class="truncate">Chats</span>
              </span>
            </button>
            <Button
              v-if="!project.isChats"
              icon="pi pi-pen-to-square"
              severity="secondary"
              text
              rounded
              size="small"
              class="pointer-events-none !absolute right-0 z-10 !h-7 !w-7 !min-w-7 !p-0 opacity-0 transition-opacity group-hover/project:pointer-events-auto group-hover/project:opacity-100 group-focus-within/project:pointer-events-auto group-focus-within/project:opacity-100"
              :aria-label="`Start Codex thread in ${projectTitle(project)}`"
              data-codex-project-start-thread
              :disabled="busy || !project.project_path.trim()"
              @click.stop="startProjectThread(project)"
            />
          </div>

          <div v-show="isProjectExpanded(project)" class="grid gap-0.5">
            <article
              v-for="thread in visibleThreads(project)"
              :key="thread.thread_id"
              class="group/thread grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-lg border py-1.5 pl-[2.15rem] pr-2 transition"
              data-codex-thread-row
              :class="
                thread.thread_id === activeThreadId
                  ? 'border-[rgba(21,94,99,0.24)] bg-[rgba(21,94,99,0.08)]'
                  : 'border-transparent hover:border-[rgba(21,94,99,0.24)] hover:bg-[rgba(21,94,99,0.08)] focus-within:border-[rgba(21,94,99,0.24)] focus-within:bg-[rgba(21,94,99,0.08)]'
              "
            >
              <InputText
                v-if="editingThreadId === thread.thread_id"
                v-model="renameDraft"
                class="h-8 min-w-0 text-sm"
                data-codex-thread-rename-input
                :disabled="busy"
                @click.stop
                @dblclick.stop
                @keydown.enter.prevent="submitRename(thread)"
                @keydown.esc.prevent="cancelRename"
                @blur="submitRename(thread)"
              />
              <button
                v-else
                type="button"
                class="min-w-0 truncate text-left text-sm disabled:cursor-wait disabled:opacity-60"
                :class="
                  thread.thread_id === activeThreadId
                    ? 'font-semibold text-[color:var(--app-text)]'
                    : 'font-medium text-[color:var(--app-text-soft)] group-hover/thread:text-[color:var(--app-text)] group-focus-within/thread:text-[color:var(--app-text)]'
                "
                data-codex-thread-name
                :title="threadTitle(thread)"
                :disabled="busy || openingThreadId === thread.thread_id"
                @click="emit('selectThread', thread.thread_id)"
                @dblclick.stop="beginRename(thread)"
              >
                {{ threadTitle(thread) }}
              </button>

              <div class="relative h-5 w-[3.25rem] shrink-0">
                <span
                  v-if="isThreadWorking(thread)"
                  class="absolute inset-y-0 right-0 inline-flex h-5 w-5 items-center justify-center text-[color:var(--app-text-soft)] group-hover/thread:hidden group-focus-within/thread:hidden"
                  aria-label="Thread is working"
                  data-codex-thread-working-indicator
                >
                  <i class="pi pi-spinner pi-spin text-[0.68rem]"></i>
                </span>
                <span
                  v-else
                  class="absolute inset-y-0 right-0 inline-flex max-w-full items-center truncate text-[0.72rem] font-semibold text-[color:var(--app-text-soft)] group-hover/thread:hidden group-focus-within/thread:hidden"
                  data-codex-thread-time
                >
                  {{ compactTimestamp(thread.updated_at || thread.started_at) }}
                </span>

                <div
                  class="absolute inset-y-0 right-0 hidden h-5 shrink-0 items-center gap-0.5 group-hover/thread:flex group-focus-within/thread:flex"
                >
                  <Button
                    icon="pi pi-ellipsis-h"
                    severity="secondary"
                    text
                    rounded
                    size="small"
                    class="!h-5 !w-5 !min-w-5 !p-0 !text-[0.68rem]"
                    :aria-label="`Open Codex thread actions ${thread.thread_id}`"
                    data-codex-thread-actions
                    :disabled="busy"
                    @click.stop="toggleThreadMenu($event, thread)"
                  />
                  <Button
                    v-if="!isThreadWorking(thread)"
                    icon="pi pi-inbox"
                    severity="secondary"
                    text
                    rounded
                    size="small"
                    class="!h-5 !w-5 !min-w-5 !p-0 !text-[0.68rem]"
                    aria-label="Archive Codex thread"
                    data-codex-archive-thread
                    :disabled="busy || archivingThreadId === thread.thread_id"
                    @click.stop="emit('archiveThread', thread.thread_id)"
                  />
                  <span
                    v-else
                    class="inline-flex h-5 w-5 items-center justify-center text-[color:var(--app-text-soft)]"
                    aria-label="Thread is working"
                  >
                    <i class="pi pi-spinner pi-spin text-[0.68rem]"></i>
                  </span>
                </div>
              </div>
            </article>
            <Button
              v-if="hiddenThreadCount(project) > 0"
              icon="pi pi-angle-down"
              :label="`Show ${hiddenThreadCount(project)} more`"
              severity="secondary"
              text
              size="small"
              class="!justify-start !py-1 !pl-[2.15rem] !text-xs"
              data-codex-show-more-threads
              @click="showMoreThreads(project)"
            />
          </div>
        </section>
      </div>
    </ScrollPanel>

    <footer
      class="border-t border-[color:var(--app-border)] p-2.5 pb-[calc(0.625rem+env(safe-area-inset-bottom))]"
    >
      <button
        type="button"
        class="flex h-9 w-full items-center gap-2 rounded-md px-2.5 text-sm font-semibold text-[color:var(--app-text)] transition hover:bg-white/70"
        data-codex-open-settings
        @click="settingsVisible = true"
      >
        <i class="pi pi-cog w-4 text-center text-[color:var(--app-text-soft)]"></i>
        <span>Settings</span>
      </button>
    </footer>

    <CodexAddProjectDialog
      v-model:visible="addProjectVisible"
      :workspace="workspace"
      :disabled="busy"
      @project-changed="emit('remoteConnectionChanged')"
    />
    <CodexSettingsDialog
      v-model:visible="settingsVisible"
      :workspace="workspace"
      :busy="busy"
      @remote-connection-changed="emit('remoteConnectionChanged')"
    />

    <Menu ref="threadActionMenu" :model="threadActionItems" popup data-codex-thread-action-menu />
  </aside>
</template>
