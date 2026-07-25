<script setup lang="ts">
import { computed, ref } from 'vue'

import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import SelectButton from 'primevue/selectbutton'

import { apiPost, apiPut } from '../../lib/api'
import type {
  CodexRemoteConnection,
  CodexRemoteConnectionPayload,
  CodexRemoteConnectionResponse,
  CodexRemoteConnectionTestResponse,
  CodexWorkspaceResponse,
} from '../types'
import CodexHostPathPicker from './CodexHostPathPicker.vue'

type RemoteConnectionMode = 'direct' | 'alias'

const props = defineProps<{
  workspace: CodexWorkspaceResponse
  busy?: boolean
}>()

const emit = defineEmits<{
  remoteConnectionChanged: []
}>()

const remoteDialogVisible = ref(false)
const remoteConnectionMode = ref<RemoteConnectionMode>('direct')
const identityFilePickerVisible = ref(false)
const remoteError = ref('')
const remoteTestingId = ref('')
const remoteInstallingId = ref('')
const remoteSaving = ref(false)
const remoteEditingId = ref('')
const remoteDraft = ref<CodexRemoteConnectionPayload>(emptyRemoteDraft())
const remotePortDraft = ref('')
const apiKeyDialogConnection = ref<CodexRemoteConnection | null>(null)
const apiKeyDraft = ref('')
const apiKeySaving = ref(false)
const remoteConnectionModeOptions = [
  { label: 'Direct SSH', value: 'direct' },
  { label: 'SSH config alias', value: 'alias' },
]

const remoteConnections = computed(() => props.workspace.remote_connections ?? [])
const remoteStatuses = computed(() => props.workspace.remote_connection_statuses ?? {})
const identityFilePickerPath = computed(
  () => parentDirectory(remoteDraft.value.identity_file) || '~/.ssh',
)
const apiKeyDialogTitle = computed(() =>
  apiKeyDialogConnection.value
    ? `Sign in to ${remoteTitle(apiKeyDialogConnection.value)}`
    : 'Sign in',
)

function emptyRemoteDraft(): CodexRemoteConnectionPayload {
  return {
    display_name: '',
    ssh_host: '',
    ssh_username: '',
    ssh_port: null,
    ssh_alias: '',
    identity_file: '',
    remote_path: '~',
    auto_connect: false,
  }
}

function remoteTitle(connection: CodexRemoteConnection) {
  return connection.display_name || connection.ssh_alias || connection.ssh_host
}

function remoteSubtitle(connection: CodexRemoteConnection) {
  const target = connection.ssh_alias || directTarget(connection)
  const port = connection.ssh_alias || !connection.ssh_port ? '' : `:${connection.ssh_port}`
  return `${target}${port} · ${connection.remote_path || '~'}`
}

function directTarget(connection: Pick<CodexRemoteConnection, 'ssh_host' | 'ssh_username'>) {
  return connection.ssh_username
    ? `${connection.ssh_username}@${connection.ssh_host}`
    : connection.ssh_host
}

function remoteStatus(connection: CodexRemoteConnection) {
  return (
    remoteStatuses.value[connection.id] ?? {
      status: 'disconnected',
      detail: 'Not connected yet',
    }
  )
}

function remoteStatusLabel(connection: CodexRemoteConnection) {
  const status = remoteStatus(connection).status
  if (status === 'connected') {
    return 'Connected'
  }
  if (status === 'connecting') {
    return 'Connecting'
  }
  if (status === 'error') {
    return 'Connection failed'
  }
  return 'Disconnected'
}

function remoteStatusClass(connection: CodexRemoteConnection) {
  const status = remoteStatus(connection).status
  if (status === 'connected') {
    return 'bg-emerald-50 text-emerald-700'
  }
  if (status === 'connecting') {
    return 'bg-amber-50 text-amber-700'
  }
  if (status === 'error') {
    return 'bg-red-50 text-red-700'
  }
  return 'bg-slate-100 text-slate-600'
}

function openAddRemoteDialog() {
  remoteEditingId.value = ''
  remoteConnectionMode.value = 'direct'
  remoteDraft.value = emptyRemoteDraft()
  remotePortDraft.value = ''
  remoteError.value = ''
  remoteDialogVisible.value = true
}

function openEditRemoteDialog(connection: CodexRemoteConnection) {
  remoteEditingId.value = connection.id
  remoteConnectionMode.value = connection.ssh_alias ? 'alias' : 'direct'
  remoteDraft.value = {
    display_name: connection.display_name,
    ssh_host: connection.ssh_host,
    ssh_username: connection.ssh_username ?? '',
    ssh_port: connection.ssh_port ?? null,
    ssh_alias: connection.ssh_alias,
    identity_file: connection.identity_file,
    remote_path: connection.remote_path || '~',
    auto_connect: connection.auto_connect,
  }
  remotePortDraft.value = connection.ssh_port ? String(connection.ssh_port) : ''
  remoteError.value = ''
  remoteDialogVisible.value = true
}

function setRemoteConnectionMode(mode: RemoteConnectionMode | null) {
  if (!mode) {
    return
  }
  remoteConnectionMode.value = mode
  if (mode === 'alias') {
    remoteDraft.value = {
      ...remoteDraft.value,
      ssh_host: '',
      ssh_username: '',
      ssh_port: null,
      identity_file: '',
    }
    remotePortDraft.value = ''
    return
  }
  remoteDraft.value = { ...remoteDraft.value, ssh_alias: '' }
}

function closeRemoteDialog() {
  remoteDialogVisible.value = false
  identityFilePickerVisible.value = false
  remoteEditingId.value = ''
  remoteError.value = ''
}

function parentDirectory(path: string) {
  const normalizedPath = path.trim().replace(/\\/g, '/')
  const separatorIndex = normalizedPath.lastIndexOf('/')
  if (separatorIndex < 0) {
    return ''
  }
  if (separatorIndex === 0) {
    return '/'
  }
  return normalizedPath.slice(0, separatorIndex)
}

function selectIdentityFile(path: string) {
  remoteDraft.value.identity_file = path
  identityFilePickerVisible.value = false
}

function openApiKeyDialog(connection: CodexRemoteConnection) {
  apiKeyDialogConnection.value = connection
  apiKeyDraft.value = ''
  remoteError.value = ''
}

function closeApiKeyDialog() {
  apiKeyDialogConnection.value = null
  apiKeyDraft.value = ''
}

async function saveRemoteConnection() {
  remoteError.value = ''
  const isAliasMode = remoteConnectionMode.value === 'alias'
  const payload = {
    ...remoteDraft.value,
    ssh_host: isAliasMode ? '' : remoteDraft.value.ssh_host,
    ssh_username: isAliasMode ? '' : remoteDraft.value.ssh_username,
    ssh_port: isAliasMode
      ? null
      : remotePortDraft.value.trim()
        ? Number(remotePortDraft.value.trim())
        : null,
    ssh_alias: isAliasMode ? remoteDraft.value.ssh_alias : '',
    identity_file: isAliasMode ? '' : remoteDraft.value.identity_file,
  }
  if (payload.ssh_port !== null && !Number.isInteger(payload.ssh_port)) {
    remoteError.value = 'SSH port must be an integer.'
    return
  }
  if (isAliasMode && !payload.ssh_alias.trim()) {
    remoteError.value = 'SSH config alias is required.'
    return
  }
  if (!isAliasMode && !payload.ssh_host.trim()) {
    remoteError.value = 'Host is required for a direct SSH connection.'
    return
  }
  remoteSaving.value = true
  try {
    if (remoteEditingId.value) {
      await apiPut<CodexRemoteConnectionResponse>(
        `/api/codex/remote-connections/${encodeURIComponent(remoteEditingId.value)}`,
        payload,
      )
    } else {
      await apiPost<CodexRemoteConnectionResponse>('/api/codex/remote-connections', payload)
    }
    closeRemoteDialog()
    emit('remoteConnectionChanged')
  } catch (error) {
    remoteError.value = error instanceof Error ? error.message : String(error)
  } finally {
    remoteSaving.value = false
  }
}

async function testRemoteConnection(connection: CodexRemoteConnection) {
  remoteTestingId.value = connection.id
  remoteError.value = ''
  try {
    const result = await apiPost<CodexRemoteConnectionTestResponse>(
      `/api/codex/remote-connections/${encodeURIComponent(connection.id)}/test`,
      {},
    )
    remoteError.value = result.ok ? `Connected: ${result.detail}` : result.detail
  } catch (error) {
    remoteError.value = error instanceof Error ? error.message : String(error)
  } finally {
    remoteTestingId.value = ''
  }
}

async function restartRemoteConnection(connection: CodexRemoteConnection) {
  remoteError.value = ''
  try {
    await apiPost(`/api/codex/remote-connections/${encodeURIComponent(connection.id)}/restart`, {})
    emit('remoteConnectionChanged')
  } catch (error) {
    remoteError.value = error instanceof Error ? error.message : String(error)
  }
}

async function installRemoteCodex(connection: CodexRemoteConnection) {
  remoteInstallingId.value = connection.id
  remoteError.value = ''
  try {
    const result = await apiPost<CodexRemoteConnectionTestResponse>(
      `/api/codex/remote-connections/${encodeURIComponent(connection.id)}/install`,
      {},
    )
    remoteError.value = result.ok ? `Installed: ${result.detail}` : result.detail
    emit('remoteConnectionChanged')
  } catch (error) {
    remoteError.value = error instanceof Error ? error.message : String(error)
  } finally {
    remoteInstallingId.value = ''
  }
}

async function loginRemoteApiKey() {
  const connection = apiKeyDialogConnection.value
  const apiKey = apiKeyDraft.value.trim()
  if (!connection || !apiKey) {
    remoteError.value = 'API key is required.'
    return
  }
  apiKeySaving.value = true
  remoteError.value = ''
  try {
    const result = await apiPost<CodexRemoteConnectionTestResponse>(
      `/api/codex/remote-connections/${encodeURIComponent(connection.id)}/login-api-key`,
      { apiKey },
    )
    remoteError.value = result.ok ? result.detail : result.detail
    closeApiKeyDialog()
    emit('remoteConnectionChanged')
  } catch (error) {
    remoteError.value = error instanceof Error ? error.message : String(error)
  } finally {
    apiKeySaving.value = false
  }
}

async function deleteRemoteConnection(connection: CodexRemoteConnection) {
  remoteError.value = ''
  try {
    await apiPost(`/api/codex/remote-connections/${encodeURIComponent(connection.id)}/delete`, {})
    emit('remoteConnectionChanged')
  } catch (error) {
    remoteError.value = error instanceof Error ? error.message : String(error)
  }
}
</script>

<template>
  <section class="grid gap-4">
    <div
      class="flex items-center justify-between gap-3 border-b border-[color:var(--app-border)] pb-3"
    >
      <div class="min-w-0">
        <h2 class="m-0 text-base font-semibold text-[color:var(--app-text)]">
          Remote environments
        </h2>
        <p class="m-0 mt-1 text-sm text-[color:var(--app-text-soft)]">
          Connect to projects over SSH.
        </p>
      </div>
      <Button
        icon="pi pi-plus"
        severity="secondary"
        text
        rounded
        size="small"
        aria-label="Add SSH connection"
        data-codex-add-remote
        :disabled="busy"
        @click="openAddRemoteDialog"
      />
    </div>

    <div class="grid gap-2">
      <div
        v-for="connection in remoteConnections"
        :key="connection.id"
        class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md border border-[color:var(--app-border)] bg-white px-3 py-2.5"
        data-codex-remote-row
      >
        <div class="min-w-0">
          <span class="block truncate text-sm font-semibold text-[color:var(--app-text)]">
            {{ remoteTitle(connection) }}
          </span>
          <span class="block truncate text-[0.68rem] text-[color:var(--app-text-soft)]">
            {{ remoteSubtitle(connection) }}
          </span>
          <span
            class="mt-1 inline-flex max-w-full items-center rounded px-1.5 py-0.5 text-[0.62rem] font-semibold"
            :class="remoteStatusClass(connection)"
            :title="remoteStatus(connection).detail"
            data-codex-remote-runtime-status
          >
            {{ remoteStatusLabel(connection) }}
          </span>
        </div>
        <div class="flex items-center gap-0.5">
          <Button
            icon="pi pi-refresh"
            severity="secondary"
            text
            rounded
            size="small"
            class="!h-6 !w-6 !min-w-6 !p-0 !text-[0.68rem]"
            aria-label="Restart SSH connection"
            data-codex-restart-remote
            :disabled="busy"
            @click.stop="restartRemoteConnection(connection)"
          />
          <Button
            icon="pi pi-download"
            severity="secondary"
            text
            rounded
            size="small"
            class="!h-6 !w-6 !min-w-6 !p-0 !text-[0.68rem]"
            aria-label="Install Codex on remote"
            data-codex-install-remote
            :loading="remoteInstallingId === connection.id"
            :disabled="busy"
            @click.stop="installRemoteCodex(connection)"
          />
          <Button
            icon="pi pi-key"
            severity="secondary"
            text
            rounded
            size="small"
            class="!h-6 !w-6 !min-w-6 !p-0 !text-[0.68rem]"
            aria-label="Sign in with API key"
            data-codex-login-api-key-remote
            :disabled="busy"
            @click.stop="openApiKeyDialog(connection)"
          />
          <Button
            icon="pi pi-verified"
            severity="secondary"
            text
            rounded
            size="small"
            class="!h-6 !w-6 !min-w-6 !p-0 !text-[0.68rem]"
            aria-label="Test SSH connection"
            data-codex-test-remote
            :loading="remoteTestingId === connection.id"
            :disabled="busy"
            @click.stop="testRemoteConnection(connection)"
          />
          <Button
            icon="pi pi-pencil"
            severity="secondary"
            text
            rounded
            size="small"
            class="!h-6 !w-6 !min-w-6 !p-0 !text-[0.68rem]"
            aria-label="Edit SSH connection"
            data-codex-edit-remote
            :disabled="busy"
            @click.stop="openEditRemoteDialog(connection)"
          />
          <Button
            icon="pi pi-trash"
            severity="secondary"
            text
            rounded
            size="small"
            class="!h-6 !w-6 !min-w-6 !p-0 !text-[0.68rem]"
            aria-label="Delete SSH connection"
            data-codex-delete-remote
            :disabled="busy"
            @click.stop="deleteRemoteConnection(connection)"
          />
        </div>
      </div>
    </div>

    <p
      v-if="remoteError"
      class="m-0 mt-2 line-clamp-2 text-[0.72rem] text-[color:var(--app-text-soft)]"
      data-codex-remote-status
    >
      {{ remoteError }}
    </p>
  </section>

  <Dialog
    v-model:visible="remoteDialogVisible"
    modal
    :header="remoteEditingId ? 'Edit SSH connection' : 'Add SSH connection'"
    class="w-[min(30rem,calc(100vw-2rem))]"
    :draggable="false"
    data-codex-remote-dialog
  >
    <div class="grid gap-3">
      <label class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
        Display name
        <InputText v-model="remoteDraft.display_name" data-codex-remote-display-name />
      </label>
      <div class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
        <span>Connection method</span>
        <SelectButton
          :model-value="remoteConnectionMode"
          :options="remoteConnectionModeOptions"
          option-label="label"
          option-value="value"
          :allow-empty="false"
          fluid
          data-codex-remote-connection-mode
          @update:model-value="setRemoteConnectionMode"
        />
      </div>
      <template v-if="remoteConnectionMode === 'direct'">
        <label class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
          Host
          <InputText
            v-model="remoteDraft.ssh_host"
            placeholder="100.64.0.93 or server.example.com"
            data-codex-remote-host
          />
        </label>
        <div class="grid grid-cols-[minmax(0,1fr)_7rem] gap-2">
          <label class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
            Username
            <InputText
              v-model="remoteDraft.ssh_username"
              placeholder="optional"
              data-codex-remote-username
            />
          </label>
          <label class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
            Port
            <InputText v-model="remotePortDraft" placeholder="22" data-codex-remote-port />
          </label>
        </div>
        <div class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
          <label for="codex-remote-identity">Identity file</label>
          <span class="flex min-w-0 gap-2">
            <InputText
              id="codex-remote-identity"
              v-model="remoteDraft.identity_file"
              class="min-w-0 flex-1"
              placeholder="~/.ssh/id_ed25519"
              data-codex-remote-identity
            />
            <Button
              icon="pi pi-folder-open"
              severity="secondary"
              outlined
              aria-label="Choose SSH identity file"
              title="Choose SSH identity file"
              data-codex-browse-remote-identity
              @click="identityFilePickerVisible = true"
            />
          </span>
        </div>
      </template>
      <label v-else class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
        SSH config alias
        <InputText
          v-model="remoteDraft.ssh_alias"
          placeholder="Host name from ~/.ssh/config"
          data-codex-remote-alias
        />
      </label>
      <label class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
        Remote path
        <InputText v-model="remoteDraft.remote_path" data-codex-remote-path />
      </label>
      <p v-if="remoteError" class="m-0 text-sm text-red-700" data-codex-remote-dialog-error>
        {{ remoteError }}
      </p>
      <footer class="mt-1 flex justify-end gap-2">
        <Button label="Cancel" severity="secondary" outlined @click="closeRemoteDialog" />
        <Button
          label="Save"
          icon="pi pi-save"
          data-codex-save-remote
          :loading="remoteSaving"
          @click="saveRemoteConnection"
        />
      </footer>
    </div>
  </Dialog>

  <CodexHostPathPicker
    v-model:visible="identityFilePickerVisible"
    title="Choose SSH identity file"
    :selected-path="identityFilePickerPath"
    :disabled="remoteSaving"
    allow-files
    :allow-current-folder="false"
    data-codex-identity-file-picker
    @select="selectIdentityFile"
  />

  <Dialog
    :visible="Boolean(apiKeyDialogConnection)"
    modal
    :header="apiKeyDialogTitle"
    class="w-[min(30rem,calc(100vw-2rem))]"
    :draggable="false"
    data-codex-remote-api-key-dialog
    @update:visible="!$event && closeApiKeyDialog()"
  >
    <div class="grid gap-3">
      <label class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
        API key
        <InputText
          v-model="apiKeyDraft"
          type="password"
          autocomplete="off"
          data-codex-remote-api-key
          @keydown.enter.prevent="loginRemoteApiKey"
        />
      </label>
      <p v-if="remoteError" class="m-0 text-sm text-red-700" data-codex-remote-api-key-error>
        {{ remoteError }}
      </p>
      <footer class="mt-1 flex justify-end gap-2">
        <Button label="Cancel" severity="secondary" outlined @click="closeApiKeyDialog" />
        <Button
          label="Sign in"
          icon="pi pi-key"
          data-codex-remote-api-key-submit
          :loading="apiKeySaving"
          @click="loginRemoteApiKey"
        />
      </footer>
    </div>
  </Dialog>
</template>
