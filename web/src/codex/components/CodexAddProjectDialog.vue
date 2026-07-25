<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Message from 'primevue/message'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'

import { apiPost } from '../../lib/api'
import type { CodexProjectPayload, CodexRemoteConnection, CodexWorkspaceResponse } from '../types'
import CodexHostPathPicker from './CodexHostPathPicker.vue'

const visible = defineModel<boolean>('visible', { required: true })

const props = defineProps<{
  workspace: CodexWorkspaceResponse
  disabled?: boolean
}>()

const emit = defineEmits<{
  projectChanged: []
}>()

type ProjectKind = CodexProjectPayload['kind']

const kind = ref<ProjectKind>('local')
const connectionId = ref('')
const projectPath = ref('')
const pathPickerVisible = ref(false)
const saving = ref(false)
const errorMessage = ref('')

const kindOptions = [
  { label: 'Local', value: 'local', icon: 'pi pi-desktop' },
  { label: 'Remote', value: 'remote', icon: 'pi pi-globe' },
]

const remoteConnections = computed(() => props.workspace.remote_connections ?? [])
const connectionOptions = computed(() =>
  remoteConnections.value.map((connection) => ({
    label: remoteTitle(connection),
    value: connection.id,
  })),
)
const selectedConnection = computed(() =>
  remoteConnections.value.find((connection) => connection.id === connectionId.value),
)
const selectedHostId = computed(() =>
  kind.value === 'remote' && connectionId.value ? `ssh:${connectionId.value}` : 'local',
)
const canBrowse = computed(() => kind.value === 'local' || Boolean(selectedConnection.value))
const canSave = computed(() => Boolean(projectPath.value.trim()) && canBrowse.value)

watch(visible, (isVisible) => {
  if (!isVisible) {
    return
  }
  kind.value = 'local'
  connectionId.value = ''
  projectPath.value = ''
  errorMessage.value = ''
})

watch(kind, () => {
  projectPath.value = ''
  errorMessage.value = ''
})

watch(selectedConnection, (connection) => {
  if (kind.value === 'remote') {
    projectPath.value = connection?.remote_path || ''
  }
})

function remoteTitle(connection: CodexRemoteConnection) {
  return connection.display_name || connection.ssh_alias || connection.ssh_host
}

function openPathPicker() {
  if (!canBrowse.value) {
    errorMessage.value = 'Choose an SSH connection first.'
    return
  }
  errorMessage.value = ''
  pathPickerVisible.value = true
}

function selectProjectPath(path: string) {
  projectPath.value = path.trim()
  pathPickerVisible.value = false
}

async function saveProject() {
  if (!canSave.value || saving.value) {
    return
  }
  saving.value = true
  errorMessage.value = ''
  try {
    await apiPost('/api/codex/projects', {
      name: '',
      kind: kind.value,
      host_id: selectedHostId.value,
      project_path: projectPath.value.trim(),
    } satisfies CodexProjectPayload)
    visible.value = false
    emit('projectChanged')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    header="Add project"
    class="w-[min(32rem,calc(100vw-2rem))]"
    :draggable="false"
    data-codex-add-project-dialog
  >
    <div class="grid gap-4">
      <SelectButton
        v-model="kind"
        :options="kindOptions"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        fluid
        data-codex-project-kind
      >
        <template #option="slotProps">
          <span class="inline-flex items-center gap-2">
            <i :class="slotProps.option.icon"></i>
            <span>{{ slotProps.option.label }}</span>
          </span>
        </template>
      </SelectButton>

      <label
        v-if="kind === 'remote'"
        class="grid gap-1.5 text-sm font-medium text-[color:var(--app-text)]"
      >
        SSH connection
        <Select
          v-model="connectionId"
          :options="connectionOptions"
          option-label="label"
          option-value="value"
          placeholder="Choose a connection"
          fluid
          data-codex-project-connection
        />
      </label>

      <div class="grid gap-1.5 text-sm font-medium text-[color:var(--app-text)]">
        <span>Project folder</span>
        <button
          type="button"
          class="grid min-h-11 min-w-0 grid-cols-[1.25rem_minmax(0,1fr)_1rem] items-center gap-2 rounded-md border border-[color:var(--app-border)] bg-white px-3 text-left transition hover:border-[color:var(--app-accent)] disabled:cursor-not-allowed disabled:opacity-55"
          :disabled="disabled || !canBrowse"
          data-codex-project-browse
          @click="openPathPicker"
        >
          <i class="pi pi-folder-open text-[color:var(--app-text-soft)]"></i>
          <span
            class="truncate text-sm"
            :class="
              projectPath ? 'text-[color:var(--app-text)]' : 'text-[color:var(--app-text-soft)]'
            "
          >
            {{ projectPath || 'Choose a folder' }}
          </span>
          <i class="pi pi-chevron-right text-xs text-[color:var(--app-text-soft)]"></i>
        </button>
      </div>

      <Message v-if="errorMessage" severity="error" :closable="false">
        {{ errorMessage }}
      </Message>
    </div>

    <template #footer>
      <Button label="Cancel" severity="secondary" text @click="visible = false" />
      <Button
        label="Add project"
        icon="pi pi-plus"
        :loading="saving"
        :disabled="disabled || !canSave"
        data-codex-project-save
        @click="saveProject"
      />
    </template>
  </Dialog>

  <CodexHostPathPicker
    v-model:visible="pathPickerVisible"
    :host-id="selectedHostId"
    :selected-path="projectPath || selectedConnection?.remote_path"
    :title="kind === 'remote' ? 'Choose remote project folder' : 'Choose project folder'"
    :disabled="disabled || saving"
    @select="selectProjectPath"
  />
</template>
