<template>
  <section ref="root" class="cine" :class="[`era-${era}`, { drifting: stillDrift }]" :aria-label="scenes[era].label">
    <div class="media" aria-hidden="true">
      <div
        v-for="(scene, key) in scenes"
        :key="key"
        class="layer"
        :class="{ active: shown === key, rolling: playing[key], rested: rested[key] }"
      >
        <!-- Below 700px the plate is a 3:4 crop centred on the temple. Wider, cover
             crops the 2560x1086 still, so on a taller screen it is drawn 236vh wide. -->
        <picture>
          <source media="(max-width: 699px)" :srcset="scene.portrait1280" />
          <img
            :src="scene.still2560"
            :srcset="`${scene.still1280} 1280w, ${scene.still2560} 2560w`"
            sizes="(max-aspect-ratio: 2560/1086) 236vh, 100vw"
            alt=""
            :fetchpriority="key === 'ancient' ? 'high' : 'low'"
            :loading="key === 'ancient' ? 'eager' : 'lazy'"
            decoding="async"
          />
        </picture>
        <video
          v-if="videoAllowed"
          :ref="(el) => (videos[key] = el)"
          muted
          playsinline
          preload="metadata"
          :src="videoSrc(scene)"
          @seeked="onFrame(key)"
          @playing="onFrame(key)"
          @ended="onEnded(key)"
        ></video>
      </div>
    </div>

    <SwarmCanvas
      v-if="!motionPaused"
      class="swarm"
      :era="era"
      :intensity="speaker ? 1 : 0"
      :region="sky"
      :avoid="avoid"
    />

    <!-- The grade belongs to the plate: night pools at the left and the foot of
         the frame where the words sit, and the temple keeps its light. -->
    <div class="shade" aria-hidden="true"></div>

    <div ref="copy" class="copy">
      <h1 class="title">
        <span class="line">{{ $t('parthenon.heroLine1') }} <em>{{ $t('parthenon.heroLine2') }}</em></span>
        <span class="line">{{ $t('parthenon.heroLine3') }}</span>
      </h1>
      <p class="lede">{{ $t('parthenon.heroLede') }}</p>
      <div class="actions">
        <button type="button" class="p-button cta" @click="$emit('begin')">
          {{ $t('parthenon.heroCta') }}
          <span class="cta-arrow" aria-hidden="true">→</span>
        </button>

        <div class="era" role="group" :aria-label="$t('parthenon.eraLabel')">
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
            >{{ scene.year }}</button>
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

    <!-- Always in the DOM so the first speaker is announced too. -->
    <p class="floor" aria-live="polite" aria-atomic="true">
      <template v-if="speaker">
        <span class="floor-letter" aria-hidden="true">{{ speaker.letter }}</span>
        {{ $t('parthenon.hasTheFloor', { name: speaker.name }) }}
      </template>
    </p>
  </section>
</template>

<script setup>
import { ref, reactive, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import SwarmCanvas from './SwarmCanvas.vue'

const props = defineProps({
  era: { type: String, default: 'ancient' }, // 'ancient' | 'now'
  speaker: { type: Object, default: null } // { name, letter } when someone has the floor
})
defineEmits(['update:era', 'begin'])

const { t, te } = useI18n()
// English until the key reaches every locale.
const label = (key, fallback) => (te(key) ? t(key) : fallback)

// Same camera, 2,425 years apart: the Propylaea at dawn in 399 BC, and today.
const scenes = {
  ancient: {
    year: '399 BC',
    label: 'The Parthenon seen from the steps of the Propylaea at sunrise in 399 BC',
    still1280: '/media/hero/acropolis-399bc-1280.jpg',
    still2560: '/media/hero/acropolis-399bc-2560.jpg',
    portrait1280: '/media/hero/acropolis-399bc-portrait-1280.jpg',
    video1280: '/media/hero/acropolis-399bc-1280.mp4',
    video1920: '/media/hero/acropolis-399bc-1920.mp4'
  },
  now: {
    year: '2026',
    label: 'The same view today: the floodlit Parthenon at night with a restoration crane',
    still1280: '/media/hero/acropolis-2026-1280.jpg',
    still2560: '/media/hero/acropolis-2026-2560.jpg',
    portrait1280: '/media/hero/acropolis-2026-portrait-1280.jpg',
    video1280: '/media/hero/acropolis-2026-1280.mp4',
    video1920: '/media/hero/acropolis-2026-1920.mp4'
  }
}

// Where things are on the plates, as fractions of the image: the roofline
// (the tip of Athena's spear) and the Propylaea columns either side. The
// portrait is cut from the foot of the wide still with less sky, so the
// temple stands higher in the frame and clear of the words on a phone.
const PLATE = {
  landscape: { w: 2560, h: 1086, roof: 0.46, colLeft: 0.28, colRight: 0.72 },
  portrait: { w: 960, h: 1280, roof: 0.36, colLeft: -1, colRight: 2 }
}

const root = ref(null)
const copy = ref(null)
const videos = {}
// rolling: the video has a decoded frame worth showing over the still.
const playing = reactive({ ancient: false, now: false })
// rested: the climb is over; the last frame drifts on slowly.
const rested = reactive({ ancient: false, now: false })
// The layer on screen. It follows era once the new video shows the same moment.
const shown = ref(props.era)

// Video only when motion is welcome and data is not being saved. Below 700px
// the plate is a portrait crop the landscape video cannot match, so a phone
// gets the still with a slow drift instead.
const reduceMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const saveData = typeof navigator !== 'undefined' && navigator.connection?.saveData
const phoneQuery = typeof window !== 'undefined' ? window.matchMedia('(max-width: 699px)') : null
const phone = ref(phoneQuery ? phoneQuery.matches : false)
const motionAllowed = !reduceMotion
const videoAllowed = motionAllowed && !saveData && !phone.value

// Pick the video by how wide cover really draws it (the 2560x1086 frame is
// 236vh wide on a tall screen), in device pixels.
const drawnWidth = typeof window !== 'undefined'
  ? Math.max(window.innerWidth, window.innerHeight * (2560 / 1086)) * Math.min(window.devicePixelRatio || 1, 2)
  : 0
const small = drawnWidth <= 1600

const videoSrc = (scene) => (small ? scene.video1280 : scene.video1920)

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
  stillDrift.value = motionAllowed && !videoAllowed && !motionPaused.value
}
syncDrift()

// The sky the flock may use and the block of words it keeps out of, both
// measured from how cover really places the plate in this frame.
const sky = ref({ top: 0.05, bottom: 0.44, left: 0.2, right: 0.9 })
const avoid = ref(null)
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

const measure = () => {
  const el = root.value
  if (!el) return
  const W = el.clientWidth
  const H = el.clientHeight
  if (W < 2 || H < 2) return
  const portrait = phone.value
  const plate = portrait ? PLATE.portrait : PLATE.landscape
  const tall = W / H < 1
  // Must match .layer img / video object-position below.
  const px = portrait ? 0.5 : tall ? 0.52 : 0.22
  const py = portrait ? 0.6 : tall ? 0.6 : 0.58
  const scale = Math.max(W / plate.w, H / plate.h)
  const dw = plate.w * scale
  const dh = plate.h * scale
  const ox = (dw - W) * px
  const oy = (dh - H) * py
  sky.value = {
    top: 0.05,
    bottom: clamp((plate.roof * dh - oy) / H - 0.03, 0.24, 0.6),
    left: clamp((plate.colLeft * dw - ox) / W + 0.02, 0.04, 0.4),
    right: clamp((plate.colRight * dw - ox) / W - 0.02, 0.6, 0.96)
  }
  const c = copy.value
  if (c) {
    const r = el.getBoundingClientRect()
    const b = c.getBoundingClientRect()
    avoid.value = { x: b.left - r.left, y: b.top - r.top, w: b.width, h: b.height }
  }
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

const toggleMotion = () => {
  motionPaused.value = !motionPaused.value
  try {
    if (motionPaused.value) localStorage.setItem(MOTION_KEY, 'paused')
    else localStorage.removeItem(MOTION_KEY)
  } catch {
    // storage blocked; the choice lasts for this visit
  }
  syncDrift()
  const video = videos[props.era]
  if (!video) return
  if (motionPaused.value) video.pause()
  else if (inView && !video.ended) resume(video)
}

let heroObserver = null
let sizeObserver = null
let inView = true

const onPhoneChange = (e) => {
  phone.value = e.matches
  syncDrift()
  measure()
}

onMounted(() => {
  measure()
  sizeObserver = new ResizeObserver(measure)
  sizeObserver.observe(root.value)
  if (copy.value) sizeObserver.observe(copy.value)
  phoneQuery?.addEventListener('change', onPhoneChange)

  if (!videoAllowed) return
  if (!motionPaused.value) play(props.era)
  heroObserver = new IntersectionObserver(([entry]) => {
    inView = entry.isIntersecting
    const video = videos[props.era]
    if (!video || video.ended) return
    // A climb cued while the hero was off screen starts when it comes back.
    if (!inView) video.pause()
    else if (!motionPaused.value) resume(video)
  }, { threshold: 0.2 })
  heroObserver.observe(root.value)
})

onBeforeUnmount(() => {
  heroObserver?.disconnect()
  sizeObserver?.disconnect()
  phoneQuery?.removeEventListener('change', onPhoneChange)
})

// Switching eras mid-climb keeps the camera where it is; after the climb, the
// new era replays its own entrance. Off screen or paused, the new era is only
// lined up, so nothing plays unseen.
let swap = 0
watch(() => props.era, async (next, previous) => {
  const turn = ++swap
  if (!videoAllowed) {
    shown.value = next
    return
  }
  const old = videos[previous]
  const live = inView && !motionPaused.value
  if (next === shown.value) {
    // Switched back before the crossfade began: that layer never left.
    old?.pause()
    if (live && videos[next] && !videos[next].ended) resume(videos[next])
    return
  }
  const from = old && !old.ended ? old.currentTime : 0
  if (live) play(next, from)
  else cue(next, from)
  // On screen, hold the old layer until the new video shows the same moment.
  if (inView && (live || from > 0)) await whenRolling(next)
  if (turn !== swap) return
  shown.value = next
  old?.pause()
})
</script>

<style scoped>
/* The copy sits in flow at the bottom, so a tall copy block (a phone in
   landscape) grows the hero instead of running up under the top bar. */
.cine {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  min-height: 100dvh;
  padding-top: 88px;
  overflow: hidden;
  isolation: isolate;
  background: #0b0e13;
  color: var(--p-ink);
}

.media,
.layer,
.layer picture,
.layer img,
.layer video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.layer {
  opacity: 0;
  transition: opacity 1.4s cubic-bezier(0.22, 1, 0.36, 1);
}

.layer.active {
  opacity: 1;
}

/* The plate sits so the temple stands clear of the words: right of centre on
   a landscape screen, centred on a tall one. measure() mirrors these numbers. */
.layer img,
.layer video {
  object-fit: cover;
  object-position: 22% 58%;
}

@media (max-aspect-ratio: 1/1) {
  .layer img,
  .layer video {
    object-position: 52% 60%;
  }
}

@media (max-width: 699px) {
  .layer img,
  .layer video {
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

/* After the climb, the camera keeps breathing for forty seconds. */
@keyframes drift {
  from { transform: scale(1); }
  to { transform: scale(1.06); }
}

.layer.rested video {
  transform-origin: 60% 45%;
  animation: drift 40s ease-out forwards;
}

/* A phone gets the still: the same slow drift instead of the climb. */
.drifting .layer.active img {
  transform-origin: 50% 45%;
  animation: drift 40s ease-out forwards;
}

.swarm {
  z-index: 1;
}

/* The grade: a wide left-bottom vignette, a seat under the words, a breath of
   night under the top bar. Nothing sits behind the type but the plate. */
.shade {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
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

.copy {
  position: relative;
  z-index: 3;
  margin: 0 clamp(20px, 5vw, 72px) clamp(36px, 8vh, 88px);
  max-width: 640px;
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
  animation: rise 1s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.title .line:nth-child(2) {
  animation-delay: 0.22s;
}

.title em {
  font-style: italic;
  color: var(--p-gold);
  padding-bottom: 0.06em;
}

.lede {
  max-width: 34ch;
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

.floor {
  position: absolute;
  z-index: 3;
  right: clamp(20px, 5vw, 72px);
  bottom: clamp(36px, 8vh, 88px);
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
    margin-bottom: clamp(28px, 6vh, 64px);
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
</style>
