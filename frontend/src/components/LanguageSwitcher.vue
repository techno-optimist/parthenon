<template>
  <div class="language-switcher" :class="{ compact }" ref="switcherRef" @keydown.esc="closeAndFocusTrigger">
    <button
      ref="triggerRef"
      type="button"
      class="switcher-trigger"
      :lang="locale"
      :aria-label="t('parthenon.language.choose', { current: currentLabel })"
      :title="compact ? t('parthenon.language.choose', { current: currentLabel }) : undefined"
      :aria-expanded="open"
      :aria-controls="listId"
      @click="toggleDropdown"
    >
      {{ compact ? shortLabel : currentLabel }}
      <span class="caret" aria-hidden="true">{{ open ? '▲' : '▼' }}</span>
    </button>
    <ul v-if="open" :id="listId" ref="listRef" class="switcher-dropdown" :class="{ up: openUp }">
      <li v-for="loc in availableLocales" :key="loc.key">
        <button
          type="button"
          class="switcher-option"
          :class="{ active: loc.key === locale }"
          :aria-current="loc.key === locale ? 'true' : undefined"
          :lang="loc.key"
          @click="switchLocale(loc.key)"
        >
          {{ loc.label }}
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { availableLocales } from '@/i18n/index.js'

// i18n/index.js keeps <html lang> and the city's words in step with `locale`.
defineProps({
  // For a phone's bottom bar: a square holding the language's short name.
  compact: { type: Boolean, default: false }
})

const { locale, t } = useI18n()
const open = ref(false)
const switcherRef = ref(null)
const triggerRef = ref(null)
const listRef = ref(null)
// In an act's bottom bar there is no room below, so the list opens upward.
const openUp = ref(false)
const listId = `language-switcher-${useId()}`

const currentLabel = computed(() => {
  const found = availableLocales.find(l => l.key === locale.value)
  return found ? found.label : locale.value
})

// 'EN', 'ES'...; a language written in its own script keeps its own name (中文).
const shortLabel = computed(() => {
  const label = currentLabel.value || ''
  return /^[\u0000-\u024f\s]+$/.test(label) ? String(locale.value).slice(0, 2).toUpperCase() : label
})

const toggleDropdown = async () => {
  open.value = !open.value
  if (!open.value) return
  openUp.value = false
  await nextTick()
  const trigger = triggerRef.value?.getBoundingClientRect()
  const list = listRef.value?.getBoundingClientRect()
  if (!trigger || !list) return
  const below = window.innerHeight - trigger.bottom
  openUp.value = below < list.height + 8 && trigger.top > below
}

const switchLocale = (key) => {
  locale.value = key
  try {
    localStorage.setItem('locale', key)
  } catch {
    // A private window keeps the choice for this visit only.
  }
  open.value = false
  triggerRef.value?.focus()
}

const closeAndFocusTrigger = () => {
  if (!open.value) return
  open.value = false
  triggerRef.value?.focus()
}

const onClickOutside = (e) => {
  if (switcherRef.value && !switcherRef.value.contains(e.target)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', onClickOutside)
})
</script>

<style scoped>
.language-switcher {
  position: relative;
  display: inline-block;
  font-family: var(--p-font-inscription);
}

/* Light theme (default - for white header backgrounds) */
.switcher-trigger {
  min-height: 40px;
  background: transparent;
  color: var(--p-ink-2);
  border: 1px solid var(--p-control-border);
  padding: 5px 12px;
  font-family: var(--p-font-inscription);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: border-color 0.2s, opacity 0.2s;
}

.switcher-trigger:hover {
  border-color: var(--p-terracotta);
  color: var(--p-terracotta);
}

.caret {
  font-size: 0.6rem;
}

.switcher-dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  background: var(--p-surface);
  border: 1px solid var(--p-line-strong);
  list-style: none;
  padding: 4px 0;
  min-width: 100%;
  z-index: 1000;
  box-shadow: 0 2px 8px rgba(31, 26, 22, 0.1);
}

.switcher-dropdown.up {
  top: auto;
  bottom: 100%;
  margin-top: 0;
  margin-bottom: 4px;
}

.switcher-dropdown li {
  margin: 0;
}

.switcher-option {
  display: block;
  width: 100%;
  background: transparent;
  border: 0;
  text-align: left;
  font-family: inherit;
  padding: 7px 14px;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--p-ink-2);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}

.switcher-option:hover,
.switcher-option:focus-visible {
  background: var(--p-surface-2);
}

.switcher-option.active {
  color: var(--orange, var(--p-terracotta));
}

.switcher-trigger:focus-visible,
.switcher-option:focus-visible {
  outline: 2px solid var(--p-gold, currentColor);
  outline-offset: 2px;
}

/* Compact: a 44px square, the short name over nothing else; the caret goes. */
.compact .switcher-trigger {
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  padding: 0 8px;
  font-size: 12px;
  letter-spacing: 0.08em;
}

.compact .caret {
  display: none;
}

/* Cinzel has no Chinese; the language names read in the serif, untracked. */
.switcher-trigger:lang(zh),
.switcher-option:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

.switcher-option {
  min-height: 40px;
}


</style>
