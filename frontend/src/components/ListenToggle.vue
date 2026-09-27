<template>
  <button
    v-if="sound.supported"
    type="button"
    class="listen-toggle"
    :class="{ compact, captioned: compact && captioned, waiting: sound.enabled && sound.waiting }"
    :aria-pressed="sound.enabled ? 'true' : 'false'"
    :title="title"
    @click="toggleListening"
  >
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
      <path d="M3 8h3l4-3.5v11L6 12H3z" fill="currentColor" />
      <path
        v-if="sound.enabled"
        class="waves"
        d="M13 7.2a4 4 0 0 1 0 5.6M15.2 5a7 7 0 0 1 0 10"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
      />
      <path v-else d="M13.5 8l4 4M17.5 8l-4 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
    </svg>
    <span :class="compact && !captioned ? 'lt-hidden' : compact ? 'lt-caption' : 'lt-label'">{{ $t('parthenon.listen.label') }}</span>
  </button>
</template>

<script setup>
// The one Listen switch. Every copy of it reads and flips the same state in
// parthenon/sound.js, so the hero, the acts and the square agree. A visitor
// who chose Listen on an earlier visit finds it on; until they first touch the
// page the browser keeps it quiet, and the switch says so with faint waves.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { sound, toggleListening } from '../parthenon/sound'

defineProps({
  // Icon only, for tight headers; the word stays for screen readers.
  compact: { type: Boolean, default: false },
  // With compact: a square with the icon over a small word, beside the
  // acts' Web switch, so the pair reads the same.
  captioned: { type: Boolean, default: false }
})

const { t } = useI18n()
const title = computed(() => {
  if (!sound.enabled) return t('parthenon.listen.titleOff')
  return sound.waiting ? t('parthenon.listen.titleWaiting') : t('parthenon.listen.titleOn')
})
</script>

<style scoped>
.listen-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  min-width: 40px;
  padding: 0 12px;
  border: 1px solid var(--p-control-border);
  background: transparent;
  color: var(--p-ink-2);
  font-family: var(--p-font-inscription);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease, background 0.2s ease;
}

.listen-toggle.compact {
  justify-content: center;
  padding: 0;
  width: 40px;
}

.listen-toggle.captioned {
  flex-direction: column;
  gap: 3px;
  width: 44px;
  min-width: 44px;
  height: 44px;
  min-height: 44px;
}

.lt-caption {
  font-family: var(--p-font-body);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.06em;
}

.listen-toggle:hover {
  color: var(--p-ink);
  border-color: var(--p-gold);
}

.listen-toggle[aria-pressed='true'] {
  background: var(--p-terracotta-tint);
  border-color: var(--p-gold);
  color: var(--p-gold);
}

.listen-toggle.waiting .waves {
  opacity: 0.4;
}

@media (prefers-reduced-motion: no-preference) {
  .listen-toggle.waiting .waves {
    animation: listen-breathe 2.4s ease-in-out infinite;
  }
}

@keyframes listen-breathe {
  0%, 100% { opacity: 0.25; }
  50% { opacity: 0.8; }
}

.listen-toggle:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 3px;
}

.lt-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
