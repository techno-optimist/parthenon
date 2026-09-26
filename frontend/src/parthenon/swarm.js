// The swarm: a murmuration with depth. Three layers of birds (far, middle,
// near) ride a curl-noise current inside a soft, wandering ellipse above the
// roofline; alignment and local cohesion fold them into bands and turning
// edges. Warm near-black birds against the dawn of 399 BC; gold embers
// rising off the floodlit temple in 2026.
// Pure simulation and drawing: no DOM, no Vue, so it can be stepped by hand.

export const PALETTES = {
  ancient: { blend: 'source-over', core: [44, 30, 22], glow: null },
  now: { blend: 'lighter', core: [255, 214, 140], glow: [255, 166, 62] }
}

// Depth layers, far to near. Size, speed and presence grow with nearness;
// far birds beat their wings more slowly to the eye.
export const LAYERS = [
  { share: 0.46, size: 0.8, speed: 0.74, alpha: 0.5, trail: 1.7, beat: 0.55 },
  { share: 0.34, size: 1.15, speed: 1.0, alpha: 0.8, trail: 2.2, beat: 0.8 },
  { share: 0.2, size: 1.7, speed: 1.3, alpha: 1.0, trail: 2.8, beat: 1.0 }
]

const CELL = 36
const MAX_SPEED = 2.5
const MIN_SPEED = 0.8
const NEIGHBOURS = 14
// Fractions of the canvas: the sky between the Propylaea columns, above the roofline.
export const DEFAULT_REGION = { top: 0.05, bottom: 0.46, left: 0.2, right: 0.9 }
// A wingbeat is a flicker of presence; three shades keep the drawing to nine strokes.
const FLICKER = [0.5, 0.76, 1]

export function createSwarm({ width, height, region, count, era = 'ancient' } = {}) {
  const state = {
    width,
    height,
    region: { ...DEFAULT_REGION, ...(region || {}) },
    era,
    birds: [],
    grid: new Map(),
    clock: 0,
    energy: 0,
    pointer: { x: -9999, y: -9999, active: false },
    // A rectangle the flock stays out of (the headline), in canvas pixels.
    avoid: null,
    buckets: Array.from({ length: LAYERS.length * FLICKER.length }, () => [])
  }

  // 250 to 400 birds on a desktop, about 120 on a phone.
  const flockSize = () => {
    if (count) return count
    if (state.width < 700) return 120
    return Math.max(250, Math.min(400, Math.round((state.width * state.height) / 3600)))
  }

  let s = 20260925
  const rand = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646

  const layerFor = (r) => (r < LAYERS[0].share ? 0 : r < LAYERS[0].share + LAYERS[1].share ? 1 : 2)

  const hatch = (x, y, vx, vy, i, z) => ({
    x,
    y,
    vx,
    vy,
    z,
    p: i * 2.39996,
    // Wingbeats: five to ten a second, slower for the far layer.
    w: Math.PI * 2 * (5 + 5 * rand()) * LAYERS[z].beat
  })

  // Start as a loose cloud over the temple (deterministic, so every visit
  // opens on the same sky), heading roughly the same way like a real flock.
  const seed = () => {
    s = 20260925
    const n = flockSize()
    const { top, bottom, left, right } = state.region
    const cx = state.width * (left + right) / 2
    const cy = state.height * (top + (bottom - top) * 0.45)
    const rx = state.width * (right - left) * 0.26
    const ry = state.height * (bottom - top) * 0.28
    state.birds = Array.from({ length: n }, (_, i) => {
      const r = Math.sqrt(rand())
      const a = rand() * Math.PI * 2
      const heading = -0.35 + (rand() - 0.5) * 0.9
      const z = layerFor(rand())
      const v = 1.6 * LAYERS[z].speed
      return hatch(cx + Math.cos(a) * r * rx, cy + Math.sin(a) * r * ry, Math.cos(heading) * v, Math.sin(heading) * v, i, z)
    })
  }

  // Let a freshly seeded flock find its shape before anyone sees it.
  const prewarm = (steps = 80) => {
    for (let i = 0; i < steps; i++) step(16.67, 0)
  }

  const cellKey = (cx, cy) => cx * 7919 + cy

  const buildGrid = () => {
    state.grid.clear()
    state.birds.forEach((b, i) => {
      const key = cellKey(Math.floor(b.x / CELL), Math.floor(b.y / CELL))
      let bucket = state.grid.get(key)
      if (!bucket) state.grid.set(key, (bucket = []))
      bucket.push(i)
    })
  }

  // Divergence-free swirl (curl of a moving stream function): the current
  // folds and stretches the flock without piling birds onto one line.
  const curl = (x, y, t) => {
    const a = 0.0046
    const b = 0.0061
    const c = 0.0023
    const u = x * a + t * 0.27
    const v = y * b - t * 0.19
    const w = (x + y) * c + t * 0.13
    const dPsiDx = a * Math.cos(u) * Math.cos(v) + 0.6 * c * Math.cos(w)
    const dPsiDy = -b * Math.sin(u) * Math.sin(v) + 0.6 * c * Math.cos(w)
    return [dPsiDy, -dPsiDx]
  }

  // Advance by dt milliseconds; intensity 0..1 is how strongly a speaker holds the floor.
  const step = (dt, intensity = 0) => {
    const k = dt / 16.67
    const { birds, pointer, avoid } = state
    const embers = state.era === 'now'
    state.clock += dt / 1000
    state.energy += (intensity - state.energy) * Math.min(1, 0.02 * k)
    const energy = state.energy
    const t = state.clock

    const { top, bottom, left, right } = state.region
    const minX = state.width * left
    const maxX = state.width * right
    const minY = state.height * top
    const maxY = state.height * bottom

    // The cloud's heart wanders over the temple; its size breathes. Embers
    // hang lower, just off the roof. When a speaker has the floor the flock
    // draws in and wheels around them.
    const heartX = minX + (maxX - minX) * (0.5 + 0.3 * Math.sin(t * 0.083) * (1 - 0.6 * energy))
    const heartY = minY + (maxY - minY) * ((embers ? 0.58 : 0.45) + 0.2 * Math.sin(t * 0.131 + 1.7) * (1 - 0.6 * energy))
    const breathe = 1 + 0.25 * Math.sin(t * 0.21)
    const rx = (maxX - minX) * (0.27 - 0.12 * energy) * breathe
    const ry = (maxY - minY) * (0.3 - 0.12 * energy) * breathe
    const flowScale = 240 * (1 + 0.4 * energy)

    let ax = 0
    let ay = 0
    let aw = 0
    let ah = 0
    if (avoid) {
      ax = avoid.x + avoid.w / 2
      ay = avoid.y + avoid.h / 2
      aw = avoid.w / 2 + 36
      ah = avoid.h / 2 + 36
    }

    buildGrid()
    for (let i = 0; i < birds.length; i++) {
      const b = birds[i]
      const layer = LAYERS[b.z]
      const cx = Math.floor(b.x / CELL)
      const cy = Math.floor(b.y / CELL)
      let n = 0
      let weight = 0
      let avx = 0
      let avy = 0
      let mx = 0
      let my = 0
      let sx = 0
      let sy = 0
      for (let gx = cx - 1; gx <= cx + 1; gx++) {
        for (let gy = cy - 1; gy <= cy + 1; gy++) {
          const bucket = state.grid.get(cellKey(gx, gy))
          if (!bucket) continue
          for (let q = 0; q < bucket.length && n < NEIGHBOURS; q++) {
            const j = bucket[q]
            if (j === i) continue
            const o = birds[j]
            const dx = o.x - b.x
            const dy = o.y - b.y
            const d2 = dx * dx + dy * dy
            if (d2 > CELL * CELL) continue
            // Birds mostly school with their own depth; a neighbour one layer
            // away still counts for half, so the layers fold together.
            const wz = b.z === o.z ? 1 : Math.abs(b.z - o.z) === 1 ? 0.5 : 0.15
            n++
            weight += wz
            avx += o.vx * wz
            avy += o.vy * wz
            mx += dx * wz
            my += dy * wz
            if (d2 < 324) {
              sx -= (dx / (d2 + 4)) * wz
              sy -= (dy / (d2 + 4)) * wz
            }
          }
        }
      }

      let fx = 0
      let fy = 0
      if (weight > 0) {
        fx += (avx / weight - b.vx) * 0.05 // alignment: neighbours turn together
        fy += (avy / weight - b.vy) * 0.05
        fx += (mx / weight) * 0.004 // local cohesion: bands and folding edges
        fy += (my / weight) * 0.004
      }
      fx += sx * 1.5 // separation keeps the cloud airy
      fy += sy * 1.5

      // Each bird wobbles on its own rhythm, so the flock never files into a line.
      const wobble = Math.sin(t * 1.9 + b.p) * 0.1
      fx += -b.vy * wobble
      fy += b.vx * wobble

      // Ride the current.
      const [cu, cv] = curl(b.x, b.y, t)
      fx += (cu * flowScale * layer.speed - b.vx) * 0.03
      fy += (cv * flowScale * 0.75 * layer.speed - b.vy) * 0.03

      // Embers rise off the roof, then are drawn back by the heart.
      if (embers) fy -= 0.012 * layer.speed

      // Soft ellipse: outside it, birds are drawn back toward the heart.
      const ex = (b.x - heartX) / rx
      const ey = (b.y - heartY) / ry
      const e = Math.sqrt(ex * ex + ey * ey)
      if (e > 1) {
        const pullBack = (e - 1) * 0.05
        fx -= (ex / e) * pullBack
        fy -= (ey / e) * pullBack
      }

      // With a speaker on the floor, the flock wheels around them.
      if (energy > 0.01) {
        const dx = b.x - heartX
        const dy = b.y - heartY
        const d = Math.sqrt(dx * dx + dy * dy) + 1
        fx += (-dy / d) * 0.05 * energy
        fy += (dx / d) * 0.05 * energy
      }

      // Soft walls keep the flock in the sky, above the roofline.
      if (b.x < minX) fx += (minX - b.x) * 0.004
      else if (b.x > maxX) fx -= (b.x - maxX) * 0.004
      if (b.y < minY) fy += (minY - b.y) * 0.006
      else if (b.y > maxY) fy -= (b.y - maxY) * 0.008

      // The headline is not sky: birds that drift into it leave by the nearest edge.
      if (avoid) {
        const nx = (b.x - ax) / aw
        const ny = (b.y - ay) / ah
        if (nx > -1 && nx < 1 && ny > -1 && ny < 1) {
          const outX = (1 - Math.abs(nx)) * aw
          const outY = (1 - Math.abs(ny)) * ah
          if (outX < outY) fx += (nx < 0 ? -1 : 1) * 0.14
          else fy += (ny < 0 ? -1 : 1) * 0.14
        }
      }

      // The swarm parts around you.
      if (pointer.active) {
        const dx = b.x - pointer.x
        const dy = b.y - pointer.y
        const d = Math.sqrt(dx * dx + dy * dy)
        if (d < 150) {
          const f = (1 - d / 150) * 0.9
          fx += (dx / (d + 0.01)) * f
          fy += (dy / (d + 0.01)) * f
        }
      }

      b.vx += fx * k
      b.vy += fy * k
      const maxSpeed = MAX_SPEED * layer.speed * (1 + 0.3 * energy)
      const minSpeed = MIN_SPEED * layer.speed
      const speed = Math.hypot(b.vx, b.vy) || 1
      if (speed > maxSpeed) {
        b.vx = (b.vx / speed) * maxSpeed
        b.vy = (b.vy / speed) * maxSpeed
      } else if (speed < minSpeed) {
        b.vx = (b.vx / speed) * minSpeed
        b.vy = (b.vy / speed) * minSpeed
      }
      b.x += b.vx * k
      b.y += b.vy * k
    }
  }

  const rgba = (c, a) => `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${a.toFixed(3)})`

  // Far layer first, near layer last. Each layer is three strokes (one per
  // wingbeat shade): a soft glow for embers, then the bird itself.
  const draw = (ctx, era = state.era, dpr = 1) => {
    const palette = PALETTES[era] || PALETTES.ancient
    const { birds, buckets } = state
    const t = state.clock
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, state.width, state.height)
    ctx.globalCompositeOperation = palette.blend
    ctx.lineCap = 'round'

    for (const bucket of buckets) bucket.length = 0
    for (let i = 0; i < birds.length; i++) {
      const b = birds[i]
      const beat = 0.5 + 0.5 * Math.sin(t * b.w + b.p)
      buckets[b.z * FLICKER.length + (beat < 0.34 ? 0 : beat < 0.67 ? 1 : 2)].push(i)
    }

    const lift = 0.85 + 0.15 * state.energy
    for (let z = 0; z < LAYERS.length; z++) {
      const layer = LAYERS[z]
      for (let q = 0; q < FLICKER.length; q++) {
        const list = buckets[z * FLICKER.length + q]
        if (!list.length) continue
        const alpha = Math.min(1, layer.alpha * FLICKER[q] * lift)
        ctx.beginPath()
        for (let n = 0; n < list.length; n++) {
          const b = birds[list[n]]
          ctx.moveTo(b.x - b.vx * layer.trail, b.y - b.vy * layer.trail)
          ctx.lineTo(b.x, b.y)
        }
        if (palette.glow) {
          ctx.strokeStyle = rgba(palette.glow, alpha * 0.24)
          ctx.lineWidth = layer.size * 3.4 + 1.2 * state.energy
          ctx.stroke()
        }
        ctx.strokeStyle = rgba(palette.core, alpha)
        ctx.lineWidth = layer.size
        ctx.stroke()
      }
    }
    ctx.globalCompositeOperation = 'source-over'
  }

  // Match the flock to its target size without a reset: drop the tail, or
  // hatch newcomers beside existing birds and let separation spread them.
  // Small drifts (a toolbar sliding away) leave the flock untouched.
  const fitFlock = () => {
    const n = flockSize()
    const have = state.birds.length
    if (Math.abs(n - have) <= have * 0.15) return
    if (n < have) state.birds.length = n
    for (let i = have; i < n; i++) {
      const src = state.birds[i % have]
      const p = i * 2.39996
      state.birds.push(hatch(src.x + Math.sin(p) * 6, src.y + Math.cos(p) * 6, src.vx, src.vy, i, src.z))
    }
  }

  // Mobile toolbars nudge the hero's height as the page scrolls, so a resize
  // rescales the flock in place. Reseed only on first layout or when the
  // width crosses the 700px cap (a phone rotating, a window snapping wide).
  const resize = (nextWidth, nextHeight) => {
    const prevWidth = state.width
    const prevHeight = state.height
    const crossedCap = !count && (prevWidth < 700) !== (nextWidth < 700)
    state.width = nextWidth
    state.height = nextHeight
    if (!state.birds.length || !(prevWidth >= 2) || !(prevHeight >= 2) || crossedCap) {
      seed()
      prewarm()
      return
    }
    const sx = nextWidth / prevWidth
    const sy = nextHeight / prevHeight
    if (sx !== 1 || sy !== 1) {
      for (const b of state.birds) {
        b.x *= sx
        b.y *= sy
      }
    }
    fitFlock()
  }

  const setPointer = (x, y, active = true) => {
    state.pointer.x = x
    state.pointer.y = y
    state.pointer.active = active
  }

  // Where the sky is, as fractions of the canvas. The flock drifts to it.
  const setRegion = (next) => {
    state.region = { ...DEFAULT_REGION, ...(next || {}) }
  }

  // A rectangle in canvas pixels ({x, y, w, h}) the flock keeps out of, or null.
  const setAvoid = (rect) => {
    state.avoid = rect && rect.w > 0 && rect.h > 0 ? { x: rect.x, y: rect.y, w: rect.w, h: rect.h } : null
  }

  const setEra = (next) => {
    state.era = next === 'now' ? 'now' : 'ancient'
  }

  seed()
  prewarm()
  return { state, step, draw, resize, setPointer, setRegion, setAvoid, setEra }
}
