<template>
  <section ref="rootEl" class="chronicle-film" :class="`is-${view}`" :aria-labelledby="ids.title">
    <div class="p-meander ink cf-rule" aria-hidden="true"></div>

    <header class="cf-head">
      <p class="cf-eyebrow">{{ $t('parthenon.film.eyebrow') }}</p>
      <h2 :id="ids.title" ref="headingEl" class="cf-title" tabindex="-1">{{ $t('parthenon.film.title') }}</h2>
      <!-- How a film is made is said while one is being made, not over a finished film -->
      <p v-if="view !== 'completed' || composing" class="cf-lede">{{ $t('parthenon.film.lede') }}</p>
    </header>

    <!-- Stage changes and the finished film, for screen readers -->
    <p class="visually-hidden" aria-live="polite" aria-atomic="true">{{ announcement }}</p>

    <p v-if="view === 'checking'" class="cf-quiet-line">{{ $t('parthenon.film.checking') }}</p>

    <!-- The first status read failed: no Film it until we know whether a film is already here -->
    <div v-else-if="view === 'unknown'" class="cf-unknown">
      <p class="cf-quiet-line">{{ checkLine }}</p>
      <div class="cf-actions">
        <button
          ref="recheckButton"
          type="button"
          class="p-button ghost"
          :aria-disabled="rechecking ? 'true' : undefined"
          @click="checkAgain"
        >
          {{ $t('parthenon.film.retry') }}
        </button>
      </div>
    </div>

    <!-- Filming: stage, progress and the shots as they are painted -->
    <div v-else-if="view === 'running'" class="cf-running">
      <div class="cf-progress">
        <div class="cf-stage-row">
          <p ref="stageEl" class="cf-stage" tabindex="-1">{{ stageLabel }}</p>
          <span class="cf-percent" aria-hidden="true">{{ film.progress }}%</span>
        </div>
        <div
          class="cf-bar"
          role="progressbar"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-label="$t('parthenon.film.progressLabel')"
          :aria-valuenow="film.progress"
          :aria-valuetext="$t('parthenon.film.progressValue', { stage: stageLabel, percent: film.progress })"
        >
          <span class="cf-bar-fill" :style="{ transform: `scaleX(${film.progress / 100})` }"></span>
        </div>
        <p v-if="stageDetail" class="cf-detail">{{ stageDetail }}</p>
        <p v-if="pollTrouble" class="cf-detail cf-detail--warn">{{ $t('parthenon.film.reconnecting') }}</p>
      </div>

      <p v-if="filmWords(film.title)" class="cf-working">
        <span class="cf-working-label">{{ $t('parthenon.film.workingTitle') }}</span>
        <span class="cf-working-title">{{ filmWords(film.title) }}</span>
      </p>

      <p v-if="!shots.length" class="cf-quiet-line">{{ $t('parthenon.film.shotsPending') }}</p>
      <ol v-else class="cf-shots" role="list" :aria-label="$t('parthenon.film.shotsLabel')">
        <li v-for="shot in shots" :key="shot.key" class="cf-shot" :class="`is-${shot.phase}`">
          <div class="cf-shot-frame">
            <img
              v-if="shot.thumb"
              :src="shot.thumb"
              :alt="$t('parthenon.film.shotAlt', { n: shot.number })"
              loading="lazy"
              decoding="async"
            />
            <span v-else class="cf-shot-numeral" aria-hidden="true">{{ shot.number }}</span>
          </div>
          <div class="cf-shot-meta">
            <span class="cf-shot-number">{{ $t('parthenon.film.shotNumber', { n: shot.number }) }}</span>
            <span class="cf-shot-status">{{ shot.statusLabel }}</span>
          </div>
          <p v-if="shot.narration" class="cf-shot-line">{{ shot.narration }}</p>
        </li>
      </ol>
    </div>

    <!-- The finished film. It plays in the city's own chrome: a gold coin, a
         thin gold line, the narrator's words under the picture. Pressing play
         lets the page fall dark and lifts the frame into a theatre across the
         screen; Esc, the leave button or the dark itself brings it back. The
         browser's own controls stand in only until the player has woken. -->
    <template v-else-if="view === 'completed'">
      <figure class="cf-film">
        <div class="cf-hold" :style="theatre ? { height: `${holdHeight}px` } : undefined">
          <Teleport to="body" :disabled="!theatre">
            <div
              class="cf-stage"
              :class="{ lifted: theatre, still: reducedMotion }"
              :role="theatre ? 'dialog' : undefined"
              :aria-modal="theatre ? 'true' : undefined"
              :aria-label="theatre ? $t('parthenon.film.player.theatre') : undefined"
              @click.self="leaveTheatre"
            >
              <div
                ref="theatreEl"
                class="cf-theatre"
                :class="{ playing: playing, started, fullscreen: isFull, 'words-on': wordsOn }"
                @keydown="onPlayerKey"
              >
                <div class="cf-screen" @click="togglePlay">
                  <video
                    ref="videoEl"
                    :key="videoSrc"
                    class="cf-video"
                    :controls="!enhanced"
                    playsinline
                    preload="metadata"
                    crossorigin="anonymous"
                    :poster="posterSrc || undefined"
                    :aria-label="$t('parthenon.film.videoLabel', { title: filmTitle })"
                    @play="onFilmPlay"
                    @playing="onFilmPlaying"
                    @pause="onFilmPause"
                    @ended="onFilmEnded"
                    @emptied="onFilmRest"
                    @loadedmetadata="onMeta"
                    @durationchange="onMeta"
                    @timeupdate="onTime"
                    @volumechange="onVolume"
                  >
                    <source :src="videoSrc" type="video/mp4" />
                    <track
                      v-if="captionsSrc"
                      ref="trackEl"
                      kind="captions"
                      :srclang="captionsLang || undefined"
                      :label="captionsLabel || undefined"
                      :src="captionsSrc"
                      default
                      @load="bindWords"
                    />
                    {{ $t('parthenon.film.noVideo') }}
                  </video>
                  <!-- Before the first frame: one gold coin over the poster -->
                  <span v-if="enhanced && !started" class="cf-big-play" aria-hidden="true">
                    <svg viewBox="0 0 20 20" width="30" height="30"><path d="M6.5 3.8v12.4L16.5 10z" fill="currentColor" /></svg>
                  </span>
                  <!-- The narrator's words, set in the reading serif under the picture -->
                  <p v-if="enhanced && wordsOn && cue" class="cf-words" :lang="cueLang" aria-hidden="true">{{ cue }}</p>
                </div>

                <div v-if="enhanced" class="cf-controls" role="group" :aria-label="$t('parthenon.film.player.label')">
                  <button
                    ref="playButton"
                    type="button"
                    class="cf-coin"
                    :aria-label="playLabel"
                    :title="playLabel"
                    @click="togglePlay"
                  >
                    <svg v-if="playing" viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                      <rect x="5" y="4" width="3.2" height="12" fill="currentColor" />
                      <rect x="11.8" y="4" width="3.2" height="12" fill="currentColor" />
                    </svg>
                    <svg v-else-if="ended" viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                      <path d="M4.2 10a5.8 5.8 0 1 0 1.9-4.3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
                      <path d="M3.4 3.2v3.9h3.9" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
                    </svg>
                    <svg v-else viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                      <path d="M6.5 3.8v12.4L16.5 10z" fill="currentColor" />
                    </svg>
                  </button>

                  <span class="cf-time" aria-hidden="true">{{ clock(now) }}</span>
                  <input
                    class="cf-scrub"
                    type="range"
                    min="0"
                    :max="length || 0"
                    step="0.1"
                    :value="now"
                    :style="{ '--done': `${progress}%` }"
                    :disabled="!length"
                    :aria-label="$t('parthenon.film.player.seek')"
                    :aria-valuetext="$t('parthenon.film.player.seekValue', { now: clock(now), total: clock(length) })"
                    @input="onScrub"
                  />
                  <span class="cf-time cf-time--end" aria-hidden="true">{{ clock(length) }}</span>

                  <span class="cf-tools">
                    <button
                      v-if="captionsSrc"
                      type="button"
                      class="cf-tool"
                      :aria-pressed="wordsOn ? 'true' : 'false'"
                      :aria-label="$t('parthenon.film.player.words')"
                      :title="wordsOn ? $t('parthenon.film.player.wordsOff') : $t('parthenon.film.player.wordsOn')"
                      @click="wordsOn = !wordsOn"
                    >
                      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                        <rect x="2.5" y="4.5" width="15" height="11" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4" />
                        <path d="M5.5 9.2h5.4M12.4 9.2h2.1M5.5 12h2.4M9.4 12h5.1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      class="cf-tool"
                      :aria-label="muted ? $t('parthenon.film.player.unmute') : $t('parthenon.film.player.mute')"
                      :title="muted ? $t('parthenon.film.player.unmute') : $t('parthenon.film.player.mute')"
                      @click="toggleMute"
                    >
                      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                        <path d="M3 8h3l4-3.5v11L6 12H3z" fill="currentColor" />
                        <path v-if="!muted" d="M13 7.2a4 4 0 0 1 0 5.6M15.2 5a7 7 0 0 1 0 10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                        <path v-else d="M13.2 7.6l4.4 4.8M17.6 7.6l-4.4 4.8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                      </svg>
                    </button>
                    <button
                      v-if="canFull"
                      type="button"
                      class="cf-tool"
                      :aria-label="isFull ? $t('parthenon.film.player.leaveFull') : $t('parthenon.film.player.full')"
                      :title="isFull ? $t('parthenon.film.player.leaveFull') : $t('parthenon.film.player.full')"
                      @click="toggleFull"
                    >
                      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                        <path v-if="!isFull" d="M3.5 7.5v-4h4M12.5 3.5h4v4M16.5 12.5v4h-4M7.5 16.5h-4v-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                        <path v-else d="M7.5 3.5v4h-4M16.5 7.5h-4v-4M12.5 16.5v-4h4M3.5 12.5h4v4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                      </svg>
                    </button>
                    <button
                      v-if="theatre"
                      type="button"
                      class="cf-tool cf-leave"
                      :aria-label="$t('parthenon.film.player.leave')"
                      :title="$t('parthenon.film.player.leave')"
                      @click="leaveTheatre"
                    >
                      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                        <path d="M5 5l10 10M15 5L5 15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                      </svg>
                    </button>
                  </span>
                </div>
              </div>
            </div>
          </Teleport>
        </div>
        <figcaption class="cf-caption">
          <h3 ref="filmTitleEl" class="cf-film-title" tabindex="-1">{{ filmTitle }}</h3>
          <p v-if="filmWords(film.logline)" class="cf-logline">{{ filmWords(film.logline) }}</p>
          <p v-if="metaLine" class="cf-meta">{{ metaLine }}</p>
        </figcaption>
      </figure>

      <div v-if="!composing" class="cf-actions">
        <a class="p-button" :href="videoSrc" :download="fileName" @click="onDownload">
          {{ downloading ? $t('parthenon.film.downloading') : $t('parthenon.film.download') }}
        </a>
        <button v-if="mayFilm" ref="againButton" type="button" class="p-button ghost" @click="composeAgain">
          {{ $t('parthenon.film.filmAgain') }}
        </button>
      </div>
    </template>

    <!-- On the public steps with no film makers, or a guest: what there is, in one calm line. -->
    <p v-if="setupAway" class="calm-line inline">{{ awayLine }}</p>

    <!-- Choose a narrator and roll -->
    <div v-if="showSetup" class="cf-setup">
      <div v-if="view === 'failed'" ref="failedEl" class="cf-failed" role="alert" tabindex="-1">
        <p class="cf-failed-title">{{ $t('parthenon.film.failedTitle') }}</p>
        <p class="cf-failed-detail">{{ readable(film.error, '') || $t('parthenon.film.failedFallback') }}</p>
      </div>

      <!-- The narrators are voices: each can be heard before it is chosen. A Hear
           button stands outside its radio's label, so hearing never chooses, and
           it stays pressable while the choice itself waits for the Chronicle. -->
      <fieldset ref="voicesEl" class="cf-voices" :class="{ 'is-disabled': !canStart }">
        <legend class="cf-label">{{ $t('parthenon.film.voiceLabel') }}</legend>
        <div class="cf-segmented">
          <div v-for="v in FILM_VOICES" :key="v" class="cf-seg-cell">
            <label class="cf-seg">
              <input v-model="voice" type="radio" class="visually-hidden" :name="ids.voice" :value="v" :disabled="!canStart" />
              <span class="cf-seg-face">
                <span class="cf-seg-name">{{ $t(`parthenon.film.voices.${v}`) }}</span>
                <span class="cf-seg-note">{{ $t(`parthenon.film.voiceNotes.${v}`) }}</span>
              </span>
            </label>
            <button
              type="button"
              class="cf-hear"
              :aria-pressed="previewing === v ? 'true' : 'false'"
              :aria-label="$t(`parthenon.film.hearVoice.${v}`)"
              @click="preview(v)"
            >
              <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
                <path d="M3 8h3l4-3.5v11L6 12H3z" fill="currentColor" />
                <path
                  d="M13 7.2a4 4 0 0 1 0 5.6M15.2 5a7 7 0 0 1 0 10"
                  class="cf-hear-waves"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                />
              </svg>
              <span>{{ $t('parthenon.film.hear') }}</span>
            </button>
          </div>
        </div>
        <p class="cf-sample" :class="{ 'is-on': !!previewing }">
          <span v-if="previewing">{{ $t('parthenon.film.sampleLine') }}</span>
        </p>
      </fieldset>

      <div class="cf-actions">
        <button
          type="button"
          class="p-button"
          :disabled="!canStart"
          :aria-describedby="ids.hint"
          @click="startFilm"
        >
          {{ startLabel }}
        </button>
        <button v-if="composing" type="button" class="p-button ghost" @click="keepFilm">
          {{ $t('parthenon.film.keepFilm') }}
        </button>
      </div>
      <p :id="ids.hint" class="cf-hint">{{ hintText }}</p>
      <p v-if="startError" class="cf-error" role="alert">{{ startError }}</p>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import i18n, { availableLocales } from '../i18n'
import { FILM_VOICES, filmAssetUrl, getChronicleFilm, startChronicleFilm } from '../api/parthenon'
import { sound, speak, stopSpeaking, voiceUrl, holdDuck } from '../parthenon/sound.js'
import { canControl, featureOn } from '../parthenon/access.js'
import { forReader, readable } from '../parthenon/vocabulary.js'

const props = defineProps({
  reportId: String,
  ready: Boolean,
  // The language the Chronicle's record is written in, and so its film.
  recordLang: { type: String, default: '' }
})

const { t } = useI18n()

const POLL_MS = 3000
// Retrying a failed first status read backs off from POLL_MS up to this.
const RECHECK_MAX_MS = 30000
const VOICE_KEY = 'parthenon.film.voice'
const FILM_STATUSES = ['none', 'running', 'completed', 'failed']
const LANGUAGE_TAG = /^[a-z]{2,3}(-[a-z0-9]{2,8})*$/i

// The backend's stages (services/chronicle_film.py), folded onto the labels we have copy for.
// "queued" is ours: the moment between starting a film and its first status read.
const STAGES = {
  queued: 'queued',
  screenplay: 'screenplay',
  frames: 'painting', // "animating" once any shot is being animated; see stageKey
  narration: 'narrating',
  cutting: 'editing',
  done: 'done'
}
// The backend's shot statuses: "image" while it is painted, "video" while it is animated,
// "still" when animation failed and the painting is used, "skipped" when it is left out.
const SHOT_PHASES = {
  pending: 'pending',
  image: 'painting',
  video: 'animating',
  done: 'done',
  still: 'done',
  skipped: 'failed'
}
// Shot statuses that mean animating has begun for that shot.
const ANIMATING_STATUSES = new Set(['video', 'done', 'still'])
const animationBegun = (shot) => ANIMATING_STATUSES.has(String(shot.status || '').toLowerCase())

const uid = String(useId() || 'cf').replace(/[^A-Za-z0-9_-]/g, '')
const ids = {
  title: `${uid}-film-title`,
  voice: `${uid}-film-voice`,
  hint: `${uid}-film-hint`
}

const emptyFilm = () => ({
  status: 'none',
  stage: null,
  progress: 0,
  message: null,
  title: null,
  logline: null,
  voice: null,
  lang: null,
  duration: null,
  error: null,
  shots: [],
  video_url: null,
  poster_url: null,
  captions_url: null
})

const readVoice = () => {
  try {
    const saved = localStorage.getItem(VOICE_KEY)
    if (FILM_VOICES.includes(saved)) return saved
  } catch {
    // Storage can be blocked; the default voice is fine.
  }
  return FILM_VOICES[0]
}

const film = reactive(emptyFilm())
const voice = ref(readVoice())
const checking = ref(false)
// The first status read failed, so we cannot tell whether Film it would replace a film.
const checkFailed = ref(false)
const checkOffline = ref(false)
const rechecking = ref(false)
const starting = ref(false)
const startError = ref('')
const composing = ref(false)
const finishedHere = ref(false)
const pollFailures = ref(0)
const downloading = ref(false)
// UI locale sent with the request that started the running film, when this panel started it.
const startedLocale = ref('')

const rootEl = ref(null)
const headingEl = ref(null)
const stageEl = ref(null)
const filmTitleEl = ref(null)
const failedEl = ref(null)
const recheckButton = ref(null)
const voicesEl = ref(null)
const againButton = ref(null)
const videoEl = ref(null)

let pollTimer = null
let generation = 0
let requestSeq = 0
let appliedSeq = 0
let loadedFor = null
let statusKnown = false
let unmounted = false

watch(voice, (value) => {
  try {
    localStorage.setItem(VOICE_KEY, value)
  } catch {
    // Remembering the voice is a convenience only.
  }
})

// View

const view = computed(() => {
  if (checking.value) return 'checking'
  if (checkFailed.value) return 'unknown'
  if (film.status === 'running') return 'running'
  if (film.status === 'completed') return film.video_url ? 'completed' : 'failed'
  if (film.status === 'failed') return 'failed'
  return 'setup'
})

// Filming comes only where the film makers can work (a key for them) and for
// the one who began the gathering (on the public steps). At home, always.
const mayFilm = computed(() => featureOn('film') && canControl(props.reportId))
const wantsSetup = computed(() =>
  view.value === 'setup' || view.value === 'failed' || (view.value === 'completed' && composing.value)
)
const showSetup = computed(() => mayFilm.value && wantsSetup.value)
const setupAway = computed(() => !mayFilm.value && (view.value === 'setup' || view.value === 'failed'))
const awayLine = computed(() => (featureOn('film') ? t('parthenon.public.noFilm') : t('parthenon.public.features.film')))

const canStart = computed(() =>
  props.ready && !!props.reportId && !starting.value &&
  !['checking', 'unknown', 'running'].includes(view.value)
)

const startLabel = computed(() => {
  if (starting.value) return t('parthenon.film.starting')
  if (view.value === 'failed') return t('parthenon.film.retry')
  return t('parthenon.film.filmIt')
})

const hintText = computed(() => {
  if (!props.ready) return t('parthenon.film.notReady')
  if (composing.value) return t('parthenon.film.againHint')
  return t('parthenon.film.takesMinutes')
})

const stageKey = computed(() => {
  const key = STAGES[String(film.stage || '').toLowerCase()] || null
  // Shots are painted and animated side by side; once any is animating, that is the work.
  if (key === 'painting' && film.shots.some(animationBegun)) return 'animating'
  return key
})

const stageLabel = computed(() => {
  if (stageKey.value) return t(`parthenon.film.stages.${stageKey.value}`)
  return readable(film.message, '') || t('parthenon.film.stageFallback')
})

// Under a known stage the backend's message only adds something when it counts
// ("Filming the shots (2 of 6 ready)"); otherwise it restates the stage.
const stageDetail = computed(() => {
  const message = readable(film.message, '')
  return stageKey.value && message && /\d/.test(message) ? message : ''
})

const pollTrouble = computed(() => view.value === 'running' && pollFailures.value >= 2)

const checkLine = computed(() => {
  if (rechecking.value) return t('parthenon.film.checking')
  return checkOffline.value ? t('parthenon.film.offline') : t('parthenon.film.reconnecting')
})

const announcement = computed(() => {
  if (view.value === 'unknown') return checkLine.value
  if (view.value === 'running') {
    const percent = Math.floor(film.progress / 10) * 10
    return t('parthenon.film.announce', { stage: stageLabel.value, percent })
  }
  if (view.value === 'completed' && finishedHere.value) return t('parthenon.film.ready')
  return ''
})

// Assets

// The server stamps each asset url with its file's mtime, so a new film of the
// same Chronicle gets fresh urls and an unchanged one stays cached.
const assetSrc = (path) => filmAssetUrl(path)

const videoSrc = computed(() => assetSrc(film.video_url))
const posterSrc = computed(() => assetSrc(film.poster_url))
const captionsSrc = computed(() => assetSrc(film.captions_url))

// The backend narrates and captions in the language of the Chronicle's record (older films:
// the UI locale of the request that started them). Prefer the film's own language (film.json
// 'lang'), then the record's, then the locale this panel started it in, then the UI language.
const captionsLang = computed(() =>
  [film.lang, film.language, props.recordLang, startedLocale.value, i18n.global.locale.value]
    .map((tag) => String(tag || '').trim())
    .find((tag) => LANGUAGE_TAG.test(tag)) || ''
)

const captionsLabel = computed(() => {
  const lang = captionsLang.value
  if (!lang) return ''
  const known = availableLocales.find((item) => item.key === lang)
  if (known) return known.label
  try {
    return new Intl.DisplayNames([lang], { type: 'language' }).of(lang) || lang
  } catch {
    return lang
  }
})

// The film's words, less what the visitor cannot read of them (forReader): a
// Chinese reader keeps a Chinese film, whatever the record's language; an
// English reader never meets Chinese, even in an older film made in Chinese
// for an English record. Only a Chinese record's film is left as it was made.
const filmWords = (text) => forReader(text, props.recordLang || film.lang || undefined, i18n.global.locale.value)

const filmTitle = computed(() => filmWords(film.title) || t('parthenon.film.untitled'))

const formatDuration = (seconds) => {
  const total = Math.round(Number(seconds))
  if (!Number.isFinite(total) || total <= 0) return ''
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

// The narrator is described, never named: a deep voice, a warm one, a bright one.
const metaLine = computed(() => {
  const parts = []
  if (FILM_VOICES.includes(film.voice)) {
    parts.push(t(`parthenon.film.narration.${film.voice}`))
  } else if (film.voice) {
    parts.push(t('parthenon.film.narrated'))
  }
  const runtime = formatDuration(film.duration)
  if (runtime) parts.push(runtime)
  return parts.join(' · ')
})

const fileName = computed(() => {
  const slug = String(film.title || '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return `${slug || 'chronicle'}-film.mp4`
})

const shots = computed(() =>
  [...film.shots]
    .sort((a, b) => (Number(a.index) || 0) - (Number(b.index) || 0))
    .map((shot, i) => {
      const raw = String(shot.status || '').toLowerCase()
      const phase = SHOT_PHASES[raw] || (raw ? 'other' : 'pending')
      return {
        key: shot.index ?? i,
        number: i + 1,
        narration: typeof shot.narration === 'string' ? filmWords(shot.narration) : '',
        thumb: assetSrc(shot.thumb_url),
        phase,
        statusLabel: phase === 'other'
          ? raw.charAt(0).toUpperCase() + raw.slice(1)
          : t(`parthenon.film.shotStatus.${phase}`)
      }
    })
)

// State from the backend

const applyFilm = (data) => {
  const next = { ...emptyFilm(), ...(data && typeof data === 'object' ? data : {}) }
  if (!FILM_STATUSES.includes(next.status)) next.status = 'none'
  const progress = Math.round(Number(next.progress))
  next.progress = Number.isFinite(progress) ? Math.min(100, Math.max(0, progress)) : 0
  next.shots = Array.isArray(next.shots) ? next.shots.filter((s) => s && typeof s === 'object') : []

  const was = film.status
  if (next.status === 'running' && was !== 'running') {
    startedLocale.value = '' // startFilm records its own after this
  }
  if (next.status === 'completed' && was === 'running') finishedHere.value = true
  if (next.status !== 'completed') composing.value = false

  Object.assign(film, next)
}

const isOffline = (err) => err?.code === 'ERR_NETWORK' || err?.message === 'Network Error'

const clearPoll = () => {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

const schedulePoll = () => {
  clearPoll()
  if (unmounted) return
  if (film.status === 'running') {
    pollTimer = setTimeout(refresh, POLL_MS)
  } else if (checkFailed.value) {
    const delay = Math.min(POLL_MS * 2 ** Math.max(pollFailures.value - 1, 0), RECHECK_MAX_MS)
    pollTimer = setTimeout(refresh, delay)
  }
}

async function refresh() {
  const reportId = props.reportId
  if (!reportId || unmounted) return
  const gen = generation
  const seq = ++requestSeq
  try {
    const res = await getChronicleFilm(reportId)
    if (gen !== generation || unmounted || seq < appliedSeq) return
    appliedSeq = seq
    statusKnown = true
    checkFailed.value = false
    applyFilm(res?.data)
    pollFailures.value = 0
  } catch (err) {
    if (gen !== generation || unmounted) return
    pollFailures.value += 1
    if (!statusKnown) {
      checkFailed.value = true
      checkOffline.value = isOffline(err)
    }
    console.warn('Failed to fetch Chronicle film:', err)
  } finally {
    if (gen === generation && !unmounted) {
      checking.value = false
      rechecking.value = false
      schedulePoll()
    }
  }
}

const reset = () => {
  generation += 1
  clearPoll()
  Object.assign(film, emptyFilm())
  loadedFor = null
  statusKnown = false
  checking.value = false
  checkFailed.value = false
  checkOffline.value = false
  rechecking.value = false
  starting.value = false
  startError.value = ''
  composing.value = false
  finishedHere.value = false
  pollFailures.value = 0
  startedLocale.value = ''
}

watch(
  () => [props.reportId, props.ready],
  ([reportId, ready], previous) => {
    if (!previous || reportId !== previous[0]) reset()
    if (reportId && ready && loadedFor !== reportId) {
      loadedFor = reportId
      checking.value = true
      refresh()
    }
  },
  { immediate: true }
)

// Hearing the narrators. A press plays that narrator's sample line through the
// city's one voice (it sounds whether or not Listen is on, since it was asked
// for); a second press stops it. Previewing never changes the chosen narrator.
const previewVoice = ref(null)
const previewSrc = ref('')
let previewSeq = 0
const previewing = computed(() =>
  previewSrc.value && sound.speaking === previewSrc.value ? previewVoice.value : null
)

const playSample = (v, src) => {
  previewVoice.value = v
  previewSrc.value = src
  return speak(src, { always: true })
}

const stopPreview = () => {
  previewSeq += 1
  if (previewing.value) stopSpeaking()
}

const preview = async (v) => {
  if (previewing.value === v) {
    stopPreview()
    return
  }
  const seq = ++previewSeq
  // One voice at a time: the film rests while a narrator is heard.
  const video = videoEl.value
  if (video && !video.paused) video.pause()
  const lang = String(i18n.global.locale.value || 'en')
  const local = voiceUrl(`narrator-${v}`, lang)
  const english = voiceUrl(`narrator-${v}`, 'en')
  const listening = sound.enabled
  const asked = Date.now()
  const ok = await playSample(v, local)
  // A narrator not yet recorded in this language is heard in English: only when
  // the clip failed at once, not when it was stopped or another voice began.
  if (
    !ok && local !== english && !unmounted && seq === previewSeq &&
    !sound.speaking && sound.enabled === listening && Date.now() - asked < 4000
  ) {
    await playSample(v, english)
  }
}

// While the film plays, the night under the page dips for it.
let releaseFilmDuck = null
const onFilmRest = () => {
  if (!releaseFilmDuck) return
  const release = releaseFilmDuck
  releaseFilmDuck = null
  release()
}

// ---- The player ----
// The city's own controls over the film. Until they wake (and wherever script
// never runs) the browser's controls stand in.
const reducedMotion = typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const enhanced = ref(false)
const theatreEl = ref(null)
const trackEl = ref(null)
const playButton = ref(null)
const playing = ref(false)
const started = ref(false)
const ended = ref(false)
const now = ref(0)
const length = ref(0)
const muted = ref(false)
const wordsOn = ref(true)
const cue = ref('')
// The words are marked in their own language, whatever the page is read in.
const cueLang = computed(() => (/[\u3400-\u9fff]/.test(cue.value) ? 'zh' : 'en'))
const isFull = ref(false)
const theatre = ref(false)
const holdHeight = ref(0)
// A visitor who left the theatre while the film played is not lifted again until they pause.
let declined = false
let frame = 0
let endTimer = 0

const canFull = typeof document !== 'undefined' &&
  !!(document.fullscreenEnabled || document.webkitFullscreenEnabled || (typeof HTMLVideoElement !== 'undefined' && 'webkitEnterFullscreen' in HTMLVideoElement.prototype))

const progress = computed(() => (length.value > 0 ? Math.min(100, (now.value / length.value) * 100) : 0))
const playLabel = computed(() => {
  if (playing.value) return t('parthenon.film.player.pause')
  if (ended.value) return t('parthenon.film.player.replay')
  return t('parthenon.film.player.play')
})
const clock = (seconds) => {
  const s = Math.max(0, Math.floor(Number(seconds) || 0))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// The line moves with the picture, not in the quarter-second steps of timeupdate.
const tick = () => {
  frame = 0
  const v = videoEl.value
  if (!v) return
  now.value = v.currentTime || 0
  if (!v.paused && !v.ended) frame = requestAnimationFrame(tick)
}
const stopTick = () => {
  if (frame) cancelAnimationFrame(frame)
  frame = 0
}

const onMeta = () => {
  const v = videoEl.value
  const d = v ? Number(v.duration) : 0
  length.value = Number.isFinite(d) && d > 0 ? d : Number(film.duration) || 0
  if (v) muted.value = !!v.muted
  bindWords()
}
const onTime = () => {
  if (!frame && videoEl.value) now.value = videoEl.value.currentTime || 0
}
const onVolume = () => {
  if (videoEl.value) muted.value = !!videoEl.value.muted
}

const onFilmPlay = () => {
  if (previewing.value) stopPreview()
  playing.value = true
  started.value = true
  ended.value = false
  if (endTimer) clearTimeout(endTimer)
  endTimer = 0
  stopTick()
  frame = requestAnimationFrame(tick)
  if (enhanced.value && !theatre.value && !declined && !isFull.value) enterTheatre()
}
const onFilmPlaying = () => {
  if (!releaseFilmDuck) releaseFilmDuck = holdDuck()
}
const onFilmPause = () => {
  playing.value = false
  declined = false
  stopTick()
  if (videoEl.value) now.value = videoEl.value.currentTime || 0
  onFilmRest()
}
// The last frame holds a moment in the dark, then the lights come up.
const onFilmEnded = () => {
  playing.value = false
  ended.value = true
  declined = false
  stopTick()
  now.value = length.value
  onFilmRest()
  if (theatre.value) endTimer = setTimeout(() => { endTimer = 0; leaveTheatre() }, reducedMotion ? 400 : 1600)
}

const togglePlay = () => {
  const v = videoEl.value
  if (!v || !enhanced.value) return
  if (v.paused || v.ended) {
    const p = v.play()
    if (p && typeof p.catch === 'function') p.catch(() => {})
  } else {
    v.pause()
  }
}
const onScrub = (e) => {
  const v = videoEl.value
  const to = Number(e.target.value)
  if (!v || !Number.isFinite(to)) return
  v.currentTime = to
  now.value = to
  if (ended.value && to < length.value) ended.value = false
}
const toggleMute = () => {
  const v = videoEl.value
  if (!v) return
  v.muted = !v.muted
  muted.value = v.muted
}

// The narrator's words: the captions track is read, not drawn by the
// browser, and set under the picture in the city's type.
let boundTrack = null
const onCue = () => {
  const tr = boundTrack
  const active = tr && tr.activeCues ? Array.from(tr.activeCues) : []
  cue.value = filmWords(active.map((c) => String(c.text || '').replace(/<[^>]+>/g, '')).join(' ')).trim()
}
const bindWords = () => {
  const v = videoEl.value
  if (!v || !enhanced.value || !v.textTracks || !v.textTracks.length) return
  const tr = v.textTracks[0]
  if (boundTrack !== tr) {
    if (boundTrack) boundTrack.removeEventListener('cuechange', onCue)
    boundTrack = tr
    tr.addEventListener('cuechange', onCue)
  }
  // Hidden still fires its cues; the browser simply does not paint them.
  if (tr.mode !== 'hidden') tr.mode = 'hidden'
  onCue()
}

// ---- The theatre: the page falls dark and the frame is lifted across the screen ----
let savedOverflow = ''
const enterTheatre = async () => {
  const el = theatreEl.value
  if (!el || theatre.value) return
  const hadFocus = el.contains(document.activeElement)
  const first = el.getBoundingClientRect()
  holdHeight.value = Math.round(el.getBoundingClientRect().height)
  theatre.value = true
  try {
    savedOverflow = document.documentElement.style.overflow
    document.documentElement.style.overflow = 'hidden'
  } catch { /* nothing to lock */ }
  await nextTick()
  const moved = theatreEl.value
  if (!moved) return
  if (hadFocus) playButton.value?.focus({ preventScroll: true })
  if (reducedMotion || typeof moved.animate !== 'function') return
  const last = moved.getBoundingClientRect()
  if (!last.width) return
  moved.animate(
    [
      { transformOrigin: '0 0', transform: `translate(${first.left - last.left}px, ${first.top - last.top}px) scale(${first.width / last.width})` },
      { transformOrigin: '0 0', transform: 'none' }
    ],
    { duration: 640, easing: 'cubic-bezier(0.2, 0.7, 0.15, 1)' }
  )
}
const leaveTheatre = async () => {
  if (!theatre.value) return
  if (endTimer) clearTimeout(endTimer)
  endTimer = 0
  if (playing.value) declined = true
  const el = theatreEl.value
  const hadFocus = el && el.contains(document.activeElement)
  const first = el ? el.getBoundingClientRect() : null
  theatre.value = false
  try { document.documentElement.style.overflow = savedOverflow } catch { /* nothing to restore */ }
  await nextTick()
  const moved = theatreEl.value
  if (!moved) return
  if (hadFocus) playButton.value?.focus({ preventScroll: true })
  if (!first || reducedMotion || typeof moved.animate !== 'function') return
  const last = moved.getBoundingClientRect()
  if (!last.width) return
  moved.animate(
    [
      { transformOrigin: '0 0', transform: `translate(${first.left - last.left}px, ${first.top - last.top}px) scale(${first.width / last.width})` },
      { transformOrigin: '0 0', transform: 'none' }
    ],
    { duration: 480, easing: 'cubic-bezier(0.3, 0.6, 0.2, 1)' }
  )
}

const fullElement = () => document.fullscreenElement || document.webkitFullscreenElement || null
const onFullChange = () => {
  isFull.value = !!fullElement() && fullElement() === theatreEl.value
}
const toggleFull = async () => {
  const el = theatreEl.value
  const v = videoEl.value
  if (!el) return
  try {
    if (fullElement()) {
      await (document.exitFullscreen ? document.exitFullscreen() : document.webkitExitFullscreen?.())
    } else if (el.requestFullscreen) {
      await el.requestFullscreen()
    } else if (el.webkitRequestFullscreen) {
      el.webkitRequestFullscreen()
    } else if (v && v.webkitEnterFullscreen) {
      // A phone that only lets the video itself fill the screen, in its own chrome.
      v.webkitEnterFullscreen()
    }
  } catch { /* the browser said no */ }
}

// Keys inside the player: Space or K plays and pauses, arrows step five
// seconds, M silences, C shows the words, F fills the screen, Esc leaves.
// Tab stays inside the theatre while it is up.
const onPlayerKey = (e) => {
  if (!enhanced.value) return
  const onRange = e.target && e.target.classList && e.target.classList.contains('cf-scrub')
  const onButton = e.target && e.target.tagName === 'BUTTON'
  const key = e.key
  if (key === 'Escape' && theatre.value && !isFull.value) {
    e.preventDefault()
    leaveTheatre()
    return
  }
  if (key === 'Tab' && theatre.value) {
    const items = Array.from(theatreEl.value?.querySelectorAll('button, input') || []).filter((el) => !el.disabled)
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
    return
  }
  if (e.altKey || e.ctrlKey || e.metaKey) return
  if ((key === ' ' && !onButton && !onRange) || key === 'k' || key === 'K') {
    e.preventDefault()
    togglePlay()
  } else if (!onRange && (key === 'ArrowLeft' || key === 'ArrowRight')) {
    const v = videoEl.value
    if (!v) return
    e.preventDefault()
    v.currentTime = Math.max(0, Math.min(length.value || v.duration || 0, v.currentTime + (key === 'ArrowLeft' ? -5 : 5)))
    now.value = v.currentTime
  } else if (key === 'm' || key === 'M') {
    toggleMute()
  } else if ((key === 'c' || key === 'C') && captionsSrc.value) {
    wordsOn.value = !wordsOn.value
  } else if ((key === 'f' || key === 'F') && canFull) {
    toggleFull()
  }
}

// Esc anywhere leaves the theatre (focus may rest on the dark around the frame).
const onDocKey = (e) => {
  if (e.key === 'Escape' && theatre.value && !isFull.value) leaveTheatre()
}

onMounted(() => {
  enhanced.value = true
  document.addEventListener('fullscreenchange', onFullChange)
  document.addEventListener('webkitfullscreenchange', onFullChange)
  document.addEventListener('keydown', onDocKey)
})

// A new film (or none): the player starts from its first frame.
watch(videoSrc, () => {
  stopTick()
  playing.value = false
  started.value = false
  ended.value = false
  now.value = 0
  cue.value = ''
  if (boundTrack) boundTrack.removeEventListener('cuechange', onCue)
  boundTrack = null
  if (theatre.value) leaveTheatre()
})

watch(showSetup, (shown) => {
  if (!shown) stopPreview()
})
watch(view, (next) => {
  if (next !== 'completed') {
    onFilmRest()
    if (theatre.value) {
      theatre.value = false
      try { document.documentElement.style.overflow = savedOverflow } catch { /* nothing to restore */ }
    }
  }
})

onBeforeUnmount(() => {
  unmounted = true
  generation += 1
  clearPoll()
  stopPreview()
  onFilmRest()
  stopTick()
  if (endTimer) clearTimeout(endTimer)
  if (boundTrack) boundTrack.removeEventListener('cuechange', onCue)
  if (theatre.value) {
    try { document.documentElement.style.overflow = savedOverflow } catch { /* nothing to restore */ }
  }
  document.removeEventListener('fullscreenchange', onFullChange)
  document.removeEventListener('webkitfullscreenchange', onFullChange)
  document.removeEventListener('keydown', onDocKey)
})

// Focus

const viewLead = () => {
  switch (view.value) {
    case 'running': return stageEl.value
    case 'completed': return filmTitleEl.value
    case 'failed': return failedEl.value
    case 'unknown': return recheckButton.value
    case 'setup': return voicesEl.value?.querySelector('input:checked:not(:disabled)')
    default: return null
  }
}

const focusLead = () => {
  const lead = viewLead() || headingEl.value
  lead?.focus()
}

// For a jump from elsewhere on the page: scroll the panel in and land focus on
// whatever acts next (Film it, the player, Try again).
const reveal = () => {
  const root = rootEl.value
  if (!root) return
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  root.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' })
  const lead = viewLead() || headingEl.value
  lead?.focus({ preventScroll: true })
}

defineExpose({ reveal })

// A view change can remove the focused element (the stage line when filming ends, Try again
// once the status is read). Move focus to the new view instead of dropping it on <body>.
watch(view, async () => {
  const root = rootEl.value
  if (!root || !root.contains(document.activeElement)) return
  await nextTick()
  if (unmounted || root.contains(document.activeElement)) return
  focusLead()
})

// Actions

const describeError = (err) => {
  if (isOffline(err)) return t('parthenon.film.offline')
  return err?.message || t('parthenon.film.startFailed')
}

const checkAgain = () => {
  if (rechecking.value) return
  rechecking.value = true
  clearPoll()
  refresh()
}

const startFilm = async () => {
  if (!canStart.value) return
  const reportId = props.reportId
  const gen = generation
  const requestLocale = i18n.global.locale.value
  starting.value = true
  startError.value = ''
  try {
    await startChronicleFilm(reportId, { voice: voice.value })
    if (gen !== generation || unmounted) return
    finishedHere.value = false
    appliedSeq = ++requestSeq // a status read already in flight is older than this
    applyFilm({ status: 'running', stage: 'queued', progress: 0, voice: voice.value })
    startedLocale.value = requestLocale
    await nextTick()
    stageEl.value?.focus()
    refresh()
  } catch (err) {
    if (gen !== generation || unmounted) return
    if (err?.response?.status === 409) {
      // Already filming (perhaps from another tab): show that run.
      await refresh()
      if (gen !== generation || film.status === 'running') return
    }
    startError.value = describeError(err)
  } finally {
    if (gen === generation) starting.value = false
  }
}

const composeAgain = async () => {
  startError.value = ''
  // Filming again starts from the narrator the current film was read by.
  if (FILM_VOICES.includes(film.voice)) voice.value = film.voice
  if (theatre.value) await leaveTheatre()
  composing.value = true
  await nextTick()
  voicesEl.value?.querySelector('input:checked')?.focus()
}

const keepFilm = async () => {
  composing.value = false
  startError.value = ''
  await nextTick()
  againButton.value?.focus()
}

const onDownload = async (event) => {
  const href = videoSrc.value
  if (!href) return
  let sameOrigin = true
  try {
    sameOrigin = new URL(href, window.location.href).origin === window.location.origin
  } catch {
    sameOrigin = true
  }
  // Same origin: the download attribute works on its own.
  if (sameOrigin) return

  // Browsers ignore download on cross-origin links, so fetch the file first.
  event.preventDefault()
  if (downloading.value) return
  downloading.value = true
  try {
    const response = await fetch(href, { mode: 'cors', credentials: 'omit' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blobUrl = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = fileName.value
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(blobUrl), 10000)
  } catch (err) {
    console.warn('Film download fell back to opening the file:', err)
    window.open(href, '_blank', 'noopener')
  } finally {
    downloading.value = false
  }
}
</script>

<style scoped>
.chronicle-film {
  /* Control boundaries need 3:1 against the page (WCAG 1.4.11); --p-line is for dividers. */
  --cf-control-border: color-mix(in srgb, var(--p-ink) 40%, transparent);

  container-type: inline-size;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  margin-top: 56px;
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
}

.visually-hidden {
  position: absolute !important;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}

.chronicle-film video:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 3px;
}

.cf-rule {
  margin-bottom: 28px;
}

/* Header */
.cf-eyebrow {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-gold);
}

/* Chinese in the inscriptions: the serif, upright, lightly tracked */
.cf-eyebrow:lang(zh),
.cf-label:lang(zh),
.cf-working-label:lang(zh),
.cf-shot-meta:lang(zh) {
  font-family: var(--p-font-serif);
  font-size: 13px;
  letter-spacing: 0.04em;
  text-transform: none;
}

.cf-title {
  margin-top: 10px;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.1;
  letter-spacing: -0.01em;
  color: var(--p-ink);
}

.cf-lede {
  max-width: 60ch;
  margin-top: 12px;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-3);
}

.cf-quiet-line {
  margin-top: 20px;
  font-family: var(--p-font-serif);
  font-size: var(--t-lg);
  font-style: italic;
  line-height: 1.4;
  color: var(--p-ink-3);
}

.cf-unknown .cf-actions {
  margin-top: 4px;
}

/* Narrator voice: a segmented control of radios */
.cf-voices {
  min-width: 0;
  margin-top: 24px;
  padding: 0;
  border: 0;
}

.cf-label {
  padding: 0;
  margin-bottom: 8px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.cf-segmented {
  display: flex;
  max-width: 420px;
  border: 1px solid var(--cf-control-border);
}

.cf-seg-cell {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  min-width: 0;
}

.cf-seg-cell + .cf-seg-cell {
  border-left: 1px solid var(--cf-control-border);
}

.cf-seg {
  position: relative;
  display: block;
  cursor: pointer;
}

.cf-seg-face {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-height: 52px;
  padding: 8px 6px;
  background: var(--p-surface);
  text-align: center;
  transition: background-color 0.15s ease;
}

.cf-seg-name {
  font-family: var(--p-font-display);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.1;
  color: var(--p-ink);
}

.cf-seg-note {
  font-size: 12px;
  line-height: 1.3;
  color: var(--p-ink-4);
}

.cf-seg:hover .cf-seg-face {
  background: var(--p-surface-2);
}

.cf-seg input:checked + .cf-seg-face {
  background: var(--p-ink);
}

.cf-seg input:checked + .cf-seg-face .cf-seg-name,
.cf-seg input:checked + .cf-seg-face .cf-seg-note {
  color: var(--p-surface);
}

.cf-seg input:focus-visible + .cf-seg-face {
  position: relative;
  z-index: 1;
  outline: 2px solid var(--p-gold);
  outline-offset: 3px;
}

.cf-voices.is-disabled .cf-seg {
  cursor: not-allowed;
}

.cf-voices.is-disabled .cf-seg-face {
  background: var(--p-surface-2);
}

.cf-voices.is-disabled .cf-seg-name {
  color: var(--p-ink-4);
}

.cf-voices.is-disabled .cf-seg input:checked + .cf-seg-face {
  background: var(--p-ink-3);
}

/* Hear: a small voice under each narrator, outside its radio */
.cf-hear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  min-height: 40px;
  padding: 0 6px;
  border: 0;
  border-top: 1px solid var(--p-line);
  background: transparent;
  color: var(--p-ink-3);
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  cursor: pointer;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.cf-hear:hover {
  color: var(--p-ink);
  background: var(--p-surface-2);
}

.cf-hear:focus-visible {
  position: relative;
  z-index: 1;
  outline: 2px solid var(--p-gold);
  outline-offset: -2px;
}

.cf-hear[aria-pressed='true'] {
  background: var(--p-terracotta-tint);
  color: var(--p-gold);
}

.cf-hear-waves {
  opacity: 0.45;
}

.cf-hear[aria-pressed='true'] .cf-hear-waves {
  opacity: 1;
  animation: cf-waves 1.1s ease-in-out infinite;
}

@keyframes cf-waves {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

/* The line the narrators read, written out while it is heard */
.cf-sample {
  min-height: 1.4em;
  max-width: 420px;
  margin-top: 10px;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  font-style: italic;
  line-height: 1.4;
  color: var(--p-ink-3);
}

/* Chinese has no italic and the inscription face has no Chinese: upright, in the serif. */
.cf-sample:lang(zh) {
  font-style: normal;
}

.cf-hear:lang(zh) {
  font-family: var(--p-font-serif);
  font-size: var(--t-sm, 13px);
  letter-spacing: 0.08em;
}

@media (prefers-reduced-motion: reduce) {
  .cf-hear[aria-pressed='true'] .cf-hear-waves {
    animation: none;
  }
}

/* Actions */
.cf-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 20px;
  margin-top: 20px;
}

/* The one button, as a link: the download keeps its href */
a.p-button {
  text-decoration: none;
}

.cf-hint {
  max-width: 60ch;
  margin-top: 10px;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-4);
}

.cf-error {
  margin-top: 12px;
  padding: 10px 12px;
  border-left: 2px solid var(--p-error);
  background: var(--p-error-tint);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-error);
  overflow-wrap: anywhere;
}

/* Filming */
.cf-progress {
  margin-top: 24px;
}

.cf-stage-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px 12px;
}

.cf-stage {
  min-width: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-lg);
  font-style: italic;
  font-weight: 500;
  line-height: 1.2;
  color: var(--p-ink);
}

/* Focus lands on these when the view changes under it */
.cf-title:focus:not(:focus-visible),
.cf-stage:focus:not(:focus-visible),
.cf-film-title:focus:not(:focus-visible),
.cf-failed:focus:not(:focus-visible) {
  outline: none;
}

.cf-title:focus-visible,
.cf-stage:focus-visible,
.cf-film-title:focus-visible,
.cf-failed:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 3px;
}

.cf-percent {
  font-family: var(--p-font-mono);
  font-size: var(--t-xs);
  letter-spacing: var(--track-mono);
  font-variant-numeric: tabular-nums;
  color: var(--p-ink-3);
}

.cf-bar {
  position: relative;
  height: 3px;
  margin-top: 10px;
  overflow: hidden;
  background: var(--p-line);
}

.cf-bar-fill {
  position: absolute;
  inset: 0;
  background: var(--p-gold);
  transform-origin: left center;
  transition: transform 0.6s ease;
}

.cf-detail {
  margin-top: 8px;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-4);
  overflow-wrap: anywhere;
}

.cf-detail--warn {
  color: var(--p-ochre-deep);
}

.cf-working {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
  margin-top: 20px;
}

.cf-working-label {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-4);
}

.cf-working-title {
  min-width: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-style: italic;
  line-height: 1.25;
  color: var(--p-ink);
  overflow-wrap: anywhere;
}

.cf-shots {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 168px), 1fr));
  gap: 20px 14px;
  margin-top: 20px;
  padding: 0;
  list-style: none;
}

.cf-shot {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.cf-shot-frame {
  position: relative;
  display: grid;
  place-items: center;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border: 1px solid var(--p-line);
  background: var(--p-surface-3);
}

.cf-shot-frame img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  animation: cf-develop 0.9s ease both;
}

.cf-shot-numeral {
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  color: var(--p-ink-4);
}

/* Shots still being made breathe; a thin rule marks them */
.cf-shot.is-painting .cf-shot-frame,
.cf-shot.is-animating .cf-shot-frame {
  animation: cf-breathe 2.4s ease-in-out infinite;
}

.cf-shot.is-painting .cf-shot-frame::after,
.cf-shot.is-animating .cf-shot-frame::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: var(--p-gold);
  animation: cf-pulse 1.6s ease-in-out infinite;
}

.cf-shot-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 2px 8px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-4);
}

.cf-shot.is-done .cf-shot-status {
  color: var(--p-olive-deep);
}

.cf-shot.is-painting .cf-shot-status,
.cf-shot.is-animating .cf-shot-status {
  color: var(--p-ochre-deep);
}

.cf-shot.is-failed .cf-shot-status {
  color: var(--p-error);
}

.cf-shot-line {
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  font-style: italic;
  line-height: 1.35;
  color: var(--p-ink-2);
  overflow-wrap: anywhere;
}

@keyframes cf-develop {
  from {
    opacity: 0;
    filter: sepia(0.7) blur(2px);
  }
  to {
    opacity: 1;
    filter: none;
  }
}

@keyframes cf-breathe {
  0%,
  100% {
    background-color: var(--p-surface-3);
  }
  50% {
    background-color: var(--p-surface-2);
  }
}

@keyframes cf-pulse {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

/* The finished film */
.cf-film {
  margin: 24px 0 0;
}

/* ---- The player: a night box, the same inline on parchment and lifted in the dark ---- */
.cf-stage {
  --cf-gold: #f0b660;
  --cf-ink: #f2ede4;
  --cf-ink-2: #d8d2c7;
  --cf-ink-3: #a7a197;
  --cf-night: #07090c;
}

.cf-theatre {
  position: relative;
  font-style: normal;
  background: var(--cf-night);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.2), 0 24px 60px -30px rgba(10, 8, 4, 0.55);
  color: var(--cf-ink);
}

.cf-screen {
  position: relative;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: var(--cf-night);
  cursor: pointer;
}

.cf-video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: var(--cf-night);
}

/* Before the first frame: the poster, and one gold coin to begin */
.cf-big-play {
  position: absolute;
  left: 50%;
  top: 50%;
  display: grid;
  place-items: center;
  width: 84px;
  height: 84px;
  padding-left: 4px;
  border-radius: 50%;
  border: 1.5px solid var(--cf-gold);
  background: radial-gradient(circle, rgba(7, 9, 12, 0.72), rgba(7, 9, 12, 0.5));
  box-shadow: 0 0 0 8px rgba(240, 182, 96, 0.12), 0 12px 40px rgba(0, 0, 0, 0.5);
  color: var(--cf-gold);
  transform: translate(-50%, -50%);
  pointer-events: none;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.cf-screen:hover .cf-big-play {
  transform: translate(-50%, -50%) scale(1.06);
  box-shadow: 0 0 0 12px rgba(240, 182, 96, 0.16), 0 12px 40px rgba(0, 0, 0, 0.5);
}

/* The narrator's words: the reading serif at the foot of the picture */
.cf-words {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  margin: 0;
  padding: 44px 8% 16px;
  background: linear-gradient(to top, rgba(7, 9, 12, 0.82), rgba(7, 9, 12, 0.5) 55%, rgba(7, 9, 12, 0));
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: clamp(0.9375rem, 2.1cqi, 1.3125rem);
  line-height: 1.4;
  text-align: center;
  text-wrap: balance;
  color: var(--cf-ink);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.9), 0 0 14px rgba(0, 0, 0, 0.6);
  pointer-events: none;
}

.cf-words:lang(zh) { font-style: normal; letter-spacing: 0.04em; }

/* The controls: a gold coin, the time, a thin gold line, and the few tools */
.cf-controls {
  display: flex;
  align-items: center;
  gap: 4px 12px;
  min-height: 60px;
  padding: 8px 12px 8px 10px;
  border-top: 1px solid rgba(240, 182, 96, 0.16);
  background: linear-gradient(180deg, #0c0f14, var(--cf-night));
}

.cf-coin {
  flex: 0 0 auto;
  display: inline-grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid var(--cf-gold);
  border-radius: 50%;
  background: rgba(240, 182, 96, 0.1);
  color: var(--cf-gold);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;
}

.cf-coin:hover {
  background: var(--cf-gold);
  color: #1f1a16;
}

.playing .cf-coin { box-shadow: 0 0 0 4px rgba(240, 182, 96, 0.1); }

.cf-time {
  flex: 0 0 auto;
  min-width: 3.4em;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  font-variant-numeric: tabular-nums lining-nums;
  color: var(--cf-ink-2);
}

.cf-time--end { color: var(--cf-ink-3); text-align: right; }

/* The line: 1px of gold across, the part already seen drawn in full gold;
   the hit area is 44px tall, the thumb a small sun. */
.cf-scrub {
  flex: 1 1 auto;
  min-width: 60px;
  height: 44px;
  margin: 0;
  background: transparent;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
}

.cf-scrub:disabled { cursor: default; opacity: 0.5; }

.cf-scrub::-webkit-slider-runnable-track {
  height: 2px;
  background: linear-gradient(90deg, var(--cf-gold) 0 var(--done, 0%), rgba(240, 182, 96, 0.26) var(--done, 0%) 100%);
}

.cf-scrub::-moz-range-track {
  height: 2px;
  background: rgba(240, 182, 96, 0.26);
}

.cf-scrub::-moz-range-progress {
  height: 2px;
  background: var(--cf-gold);
}

.cf-scrub::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  margin-top: -6px;
  border: 0;
  border-radius: 50%;
  background: var(--cf-gold);
  box-shadow: 0 0 0 4px rgba(240, 182, 96, 0.18), 0 0 14px rgba(240, 182, 96, 0.55);
}

.cf-scrub::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border: 0;
  border-radius: 50%;
  background: var(--cf-gold);
  box-shadow: 0 0 0 4px rgba(240, 182, 96, 0.18), 0 0 14px rgba(240, 182, 96, 0.55);
}

.cf-tools {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.cf-tool {
  display: inline-grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--cf-ink-3);
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}

.cf-tool:hover { color: var(--cf-ink); background: rgba(242, 237, 228, 0.06); }
.cf-tool[aria-pressed='true'] { color: var(--cf-gold); }
.cf-leave { margin-left: 4px; border: 1px solid rgba(242, 237, 228, 0.22); }

.cf-coin:focus-visible,
.cf-tool:focus-visible,
.cf-scrub:focus-visible {
  outline: 2px solid var(--cf-gold);
  outline-offset: 2px;
}

/* ---- The theatre: the page falls to night, the frame is lifted across it ---- */
.cf-stage.lifted {
  position: fixed;
  inset: 0;
  z-index: 1400;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: radial-gradient(ellipse 70% 60% at 50% 45%, rgba(18, 14, 9, 0.95), rgba(3, 4, 6, 0.985));
  animation: cf-lights-down 0.7s ease both;
}

.cf-stage.lifted .cf-theatre {
  width: min(100%, calc((100vh - 170px) * 16 / 9));
  box-shadow: 0 0 0 1px rgba(240, 182, 96, 0.14), 0 40px 120px rgba(0, 0, 0, 0.8);
}

/* In the dark the words are set a size up */
.cf-stage.lifted .cf-words {
  padding-bottom: 22px;
  font-size: clamp(1rem, 1.5vw, 1.5rem);
}

@keyframes cf-lights-down {
  from { background-color: transparent; opacity: 0; }
  to { opacity: 1; }
}

.cf-stage.still,
.cf-stage.still .cf-big-play { animation: none; transition: none; }

/* Filling the screen: the picture as large as it goes, the bar at its foot */
.cf-theatre.fullscreen {
  display: flex;
  flex-direction: column;
  justify-content: center;
  width: 100vw;
  height: 100vh;
  background: #000;
}

.cf-theatre.fullscreen .cf-screen {
  flex: 1 1 auto;
  aspect-ratio: auto;
  min-height: 0;
}

.cf-caption {
  margin-top: 16px;
}

.cf-film-title {
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.15;
  color: var(--p-ink);
  overflow-wrap: anywhere;
}

.cf-logline {
  margin-top: 6px;
  font-family: var(--p-font-serif);
  font-size: var(--t-lg);
  font-style: italic;
  line-height: 1.4;
  color: var(--p-ink-3);
}

.cf-meta {
  margin-top: 8px;
  font-size: var(--t-xs);
  letter-spacing: var(--track-mono);
  color: var(--p-ink-4);
}

/* Failed */
.cf-failed {
  margin-top: 24px;
  padding: 14px 16px;
  border-left: 2px solid var(--p-error);
  background: var(--p-error-tint);
}

.cf-failed-title {
  font-weight: 600;
  color: var(--p-error);
}

.cf-failed-detail {
  margin-top: 4px;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-2);
  overflow-wrap: anywhere;
}

.cf-setup .cf-failed + .cf-voices {
  margin-top: 20px;
}

/* A narrow column: the gold line takes a row of its own across the whole
   width, the coin, the time and the tools sit under it. */
@container (max-width: 460px) {
  .cf-controls { flex-wrap: wrap; gap: 0 6px; padding: 0 8px 6px; }
  .cf-scrub { order: -1; flex: 1 1 100%; height: 40px; }
  .cf-time--end { margin-right: auto; text-align: left; }
  .cf-time--end::before { content: '/\00a0'; }
}

@media (max-width: 520px) {
  .cf-stage.lifted { padding: 12px; }
  .cf-stage.lifted .cf-controls { flex-wrap: wrap; gap: 0 6px; padding: 0 8px 6px; }
  .cf-stage.lifted .cf-scrub { order: -1; flex: 1 1 100%; height: 40px; }
  .cf-stage.lifted .cf-time--end { margin-right: auto; text-align: left; }
  .cf-stage.lifted .cf-time--end::before { content: '/\00a0'; }
}

@container (max-width: 420px) {
  .cf-title {
    font-size: var(--t-xl);
  }

  .cf-segmented {
    max-width: none;
  }

  /* The sample line may take two lines here; its room is kept so nothing jumps. */
  .cf-sample {
    min-height: 2.8em;
  }

  .cf-actions .p-button:not(.ghost) {
    flex: 1 1 100%;
  }

  .cf-shots {
    grid-template-columns: 1fr;
  }
}
</style>
