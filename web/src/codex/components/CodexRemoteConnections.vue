<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'

import { apiPost, apiPut } from '../../lib/api'
import type {
  CodexRemoteConnection,
  CodexRemoteConnectionAutoConnectPayload,
  CodexRemoteConnectionPayload,
  CodexRemoteConnectionResponse,
  CodexRemoteConnectionTestResponse,
  CodexWorkspaceResponse,
} from '../types'
import CodexHostPathPicker from './CodexHostPathPicker.vue'
import CodexSshConfigAliasSelect from './CodexSshConfigAliasSelect.vue'

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
const remoteTogglingId = ref('')
const remoteAutoConnectOverrides = ref<Record<string, boolean>>({})
const remoteSaving = ref(false)
const remoteEditingId = ref('')
const remoteDraft = ref<CodexRemoteConnectionPayload>(emptyRemoteDraft())
const remotePortDraft = ref('')
const remoteConnectionModeOptions = [
  { label: 'Direct SSH', value: 'direct' },
  { label: 'SSH config alias', value: 'alias' },
]

const remoteConnections = computed(() => props.workspace.remote_connections ?? [])
const remoteStatuses = computed(() => props.workspace.remote_connection_statuses ?? {})
const identityFilePickerPath = computed(
  () => parentDirectory(remoteDraft.value.identity_file) || '~/.ssh',
)

watch(remoteConnections, (connections) => {
  const overrides = { ...remoteAutoConnectOverrides.value }
  let changed = false
  for (const connection of connections) {
    if (overrides[connection.id] !== connection.auto_connect) {
      continue
    }
    delete overrides[connection.id]
    changed = true
  }
  if (changed) {
    remoteAutoConnectOverrides.value = overrides
  }
})

function emptyRemoteDraft(): CodexRemoteConnectionPayload {
  return {
    display_name: '',
    ssh_host: '',
    ssh_username: '',
    ssh_port: null,
    ssh_alias: '',
    identity_file: '',
    auto_connect: false,
  }
}

function remoteTitle(connection: CodexRemoteConnection) {
  return connection.display_name || connection.ssh_alias || connection.ssh_host
}

function remoteSubtitle(connection: CodexRemoteConnection) {
  const target = connection.ssh_alias || directTarget(connection)
  const port = connection.ssh_alias || !connection.ssh_port ? '' : `:${connection.ssh_port}`
  return `${target}${port}`
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
    return 'bg-[color:var(--app-success-bg)] text-[color:var(--app-success-text)]'
  }
  if (status === 'connecting') {
    return 'bg-[color:var(--app-warning-bg)] text-[color:var(--app-warning-text)]'
  }
  if (status === 'error') {
    return 'bg-[color:var(--app-danger-bg)] text-[color:var(--app-danger-text)]'
  }
  return 'bg-[color:var(--app-neutral-status-bg)] text-[color:var(--app-neutral-status-text)]'
}

function remoteAutoConnect(connection: CodexRemoteConnection) {
  return remoteAutoConnectOverrides.value[connection.id] ?? connection.auto_connect
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

async function toggleRemoteConnection(connection: CodexRemoteConnection, autoConnect: boolean) {
  remoteTogglingId.value = connection.id
  remoteAutoConnectOverrides.value = {
    ...remoteAutoConnectOverrides.value,
    [connection.id]: autoConnect,
  }
  remoteError.value = ''
  try {
    const payload = {
      auto_connect: autoConnect,
    } satisfies CodexRemoteConnectionAutoConnectPayload
    await apiPut<CodexRemoteConnectionResponse>(
      `/api/codex/remote-connections/${encodeURIComponent(connection.id)}/auto-connect`,
      payload,
    )
    emit('remoteConnectionChanged')
  } catch (error) {
    const overrides = { ...remoteAutoConnectOverrides.value }
    delete overrides[connection.id]
    remoteAutoConnectOverrides.value = overrides
    remoteError.value = error instanceof Error ? error.message : String(error)
  } finally {
    remoteTogglingId.value = ''
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
        v-tooltip.left="'Add an SSH server connection'"
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
        class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-3 py-2.5 max-sm:grid-cols-1"
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
        <div class="flex items-center justify-end gap-0.5">
          <ToggleSwitch
            v-tooltip.top="
              remoteAutoConnect(connection)
                ? 'Disconnect this SSH server'
                : 'Connect to this SSH server'
            "
            :model-value="remoteAutoConnect(connection)"
            :disabled="busy || remoteTogglingId === connection.id"
            :aria-label="`${remoteAutoConnect(connection) ? 'Disconnect from' : 'Connect to'} ${remoteTitle(connection)}`"
            class="mr-2 shrink-0"
            data-codex-toggle-remote
            @update:model-value="toggleRemoteConnection(connection, Boolean($event))"
          />
          <Button
            v-tooltip.top="'Restart the remote Codex connection'"
            icon="pi pi-refresh"
            severity="secondary"
            text
            rounded
            size="small"
            class="!h-6 !w-6 !min-w-6 !p-0 !text-[0.68rem]"
            aria-label="Restart SSH connection"
            data-codex-restart-remote
            :disabled="busy || !remoteAutoConnect(connection)"
            @click.stop="restartRemoteConnection(connection)"
          />
          <Button
            v-tooltip.top="'Install Codex on this server'"
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
            v-tooltip.top="'Test SSH and Codex availability'"
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
            v-tooltip.top="'Edit this SSH connection'"
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
            v-tooltip.top="'Delete this SSH connection'"
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
        <label class="grid min-w-0 gap-1 text-sm font-medium text-[color:var(--app-text)]">
          Host
          <InputText
            v-model="remoteDraft.ssh_host"
            class="min-w-0 w-full"
            placeholder="server.example.com"
            data-codex-remote-host
          />
        </label>
        <div class="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(5rem,7rem)] gap-2">
          <label class="grid min-w-0 gap-1 text-sm font-medium text-[color:var(--app-text)]">
            Username
            <InputText
              v-model="remoteDraft.ssh_username"
              class="min-w-0 w-full"
              placeholder="optional"
              data-codex-remote-username
            />
          </label>
          <label class="grid min-w-0 gap-1 text-sm font-medium text-[color:var(--app-text)]">
            Port
            <InputText
              v-model="remotePortDraft"
              class="min-w-0 w-full"
              inputmode="numeric"
              placeholder="22"
              data-codex-remote-port
            />
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
              v-tooltip.top="'Choose a private key from this computer'"
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
      <CodexSshConfigAliasSelect v-else v-model="remoteDraft.ssh_alias" />
      <p
        v-if="remoteError"
        class="m-0 text-sm text-[color:var(--app-danger-text)]"
        data-codex-remote-dialog-error
      >
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
</template>
