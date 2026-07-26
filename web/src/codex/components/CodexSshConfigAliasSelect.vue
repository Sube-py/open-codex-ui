<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from 'primevue/button'
import Select from 'primevue/select'

import { apiGet } from '../../lib/api'
import type { CodexSshConfigHost, CodexSshConfigHostsResponse } from '../types'

const alias = defineModel<string>({ required: true })

const hosts = ref<CodexSshConfigHost[]>([])
const loading = ref(false)
const errorMessage = ref('')

const options = computed(() => {
  if (!alias.value || hosts.value.some((host) => host.alias === alias.value)) {
    return hosts.value
  }
  return [
    ...hosts.value,
    {
      alias: alias.value,
      hostname: '',
      port: null,
      identity_file: '',
    },
  ]
})

onMounted(() => loadHosts())

async function loadHosts() {
  if (loading.value) {
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await apiGet<CodexSshConfigHostsResponse>('/api/codex/ssh-config-hosts')
    hosts.value = response.hosts
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to read ~/.ssh/config.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="grid gap-1 text-sm font-medium text-[color:var(--app-text)]">
    <label for="codex-remote-alias">SSH config alias</label>
    <span class="flex min-w-0 gap-2">
      <Select
        id="codex-remote-alias"
        v-model="alias"
        :options="options"
        option-label="alias"
        option-value="alias"
        placeholder="Choose a host from ~/.ssh/config"
        empty-message="No concrete hosts found in ~/.ssh/config"
        :loading="loading"
        class="min-w-0 flex-1"
        fluid
        data-codex-remote-alias
      >
        <template #option="{ option }">
          <span class="grid min-w-0 gap-0.5">
            <span class="truncate">{{ option.alias }}</span>
            <span v-if="option.hostname" class="truncate text-xs text-[color:var(--app-text-soft)]">
              {{ option.hostname }}<template v-if="option.port">:{{ option.port }}</template>
            </span>
          </span>
        </template>
      </Select>
      <Button
        v-tooltip.top="'Reload hosts from ~/.ssh/config'"
        icon="pi pi-refresh"
        severity="secondary"
        outlined
        aria-label="Refresh SSH config hosts"
        title="Refresh SSH config hosts"
        :loading="loading"
        data-codex-refresh-ssh-config
        @click="loadHosts"
      />
    </span>
    <small v-if="errorMessage" class="text-[color:var(--app-danger-text)]">
      {{ errorMessage }}
    </small>
  </div>
</template>
