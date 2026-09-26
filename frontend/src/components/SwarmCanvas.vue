<template>
  <canvas ref="canvas" class="swarm-canvas" aria-hidden="true"></canvas>
</template>

<script setup>
// Runs the murmuration (parthenon/swarm.js) over the hero: parts around the
// pointer, gathers when a speaker takes the steps, keeps out of the headline,
// pauses off-screen, stays still for reduced motion.
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { createSwarm } from '../parthenon/swarm.js'

const props = defineProps({
  era: { type: String, default: 'ancient' }, // 'ancient' | 'now'
  intensity: { type: Number, default: 0 }, // 0 idle .. 1 a speaker has the floor
  // The sky, as fractions of the canvas: { top, bottom, left, right }
  region: { type: Object, default: null },
  // A rectangle in canvas pixels the flock stays out of: { x, y, w, h }
  avoid: { type: Object, default: null }
})

const canvas = ref(null)

// Home.vue's fixed .topbar is 68px tall. The strip of hero under it does not
// count as on screen; the extra pixel matters because the #stages anchor lands
// the hero's bottom exactly on 68, and an edge-adjacent target still reports
// isIntersecting.
const TOPBAR = 68

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
let settleTimer = 0
let intersectionObserver = null
let reduceQuery = null
let dprQuery = null
let host = null

const frame = (now) => {
  if (!running) return
  const dt = Math.min(34, last ? now - last : 16.67)
  last = now
  swarm.step(dt, props.intensity)
  swarm.draw(ctx, props.era, dpr)
  raf = requestAnimationFrame(frame)
}

const start = () => {
  if (running || reduced || !visible || document.hidden || !swarm) return
  running = true
  last = 0
  raf = requestAnimationFrame(frame)
}

const stop = () => {
  running = false
  cancelAnimationFrame(raf)
}

// A still murmuration for reduced motion: let the flock settle, then draw once.
const drawStill = () => {
  for (let i = 0; i < 90; i++) swarm.step(16.67, props.intensity)
  swarm.draw(ctx, props.era, dpr)
}

// Reduced motion: settle a reseeded flock once, after the resize goes quiet,
// so a drag-resize never runs the whole settle on every callback.
const settleSoon = () => {
  clearTimeout(settleTimer)
  settleTimer = setTimeout(() => {
    settleTimer = 0
    if (reduced && swarm) drawStill()
  }, 150)
}

const resize = () => {
  resizeRaf = 0
  const el = canvas.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const width = Math.max(1, Math.round(rect.width))
  const height = Math.max(1, Math.round(rect.height))
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  el.width = Math.round(width * dpr)
  el.height = Math.round(height * dpr)
  const birds = swarm?.state.birds
  if (!swarm) {
    swarm = createSwarm({ width, height, region: props.region || undefined, era: props.era })
    swarm.setAvoid(props.avoid)
  } else {
    swarm.resize(width, height)
  }
  if (reduced && !birds) {
    drawStill()
  } else {
    // Resizing clears the canvas: repaint once so no blank frame shows.
    swarm.draw(ctx, props.era, dpr)
    if (reduced && swarm.state.birds !== birds) settleSoon()
  }
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

const onVisibility = () => (document.hidden ? stop() : start())

const onReduceChange = () => {
  reduced = reduceQuery.matches
  if (reduced) {
    stop()
    drawStill()
  } else {
    start()
  }
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
    visible ? start() : stop()
  }, { rootMargin: `-${TOPBAR + 1}px 0px 0px 0px` })
  intersectionObserver.observe(canvas.value)

  // Listen on the hero; the canvas itself ignores the pointer so buttons work.
  host = canvas.value.parentElement
  host.addEventListener('pointermove', onPointerMove, { passive: true })
  host.addEventListener('pointerleave', onPointerLeave, { passive: true })
  document.addEventListener('visibilitychange', onVisibility)
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
  document.removeEventListener('visibilitychange', onVisibility)
})

watch(() => props.era, (era) => {
  swarm?.setEra(era)
  if (reduced && swarm) swarm.draw(ctx, era, dpr)
})

watch(() => props.region, (region) => swarm?.setRegion(region), { deep: true })
watch(() => props.avoid, (avoid) => swarm?.setAvoid(avoid), { deep: true })
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
