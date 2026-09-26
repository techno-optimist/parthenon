import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildWebModel,
  nodeDossier,
  searchNodes,
  cityWords,
  tieStance,
  isChatterEdge,
  nodeRadius,
  createWeb,
  syncWeb,
  stepWeb,
  settleWeb,
  neighbourhood,
  setChatterVisible,
  labelRect,
  placeLabels,
  segmentMeetsBox,
  boxesMeet,
  fitView,
  nodeAt,
  updateEmphasis,
  tidyArrivals,
  appearance,
  drift,
  parseColor,
  resolvePalette,
  drawWeb,
  drawConstellation,
  drawOverlay,
  placeStars,
  toScreen,
  toWorld,
  easeView,
  labelVoice,
  labelText,
  labelStyle,
  clearance,
  keyRadius,
  updateFaces,
  faceRadius,
  flashBeat,
  tidyFlashes,
  flashLeft,
  settleFor,
  settleCap,
  webInWords,
  findByName,
  nameKey,
  R_MIN,
  R_MAX,
  TOP_LABELS,
  LABEL_FLOOR,
  FACE_GROW,
  FACE_MS,
  FLASH_MS
} from './web.js'

const node = (uuid, name, type) => ({ uuid, name, labels: type ? ['Entity', type] : ['Entity'], summary: `${name} of Athens` })
const edge = (a, b, name, fact = '') => ({ source_node_uuid: a, target_node_uuid: b, name, fact })

const athens = () => ({
  graph_id: 'g',
  nodes: [
    node('s', 'Socrates', 'Philosopher'),
    node('c', 'Crito', 'Follower'),
    node('p', 'Plato', 'Follower'),
    node('m', 'Meletus', 'Accuser'),
    node('j', 'Jurors', 'CitizenJuror'),
    node('x', 'Xanthippe', 'FamilyMember'),
    node('t', 'Twitter', ''),
    node('r', 'Reddit', ''),
    node('h', 'Hemlock', '')
  ],
  edges: [
    edge('c', 's', 'RELATED_TO', 'Crito is Socrates’ oldest friend.'),
    edge('c', 's', 'DEFENDS', 'Crito plans to bribe the guards so Socrates can escape.'),
    edge('p', 's', 'FOLLOWS', 'Plato is a follower of Socrates.'),
    edge('m', 's', 'ACCUSES', 'Meletus accuses Socrates of impiety.'),
    edge('j', 's', 'ACCUSES', 'The jurors convicted Socrates.'),
    edge('x', 's', 'RELATED_TO', 'Xanthippe is the wife of Socrates.'),
    edge('s', 't', 'POSTED', 'On Twitter, Socrates posted: “Know thyself.”'),
    edge('c', 'p', 'QUOTED', 'On Twitter, Crito quoted Plato’s post “He was the best of us.”'),
    edge('c', 'p', 'LIKED_POST_OF', 'On Reddit, Crito liked Plato’s post: “He was the best.”'),
    edge('m', 'j', 'FOLLOWS', 'On Reddit, Meletus followed the user “jurors_12”'),
    edge('s', 's', 'RELATES_TO', 'Socrates is himself.')
  ]
})

test('platform hubs are never in the sky', () => {
  const m = buildWebModel(athens())
  assert.ok(!m.nodes.some((n) => n.name === 'Twitter' || n.name === 'Reddit'))
  assert.equal(m.nodes.length, 7)
})

test('scroll ties are structural, the square is chatter, even with an activity name', () => {
  assert.equal(isChatterEdge('FOLLOWS', 'Plato is a follower of Socrates.'), false)
  assert.equal(isChatterEdge('FOLLOWS', 'On Reddit, Meletus followed the user "jurors"'), true)
  assert.equal(isChatterEdge('COMMENTED', ''), true)
  assert.equal(isChatterEdge('ACCUSES', 'On Twitter, x'), false)
  const m = buildWebModel(athens())
  const plato = m.links.find((l) => l.key === 'p|s')
  assert.equal(plato.structural, 1)
  assert.equal(plato.chatter, 0)
  const cp = m.links.find((l) => l.key === 'c|p')
  assert.equal(cp.structural, 0)
  assert.equal(cp.chatter, 2)
})

test('parallel ties merge into one thread with a count', () => {
  const m = buildWebModel(athens())
  const cs = m.links.filter((l) => (l.source === 'c' && l.target === 's') || (l.source === 's' && l.target === 'c'))
  assert.equal(cs.length, 1)
  assert.equal(cs[0].structural, 2)
  assert.equal(cs[0].ties.length, 2)
  assert.equal(cs[0].stance, 'supports')
  assert.equal(m.links.find((l) => l.key === 'm|s').stance, 'opposes')
})

test('stances read from the tie name', () => {
  assert.equal(tieStance('SUPPORTS'), 'supports')
  assert.equal(tieStance('DEFENDS'), 'supports')
  assert.equal(tieStance('OPPOSES'), 'opposes')
  assert.equal(tieStance('CRITICIZES'), 'opposes')
  assert.equal(tieStance('MOCKS'), 'opposes')
  assert.equal(tieStance('RELATES_TO'), '')
  assert.equal(tieStance(''), '')
})

test('radius runs from 3 to 14 by structural degree', () => {
  assert.equal(nodeRadius(0, 10), R_MIN)
  assert.equal(nodeRadius(10, 10), R_MAX)
  assert.ok(nodeRadius(3, 10) > R_MIN && nodeRadius(3, 10) < R_MAX)
  assert.ok(nodeRadius(0, 0) >= R_MIN)
  const m = buildWebModel(athens())
  const soc = m.nodes.find((n) => n.name === 'Socrates')
  assert.equal(soc.r, R_MAX)
  assert.equal(soc.rank, 0)
  assert.ok(soc.top)
  for (const n of m.nodes) assert.ok(n.r >= R_MIN && n.r <= R_MAX)
  assert.ok(TOP_LABELS >= 12 && TOP_LABELS <= 18)
})

test('untyped names are things spoken of, listed last in the legend', () => {
  const m = buildWebModel(athens())
  const hemlock = m.nodes.find((n) => n.name === 'Hemlock')
  assert.equal(hemlock.family, 'things')
  assert.equal(hemlock.role, '')
  assert.equal(m.legend[m.legend.length - 1].key, '')
})

test('the engine’s words become the city’s', () => {
  assert.equal(cityWords('On Twitter, Socrates posted: “Know thyself.”'), 'In the Agora, Socrates said: “Know thyself.”')
  assert.equal(cityWords('On Reddit, Meletus followed the user “jurors_12”'), 'In the Stoa, Meletus followed Jurors')
  assert.equal(cityWords('On Reddit, Stelios searched for the user “stelios_moraitis”'), 'In the Stoa, Stelios asked after Stelios Moraitis')
  assert.equal(cityWords('On Reddit, Crito liked Plato\'s post: “x”'), 'In the Stoa, Crito nodded to Plato’s words: “x”')
  assert.ok(!/sim_|proj_/.test(cityWords('see sim_2c79002f1b0c now')))
})

test('the dossier leads with the scroll’s facts, the chatter kept apart', () => {
  const m = buildWebModel(athens())
  const d = nodeDossier(m, 'c')
  assert.equal(d.node.name, 'Crito')
  assert.equal(d.facts.length, 2)
  assert.ok(d.facts.every((f) => f.otherName === 'Socrates'))
  assert.equal(d.chatterFacts.length, 2)
  assert.equal(d.neighbours[0].name, 'Socrates')
  assert.equal(nodeDossier(m, 'nobody'), null)
  // A tie with no fact still reads as a sentence.
  const bare = buildWebModel({ nodes: [node('a', 'Anytus', 'Accuser'), node('b', 'Lycon', 'Accuser')], edges: [edge('a', 'b', 'ADVISES', '')] })
  assert.equal(nodeDossier(bare, 'a').facts[0].text, 'Anytus advises Lycon.')
})

test('search finds by name start, word start, then anywhere', () => {
  const m = buildWebModel(athens())
  assert.deepEqual(searchNodes(m.nodes, 'cri').map((n) => n.name), ['Crito'])
  assert.equal(searchNodes(m.nodes, 'SOC')[0].name, 'Socrates')
  assert.equal(searchNodes(m.nodes, 'ant')[0].name, 'Xanthippe')
  assert.deepEqual(searchNodes(m.nodes, ''), [])
  assert.equal(searchNodes(m.nodes, 'follower').length, 2)
})

test('the layout settles, keeps names apart and is the same on every visit', () => {
  const run = () => {
    const w = createWeb({ width: 600, height: 700 })
    syncWeb(w, buildWebModel(athens()), { now: 0 })
    settleWeb(w, 600)
    return w
  }
  const a = run()
  const b = run()
  assert.equal(a.alpha, 0)
  for (const n of a.nodes) {
    assert.ok(Number.isFinite(n.x) && Number.isFinite(n.y))
    assert.equal(n.x, b.byId.get(n.id).x)
  }
  for (let i = 0; i < a.nodes.length; i++) {
    for (let j = i + 1; j < a.nodes.length; j++) {
      const p = a.nodes[i]
      const q = a.nodes[j]
      assert.ok(Math.hypot(p.x - q.x, p.y - q.y) > p.r + q.r, `${p.name} and ${q.name} overlap`)
    }
  }
  // Neighbourhoods follow the drawn ties: the chatter only while it shows.
  assert.deepEqual([...neighbourhood(a, 'c')].sort(), ['c', 's'])
  setChatterVisible(a, true)
  assert.deepEqual([...neighbourhood(a, 'c')].sort(), ['c', 'p', 's'])
})

test('a new reading keeps every place and blooms the newcomers beside their ties', () => {
  const w = createWeb({ width: 600, height: 700 })
  const g = athens()
  syncWeb(w, buildWebModel(g), { now: 0 })
  settleWeb(w, 600)
  const before = new Map(w.nodes.map((n) => [n.id, [n.x, n.y]]))
  const soc = w.byId.get('s')

  g.nodes.push(node('a', 'Anytus', 'Accuser'))
  g.edges.push(edge('a', 's', 'ACCUSES', 'Anytus accuses Socrates.'))
  const res = syncWeb(w, buildWebModel(g), { now: 5000 })
  assert.deepEqual(res.added, ['a'])
  assert.deepEqual(res.addedLinks, ['a|s'])
  const anytus = w.byId.get('a')
  assert.equal(anytus.bornAt, 5000)
  assert.ok(Math.hypot(anytus.x - soc.x, anytus.y - soc.y) < 60, 'the newcomer stands near the one they are tied to')
  assert.ok(w.alpha > 0 && w.alpha < 0.5, 'a growing sky is only nudged')
  settleWeb(w, 600)
  // Nothing re-explodes: the names already there move only a little.
  for (const [id, [x, y]] of before) {
    const n = w.byId.get(id)
    assert.ok(Math.hypot(n.x - x, n.y - y) < 45, `${n.name} moved too far`)
  }
  // The same reading again changes nothing.
  const again = syncWeb(w, buildWebModel(g), { now: 9000 })
  assert.deepEqual(again.added, [])
  assert.equal(w.alpha, 0)
})

test('remembered positions are used and barely disturbed', () => {
  const w = createWeb()
  const stored = { s: [0, 0], c: [80, 0], p: [0, 80], m: [-80, 0], j: [-80, 60], x: [60, -60], h: [120, 120] }
  syncWeb(w, buildWebModel(athens()), { now: 0, stored })
  assert.equal(w.byId.get('c').x, 80)
  assert.ok(w.alpha <= 0.1)
})

test('arrivals and emphasis ease and then rest', () => {
  const w = createWeb()
  syncWeb(w, buildWebModel(athens()), { now: 0, intro: true })
  assert.ok(w.byId.get('s').introAt === 0)
  assert.ok(w.byId.get('h').introAt > 0)
  assert.equal(appearance(w.byId.get('h'), 0, false), 0)
  assert.equal(appearance(w.byId.get('h'), 0, true), 1, 'still under reduced motion')
  assert.equal(tidyArrivals(w, 100), true)
  assert.equal(tidyArrivals(w, 60000), false)
  assert.deepEqual(drift(w.byId.get('s'), 1234, true), [0, 0])

  updateEmphasis(w, 'c', 16, true)
  assert.equal(w.byId.get('c').em, 1)
  assert.equal(w.byId.get('s').em, 1)
  assert.ok(w.byId.get('m').em < 0.5)
  assert.equal(w.byId.get('c').hot, 1)
  const cs = w.links.find((l) => l.key === 'c|s')
  const ms = w.links.find((l) => l.key === 'm|s')
  assert.ok(cs.em > ms.em)
  updateEmphasis(w, null, 16, true)
  assert.ok(w.nodes.every((n) => n.em === 1))
})

test('labels never overlap each other or cover another star', () => {
  const items = [
    { id: 'a', x: 100, y: 100, r: 8, w: 70, forced: false },
    { id: 'b', x: 150, y: 102, r: 6, w: 60, forced: false },
    { id: 'c', x: 104, y: 120, r: 4, w: 80, forced: false }
  ]
  const stars = items.map(({ id, x, y, r }) => ({ id, x, y, r }))
  const out = placeLabels(items, stars)
  const rects = [...out.values()]
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) assert.ok(!boxesMeet(rects[i], rects[j]))
  }
  for (const [id, rect] of out) {
    for (const s of stars) {
      if (s.id === id) continue
      const nx = Math.max(rect.x0, Math.min(s.x, rect.x1))
      const ny = Math.max(rect.y0, Math.min(s.y, rect.y1))
      assert.ok(Math.hypot(s.x - nx, s.y - ny) >= s.r, `${id}'s name covers ${s.id}`)
    }
  }
  // A name keeps the side it had.
  const again = placeLabels(items, stars, { prev: out })
  for (const [id, rect] of out) assert.equal(again.get(id).side, rect.side)
  // A crowded name is left out unless it is the one pointed at.
  const crowd = [
    { id: 'a', x: 0, y: 0, r: 4, w: 700, forced: false },
    { id: 'b', x: 0, y: 0.5, r: 4, w: 700, forced: false }
  ]
  const bounds = { x0: -300, x1: 300, y0: -300, y1: 300 }
  assert.equal(placeLabels(crowd, [], { bounds }).size, 0)
  const forced = placeLabels([{ ...crowd[0], forced: true }], [], { bounds })
  assert.equal(forced.get('a').crowded, true)
  assert.equal(labelRect('l', 0, 0, 5, 50).x1, -11)
  // A name keeps out from under a block (the legend).
  const blocked = placeLabels([{ id: 'a', x: 0, y: 0, r: 5, w: 50 }], [], { blocks: [{ x0: 0, x1: 200, y0: -20, y1: 20 }] })
  assert.notEqual(blocked.get('a').side, 'r')
  // A name would rather not lie across its own thread.
  const threaded = placeLabels([{ id: 'a', x: 0, y: 0, r: 5, w: 50, threads: [[0, 0, 200, 0]] }], [])
  assert.notEqual(threaded.get('a').side, 'r')
  assert.equal(segmentMeetsBox(0, 0, 100, 0, { x0: 10, x1: 20, y0: -5, y1: 5 }), true)
  assert.equal(segmentMeetsBox(0, 0, 0, 100, { x0: 10, x1: 20, y0: -5, y1: 5 }), false)
})

test('fit keeps every star and printed name inside the frame', () => {
  const nodes = [
    { id: 'a', x: -300, y: -100, r: 14 },
    { id: 'b', x: 300, y: 250, r: 5 },
    { id: 'c', x: 0, y: 0, r: 8 }
  ]
  const box = { x0: 16, y0: 12, x1: 584, y1: 688 }
  const labelsAt = () => new Map([['b', { x0: 11, x1: 131, y0: -7, y1: 7 }]])
  const v = fitView(nodes, box, { labelsAt, minK: 0.2, maxK: 3 })
  const bx = 300 * v.k + v.tx + 131
  assert.ok(bx <= box.x1 + 1, 'the right name fits')
  assert.ok(-300 * v.k + v.tx - 14 >= box.x0 - 1)
  assert.ok(250 * v.k + v.ty + 7 <= box.y1 + 1)
  // A lone star sits in the middle.
  const lone = fitView([{ id: 'z', x: 40, y: 40, r: 6 }], box)
  assert.ok(Math.abs(40 * lone.k + lone.tx - 300) < 2)
  // An empty sky does not fail.
  assert.equal(fitView([], box).k, 1)
})

test('the star under a finger is found with slop', () => {
  const nodes = [{ id: 'a', x: 0, y: 0, r: 4 }, { id: 'b', x: 100, y: 0, r: 10 }]
  const view = { k: 1, tx: 50, ty: 50 }
  assert.equal(nodeAt(nodes, view, 52, 51)?.id, 'a')
  assert.equal(nodeAt(nodes, view, 158, 50, 6)?.id, 'b')
  assert.equal(nodeAt(nodes, view, 100, 120), null)
  // A stretched view finds stars where they are drawn.
  const tall = { k: 1, tx: 50, ty: 50, s: 2 }
  assert.equal(nodeAt([{ id: 'c', x: 0, y: 40, r: 4 }], tall, 50, 130)?.id, 'c')
  // An open face is a wider target.
  assert.equal(nodeAt([{ id: 'd', x: 0, y: 0, r: 4, face: 1 }], view, 50 + 13, 50)?.id, 'd')
})

test('palette resolves tokens and falls back', () => {
  assert.deepEqual(parseColor('#f0b660'), [240, 182, 96])
  assert.deepEqual(parseColor('#fff'), [255, 255, 255])
  assert.deepEqual(parseColor('rgb(1, 2, 3)'), [1, 2, 3])
  assert.deepEqual(parseColor('nonsense', [9, 9, 9]), [9, 9, 9])
  const p = resolvePalette((name) => (name === '--p-gold' ? '#010203' : ''))
  assert.deepEqual(p.gold, [1, 2, 3])
  assert.deepEqual(p.families.people, [1, 2, 3])
  assert.deepEqual(p.families.institutions, [143, 184, 216])
})

test('drawing runs against a bare 2D context', () => {
  const calls = []
  const gradient = { addColorStop: () => {} }
  const ctx = new Proxy({}, {
    get: (target, key) => {
      if (key in target) return target[key]
      if (key === 'createLinearGradient' || key === 'createRadialGradient') return () => gradient
      return (...args) => calls.push(key)
    },
    set: (target, key, value) => { target[key] = value; return true }
  })
  const w = createWeb()
  const g = athens()
  syncWeb(w, buildWebModel(g), { now: 0 })
  settleWeb(w, 300)
  g.nodes.push(node('a', 'Anytus', 'Accuser'))
  g.edges.push(edge('a', 's', 'ACCUSES', 'Anytus accuses Socrates.'))
  syncWeb(w, buildWebModel(g), { now: 1000 })
  const labels = new Map([['s', { x0: 10, x1: 80, y0: 0, y1: 15, side: 'r' }]])
  drawWeb(ctx, w, {
    width: 600, height: 480, view: { k: 1, tx: 300, ty: 240 }, palette: resolvePalette(), time: 1500, now: 1500,
    chatter: true, labels, center: 'c', focus: 'c', dust: [{ u: 0.5, v: 0.5, r: 1, a: 0.2, s: 1, p: 0 }],
    fonts: { display: 'Cormorant Garamond', inscription: 'Cinzel' }
  })
  assert.ok(calls.includes('fillText'))
  assert.ok(calls.includes('arc'))
  assert.ok(calls.filter((c) => c === 'stroke').length > 3)
  assert.match(ctx.font, /Cormorant Garamond/)

  // A face is drawn clipped to its disc once its portrait is there.
  calls.length = 0
  w.byId.get('s').face = 1
  const img = { naturalWidth: 400, naturalHeight: 600 }
  drawConstellation(ctx, w, { width: 600, height: 480, palette: resolvePalette(), now: 9000, faceOf: (n) => (n.id === 's' ? img : null), labels: new Map() })
  assert.ok(calls.includes('clip'))
  assert.ok(calls.includes('drawImage'))

  // A beat from the square passes over the sky, steady under reduced motion.
  calls.length = 0
  flashBeat(w, 's', 'c', 9000)
  drawOverlay(ctx, w, { palette: resolvePalette(), now: 9100, time: 9100 })
  assert.ok(calls.includes('arc'))
  calls.length = 0
  drawOverlay(ctx, w, { palette: resolvePalette(), now: 9100, time: 0, still: true })
  assert.ok(calls.includes('stroke'))
})

test('a citizen’s name is set in the display face, a thing in inscription capitals', () => {
  const m = buildWebModel(athens())
  const soc = m.nodes.find((n) => n.name === 'Socrates')
  const hemlock = m.nodes.find((n) => n.name === 'Hemlock')
  assert.equal(labelVoice(soc), 'voice')
  assert.equal(labelVoice(hemlock), 'thing')
  assert.equal(labelVoice({ family: 'places' }), 'thing')
  assert.equal(labelText(soc), 'Socrates')
  assert.equal(labelText(hemlock), 'HEMLOCK')
  const fonts = { display: "'Cormorant Garamond', serif", inscription: "'Cinzel', serif" }
  const voice = labelStyle('voice', fonts)
  assert.equal(voice.font, "600 15px 'Cormorant Garamond', serif")
  assert.equal(voice.tracking, 0)
  const thing = labelStyle('thing', fonts)
  assert.equal(thing.font, "600 11px 'Cinzel', serif")
  assert.ok(Math.abs(thing.tracking - 1.32) < 0.01, 'tracked 0.12em')
  assert.ok(thing.h < voice.h)
})

test('a dimmed name still reads at 4.5:1 on the night sky', () => {
  const P = resolvePalette()
  const lum = (c) => {
    const [r, g, b] = c.map((v) => {
      const x = v / 255
      return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4)
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const over = (fg, bg, a) => fg.map((v, i) => v * a + bg[i] * (1 - a))
  const sky = [16, 20, 27] // the deep well of the sky, a shade over the surface
  const ratio = (fg) => (lum(fg) + 0.05) / (lum(sky) + 0.05)
  assert.ok(ratio(over(P.ink2, sky, LABEL_FLOOR)) >= 4.5, `ink-2 at ${LABEL_FLOOR} reads ${ratio(over(P.ink2, sky, LABEL_FLOOR)).toFixed(2)}:1`)
})

test('names stand clear of faces, keys and rings', () => {
  const n = { r: 6 }
  assert.equal(clearance(n), 6)
  assert.equal(clearance(n, { chosen: true }), 12)
  assert.ok(clearance(n, { key: true }) > clearance(n, { chosen: true }))
  assert.equal(clearance(n, { face: true }), 6 + FACE_GROW + 5)
  assert.ok(keyRadius(n) > n.r + FACE_GROW, 'the key rings the face, not the name')
  assert.ok(clearance(n, { key: true }) + 6 >= keyRadius(n) + 2, 'a keyed name starts beyond the ring')
})

test('faces open over their time and close again, at once under reduced motion', () => {
  const w = createWeb()
  syncWeb(w, buildWebModel(athens()), { now: 0 })
  const s = w.byId.get('s')
  assert.equal(updateFaces(w, new Set(['s']), FACE_MS / 2), true)
  assert.ok(s.face > 0.4 && s.face < 0.6)
  assert.ok(faceRadius(s) > s.r && faceRadius(s) < s.r + FACE_GROW)
  updateFaces(w, new Set(['s']), FACE_MS)
  assert.equal(s.face, 1)
  assert.equal(faceRadius(s), s.r + FACE_GROW)
  assert.equal(updateFaces(w, new Set(['s']), 16), false, 'resting')
  updateFaces(w, new Set(), 16, true)
  assert.equal(s.face, 0)
})

test('a beat from the square lights the speaker and the one addressed, then fades', () => {
  const w = createWeb()
  syncWeb(w, buildWebModel(athens()), { now: 0 })
  assert.equal(flashBeat(w, 'nobody', 's', 100), false)
  assert.equal(flashBeat(w, 'c', 's', 100), true)
  assert.equal(w.flashes[0].to, 's')
  flashBeat(w, 'm', 'm', 120)
  assert.equal(w.flashes[1].to, null, 'no one answers themselves')
  assert.equal(tidyFlashes(w, 200), true)
  assert.ok(flashLeft(w, 200) > 0 && flashLeft(w, 200) <= FLASH_MS)
  assert.equal(tidyFlashes(w, 120 + FLASH_MS + 1), false)
  for (let i = 0; i < 30; i++) flashBeat(w, 's', null, 5000 + i)
  assert.ok(w.flashes.length <= 12)
})

test('a phone’s tall sheet draws the constellation out to its height', () => {
  const nodes = [
    { id: 'a', x: -200, y: -40, r: 8 },
    { id: 'b', x: 200, y: 40, r: 8 },
    { id: 'c', x: 0, y: 0, r: 8 }
  ]
  const tall = { x0: 16, y0: 12, x1: 374, y1: 700 }
  const flat = fitView(nodes, tall)
  assert.equal(flat.s, 1)
  const v = fitView(nodes, tall, { stretch: 1.8 })
  assert.ok(v.s > 1.2 && v.s <= 1.8)
  assert.ok(Math.abs(v.k - flat.k) < 0.05, 'the width sets the scale; the height only draws it out')
  for (const n of nodes) {
    const [x, y] = toScreen(v, n.x, n.y)
    assert.ok(x - n.r >= tall.x0 - 1 && x + n.r <= tall.x1 + 1)
    assert.ok(y - n.r >= tall.y0 - 1 && y + n.r <= tall.y1 + 1)
    const [wx, wy] = toWorld(v, x, y)
    assert.ok(Math.abs(wx - n.x) < 1e-6 && Math.abs(wy - n.y) < 1e-6)
  }
  // A focus keeps the whole view's stretch.
  assert.equal(fitView(nodes.slice(0, 2), tall, { s: v.s }).s, v.s)
  // The camera eases the stretch with the rest.
  const cam = { k: 1, tx: 0, ty: 0, s: 1 }
  easeView(cam, v, 16)
  assert.ok(cam.s > 1 && cam.s < v.s)
  easeView(cam, v, 16, true)
  assert.equal(cam.s, v.s)
  placeStars({ nodes: nodes.map((n) => ({ ...n })) }, v)
})

test('a large sky settles a slice at a time', () => {
  const w = createWeb()
  syncWeb(w, buildWebModel(athens()), { now: 0 })
  let t = 0
  const clock = () => (t += 1)
  const steps = settleFor(w, 5, clock)
  assert.ok(steps >= 1 && steps <= 6)
  assert.ok(w.alpha > 0, 'not done in one slice')
  let total = steps
  while (w.alpha > 0 && total < 2000) total += settleFor(w, 1000, clock, 50)
  assert.equal(w.alpha, 0)
  assert.equal(settleCap(20), 400)
  assert.ok(settleCap(300) < 400 && settleCap(300) >= 140)
  assert.ok(settleCap(3000) >= 140)
})

test('the Web in words lists every name by role with its ties', () => {
  const m = buildWebModel(athens())
  const groups = webInWords(m)
  const names = groups.flatMap((g) => g.names.map((n) => n.name))
  assert.equal(names.length, m.nodes.length)
  assert.equal(groups[groups.length - 1].key, '', 'things spoken of come last')
  const soc = groups.flatMap((g) => g.names).find((n) => n.name === 'Socrates')
  assert.ok(soc.atOdds.includes('Meletus'))
  assert.ok(soc.allied.includes('Crito'))
  assert.ok(soc.tied.includes('Plato'))
  const hemlock = groups.flatMap((g) => g.names).find((n) => n.name === 'Hemlock')
  assert.deepEqual([hemlock.tied, hemlock.allied, hemlock.atOdds], [[], [], []])
})

test('a speaker in the square is found in the sky by name', () => {
  const m = buildWebModel({ nodes: [node('i', 'Dr. Ioanna Pappa', 'Person'), node('z', 'Zoë Ángel', 'Person'), node('s', 'Sand', 'Aisystem')], edges: [] })
  assert.equal(findByName(m.nodes, 'Ioanna Pappa')?.id, 'i')
  assert.equal(findByName(m.nodes, 'zoe angel')?.id, 'z')
  assert.equal(findByName(m.nodes, 'SAND')?.id, 's')
  assert.equal(findByName(m.nodes, 'Nobody'), null)
  assert.equal(findByName(m.nodes, ''), null)
  assert.equal(nameKey('Zoë  Ángel!'), 'zoe angel')
})

test('an empty or missing graph is an empty sky', () => {
  assert.equal(buildWebModel(null).nodes.length, 0)
  assert.equal(buildWebModel({ nodes: [] }).links.length, 0)
  const w = createWeb()
  syncWeb(w, buildWebModel(null))
  assert.equal(stepWeb(w), 0)
})
