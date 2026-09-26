<template>
  <section ref="rootEl" class="chronicle-film" :class="`is-${view}`" :aria-labelledby="ids.title">
    <div class="p-meander ink cf-rule" aria-hidden="true"></div>

    <header class="cf-head">
      <p class="cf-eyebrow">{{ $t('parthenon.film.eyebrow') }}</p>
      <h2 :id="ids.title" ref="headingEl" class="cf-title" tabindex="-1">{{ $t('parthenon.film.title') }}</h2>
      <p class="cf-lede">{{ $t('parthenon.film.lede') }}</p>
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

      <p v-if="film.title" class="cf-working">
        <span class="cf-working-label">{{ $t('parthenon.film.workingTitle') }}</span>
        <span class="cf-working-title">{{ film.title }}</span>
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

    <!-- The finished film -->
    <template v-else-if="view === 'completed'">
      <figure class="cf-film">
        <div class="cf-screen">
          <video
            :key="videoSrc"
            class="cf-video"
            controls
            playsinline
            preload="metadata"
            crossorigin="anonymous"
            :poster="posterSrc || undefined"
            :aria-label="$t('parthenon.film.videoLabel', { title: filmTitle })"
          >
            <source :src="videoSrc" type="video/mp4" />
            <track
              v-if="captionsSrc"
              kind="captions"
              :srclang="captionsLang || undefined"
              :label="captionsLabel || undefined"
              :src="captionsSrc"
              default
            />
            {{ $t('parthenon.film.noVideo') }}
          </video>
        </div>
        <figcaption class="cf-caption">
          <h3 ref="filmTitleEl" class="cf-film-title" tabindex="-1">{{ filmTitle }}</h3>
          <p v-if="film.logline" class="cf-logline">{{ film.logline }}</p>
          <p v-if="metaLine" class="cf-meta">{{ metaLine }}</p>
        </figcaption>
      </figure>

      <div v-if="!composing" class="cf-actions">
        <a class="p-button" :href="videoSrc" :download="fileName" @click="onDownload">
          {{ downloading ? $t('parthenon.film.downloading') : $t('parthenon.film.download') }}
        </a>
        <button ref="againButton" type="button" class="p-button ghost" @click="composeAgain">
          {{ $t('parthenon.film.filmAgain') }}
        </button>
      </div>
    </template>

    <!-- Choose a narrator and roll -->
    <div v-if="showSetup" class="cf-setup">
      <div v-if="view === 'failed'" ref="failedEl" class="cf-failed" role="alert" tabindex="-1">
        <p class="cf-failed-title">{{ $t('parthenon.film.failedTitle') }}</p>
        <p class="cf-failed-detail">{{ film.error || $t('parthenon.film.failedFallback') }}</p>
      </div>

      <fieldset ref="voicesEl" class="cf-voices" :disabled="!canStart">
        <legend class="cf-label">{{ $t('parthenon.film.voiceLabel') }}</legend>
        <div class="cf-segmented">
          <label v-for="v in FILM_VOICES" :key="v" class="cf-seg">
            <input v-model="voice" type="radio" class="visually-hidden" :name="ids.voice" :value="v" />
            <span class="cf-seg-face">
              <span class="cf-seg-name">{{ $t(`parthenon.film.voices.${v}`) }}</span>
              <span class="cf-seg-note">{{ $t(`parthenon.film.voiceNotes.${v}`) }}</span>
            </span>
          </label>
        </div>
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
import { computed, nextTick, onBeforeUnmount, reactive, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import i18n, { availableLocales } from '../i18n'
import { FILM_VOICES, filmAssetUrl, getChronicleFilm, startChronicleFilm } from '../api/parthenon'

const props = defineProps({
  reportId: String,
  ready: Boolean
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
  language: null,
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

const showSetup = computed(() =>
  view.value === 'setup' || view.value === 'failed' || (view.value === 'completed' && composing.value)
)

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
  return film.message || t('parthenon.film.stageFallback')
})

// Under a known stage the backend's message only adds something when it counts
// ("Filming the shots (2 of 6 ready)"); otherwise it restates the stage.
const stageDetail = computed(() =>
  stageKey.value && film.message && /\d/.test(film.message) ? film.message : ''
)

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

// The backend narrates and captions in the UI locale of the request that started the film.
// Prefer the manifest's record, then the locale this panel started it in; a film found on
// load was most likely started in the UI language still in use.
const captionsLang = computed(() =>
  [film.language, startedLocale.value, i18n.global.locale.value]
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

const filmTitle = computed(() => film.title || t('parthenon.film.untitled'))

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
        narration: typeof shot.narration === 'string' ? shot.narration : '',
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

onBeforeUnmount(() => {
  unmounted = true
  generation += 1
  clearPoll()
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

.cf-seg {
  position: relative;
  flex: 1 1 0;
  min-width: 0;
  cursor: pointer;
}

.cf-seg + .cf-seg {
  border-left: 1px solid var(--cf-control-border);
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

.cf-voices:disabled .cf-seg {
  cursor: not-allowed;
}

.cf-voices:disabled .cf-seg-face {
  background: var(--p-surface-2);
}

.cf-voices:disabled .cf-seg-name {
  color: var(--p-ink-4);
}

.cf-voices:disabled .cf-seg input:checked + .cf-seg-face {
  background: var(--p-ink-3);
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

.cf-screen {
  aspect-ratio: 16 / 9;
  border: 1px solid var(--p-ink);
  background: var(--p-ink);
}

.cf-video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: var(--p-ink);
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

@container (max-width: 420px) {
  .cf-title {
    font-size: var(--t-xl);
  }

  .cf-segmented {
    max-width: none;
  }

  .cf-actions .p-button:not(.ghost) {
    flex: 1 1 100%;
  }

  .cf-shots {
    grid-template-columns: 1fr;
  }
}
</style>
