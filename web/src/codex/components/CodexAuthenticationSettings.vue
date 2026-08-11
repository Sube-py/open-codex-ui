<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Message from 'primevue/message'
import ToggleSwitch from 'primevue/toggleswitch'

import { apiGet, apiPut } from '../../lib/api'
import type { AuthConfigResponse, SaveAuthConfigRequest } from '../../types/api'

const props = defineProps<{
  busy?: boolean
}>()

const authConfig = ref<AuthConfigResponse | null>(null)
const enabled = ref(false)
const password = ref('')
const secret = ref('')
const sessionTtlHours = ref(168)
const isLoading = ref(true)
const isSaving = ref(false)
const secretTouched = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const passwordManagedByEnvironment = computed(
  () => authConfig.value?.password_source === 'environment',
)
const secretManagedByEnvironment = computed(
  () => authConfig.value?.secret_source === 'environment',
)
const ttlManagedByEnvironment = computed(
  () => authConfig.value?.session_ttl_source === 'environment',
)
const isBusy = computed(() => props.busy || isLoading.value || isSaving.value)

function passwordPlaceholder() {
  if (passwordManagedByEnvironment.value) {
    return 'Managed by environment'
  }
  return authConfig.value?.has_password ? 'Configured' : 'Enter password'
}

function secretPlaceholder() {
  if (secretManagedByEnvironment.value) {
    return 'Managed by environment'
  }
  return authConfig.value?.has_secret ? 'Configured' : 'Optional'
}

function resetDraft(config: AuthConfigResponse) {
  authConfig.value = config
  enabled.value = config.enabled
  password.value = ''
  secret.value = ''
  sessionTtlHours.value = config.session_ttl_hours
  secretTouched.value = false
}

async function loadAuthConfig() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    resetDraft(await apiGet<AuthConfigResponse>('/api/config/auth'))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    isLoading.value = false
  }
}

function markSecretTouched(value: string | undefined) {
  secret.value = value ?? ''
  secretTouched.value = true
}

async function saveAuthConfig() {
  errorMessage.value = ''
  successMessage.value = ''
  if (!authConfig.value) {
    return
  }
  if (enabled.value && !authConfig.value.has_password && !password.value.trim()) {
    errorMessage.value = 'A password is required to enable authentication.'
    return
  }

  isSaving.value = true
  const payload = {
    enabled: enabled.value,
    password: password.value.trim() || null,
    secret: secretTouched.value ? secret.value.trim() : null,
    session_ttl_hours: sessionTtlHours.value,
  } satisfies SaveAuthConfigRequest
  try {
    resetDraft(await apiPut<AuthConfigResponse>('/api/config/auth', payload))
    successMessage.value = 'Authentication settings saved.'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    isSaving.value = false
  }
}

onMounted(() => {
  void loadAuthConfig()
})
</script>

<template>
  <section class="grid gap-5" data-codex-auth-settings>
    <div class="flex items-center justify-between gap-3 border-b border-[color:var(--app-border)] pb-3">
      <h2 class="m-0 text-base font-semibold text-[color:var(--app-text)]">Authentication</h2>
      <span
        class="shrink-0 rounded px-1.5 py-0.5 text-[0.68rem] font-semibold"
        :class="
          enabled
            ? 'bg-[color:var(--app-success-bg)] text-[color:var(--app-success-text)]'
            : 'bg-[color:var(--app-neutral-status-bg)] text-[color:var(--app-neutral-status-text)]'
        "
      >
        {{ enabled ? 'Enabled' : 'Disabled' }}
      </span>
    </div>

    <Message v-if="errorMessage" severity="error" :closable="false" data-codex-auth-error>
      {{ errorMessage }}
    </Message>
    <Message v-if="successMessage" severity="success" :closable="false" data-codex-auth-success>
      {{ successMessage }}
    </Message>

    <div class="grid gap-2">
      <div class="flex items-center justify-between gap-3">
        <label for="codex-auth-enabled" class="text-sm font-semibold text-[color:var(--app-text)]">
          Require sign in
        </label>
        <span
          v-if="passwordManagedByEnvironment"
          class="rounded bg-[color:var(--app-neutral-status-bg)] px-1.5 py-0.5 text-[0.68rem] font-semibold text-[color:var(--app-neutral-status-text)]"
        >
          Environment
        </span>
      </div>
      <ToggleSwitch
        v-model="enabled"
        input-id="codex-auth-enabled"
        :disabled="isBusy || passwordManagedByEnvironment"
        data-codex-auth-enabled
      />
    </div>

    <div class="grid gap-2">
      <div class="flex items-center justify-between gap-3">
        <label for="codex-auth-password" class="text-sm font-semibold text-[color:var(--app-text)]">
          Password
        </label>
        <span
          v-if="passwordManagedByEnvironment"
          class="rounded bg-[color:var(--app-neutral-status-bg)] px-1.5 py-0.5 text-[0.68rem] font-semibold text-[color:var(--app-neutral-status-text)]"
        >
          Environment
        </span>
      </div>
      <InputText
        id="codex-auth-password"
        v-model="password"
        type="password"
        class="w-full"
        :placeholder="passwordPlaceholder()"
        :disabled="isBusy || passwordManagedByEnvironment"
        autocomplete="new-password"
        data-codex-auth-password
      />
    </div>

    <div class="grid gap-2">
      <div class="flex items-center justify-between gap-3">
        <label for="codex-auth-secret" class="text-sm font-semibold text-[color:var(--app-text)]">
          Session signing secret
        </label>
        <span
          v-if="secretManagedByEnvironment"
          class="rounded bg-[color:var(--app-neutral-status-bg)] px-1.5 py-0.5 text-[0.68rem] font-semibold text-[color:var(--app-neutral-status-text)]"
        >
          Environment
        </span>
      </div>
      <InputText
        id="codex-auth-secret"
        :model-value="secret"
        type="password"
        class="w-full"
        :placeholder="secretPlaceholder()"
        :disabled="isBusy || secretManagedByEnvironment"
        autocomplete="new-password"
        data-codex-auth-secret
        @update:model-value="markSecretTouched"
      />
    </div>

    <div class="grid gap-2">
      <div class="flex items-center justify-between gap-3">
        <label for="codex-auth-ttl" class="text-sm font-semibold text-[color:var(--app-text)]">
          Session duration (hours)
        </label>
        <span
          v-if="ttlManagedByEnvironment"
          class="rounded bg-[color:var(--app-neutral-status-bg)] px-1.5 py-0.5 text-[0.68rem] font-semibold text-[color:var(--app-neutral-status-text)]"
        >
          Environment
        </span>
      </div>
      <input
        id="codex-auth-ttl"
        v-model.number="sessionTtlHours"
        type="number"
        min="1"
        step="1"
        class="h-10 w-full rounded-md border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-3 text-sm text-[color:var(--app-text)] outline-none transition focus:border-[color:var(--app-focus)] disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="isBusy || ttlManagedByEnvironment"
        data-codex-auth-ttl
      />
    </div>

    <div class="flex justify-end">
      <Button
        label="Save"
        icon="pi pi-save"
        :loading="isSaving"
        :disabled="isBusy || !authConfig"
        data-codex-save-auth
        @click="saveAuthConfig"
      />
    </div>
  </section>
</template>
