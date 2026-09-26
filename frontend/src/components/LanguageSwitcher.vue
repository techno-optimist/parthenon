<template>
  <div class="language-switcher" ref="switcherRef" @keydown.esc="closeAndFocusTrigger">
    <button
      ref="triggerRef"
      type="button"
      class="switcher-trigger"
      :aria-expanded="open"
      :aria-controls="listId"
      @click="toggleDropdown"
    >
      {{ currentLabel }}
      <span class="caret" aria-hidden="true">{{ open ? '▲' : '▼' }}</span>
    </button>
    <ul v-if="open" :id="listId" class="switcher-dropdown">
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
import { ref, computed, onMounted, onUnmounted, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { availableLocales } from '@/i18n/index.js'

const { locale } = useI18n()
const open = ref(false)
const switcherRef = ref(null)
const triggerRef = ref(null)
const listId = `language-switcher-${useId()}`

const currentLabel = computed(() => {
  const found = availableLocales.find(l => l.key === locale.value)
  return found ? found.label : locale.value
})

const toggleDropdown = () => {
  open.value = !open.value
}

const switchLocale = (key) => {
  locale.value = key
  localStorage.setItem('locale', key)
  document.documentElement.lang = key
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
  document.documentElement.lang = locale.value
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
  background: transparent;
  color: var(--p-ink-2);
  border: 1px solid var(--p-line-strong);
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


</style>
