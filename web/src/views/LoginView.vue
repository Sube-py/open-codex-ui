<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Button from 'primevue/button'
import Message from 'primevue/message'
import Password from 'primevue/password'

import { ApiError, apiGet, apiPost } from '../lib/api'
import type { AuthLoginRequest, AuthSessionResponse } from '../types/api'

const route = useRoute()
const router = useRouter()

const password = ref('')
const errorMessage = ref('')
const isCheckingSession = ref(true)
const isSubmitting = ref(false)

const nextPath = computed(() => {
  const rawNext = typeof route.query.next === 'string' ? route.query.next : ''
  if (!rawNext.startsWith('/') || rawNext.startsWith('//') || rawNext.startsWith('/login')) {
    return '/codex'
  }
  return rawNext
})

async function syncSessionState() {
  const session = await apiGet<AuthSessionResponse>('/api/auth/session')
  if (!session.enabled || session.authenticated) {
    await router.replace(nextPath.value)
  }
}

async function submitLogin() {
  errorMessage.value = ''
  isSubmitting.value = true

  try {
    await apiPost<AuthSessionResponse>('/api/auth/login', {
      password: password.value,
    } satisfies AuthLoginRequest)
    await router.replace(nextPath.value)
  } catch (error) {
    if (error instanceof ApiError || error instanceof Error) {
      errorMessage.value = error.message
    } else {
      errorMessage.value = 'Unable to sign in right now.'
    }
  } finally {
    isSubmitting.value = false
  }
}

onMounted(async () => {
  try {
    await syncSessionState()
  } catch (error) {
    if (error instanceof Error) {
      errorMessage.value = error.message
    }
  } finally {
    isCheckingSession.value = false
  }
})
</script>

<template>
  <main
    class="relative min-h-screen overflow-hidden bg-[color:var(--app-bg)] px-4 py-6 text-[color:var(--app-text)] sm:px-6 lg:px-8"
  >
    <div
      class="relative mx-auto flex min-h-[calc(100vh-3rem)] max-w-5xl items-center justify-center"
    >
      <section
        class="grid w-full max-w-4xl overflow-hidden rounded-[2rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] shadow-[var(--app-shadow)] backdrop-blur-[16px] lg:grid-cols-[minmax(0,1.2fr)_minmax(22rem,26rem)]"
      >
        <div class="flex flex-col justify-between gap-8 px-6 py-8 sm:px-8 sm:py-10">
          <div class="space-y-5">
            <p
              class="m-0 text-[0.76rem] font-bold uppercase tracking-[0.22em] text-[color:var(--app-accent-deep)]"
            >
              Protected Workspace
            </p>
            <div class="space-y-3">
              <h1
                class="m-0 font-['Iowan_Old_Style','Palatino_Linotype',Palatino,serif] text-[clamp(2.2rem,4vw,3.8rem)] leading-[0.94] font-semibold text-[color:var(--app-text)]"
              >
                Sign in before
                <br />
                the console wakes up.
              </h1>
              <p
                class="m-0 max-w-[34rem] text-[1rem] leading-[1.75] text-[color:var(--app-text-soft)]"
              >
                This deployment is protected with a shared access password. Enter it once and the
                browser will keep a secure session cookie for the app.
              </p>
            </div>
          </div>

          <div
            class="grid gap-3 rounded-[1.5rem] border border-[color:var(--app-border)] bg-[color:var(--app-surface-translucent)] p-4 text-[0.95rem] text-[color:var(--app-text-soft)]"
          >
            <div class="flex items-center gap-3">
              <span
                class="inline-flex h-10 w-10 items-center justify-center rounded-full bg-[rgba(18,126,129,0.12)] text-[color:var(--app-accent-deep)]"
              >
                <i class="pi pi-shield text-[1rem]"></i>
              </span>
              <div>
                <p class="m-0 font-semibold text-[color:var(--app-text)]">Server-side protection</p>
                <p class="m-0">API routes, SSE streams, and workspace pages all require login.</p>
              </div>
            </div>
          </div>
        </div>

        <div
          class="border-t border-[color:var(--app-border)] bg-[color:var(--app-surface-muted)] px-6 py-8 sm:px-8 sm:py-10 lg:border-t-0 lg:border-l"
        >
          <form class="flex h-full flex-col justify-center gap-5" @submit.prevent="submitLogin">
            <div class="space-y-2">
              <p
                class="m-0 text-[0.8rem] font-bold uppercase tracking-[0.2em] text-[color:var(--app-text-soft)]"
              >
                Access
              </p>
              <h2 class="m-0 text-[1.7rem] font-semibold text-[color:var(--app-text)]">
                Unlock Yier
              </h2>
              <p class="m-0 text-[0.96rem] leading-[1.7] text-[color:var(--app-text-soft)]">
                Use the deployment password configured on the server.
              </p>
            </div>

            <Message v-if="errorMessage" severity="error" class="m-0">
              {{ errorMessage }}
            </Message>

            <div class="grid gap-2">
              <label
                for="login-password"
                class="text-[0.9rem] font-semibold text-[color:var(--app-text-soft)]"
              >
                Password
              </label>
              <Password
                id="login-password"
                v-model="password"
                fluid
                toggle-mask
                :feedback="false"
                :disabled="isCheckingSession || isSubmitting"
                placeholder="Enter deployment password"
                input-class="w-full"
              />
            </div>

            <Button
              type="submit"
              label="Sign In"
              icon="pi pi-lock-open"
              :loading="isSubmitting || isCheckingSession"
              :disabled="isCheckingSession || !password.trim()"
            />
          </form>
        </div>
      </section>
    </div>
  </main>
</template>
