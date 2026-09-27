/*
 * The descent: the home read as one climb, from the foot of the Propylaea to
 * the temple, then down the steps to the philosophers and the bema.
 *
 * One passive scroll listener serves every subscriber, and it does its work
 * at most once a frame. A subscriber reads its own element's rectangle and
 * writes a CSS variable; CSS does the rest. Nothing here touches the DOM
 * beyond the window it is given, so the helpers run under node for tests.
 *
 * Contract
 *   clamp01(x)                          0..1, and 0 for anything not a number
 *   trackProgress(top, height, vh)      how far a pinned track has been scrolled, 0..1:
 *                                       0 while its top is at the top of the screen,
 *                                       1 when its bottom meets the bottom of the screen
 *   passage(top, height, vh)            how far a section has passed through the screen,
 *                                       0 as its top enters from below, 1 as its bottom leaves above
 *   ramp(x, from, to)                   linear 0..1 inside a window
 *   smoothstep(from, to, x)             the same window, eased at both ends
 *   sceneSummary(text, n)               the first n sentences of a scene's question
 *   coverPoint(x, y, box, img, pos)     where a point of an image drawn with object-fit:
 *                                       cover lands in its box, in box pixels
 *   coverSource(rect, box, img, pos)    the inverse: the image pixels under a box rectangle
 *   meanLuma(rgba)                      mean luma of canvas bytes, 0..1
 *   skyNeed(luma)                       how much night the lapse counter needs from its sky
 *   lapseSkyGuess(f, to)                the same guessed from the file's position, 0..1
 *   climbTime(p, from, duration, end)   the camera's time while the visitor scrolls: from
 *                                       `from` (where the climb stood) to the last frame
 *                                       at p = end
 *   lapseYear(f, anchors)               the year on screen f (0..1) through the time-lapse,
 *                                       read from a table of [f, year] measured on the file
 *                                       (LAPSE_LANDSCAPE, LAPSE_PORTRAIT); even pace without one
 *   cityPunctuation(line)               a prepared scroll's line as the city prints it: the
 *                                       first spaced dash a colon, any later one a comma
 *   renderScroll(markdown)              just enough Markdown for the scrolls, as HTML, each
 *                                       line through undash() as the Hearing prints it
 *   smoothPath(points)                  an SVG path through every point, as gentle curves
 *   firstClause(text, max)              a sentence's opening clause, for a one-line gloss
 *   createDescent(win)                  { subscribe(fn, { immediate }), count() } on a window
 *   subscribe(fn, opts)                 the page's one shared listener; returns unsubscribe.
 *                                       fn(metrics) reads the page; if it returns a
 *                                       function, that one writes, after every read
 *   afterIdle(win, delay, fn)           fn once the page has loaded, waited `delay` ms
 *                                       and gone idle; returns cancel
 */

import { undash } from './vocabulary.js'

export const clamp01 = (x) => (Number.isFinite(x) ? (x <= 0 ? 0 : x > 1 ? 1 : x) : 0)

export const trackProgress = (top, height, viewport) => {
  const run = height - viewport
  if (!(run > 0)) return top < 0 ? 1 : 0
  return clamp01(-top / run)
}

export const passage = (top, height, viewport) => {
  const span = viewport + height
  if (!(span > 0)) return 0
  return clamp01((viewport - top) / span)
}

export const ramp = (x, from, to) => {
  if (from === to) return x < from ? 0 : 1
  return clamp01((x - from) / (to - from))
}

export const smoothstep = (from, to, x) => {
  const t = ramp(x, from, to)
  return t * t * (3 - 2 * t)
}

// Sentences end at . ? ! (and 。？！ in Chinese), with any closing quote kept.
const SENTENCE = /[^.?!。？！]+(?:[.?!。？！]+["'”’」』)]*|$)/g

export const sceneSummary = (text, n = 2) => {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  if (!clean) return ''
  const parts = (clean.match(SENTENCE) || []).map((s) => s.trim()).filter(Boolean)
  const joiner = /[　-鿿]/.test(clean) ? '' : ' '
  return parts.slice(0, Math.max(1, n)).join(joiner)
}

// object-fit: cover with object-position px py (0..1): the image is scaled to
// fill the box and the overflow is split px : 1 - px (and py : 1 - py).
export const coverPoint = (x, y, box, img, pos = { x: 0.5, y: 0.5 }) => {
  const W = box?.w || 0
  const H = box?.h || 0
  if (!(W > 0 && H > 0 && img?.w > 0 && img?.h > 0)) return { x: 0, y: 0, scale: 0 }
  const scale = Math.max(W / img.w, H / img.h)
  const ox = (img.w * scale - W) * pos.x
  const oy = (img.h * scale - H) * pos.y
  return { x: x * scale - ox, y: y * scale - oy, scale }
}

// The inverse: the part of the image under a box rectangle { x, y, w, h },
// in image pixels, kept inside the image.
export const coverSource = (rect, box, img, pos = { x: 0.5, y: 0.5 }) => {
  const W = box?.w || 0
  const H = box?.h || 0
  if (!(W > 0 && H > 0 && img?.w > 0 && img?.h > 0 && rect)) return null
  const scale = Math.max(W / img.w, H / img.h)
  const ox = (img.w * scale - W) * pos.x
  const oy = (img.h * scale - H) * pos.y
  const x0 = Math.min(Math.max((rect.x + ox) / scale, 0), img.w)
  const y0 = Math.min(Math.max((rect.y + oy) / scale, 0), img.h)
  const x1 = Math.min(Math.max((rect.x + rect.w + ox) / scale, 0), img.w)
  const y1 = Math.min(Math.max((rect.y + rect.h + oy) / scale, 0), img.h)
  if (!(x1 - x0 >= 1 && y1 - y0 >= 1)) return null
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
}

// How bright a patch of picture is, 0 (black) to 1 (white): the mean luma of
// RGBA bytes, as read back from a canvas.
export const meanLuma = (data) => {
  const n = data ? Math.floor(data.length / 4) : 0
  if (!n) return 0
  let sum = 0
  for (let i = 0; i < n; i++) sum += 0.2126 * data[i * 4] + 0.7152 * data[i * 4 + 1] + 0.0722 * data[i * 4 + 2]
  return sum / n / 255
}

// How much night the time-lapse's counter needs from its sky: all of it over
// the white dawn of 399 BC, none once the footage has gone to blue hour.
export const skyNeed = (luma) => smoothstep(0.38, 0.86, luma)

// The same, guessed from where the file stands (0..1) when the picture cannot
// be read: the forward file loses its light steadily from about a fifth of the
// way in; the reversed one gains it back at the same pace.
export const lapseSkyGuess = (f, to = 'now') => {
  const x = to === 'ancient' ? 1 - clamp01(f) : clamp01(f)
  return 1 - smoothstep(0.22, 0.66, x)
}

export const climbTime = (p, from, duration, end = 1) => {
  if (!(duration > 0)) return 0
  const start = Math.min(Math.max(Number(from) || 0, 0), duration)
  return start + (duration - start) * ramp(p, 0, end)
}

// The time-lapse runs from the morning of 399 BC to an evening in 2026, but
// not at an even pace: the footage keeps the ancient light for a long while,
// loses Athena Promachos (carried off to Constantinople, about AD 465), races
// through the centuries and slows again for the scaffolds and the cranes of
// the restoration (1975 on). Each table is [f, year] pairs measured on its
// own file, so the counter never reads the Middle Ages under a crane. There
// is no year 0: 1 BC is followed by AD 1.
export const FIRST_YEAR = -399
export const LAST_YEAR = 2026
export const LAPSE_EVEN = [[0, FIRST_YEAR], [1, LAST_YEAR]]
// era-timelapse-1280/1920.mp4 (8.04 s): Athena falls at 3.0 s, modern dress at
// 3.75 s, the first crane at 4.0 s.
export const LAPSE_LANDSCAPE = [[0, FIRST_YEAR], [0.38, 465], [0.46, 1900], [0.495, 1975], [1, LAST_YEAR]]
// era-timelapse-portrait-960.mp4 (8.04 s): Athena falls at 2.7 s, the first
// scaffold at 3.0 s, the crane at 3.2 s.
export const LAPSE_PORTRAIT = [[0, FIRST_YEAR], [0.335, 465], [0.375, 1900], [0.4, 1975], [1, LAST_YEAR]]

// Years as a number line with no gap: 1 BC is 0, AD 1 is 1.
const toLine = (y) => (y < 0 ? y + 1 : y)
const fromLine = (n) => (n <= 0 ? n - 1 : n)

export const lapseYear = (f, anchors = LAPSE_EVEN) => {
  const pts = Array.isArray(anchors) && anchors.length > 1 ? anchors : LAPSE_EVEN
  const x = clamp01(f)
  let i = 1
  while (i < pts.length - 1 && x > pts[i][0]) i++
  const [f0, y0] = pts[i - 1]
  const [f1, y1] = pts[i]
  const t = f1 > f0 ? clamp01((x - f0) / (f1 - f0)) : 1
  const n = toLine(y0) + (toLine(y1) - toLine(y0)) * t
  return fromLine(Math.round(n))
}

// The prepared scrolls were written with long dashes; the city prints none.
// Display only: the seeds are never changed. On each line the first spaced
// dash becomes a colon and any later one a comma; one opening a line (an
// attribution) goes, and so does one closing it.
export const cityPunctuation = (line) => {
  let first = true
  return String(line ?? '')
    .replace(/^(\s*)\u2014\s*/, '$1')
    .replace(/\s*\u2014\s*$/, '')
    .replace(/\s*\u2014\s*/g, (m) => {
      const spaced = /^\s/.test(m)
      const mark = first && spaced ? ': ' : ', '
      first = false
      return mark
    })
}

// Just enough Markdown for the scrolls (headings, lists, emphasis), in the
// city's punctuation.
const escapeHtml = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
// One line as the Hearing prints it (undash: a spaced long or short dash, the
// first a colon and any later one a comma), after a dash at either end has
// gone; cityPunctuation takes any long dash still left (an unspaced one).
const cityLine = (line) =>
  cityPunctuation(
    undash(
      String(line ?? '')
        .replace(/^(\s*)[\u2014\u2013]\s*/, '$1')
        .replace(/\s*[\u2014\u2013]\s*$/, '')
    )
  )
const inline = (text) =>
  escapeHtml(cityLine(text))
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')

export const renderScroll = (markdown) => {
  const html = []
  for (const block of String(markdown || '').trim().split(/\n{2,}/)) {
    if (!block.trim()) continue
    const lines = block.split('\n')
    if (lines.every((l) => l.startsWith('- '))) {
      html.push(`<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join('')}</ul>`)
      continue
    }
    for (const line of lines) {
      if (line.startsWith('### ')) html.push(`<h5>${inline(line.slice(4))}</h5>`)
      else if (line.startsWith('## ')) html.push(`<h4>${inline(line.slice(3))}</h4>`)
      else if (line.startsWith('# ')) html.push(`<h3>${inline(line.slice(2))}</h3>`)
    }
    const prose = lines.filter((l) => !l.startsWith('#')).map(cityLine).join(' ')
    if (prose) html.push(`<p>${inline(prose)}</p>`)
  }
  return html.join('')
}

// The opening clause of a sentence: up to the first colon, semicolon or comma
// (and their Chinese forms), then, if still long, up to the first " and ".
export const firstClause = (text, max = 44) => {
  let s = String(text || '').replace(/\s+/g, ' ').trim()
  if (!s) return ''
  const cut = s.search(/[:;,，：；、]/)
  if (cut > 0) s = s.slice(0, cut)
  if (s.length > max) {
    const and = s.indexOf(' and ')
    if (and > 12) s = s.slice(0, and)
  }
  return s.replace(/[\s.。!！?？]+$/, '')
}

// A Catmull-Rom curve through the points, written as cubic Beziers, so the
// Way passes exactly through every station.
export const smoothPath = (points, tension = 1) => {
  const pts = (points || []).filter((p) => p && Number.isFinite(p.x) && Number.isFinite(p.y))
  if (!pts.length) return ''
  const f = (n) => Math.round(n * 10) / 10
  let d = `M${f(pts[0].x)} ${f(pts[0].y)}`
  if (pts.length === 1) return d
  const k = tension / 6
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || p2
    const c1 = { x: p1.x + (p2.x - p0.x) * k, y: p1.y + (p2.y - p0.y) * k }
    const c2 = { x: p2.x - (p3.x - p1.x) * k, y: p2.y - (p3.y - p1.y) * k }
    d += ` C${f(c1.x)} ${f(c1.y)} ${f(c2.x)} ${f(c2.y)} ${f(p2.x)} ${f(p2.y)}`
  }
  return d
}

export function createDescent(win) {
  const subscribers = new Set()
  let ticking = false
  let attached = false

  const metrics = () => ({
    y: win.scrollY || win.pageYOffset || 0,
    vh: win.innerHeight || 0,
    vw: win.innerWidth || 0
  })

  // Every read first, then every write, so no subscriber forces a layout
  // another one has just invalidated.
  const run = () => {
    ticking = false
    const m = metrics()
    const writes = []
    for (const fn of [...subscribers]) {
      try {
        const write = fn(m)
        if (typeof write === 'function') writes.push(write)
      } catch {
        // one subscriber's trouble never stops the others
      }
    }
    for (const write of writes) {
      try {
        write()
      } catch {
        // as above
      }
    }
  }

  const onScroll = () => {
    if (ticking) return
    ticking = true
    const raf = win.requestAnimationFrame || ((cb) => win.setTimeout(cb, 16))
    raf.call(win, run)
  }

  const attach = () => {
    if (attached) return
    attached = true
    win.addEventListener('scroll', onScroll, { passive: true })
    win.addEventListener('resize', onScroll, { passive: true })
  }

  const detach = () => {
    if (!attached) return
    attached = false
    win.removeEventListener('scroll', onScroll)
    win.removeEventListener('resize', onScroll)
  }

  const subscribe = (fn, { immediate = true } = {}) => {
    if (typeof fn !== 'function') return () => {}
    subscribers.add(fn)
    attach()
    if (immediate) {
      try {
        const write = fn(metrics())
        if (typeof write === 'function') write()
      } catch {
        // as above
      }
    }
    return () => {
      subscribers.delete(fn)
      if (!subscribers.size) detach()
    }
  }

  return { subscribe, count: () => subscribers.size, listening: () => attached }
}

const shared = typeof window !== 'undefined' ? createDescent(window) : null

export const subscribe = (fn, opts) => (shared ? shared.subscribe(fn, opts) : () => {})

export function afterIdle(win, delay, fn) {
  if (!win) return () => {}
  let done = false
  let timer = 0
  let idle = 0
  const fire = () => {
    if (done) return
    done = true
    fn()
  }
  const wait = () => {
    timer = win.setTimeout(() => {
      timer = 0
      if (typeof win.requestIdleCallback === 'function') idle = win.requestIdleCallback(fire, { timeout: 2000 })
      else fire()
    }, delay)
  }
  const onLoad = () => {
    win.removeEventListener('load', onLoad)
    wait()
  }
  if (win.document && win.document.readyState !== 'complete') win.addEventListener('load', onLoad)
  else wait()
  return () => {
    done = true
    win.removeEventListener('load', onLoad)
    if (timer) win.clearTimeout(timer)
    if (idle && typeof win.cancelIdleCallback === 'function') win.cancelIdleCallback(idle)
  }
}
