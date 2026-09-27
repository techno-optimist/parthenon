// Run: cd frontend && node --test src/parthenon/descent.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  clamp01,
  trackProgress,
  passage,
  ramp,
  smoothstep,
  sceneSummary,
  coverPoint,
  climbTime,
  lapseYear,
  LAPSE_LANDSCAPE,
  LAPSE_PORTRAIT,
  cityPunctuation,
  renderScroll,
  smoothPath,
  firstClause,
  createDescent,
  afterIdle,
  subscribe
} from './descent.js'
import { speakers } from './speakers.js'
import { arrivals } from './arrivals/index.js'

test('clamp01 keeps numbers in 0..1 and turns anything else into 0', () => {
  assert.equal(clamp01(-0.2), 0)
  assert.equal(clamp01(0.4), 0.4)
  assert.equal(clamp01(3), 1)
  assert.equal(clamp01(NaN), 0)
  assert.equal(clamp01(Infinity), 0)
  assert.equal(clamp01(undefined), 0)
})

test('trackProgress runs 0..1 over the scroll a pinned track allows', () => {
  // A 220vh track on a 900px screen: 1980px tall, 1080px of scroll.
  assert.equal(trackProgress(0, 1980, 900), 0)
  assert.equal(trackProgress(120, 1980, 900), 0, 'not reached yet')
  assert.equal(trackProgress(-540, 1980, 900), 0.5)
  assert.equal(trackProgress(-1080, 1980, 900), 1)
  assert.equal(trackProgress(-1600, 1980, 900), 1, 'past the end')
  // A phone: 160vh of 844px.
  assert.ok(Math.abs(trackProgress(-253.2, 1350.4, 844) - 0.5) < 1e-9)
})

test('trackProgress on a track no taller than the screen is a step', () => {
  assert.equal(trackProgress(0, 900, 900), 0)
  assert.equal(trackProgress(-1, 900, 900), 1)
  assert.equal(trackProgress(-10, 0, 900), 1)
})

test('passage runs 0..1 as a section crosses the screen', () => {
  assert.equal(passage(900, 600, 900), 0, 'top at the bottom edge')
  assert.equal(passage(150, 600, 900), 0.5, 'centred')
  assert.equal(passage(-600, 600, 900), 1, 'bottom at the top edge')
  assert.equal(passage(2000, 600, 900), 0)
  assert.equal(passage(-2000, 600, 900), 1)
  assert.equal(passage(0, 0, 0), 0)
})

const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, msg || `${a} is not ${b}`)

test('ramp and smoothstep open a window on the descent', () => {
  assert.equal(ramp(0.2, 0.35, 0.75), 0)
  near(ramp(0.55, 0.35, 0.75), 0.5)
  assert.equal(ramp(0.9, 0.35, 0.75), 1)
  assert.equal(ramp(0.5, 0.5, 0.5), 1)
  assert.equal(ramp(0.4, 0.5, 0.5), 0)
  assert.equal(smoothstep(0.35, 0.75, 0.35), 0)
  near(smoothstep(0.35, 0.75, 0.55), 0.5)
  assert.equal(smoothstep(0.35, 0.75, 0.75), 1)
  // eased: slower than linear near the edges
  assert.ok(smoothstep(0, 1, 0.1) < 0.1)
  assert.ok(smoothstep(0, 1, 0.9) > 0.9)
  // monotonic
  let last = -1
  for (let x = 0; x <= 1.0001; x += 0.05) {
    const v = smoothstep(0.2, 0.8, x)
    assert.ok(v >= last)
    last = v
  }
})

test('sceneSummary keeps the first sentences, with their closing marks', () => {
  assert.equal(sceneSummary('One. Two? Three!'), 'One. Two?')
  assert.equal(sceneSummary('One. Two? Three!', 1), 'One.')
  assert.equal(sceneSummary('He said “Enough.” Then left. Later.'), 'He said “Enough.” Then left.')
  assert.equal(sceneSummary('No stop at all'), 'No stop at all')
  assert.equal(sceneSummary(''), '')
  assert.equal(sceneSummary(null), '')
  assert.equal(sceneSummary('  Spaced   out.\n Next   one.  More. '), 'Spaced out. Next one.')
  assert.equal(sceneSummary('雅典判了他死刑。城邦如何谈论？谁会改变主意？'), '雅典判了他死刑。城邦如何谈论？')
})

test('every speaker has a two sentence scene', () => {
  for (const s of speakers) {
    const summary = sceneSummary(s.question, 2)
    assert.ok(summary.length > 40, `${s.id} summary too short`)
    assert.ok(summary.length < s.question.length, `${s.id} summary is the whole question`)
    assert.ok(/[.?!]$/.test(summary), `${s.id} summary ends mid-sentence`)
    assert.ok(!summary.includes('—'), 'no em-dashes')
  }
})

test('coverPoint follows object-fit: cover', () => {
  const img = { w: 2560, h: 1084 }
  // A 1440x900 box: the height fills, the width overflows.
  const box = { w: 1440, h: 900 }
  const scale = 900 / 1084
  const centre = coverPoint(1280, 542, box, img, { x: 0.5, y: 0.5 })
  near(centre.x, 720)
  near(centre.y, 450)
  near(centre.scale, scale)
  const left = coverPoint(0, 0, box, img, { x: 0, y: 0.5 })
  near(left.x, 0, 'object-position 0%: the left edge stays')
  const right = coverPoint(2560, 1084, box, img, { x: 1, y: 0.5 })
  near(right.x, 1440, 'object-position 100%: the right edge stays')
  near(right.y, 900)
  // A phone: the width fills a wide box.
  const wide = coverPoint(512, 0, { w: 390, h: 300 }, { w: 1024, h: 1280 }, { x: 0.5, y: 0.4 })
  near(wide.scale, 390 / 1024)
  near(wide.y, -(1280 * (390 / 1024) - 300) * 0.4)
  assert.deepEqual(coverPoint(1, 1, { w: 0, h: 0 }, img), { x: 0, y: 0, scale: 0 })
})

test('climbTime carries the camera from where it stood to the last frame', () => {
  assert.equal(climbTime(0, 0, 10), 0)
  assert.equal(climbTime(1, 0, 10), 10)
  near(climbTime(0.35, 0, 10, 0.7), 5)
  assert.equal(climbTime(0.9, 0, 10, 0.7), 10, 'held on the last frame')
  // The climb had reached 4 s when the visitor began to scroll.
  assert.equal(climbTime(0, 4, 10, 0.7), 4, 'no jump back at the top')
  near(climbTime(0.35, 4, 10, 0.7), 7)
  assert.equal(climbTime(0.5, 12, 10), 10, 'a start past the end is the end')
  assert.equal(climbTime(0.5, 3, 0), 0, 'no duration yet')
})

test('lapseYear runs from 399 BC to 2026 with no year zero', () => {
  assert.equal(lapseYear(0), -399)
  assert.equal(lapseYear(1), 2026)
  assert.equal(lapseYear(-1), -399)
  assert.equal(lapseYear(2), 2026)
  const seen = new Set()
  for (let f = 0; f <= 1; f += 0.0001) seen.add(lapseYear(f))
  assert.ok(!seen.has(0), 'never year 0')
  let last = -Infinity
  for (let f = 0; f <= 1.00001; f += 0.01) {
    const y = lapseYear(f)
    assert.ok(y >= last)
    last = y
  }
})

test('lapseYear follows each file: slow while Athena stands, fast through the centuries, slow for the cranes', () => {
  for (const [name, table] of [['landscape', LAPSE_LANDSCAPE], ['portrait', LAPSE_PORTRAIT]]) {
    assert.equal(lapseYear(0, table), -399, `${name} starts in 399 BC`)
    assert.equal(lapseYear(1, table), 2026, `${name} ends in 2026`)
    assert.equal(lapseYear(-3, table), -399)
    assert.equal(lapseYear(3, table), 2026)
    let last = -Infinity
    const seen = new Set()
    for (let f = 0; f <= 1.00001; f += 0.0005) {
      const y = lapseYear(f, table)
      assert.ok(y >= last, `${name} runs forward at ${f.toFixed(4)}`)
      assert.notEqual(y, 0, `${name} never shows year 0`)
      seen.add(y)
      last = y
    }
    // every anchor is met exactly
    for (const [f, year] of table) assert.equal(lapseYear(f, table), year, `${name} anchor ${f}`)
    // reversed file: f' = 1 - f runs back from 2026
    assert.equal(lapseYear(1 - 0, table), 2026)
  }
  // Landscape: Athena still stands at 2.75 s (f 0.342) and has gone by 3.25 s (f 0.404);
  // the first crane shows at 4.0 s (f 0.497).
  assert.ok(lapseYear(2.75 / 8.0417, LAPSE_LANDSCAPE) < 465)
  assert.ok(lapseYear(3.25 / 8.0417, LAPSE_LANDSCAPE) >= 465)
  assert.ok(lapseYear(3.75 / 8.0417, LAPSE_LANDSCAPE) < 1975, 'modern dress, no crane yet')
  assert.ok(lapseYear(4.0 / 8.0417, LAPSE_LANDSCAPE) >= 1975, '1975 at the first crane')
  assert.ok(lapseYear(4.0 / 8.0417, LAPSE_LANDSCAPE) < 1990)
  // Portrait: Athena at 2.5 s (f 0.311), fallen by 2.75 s; the crane at 3.25 s (f 0.404).
  assert.ok(lapseYear(2.5 / 8.0417, LAPSE_PORTRAIT) < 465)
  assert.ok(lapseYear(3.25 / 8.0417, LAPSE_PORTRAIT) >= 1975, '1975 at the first crane')
  assert.ok(lapseYear(3.0 / 8.0417, LAPSE_PORTRAIT) < 1975)
  // Without a table the clock is even, as before.
  assert.equal(lapseYear(0.5), lapseYear(0.5, null))
})

test('cityPunctuation prints no long dashes', () => {
  assert.equal(
    cityPunctuation('- **Dee Harrow**, 54, union steward — speaks from the open floor — and distrusts him.'),
    '- **Dee Harrow**, 54, union steward: speaks from the open floor, and distrusts him.'
  )
  assert.equal(cityPunctuation('word\u2014word'), 'word, word')
  assert.equal(cityPunctuation('\u2014 Plato'), 'Plato')
  assert.equal(cityPunctuation('he paused \u2014'), 'he paused')
  assert.equal(cityPunctuation('No dashes here.'), 'No dashes here.')
  assert.equal(cityPunctuation(null), '')
})

test('every prepared scroll unrolls at the bema without a long dash', () => {
  const scrolls = [...arrivals, ...speakers].filter((item) => item.seed)
  assert.ok(scrolls.length >= 16, 'the arrivals and the philosophers')
  for (const item of scrolls) {
    const html = renderScroll(item.seed)
    assert.ok(html.length > 200, `${item.id} renders`)
    assert.ok(!html.includes('\u2014'), `${item.id} shows a long dash`)
    assert.ok(!/<p>\s*<\/p>/.test(html), `${item.id} has an empty paragraph`)
  }
  assert.equal(renderScroll('# Title\n\n- **A** \u2014 one\n- B\n\nPlain *text* <b>'), '<h3>Title</h3><ul><li><strong>A</strong>: one</li><li>B</li></ul><p>Plain <em>text</em> &lt;b&gt;</p>')
  assert.equal(renderScroll(''), '')
})

test('the scroll on the bema reads each line as the Hearing does (undash)', () => {
  // Spaced short dashes too, and the first dash of each line is its colon.
  assert.equal(renderScroll('- **A** – one – two'), '<ul><li><strong>A</strong>: one, two</li></ul>')
  assert.equal(renderScroll('Plato — backs the labels\nAristotle — doubts them'), '<p>Plato: backs the labels Aristotle: doubts them</p>')
  // A dash at either end of a line goes; it never becomes a stray colon.
  assert.equal(renderScroll('  — Plato'), '<p>Plato</p>')
  assert.equal(renderScroll('he paused –'), '<p>he paused</p>')
  // Ranges without spaces and hyphens are left alone; the long dash is not.
  assert.equal(renderScroll('399–347 BC, well-known'), '<p>399–347 BC, well-known</p>')
  assert.equal(renderScroll('word—word'), '<p>word, word</p>')
  for (const item of [...arrivals, ...speakers].filter((x) => x.seed)) {
    const html = renderScroll(item.seed)
    assert.ok(!/ [—–] /.test(html), `${item.id} keeps a spaced dash`)
    assert.ok(!/<(p|li|h\d)>:/.test(html), `${item.id} opens a line on a colon`)
  }
})

test('smoothPath passes through every station', () => {
  assert.equal(smoothPath([]), '')
  assert.equal(smoothPath([{ x: 1, y: 2 }]), 'M1 2')
  const pts = [{ x: 0, y: 100 }, { x: 50, y: 60 }, { x: 120, y: 40 }, { x: 200, y: 0 }]
  const d = smoothPath(pts)
  assert.ok(d.startsWith('M0 100 C'))
  const ends = [...d.matchAll(/C[^C]*? (-?[\d.]+) (-?[\d.]+)(?= C|$)/g)].map((m) => [Number(m[1]), Number(m[2])])
  assert.deepEqual(ends, [[50, 60], [120, 40], [200, 0]])
  assert.ok(!d.includes('NaN'))
  assert.equal(smoothPath([{ x: NaN, y: 1 }, { x: 3, y: 4 }]), 'M3 4')
})

test('firstClause makes a one-line gloss from the old copy', () => {
  assert.equal(firstClause('The city takes in the words: who is named, who is connected to whom, what was claimed.'), 'The city takes in the words')
  assert.equal(firstClause('Citizens are summoned from the crowd, each with a past, a temperament and a stake.'), 'Citizens are summoned from the crowd')
  assert.equal(firstClause('They argue in the open square and in the long threads of the Stoa, hour after hour.'), 'They argue in the open square')
  assert.equal(firstClause('The Scribe walks the city afterwards and writes down what Athens came to believe.'), 'The Scribe walks the city afterwards')
  assert.equal(firstClause('Sit down with any citizen, or with the Scribe, and question them yourself.'), 'Sit down with any citizen')
  assert.equal(firstClause('城邦听取这些话语：谁被提及，谁与谁相连，说了些什么。'), '城邦听取这些话语')
  assert.equal(firstClause('他们在开阔的广场上、在柱廊的长篇讨论里争论，一小时又一小时。'), '他们在开阔的广场上')
  assert.equal(firstClause('Short.'), 'Short')
  assert.equal(firstClause(''), '')
  assert.equal(firstClause(null), '')
})

// A window that records its listeners and runs frames on demand.
const fakeWindow = () => {
  const listeners = {}
  const frames = []
  const timers = []
  const win = {
    scrollY: 0,
    innerHeight: 900,
    innerWidth: 1440,
    document: { readyState: 'complete' },
    addEventListener(type, fn, opts) {
      ;(listeners[type] ||= []).push({ fn, opts })
    },
    removeEventListener(type, fn) {
      listeners[type] = (listeners[type] || []).filter((l) => l.fn !== fn)
    },
    requestAnimationFrame(cb) {
      frames.push(cb)
      return frames.length
    },
    setTimeout(cb, ms) {
      timers.push({ cb, ms })
      return timers.length
    },
    clearTimeout(id) {
      if (timers[id - 1]) timers[id - 1].cb = null
    },
    fire(type) {
      for (const l of [...(listeners[type] || [])]) l.fn()
    },
    flush() {
      const run = frames.splice(0)
      run.forEach((cb) => cb(0))
      return run.length
    },
    runTimers() {
      const run = timers.splice(0)
      run.forEach((t) => t.cb && t.cb())
      return run.length
    }
  }
  return { win, listeners, frames, timers }
}

test('one passive listener serves every subscriber, once a frame', () => {
  const { win, listeners } = fakeWindow()
  const d = createDescent(win)
  const seen = { a: [], b: [] }
  const offA = d.subscribe((m) => seen.a.push(m.y))
  const offB = d.subscribe((m) => seen.b.push(m.y), { immediate: false })
  assert.equal(listeners.scroll.length, 1, 'one scroll listener for two subscribers')
  assert.equal(listeners.scroll[0].opts.passive, true)
  assert.deepEqual(seen.a, [0], 'immediate call on subscribe')
  assert.deepEqual(seen.b, [])

  win.scrollY = 100
  win.fire('scroll')
  win.scrollY = 180
  win.fire('scroll')
  win.fire('scroll')
  assert.equal(win.flush(), 1, 'three scroll events, one frame')
  assert.deepEqual(seen.a, [0, 180])
  assert.deepEqual(seen.b, [180])

  win.fire('resize')
  win.flush()
  assert.equal(seen.a.length, 3, 'a resize measures again')

  offA()
  assert.equal(listeners.scroll.length, 1, 'still listening for b')
  offB()
  assert.equal(listeners.scroll.length, 0, 'the last one out removes the listener')
  assert.equal(listeners.resize.length, 0)
  assert.equal(d.count(), 0)
})

test('reads run before writes in each frame', () => {
  const { win } = fakeWindow()
  const d = createDescent(win)
  const log = []
  d.subscribe(() => {
    log.push('read a')
    return () => log.push('write a')
  }, { immediate: false })
  d.subscribe(() => {
    log.push('read b')
    return () => log.push('write b')
  }, { immediate: false })
  win.fire('scroll')
  win.flush()
  assert.deepEqual(log, ['read a', 'read b', 'write a', 'write b'])
  const now = []
  d.subscribe(() => () => now.push('written at once'))
  assert.deepEqual(now, ['written at once'], 'an immediate subscribe writes too')
})

test('a subscriber that throws does not stop the others', () => {
  const { win } = fakeWindow()
  const d = createDescent(win)
  const seen = []
  d.subscribe(() => {
    throw new Error('boom')
  })
  d.subscribe((m) => seen.push(m.vh))
  win.fire('scroll')
  win.flush()
  assert.deepEqual(seen, [900, 900])
})

test('subscribe ignores what is not a function', () => {
  const { win, listeners } = fakeWindow()
  const d = createDescent(win)
  const off = d.subscribe(null)
  assert.equal(typeof off, 'function')
  assert.equal(listeners.scroll, undefined)
})

test('the shared subscribe is harmless without a window', () => {
  const off = subscribe(() => {})
  assert.equal(typeof off, 'function')
  off()
})

test('afterIdle waits for load, then the delay, then idle', () => {
  const { win, listeners, timers } = fakeWindow()
  win.document.readyState = 'loading'
  let fired = 0
  let idleCb = null
  win.requestIdleCallback = (cb) => {
    idleCb = cb
    return 7
  }
  afterIdle(win, 4000, () => fired++)
  assert.equal(timers.length, 0, 'nothing before load')
  win.fire('load')
  assert.equal(listeners.load.length, 0, 'load listener removed')
  assert.equal(timers[0].ms, 4000)
  win.runTimers()
  assert.equal(fired, 0, 'waits for idle')
  idleCb()
  idleCb()
  assert.equal(fired, 1, 'fires once')
})

test('afterIdle falls back to a timer and can be cancelled', () => {
  const { win } = fakeWindow()
  let fired = 0
  afterIdle(win, 4000, () => fired++)
  win.runTimers()
  assert.equal(fired, 1, 'no requestIdleCallback: fires after the delay')

  const cancel = afterIdle(win, 4000, () => fired++)
  cancel()
  win.runTimers()
  assert.equal(fired, 1, 'cancelled')
  assert.equal(typeof afterIdle(null, 10, () => {}), 'function')
})
