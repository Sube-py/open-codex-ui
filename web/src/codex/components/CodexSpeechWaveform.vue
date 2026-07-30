<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  active: boolean
  connecting: boolean
  level: number
}>()

const barShape = [0.38, 0.62, 0.82, 1, 0.82, 0.62, 0.38]
const barStyles = computed(() => {
  const normalizedLevel = Math.max(0, Math.min(props.level, 1))
  return barShape.map((shape, index) => ({
    height: `${Math.round(10 + normalizedLevel * shape * 44)}px`,
    animationDelay: `${index * 70}ms`,
  }))
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="active"
      class="pointer-events-none fixed left-1/2 top-[calc(var(--yier-viewport-height,100dvh)/2)] z-[70] flex -translate-x-1/2 -translate-y-1/2 items-center gap-1.5"
      role="status"
      aria-live="polite"
      aria-label="Voice input active"
      data-codex-speech-waveform
    >
      <span class="sr-only">Voice input active</span>
      <span
        v-for="(style, index) in barStyles"
        :key="index"
        class="h-2.5 w-1 rounded-full bg-[color:var(--app-accent)] shadow-[0_0_10px_var(--app-accent)] transition-[height] duration-75 ease-out"
        :class="connecting ? 'codex-speech-waveform-connecting' : ''"
        :style="style"
        aria-hidden="true"
      ></span>
    </div>
  </Teleport>
</template>

<style scoped>
@keyframes codex-speech-waveform-connect {
  0%,
  100% {
    height: 10px;
    opacity: 0.55;
  }
  50% {
    height: 38px;
    opacity: 1;
  }
}

.codex-speech-waveform-connecting {
  animation: codex-speech-waveform-connect 700ms ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
  .codex-speech-waveform-connecting {
    animation: none;
    height: 20px !important;
    opacity: 1;
  }
}
</style>
