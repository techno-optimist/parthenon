// Run: cd frontend && node --test src/parthenon/sound.test.mjs
//
// The sound engine against a stubbed window: a storage, a media query, the
// browser's record of the visitor's touch, fake timers, an <audio> element and
// a tiny AudioContext that records the levels asked of each gain. Each test
// installs its own window and imports a fresh copy of the module.
import test from 'node:test'
import assert from 'node:assert/strict'
// Vue is loaded once, before any stub document exists (its DOM runtime looks for one).
import 'vue'

// ---- A tiny Web Audio ----

class FakeParam {
  constructor(value = 0) {
    this.value = value
    this.target = value
    this.events = []
  }
  setValueAtTime(v, t) {
    this.events.push(['set', v, t])
  }
  linearRampToValueAtTime(v, t) {
    this.events.push(['linear', v, t])
  }
  exponentialRampToValueAtTime(v, t) {
    this.events.push(['exp', v, t])
  }
  setTargetAtTime(v, t, tc) {
    this.events.push(['target', v, t, tc])
    this.target = v
  }
  cancelScheduledValues(t) {
    this.events.push(['cancel', t])
  }
  setValueCurveAtTime(curve, t, d) {
    this.events.push(['curve', t, d, curve[0], curve[curve.length - 1]])
  }
}

class FakeNode {
  constructor(ctx, kind) {
    this.ctx = ctx
    this.kind = kind
    this.outputs = new Set()
    this.disconnected = false
    ctx.nodes.push(this)
  }
  connect(n) {
    this.outputs.add(n)
    this.disconnected = false
    return n
  }
  disconnect() {
    this.outputs.clear()
    this.disconnected = true
  }
}

class FakeSource extends FakeNode {
  constructor(ctx, kind) {
    super(ctx, kind)
    this.onended = null
    this.startedAt = null
    this.stoppedAt = null
  }
  start(t = 0, offset = 0, duration = undefined) {
    this.startedAt = t
    this.offset = offset
    this.duration = duration
    this.ctx.starts.push(t)
  }
  stop(t = 0) {
    this.stoppedAt = t
  }
  end() {
    if (this.onended) this.onended()
  }
}

class FakeAudioContext {
  constructor() {
    FakeAudioContext.instances.push(this)
    this.state = 'suspended'
    this.currentTime = 0
    this.sampleRate = 8000
    this.nodes = []
    this.starts = []
    this.listeners = []
    this.resumes = 0
    this.suspends = 0
    this.destination = new FakeNode(this, 'destination')
  }
  addEventListener(type, fn) {
    if (type === 'statechange') this.listeners.push(fn)
  }
  setState(s) {
    if (this.state === s) return
    this.state = s
    for (const fn of this.listeners) fn()
  }
  resume() {
    this.resumes++
    return Promise.resolve().then(() => this.setState('running'))
  }
  suspend() {
    this.suspends++
    return Promise.resolve().then(() => this.setState('suspended'))
  }
  createGain() {
    const n = new FakeNode(this, 'gain')
    n.gain = new FakeParam(1)
    return n
  }
  createBiquadFilter() {
    const n = new FakeNode(this, 'filter')
    n.frequency = new FakeParam(350)
    n.Q = new FakeParam(1)
    return n
  }
  createStereoPanner() {
    const n = new FakeNode(this, 'panner')
    n.pan = new FakeParam(0)
    return n
  }
  createOscillator() {
    const n = new FakeSource(this, 'oscillator')
    n.frequency = new FakeParam(440)
    return n
  }
  createBufferSource() {
    const n = new FakeSource(this, 'bufferSource')
    n.playbackRate = new FakeParam(1)
    return n
  }
  createBuffer(channels, length, sampleRate) {
    const data = new Float32Array(length)
    return { length, sampleRate, duration: length / sampleRate, getChannelData: () => data }
  }
}
FakeAudioContext.instances = []

// ---- An <audio> element ----

class FakeAudio {
  constructor() {
    FakeAudio.instances.push(this)
    this.paused = true
    this.ended = false
    this.error = null
    this.readyState = 0
    this.volume = 1
    this._src = ''
    this.onended = this.onerror = this.onplaying = null
  }
  set src(v) {
    this._src = v
    this.ended = false
    this.error = null
    this.readyState = 0
  }
  get src() {
    return this._src
  }
  play() {
    if (FakeAudio.refuse) return Promise.reject(new Error('NotAllowedError'))
    this.paused = false
    return Promise.resolve()
  }
  pause() {
    this.paused = true
  }
  // What the browser would do
  begin() {
    this.readyState = 4
    if (this.onplaying) this.onplaying()
  }
  finishLine() {
    this.ended = true
    this.paused = true
    if (this.onended) this.onended()
  }
  fail() {
    this.error = { code: 4 }
    if (this.onerror) this.onerror()
  }
}
FakeAudio.instances = []
FakeAudio.refuse = false

// ---- Timers we can move by hand ----

function fakeTimers() {
  let now = 0
  let id = 0
  const queue = new Map()
  return {
    setTimeout(fn, ms = 0) {
      queue.set(++id, { at: now + ms, fn })
      return id
    },
    clearTimeout(i) {
      queue.delete(i)
    },
    setInterval(fn, ms) {
      queue.set(++id, { at: now + ms, fn, every: ms })
      return id
    },
    clearInterval(i) {
      queue.delete(i)
    },
    advance(ms) {
      const end = now + ms
      for (;;) {
        let next = null
        for (const entry of queue) if (entry[1].at <= end && (!next || entry[1].at < next[1].at)) next = entry
        if (!next) break
        const [i, t] = next
        now = t.at
        if (t.every) t.at += t.every
        else queue.delete(i)
        t.fn()
      }
      now = end
    }
  }
}

// ---- The window ----

let seq = 0
const flush = () => new Promise((resolve) => setImmediate(resolve))
// A line's promise, or 'pending' if it has not settled: a test fails rather than hangs.
const settle = (p) => Promise.race([p, new Promise((resolve) => setTimeout(() => resolve('pending'), 300))])

// A recording as the browser would hand it back after decoding.
const fakeRecording = (duration = 16) => ({ duration, length: Math.round(duration * 8000), sampleRate: 8000, getChannelData: () => new Float32Array(8) })

// The server behind fetch(): beds.json and the files it lists. `files` maps a
// path to a JSON object, 'audio', 404, or 'hang' (never answers).
function fakeFetch(files) {
  const calls = []
  const fetch = (url) => {
    calls.push(url)
    const f = files[url]
    if (f === 'hang') return new Promise(() => {})
    if (f === undefined || f === 404) return Promise.resolve({ ok: false, status: 404 })
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(f),
      arrayBuffer: () => Promise.resolve(new ArrayBuffer(16))
    })
  }
  return { fetch, calls }
}

const BEDS_JSON = {
  ancient: { src: '/media/sound/ancient.m4a', loopStart: 0.1, loopEnd: 16 },
  now: { src: '/media/sound/now.m4a', loopStart: 0.1, loopEnd: 13.7 },
  night: { src: '/media/sound/night.m4a', loopStart: 0.1, loopEnd: 16 }
}

function install({ stored = {}, reduced = false, touched = false, active = false, blocked = false, files = null, decode = 'none', saveData = false } = {}) {
  FakeAudioContext.instances = []
  FakeAudio.instances = []
  FakeAudio.refuse = false
  const store = new Map(Object.entries(stored))
  const listeners = {}
  const docListeners = {}
  const timers = fakeTimers()
  const userActivation = { hasBeenActive: touched, isActive: active }
  // A browser that can decode: the context hands back a recording, or refuses.
  FakeAudioContext.prototype.decodeAudioData = undefined
  if (decode !== 'none') {
    FakeAudioContext.prototype.decodeAudioData = function (data) {
      this.decodes = (this.decodes || 0) + 1
      return decode === 'fail' ? Promise.reject(new Error('EncodingError')) : Promise.resolve(fakeRecording())
    }
  }
  const server = files ? fakeFetch(files) : null
  const win = {
    matchMedia: (q) => ({ matches: reduced && q.includes('reduce') }),
    navigator: { userActivation, connection: saveData ? { saveData: true } : undefined },
    fetch: server ? server.fetch : undefined,
    AudioContext: FakeAudioContext,
    Audio: FakeAudio,
    addEventListener(type, fn) {
      ;(listeners[type] ||= new Set()).add(fn)
    },
    removeEventListener(type, fn) {
      listeners[type]?.delete(fn)
    },
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval
  }
  const storage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k)
  }
  Object.defineProperty(win, 'localStorage', {
    get() {
      if (blocked) throw new Error('SecurityError: storage is blocked')
      return storage
    }
  })
  const doc = {
    hidden: false,
    addEventListener(type, fn) {
      ;(docListeners[type] ||= new Set()).add(fn)
    },
    removeEventListener(type, fn) {
      docListeners[type]?.delete(fn)
    }
  }
  globalThis.window = win
  globalThis.document = doc
  return {
    win,
    doc,
    store,
    timers,
    userActivation,
    fetched: server ? server.calls : [],
    listening: (type) => listeners[type]?.size || 0,
    fire(type) {
      for (const fn of [...(listeners[type] || [])]) fn({ type })
    },
    fireDoc(type) {
      for (const fn of [...(docListeners[type] || [])]) fn({ type })
    }
  }
}

const load = () => import(`./sound.js?case=${++seq}`)

// The engine's graph: master into the destination, ambience into master, then
// the murmur bus and one gain per bed into the ambience.
const graph = (ctx) => {
  const gains = ctx.nodes.filter((n) => n.kind === 'gain')
  const master = gains.find((n) => n.outputs.has(ctx.destination))
  const ambience = gains.find((n) => n.outputs.has(master))
  const intoAmbience = gains.filter((n) => n.outputs.has(ambience))
  return { master, ambience, murmur: intoAmbience[0], beds: intoAmbience.slice(1) }
}

test.afterEach(() => {
  delete globalThis.window
  delete globalThis.document
})

// ---- readChoice ----

test('readChoice: the new key, the old Agora key, and blocked storage', async () => {
  install()
  const { readChoice, LISTEN_KEY } = await load()
  const mem = (entries) => {
    const m = new Map(Object.entries(entries))
    return { getItem: (k) => (m.has(k) ? m.get(k) : null) }
  }
  assert.equal(LISTEN_KEY, 'parthenon.listen')
  assert.equal(readChoice(mem({ 'parthenon.listen': '1' })), true)
  assert.equal(readChoice(mem({ 'parthenon.listen': '0' })), false)
  assert.equal(readChoice(mem({})), false)
  assert.equal(readChoice(mem({ 'parthenon.agora.listen': '1' })), true, 'the Agora key counts as a yes')
  assert.equal(readChoice(mem({ 'parthenon.agora.listen': '0' })), false)
  assert.equal(readChoice(mem({ 'parthenon.listen': '0', 'parthenon.agora.listen': '1' })), false, 'a later no wins')
  assert.equal(readChoice(null), false)
  assert.equal(readChoice(undefined), false)
  const throwing = {
    getItem() {
      throw new Error('blocked')
    }
  }
  assert.equal(readChoice(throwing), false)
})

// ---- voiceUrl ----

test('voiceUrl: English at the root, other languages in their folder', async () => {
  install()
  const { voiceUrl } = await load()
  assert.equal(voiceUrl('hero'), '/media/voices/hero.mp3')
  assert.equal(voiceUrl('hero', 'en'), '/media/voices/hero.mp3')
  assert.equal(voiceUrl('speaker-socrates', 'en-GB'), '/media/voices/speaker-socrates.mp3')
  assert.equal(voiceUrl('hero', 'zh'), '/media/voices/zh/hero.mp3')
  assert.equal(voiceUrl('arrival-plato-new-cave', 'zh-CN'), '/media/voices/zh/arrival-plato-new-cave.mp3')
  assert.equal(voiceUrl('hero', 'ZH'), '/media/voices/zh/hero.mp3')
  assert.equal(voiceUrl('hero', null), '/media/voices/hero.mp3')
})

// ---- The stored choice at load ----

test('a first visit starts silent', async () => {
  install()
  const { sound } = await load()
  assert.equal(sound.enabled, false)
  assert.equal(sound.supported, true)
  assert.equal(sound.bed, null)
  assert.equal(sound.speaking, null)
  assert.equal(sound.ducked, false)
  assert.equal(sound.waiting, false)
})

test('a stored yes, under either key, starts on', async () => {
  install({ stored: { 'parthenon.listen': '1' } })
  assert.equal((await load()).sound.enabled, true)
  install({ stored: { 'parthenon.agora.listen': '1' } })
  assert.equal((await load()).sound.enabled, true)
})

test('reduced motion starts each visit silent, whatever was stored, until Listen', async () => {
  const env = install({ stored: { 'parthenon.listen': '1' }, reduced: true })
  const { sound, setBed, setListening } = await load()
  assert.equal(sound.enabled, false)
  setBed('night')
  await flush()
  assert.equal(FakeAudioContext.instances.length, 0)
  env.userActivation.hasBeenActive = env.userActivation.isActive = true
  setListening(true)
  await flush()
  assert.equal(sound.enabled, true)
  assert.equal(FakeAudioContext.instances.length, 1)
})

test('blocked storage: silent at first, and the switch still works for the visit', async () => {
  install({ stored: { 'parthenon.listen': '1' }, blocked: true, touched: true, active: true })
  const { sound, setListening, toggleListening } = await load()
  assert.equal(sound.enabled, false)
  assert.doesNotThrow(() => setListening(true))
  assert.equal(sound.enabled, true)
  toggleListening()
  assert.equal(sound.enabled, false)
})

// ---- speak() ----

test('speak() is silent and resolves false when Listen is off', async () => {
  install()
  const { speak, sound } = await load()
  assert.equal(await settle(speak('/media/voices/hero.mp3')), false)
  assert.equal(await settle(speak('')), false)
  assert.equal(FakeAudio.instances.length, 0, 'no element is made')
  assert.equal(sound.speaking, null)
  assert.equal(sound.ducked, false)
})

test('speak(): a line played to its end resolves true and lets the duck go', async () => {
  install()
  const { speak, sound } = await load()
  const line = speak('/media/voices/hero.mp3', { always: true })
  const el = FakeAudio.instances[0]
  assert.equal(el.src, '/media/voices/hero.mp3')
  assert.equal(sound.speaking, '/media/voices/hero.mp3')
  assert.equal(sound.ducked, true)
  el.begin()
  el.finishLine()
  assert.equal(await settle(line), true)
  assert.equal(sound.speaking, null)
  assert.equal(sound.ducked, false)
})

test('speak(): a second line ends the first cleanly; a late event from the first ends nothing', async () => {
  install()
  const { speak, sound } = await load()
  const first = speak('/media/voices/speaker-socrates.mp3', { always: true })
  const el = FakeAudio.instances[0]
  const lateEnded = el.onended
  const second = speak('/media/voices/speaker-plato.mp3', { always: true })
  assert.equal(await settle(first), false)
  assert.equal(FakeAudio.instances.length, 1, 'one element for every line')
  assert.equal(sound.speaking, '/media/voices/speaker-plato.mp3')
  lateEnded()
  await flush()
  assert.equal(sound.speaking, '/media/voices/speaker-plato.mp3', 'the first line cannot end the second')
  assert.equal(sound.ducked, true)
  el.finishLine()
  assert.equal(await settle(second), true)
  assert.equal(sound.ducked, false)
})

test('speak(): stopSpeaking, a failed load, a refused play and a stalled load all resolve false', async () => {
  const env = install()
  const { speak, stopSpeaking, sound } = await load()

  const stopped = speak('/media/voices/hero.mp3', { always: true })
  stopSpeaking()
  assert.equal(await settle(stopped), false)
  assert.equal(sound.speaking, null)

  const missing = speak('/media/voices/zh/hero.mp3', { always: true })
  FakeAudio.instances[0].fail()
  assert.equal(await settle(missing), false)

  FakeAudio.refuse = true
  assert.equal(await settle(speak('/media/voices/hero.mp3', { always: true })), false)
  FakeAudio.refuse = false

  const stalled = speak('/media/voices/hero.mp3', { always: true })
  env.timers.advance(16000)
  assert.equal(await settle(stalled), false)

  assert.equal(sound.speaking, null)
  assert.equal(sound.ducked, false, 'no line holds the duck after it is gone')
  stopSpeaking() // nothing playing: harmless
})

test('speak() with Listen on plays without an explicit ask', async () => {
  install({ stored: { 'parthenon.listen': '1' } })
  const { speak } = await load()
  const line = speak('/media/voices/arrival-plato-new-cave.mp3')
  assert.equal(FakeAudio.instances.length, 1)
  FakeAudio.instances[0].finishLine()
  assert.equal(await settle(line), true)
})

// ---- The switch, the beds and the duck ----

test('Listen made in a gesture: the context, the master, the night bed, remembered', async () => {
  const env = install({ touched: true, active: true })
  const { sound, setListening, setBed, MASTER_LEVEL, BED_LEVEL } = await load()
  setBed('night')
  assert.equal(sound.bed, 'night')
  assert.equal(FakeAudioContext.instances.length, 0, 'nothing is made while Listen is off')

  setListening(true)
  assert.equal(env.store.get('parthenon.listen'), '1')
  const ctx = FakeAudioContext.instances[0]
  assert.ok(ctx, 'the context is made inside the gesture')
  assert.equal(ctx.resumes, 1, 'and resumed inside it')
  await flush()
  assert.equal(ctx.state, 'running')
  const g = graph(ctx)
  assert.equal(g.master.gain.target, MASTER_LEVEL)
  assert.equal(g.ambience.gain.target, 1)
  assert.equal(g.beds.length, 1)
  assert.equal(g.beds[0].gain.target, BED_LEVEL.night)
  assert.equal(env.listening('pointerdown'), 0, 'no gesture listeners left once running')
})

test('holdDuck counts its holders, and each release counts once', async () => {
  install({ touched: true, active: true })
  const { sound, setListening, setBed, holdDuck, DUCK_LEVEL } = await load()
  setListening(true)
  setBed('night')
  await flush()
  const { ambience } = graph(FakeAudioContext.instances[0])
  const a = holdDuck()
  const b = holdDuck()
  await flush()
  assert.equal(sound.ducked, true)
  assert.equal(ambience.gain.target, DUCK_LEVEL)
  a()
  a()
  await flush()
  assert.equal(sound.ducked, true, 'one holder is still speaking')
  assert.equal(ambience.gain.target, DUCK_LEVEL)
  b()
  await flush()
  assert.equal(sound.ducked, false)
  assert.equal(ambience.gain.target, 1)
})

test('the duck is deep enough for a voice to stand forward', async () => {
  install()
  const { DUCK_LEVEL, BED_LEVEL, MASTER_LEVEL } = await load()
  const db = (x) => 20 * Math.log10(x)
  assert.ok(db(DUCK_LEVEL) <= -12, `duck ${db(DUCK_LEVEL).toFixed(1)} dB`)
  const levels = Object.values(BED_LEVEL).map((v) => db(v * MASTER_LEVEL))
  assert.ok(Math.max(...levels) < 0)
})

test('setBed crossfades, retires the faded bed, and the Listen switch sleeps the context', async () => {
  const env = install({ touched: true, active: true })
  const { sound, setListening, setBed, BED_LEVEL } = await load()
  setListening(true)
  setBed('night')
  await flush()
  const ctx = FakeAudioContext.instances[0]
  const night = graph(ctx).beds[0]

  setBed('now')
  await flush()
  const beds = graph(ctx).beds
  const now = beds.find((b) => b !== night)
  assert.equal(night.gain.target, 0)
  assert.equal(now.gain.target, BED_LEVEL.now)
  env.timers.advance(7000)
  assert.equal(night.disconnected, true, 'the faded bed is taken apart')
  assert.equal(now.disconnected, false)

  setBed('nowhere')
  assert.equal(sound.bed, null, 'an unknown bed is no bed')
  setBed('now')

  setListening(false)
  assert.equal(env.store.get('parthenon.listen'), '0')
  await flush()
  const { master } = graph(ctx)
  assert.equal(master.gain.target, 0)
  assert.ok(master.gain.events.some(([kind, v]) => kind === 'set' && v === 0), 'the fade lands on true zero')
  env.timers.advance(1700)
  await flush()
  assert.equal(ctx.suspends, 1)
  assert.equal(ctx.state, 'suspended')

  setListening(true)
  await flush()
  assert.equal(ctx.state, 'running')
  assert.equal(master.gain.target, 0.9)
  assert.equal(FakeAudioContext.instances.length, 1, 'one context for the page')
})

test('a stored yes waits for the first touch; a touch that does not count is passed over', async () => {
  const env = install({ stored: { 'parthenon.listen': '1' } })
  const { sound, setBed, murmurInput, BED_LEVEL } = await load()
  setBed('night')
  assert.equal(sound.enabled, true)
  assert.equal(sound.waiting, true, 'on, and waiting for the page to be touched')
  assert.equal(murmurInput(), null)
  await flush()
  assert.equal(FakeAudioContext.instances.length, 0, 'no context before a touch, so no warning')
  assert.equal(env.listening('pointerdown'), 1)
  assert.equal(env.listening('keydown'), 1)

  // A finger's pointerdown does not unlock sound; its pointerup does.
  env.userActivation.hasBeenActive = true
  env.fire('pointerdown')
  assert.equal(FakeAudioContext.instances.length, 0)
  env.userActivation.isActive = true
  env.fire('pointerup')
  const ctx = FakeAudioContext.instances[0]
  assert.ok(ctx)
  assert.equal(sound.waiting, false)
  await flush()
  await flush()
  assert.equal(ctx.state, 'running')
  const g = graph(ctx)
  assert.equal(g.master.gain.target, 0.9)
  assert.equal(g.beds[0].gain.target, BED_LEVEL.night)
  assert.equal(env.listening('pointerdown'), 0)
  const m = murmurInput()
  assert.equal(m.ctx, ctx)
  assert.equal(m.input, g.murmur)
})

test('turning Listen off while it waits for a touch: no longer waiting, no listeners', async () => {
  const env = install({ stored: { 'parthenon.listen': '1' } })
  const { sound, setBed, toggleListening } = await load()
  setBed('night')
  assert.equal(sound.waiting, true)
  toggleListening()
  assert.equal(sound.enabled, false)
  assert.equal(sound.waiting, false)
  assert.equal(env.listening('pointerdown'), 0)
  assert.equal(env.store.get('parthenon.listen'), '0')
  env.userActivation.hasBeenActive = env.userActivation.isActive = true
  env.fire('pointerup')
  assert.equal(FakeAudioContext.instances.length, 0)
})

test('a browser without userActivation still waits for a touch, then wakes after a hidden spell', async () => {
  const env = install({ stored: { 'parthenon.listen': '1' } })
  delete env.win.navigator.userActivation
  const { setBed } = await load()
  setBed('night')
  await flush()
  assert.equal(FakeAudioContext.instances.length, 0)
  env.fire('keydown')
  const ctx = FakeAudioContext.instances[0]
  assert.ok(ctx)
  await flush()
  assert.equal(ctx.state, 'running')

  env.doc.hidden = true
  env.fireDoc('visibilitychange')
  env.timers.advance(1700)
  await flush()
  assert.equal(ctx.state, 'suspended')
  env.doc.hidden = false
  env.fireDoc('visibilitychange')
  await flush()
  assert.equal(ctx.state, 'running', 'resumed on return without waiting for another touch')
})

test('a hidden tab fades out and sleeps; seen again, it wakes', async () => {
  const env = install({ touched: true, active: true })
  const { setListening, setBed } = await load()
  setListening(true)
  setBed('night')
  await flush()
  const ctx = FakeAudioContext.instances[0]
  const { master } = graph(ctx)

  env.doc.hidden = true
  env.fireDoc('visibilitychange')
  assert.equal(master.gain.target, 0)
  env.timers.advance(1700)
  await flush()
  assert.equal(ctx.state, 'suspended')

  env.userActivation.isActive = false
  env.doc.hidden = false
  env.fireDoc('visibilitychange')
  await flush()
  assert.equal(ctx.state, 'running')
  assert.equal(master.gain.target, 0.9)
})

test('two copies of the module share one engine (a dev server swapping files)', async () => {
  install({ touched: true, active: true })
  const a = await load()
  const b = await load()
  assert.equal(a.sound, b.sound)
  a.setListening(true)
  b.setBed('night')
  await flush()
  assert.equal(b.sound.enabled, true)
  assert.equal(a.sound.bed, 'night')
  assert.equal(FakeAudioContext.instances.length, 1)
})

// ---- The beds themselves ----

for (const name of ['ancient', 'now', 'night']) {
  test(`the ${name} bed: no burst after a long sleep, and every passing sound lets go`, async () => {
    install()
    const { buildBed } = await load()
    const ctx = new FakeAudioContext()
    ctx.state = 'running'
    const out = ctx.createGain()
    const bed = buildBed(name, ctx, out)
    const kitNodes = ctx.nodes.length

    bed.schedule(1.2)
    const firstWindow = ctx.starts.length

    // Ten minutes asleep, then one tick.
    ctx.currentTime = 600
    ctx.starts.length = 0
    bed.schedule(601.2)
    assert.ok(ctx.starts.every((t) => t >= 600), 'nothing is scheduled in the past')
    assert.ok(ctx.starts.length <= Math.max(firstWindow, 1) * 4 + 30, `${ctx.starts.length} events after a sleep`)

    // A steady run of ticks never writes behind the clock, and the pace holds.
    const before = ctx.starts.length
    for (let i = 0; i < 40; i++) {
      ctx.currentTime += 0.25
      const from = ctx.starts.length
      bed.schedule(ctx.currentTime + 1.2)
      assert.ok(ctx.starts.slice(from).every((s) => s >= ctx.currentTime), 'written ahead of the clock')
    }
    const perSecond = (ctx.starts.length - before) / 10
    assert.ok(perSecond < 60, `${perSecond.toFixed(1)} sounds a second`)

    // Every one-shot source ends; all their nodes are let go.
    const passing = ctx.nodes.slice(kitNodes)
    for (const n of passing) if (n instanceof FakeSource) n.end()
    const held = passing.filter((n) => !n.disconnected)
    assert.equal(held.length, 0, `${held.length} passing nodes still connected`)

    // stop() takes the bed's own loops apart.
    bed.stop()
    const kit = ctx.nodes.slice(1, kitNodes).filter((n) => n !== out)
    assert.ok(kit.every((n) => n.disconnected), 'the loops and their filters are let go')
  })
}

test('buildBed knows only the three beds', async () => {
  install()
  const { buildBed, BEDS } = await load()
  assert.deepEqual(BEDS, ['ancient', 'now', 'night'])
  assert.equal(buildBed('storm', new FakeAudioContext(), null), null)
})

// ---- The recorded beds ----

const settleAll = async (n = 6) => {
  for (let i = 0; i < n; i++) await flush()
}
const recordedSources = (ctx) => ctx.nodes.filter((n) => n.kind === 'bufferSource' && n.buffer && n.buffer.duration === 16 && n.startedAt !== null)
const oscillators = (ctx) => ctx.nodes.filter((n) => n.kind === 'oscillator')

test('a recording listed in beds.json is heard in place of the drawn bed', async () => {
  const env = install({
    touched: true,
    active: true,
    decode: 'ok',
    files: { '/media/sound/beds.json': BEDS_JSON, '/media/sound/night.m4a': 'audio' }
  })
  const { setListening, setBed, BED_LEVEL } = await load()
  setListening(true)
  setBed('night')
  await settleAll()
  const ctx = FakeAudioContext.instances[0]
  env.timers.advance(300) // one tick of the beds
  assert.deepEqual(env.fetched, ['/media/sound/beds.json', '/media/sound/night.m4a'])
  assert.equal(ctx.decodes, 1)
  const stretches = recordedSources(ctx)
  assert.ok(stretches.length >= 2, `${stretches.length} stretches of the recording, two voices`)
  assert.equal(oscillators(ctx).length, 0, 'no drawn crickets under a recording')
  assert.equal(graph(ctx).beds[0].gain.target, BED_LEVEL.night, 'the bed gain, and so the duck and the fades, are the same')

  // Leaving and coming back: the recording is not fetched again.
  setBed('now')
  await settleAll()
  setBed('night')
  await settleAll()
  assert.equal(env.fetched.filter((u) => u.endsWith('night.m4a')).length, 1)
  assert.equal(env.fetched.filter((u) => u.endsWith('beds.json')).length, 1, 'the list is read once')
})

test('a missing recording, a failed decode or a load that never answers: the drawn bed', async () => {
  for (const [label, opts, wait] of [
    ['missing', { decode: 'ok', files: { '/media/sound/beds.json': BEDS_JSON, '/media/sound/night.m4a': 404 } }, 0],
    ['no list', { decode: 'ok', files: {} }, 0],
    ['undecodable', { decode: 'fail', files: { '/media/sound/beds.json': BEDS_JSON, '/media/sound/night.m4a': 'audio' } }, 0],
    ['stalled', { decode: 'ok', files: { '/media/sound/beds.json': BEDS_JSON, '/media/sound/night.m4a': 'hang' } }, 9500]
  ]) {
    const env = install({ touched: true, active: true, ...opts })
    const { setListening, setBed } = await load()
    setListening(true)
    setBed('night')
    await settleAll()
    if (wait) {
      env.timers.advance(wait)
      await settleAll()
    }
    env.timers.advance(2000)
    const ctx = FakeAudioContext.instances[0]
    assert.equal(recordedSources(ctx).length, 0, `${label}: nothing recorded plays`)
    assert.ok(oscillators(ctx).length > 0, `${label}: the drawn crickets sing`)
  }
})

test('Save-Data, or a browser that cannot decode: nothing is fetched, the bed is drawn', async () => {
  for (const opts of [{ saveData: true, decode: 'ok' }, { decode: 'none' }]) {
    const env = install({ touched: true, active: true, files: { '/media/sound/beds.json': BEDS_JSON, '/media/sound/night.m4a': 'audio' }, ...opts })
    const { setListening, setBed } = await load()
    setListening(true)
    setBed('night')
    await settleAll()
    env.timers.advance(600)
    assert.deepEqual(env.fetched, [])
    assert.ok(oscillators(FakeAudioContext.instances[0]).length > 0)
  }
})

test('the recorded bed: stretches fade into each other, never behind the clock, and let go', async () => {
  install()
  const { buildRecordedBed, CROSSFADE } = await load()
  for (const name of ['ancient', 'now', 'night']) {
    const ctx = new FakeAudioContext()
    ctx.state = 'running'
    const out = ctx.createGain()
    const rec = { buffer: fakeRecording(16), loopStart: 0.1, loopEnd: 16 }
    const bed = buildRecordedBed(name, ctx, out, rec)
    bed.schedule(40)
    const stretches = recordedSources(ctx)
    assert.ok(stretches.length >= 6, `${name}: ${stretches.length} stretches in forty seconds`)
    for (const s of stretches) {
      assert.ok(s.offset >= 0.1 - 1e-9 && s.offset + s.duration <= 16 + 1e-9, 'inside the loop points')
      assert.ok(s.duration >= 3 * CROSSFADE - 1e-9)
      const g = [...s.outputs][0]
      const curves = g.gain.events.filter((e) => e[0] === 'curve')
      assert.equal(curves.length, 2, 'a fade in and a fade out')
      assert.equal(curves[0][1], s.startedAt)
      assert.equal(curves[1][1] + curves[1][2], s.startedAt + s.duration, 'the fade out ends with the stretch')
      assert.ok(curves[0][4] > 0.99 && curves[1][4] < 0.01)
    }
    // Within one voice, each stretch begins as the one before starts to fade.
    const byVoice = new Map()
    for (const s of stretches) {
      const voice = [...[...s.outputs][0].outputs][0]
      if (!byVoice.has(voice)) byVoice.set(voice, [])
      byVoice.get(voice).push(s)
    }
    assert.equal(byVoice.size, 2, 'two voices')
    for (const list of byVoice.values()) {
      for (let i = 1; i < list.length; i++) {
        const prev = list[i - 1]
        const fadeOut = [...prev.outputs][0].gain.events.filter((e) => e[0] === 'curve')[1]
        assert.ok(Math.abs(list[i].startedAt - fadeOut[1]) < 1e-9, 'no gap and no pile-up')
      }
    }
    // Ten minutes asleep, then one tick: nothing in the past, no burst.
    ctx.currentTime = 600
    ctx.starts.length = 0
    bed.schedule(601.2)
    assert.ok(ctx.starts.every((t) => t >= 600))
    assert.ok(ctx.starts.length <= 60)
    // Every stretch that ends lets go of its nodes; stop() takes the rest apart.
    for (const s of stretches) s.end()
    assert.ok(stretches.every((s) => s.disconnected && [...s.outputs].length === 0))
    bed.stop()
  }
})

test('buildRecordedBed needs a known bed and a recording', async () => {
  install()
  const { buildRecordedBed } = await load()
  const ctx = new FakeAudioContext()
  assert.equal(buildRecordedBed('storm', ctx, ctx.createGain(), { buffer: fakeRecording() }), null)
  assert.equal(buildRecordedBed('night', ctx, ctx.createGain(), null), null)
})

test('the city at dusk draws no engine: no sawtooth anywhere in the now bed', async () => {
  install()
  const { buildBed } = await load()
  const ctx = new FakeAudioContext()
  ctx.state = 'running'
  const bed = buildBed('now', ctx, ctx.createGain())
  for (let t = 0; t < 120; t += 0.25) {
    ctx.currentTime = t
    bed.schedule(t + 1.2)
  }
  assert.equal(oscillators(ctx).filter((o) => o.type === 'sawtooth').length, 0)
})
