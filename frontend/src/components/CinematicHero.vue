<template>
  <!-- The descent: a tall track with one pinned screen. Scrolling climbs the
       Propylaea (the era's climb scrubbed, or the start plate pushing in and
       dipping through night to the end frame), then the Way is drawn across the
       temple. Under reduced motion nothing is pinned: the hero is a still first
       screen and the end frame with the Way is a section after it. -->
  <div
    ref="track"
    class="descent"
    :class="[
      `era-${era}`,
      `mode-${phase}`,
      `layout-${wayMode}`,
      {
        still,
        portrait,
        drifting: stillDrift,
        descended,
        'cam-end': camEnd,
        cut,
        lapsing: lapse.on,
        veiled: lapse.veil,
        'scrub-on': scrubOn,
        'motion-off': motionPaused
      }
    ]"
  >
    <div class="stage">
      <section ref="root" class="cine" aria-labelledby="hero-title">
        <div class="media" aria-hidden="true">
          <div class="push">
            <div
              v-for="(scene, key) in scenes"
              :key="key"
              class="layer"
              :class="{ active: shown === key, rolling: playing[key], rested: rested[key] }"
            >
              <!-- Upright screens (phones, and tablets held upright) get the 3:4 plate
                   centred on the temple. Wider, cover crops the 2560x1086 still, so on
                   a taller screen it is drawn 236vh wide. The other era waits until it
                   is asked for, or the page is idle. -->
              <picture v-if="armed[key]">
                <source :media="PORTRAIT_QUERY" :srcset="scene.portrait1280" />
                <img
                  :src="scene.still2560"
                  :srcset="`${scene.still1280} 1280w, ${scene.still2560} 2560w`"
                  sizes="(max-aspect-ratio: 2560/1086) 236vh, 100vw"
                  alt=""
                  :fetchpriority="key === initialEra ? 'high' : 'low'"
                  decoding="async"
                />
              </picture>
              <video
                v-if="layerVideo && armed[key]"
                :ref="(el) => (videos[key] = el)"
                muted
                playsinline
                preload="metadata"
                :src="videoSrc(scene)"
                @seeked="onLayerSeeked(key)"
                @playing="onFrame(key)"
                @ended="onEnded(key)"
              ></video>
            </div>
          </div>

          <!-- The climb cut for seeking, where the playing climb cannot be scrubbed
               itself: the upright climb on a phone, the 1280 cut on a small screen.
               On a wide screen the climb that played is the one the scroll drives. -->
          <video
            v-if="scrubAllowed && scrubArmed && !unified"
            ref="scrubEl"
            class="scrub"
            :class="{ on: scrubOn }"
            muted
            playsinline
            preload="auto"
            :src="scrubSrc"
            @loadeddata="onScrubLoaded"
            @seeked="onScrubSeeked"
            @emptied="scrubReady = false"
          ></video>

          <!-- Twenty-four centuries on one locked camera, between the two start frames. -->
          <video
            v-if="lapseAllowed && lapseArmed"
            ref="lapseEl"
            class="lapse"
            :class="{ on: lapse.on }"
            muted
            playsinline
            :preload="lapsePreload"
            :src="lapseSrc"
            @ended="onLapseEnded"
          ></video>

          <!-- Night, for a moment: the camera leaves mid-climb for the foot of the steps. -->
          <div class="veil"></div>
        </div>

        <SwarmCanvas
          v-if="motionAllowed"
          class="swarm"
          :era="era"
          :intensity="speaker ? 1 : 0"
          :region="sky"
          :avoid="avoid"
          :paused="swarmPaused || motionPaused"
        />

        <!-- The grade belongs to the plate: night pools at the left and the foot of
             the frame where the words sit, and the temple keeps its light. -->
        <div class="shade" aria-hidden="true"></div>

        <p ref="lapseCap" class="lapse-caption" :class="{ on: lapse.on }" aria-hidden="true">
          <span class="lapse-title">{{ label('parthenon.hero.lapseCaption', 'Twenty-four centuries') }}</span>
          <span class="lapse-year">{{ lapseYearText }}</span>
          <span class="lapse-beats">
            <span v-for="b in lapseBeats" :key="b.key" class="lapse-beat" :class="{ on: b.on }">{{ b.text }}</span>
          </span>
        </p>

        <div ref="copy" class="copy" @focusin="onCopyFocus">
          <h1 id="hero-title" class="title">
            <span class="line">{{ heroLine1 }}<em>{{ $t('parthenon.heroLine2') }}</em></span>
            <span class="line">{{ $t('parthenon.heroLine3') }}</span>
          </h1>
          <p class="hero-sr">{{ sceneLabel }}</p>
          <p class="lede">{{ $t('parthenon.heroLede') }}</p>
          <div class="actions">
            <button type="button" class="p-button cta" @click="$emit('begin')">
              {{ $t('parthenon.heroCta') }}
              <span class="cta-arrow" aria-hidden="true">→</span>
            </button>

            <div
              class="era"
              role="group"
              :aria-label="$t('parthenon.eraLabel')"
              @pointerenter="warmLapse"
              @focusin="warmLapse"
            >
              <span class="era-caption">{{ label('parthenon.hero.eraCaption', 'The same steps, 2,425 years apart') }}</span>
              <span class="era-options">
                <button
                  v-for="(scene, key) in scenes"
                  :key="key"
                  type="button"
                  class="era-option"
                  :class="{ active: era === key }"
                  :aria-pressed="era === key"
                  @click="$emit('update:era', key)"
                >{{ eraYear(key) }}</button>
              </span>
            </div>

            <button
              v-if="motionAllowed"
              type="button"
              class="p-button ghost small motion"
              :aria-pressed="motionPaused"
              :aria-label="label('parthenon.pauseMotion', 'Pause motion')"
              @click="toggleMotion"
            >
              <svg v-if="!motionPaused" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <rect x="3" y="2.5" width="3.4" height="11" fill="currentColor" />
                <rect x="9.6" y="2.5" width="3.4" height="11" fill="currentColor" />
              </svg>
              <svg v-else viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
              </svg>
              <span class="motion-text">{{ label('parthenon.pauseMotion', 'Pause motion') }}</span>
            </button>
          </div>
        </div>

        <span class="climb-cue" aria-hidden="true">
          <span class="climb-inner">
            {{ label('parthenon.hero.climbCue', 'Climb the steps') }}
            <span class="climb-line"></span>
          </span>
        </span>

        <!-- Always in the DOM so the first speaker is announced too. -->
        <p class="floor" aria-live="polite" aria-atomic="true">
          <template v-if="speaker">
            <span class="floor-letter" aria-hidden="true">{{ speaker.letter }}</span>
            {{ $t('parthenon.hasTheFloor', { name: speaker.name }) }}
          </template>
        </p>
      </section>

      <!-- The top of the climb: inside the Propylaea, the temple ahead, and the
           five stations drawn as the Panathenaic Way up the steps. -->
      <section
        :id="still ? 'how' : undefined"
        ref="arrival"
        class="arrival"
        aria-labelledby="way-title"
      >
        <div class="end-plate" aria-hidden="true">
          <div
            v-for="(scene, key) in scenes"
            :key="key"
            class="end-layer"
            :class="{ active: shown === key }"
          >
            <picture v-if="endArmed && endFor[key]">
              <source :media="PORTRAIT_QUERY" :srcset="scene.endPortrait" />
              <img :src="scene.end2560" alt="" :loading="still ? 'lazy' : 'eager'" decoding="async" />
            </picture>
          </div>
        </div>
        <div class="way-shade" aria-hidden="true"></div>

        <div class="way">
          <header class="way-head">
            <p class="p-eyebrow">{{ $t('parthenon.how.eyebrow') }}</p>
            <h2 id="way-title">{{ $t('parthenon.how.title') }}</h2>
            <p class="way-lede">{{ $t('parthenon.how.lede') }}</p>
          </header>

          <svg
            v-if="wayMode === 'path' && pathD"
            class="way-path"
            :viewBox="`0 0 ${box.w} ${box.h}`"
            aria-hidden="true"
          >
            <path class="way-glow" :d="pathD" pathLength="1" />
            <path class="way-line" :d="pathD" pathLength="1" />
          </svg>

          <ol class="stations" role="list">
            <li
              v-for="(s, i) in stations"
              :key="i"
              class="station"
              :class="`side-${s.side}`"
              :style="stationStyle(s, i)"
            >
              <span class="station-coin" aria-hidden="true">{{ s.numeral }}</span>
              <span class="station-text">
                <span class="station-name">{{ s.name }}</span>
                <span class="station-gloss">{{ s.gloss }}</span>
              </span>
            </li>
          </ol>
        </div>
      </section>
    </div>

    <!-- The anchor for #how while the Way is pinned: it sits where the climb
         ends, so a link lands on the finished Way. -->
    <span v-if="!still" id="how" class="way-anchor" aria-hidden="true"></span>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import SwarmCanvas from './SwarmCanvas.vue'
import { ACTS } from '../parthenon/vocabulary.js'
import { withBase } from '../parthenon/base.js'
import {
  subscribe,
  trackProgress,
  coverPoint,
  climbTime,
  lapseYear,
  LAPSE_LANDSCAPE,
  LAPSE_PORTRAIT,
  coverSource,
  meanLuma,
  skyNeed,
  lapseSkyGuess,
  smoothPath,
  firstClause,
  afterIdle
} from '../parthenon/descent.js'

const props = defineProps({
  era: { type: String, default: 'ancient' }, // 'ancient' | 'now'
  speaker: { type: Object, default: null } // { name, letter } when someone has the floor
})
// view: { inView, top } as the hero passes. way: where the Way leaves the foot
// of the frame, { x } in page pixels, so the page can carry the thread on.
const emit = defineEmits(['update:era', 'begin', 'view', 'way'])

const { t, te, tm, locale } = useI18n()
// English until the key reaches every locale.
const label = (key, fallback) => (te(key) ? t(key) : fallback)
const zh = computed(() => String(locale.value).startsWith('zh'))

// Same camera, 2,425 years apart: the Propylaea at dawn in 399 BC, and today.
const scenes = {
  ancient: {
    still1280: withBase('/media/hero/acropolis-399bc-1280.jpg'),
    still2560: withBase('/media/hero/acropolis-399bc-2560.jpg'),
    portrait1280: withBase('/media/hero/acropolis-399bc-portrait-1280.jpg'),
    video1280: withBase('/media/hero/acropolis-399bc-1280.mp4'),
    // The 1920 climb cut with a keyframe every 8 frames: it plays on arrival and
    // is then scrubbed by the scroll, one file and one element on a wide screen.
    climb1920: withBase('/media/hero/acropolis-399bc-climb-1920.mp4'),
    scrub: withBase('/media/hero/acropolis-399bc-scrub-1280.mp4'),
    scrubPortrait: withBase('/media/hero/acropolis-399bc-scrub-portrait-960.mp4'),
    end2560: withBase('/media/hero/acropolis-399bc-end-2560.jpg'),
    endPortrait: withBase('/media/hero/acropolis-399bc-end-portrait-1280.jpg')
  },
  now: {
    still1280: withBase('/media/hero/acropolis-2026-1280.jpg'),
    still2560: withBase('/media/hero/acropolis-2026-2560.jpg'),
    portrait1280: withBase('/media/hero/acropolis-2026-portrait-1280.jpg'),
    video1280: withBase('/media/hero/acropolis-2026-1280.mp4'),
    climb1920: withBase('/media/hero/acropolis-2026-climb-1920.mp4'),
    scrub: withBase('/media/hero/acropolis-2026-scrub-1280.mp4'),
    scrubPortrait: withBase('/media/hero/acropolis-2026-scrub-portrait-960.mp4'),
    end2560: withBase('/media/hero/acropolis-2026-end-2560.jpg'),
    endPortrait: withBase('/media/hero/acropolis-2026-end-portrait-1280.jpg')
  }
}

// The picture described once, in the visitor's language; the section itself is
// named by its heading.
const sceneLabel = computed(() => label(`parthenon.hero.scenes.${props.era}`, ''))
const eraYear = (key) => (key === 'ancient' ? label('parthenon.eraAncient', '399 BC') : label('parthenon.eraNow', '2026'))
// "Sit on the steps. Listen." In Chinese the full stop already ends the phrase.
const heroLine1 = computed(() => `${t('parthenon.heroLine1')}${zh.value ? '' : ' '}`)

// The time-lapse toward each era: forward to 2026, reversed back to 399 BC.
const LAPSES = {
  now: {
    w1280: withBase('/media/hero/era-timelapse-1280.mp4'),
    w1920: withBase('/media/hero/era-timelapse-1920.mp4'),
    portrait: withBase('/media/hero/era-timelapse-portrait-960.mp4')
  },
  ancient: {
    w1280: withBase('/media/hero/era-timelapse-rev-1280.mp4'),
    w1920: withBase('/media/hero/era-timelapse-rev-1920.mp4'),
    portrait: withBase('/media/hero/era-timelapse-portrait-rev-960.mp4')
  }
}
const LAPSE_RATE = 2
// Two moments of the building's life, told as the years pass them (on the way
// forward only): Athena Promachos leaves, and the restoration begins.
const BEATS = [
  { key: 'statue', year: 465, fallback: 'About AD 465: Athena Promachos is carried off to Constantinople' },
  { key: 'restore', year: 1975, fallback: '1975: the restoration begins' }
]

// Where things are on the plates, as fractions of the image: the roofline
// (the tip of Athena's spear, or the floodlit pediment) and the Propylaea
// columns either side. The upright plate is cut with less sky, so the temple
// stands higher in the frame and clear of the words on a phone.
const PLATE = {
  landscape: { w: 2560, h: 1086, roof: { ancient: 0.46, now: 0.46 }, colLeft: 0.28, colRight: 0.72 },
  portrait: { w: 960, h: 1280, roof: { ancient: 0.36, now: 0.4 }, colLeft: -1, colRight: 2 }
}

// The Way on each end frame (2560x1084), from the foot of the steps to the
// temple: where the path enters, the five stations, and where it ends. `side`
// is where a station's words sit. These are the plate's own pixels; they are
// mapped through the same cover crop as the image.
const END = { w: 2560, h: 1084 }
const WAY = {
  ancient: {
    // The path comes up from the foot of the frame on the left, the side the
    // page carries it on to (the thread down to the stages).
    enter: { x: 1040, y: 1170 },
    stations: [
      { x: 1150, y: 1010, side: 'right' },
      { x: 905, y: 905, side: 'left' },
      { x: 1110, y: 830, side: 'right' },
      { x: 1350, y: 748, side: 'left' },
      { x: 1560, y: 660, side: 'right' }
    ],
    leave: { x: 1600, y: 640 }
  },
  now: {
    enter: { x: 1100, y: 1170 },
    stations: [
      { x: 1216, y: 1030, side: 'left' },
      { x: 1225, y: 930, side: 'left' },
      { x: 1500, y: 880, side: 'right' },
      { x: 1400, y: 640, side: 'left' },
      { x: 1560, y: 500, side: 'right' }
    ],
    leave: { x: 1600, y: 450 }
  }
}

const track = ref(null)
const root = ref(null)
const copy = ref(null)
const arrival = ref(null)
const scrubEl = ref(null)
const lapseEl = ref(null)
const lapseCap = ref(null)
const videos = {}
const initialEra = props.era
// rolling: the video has a decoded frame worth showing over the still.
const playing = reactive({ ancient: false, now: false })
// rested: the climb is over; the last frame drifts on slowly.
const rested = reactive({ ancient: false, now: false })
// The layer on screen. It follows era once the new video shows the same moment.
const shown = ref(props.era)

// What may load: the first era at once; the other, the end frames, the
// scrub and the time-lapse only after first paint (idle, a scroll, a hover).
// An era's end frame waits until that era is chosen.
const armed = reactive({ ancient: props.era === 'ancient', now: props.era === 'now' })
const endFor = reactive({ ancient: props.era === 'ancient', now: props.era === 'now' })

const hasWindow = typeof window !== 'undefined'
const media = (q) => (hasWindow && window.matchMedia ? window.matchMedia(q) : null)
const reduceMotion = !!media('(prefers-reduced-motion: reduce)')?.matches
const saveData = typeof navigator !== 'undefined' && !!navigator.connection?.saveData
// Upright screens: phones, and tablets or windows held upright. index.html
// preloads by the same query.
const PORTRAIT_QUERY = '(max-width: 699px), (orientation: portrait) and (max-width: 1100px)'
const portraitQuery = media(PORTRAIT_QUERY)
// A phone on its side has no room to pin a screen: the descent lies flat.
const shortQuery = media('(max-height: 500px) and (orientation: landscape)')
const portrait = ref(!!portraitQuery?.matches)
const short = ref(!!shortQuery?.matches)
const still = computed(() => reduceMotion || short.value)
const motionAllowed = !reduceMotion

// Video only when motion is welcome and data is not being saved. The climb
// that plays on arrival is landscape: an upright screen keeps its still, with
// a slow drift, and climbs by the upright scrub when the visitor scrolls.
const videoAllowed = motionAllowed && !saveData
const layerVideo = computed(() => videoAllowed && !portrait.value)
const scrubAllowed = videoAllowed
const lapseAllowed = motionAllowed && !saveData

const endArmed = ref(still.value)
const scrubArmed = ref(false)
const lapseArmed = ref(false)
const lapsePreload = ref('metadata')

// Pick the video by how wide cover really draws it (the 2560x1086 frame is
// 236vh wide on a tall screen), in device pixels.
const drawnWidth = hasWindow
  ? Math.max(window.innerWidth, window.innerHeight * (2560 / 1086)) * Math.min(window.devicePixelRatio || 1, 2)
  : 0
const small = drawnWidth <= 1600
// A wide screen plays the seekable 1920 climb and scrubs that same element.
const unified = computed(() => layerVideo.value && !small)

const videoSrc = (scene) => (small ? scene.video1280 : scene.climb1920)
const scrubSrc = computed(() => (portrait.value ? scenes[shown.value].scrubPortrait : scenes[shown.value].scrub))

// The visitor can stop the video and the swarm (WCAG 2.2.2); remembered per browser.
const MOTION_KEY = 'parthenon.heroMotion'
const readPaused = () => {
  try {
    return localStorage.getItem(MOTION_KEY) === 'paused'
  } catch {
    return false
  }
}
const motionPaused = ref(!reduceMotion && readPaused())
const stillDrift = ref(false)
const syncDrift = () => {
  stillDrift.value = motionAllowed && !layerVideo.value && !motionPaused.value
}
syncDrift()

// The sky the flock may use and the block of words it keeps out of, both
// measured from how cover really places the plate in this frame.
const sky = ref({ top: 0.05, bottom: 0.44, left: 0.2, right: 0.9 })
const avoid = ref(null)
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

// The stage's size and the Way drawn in it.
const box = reactive({ w: 0, h: 0 })
const wayMode = ref('path') // 'path' across a wide frame, 'list' up a tall one
const points = ref([]) // the stations in stage pixels, with side and dy
const pathD = ref('')

// The five stations: the Greek numeral, the act's name and one line of gloss.
const stations = computed(() => {
  const names = tm('main.stepNames')
  const moves = tm('parthenon.movements')
  const glosses = tm('parthenon.how.stations')
  const way = WAY[shown.value] || WAY.ancient
  return ACTS.map((act, i) => ({
    numeral: act.numeral,
    name: (Array.isArray(names) && names[i]) || moves?.[i]?.title || '',
    gloss: (Array.isArray(glosses) && typeof glosses[i] === 'string' && glosses[i]) || firstClause(moves?.[i]?.desc || ''),
    side: wayMode.value === 'path' ? points.value[i]?.side || way.stations[i]?.side || 'right' : 'right'
  }))
})

const stationStyle = (s, i) => {
  const p = points.value[i]
  const style = { '--i': i }
  if (wayMode.value === 'path' && p) {
    style['--x'] = `${Math.round(p.x)}px`
    style['--y'] = `${Math.round(p.y)}px`
    if (p.dy) style['--dy'] = `${Math.round(p.dy)}px`
  }
  return style
}

const measure = () => {
  const el = root.value
  if (!el) return
  const W = el.clientWidth
  const H = el.clientHeight
  if (W < 2 || H < 2) return
  box.w = W
  box.h = H
  const upright = portrait.value
  const plate = upright ? PLATE.portrait : PLATE.landscape
  const roof = plate.roof[shown.value] ?? plate.roof.ancient
  const tall = W / H < 1
  // Must match .layer img / video object-position below.
  const px = upright ? 0.5 : tall ? 0.52 : 0.22
  const py = upright ? 0.6 : tall ? 0.6 : 0.58
  const scale = Math.max(W / plate.w, H / plate.h)
  const dw = plate.w * scale
  const dh = plate.h * scale
  const ox = (dw - W) * px
  const oy = (dh - H) * py
  sky.value = {
    top: 0.05,
    bottom: clamp((roof * dh - oy) / H - 0.03, 0.24, 0.6),
    left: clamp((plate.colLeft * dw - ox) / W + 0.02, 0.04, 0.4),
    right: clamp((plate.colRight * dw - ox) / W - 0.02, 0.6, 0.96)
  }
  const c = copy.value
  if (c) {
    const r = el.getBoundingClientRect()
    const b = c.getBoundingClientRect()
    avoid.value = { x: b.left - r.left, y: b.top - r.top, w: b.width, h: b.height }
    // Where the words begin (their layout, before the climb moves them): on a
    // short frame the night is anchored there rather than to the screen.
    track.value?.style.setProperty('--copy-top', `${Math.round(c.offsetTop)}px`)
    // And where they end on the right: the widest line, the lede, the actions.
    const parts = c.querySelectorAll('.title .line, .lede, .actions > *')
    let right = 0
    parts.forEach((e) => {
      right = Math.max(right, e.offsetLeft + e.offsetWidth)
    })
    track.value?.style.setProperty('--copy-right', `${Math.round(c.offsetLeft + right)}px`)
  }
  measureWay()
}

// The Way follows the end frame's own cover crop (the same object-position
// as the plates), so the path climbs the real steps.
const measureWay = () => {
  const a = arrival.value
  const W = a?.clientWidth || box.w
  const H = a?.clientHeight || box.h
  if (W < 2 || H < 2) return
  box.w = W
  box.h = H
  const list = portrait.value || W / H < 1 || H < 560 || W < 900
  wayMode.value = list ? 'list' : 'path'
  if (list) {
    points.value = []
    pathD.value = ''
    nextTick(tellFoot)
    return
  }
  const way = WAY[shown.value] || WAY.ancient
  const pos = { x: 0.22, y: 0.58 }
  const map = (p) => coverPoint(p.x, p.y, { w: W, h: H }, END, pos)
  const marks = way.stations.map((p) => {
    const q = map(p)
    return { x: clamp(q.x, 36, W - 36), y: clamp(q.y, 110, H - 44), side: p.side, dy: 0 }
  })
  points.value = marks
  const enter = map(way.enter)
  pathD.value = smoothPath([enter, ...marks, map(way.leave)])
  // Where the path crosses the foot of the frame, between its entry and A'.
  const a0 = marks[0]
  const k = enter.y > a0.y ? clamp((enter.y - H) / (enter.y - a0.y), 0, 1) : 0
  foot.x = enter.x + (a0.x - enter.x) * k
  nextTick(() => {
    fitPlaques()
    tellFoot()
  })
}

// The page carries the Way on below the frame from where it leaves.
const foot = { x: 0 }
const tellFoot = () => {
  const a = arrival.value
  if (!a) return
  let x = foot.x
  // Where the drawn curve itself crosses the foot of the frame.
  const line = wayMode.value === 'path' ? a.querySelector('.way-line') : null
  if (line && typeof line.getTotalLength === 'function') {
    try {
      const H = box.h
      let lo = 0
      let hi = line.getTotalLength()
      if (line.getPointAtLength(lo).y > H) {
        for (let k = 0; k < 24; k++) {
          const mid = (lo + hi) / 2
          if (line.getPointAtLength(mid).y > H) lo = mid
          else hi = mid
        }
        x = line.getPointAtLength(hi).x
      }
    } catch {
      /* not laid out yet: the straight estimate stands */
    }
  }
  if (wayMode.value === 'list') {
    const coin = a.querySelector('.station-coin')
    const r = coin?.getBoundingClientRect()
    const base = a.getBoundingClientRect()
    x = r ? r.left - base.left + r.width / 2 : 0
  }
  emit('way', { x: Math.round(x), mode: wayMode.value })
}

// Each plaque sits beside its station, on the side it was placed. One that
// would run off the frame, or cover another plaque or coin, turns to the other
// side; if both sides are taken it steps up clear of the one below.
const fitPlaques = () => {
  const a = arrival.value
  if (!a || wayMode.value !== 'path' || !points.value.length) return
  const texts = a.querySelectorAll('.station-text')
  const W = box.w
  const GAP = 32
  const coins = points.value.map((m) => ({ x0: m.x - 22, x1: m.x + 22, y0: m.y - 22, y1: m.y + 22 }))
  const hits = (r, placed, own) =>
    placed.some((q) => r.x0 < q.x1 + 6 && r.x1 > q.x0 - 6 && r.y0 < q.y1 + 6 && r.y1 > q.y0 - 6) ||
    coins.some((c, j) => j !== own && r.x0 < c.x1 && r.x1 > c.x0 && r.y0 < c.y1 && r.y1 > c.y0)
  const rect = (m, side, w, h, dy = 0) => {
    const x0 = side === 'right' ? m.x + GAP : m.x - GAP - w
    return { x0, x1: x0 + w, y0: m.y - h / 2 + dy, y1: m.y + h / 2 + dy }
  }
  const way = WAY[shown.value] || WAY.ancient
  const placed = []
  let changed = false
  const next = points.value.map((m, i) => {
    const w = texts[i]?.offsetWidth || 240
    const h = texts[i]?.offsetHeight || 48
    const preferred = way.stations[i]?.side || 'right'
    const other = preferred === 'right' ? 'left' : 'right'
    const fits = (side) => {
      const r = rect(m, side, w, h)
      return r.x0 >= 12 && r.x1 <= W - 12
    }
    let side = [preferred, other].find((sd) => fits(sd) && !hits(rect(m, sd, w, h), placed, i))
    let dy = 0
    if (!side) {
      // Both sides are taken: the plaque slides along its coin, up or down, by
      // the least that clears (never far from its station).
      let best = null
      for (const sd of [preferred, other]) {
        if (!fits(sd)) continue
        for (let step = 4; step <= 56; step += 4) {
          const clear = [-step, step].find((d) => !hits(rect(m, sd, w, h, d), placed, i))
          if (clear !== undefined) {
            if (!best || step < Math.abs(best.dy)) best = { side: sd, dy: clear }
            break
          }
        }
      }
      side = best?.side || (fits(preferred) ? preferred : other)
      dy = best?.dy || 0
    }
    placed.push(rect(m, side, w, h, dy))
    if (side !== m.side || dy !== (m.dy || 0)) changed = true
    return { ...m, side, dy }
  })
  if (changed) points.value = next
}

const resume = (video) => {
  video.play().catch(() => {
    // Autoplay can be refused (low power mode); the still stays.
  })
}

// Line a video up at `from`, hiding its old frame until the new one is decoded.
const cue = (key, from = 0) => {
  const video = videos[key]
  if (!video) return
  playing[key] = false
  rested[key] = false
  try {
    video.currentTime = from
  } catch {
    // metadata not loaded yet; it will start from 0
  }
}

const play = (key, from = 0) => {
  cue(key, from)
  if (videos[key]) resume(videos[key])
}

// Show the video once it has a frame at its new time. Paused on frame 0, the
// still is the same view, only sharper.
const onFrame = (key) => {
  const video = videos[key]
  if (!video || video.seeking || video.readyState < 2) return
  if (!video.paused || video.currentTime > 0) playing[key] = true
}

// Entering the city: each era's climb plays once and rests on its last frame,
// which then drifts for forty seconds.
const onEnded = (key) => {
  playing[key] = true
  rested[key] = true
}

// Resolves once the video is rolling (or after `ms`). The style read commits the
// video as opaque while its layer is still hidden, so only the layer crossfades.
const whenRolling = (key, ms = 900) => new Promise((resolve) => {
  let stopWatch = null
  const finish = async () => {
    clearTimeout(timer)
    stopWatch?.()
    await nextTick()
    if (videos[key]) void getComputedStyle(videos[key]).opacity
    resolve()
  }
  const timer = setTimeout(finish, ms)
  stopWatch = watch(() => playing[key], (on) => on && finish())
})

// ---- The descent ----
// phase: 'top' (the hero as it was), 'scrub' (the scroll drives the climb) or
// 'dissolve' (the still pushes in, dips through night, and the end frame comes
// up). The phase is chosen when the descent begins and kept until the visitor
// is back at the top, so the picture never changes method halfway up the steps.
const phase = ref('top')
const descended = ref(false) // past the words: they no longer take clicks
const camEnd = ref(false) // the climb had already finished at the top
const cut = ref(false) // a match-cut: no crossfade for one frame
const scrubOn = ref(false)
const scrubReady = ref(false)
let progress = 0
let camTime = 0 // where the climb stood when the descent began
let visible = true
let viewed = null
let viewedTop = null
let wantTime = null
let seeking = false
const CLIMB_END = 0.7 // the scrubbed climb reaches the end frame here

const swarmPaused = ref(false)

// The element the scroll drives: the playing climb itself on a wide screen,
// else the scrub cut.
const scrubVideo = () => (unified.value ? videos[shown.value] : scrubEl.value)
const scrubIsReady = () => {
  const s = scrubVideo()
  if (!s || !(Number.isFinite(s.duration) && s.duration > 0)) return false
  return unified.value ? s.readyState >= 2 : scrubReady.value
}

const onScrubLoaded = () => {
  scrubReady.value = true
}

const seekTo = (time) => {
  wantTime = time
  const el = scrubVideo()
  if (!el || seeking || !(el.readyState >= 1)) return
  if (Math.abs(el.currentTime - time) < 1 / 48) {
    if (phase.value === 'scrub' && el.readyState >= 2) scrubOn.value = true
    return
  }
  seeking = true
  try {
    el.currentTime = time
  } catch {
    seeking = false
  }
}

// One seek at a time; the newest wish is taken up on the next frame.
const onScrubSeeked = () => {
  seeking = false
  if (phase.value === 'scrub') scrubOn.value = true
  if (wantTime == null) return
  requestAnimationFrame(() => {
    if (phase.value === 'scrub' && wantTime != null) seekTo(wantTime)
  })
}

// The playing climb reports a new frame; on a wide screen it is also the scrub.
const onLayerSeeked = (key) => {
  onFrame(key)
  if (unified.value && key === shown.value) onScrubSeeked()
}

// An upright still drifts slowly at the top. The climb starts from the same
// framing: the drift is held, and the scrub takes its scale and lets it go
// over the first steps.
const holdDrift = () => {
  const img = root.value?.querySelector('.layer.active img')
  let s = 1
  if (img && stillDrift.value) {
    const m = getComputedStyle(img).transform
    const a = m && m.startsWith('matrix(') ? parseFloat(m.slice(7)) : 1
    if (a > 1 && a < 1.2) s = a
  }
  track.value?.style.setProperty('--drift-s', s.toFixed(4))
}

const enterDescent = () => {
  const key = shown.value
  const v = videos[key]
  camTime = v && playing[key] ? v.currentTime || 0 : 0
  camEnd.value = !!rested[key]
  v?.pause()
  holdDrift()
  const dur = scrubVideo()?.duration
  const ready = scrubIsReady() && !lapse.on
  phase.value = ready && !camEnd.value && camTime < dur - 0.3 ? 'scrub' : 'dissolve'
  if (phase.value === 'scrub') {
    wantTime = camTime
    seekTo(camTime)
  }
}

const leaveDescent = () => {
  const wasScrub = phase.value === 'scrub'
  phase.value = 'top'
  scrubOn.value = false
  wantTime = null
  camEnd.value = false
  const v = videos[shown.value]
  // The scrubbed climb goes back to where the visitor set off from.
  if (unified.value && wasScrub && v) {
    try {
      if (Math.abs(v.currentTime - camTime) > 0.04) v.currentTime = camTime
    } catch {
      /* not seekable yet */
    }
  }
  if (v && visible && !motionPaused.value && !v.ended && !lapse.on) resume(v)
}

const armLater = () => {
  if (!endArmed.value) endArmed.value = true
  if (scrubAllowed && !scrubArmed.value) scrubArmed.value = true
}

const stepDescent = (p) => {
  if (p > 0.001) armLater()
  if (p <= 0.001) {
    if (phase.value !== 'top') leaveDescent()
  } else {
    if (phase.value === 'top') enterDescent()
    // The scrub arrived just after the visitor set off: take it while the
    // push-in has hardly begun, so the change is not seen.
    if (phase.value === 'dissolve' && p < 0.06 && !camEnd.value && !lapse.on && scrubIsReady()) {
      const dur = scrubVideo()?.duration
      if (dur > 0 && camTime < dur - 0.3) {
        phase.value = 'scrub'
        wantTime = camTime
      }
    }
    if (phase.value === 'scrub') {
      const dur = scrubVideo()?.duration
      if (dur > 0) seekTo(climbTime(p, camTime, dur, CLIMB_END))
    }
  }
  const past = p > 0.2
  if (past !== descended.value) descended.value = past
  // The flock has faded out by 0.733 (--d-sky); it rests from just after.
  const hush = p > 0.74 || !visible
  if (hush !== swarmPaused.value) swarmPaused.value = hush
}

const setVisible = (on) => {
  if (on === visible) return
  visible = on
  const v = videos[shown.value]
  if (!v || v.ended) return
  // A climb cued while the hero was off screen starts when it comes back.
  if (!on) v.pause()
  else if (!motionPaused.value && phase.value === 'top' && !lapse.on) resume(v)
}

const onScroll = (m) => {
  const tr = track.value
  const cine = root.value
  if (!tr || !cine) return
  const r = tr.getBoundingClientRect()
  const c = cine.getBoundingClientRect()
  const p = still.value ? 0 : trackProgress(r.top, r.height, m.vh)
  const onScreen = c.bottom > m.vh * 0.2 && c.top < m.vh * 0.8
  const inView = c.bottom > 68 + m.vh * 0.12
  // At the top: the climb has not really begun (or, still, the hero has not
  // yet moved); the page's bar goes solid once it has.
  const atTop = inView && (still.value ? c.top > -40 : p < 0.3)
  return () => {
    if (p !== progress) {
      progress = p
      tr.style.setProperty('--descent', p.toFixed(4))
    }
    setVisible(onScreen)
    stepDescent(p)
    if (inView !== viewed || atTop !== viewedTop) {
      viewed = inView
      viewedTop = atTop
      emit('view', { inView, top: atTop })
    }
  }
}

// A keyboard visitor tabbing back into the words while they are faded out is
// taken back to the top, where they can be seen.
const onCopyFocus = () => {
  if (still.value || progress < 0.2 || !track.value) return
  const top = track.value.getBoundingClientRect().top + window.scrollY
  window.scrollTo({ top, behavior: 'smooth' })
}

// ---- The time-lapse ----
// veil: night over the picture while the camera leaves mid-climb for the foot
// of the steps, so the years begin on a clean frame.
const lapse = reactive({ on: false, to: null, year: -399, veil: false })
const lapseTarget = computed(() => lapse.to || (shown.value === 'ancient' ? 'now' : 'ancient'))
const lapseSrc = computed(() => {
  const files = LAPSES[lapseTarget.value]
  return portrait.value ? files.portrait : small ? files.w1280 : files.w1920
})
const lapseYearText = computed(() => {
  const y = lapse.year
  const key = y < 0 ? 'parthenon.hero.yearBC' : 'parthenon.hero.yearAD'
  const year = String(Math.abs(y))
  if (te(key)) return t(key, { year })
  return y < 0 ? `${year} BC` : `AD ${year}`
})
// The beats stay once passed, one under the other, until the years stop.
const lapseBeats = computed(() =>
  BEATS.map((b) => ({
    key: b.key,
    text: label(`parthenon.hero.lapseBeats.${b.key}`, b.fallback),
    on: lapse.on && lapse.to === 'now' && lapse.year >= b.year
  }))
)

// Ready the time-lapse when the visitor reaches for the years.
const warmLapse = () => {
  if (!lapseAllowed) return
  lapseArmed.value = true
  lapsePreload.value = 'auto'
  armed.ancient = true
  armed.now = true
}

// The counter's night follows the sky under it: a few times a second the
// patch of picture behind the year and its title is read back, very small,
// and the counter takes as much night as that sky needs (all of it over the
// white dawn, none at blue hour). Where the picture cannot be read, the
// file's position stands in for it.
const SKY_EVERY = 110
let skyCanvas = null
let skyCtx = null
let skyBlind = false
let skyAt = 0
// How much night the counter has now (0..1), written to its --sky.
let skyNight = 1
const setSky = (value) => {
  skyNight = value
  lapseCap.value?.style.setProperty('--sky', value.toFixed(3))
}
const readSky = (el) => {
  if (skyBlind || !(el.videoWidth > 0) || el.readyState < 2) return null
  const cap = lapseCap.value
  if (!cap) return null
  const parts = cap.querySelectorAll('.lapse-title, .lapse-year')
  if (!parts.length) return null
  const v = el.getBoundingClientRect()
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  parts.forEach((p) => {
    const r = p.getBoundingClientRect()
    x0 = Math.min(x0, r.left)
    y0 = Math.min(y0, r.top)
    x1 = Math.max(x1, r.right)
    y1 = Math.max(y1, r.bottom)
  })
  const [px, py] = getComputedStyle(el)
    .objectPosition.split(' ')
    .map((n) => (n.endsWith('%') ? parseFloat(n) / 100 : 0.5))
  const src = coverSource(
    { x: x0 - v.left - 12, y: y0 - v.top - 8, w: x1 - x0 + 24, h: y1 - y0 + 16 },
    { w: v.width, h: v.height },
    { w: el.videoWidth, h: el.videoHeight },
    { x: Number.isFinite(px) ? px : 0.5, y: Number.isFinite(py) ? py : 0.5 }
  )
  if (!src) return null
  try {
    if (!skyCanvas) {
      skyCanvas = document.createElement('canvas')
      skyCanvas.width = 24
      skyCanvas.height = 8
      skyCtx = skyCanvas.getContext('2d', { willReadFrequently: true })
    }
    if (!skyCtx) throw new Error('no 2d')
    skyCtx.drawImage(el, src.x, src.y, src.w, src.h, 0, 0, 24, 8)
    return meanLuma(skyCtx.getImageData(0, 0, 24, 8).data)
  } catch {
    skyBlind = true
    return null
  }
}
const tickSky = (el, f, now) => {
  if (now - skyAt < SKY_EVERY) return
  skyAt = now
  const luma = lapse.veil ? null : readSky(el)
  const need = luma == null ? lapseSkyGuess(f, lapse.to) : skyNeed(luma)
  // Eased, so a flicker in the footage never shows in the night.
  setSky(skyNight + (need - skyNight) * 0.45)
}

let lapseDone = null
let yearFrame = 0
let yearsFrom = 0
const tickYear = () => {
  const el = lapseEl.value
  if (!lapse.on || !el) {
    yearFrame = 0
    return
  }
  const f = el.duration > 0 ? el.currentTime / el.duration : 0
  // Each file has its own clock: the upright cut loses Athena sooner.
  const table = portrait.value ? LAPSE_PORTRAIT : LAPSE_LANDSCAPE
  const now = performance.now()
  if (!lapse.veil && now >= yearsFrom) lapse.year = lapseYear(lapse.to === 'ancient' ? 1 - f : f, table)
  tickSky(el, f, now)
  yearFrame = requestAnimationFrame(tickYear)
}

const onLapseEnded = () => {
  lapseDone?.()
}

const stopLapse = () => {
  lapseDone?.(false)
  lapseDone = null
  lapse.on = false
  lapse.to = null
  lapse.veil = false
  if (yearFrame) cancelAnimationFrame(yearFrame)
  yearFrame = 0
  try {
    lapseEl.value?.pause()
  } catch {
    /* nothing to stop */
  }
}

// Resolves true once the element is playing, false after `ms`.
const playWithin = (el, ms) => new Promise((resolve) => {
  let settled = false
  const done = (ok) => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    el.removeEventListener('playing', onPlaying)
    resolve(ok)
  }
  const onPlaying = () => done(true)
  const timer = setTimeout(() => done(false), ms)
  el.addEventListener('playing', onPlaying)
  el.play().catch(() => done(false))
})

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Twenty-four centuries at twice their pace, then a cut onto the other era's
// first frame: the time-lapse ends on exactly that picture.
const runLapse = async (next, previous, turn) => {
  lapseArmed.value = true
  lapsePreload.value = 'auto'
  lapse.to = next
  await nextTick()
  const el = lapseEl.value
  if (!el) return false
  el.defaultPlaybackRate = LAPSE_RATE
  el.playbackRate = LAPSE_RATE
  // From the foot of the steps it is a cut. From anywhere up the climb the
  // camera must jump back down: night falls over the picture first.
  const old = videos[previous]
  const atFoot = !old || !playing[previous] || old.currentTime < 0.15
  if (!atFoot) {
    lapse.veil = true
    await wait(250)
    if (turn !== swap) return true
  }
  try {
    el.currentTime = 0
  } catch {
    /* not loaded yet: it starts at 0 anyway */
  }
  const started = await playWithin(el, 2600)
  if (turn !== swap) return true
  if (!started) {
    lapse.to = null
    lapse.veil = false
    try {
      el.pause()
    } catch {
      /* never started */
    }
    return false
  }
  cut.value = true
  yearsFrom = 0
  lapse.year = lapse.to === 'ancient' ? 2026 : -399
  // The first frame is the other era's start: the white dawn going forward,
  // the lit night going back.
  setSky(lapse.to === 'ancient' ? 0 : 1)
  skyAt = 0
  lapse.on = true
  if (yearFrame) cancelAnimationFrame(yearFrame)
  yearFrame = requestAnimationFrame(tickYear)
  requestAnimationFrame(() => {
    cut.value = false
    // Lift the night; the years hold their first value until it has gone.
    if (lapse.veil) {
      lapse.veil = false
      yearsFrom = performance.now() + 350
    }
  })
  old?.pause()
  const finished = await new Promise((resolve) => {
    lapseDone = resolve
    // A stalled file never holds the hero: give up after twice its length.
    setTimeout(() => resolve(true), 9000)
  })
  lapseDone = null
  if (turn !== swap || finished === false) return true
  // Land: the other era's climb waits on frame 0 (its still is the same picture).
  cut.value = true
  cue(next, 0)
  shown.value = next
  measure()
  await nextTick()
  lapse.on = false
  lapse.to = null
  lapse.year = next === 'now' ? 2026 : -399
  if (previous && videos[previous]) {
    playing[previous] = false
    rested[previous] = false
  }
  requestAnimationFrame(() => {
    cut.value = false
  })
  const v = videos[next]
  if (v && visible && !motionPaused.value && phase.value === 'top') resume(v)
  return true
}

const toggleMotion = () => {
  motionPaused.value = !motionPaused.value
  try {
    if (motionPaused.value) localStorage.setItem(MOTION_KEY, 'paused')
    else localStorage.removeItem(MOTION_KEY)
  } catch {
    // storage blocked; the choice lasts for this visit
  }
  syncDrift()
  if (motionPaused.value && (lapse.on || lapse.to)) {
    // The years stop where the visitor asked; the chosen era is shown at once.
    stopLapse()
    if (shown.value !== props.era) {
      shown.value = props.era
      measure()
    }
  }
  const video = videos[props.era]
  if (!video) return
  if (motionPaused.value) video.pause()
  else if (visible && phase.value === 'top' && !video.ended) resume(video)
}

let sizeObserver = null
let unsubscribe = null
let cancelIdle = null
let cancelSoon = null

const onPortraitChange = (e) => {
  portrait.value = e.matches
  syncDrift()
  measure()
}
const onShortChange = (e) => {
  short.value = e.matches
  if (e.matches) endArmed.value = true
  nextTick(measure)
}

// A phone downloads the time-lapse whole only on a good connection.
const goodLink = () => {
  const type = typeof navigator !== 'undefined' ? navigator.connection?.effectiveType : undefined
  return !type || type === '4g'
}

onMounted(() => {
  measure()
  sizeObserver = new ResizeObserver(measure)
  sizeObserver.observe(root.value)
  if (copy.value) sizeObserver.observe(copy.value)
  if (arrival.value) sizeObserver.observe(arrival.value)
  portraitQuery?.addEventListener('change', onPortraitChange)
  shortQuery?.addEventListener('change', onShortChange)
  unsubscribe = subscribe(onScroll)

  // Soon after load, this era's scrub and end frame. Idle four seconds after
  // load, the other era's first frame and the time-lapse's first bytes (its
  // header); the whole file when the visitor reaches for the years, or at once
  // where a hand cannot hover and the link is good. Never before first paint.
  cancelSoon = afterIdle(window, 1200, armLater)
  cancelIdle = afterIdle(window, 4000, () => {
    armed.ancient = true
    armed.now = true
    armLater()
    if (lapseAllowed) {
      lapseArmed.value = true
      const touch = media('(hover: none)')?.matches
      lapsePreload.value = touch && goodLink() ? 'auto' : 'metadata'
    }
  })

  if (!layerVideo.value) return
  if (!motionPaused.value && phase.value === 'top') play(props.era)
})

onBeforeUnmount(() => {
  sizeObserver?.disconnect()
  portraitQuery?.removeEventListener('change', onPortraitChange)
  shortQuery?.removeEventListener('change', onShortChange)
  unsubscribe?.()
  cancelIdle?.()
  cancelSoon?.()
  stopLapse()
})

// Switching eras at the foot of the steps plays the time-lapse. Anywhere else
// (mid-climb, off screen, paused, reduced motion, saving data) it is the old
// crossfade: mid-climb keeps the camera where it is; after the climb, the new
// era replays its own entrance; off screen the new era is only lined up.
let swap = 0
watch(() => props.era, async (next, previous) => {
  const turn = ++swap
  armed[next] = true
  endFor[next] = true
  if (lapse.on || lapse.to) stopLapse()
  const live = visible && !motionPaused.value && phase.value === 'top'
  if (lapseAllowed && live && next !== shown.value && !still.value) {
    const handled = await runLapse(next, previous, turn)
    if (handled) return
  }
  if (turn !== swap) return
  if (!layerVideo.value) {
    shown.value = next
    measure()
    return
  }
  const old = videos[previous]
  if (next === shown.value) {
    // Switched back before the crossfade began: that layer never left.
    old?.pause()
    if (live && videos[next] && !videos[next].ended) resume(videos[next])
    return
  }
  await nextTick()
  const from = old && !old.ended ? old.currentTime : 0
  if (live) play(next, from)
  else cue(next, from)
  // On screen, hold the old layer until the new video shows the same moment.
  if (visible && (live || from > 0)) await whenRolling(next)
  if (turn !== swap) return
  shown.value = next
  measure()
  old?.pause()
})

// Words change width with the language.
watch(locale, () => nextTick(fitPlaques))

// The scrub follows the era on screen.
watch(shown, () => {
  scrubReady.value = false
  scrubOn.value = false
  if (phase.value === 'scrub') phase.value = 'dissolve'
})
</script>

<style scoped>
/* The track the visitor scrolls through; the stage stays pinned inside it.
   JS writes only --descent (0..1); every window below is read from it. */
.descent {
  --descent: 0;
  /* The browser's own bars on a phone, while they show. */
  --bars: max(0px, calc(100vh - 100dvh));
  --d-copy: clamp(0, calc(1 - var(--descent) * 3.6), 1);
  --d-push: clamp(0, calc(var(--descent) / 0.75), 1);
  --d-end: clamp(0, calc((var(--descent) - 0.35) / 0.37), 1);
  --d-way: clamp(0, calc((var(--descent) - 0.68) / 0.1), 1);
  /* The Way's night is laid first: it is whole by 0.68, where its words begin,
     so the heading never shows as a ghost over the dawn. */
  --d-way-shade: clamp(0, calc((var(--descent) - 0.58) / 0.1), 1);
  --d-draw: clamp(0, calc((var(--descent) - 0.7) / 0.24), 1);
  --d-sky: clamp(0, calc(1 - (var(--descent) - 0.4) * 3), 1);
  /* An upright climb: the drift the still had at the top lets go over the
     first steps, and the frame sinks below the top bar as the temple nears. */
  --d-unzoom: clamp(0, calc(var(--descent) / 0.3), 1);
  --d-lift: clamp(0, calc((var(--descent) - 0.3) / 0.36), 1);
  --drift-s: 1;
  --lift: 0px;

  position: relative;
  height: 220vh;
  background: #0b0e13;
  color: var(--p-ink);
}

/* The scrubbed climb arrives at the end frame by itself; the sharp still
   takes over only at the very top. */
.descent.mode-scrub {
  --d-push: 0;
  --d-end: clamp(0, calc((var(--descent) - 0.66) / 0.08), 1);
}

/* The climb already finished at the top: the camera is there. */
.descent.cam-end {
  --d-push: 0;
}

/* Without the scrubbed climb the camera walks into the dark of the gate and
   comes out at the top of the steps: the start plate goes to night, then the
   end frame comes up. Two temples are never on screen at once. */
.descent.mode-dissolve:not(.cam-end) {
  --d-end: clamp(0, calc((var(--descent) - 0.55) / 0.1), 1);
  --d-sky: clamp(0, calc((0.5 - var(--descent)) / 0.1), 1);
}

.mode-dissolve:not(.cam-end) .push {
  opacity: clamp(0, calc((0.5 - var(--descent)) / 0.1), 1);
}

.descent.portrait {
  --lift: 60px;
}

.stage {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: hidden;
  isolation: isolate;
}

/* The copy sits in flow at the bottom. */
.cine {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding-top: 88px;
  overflow: hidden;
  isolation: isolate;
  background: #0b0e13;
  color: var(--p-ink);
}

.media,
.push,
.layer,
.layer picture,
.layer img,
.layer video,
.scrub,
.lapse {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

/* The camera moves forward up the steps: the plate grows toward the temple
   and the steps sink below the frame. */
.push {
  transform-origin: 60% 50%;
  transform:
    translate3d(calc(var(--d-push) * -1.5%), calc(var(--d-push) * 3%), 0)
    scale(calc(1 + var(--d-push) * 0.18));
  will-change: transform;
}

.layer {
  opacity: 0;
  transition: opacity 1.4s cubic-bezier(0.22, 1, 0.36, 1);
}

.layer.active {
  opacity: 1;
}

/* The plate sits so the temple stands clear of the words: right of centre on
   a landscape screen, centred on a tall one. measure() mirrors these numbers,
   and the end frame, the scrub and the time-lapse share them. */
.layer img,
.layer video,
.scrub,
.lapse,
.end-layer img {
  object-fit: cover;
  object-position: 22% 58%;
}

@media (max-aspect-ratio: 1/1) {
  .layer img,
  .layer video,
  .scrub,
  .lapse,
  .end-layer img {
    object-position: 52% 60%;
  }
}

/* Upright screens get the 3:4 plates and the upright climb, all placed alike,
   so the still, the scrub and the end frame meet as match-cuts. */
@media (max-width: 699px), (orientation: portrait) and (max-width: 1100px) {
  .layer img,
  .layer video,
  .scrub,
  .lapse,
  .end-layer img {
    object-position: 50% 60%;
  }
}

/* A stale frame is hidden at once; the video fades in over the still only on
   the layer already on screen (an incoming layer is ready before it fades in). */
.layer video {
  opacity: 0;
}

.layer.rolling video {
  opacity: 1;
}

.layer.active.rolling video {
  transition: opacity 0.8s ease;
}

.scrub,
.lapse {
  opacity: 0;
  pointer-events: none;
}

.scrub.on,
.lapse.on {
  opacity: 1;
}

.lapse {
  transition: opacity 0.45s ease;
}

/* A match-cut: the frames agree, so nothing fades. */
.cut .layer,
.cut .layer video,
.cut .lapse,
.cut .end-layer {
  transition: none !important;
}

/* After the climb, the camera keeps breathing for forty seconds. */
@keyframes drift {
  from { transform: scale(1); }
  to { transform: scale(1.06); }
}

.layer.rested video {
  transform-origin: 60% 45%;
  animation: drift 40s ease-out forwards;
}

/* An upright screen gets the still: the same slow drift instead of the climb.
   It holds while the visitor climbs. */
.drifting .layer.active img {
  transform-origin: 50% 45%;
  animation: drift 40s ease-out forwards;
}

.descent:not(.mode-top) .layer img {
  animation-play-state: paused;
}

/* The upright scrub starts at the drifted framing and sinks below the bar as
   it climbs; the end frame sits exactly where the climb ends. */
.portrait .scrub {
  transform-origin: 50% 45%;
  transform:
    translate3d(0, calc(var(--d-lift) * var(--lift)), 0)
    scale(calc(1 + (var(--drift-s) - 1) * (1 - var(--d-unzoom))));
}

.descent.portrait.scrub-on .push {
  opacity: 0;
}

/* Night for a moment while the camera goes back down the steps. */
.veil {
  position: absolute;
  inset: 0;
  background: #0b0e13;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.35s ease;
}

.veiled .veil {
  opacity: 1;
  transition-duration: 0.25s;
}

.swarm {
  z-index: 1;
  opacity: var(--d-sky);
}

/* The grade: a wide left-bottom vignette, a seat under the words, a breath of
   night under the top bar. Nothing sits behind the type but the plate. */
.shade {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  opacity: calc(0.25 + var(--d-copy) * 0.75);
  background:
    linear-gradient(180deg, rgba(8, 10, 14, 0.5) 0%, rgba(8, 10, 14, 0) 16%),
    radial-gradient(ellipse 92% 100% at 0% 100%, rgba(8, 10, 14, 0.96) 0%, rgba(8, 10, 14, 0.92) 30%, rgba(8, 10, 14, 0.8) 46%, rgba(8, 10, 14, 0.5) 58%, rgba(8, 10, 14, 0.2) 70%, rgba(8, 10, 14, 0) 82%),
    linear-gradient(0deg, rgba(8, 10, 14, 0.82) 0%, rgba(8, 10, 14, 0.5) 18%, rgba(8, 10, 14, 0.14) 36%, rgba(8, 10, 14, 0) 50%);
}

/* Narrow screens: the words span the width below the temple, so the night
   rises from the foot of the frame, holds under the words, and lets go
   before the roofline so the temple keeps its light. */
@media (max-width: 900px) {
  .shade {
    background:
      linear-gradient(180deg, rgba(8, 10, 14, 0.5) 0%, rgba(8, 10, 14, 0) 16%),
      radial-gradient(ellipse 110% 60% at 0% 100%, rgba(8, 10, 14, 0.6) 0%, rgba(8, 10, 14, 0.3) 45%, rgba(8, 10, 14, 0) 80%),
      linear-gradient(0deg, rgba(8, 10, 14, 0.94) 0%, rgba(8, 10, 14, 0.9) 24%, rgba(8, 10, 14, 0.82) 36%, rgba(8, 10, 14, 0.5) 45%, rgba(8, 10, 14, 0.16) 53%, rgba(8, 10, 14, 0) 60%);
  }
}

/* A short frame (a zoomed page, a small laptop, the smallest phones): the
   words fill most of it and climb onto the lit temple, so the night rises
   from the foot of the frame to just above where they begin. */
@media (max-width: 900px) and (max-height: 620px), (max-width: 359px) {
  .shade {
    background:
      linear-gradient(180deg, rgba(8, 10, 14, 0.5) 0%, rgba(8, 10, 14, 0) 16%),
      linear-gradient(0deg, rgba(8, 10, 14, 0.94) 0%, rgba(8, 10, 14, 0.86) calc(100% - var(--copy-top, 50%)), rgba(8, 10, 14, 0.5) calc(100% - var(--copy-top, 50%) + 56px), rgba(8, 10, 14, 0) calc(100% - var(--copy-top, 50%) + 130px));
  }
}

/* Short and wide (a phone on its side): the words take the left of the frame,
   so the night stops just past where they end and the temple keeps its light. */
@media (max-width: 900px) and (max-height: 620px) and (min-aspect-ratio: 1/1) {
  .shade {
    background:
      linear-gradient(180deg, rgba(8, 10, 14, 0.5) 0%, rgba(8, 10, 14, 0) 16%),
      linear-gradient(90deg, rgba(8, 10, 14, 0.92) 0%, rgba(8, 10, 14, 0.86) var(--copy-right, 60%), rgba(8, 10, 14, 0.42) calc(var(--copy-right, 60%) + 80px), rgba(8, 10, 14, 0) calc(var(--copy-right, 60%) + 190px));
  }
}

/* No room for the cue under the words on a short frame. */
@media (max-height: 700px) {
  .climb-cue {
    display: none;
  }
}

/* Twenty-four centuries: the caption in the sky while the years pass. */
.lapse-caption {
  position: absolute;
  z-index: 3;
  top: clamp(96px, 16vh, 150px);
  left: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin: 0;
  transform: translate(-50%, 8px);
  opacity: 0;
  pointer-events: none;
  text-align: center;
  white-space: nowrap;
  /* How much night the sky under the words needs (0..1), measured on the
     playing file: all of it over the white dawn, none at blue hour. */
  --sky: 1;
  /* A fine night on the glyphs themselves, darker while the sky is white. */
  text-shadow:
    0 0 1px rgba(8, 10, 14, calc(0.5 + var(--sky) * 0.45)),
    0 1px 2px rgba(8, 10, 14, calc(0.45 + var(--sky) * 0.4)),
    0 0 5px rgba(8, 10, 14, calc(0.22 + var(--sky) * 0.58)),
    0 0 14px rgba(8, 10, 14, calc(0.18 + var(--sky) * 0.47)),
    0 0 34px rgba(8, 10, 14, calc(0.14 + var(--sky) * 0.34));
  transition: opacity 0.6s ease, transform 0.8s cubic-bezier(0.22, 1, 0.36, 1);
}

.lapse-caption.on {
  opacity: 1;
  transform: translate(-50%, 0);
}

/* And a breath of dusk over the sky around them, far wider than the words
   and with no edge anywhere, only as strong as the sky is bright: it is gone
   by the time the footage reaches blue hour. */
.lapse-caption::before {
  content: '';
  position: absolute;
  inset: -150px -30vw;
  z-index: -1;
  opacity: var(--sky);
  transition: opacity 0.3s linear;
  background: radial-gradient(
    closest-side,
    rgba(8, 10, 14, 0.54) 0%,
    rgba(8, 10, 14, 0.5) 14%,
    rgba(8, 10, 14, 0.41) 28%,
    rgba(8, 10, 14, 0.29) 44%,
    rgba(8, 10, 14, 0.17) 60%,
    rgba(8, 10, 14, 0.08) 76%,
    rgba(8, 10, 14, 0.025) 90%,
    rgba(8, 10, 14, 0) 100%
  );
}

.lapse-title {
  font-family: var(--p-font-inscription);
  font-size: var(--t-sm);
  font-weight: 600;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--p-gold);
}

.lapse-beats {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  white-space: normal;
  max-width: min(540px, 84vw);
}

.lapse-beat {
  font-family: var(--p-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(15px, 1.35vw, 19px);
  line-height: 1.3;
  color: #f2ede4;
  opacity: 0;
  transform: translateY(6px);
  transition: opacity 0.5s ease, transform 0.6s cubic-bezier(0.22, 1, 0.36, 1);
}

.lapse-beat.on {
  opacity: 1;
  transform: none;
}

.lapse-year {
  font-family: var(--p-font-display);
  font-size: clamp(34px, 4.4vw, 60px);
  font-weight: 500;
  line-height: 1;
  font-variant-numeric: tabular-nums lining-nums;
  color: #f6f1e8;
}

.copy {
  position: relative;
  z-index: 3;
  isolation: isolate;
  margin: 0 clamp(20px, 5vw, 72px) calc(clamp(36px, 8vh, 88px) + var(--bars));
  max-width: 640px;
  opacity: var(--d-copy);
  transform: translate3d(0, calc(var(--descent) * -36vh), 0);
}

/* The night belongs to the words, not to the screen: wherever the frame is
   short (a zoomed page, a small laptop, a small phone) and the words climb
   onto the lit temple, a pool of dusk goes with them. */
.copy::before {
  content: '';
  position: absolute;
  inset: -42% -34% -30% -34%;
  z-index: -1;
  pointer-events: none;
  /* The ellipse stays inside its box, so the dusk has no edge anywhere. */
  background: radial-gradient(ellipse 50% 50% at 50% 50%, rgba(8, 10, 14, 0.8) 0%, rgba(8, 10, 14, 0.66) 38%, rgba(8, 10, 14, 0.34) 66%, rgba(8, 10, 14, 0.1) 86%, rgba(8, 10, 14, 0) 100%);
}

.hero-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

/* Faded out on the way up: the words take no clicks. */
.descended .copy,
.descended .floor {
  pointer-events: none;
}

.floor {
  opacity: var(--d-copy);
}

/* The words arrive one line at a time. */
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.title {
  display: flex;
  flex-direction: column;
  margin: 0 0 18px;
  font-family: var(--p-font-display);
  font-weight: 500;
  font-size: clamp(40px, 4.8vw, 72px);
  line-height: 1.02;
  letter-spacing: -0.015em;
  color: #f6f1e8;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6), 0 2px 24px rgba(0, 0, 0, 0.55), 0 0 60px rgba(0, 0, 0, 0.35);
}

.title .line {
  position: relative;
  align-self: flex-start;
  animation: rise 1s cubic-bezier(0.22, 1, 0.36, 1) both;
}

/* A breath of dusk behind the gold word, where the first line reaches out
   over the brighter sky. */
@media (min-width: 901px) {
  .title .line:first-child::before {
    content: '';
    position: absolute;
    inset: -28% -14% -30% 30%;
    z-index: -1;
    pointer-events: none;
    background: radial-gradient(ellipse 50% 50% at 50% 50%, rgba(8, 10, 14, 0.62) 0%, rgba(8, 10, 14, 0.46) 45%, rgba(8, 10, 14, 0.16) 78%, rgba(8, 10, 14, 0) 100%);
  }
}

.title .line:nth-child(2) {
  animation-delay: 0.22s;
}

.title em {
  font-style: italic;
  color: #f6c77f;
  padding-bottom: 0.06em;
}

.lede {
  max-width: 34ch;
  text-wrap: pretty;
  margin: 0 0 28px;
  font-family: var(--p-font-serif);
  font-size: clamp(16px, 1.35vw, 19px);
  line-height: 1.55;
  color: var(--p-ink-2);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6), 0 1px 18px rgba(0, 0, 0, 0.5);
  animation: rise 1s cubic-bezier(0.22, 1, 0.36, 1) 0.42s both;
}

/* The gold button leads; the era and the pause are quiet beside it. */
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 26px;
  animation: rise 1s cubic-bezier(0.22, 1, 0.36, 1) 0.6s both;
}

.cta {
  min-height: 54px;
  padding-inline: 26px;
  font-size: var(--t-md);
  transition: background 0.25s ease, transform 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.cta:active {
  transform: translateY(1px) scale(0.99);
}

.cta-arrow {
  transition: transform 0.25s ease;
}

.cta:hover .cta-arrow {
  transform: translateX(4px);
}

.era {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.era-caption {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-2);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}

.era-options {
  display: inline-flex;
  gap: 18px;
}

/* The two years as inscriptions: the one in force carries a gold rule. */
.era-option {
  min-height: 40px;
  padding: 6px 0;
  border: none;
  border-bottom: 1px solid transparent;
  background: transparent;
  color: var(--p-ink-3);
  font-family: var(--p-font-inscription);
  font-size: var(--t-sm);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
  cursor: pointer;
  transition: color 0.2s, border-color 0.3s;
}

.era-option.active {
  color: var(--p-gold);
  border-bottom-color: var(--p-gold);
}

.era-option:not(.active):hover {
  color: var(--p-ink);
}

.motion {
  color: var(--p-ink-2);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}

.motion[aria-pressed='true'] {
  color: var(--p-gold);
}

/* A quiet cue at the foot of the frame: the steps go on up. */
.climb-cue {
  position: absolute;
  z-index: 3;
  left: 50%;
  bottom: calc(18px + var(--bars));
  transform: translateX(-50%);
  opacity: calc(var(--d-copy) * 0.9);
  pointer-events: none;
}

.climb-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  font-family: var(--p-font-inscription);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: var(--p-ink-3);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
  animation: rise 1s cubic-bezier(0.22, 1, 0.36, 1) 1.4s both;
}

.climb-line {
  display: block;
  width: 1px;
  height: 34px;
  background: linear-gradient(180deg, var(--p-gold), rgba(240, 182, 96, 0));
  transform-origin: top;
  animation: climb-line 2.4s cubic-bezier(0.22, 1, 0.36, 1) 2s infinite;
}

.motion-off .climb-line {
  animation: none;
  transform: scaleY(1);
  opacity: 0.6;
}

@keyframes climb-line {
  0% { transform: scaleY(0); opacity: 1; }
  60% { transform: scaleY(1); opacity: 1; }
  100% { transform: scaleY(1); opacity: 0; }
}

.floor {
  position: absolute;
  z-index: 3;
  right: clamp(20px, 5vw, 72px);
  bottom: calc(clamp(36px, 8vh, 88px) + var(--bars));
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  color: var(--p-ink);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}

.floor-letter {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: var(--p-radius-coin);
  border: 1px solid var(--p-gold);
  font-family: var(--p-font-display);
  font-size: 17px;
  color: var(--p-gold);
}

/* ---- The top of the climb ---- */
.arrival {
  position: absolute;
  inset: 0;
  z-index: 4;
  pointer-events: none;
  color: var(--p-ink);
}

/* The frame gives way to night at its foot, so the page below begins where
   the steps end, not at an edge. The Way runs on over it. */
.arrival::after {
  content: '';
  position: absolute;
  inset: auto 0 0 0;
  z-index: 1;
  height: 22%;
  pointer-events: none;
  opacity: var(--d-way);
  background: linear-gradient(0deg, #0b0e13 0%, rgba(11, 14, 19, 0.84) 26%, rgba(11, 14, 19, 0.36) 62%, rgba(11, 14, 19, 0) 100%);
}

.end-plate {
  position: absolute;
  inset: 0;
  opacity: var(--d-end);
  background: #0b0e13;
}

.end-layer,
.end-layer picture,
.end-layer img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.end-layer {
  opacity: 0;
  transition: opacity 1.4s cubic-bezier(0.22, 1, 0.36, 1);
}

.end-layer.active {
  opacity: 1;
}

/* The end frame settles into place as it arrives. */
.end-layer img {
  transform: scale(calc(1.05 - var(--d-end) * 0.05));
  transform-origin: 60% 50%;
}

.mode-scrub .end-layer img {
  transform: none;
}

.descent.portrait:not(.still) .end-layer img {
  transform-origin: 50% 45%;
  transform: translate3d(0, calc(var(--d-lift) * var(--lift)), 0);
}

.descent.portrait.mode-dissolve .end-layer img {
  transform:
    translate3d(0, calc(var(--d-lift) * var(--lift)), 0)
    scale(calc(1.05 - var(--d-end) * 0.05));
}

/* Night gathers where the words of the Way sit: under the roof of the gate
   (the top of the frame, where the heading stands, well clear of the temple's
   light), in the gate's shadow at the left, and at the foot of the steps. */
.way-shade {
  position: absolute;
  inset: 0;
  opacity: var(--d-way-shade);
  background:
    linear-gradient(180deg, rgba(8, 10, 14, 0.86) 0%, rgba(8, 10, 14, 0.78) 22%, rgba(8, 10, 14, 0.62) 35%, rgba(8, 10, 14, 0.28) 45%, rgba(8, 10, 14, 0) 55%),
    radial-gradient(ellipse 72% 82% at 0% 8%, rgba(8, 10, 14, 0.8) 0%, rgba(8, 10, 14, 0.62) 30%, rgba(8, 10, 14, 0.28) 56%, rgba(8, 10, 14, 0) 82%),
    linear-gradient(0deg, rgba(8, 10, 14, 0.66) 0%, rgba(8, 10, 14, 0.26) 22%, rgba(8, 10, 14, 0) 42%);
}

.way {
  position: absolute;
  inset: 0;
  z-index: 2;
  opacity: var(--d-way);
}

.way-head {
  position: absolute;
  top: clamp(100px, 15vh, 150px);
  left: clamp(20px, 5vw, 72px);
  max-width: min(420px, 34vw);
  isolation: isolate;
  transform: translate3d(0, calc((1 - var(--d-way)) * 18px), 0);
}


.way-head .p-eyebrow {
  margin: 0 0 12px;
}

.way-head h2 {
  margin: 0 0 12px;
  font-family: var(--p-font-display);
  font-weight: 500;
  font-size: clamp(34px, 3.6vw, 54px);
  line-height: 1.04;
  letter-spacing: -0.01em;
  color: #f6f1e8;
  text-wrap: balance;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6), 0 2px 24px rgba(0, 0, 0, 0.5);
}

.way-lede {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--p-ink-2);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.7), 0 1px 18px rgba(0, 0, 0, 0.6);
}

/* The path: a thread of gold drawn up the steps as the visitor arrives. */
.way-path {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.way-path path {
  fill: none;
  stroke-linecap: round;
  stroke-dasharray: 1 1;
  stroke-dashoffset: calc(1 - var(--d-draw));
}

.way-line {
  stroke: var(--p-gold);
  stroke-width: 1.6;
}

.way-glow {
  stroke: rgba(240, 182, 96, 0.28);
  stroke-width: 7;
  filter: blur(3px);
}

.stations {
  list-style: none;
  margin: 0;
  padding: 0;
}

/* Each station arrives in turn as the path reaches it. */
.station {
  --d-st: clamp(0, calc((var(--descent) - 0.74 - var(--i) * 0.045) / 0.06), 1);

  opacity: var(--d-st);
}

.station-coin {
  display: grid;
  place-items: center;
  flex: none;
  width: 40px;
  height: 40px;
  border-radius: var(--p-radius-coin);
  border: 1px solid var(--p-gold);
  background: rgba(11, 14, 19, 0.82);
  box-shadow: 0 0 0 4px rgba(240, 182, 96, 0.12), 0 0 24px rgba(240, 182, 96, 0.35);
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  line-height: 1;
  color: var(--p-gold);
}

.station-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.station-name {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-gold);
}

.station-gloss {
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.45;
  color: var(--p-ink);
}

/* On a wide frame each station stands on the path, its words on a small
   night plaque beside it. */
.way-path ~ .stations .station {
  position: absolute;
  left: var(--x);
  top: var(--y);
  display: flex;
  align-items: center;
  gap: 14px;
  width: 0;
  height: 0;
}

.way-path ~ .stations .station-coin {
  position: absolute;
  left: -20px;
  top: -20px;
  transform: scale(calc(0.6 + var(--d-st) * 0.4));
}

.way-path ~ .stations .station-text {
  position: absolute;
  top: 0;
  width: max-content;
  max-width: min(340px, max(24vw, 300px));
  padding: 7px 12px 8px;
  background: linear-gradient(90deg, rgba(8, 10, 14, 0.76), rgba(8, 10, 14, 0.56));
  backdrop-filter: blur(4px);
  transform: translateY(calc(-50% + var(--dy, 0px)));
}

.way-path ~ .stations .side-right .station-text {
  left: 32px;
}

.way-path ~ .stations .side-left .station-text {
  right: 32px;
  text-align: right;
  background: linear-gradient(270deg, rgba(8, 10, 14, 0.72), rgba(8, 10, 14, 0.5));
}

/* A tall or narrow frame: the Way stands upright under the temple, climbing
   from the first station at the foot to the fifth at the top. The end frame
   stays whole, exactly where the climb left it; night rises from the foot of
   the frame under the stations instead. */
.layout-list .end-plate {
  background: #0b0e13;
}

.layout-list .way-shade {
  background:
    linear-gradient(180deg, rgba(8, 10, 14, 0.55) 0%, rgba(8, 10, 14, 0) 20%),
    linear-gradient(0deg, #0b0e13 0%, rgba(11, 14, 19, 0.95) 34%, rgba(11, 14, 19, 0.8) 45%, rgba(11, 14, 19, 0.34) 57%, rgba(11, 14, 19, 0) 67%);
}

.layout-list .way {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 0 clamp(20px, 6vw, 56px) calc(28px + var(--bars));
}

.layout-list .way-head {
  position: static;
  max-width: 560px;
  margin-bottom: 18px;
}

.layout-list .way-head h2 {
  font-size: clamp(28px, 7vw, 40px);
}

.layout-list .way-lede {
  display: none;
}

.layout-list .stations {
  position: relative;
  display: flex;
  flex-direction: column-reverse;
  gap: 14px;
  max-width: 560px;
}

/* The upright path: from the first coin up past the last, into the temple. */
.layout-list .stations::before {
  content: '';
  position: absolute;
  left: 17.5px;
  top: -10px;
  bottom: 18px;
  width: 1px;
  background: linear-gradient(0deg, var(--p-gold) 0%, var(--p-gold) 70%, rgba(240, 182, 96, 0) 100%);
  transform-origin: bottom;
  transform: scaleY(var(--d-draw));
}

.layout-list .station {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.layout-list .station-coin {
  width: 36px;
  height: 36px;
  font-size: var(--t-md);
}

.layout-list .station-text {
  padding-top: 2px;
}

.layout-list .station-gloss {
  font-size: 13px;
  line-height: 1.4;
  color: var(--p-ink-2);
}

/* The anchor for #how while pinned: where the climb is complete. */
.way-anchor {
  position: absolute;
  left: 0;
  bottom: calc(100vh - 88px);
  width: 1px;
  height: 1px;
  scroll-margin-top: 88px;
  pointer-events: none;
}

/* ---- Still: reduced motion, or a phone on its side ----
   Nothing is pinned or driven: the hero is a first screen as it was, and the
   top of the climb with the Way is a section of its own after it. */
.descent.still {
  --descent: 0;
  --d-copy: 1;
  --d-push: 0;
  --d-end: 1;
  --d-way: 1;
  --d-way-shade: 1;
  --d-draw: 1;
  --d-sky: 1;

  height: auto;
}

.still .stage {
  position: relative;
  height: auto;
  overflow: visible;
}

.still .cine {
  position: relative;
  inset: auto;
  min-height: 100vh;
  min-height: 100dvh;
}

.still .arrival {
  position: relative;
  inset: auto;
  min-height: 100vh;
  min-height: 100dvh;
  overflow: hidden;
}

/* Still, the two plates meet through night: the hero's foot and the top of
   the steps each fade into it. */
.still .cine::after,
.still .arrival::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  height: 18%;
  pointer-events: none;
}

.still .cine::after {
  bottom: 0;
  z-index: 2;
  background: linear-gradient(0deg, #0b0e13 0%, rgba(11, 14, 19, 0.62) 42%, rgba(11, 14, 19, 0) 100%);
}

.still .arrival::before {
  top: 0;
  z-index: 1;
  background: linear-gradient(180deg, #0b0e13 0%, rgba(11, 14, 19, 0.62) 42%, rgba(11, 14, 19, 0) 100%);
}

.still .station {
  --d-st: 1;
}

.still .climb-cue {
  display: none;
}

.still .end-layer img {
  transform: none;
}

.still.layout-list .arrival {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  min-height: 0;
}

.still.layout-list .end-plate {
  position: relative;
  inset: auto;
  height: min(70vh, 110vw);
}

.still.layout-list .end-layer {
  height: 100%;
}

.still.layout-list .end-layer img {
  object-position: 50% 15%;
}

.still.layout-list .way {
  position: relative;
  inset: auto;
  margin-top: -10vh;
  padding-bottom: 48px;
}

/* Phones: a shorter climb; the Way upright. */
@media (max-width: 699px) {
  .descent {
    height: 160vh;
  }

  .descent.still {
    height: auto;
  }
}

/* Phones: "Sit on the steps. Listen." is about 8.4em wide; shrink it to fit
   between the 20px gutters so the headline stays at two lines. */
@media (max-width: 420px) {
  .title {
    font-size: clamp(28px, calc((100vw - 40px) / 8.8), 40px);
  }
}

@media (max-width: 640px) {
  /* The words sit lower so the temple stands above them. */
  .title {
    margin-bottom: 14px;
  }

  .lede {
    margin-bottom: 20px;
  }

  .copy {
    margin-bottom: calc(clamp(28px, 6vh, 64px) + var(--bars));
  }

  .cta {
    width: 100%;
  }

  .motion-text {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

  .actions {
    gap: 10px 18px;
  }

  .era {
    flex: 1;
  }

  .climb-cue {
    display: none;
  }
}

/* Phones in landscape: tighten so the hero still fits the screen. */
@media (max-height: 480px) and (orientation: landscape) {
  .cine {
    padding-top: 76px;
  }

  .copy {
    margin-bottom: 20px;
  }

  .title {
    font-size: 34px;
    margin-bottom: 12px;
  }

  .lede {
    margin-bottom: 16px;
  }
}

/* Small screens: no room for the badge, but the live region still speaks. */
@media (max-width: 900px) {
  .floor {
    width: 1px;
    height: 1px;
    margin: -1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
}

/* Chinese stands upright, in its own serif, without the Latin tracking. */
:lang(zh) .title em,
:lang(zh) .era-caption,
:lang(zh) .lapse-beat {
  font-style: normal;
}

:lang(zh) .era-option,
:lang(zh) .climb-inner,
:lang(zh) .lapse-title,
:lang(zh) .station-name {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

/* Six Chinese characters carry no capitals or tracking to hold them up over
   the white dawn: a step larger, with room between them. */
:lang(zh) .lapse-title {
  font-size: var(--t-md);
  letter-spacing: 0.24em;
}

@media (prefers-reduced-motion: reduce) {
  .layer,
  .end-layer {
    transition-duration: 0.6s;
  }

  .climb-line {
    animation: none;
  }
}
</style>
