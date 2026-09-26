<template>
  <div class="home">
    <header class="topbar" :class="{ solid: !heroInView }">
      <router-link to="/" class="topbar-brand" :aria-label="$t('parthenon.navHome')">
        <ParthenonBrand />
      </router-link>
      <nav class="topbar-links" :aria-label="$t('parthenon.navSections')">
        <a href="#stages">{{ $t('parthenon.navSpeakers') }}</a>
        <a href="#chronicles">{{ $t('parthenon.navArchive') }}</a>
      </nav>
    </header>

    <div ref="heroWrap">
      <CinematicHero
        :era="sceneEra"
        :speaker="sceneSpeaker"
        @update:era="chooseEra"
        @begin="openTab(tab, true)"
      />
    </div>

    <main>
      <!-- How a gathering works: the five stations and the path between them -->
      <section id="how" class="how wrap" aria-labelledby="how-title">
        <header class="section-head">
          <p class="p-eyebrow">{{ $t('parthenon.how.eyebrow') }}</p>
          <h2 id="how-title">{{ $t('parthenon.how.title') }}</h2>
          <p>{{ $t('parthenon.how.lede') }}</p>
        </header>
        <ol ref="wayLine" class="way-line" :class="{ drawn: wayDrawn }" role="list">
          <svg class="way-path" viewBox="0 0 1000 44" preserveAspectRatio="none" aria-hidden="true">
            <path d="M100 22 C170 6, 230 38, 300 22 S430 6, 500 22 S630 38, 700 22 S830 6, 900 22" />
          </svg>
          <li v-for="(m, i) in movements" :key="i" class="station">
            <span class="station-coin" aria-hidden="true">{{ ACTS[i]?.numeral }}</span>
            <h3>{{ m.title }}</h3>
            <p>{{ m.desc }}</p>
          </li>
        </ol>
      </section>

      <!-- Choose your stage -->
      <section id="stages" class="stages">
        <div class="wrap">
          <header class="section-head">
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
            </button>
          </div>
        </div>

        <!-- Athens, 399 BC -->
        <div v-show="tab === 'athens'" id="panel-athens" role="tabpanel" aria-labelledby="tab-athens">
          <div class="wrap">
            <p class="panel-intro">{{ $t('parthenon.speakersDesc') }}</p>
          </div>
          <div class="filmstrip" role="group" :aria-label="$t('parthenon.tabAthens')">
            <button
              v-for="(s, i) in speakers"
              :key="s.id"
              type="button"
              class="portrait-card"
              :class="{ selected: isSelected('speaker', s.id) }"
              :aria-pressed="isSelected('speaker', s.id)"
              :disabled="loading"
              @click="chooseSpeaker(s)"
            >
              <span class="portrait-frame" :style="{ '--tile': tone(i) }">
                <img
                  :src="`/media/portraits/${s.id}.jpg`"
                  alt=""
                  width="800"
                  height="993"
                  :loading="i < 4 ? 'eager' : 'lazy'"
                  decoding="async"
                />
              </span>
              <span class="portrait-name">{{ s.name }}</span>
              <span class="portrait-work">{{ s.work }}</span>
              <span class="portrait-meta">{{ s.place }}, {{ s.year }}</span>
              <span class="portrait-line">“{{ s.line }}”</span>
            </button>
          </div>
        </div>

        <!-- The Arrivals, 2026 -->
        <div v-show="tab === 'arrivals'" id="panel-arrivals" role="tabpanel" aria-labelledby="tab-arrivals">
          <div class="omens">
            <img
              class="omens-image"
              src="/media/scenes/golden-handmaidens.jpg"
              alt="Golden handmaidens at work in the forge of Hephaestus"
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
                    :loading="i < 3 ? 'eager' : 'lazy'"
                    decoding="async"
                  />
                </span>
                <span class="scene-meta">{{ a.year }}, {{ formatLabel(a.format).toLowerCase() }}</span>
                <span class="scene-title">{{ a.title }}</span>
                <span class="scene-challenge">{{ a.challenge }}</span>
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
              alt="The empty speaker's platform on the Pnyx at dusk, facing the Acropolis"
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

      <!-- The scroll and the question -->
      <section id="gathering" class="gathering wrap">
        <div class="scroll-panel">
          <h3 ref="scrollTitle" class="panel-title" tabindex="-1">{{ $t('parthenon.scrollLabel') }}</h3>

          <template v-if="selection">
            <article class="scroll-sheet p-paper" v-html="scrollHtml"></article>
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

          <div
            v-else
            class="scroll-empty"
            :class="{ 'drag-over': isDragOver }"
            @dragover.prevent="handleDragOver"
            @dragleave.prevent="handleDragLeave"
            @drop.prevent="handleDrop"
          >
            <p>{{ $t('parthenon.scrollEmpty') }}</p>
          </div>
        </div>

        <div class="question-panel">
          <label class="panel-title" for="city-question">{{ $t('parthenon.questionLabel') }}</label>
          <textarea
            id="city-question"
            ref="questionInput"
            v-model="formData.simulationRequirement"
            class="question-input"
            rows="7"
            :placeholder="$t('parthenon.questionPlaceholder')"
            :disabled="loading"
          ></textarea>
          <p class="question-hint">{{ $t('parthenon.questionHint') }}</p>

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

          <p v-if="zepMissing" class="setup-notice" role="status">
            {{ $t('parthenon.zepMissing') }}
            <a href="https://app.getzep.com" target="_blank" rel="noopener">app.getzep.com</a>
          </p>
          <button type="button" class="p-button begin" :disabled="!canSubmit || loading || zepMissing" @click="startSimulation">
            <span>{{ loading ? $t('home.initializing') : $t('parthenon.begin') }}</span>
            <span class="begin-arrow" aria-hidden="true">→</span>
          </button>
          <p v-if="!canSubmit" class="begin-hint">{{ $t('parthenon.beginHint') }}</p>
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
      <div class="footer-tools"><LanguageSwitcher /></div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import ParthenonBrand from '../components/ParthenonBrand.vue'
import CinematicHero from '../components/CinematicHero.vue'
import StageBuilder from '../components/StageBuilder.vue'
import { speakers, speakerSeedFile } from '../parthenon/speakers.js'
import { arrivals, arrivalSeedFile } from '../parthenon/arrivals/index.js'
import { FORMATS } from '../parthenon/composeStage.js'
import { ACTS, RUN_LENGTHS } from '../parthenon/vocabulary.js'
import { getInstanceStatus } from '../api/parthenon.js'
import pendingUpload, { setPendingUpload } from '../store/pendingUpload.js'

const router = useRouter()
const { t, tm } = useI18n()

const movements = computed(() => tm('parthenon.movements'))
const omens = computed(() => tm('parthenon.omens'))

const tabs = [
  { id: 'athens', era: 'tabAthensEra', name: 'tabAthens' },
  { id: 'arrivals', era: 'tabArrivalsEra', name: 'tabArrivals' },
  { id: 'build', era: 'tabBuildEra', name: 'tabBuild' }
]
const tab = ref('athens')

// The tabs stack into a column at 640px and below (see the CSS); keys and aria-orientation follow.
const tabsVertical = ref(false)
let narrowQuery = null
const syncTabsOrientation = () => {
  tabsVertical.value = !!narrowQuery?.matches
}

// Warm darks for a tile before its paint arrives, so no frame is ever flat black.
const TONES = ['#2b2019', '#1e2431', '#2d2126', '#1f2a27', '#332616', '#252030', '#2a2418', '#1c2632', '#302020', '#232b1f']
const tone = (i) => TONES[i % TONES.length]

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
const lengthMeta = (l) =>
  /hour/.test(String(l.minutes))
    ? t('parthenon.length.metaLong', { hours: l.hours, span: l.minutes })
    : t('parthenon.length.meta', { hours: l.hours, minutes: l.minutes })

const loading = ref(false)
const isDragOver = ref(false)

const fileInput = ref(null)

// Where keyboard focus lands after the page jumps to the scroll and the question.
const scrollTitle = ref(null)
const questionInput = ref(null)

const canSubmit = computed(() => {
  return formData.value.simulationRequirement.trim() !== '' && files.value.length > 0
})

const isSelected = (kind, id) => selection.value?.kind === kind && selection.value?.id === id

const formatLabel = (id) => FORMATS.find((f) => f.id === id)?.label || ''

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

const presetQuestions = new Set([...speakers, ...arrivals].map((item) => item.question))
const isPresetQuestion = (text) => presetQuestions.has(text) || text === selection.value?.question

// Top bar sits over the hero until the hero leaves the screen.
const heroWrap = ref(null)
const heroInView = ref(true)
let heroObserver = null

// The path between the stations draws itself when the Way comes into view.
const wayLine = ref(null)
const wayDrawn = ref(false)
let wayObserver = null

// What this instance can run (e.g. a missing Zep key), shown before a run fails.
const instance = ref(null)

// Without a Zep key the hearing fails after the first reading, so hold the run here.
const zepMissing = computed(() => instance.value?.zepConfigured === false)

onMounted(() => {
  getInstanceStatus()
    .then((res) => { instance.value = res.data })
    .catch(() => { instance.value = null })
  heroObserver = new IntersectionObserver(([entry]) => {
    heroInView.value = entry.intersectionRatio > 0.12
  }, { threshold: [0, 0.12, 0.5] })
  if (heroWrap.value) heroObserver.observe(heroWrap.value)
  wayObserver = new IntersectionObserver(([entry]) => {
    if (!entry.isIntersecting) return
    wayDrawn.value = true
    wayObserver?.disconnect()
  }, { threshold: 0.35 })
  if (wayLine.value) wayObserver.observe(wayLine.value)
  narrowQuery = window.matchMedia('(max-width: 640px)')
  syncTabsOrientation()
  narrowQuery.addEventListener('change', syncTabsOrientation)
})

onBeforeUnmount(() => {
  heroObserver?.disconnect()
  wayObserver?.disconnect()
  narrowQuery?.removeEventListener('change', syncTabsOrientation)
})

// Read at call time, so turning reduced motion on mid-visit takes effect at once.
const scrollBehavior = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'

// Jump to a section and bring keyboard focus along, so the next Tab starts there.
const scrollToId = async (id) => {
  await nextTick()
  document.getElementById(id)?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
  const target = id === 'gathering'
    ? (formData.value.simulationRequirement.trim() ? scrollTitle.value : questionInput.value)
    : document.getElementById(`tab-${tab.value}`)
  target?.focus({ preventScroll: true })
}

const openTab = (id, scroll = false) => {
  tab.value = id
  eraOverride.value = null
  if (scroll) scrollToId('stages')
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
const present = (item, file) => {
  const current = formData.value.simulationRequirement.trim()
  if (!current || isPresetQuestion(current)) {
    formData.value.simulationRequirement = item.question
  }
  selection.value = item
  eraOverride.value = null
  files.value = [file]
  scrollToId('gathering')
}

const chooseSpeaker = (speaker) => {
  if (loading.value) return
  present({
    kind: 'speaker',
    id: speaker.id,
    title: speaker.name,
    letter: speaker.letter,
    era: 'ancient',
    markdown: speaker.seed,
    fileName: speaker.fileName,
    question: speaker.question
  }, speakerSeedFile(speaker))
}

const chooseArrival = (arrival) => {
  if (loading.value) return
  present({
    kind: 'arrival',
    id: arrival.id,
    title: arrival.name,
    letter: arrival.letter,
    era: 'now',
    markdown: arrival.seed,
    fileName: arrival.fileName,
    question: arrival.question,
    noteKey: arrival.noteKey
  }, arrivalSeedFile(arrival))
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

// Just enough Markdown for the scrolls (headings, lists, emphasis).
const escapeHtml = (text) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const inline = (text) =>
  escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')

const renderScroll = (markdown) => {
  const html = []
  for (const block of markdown.trim().split(/\n{2,}/)) {
    const lines = block.split('\n')
    if (lines.every((l) => l.startsWith('- '))) {
      html.push(`<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join('')}</ul>`)
      continue
    }
    for (const line of lines) {
      if (line.startsWith('### ')) html.push(`<h5>${inline(line.slice(4))}</h5>`)
      else if (line.startsWith('## ')) html.push(`<h4>${inline(line.slice(3))}</h4>`)
      else if (line.startsWith('# ')) html.push(`<h3>${inline(line.slice(2))}</h3>`)
    }
    const prose = lines.filter((l) => !l.startsWith('#')).join(' ')
    if (prose) html.push(`<p>${inline(prose)}</p>`)
  }
  return html.join('')
}

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
  background: linear-gradient(180deg, rgba(8, 10, 14, 0.55), rgba(8, 10, 14, 0));
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
}

.topbar-links {
  display: flex;
  align-items: center;
  gap: clamp(14px, 2.6vw, 30px);
  min-width: 0;
}

.topbar-links a {
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

/* How a gathering works: five stations on a drawn path */
.how {
  padding-top: clamp(72px, 10vw, 128px);
  scroll-margin-top: 68px;
}

.way-line {
  position: relative;
  list-style: none;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 24px;
  margin: 44px 0 0;
  padding: 0;
}

.way-path {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 44px;
  overflow: visible;
  pointer-events: none;
}

/* The path is about 830 user units long; one dash that long hides it until the
   Way comes into view, then slides in from the first station. */
.way-path path {
  fill: none;
  stroke: var(--gold);
  stroke-width: 1.2;
  stroke-linecap: round;
  opacity: 0.85;
  stroke-dasharray: 900;
  stroke-dashoffset: 900;
  transition: stroke-dashoffset 2.6s cubic-bezier(0.22, 1, 0.36, 1);
}

.way-line.drawn .way-path path {
  stroke-dashoffset: 0;
}

.station {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 0 8px;
  min-width: 0;
}

.station-coin {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin-bottom: 18px;
  border-radius: var(--p-radius-coin);
  border: 1px solid var(--gold);
  background: var(--p-bg);
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  color: var(--gold);
  box-shadow: 0 0 0 6px var(--p-bg);
}

.station h3 {
  margin: 0 0 8px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  line-height: 1.1;
  color: var(--p-ink);
}

.station p {
  margin: 0;
  font-size: var(--t-sm);
  line-height: 1.55;
  color: var(--p-ink-3);
  max-width: 26ch;
}

/* Choose your stage */
.stages {
  padding: clamp(72px, 10vw, 128px) 0 0;
  scroll-margin-top: 68px;
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

/* Athens: a film strip of faces */
.filmstrip {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: clamp(230px, 22vw, 300px);
  gap: 22px;
  overflow-x: auto;
  --strip-inset: max(var(--p-gutter), (100vw - 1240px) / 2);
  scroll-snap-type: x mandatory;
  scroll-padding-inline: var(--strip-inset);
  padding: 4px var(--strip-inset) 24px;
  scrollbar-width: thin;
  scrollbar-color: var(--p-line-strong) transparent;
}

.portrait-card,
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

.portrait-frame,
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

.portrait-frame {
  aspect-ratio: 4 / 5;
}

.portrait-frame img,
.scene-frame img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scale(1.01);
  transition: transform 1.2s cubic-bezier(0.22, 1, 0.36, 1);
  filter: saturate(0.92);
}

.portrait-card:hover img,
.scene-card:hover img {
  transform: scale(1.05);
}

.portrait-card.selected .portrait-frame,
.scene-card.selected .scene-frame {
  outline: 2px solid var(--gold);
  outline-offset: -2px;
  box-shadow: 0 24px 60px -28px rgba(240, 182, 96, 0.55);
}

.portrait-name {
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.05;
  color: var(--p-ink);
}

.portrait-work {
  font-size: var(--t-sm);
  font-weight: 500;
  color: var(--p-ink-2);
}

.portrait-meta {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

.portrait-line {
  margin-top: 6px;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.35;
  color: var(--gold);
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
  margin-top: 40px;
  padding: 18px 22px;
  border: 1px dashed var(--p-line-strong);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.own-scroll:hover,
.own-scroll.drag-over {
  border-color: var(--gold);
  background: var(--p-surface);
}

.own-scroll.selected {
  border-style: solid;
  border-color: var(--gold);
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

/* The scroll and the question */
.gathering {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 40px;
  align-items: start;
  padding-top: clamp(72px, 9vw, 120px);
  scroll-margin-top: 80px;
}

.panel-title {
  display: block;
  margin: 0 0 14px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  color: var(--p-ink);
}

/* A focus target after the jump to this section, not a control: no ring. */
h3.panel-title:focus {
  outline: none;
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

.scroll-empty {
  display: grid;
  place-items: center;
  min-height: 300px;
  padding: 30px;
  border: 1px dashed var(--p-line-strong);
  text-align: center;
  color: var(--p-ink-3);
  transition: border-color 0.2s, background 0.2s;
}

.scroll-empty.drag-over {
  border-color: var(--gold);
  background: var(--p-surface);
}

.scroll-empty p {
  max-width: 320px;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
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

.question-panel {
  position: sticky;
  top: 92px;
  min-width: 0;
}

.question-input {
  width: 100%;
  padding: 16px 18px;
  border: 1px solid var(--p-line-strong);
  background: var(--p-surface);
  font-family: var(--p-font-body);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink);
  resize: vertical;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.question-input::placeholder {
  color: var(--p-ink-4);
}

.question-input:focus {
  outline: none;
  border-color: var(--gold);
  box-shadow: 0 0 0 3px var(--p-terracotta-tint);
}

.question-hint {
  margin: 10px 0 26px;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
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
  border: 1px solid var(--p-line-strong);
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

.begin-hint {
  margin-top: 8px;
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  text-align: center;
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

.credits a {
  color: var(--p-ink-2);
}

.footer-tools {
  display: flex;
  justify-content: center;
  margin-top: 22px;
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
  .gathering {
    grid-template-columns: 1fr;
  }

  .question-panel {
    position: static;
  }

  /* The Way stands upright: one line down the left, the coins on it. */
  .way-line {
    grid-template-columns: 1fr;
    gap: 26px;
  }

  .way-path {
    display: none;
  }

  .way-line::before {
    content: '';
    position: absolute;
    top: 22px;
    bottom: 22px;
    left: 22px;
    width: 1px;
    background: linear-gradient(180deg, var(--gold), rgba(240, 182, 96, 0.15));
  }

  .station {
    align-items: flex-start;
    text-align: left;
    padding: 0 0 0 66px;
  }

  .station-coin {
    position: absolute;
    left: 0;
    top: 0;
    margin: 0;
    box-shadow: none;
  }

  .station p {
    max-width: 48ch;
  }
}

@media (max-width: 640px) {
  .topbar {
    padding-inline: 16px;
  }

  .topbar-links {
    gap: 14px;
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

  .tabs {
    grid-template-columns: 1fr;
  }

  .tab {
    padding: 14px 0;
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
}
</style>
