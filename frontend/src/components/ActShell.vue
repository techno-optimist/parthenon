<template>
  <div class="act-shell" :class="{ 'has-web': hasWeb, 'web-open': webVisible }">
    <!-- The title card: a beat of darkness with the act's name before the scene. -->
    <div v-if="card" class="title-card" aria-hidden="true" @animationend="card = false">
      <span class="tc-numeral">{{ actInfo.numeral }}</span>
      <span class="tc-name">{{ actName }}</span>
      <span class="tc-lede">{{ actLede }}</span>
    </div>

    <header class="act-header">
      <router-link to="/" class="act-brand" :aria-label="$t('parthenon.navHome')"><ParthenonBrand /></router-link>
      <div class="act-subject">
        <span class="act-numeral">{{ actInfo.numeral }}</span>
        <p class="act-name">{{ actName }}</p>
      </div>
      <div class="act-tools">
        <slot name="tools"></slot>
        <button
          v-if="hasWeb"
          type="button"
          class="web-toggle"
          :aria-pressed="webVisible"
          @click="toggleWeb"
        >
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
            <circle cx="4" cy="10" r="2" /><circle cx="15" cy="4.5" r="2" /><circle cx="15" cy="15.5" r="2" /><circle cx="10" cy="10" r="1.2" />
            <path d="M5.8 9.2 8.9 9.8M11.5 8.9l2.2-3M11.5 11.1l2.2 3" />
          </svg>
          <span>{{ webVisible ? $t('parthenon.shell.hideWeb') : $t('parthenon.shell.showWeb') }}</span>
        </button>
        <span class="act-status" :class="`is-${status}`" role="status">
          <span class="dot" aria-hidden="true"></span>
          <span>{{ statusLabel }}</span>
        </span>
      </div>
    </header>

    <h1 v-if="bare" class="sr-only">{{ actName }}</h1>

    <div class="act-body">
      <!-- The Web of Athens: a column on wide screens, a sheet on phones. -->
      <aside
        v-if="hasWeb"
        class="web-pane"
        :class="{ sheet: isNarrow }"
        :hidden="!webVisible"
        :aria-label="$t('parthenon.shell.web')"
      >
        <div v-if="isNarrow" class="sheet-bar">
          <span class="p-eyebrow">{{ $t('parthenon.shell.web') }}</span>
          <button type="button" class="p-button ghost small" @click="toggleWeb">{{ $t('parthenon.shell.close') }}</button>
        </div>
        <div class="web-inner"><slot name="web"></slot></div>
      </aside>

      <main class="stage">
        <!-- The threshold: the scene of the act, the name and its promise. -->
        <div v-if="!bare" class="threshold" :style="thresholdStyle">
          <div class="th-shade" aria-hidden="true"></div>
          <div class="th-copy">
            <span class="p-eyebrow">{{ actInfo.numeral }} · {{ $t('parthenon.shell.actOrdinal', { ordinal: ordinal }) }}</span>
            <h1 class="th-name">{{ actName }}</h1>
            <p class="th-lede">{{ actLede }}</p>
            <slot name="threshold"></slot>
          </div>
        </div>

        <slot></slot>

        <!-- The scribe's ledger: what the engine did, in a drawer, in words. -->
        <section v-if="logs.length" class="ledger" :class="{ open: ledgerOpen }">
          <button type="button" class="ledger-bar" :aria-expanded="ledgerOpen" @click="ledgerOpen = !ledgerOpen">
            <span class="p-eyebrow">{{ $t('parthenon.shell.ledger') }}</span>
            <span class="ledger-last">{{ ledgerLine || lastLine }}</span>
            <span class="chev" aria-hidden="true"></span>
          </button>
          <ol v-if="ledgerOpen" ref="ledgerList" class="ledger-list" role="log" aria-live="polite">
            <li v-for="(line, i) in cleanLogs" :key="i">
              <span class="ledger-time">{{ line.time }}</span>
              <span class="ledger-text">{{ line.text }}</span>
            </li>
          </ol>
        </section>
      </main>
    </div>

    <!-- The Way: the five stations, where you are, what you can go back to. -->
    <nav class="way" :aria-label="$t('parthenon.shell.way')">
      <ol class="way-list">
        <li
          v-for="a in ACTS"
          :key="a.n"
          class="way-station"
          :class="{ current: a.n === act, passed: a.n < act, coming: a.n > act, linked: !!stationRoute(a) }"
          :aria-current="a.n === act ? 'step' : undefined"
        >
          <component :is="stationRoute(a) ? 'router-link' : 'span'" :to="stationRoute(a) || undefined" class="way-link">
            <span class="way-numeral">{{ a.numeral }}</span>
            <span class="way-name">{{ $tm('main.stepNames')[a.n - 1] }}</span>
          </component>
        </li>
      </ol>
      <div class="way-tools"><LanguageSwitcher /></div>
    </nav>
  </div>
</template>

<script setup>
// The shell every act stands in: one header, the threshold scene, the stage,
// the Web of Athens beside it, the scribe's ledger and the Way strip. Acts pass
// what they know (status, logs, where earlier acts can be revisited) and put
// their own work in the default slot.
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, useSlots, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ParthenonBrand from './ParthenonBrand.vue'
import LanguageSwitcher from './LanguageSwitcher.vue'
import { ACTS, stripIds } from '../parthenon/vocabulary.js'

const props = defineProps({
  act: { type: Number, required: true }, // 1..5
  status: { type: String, default: 'ready' }, // ready | working | live | done | error
  statusText: { type: String, default: '' },
  lede: { type: String, default: '' },
  logs: { type: Array, default: () => [] },
  // Routes for stations that can be revisited: { 1: {name, params}, 2: ... }
  links: { type: Object, default: () => ({}) },
  bare: { type: Boolean, default: false }, // no threshold band (the Agora fills the stage)
  scene: { type: String, default: '' },
  quiet: { type: Boolean, default: false }, // no title card
  ledgerLine: { type: String, default: '' } // one line in the city's words for the closed ledger
})

const { t, tm } = useI18n()
const slots = useSlots()

const actInfo = computed(() => ACTS[props.act - 1] || ACTS[0])
const actName = computed(() => tm('main.stepNames')[props.act - 1] || '')
const actLede = computed(() => {
  if (props.lede) return props.lede
  const movements = tm('parthenon.movements')
  const m = Array.isArray(movements) ? movements[props.act - 1] : null
  return (m && (m.text || m.desc || m.body)) || ''
})
const thresholdStyle = computed(() => ({ '--scene': `url(${props.scene || actInfo.value.scene})` }))

const statusLabel = computed(() => props.statusText || t(`parthenon.shell.status.${props.status}`))
const ordinal = computed(() => {
  const words = tm('parthenon.shell.ordinals')
  return Array.isArray(words) ? words[props.act - 1] || String(props.act) : String(props.act)
})

// The Web pane
const hasWeb = computed(() => !!slots.web)
const NARROW = '(max-width: 899px)'
const narrowQuery = typeof window !== 'undefined' ? window.matchMedia(NARROW) : null
const isNarrow = ref(narrowQuery ? narrowQuery.matches : false)
const WEB_KEY = 'parthenon.web.open'
const readPref = () => {
  try { return localStorage.getItem(WEB_KEY) !== 'closed' } catch (e) { return true }
}
const webVisible = ref(!isNarrow.value && readPref())
provide('parthenonWebSheet', isNarrow)
const toggleWeb = () => {
  webVisible.value = !webVisible.value
  if (!isNarrow.value) {
    try { localStorage.setItem(WEB_KEY, webVisible.value ? 'open' : 'closed') } catch (e) { /* per-viewer convenience only */ }
  }
}
const onNarrow = (e) => {
  isNarrow.value = e.matches
  webVisible.value = e.matches ? false : readPref()
}

// The ledger
const ledgerOpen = ref(false)
const ledgerList = ref(null)
watch(ledgerOpen, async (open) => {
  if (!open) return
  await nextTick()
  if (ledgerList.value) ledgerList.value.scrollTop = ledgerList.value.scrollHeight
})
const cleanLogs = computed(() =>
  props.logs
    .map((l) => (typeof l === 'string' ? { time: '', text: l } : { time: l.time || l.timestamp || '', text: l.message ?? l.text ?? '' }))
    .map((l) => ({ time: String(l.time).slice(0, 8), text: stripIds(l.text) }))
    .filter((l) => l.text)
)
const lastLine = computed(() => cleanLogs.value.length ? cleanLogs.value[cleanLogs.value.length - 1].text : '')

// Stations
const stationRoute = (a) => (a.n < props.act ? props.links[a.n] || null : a.n === props.act ? null : props.links[a.n] || null)

// The title card shows once per act per visit, and never under reduced motion.
const card = ref(false)
onMounted(() => {
  narrowQuery?.addEventListener('change', onNarrow)
  const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (props.quiet || reduced) return
  const key = `parthenon.card.${props.act}`
  try {
    if (sessionStorage.getItem(key)) return
    sessionStorage.setItem(key, '1')
  } catch (e) { /* show it anyway */ }
  card.value = true
})
onBeforeUnmount(() => narrowQuery?.removeEventListener('change', onNarrow))

watch(() => props.act, () => { ledgerOpen.value = false })
</script>

<style scoped>
.act-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--p-bg);
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
  padding-bottom: var(--p-way-h);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* Title card */
.title-card {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: #0b0e13;
  color: var(--p-ink);
  text-align: center;
  padding: 24px;
  animation: card 1.6s ease forwards;
  pointer-events: none;
}

.tc-numeral {
  font-family: var(--p-font-inscription);
  font-size: var(--t-sm);
  letter-spacing: var(--track-inscription);
  color: var(--p-gold);
}

.tc-name {
  font-family: var(--p-font-display);
  font-size: var(--t-3xl);
  line-height: 1;
}

.tc-lede {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
  max-width: 34em;
}

@keyframes card {
  0% { opacity: 0; }
  18% { opacity: 1; }
  72% { opacity: 1; }
  100% { opacity: 0; }
}

/* Header */
.act-header {
  position: sticky;
  top: 0;
  z-index: 30;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 16px;
  height: var(--p-header-h);
  padding: 0 var(--p-gutter);
  background: rgba(11, 14, 19, 0.88);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--p-line);
}

.act-brand {
  justify-self: start;
  text-decoration: none;
  color: inherit;
  display: inline-flex;
}

.act-subject {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
  overflow: hidden;
}

.act-numeral {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  color: var(--p-gold);
}

.act-name {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  color: var(--p-ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1;
}

.act-tools {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: 18px;
}

.web-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 8px 12px;
  background: transparent;
  border: 1px solid var(--p-control-border);
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  font-weight: 600;
  cursor: pointer;
}

.web-toggle:hover,
.web-toggle[aria-pressed='true'] {
  border-color: var(--p-gold);
  color: var(--p-gold);
}

.act-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.act-status .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--p-ink-4);
}

.act-status.is-working .dot,
.act-status.is-live .dot {
  background: var(--p-gold);
  box-shadow: 0 0 0 4px var(--p-terracotta-tint);
  animation: pulse 1.6s ease-in-out infinite;
}

.act-status.is-done .dot { background: var(--p-olive); }
.act-status.is-error .dot { background: var(--p-error); }

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 3px var(--p-terracotta-tint); }
  50% { box-shadow: 0 0 0 7px transparent; }
}

/* Threshold */
.threshold {
  position: relative;
  min-height: 220px;
  display: flex;
  align-items: flex-end;
  padding: 44px var(--p-gutter) 30px;
  background-image: var(--scene);
  background-size: cover;
  background-position: center 40%;
  isolation: isolate;
}

.th-shade {
  position: absolute;
  inset: 0;
  z-index: -1;
  background:
    linear-gradient(180deg, rgba(11, 14, 19, 0.55) 0%, rgba(11, 14, 19, 0.35) 45%, rgba(11, 14, 19, 0.96) 100%),
    linear-gradient(90deg, rgba(11, 14, 19, 0.55) 0%, rgba(11, 14, 19, 0) 60%);
}

.th-copy {
  max-width: 1240px;
  width: 100%;
  margin-inline: auto;
}

.th-name {
  margin: 8px 0 6px;
  font-family: var(--p-font-display);
  font-size: var(--t-3xl);
  font-weight: 500;
  line-height: 1;
  color: var(--p-ink);
  text-wrap: balance;
}

.th-lede {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-2);
  max-width: 40em;
}

/* Body */
.act-body {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-height: 0;
}

.has-web.web-open .act-body {
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
}

.web-pane {
  position: sticky;
  top: var(--p-header-h);
  height: calc(100vh - var(--p-header-h) - var(--p-way-h));
  border-right: 1px solid var(--p-line);
  background: var(--p-surface);
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.web-inner {
  flex: 1;
  min-height: 0;
  position: relative;
}

.web-pane[hidden] {
  display: none;
}

.web-pane.sheet {
  position: fixed;
  inset: var(--p-header-h) 0 0 0;
  z-index: 40;
  height: auto;
  border-right: 0;
}

.sheet-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px var(--p-gutter);
  border-bottom: 1px solid var(--p-line);
}

.stage {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

/* Ledger */
.ledger {
  margin-top: auto;
  border-top: 1px solid var(--p-line);
  background: var(--p-surface-2);
}

.ledger-bar {
  width: 100%;
  display: grid;
  grid-template-columns: auto 1fr 12px;
  align-items: center;
  gap: 16px;
  padding: 10px var(--p-gutter);
  background: transparent;
  border: 0;
  color: var(--p-ink-3);
  font-family: var(--p-font-mono);
  font-size: var(--t-xs);
  letter-spacing: var(--track-mono);
  text-align: left;
  cursor: pointer;
}

.ledger-bar:hover { color: var(--p-ink-2); }

.ledger-last {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chev {
  width: 8px;
  height: 8px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(-135deg);
  transition: transform 0.2s ease;
}

.ledger.open .chev { transform: rotate(45deg); }

.ledger-list {
  list-style: none;
  margin: 0;
  padding: 4px var(--p-gutter) 12px;
  max-height: 240px;
  overflow: auto;
  font-family: var(--p-font-mono);
  font-size: var(--t-xs);
  letter-spacing: var(--track-mono);
  color: var(--p-ink-3);
}

.ledger-list li {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 12px;
  padding: 3px 0;
}

.ledger-time { color: var(--p-ink-4); font-variant-numeric: tabular-nums; }

/* The Way */
.way {
  position: fixed;
  inset: auto 0 0 0;
  z-index: 35;
  height: var(--p-way-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 var(--p-gutter) env(safe-area-inset-bottom, 0px);
  background: rgba(17, 21, 28, 0.94);
  backdrop-filter: blur(10px);
  border-top: 1px solid var(--p-line);
}

.way-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  align-items: center;
  gap: 0;
  min-width: 0;
  overflow: hidden;
}

.way-station {
  position: relative;
  display: flex;
  align-items: center;
}

.way-station + .way-station::before {
  content: '';
  width: clamp(16px, 3vw, 40px);
  height: 1px;
  background: var(--p-line-strong);
  margin: 0 8px;
}

.way-station.passed + .way-station::before,
.way-station.passed + .way-station.current::before {
  background: var(--p-gold);
}

.way-link {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 2px;
  text-decoration: none;
  color: var(--p-ink-4);
  white-space: nowrap;
}

.way-numeral {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
}

.way-name {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 500;
}

.way-station.passed .way-link { color: var(--p-ink-2); }
.way-station.linked .way-link:hover { color: var(--p-gold); }
.way-station.current .way-link { color: var(--p-gold); }

.way-tools { flex-shrink: 0; }

@media (max-width: 899px) {
  .act-header {
    grid-template-columns: auto 1fr auto;
    gap: 12px;
    padding: 0 16px;
  }

  .act-name { font-size: var(--t-lg); }
  .act-tools { gap: 10px; }
  .act-status { font-size: 10px; letter-spacing: 0.1em; }
  .web-toggle span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .web-toggle { min-width: 44px; min-height: 44px; padding: 8px; justify-content: center; }
  .ledger { display: none; }
  .threshold { min-height: 160px; padding: 28px 16px 22px; }
  .th-name { font-size: var(--t-2xl); }
  .th-lede { font-size: var(--t-md); }
  .way { padding-inline: 12px; }
  .way-tools { display: none; }
  .way-name { display: none; }
  .way-station.current .way-name { display: inline; }
  .way-station + .way-station::before { width: 10px; margin: 0 4px; }
  .way-link { padding: 12px 8px; min-width: 40px; justify-content: center; }
  .ledger-bar { padding-inline: 16px; }
  .ledger-list { padding-inline: 16px; }
}

@media (max-width: 480px) {
  .act-brand :deep(.p-brand-word) { display: none; }
  .act-name { font-size: var(--t-md); }
}
</style>
