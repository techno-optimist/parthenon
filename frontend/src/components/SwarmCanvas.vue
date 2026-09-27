<template>
  <canvas ref="canvas" class="swarm-canvas" aria-hidden="true"></canvas>
</template>

<script setup>
// Runs the sky over the hero (parthenon/swarm.js): the starlings of 399 BC,
// the embers of 2026. The flock parts around the pointer, gathers when a
// speaker takes the steps and keeps out of the headline. The loop stops off
// screen, in a hidden tab and while paused, and resumes where it left off;
// under reduced motion it draws one still frame.
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { createSwarm } from '../parthenon/swarm.js'

const props = defineProps({
  era: { type: String, default: 'ancient' }, // 'ancient' | 'now'
  intensity: { type: Number, default: 0 }, // 0 idle .. 1 a speaker has the floor
  // The sky, as fractions of the canvas: { top, bottom, left, right }
  region: { type: Object, default: null },
  // A rectangle in canvas pixels the flock stays out of: { x, y, w, h }
  avoid: { type: Object, default: null },
  // Hold the sky still (the visitor paused motion); the frame stays on screen.
  paused: { type: Boolean, default: false }
})

const canvas = ref(null)

// The hero keeps this canvas in its sticky stage for the whole descent and
// holds the sky itself (:paused) once the descent is nearly over or the stage
// is off screen. This observer is the backstop for any host: when the stage
// finally scrolls up under Home.vue's fixed 68px .topbar, the strip behind the
// bar does not count as sky. The extra pixel matters because a canvas whose
// bottom rests exactly on the bar's edge still reports isIntersecting.
const TOPBAR = 68
// Birds a pixel wide need no more than this; it keeps the fill cheap on 3x phones.
const MAX_DPR = 1.5
const DEV = import.meta.env.DEV

let ctx = null
let swarm = null
let dpr = 1
let raf = 0
let last = 0
let running = false
let visible = true
let reduced = false
let resizeObserver = null
let resizeRaf = 0
let intersectionObserver = null
let reduceQuery = null
let dprQuery = null
let host = null
let settleTimer = 0
// Dev only: running averages of the frame's cost, for checks.
const cost = { step: 0, draw: 0, frames: 0 }

const frame = (now) => {
  if (!running) return
  const dt = Math.min(34, last ? now - last : 16.67)
  last = now
  if (DEV) {
    const t0 = performance.now()
    swarm.step(dt, props.intensity)
    const t1 = performance.now()
    swarm.draw(ctx, props.era, dpr)
    const t2 = performance.now()
    cost.step += (t1 - t0 - cost.step) * 0.05
    cost.draw += (t2 - t1 - cost.draw) * 0.05
    cost.frames++
  } else {
    swarm.step(dt, props.intensity)
    swarm.draw(ctx, props.era, dpr)
  }
  raf = requestAnimationFrame(frame)
}

const canRun = () => !reduced && !props.paused && visible && !document.hidden && !!swarm

const start = () => {
  if (running || !canRun()) return
  running = true
  last = 0
  raf = requestAnimationFrame(frame)
}

const stop = () => {
  running = false
  cancelAnimationFrame(raf)
}

const sync = () => (canRun() ? start() : stop())

// The flock is settled when it is seeded, so a still frame is one draw.
const drawOnce = () => {
  if (swarm && ctx) swarm.draw(ctx, props.era, dpr)
}

// Held still, a new layout (the sky measured, the words moved) is flown into
// quietly for a second of sky, once the changes stop, then drawn.
const settleSoon = () => {
  clearTimeout(settleTimer)
  settleTimer = setTimeout(() => {
    settleTimer = 0
    if (running || !swarm) return
    for (let i = 0; i < 60; i++) swarm.step(16.67, props.intensity)
    drawOnce()
  }, 150)
}

const resize = () => {
  resizeRaf = 0
  const el = canvas.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const width = Math.max(1, Math.round(rect.width))
  const height = Math.max(1, Math.round(rect.height))
  dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR)
  el.width = Math.round(width * dpr)
  el.height = Math.round(height * dpr)
  if (!swarm) {
    swarm = createSwarm({ width, height, region: props.region || undefined, era: props.era })
    swarm.setAvoid(props.avoid)
  } else {
    swarm.resize(width, height)
  }
  // Resizing clears the canvas: repaint once so no blank frame shows.
  drawOnce()
  if (!running) settleSoon()
}

// Coalesce resize bursts (window drags, mobile toolbars) into one per frame.
const scheduleResize = () => {
  if (!resizeRaf) resizeRaf = requestAnimationFrame(resize)
}

// A devicePixelRatio change alone (window moved to another display) never
// reaches the ResizeObserver, so watch it and re-arm for the new ratio.
const watchDpr = () => {
  dprQuery?.removeEventListener('change', onDprChange)
  dprQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`)
  dprQuery.addEventListener('change', onDprChange)
}

const onDprChange = () => {
  watchDpr()
  scheduleResize()
}

const onPointerMove = (event) => {
  const rect = canvas.value.getBoundingClientRect()
  swarm?.setPointer(event.clientX - rect.left, event.clientY - rect.top, true)
}

const onPointerLeave = () => swarm?.setPointer(-9999, -9999, false)

// A finger lifts (or the page takes it for a scroll) without leaving the hero.
const onPointerEnd = (event) => {
  if (event.pointerType !== 'mouse') onPointerLeave()
}

const onVisibility = () => sync()

const onReduceChange = () => {
  reduced = reduceQuery.matches
  sync()
  if (!running) drawOnce()
}

onMounted(() => {
  ctx = canvas.value.getContext('2d')
  reduceQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  reduced = reduceQuery.matches
  reduceQuery.addEventListener('change', onReduceChange)

  resizeObserver = new ResizeObserver(scheduleResize)
  resizeObserver.observe(canvas.value)
  resize()
  watchDpr()

  intersectionObserver = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting
    sync()
  }, { rootMargin: `-${TOPBAR + 1}px 0px 0px 0px` })
  intersectionObserver.observe(canvas.value)

  // Listen on the hero; the canvas itself ignores the pointer so buttons work.
  host = canvas.value.parentElement
  host.addEventListener('pointermove', onPointerMove, { passive: true })
  host.addEventListener('pointerleave', onPointerLeave, { passive: true })
  host.addEventListener('pointerup', onPointerEnd, { passive: true })
  host.addEventListener('pointercancel', onPointerEnd, { passive: true })
  document.addEventListener('visibilitychange', onVisibility)

  if (DEV) {
    window.__parthenonSwarm = {
      swarm,
      stats: () => ({
        running,
        dpr,
        era: swarm?.state.era,
        birds: swarm?.state.flocks[swarm.state.era]?.n || 0,
        stepMs: +cost.step.toFixed(3),
        drawMs: +cost.draw.toFixed(3),
        frames: cost.frames
      })
    }
  }
  start()
})

onBeforeUnmount(() => {
  stop()
  cancelAnimationFrame(resizeRaf)
  clearTimeout(settleTimer)
  resizeObserver?.disconnect()
  intersectionObserver?.disconnect()
  reduceQuery?.removeEventListener('change', onReduceChange)
  dprQuery?.removeEventListener('change', onDprChange)
  host?.removeEventListener('pointermove', onPointerMove)
  host?.removeEventListener('pointerleave', onPointerLeave)
  host?.removeEventListener('pointerup', onPointerEnd)
  host?.removeEventListener('pointercancel', onPointerEnd)
  document.removeEventListener('visibilitychange', onVisibility)
  if (DEV && window.__parthenonSwarm?.swarm === swarm) delete window.__parthenonSwarm
})

watch(() => props.era, (era) => {
  if (!swarm) return
  // On screen the flocks cross-fade; held still, the new sky shows at once.
  swarm.setEra(era, !running)
  if (!running) drawOnce()
})

watch(() => props.paused, () => sync())

watch(() => props.region, (region) => {
  swarm?.setRegion(region)
  if (!running) settleSoon()
}, { deep: true })

watch(() => props.avoid, (avoid) => {
  swarm?.setAvoid(avoid)
  if (!running) settleSoon()
}, { deep: true })
</script>

<style scoped>
.swarm-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
