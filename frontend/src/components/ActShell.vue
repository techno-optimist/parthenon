<template>
  <div class="act-shell" :class="{ 'has-web': hasWeb, 'web-open': webVisible }">
    <!-- For the keyboard: past the header and the Web, straight to the act. -->
    <a class="skip-link" href="#act-main" @click.prevent="skipToAct">{{ $t('parthenon.shell.skip') }}</a>

    <!-- The title card: a beat of darkness with the act's name before the scene. -->
    <div v-if="card" class="title-card" aria-hidden="true" @animationend="card = false">
      <span class="tc-numeral">{{ actInfo.numeral }}</span>
      <span class="tc-name">{{ actName }}</span>
      <span class="tc-lede">{{ actLede }}</span>
    </div>

    <header class="act-header" data-chrome="top" :inert="sheetOpen || undefined">
      <router-link to="/" class="act-brand" :aria-label="$t('parthenon.navHome')"><ParthenonBrand /></router-link>
      <!-- The act's name, and under it how the act stands: one line of the city's words. -->
      <div class="act-subject">
        <p class="act-title">
          <span class="act-numeral" aria-hidden="true">{{ actInfo.numeral }}</span>
          <span class="act-name">{{ actName }}</span>
        </p>
        <span class="act-status" :class="`is-${status}`" role="status" :title="statusLabel">
          <span class="dot" aria-hidden="true"></span>
          <span class="status-word">{{ statusLabel }}</span>
        </span>
      </div>
      <div class="act-tools">
        <slot name="tools"></slot>
        <ListenToggle :compact="compactTools" :captioned="compactTools" />
        <button
          v-if="hasWeb"
          ref="webToggleEl"
          type="button"
          class="web-toggle"
          :class="{ compact: compactTools, beckon }"
          :aria-pressed="webVisible"
          :title="compactTools ? webLabel : undefined"
          @click="toggleWeb"
          @animationend="beckon = false"
        >
          <!-- An asterism: five stars joined, as the Web draws the city's ties in the night sky. -->
          <svg class="wt-mark" viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
            <path d="M2.2 6.6 6.1 13.4 10 9.2 13.9 14.6 17.8 5.4" fill="none" stroke="currentColor" stroke-width="1" stroke-opacity=".6" stroke-linejoin="round" />
            <circle cx="2.2" cy="6.6" r="1.5" fill="currentColor" />
            <circle cx="6.1" cy="13.4" r="2" fill="currentColor" />
            <circle cx="10" cy="9.2" r="1.35" fill="currentColor" />
            <circle cx="13.9" cy="14.6" r="1.75" fill="currentColor" />
            <circle cx="17.8" cy="5.4" r="1.5" fill="currentColor" />
          </svg>
          <span class="wt-label">{{ webLabel }}</span>
          <span v-if="compactTools" class="wt-caption" aria-hidden="true">{{ $t('parthenon.shell.webShort') }}</span>
        </button>
      </div>
    </header>

    <div class="act-body">
      <!-- The Web of Athens: a column on wide screens, a sheet on phones. -->
      <aside
        v-if="hasWeb"
        ref="webPaneEl"
        class="web-pane"
        :class="{ sheet: isNarrow }"
        :hidden="!webVisible"
        :role="isNarrow ? 'dialog' : undefined"
        :aria-modal="isNarrow ? 'true' : undefined"
        :aria-label="$t('parthenon.shell.web')"
        tabindex="-1"
      >
        <!-- While the sheet is open, Tab and Shift+Tab turn round inside it. -->
        <span v-if="sheetOpen" class="sentinel" tabindex="0" @focus="wrapFocus('last')"></span>
        <div v-if="isNarrow" class="sheet-bar">
          <span class="p-eyebrow">{{ $t('parthenon.shell.web') }}</span>
          <button ref="sheetCloseEl" type="button" class="p-button ghost small" @click="closeSheet">{{ $t('parthenon.shell.close') }}</button>
        </div>
        <div class="web-inner"><slot name="web"></slot></div>
        <span v-if="sheetOpen" class="sentinel" tabindex="0" @focus="wrapFocus('first')"></span>
      </aside>

      <main id="act-main" ref="mainEl" class="stage" tabindex="-1" :inert="sheetOpen || undefined">
        <h1 v-if="bare && nameHeading" class="sr-only">{{ actName }}</h1>

        <!-- The threshold: the scene of the act, the name and its promise. -->
        <div v-if="!bare" class="threshold" :style="thresholdStyle">
          <div class="th-shade" aria-hidden="true"></div>
          <div class="th-copy">
            <span class="p-eyebrow">{{ actInfo.numeral }} · {{ $t('parthenon.shell.actOrdinal', { ordinal: ordinal }) }}</span>
            <component :is="nameHeading ? 'h1' : 'p'" class="th-name">{{ actName }}</component>
            <p class="th-lede">{{ actLede }}</p>
            <slot name="threshold"></slot>
          </div>
        </div>

        <!-- On the public steps, at someone else's gathering: one line on why the controls are not here. -->
        <p v-if="guest" class="calm-line guest-line" role="note">{{ $t(guestAsks ? 'parthenon.public.guest' : 'parthenon.public.guestInvite') }}</p>

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

    <!-- The Way: the five stations, where you are, what you can go back to;
         then the shelf of every Chronicle and the visitor's language. -->
    <nav class="way" data-chrome="bottom" :aria-label="$t('parthenon.shell.way')" :inert="sheetOpen || undefined">
      <ol class="way-list">
        <li
          v-for="a in ACTS"
          :key="a.n"
          class="way-station"
          :class="{ current: a.n === act, passed: isPassed(a), coming: !isPassed(a) && a.n !== act, linked: !!stationRoute(a) }"
          :aria-current="a.n === act ? 'step' : undefined"
        >
          <component
            :is="stationRoute(a) ? 'router-link' : 'span'"
            :to="stationRoute(a) || undefined"
            class="way-link"
            :title="isNarrow ? stepName(a.n) : undefined"
          >
            <span class="way-numeral" aria-hidden="true">{{ a.numeral }}</span>
            <span class="way-name">{{ stepName(a.n) }}</span>
          </component>
        </li>
      </ol>
      <div class="way-tools">
        <router-link :to="{ name: 'Chronicles' }" class="way-shelf" :title="isNarrow ? $t('parthenon.navArchive') : undefined">
          <!-- Tablets on a shelf -->
          <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true">
            <path d="M1.5 17.6h17" />
            <path d="M3.6 17.1V5.4h3.3v11.7M8.4 17.1V3.2h3.3v13.9" />
            <path d="M13.1 16.9 15.3 6.1l3.2.7-2.2 10.7" />
          </svg>
          <span class="way-shelf-word">{{ $t('parthenon.navArchive') }}</span>
        </router-link>
        <LanguageSwitcher :compact="isNarrow" />
      </div>
    </nav>
  </div>
</template>

<script>
// How many act shells stand at this moment, across instances: one act leaving
// while the next arrives share the night under them.
let shellsStanding = 0
</script>

<script setup>
// The shell every act stands in: one header (the act's name and how it stands,
// the Listen switch and the Web), the threshold scene, the stage, the Web of
// Athens beside it, the scribe's ledger and the Way strip with the shelf and
// the language. Acts pass what they know (status, logs, where earlier acts can
// be revisited, a title for the tab) and put their own work in the default slot.
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, useSlots, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { access, canControl, inviteNeeded } from '../parthenon/access.js'
import { isGatheringId } from '../parthenon/owned.js'
import ParthenonBrand from './ParthenonBrand.vue'
import LanguageSwitcher from './LanguageSwitcher.vue'
import ListenToggle from './ListenToggle.vue'
import { ACTS, stripIds, readable } from '../parthenon/vocabulary.js'
import { sound, setBed } from '../parthenon/sound.js'

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
  ledgerLine: { type: String, default: '' }, // one line in the city's words for the closed ledger
  webDefault: { type: String, default: 'open' }, // 'open' | 'closed': the Web on wide screens before the visitor chooses
  docTitle: { type: String, default: '' }, // the gathering's own title (a Chronicle's), named first in the browser tab
  // How far this gathering really came, when the act was opened without it (a Chronicle
  // not found): stations after it are not passed. Unset, every earlier act counts as passed.
  reached: { type: Number, default: null },
  // False when the act's own page carries the h1 (the Chronicle's title); the act name then stays a line.
  nameHeading: { type: Boolean, default: true }
})

const { t, tm, locale } = useI18n()
const slots = useSlots()

// A guest: on the public steps, at a gathering this browser did not begin.
// The act hides what only its owner may do; the shell says why, once.
const route = useRoute()
const gatheringIds = computed(() =>
  [route.params.projectId, route.params.simulationId, route.params.reportId].filter(isGatheringId)
)
const guest = computed(() => access.public && gatheringIds.value.length > 0 && !canControl(...gatheringIds.value))
// A guest may ask, unless the steps ask for a word this browser has not brought.
const guestAsks = computed(() => !inviteNeeded())

const actInfo = computed(() => ACTS[props.act - 1] || ACTS[0])
const stepName = (n) => {
  const names = tm('main.stepNames')
  return (Array.isArray(names) && names[n - 1]) || ''
}
const actName = computed(() => stepName(props.act))
const actLede = computed(() => {
  if (props.lede) return props.lede
  const movements = tm('parthenon.movements')
  const m = Array.isArray(movements) ? movements[props.act - 1] : null
  return (m && (m.text || m.desc || m.body)) || ''
})
const thresholdStyle = computed(() => ({ '--scene': `url(${props.scene || actInfo.value.scene})` }))

// How the act stands, in the city's words: each act ends on its own word.
const statusLabel = computed(() => {
  if (props.statusText) return props.statusText
  if (props.status === 'done') {
    const done = tm('parthenon.shell.statusDone')
    if (Array.isArray(done) && done[props.act - 1]) return done[props.act - 1]
  }
  return t(`parthenon.shell.status.${props.status}`)
})
const ordinal = computed(() => {
  const words = tm('parthenon.shell.ordinals')
  return Array.isArray(words) ? words[props.act - 1] || String(props.act) : String(props.act)
})

// The browser tab names the act (and the gathering, when the act knows it).
const BRAND = 'Parthenon'
const tabTitle = computed(() => [props.docTitle, actName.value, BRAND].filter(Boolean).join(' · '))
watch(tabTitle, (title) => {
  if (typeof document !== 'undefined' && title) document.title = title
})

// The Web pane
const hasWeb = computed(() => !!slots.web)
const NARROW = '(max-width: 899px)'
const narrowQuery = typeof window !== 'undefined' ? window.matchMedia(NARROW) : null
const isNarrow = ref(narrowQuery ? narrowQuery.matches : false)
// The visitor's choice is remembered per act; until they choose, the act decides.
const WEB_KEY = `parthenon.web.open.${props.act}`
const readPref = () => {
  try {
    const saved = localStorage.getItem(WEB_KEY)
    if (saved) return saved !== 'closed'
  } catch (e) { /* fall through to the act's default */ }
  return props.webDefault !== 'closed'
}
const webVisible = ref(!isNarrow.value && readPref())
provide('parthenonWebSheet', isNarrow)
const webLabel = computed(() => (webVisible.value ? t('parthenon.shell.hideWeb') : t('parthenon.shell.showWeb')))

const webToggleEl = ref(null)
const webPaneEl = ref(null)
const sheetCloseEl = ref(null)
const mainEl = ref(null)
const sheetOpen = computed(() => isNarrow.value && webVisible.value)

const toggleWeb = () => {
  beckon.value = false
  webVisible.value = !webVisible.value
  if (!isNarrow.value) {
    try { localStorage.setItem(WEB_KEY, webVisible.value ? 'open' : 'closed') } catch (e) { /* per-viewer convenience only */ }
  }
}

const closeSheet = () => {
  webVisible.value = false
  nextTick(() => webToggleEl.value?.focus())
}

// On phones the Web is a dialog: focus goes in when it opens, Tab turns round
// inside it, the page behind is inert, and Escape closes it wherever focus is.
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]):not(.sentinel)'
const focusables = () =>
  [...(webPaneEl.value?.querySelectorAll(FOCUSABLE) || [])].filter((el) => el.getClientRects().length && !el.closest('[inert]'))
const wrapFocus = (to) => {
  const list = focusables()
  const target = to === 'first' ? list[0] : list[list.length - 1]
  ;(target || sheetCloseEl.value || webPaneEl.value)?.focus()
}
const onSheetKey = (e) => {
  if (e.key === 'Escape' && sheetOpen.value && !e.defaultPrevented) closeSheet()
}
watch(sheetOpen, async (open) => {
  if (typeof document === 'undefined') return
  if (!open) {
    document.removeEventListener('keydown', onSheetKey)
    return
  }
  document.addEventListener('keydown', onSheetKey)
  await nextTick()
  ;(sheetCloseEl.value || webPaneEl.value)?.focus()
})
const onNarrow = (e) => {
  isNarrow.value = e.matches
  webVisible.value = e.matches ? false : readPref()
}

// The first time a visitor on a phone stands in an act with a Web, its
// switch glows once, so the Web is found and not taken for a button to share.
const beckon = ref(false)
const BECKON_KEY = 'parthenon.web.beckoned'
const maybeBeckon = () => {
  if (!hasWeb.value || !isNarrow.value || webVisible.value) return
  try {
    if (localStorage.getItem(BECKON_KEY)) return
    localStorage.setItem(BECKON_KEY, '1')
  } catch (e) {
    return // no memory: never beckon on every visit
  }
  // After the title card has lifted.
  setTimeout(() => { beckon.value = true }, card.value ? 1700 : 500)
}

// Listen and the Web as two matched squares, each with its word beneath, where
// a wide header would crowd them; the word beside the icon on wide screens.
const COMPACT = '(max-width: 1199px)'
const compactQuery = typeof window !== 'undefined' ? window.matchMedia(COMPACT) : null
const compactTools = ref(compactQuery ? compactQuery.matches : false)
const onCompact = (e) => { compactTools.value = e.matches }

// For the keyboard: the skip link lands on the act itself.
const skipToAct = () => {
  const el = mainEl.value
  if (!el) return
  el.focus({ preventScroll: true })
  const header = document.querySelector('.act-header')?.getBoundingClientRect().height || 64
  const top = el.getBoundingClientRect().top + window.scrollY - header
  window.scrollTo({ top: Math.max(0, top) })
}

// Under the five acts, the night: crickets and a hearth, heard once Listen is
// on. The route lets one act fade out before the next comes in, so the night
// is only let go when, after a breath, no act has come to take it up and
// nothing else (the steps, a film) has asked for another bed meanwhile.
const NIGHT_GRACE_MS = 1200
onMounted(() => {
  compactQuery?.addEventListener('change', onCompact)
  shellsStanding++
  setBed('night')
  if (tabTitle.value) document.title = tabTitle.value
})
onBeforeUnmount(() => {
  compactQuery?.removeEventListener('change', onCompact)
  if (typeof document !== 'undefined') document.removeEventListener('keydown', onSheetKey)
  shellsStanding = Math.max(0, shellsStanding - 1)
  setTimeout(() => {
    if (shellsStanding === 0 && sound.bed === 'night') setBed(null)
  }, NIGHT_GRACE_MS)
})

// The ledger
const ledgerOpen = ref(false)
const ledgerList = ref(null)
watch(ledgerOpen, async (open) => {
  if (!open) return
  await nextTick()
  if (ledgerList.value) ledgerList.value.scrollTop = ledgerList.value.scrollHeight
})
// A line the reader cannot read (the engine's, or one set down before they
// changed language) is not shown to them.
const cleanLogs = computed(() =>
  props.logs
    .map((l) => (typeof l === 'string' ? { time: '', text: l } : { time: l.time || l.timestamp || '', text: l.message ?? l.text ?? '' }))
    .map((l) => ({ time: String(l.time).slice(0, 8), text: readable(stripIds(l.text), '', locale.value) }))
    .filter((l) => l.text)
)
const lastLine = computed(() => cleanLogs.value.length ? cleanLogs.value[cleanLogs.value.length - 1].text : '')

// Stations
const reachedTo = computed(() => (props.reached == null ? props.act - 1 : Math.min(props.reached, props.act - 1)))
const isPassed = (a) => a.n < props.act && a.n <= reachedTo.value
const stationRoute = (a) => (a.n < props.act ? props.links[a.n] || null : a.n === props.act ? null : props.links[a.n] || null)

// The title card shows once per act per visit, and never under reduced motion.
const card = ref(false)
onMounted(() => {
  narrowQuery?.addEventListener('change', onNarrow)
  const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!props.quiet && !reduced) {
    const key = `parthenon.card.${props.act}`
    let seen = false
    try {
      seen = !!sessionStorage.getItem(key)
      if (!seen) sessionStorage.setItem(key, '1')
    } catch (e) { /* show it anyway */ }
    if (!seen) card.value = true
  }
  if (!reduced) maybeBeckon()
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
  clip-path: inset(50%);
  white-space: nowrap;
}

/* Skip link: out of sight until the keyboard reaches it. */
.skip-link {
  position: fixed;
  top: 10px;
  left: 10px;
  z-index: 70;
  padding: 12px 18px;
  background: var(--p-gold);
  color: #1f1a16;
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  font-weight: 600;
  text-decoration: none;
  transform: translateY(-160%);
  transition: transform 0.2s ease;
}

.skip-link:focus-visible {
  transform: none;
  outline: 2px solid var(--p-ink);
  outline-offset: 2px;
}

.stage:focus,
.stage:focus-visible {
  outline: none;
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
  align-items: center;
  min-height: 40px;
}

.act-subject {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  min-width: 0;
  max-width: 100%;
}

.act-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
  max-width: 100%;
  margin: 0;
}

.act-numeral {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  color: var(--p-gold);
}

.act-name {
  min-width: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  color: var(--p-ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1;
}

/* How the act stands: a small inscription under its name. */
.act-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  max-width: 100%;
  font-family: var(--p-font-inscription);
  font-size: 10px;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
  white-space: nowrap;
}

.status-word {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.act-status .dot {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--p-ink-4);
}

.act-status.is-working .dot,
.act-status.is-live .dot {
  background: var(--p-gold);
  box-shadow: 0 0 0 3px var(--p-terracotta-tint);
  animation: pulse 1.6s ease-in-out infinite;
}

.act-status.is-done .dot { background: var(--p-olive); }
.act-status.is-error .dot { background: var(--p-error); }
.act-status.is-error { color: var(--p-ink-2); }

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 2px var(--p-terracotta-tint); }
  50% { box-shadow: 0 0 0 6px transparent; }
}

.act-tools {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: 12px;
}

/* The Web's switch, dressed like Listen beside it. */
.web-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 14px;
  background: transparent;
  border: 1px solid var(--p-control-border);
  color: var(--p-ink-2);
  font-family: var(--p-font-inscription);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease, background 0.2s ease;
}

.wt-mark { flex-shrink: 0; }

.web-toggle:hover {
  border-color: var(--p-gold);
  color: var(--p-ink);
}

.web-toggle[aria-pressed='true'] {
  background: var(--p-terracotta-tint);
  border-color: var(--p-gold);
  color: var(--p-gold);
}

/* Compact: a 44px square, the stars over their word. */
.web-toggle.compact {
  flex-direction: column;
  justify-content: center;
  gap: 3px;
  width: 44px;
  min-width: 44px;
  height: 44px;
  min-height: 44px;
  padding: 0;
}

.web-toggle.compact .wt-label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.wt-caption {
  font-family: var(--p-font-body);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.web-toggle.beckon {
  animation: beckon 1.3s ease-out 2;
}

@keyframes beckon {
  0% { box-shadow: 0 0 0 0 rgba(240, 182, 96, 0.55); border-color: var(--p-gold); color: var(--p-gold); }
  70% { box-shadow: 0 0 0 12px rgba(240, 182, 96, 0); }
  100% { box-shadow: 0 0 0 0 rgba(240, 182, 96, 0); }
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

.web-pane:focus { outline: none; }

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

.sentinel {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
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

/* A guest's one line, under the threshold */
.guest-line {
  margin-top: 16px;
  margin-bottom: 4px;
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
  min-height: 40px;
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
  height: calc(var(--p-way-h) + env(safe-area-inset-bottom, 0px));
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
  min-width: 0;
}

.way-station + .way-station::before {
  content: '';
  flex: 0 1 clamp(16px, 3vw, 40px);
  width: clamp(16px, 3vw, 40px);
  min-width: 4px;
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
  min-width: 0;
  padding: 10px 2px;
  line-height: 20px;
  text-decoration: none;
  color: #969085; /* stations yet to come: 4.8:1 on the strip */
  white-space: nowrap;
}

.way-numeral {
  flex-shrink: 0;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
}

.way-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 500;
}

.way-station.linked .way-link { color: var(--p-ink-3); }
.way-station.passed .way-link { color: var(--p-ink-2); }
.way-station.linked .way-link:hover { color: var(--p-gold); }
.way-station.current .way-link { color: var(--p-gold); }

.way-tools {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 18px;
}

.way-shelf {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 4px;
  color: var(--p-ink-3);
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;
}

.way-shelf:hover { color: var(--p-gold); }

@media (max-width: 1199px) {
  .act-tools { gap: 10px; }
}

/* Between the phone and the wide screen, the other stations keep their
   numerals and give their names to the one you stand at. */
@media (max-width: 1149px) {
  .way-station:not(.current) .way-name {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .way-station:not(.current) .way-link { min-width: 40px; justify-content: center; }
}

@media (max-width: 899px) {
  /* The name and its standing on the left; Listen and the Web on the right. */
  .act-header {
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 12px;
    padding: 0 16px;
  }

  .act-subject { align-items: flex-start; gap: 6px; }
  .act-name { font-size: var(--t-lg); }
  .act-brand { min-width: 40px; }
  .ledger { display: none; }
  .threshold { min-height: 160px; padding: 28px 16px 22px; }
  .th-name { font-size: var(--t-2xl); }
  .th-lede { font-size: var(--t-md); }
  .way { padding-inline: 12px; gap: 8px; }
  /* The five stations spread across the strip, up to the shelf. */
  .way-list { flex: 1 1 auto; }
  .way-station + .way-station { flex: 1 1 auto; }
  .way-station + .way-station::before { flex: 1 1 12px; width: auto; max-width: 44px; margin: 0 3px; }
  .way-link { padding: 12px 8px; min-width: 40px; justify-content: center; }
  .way-tools { gap: 6px; }
  .way-shelf { justify-content: center; width: 44px; height: 44px; padding: 0; }
  .way-shelf-word {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .ledger-bar { padding-inline: 16px; }
  .ledger-list { padding-inline: 16px; }
}

/* On a phone the header names the act; the Way keeps five numerals, with
   their names for the ear and on a long press. */
@media (max-width: 599px) {
  .way-station.current .way-name {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .way-station.current .way-link {
    position: relative;
  }
  .way-station.current .way-link::after {
    content: '';
    position: absolute;
    left: 50%;
    bottom: 6px;
    width: 14px;
    height: 1.5px;
    margin-left: -7px;
    background: currentColor;
  }
}

@media (max-width: 480px) {
  .act-header { gap: 10px; }
  .act-status { letter-spacing: 0.08em; }
  .act-brand :deep(.p-brand-word) { display: none; }
  /* The numeral stands in the Way below and on the threshold; here the name needs the room. */
  .act-numeral { display: none; }
  .act-name { font-size: 18px; }
  .act-tools { gap: 8px; }
}

@media (max-width: 359px) {
  .way { padding-inline: 8px; }
  .way-link,
  .way-station:not(.current) .way-link { padding-inline: 4px; min-width: 36px; }
  .way-station + .way-station::before { flex-basis: 4px; min-width: 2px; margin: 0; }
  .act-status { letter-spacing: 0.04em; }
}

@media (prefers-reduced-motion: reduce) {
  .web-toggle.beckon { animation: none; }
  .skip-link { transition: none; }
}
</style>
