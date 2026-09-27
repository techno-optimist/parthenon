// The sky over the hero, one flock per era.
//
// 399 BC: a distant murmuration of starlings at dawn. About a thousand tiny
// umber birds fly as one body: separation, alignment and cohesion on a
// uniform grid, held in a slowly wandering, breathing body of three lobes on
// a bending spine above the roofline, folded by a curl-noise current (the
// lobes, not the birds' spacing, draw the outline). Seen from far away it is
// a sheet in three dimensions, so as it banks it thins to a dark edge and
// opens again; now and then a falcon stoops through it and a wave of
// darkness ripples out from the strike. Dust motes drift in the low sunbeam
// at the left of the plate.
//
// 2026: gold embers rising off the floodlit temple. Born on the roofline
// itself (just under the sky the birds keep to), they leave the stone
// white-hot, climb on the warm air, sway and curl in the current, and cool
// through gold to a deep orange as they thin into the dark (three depth
// layers, drawn as short glowing strokes).
//
// Pure simulation and drawing: no DOM, no Vue, so it can be stepped by hand.
// Every array is allocated when a flock is seeded or the canvas resized;
// step() and draw() allocate nothing.

export const PALETTES = {
  ancient: { blend: 'source-over', core: [46, 32, 24], glow: null, mote: [255, 218, 160] },
  // An ember's colour is its heat, coolest first: a deep orange high in the
  // dark, gold in the plume, white-gold as it leaves the stone.
  now: {
    blend: 'lighter',
    core: [[240, 128, 52], [255, 200, 118], [255, 240, 206]],
    glow: [[196, 64, 18], [255, 140, 46], [255, 184, 88]]
  }
}

// Embers: depth layers, far to near. Size, speed and presence grow with
// nearness; far embers flicker more slowly to the eye (beat).
export const LAYERS = [
  { share: 0.46, size: 0.8, speed: 0.74, alpha: 0.5, trail: 1.7, beat: 0.55 },
  { share: 0.34, size: 1.15, speed: 1.0, alpha: 0.8, trail: 2.2, beat: 0.8 },
  { share: 0.2, size: 1.7, speed: 1.3, alpha: 1.0, trail: 2.8, beat: 1.0 }
]

// Starlings: depth layers of the sheet. Sizes are CSS pixels (1 to 1.6).
export const STARLING_LAYERS = [
  { share: 0.44, size: 1.0, alpha: 0.5 },
  { share: 0.36, size: 1.25, alpha: 0.7 },
  { share: 0.2, size: 1.6, alpha: 0.88 }
]

// Fractions of the canvas: the sky between the Propylaea columns, above the
// roofline. Two optional keys place the embers' fire on the plate:
//   roof   the roofline they rise from: a level height, or the roof's outline
//          as up to eight [x, y] points from left to right (a gable, a roof
//          seen from its corner). Without it, ROOF_MARGIN under the sky's
//          bottom, the margin a host leaves so the birds never cross the temple.
//   heart  where across the canvas the plume is centred. Without it, over the
//          outline's highest point, or a little right of the sky's middle.
export const DEFAULT_REGION = { top: 0.05, bottom: 0.46, left: 0.2, right: 0.9 }
export const ROOF_MARGIN = 0.03

// Ember shades: flicker and the glow of a cooling ember.
const EMBER_SHADES = [0.34, 0.66, 1]
// Starling wingbeat shades: a distant bird only twinkles.
const TWINKLE = [0.72, 1]

const EMBER = { cell: 36, neighbours: 10, maxSpeed: 2.2 }
const STARLING = {
  cell: 12, // neighbour radius and grid cell
  neighbours: 12, // a starling watches about seven to twelve neighbours
  sep: 5.3, // separation radius
  align: 0.085,
  cohere: 0.005,
  separate: 0.34,
  flow: 0.018,
  body: 0.05,
  minSpeed: 0.62,
  maxSpeed: 1.32
}

const PHONE = 700
// Seconds into the sky's rhythms at which every visit opens.
const OPENING = 8.5
const TAU = Math.PI * 2

// ---------------------------------------------------------------------------
// A uniform grid built by counting sort. Cells cover [0, width) x [0, height);
// points outside are clamped into the edge cells, which keeps queries exact
// because clamping never moves two points more than one cell apart.

export function createGrid(capacity, cell) {
  return {
    cell,
    cols: 1,
    rows: 1,
    cells: 1,
    start: new Uint32Array(2),
    items: new Uint32Array(Math.max(1, capacity)),
    home: new Uint32Array(Math.max(1, capacity))
  }
}

export function gridResize(grid, width, height) {
  grid.cols = Math.max(1, Math.ceil(width / grid.cell))
  grid.rows = Math.max(1, Math.ceil(height / grid.cell))
  grid.cells = grid.cols * grid.rows
  if (grid.start.length < grid.cells + 1) grid.start = new Uint32Array(grid.cells + 1)
}

const cellX = (grid, x) => {
  const c = (x / grid.cell) | 0
  return c < 0 ? 0 : c >= grid.cols ? grid.cols - 1 : c
}

const cellY = (grid, y) => {
  const c = (y / grid.cell) | 0
  return c < 0 ? 0 : c >= grid.rows ? grid.rows - 1 : c
}

// Sort the first n points into cells: start[c]..start[c + 1] indexes items.
export function gridBuild(grid, xs, ys, n) {
  const { start, items, home, cells } = grid
  start.fill(0, 0, cells + 1)
  for (let i = 0; i < n; i++) {
    const c = cellY(grid, ys[i]) * grid.cols + cellX(grid, xs[i])
    home[i] = c
    start[c]++
  }
  let sum = 0
  for (let c = 0; c < cells; c++) {
    const count = start[c]
    start[c] = sum
    sum += count
  }
  start[cells] = sum
  for (let i = 0; i < n; i++) items[start[home[i]]++] = i
  for (let c = cells; c > 0; c--) start[c] = start[c - 1]
  start[0] = 0
}

// The centre cell first, so a capped query favours the nearest birds.
const AROUND = [0, 0, -1, 0, 1, 0, 0, -1, 0, 1, -1, -1, 1, -1, -1, 1, 1, 1]

// Indices of the points within radius r of point i (not i itself), written
// to out (squared distances to outD), at most max of them. Returns the count.
// r must not exceed the cell size.
export function gridNeighbours(grid, xs, ys, i, r, out, outD, max = out.length) {
  const x = xs[i]
  const y = ys[i]
  const r2 = r * r
  const cx = cellX(grid, x)
  const cy = cellY(grid, y)
  const { start, items, cols, rows } = grid
  let n = 0
  for (let a = 0; a < 18; a += 2) {
    const gx = cx + AROUND[a]
    const gy = cy + AROUND[a + 1]
    if (gx < 0 || gy < 0 || gx >= cols || gy >= rows) continue
    const c = gy * cols + gx
    for (let q = start[c], end = start[c + 1]; q < end; q++) {
      const j = items[q]
      if (j === i) continue
      const dx = xs[j] - x
      const dy = ys[j] - y
      const d2 = dx * dx + dy * dy
      if (d2 > r2) continue
      out[n] = j
      if (outD) outD[n] = d2
      if (++n >= max) return n
    }
  }
  return n
}

// ---------------------------------------------------------------------------

function makeFlock(capacity, cell) {
  return {
    n: 0,
    cap: capacity,
    seeded: false,
    x: new Float32Array(capacity),
    y: new Float32Array(capacity),
    vx: new Float32Array(capacity),
    vy: new Float32Array(capacity),
    // Where each bird is drawn (the sheet seen in perspective).
    rx: new Float32Array(capacity),
    ry: new Float32Array(capacity),
    z: new Uint8Array(capacity), // depth layer
    p: new Float32Array(capacity), // phase
    w: new Float32Array(capacity), // wingbeat, radians per second
    s: new Float32Array(capacity), // own speed factor
    age: new Float32Array(capacity), // embers: seconds alight
    base: new Float32Array(capacity), // embers: the roof they rose from
    life: new Float32Array(capacity), // embers: seconds they burn
    shade: new Int8Array(capacity), // this frame's shade, -1 for unseen
    grid: createGrid(capacity, cell),
    nb: new Uint32Array(32),
    nbD: new Float32Array(32),
    cx: 0,
    cy: 0
  }
}

export function createSwarm({ width, height, region, count, era = 'ancient' } = {}) {
  const state = {
    width,
    height,
    region: { ...DEFAULT_REGION, ...(region || {}) },
    era: era === 'now' ? 'now' : 'ancient',
    // 0 shows 399 BC, 1 shows 2026; eases between them when the era changes.
    mix: era === 'now' ? 1 : 0,
    // The sky's clock opens where the sheet is banking into a long ribbon.
    clock: OPENING,
    energy: 0,
    seeds: 0,
    pointer: { x: -9999, y: -9999, active: false },
    // A rectangle the flock stays out of (the headline), in canvas pixels.
    avoid: null,
    flocks: { ancient: null, now: null },
    // The body of the murmuration: its heart, size and lean, and the sheet's bank.
    body: { x: 0, y: 0, a: 1, b: 1, lean: 0, bank: 1, axis: 0, fold: 0, shear: 0 },
    // A falcon stoops through the sheet now and then.
    falcon: { active: false, x: 0, y: 0, dx: 0, dy: 0, until: 0, next: OPENING + 8, waveX: 0, waveY: 0, waveAt: -99 },
    motes: null
  }

  const phone = () => state.width < PHONE

  // Starlings: about 800 on a phone, 1000 to 1500 on a desktop.
  const starlingCount = () => {
    if (count) return count
    if (phone()) return 800
    return Math.max(1000, Math.min(1500, Math.round((state.width * state.height) / 1100)))
  }

  // Embers: 250 to 400 on a desktop, 170 on a phone (its roof is near and
  // bright, and a thinner plume there reads as dust, not fire).
  const emberCount = () => {
    if (count) return count
    if (phone()) return 170
    return Math.max(250, Math.min(400, Math.round((state.width * state.height) / 3600)))
  }

  let s = 20260925
  const rand = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646

  // The sky, in canvas pixels, and the roofline under it: the embers' sky
  // reaches down to the roof they rise from (roofY, its lowest point); the
  // birds keep above maxY. The outline is kept as canvas points (roofPts).
  const bounds = { minX: 0, maxX: 1, minY: 0, maxY: 1, roofY: 1, heartX: 0, spread: 1 }
  const ROOF_POINTS = 8
  const roofPts = new Float32Array(ROOF_POINTS * 2)
  let roofN = 0
  const measureBounds = () => {
    const { top, bottom, left, right, roof, heart } = state.region
    const W = state.width
    const H = state.height
    bounds.minX = W * left
    bounds.maxX = Math.max(bounds.minX + 1, W * right)
    bounds.minY = H * top
    bounds.maxY = Math.max(bounds.minY + 1, H * bottom)
    // The roof never climbs into the top of the sky, nor falls off the canvas.
    const lo = bounds.minY + 24
    roofN = 0
    if (Array.isArray(roof)) {
      for (let k = 0; k < roof.length && roofN < ROOF_POINTS; k++) {
        const pt = roof[k]
        if (!pt || !Number.isFinite(pt[0]) || !Number.isFinite(pt[1])) continue
        const x = W * pt[0]
        if (roofN && x <= roofPts[roofN * 2 - 2]) continue // left to right only
        roofPts[roofN * 2] = x
        roofPts[roofN * 2 + 1] = Math.min(H, Math.max(lo, H * pt[1]))
        roofN++
      }
    }
    if (!roofN) {
      roofPts[0] = 0
      roofPts[1] = Math.min(H, Math.max(lo, H * (Number.isFinite(roof) ? roof : bottom + ROOF_MARGIN)))
      roofN = 1
    }
    let lowest = roofPts[1]
    let peak = 0
    for (let k = 1; k < roofN; k++) {
      const y = roofPts[k * 2 + 1]
      if (y > lowest) lowest = y
      if (y < roofPts[peak * 2 + 1]) peak = k
    }
    bounds.roofY = lowest
    const x = Number.isFinite(heart)
      ? W * heart
      : roofN > 1
        ? roofPts[peak * 2]
        : bounds.minX + (bounds.maxX - bounds.minX) * 0.58
    bounds.heartX = Math.min(bounds.maxX, Math.max(bounds.minX, x))
    // How far either side of the heart sparks are born: along the whole outline
    // when there is one, else four tenths of the sky.
    const sky = bounds.maxX - bounds.minX
    bounds.spread = sky * 0.4
    if (roofN > 1) {
      const a = Math.max(bounds.minX, roofPts[0])
      const b = Math.min(bounds.maxX, roofPts[roofN * 2 - 2])
      bounds.spread = Math.max(sky * 0.2, bounds.heartX - a, b - bounds.heartX)
    }
  }

  // The roofline's height at x (level past its ends).
  const roofAt = (x) => {
    if (roofN === 1 || x <= roofPts[0]) return roofPts[1]
    for (let k = 1; k < roofN; k++) {
      const x1 = roofPts[k * 2]
      if (x <= x1) {
        const x0 = roofPts[k * 2 - 2]
        const y0 = roofPts[k * 2 - 1]
        return y0 + ((roofPts[k * 2 + 1] - y0) * (x - x0)) / (x1 - x0)
      }
    }
    return roofPts[roofN * 2 - 1]
  }

  // Padded headline rectangle: [ax0, ax1] x [ay0, ay1], or none.
  const hole = { on: false, x0: 0, x1: 0, y0: 0, y1: 0 }
  const measureHole = () => {
    const a = state.avoid
    hole.on = !!a
    if (!a) return
    hole.x0 = a.x - 12
    hole.x1 = a.x + a.w + 12
    hole.y0 = a.y - 12
    hole.y1 = a.y + a.h + 12
  }
  const inHole = (x, y) => hole.on && x > hole.x0 && x < hole.x1 && y > hole.y0 && y < hole.y1

  // ---- 399 BC: the starlings -------------------------------------------

  const layerOf = (r, layers) => {
    let acc = 0
    for (let z = 0; z < layers.length; z++) {
      acc += layers[z].share
      if (r < acc) return z
    }
    return layers.length - 1
  }

  // Where the body wanders: a slow Lissajous over the sky, kept clear of the
  // edges and the headline, drawn toward the temple when a speaker has the
  // floor. The body is three lobes strung on a bending spine, so it swells,
  // pinches into a waist and trails a tail instead of holding one oval.
  const LOBES = 3
  const lobes = new Float32Array(LOBES * 4) // x, y, a, b per lobe (leaning with the spine)
  const placeBody = (clock, energy, n) => {
    // The body's rhythms run a little slower than the birds: it is far away.
    const t = clock * 0.75
    const { minX, maxX, minY, maxY } = bounds
    const W = maxX - minX
    const H = maxY - minY
    const body = state.body
    const breathe = 1 + 0.1 * Math.sin(t * 0.23) + 0.05 * Math.sin(t * 0.61 + 0.4)
    // Sized so the birds fill the lobes a little pressed (about 22 px2 each):
    // the lobes, not the birds' spacing, draw the outline.
    const lobe = Math.sqrt((2 * n * 22) / 2.6 / Math.PI)
    const size = Math.max(40, Math.min(W * (phone() ? 0.26 : 0.16), lobe / 0.62))
    const gather = 1 - 0.35 * energy
    body.a = size * breathe * gather
    body.b = body.a * (0.5 + 0.1 * Math.sin(t * 0.17 + 2.1))
    body.lean = 0.3 * Math.sin(t * 0.049 + 0.7) + 0.12 * Math.sin(t * 0.13)
    const c = Math.cos(body.lean)
    const sn = Math.sin(body.lean)
    // The spine: its length stretches and its bend swings.
    const len = body.a * (0.75 + 0.35 * Math.sin(t * 0.071 + 0.4)) * (1 - 0.5 * energy)
    const bend = body.a * 0.35 * Math.sin(t * 0.059 + 2.6)
    // Half extents of the whole body, for keeping it in the sky.
    const hx = Math.abs(c) * len + body.a * 0.62 + Math.abs(sn) * Math.abs(bend)
    const hy = Math.abs(sn) * len + body.b * 0.62 + Math.abs(c) * Math.abs(bend)
    let x = minX + W * (0.5 + 0.32 * Math.sin(t * 0.041 + 0.3) + 0.08 * Math.sin(t * 0.113 + 1.9))
    let y = minY + H * (0.46 + 0.2 * Math.sin(t * 0.057 + 1.1) + 0.06 * Math.sin(t * 0.151))
    // A speaker on the floor: the sheet gathers nearer the temple.
    const tx = minX + W * 0.62
    const ty = minY + H * 0.7
    x += (tx - x) * 0.85 * energy
    y += (ty - y) * 0.85 * energy
    x = hx * 2 > W ? minX + W / 2 : Math.min(maxX - hx, Math.max(minX + hx, x))
    y = hy * 2 > H ? minY + H / 2 : Math.min(maxY - hy, Math.max(minY + hy, y))
    if (hole.on && x + hx > hole.x0 && x - hx < hole.x1 && y + hy > hole.y0 && y - hy < hole.y1) {
      // Rise above the words if the sky allows, else step aside.
      const above = hole.y0 - hy
      if (above >= minY + hy * 0.6) y = above
      else if (hole.x1 + hx <= maxX) x = hole.x1 + hx
      else if (hole.x0 - hx >= minX) x = hole.x0 - hx
    }
    body.x = x
    body.y = y
    for (let k = 0; k < LOBES; k++) {
      const along = k - 1 // -1, 0, 1
      const swell = 0.62 + 0.26 * Math.sin(t * (0.083 + 0.031 * k) + k * 2.1)
      const ox = along * len
      const oy = (1 - along * along) * bend - 0.5 * bend
      lobes[k * 4] = x + ox * c - oy * sn
      lobes[k * 4 + 1] = y + ox * sn + oy * c
      lobes[k * 4 + 2] = body.a * swell * (k === 1 ? 1 : 0.85)
      lobes[k * 4 + 3] = body.b * swell * (k === 1 ? 1 : 0.8)
    }
    // The bank: the sheet turns edge-on (thin and dark) and opens again.
    body.axis = 0.55 + 0.6 * Math.sin(t * 0.043) + 0.3 * Math.sin(t * 0.097 + 1.3)
    const roll = Math.cos(t * 0.29 + 0.9 * Math.sin(t * 0.071))
    const bank = 0.6 + 0.4 * roll
    body.bank = bank + (1 - bank) * 0.7 * energy
    body.fold = Math.max(0, Math.sin(t * 0.083 + 2.2)) * 0.55 * (1 - energy)
    body.shear = 0.3 * Math.sin(t * 0.052 + 0.5)
  }

  const seedStarlings = (f) => {
    const n = Math.min(f.cap, starlingCount())
    f.n = n
    measureBounds()
    placeBody(state.clock, state.energy, n)
    const { lean } = state.body
    const c = Math.cos(lean)
    const sn = Math.sin(lean)
    const heading = lean + (rand() < 0.5 ? 0 : Math.PI)
    for (let i = 0; i < n; i++) {
      const k = i % LOBES
      const r = Math.sqrt(rand())
      const ang = rand() * TAU
      const u = Math.cos(ang) * r * lobes[k * 4 + 2] * 0.9
      const v = Math.sin(ang) * r * lobes[k * 4 + 3] * 0.9
      f.x[i] = lobes[k * 4] + u * c - v * sn
      f.y[i] = lobes[k * 4 + 1] + u * sn + v * c
      const h = heading + (rand() - 0.5) * 0.5
      f.s[i] = 0.85 + 0.3 * rand()
      const speed = 0.95 * f.s[i]
      f.vx[i] = Math.cos(h) * speed
      f.vy[i] = Math.sin(h) * speed
      f.z[i] = layerOf(rand(), STARLING_LAYERS)
      f.p[i] = i * 2.39996
      f.w[i] = TAU * (7 + 5 * rand())
      f.rx[i] = f.x[i]
      f.ry[i] = f.y[i]
    }
    // Keep every bird inside the sky and out of the words from the first frame.
    for (let i = 0; i < n; i++) confine(f, i, f.x[i], f.y[i])
  }

  // Push a point that is outside the sky or inside the headline back to the
  // nearest allowed place (used at seeding and for birds a new layout strands).
  // The embers' sky reaches down to the roof (maxY = bounds.roofY).
  const confine = (f, i, x, y, maxY = bounds.maxY) => {
    const { minX, maxX, minY } = bounds
    if (x < minX) x = minX + 1
    else if (x > maxX) x = maxX - 1
    if (y < minY) y = minY + 1
    else if (y > maxY) y = maxY - 1
    if (inHole(x, y)) {
      const up = y - hole.y0
      const down = hole.y1 - y
      const left = x - hole.x0
      const right = hole.x1 - x
      const m = Math.min(up, hole.y1 < maxY ? down : Infinity, hole.x0 > minX ? left : Infinity, hole.x1 < maxX ? right : Infinity)
      if (m === up && hole.y0 - 1 > minY) y = hole.y0 - 1
      else if (m === down) y = hole.y1 + 1
      else if (m === left) x = hole.x0 - 1
      else if (m === right) x = hole.x1 + 1
    }
    f.x[i] = x
    f.y[i] = y
  }

  const stepFalcon = (f, t, k) => {
    const falcon = state.falcon
    if (!falcon.active) {
      if (t < falcon.next || state.energy > 0.4 || f.n === 0) return
      // Stoop at a bird near the heart of the sheet, from above.
      const i = (rand() * f.n) | 0
      const tx = (f.rx[i] + state.body.x) / 2
      const ty = (f.ry[i] + state.body.y) / 2
      const ang = Math.PI / 2 + (rand() - 0.5) * 1.3
      falcon.dx = Math.cos(ang) * 4.4
      falcon.dy = Math.sin(ang) * 4.4
      const lead = 36 // frames before it reaches the sheet
      falcon.x = tx - falcon.dx * lead
      falcon.y = ty - falcon.dy * lead
      falcon.waveX = tx
      falcon.waveY = ty
      falcon.waveAt = t + lead / 60
      falcon.until = t + (lead * 2) / 60
      falcon.active = true
      falcon.next = t + 9 + rand() * 9
      return
    }
    falcon.x += falcon.dx * k
    falcon.y += falcon.dy * k
    if (t > falcon.until) falcon.active = false
  }

  const stepStarlings = (f, dt, k) => {
    const t = state.clock
    const energy = state.energy
    placeBody(t, energy, f.n)
    stepFalcon(f, t, k)
    const { minX, maxX, minY, maxY } = bounds
    const { x: X, y: Y, vx: VX, vy: VY, rx: RX, ry: RY, s: S, nb, nbD, grid } = f
    const body = state.body
    const bc = Math.cos(body.lean)
    const bs = Math.sin(body.lean)
    const pointer = state.pointer
    const falcon = state.falcon
    const sep = STARLING.sep
    const sep2 = sep * sep
    const edge = 22
    const flowScale = 150

    gridBuild(grid, X, Y, f.n)
    let sumX = 0
    let sumY = 0
    for (let i = 0; i < f.n; i++) {
      const xi = X[i]
      const yi = Y[i]
      const vxi = VX[i]
      const vyi = VY[i]
      const m = gridNeighbours(grid, X, Y, i, STARLING.cell, nb, nbD, STARLING.neighbours)
      let ax = 0
      let ay = 0
      let cx = 0
      let cy = 0
      let sx = 0
      let sy = 0
      for (let q = 0; q < m; q++) {
        const j = nb[q]
        const dx = X[j] - xi
        const dy = Y[j] - yi
        ax += VX[j]
        ay += VY[j]
        cx += dx
        cy += dy
        const d2 = nbD[q]
        if (d2 < sep2) {
          const d = Math.sqrt(d2) + 0.001
          const push = (1 - d / sep) / d
          sx -= dx * push
          sy -= dy * push
        }
      }
      let fx = sx * STARLING.separate
      let fy = sy * STARLING.separate
      if (m > 0) {
        const inv = 1 / m
        fx += (ax * inv - vxi) * STARLING.align + cx * inv * STARLING.cohere
        fy += (ay * inv - vyi) * STARLING.align + cy * inv * STARLING.cohere
      }

      // The current: curl of a moving stream function folds the body.
      const u = xi * 0.0071 + t * 0.21
      const v = yi * 0.0093 - t * 0.17
      const w = (xi + yi) * 0.0031 + t * 0.11
      const cw = 0.6 * 0.0031 * Math.cos(w)
      const dPsiDx = 0.0071 * Math.cos(u) * Math.cos(v) + cw
      const dPsiDy = -0.0093 * Math.sin(u) * Math.sin(v) + cw
      fx += (dPsiDy * flowScale - vxi) * STARLING.flow
      fy += (-dPsiDx * flowScale * 0.7 - vyi) * STARLING.flow

      // The body: outside every lobe, a bird turns back to the nearest.
      let best = Infinity
      let bx = 0
      let by = 0
      for (let q = 0; q < 12; q += 4) {
        const lx = xi - lobes[q]
        const ly = yi - lobes[q + 1]
        const eu = (lx * bc + ly * bs) / lobes[q + 2]
        const ev = (ly * bc - lx * bs) / lobes[q + 3]
        const e2 = eu * eu + ev * ev
        if (e2 < best) {
          best = e2
          bx = lx
          by = ly
        }
      }
      if (best > 1) {
        const pull = Math.min(0.3, (Math.sqrt(best) - 1) * STARLING.body)
        const d = Math.sqrt(bx * bx + by * by) + 0.001
        fx -= (bx / d) * pull
        fy -= (by / d) * pull
      }
      const ex = xi - body.x
      const ey = yi - body.y

      // With a speaker on the floor the sheet wheels around its heart.
      if (energy > 0.01) {
        const d = Math.sqrt(ex * ex + ey * ey) + 1
        fx += (-ey / d) * 0.06 * energy
        fy += (ex / d) * 0.06 * energy
      }

      // Soft walls, a little inside the sky.
      if (xi < minX + edge) fx += (minX + edge - xi) * 0.01
      else if (xi > maxX - edge) fx -= (xi - maxX + edge) * 0.01
      if (yi < minY + edge) fy += (minY + edge - yi) * 0.01
      else if (yi > maxY - edge) fy -= (yi - maxY + edge) * 0.012

      // The words are not sky.
      if (hole.on && inHole(xi, yi)) {
        const up = yi - hole.y0
        const down = hole.y1 - yi
        if (up < down || hole.y1 >= maxY) fy -= 0.2
        else fy += 0.2
      }

      // The sheet parts around the pointer and scatters from the falcon
      // (both measured where the bird is drawn).
      if (pointer.active) {
        const dx = RX[i] - pointer.x
        const dy = RY[i] - pointer.y
        const d2 = dx * dx + dy * dy
        if (d2 < 12100) {
          const d = Math.sqrt(d2) + 0.01
          const push = (1 - d / 110) * 0.5
          fx += (dx / d) * push
          fy += (dy / d) * push
        }
      }
      if (falcon.active) {
        const dx = RX[i] - falcon.x
        const dy = RY[i] - falcon.y
        const d2 = dx * dx + dy * dy
        if (d2 < 1600) {
          const d = Math.sqrt(d2) + 0.01
          const push = (1 - d / 40) * 0.45
          fx += (dx / d) * push
          fy += (dy / d) * push
        }
      }

      let nvx = vxi + fx * k
      let nvy = vyi + fy * k
      const own = S[i] * (1 + 0.2 * energy)
      const maxSpeed = STARLING.maxSpeed * own
      const minSpeed = STARLING.minSpeed * own
      const speed = Math.sqrt(nvx * nvx + nvy * nvy) || 1
      if (speed > maxSpeed) {
        nvx *= maxSpeed / speed
        nvy *= maxSpeed / speed
      } else if (speed < minSpeed) {
        nvx *= minSpeed / speed
        nvy *= minSpeed / speed
      }
      let nx = xi + nvx * k
      let ny = yi + nvy * k

      // Hard edges: a bird inside the sky never leaves it, and never flies
      // into the words (it turns off the wall instead). Inside allows a pixel
      // of slack, so a bird held on a wall (stored as a float32, a hair past
      // it) is still held.
      const wasIn = xi >= minX - 1 && xi <= maxX + 1 && yi >= minY - 1 && yi <= maxY + 1
      if (wasIn) {
        if (nx < minX) { nx = minX; nvx = Math.abs(nvx) }
        else if (nx > maxX) { nx = maxX; nvx = -Math.abs(nvx) }
        if (ny < minY) { ny = minY; nvy = Math.abs(nvy) }
        else if (ny > maxY) { ny = maxY; nvy = -Math.abs(nvy) }
      }
      if (hole.on && inHole(nx, ny) && !inHole(xi, yi)) {
        if (xi <= hole.x0 || xi >= hole.x1) { nx = xi; nvx = -nvx }
        else { ny = yi; nvy = -nvy }
      }
      X[i] = nx
      Y[i] = ny
      VX[i] = nvx
      VY[i] = nvy
      sumX += nx
      sumY += ny
    }
    if (f.n) {
      f.cx = sumX / f.n
      f.cy = sumY / f.n
    }
    projectStarlings(f)
  }

  // Where each bird is drawn: the sheet seen from far away. Along the bank
  // axis the body is squeezed (edge-on) and sometimes folded over itself;
  // the falcon's wave is a ring of compression running out from the strike.
  const projectStarlings = (f) => {
    const body = state.body
    const falcon = state.falcon
    const { minX, maxX, minY, maxY } = bounds
    const nx = Math.cos(body.axis)
    const ny = Math.sin(body.axis)
    const bank = body.bank
    const fold = body.fold
    const shear = body.shear
    const lf = body.a * 0.42
    const ilf = 1 / lf
    const age = state.clock - falcon.waveAt
    const wave = age > 0 && age < 3.2
    const waveR = age * 78
    const waveA = wave ? 5.5 * Math.exp(-age / 1.3) * Math.min(1, age * 4) : 0
    const band = 15
    const iband = 1 / band
    const { x: X, y: Y, rx: RX, ry: RY } = f
    const cx = f.cx
    const cy = f.cy
    for (let i = 0; i < f.n; i++) {
      const dx = X[i] - cx
      const dy = Y[i] - cy
      const along = dx * nx + dy * ny
      const across = dy * nx - dx * ny
      const a2 = along * bank + fold * lf * Math.sin(along * ilf)
      const c2 = across + shear * along
      let x = cx + nx * a2 - ny * c2
      let y = cy + ny * a2 + nx * c2
      if (wave) {
        const wx = x - falcon.waveX
        const wy = y - falcon.waveY
        const d = Math.sqrt(wx * wx + wy * wy) + 0.01
        const off = (d - waveR) * iband
        if (off > -3 && off < 3) {
          const push = -waveA * off * Math.exp(-off * off)
          x += (wx / d) * push
          y += (wy / d) * push
        }
      }
      RX[i] = x < minX ? minX : x > maxX ? maxX : x
      RY[i] = y < minY ? minY : y > maxY ? maxY : y
    }
  }

  // ---- 399 BC: motes in the sunbeam --------------------------------------

  const MOTES_DESKTOP = 40
  const MOTES_PHONE = 22
  const makeMotes = () => {
    const cap = MOTES_DESKTOP
    return {
      n: 0,
      x: new Float32Array(cap),
      y: new Float32Array(cap),
      v: new Float32Array(cap),
      r: new Float32Array(cap),
      a: new Float32Array(cap),
      p: new Float32Array(cap)
    }
  }

  // The beam: light from the low sun at the left, through the columns,
  // sloping gently down to the right.
  const beam = { x0: 0, x1: 1, y0: 0, slope: 0.1, half: 1 }
  const measureBeam = () => {
    const { top, bottom, left } = state.region
    beam.x0 = -8
    beam.x1 = state.width * Math.min(0.52, left + 0.3)
    beam.y0 = state.height * (top + (bottom - top) * (phone() ? 0.5 : 0.62))
    beam.slope = 0.12
    beam.half = state.height * (phone() ? 0.1 : 0.15)
  }

  const placeMote = (m, i, anywhere) => {
    m.x[i] = anywhere ? beam.x0 + rand() * (beam.x1 - beam.x0) : beam.x0
    const across = (rand() * 2 - 1) * (0.35 + 0.65 * rand())
    m.y[i] = beam.y0 + m.x[i] * beam.slope + across * beam.half
    m.v[i] = 0.05 + 0.08 * rand()
    const near = rand() < 0.18
    m.r[i] = near ? 3.5 + 2.5 * rand() : 1.1 + 1.1 * rand()
    m.a[i] = near ? 0.18 + 0.12 * rand() : 0.55 + 0.45 * rand()
    m.p[i] = rand() * TAU
  }

  const seedMotes = () => {
    if (!state.motes) state.motes = makeMotes()
    const m = state.motes
    measureBeam()
    m.n = phone() ? MOTES_PHONE : MOTES_DESKTOP
    for (let i = 0; i < m.n; i++) placeMote(m, i, true)
  }

  const stepMotes = (k) => {
    const m = state.motes
    if (!m) return
    const t = state.clock
    for (let i = 0; i < m.n; i++) {
      m.x[i] += m.v[i] * k
      m.y[i] += Math.sin(t * 0.37 + m.p[i]) * 0.045 * k + 0.012 * k
      const mid = beam.y0 + m.x[i] * beam.slope
      if (m.x[i] > beam.x1 || Math.abs(m.y[i] - mid) > beam.half * 1.3) placeMote(m, i, false)
    }
  }

  // ---- 2026: embers rising off the floodlit temple -----------------------

  // Where embers are born: on the roofline, most over the temple's heart.
  const spawnEmber = (f, i, spread) => {
    const { minX, maxX, minY, heartX, spread: reach } = bounds
    const z = f.z[i]
    // Folded back at the sky's sides, so a heart near an edge piles no sparks on it.
    let x = heartX + reach * (rand() + rand() - 1)
    if (x < minX) x = 2 * minX - x
    else if (x > maxX) x = 2 * maxX - x
    x = Math.min(maxX - 1, Math.max(minX + 1, x))
    const base = roofAt(x)
    f.x[i] = x
    f.base[i] = base
    f.life[i] = 3.5 + 4 * rand()
    if (spread) {
      // At seeding the plume is already standing: embers at every height and age.
      const age = rand()
      f.age[i] = age * f.life[i]
      f.y[i] = base - 3 - (base - minY) * 0.92 * age * (0.55 + 0.45 * rand())
    } else {
      // Off the stone: a thin line of sparks along the cornice.
      f.age[i] = 0
      f.y[i] = base - 1 - rand() * 7
    }
    f.vx[i] = (rand() - 0.5) * 0.4
    f.vy[i] = -(0.45 + 0.45 * rand()) * LAYERS[z].speed
    if (f.y[i] < minY) f.y[i] = minY + 1
    if (inHole(f.x[i], f.y[i])) confine(f, i, f.x[i], f.y[i], bounds.roofY)
  }

  const seedEmbers = (f) => {
    const n = Math.min(f.cap, emberCount())
    f.n = n
    measureBounds()
    for (let i = 0; i < n; i++) {
      f.z[i] = layerOf(rand(), LAYERS)
      f.p[i] = i * 2.39996
      // Flicker: five to ten a second, slower for the far layer.
      f.w[i] = TAU * (5 + 5 * rand()) * LAYERS[f.z[i]].beat
      f.s[i] = 0.8 + 0.4 * rand()
      spawnEmber(f, i, true)
    }
    for (let i = 0; i < n; i++) confine(f, i, f.x[i], f.y[i], bounds.roofY)
  }

  const stepEmbers = (f, dt, k) => {
    const t = state.clock
    const secs = dt / 1000
    const energy = state.energy
    // The embers' sky runs from the top of the sky down to the roof's lowest point.
    const { minX, maxX, minY, roofY: maxY } = bounds
    const { x: X, y: Y, vx: VX, vy: VY, z: Z, p: P, s: S, age: AGE, life: LIFE, base: BASE, nb, nbD, grid } = f
    const pointer = state.pointer

    // With a speaker on the floor the embers gather and wheel just above the temple.
    const heartX = bounds.heartX
    const heartY = minY + (bounds.maxY - minY) * 0.62
    const flowScale = 240 * (1 + 0.4 * energy)
    const cell = EMBER.cell

    gridBuild(grid, X, Y, f.n)
    for (let i = 0; i < f.n; i++) {
      AGE[i] += secs
      const xi = X[i]
      const yi = Y[i]
      // Burnt out, or risen to the top of the sky: born again on the roof.
      if (AGE[i] > LIFE[i] || yi < minY + 3) {
        spawnEmber(f, i, false)
        continue
      }
      const zi = Z[i]
      const layer = LAYERS[zi]
      const m = gridNeighbours(grid, X, Y, i, cell, nb, nbD, EMBER.neighbours)
      let avx = 0
      let avy = 0
      let sx = 0
      let sy = 0
      for (let q = 0; q < m; q++) {
        const j = nb[q]
        const d2 = nbD[q]
        avx += VX[j]
        avy += VY[j]
        if (d2 < 196) {
          const dx = X[j] - xi
          const dy = Y[j] - yi
          sx -= dx / (d2 + 4)
          sy -= dy / (d2 + 4)
        }
      }
      let fx = sx * 0.8
      let fy = sy * 0.8
      if (m > 0) {
        // The air carries neighbours together a little.
        fx += (avx / m - VX[i]) * 0.02
        fy += (avy / m - VY[i]) * 0.02
      }

      const wobble = Math.sin(t * 1.9 + P[i]) * 0.1
      fx += -VY[i] * wobble
      fy += VX[i] * wobble

      // The warm air rises and cools: strong off the roof, slack near the top.
      const height = (BASE[i] - yi) / Math.max(24, BASE[i] - minY)
      const rise = (0.95 - 0.55 * height) * layer.speed * S[i] * (1 - 0.6 * energy)
      fy += (-rise - VY[i]) * 0.03

      // Ride the current: it sways and curls the plume.
      const u = xi * 0.0046 + t * 0.27
      const v = yi * 0.0061 - t * 0.19
      const w = (xi + yi) * 0.0023 + t * 0.13
      const cw = 0.6 * 0.0023 * Math.cos(w)
      const dPsiDx = 0.0046 * Math.cos(u) * Math.cos(v) + cw
      const dPsiDy = -0.0061 * Math.sin(u) * Math.sin(v) + cw
      fx += (dPsiDy * flowScale * layer.speed - VX[i]) * 0.025
      fy += -dPsiDx * flowScale * 0.35 * layer.speed * 0.025

      if (energy > 0.01) {
        const dx = xi - heartX
        const dy = yi - heartY
        const d = Math.sqrt(dx * dx + dy * dy) + 1
        fx += ((-dy / d) * 0.06 - (dx / d) * 0.012) * energy
        fy += ((dx / d) * 0.06 - (dy / d) * 0.012) * energy
      }

      // Soft walls at the sides.
      if (xi < minX + 12) fx += (minX + 12 - xi) * 0.01
      else if (xi > maxX - 12) fx -= (xi - maxX + 12) * 0.01

      if (hole.on && inHole(xi, yi)) {
        const up = yi - hole.y0
        const down = hole.y1 - yi
        if (up < down || hole.y1 >= maxY) fy -= 0.2
        else fy += 0.2
      }

      if (pointer.active) {
        const dx = xi - pointer.x
        const dy = yi - pointer.y
        const d = Math.sqrt(dx * dx + dy * dy)
        if (d < 150) {
          const push = (1 - d / 150) * 0.9
          fx += (dx / (d + 0.01)) * push
          fy += (dy / (d + 0.01)) * push
        }
      }

      let nvx = VX[i] + fx * k
      let nvy = VY[i] + fy * k
      const maxSpeed = EMBER.maxSpeed * layer.speed * (1 + 0.3 * energy)
      const speed = Math.sqrt(nvx * nvx + nvy * nvy) || 1
      if (speed > maxSpeed) {
        nvx *= maxSpeed / speed
        nvy *= maxSpeed / speed
      }
      let nx = xi + nvx * k
      let ny = yi + nvy * k
      const wasIn = xi >= minX - 1 && xi <= maxX + 1 && yi >= minY - 1 && yi <= maxY + 1
      if (wasIn) {
        if (nx < minX) { nx = minX; nvx = Math.abs(nvx) }
        else if (nx > maxX) { nx = maxX; nvx = -Math.abs(nvx) }
        if (ny < minY) { ny = minY; nvy = Math.abs(nvy) }
        else if (ny > maxY) { ny = maxY; nvy = -Math.abs(nvy) }
      }
      if (hole.on && inHole(nx, ny) && !inHole(xi, yi)) {
        if (xi <= hole.x0 || xi >= hole.x1) { nx = xi; nvx = -nvx }
        else { ny = yi; nvy = -nvy }
      }
      X[i] = nx
      Y[i] = ny
      VX[i] = nvx
      VY[i] = nvy
    }
  }

  // ---- the flocks ---------------------------------------------------------

  const ensure = (name) => {
    let f = state.flocks[name]
    if (!f) {
      f = state.flocks[name] = name === 'ancient' ? makeFlock(1500, STARLING.cell) : makeFlock(400, EMBER.cell)
    }
    if (!f.seeded) {
      gridResize(f.grid, state.width, state.height)
      measureBounds()
      measureHole()
      if (name === 'ancient') {
        seedStarlings(f)
        seedMotes()
      } else {
        seedEmbers(f)
      }
      f.seeded = true
      state.seeds++
      prewarm(f, name)
    }
    return f
  }

  // Let a freshly seeded flock find its shape before anyone sees it.
  const prewarm = (f, name, steps = name === 'ancient' ? 140 : 80) => {
    const k = 1
    for (let i = 0; i < steps; i++) {
      if (name === 'ancient') {
        stepStarlings(f, 16.67, k)
        stepMotes(k)
      } else {
        stepEmbers(f, 16.67, k)
      }
    }
  }

  // Advance by dt milliseconds; intensity 0..1 is how strongly a speaker holds the floor.
  const step = (dt, intensity = 0) => {
    const k = dt / 16.67
    state.clock += dt / 1000
    state.energy += (intensity - state.energy) * Math.min(1, 0.02 * k)
    const target = state.era === 'now' ? 1 : 0
    if (state.mix !== target) {
      const d = dt / 1200
      state.mix = target > state.mix ? Math.min(target, state.mix + d) : Math.max(target, state.mix - d)
    }
    measureBounds()
    measureHole()
    if (state.mix < 1) {
      const f = ensure('ancient')
      stepStarlings(f, dt, k)
      stepMotes(k)
    }
    if (state.mix > 0) stepEmbers(ensure('now'), dt, k)
  }

  // ---- drawing ------------------------------------------------------------

  const rgba = (c, a) => `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${a.toFixed(3)})`
  // Style strings are made once, never per frame.
  const STARLING_STYLE = rgba(PALETTES.ancient.core, 1)
  // Per shade (its heat) and depth layer: the hotter, the whiter and brighter.
  const EMBER_CORE = EMBER_SHADES.map((q, h) => LAYERS.map((l) => rgba(PALETTES.now.core[h], l.alpha * q)))
  const EMBER_GLOW = EMBER_SHADES.map((q, h) => LAYERS.map((l) => rgba(PALETTES.now.glow[h], l.alpha * q * 0.2)))
  const EMBER_HALO = EMBER_SHADES.map((q, h) => LAYERS.map((l) => rgba(PALETTES.now.glow[h], l.alpha * q * 0.075)))
  let moteSprite = null

  const makeMoteSprite = (ctx) => {
    const doc = ctx.canvas && ctx.canvas.ownerDocument
    if (!doc) return null
    const c = doc.createElement('canvas')
    c.width = c.height = 32
    const g = c.getContext('2d')
    const [r, gg, b] = PALETTES.ancient.mote
    const grad = g.createRadialGradient(16, 16, 0, 16, 16, 16)
    grad.addColorStop(0, `rgba(${r}, ${gg}, ${b}, 1)`)
    grad.addColorStop(0.35, `rgba(${r}, ${gg}, ${b}, 0.55)`)
    grad.addColorStop(1, `rgba(${r}, ${gg}, ${b}, 0)`)
    g.fillStyle = grad
    g.fillRect(0, 0, 32, 32)
    return c
  }

  const drawStarlings = (ctx, f, fade) => {
    const t = state.clock
    const { rx: RX, ry: RY, z: Z, p: P, w: Wb, shade: SH } = f
    // Each bird's shade this frame: its depth layer and a twinkle of wingbeat.
    for (let i = 0; i < f.n; i++) {
      SH[i] = hole.on && inHole(RX[i], RY[i]) ? -1 : Z[i] * 2 + (Math.sin(t * Wb[i] + P[i]) > 0.35 ? 1 : 0)
    }
    ctx.globalCompositeOperation = 'source-over'
    ctx.fillStyle = STARLING_STYLE
    const lift = 0.9 + 0.1 * state.energy
    for (let z = 0; z < STARLING_LAYERS.length; z++) {
      const layer = STARLING_LAYERS[z]
      const size = layer.size
      const half = size / 2
      for (let q = 0; q < TWINKLE.length; q++) {
        const want = z * 2 + q
        ctx.beginPath()
        let any = false
        for (let i = 0; i < f.n; i++) {
          if (SH[i] !== want) continue
          ctx.rect(RX[i] - half, RY[i] - half, size, size)
          any = true
        }
        if (!any) continue
        ctx.globalAlpha = Math.min(1, layer.alpha * TWINKLE[q] * lift * fade)
        ctx.fill()
      }
    }
    // The falcon, a darker fleck on its stoop.
    const falcon = state.falcon
    if (falcon.active && falcon.x > bounds.minX && falcon.x < bounds.maxX && falcon.y > bounds.minY && falcon.y < bounds.maxY && !inHole(falcon.x, falcon.y)) {
      ctx.globalAlpha = 0.9 * fade
      ctx.beginPath()
      ctx.moveTo(falcon.x - falcon.dx * 1.1, falcon.y - falcon.dy * 1.1)
      ctx.lineTo(falcon.x, falcon.y)
      ctx.strokeStyle = STARLING_STYLE
      ctx.lineWidth = 1.9
      ctx.lineCap = 'round'
      ctx.stroke()
    }
    ctx.globalAlpha = 1
  }

  const drawMotes = (ctx, fade) => {
    const m = state.motes
    if (!m || !m.n) return
    if (!moteSprite) moteSprite = makeMoteSprite(ctx)
    if (!moteSprite) return
    const t = state.clock
    ctx.globalCompositeOperation = 'lighter'
    for (let i = 0; i < m.n; i++) {
      const x = m.x[i]
      const y = m.y[i]
      if (hole.on && inHole(x, y)) continue
      // Brighter in the heart of the beam; each mote turns and catches the light.
      const mid = beam.y0 + x * beam.slope
      const across = Math.abs(y - mid) / beam.half
      const inBeam = Math.max(0, 1 - across * across)
      const glint = 0.55 + 0.45 * Math.sin(t * 0.9 + m.p[i] * 3.1)
      const a = m.a[i] * inBeam * glint * fade
      if (a < 0.01) continue
      const r = m.r[i] * 3.2
      ctx.globalAlpha = a
      ctx.drawImage(moteSprite, x - r, y - r, r * 2, r * 2)
    }
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
  }

  // Each ember leaves the roof at its hottest and fades as it cools and
  // climbs; with its flicker that makes three heats per depth layer, nine
  // strokes in all.
  const emberShade = (f, i, t) => {
    const age = f.age[i]
    const life = f.life[i]
    // A spark leaves the stone at once, at its hottest.
    const glowIn = age < 0.12 ? age / 0.12 : 1
    const cool = age > life * 0.5 ? Math.max(0, (life - age) / (life * 0.5)) : 1
    const beat = 0.62 + 0.38 * Math.sin(t * f.w[i] + f.p[i])
    // Dimmer the higher it has climbed, so the plume thins into the dark.
    const height = Math.max(0, (f.base[i] - f.y[i]) / Math.max(24, f.base[i] - bounds.minY))
    const b = glowIn * cool * beat * (1 - 0.55 * height)
    return b < 0.1 ? -1 : b < 0.38 ? 0 : b < 0.68 ? 1 : 2
  }

  const drawEmbers = (ctx, f, fade) => {
    const t = state.clock
    const { x: X, y: Y, vx: VX, vy: VY, z: Z, shade: SH } = f
    for (let i = 0; i < f.n; i++) SH[i] = hole.on && inHole(X[i], Y[i]) ? -1 : emberShade(f, i, t)
    ctx.globalCompositeOperation = PALETTES.now.blend
    ctx.lineCap = 'round'
    const lift = (0.85 + 0.15 * state.energy) * fade
    for (let z = 0; z < LAYERS.length; z++) {
      const layer = LAYERS[z]
      for (let q = 0; q < EMBER_SHADES.length; q++) {
        ctx.beginPath()
        let any = false
        // The hottest sparks streak a little longer.
        const trail = layer.trail * (q === 2 ? 1.3 : 1)
        for (let i = 0; i < f.n; i++) {
          if (Z[i] !== z || SH[i] !== q) continue
          const x = X[i]
          const y = Y[i]
          ctx.moveTo(x - VX[i] * trail, y - VY[i] * trail)
          ctx.lineTo(x, y)
          any = true
        }
        if (!any) continue
        // A soft bloom, not a ring: a wide faint halo, a tighter glow, the core.
        ctx.globalAlpha = Math.min(1, lift)
        ctx.strokeStyle = EMBER_HALO[q][z]
        ctx.lineWidth = layer.size * 5.2 + 1.6 * state.energy
        ctx.stroke()
        ctx.strokeStyle = EMBER_GLOW[q][z]
        ctx.lineWidth = layer.size * 2.5 + 0.6 * state.energy
        ctx.stroke()
        ctx.strokeStyle = EMBER_CORE[q][z]
        ctx.lineWidth = layer.size
        ctx.stroke()
      }
    }
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
  }

  const draw = (ctx, _era, dpr = 1) => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, state.width, state.height)
    const mix = state.mix
    if (mix < 1 && state.flocks.ancient?.seeded) {
      drawMotes(ctx, 1 - mix)
      drawStarlings(ctx, state.flocks.ancient, 1 - mix)
    }
    if (mix > 0 && state.flocks.now?.seeded) drawEmbers(ctx, state.flocks.now, mix)
  }

  // ---- layout -------------------------------------------------------------

  // Mobile toolbars nudge the hero's height as the page scrolls, so a resize
  // rescales the flocks in place. Reseed only on first layout or when the
  // width crosses the phone cap (a phone rotating, a window snapping wide).
  const resize = (nextWidth, nextHeight) => {
    const prevWidth = state.width
    const prevHeight = state.height
    const crossedCap = !count && (prevWidth < PHONE) !== (nextWidth < PHONE)
    state.width = nextWidth
    state.height = nextHeight
    measureBounds()
    measureHole()
    const reseed = !(prevWidth >= 2) || !(prevHeight >= 2) || crossedCap
    const sx = reseed ? 1 : nextWidth / prevWidth
    const sy = reseed ? 1 : nextHeight / prevHeight
    for (const name of ['ancient', 'now']) {
      const f = state.flocks[name]
      if (!f) continue
      gridResize(f.grid, nextWidth, nextHeight)
      if (reseed) {
        f.seeded = false
        continue
      }
      if (sx !== 1 || sy !== 1) {
        for (let i = 0; i < f.n; i++) {
          f.x[i] *= sx
          f.y[i] *= sy
          f.rx[i] *= sx
          f.ry[i] *= sy
          f.base[i] *= sy
        }
      }
    }
    if (state.motes) {
      measureBeam()
      if (reseed) {
        state.motes.n = 0
      } else {
        for (let i = 0; i < state.motes.n; i++) {
          state.motes.x[i] *= sx
          state.motes.y[i] *= sy
        }
      }
    }
    // The flock on screen is seeded again straight away.
    ensure(state.mix < 0.5 ? 'ancient' : 'now')
  }

  const setPointer = (x, y, active = true) => {
    state.pointer.x = x
    state.pointer.y = y
    state.pointer.active = active
  }

  // Where the sky is, as fractions of the canvas. The flock drifts to it.
  const setRegion = (next) => {
    state.region = { ...DEFAULT_REGION, ...(next || {}) }
    measureBounds()
    measureBeam()
  }

  // A rectangle in canvas pixels ({x, y, w, h}) the flock keeps out of, or null.
  const setAvoid = (rect) => {
    state.avoid = rect && rect.w > 0 && rect.h > 0 ? { x: rect.x, y: rect.y, w: rect.w, h: rect.h } : null
    measureHole()
  }

  // Change era: the flocks cross-fade over a second, or at once when instant
  // (reduced motion, paused, off screen).
  const setEra = (next, instant = false) => {
    state.era = next === 'now' ? 'now' : 'ancient'
    ensure(state.era)
    if (instant) state.mix = state.era === 'now' ? 1 : 0
  }

  measureBounds()
  measureHole()
  ensure(state.era)
  return { state, step, draw, resize, setPointer, setRegion, setAvoid, setEra }
}
