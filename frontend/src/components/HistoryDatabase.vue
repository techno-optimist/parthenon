<template>
  <section class="chronicles" :aria-labelledby="titleId">
    <header class="shelf-head">
      <p class="p-eyebrow">{{ $t('parthenon.chronicles.eyebrow') }}</p>
      <h2 :id="titleId" class="shelf-title">{{ $t('history.title') }}</h2>
      <p class="shelf-lede">{{ $t('parthenon.chronicles.lede') }}</p>
    </header>

    <p v-if="loading" class="shelf-note" role="status">{{ $t('history.loadingText') }}</p>
    <p v-else-if="!tablets.length" class="shelf-note">{{ $t('parthenon.chronicles.empty') }}</p>

    <ul v-else class="shelf" role="list">
      <li v-for="tablet in tablets" :key="tablet.id" class="shelf-cell">
        <button type="button" class="tablet" :class="{ live: tablet.state === 'live' }" @click="open(tablet)">
          <span class="tablet-plate" :style="{ '--plate': tablet.tone }">
            <img v-if="tablet.image" :src="tablet.image" alt="" loading="lazy" decoding="async" />
            <span v-else class="tablet-letter" aria-hidden="true">{{ tablet.letter }}</span>
            <span v-if="tablet.film" class="tablet-film">{{ $t('parthenon.chronicles.film') }}</span>
          </span>
          <span class="tablet-body">
            <span class="tablet-meta">
              <span v-if="tablet.era" class="tablet-era">{{ tablet.era }}</span>
              <time :datetime="tablet.iso">{{ tablet.date }}</time>
            </span>
            <span class="tablet-title">{{ tablet.title }}</span>
            <span class="tablet-question">{{ tablet.question }}</span>
            <span class="tablet-status" :class="tablet.state">
              <span class="dot" aria-hidden="true"></span>
              <span class="status-word">{{ tablet.word }}</span>
              <span class="status-text">{{ tablet.status }}</span>
            </span>
          </span>
        </button>
      </li>
    </ul>

    <!-- One gathering, held up: its question and the stations you can revisit -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="selected" class="modal-overlay" @click.self="closeModal">
          <div
            ref="modalContent"
            class="modal-content"
            role="dialog"
            aria-modal="true"
            :aria-labelledby="modalTitleId"
            tabindex="-1"
          >
            <header class="modal-head">
              <span class="modal-plate" :style="{ '--plate': selected.tone }" aria-hidden="true">
                <img v-if="selected.image" :src="selected.image" alt="" />
                <span v-else class="tablet-letter">{{ selected.letter }}</span>
              </span>
              <div class="modal-title-block">
                <p class="tablet-meta">
                  <span v-if="selected.era" class="tablet-era">{{ selected.era }}</span>
                  <time :datetime="selected.iso">{{ selected.date }}</time>
                </p>
                <h3 :id="modalTitleId" class="modal-title">{{ selected.title }}</h3>
                <p class="tablet-status" :class="selected.state">
                  <span class="dot" aria-hidden="true"></span>
                  <span class="status-word">{{ selected.word }}</span>
                  <span class="status-text">{{ selected.status }}</span>
                </p>
              </div>
              <button
                ref="modalCloseBtn"
                type="button"
                class="modal-close"
                :aria-label="$t('common.close')"
                @click="closeModal"
              ><span aria-hidden="true">×</span></button>
            </header>

            <div class="modal-body">
              <p class="p-eyebrow">{{ $t('parthenon.chronicles.question') }}</p>
              <p class="modal-question">{{ selected.question || $t('common.none') }}</p>
            </div>

            <div class="modal-revisit">
              <p class="p-eyebrow">{{ $t('parthenon.chronicles.revisit') }}</p>
              <ol class="modal-actions" role="list">
                <li v-for="station in stations" :key="station.n" class="modal-action">
                  <button
                    type="button"
                    class="p-button secondary station-link"
                    :class="{ live: station.live }"
                    :disabled="!station.enabled"
                    @click="visit(station)"
                  >
                    <span class="station-numeral" aria-hidden="true">{{ station.numeral }}</span>
                    <span class="station-name">{{ station.name }}</span>
                    <span v-if="station.live" class="station-live" aria-hidden="true"></span>
                  </button>
                </li>
              </ol>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup>
// The Chronicles: a shelf of every gathering the city has held. Each tablet
// shows the film poster or the speaker's face, the Chronicle's title, the
// question, the era, one status sentence and the date. The record comes from
// the history payload; the newer fields (report_title, report_status,
// question, film) are used when present and worked around when not.
import { ref, computed, onMounted, onUnmounted, onActivated, watch, nextTick, useId } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getSimulationHistory } from '../api/simulation'
import { speakers } from '../parthenon/speakers.js'
import { arrivals } from '../parthenon/arrivals/index.js'
import { ACTS, RUN_LENGTHS } from '../parthenon/vocabulary.js'

const router = useRouter()
const route = useRoute()
const { t, tm, locale } = useI18n()

const uid = `chronicles-${useId()}`
const titleId = `${uid}-title`
const modalTitleId = `${uid}-modal-title`

const projects = ref([])
const loading = ref(true)
const selected = ref(null)
const modalContent = ref(null)
const modalCloseBtn = ref(null)
let lastFocused = null

const stepNames = computed(() => tm('main.stepNames') || [])

// Warm darks for a plate before its image arrives, or when it has none.
const TONES = ['#2b2019', '#1e2431', '#2d2126', '#1f2a27', '#332616', '#252030', '#2a2418', '#1c2632']

const dateFormat = computed(() => {
  try {
    return new Intl.DateTimeFormat(locale.value, { day: 'numeric', month: 'long', year: 'numeric' })
  } catch {
    return null
  }
})

const formatDate = (value) => {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 10)
  return dateFormat.value ? dateFormat.value.format(d) : d.toLocaleDateString()
}

// A title from the question when the Chronicle has none: the first clause,
// cut at a comma or a period, never longer than about seventy letters.
const titleFromQuestion = (text) => {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  if (!clean) return t('parthenon.chronicles.untitled')
  const first = clean.split(/(?<=[.?!])\s/)[0]
  if (first.length <= 72) return first.replace(/[.?!]$/, '')
  const cut = first.slice(0, 72)
  const at = Math.max(cut.lastIndexOf(','), cut.lastIndexOf(' '))
  return `${cut.slice(0, at > 30 ? at : 72).replace(/[,\s]+$/, '')}…`
}

const filmMade = (film) => !!film && (film.status === 'completed' || !!film.poster_url)

// The city keeps time in hours and days, never in rounds. A run's rounds are
// spread over its hours in the city (total_simulation_hours); when the record
// has no hours, a story-sized length with the same round count supplies them,
// and failing that a round is taken as an hour.
const spanOf = (p) => {
  const currentRounds = Math.max(0, Number(p.current_round) || 0)
  const totalRounds = Math.max(0, Number(p.total_rounds) || 0)
  const known = RUN_LENGTHS.find((l) => l.rounds === totalRounds)
  const totalHours = Number(p.total_simulation_hours) || known?.hours || totalRounds
  const currentHours = totalRounds ? (Math.min(currentRounds, totalRounds) / totalRounds) * totalHours : 0
  const over = currentRounds >= totalRounds && totalRounds > 0
  const inDays = totalHours >= 48
  const per = inDays ? 24 : 1
  const total = Math.max(1, Math.round(totalHours / per))
  let current = Math.round(currentHours / per)
  if (currentRounds > 0) current = Math.max(1, current)
  // A run that stopped early never reads as if it went the distance.
  if (!over && current >= total) current = Math.max(1, total - 1)
  if (over) current = total
  return { current, total, over, inDays, begun: currentRounds > 0 }
}

// One sentence in words: where the run got to, what has been written, what
// has been filmed. Beside it, the shell's status word for the dot.
const statusOf = (p) => {
  const runner = String(p.runner_status || '').toLowerCase()
  const live = ['running', 'starting', 'paused', 'stopping'].includes(runner) || p.status === 'running'
  const failed = runner === 'failed' || p.status === 'failed' || (!!p.error && !live)
  const span = spanOf(p)
  const unit = span.inDays ? 'Days' : 'Hours'
  const parts = []
  if (live) parts.push(t(`parthenon.chronicles.status.live${unit}`, { current: Math.max(1, span.current), total: span.total }))
  else if (!span.begun) parts.push(t(failed ? 'parthenon.chronicles.status.troubleEarly' : 'parthenon.chronicles.status.notStarted'))
  else if (span.over) parts.push(t(`parthenon.chronicles.status.argued${unit}`, { total: span.total }, span.total))
  else parts.push(t(`parthenon.chronicles.status.stopped${unit}`, { current: span.current, total: span.total }))
  if (p.report_id) {
    const writing = p.report_status && !['completed', 'done', 'finished'].includes(String(p.report_status).toLowerCase())
    parts.push(t(writing ? 'parthenon.chronicles.status.chronicleWriting' : 'parthenon.chronicles.status.chronicleWritten'))
  }
  if (filmMade(p.film)) parts.push(t('parthenon.chronicles.status.filmMade'))
  const state = live ? 'live' : failed ? 'error' : span.begun ? 'done' : 'idle'
  const word = t(`parthenon.shell.status.${state === 'idle' ? 'ready' : state}`)
  return { text: parts.join(', '), state, word }
}

const toTablet = (p, i) => {
  const seed = p.files?.[0]?.filename || ''
  const speaker = speakers.find((s) => s.fileName === seed)
  const arrival = arrivals.find((a) => a.fileName === seed)
  const question = p.question || p.simulation_requirement || ''
  const poster = p.film?.poster_url || ''
  const image = poster || (arrival ? `/media/scenes/arrival-${arrival.id}.jpg` : speaker ? `/media/portraits/${speaker.id}.jpg` : '')
  const status = statusOf(p)
  return {
    id: p.simulation_id,
    projectId: p.project_id || '',
    simulationId: p.simulation_id,
    reportId: p.report_id || '',
    title: p.report_title || arrival?.title || (speaker ? `${speaker.name}, ${speaker.work}` : titleFromQuestion(question)),
    question,
    era: speaker?.year || arrival?.year || '',
    letter: speaker?.letter || arrival?.letter || (question.trim().charAt(0) || 'Σ').toUpperCase(),
    image,
    film: filmMade(p.film),
    tone: TONES[i % TONES.length],
    iso: p.created_at || '',
    date: formatDate(p.created_at),
    status: status.text,
    state: status.state,
    word: status.word
  }
}

const tablets = computed(() => projects.value.map(toTablet))

const open = (tablet) => {
  lastFocused = document.activeElement
  selected.value = tablet
}

// Close, and give focus back to the tablet that opened it.
const closeModal = () => {
  selected.value = null
  const target = lastFocused
  lastFocused = null
  if (target && typeof target.focus === 'function' && document.contains(target)) {
    target.focus()
  }
}

// Esc closes; Tab stays inside the dialog.
const onModalKeydown = (event) => {
  if (!selected.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeModal()
    return
  }
  if (event.key !== 'Tab' || !modalContent.value) return
  const focusable = Array.from(
    modalContent.value.querySelectorAll('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')
  )
  if (focusable.length === 0) {
    event.preventDefault()
    modalContent.value.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (!modalContent.value.contains(active)) {
    event.preventDefault()
    first.focus()
  } else if (event.shiftKey && (active === first || active === modalContent.value)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(selected, async (value, oldValue) => {
  if (value && !oldValue) {
    document.addEventListener('keydown', onModalKeydown)
    await nextTick()
    ;(modalCloseBtn.value || modalContent.value)?.focus()
  } else if (!value && oldValue) {
    document.removeEventListener('keydown', onModalKeydown)
  }
})

// The five stations of the Way, in order, each a link back into that act of
// this gathering. The Agora opens a finished run in replay and a live one as
// it happens; it never starts a run by being opened.
const stations = computed(() => {
  const s = selected.value
  if (!s) return []
  const names = stepNames.value
  const live = s.state === 'live'
  const routes = [
    { name: 'Process', params: { projectId: s.projectId }, enabled: !!s.projectId },
    { name: 'Simulation', params: { simulationId: s.simulationId }, enabled: !!s.simulationId },
    { name: 'SimulationRun', params: { simulationId: s.simulationId }, enabled: !!s.simulationId, live },
    { name: 'Report', params: { reportId: s.reportId }, enabled: !!s.reportId },
    { name: 'Interaction', params: { reportId: s.reportId }, enabled: !!s.reportId }
  ]
  return ACTS.map((act, i) => ({
    n: act.n,
    numeral: act.numeral,
    name: routes[i].live ? t('parthenon.chronicles.watchLive') : names[i] || '',
    enabled: routes[i].enabled,
    live: !!routes[i].live,
    to: { name: routes[i].name, params: routes[i].params }
  }))
})

const visit = (station) => {
  if (!station?.enabled) return
  router.push(station.to)
  closeModal()
}

const loadHistory = async () => {
  try {
    loading.value = true
    const response = await getSimulationHistory(20)
    if (response.success) {
      projects.value = Array.isArray(response.data) ? response.data : []
    }
  } catch (error) {
    projects.value = []
  } finally {
    loading.value = false
  }
}

// Coming back to the home page reloads the shelf.
watch(() => route.path, (newPath) => {
  if (newPath === '/') loadHistory()
})

onMounted(loadHistory)
onActivated(loadHistory)

onUnmounted(() => {
  document.removeEventListener('keydown', onModalKeydown)
})
</script>

<style scoped>
.chronicles {
  position: relative;
  width: 100%;
  min-width: 0;
}

.shelf-head {
  max-width: 720px;
  margin-bottom: 32px;
}

.shelf-head .p-eyebrow {
  margin: 0 0 14px;
}

.shelf-title {
  margin: 0 0 12px;
  font-family: var(--p-font-display);
  font-weight: 500;
  font-size: clamp(36px, 4.4vw, 60px);
  line-height: 1.04;
  letter-spacing: -0.01em;
  color: var(--p-ink);
}

.shelf-lede {
  margin: 0;
  max-width: 60ch;
  font-family: var(--p-font-serif);
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.shelf-note {
  margin: 0;
  padding: 36px 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

/* The shelf: a static grid of tablets */
.shelf {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 28px 24px;
  margin: 0;
  padding: 0;
}

.shelf-cell {
  min-width: 0;
}

.tablet {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  padding: 0;
  border: 1px solid var(--p-line);
  background: var(--p-surface);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.25s ease, transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.35s ease;
}

.tablet:hover {
  border-color: var(--p-line-strong);
  transform: translateY(-3px);
  box-shadow: var(--p-shadow-2);
}

.tablet.live {
  border-color: rgba(240, 182, 96, 0.5);
}

.tablet-plate,
.modal-plate {
  position: relative;
  display: grid;
  place-items: center;
  overflow: hidden;
  background: var(--plate, var(--p-surface-2));
}

.tablet-plate {
  width: 100%;
  aspect-ratio: 16 / 10;
}

.tablet-plate img,
.modal-plate img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 30%;
  filter: saturate(0.9);
  transition: transform 1.2s cubic-bezier(0.22, 1, 0.36, 1);
}

.tablet:hover .tablet-plate img {
  transform: scale(1.04);
}

.tablet-letter {
  font-family: var(--p-font-display);
  font-size: var(--t-3xl);
  color: var(--p-gold);
  opacity: 0.8;
}

.tablet-film {
  position: absolute;
  right: 12px;
  top: 12px;
  padding: 4px 10px;
  background: rgba(11, 14, 19, 0.8);
  border: 1px solid rgba(240, 182, 96, 0.5);
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-gold);
}

.tablet-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px 20px 20px;
  min-width: 0;
}

.tablet-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin: 0;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.tablet-era {
  color: var(--p-gold);
}

.tablet-title {
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.12;
  color: var(--p-ink);
  text-wrap: balance;
}

.tablet-question {
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* The dot, its status word in the inscription face, then the sentence */
.tablet-status {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  margin: 6px 0 0;
  font-size: var(--t-xs);
  line-height: 1.45;
  color: var(--p-ink-2);
}

.tablet-status .dot {
  flex-shrink: 0;
  align-self: center;
  width: 8px;
  height: 8px;
  border-radius: var(--p-radius-coin);
  background: var(--p-ink-4);
}

.status-word {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.status-text {
  min-width: 0;
  color: var(--p-ink-2);
}

.tablet-status.done .dot {
  background: var(--p-olive);
}

.tablet-status.done .status-word {
  color: var(--p-olive);
}

.tablet-status.error .dot {
  background: var(--p-error);
}

.tablet-status.error .status-word {
  color: var(--p-error);
}

.tablet-status.live .dot,
.station-live {
  background: var(--p-gold);
  box-shadow: 0 0 0 4px var(--p-terracotta-tint);
  animation: pulse 1.6s ease-in-out infinite;
}

.tablet-status.live .status-word {
  color: var(--p-gold);
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 3px var(--p-terracotta-tint); }
  50% { box-shadow: 0 0 0 7px transparent; }
}

@media (prefers-reduced-motion: reduce) {
  .tablet-status.live .dot,
  .station-live {
    animation: none;
  }

  .tablet,
  .tablet-plate img,
  .modal-plate img {
    transition: none;
  }

  .tablet:hover {
    transform: none;
  }

  .tablet:hover .tablet-plate img {
    transform: none;
  }
}

/* The gathering, held up */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(11, 14, 19, 0.72);
  backdrop-filter: blur(6px);
}

.modal-content {
  width: 640px;
  max-width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--p-surface);
  border: 1px solid var(--p-line-strong);
  box-shadow: var(--p-shadow-2);
}

.modal-content:focus {
  outline: none;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-content {
  transition: transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.35s ease;
}

.modal-leave-active .modal-content {
  transition: transform 0.2s ease-in, opacity 0.2s ease-in;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: translateY(10px);
  opacity: 0;
}

.modal-head {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) auto;
  gap: 18px;
  align-items: start;
  padding: 24px 24px 20px;
  border-bottom: 1px solid var(--p-line);
}

.modal-plate {
  width: 96px;
  aspect-ratio: 4 / 5;
}

.modal-plate .tablet-letter {
  font-size: var(--t-2xl);
}

.modal-title-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.modal-title {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.12;
  color: var(--p-ink);
}

.modal-close {
  width: 40px;
  height: 40px;
  border: 1px solid transparent;
  background: transparent;
  font-size: 26px;
  line-height: 1;
  color: var(--p-ink-3);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.2s ease, border-color 0.2s ease;
}

.modal-close:hover {
  color: var(--p-ink);
  border-color: var(--p-line-strong);
}

.modal-body {
  padding: 22px 24px;
}

.modal-body .p-eyebrow,
.modal-revisit .p-eyebrow {
  margin: 0 0 10px;
}

.modal-question {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
}

.modal-revisit {
  padding: 4px 24px 24px;
}

/* The five stations of the Way, one under the other, a path drawn between them */
.modal-actions {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.modal-actions::before {
  content: '';
  position: absolute;
  left: 31px;
  top: 26px;
  bottom: 26px;
  width: 1px;
  background: linear-gradient(to bottom, var(--p-gold), var(--p-line-strong));
  opacity: 0.55;
  pointer-events: none;
}

.modal-action {
  min-width: 0;
}

.station-link {
  position: relative;
  width: 100%;
  justify-content: flex-start;
  gap: 14px;
  min-height: 52px;
  padding-inline: 18px;
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 500;
}

/* A small coin, as on the Way, so the path runs behind it rather than through it */
.station-numeral {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: var(--p-radius-coin);
  border: 1px solid var(--p-line-strong);
  background: var(--p-surface);
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: 0;
  text-indent: 0.1em;
  color: var(--p-gold);
}

.station-link:hover .station-numeral {
  border-color: var(--p-gold);
}

.station-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.station-live {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  margin-left: auto;
  border-radius: var(--p-radius-coin);
}

.station-link.live {
  border-color: rgba(240, 182, 96, 0.5);
}

.station-link:disabled .station-numeral {
  color: var(--p-ink-4);
}

@media (max-width: 640px) {
  .modal-head {
    grid-template-columns: 72px minmax(0, 1fr) auto;
    gap: 14px;
    padding: 18px 16px 16px;
  }

  .modal-plate {
    width: 72px;
  }

  .modal-body,
  .modal-revisit {
    padding-inline: 16px;
  }
}
</style>
