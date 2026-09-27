<template>
  <div class="home">
    <header class="topbar" :class="{ solid: !heroInView || !heroTop }">
      <router-link to="/" class="topbar-brand" :aria-label="$t('parthenon.navHome')">
        <ParthenonBrand />
      </router-link>
      <div class="topbar-end">
        <nav class="topbar-links" :aria-label="$t('parthenon.navSections')">
          <a href="#stages" class="topbar-stages">{{ $t('parthenon.navSpeakers') }}</a>
          <router-link :to="{ name: 'Chronicles' }">{{ $t('parthenon.navArchive') }}</router-link>
        </nav>
        <ListenToggle :compact="narrow" class="topbar-listen" />
      </div>
    </header>

    <!-- The descent: the climb up the Propylaea and the Way across the temple -->
    <CinematicHero
      :era="sceneEra"
      :speaker="sceneSpeaker"
      @update:era="chooseEra"
      @begin="openTab(tab, true)"
      @view="onHeroView"
      @way="onWay"
    />

    <main>
      <!-- Choose your stage -->
      <section id="stages" ref="stagesEl" class="stages" :style="threadStyle">
        <!-- The Way leaves the foot of the climb and comes down the steps to the choice. -->
        <svg
          v-if="thread.d"
          class="thread"
          :viewBox="`0 0 ${thread.w} ${thread.h}`"
          :width="thread.w"
          :height="thread.h"
          aria-hidden="true"
        >
          <path class="thread-glow" :d="thread.d" pathLength="1" />
          <path class="thread-line" :d="thread.d" pathLength="1" />
        </svg>
        <div class="wrap">
          <header ref="stagesHead" class="section-head stages-head">
            <h2>{{ $t('parthenon.stageTitle') }}</h2>
            <p>{{ $t('parthenon.stageDesc') }}</p>
          </header>

          <div
            class="tabs"
            role="tablist"
            :aria-label="$t('parthenon.stageTitle')"
            :aria-orientation="tabsVertical ? 'vertical' : 'horizontal'"
          >
            <button
              v-for="t in tabs"
              :id="`tab-${t.id}`"
              :key="t.id"
              type="button"
              role="tab"
              class="tab"
              :class="{ active: tab === t.id }"
              :aria-selected="tab === t.id"
              :aria-controls="`panel-${t.id}`"
              :tabindex="tab === t.id ? 0 : -1"
              @click="openTab(t.id)"
              @keydown.right.prevent="stepTab(1)"
              @keydown.down.prevent="stepTab(1)"
              @keydown.left.prevent="stepTab(-1)"
              @keydown.up.prevent="stepTab(-1)"
              @keydown.home.prevent="focusTab(0)"
              @keydown.end.prevent="focusTab(tabs.length - 1)"
            >
              <span class="tab-era">{{ $t(`parthenon.${t.era}`) }}</span>
              <span class="tab-name">{{ $t(`parthenon.${t.name}`) }}</span>
              <svg class="tab-chevron" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="1.4" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Athens, 399 BC: the six on the steps -->
        <div v-show="tab === 'athens'" id="panel-athens" role="tabpanel" aria-labelledby="tab-athens">
          <div class="wrap">
            <p class="panel-intro">{{ $t('parthenon.speakersDesc') }}</p>
          </div>

          <div ref="figuresEl" class="figures" :class="{ choosing: !!chosenSpeaker }">
            <div class="figure-row" role="group" :aria-label="$t('parthenon.tabAthens')">
              <button
                v-for="(s, i) in speakers"
                :key="s.id"
                type="button"
                class="figure"
                :data-figure="s.id"
                :class="{ selected: isSelected('speaker', s.id) }"
                :style="{ '--i': i, '--depth': FIGURE_DEPTH[i % FIGURE_DEPTH.length] }"
                :aria-pressed="isSelected('speaker', s.id)"
                :aria-labelledby="`fig-${s.id}-name fig-${s.id}-epithet`"
                :aria-describedby="`fig-${s.id}-line`"
                aria-controls="speaker-scroll"
                :disabled="loading"
                @click="chooseSpeaker(s)"
              >
                <span class="figure-body">
                  <span class="figure-plate">
                    <img
                      :src="`/media/figures/${s.id}-560.jpg`"
                      :srcset="`/media/figures/${s.id}-560.jpg 560w, /media/figures/${s.id}.jpg 832w`"
                      sizes="(max-width: 699px) 70vw, 17vw"
                      alt=""
                      width="560"
                      height="840"
                      loading="lazy"
                      decoding="async"
                    />
                  </span>
                  <span :id="`fig-${s.id}-line`" class="figure-line">{{ quote(lt(s, 'line')) }}</span>
                </span>
                <!-- The names keep one baseline: only the plate steps forward. -->
                <span class="figure-caption">
                  <span :id="`fig-${s.id}-name`" class="figure-name">{{ lt(s, 'name') }}</span>
                  <span :id="`fig-${s.id}-epithet`" class="figure-epithet">{{ lt(s, 'epithet') }}</span>
                </span>
              </button>
            </div>
            <div class="step-band" aria-hidden="true"></div>
          </div>

          <!-- The scroll unrolls in place under the one who stepped forward. -->
          <div id="speaker-scroll" class="unroll" :class="{ open: !!chosenSpeaker }">
            <div class="unroll-clip">
              <div v-if="bandSpeaker" ref="sheetEl" class="unroll-sheet p-paper" :inert="!chosenSpeaker || undefined">
                <div class="unroll-quote-col">
                  <p class="unroll-meta">
                    <span class="unroll-work">{{ lt(bandSpeaker, 'work') }}</span>
                    <span class="unroll-place">{{ lt(bandSpeaker, 'place') }}{{ comma }}{{ lt(bandSpeaker, 'year') }}</span>
                  </p>
                  <blockquote class="unroll-quote">
                    <p>{{ quote(lt(bandSpeaker, 'line')) }}</p>
                    <footer>{{ lt(bandSpeaker, 'name') }}{{ comma }}{{ lt(bandSpeaker, 'epithet') }}</footer>
                  </blockquote>
                </div>
                <div class="unroll-scene">
                  <h3 class="unroll-scene-title">{{ $t('parthenon.figures.scene') }}</h3>
                  <p class="unroll-summary">{{ bandSummary }}</p>
                  <button type="button" class="p-button unroll-carry" @click="carryScroll">
                    {{ $t('parthenon.figures.carry') }}
                    <span aria-hidden="true">→</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
          <p v-if="!chosenSpeaker" class="wrap figures-hint">{{ $t('parthenon.figures.choose') }}</p>
          <p class="sr-status" aria-live="polite">{{ chosenSpeaker ? $t('parthenon.figures.unrolledBelow') : '' }}</p>
        </div>

        <!-- The Arrivals, 2026 -->
        <div v-show="tab === 'arrivals'" id="panel-arrivals" role="tabpanel" aria-labelledby="tab-arrivals">
          <div class="omens">
            <img
              class="omens-image"
              src="/media/scenes/golden-handmaidens.jpg"
              :alt="$t('parthenon.alts.omens')"
              width="2000"
              height="848"
              loading="lazy"
              decoding="async"
            />
            <div class="omens-shade" aria-hidden="true"></div>
            <div class="wrap omens-body">
              <div class="omens-lead">
                <h3>{{ $t('parthenon.arrivalsTitle') }}</h3>
                <p>{{ $t('parthenon.arrivalsIntro') }}</p>
                <p class="omens-note">{{ $t('parthenon.arrivalsNote') }}</p>
              </div>
              <ul class="omen-list">
                <li v-for="(o, i) in omens" :key="i" class="omen">
                  <p>{{ o.text }}</p>
                  <span>{{ o.source }}</span>
                </li>
              </ul>
            </div>
          </div>

          <div class="wrap">
            <div class="mosaic" role="group" :aria-label="$t('parthenon.tabArrivals')">
              <button
                v-for="(a, i) in arrivals"
                :key="a.id"
                type="button"
                class="scene-card"
                :class="{ selected: isSelected('arrival', a.id), lead: i === 0, 'lead-close': a.closing && i === arrivals.length - 1 }"
                :aria-pressed="isSelected('arrival', a.id)"
                :disabled="loading"
                @click="chooseArrival(a)"
              >
                <!-- Each tile has its own warm dark before the paint arrives; the first row loads at once. -->
                <span class="scene-frame" :style="{ '--tile': tone(i) }">
                  <img
                    :src="`/media/scenes/arrival-${a.id}.jpg`"
                    alt=""
                    width="1200"
                    height="800"
                    :loading="tab === 'arrivals' && i < 3 ? 'eager' : 'lazy'"
                    fetchpriority="low"
                    decoding="async"
                  />
                </span>
                <span class="scene-meta">{{ lt(a, 'year') }}{{ comma }}{{ formatLabel(a.format) }}</span>
                <span class="scene-title">{{ lt(a, 'title') }}</span>
                <span class="scene-challenge">{{ lt(a, 'challenge') }}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Build your own stage -->
        <div v-show="tab === 'build'" id="panel-build" role="tabpanel" aria-labelledby="tab-build">
          <div class="bema">
            <img
              class="bema-image"
              src="/media/scenes/pnyx-bema.jpg"
              :alt="$t('parthenon.alts.bema')"
              width="2000"
              height="848"
              loading="lazy"
              decoding="async"
            />
            <div class="bema-shade" aria-hidden="true"></div>
            <div class="wrap bema-body">
              <h3>{{ $t('parthenon.buildTitle') }}</h3>
              <p>{{ $t('parthenon.buildIntro') }}</p>
            </div>
          </div>
          <div class="wrap builder-wrap">
            <StageBuilder :disabled="loading" @use-stage="useStage" />
          </div>
        </div>

        <!-- The one upload control, on every tab; the empty scroll below only takes drops. -->
        <div class="wrap">
          <button
            type="button"
            class="own-scroll"
            :class="{ selected: !selection && files.length > 0, 'drag-over': isDragOver }"
            :disabled="loading"
            @click="triggerFileInput"
            @dragover.prevent="handleDragOver"
            @dragleave.prevent="handleDragLeave"
            @drop.prevent="handleDrop"
          >
            <span class="own-scroll-text">
              <strong>{{ $t('parthenon.ownScrollTitle') }}</strong>
              {{ $t('parthenon.ownScrollDesc') }}
            </span>
            <span class="own-scroll-cta">{{ $t('parthenon.ownScrollCta') }} <span aria-hidden="true">↑</span></span>
          </button>
        </div>
        <input
          ref="fileInput"
          type="file"
          multiple
          accept=".pdf,.md,.txt"
          hidden
          :disabled="loading"
          @change="handleFileSelect"
        />
      </section>

      <!-- The bema: the scroll held up above, the question cut into the stone -->
      <section id="gathering" class="gathering" aria-labelledby="bema-title">
        <!-- The Pnyx at dusk under the night: the platform the question is cut into. -->
        <div class="pnyx" aria-hidden="true">
          <img src="/media/scenes/pnyx-bema.jpg" alt="" width="2000" height="848" loading="lazy" decoding="async" />
        </div>
        <div class="wrap bema-stage">
          <header class="section-head bema-head">
            <p class="p-eyebrow">{{ $t('parthenon.bema.eyebrow') }}</p>
            <h2 id="bema-title">{{ $t('parthenon.bema.title') }}</h2>
          </header>

          <div class="held">
            <h3 ref="scrollTitle" class="panel-title held-title" tabindex="-1">{{ $t('parthenon.scrollLabel') }}</h3>

            <template v-if="selection">
              <div class="held-scroll">
                <article
                  class="scroll-sheet p-paper"
                  tabindex="0"
                  role="region"
                  :aria-label="$t('parthenon.scrollLabel')"
                  v-html="scrollHtml"
                ></article>
              </div>
              <p class="scroll-note">
                {{ scrollNote }}
                <button v-if="selection.kind === 'stage'" type="button" class="text-button" @click="openTab('build', true)">
                  {{ $t('parthenon.editStage') }}
                </button>
              </p>
            </template>

            <div v-else-if="files.length" class="file-list">
              <div v-for="(file, index) in files" :key="`${file.name}-${index}`" class="file-item">
                <span class="file-name">{{ file.name }}</span>
                <button type="button" class="file-remove" :aria-label="`${$t('common.cancel')}: ${file.name}`" @click="removeFile(index)">×</button>
              </div>
              <button type="button" class="text-button" @click="triggerFileInput">{{ $t('parthenon.addScroll') }}</button>
            </div>

            <!-- The scroll still rolled: two rods closed on each other. The whole
                 place takes a dropped file. -->
            <div
              v-else
              class="scroll-empty"
              :class="{ 'drag-over': isDragOver }"
              @dragover.prevent="handleDragOver"
              @dragleave.prevent="handleDragLeave"
              @drop.prevent="handleDrop"
            >
              <span class="rolled" aria-hidden="true"></span>
              <p>{{ $t('parthenon.scrollRolled') }}</p>
              <span class="rolled" aria-hidden="true"></span>
            </div>
          </div>

          <div class="bema-block">
            <div class="bema-cornice" aria-hidden="true"></div>
            <div class="bema-face">
              <label class="inscription-label" for="city-question">{{ $t('parthenon.questionLabel') }}</label>
              <textarea
                id="city-question"
                ref="questionInput"
                v-model="formData.simulationRequirement"
                class="inscription"
                rows="4"
                :placeholder="$t('parthenon.questionPlaceholder')"
                :disabled="loading"
              ></textarea>
              <p class="question-hint">{{ $t('parthenon.questionHint') }}</p>
            </div>
            <div class="bema-steps" aria-hidden="true"><span></span><span></span></div>
          </div>

          <div class="bema-foot">
            <!-- How long the city talks, in story sizes -->
            <fieldset class="length" :disabled="loading">
              <legend class="panel-title">{{ $t('parthenon.length.label') }}</legend>
              <div class="length-options">
                <label v-for="l in RUN_LENGTHS" :key="l.id" class="length-option" :class="{ chosen: runLength === l.id }">
                  <input v-model="runLength" type="radio" name="run-length" :value="l.id" class="visually-hidden" />
                  <span class="length-name">{{ $t(`parthenon.length.${l.id}`) }}</span>
                  <span class="length-meta">{{ lengthMeta(l) }}</span>
                </label>
              </div>
              <p class="length-note">{{ $t('parthenon.length.note') }}</p>
            </fieldset>

            <div class="begin-wrap">
              <p v-if="zepMissing" class="setup-notice" role="status">
                {{ $t('parthenon.zepMissing') }}
                <a href="https://app.getzep.com" target="_blank" rel="noopener">app.getzep.com</a>
              </p>
              <button type="button" class="p-button begin" :disabled="!canSubmit || loading || zepMissing" @click="startSimulation">
                <span>{{ loading ? $t('parthenon.beginning') : $t('parthenon.begin') }}</span>
                <span class="begin-arrow" aria-hidden="true">→</span>
              </button>
              <p v-if="!canSubmit" class="begin-hint">{{ $t('parthenon.beginHint') }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- The Chronicles -->
      <section id="chronicles" class="archive wrap">
        <HistoryDatabase />
      </section>
    </main>

    <footer class="footer wrap">
      <p class="maxim" lang="grc">ΓΝΩΘΙ ΣΕΑΥΤΟΝ</p>
      <p class="maxim-gloss">{{ $t('parthenon.maxim') }}</p>
      <p class="credits">
        {{ $t('parthenon.footerLead') }}
        <a href="https://github.com/666ghj/MiroFish" target="_blank" rel="noopener">MiroFish</a>
        (AGPL-3.0)
      </p>
      <p class="credits credits-made">{{ $t('parthenon.footerVoices') }}</p>
      <div class="footer-tools"><LanguageSwitcher /></div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import ParthenonBrand from '../components/ParthenonBrand.vue'
import CinematicHero from '../components/CinematicHero.vue'
import StageBuilder from '../components/StageBuilder.vue'
import ListenToggle from '../components/ListenToggle.vue'
import { speakers, speakerSeedFile } from '../parthenon/speakers.js'
import { arrivals, arrivalSeedFile } from '../parthenon/arrivals/index.js'
import { RUN_LENGTHS, spansHours } from '../parthenon/vocabulary.js'
import { localText } from '../parthenon/localText.js'
import { sound, setBed, speak, voiceUrl } from '../parthenon/sound.js'
import { subscribe, passage, sceneSummary, renderScroll, smoothPath } from '../parthenon/descent.js'
import { getInstanceStatus } from '../api/parthenon.js'
import pendingUpload, { setPendingUpload } from '../store/pendingUpload.js'

const router = useRouter()
const { t, tm, locale } = useI18n()

// A speaker's or an arrival's words in the visitor's language.
const lt = (item, field) => localText(item, field, locale.value)
const zh = computed(() => String(locale.value).startsWith('zh'))
const comma = computed(() => (zh.value ? '，' : ', '))
// A line quoted in the visitor's own marks.
const quote = (text) => (zh.value ? `「${text}」` : `“${text}”`)

const omens = computed(() => tm('parthenon.omens'))

const tabs = [
  { id: 'athens', era: 'tabAthensEra', name: 'tabAthens' },
  { id: 'arrivals', era: 'tabArrivalsEra', name: 'tabArrivals' },
  { id: 'build', era: 'tabBuildEra', name: 'tabBuild' }
]
const tab = ref('athens')

// The tabs stack into a column at 640px and below (see the CSS); keys and aria-orientation follow.
const tabsVertical = ref(false)
const narrow = ref(false)
let narrowQuery = null
const syncTabsOrientation = () => {
  tabsVertical.value = !!narrowQuery?.matches
  narrow.value = !!narrowQuery?.matches
}

// Warm darks for a tile before its paint arrives, so no frame is ever flat black.
const TONES = ['#2b2019', '#1e2431', '#2d2126', '#1f2a27', '#332616', '#252030', '#2a2418', '#1c2632', '#302020', '#232b1f']
const tone = (i) => TONES[i % TONES.length]

// How far each philosopher's painting drifts as the row passes (px across the pass).
const FIGURE_DEPTH = [22, 34, 26, 38, 24, 32]

// The question put to the city
const formData = ref({
  simulationRequirement: ''
})

// The scrolls to be read
const files = ref([])

// What is on the scroll: a speaker, an arrival, or a stage the user built.
// { kind, id, title, letter, era, markdown, fileName, question }
const selection = ref(null)
const eraOverride = ref(null)

// How long Athens talks, in story sizes (see RUN_LENGTHS).
const runLength = ref('day')
const chosenLength = computed(() => RUN_LENGTHS.find((l) => l.id === runLength.value) || RUN_LENGTHS[1])
// Two facts: how long the argument runs, and the whole night around it (the
// reading and the gathering before, the Chronicle after). A span that names
// its own hours ("2 to 3 hours", "2 至 3 小时") takes the phrasing without a
// unit of its own, so no length ever reads "小时 分钟".
const lengthMeta = (l) => {
  const night = t(`parthenon.length.night.${l.id}`)
  const span = String(l.minutes ?? '')
  return spansHours(span)
    ? t('parthenon.length.metaLong', { hours: l.hours, span, night })
    : t('parthenon.length.meta', { hours: l.hours, minutes: span, night })
}

const loading = ref(false)
const isDragOver = ref(false)

const fileInput = ref(null)

// Where keyboard focus lands after the page moves to the scroll and the question.
const scrollTitle = ref(null)
const questionInput = ref(null)

const canSubmit = computed(() => {
  return formData.value.simulationRequirement.trim() !== '' && files.value.length > 0
})

const isSelected = (kind, id) => selection.value?.kind === kind && selection.value?.id === id

// "a speech", "一场演说": the stage's form in the visitor's language.
const formatLabel = (id) => (id ? t(`parthenon.builder.oracle.formats.${id}`) : '')

// The hero follows the chosen scroll, else the tab, unless the visitor flipped the era.
const sceneEra = computed(() => {
  if (eraOverride.value) return eraOverride.value
  if (selection.value?.era) return selection.value.era === 'ancient' ? 'ancient' : 'now'
  return tab.value === 'athens' ? 'ancient' : 'now'
})

const sceneSpeaker = computed(() =>
  selection.value?.letter ? { name: selection.value.title, letter: selection.value.letter } : null
)

// One sentence under the scroll about where it came from. No filenames.
const scrollNote = computed(() => {
  const s = selection.value
  if (!s) return ''
  const key = s.noteKey === 'parthenon.scrollNoteSand' ? 'sand' : s.kind
  return t(`parthenon.scrollNotes.${key}`)
})

// Every prepared question in every language, so one the visitor wrote themselves is kept.
const presetQuestions = new Set(
  [...speakers, ...arrivals].flatMap((item) => [item.question, item.zh?.question]).filter(Boolean)
)
const isPresetQuestion = (text) => presetQuestions.has(text) || text === selection.value?.question

// The philosopher who stepped forward, and the scroll unrolled under the row.
// The band keeps its last speaker while it rolls shut.
const chosenSpeaker = computed(() =>
  selection.value?.kind === 'speaker' ? speakers.find((s) => s.id === selection.value.id) || null : null
)
const bandSpeaker = ref(null)
watch(chosenSpeaker, (s) => {
  if (s) bandSpeaker.value = s
})
const bandSummary = computed(() => (bandSpeaker.value ? sceneSummary(lt(bandSpeaker.value, 'question'), 2) : ''))

// The top bar sits over the hero at the top; once the climb begins, or the
// hero leaves the screen, it is solid.
const heroInView = ref(true)
const heroTop = ref(true)
const onHeroView = ({ inView, top }) => {
  heroInView.value = inView
  heroTop.value = top
}

// ---- The thread ----
// The Way leaves the foot of the climb at x; a gold thread carries it down
// from there to the heading of the stages, so the path leads to the choice.
const stagesEl = ref(null)
const stagesHead = ref(null)
const wayFoot = ref(null)
const thread = ref({ d: '', w: 0, h: 0 })
const onWay = ({ x }) => {
  wayFoot.value = Number.isFinite(x) ? x : null
  nextTick(drawThread)
}
const drawThread = () => {
  const sec = stagesEl.value
  const head = stagesHead.value
  if (!sec || !head || wayFoot.value == null) {
    thread.value = { d: '', w: 0, h: 0 }
    return
  }
  const base = sec.getBoundingClientRect()
  const h = head.getBoundingClientRect()
  const W = Math.round(base.width)
  const H = Math.max(24, Math.round(h.top - base.top - 14))
  const x0 = Math.min(W - 2, Math.max(2, wayFoot.value - base.left))
  const x1 = Math.max(2, h.left - base.left + 1)
  // Down from the foot of the frame, across, and down onto the heading's first letter.
  // Close above the heading (an upright list), the thread simply drops.
  const d = Math.abs(x0 - x1) < 64
    ? `M${x0} 0 L${x0} ${H}`
    : smoothPath([
      { x: x0, y: 0 },
      { x: x0 + (x1 - x0) * 0.12, y: H * 0.42 },
      { x: x1 + (x0 - x1) * 0.2, y: H * 0.72 },
      { x: x1, y: H }
    ], 0.8)
  thread.value = { d, w: W, h: H }
}
// Drawn as the section rises into view.
const threadDraw = ref(0)
const threadStyle = computed(() => ({ '--thread': threadDraw.value.toFixed(3) }))
const onThreadScroll = (m) => {
  const sec = stagesEl.value
  if (!sec || !thread.value.d) return
  const r = sec.getBoundingClientRect()
  // 0 as the section's top enters the lower third, 1 once it reaches the upper third.
  const k = Math.min(1, Math.max(0, (m.vh * 0.92 - r.top) / (m.vh * 0.55)))
  if (Math.abs(k - threadDraw.value) < 0.002) return
  return () => { threadDraw.value = k }
}

// What this instance can run (e.g. a missing Zep key), shown before a run fails.
const instance = ref(null)

// Without a Zep key the hearing fails after the first reading, so hold the run here.
const zepMissing = computed(() => instance.value?.zepConfigured === false)

// ---- Sound ----
// The hero's bed follows the era: dawn wind in 399 BC, the city's hum in 2026.
let homeBed = null
const followBed = (era) => {
  homeBed = era === 'now' ? 'now' : 'ancient'
  setBed(homeBed)
}
watch(sceneEra, followBed)

// Turning Listen on with the hero in view: the narrator reads the hero line,
// once a visit.
const HERO_LINE_KEY = 'parthenon.heroLineSpoken'
const readSpoken = () => {
  try {
    return sessionStorage.getItem(HERO_LINE_KEY) === '1'
  } catch {
    return false
  }
}
let heroSpoken = readSpoken()
watch(() => sound.enabled, (on, was) => {
  if (!on || was || heroSpoken || !heroTop.value) return
  heroSpoken = true
  try {
    sessionStorage.setItem(HERO_LINE_KEY, '1')
  } catch {
    // storage blocked; once for this page then
  }
  speak(voiceUrl('hero', locale.value))
})

// The inscription grows with the question, so the whole of it is cut in the stone.
const fitInscription = () => {
  const el = questionInput.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight + 2, 420)}px`
}
watch(() => formData.value.simulationRequirement, () => nextTick(fitInscription))

// ---- The figures pass ----
// The row drifts gently as it crosses the screen, on the page's one scroll
// listener (parthenon/descent.js). Nothing moves under reduced motion.
const figuresEl = ref(null)
let offFigures = null
let offThread = null
const onFiguresScroll = (m) => {
  const el = figuresEl.value
  if (!el || tab.value !== 'athens') return
  const r = el.getBoundingClientRect()
  if (r.bottom < -200 || r.top > m.vh + 200) return
  const p = passage(r.top, r.height, m.vh)
  return () => el.style.setProperty('--pass', p.toFixed(3))
}

onMounted(() => {
  followBed(sceneEra.value)
  getInstanceStatus()
    .then((res) => { instance.value = res.data })
    .catch(() => { instance.value = null })
  narrowQuery = window.matchMedia('(max-width: 640px)')
  syncTabsOrientation()
  narrowQuery.addEventListener('change', syncTabsOrientation)
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    offFigures = subscribe(onFiguresScroll)
    offThread = subscribe(onThreadScroll)
  } else {
    threadDraw.value = 1
  }
  window.addEventListener('resize', drawThread, { passive: true })
})

onBeforeUnmount(() => {
  narrowQuery?.removeEventListener('change', syncTabsOrientation)
  offFigures?.()
  offThread?.()
  window.removeEventListener('resize', drawThread)
  // Leave the next place its own bed; clear only the one the home set.
  if (homeBed && sound.bed === homeBed) setBed(null)
})

// Read at call time, so turning reduced motion on mid-visit takes effect at once.
const scrollBehavior = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'

// Go to a section and bring keyboard focus along, so the next Tab starts there.
const scrollToId = async (id) => {
  await nextTick()
  document.getElementById(id)?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
  const target = id === 'gathering'
    ? (formData.value.simulationRequirement.trim() ? scrollTitle.value : questionInput.value)
    : document.getElementById(`tab-${tab.value}`)
  target?.focus({ preventScroll: true })
}

// From the hero's "Choose your stage": land so the six stand whole on the
// screen, heads to names, with the choice above them where there is room.
// On a small screen the three stages come first, never cut by the bar.
const BAR = 68
const landOnStage = async () => {
  await nextTick()
  const sec = document.getElementById('stages')
  if (!sec) return
  const y = window.scrollY
  const base = sec.getBoundingClientRect().top + y - BAR
  let top = base
  const row = tab.value === 'athens' ? figuresEl.value : null
  const head = stagesHead.value
  if (row && head) {
    const rowFit = row.getBoundingClientRect().bottom + y + 16 - window.innerHeight
    const headEnd = head.getBoundingClientRect().bottom + y - BAR + 4
    if (rowFit > base) top = Math.min(rowFit, headEnd)
  }
  window.scrollTo({ top: Math.max(0, top), behavior: scrollBehavior() })
  document.getElementById(`tab-${tab.value}`)?.focus({ preventScroll: true })
}

const openTab = (id, scroll = false) => {
  tab.value = id
  eraOverride.value = null
  if (scroll) landOnStage()
}

const chooseEra = (era) => {
  eraOverride.value = era
  tab.value = era === 'ancient' ? 'athens' : 'arrivals'
}

const focusTab = (index) => {
  const next = tabs[(index + tabs.length) % tabs.length]
  openTab(next.id)
  nextTick(() => document.getElementById(`tab-${next.id}`)?.focus())
}

const stepTab = (delta) => focusTab(tabs.findIndex((t) => t.id === tab.value) + delta)

// Load a prepared scroll; keep a question the user wrote themselves.
const present = (item, file, { jump = true } = {}) => {
  const current = formData.value.simulationRequirement.trim()
  if (!current || isPresetQuestion(current)) {
    formData.value.simulationRequirement = item.question
  }
  selection.value = item
  eraOverride.value = null
  files.value = [file]
  if (jump) scrollToId('gathering')
}

// A philosopher steps forward: the narrator reads the line (only if the
// visitor chose to listen) and the scroll unrolls under the row. The page
// stays where it is; "Carry the scroll to the bema" moves on.
// The unrolled sheet comes into view with its "Carry" button, while the
// chosen philosopher's head stays on screen below the bar.
const sheetEl = ref(null)
const revealSheet = async (speakerId) => {
  await nextTick()
  const sheet = sheetEl.value
  const clip = sheet?.parentElement
  const fig = figuresEl.value?.querySelector('.figure.selected') || null
  if (!sheet || !clip) return
  // The sheet's open height, read before the grid has finished opening.
  const top = clip.getBoundingClientRect().top
  const neededBottom = top + clip.scrollHeight
  const limit = window.innerHeight - 24
  if (neededBottom <= limit) return
  // A phone has no room for the whole figure and the sheet: there the name
  // stays in view instead of the head.
  const small = window.matchMedia('(max-width: 699px)').matches
  const keep = (small && fig?.querySelector('.figure-caption')) || fig
  const keepTop = keep ? keep.getBoundingClientRect().top : top
  const by = Math.min(neededBottom - window.innerHeight + 32, keepTop - 80)
  if (by > 0 && selection.value?.id === speakerId) window.scrollBy({ top: by, behavior: scrollBehavior() })
}

const chooseSpeaker = (speaker) => {
  if (loading.value) return
  present({
    kind: 'speaker',
    id: speaker.id,
    title: lt(speaker, 'name'),
    letter: speaker.letter,
    era: 'ancient',
    markdown: speaker.seed,
    fileName: speaker.fileName,
    question: lt(speaker, 'question')
  }, speakerSeedFile(speaker), { jump: false })
  speak(voiceUrl(`speaker-${speaker.id}`, locale.value))
  revealSheet(speaker.id)
}

const carryScroll = () => scrollToId('gathering')

const chooseArrival = (arrival) => {
  if (loading.value) return
  present({
    kind: 'arrival',
    id: arrival.id,
    title: lt(arrival, 'name'),
    letter: arrival.letter,
    era: 'now',
    markdown: arrival.seed,
    fileName: arrival.fileName,
    question: lt(arrival, 'question'),
    noteKey: arrival.noteKey
  }, arrivalSeedFile(arrival))
  speak(voiceUrl(`arrival-${arrival.id}`, locale.value))
}

// The builder composed a stage: it replaces the scroll and brings its own question.
const useStage = (payload) => {
  if (loading.value) return
  const firstName = payload.stage?.speakers?.find((sp) => sp.name?.trim())?.name.trim() || ''
  selection.value = {
    kind: 'stage',
    id: payload.fileName,
    title: firstName || payload.title,
    letter: firstName ? firstName[0].toUpperCase() : 'Φ',
    era: payload.era,
    markdown: payload.markdown,
    fileName: payload.fileName,
    question: payload.question
  }
  eraOverride.value = null
  files.value = [payload.file]
  formData.value.simulationRequirement = payload.question
  scrollToId('gathering')
}

const triggerFileInput = () => {
  if (!loading.value) {
    fileInput.value?.click()
  }
}

const handleFileSelect = (event) => {
  addFiles(Array.from(event.target.files))
  event.target.value = ''
}

const handleDragOver = () => {
  if (!loading.value) {
    isDragOver.value = true
  }
}

const handleDragLeave = () => {
  isDragOver.value = false
}

const handleDrop = (e) => {
  isDragOver.value = false
  if (loading.value) return
  addFiles(Array.from(e.dataTransfer.files))
}

// Your own scroll replaces a prepared one.
const addFiles = (newFiles) => {
  const validFiles = newFiles.filter((file) => {
    const ext = file.name.split('.').pop().toLowerCase()
    return ['pdf', 'md', 'txt'].includes(ext)
  })
  if (!validFiles.length) return
  if (selection.value) {
    if (isPresetQuestion(formData.value.simulationRequirement.trim())) {
      formData.value.simulationRequirement = ''
    }
    selection.value = null
    files.value = []
  }
  files.value.push(...validFiles)
  scrollToId('gathering')
}

const removeFile = (index) => {
  files.value.splice(index, 1)
}

// The scroll as the city prints it (parthenon/descent.js): no long dashes.
const scrollHtml = computed(() => (selection.value ? renderScroll(selection.value.markdown) : ''))

// Let Athens speak: the scrolls and the question wait on the pending record;
// the Hearing reads them. The chosen length rides along three ways (on the
// record, in this tab's storage and on the route) so the Gathering can hand
// it to the Agora as maxRounds, the way the app already passes it.
const RUN_LENGTH_KEY = 'parthenon.runLength'
const startSimulation = () => {
  if (!canSubmit.value || loading.value || zepMissing.value) return
  loading.value = true
  const length = chosenLength.value
  setPendingUpload(files.value, formData.value.simulationRequirement)
  pendingUpload.runLength = length.id
  pendingUpload.maxRounds = length.rounds
  try {
    sessionStorage.setItem(RUN_LENGTH_KEY, JSON.stringify({ id: length.id, rounds: length.rounds, hours: length.hours, chosenAt: Date.now() }))
  } catch {
    // storage blocked; the record and the route still carry it
  }
  router.push({
    name: 'Process',
    params: { projectId: 'new' },
    query: { maxRounds: length.rounds }
  })
}
</script>

<style scoped>
/* The night tokens are global now; only the short alias stays. */
.home {
  --gold: var(--p-gold);

  min-height: 100vh;
  background: var(--p-bg);
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
}

.wrap {
  width: min(1240px, 100% - 2 * var(--p-gutter));
  margin-inline: auto;
}

.visually-hidden {
  position: absolute !important;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* Top bar */
.topbar {
  position: fixed;
  inset: 0 0 auto 0;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 68px;
  padding: 0 var(--p-gutter);
}

/* Two painted layers crossfade on opacity: the shade over the hero, then the solid bar. */
.topbar::before,
.topbar::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  transition: opacity 0.4s ease;
}

.topbar::before {
  bottom: -28px;
  background: linear-gradient(180deg, rgba(8, 10, 14, 0.72) 0%, rgba(8, 10, 14, 0.35) 70%, rgba(8, 10, 14, 0) 100%);
}

.topbar::after {
  background: rgba(11, 14, 19, 0.86);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--p-line);
  opacity: 0;
}

.topbar.solid::before {
  opacity: 0;
}

.topbar.solid::after {
  opacity: 1;
}

.topbar-brand {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  min-width: 40px;
  min-height: 40px;
}

.topbar-links {
  display: flex;
  align-items: center;
  gap: clamp(14px, 2.6vw, 30px);
  min-width: 0;
}

.topbar-links a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 40px;
  min-height: 40px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink);
  text-decoration: none;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
  transition: color 0.2s;
  white-space: nowrap;
  padding: 10px 0;
}

.topbar-links a:hover {
  color: var(--gold);
}

/* Section scaffolding */
.section-head {
  max-width: 720px;
  margin-bottom: 32px;
}

.section-head h2 {
  margin: 0 0 12px;
  font-family: var(--p-font-display);
  font-weight: 500;
  font-size: clamp(36px, 4.4vw, 60px);
  line-height: 1.04;
  letter-spacing: -0.01em;
  color: var(--p-ink);
  text-wrap: balance;
}

.section-head .p-eyebrow {
  margin: 0 0 14px;
}

.section-head p {
  max-width: 60ch;
  font-family: var(--p-font-serif);
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.section-head p.p-eyebrow {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  line-height: 1.4;
  color: var(--p-gold);
}

/* Choose your stage */
.stages {
  --thread: 0;

  position: relative;
  padding: clamp(72px, 10vw, 128px) 0 0;
  scroll-margin-top: 68px;
}

/* The Way, carried on below the climb: a gold thread from where the path
   leaves the frame down to the heading, drawn as the section rises. */
.thread {
  position: absolute;
  top: 0;
  left: 0;
  overflow: visible;
  pointer-events: none;
}

.thread path {
  fill: none;
  stroke-linecap: round;
  stroke-dasharray: 1 1;
  stroke-dashoffset: calc(1 - var(--thread));
}

.thread-line {
  stroke: var(--p-gold);
  stroke-width: 1.2;
}

.thread-glow {
  stroke: rgba(240, 182, 96, 0.22);
  stroke-width: 6;
  filter: blur(3px);
}

/* Tabs */
.tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-top: 1px solid var(--p-line-strong);
  margin-bottom: 36px;
}

.tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 18px 20px 20px 0;
  border: none;
  border-top: 2px solid transparent;
  margin-top: -1px;
  background: none;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.3s ease;
  min-width: 0;
}

.tab.active {
  border-top-color: var(--gold);
}

.tab-era {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-4);
  transition: color 0.3s;
}

.tab-chevron {
  display: none;
}

.tab-name {
  font-family: var(--p-font-display);
  font-size: clamp(22px, 2.3vw, 32px);
  font-weight: 500;
  line-height: 1.1;
  color: var(--p-ink-3);
  transition: color 0.3s;
}

.tab.active .tab-era {
  color: var(--gold);
}

.tab.active .tab-name,
.tab:hover .tab-name {
  color: var(--p-ink);
}

.panel-intro {
  max-width: 60ch;
  margin-bottom: 26px;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-3);
}

/* The Listen switch sits at the end of the bar, beside the links. */
.topbar-end {
  display: flex;
  align-items: center;
  gap: clamp(12px, 2.4vw, 28px);
  min-width: 0;
}

.topbar-listen {
  flex: none;
}

/* Athens: the six on the steps. One sky and one light run over all six (see
   .figure-row::before and ::after), the night closes in over the top and at
   the sides, and one marble step runs under them all, so the row reads as one
   place at one sunrise. */
.figures {
  --pass: 0.5;

  position: relative;
  width: min(1480px, 100%);
  margin: 0 auto;
  padding-top: 6px;
}

.figure-row {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  padding: 0 var(--p-gutter);
  transform: translate3d(0, calc((var(--pass) - 0.5) * -26px), 0);
}

.figure {
  position: relative;
  display: block;
  min-width: 0;
  margin: 0 -14px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: center;
  cursor: pointer;
}

.figure:disabled {
  cursor: not-allowed;
}

.figure:focus-visible {
  z-index: 3;
  outline: 2px solid var(--p-gold);
  outline-offset: 2px;
}

.figure-body {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  transform-origin: 50% 86%;
  transition: transform 0.7s cubic-bezier(0.22, 1, 0.36, 1);
}

.figure-plate {
  position: relative;
  display: block;
  width: 100%;
  aspect-ratio: 2 / 3;
  overflow: hidden;
  background: #17140f;
  /* Wide soft sides, so each painting's sky and steps meet the next in the
     dusk instead of at a seam. */
  -webkit-mask-image:
    linear-gradient(90deg, transparent 0%, rgba(0, 0, 0, 0.5) 9%, #000 22%, #000 78%, rgba(0, 0, 0, 0.5) 91%, transparent 100%),
    linear-gradient(180deg, transparent 0%, rgba(0, 0, 0, 0.55) 9%, #000 26%, #000 86%, transparent 100%);
  -webkit-mask-composite: source-in;
  mask-image:
    linear-gradient(90deg, transparent 0%, rgba(0, 0, 0, 0.5) 9%, #000 22%, #000 78%, rgba(0, 0, 0, 0.5) 91%, transparent 100%),
    linear-gradient(180deg, transparent 0%, rgba(0, 0, 0, 0.55) 9%, #000 26%, #000 86%, transparent 100%);
  mask-composite: intersect;
  transition: filter 0.6s ease;
}

/* Each painting drifts a little against its frame as the row passes. */
.figure-plate img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 50% 100%;
  transform: translate3d(0, calc((var(--pass) - 0.5) * var(--depth) * 1px), 0) scale(1.1);
  /* One grade for all six: the same hour of the same morning, each painting
     brought to the same exposure (Heraclitus was painted under cloud). */
  filter: sepia(0.1) brightness(calc(0.94 * var(--expose, 1))) contrast(1.04) saturate(0.92);
}

.figure[data-figure='heraclitus'] {
  --expose: 1.21;
}

.figure[data-figure='epicurus'] {
  --expose: 0.96;
}

/* One sunrise over the row: a single sky behind all six, so the seams between
   the paintings are that sky and not the night, and a single light over them,
   warm from the east at the left and cooling toward the right, into which each
   painting's own sky dissolves. Where the six stand in a row (not the phone's
   carousel). */
@media (min-width: 700px) {
  .figure-row::before,
  .figure-row::after {
    content: '';
    position: absolute;
    grid-column: 1 / -1;
    grid-row: 1;
    top: 0;
    bottom: 58px;
    left: -14px;
    right: -14px;
    pointer-events: none;
    transition: opacity 0.6s ease;
  }

  .figure-row::before {
    z-index: -1;
    background:
      radial-gradient(ellipse 46% 60% at 8% 30%, rgba(255, 214, 160, 0.34), rgba(255, 214, 160, 0) 70%),
      linear-gradient(180deg, rgba(180, 160, 138, 0) 0%, rgba(180, 160, 138, 0.5) 10%, rgba(176, 154, 126, 0.78) 24%, rgba(150, 124, 97, 0.8) 44%, rgba(120, 99, 79, 0.72) 64%, rgba(100, 83, 68, 0.45) 84%, rgba(100, 83, 68, 0) 100%);
    -webkit-mask-image: linear-gradient(90deg, transparent 0%, #000 7%, #000 93%, transparent 100%);
    mask-image: linear-gradient(90deg, transparent 0%, #000 7%, #000 93%, transparent 100%);
  }

  .figure-row::after {
    z-index: 4;
    mix-blend-mode: soft-light;
    background:
      radial-gradient(ellipse 55% 70% at 10% 38%, rgba(255, 196, 128, 0.6), rgba(255, 196, 128, 0) 72%),
      linear-gradient(180deg, rgba(40, 36, 60, 0.55) 0%, rgba(40, 36, 60, 0.2) 22%, rgba(40, 36, 60, 0) 40%),
      linear-gradient(90deg, rgba(255, 178, 110, 0.3) 0%, rgba(255, 178, 110, 0.1) 45%, rgba(30, 26, 44, 0.3) 100%);
    -webkit-mask-image:
      linear-gradient(90deg, transparent 0%, #000 8%, #000 92%, transparent 100%),
      linear-gradient(180deg, transparent 0%, #000 22%, #000 78%, transparent 100%);
    -webkit-mask-composite: source-in;
    mask-image:
      linear-gradient(90deg, transparent 0%, #000 8%, #000 92%, transparent 100%),
      linear-gradient(180deg, transparent 0%, #000 22%, #000 78%, transparent 100%);
    mask-composite: intersect;
  }

  /* While one is chosen the others wait in the dusk, and so does their sky. */
  .figures.choosing .figure-row::before {
    opacity: 0.26;
  }

  .figures.choosing .figure-row::after {
    opacity: 0.35;
  }
}

/* The line, on hover or focus, in the sky above the head. */
.figure-line {
  position: absolute;
  top: 7%;
  left: 12%;
  right: 12%;
  z-index: 1;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: clamp(15px, 1.15vw, 18px);
  line-height: 1.3;
  color: #f6f1e8;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8), 0 2px 18px rgba(0, 0, 0, 0.75);
  opacity: 0;
  transform: translateY(6px);
  transition: opacity 0.4s ease, transform 0.5s cubic-bezier(0.22, 1, 0.36, 1);
  pointer-events: none;
}

.figure:hover .figure-line,
.figure:focus-visible .figure-line {
  opacity: 1;
  transform: translateY(0);
}

/* A touch leaves :hover behind on the chosen one; there the line would sit
   across the face. The unrolled scroll carries the line instead. */
@media (hover: none) {
  .figure:hover .figure-line {
    opacity: 0;
  }
}

.sr-status {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.figure-caption {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  margin-top: -10px;
  padding: 0 6px 18px;
  min-height: 64px;
}

.figure-name {
  font-family: var(--p-font-inscription);
  font-size: clamp(12px, 1vw, 15px);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
  transition: color 0.3s ease;
}

.figure-epithet {
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: clamp(15px, 1.1vw, 17px);
  color: var(--p-ink-3);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
}

/* The chosen one steps forward into the light; the others wait in the dusk. */
.figure.selected {
  z-index: 2;
}

.figure.selected .figure-body {
  transform: translateY(-14px) scale(1.06);
}

.figure.selected .figure-name {
  color: var(--p-gold);
}

.figure.selected .figure-caption::before {
  content: '';
  position: absolute;
  top: -2px;
  left: 50%;
  width: 46px;
  height: 1px;
  background: var(--p-gold);
  box-shadow: 0 0 14px rgba(240, 182, 96, 0.8);
  transform: translateX(-50%);
}

.figures.choosing .figure:not(.selected) .figure-plate {
  filter: brightness(0.42) saturate(0.55);
}

.figures.choosing .figure:not(.selected):hover .figure-plate,
.figures.choosing .figure:not(.selected):focus-visible .figure-plate {
  filter: brightness(0.72) saturate(0.8);
}

.figure:not(.selected):hover .figure-body {
  transform: translateY(-4px);
}

/* One flight of real steps under all six (cut from their own plates), rising
   out of the dusk under their feet and going down into the night under
   their names. */
.step-band {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -18px;
  z-index: 0;
  height: 150px;
  background:
    linear-gradient(180deg, rgba(11, 14, 19, 0.08) 0%, rgba(11, 14, 19, 0.4) 38%, rgba(11, 14, 19, 0.82) 72%, var(--p-bg) 100%),
    url('/media/figures/steps-band-1920.jpg') center top / cover no-repeat;
  -webkit-mask-image:
    linear-gradient(180deg, transparent 0%, #000 30%),
    linear-gradient(90deg, transparent 0%, #000 10%, #000 90%, transparent 100%);
  -webkit-mask-composite: source-in;
  mask-image:
    linear-gradient(180deg, transparent 0%, #000 30%),
    linear-gradient(90deg, transparent 0%, #000 10%, #000 90%, transparent 100%);
  mask-composite: intersect;
}

.figures-hint {
  margin-top: 14px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  text-align: center;
  color: var(--p-ink-3);
}

/* The scroll unrolls in place: its height opens and the parchment is
   revealed from the top rod down. */
.unroll {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.8s cubic-bezier(0.22, 1, 0.36, 1);
}

.unroll.open {
  grid-template-rows: 1fr;
}

.unroll-clip {
  min-height: 0;
  overflow: hidden;
}

.unroll-sheet {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: clamp(26px, 4vw, 56px);
  width: min(1100px, calc(100% - 2 * var(--p-gutter) - 28px));
  margin: 22px auto 30px;
  padding: 42px clamp(22px, 4vw, 56px) 40px;
  background-color: var(--p-surface-2);
  background-image: var(--p-marble-texture);
  box-shadow: var(--p-shadow-2), inset 0 0 80px rgba(160, 110, 50, 0.16);
  clip-path: inset(0 -20px 100% -20px);
  transition: clip-path 0.95s cubic-bezier(0.22, 1, 0.36, 1);
}

.unroll.open .unroll-sheet {
  clip-path: inset(-12px -20px -12px -20px);
}

/* The rods the parchment is wound on. */
.unroll-sheet::before,
.unroll-sheet::after {
  content: '';
  position: absolute;
  left: -14px;
  right: -14px;
  height: 12px;
  background: linear-gradient(180deg, #a07a45 0%, #6b4e2b 45%, #3e2c17 100%);
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.45);
}

.unroll-sheet::before {
  top: -6px;
}

.unroll-sheet::after {
  bottom: -6px;
}

.unroll-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 14px;
  margin: 0 0 18px;
}

.unroll-work {
  font-family: var(--p-font-inscription);
  font-size: var(--t-sm);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-gold);
}

.unroll-place {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.unroll-quote {
  margin: 0;
  padding: 0 0 0 20px;
  border-left: 2px solid var(--p-gold);
}

.unroll-quote p {
  margin: 0 0 12px;
  font-family: var(--p-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(26px, 2.6vw, 38px);
  line-height: 1.18;
  color: var(--p-ink);
  text-wrap: balance;
}

.unroll-quote footer {
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.unroll-scene-title {
  margin: 4px 0 10px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.unroll-summary {
  margin: 0 0 24px;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.65;
  color: var(--p-ink-2);
}

/* Ink on parchment: the one dark button on the light object. */
.unroll-carry {
  background: #1f1a16;
  border-color: #1f1a16;
  color: #f6f1e8;
}

.unroll-carry:hover {
  background: #3e2c17;
  border-color: #3e2c17;
}

.unroll-carry:focus-visible {
  outline: 2px solid #1f1a16;
  outline-offset: 3px;
}

/* ---- The bema: the scroll held up, the question cut into the stone ---- */
.gathering {
  position: relative;
  isolation: isolate;
  overflow-x: clip;
  padding-top: clamp(80px, 10vw, 136px);
  scroll-margin-top: 72px;
  background:
    radial-gradient(ellipse 50% 42% at 50% 62%, rgba(240, 182, 96, 0.07), rgba(240, 182, 96, 0) 70%);
}

/* The Pnyx at dusk stands behind the platform, faint under the night: the
   question is cut into a slab on the hill where Athens once voted. */
.pnyx {
  position: absolute;
  z-index: -1;
  left: 50%;
  bottom: 0;
  width: max(1500px, 100%);
  height: min(100%, 980px);
  transform: translateX(-50%);
  pointer-events: none;
  -webkit-mask-image: linear-gradient(180deg, transparent 0%, #000 34%, #000 70%, transparent 100%);
  mask-image: linear-gradient(180deg, transparent 0%, #000 34%, #000 70%, transparent 100%);
}

.pnyx img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 50% 62%;
  opacity: 0.36;
  filter: saturate(0.8);
}

.pnyx::after {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 46% 60% at 50% 58%, rgba(11, 14, 19, 0.72) 0%, rgba(11, 14, 19, 0.4) 60%, rgba(11, 14, 19, 0.1) 100%),
    linear-gradient(90deg, var(--p-bg) 0%, rgba(11, 14, 19, 0) 18%, rgba(11, 14, 19, 0) 82%, var(--p-bg) 100%);
}

.bema-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.bema-head {
  text-align: center;
  margin-inline: auto;
  margin-bottom: 36px;
}

.bema-head h2,
.bema-head p,
.bema-head .p-eyebrow {
  margin-inline: auto;
}

.panel-title {
  display: block;
  margin: 0 0 14px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  color: var(--p-ink);
}

/* A focus target after the move to this section, not a control: no ring. */
h3.panel-title:focus {
  outline: none;
}

/* The scroll, held up above the platform. */
.held {
  position: relative;
  z-index: 1;
  width: min(760px, 100%);
}

.held-title {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  text-align: center;
  color: var(--p-gold);
}

.held-scroll {
  position: relative;
  margin: 0 14px;
}

.held-scroll::before,
.held-scroll::after {
  content: '';
  position: absolute;
  z-index: 1;
  left: -14px;
  right: -14px;
  height: 12px;
  background: linear-gradient(180deg, #a07a45 0%, #6b4e2b 45%, #3e2c17 100%);
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.45);
}

.held-scroll::before {
  top: -6px;
}

.held-scroll::after {
  bottom: -6px;
}


/* The platform: a block of night marble with a cornice, two steps below. */
.bema-block {
  position: relative;
  width: min(980px, 100%);
  margin-top: 30px;
}

.bema-cornice {
  height: 14px;
  margin: 0 -14px;
  background: linear-gradient(180deg, #57524b 0%, #3a3732 55%, #26241f 100%);
  box-shadow: 0 6px 14px rgba(0, 0, 0, 0.45);
}

.bema-face {
  position: relative;
  padding: 30px clamp(20px, 4vw, 56px) 28px;
  background-color: #1c1d20;
  background-image:
    var(--p-marble-texture),
    linear-gradient(180deg, #2b2b2d 0%, #1f2023 50%, #18191c 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), inset 0 -40px 60px rgba(0, 0, 0, 0.35);
  transition: box-shadow 0.3s ease;
}

.bema-face:focus-within {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), inset 0 -40px 60px rgba(0, 0, 0, 0.35), inset 0 0 0 1px rgba(240, 182, 96, 0.5);
}

.inscription-label {
  display: block;
  margin: 0 0 12px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  text-align: center;
  color: var(--p-ink-3);
}

/* The question, cut into the face: large Cormorant, carved light and shadow,
   a gold caret. Still a plain textarea. */
.inscription {
  display: block;
  width: 100%;
  min-height: 120px;
  padding: 10px 4px;
  border: none;
  border-bottom: 1px solid rgba(242, 237, 228, 0.16);
  background: transparent;
  font-family: var(--p-font-display);
  font-size: clamp(21px, 2vw, 28px);
  font-weight: 500;
  line-height: 1.36;
  text-align: center;
  color: #e9e2d6;
  caret-color: var(--p-gold);
  text-shadow: 0 -1px 0 rgba(0, 0, 0, 0.75), 0 1px 0 rgba(255, 244, 228, 0.1);
  resize: vertical;
  transition: border-color 0.2s ease;
}

.inscription::placeholder {
  color: var(--p-ink-4);
  font-style: italic;
  text-shadow: none;
}

.inscription:focus {
  outline: none;
  border-bottom-color: var(--p-gold);
}

.inscription:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 6px;
}

.inscription:disabled {
  opacity: 0.6;
}

.question-hint {
  margin: 14px auto 0;
  max-width: 62ch;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  text-align: center;
  color: var(--p-ink-3);
}

.bema-steps {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

.bema-steps span {
  display: block;
  height: 12px;
  background: linear-gradient(180deg, #34322e 0%, #1d1c1a 100%);
  border-top: 1px solid rgba(255, 238, 214, 0.1);
}

.bema-steps span:nth-child(1) {
  margin: 0 -22px;
}

.bema-steps span:nth-child(2) {
  margin: 0 -40px;
  opacity: 0.7;
}

/* Below the platform: how long, and the one "Let Athens speak". */
.bema-foot {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 340px);
  gap: 26px 36px;
  align-items: end;
  width: min(980px, 100%);
  margin-top: 40px;
}

.begin-wrap {
  min-width: 0;
}

.scene-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 0;
  border: none;
  background: none;
  text-align: left;
  color: inherit;
  font: inherit;
  cursor: pointer;
  scroll-snap-align: start;
  min-width: 0;
}

.scene-frame {
  position: relative;
  display: block;
  width: 100%;
  overflow: hidden;
  margin-bottom: 12px;
  background: var(--tile, var(--p-surface-2));
  outline: 1px solid var(--p-line);
  outline-offset: -1px;
}


.scene-frame img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scale(1.01);
  transition: transform 1.2s cubic-bezier(0.22, 1, 0.36, 1);
  filter: saturate(0.92);
}

.scene-card:hover img {
  transform: scale(1.05);
}

.scene-card.selected .scene-frame {
  outline: 2px solid var(--gold);
  outline-offset: -2px;
  box-shadow: 0 24px 60px -28px rgba(240, 182, 96, 0.55);
}





/* Arrivals: the omens, then a mosaic of scenes */
.omens,
.bema {
  position: relative;
  overflow: hidden;
  min-height: clamp(420px, 56vw, 620px);
  margin-bottom: 44px;
  display: flex;
  align-items: flex-end;
  background: var(--p-surface-2);
}

.omens-image,
.bema-image {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.omens-shade,
.bema-shade {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(0deg, rgba(11, 14, 19, 0.96) 0%, rgba(11, 14, 19, 0.72) 42%, rgba(11, 14, 19, 0.12) 78%),
    linear-gradient(90deg, rgba(11, 14, 19, 0.6), rgba(11, 14, 19, 0) 60%);
}

.omens-body,
.bema-body {
  position: relative;
  padding: 48px 0 44px;
}

.omens-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr);
  gap: 40px;
  align-items: end;
}

.omens-lead h3,
.bema-body h3 {
  margin: 0 0 12px;
  font-family: var(--p-font-display);
  font-size: clamp(30px, 3.4vw, 46px);
  font-weight: 500;
  line-height: 1.05;
  color: var(--p-ink);
}

.omens-lead p,
.bema-body p {
  max-width: 52ch;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
}

.omens-note {
  margin-top: 10px;
  font-family: var(--p-font-body) !important;
  font-size: var(--t-sm) !important;
  color: var(--p-ink-3) !important;
}

.omen-list {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px 26px;
  margin: 0;
  padding: 0;
}

.omen {
  padding-left: 14px;
  border-left: 1px solid var(--gold);
  min-width: 0;
}

.omen p {
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.4;
  color: var(--p-ink);
  text-shadow: 0 1px 12px rgba(0, 0, 0, 0.6);
}

.omen span {
  display: block;
  margin-top: 6px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--gold);
}

.mosaic {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 28px 22px;
}

.scene-card.lead {
  grid-column: span 2;
  grid-row: span 2;
}

/* A closing feature tile mirrors the lead: bottom-right on four columns, so ten
   cards fill four even rows. */
.scene-card.lead-close {
  grid-column: 3 / span 2;
  grid-row: 3 / span 2;
}

.scene-frame {
  aspect-ratio: 3 / 2;
}

.scene-card.lead .scene-frame,
.scene-card.lead-close .scene-frame {
  aspect-ratio: 4 / 3;
}

.scene-meta {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--gold);
}

.scene-title {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  line-height: 1.1;
  color: var(--p-ink);
}

.scene-card.lead .scene-title,
.scene-card.lead-close .scene-title {
  font-size: clamp(28px, 2.6vw, 36px);
}

.scene-challenge {
  font-size: var(--t-sm);
  line-height: 1.45;
  color: var(--p-ink-3);
}

/* Build: the empty bema */
.bema-body p {
  max-width: 60ch;
}

.builder-wrap {
  margin-bottom: 12px;
}

.own-scroll {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  width: 100%;
  min-height: 56px;
  margin-top: 40px;
  padding: 18px 4px 16px;
  border: none;
  border-top: 1px solid var(--p-control-border);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.own-scroll:hover,
.own-scroll.drag-over {
  border-top-color: var(--gold);
  background: linear-gradient(180deg, rgba(240, 182, 96, 0.06), rgba(240, 182, 96, 0));
}

.own-scroll:focus-visible {
  outline: 2px solid var(--gold);
  outline-offset: 4px;
}

.own-scroll.selected {
  border-top-color: var(--gold);
}

.own-scroll:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.own-scroll-text {
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.own-scroll-text strong {
  color: var(--p-ink);
  font-weight: 600;
}

.own-scroll-cta {
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--gold);
  white-space: nowrap;
}

/* The scroll stays parchment: an object held up in the dark (.p-paper). */
.scroll-sheet {
  max-height: 560px;
  overflow-y: auto;
  padding: 34px 38px;
  background-color: var(--p-surface-2);
  background-image: var(--p-marble-texture);
  box-shadow: var(--p-shadow-2), inset 0 0 70px rgba(160, 110, 50, 0.14);
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.72;
  color: var(--p-ink-2);
}

.scroll-sheet:focus-visible {
  outline: 2px solid var(--gold);
  outline-offset: 4px;
}

.scroll-sheet :deep(h3) {
  margin: 0 0 10px;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 600;
  line-height: 1.12;
  color: var(--p-ink);
}

.scroll-sheet :deep(h4) {
  margin: 24px 0 8px;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  color: var(--p-terracotta);
}

.scroll-sheet :deep(h5) {
  margin: 16px 0 6px;
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  color: var(--p-ink);
}

.scroll-sheet :deep(p) {
  margin: 0 0 12px;
}

.scroll-sheet :deep(ul) {
  margin: 0 0 12px 18px;
  padding: 0;
}

.scroll-sheet :deep(li) {
  margin-bottom: 5px;
}

.scroll-sheet :deep(strong) {
  color: var(--p-ink);
}

.scroll-note {
  margin-top: 12px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.text-button {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  margin-left: 8px;
  padding: 0;
  border: none;
  background: none;
  font-family: var(--p-font-body);
  font-style: normal;
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--gold);
  cursor: pointer;
}

/* The scroll still rolled: the two rods of the parchment, closed on each
   other, with a line of italic between. The whole place takes a drop. */
.scroll-empty {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: center;
  gap: 26px;
  min-height: 200px;
  padding: 40px 14px;
  text-align: center;
  color: var(--p-ink-3);
  transition: background 0.3s ease;
}

.rolled {
  display: block;
  height: 12px;
  margin: 0 -14px;
  border-radius: 6px;
  background: linear-gradient(180deg, #a07a45 0%, #6b4e2b 45%, #3e2c17 100%);
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.45);
  transition: box-shadow 0.3s ease;
}

.scroll-empty.drag-over {
  background: radial-gradient(ellipse 60% 70% at 50% 50%, rgba(240, 182, 96, 0.1), rgba(240, 182, 96, 0));
}

.scroll-empty.drag-over .rolled {
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.45), 0 0 18px rgba(240, 182, 96, 0.5);
}

.scroll-empty p {
  max-width: 420px;
  margin: 0 auto;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.4;
  color: var(--p-ink-2);
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
}

.file-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--t-sm);
  color: var(--p-ink-2);
}

.file-remove {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin: -8px -8px -8px 0;
  border: none;
  background: none;
  font-size: 20px;
  line-height: 1;
  color: var(--p-ink-3);
  cursor: pointer;
}

.file-remove:hover {
  color: var(--p-error);
}






/* How long Athens talks */
.length {
  margin: 0 0 22px;
  padding: 0;
  border: 0;
  min-width: 0;
}

.length legend {
  padding: 0;
}

.length-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.length-option {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--p-control-border);
  background: var(--p-surface);
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  min-width: 0;
}

.length-option:hover {
  border-color: var(--gold);
}

.length-option.chosen {
  border-color: var(--gold);
  background: var(--p-terracotta-tint);
  box-shadow: inset 0 0 0 1px var(--gold);
}

.length-option:focus-within {
  outline: 2px solid var(--gold);
  outline-offset: 3px;
}

.length:disabled .length-option {
  cursor: not-allowed;
  opacity: 0.6;
}

.length-name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  line-height: 1.1;
  color: var(--p-ink);
}

.length-option.chosen .length-name {
  color: var(--gold);
}

.length-meta {
  font-size: var(--t-xs);
  line-height: 1.45;
  color: var(--p-ink-3);
}

.length-note {
  margin: 10px 0 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.setup-notice {
  margin: 0 0 14px;
  padding: 12px 14px;
  border-left: 2px solid var(--gold);
  background: var(--p-terracotta-tint);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-2);
}

.setup-notice a {
  color: var(--gold);
}

.begin {
  width: 100%;
  justify-content: space-between;
  min-height: 58px;
  font-size: var(--t-md);
}

.begin-arrow {
  font-size: 20px;
}


.archive {
  margin-top: clamp(72px, 9vw, 130px);
  scroll-margin-top: 80px;
}

.footer {
  padding: 72px 0 48px;
  text-align: center;
  border-top: 1px solid var(--p-line);
  margin-top: 40px;
}

.maxim {
  margin: 0;
  font-family: var(--p-font-inscription);
  font-size: var(--t-sm);
  font-weight: 600;
  letter-spacing: 0.34em;
  color: var(--gold);
}

.maxim-gloss {
  margin: 6px 0 18px;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
}

.credits {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

.credits-made {
  max-width: 34em;
  margin: 6px auto 0;
  text-wrap: balance;
}

.credits a {
  display: inline-block;
  padding: 12px 0;
  margin: -12px 0;
  color: var(--p-ink-2);
}

.footer-tools {
  display: flex;
  justify-content: center;
  margin-top: 22px;
}


/* Held up above the bema, the scroll shows a little at a time. */
.held-scroll .scroll-sheet {
  max-height: 380px;
}

.begin-hint {
  margin-top: 8px;
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  text-align: center;
}

@media (max-width: 1100px) {
  .mosaic {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scene-card.lead-close {
    grid-column: span 2;
    grid-row: span 2;
  }

  .omens-body {
    grid-template-columns: 1fr;
    gap: 26px;
  }
}

@media (max-width: 900px) {
  .bema-foot {
    grid-template-columns: 1fr;
  }

  .unroll-sheet {
    grid-template-columns: 1fr;
  }
}

/* Phones: the six become a row to swipe, one at a time, each most of the
   width; the scroll unrolls below. */
@media (max-width: 699px) {
  .figure-row {
    display: flex;
    gap: 0;
    padding: 0 15vw;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scroll-snap-type: x mandatory;
    scrollbar-width: none;
    transform: none;
  }

  .figure-row::-webkit-scrollbar {
    display: none;
  }

  .figure {
    flex: 0 0 70vw;
    margin: 0 -3px;
    scroll-snap-align: center;
  }

  .figure-name {
    font-size: 14px;
  }

  .figure-line {
    font-size: 17px;
  }

  .figure.selected .figure-body {
    transform: translateY(-8px) scale(1.03);
  }

  .step-band {
    height: 104px;
  }

  .unroll-sheet {
    padding: 34px 22px 30px;
  }

  .bema-steps span:nth-child(1) {
    margin: 0 -10px;
  }

  .bema-steps span:nth-child(2) {
    margin: 0 -16px;
  }

  .bema-cornice {
    margin: 0 -8px;
  }
}

@media (max-width: 640px) {
  .topbar {
    padding-inline: 16px;
  }

  .topbar-links {
    gap: 14px;
  }

  .topbar-end {
    gap: 10px;
  }

  /* Twelve pixels at the least, and a hit box at least twenty-four tall */
  .topbar-links a {
    font-size: var(--t-xs);
    letter-spacing: 0.08em;
    padding: 10px 0;
  }

  /* The mark alone on a phone; the word returns with the room for it. */
  .topbar-brand :deep(.p-brand-word) {
    display: none;
  }

  /* The three stages as a list to choose from: bordered rows, the chosen
     one lit with a gold bar, the others pointing on. */
  .tabs {
    grid-template-columns: 1fr;
    gap: 0;
    border: 1px solid var(--p-control-border);
    background: rgba(242, 237, 228, 0.02);
  }

  .tab {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-rows: auto auto;
    align-items: center;
    column-gap: 12px;
    row-gap: 4px;
    min-height: 64px;
    margin: 0;
    padding: 12px 16px 12px 20px;
    border-top: 1px solid var(--p-line-strong);
  }

  .tab:first-child {
    border-top: none;
  }

  .tab::before {
    content: '';
    position: absolute;
    left: -1px;
    top: -1px;
    bottom: -1px;
    width: 3px;
    background: transparent;
    transition: background 0.3s ease;
  }

  .tab.active {
    border-top-color: var(--p-line-strong);
    background: var(--p-surface);
  }

  .tab:first-child.active {
    border-top-color: transparent;
  }

  .tab.active::before {
    background: var(--gold);
  }

  .tab-era {
    grid-column: 1;
  }

  .tab-name {
    grid-column: 1;
    font-size: 24px;
  }

  .tab-chevron {
    display: block;
    grid-column: 2;
    grid-row: 1 / span 2;
    color: var(--p-ink-3);
    transition: transform 0.3s ease, color 0.3s ease;
  }

  .tab.active .tab-chevron {
    color: var(--gold);
    transform: rotate(90deg);
  }

  .tab:focus-visible {
    outline: 2px solid var(--gold);
    outline-offset: -2px;
  }

  .mosaic {
    grid-template-columns: 1fr;
  }

  .scene-card.lead,
  .scene-card.lead-close {
    grid-column: auto;
    grid-row: auto;
  }

  .omen-list {
    grid-template-columns: 1fr;
  }

  .scroll-sheet {
    padding: 22px;
  }

  .own-scroll {
    flex-direction: column;
    align-items: flex-start;
  }

  .length-options {
    grid-template-columns: 1fr;
  }

  .inscription {
    text-align: left;
  }
}

/* The smallest phones: the hero's own button reaches the stages, so the bar
   keeps only the Chronicles beside Listen, and nothing runs under it. */
@media (max-width: 359px) {
  .topbar-stages {
    display: none !important;
  }

  .topbar-links a {
    font-size: 11px;
    letter-spacing: 0.06em;
  }

  .topbar-end {
    gap: 10px;
  }
}

/* Chinese in its own serif, without the Latin capitals' tracking. */
:lang(zh) .topbar-links a,
:lang(zh) .tab-era,
:lang(zh) .figure-name,
:lang(zh) .unroll-work,
:lang(zh) .held-title,
:lang(zh) .inscription-label {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

:lang(zh) .scroll-empty p {
  font-style: normal;
}

/* Chinese is never slanted: the italic voices stand upright. */
:lang(zh) .figure-epithet,
:lang(zh) .figure-line,
:lang(zh) .unroll-place,
:lang(zh) .unroll-quote p,
:lang(zh) .figures-hint {
  font-style: normal;
}

/* Reduced motion: everything is in place at once. */
@media (prefers-reduced-motion: reduce) {
  .unroll,
  .unroll-sheet,
  .figure-body,
  .figure-line,
  .figure-plate {
    transition: none;
  }

  .figure-row,
  .figure-plate img {
    transform: none;
  }

  .figure-plate img {
    transform: scale(1.02);
  }
}
</style>
