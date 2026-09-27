// node --test src/parthenon/swarm.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { createGrid, gridResize, gridBuild, gridNeighbours, createSwarm, ROOF_MARGIN } from './swarm.js'

// A deterministic scatter, with some points outside the grid on every side.
const scatter = (n, width, height, seed = 7) => {
  let s = seed
  const rand = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646
  const xs = new Float32Array(n)
  const ys = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    // Clusters and sparse sky, like a flock.
    const clump = rand() < 0.6
    xs[i] = clump ? width * 0.4 + (rand() - 0.5) * 80 : -40 + rand() * (width + 80)
    ys[i] = clump ? height * 0.3 + (rand() - 0.5) * 40 : -40 + rand() * (height + 80)
  }
  return { xs, ys }
}

const brute = (xs, ys, n, i, r) => {
  const found = []
  for (let j = 0; j < n; j++) {
    if (j === i) continue
    const dx = xs[j] - xs[i]
    const dy = ys[j] - ys[i]
    if (dx * dx + dy * dy <= r * r) found.push(j)
  }
  return found.sort((a, b) => a - b)
}

test('the grid finds the same neighbours as brute force', () => {
  for (const [cell, r] of [[12, 12], [12, 7.5], [36, 36]]) {
    const width = 640
    const height = 360
    const n = 1500
    const { xs, ys } = scatter(n, width, height, cell)
    const grid = createGrid(n, cell)
    gridResize(grid, width, height)
    gridBuild(grid, xs, ys, n)
    const out = new Uint32Array(n)
    const outD = new Float32Array(n)
    let pairs = 0
    for (let i = 0; i < n; i++) {
      const m = gridNeighbours(grid, xs, ys, i, r, out, outD, n)
      const got = Array.from(out.subarray(0, m)).sort((a, b) => a - b)
      assert.deepEqual(got, brute(xs, ys, n, i, r), `bird ${i}, cell ${cell}, radius ${r}`)
      for (let q = 0; q < m; q++) {
        const dx = xs[out[q]] - xs[i]
        const dy = ys[out[q]] - ys[i]
        assert.ok(Math.abs(outD[q] - (dx * dx + dy * dy)) < 1e-3)
      }
      pairs += m
    }
    assert.ok(pairs > n, 'the scatter has neighbours to find')
  }
})

test('a capped query stops at the cap', () => {
  const n = 400
  const { xs, ys } = scatter(n, 200, 200, 3)
  const grid = createGrid(n, 12)
  gridResize(grid, 200, 200)
  gridBuild(grid, xs, ys, n)
  const out = new Uint32Array(n)
  for (let i = 0; i < n; i++) {
    const all = brute(xs, ys, n, i, 12).length
    assert.equal(gridNeighbours(grid, xs, ys, i, 12, out, null, 5), Math.min(5, all))
  }
})

const REGION = { top: 0.05, bottom: 0.45, left: 0.2, right: 0.92 }

// The birds keep to the sky; the embers' sky reaches down to the roof below it.
const inside = (swarm, flock, test, floor = swarm.state.region.bottom) => {
  const { width, height, region } = swarm.state
  const minX = width * region.left
  const maxX = width * region.right
  const minY = height * region.top
  const maxY = height * floor
  for (let i = 0; i < flock.n; i++) {
    for (const [x, y] of [[flock.x[i], flock.y[i]], [flock.rx[i], flock.ry[i]]]) {
      assert.ok(x >= minX - 1e-3 && x <= maxX + 1e-3 && y >= minY - 1e-3 && y <= maxY + 1e-3, `${test}: bird ${i} at ${x.toFixed(1)}, ${y.toFixed(1)}`)
    }
  }
}

test('the starlings stay inside the sky after many steps', () => {
  for (const [width, height] of [[1440, 900], [390, 844]]) {
    const swarm = createSwarm({ width, height, region: REGION })
    const flock = swarm.state.flocks.ancient
    assert.ok(flock.n >= 800 && flock.n <= 1500, `flock of ${flock.n}`)
    // Including a speaker taking the floor and a pointer in the sheet.
    for (let i = 0; i < 3000; i++) {
      if (i === 900) swarm.setPointer(width * 0.5, height * 0.25, true)
      if (i === 1300) swarm.setPointer(-9999, -9999, false)
      swarm.step(16.67, i > 1500 && i < 2400 ? 1 : 0)
      if (i % 250 === 0) inside(swarm, flock, `${width}px step ${i}`)
    }
    inside(swarm, flock, `${width}px end`)
  }
})

const settle = (flock) => {
  for (let i = 0; i < flock.n; i++) {
    flock.rx[i] = flock.x[i]
    flock.ry[i] = flock.y[i]
  }
}

test('the embers stay between the roof and the top of the sky', () => {
  const swarm = createSwarm({ width: 1440, height: 900, region: REGION, era: 'now' })
  const flock = swarm.state.flocks.now
  assert.ok(flock.n >= 250 && flock.n <= 400)
  for (let i = 0; i < 2000; i++) swarm.step(16.67, i > 800 && i < 1400 ? 1 : 0)
  settle(flock)
  inside(swarm, flock, 'embers', REGION.bottom + ROOF_MARGIN)
})

// A stand-in 2D context: drawing only records nothing, but it runs the shades.
const blankContext = () => {
  const noop = () => {}
  return new Proxy({ canvas: null }, { get: (o, k) => (k in o ? o[k] : noop), set: () => true })
}

test('the embers are born on the roof and leave it at their hottest', () => {
  // A phone, with the roofline given by the host a little under the sky.
  const width = 390
  const height = 844
  const region = { top: 0.05, bottom: 0.33, left: 0.04, right: 0.96, roof: 0.4 }
  const swarm = createSwarm({ width, height, region, era: 'now' })
  const flock = swarm.state.flocks.now
  const ctx = blankContext()
  const roofY = height * region.roof
  const skyY = height * region.bottom
  let born = 0
  let low = 0
  let lowHeat = 0
  let high = 0
  let highHeat = 0
  for (let i = 0; i < 1200; i++) {
    swarm.step(16.67, 0)
    if (i % 10) continue
    swarm.draw(ctx, 'now', 1)
    for (let j = 0; j < flock.n; j++) {
      const y = flock.y[j]
      assert.ok(y <= roofY + 1e-3, `ember ${j} under the roof at ${y.toFixed(1)}`)
      if (y > skyY) born++
      const u = (roofY - y) / (roofY - height * region.top)
      const heat = flock.shade[j]
      if (u < 0.2) { low++; lowHeat += heat }
      else if (u > 0.6) { high++; highHeat += heat }
    }
  }
  // Sparks do rise off the roof itself, below the birds' sky.
  assert.ok(born > 0, 'embers between the sky and the roof')
  // The plume is densest and hottest at the stone and thins and cools above.
  assert.ok(low > high * 1.5, `${low} low, ${high} high`)
  assert.ok(lowHeat / low > highHeat / Math.max(1, high) + 0.5, `heat ${(lowHeat / low).toFixed(2)} low, ${(highHeat / Math.max(1, high)).toFixed(2)} high`)
})

test('a host can place the fire: the plume rises from its roof and heart', () => {
  const width = 390
  const height = 844
  const region = { top: 0.05, bottom: 0.33, left: 0.04, right: 0.96, roof: 0.4, heart: 0.7 }
  const swarm = createSwarm({ width, height, region, era: 'now' })
  const flock = swarm.state.flocks.now
  let sum = 0
  let n = 0
  for (let i = 0; i < 600; i++) {
    swarm.step(16.67, 0)
    for (let j = 0; j < flock.n; j++) {
      // The sparks just off the stone.
      if (flock.age[j] < 0.1) {
        assert.ok(flock.y[j] > height * 0.4 - 20 && flock.y[j] <= height * 0.4 + 1e-3, `newborn at ${flock.y[j].toFixed(1)}`)
        assert.ok(flock.x[j] > width * 0.04 && flock.x[j] < width * 0.96)
        sum += flock.x[j]
        n++
      }
    }
  }
  assert.ok(n > 100, `${n} newborn sparks`)
  assert.ok(Math.abs(sum / n - width * 0.7) < width * 0.06, `plume centred at ${(sum / n).toFixed(1)}`)
})

test('the sparks follow a sloping roof and centre over its peak', () => {
  // A temple seen from its corner: the roof falls away to the left of the gable.
  const width = 390
  const height = 844
  const roof = [[0, 0.54], [0.71, 0.4], [1, 0.42]]
  const region = { top: 0.05, bottom: 0.37, left: 0.04, right: 0.96, roof }
  const swarm = createSwarm({ width, height, region, era: 'now' })
  const flock = swarm.state.flocks.now
  const roofAt = (x) => {
    const u = x / width
    const [a, b] = u <= roof[1][0] ? [roof[0], roof[1]] : [roof[1], roof[2]]
    return height * (a[1] + ((b[1] - a[1]) * (u - a[0])) / (b[0] - a[0]))
  }
  let sum = 0
  let n = 0
  let left = 0
  for (let i = 0; i < 900; i++) {
    swarm.step(16.67, 0)
    for (let j = 0; j < flock.n; j++) {
      // Never below the roof's lowest point; each spark leaves its own stretch of roof.
      assert.ok(flock.y[j] <= height * 0.54 + 1e-3)
      if (flock.age[j] < 0.05) {
        const y = roofAt(flock.x[j])
        assert.ok(Math.abs(flock.base[j] - y) < 1, `base ${flock.base[j].toFixed(1)} for roof ${y.toFixed(1)}`)
        assert.ok(flock.y[j] <= y + 1e-3 && flock.y[j] > y - 16, `newborn at ${flock.y[j].toFixed(1)}, roof ${y.toFixed(1)}`)
        if (flock.x[j] < width * 0.35) left++
        sum += flock.x[j]
        n++
      }
    }
  }
  assert.ok(n > 60 && left > 3, `${n} newborn, ${left} off the low end of the roof`)
  assert.ok(Math.abs(sum / n - width * 0.71) < width * 0.08, `plume centred at ${(sum / n).toFixed(1)}`)
})

test('the flock keeps out of the avoid rectangle', () => {
  // A headline that reaches up into the sky, on a desktop and on a phone.
  for (const [width, height, avoid] of [
    [1440, 900, { x: 60, y: 260, w: 700, h: 420 }],
    [390, 844, { x: 20, y: 200, w: 350, h: 420 }]
  ]) {
    for (const era of ['ancient', 'now']) {
      const swarm = createSwarm({ width, height, region: { ...REGION, left: 0.04, bottom: 0.5 }, era })
      swarm.setAvoid(avoid)
      const flock = swarm.state.flocks[era]
      const count = () => {
        let n = 0
        for (let i = 0; i < flock.n; i++) {
          const x = flock.x[i]
          const y = flock.y[i]
          if (x > avoid.x && x < avoid.x + avoid.w && y > avoid.y && y < avoid.y + avoid.h) n++
        }
        return n
      }
      for (let i = 0; i < 2500; i++) {
        swarm.step(16.67, 0)
        if (i > 600 && i % 100 === 0) assert.equal(count(), 0, `${era} ${width}px step ${i}`)
      }
      assert.equal(count(), 0, `${era} ${width}px end`)
    }
  }
})

test('a small resize keeps the flock; crossing to a phone reseeds it', () => {
  const swarm = createSwarm({ width: 1440, height: 900, region: REGION })
  for (let i = 0; i < 60; i++) swarm.step(16.67)
  const flock = swarm.state.flocks.ancient
  const seeds = swarm.state.seeds
  const x0 = flock.x[10]
  const y0 = flock.y[10]
  // A mobile toolbar sliding away: the birds are rescaled in place.
  swarm.resize(1440, 960)
  assert.equal(swarm.state.seeds, seeds)
  assert.ok(Math.abs(flock.x[10] - x0) < 1e-3)
  assert.ok(Math.abs(flock.y[10] - (y0 * 960) / 900) < 1e-2)
  // A phone: a new, smaller flock for the new sky.
  swarm.resize(390, 844)
  assert.equal(swarm.state.seeds, seeds + 1)
  assert.equal(flock.n, 800)
  inside(swarm, flock, 'after reseed')
})

test('birds a new layout strands outside the sky fly back in', () => {
  const swarm = createSwarm({ width: 1440, height: 900, region: REGION })
  const flock = swarm.state.flocks.ancient
  // The sky shrinks to its right half.
  swarm.setRegion({ ...REGION, left: 0.6 })
  for (let i = 0; i < 900; i++) swarm.step(16.67)
  inside(swarm, flock, 'new sky')
})

test('the era cross-fades and keeps each flock', () => {
  const swarm = createSwarm({ width: 1440, height: 900, region: REGION })
  const ancient = swarm.state.flocks.ancient
  swarm.setEra('now')
  assert.ok(swarm.state.flocks.now.seeded)
  for (let i = 0; i < 90; i++) swarm.step(16.67)
  assert.equal(swarm.state.mix, 1)
  swarm.setEra('ancient', true)
  assert.equal(swarm.state.mix, 0)
  assert.equal(swarm.state.flocks.ancient, ancient)
})

test('step() with 1200 birds is fast', () => {
  const swarm = createSwarm({ width: 1440, height: 900, region: REGION, count: 1200 })
  const flock = swarm.state.flocks.ancient
  assert.equal(flock.n, 1200)
  for (let i = 0; i < 200; i++) swarm.step(16.67) // warm the JIT
  const frames = 600
  const t0 = performance.now()
  for (let i = 0; i < frames; i++) swarm.step(16.67, i > 300 ? 1 : 0)
  const ms = (performance.now() - t0) / frames
  console.log(`# step() with 1200 starlings: ${ms.toFixed(3)} ms per frame`)
  assert.ok(ms < 2, `${ms.toFixed(3)} ms`)
})
