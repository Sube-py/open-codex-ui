<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import type { CodexPendingRequest, CodexRequestQuestion, JsonRecord } from '../types'
import { compactJson } from '../lib/format'

const PLAN_IMPLEMENTATION_REQUEST_METHOD = 'item/plan/requestImplementation'

const props = defineProps<{
  request: CodexPendingRequest | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  submitResponse: [requestId: string, response: JsonRecord]
}>()

const answers = reactive<Record<string, string>>({})
const currentQuestionIndex = ref(0)
const jsonDraft = ref('{\n  "answers": {}\n}')
const validationError = ref('')
const planFeedback = ref('')
const useJsonFallback = ref(false)

const isPlanImplementationRequest = computed(
  () => props.request?.method === PLAN_IMPLEMENTATION_REQUEST_METHOD,
)
const questions = computed<CodexRequestQuestion[]>(() => {
  const rawQuestions = props.request?.params?.questions
  return Array.isArray(rawQuestions) ? rawQuestions.filter(isQuestion) : []
})
const supportsStructuredInput = computed(() => questions.value.length > 0)
const visibleAsJson = computed(
  () =>
    !isPlanImplementationRequest.value && (!supportsStructuredInput.value || useJsonFallback.value),
)
const currentQuestion = computed(() => questions.value[currentQuestionIndex.value] ?? null)
const isFirstQuestion = computed(() => currentQuestionIndex.value === 0)
const isLastQuestion = computed(() => currentQuestionIndex.value >= questions.value.length - 1)
const planContent = computed(() => {
  const value = props.request?.params?.planContent
  return typeof value === 'string' ? value : ''
})
const requestLabel = computed(() =>
  isPlanImplementationRequest.value ? 'Plan ready' : 'User input required',
)

watch(
  () => props.request?.id,
  () => {
    for (const key of Object.keys(answers)) {
      delete answers[key]
    }
    currentQuestionIndex.value = 0
    validationError.value = ''
    planFeedback.value = ''
    useJsonFallback.value = false
    jsonDraft.value = '{\n  "answers": {}\n}'
  },
)

watch(
  () => questions.value.length,
  (questionCount) => {
    if (!questionCount) {
      currentQuestionIndex.value = 0
      return
    }
    if (currentQuestionIndex.value >= questionCount) {
      currentQuestionIndex.value = questionCount - 1
    }
  },
)

function isQuestion(value: unknown): value is CodexRequestQuestion {
  return (
    Boolean(value) &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    typeof (value as CodexRequestQuestion).id === 'string' &&
    Boolean((value as CodexRequestQuestion).id)
  )
}

function questionTitle(question: CodexRequestQuestion) {
  return question.header || question.question || question.id
}

function questionPrompt(question: CodexRequestQuestion) {
  return question.question && question.question !== questionTitle(question) ? question.question : ''
}

function optionKey(question: CodexRequestQuestion, optionLabel: string) {
  return `${question.id}-${optionLabel}`
}

function answerFor(question: CodexRequestQuestion) {
  return answers[question.id] ?? ''
}

function hasAnswer(question: CodexRequestQuestion) {
  return Boolean(answerFor(question).trim())
}

function selectAnswer(question: CodexRequestQuestion, value: string) {
  answers[question.id] = value
  validationError.value = ''
}

function selectOptionAnswer(question: CodexRequestQuestion, value: string) {
  selectAnswer(question, value)
  if (question.id === currentQuestion.value?.id && !isLastQuestion.value) {
    advanceQuestion()
  }
}

function validateCurrentQuestion() {
  const question = currentQuestion.value
  if (!question) {
    return true
  }
  if (hasAnswer(question)) {
    validationError.value = ''
    return true
  }
  validationError.value = `${questionTitle(question)} is required.`
  return false
}

function advanceQuestion() {
  if (!validateCurrentQuestion() || isLastQuestion.value) {
    return
  }
  currentQuestionIndex.value += 1
}

function goBack() {
  if (isFirstQuestion.value) {
    return
  }
  currentQuestionIndex.value -= 1
  validationError.value = ''
}

function submitEmpty() {
  const requestId = props.request?.id
  if (!requestId) {
    return
  }
  if (isPlanImplementationRequest.value) {
    emit('submitResponse', requestId, { decision: 'cancel' })
    return
  }
  emit('submitResponse', requestId, { answers: {} })
}

function submitPlanImplementation() {
  const requestId = props.request?.id
  if (!requestId) {
    return
  }
  emit('submitResponse', requestId, {
    decision: 'accept',
    planContent: planContent.value,
    followupMessage: planFeedback.value.trim(),
  })
}

function submitStructured() {
  const requestId = props.request?.id
  if (!requestId) {
    return
  }
  const responseAnswers: Record<string, { answers: string[] }> = {}
  for (const [index, question] of questions.value.entries()) {
    const answer = (answers[question.id] ?? '').trim()
    if (!answer) {
      currentQuestionIndex.value = index
      validationError.value = `${questionTitle(question)} is required.`
      return
    }
    responseAnswers[question.id] = { answers: [answer] }
  }
  emit('submitResponse', requestId, { answers: responseAnswers })
}

function submitJson() {
  const requestId = props.request?.id
  if (!requestId) {
    return
  }
  try {
    const parsed = JSON.parse(jsonDraft.value) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('Response must be a JSON object.')
    }
    emit('submitResponse', requestId, parsed as JsonRecord)
  } catch (error) {
    validationError.value = error instanceof Error ? error.message : String(error)
  }
}
</script>

<template>
  <section
    v-if="request"
    class="flex shrink-0 flex-col border-t border-[color:var(--app-border)] bg-[color:var(--app-surface-muted)] px-4 py-3 max-sm:max-h-[min(56dvh,26rem)] max-sm:overflow-hidden max-sm:px-2.5"
  >
    <div class="mx-auto flex min-h-0 w-full max-w-5xl flex-1 flex-col gap-3">
      <div class="flex shrink-0 items-start justify-between gap-3 max-sm:flex-wrap">
        <div class="min-w-0">
          <p
            class="m-0 text-xs font-bold uppercase tracking-[0.14em] text-[color:var(--app-accent)]"
          >
            {{ requestLabel }}
          </p>
          <!-- <p class="m-0 mt-1 truncate text-sm font-semibold text-[color:var(--app-text)]">
            {{ request.params?.turnId || request.id }}
          </p> -->
        </div>
        <!-- 仅调试使用 -->
        <button
          v-if="false && supportsStructuredInput && !isPlanImplementationRequest"
          type="button"
          class="inline-flex h-8 shrink-0 items-center gap-2 rounded-lg border border-[color:var(--app-focus)] bg-[color:var(--app-surface-raised)] px-3 text-xs font-semibold text-[color:var(--app-accent)]"
          :disabled="disabled"
          @click="useJsonFallback = !useJsonFallback"
        >
          <i class="pi pi-code text-[0.7rem]"></i>
          <span>{{ useJsonFallback ? 'Form' : 'JSON' }}</span>
        </button>
      </div>

      <div
        class="grid min-h-0 flex-1 gap-3 overflow-y-auto overscroll-contain pr-1 max-sm:pb-1"
        data-codex-request-body
      >
        <div v-if="isPlanImplementationRequest" class="grid gap-3">
          <div
            class="grid min-w-0 gap-2 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-translucent)] px-3 py-2.5"
          >
            <p class="m-0 text-sm font-semibold text-[color:var(--app-text)]">
              Implement this plan?
            </p>
            <pre
              v-if="planContent"
              class="m-0 max-h-64 max-w-full overflow-auto whitespace-pre-wrap rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface)] p-3 font-inherit text-sm leading-6 text-[color:var(--app-text)]"
              >{{ planContent }}</pre
            >
            <textarea
              v-model="planFeedback"
              class="min-h-24 w-full resize-y rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-3 py-2 text-sm leading-6 text-[color:var(--app-text)] outline-none focus:border-[color:var(--app-accent)]"
              :disabled="disabled"
              placeholder="Optional: refine the plan before implementation..."
            ></textarea>
          </div>
        </div>

        <div v-else-if="!visibleAsJson && currentQuestion" class="grid gap-3">
          <div
            class="grid min-w-0 gap-2 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-translucent)] px-3 py-2.5"
          >
            <div class="flex items-start justify-between gap-0 max-sm:grid max-sm:grid-cols-1">
              <div class="grid min-w-0 gap-0.5">
                <p
                  class="m-0 text-[0.7rem] font-bold uppercase tracking-[0.12em] text-[color:var(--app-accent)]"
                >
                  Question {{ currentQuestionIndex + 1 }} of {{ questions.length }}
                </p>
                <p class="m-0 text-sm font-semibold text-[color:var(--app-text)]">
                  {{ questionPrompt(currentQuestion) }}
                </p>
              </div>
              <div
                class="flex max-w-36 shrink-0 flex-wrap justify-end gap-1 pt-1 max-sm:max-w-full max-sm:justify-start"
                aria-hidden="true"
              >
                <span
                  v-for="(question, questionIndex) in questions"
                  :key="question.id"
                  class="h-1.5 w-5 rounded-full transition"
                  :class="
                    questionIndex <= currentQuestionIndex
                      ? 'bg-[color:var(--app-accent)]'
                      : 'bg-[color:var(--app-border-strong)]'
                  "
                ></span>
              </div>
            </div>

            <div v-if="currentQuestion.options?.length" class="grid gap-1.5">
              <button
                v-for="option in currentQuestion.options"
                :key="optionKey(currentQuestion, option.label)"
                type="button"
                class="grid rounded-lg border px-3 py-2 text-left transition"
                :class="
                  answerFor(currentQuestion) === option.label
                    ? 'border-[color:var(--app-focus)] bg-[color:var(--app-selected)]'
                    : 'border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] hover:border-[color:var(--app-focus)]'
                "
                :disabled="disabled"
                @click="selectOptionAnswer(currentQuestion, option.label)"
              >
                <span class="text-sm font-semibold text-[color:var(--app-text)]">
                  {{ option.label }}
                </span>
                <span
                  v-if="option.description"
                  class="mt-0.5 text-xs leading-5 text-[color:var(--app-text-soft)]"
                >
                  {{ option.description }}
                </span>
              </button>
            </div>

            <input
              v-if="!currentQuestion.options?.length || currentQuestion.isOther"
              class="h-10 min-w-0 rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-3 text-sm text-[color:var(--app-text)] outline-none transition focus:border-[color:var(--app-accent)]"
              :type="currentQuestion.isSecret ? 'password' : 'text'"
              :value="answerFor(currentQuestion)"
              :disabled="disabled"
              :placeholder="currentQuestion.options?.length ? 'Other answer' : 'Answer'"
              @input="selectAnswer(currentQuestion, ($event.target as HTMLInputElement).value)"
              @keydown.enter.prevent="isLastQuestion ? submitStructured() : advanceQuestion()"
            />
          </div>
        </div>

        <div v-else class="grid gap-2">
          <textarea
            v-model="jsonDraft"
            class="min-h-32 w-full min-w-0 resize-y rounded-lg border border-[color:var(--app-border)] bg-[color:var(--app-surface-raised)] px-3 py-2 font-mono text-xs leading-5 text-[color:var(--app-text)] outline-none focus:border-[color:var(--app-accent)]"
            :disabled="disabled"
          ></textarea>
          <pre
            class="max-h-44 max-w-full overflow-auto rounded-lg bg-[color:var(--app-surface-translucent)] p-3 text-xs leading-5 text-[color:var(--app-text-soft)]"
            v-text="compactJson(request)"
          ></pre>
        </div>

        <p
          v-if="validationError"
          class="m-0 text-sm font-semibold text-[color:var(--app-danger-text)]"
        >
          {{ validationError }}
        </p>
      </div>

      <div
        class="flex shrink-0 flex-wrap items-center justify-between gap-2 max-sm:grid max-sm:grid-cols-1"
        data-codex-request-actions
      >
        <button
          type="button"
          class="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[color:var(--app-focus)] bg-[color:var(--app-surface-raised)] px-3 text-sm font-semibold text-[color:var(--app-accent)] transition hover:bg-[color:var(--app-hover)]"
          :disabled="disabled"
          @click="submitEmpty"
        >
          <i class="pi pi-times text-xs"></i>
          <span>Dismiss</span>
        </button>
        <div class="flex flex-wrap items-center justify-end gap-2 max-sm:grid max-sm:grid-cols-1">
          <button
            v-if="!isPlanImplementationRequest && !visibleAsJson && !isFirstQuestion"
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[color:var(--app-focus)] bg-[color:var(--app-surface-raised)] px-3 text-sm font-semibold text-[color:var(--app-accent)] transition hover:bg-[color:var(--app-hover)]"
            :disabled="disabled"
            @click="goBack"
          >
            <i class="pi pi-arrow-left text-xs"></i>
            <span>Back</span>
          </button>
          <button
            v-if="!isPlanImplementationRequest && !visibleAsJson && !isLastQuestion"
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-[color:var(--app-accent)] px-3 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-55"
            :disabled="disabled"
            @click="advanceQuestion"
          >
            <span>Next</span>
            <i class="pi pi-arrow-right text-xs"></i>
          </button>
          <button
            v-else
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-[color:var(--app-accent)] px-3 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-55"
            :disabled="disabled"
            @click="
              isPlanImplementationRequest
                ? submitPlanImplementation()
                : visibleAsJson
                  ? submitJson()
                  : submitStructured()
            "
          >
            <i class="pi pi-send text-xs"></i>
            <span>{{ isPlanImplementationRequest ? 'Implement plan' : 'Submit' }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
