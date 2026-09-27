<template>
  <section
    class="chronicles"
    :class="`mode-${mode}`"
    :aria-labelledby="page ? undefined : titleId"
    :aria-label="page ? $t('history.title') : undefined"
  >
    <!-- On the home page: the shelf's own head -->
    <header v-if="!page" class="shelf-head">
      <p class="p-eyebrow">{{ $t('parthenon.chronicles.eyebrow') }}</p>
      <h2 :id="titleId" class="shelf-title">{{ $t('history.title') }}</h2>
      <p class="shelf-lede">{{ $t('parthenon.chronicles.lede') }}</p>
    </header>

    <!-- In the Chronicles: what is on the shelf, a search and the kinds -->
    <div v-if="page && groups.length" class="shelf-tools">
      <p class="shelf-count">{{ summary }}</p>
      <div class="tools-row">
        <label class="find">
          <span class="visually-hidden">{{ $t('parthenon.chronicles.find') }}</span>
          <svg class="find-icon" viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
            <circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4" />
            <path d="m12.6 12.6 4.4 4.4" stroke="currentColor" stroke-width="1.4" />
          </svg>
          <input
            v-model="query"
            class="find-input"
            type="search"
            enterkeyhint="search"
            autocomplete="off"
            :placeholder="$t('parthenon.chronicles.findPlaceholder')"
          />
        </label>
        <div class="filters" role="group" :aria-label="$t('parthenon.chronicles.filters')">
          <button
            v-for="f in filterOptions"
            :key="f.id"
            type="button"
            class="filter"
            :class="`filter-${f.id}`"
            :aria-pressed="filter === f.id ? 'true' : 'false'"
            @click="filter = f.id"
          >
            <span>{{ f.label }}</span>
            <span class="filter-n" aria-hidden="true">{{ f.count }}</span>
          </button>
        </div>
      </div>
    </div>

    <div v-if="loading && !projects.length" class="shelf-waiting" role="status">
      <span class="visually-hidden">{{ $t('parthenon.chronicles.loading') }}</span>
      <ul class="shelf" aria-hidden="true">
        <li v-for="i in 3" :key="i" class="shelf-cell">
          <span class="tablet ghost">
            <span class="tablet-plate"></span>
            <span class="tablet-body">
              <span class="ghost-line short"></span>
              <span class="ghost-line"></span>
              <span class="ghost-line"></span>
            </span>
          </span>
        </li>
      </ul>
    </div>

    <div v-else-if="failed && !projects.length" class="shelf-note">
      <p>{{ $t('parthenon.chronicles.unreachable') }}</p>
      <button type="button" class="p-button secondary small" @click="loadHistory">{{ $t('parthenon.chronicles.retry') }}</button>
    </div>

    <p v-else-if="!groups.length" class="shelf-note">{{ $t('parthenon.chronicles.empty') }}</p>

    <div v-else-if="!shown.length" class="shelf-note">
      <p>{{ $t('parthenon.chronicles.noMatch') }}</p>
      <button type="button" class="p-button secondary small" @click="clearFind">{{ $t('parthenon.chronicles.clear') }}</button>
    </div>

    <ul v-else class="shelf" role="list">
      <li
        v-for="g in shown"
        :key="g.key"
        class="shelf-cell"
        :class="{ stacked: g.nights.length > 1, deep: g.nights.length > 2 }"
      >
        <component
          :is="page ? 'button' : 'router-link'"
          v-bind="page ? { type: 'button' } : { to: gatheringLink(g.lead) }"
          class="tablet"
          :class="{ live: g.live, heard: g.heardOnly }"
          :data-group="g.key"
          :aria-labelledby="tabletId(g, 'title')"
          :aria-describedby="`${tabletId(g, 'meta')} ${tabletId(g, 'status')}`"
          v-on="page ? { click: () => openGroup(g) } : {}"
        >
          <span class="tablet-plate" :style="{ '--plate': g.tone }">
            <img
              v-if="plateImage(g.lead)"
              :src="plateImage(g.lead)"
              alt=""
              loading="lazy"
              decoding="async"
              @error="markBroken(plateImage(g.lead))"
            />
            <span v-else class="tablet-letter" aria-hidden="true">{{ g.lead.letter }}</span>
            <span v-if="g.live" class="tablet-lit"><span class="dot" aria-hidden="true"></span>{{ $t('parthenon.chronicles.word.live') }}</span>
            <span v-if="g.lead.film" class="tablet-film">{{ $t('parthenon.chronicles.film') }}</span>
            <span v-if="g.nights.length > 1" class="tablet-nights">
              {{ $t('parthenon.chronicles.nights', { n: g.nights.length }, g.nights.length) }}
            </span>
          </span>
          <span class="tablet-body">
            <span :id="tabletId(g, 'meta')" class="tablet-meta">
              <span v-if="g.lead.era" class="tablet-era">{{ g.lead.era }}</span>
              <time :datetime="g.lead.iso">{{ g.lead.date }}</time>
            </span>
            <span :id="tabletId(g, 'title')" class="tablet-title" :lang="textLang(g.lead.title)">{{ g.lead.title }}</span>
            <span v-if="g.lead.question" class="tablet-question" :lang="textLang(g.lead.question)" aria-hidden="true">{{ g.lead.question }}</span>
            <span :id="tabletId(g, 'status')" class="tablet-status" :class="g.lead.state">
              <span class="dot" aria-hidden="true"></span>
              <span class="status-word">{{ g.lead.word }}</span>
              <span class="status-text">{{ g.lead.status }}</span>
            </span>
          </span>
        </component>
      </li>
    </ul>

    <div v-if="!page && groups.length" class="shelf-foot">
      <router-link :to="{ name: 'Chronicles' }" class="p-button secondary see-all">
        <span>{{ $t('parthenon.chronicles.seeAll') }}</span>
        <span class="see-all-arrow" aria-hidden="true">→</span>
      </router-link>
    </div>

    <!-- One gathering, held up: its question, a filmstrip of its acts, its other nights -->
    <Teleport to="body">
      <Transition name="panel">
        <div v-if="page && panelGroup && night" class="panel-overlay" @click.self="closePanel">
          <div
            ref="panelEl"
            class="panel"
            role="dialog"
            aria-modal="true"
            :aria-labelledby="panelTitleId"
            tabindex="-1"
          >
            <header class="panel-banner" :class="{ live: night.live }" :style="{ '--plate': panelGroup.tone }">
              <img v-if="plateImage(night)" :src="plateImage(night)" alt="" @error="markBroken(plateImage(night))" />
              <span v-else class="tablet-letter banner-letter" aria-hidden="true">{{ night.letter }}</span>
              <span class="banner-shade" aria-hidden="true"></span>
              <button
                ref="panelCloseBtn"
                type="button"
                class="panel-close"
                :aria-label="$t('common.close')"
                @click="closePanel"
              >
                <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                  <path d="M5 5l10 10M15 5 5 15" stroke="currentColor" stroke-width="1.6" />
                </svg>
              </button>
              <div class="banner-copy">
                <p class="tablet-meta">
                  <span v-if="night.era" class="tablet-era">{{ night.era }}</span>
                  <time :datetime="night.iso">{{ night.dateTime }}</time>
                </p>
                <h2 :id="panelTitleId" class="panel-title" :lang="textLang(night.title)">{{ night.title }}</h2>
                <p class="tablet-status" :class="night.state">
                  <span class="dot" aria-hidden="true"></span>
                  <span class="status-word">{{ night.word }}</span>
                  <span class="status-text">{{ night.status }}</span>
                </p>
              </div>
            </header>

            <div class="panel-body">
              <section v-if="night.question" class="panel-question">
                <p class="p-eyebrow">{{ $t('parthenon.chronicles.question') }}</p>
                <p class="panel-question-text" :lang="textLang(night.question)">{{ night.question }}</p>
              </section>

              <section class="panel-strip" :aria-labelledby="stripTitleId">
                <p :id="stripTitleId" class="p-eyebrow">{{ $t('parthenon.chronicles.strip') }}</p>
                <ol class="filmstrip" role="list">
                  <li v-for="f in frames" :key="f.key" class="frame-cell">
                    <component
                      :is="f.to ? 'router-link' : 'div'"
                      :to="f.to || undefined"
                      class="frame"
                      :class="[`is-${f.state}`, `frame-${f.key}`]"
                      :aria-disabled="f.to ? undefined : 'true'"
                    >
                      <span class="frame-image" :style="{ '--frame': f.background }">
                        <span class="frame-numeral" aria-hidden="true">{{ f.numeral }}</span>
                        <svg v-if="f.key === 'film' && !f.image" class="frame-reel" viewBox="0 0 40 40" aria-hidden="true">
                          <circle cx="20" cy="20" r="15" fill="none" stroke="currentColor" stroke-width="1.2" />
                          <circle cx="20" cy="20" r="2.5" fill="currentColor" />
                          <circle cx="20" cy="11" r="4" fill="none" stroke="currentColor" stroke-width="1.1" />
                          <circle cx="20" cy="29" r="4" fill="none" stroke="currentColor" stroke-width="1.1" />
                          <circle cx="11" cy="20" r="4" fill="none" stroke="currentColor" stroke-width="1.1" />
                          <circle cx="29" cy="20" r="4" fill="none" stroke="currentColor" stroke-width="1.1" />
                        </svg>
                        <span v-if="f.state === 'live'" class="frame-lit" aria-hidden="true"></span>
                        <span v-if="f.key === 'crowd' && crowd.length" class="frame-faces" aria-hidden="true">
                          <CitizenCoin
                            v-for="c in crowd"
                            :key="c.name"
                            :name="c.name"
                            :type="c.type"
                            :portrait="c.portrait"
                            size="sm"
                          />
                        </span>
                      </span>
                      <span class="frame-caption">
                        <span class="frame-name">{{ f.name }}</span>
                        <span class="frame-line">{{ f.line }}</span>
                      </span>
                    </component>
                  </li>
                </ol>
              </section>

              <section v-if="panelGroup.nights.length > 1" class="panel-nights" :aria-labelledby="nightsTitleId">
                <p :id="nightsTitleId" class="p-eyebrow">{{ $t('parthenon.chronicles.nightsOfStage') }}</p>
                <ul class="nights" role="list">
                  <li v-for="n in panelGroup.nights" :key="n.id">
                    <button
                      type="button"
                      class="night"
                      :class="[n.state, { current: n.id === night.id }]"
                      :aria-pressed="n.id === night.id ? 'true' : 'false'"
                      @click="chooseNight(n)"
                    >
                      <span class="dot" aria-hidden="true"></span>
                      <span class="night-when"><time :datetime="n.iso">{{ n.dateTime }}</time></span>
                      <span class="night-status">
                        <span class="status-word">{{ n.word }}</span>
                        <span class="status-text">{{ n.status }}</span>
                      </span>
                    </button>
                  </li>
                </ul>
              </section>

              <footer class="panel-foot">
                <router-link class="p-button" :to="gatheringLink(night)">
                  <span>{{ $t('parthenon.chronicles.returnTo') }}</span>
                  <span aria-hidden="true">→</span>
                </router-link>
                <button type="button" class="p-button secondary" @click="copyLink(night)">
                  {{ copyState === 'copied' ? $t('parthenon.chronicles.copied') : $t('parthenon.chronicles.copyLink') }}
                </button>
                <span class="visually-hidden" aria-live="polite">{{ copyNote }}</span>
              </footer>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup>
// The Chronicles: a shelf of every gathering the city has held. Each tablet
// shows the film poster or the stage's image, the Chronicle's title, the
// question, the era, one status sentence and the date. Re-runs of the same
// stage stand together as one tablet with its nights.
//
// mode 'shelf' (the home page): the newest few, each tablet a permanent link
// to /gathering/<id>, and a way to every Chronicle.
// mode 'page' (/chronicles): every gathering, found by word or kind, and each
// tablet opens a filmstrip of its acts.
import { ref, reactive, computed, onMounted, onUnmounted, onActivated, onDeactivated, watch, nextTick, useId } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import CitizenCoin from './CitizenCoin.vue'
import { getSimulationHistory, getSimulationConfig } from '../api/simulation'
import { listProjects } from '../api/graph'
import { filmAssetUrl, getCitizenPortraits } from '../api/parthenon'
import { speakers } from '../parthenon/speakers.js'
import { arrivals } from '../parthenon/arrivals/index.js'
import { localText } from '../parthenon/localText.js'
import { speakerFace } from '../parthenon/portraits.js'
import { ACTS, citizenName, isPlatformNode, textLang, smartQuotes } from '../parthenon/vocabulary.js'

const props = defineProps({
  mode: { type: String, default: 'shelf' }, // shelf | page
  limit: { type: Number, default: 6 } // tablets on the home shelf
})

const router = useRouter()
const route = useRoute()
const { t, locale } = useI18n()

const page = computed(() => props.mode === 'page')

const uid = `chronicles-${useId()}`
const titleId = `${uid}-title`
const panelTitleId = `${uid}-panel-title`
const stripTitleId = `${uid}-strip`
const nightsTitleId = `${uid}-nights`

const projects = ref([])
// Scrolls the court has heard whose citizens were never summoned: they stand
// on the shelf too, so a gathering left during the Hearing is not lost.
const heardScrolls = ref([])
const loading = ref(true)
const tabletId = (g, part) => `${uid}-t-${String(g.key).replace(/[^A-Za-z0-9_-]/g, '')}-${part}`
const failed = ref(false)

// Warm darks for a plate before its image arrives, or when it has none.
const TONES = ['#2b2019', '#1e2431', '#2d2126', '#1f2a27', '#332616', '#252030', '#2a2418', '#1c2632']

// ---- Dates ----
// The Chronicle's own dates: "25 September 2026", 2026年9月25日.
const dateTag = () => (String(locale.value).startsWith('zh') ? 'zh-CN' : 'en-GB')
const formatWith = (options, value) => {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 10)
  try {
    return new Intl.DateTimeFormat(dateTag(), options).format(d)
  } catch {
    return d.toLocaleDateString()
  }
}
const formatDate = (value) => formatWith({ day: 'numeric', month: 'long', year: 'numeric' }, value)
// The part of the day, not the clock: a night on the steps is remembered as an afternoon.
const partOfDay = (value) => {
  const d = new Date(value)
  if (!value || Number.isNaN(d.getTime())) return ''
  const h = d.getHours()
  const part = h < 5 ? 'night' : h < 12 ? 'morning' : h < 17 ? 'afternoon' : h < 21 ? 'evening' : 'night'
  return t(`parthenon.chronicles.partOfDay.${part}`)
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

// ---- Time in the city ----
// The city keeps time in hours and days, never in rounds. A turn is an hour
// unless the Scribe set a shorter one, which shows when the planned turns fill
// the planned hours exactly (a week of half hours is 336 turns).
const minutesPerTurn = (p) => {
  const hours = Number(p.total_simulation_hours) || 0
  const rounds = Number(p.total_rounds) || 0
  if (hours && rounds) {
    const m = (hours * 60) / rounds
    if (m < 60 && [5, 10, 15, 20, 30].some((x) => Math.abs(m - x) < 0.01)) return m
  }
  return 60
}

const spanOf = (p) => {
  const currentRounds = Math.max(0, Number(p.current_round) || 0)
  const totalRounds = Math.max(0, Number(p.total_rounds) || 0)
  const perTurn = minutesPerTurn(p) / 60
  const totalHours = totalRounds ? totalRounds * perTurn : Number(p.total_simulation_hours) || 0
  const currentHours = Math.min(currentRounds, totalRounds || currentRounds) * perTurn
  const over = totalRounds > 0 && currentRounds >= totalRounds
  const inDays = totalHours >= 48
  const per = inDays ? 24 : 1
  const total = Math.max(1, Math.round(totalHours / per))
  let current = Math.round(currentHours / per)
  if (currentRounds > 0) current = Math.max(1, current)
  // A live run counts the day it is in: hour 30 is on day 2.
  const day = inDays ? Math.min(total, Math.floor(currentHours / per) + 1) : current
  // A run that stopped early never reads as if it went the distance.
  if (!over && current >= total) current = Math.max(1, total - 1)
  if (over) current = total
  return { current, day, total, over, inDays, begun: currentRounds > 0 }
}

const LIVE = ['running', 'starting', 'stopping']
const WRITING = ['pending', 'planning', 'generating']

// ---- One night: a single run of a stage ----
const nightOf = (p) => {
  const runner = String(p.runner_status || '').toLowerCase()
  const paused = runner === 'paused'
  const live = LIVE.includes(runner) || p.status === 'running'
  const failedRun = runner === 'failed' || p.status === 'failed'
  const span = spanOf(p)
  const unit = span.inDays ? 'Days' : 'Hours'
  const reportStatus = String(p.report_status || '').toLowerCase()
  const reportId = p.report_id || ''
  const writing = !!reportId && WRITING.includes(reportStatus)
  const reportTrouble = !!reportId && reportStatus === 'failed'
  const reportDone = !!reportId && !writing && !reportTrouble
  const film = filmMade(p.film)
  const filmStatus = String(p.film?.status || 'none')

  // One sentence in words: where the run got to, what has been written, what
  // has been filmed.
  const parts = []
  if (live) parts.push(t(`parthenon.chronicles.status.live${unit}`, { current: Math.max(1, span.day), total: span.total }))
  else if (paused) parts.push(t(`parthenon.chronicles.status.paused${unit}`, { current: Math.max(1, span.day), total: span.total }))
  else if (!span.begun) {
    if (failedRun || p.error) parts.push(t('parthenon.chronicles.status.troubleEarly'))
    else if (p.status === 'ready' || p.config_generated) parts.push(t('parthenon.chronicles.status.gathered'))
    else parts.push(t('parthenon.chronicles.status.notStarted'))
  } else if (span.over) parts.push(t(`parthenon.chronicles.status.argued${unit}`, { total: span.total }, span.total))
  else parts.push(t(`parthenon.chronicles.status.stopped${unit}`, { current: span.current, total: span.total }))
  if (reportId) {
    parts.push(t(writing ? 'parthenon.chronicles.status.chronicleWriting'
      : reportTrouble ? 'parthenon.chronicles.status.chronicleTrouble'
        : 'parthenon.chronicles.status.chronicleWritten'))
  }
  const runSentence = parts[0]
  if (film) parts.push(t('parthenon.chronicles.status.filmMade'))

  const state = live || paused || writing ? 'live'
    : failedRun || (!span.begun && p.error) ? 'error'
      : span.begun ? (span.over ? 'done' : 'stopped')
        : 'idle'
  const word = t(`parthenon.chronicles.word.${
    state === 'live' ? 'live' : state === 'error' ? 'trouble' : state === 'done' ? 'complete' : state === 'stopped' ? 'stopped' : 'waiting'
  }`)

  const seed = p.files?.[0]?.filename || ''
  const speaker = speakers.find((s) => s.fileName === seed)
  const arrival = arrivals.find((a) => a.fileName === seed)
  const lang = locale.value
  const question = String(p.question || p.simulation_requirement || '').trim()
  const poster = film ? filmAssetUrl(p.film?.poster_url) : ''
  const stageImage = arrival ? `/media/scenes/arrival-${arrival.id}.jpg` : speaker ? `/media/portraits/${speaker.id}.jpg` : ''
  const iso = p.created_at || ''

  return {
    id: p.simulation_id,
    projectId: p.project_id || '',
    simulationId: p.simulation_id || '',
    reportId,
    title: printed(p.report_title) || stageTitle(speaker, arrival, lang) || titleFromQuestion(question),
    stageName: [arrival?.title, arrival?.zh?.title, speaker?.name, speaker?.work, speaker?.zh?.name, speaker?.zh?.work].filter(Boolean).join(' '),
    question,
    era: localText(speaker, 'year', lang) || localText(arrival, 'year', lang) || '',
    letter: speaker?.letter || arrival?.letter || (question.charAt(0) || 'Σ').toUpperCase(),
    image: poster || stageImage,
    stageImage,
    poster,
    film,
    filmRunning: filmStatus === 'running',
    citizens: Number(p.profiles_count) || 0,
    live: live || paused,
    writing,
    reportDone,
    reportTrouble,
    span,
    unit,
    iso,
    latest: String(p.updated_at || iso || ''),
    date: formatDate(iso),
    dateTime: t('parthenon.chronicles.nightOn', { date: formatDate(iso), time: partOfDay(iso) }),
    status: parts.join(String(locale.value).startsWith('zh') ? '，' : ', '),
    runSentence,
    state,
    word,
    // The night that stands for its stage: live, then written, then argued, then newest.
    rank: live || paused || writing ? 4 : reportId ? 3 : span.begun ? 2 : 1
  }
}

// The Scribe's title, set as a printer would (curly quotes in English).
const printed = (title) => {
  const text = String(title || '').trim()
  return text && textLang(text) === 'en' ? smartQuotes(text) : text
}

// A stage's title in the visitor's language: the arrival's, or the speaker's work.
const stageTitle = (speaker, arrival, lang) => {
  if (arrival) return localText(arrival, 'title', lang) || localText(arrival, 'name', lang)
  if (!speaker) return ''
  const name = localText(speaker, 'name', lang)
  const work = localText(speaker, 'work', lang)
  if (!work) return name
  return String(lang).startsWith('zh') ? `${name}《${work}》` : `${name}, ${work}`
}

// ---- A scroll heard, its citizens never summoned ----
// It stands as a tablet of its own, opening the Hearing, where the door to
// summon them waits.
const HEARD = ['graph_building', 'graph_completed']
const heardOf = (p) => {
  const seed = p.files?.[0]?.filename || ''
  const speaker = speakers.find((s) => s.fileName === seed)
  const arrival = arrivals.find((a) => a.fileName === seed)
  const lang = locale.value
  const question = String(p.simulation_requirement || '').trim()
  const stageImage = arrival ? `/media/scenes/arrival-${arrival.id}.jpg` : speaker ? `/media/portraits/${speaker.id}.jpg` : ''
  const iso = p.created_at || ''
  const building = p.status === 'graph_building'
  const status = t(building ? 'parthenon.chronicles.status.hearing' : 'parthenon.chronicles.status.heardOnly')
  return {
    id: p.project_id,
    projectId: p.project_id,
    simulationId: '',
    reportId: '',
    title: stageTitle(speaker, arrival, lang) || titleFromQuestion(question),
    stageName: [arrival?.title, arrival?.zh?.title, speaker?.name, speaker?.work, speaker?.zh?.name, speaker?.zh?.work].filter(Boolean).join(' '),
    question,
    era: localText(speaker, 'year', lang) || localText(arrival, 'year', lang) || '',
    letter: speaker?.letter || arrival?.letter || (question.charAt(0) || 'Σ').toUpperCase(),
    image: stageImage,
    stageImage,
    poster: '',
    film: false,
    filmRunning: false,
    citizens: 0,
    live: false,
    writing: false,
    reportDone: false,
    reportTrouble: false,
    span: { current: 0, day: 0, total: 0, over: false, inDays: false, begun: false },
    unit: 'Hours',
    iso,
    latest: String(p.updated_at || iso || ''),
    date: formatDate(iso),
    dateTime: t('parthenon.chronicles.nightOn', { date: formatDate(iso), time: partOfDay(iso) }),
    status,
    runSentence: status,
    state: building ? 'live' : 'idle',
    word: t(`parthenon.chronicles.word.${building ? 'live' : 'heard'}`),
    heardOnly: true,
    rank: 0
  }
}

// ---- The shelf: stages, each with its nights ----
const groups = computed(() => {
  const byStage = new Map()
  for (const p of projects.value) {
    if (!p?.simulation_id) continue
    const key = p.project_id || p.simulation_id
    if (!byStage.has(key)) byStage.set(key, [])
    byStage.get(key).push(nightOf(p))
  }
  for (const p of heardScrolls.value) {
    if (!p?.project_id || byStage.has(p.project_id) || !HEARD.includes(p.status)) continue
    byStage.set(p.project_id, [heardOf(p)])
  }
  const list = [...byStage.entries()].map(([key, nights]) => {
    nights.sort((a, b) => b.iso.localeCompare(a.iso))
    const lead = [...nights].sort((a, b) => b.rank - a.rank || b.iso.localeCompare(a.iso))[0]
    const latest = nights.reduce((m, n) => (n.latest > m ? n.latest : m), '')
    return {
      key,
      lead,
      nights,
      latest,
      heardOnly: !!lead.heardOnly,
      live: nights.some((n) => n.state === 'live'),
      written: nights.some((n) => n.reportDone),
      filmed: nights.some((n) => n.film),
      haystack: nights
        .map((n) => [n.title, n.question, n.era, n.stageName].join(' '))
        .join(' ')
        .normalize('NFKD')
        .replace(/[̀-ͯ]/g, '')
        .toLowerCase()
    }
  })
  list.sort((a, b) => Number(b.live) - Number(a.live) || b.latest.localeCompare(a.latest))
  return list.map((g, i) => ({ ...g, tone: TONES[i % TONES.length] }))
})

// ---- Finding a gathering (the Chronicles page) ----
const query = ref('')
const filter = ref('all')

const filterOptions = computed(() => {
  const all = groups.value
  const options = [
    { id: 'all', count: all.length },
    { id: 'live', count: all.filter((g) => g.live).length },
    { id: 'written', count: all.filter((g) => g.written).length },
    { id: 'filmed', count: all.filter((g) => g.filmed).length }
  ]
  return options
    .filter((o) => o.id === 'all' || o.count > 0)
    .map((o) => ({ ...o, label: t(`parthenon.chronicles.filter.${o.id}`) }))
})

// A kind that has emptied out (the live run finished) falls back to every gathering.
watch(filterOptions, (options) => {
  if (!options.some((o) => o.id === filter.value)) filter.value = 'all'
})

const shown = computed(() => {
  if (!page.value) return groups.value.slice(0, Math.max(1, props.limit))
  const words = query.value
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
  return groups.value.filter((g) => {
    if (filter.value === 'live' && !g.live) return false
    if (filter.value === 'written' && !g.written) return false
    if (filter.value === 'filmed' && !g.filmed) return false
    return words.every((w) => g.haystack.includes(w))
  })
})

const clearFind = () => {
  query.value = ''
  filter.value = 'all'
}

const summary = computed(() => {
  const nights = groups.value.flatMap((g) => g.nights).filter((n) => !n.heardOnly)
  const live = nights.filter((n) => n.live).length
  const written = nights.filter((n) => n.reportDone).length
  const films = nights.filter((n) => n.film).length
  const parts = []
  if (live) parts.push(t('parthenon.chronicles.summary.live', { n: live }, live))
  parts.push(t('parthenon.chronicles.summary.stages', { n: groups.value.length }, groups.value.length))
  parts.push(t('parthenon.chronicles.summary.gatherings', { n: nights.length }, nights.length))
  if (written) parts.push(t('parthenon.chronicles.summary.chronicles', { n: written }, written))
  if (films) parts.push(t('parthenon.chronicles.summary.films', { n: films }, films))
  return parts.join(String(locale.value).startsWith('zh') ? '，' : ', ')
})

// ---- Images ----
// A poster that will not load gives way to the stage's image, then the letter.
const broken = reactive(new Set())
const markBroken = (url) => {
  if (url) broken.add(url)
}
const plateImage = (n) => {
  if (n.image && !broken.has(n.image)) return n.image
  if (n.stageImage && !broken.has(n.stageImage)) return n.stageImage
  return ''
}

// ---- Links ----
// The permanent link opens the furthest act reached; a Chronicle id when
// there is one, since it names the gathering and its Chronicle both.
const gatheringLink = (n) => ({ name: 'Gathering', params: { id: n.reportId || n.simulationId || n.projectId } })

// ---- The panel (the Chronicles page) ----
// The open gathering lives in the address (?g=<night>), so a link can open it
// and Back closes it.
const panelEl = ref(null)
const panelCloseBtn = ref(null)
let lastFocused = null
let pushedPanel = false

const openNightId = computed(() => (page.value ? String(route.query.g || '') : ''))
const panelGroup = computed(() => {
  const id = openNightId.value
  if (!id) return null
  return groups.value.find((g) => g.nights.some((n) => n.id === id)) || null
})
const night = computed(() => panelGroup.value?.nights.find((n) => n.id === openNightId.value) || null)

const openGroup = (g) => {
  lastFocused = document.activeElement
  pushedPanel = true
  router.push({ query: { ...route.query, g: g.lead.id } })
}

const chooseNight = (n) => {
  router.replace({ query: { ...route.query, g: n.id } })
}

const closePanel = () => {
  if (pushedPanel && window.history.state?.back) {
    pushedPanel = false
    router.back()
    return
  }
  pushedPanel = false
  const rest = { ...route.query }
  delete rest.g
  router.replace({ query: rest })
}

// Esc closes; Tab stays inside the dialog.
const onPanelKeydown = (event) => {
  if (!panelGroup.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closePanel()
    return
  }
  if (event.key !== 'Tab' || !panelEl.value) return
  const focusable = Array.from(
    panelEl.value.querySelectorAll('button:not([disabled]), [href], input, [tabindex]:not([tabindex="-1"])')
  )
  if (focusable.length === 0) {
    event.preventDefault()
    panelEl.value.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (!panelEl.value.contains(active)) {
    event.preventDefault()
    first.focus()
  } else if (event.shiftKey && (active === first || active === panelEl.value)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

// The page behind holds still while a gathering is held up.
let lockedOverflow = null
const lockPage = (on) => {
  const root = document.documentElement
  if (on && lockedOverflow === null) {
    lockedOverflow = root.style.overflow
    root.style.overflow = 'hidden'
  } else if (!on && lockedOverflow !== null) {
    root.style.overflow = lockedOverflow
    lockedOverflow = null
  }
}

let lastGroupKey = ''
watch(panelGroup, (g) => { if (g) lastGroupKey = g.key })

watch(
  () => !!panelGroup.value,
  async (open, wasOpen) => {
    if (open && !wasOpen) {
      document.addEventListener('keydown', onPanelKeydown)
      lockPage(true)
      await nextTick()
      ;(panelCloseBtn.value || panelEl.value)?.focus()
    } else if (!open && wasOpen) {
      document.removeEventListener('keydown', onPanelKeydown)
      lockPage(false)
      copyState.value = ''
      // Give focus back to the tablet that opened it, or to its stage's tablet.
      await nextTick()
      const own = lastFocused && document.contains(lastFocused) ? lastFocused : null
      const stage = lastGroupKey ? document.querySelector(`.tablet[data-group="${CSS.escape(lastGroupKey)}"]`) : null
      lastFocused = null
      ;(own || stage)?.focus?.()
    }
  }
)

// ---- The filmstrip of one night ----
const SCENES = {
  scroll: '/media/acts/hearing.jpg',
  crowd: '/media/acts/gathering.jpg',
  argument: '/media/acts/agora.jpg',
  chronicle: '/media/acts/chronicle.jpg',
  symposium: '/media/acts/symposium.jpg'
}

const frames = computed(() => {
  const n = night.value
  if (!n) return []
  const line = (key, named, plural) => t(`parthenon.chronicles.frameLine.${key}`, named || {}, plural)
  const closed = line('closed')
  const report = n.reportId
  const sim = n.simulationId
  const argued = n.span.begun || n.live
  const list = [
    {
      key: 'scroll',
      act: 1,
      to: n.projectId ? { name: 'Process', params: { projectId: n.projectId } } : null,
      state: n.projectId ? 'kept' : 'closed',
      line: n.projectId ? line('scroll') : closed
    },
    {
      key: 'crowd',
      act: 2,
      to: sim ? { name: 'Simulation', params: { simulationId: sim } } : null,
      state: sim ? (n.citizens ? 'kept' : 'open') : 'closed',
      line: !sim ? closed : n.citizens ? line('crowd', { n: n.citizens }, n.citizens) : line('crowdNone')
    },
    {
      key: 'argument',
      act: 3,
      to: sim ? { name: 'SimulationRun', params: { simulationId: sim } } : null,
      state: !sim ? 'closed' : n.live && !n.writing ? 'live' : argued ? 'kept' : 'open',
      line: !sim ? closed : argued ? n.runSentence : line('argumentNone')
    },
    {
      key: 'chronicle',
      act: 4,
      to: report ? { name: 'Report', params: { reportId: report } } : null,
      state: !report ? 'closed' : n.writing ? 'live' : n.reportTrouble ? 'open' : 'kept',
      line: !report ? line('chronicleNone') : n.writing ? line('chronicleWriting') : n.reportTrouble ? line('chronicleTrouble') : line('chronicleDone')
    },
    {
      key: 'film',
      act: 4,
      image: n.poster && !broken.has(n.poster) ? n.poster : '',
      to: report && n.reportDone ? { name: 'Report', params: { reportId: report }, hash: '#film' } : null,
      state: n.film ? 'kept' : n.filmRunning ? 'live' : n.reportDone ? 'open' : 'closed',
      line: n.film ? line('filmDone') : n.filmRunning ? line('filmRunning') : n.reportDone ? line('filmNone') : closed
    },
    {
      key: 'symposium',
      act: 5,
      to: report ? { name: 'Interaction', params: { reportId: report } } : null,
      state: !report ? 'closed' : n.reportDone ? 'kept' : 'open',
      line: !report ? closed : n.reportDone ? line('symposiumOpen') : line('symposiumWaiting')
    }
  ]
  return list.map((f) => {
    const image = f.image !== undefined ? f.image : SCENES[f.key]
    return {
      ...f,
      image,
      background: image ? `url("${image}")` : 'none',
      numeral: ACTS[f.act - 1].numeral,
      name: t(`parthenon.chronicles.frames.${f.key}`)
    }
  })
})

// ---- Faces in the crowd ----
// The painted portraits when there are some; else the citizens' names, so the
// Crowd frame shows their initials in their role colours.
const crowds = reactive({})
const loadCrowd = async (simId) => {
  if (!simId || crowds[simId]) return
  crowds[simId] = []
  let people = []
  try {
    const res = await getCitizenPortraits(simId)
    people = (res?.data?.portraits || []).map((p) => ({
      name: citizenName(p.name),
      type: p.entity_type || '',
      // The philosophers keep the one face they have everywhere.
      portrait: speakerFace(p.name) || (p.status === 'done' && p.url ? filmAssetUrl(p.url) : '')
    }))
  } catch {
    people = []
  }
  if (!people.length) {
    try {
      const res = await getSimulationConfig(simId)
      people = (res?.data?.agent_configs || []).map((a) => ({
        name: citizenName(a.entity_name),
        type: a.entity_type || '',
        portrait: ''
      }))
    } catch {
      people = []
    }
  }
  const seen = new Set()
  crowds[simId] = people
    .filter((p) => p.name && !isPlatformNode(p.name) && !seen.has(p.name) && seen.add(p.name))
    .sort((a, b) => Number(!!b.portrait) - Number(!!a.portrait))
    .slice(0, 5)
}
const crowd = computed(() => (night.value ? crowds[night.value.simulationId] || [] : []))
watch(() => night.value?.simulationId, (id) => { if (id) loadCrowd(id) })

// ---- Copying the permanent link ----
const copyState = ref('')
const copyNote = computed(() =>
  copyState.value === 'copied' ? t('parthenon.chronicles.copied')
    : copyState.value === 'failed' ? t('parthenon.chronicles.copyFailed') : ''
)
let copyTimer = 0
const copyLink = async (n) => {
  const href = router.resolve(gatheringLink(n)).href
  const url = `${window.location.origin}${href}`
  try {
    await navigator.clipboard.writeText(url)
    copyState.value = 'copied'
  } catch {
    copyState.value = 'failed'
  }
  clearTimeout(copyTimer)
  copyTimer = setTimeout(() => { copyState.value = '' }, 2600)
}

// ---- Reading the shelf ----
let inflight = null
const loadHistory = async () => {
  if (inflight) return inflight
  inflight = (async () => {
    try {
      loading.value = true
      const [response, heard] = await Promise.all([
        getSimulationHistory(page.value ? 500 : 60),
        // The court's own list; a shelf without it still shows every gathering.
        listProjects().catch(() => null)
      ])
      if (response?.success) {
        projects.value = Array.isArray(response.data) ? response.data : []
        failed.value = false
      }
      if (heard?.success && Array.isArray(heard.data)) heardScrolls.value = heard.data
    } catch (error) {
      failed.value = true
    } finally {
      loading.value = false
      inflight = null
    }
  })()
  return inflight
}

// While something is live, the shelf looks again now and then, so the lit
// tablets keep their hour and go out when the run ends.
const anyLive = computed(() => groups.value.some((g) => g.live))
let pollTimer = 0
const schedulePoll = () => {
  clearTimeout(pollTimer)
  if (!anyLive.value) return
  pollTimer = setTimeout(async () => {
    if (document.visibilityState === 'visible') await loadHistory()
    schedulePoll()
  }, 15000)
}
watch(anyLive, schedulePoll)

// Coming back to the home page reloads the shelf.
watch(() => route.path, (newPath) => {
  if (!page.value && newPath === '/') loadHistory()
})

onMounted(loadHistory)
onActivated(() => {
  loadHistory()
  schedulePoll()
})
onDeactivated(() => clearTimeout(pollTimer))

onUnmounted(() => {
  document.removeEventListener('keydown', onPanelKeydown)
  lockPage(false)
  clearTimeout(pollTimer)
  clearTimeout(copyTimer)
})
</script>

<style scoped>
.chronicles {
  position: relative;
  width: 100%;
  min-width: 0;
}

.visually-hidden {
  position: absolute !important;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
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
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 18px;
  margin: 0;
  padding: 36px 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

.shelf-note p {
  margin: 0;
}

.shelf-note .p-button {
  font-style: normal;
}

/* Tools: a count in words, a search, the kinds */
.shelf-tools {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 32px;
}

.shelf-count {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

.tools-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 20px;
}

.find {
  position: relative;
  flex: 1 1 280px;
  max-width: 420px;
  display: flex;
  align-items: center;
}

.find-icon {
  position: absolute;
  left: 14px;
  color: var(--p-ink-3);
  pointer-events: none;
}

.find-input {
  width: 100%;
  min-height: 44px;
  padding: 0 14px 0 40px;
  border: 1px solid var(--p-control-border);
  border-radius: var(--p-radius);
  background: var(--p-surface);
  color: var(--p-ink);
  font-family: var(--p-font-body);
  font-size: var(--t-md);
}

.find-input::placeholder {
  color: var(--p-ink-4);
}

.find-input:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 2px;
  border-color: var(--p-gold);
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.filter {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 14px;
  border: 1px solid var(--p-line-strong);
  border-radius: var(--p-radius);
  background: transparent;
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  font-weight: 500;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease;
}

.filter:hover {
  border-color: var(--p-gold);
  color: var(--p-ink);
}

.filter[aria-pressed='true'] {
  border-color: var(--p-gold);
  background: var(--p-terracotta-tint);
  color: var(--p-ink);
}

.filter-n {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  color: var(--p-gold);
}

.filter:focus-visible,
.tablet:focus-visible,
.frame:focus-visible,
.night:focus-visible,
.panel-close:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 3px;
}

/* The shelf: a static grid of tablets */
.shelf {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 30px 26px;
  margin: 0;
  padding: 0;
}

.mode-page .shelf {
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 36px 30px;
}

.shelf-cell {
  position: relative;
  min-width: 0;
  isolation: isolate;
}

/* Re-runs of one stage: the tablets behind the one in front */
.shelf-cell.stacked::before,
.shelf-cell.deep::after {
  content: '';
  position: absolute;
  inset: 0;
  border: 1px solid var(--p-line-strong);
  background: var(--p-surface-2);
  pointer-events: none;
}

.shelf-cell.stacked::before {
  transform: translate(8px, 8px);
  opacity: 0.9;
}

.shelf-cell.deep::after {
  transform: translate(16px, 16px);
  opacity: 0.5;
  z-index: -1;
}

.tablet {
  position: relative;
  z-index: 1;
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
  text-decoration: none;
  cursor: pointer;
  transition: border-color 0.25s ease, transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.35s ease;
}

.tablet:hover {
  border-color: var(--p-line-strong);
  transform: translateY(-3px);
  box-shadow: var(--p-shadow-2);
}

/* A live gathering is lit: a lamp in the window */
.tablet.live {
  border-color: rgba(240, 182, 96, 0.6);
  box-shadow: 0 0 0 1px rgba(240, 182, 96, 0.18), 0 0 48px rgba(240, 182, 96, 0.14);
}

.tablet.live .tablet-plate::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 80% 70% at 50% 100%, rgba(240, 182, 96, 0.28), transparent 70%);
  pointer-events: none;
}

.tablet-plate {
  position: relative;
  display: grid;
  place-items: center;
  overflow: hidden;
  width: 100%;
  aspect-ratio: 16 / 10;
  background: var(--plate, var(--p-surface-2));
}

.tablet-plate img {
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

.tablet-film,
.tablet-lit,
.tablet-nights {
  position: absolute;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  background: rgba(11, 14, 19, 0.82);
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
}

.tablet-film {
  right: 12px;
  top: 12px;
  border: 1px solid rgba(240, 182, 96, 0.5);
  color: var(--p-gold);
}

.tablet-lit {
  left: 12px;
  top: 12px;
  border: 1px solid var(--p-gold);
  color: var(--p-gold);
}

.tablet-nights {
  left: 12px;
  bottom: 12px;
  border: 1px solid var(--p-line-strong);
  color: var(--p-ink);
  letter-spacing: 0.08em;
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
  margin: auto 0 0;
  padding-top: 6px;
  font-size: var(--t-xs);
  line-height: 1.45;
  color: var(--p-ink-2);
}

.dot {
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

.done .dot { background: var(--p-olive); }
.done .status-word { color: var(--p-olive); }
.stopped .dot { background: var(--p-ochre); }
.stopped .status-word { color: var(--p-ochre); }
.error .dot { background: var(--p-error); }
.error .status-word { color: var(--p-error); }
.live .status-word { color: var(--p-gold); }

.live > .dot,
.tablet-lit .dot,
.frame-lit {
  background: var(--p-gold);
  box-shadow: 0 0 0 4px var(--p-terracotta-tint);
  animation: pulse 1.6s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(240, 182, 96, 0.28); }
  50% { box-shadow: 0 0 0 8px rgba(240, 182, 96, 0); }
}

/* Waiting for the shelf: the tablets' outlines, still */
.tablet.ghost {
  cursor: default;
  pointer-events: none;
}

.ghost-line {
  display: block;
  height: 12px;
  width: 100%;
  background: var(--p-surface-3);
}

.ghost-line.short {
  width: 40%;
}

.shelf-foot {
  display: flex;
  justify-content: flex-start;
  margin-top: 36px;
}

.see-all-arrow {
  font-size: var(--t-lg);
  line-height: 1;
}

/* ---- The gathering, held up ---- */
.panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(7, 9, 12, 0.78);
  backdrop-filter: blur(8px);
}

.panel {
  position: relative;
  width: min(1060px, 100%);
  font-family: var(--p-font-body);
  color: var(--p-ink-2);
  max-height: calc(100vh - 48px);
  max-height: calc(100dvh - 48px);
  overflow-y: auto;
  overscroll-behavior: contain;
  background: var(--p-surface);
  border: 1px solid var(--p-line-strong);
  box-shadow: var(--p-shadow-2);
}

.panel:focus {
  outline: none;
}

.panel-enter-active,
.panel-leave-active {
  transition: opacity 0.3s ease;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
}

.panel-enter-active .panel {
  transition: transform 0.4s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.4s ease;
}

.panel-leave-active .panel {
  transition: transform 0.2s ease-in, opacity 0.2s ease-in;
}

.panel-enter-from .panel,
.panel-leave-to .panel {
  transform: translateY(14px);
  opacity: 0;
}

/* Chinese is not set in capitals with inscription tracking. */
.tablet-film:lang(zh),
.tablet-lit:lang(zh),
.tablet-nights:lang(zh),
.tablet-meta:lang(zh),
.status-word:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

.tablet.heard .tablet-plate img {
  filter: saturate(0.55) brightness(0.8);
}

.panel-banner {
  position: relative;
  display: flex;
  align-items: flex-end;
  min-height: 280px;
  overflow: hidden;
  background: var(--plate, var(--p-surface-2));
  isolation: isolate;
}

.panel-banner img {
  position: absolute;
  inset: 0;
  z-index: -2;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 32%;
}

.banner-letter {
  position: absolute;
  top: 40px;
  left: 50%;
  transform: translateX(-50%);
  z-index: -2;
  font-size: 120px;
  opacity: 0.35;
}

.banner-shade {
  position: absolute;
  inset: 0;
  z-index: -1;
  background:
    linear-gradient(180deg, rgba(17, 21, 28, 0.2) 0%, rgba(17, 21, 28, 0.35) 40%, rgba(17, 21, 28, 0.97) 100%),
    linear-gradient(90deg, rgba(17, 21, 28, 0.7) 0%, rgba(17, 21, 28, 0) 70%);
}

.panel-banner.live .banner-shade {
  background:
    radial-gradient(ellipse 70% 60% at 30% 100%, rgba(240, 182, 96, 0.22), transparent 70%),
    linear-gradient(180deg, rgba(17, 21, 28, 0.2) 0%, rgba(17, 21, 28, 0.35) 40%, rgba(17, 21, 28, 0.97) 100%);
}

.panel-close {
  position: absolute;
  top: 14px;
  right: 14px;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 1px solid var(--p-line-strong);
  border-radius: var(--p-radius);
  background: rgba(11, 14, 19, 0.7);
  color: var(--p-ink);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease;
}

.panel-close:hover {
  border-color: var(--p-gold);
  color: var(--p-gold);
}

.banner-copy {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  padding: 28px 32px 24px;
}

/* The date and era over a bright sky keep a dark halo, as the title does. */
.banner-copy .tablet-meta {
  align-self: flex-start;
  padding: 3px 8px;
  margin-left: -8px;
  background: rgba(11, 14, 19, 0.62);
  color: var(--p-ink-2);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
}

.banner-copy .panel-title,
.banner-copy .tablet-status {
  text-shadow: 0 1px 12px rgba(11, 14, 19, 0.85), 0 1px 2px rgba(11, 14, 19, 0.9);
}

.panel-title {
  margin: 0;
  max-width: 30ch;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.06;
  color: var(--p-ink);
  text-wrap: balance;
}

.banner-copy .tablet-status {
  margin: 0;
  padding: 0;
  font-size: var(--t-sm);
}

.panel-body {
  display: flex;
  flex-direction: column;
  gap: 28px;
  padding: 8px 32px 32px;
}

.panel-body .p-eyebrow {
  margin: 0 0 12px;
}

.panel-question-text {
  margin: 0;
  max-width: 72ch;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.65;
  color: var(--p-ink-2);
}

/* The filmstrip: six frames on a band of film, sprockets above and below */
.filmstrip {
  position: relative;
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
  padding: 24px 12px;
  list-style: none;
  background: #07090c;
  border: 1px solid rgba(242, 237, 228, 0.06);
}

.filmstrip::before,
.filmstrip::after {
  content: '';
  position: absolute;
  left: 8px;
  right: 8px;
  height: 8px;
  background: linear-gradient(90deg, transparent 0 5px, rgba(242, 237, 228, 0.16) 5px 13px, transparent 13px) 0 0 / 20px 8px repeat-x;
  pointer-events: none;
}

.filmstrip::before { top: 8px; }
.filmstrip::after { bottom: 8px; }

.frame-cell {
  min-width: 0;
}

.frame {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 44px;
  background: #0e1116;
  border: 1px solid rgba(242, 237, 228, 0.08);
  color: inherit;
  text-decoration: none;
  transition: border-color 0.25s ease, transform 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}

a.frame:hover {
  border-color: var(--p-gold);
  transform: translateY(-2px);
}

.frame-image {
  position: relative;
  display: block;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background-color: #151a21;
  background-image: var(--frame);
  background-size: cover;
  background-position: center 45%;
  transition: filter 0.35s ease;
}

.frame-numeral {
  position: absolute;
  top: 6px;
  left: 6px;
  padding: 2px 6px;
  background: rgba(7, 9, 12, 0.75);
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: 0.06em;
  color: var(--p-gold);
}

.frame-reel {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 44%;
  max-width: 56px;
  transform: translate(-50%, -50%);
  color: var(--p-ink-4);
}

.frame-film .frame-image {
  background-color: #10141a;
}

.frame-lit {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 9px;
  height: 9px;
  border-radius: var(--p-radius-coin);
}

.frame-faces {
  position: absolute;
  left: 6px;
  right: 6px;
  bottom: 6px;
  display: flex;
}

.frame-faces > * + * {
  margin-left: -9px;
}

.frame-faces :deep(.citizen-coin) {
  flex-shrink: 0;
  background-color: #11151c;
  box-shadow: 0 0 0 2px #0e1116;
}

.frame-caption {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 10px 12px;
  min-width: 0;
}

.frame-name {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  line-height: 1.15;
  color: var(--p-ink);
}

.frame-line {
  font-size: var(--t-xs);
  line-height: 1.4;
  color: var(--p-ink-3);
}

/* Kept: the act happened. Live: it is happening, lit. Open: it can be
   visited but has not happened. Closed: not yet reached. */
.frame.is-live {
  border-color: var(--p-gold);
  box-shadow: 0 0 24px rgba(240, 182, 96, 0.22);
}

.frame.is-live .frame-line {
  color: var(--p-gold);
}

.frame.is-open .frame-image {
  filter: grayscale(0.7) brightness(0.62);
}

a.frame.is-open:hover .frame-image {
  filter: none;
}

.frame.is-closed {
  cursor: default;
  border-style: dashed;
}

.frame.is-closed .frame-image {
  filter: grayscale(1) brightness(0.3);
}

.frame.is-closed .frame-name {
  color: var(--p-ink-3);
}

.frame.is-closed .frame-line {
  color: var(--p-ink-4);
}

/* Every night of this stage */
.nights {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.night {
  display: grid;
  grid-template-columns: 8px minmax(150px, auto) minmax(0, 1fr);
  align-items: center;
  gap: 8px 16px;
  width: 100%;
  min-height: 52px;
  padding: 10px 16px;
  border: 1px solid var(--p-line);
  border-radius: var(--p-radius);
  background: transparent;
  color: var(--p-ink-2);
  font: inherit;
  font-size: var(--t-sm);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.night:hover {
  border-color: var(--p-line-strong);
}

.night.current {
  border-color: var(--p-gold);
  background: var(--p-terracotta-tint);
}

.night-when {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-ink);
}

.night-status {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  align-items: baseline;
  min-width: 0;
}

.night.live .dot {
  background: var(--p-gold);
}

.panel-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid var(--p-line);
}

@media (max-width: 899px) {
  .filmstrip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    row-gap: 32px;
  }

  .filmstrip::before,
  .filmstrip::after {
    display: none;
  }

  .filmstrip {
    background-image:
      linear-gradient(90deg, transparent 0 5px, rgba(242, 237, 228, 0.16) 5px 13px, transparent 13px),
      linear-gradient(90deg, transparent 0 5px, rgba(242, 237, 228, 0.16) 5px 13px, transparent 13px);
    background-size: 20px 8px, 20px 8px;
    background-repeat: repeat-x;
    background-position: 8px 8px, 8px calc(100% - 8px);
  }
}

/* Phones: the dialog is the whole screen and the film runs downward */
@media (max-width: 640px) {
  .panel-overlay {
    padding: 0;
    align-items: stretch;
  }

  .panel {
    width: 100%;
    max-height: none;
    height: 100%;
    border: 0;
  }

  .panel-banner {
    min-height: 240px;
  }

  .banner-copy {
    padding: 24px 16px 18px;
  }

  .panel-title {
    font-size: var(--t-xl);
  }

  .panel-body {
    gap: 24px;
    padding: 4px 16px 32px;
  }

  .filmstrip {
    grid-template-columns: minmax(0, 1fr);
    row-gap: 8px;
    padding: 10px 10px 10px 30px;
    background-image: linear-gradient(180deg, transparent 0 5px, rgba(242, 237, 228, 0.16) 5px 13px, transparent 13px);
    background-size: 8px 20px;
    background-repeat: repeat-y;
    background-position: 11px 6px;
  }

  .frame {
    flex-direction: row;
    min-height: 80px;
  }

  .frame-image {
    flex-shrink: 0;
    width: 112px;
    aspect-ratio: 4 / 3;
  }

  .frame-caption {
    justify-content: center;
    padding: 10px 14px;
  }

  .frame-faces :deep(.citizen-coin:nth-child(n + 4)) {
    display: none;
  }

  .night {
    grid-template-columns: 8px minmax(0, 1fr);
  }

  .night-status {
    grid-column: 2;
  }

  .panel-foot {
    flex-direction: column;
  }

  .panel-foot .p-button {
    width: 100%;
  }

  .shelf-foot .p-button {
    width: 100%;
  }

  .find {
    max-width: none;
    flex-basis: 100%;
  }

  .shelf-cell.stacked::before {
    transform: translate(5px, 5px);
  }

  .shelf-cell.deep::after {
    transform: translate(10px, 10px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .live > .dot,
  .tablet-lit .dot,
  .frame-lit {
    animation: none;
  }

  .tablet,
  .tablet-plate img,
  .frame,
  .frame-image {
    transition: none;
  }

  .tablet:hover,
  a.frame:hover {
    transform: none;
  }

  .tablet:hover .tablet-plate img {
    transform: none;
  }

  .panel-enter-active,
  .panel-leave-active,
  .panel-enter-active .panel,
  .panel-leave-active .panel {
    transition: none;
  }
}
</style>
