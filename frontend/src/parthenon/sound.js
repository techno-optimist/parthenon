/*
 * The sound of the night. One Listen switch serves the whole product: the
 * bed under the hero and the acts, the narrator's lines, the Agora's murmur.
 *
 * Nothing sounds until the visitor asks, and the choice is remembered for
 * this browser. A visitor who prefers reduced motion starts every visit in
 * silence until they press Listen again.
 *
 * Each bed is a recording of the place where one is on hand (media/sound,
 * listed in beds.json): dawn wind on the steps in 399 BC, the city at dusk in
 * 2026, crickets under the five acts. It is heard in long overlapping
 * stretches, each fading into the next, so the loop never shows its seam; the
 * few drawn sounds that pass for real (a gust over the stone, a hearth's
 * crackle) ride on top. Where no recording can be had (none listed, Save-Data,
 * a failed load or decode) the bed is drawn whole in Web Audio instead. Any
 * voice ducks the beds, recorded or drawn, the same way.
 *
 * Contract
 *   sound                    readonly state: enabled, supported, bed, speaking, ducked,
 *                            and waiting (on, but the page has not been touched yet)
 *   setListening(on)         the switch; remembered unless { remember: false }
 *   toggleListening()
 *   setBed(name | null)      'ancient' | 'now' | 'night'; crossfades, silent when off
 *   speak(src, opts)         plays one clip, ducking the beds. Silent when off unless
 *                            { always: true } (a button that says "hear this").
 *                            Resolves true when it played to the end; false when
 *                            it was silent, stopped, cut off by the next line or
 *                            could not load (a missing clip simply stays silent).
 *   stopSpeaking()           ends the line now; its promise resolves false
 *   voiceUrl(key, locale)    /media/voices/<key>.mp3, or /media/voices/zh/<key>.mp3
 *   holdDuck()               for voices played elsewhere; returns release()
 *   murmurInput()            { ctx, input } for the Agora's murmur, or null
 *   buildBed(name, ctx, out) the drawn bed, for offline rendering in checks
 *   buildRecordedBed(name, ctx, out, recording)
 *                            the recorded bed ({ buffer, loopStart, loopEnd }) with
 *                            its overlay, for offline rendering in checks
 *
 * The rules a browser sets, kept here so no caller has to:
 *   - The audio context is only made, or woken, inside a gesture or after the
 *     page has had one, so a page load never warns that audio was not allowed
 *     to start. With a stored yes, the first touch or key anywhere wakes it.
 *   - A hidden tab fades out and the context sleeps; it wakes when seen again.
 *   - The beds schedule a little ahead on a slow tick. Anything that fell
 *     behind (a sleep, a throttled tab, a bed brought back) is moved up to
 *     now, never played in a burst.
 *   - Every passing sound (a swallow, a crackle, a chirp, a stretch of a
 *     recording) lets go
 *     of its nodes when it ends; the long-lived parameters are never
 *     automated per event, so nothing grows while the night goes on.
 *   - There is one engine per page, however many copies of this module a dev
 *     server has loaded, so there is only ever one night playing.
 */
import { reactive, readonly } from 'vue'
import { withBase } from './base.js'

export const LISTEN_KEY = 'parthenon.listen'
const OLD_KEYS = ['parthenon.agora.listen']
export const BEDS = ['ancient', 'now', 'night']

const hasWindow = typeof window !== 'undefined'

export const prefersReducedMotion = () => {
  try {
    return hasWindow && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

// The stored choice; the Agora's old key counts as a yes.
export const readChoice = (storage) => {
  try {
    const v = storage?.getItem(LISTEN_KEY)
    if (v === '1' || v === '0') return v === '1'
    return OLD_KEYS.some((k) => storage?.getItem(k) === '1')
  } catch {
    return false
  }
}

const storage = () => {
  try {
    return hasWindow ? window.localStorage : null
  } catch {
    return null
  }
}

const AC = hasWindow ? window.AudioContext || window.webkitAudioContext || null : null

export const voiceUrl = (key, locale = 'en') => {
  const lang = String(locale || 'en').slice(0, 2).toLowerCase()
  return lang === 'en' ? withBase(`/media/voices/${key}.mp3`) : withBase(`/media/voices/${lang}/${key}.mp3`)
}

// ---- Levels ----
// Each bed plays at about -31.5 dBFS RMS through the master, within a decibel
// of the others, with peaks near -15 to -20 dBFS (rendered offline in the
// browser for forty seconds; drawn with buildBed: ancient -31.3, now -31.8,
// night -31.2; recorded with buildRecordedBed: ancient -31.2, now -31.4,
// night -31.8). The narrator's clips sit near -23 dBFS RMS; under a voice the beds
// fall by DUCK (about -13 dB), so a line stands some twenty decibels forward.
export const MASTER_LEVEL = 0.9
export const BED_LEVEL = Object.freeze({ ancient: 0.6, now: 0.58, night: 0.5 })
export const DUCK_LEVEL = 0.22

const RISE = 0.9 // time constants, in seconds
const FALL = 0.2
const BED_IN = 1.26
const BED_OUT = 0.9
const DUCK_DOWN = 0.12
const DUCK_UP = 0.6
const LOOKAHEAD = 1.2 // how far ahead the beds are written, in seconds
const TICK_MS = 250
const SLEEP_MS = 1600 // after the fade to silence, the context sleeps
const RETIRE_MS = 6000 // a bed faded out is taken apart

// ---- The beds ----

const buffers = new WeakMap()

const noise = (c, kind) => {
  let cache = buffers.get(c)
  if (!cache) buffers.set(c, (cache = {}))
  if (cache[kind]) return cache[kind]
  const seconds = kind === 'crackle' ? 0.06 : 6
  const len = Math.floor(c.sampleRate * seconds)
  const buf = c.createBuffer(1, len, c.sampleRate)
  const d = buf.getChannelData(0)
  if (kind === 'brown') {
    let last = 0
    for (let i = 0; i < len; i++) {
      last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02
      d[i] = last * 3.5
    }
  } else if (kind === 'crackle') {
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.exp(-i / (c.sampleRate * 0.006))
  } else {
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1
  }
  cache[kind] = buf
  return buf
}

const filter = (c, type, frequency, Q = 0.7) => {
  const f = c.createBiquadFilter()
  f.type = type
  f.frequency.value = frequency
  f.Q.value = Q
  return f
}

const gain = (c, value) => {
  const g = c.createGain()
  g.gain.value = value
  return g
}

const pan = (c, value) => {
  if (!c.createStereoPanner) return gain(c, 1)
  const p = c.createStereoPanner()
  p.pan.value = value
  return p
}

const chain = (...nodes) => {
  for (let i = 0; i < nodes.length - 1; i++) nodes[i].connect(nodes[i + 1])
  return nodes[nodes.length - 1]
}

const rand = (a, b) => a + Math.random() * (b - a)

// A passing sound lets go of its nodes once its last source has ended.
const oneShot = (sources, nodes) => {
  let left = sources.length
  const ended = () => {
    if (--left > 0) return
    for (const s of sources) s.onended = null
    for (const n of nodes) {
      try {
        n.disconnect()
      } catch {
        /* already apart */
      }
    }
  }
  for (const s of sources) s.onended = ended
}

// The long-lived part of a bed: its loops, its slow LFOs and the nodes they
// run through. stop() ends and disconnects all of them.
const kit = (c) => {
  const sources = []
  const nodes = []
  const keep = (n) => {
    nodes.push(n)
    return n
  }
  return {
    keep,
    loop(buf) {
      const s = keep(c.createBufferSource())
      s.buffer = buf
      s.loop = true
      s.start(c.currentTime, Math.random() * buf.duration)
      sources.push(s)
      return s
    },
    lfo(frequency, depth, param) {
      const o = keep(c.createOscillator())
      o.frequency.value = frequency
      const g = keep(gain(c, depth))
      o.connect(g)
      g.connect(param)
      o.start()
      sources.push(o)
      return o
    },
    stop() {
      for (const s of sources) {
        try {
          s.stop()
        } catch {
          /* already stopped */
        }
      }
      for (const n of nodes) {
        try {
          n.disconnect()
        } catch {
          /* already apart */
        }
      }
      sources.length = 0
      nodes.length = 0
    }
  }
}

// When an event's time has fallen behind (the context slept, the tab was
// throttled, a faded bed came back), it is moved up to now with a little
// scatter, never played late in a burst.
const catchUp = (c, t, scatter) => {
  const floor = c.currentTime + 0.05
  return t < floor ? floor + Math.random() * scatter : t
}

// A swallow's phrase: a few quick rising and falling notes.
const swallow = (c, out, t) => {
  const p = pan(c, rand(-0.8, 0.8))
  p.connect(out)
  const notes = 2 + Math.floor(Math.random() * 4)
  const base = rand(3000, 4300)
  const amp = rand(0.018, 0.04)
  const sources = []
  const nodes = [p]
  let when = t
  for (let i = 0; i < notes; i++) {
    const dur = rand(0.045, 0.1)
    const o = c.createOscillator()
    o.type = 'sine'
    const f0 = base * rand(0.92, 1.08)
    o.frequency.setValueAtTime(f0, when)
    o.frequency.exponentialRampToValueAtTime(f0 * (Math.random() < 0.6 ? 1.35 : 0.78), when + dur)
    const g = gain(c, 0)
    g.gain.setValueAtTime(0, when)
    g.gain.linearRampToValueAtTime(amp, when + 0.008)
    g.gain.exponentialRampToValueAtTime(0.0001, when + dur)
    o.connect(g)
    g.connect(p)
    o.start(when)
    o.stop(when + dur + 0.02)
    sources.push(o)
    nodes.push(o, g)
    when += dur + rand(0.04, 0.12)
  }
  oneShot(sources, nodes)
}

// A goat bell far down the slope: two soft strikes.
const bell = (c, out, t) => {
  const p = pan(c, rand(-0.6, 0.6))
  p.connect(out)
  const f = rand(820, 1150)
  const sources = []
  const nodes = [p]
  const strike = (when, amp) => {
    for (const [ratio, share] of [
      [1, 1],
      [2.76, 0.35],
      [5.4, 0.12]
    ]) {
      const o = c.createOscillator()
      o.frequency.value = f * ratio
      const g = gain(c, 0)
      g.gain.setValueAtTime(0, when)
      g.gain.linearRampToValueAtTime(amp * share, when + 0.004)
      g.gain.exponentialRampToValueAtTime(0.0001, when + 1.6 / ratio)
      o.connect(g)
      g.connect(p)
      o.start(when)
      o.stop(when + 1.7)
      sources.push(o)
      nodes.push(o, g)
    }
  }
  const amp = rand(0.008, 0.014)
  strike(t, amp)
  strike(t + rand(0.18, 0.32), amp * 0.6)
  oneShot(sources, nodes)
}

// Wind over the stone: two bands of slow noise that gust and turn.
function wind(c, k, out, scale = 1) {
  const brown = noise(c, 'brown')
  const low = k.keep(filter(c, 'bandpass', 380, 0.55))
  const lowGain = k.keep(gain(c, 0.5 * scale))
  chain(k.loop(brown), k.keep(filter(c, 'highpass', 70, 0.5)), low, lowGain, k.keep(pan(c, -0.3)), out)
  k.lfo(0.061, 220, low.frequency)
  k.lfo(0.043, 0.22 * scale, lowGain.gain)
  const high = k.keep(filter(c, 'bandpass', 900, 0.8))
  const highGain = k.keep(gain(c, 0.16 * scale))
  chain(k.loop(brown), high, highGain, k.keep(pan(c, 0.35)), out)
  k.lfo(0.083, 380, high.frequency)
  k.lfo(0.029, 0.1 * scale, highGain.gain)
}

// Dawn on the steps, 399 BC: wind over the stone, swallows, a far bell.
function ancientBed(c, out) {
  const k = kit(c)
  wind(c, k, out)

  let nextBird = c.currentTime + rand(0.8, 2.5)
  let nextBell = c.currentTime + rand(6, 12)
  const schedule = (until) => {
    nextBird = catchUp(c, nextBird, 1.5)
    nextBell = catchUp(c, nextBell, 8)
    while (nextBird < until) {
      swallow(c, out, nextBird)
      nextBird += Math.random() < 0.3 ? rand(0.3, 0.8) : rand(1.4, 4.5)
    }
    while (nextBell < until) {
      bell(c, out, nextBell)
      nextBell += rand(11, 26)
    }
  }
  return { schedule, stop: k.stop }
}

// Traffic on the ring road: a swell of tyres that comes and goes.
const passing = (c, out, buf, t) => {
  const dur = rand(3.5, 7)
  const dir = Math.random() < 0.5 ? -1 : 1
  const s = c.createBufferSource()
  s.buffer = buf
  s.loop = true
  const bp = filter(c, 'bandpass', rand(250, 340), 0.45)
  const g = gain(c, 0)
  const peak = rand(0.06, 0.2)
  g.gain.setValueAtTime(0, t)
  g.gain.linearRampToValueAtTime(peak, t + dur * rand(0.35, 0.55))
  g.gain.linearRampToValueAtTime(0, t + dur)
  const p = pan(c, -0.5 * dir)
  if (p.pan) {
    p.pan.setValueAtTime(-0.5 * dir, t)
    p.pan.linearRampToValueAtTime(0.5 * dir, t + dur)
  }
  chain(s, bp, g, p, out)
  s.start(t, Math.random() * buf.duration)
  s.stop(t + dur + 0.05)
  oneShot([s], [s, bp, g, p])
}

// Swifts screaming over the rooftops at dusk.
const swifts = (c, out, t) => {
  const p = pan(c, rand(-0.9, 0.9))
  p.connect(out)
  const n = 1 + Math.floor(Math.random() * 3)
  const sources = []
  const nodes = [p]
  for (let i = 0; i < n; i++) {
    const when = t + i * rand(0.12, 0.3)
    const dur = rand(0.25, 0.45)
    const o = c.createOscillator()
    o.frequency.setValueAtTime(rand(5600, 6800), when)
    const trill = c.createOscillator()
    trill.frequency.value = rand(38, 55)
    const depth = gain(c, 420)
    trill.connect(depth)
    depth.connect(o.frequency)
    const g = gain(c, 0)
    const amp = rand(0.006, 0.012)
    g.gain.setValueAtTime(0, when)
    g.gain.linearRampToValueAtTime(amp, when + 0.03)
    g.gain.exponentialRampToValueAtTime(0.0001, when + dur)
    o.connect(g)
    g.connect(p)
    o.start(when)
    trill.start(when)
    o.stop(when + dur + 0.02)
    trill.stop(when + dur + 0.02)
    sources.push(o, trill)
    nodes.push(o, trill, depth, g)
  }
  oneShot(sources, nodes)
}

// Dusk, 2026: the city's hum, traffic swelling, voices on the terraces.
// (No engine is drawn: a sawtooth passes for a synthesizer, not a scooter.)
function nowBed(c, out) {
  const k = kit(c)
  const brown = noise(c, 'brown')
  chain(
    k.loop(brown),
    k.keep(filter(c, 'highpass', 45, 0.5)),
    k.keep(filter(c, 'lowpass', 150, 0.5)),
    k.keep(gain(c, 0.28)),
    out
  )
  const roadPan = k.keep(pan(c, 0))
  chain(k.loop(brown), k.keep(filter(c, 'bandpass', 300, 0.45)), k.keep(gain(c, 0.07)), roadPan, out)
  if (roadPan.pan) k.lfo(0.031, 0.45, roadPan.pan)
  const talk = k.keep(filter(c, 'bandpass', 620, 1.3))
  const talkGain = k.keep(gain(c, 0.09))
  chain(k.loop(brown), talk, talkGain, out)
  k.lfo(0.9, 0.035, talkGain.gain)
  k.lfo(0.23, 90, talk.frequency)

  let nextSwell = c.currentTime + rand(0.5, 2)
  let nextSwift = c.currentTime + rand(3, 7)
  const schedule = (until) => {
    nextSwell = catchUp(c, nextSwell, 2)
    nextSwift = catchUp(c, nextSwift, 3)
    while (nextSwell < until) {
      passing(c, out, brown, nextSwell)
      nextSwell += rand(2.5, 6)
    }
    while (nextSwift < until) {
      swifts(c, out, nextSwift)
      nextSwift += rand(4, 11)
    }
  }
  return { schedule, stop: k.stop }
}

// One cricket's chirp: a few pulses of one high note.
const chirp = (c, dest, frequency, amp, pulses, t) => {
  const o = c.createOscillator()
  o.frequency.value = frequency
  const g = gain(c, 0)
  for (let j = 0; j < pulses; j++) {
    const s = t + j * 0.045
    g.gain.setValueAtTime(0, s)
    g.gain.linearRampToValueAtTime(amp, s + 0.005)
    g.gain.setValueAtTime(amp, s + 0.018)
    g.gain.linearRampToValueAtTime(0, s + 0.024)
  }
  o.connect(g)
  g.connect(dest)
  o.start(t)
  o.stop(t + pulses * 0.045 + 0.02)
  oneShot([o], [o, g])
}

// Under the five acts: night air, crickets, a hearth.
function nightBed(c, out) {
  const k = kit(c)
  const brown = noise(c, 'brown')
  const air = k.keep(gain(c, 0.32))
  chain(k.loop(brown), k.keep(filter(c, 'lowpass', 240, 0.5)), air, out)
  k.lfo(0.05, 0.08, air.gain)

  const crickets = [0, 1, 2].map((i) => {
    const p = k.keep(pan(c, [-0.7, 0.55, 0.1][i]))
    p.connect(out)
    return {
      p,
      frequency: rand(4300, 4900),
      amp: [0.012, 0.009, 0.005][i],
      period: rand(0.55, 0.95),
      pulses: 2 + Math.floor(Math.random() * 3),
      next: c.currentTime + rand(0.2, 1.5)
    }
  })

  const crackles = hearth(c, k, out)

  const schedule = (until) => {
    for (const cr of crickets) {
      cr.next = catchUp(c, cr.next, cr.period)
      while (cr.next < until) {
        if (Math.random() < 0.06) {
          cr.next += rand(2, 6) // a cricket pauses
          continue
        }
        chirp(c, cr.p, cr.frequency, cr.amp, cr.pulses, cr.next)
        cr.next += cr.period * rand(0.94, 1.06)
      }
    }
    crackles(until)
  }
  return { schedule, stop: k.stop }
}

// A hearth nearby: dry crackles, now in runs, now alone. Returns its scheduler.
function hearth(c, k, out, scale = 1) {
  const crackle = noise(c, 'crackle')
  const hp = k.keep(filter(c, 'highpass', 1600, 0.7))
  chain(hp, k.keep(pan(c, 0.25)), out)
  let nextCrack = c.currentTime + rand(0.2, 0.8)
  return (until) => {
    nextCrack = catchUp(c, nextCrack, 0.5)
    while (nextCrack < until) {
      const s = c.createBufferSource()
      s.buffer = crackle
      s.playbackRate.value = rand(0.6, 1.6)
      const g = gain(c, rand(0.015, 0.06) * scale)
      chain(s, g, hp)
      s.start(nextCrack)
      oneShot([s], [s, g])
      nextCrack += Math.random() < 0.3 ? rand(0.02, 0.09) : rand(0.15, 0.9)
    }
  }
}

const MAKERS = { ancient: ancientBed, now: nowBed, night: nightBed }

export const buildBed = (name, c, out) => (MAKERS[name] ? MAKERS[name](c, out) : null)

// ---- The recorded beds ----
// A recording is heard as two voices, one leaning left and one right, each a
// chain of stretches of seven to eleven seconds taken from anywhere in the
// file and faded into the next over two seconds (equal power, so the level
// holds through the join). The two voices never turn at the same moment, a
// short file never plays back the same way twice, and a mono file opens out.

export const RECORDINGS_URL = withBase('/media/sound/beds.json')
export const CROSSFADE = 2 // seconds
// Each recording is mastered near -30 dBFS RMS; these lift or lower it to sit
// with the drawn beds (about -31.5 dBFS at the master, measured offline with
// buildRecordedBed over the files in media/sound, overlay included).
export const RECORDED_LEVEL = Object.freeze({ ancient: 1.1, now: 1.26, night: 1.32 })
const VOICE_PAN = 0.55

const fadeCurve = (rise) => {
  const n = 64
  const a = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * (Math.PI / 2)
    a[i] = rise ? Math.sin(x) : Math.cos(x)
  }
  return a
}
const FADE_IN = fadeCurve(true)
const FADE_OUT = fadeCurve(false)

// One voice: stretch after stretch of the recording, each fading into the next.
function recordingVoice(c, out, rec, side) {
  const { buffer } = rec
  const length = buffer.duration
  const from0 = Math.min(Math.max(Number(rec.loopStart) || 0, 0), Math.max(0, length - 3))
  const to0 = Number(rec.loopEnd) > from0 + 3 ? Math.min(Number(rec.loopEnd), length) : length
  const span = to0 - from0
  const p = pan(c, side * VOICE_PAN)
  p.connect(out)
  const playing = new Set()
  let next = c.currentTime + 0.02
  let lastFrom = -1

  const stretch = (t) => {
    const len = Math.min(span, rand(7, 11))
    const x = Math.min(CROSSFADE, len / 3)
    // Anywhere in the file, but not where the last stretch began.
    let from = from0 + Math.random() * Math.max(0, span - len)
    if (lastFrom >= 0 && Math.abs(from - lastFrom) < 1.5 && span - len > 3) from = from0 + ((from - from0 + (span - len) / 2) % (span - len))
    lastFrom = from
    const s = c.createBufferSource()
    s.buffer = buffer
    const g = gain(c, 0)
    g.gain.setValueCurveAtTime(FADE_IN, t, x)
    g.gain.setValueCurveAtTime(FADE_OUT, t + len - x, x)
    s.connect(g)
    g.connect(p)
    s.start(t, from, len)
    s.stop(t + len + 0.02)
    const pair = [s, g]
    playing.add(pair)
    s.onended = () => {
      s.onended = null
      playing.delete(pair)
      for (const n of pair) {
        try {
          n.disconnect()
        } catch {
          /* already apart */
        }
      }
    }
    return t + len - x
  }

  return {
    schedule(until) {
      // After a sleep the chain starts again from now, fading in; never a burst.
      if (next < c.currentTime + 0.02) next = c.currentTime + 0.02 + Math.random() * 0.2
      while (next < until) next = stretch(next)
    },
    stop() {
      for (const pair of playing) {
        for (const n of pair) {
          try {
            if (n.stop) n.stop()
          } catch {
            /* already stopped */
          }
          try {
            n.disconnect()
          } catch {
            /* already apart */
          }
        }
      }
      playing.clear()
      try {
        p.disconnect()
      } catch {
        /* already apart */
      }
    }
  }
}

// What rides on a recording: only the drawn sounds that pass for real.
const OVERLAYS = {
  ancient(c, out) {
    const k = kit(c)
    wind(c, k, out, 0.45)
    return { schedule: () => {}, stop: k.stop }
  },
  night(c, out) {
    const k = kit(c)
    return { schedule: hearth(c, k, out, 0.8), stop: k.stop }
  }
}

// The recording's two voices, without an overlay.
function recordedVoices(name, c, out, rec) {
  // Two uncorrelated voices sum 3 dB up; each is lowered to keep the level.
  const level = gain(c, (RECORDED_LEVEL[name] ?? 1) * Math.SQRT1_2)
  level.connect(out)
  const voices = [recordingVoice(c, level, rec, -1), recordingVoice(c, level, rec, 1)]
  return {
    schedule(until) {
      for (const v of voices) v.schedule(until)
    },
    stop() {
      for (const v of voices) v.stop()
      try {
        level.disconnect()
      } catch {
        /* already apart */
      }
    }
  }
}

export function buildRecordedBed(name, c, out, rec) {
  if (!MAKERS[name] || !rec || !rec.buffer) return null
  const voices = recordedVoices(name, c, out, rec)
  const overlay = OVERLAYS[name] ? OVERLAYS[name](c, out) : null
  return {
    schedule(until) {
      voices.schedule(until)
      if (overlay) overlay.schedule(until)
    },
    stop() {
      voices.stop()
      if (overlay) overlay.stop()
    }
  }
}

// A bed that waits for its recording: the overlay sounds at once, the
// recording fades in beside it once it has loaded, and if it never comes the
// drawn bed takes the place of both. `onSource` hears 'recorded' or 'drawn'.
function awaitedBed(name, c, out, pending, onSource) {
  let overlay = OVERLAYS[name] ? OVERLAYS[name](c, out) : null
  let bed = null
  let stopped = false
  pending.then((rec) => {
    if (stopped) return
    if (rec && rec.buffer) {
      bed = recordedVoices(name, c, out, rec)
      onSource('recorded')
      return
    }
    if (overlay) overlay.stop()
    overlay = null
    bed = MAKERS[name](c, out)
    onSource('drawn')
  })
  return {
    schedule(until) {
      if (bed) bed.schedule(until)
      if (overlay) overlay.schedule(until)
    },
    stop() {
      stopped = true
      if (overlay) overlay.stop()
      if (bed) bed.stop()
      overlay = bed = null
    }
  }
}

// ---- The engine ----
// Everything that lives for the page: the state, the context, the beds that
// are lit, the narrator. It is made once per page and kept on the window, so
// a second copy of this module (a dev server swapping files under a running
// page) speaks to the same engine instead of starting a second night on top
// of the first. A reload picks up edits to this file.

function createEngine() {
  const state = reactive({
    enabled: hasWindow && !prefersReducedMotion() && readChoice(storage()),
    supported: !!AC || (hasWindow && typeof window.Audio !== 'undefined'),
    bed: null,
    speaking: null,
    ducked: false,
    // On, but the page has not been touched yet, so nothing can sound.
    waiting: false
  })
  const sound = readonly(state)

  let ctx = null
  let master = null
  let ambience = null
  let murmurBus = null
  let ticker = 0
  let duckCount = 0
  let hidden = false
  let sleepTimer = 0
  let pending = false
  const beds = {} // name -> { out, bed, retireTimer }
  const targets = new WeakMap() // AudioParam -> the last level asked of it
  const recordings = {} // name -> Promise<{ buffer, loopStart, loopEnd } | null>, fetched once per page
  const sources = {} // name -> 'loading' | 'recorded' | 'drawn', for the capture scripts
  let listing = null // Promise<beds.json | null>

  const timers = () => (hasWindow ? window : globalThis)
  const live = () => state.enabled && !hidden

  // navigator.userActivation, where the browser has it: `sticky` once the page
  // has been touched, `now` inside the gesture itself.
  const activation = () => {
    const ua = hasWindow && window.navigator ? window.navigator.userActivation : null
    return ua ? { sticky: !!ua.hasBeenActive, now: !!ua.isActive } : null
  }

  // ---- Waking on a gesture ----
  // A browser keeps sound asleep until the visitor touches the page. A touch's
  // pointerdown does not count (its pointerup or touchend does), so all of them
  // are heard and the listeners stay until the context is actually running.
  const GESTURES = ['pointerdown', 'pointerup', 'touchend', 'keydown', 'click']
  let armed = false

  const disarm = () => {
    if (!armed) return
    armed = false
    for (const type of GESTURES) window.removeEventListener(type, onGesture, true)
  }

  const armGesture = () => {
    if (armed || !hasWindow || !window.addEventListener) return
    armed = true
    for (const type of GESTURES) window.addEventListener(type, onGesture, true)
  }

  function onGesture() {
    if (!state.enabled) {
      state.waiting = false
      disarm()
      return
    }
    const a = activation()
    if (a && !a.now) return // not a gesture the browser honours; wait for the next
    if (ctx && ctx.state === 'running') {
      disarm()
      return
    }
    if (ensureContext(true)) update()
  }

  // Resume the context. Outside a gesture this is only tried once the page has
  // had one, and a gesture is kept in reserve in case the browser still says no.
  // A context only exists once the page has been touched, so a browser that
  // cannot say whether it has (no userActivation) is asked to resume anyway.
  function wake(gesture) {
    if (!ctx || ctx.state === 'running' || ctx.state === 'closed') return
    const a = activation()
    if (!gesture && a && !a.sticky) {
      armGesture()
      return
    }
    let p = null
    try {
      p = ctx.resume && ctx.resume()
    } catch {
      p = null
    }
    Promise.resolve(p)
      .then(() => {
        if (ctx && ctx.state !== 'running' && live()) armGesture()
      })
      .catch(() => armGesture())
    if (!gesture) armGesture()
  }

  const onVisibility = () => {
    hidden = typeof document !== 'undefined' && !!document.hidden
    apply()
  }

  const onStateChange = () => {
    if (!ctx) return
    if (ctx.state === 'running') {
      disarm()
      update()
    } else if (ctx.state !== 'closed' && live() && !sleepTimer) {
      // Taken away from us (a call, the phone locked), or a sleep that landed
      // just as the page came back: ask again, and wake on the next touch.
      wake(false)
    }
  }

  // The context is made on a gesture, or once the page has had one.
  function ensureContext(gesture = false) {
    if (!AC) return null
    if (!ctx) {
      const a = activation()
      if (!gesture && !(a ? a.sticky : false)) {
        armGesture()
        state.waiting = state.enabled
        return null
      }
      try {
        ctx = new AC()
        master = ctx.createGain()
        master.gain.value = 0
        master.connect(ctx.destination)
        ambience = ctx.createGain()
        ambience.gain.value = duckCount > 0 ? DUCK_LEVEL : 1
        targets.set(ambience.gain, ambience.gain.value)
        ambience.connect(master)
        murmurBus = ctx.createGain()
        murmurBus.connect(ambience)
        if (ctx.addEventListener) ctx.addEventListener('statechange', onStateChange)
        else ctx.onstatechange = onStateChange
        if (typeof document !== 'undefined' && document.addEventListener) {
          hidden = !!document.hidden
          document.addEventListener('visibilitychange', onVisibility)
        }
      } catch {
        ctx = master = ambience = murmurBus = null
        return null
      }
      state.waiting = false
    }
    wake(gesture)
    if (gesture) unlock()
    return ctx
  }

  // Older iPhones only open the audio path for a context that plays something
  // inside the gesture itself: one silent frame is enough.
  let unlocked = false
  function unlock() {
    if (unlocked || !ctx) return
    unlocked = true
    try {
      const s = ctx.createBufferSource()
      s.buffer = ctx.createBuffer(1, 1, ctx.sampleRate || 44100)
      s.connect(ctx.destination)
      s.onended = () => {
        s.onended = null
        try {
          s.disconnect()
        } catch {
          /* already apart */
        }
      }
      s.start(0)
    } catch {
      unlocked = false
    }
  }

  // Move a parameter toward a level, only when the level asked of it changes,
  // so repeated calls neither restart a fade nor lengthen its timeline. A fade
  // to silence lands on true zero once it is some sixty decibels down.
  const LAND = 7
  const ramp = (param, value, tc, now) => {
    if (targets.get(param) === value) return
    targets.set(param, value)
    param.cancelScheduledValues(now)
    param.setTargetAtTime(value, now, tc)
    if (value === 0) param.setValueAtTime(0, now + tc * LAND)
  }

  const tick = () => {
    if (!ctx || ctx.state !== 'running') return
    const until = ctx.currentTime + LOOKAHEAD
    for (const name of Object.keys(beds)) {
      const b = beds[name]
      if (b && !b.retireTimer) b.bed.schedule(until)
    }
  }

  const startTicker = () => {
    if (ticker || !hasWindow) return
    ticker = timers().setInterval(tick, TICK_MS)
  }
  const stopTicker = () => {
    if (!ticker) return
    timers().clearInterval(ticker)
    ticker = 0
  }

  const retire = (name) => {
    const b = beds[name]
    if (!b) return
    if (b.retireTimer) timers().clearTimeout(b.retireTimer)
    delete beds[name]
    try {
      b.bed.stop()
    } catch {
      /* already gone */
    }
    try {
      b.out.disconnect()
    } catch {
      /* already gone */
    }
  }

  // ---- Recordings ----
  // Fetched and decoded once, on the first Listen that needs them. None under
  // Save-Data; none where the browser cannot fetch or decode; a load that
  // fails or takes too long leaves the drawn bed in its place.
  const RECORDING_WAIT_MS = 9000
  const saveData = () => {
    try {
      const conn = hasWindow && window.navigator ? window.navigator.connection : null
      return !!(conn && conn.saveData)
    } catch {
      return false
    }
  }
  const decode = (data) =>
    new Promise((resolve, reject) => {
      try {
        const p = ctx.decodeAudioData(data, resolve, reject)
        if (p && typeof p.then === 'function') p.then(resolve, reject)
      } catch (e) {
        reject(e)
      }
    })
  const within = (p, ms) =>
    new Promise((resolve) => {
      const timer = timers().setTimeout(() => resolve(null), ms)
      const done = (v) => {
        timers().clearTimeout(timer)
        resolve(v || null)
      }
      p.then(done, () => done(null))
    })
  async function fetchRecording(name) {
    if (!listing) {
      listing = window
        .fetch(RECORDINGS_URL)
        .then((r) => (r && r.ok ? r.json() : null))
        .catch(() => null)
    }
    const list = await listing
    const entry = list && typeof list === 'object' ? list[name] : null
    if (!entry || typeof entry.src !== 'string') return null
    // The listing names site paths ('/media/sound/...'): under the page's base.
    const res = await window.fetch(withBase(entry.src))
    if (!res || !res.ok) return null
    const buffer = await decode(await res.arrayBuffer())
    if (!buffer || !(buffer.duration > 3)) return null
    return { buffer, loopStart: entry.loopStart, loopEnd: entry.loopEnd }
  }
  function recordingFor(name) {
    if (!hasWindow || typeof window.fetch !== 'function' || !ctx || typeof ctx.decodeAudioData !== 'function') return null
    if (saveData()) return null
    if (!recordings[name]) recordings[name] = within(fetchRecording(name), RECORDING_WAIT_MS)
    return recordings[name]
  }
  const makeBed = (name, out) => {
    const pending = recordingFor(name)
    if (!pending) {
      sources[name] = 'drawn'
      return MAKERS[name](ctx, out)
    }
    sources[name] = 'loading'
    return awaitedBed(name, ctx, out, pending, (how) => {
      sources[name] = how
      update()
    })
  }

  const bringBed = (name) => {
    if (!ctx || !MAKERS[name]) return null
    const b = beds[name]
    if (b) {
      if (b.retireTimer) {
        timers().clearTimeout(b.retireTimer)
        b.retireTimer = 0
      }
      return b
    }
    const out = ctx.createGain()
    out.gain.value = 0
    targets.set(out.gain, 0)
    out.connect(ambience)
    try {
      const bed = makeBed(name, out)
      beds[name] = { out, bed, retireTimer: 0 }
      return beds[name]
    } catch {
      try {
        out.disconnect()
      } catch {
        /* never joined */
      }
      return null
    }
  }

  // Everything follows from state: the master, the duck and which bed is lit.
  function apply() {
    if (!ctx) return
    const now = ctx.currentTime
    const on = live()
    ramp(master.gain, on ? MASTER_LEVEL : 0, on ? RISE : FALL, now)
    ramp(ambience.gain, duckCount > 0 ? DUCK_LEVEL : 1, duckCount > 0 ? DUCK_DOWN : DUCK_UP, now)

    const want = on ? state.bed : null
    if (want) bringBed(want)
    for (const name of Object.keys(beds)) {
      const b = beds[name]
      const lit = name === want
      ramp(b.out.gain, lit ? BED_LEVEL[name] : 0, lit ? BED_IN : BED_OUT, now)
      if (!lit && !b.retireTimer) b.retireTimer = timers().setTimeout(() => retire(name), RETIRE_MS)
    }

    if (on) {
      if (sleepTimer) {
        timers().clearTimeout(sleepTimer)
        sleepTimer = 0
      }
      if (ctx.state !== 'running') wake(false)
      if (want) {
        tick()
        startTicker()
      } else {
        stopTicker()
      }
    } else if (!sleepTimer && ctx.state === 'running') {
      // Asleep after the fade, so a silent page costs nothing.
      sleepTimer = timers().setTimeout(() => {
        sleepTimer = 0
        if (live() || !ctx || ctx.state !== 'running') return
        stopTicker()
        try {
          Promise.resolve(ctx.suspend && ctx.suspend()).catch(() => {})
        } catch {
          /* a context that cannot sleep stays silent */
        }
      }, SLEEP_MS)
    }
  }

  // State changes made in one breath (an act leaving as the next arrives, a
  // voice ending as another begins) are applied once, together.
  const soon = typeof queueMicrotask === 'function' ? queueMicrotask : (fn) => Promise.resolve().then(fn)
  function update() {
    if (pending || !ctx) return
    pending = true
    soon(() => {
      pending = false
      apply()
    })
  }

  function setListening(on, { remember = true } = {}) {
    state.enabled = !!on
    if (remember) {
      try {
        storage()?.setItem(LISTEN_KEY, state.enabled ? '1' : '0')
      } catch {
        /* a private window keeps no memory; the choice holds for this visit */
      }
    }
    if (state.enabled) {
      // Called from a Listen button, so this is a gesture: the context is made
      // and resumed here, inside it, as Safari requires. A call from anywhere
      // else waits for the page's first touch like every other.
      const a = activation()
      ensureContext(a ? a.now : true)
    } else {
      state.waiting = false
      disarm()
      stopSpeaking()
    }
    update()
  }

  const toggleListening = () => setListening(!state.enabled)

  function setBed(name) {
    state.bed = MAKERS[name] ? name : null
    if (!state.enabled) return
    if (ensureContext(false)) update()
  }

  function holdDuck() {
    duckCount++
    state.ducked = true
    update()
    let held = true
    return () => {
      if (!held) return
      held = false
      duckCount = Math.max(0, duckCount - 1)
      state.ducked = duckCount > 0
      update()
    }
  }

  function murmurInput() {
    if (!state.enabled) return null
    const c = ensureContext(false)
    if (!c) return null
    update()
    return { ctx: c, input: murmurBus }
  }

  // ---- The narrator ----
  // One element for every line, so a second line cleanly ends the first.

  const LOAD_WAIT_MS = 15000
  let voiceEl = null
  let current = null // { src, el, resolve, release, timer, done }

  const finish = (me, ok) => {
    if (!me || me.done) return
    me.done = true
    if (me.timer) timers().clearTimeout(me.timer)
    if (current === me) {
      current = null
      me.el.onended = null
      me.el.onerror = null
      me.el.onplaying = null
      state.speaking = null
    }
    me.release()
    me.resolve(ok)
  }

  function stopSpeaking() {
    const me = current
    if (!me) {
      state.speaking = null
      return
    }
    try {
      me.el.pause()
    } catch {
      /* nothing was playing */
    }
    finish(me, false)
  }

  function speak(src, { always = false, volume = 1 } = {}) {
    if (!src || !hasWindow || typeof window.Audio === 'undefined') return Promise.resolve(false)
    if (!always && !state.enabled) return Promise.resolve(false)
    stopSpeaking()
    if (!voiceEl) {
      try {
        voiceEl = new window.Audio()
        voiceEl.preload = 'auto'
      } catch {
        voiceEl = null
        return Promise.resolve(false)
      }
    }
    const el = voiceEl
    return new Promise((resolve) => {
      const me = { src, el, resolve, release: holdDuck(), timer: 0, done: false }
      current = me
      state.speaking = src
      // The guards keep a late event from the line before from ending this one.
      el.onended = () => {
        if (el.ended) finish(me, true)
      }
      el.onerror = () => {
        if (el.error) finish(me, false)
      }
      el.onplaying = () => {
        if (me.timer) timers().clearTimeout(me.timer)
        me.timer = 0
      }
      // A line that never begins (a stalled load) gives up rather than holding the duck.
      me.timer = timers().setTimeout(() => {
        me.timer = 0
        if (current === me && (el.paused || el.readyState < 3)) stopSpeaking()
      }, LOAD_WAIT_MS)
      try {
        el.volume = Math.max(0, Math.min(1, volume))
      } catch {
        /* iOS keeps its own volume */
      }
      try {
        el.src = src
        const p = el.play()
        if (p && typeof p.catch === 'function') p.catch(() => finish(me, false))
      } catch {
        finish(me, false)
      }
    })
  }

  // For the capture scripts in a dev build: what the ear would hear now.
  const levels = () =>
    ctx
      ? {
          ctx: ctx.state,
          master: master.gain.value,
          ambience: ambience.gain.value,
          beds: Object.fromEntries(Object.entries(beds).map(([k, b]) => [k, b.out.gain.value])),
          sources: { ...sources },
          time: ctx.currentTime
        }
      : null

  return {
    state,
    sound,
    setListening,
    toggleListening,
    setBed,
    holdDuck,
    murmurInput,
    speak,
    stopSpeaking,
    levels,
    armed: () => armed
  }
}

const ENGINE = Symbol.for('parthenon.sound')
const engine = (hasWindow && window[ENGINE]) || createEngine()
if (hasWindow) window[ENGINE] = engine

export const sound = engine.sound
export const setListening = (on, options) => engine.setListening(on, options)
export const toggleListening = () => engine.toggleListening()
export const setBed = (name) => engine.setBed(name)
export const holdDuck = () => engine.holdDuck()
export const murmurInput = () => engine.murmurInput()
export const speak = (src, options) => engine.speak(src, options)
export const stopSpeaking = () => engine.stopSpeaking()

// In a dev build only: the engine's live levels and its handles, for the
// capture scripts.
if (hasWindow && import.meta.env && import.meta.env.DEV) {
  window.__parthenonSound = {
    state: engine.state,
    levels: engine.levels,
    armed: engine.armed,
    speak,
    stopSpeaking,
    setBed,
    setListening,
    holdDuck
  }
}
