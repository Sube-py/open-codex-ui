<script setup lang="ts">
import { ref } from 'vue'

import Dialog from 'primevue/dialog'
import SelectButton from 'primevue/selectbutton'

import {
  setColorScheme,
  useColorScheme,
  type ColorSchemePreference,
} from '../../composables/useColorScheme'
import type { CodexWorkspaceResponse } from '../types'
import CodexAuthenticationSettings from './CodexAuthenticationSettings.vue'
import CodexRemoteConnections from './CodexRemoteConnections.vue'
import CodexSpeechSettings from './CodexSpeechSettings.vue'

const visible = defineModel<boolean>('visible', { required: true })
const activeSection = ref<'appearance' | 'connections' | 'authentication' | 'speech'>('connections')
const { colorScheme } = useColorScheme()
const themeOptions: Array<{
  label: string
  value: ColorSchemePreference
  icon: string
}> = [
  { label: 'System', value: 'system', icon: 'pi pi-desktop' },
  { label: 'Light', value: 'light', icon: 'pi pi-sun' },
  { label: 'Dark', value: 'dark', icon: 'pi pi-moon' },
]

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
        class="flex flex-col gap-1 border-r border-[color:var(--app-border)] bg-[color:var(--app-surface-muted)] p-3 max-sm:flex-row max-sm:border-b max-sm:border-r-0"
        aria-label="Settings sections"
      >
        <button
          type="button"
          class="flex min-w-0 items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-semibold text-[color:var(--app-text)] transition hover:bg-[color:var(--app-hover)] max-sm:flex-1"
          :class="activeSection === 'appearance' ? 'bg-[color:var(--app-selected)]' : ''"
          :aria-current="activeSection === 'appearance' ? 'page' : undefined"
          data-codex-settings-appearance
          @click="activeSection = 'appearance'"
        >
          <i class="pi pi-palette text-xs"></i>
          <span>Appearance</span>
        </button>
        <button
          type="button"
          class="flex min-w-0 items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-semibold text-[color:var(--app-text)] transition hover:bg-[color:var(--app-hover)] max-sm:flex-1"
          :class="activeSection === 'connections' ? 'bg-[color:var(--app-selected)]' : ''"
          :aria-current="activeSection === 'connections' ? 'page' : undefined"
          data-codex-settings-connections
          @click="activeSection = 'connections'"
        >
          <i class="pi pi-server text-xs"></i>
          <span>Connections</span>
        </button>
        <button
          type="button"
          class="flex min-w-0 items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-semibold text-[color:var(--app-text)] transition hover:bg-[color:var(--app-hover)] max-sm:flex-1"
          :class="activeSection === 'authentication' ? 'bg-[color:var(--app-selected)]' : ''"
          :aria-current="activeSection === 'authentication' ? 'page' : undefined"
          data-codex-settings-authentication
          @click="activeSection = 'authentication'"
        >
          <i class="pi pi-lock text-xs"></i>
          <span>Access</span>
        </button>
        <button
          type="button"
          class="flex min-w-0 items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-semibold text-[color:var(--app-text)] transition hover:bg-[color:var(--app-hover)] max-sm:flex-1"
          :class="activeSection === 'speech' ? 'bg-[color:var(--app-selected)]' : ''"
          :aria-current="activeSection === 'speech' ? 'page' : undefined"
          data-codex-settings-speech
          @click="activeSection = 'speech'"
        >
          <i class="pi pi-microphone text-xs"></i>
          <span>Voice</span>
        </button>
      </nav>

      <div class="min-h-0 overflow-y-auto p-5 max-sm:p-4">
        <section
          v-if="activeSection === 'appearance'"
          class="grid gap-5"
          data-codex-appearance-settings
        >
          <div class="border-b border-[color:var(--app-border)] pb-3">
            <h2 class="m-0 text-base font-semibold text-[color:var(--app-text)]">Appearance</h2>
          </div>
          <div class="grid gap-2">
            <label class="text-sm font-semibold text-[color:var(--app-text)]">Color theme</label>
            <SelectButton
              :model-value="colorScheme"
              :options="themeOptions"
              option-label="label"
              option-value="value"
              :allow-empty="false"
              class="w-fit max-w-full"
              data-codex-color-scheme
              @update:model-value="setColorScheme($event as ColorSchemePreference)"
            >
              <template #option="slotProps">
                <span class="inline-flex items-center gap-2">
                  <i :class="slotProps.option.icon"></i>
                  <span>{{ slotProps.option.label }}</span>
                </span>
              </template>
            </SelectButton>
          </div>
        </section>
        <CodexRemoteConnections
          v-else-if="activeSection === 'connections'"
          :workspace="workspace"
          :busy="busy"
          @remote-connection-changed="emit('remoteConnectionChanged')"
        />
        <CodexAuthenticationSettings v-else-if="activeSection === 'authentication'" :busy="busy" />
        <CodexSpeechSettings v-else :busy="busy" />
      </div>
    </div>
  </Dialog>
</template>
