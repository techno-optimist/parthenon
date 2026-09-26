// The square: where each citizen stands on the painted Agora, where they walk
// when they answer someone, what a ribbon of speech says, where the sun is.
// Pure module: no Vue, no DOM. Points are in normalised image coordinates
// (0..1 across the 16:9 painting) unless a function says otherwise.

import { citizenName, stanceKey, STANCE_SIDES } from './vocabulary.js'

// The paintings are 16:9.
export const IMAGE_RATIO = 16 / 9

// The widths each painting is exported at, for srcset.
export const PLATE_WIDTHS = [1280, 1920, 2560]

/**
 * The two squares: the Agora as it stands today (the Stoa of Attalos rebuilt,
 * the excavated foundations, the lamps) and as it stood in 399 BC (a living
 * market square, a painted stoa, torches and braziers). Each is painted at
 * night and relit for the day from the same pixels, so the two light states
 * line up exactly. `ground` is the walkable open square, kept clear of the
 * trees, walls, stalls and lamps with room for a coin at every edge; `stoaY`
 * is the foot of the Stoa's steps; `phoneX` is where a 4:3 crop sits so the
 * whole ground stays in frame.
 */
export const PLATES = {
  now: {
    key: 'now',
    base: '/media/acts/square/agora-now',
    ground: [
      [0.35, 0.345],
      [0.7, 0.35],
      [0.74, 0.44],
      [0.775, 0.52],
      [0.775, 0.74],
      [0.75, 0.84],
      [0.58, 0.83],
      [0.42, 0.78],
      [0.3, 0.76],
      [0.265, 0.66],
      [0.27, 0.55],
      [0.31, 0.45]
    ],
    stoaY: 0.32,
    phoneX: 0.58
  },
  ancient: {
    key: 'ancient',
    base: '/media/acts/square/agora-ancient',
    ground: [
      [0.28, 0.45],
      [0.79, 0.45],
      [0.815, 0.58],
      [0.8, 0.8],
      [0.66, 0.88],
      [0.4, 0.86],
      [0.28, 0.82],
      [0.21, 0.7],
      [0.24, 0.58]
    ],
    stoaY: 0.42,
    phoneX: 0.54
  }
}

export const plateOf = (era) => PLATES[era] || PLATES.now

// '/media/acts/square/agora-now-night-1280.jpg 1280w, ...'
export const plateSrcset = (plate, light = 'night') =>
  PLATE_WIDTHS.map((w) => `${plate.base}-${light}-${w}.jpg ${w}w`).join(', ')
export const plateSrc = (plate, light = 'night', width = 1280) => `${plate.base}-${light}-${width}.jpg`

/**
 * Which Athens a gathering stands in. A speaker's scroll from the steps (its
 * file is one of `ancientFiles`) stands in 399 BC; an Arrival stands today;
 * a stage built by hand is read from its question and summary.
 *
 * @param {{ files?: Array<string|{filename}>, requirement?: string, summary?: string }} g
 * @param {string[]} ancientFiles the speakers' scroll names
 * @returns {'ancient'|'now'}
 */
export const gatheringEra = (g = {}, ancientFiles = []) => {
  const names = (g.files || []).map((f) => String((f && f.filename) || f || '').toLowerCase()).filter(Boolean)
  const known = new Set((ancientFiles || []).map((f) => String(f).toLowerCase()))
  if (names.some((n) => known.has(n))) return 'ancient'
  if (names.some((n) => n.startsWith('arrival-'))) return 'now'
  const text = `${g.requirement || ''} ${g.summary || ''}`
  if (/\bancient (athens|athenian|agora|greece|greek)\b|\b\d{2,4}\s?B\.?C\.?(E)?\b|\bclassical athens\b/i.test(text)) return 'ancient'
  return 'now'
}

// The walkable ground of the square as it stands today (the default plate).
export const GROUND = PLATES.now.ground

// The foot of the Stoa's steps, where a citizen who speaks in the Stoa turns.
export const STOA_STEPS_Y = PLATES.now.stoaY

// ---- Small deterministic tools ----

// FNV-1a, 32 bit: the same name always hashes the same.
export const hashString = (s) => {
  let h = 0x811c9dc5
  const str = String(s ?? '')
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

// A small seeded random source.
export const seededRandom = (seed) => {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export const pointInPolygon = (x, y, poly = GROUND) => {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]
    const [xj, yj] = poly[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

export const polygonBounds = (poly = GROUND) => {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const [x, y] of poly) {
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (x > maxX) maxX = x
    if (y > maxY) maxY = y
  }
  return { minX, minY, maxX, maxY }
}

export const polygonArea = (poly = GROUND) => {
  let a = 0
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) a += (poly[j][0] + poly[i][0]) * (poly[j][1] - poly[i][1])
  return Math.abs(a / 2)
}

export const polygonCentroid = (poly = GROUND) => {
  let cx = 0, cy = 0, a = 0
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const f = poly[j][0] * poly[i][1] - poly[i][0] * poly[j][1]
    cx += (poly[j][0] + poly[i][0]) * f
    cy += (poly[j][1] + poly[i][1]) * f
    a += f
  }
  a *= 0.5
  return a ? { x: cx / (6 * a), y: cy / (6 * a) } : { x: 0.5, y: 0.5 }
}

// Distance on the painting as the eye sees it: across is wider than down.
const seen = (a, b, aspect = IMAGE_RATIO) => Math.hypot((a.x - b.x) * aspect, a.y - b.y)

// ---- Stance ----

// Where a citizen stood when the argument began: for, against, or undecided.
export const stanceSide = (stance) => {
  const s = String(stance || '').trim().toLowerCase()
  if (!s) return 'undecided'
  if (/^(support|supportive|supporting|supporter|for|pro|favou?r|in favou?r|positive)/.test(s)) return 'for'
  if (/^(oppos|against|anti|reject|negative|hostile)/.test(s)) return 'against'
  return 'undecided'
}

// Supporters gather toward the left of the square, the opposed toward the
// right, the undecided and the watchers in between: the square reads like the
// ledger beside it.
const SIDE_PULL = { for: 0.2, undecided: 0.5, against: 0.8 }

// ---- Home spots ----

const randomPointIn = (rnd, poly, b) => {
  for (let i = 0; i < 400; i++) {
    const x = b.minX + rnd() * (b.maxX - b.minX)
    const y = b.minY + rnd() * (b.maxY - b.minY)
    if (pointInPolygon(x, y, poly)) return { x, y }
  }
  return polygonCentroid(poly)
}

/**
 * Where each citizen stands when no one is speaking. Spread over the ground
 * with room between coins, deterministic by name: the same gathering always
 * stands the same way, whatever order the citizens arrive in.
 *
 * @param {Array<{id, name, stance?}>} citizens
 * @returns {Object<string, {x, y}>} by id
 */
export const homeSpots = (citizens, { ground = GROUND, aspect = IMAGE_RATIO, tries = 48 } = {}) => {
  const b = polygonBounds(ground)
  const list = (citizens || [])
    .filter((c) => c && c.id !== undefined && c.id !== null)
    .map((c) => {
      const name = String(c.name || c.id)
      return { id: String(c.id), name, side: stanceSide(c.stance), h: hashString(name) }
    })
    .sort((p, q) => p.h - q.h || p.name.localeCompare(q.name) || p.id.localeCompare(q.id))
  const spacing = Math.sqrt((polygonArea(ground) * aspect) / Math.max(1, list.length))
  const placed = []
  const out = {}
  for (const c of list) {
    const rnd = seededRandom(c.h ^ hashString(c.id))
    const pull = SIDE_PULL[c.side]
    let best = null
    let bestScore = -Infinity
    for (let i = 0; i < tries; i++) {
      const p = randomPointIn(rnd, ground, b)
      let d = Infinity
      for (const q of placed) d = Math.min(d, seen(p, q, aspect))
      const room = Math.min(d, spacing * 1.4) / spacing
      const across = (p.x - b.minX) / (b.maxX - b.minX || 1)
      const score = room - Math.abs(across - pull) * 0.9
      if (score > bestScore) {
        bestScore = score
        best = p
      }
    }
    placed.push(best)
    out[c.id] = { x: round4(best.x), y: round4(best.y) }
  }
  return out
}

const round4 = (v) => Math.round(v * 10000) / 10000

/**
 * Part of the way from one citizen toward another: the answerer steps toward
 * whoever they answer and stops short, never onto them, never off the ground.
 */
export const walkToward = (from, to, { fraction = 0.42, keep = 0.12, ground = GROUND, aspect = IMAGE_RATIO } = {}) => {
  if (!from || !to) return from || null
  const d = seen(from, to, aspect)
  if (d < 1e-6) return { ...from }
  let travel = Math.min(d * fraction, d - keep)
  if (travel <= 0.004) return { ...from }
  const ux = (to.x - from.x) / d
  const uy = (to.y - from.y) / d
  for (let i = 0; i < 4; i++) {
    const p = { x: from.x + (ux * travel) / aspect, y: from.y + uy * travel }
    if (pointInPolygon(p.x, p.y, ground)) return { x: round4(p.x), y: round4(p.y) }
    travel /= 2
  }
  return { ...from }
}

// A coin further off is a little smaller: the painting is seen from above and behind.
export const depthScale = (y, { ground = GROUND, near = 1.08, far = 0.82 } = {}) => {
  const b = polygonBounds(ground)
  const t = Math.max(0, Math.min(1, (y - b.minY) / (b.maxY - b.minY || 1)))
  return Math.round((far + (near - far) * t) * 1000) / 1000
}

// ---- The frame ----

/**
 * The part of the painting a box of this shape shows under object-fit: cover,
 * with the given object-position (0..1 on each axis).
 */
export const viewWindow = (boxRatio, posX = 0.5, posY = 0.5, imageRatio = IMAGE_RATIO) => {
  const r = Number(boxRatio) || imageRatio
  if (r < imageRatio) {
    const w = r / imageRatio
    return { x0: posX * (1 - w), y0: 0, w, h: 1 }
  }
  const h = imageRatio / r
  return { x0: 0, y0: posY * (1 - h), w: 1, h }
}

// A point of the painting as percentages of the box.
export const toBox = (p, win) => ({
  left: Math.round(((p.x - win.x0) / win.w) * 10000) / 100,
  top: Math.round(((p.y - win.y0) / win.h) * 10000) / 100
})

// ---- The day clock ----

export const ARC = { x0: 3, x1: 97, apex: 5, end: 17 } // in percent of the box

// The hour of the city's day at a round (and a fraction through it).
export const hourAt = (round, minutesPerRound = 60, frac = 0) => {
  const m = Number(minutesPerRound) || 60
  const hours = ((Number(round) || 0) + Math.max(0, Math.min(0.999, frac || 0))) * (m / 60)
  return ((hours % 24) + 24) % 24
}

/**
 * The sun from six in the morning to six in the evening, the moon through the
 * night, each crossing the same thin arc along the top of the square.
 */
export const skyAt = (hour) => {
  const h = (((Number(hour) || 0) % 24) + 24) % 24
  const day = h >= 6 && h < 18
  const t = day ? (h - 6) / 12 : (((h - 18) % 24) + 24) % 24 / 12
  const k = (2 * t - 1) ** 2
  const altitude = Math.round((1 - k) * 1000) / 1000
  return {
    body: day ? 'sun' : 'moon',
    t: Math.round(t * 1000) / 1000,
    left: Math.round((ARC.x0 + (ARC.x1 - ARC.x0) * t) * 100) / 100,
    top: Math.round((ARC.apex + (ARC.end - ARC.apex) * k) * 100) / 100,
    altitude,
    daylight: day ? Math.round(Math.sqrt(Math.max(0, altitude)) * 1000) / 1000 : 0
  }
}

const smooth = (a, b, x) => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

/**
 * The light over the square at an hour: how much of the day painting shows
 * (0 at night, 1 from mid-morning to late afternoon, easing through dawn and
 * dusk), and how warm the low sun is (the rose of dawn and the amber of dusk).
 */
export const lightAt = (hour) => {
  const h = (((Number(hour) || 0) % 24) + 24) % 24
  const day = smooth(5, 7.5, h) * (1 - smooth(17, 19.5, h))
  const near = (c) => Math.max(0, 1 - Math.abs(h - c) / 1.6)
  const w = Math.max(near(6.4), near(18.2))
  return { day: Math.round(day * 1000) / 1000, warm: Math.round(w * w * (3 - 2 * w) * 1000) / 1000 }
}

// The arc itself, as an SVG path in a 100x100 box.
export const arcPath = (steps = 24) => {
  const pts = []
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const k = (2 * t - 1) ** 2
    pts.push(`${(ARC.x0 + (ARC.x1 - ARC.x0) * t).toFixed(2)} ${(ARC.apex + (ARC.end - ARC.apex) * k).toFixed(2)}`)
  }
  return `M ${pts.join(' L ')}`
}

// The hour in words, as a key and a number for the locale:
// midnight, noon, or n in the morning / afternoon / evening / at night.
export const hourWords = (hour) => {
  const h = Math.floor((((Number(hour) || 0) % 24) + 24) % 24)
  if (h === 0) return { key: 'midnight', n: 12 }
  if (h === 12) return { key: 'noon', n: 12 }
  if (h < 6) return { key: 'night', n: h }
  if (h < 12) return { key: 'morning', n: h }
  if (h < 18) return { key: 'afternoon', n: h - 12 }
  if (h < 22) return { key: 'evening', n: h - 12 }
  return { key: 'lateNight', n: h - 12 }
}

// ---- Words ----

const handleToName = (handle) => citizenName('', handle.replace(/\./g, '_'))

// '#ImpietyPunished' reads 'Impiety Punished'; '#cold_bay' reads 'cold bay'.
const tagWords = (tag) => {
  let words = tag.replace(/_+/g, ' ').trim()
  if (/^\p{Lu}/u.test(words) && /\p{Ll}\p{Lu}/u.test(words)) words = words.replace(/(\p{Ll})(\p{Lu})/gu, '$1 $2')
  return words
}

/**
 * The city speaks without hashtags or handles: '#word' keeps the word, and
 * '@handle' becomes the citizen's name. Emails and '#1' are left alone.
 *
 * @param {string} text
 * @param {(handle: string) => string|null} [resolveHandle] a known citizen's name for a handle
 */
export const cleanSpeech = (text, resolveHandle = null) =>
  String(text ?? '')
    .replace(/(^|[^\p{L}\p{N}_@.])@([\p{L}][\p{L}\p{N}_.]*[\p{L}\p{N}_]|[\p{L}])/gu, (m, pre, handle) => {
      const name = (resolveHandle && resolveHandle(handle)) || handleToName(handle)
      return `${pre}${name}`
    })
    .replace(/(^|[^\p{L}\p{N}_&#/])#(\p{L}[\p{L}\p{N}_]*)/gu, (m, pre, tag) => `${pre}${tagWords(tag)}`)

// A key that matches a name however it is written: 'Despina Nomikou',
// 'despina_nomikou_466', '@despina.nomikou'.
export const nameKey = (name) =>
  String(name || '')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/^@/, '')
    .replace(/[_.]\d+$/, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()

/**
 * A few words of a line for the ribbon above the speaker: the first sentence
 * when it is short; else the sentence cut at its last clause that fits (a
 * comma, a colon, a dash), else at a word, and an ellipsis. Never mid-word, so
 * the ribbon needs no clamp.
 */
export const ribbonWords = (text, { maxWords = 14, maxChars = 72 } = {}) => {
  const s = String(text ?? '').replace(/\s+/g, ' ').trim()
  if (!s) return ''
  const sentences = s.match(/[^.!?;:]+[.!?;:]+(?=\s|$)|[^.!?;:]+$/g) || [s]
  const fits = (t) => t.length <= maxChars && t.split(' ').length <= maxWords
  let out = sentences[0].trim()
  let i = 1
  // A very short opening takes the next sentence with it when both fit; a
  // colon always does, since what it announces is the point.
  while (i < sentences.length && (out.split(' ').length < 4 || /:$/.test(out))) {
    const next = `${out} ${sentences[i].trim()}`
    const colon = /:$/.test(out)
    if (!colon && !fits(next)) break
    out = next
    i++
    if (!fits(out)) break
  }
  const trail = (t) => `${t.replace(/[\s,.;:!?'"“‘(\-–—]+$/u, '')}…`
  // A clause that runs on (ending in a colon or a semicolon) trails off.
  if (fits(out)) return /[:;,]$/.test(out) ? trail(out) : out
  // The last clause break that still fits, if it keeps enough of the line.
  const breaks = [...out.matchAll(/[,;:](?=\s)|\s[-–—]\s/g)].map((m) => m.index)
  const least = Math.max(18, Math.round(maxChars * 0.55))
  for (let k = breaks.length - 1; k >= 0; k--) {
    const head = out.slice(0, breaks[k]).trim()
    if (head.length >= least && fits(head)) return trail(head)
  }
  let cut = ''
  for (const w of out.split(' ')) {
    const next = cut ? `${cut} ${w}` : w
    if (!fits(next)) break
    cut = next
  }
  // A cut at a word does not end on a word that leads nowhere.
  const words = (cut || out.slice(0, maxChars)).split(' ')
  while (words.length > 3 && LEADING.has(words[words.length - 1].toLowerCase().replace(/[^\p{L}]/gu, ''))) words.pop()
  return trail(words.join(' '))
}

const LEADING = new Set(['a', 'an', 'the', 'and', 'or', 'but', 'of', 'to', 'in', 'on', 'for', 'with', 'at', 'by', 'from', 'as', 'that', 'which', 'who', 'is', 'are', 'was', 'be', 'its', 'their', 'his', 'her', 'our', 'your', 'my', 'this', 'these', 'those', 'not', 'no', 'so', 'if', 'than'])

/**
 * A line without its speaker's own name as a label ('Yes for Psammos: about
 * 600 parents...' said by Yes for Psammos reads 'About 600 parents...').
 */
export const withoutOwnName = (text, name) => {
  const s = String(text ?? '').trim()
  const n = String(name || '').trim()
  if (!n || !s) return s
  const esc = n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const rest = s.replace(new RegExp(`^${esc}\\s*[:,\\-–]\\s+`, 'iu'), '')
  if (rest === s || !rest) return s
  return rest.charAt(0).toUpperCase() + rest.slice(1)
}

// ---- The murmur ----

// How busy the square is: beats in the last few seconds, per second.
export const beatsPerSecond = (times, now, windowMs = 6000) => {
  const since = (Number(now) || 0) - windowMs
  const n = (times || []).filter((t) => t > since && t <= now).length
  return Math.round((n / (windowMs / 1000)) * 1000) / 1000
}

// The murmur's level (0..1) for a pace: a low bed when the square is quiet,
// fuller as the beats come faster, never louder than 1.
export const murmurLevel = (bps) => {
  const b = Math.max(0, Number(bps) || 0)
  return Math.round((0.25 + 0.75 * (1 - Math.exp(-b / 1.2))) * 1000) / 1000
}

// ---- What each action looks like in the square ----

const SPEAK = new Set(['CREATE_POST', 'POST'])
const ANSWER = new Set(['CREATE_COMMENT', 'COMMENT', 'REPLY'])
const QUOTE = new Set(['QUOTE_POST', 'QUOTE'])
const NOD = new Set(['LIKE_POST', 'LIKE_COMMENT', 'LIKE', 'UPVOTE', 'UPVOTE_POST', 'UPVOTE_COMMENT'])
const SHAKE = new Set(['DISLIKE_POST', 'DISLIKE_COMMENT', 'DISLIKE', 'DOWNVOTE', 'DOWNVOTE_POST', 'DOWNVOTE_COMMENT'])

export const placeOf = (platform) => (String(platform || '').toLowerCase() === 'reddit' ? 'stoa' : 'agora')

/**
 * Who said which post, from the record itself: `${place}:${postId}` -> citizen id.
 * Speeches carry their post id, quotes their new one, and nods name the author.
 */
export const indexPosts = (actions, idOfName = () => null) => {
  const map = new Map()
  for (const a of actions || []) {
    const type = String(a.action_type || '').toUpperCase()
    const args = a.action_args || {}
    const place = placeOf(a.platform)
    const id = a.agent_id !== undefined && a.agent_id !== null ? String(a.agent_id) : null
    if (SPEAK.has(type) && args.post_id !== undefined && id) map.set(`${place}:${args.post_id}`, id)
    else if ((QUOTE.has(type) || type === 'REPOST') && args.new_post_id !== undefined && id) map.set(`${place}:${args.new_post_id}`, id)
    else if (args.post_id !== undefined && args.post_author_name && !map.has(`${place}:${args.post_id}`)) {
      const author = idOfName(args.post_author_name)
      if (author !== null && author !== undefined) map.set(`${place}:${args.post_id}`, String(author))
    }
  }
  return map
}

/**
 * One action as a beat of the square.
 *   speak   a citizen speaks (a ribbon)
 *   answer  a citizen answers someone (a walk toward them and a ribbon)
 *   quote   a citizen quotes someone (a walk and a ribbon)
 *   nod / shake / repeat   a glint on both coins
 *   follow / quiet         the crowd moving; nothing to stage
 *
 * ctx: { idOfName(name), postAuthor(place, postId), commentPost(place, commentId) }
 */
export const beatOf = (action, ctx = {}) => {
  const a = action || {}
  const type = String(a.action_type || '').toUpperCase()
  const args = a.action_args || {}
  const place = placeOf(a.platform)
  const idOfName = ctx.idOfName || (() => null)
  const byName = (n) => {
    if (!n) return null
    const id = idOfName(n)
    return id === undefined || id === null ? null : String(id)
  }
  const from = a.agent_id !== undefined && a.agent_id !== null ? String(a.agent_id) : byName(a.agent_name)
  const beat = {
    id: a._uniqueId ?? a.id ?? null,
    kind: 'quiet',
    from,
    to: null,
    place,
    round: Number(a.round_num) || 0,
    words: ''
  }
  const content = args.content ?? args.quote_content ?? ''
  if (ANSWER.has(type)) {
    beat.kind = 'answer'
    beat.words = String(content || '')
    let to = byName(args.post_author_name || args.parent_author_name || args.comment_author_name)
    if (!to && ctx.commentPost && ctx.postAuthor && args.comment_id !== undefined) {
      const postId = ctx.commentPost(place, args.comment_id)
      if (postId !== undefined && postId !== null) to = ctx.postAuthor(place, postId) ?? null
    }
    if (!to && ctx.postAuthor && args.post_id !== undefined) to = ctx.postAuthor(place, args.post_id) ?? null
    beat.to = to === null || to === undefined ? null : String(to)
  } else if (QUOTE.has(type)) {
    beat.kind = 'quote'
    beat.words = String(args.quote_content ?? args.content ?? '')
    beat.to = byName(args.original_author_name)
  } else if (SPEAK.has(type) || (content && type !== 'REPOST')) {
    beat.kind = 'speak'
    beat.words = String(content || '')
  } else if (NOD.has(type)) {
    beat.kind = 'nod'
    beat.to = byName(args.post_author_name || args.comment_author_name)
  } else if (SHAKE.has(type)) {
    beat.kind = 'shake'
    beat.to = byName(args.post_author_name || args.comment_author_name)
  } else if (type === 'REPOST') {
    beat.kind = 'repeat'
    beat.to = byName(args.original_author_name)
  } else if (type === 'FOLLOW') {
    beat.kind = 'follow'
    beat.to = byName(args.target_user_name || args.target_user)
  }
  if (beat.to !== null && beat.to === beat.from) beat.to = null
  return beat
}

export const isRibbonBeat = (beat) => ['speak', 'answer', 'quote'].includes(beat?.kind)

// ---- Replay pace ----

export const SPEEDS = [1, 4, 16]

const BEAT_MS = { speak: 2600, answer: 2900, quote: 2900, nod: 800, shake: 800, repeat: 900, follow: 450, quiet: 220 }

// How long a beat holds the square before the next one, at a speed.
export const beatDuration = (beat, speed = 1) => {
  const base = BEAT_MS[beat?.kind] ?? BEAT_MS.quiet
  return Math.max(60, Math.round(base / (Number(speed) || 1)))
}

// The pause as the sun moves on to the next hour.
export const roundPause = (speed = 1) => Math.max(80, Math.round(900 / (Number(speed) || 1)))

// ---- Where they stood ----

const STANCE_NOW_KEYS = ['current_stance', 'stance_now', 'final_stance', 'latest_stance']

/**
 * The 'who moved' ledger. If the gathering records a later stance for anyone
 * (stance_history, or a current/final stance), those citizens are listed as
 * having moved. Otherwise only where they began is known, in three rows.
 *
 * @param {Array} agents agent configs: { agent_id, entity_name, entity_type, stance, sentiment_bias? }
 * @returns {{ moved: Array<{id, name, type, from, to}>, rows: {for, against, undecided}, knowsDrift: boolean }}
 */
export const stanceLedger = (agents) => {
  const rows = { for: [], against: [], undecided: [] }
  const moved = []
  let knowsDrift = false
  for (const a of agents || []) {
    if (!a) continue
    const id = String(a.agent_id ?? a.id ?? '')
    const name = citizenName(a.entity_name || a.name || '')
    const type = a.entity_type || a.type || ''
    const began = stanceSide(a.stance)
    let now = null
    if (Array.isArray(a.stance_history) && a.stance_history.length) {
      knowsDrift = true
      const last = a.stance_history[a.stance_history.length - 1]
      now = stanceSide(typeof last === 'string' ? last : last?.stance)
    } else {
      for (const k of STANCE_NOW_KEYS) {
        if (a[k]) {
          knowsDrift = true
          now = stanceSide(a[k])
          break
        }
      }
    }
    const lean = Number(a.sentiment_bias) || 0
    rows[began].push({ id, name, type, lean })
    if (now && now !== began) moved.push({ id, name, type, from: began, to: now })
  }
  // Strongest conviction first on each side; the undecided by name.
  rows.for.sort((p, q) => q.lean - p.lean || p.name.localeCompare(q.name))
  rows.against.sort((p, q) => p.lean - q.lean || p.name.localeCompare(q.name))
  rows.undecided.sort((p, q) => p.name.localeCompare(q.name))
  return { moved, rows, knowsDrift }
}

// ---- Who moved: the Scribe's reading after the argument ----

/**
 * The city's time of day at the end of a round, as the day clock names it:
 * { day, part } with part night (before six), morning, afternoon or evening
 * (from six in the evening). null for a round that is not a number.
 */
export const partOfDay = (round, minutesPerRound = 60) => {
  const r = Number(round)
  if (round === null || round === undefined || round === '' || !Number.isFinite(r) || r < 0) return null
  const m = Number(minutesPerRound) > 0 ? Number(minutesPerRound) : 60
  const hours = (r * m) / 60
  const h = hours % 24
  const part = h < 6 ? 'night' : h < 12 ? 'morning' : h < 18 ? 'afternoon' : 'evening'
  return { day: Math.floor(hours / 24) + 1, part }
}

/**
 * When a citizen came to where they ended: the period that opens their last
 * unbroken stretch on that side. null when the history never reaches it.
 *
 * @param {Array<{period, from_round, to_round, stance}|string>} history
 * @param {string} side - 'for' | 'against' | 'undecided' | 'watching'
 */
export const turnOf = (history, side) => {
  const list = Array.isArray(history) ? history.filter(Boolean) : []
  let at = null
  for (let i = list.length - 1; i >= 0; i--) {
    const h = list[i]
    if (stanceKey(typeof h === 'string' ? h : h.stance) !== side) break
    at = h
  }
  return at && typeof at === 'object' ? at : null
}

const sideRows = () => Object.fromEntries(STANCE_SIDES.map((s) => [s, []]))
const sortSides = (rows) => {
  rows.for.sort((p, q) => q.lean - p.lean || p.name.localeCompare(q.name))
  rows.against.sort((p, q) => p.lean - q.lean || p.name.localeCompare(q.name))
  rows.undecided.sort((p, q) => p.name.localeCompare(q.name))
  rows.watching.sort((p, q) => p.name.localeCompare(q.name))
  return rows
}

/**
 * The Scribe's reading laid over the gathering, on the four sides: where each
 * citizen began, where they ended, and who moved (and when, by the city's
 * clock). The Scribe reads three sides (for, against, neutral), so an onlooker
 * read as neutral has not moved; the reading's own 'moved' says so when given.
 * A citizen the Scribe did not read ends where they began.
 *
 * @param {Array} agents - agent configs: { agent_id, entity_name, entity_type, stance, sentiment_bias }
 * @param {Object|null} reading - the stances reading: { minutes_per_round, citizens: [{ agent_id,
 *   stance, final_stance, moved, stance_history: [{ period, from_round, to_round, stance }] }] }
 * @param {{ minutesPerRound?: number }} [options] - the clock when the reading names none
 * @returns {{ moved: Array<{ id, name, type, from, to, round, when }>,
 *   began: Object<string, Array>, ended: Object<string, Array>,
 *   byId: Map<string, { began, ended, moved }> }}
 */
export const stanceReading = (agents, reading, { minutesPerRound } = {}) => {
  const read = new Map()
  for (const c of reading?.citizens || []) {
    if (c && c.agent_id !== undefined && c.agent_id !== null) read.set(String(c.agent_id), c)
  }
  const minutes = Number(reading?.minutes_per_round) || Number(minutesPerRound) || 60
  const began = sideRows()
  const ended = sideRows()
  const moved = []
  const byId = new Map()
  const list = agents && agents.length ? agents : reading?.citizens || []
  for (const a of list) {
    if (!a) continue
    const id = String(a.agent_id ?? a.id ?? '')
    if (!id || byId.has(id)) continue
    const r = read.get(id) || null
    const name = citizenName(a.entity_name || a.name || r?.name || '')
    const type = a.entity_type || a.type || r?.entity_type || ''
    const from = stanceKey(a.stance ?? r?.stance, a.sentiment_bias)
    const finalRaw = r?.final_stance || ''
    const readSide = finalRaw ? stanceKey(finalRaw) : from
    const didMove = !!finalRaw && readSide !== from &&
      (typeof r.moved === 'boolean' ? r.moved : !(from === 'watching' && readSide === 'undecided'))
    const to = didMove ? readSide : from
    const lean = Number(a.sentiment_bias) || 0
    began[from].push({ id, name, type, lean, moved: didMove })
    ended[to].push({ id, name, type, lean, moved: didMove })
    byId.set(id, { began: from, ended: to, moved: didMove })
    if (didMove) {
      const turn = turnOf(r.stance_history, to)
      const round = turn && Number.isFinite(Number(turn.to_round)) ? Number(turn.to_round) : null
      moved.push({ id, name, type, from, to, round, when: round === null ? null : partOfDay(round, minutes) })
    }
  }
  sortSides(began)
  sortSides(ended)
  // In the order the city saw them move; a move with no hour last.
  moved.sort((p, q) => (p.round ?? Infinity) - (q.round ?? Infinity) || p.name.localeCompare(q.name))
  return { moved, began, ended, byId }
}
