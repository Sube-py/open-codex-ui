<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import Breadcrumb from 'primevue/breadcrumb'
import Button from 'primevue/button'
import Drawer from 'primevue/drawer'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import ScrollPanel from 'primevue/scrollpanel'

import { apiGet } from '../../lib/api'
import type { CodexFilesystemEntry, CodexFilesystemResponse } from '../types'

const visible = defineModel<boolean>('visible', { required: true })

const props = withDefaults(
  defineProps<{
    selectedPath?: string
    disabled?: boolean
    title?: string
    confirmLabel?: string
    allowFiles?: boolean
    allowCurrentFolder?: boolean
    hostId?: string
  }>(),
  {
    allowCurrentFolder: true,
    allowFiles: false,
  },
)

const emit = defineEmits<{
  select: [path: string]
}>()

type BreadcrumbItem = {
  label: string
  icon?: string
  path: string
  command: () => void
}

const currentPath = ref('')
const parentPath = ref<string | null>(null)
const roots = ref<CodexFilesystemEntry[]>([])
const entries = ref<CodexFilesystemEntry[]>([])
const loading = ref(false)
const errorMessage = ref('')
const isMobile = ref(false)

let mediaQuery: MediaQueryList | null = null

const drawerPosition = computed(() => (isMobile.value ? 'full' : 'right'))
const canUseCurrentFolder = computed(
  () => Boolean(currentPath.value) && !loading.value && props.allowCurrentFolder !== false,
)
const currentLabel = computed(() => currentPath.value || 'Loading folders')
const drawerTitle = computed(() => props.title || 'Choose project folder')
const confirmLabel = computed(() => props.confirmLabel || 'Use this folder')

const breadcrumbHome = computed<BreadcrumbItem>(() => {
  const root = rootForPath(currentPath.value) ?? roots.value[0]
  const path = root?.path || '/'
  return {
    label: root?.name || '/',
    icon: 'pi pi-home',
    path,
    command: () => loadDirectory(path),
  }
})

const breadcrumbItems = computed<BreadcrumbItem[]>(() =>
  pathBreadcrumbItems(currentPath.value, breadcrumbHome.value.path).map((item) => ({
    ...item,
    command: () => loadDirectory(item.path),
  })),
)

watch(
  () => visible.value,
  (isVisible) => {
    if (isVisible) {
      loadDirectory(props.selectedPath || undefined)
    }
  },
)

onMounted(() => {
  if (visible.value) {
    loadDirectory(props.selectedPath || undefined)
  }

  if (typeof window === 'undefined') {
    return
  }
  mediaQuery = window.matchMedia?.('(max-width: 639px)') ?? null
  if (!mediaQuery) {
    isMobile.value = window.innerWidth < 640
    return
  }
  isMobile.value = mediaQuery.matches
  mediaQuery.addEventListener('change', updateMobileState)
})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener('change', updateMobileState)
})

function updateMobileState(event: MediaQueryListEvent) {
  isMobile.value = event.matches
}

async function loadDirectory(path?: string) {
  loading.value = true
  errorMessage.value = ''
  try {
    const searchParams: string[] = []
    if (path) {
      searchParams.push(`path=${encodeURIComponent(path)}`)
    }
    if (props.hostId && props.hostId !== 'local') {
      searchParams.push(`host_id=${encodeURIComponent(props.hostId)}`)
    }
    const query = searchParams.length ? `?${searchParams.join('&')}` : ''
    const payload = await apiGet<CodexFilesystemResponse>(`/api/codex/filesystem${query}`)
    currentPath.value = payload.path
    parentPath.value = payload.parent_path ?? null
    roots.value = payload.roots
    entries.value = payload.entries
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load host folders.'
  } finally {
    loading.value = false
  }
}

function selectCurrentFolder() {
  if (!canUseCurrentFolder.value) {
    return
  }
  emit('select', currentPath.value)
  visible.value = false
}

function selectFile(entry: CodexFilesystemEntry) {
  if (!props.allowFiles || entry.kind !== 'file' || !entry.readable) {
    return
  }
  emit('select', entry.path)
  visible.value = false
}

function loadBreadcrumbItem(item: unknown) {
  if (!item || typeof item !== 'object') {
    return
  }
  const path = (item as { path?: unknown }).path
  if (typeof path !== 'string' || !path) {
    return
  }
  loadDirectory(path)
}

function rootForPath(path: string) {
  if (!path) {
    return roots.value[0]
  }
  return (
    roots.value.find((root) => path === root.path || path.startsWith(root.path)) ?? roots.value[0]
  )
}

function pathBreadcrumbItems(path: string, rootPath: string) {
  if (!path || path === rootPath) {
    return []
  }

  const normalizedRoot = normalizeSeparators(rootPath).replace(/\/$/, '')
  const normalizedPath = normalizeSeparators(path)
  const relativePath = normalizedRoot
    ? normalizedPath.slice(normalizedRoot.length).replace(/^\/+/, '')
    : normalizedPath.replace(/^\/+/, '')
  const parts = relativePath.split('/').filter(Boolean)

  return parts.map((part, index) => {
    const prefix = normalizedRoot || ''
    const childPath = `${prefix}/${parts.slice(0, index + 1).join('/')}`
    return {
      label: part,
      path: childPath.replace(/^([A-Za-z]:)\/$/, '$1/'),
    }
  })
}

function normalizeSeparators(path: string) {
  return path.replace(/\\/g, '/')
}

function entryIcon(entry: CodexFilesystemEntry) {
  if (entry.kind === 'directory') {
    return entry.readable ? 'pi-folder' : 'pi-lock'
  }
  if (entry.kind !== 'file') {
    return 'pi-file'
  }
  if (isCodeExtension(entry.extension)) {
    return 'pi-file-code'
  }
  if (isImageExtension(entry.extension)) {
    return 'pi-image'
  }
  if (entry.extension === '.pdf') {
    return 'pi-file-pdf'
  }
  return 'pi-file'
}

function isCodeExtension(extension: string) {
  return ['.css', '.html', '.js', '.json', '.md', '.py', '.ts', '.tsx', '.vue'].includes(extension)
}

function isImageExtension(extension: string) {
  return ['.gif', '.jpeg', '.jpg', '.png', '.svg', '.webp'].includes(extension)
}
</script>

<template>
  <Drawer
    v-model:visible="visible"
    :header="drawerTitle"
    :position="drawerPosition"
    class="!w-full sm:!w-[34rem]"
    data-codex-host-path-picker
  >
    <div class="flex h-full min-h-0 flex-col gap-3">
      <div class="grid gap-2">
        <div
          class="flex min-w-0 items-center gap-2 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-translucent)] px-3 py-2 text-sm text-[color:var(--app-text)]"
        >
          <i class="pi pi-folder-open shrink-0 text-[color:var(--app-text-soft)]"></i>
          <span class="truncate" data-codex-host-path-current>{{ currentLabel }}</span>
        </div>

        <Breadcrumb
          :home="breadcrumbHome"
          :model="breadcrumbItems"
          class="min-w-0 overflow-hidden rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] text-sm"
          data-codex-host-path-breadcrumb
        >
          <template #item="{ item }">
            <button
              type="button"
              class="inline-flex max-w-40 min-w-0 items-center gap-1.5 truncate text-sm text-[color:var(--app-text)] hover:text-[color:var(--app-accent)]"
              @click="loadBreadcrumbItem(item)"
            >
              <i v-if="item.icon" class="pi shrink-0 text-xs" :class="item.icon"></i>
              <span class="truncate">{{ item.label }}</span>
            </button>
          </template>
        </Breadcrumb>
      </div>

      <Message v-if="errorMessage" severity="error" :closable="false" data-codex-host-path-error>
        {{ errorMessage }}
      </Message>

      <div
        v-if="loading"
        class="grid min-h-52 place-items-center rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)]"
        data-codex-host-path-loading
      >
        <ProgressSpinner style="width: 2rem; height: 2rem" stroke-width="4" />
      </div>

      <ScrollPanel
        v-else
        class="min-h-0 flex-1 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)]"
      >
        <div class="grid gap-1 p-2" data-codex-host-path-entries>
          <button
            v-if="parentPath"
            type="button"
            class="grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)] items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-[color:var(--app-text)] transition hover:bg-[color:var(--app-selected)]"
            data-codex-host-path-parent
            @click="loadDirectory(parentPath)"
          >
            <i class="pi pi-arrow-up text-xs text-[color:var(--app-text-soft)]"></i>
            <span class="truncate font-semibold">Parent folder</span>
          </button>

          <template v-for="entry in entries" :key="entry.path">
            <button
              v-if="entry.kind === 'directory'"
              type="button"
              class="grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 py-2 text-left text-sm transition"
              :class="
                entry.readable
                  ? 'text-[color:var(--app-text)] hover:bg-[color:var(--app-selected)]'
                  : 'cursor-not-allowed text-[color:var(--app-text-soft)] opacity-60'
              "
              :disabled="!entry.readable"
              data-codex-host-path-folder
              @click="loadDirectory(entry.path)"
            >
              <i class="pi text-sm text-[color:var(--app-text-soft)]" :class="entryIcon(entry)"></i>
              <span class="truncate font-semibold">{{ entry.name }}</span>
              <i class="pi pi-chevron-right text-xs text-[color:var(--app-text-soft)]"></i>
            </button>

            <div
              v-else
              class="grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 py-2 text-left text-sm transition"
              :class="
                allowFiles && entry.readable
                  ? 'cursor-pointer text-[color:var(--app-text)] hover:bg-[color:var(--app-selected)]'
                  : 'text-[color:var(--app-text-soft)]'
              "
              data-codex-host-path-file
              @click="selectFile(entry)"
            >
              <i class="pi text-sm" :class="entryIcon(entry)"></i>
              <span class="truncate">{{ entry.name }}</span>
              <span class="text-[0.68rem] uppercase">{{ entry.extension || entry.kind }}</span>
            </div>
          </template>

          <div
            v-if="!entries.length && !errorMessage"
            class="grid place-items-center gap-2 px-3 py-10 text-center text-sm text-[color:var(--app-text-soft)]"
            data-codex-host-path-empty
          >
            <i class="pi pi-folder-open text-lg"></i>
            <p class="m-0">This folder is empty.</p>
          </div>
        </div>
      </ScrollPanel>

      <div class="grid gap-2 pt-1" :class="allowCurrentFolder ? 'grid-cols-2' : 'grid-cols-1'">
        <Button
          label="Cancel"
          icon="pi pi-times"
          severity="secondary"
          outlined
          :disabled="disabled"
          @click="visible = false"
        />
        <Button
          v-if="allowCurrentFolder"
          :label="confirmLabel"
          icon="pi pi-check"
          :disabled="disabled || !canUseCurrentFolder"
          data-codex-host-path-confirm
          @click="selectCurrentFolder"
        />
      </div>
    </div>
  </Drawer>
</template>
