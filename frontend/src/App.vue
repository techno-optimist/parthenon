<template>
  <router-view v-slot="{ Component, route }">
    <transition name="act" mode="out-in" @after-enter="onArrive">
      <component :is="Component" v-if="Component" />
      <!-- An address where nothing was ever held: an empty square at night, and two ways on. -->
      <div v-else-if="ready && route.matched.length === 0" key="nowhere" class="nowhere" :lang="locale">
        <div class="nw-scene" aria-hidden="true"></div>
        <div class="nw-shade" aria-hidden="true"></div>
        <header class="nw-bar">
          <router-link to="/" class="nw-brand" :aria-label="$t('parthenon.navHome')"><ParthenonBrand /></router-link>
        </header>
        <main class="nw-copy">
          <p class="p-eyebrow"><span lang="grc">ΟΥΔΑΜΟΥ</span><span aria-hidden="true"> · </span>{{ $t('parthenon.nowhere.eyebrow') }}</p>
          <h1 class="nw-title" tabindex="-1">{{ $t('parthenon.nowhere.title') }}</h1>
          <p class="nw-lede">{{ $t('parthenon.nowhere.lede') }}</p>
          <div class="nw-ways">
            <router-link to="/" class="p-button">{{ $t('parthenon.nowhere.home') }}</router-link>
            <router-link :to="{ name: 'Chronicles' }" class="p-button secondary">{{ $t('parthenon.nowhere.chronicles') }}</router-link>
          </div>
        </main>
        <div class="p-meander nw-rule" aria-hidden="true"></div>
      </div>
    </transition>
  </router-view>
</template>

<script setup>
// The frame around every page: the fade between acts, the tab's title, where
// focus lands when the visitor moves to a new page, and a guard that keeps the
// keyboard's focus out from under the fixed bars.
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ParthenonBrand from './components/ParthenonBrand.vue'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

// Until the first address is read, the route is a blank start, not "nowhere".
const ready = ref(false)
router.isReady().then(() => { ready.value = true })

const BRAND = 'Parthenon'
// The acts name their own tab (ActShell); every other page is named here.
const ACT_ROUTES = new Set(['Process', 'Simulation', 'SimulationRun', 'Report', 'Interaction'])
const nameTab = () => {
  if (typeof document === 'undefined' || !ready.value) return
  if (route.matched.length === 0) {
    document.title = `${t('parthenon.nowhere.tab')} · ${BRAND}`
    return
  }
  if (ACT_ROUTES.has(route.name)) return
  if (route.name === 'Chronicles') document.title = `${t('history.title')} · ${BRAND}`
  else if (route.name === 'Home') document.title = BRAND
}
watch(() => [ready.value, route.fullPath, route.name, locale.value], () => nameTab(), { immediate: true })

// Moving within the app (not the first load): once the new page has faded in,
// focus its heading so a screen reader says where the visitor now stands.
let arrivals = 0
router.afterEach((to, from, failure) => {
  if (!failure) arrivals++
})
const onArrive = () => {
  if (arrivals < 2 || typeof document === 'undefined') return
  nextTick(() => {
    const scope = document.querySelector('#act-main') || document.querySelector('main') || document.body
    const heading = scope.querySelector('h1') || document.querySelector('h1')
    if (!heading) return
    if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1')
    heading.focus({ preventScroll: true })
  })
}

// The keyboard's focus kept clear of the fixed bars (the act header, the Way,
// the home's top bar). Only for the keyboard: a pointer never moves the page.
let keyboard = false
const onKeyDown = (e) => {
  if (e.key === 'Tab' || e.key.startsWith('Arrow') || e.key === 'Home' || e.key === 'End') keyboard = true
}
const onPointer = () => { keyboard = false }
const TOP_BARS = '[data-chrome="top"], .home > .topbar, .cp-bar'
const BOTTOM_BARS = '[data-chrome="bottom"]'
const barEdges = () => {
  const h = window.innerHeight
  let top = 0
  let bottom = h
  for (const el of document.querySelectorAll(TOP_BARS)) {
    const r = el.getBoundingClientRect()
    if (r.height && r.top <= 1 && r.height < h * 0.4) top = Math.max(top, r.bottom)
  }
  for (const el of document.querySelectorAll(BOTTOM_BARS)) {
    const r = el.getBoundingClientRect()
    if (r.height && r.bottom >= h - 1 && r.height < h * 0.4) bottom = Math.min(bottom, r.top)
  }
  return { top, bottom }
}
const pinned = (el) => {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    const p = getComputedStyle(n).position
    if (p === 'fixed' || p === 'sticky') return true
  }
  return false
}
const ROOM = 12
const onFocusIn = (e) => {
  if (!keyboard) return
  const el = e.target
  if (!(el instanceof Element) || el === document.body || el === document.documentElement) return
  requestAnimationFrame(() => {
    if (document.activeElement !== el || pinned(el)) return
    const r = el.getBoundingClientRect()
    if (!r.height) return
    const { top, bottom } = barEdges()
    let delta = 0
    if (r.bottom > bottom) {
      delta = r.bottom - bottom + ROOM
      if (r.top - delta < top) delta = r.top - top - ROOM // taller than the room: its top first
    } else if (r.top < top) {
      delta = r.top - top - ROOM
    }
    if (delta) window.scrollBy(0, delta)
  })
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown, true)
  window.addEventListener('pointerdown', onPointer, true)
  document.addEventListener('focusin', onFocusIn)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown, true)
  window.removeEventListener('pointerdown', onPointer, true)
  document.removeEventListener('focusin', onFocusIn)
})
</script>

<style>
/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: var(--p-font-body);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--p-ink);
  background-color: transparent;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--p-surface-2);
}

::-webkit-scrollbar-thumb {
  background: var(--p-line-strong);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--p-ink-4);
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}

/* Between acts: the lights go down and come up. Never a hard cut. */
.act-enter-active { transition: opacity 0.7s ease; }
.act-leave-active { transition: opacity 0.45s ease; }
.act-enter-from, .act-leave-to { opacity: 0; }

/* Nowhere: the empty square at night */
.nowhere {
  position: relative;
  min-height: 100vh;
  min-height: 100svh;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  overflow: hidden;
  isolation: isolate;
  background: #0b0e13;
  color: var(--p-ink-2);
}

.nw-scene {
  position: absolute;
  inset: 0;
  z-index: -2;
  background: var(--p-still-agora-night, none) center 38% / cover no-repeat;
}

.nw-shade {
  position: absolute;
  inset: 0;
  z-index: -1;
  background:
    linear-gradient(180deg, rgba(11, 14, 19, 0.7) 0%, rgba(11, 14, 19, 0.15) 30%, rgba(11, 14, 19, 0.55) 62%, rgba(11, 14, 19, 0.97) 100%),
    linear-gradient(90deg, rgba(11, 14, 19, 0.7) 0%, rgba(11, 14, 19, 0) 65%);
}

.nw-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  height: 68px;
  padding: 0 var(--p-gutter);
}

.nw-brand {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  color: inherit;
  text-decoration: none;
}

.nw-copy {
  width: min(1240px, 100% - 2 * var(--p-gutter));
  margin: 0 auto;
  padding: 120px 0 44px;
}

.nw-title {
  max-width: 16em;
  margin: 14px 0 14px;
  font-family: var(--p-font-display);
  font-size: var(--t-3xl);
  font-weight: 500;
  line-height: 1.04;
  color: var(--p-ink);
  text-wrap: balance;
}

.nw-lede {
  max-width: 36em;
  margin: 0 0 30px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-2);
}

.nw-ways {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.nw-rule {
  opacity: 0.4;
  margin-bottom: 28px;
}

@media (max-width: 599px) {
  .nw-bar { padding: 0 16px; }
  .nw-copy { width: calc(100% - 32px); padding-bottom: 32px; }
  .nw-title { font-size: 2rem; }
  .nw-lede { font-size: var(--t-md); }
  .nw-ways .p-button { flex: 1 1 100%; }
}
</style>
