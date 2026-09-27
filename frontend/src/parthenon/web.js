// The Web of Athens as a night sky. The names the scroll has tied together are
// ember stars: coloured by role, sized by their bonds, joined by fine luminous
// threads. The constellation keeps its shape from one reading to the next;
// newcomers bloom beside the names they are tied to and new ties arrive as a
// travelling pulse. Nothing ever re-explodes.
//
// Pure model, layout, growth and drawing: no Vue, and no DOM beyond the 2D
// context handed to drawWeb, so every part can be stepped and tested by hand.

import {
  entityTypeName,
  roleFamily,
  tieName,
  isActivityTie,
  isPlatformNode,
  citizenName,
  platformName,
  stripIds,
  foreignScript,
  readable,
  getVocabularyLocale
} from './vocabulary.js'

// ---------------------------------------------------------------------------
// Constants

export const TOP_LABELS = 15 // names printed without being pointed at
export const R_MIN = 3
export const R_MAX = 14
// A citizen's name is set in the display face; a thing or a place the city
// speaks of is cut in inscription capitals, smaller and spaced.
export const LABEL_PX = 15
export const LABEL_H = 17
export const THING_PX = 11
export const THING_H = 14
export const THING_TRACK = 0.12 // em
export const LABEL_GAP = 6
export const LABEL_PAD = 3
// A name outside the lit neighbourhood fades only this far, so it still reads.
export const LABEL_FLOOR = 0.62
// Right of the star, left, below, above; then the four corners.
export const SIDES = ['r', 'l', 'b', 'a', 'rb', 'ra', 'lb', 'la']

export const BLOOM_MS = 1500
export const PULSE_MS = 1700
export const INTRO_MS = 700
export const INTRO_STAGGER = 45
export const FACE_GROW = 10 // a face is shown in a disc this much wider than its star
export const FACE_MS = 200
export const FLASH_MS = 1400 // a beat in the square, seen in the sky
export const TWINKLE_MAX = 24 // the best-tied stars twinkle; the rest keep a steady glow
export const INTRO_MAX = 120 // a larger sky appears whole rather than name by name
const CROWDED_TIES = 400

const DIM = 0.14 // how far a star outside the neighbourhood fades
const LINK_DIM = 0.08

// ---------------------------------------------------------------------------
// Type

/** 'voice' for anyone who can speak (people, bodies, movements, machines); 'thing' for what is spoken of. */
export const labelVoice = (n) => (n && (n.family === 'things' || n.family === 'places') ? 'thing' : 'voice')

export const labelText = (n) => {
  const name = String((n && n.name) || '')
  return labelVoice(n) === 'thing' ? name.toLocaleUpperCase() : name
}

/** The CSS font, tracking (px) and line box of a name. fonts = { display, inscription } (CSS families). */
export const labelStyle = (voice, fonts = {}) =>
  voice === 'thing'
    ? { font: `600 ${THING_PX}px ${fonts.inscription || 'serif'}`, tracking: +(THING_PX * THING_TRACK).toFixed(2), h: THING_H }
    : { font: `600 ${LABEL_PX}px ${fonts.display || 'serif'}`, tracking: 0, h: LABEL_H }

/**
 * How far from a star's centre its name must stand: clear of a face, of the
 * keyboard's ring, or of the chosen star's ring.
 */
export const clearance = (n, { face = false, key = false, chosen = false } = {}) => {
  if (face) return n.r + FACE_GROW + 5
  if (key) return n.r + 14
  if (chosen) return n.r + 6
  return n.r
}

/** The keyboard's key for a star: a ring just outside its face. */
export const keyRadius = (n) => n.r + 14

// ---------------------------------------------------------------------------
// Words

const SQUARE_FACT = /^\s*(?:On|In)\s+(?:Twitter|X|Reddit|the Agora|the Stoa)\b/i
// The same deeds as the memory records them in Chinese: '{agent}在{platform}{deed}'.
const SQUARE_FACT_ZH = /^\s*[^「“"\n]{1,120}?在\s*(?:Twitter|X|Reddit|广场|柱廊)/

const HAN = /[㐀-鿿]/

// The memory's Chinese activity lines, read back into the English ones it
// writes for an English gathering (app/memory/activity.py FACT_TEMPLATES and
// zep_graph_memory_updater._DESCRIPTION_TEMPLATES, both languages), so an
// English reader of an older gathering meets the same words either way.
const DEEDS = [
  ['发布了一条帖子：「{content}」', 'posted: “{content}”'],
  ['发布了一条帖子', 'posted'],
  ...[['点赞', 'liked'], ['踩', 'disliked']].flatMap(([zh, en]) => [
    [`${zh}了{author}的帖子：「{content}」`, `${en} {author}'s post: “{content}”`],
    [`${zh}了一条帖子：「{content}」`, `${en} a post: “{content}”`],
    [`${zh}了{author}的一条帖子`, `${en} a post by {author}`],
    [`${zh}了一条帖子`, `${en} a post`],
    [`${zh}了{author}的评论：「{content}」`, `${en} {author}'s comment: “{content}”`],
    [`${zh}了一条评论：「{content}」`, `${en} a comment: “{content}”`],
    [`${zh}了{author}的一条评论`, `${en} a comment by {author}`],
    [`${zh}了一条评论`, `${en} a comment`]
  ]),
  ['转发了{author}的帖子：「{content}」', 'reposted {author}\'s post: “{content}”'],
  ['转发了一条帖子：「{content}」', 'reposted a post: “{content}”'],
  ['转发了{author}的一条帖子', 'reposted a post by {author}'],
  ['转发了一条帖子', 'reposted a post'],
  ...['，并评论道：「{quote}」', ''].flatMap((suffix) => {
    const added = suffix ? ', adding: “{quote}”' : ''
    return [
      [`引用了{author}的帖子「{content}」${suffix}`, `quoted {author}'s post “{content}”${added}`],
      [`引用了一条帖子「{content}」${suffix}`, `quoted a post “{content}”${added}`],
      [`引用了{author}的一条帖子${suffix}`, `quoted a post by {author}${added}`],
      [`引用了一条帖子${suffix}`, `quoted a post${added}`]
    ]
  }),
  ['关注了用户「{name}」', 'followed the user “{name}”'],
  ['关注了一个用户', 'followed a user'],
  ['在{author}的帖子「{post}」下评论道：「{content}」', 'commented on {author}\'s post “{post}”: “{content}”'],
  ['在帖子「{post}」下评论道：「{content}」', 'commented on a post “{post}”: “{content}”'],
  ['在{author}的帖子下评论道：「{content}」', 'commented on {author}\'s post: “{content}”'],
  ['评论道：「{content}」', 'commented: “{content}”'],
  ['发表了评论', 'left a comment'],
  ['搜索了用户「{query}」', 'searched for the user “{query}”'],
  ['搜索了用户', 'searched for users'],
  ['搜索了「{query}」', 'searched for “{query}”'],
  ['进行了搜索', 'ran a search'],
  ['屏蔽了用户「{name}」', 'muted the user “{name}”'],
  ['屏蔽了一个用户', 'muted a user'],
  ['执行了{action}操作', 'performed {action}'],
  ['执行了操作', 'performed an action']
].map(([zh, en]) => {
  const slots = []
  const source = zh
    .split(/(\{\w+\})/)
    .map((part) => {
      const slot = /^\{(\w+)\}$/.exec(part)
      if (!slot) return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      slots.push(slot[1])
      return '([\\s\\S]+?)'
    })
    .join('')
  return { re: new RegExp(`^${source}$`), slots, en }
})
const SQUARE_NAMES = { Twitter: 'Twitter', X: 'Twitter', 广场: 'Twitter', Reddit: 'Reddit', 柱廊: 'Reddit' }
const ZH_FACT = /^\s*([^「“"\n]{1,120}?)在\s*(Twitter|X|Reddit|广场|柱廊)\s*([\s\S]+?)\s*$/
const ZH_ACCOUNT = /^\s*(.+?)是\s*(Twitter|Reddit)\s*上的模拟账号。?\s*$/
const ZH_HUB = /^\s*(Twitter|Reddit)\s*是模拟中使用的社交媒体平台。?\s*$/

/** A Chinese activity line (fact or account summary) in the English words the memory uses, or '' when it is no such line. */
export const englishActivityLine = (text) => {
  const s = String(text ?? '')
  let m = ZH_HUB.exec(s)
  if (m) return `${m[1]} is the social media platform used in the simulation.`
  m = ZH_ACCOUNT.exec(s)
  if (m) return `${m[1].trim()} is a simulated account on ${m[2]}.`
  m = ZH_FACT.exec(s)
  if (!m) return ''
  let words = deedIn(m[3])
  // The memory cuts a long line short (MAX_FACT_CHARS), often inside a
  // quotation: it is read with the quotation closed after an ellipsis.
  const open = (m[3].match(/「/g) || []).length - (m[3].match(/」/g) || []).length
  if (!words && open > 0) words = deedIn(`${m[3].replace(/[\s…]+$/, '')}…」`)
  // Or just after one, inside the words that begin a comment on it.
  if (!words) words = deedIn(m[3].replace(/」，[并评论道：]*$/, '」'))
  return words ? `On ${SQUARE_NAMES[m[2]]}, ${m[1].trim()} ${words}` : ''
}
const deedIn = (text) => {
  for (const deed of DEEDS) {
    const d = deed.re.exec(text)
    if (d) return deed.en.replace(/\{(\w+)\}/g, (x, slot) => d[deed.slots.indexOf(slot) + 1] ?? '')
  }
  return ''
}

const readerLang = (locale) => (String(locale ?? getVocabularyLocale() ?? 'en').slice(0, 2).toLowerCase() === 'zh' ? 'zh' : 'en')

// Facts arrive in the engine's words; the square has its own. For a Chinese
// reader the squares are named in the fact's own language: an English fact
// keeps "the Agora", a Chinese one says 广场. An English reader never meets
// Chinese: the memory's Chinese activity lines are read in its English words,
// and anything else in Chinese is left out (the tie's own word stands in).
export const cityWords = (text, locale) => {
  let s = stripIds(text)
  if (!s) return ''
  if (readerLang(locale) !== 'zh' && foreignScript(s, 'en')) {
    s = readable(HAN.test(s) ? stripIds(englishActivityLine(s)) : s, '', 'en')
    if (!s) return ''
  }
  const zh = HAN.test(s)
  const agora = platformName('twitter', 'name', zh ? 'zh' : 'en')
  const stoa = platformName('reddit', 'name', zh ? 'zh' : 'en')
  const handle = (h) => (/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(h) ? citizenName('', h) : h)
  s = s
    .replace(/\bOn (Twitter|X)\b/g, zh ? `在${agora}` : `In ${agora}`)
    .replace(/\bOn Reddit\b/g, zh ? `在${stoa}` : `In ${stoa}`)
    .replace(zh ? /\s*\bTwitter\b\s*/g : /\bTwitter\b/g, agora)
    .replace(zh ? /\s*\bReddit\b\s*/g : /\bReddit\b/g, stoa)
    .replace(/\bsearched for the user [“"]([^”"]+)[”"]/gi, (m, h) => `asked after ${handle(h)}`)
    .replace(/\bfollowed the user [“"]([^”"]+)[”"]/gi, (m, h) => `followed ${handle(h)}`)
    .replace(/\bthe user [“"]([^”"]+)[”"]/gi, (m, h) => handle(h))
    .replace(/[“"]([a-z0-9]+(?:_[a-z0-9]+)*_\d+)[”"]/g, (m, h) => citizenName('', h))
    .replace(/\bsearched for\b/g, 'asked around for')
    .replace(/\b(posted):/g, 'said:')
    .replace(/\b(commented):/g, 'answered:')
    .replace(/\bliked ([^.:“"]+?)'s (post|comment)\b/g, 'nodded to $1’s words')
    .replace(/\bdisliked ([^.:“"]+?)'s (post|comment)\b/g, 'shook their head at $1’s words')
    .replace(/\bquoted ([^.:“"]+?)'s post\b/g, 'quoted $1')
    .replace(/\breposted\b/g, 'repeated')
  return s
}

// A tie that takes a side: olive for support, red for opposition.
const SUPPORT_WORDS = new Set(['SUPPORT', 'SUPPORTS', 'DEFEND', 'DEFENDS', 'ENDORSE', 'ENDORSES', 'ALLY', 'ALLIES', 'ALLIED', 'PRAISE', 'PRAISES', 'BACK', 'BACKS', 'CHAMPION', 'CHAMPIONS', 'AGREES', 'TRUSTS', 'PROTECTS', 'ADMIRES', 'LOVES'])
const OPPOSE_WORDS = new Set(['OPPOSE', 'OPPOSES', 'ACCUSE', 'ACCUSES', 'CRITICISE', 'CRITICISES', 'CRITICIZE', 'CRITICIZES', 'MOCK', 'MOCKS', 'ATTACK', 'ATTACKS', 'REJECT', 'REJECTS', 'CONDEMN', 'CONDEMNS', 'DISPUTES', 'CHALLENGES', 'PROSECUTES', 'DISTRUSTS', 'DENOUNCES', 'RIVALS', 'CONFLICTS', 'DISAGREES', 'SUES', 'BLAMES', 'CONVICTS', 'CONDEMNED', 'ACCUSED', 'OPPOSED'])

export const tieStance = (name) => {
  const first = String(name || '').trim().toUpperCase().split(/[_\s]+/)[0]
  if (OPPOSE_WORDS.has(first)) return 'opposes'
  if (SUPPORT_WORDS.has(first)) return 'supports'
  return ''
}

// The chatter of the square: who spoke, answered, nodded, quoted. A tie with an
// activity name that the scroll itself states ("Plato follows Socrates") is
// part of the shape of the city, not chatter.
export const isChatterEdge = (name, fact) =>
  isActivityTie(name) && (!fact || SQUARE_FACT.test(String(fact)) || SQUARE_FACT_ZH.test(String(fact)))

export const nodeRadius = (degree, maxDegree) => {
  if (!(maxDegree > 0)) return R_MIN + 1
  const d = Math.max(0, Math.min(degree || 0, maxDegree))
  return R_MIN + (R_MAX - R_MIN) * Math.sqrt(d / maxDegree)
}

// ---------------------------------------------------------------------------
// The model: what the sky shows, derived from the engine's graph

const EMPTY_MODEL = Object.freeze({ nodes: [], links: [], legend: [], signature: '', tieCount: 0, chatterCount: 0 })

export function buildWebModel(data) {
  if (!data || !Array.isArray(data.nodes)) return EMPTY_MODEL

  const rawNodes = data.nodes.filter((n) => n && n.uuid && !isPlatformNode(n.name))
  const ids = new Set(rawNodes.map((n) => n.uuid))
  const edges = (data.edges || []).filter(
    (e) => e && ids.has(e.source_node_uuid) && ids.has(e.target_node_uuid) && e.source_node_uuid !== e.target_node_uuid
  )

  const structuralDeg = new Map()
  const chatterDeg = new Map()
  const bundles = new Map()
  const bump = (map, id) => map.set(id, (map.get(id) || 0) + 1)

  for (const e of edges) {
    const name = String(e.name || e.fact_type || 'RELATES_TO')
    const chatter = isChatterEdge(name, e.fact)
    const a = e.source_node_uuid
    const b = e.target_node_uuid
    bump(chatter ? chatterDeg : structuralDeg, a)
    bump(chatter ? chatterDeg : structuralDeg, b)
    const key = a < b ? `${a}|${b}` : `${b}|${a}`
    let bundle = bundles.get(key)
    if (!bundle) {
      bundle = { key, source: a < b ? a : b, target: a < b ? b : a, structural: 0, chatter: 0, stance: '', ties: new Map() }
      bundles.set(key, bundle)
    }
    bundle[chatter ? 'chatter' : 'structural']++
    if (!chatter) {
      const stance = tieStance(name)
      if (stance === 'opposes') bundle.stance = 'opposes'
      else if (stance === 'supports' && !bundle.stance) bundle.stance = 'supports'
    }
    const tkey = `${name}>${a}`
    let tie = bundle.ties.get(tkey)
    if (!tie) {
      tie = { key: `${key}:${tkey}`, name, word: tieName(name), from: a, to: b, count: 0, facts: [], chatter }
      bundle.ties.set(tkey, tie)
    }
    tie.count++
    const fact = cityWords(e.fact || '')
    if (fact && !tie.facts.includes(fact)) tie.facts.push(fact)
  }

  const maxDegree = Math.max(0, ...structuralDeg.values())

  const nodes = rawNodes.map((n) => {
    const type = (n.labels || []).find((l) => l && l !== 'Entity') || ''
    const degree = structuralDeg.get(n.uuid) || 0
    return {
      id: n.uuid,
      name: citizenName(n.name) || String(n.name || ''),
      type,
      role: type ? entityTypeName(type) : '',
      family: type ? roleFamily(type) : 'things',
      degree,
      chatterDegree: chatterDeg.get(n.uuid) || 0,
      r: nodeRadius(degree, maxDegree),
      summary: cityWords(n.summary || ''),
      rank: 0,
      top: false
    }
  })

  // Rank by bonds decides who is printed first and set in a heavier hand.
  const ranked = [...nodes].sort(
    (x, y) => y.degree - x.degree || y.chatterDegree - x.chatterDegree || x.name.localeCompare(y.name)
  )
  ranked.forEach((n, i) => {
    n.rank = i
    n.top = i < TOP_LABELS
  })

  const links = [...bundles.values()].map((b) => ({
    key: b.key,
    source: b.source,
    target: b.target,
    structural: b.structural,
    chatter: b.chatter,
    stance: b.stance,
    ties: [...b.ties.values()].sort((x, y) => Number(x.chatter) - Number(y.chatter) || y.count - x.count)
  }))

  const byType = new Map()
  for (const n of nodes) {
    const k = n.type || ''
    const entry = byType.get(k) || { key: k, label: n.role, family: n.family, count: 0 }
    entry.count++
    byType.set(k, entry)
  }
  // The things the city speaks of (untyped names) come last.
  const legend = [...byType.values()].sort(
    (x, y) => Number(!x.key) - Number(!y.key) || y.count - x.count || x.label.localeCompare(y.label)
  )

  const signature =
    nodes.map((n) => n.id).sort().join(',') + '#' + links.map((l) => `${l.key}:${l.structural}:${l.chatter}`).sort().join(',')

  return {
    nodes,
    links,
    legend,
    signature,
    tieCount: links.filter((l) => l.structural > 0).length,
    chatterCount: links.filter((l) => l.chatter > 0).length,
    // Threads of chatter, one for each thing said, nodded to or quoted: the
    // unit the Hearing's ledger and status line count in.
    chatterThreads: links.reduce((sum, l) => sum + (l.chatter || 0), 0)
  }
}

// The words of a sentence, for comparing what two facts say.
const wordsOf = (text) => new Set(String(text || '').toLowerCase().match(/[\p{L}\p{N}]+/gu) || [])
const saysLess = (a, b) => {
  const wa = wordsOf(a)
  const wb = wordsOf(b)
  if (!wa.size || wa.size >= wb.size) return false
  for (const w of wa) if (!wb.has(w)) return false
  return true
}
// Within one tie, a fact that only says part of what another fact says is
// left out ("Sand is operated by Ammolith Compute." beside "Sand is the AI
// model operated by Ammolith Compute."); the longer one is kept.
export const fullestFacts = (texts) => {
  const list = [...new Set((texts || []).filter(Boolean))]
  return list.filter((t) => !list.some((other) => other !== t && saysLess(t, other)))
}

// Who a name is and what the scroll says of them: the card's contents.
export function nodeDossier(model, id) {
  const byId = new Map(model.nodes.map((n) => [n.id, n]))
  const node = byId.get(id)
  if (!node) return null
  const facts = []
  const chatterFacts = []
  const neighbours = new Map()
  for (const l of model.links) {
    if (l.source !== id && l.target !== id) continue
    const otherId = l.source === id ? l.target : l.source
    const other = byId.get(otherId)
    if (!other) continue
    for (const tie of l.ties) {
      const list = tie.chatter ? chatterFacts : facts
      const from = byId.get(tie.from)
      const to = byId.get(tie.to)
      const fromName = from ? from.name : ''
      const toName = to ? to.name : ''
      // A tie with no sentence of its own is said in the tie's language:
      // Chinese runs its words together and ends with 。
      const plain = HAN.test(tie.word)
        ? `${fromName}${tie.word}${toName}。`
        : `${fromName} ${tie.word} ${toName}.`.trim()
      const texts = tie.facts.length ? fullestFacts(tie.facts) : [plain]
      for (const text of texts) {
        if (list.some((f) => f.text === text)) continue
        list.push({
          key: `${tie.key}#${list.length}`,
          text,
          otherId,
          otherName: other.name,
          otherType: other.type,
          otherFamily: other.family,
          stance: tie.chatter ? '' : tieStance(tie.name),
          word: tie.word
        })
      }
    }
    const nb = neighbours.get(otherId) || { id: otherId, name: other.name, type: other.type, family: other.family, structural: 0, chatter: 0 }
    nb.structural += l.structural
    nb.chatter += l.chatter
    neighbours.set(otherId, nb)
  }
  const nbs = [...neighbours.values()].sort(
    (a, b) => Number(b.structural > 0) - Number(a.structural > 0) || b.structural - a.structural || b.chatter - a.chatter || a.name.localeCompare(b.name)
  )
  return { node, facts, chatterFacts, neighbours: nbs }
}

// ---------------------------------------------------------------------------
// Search

const fold = (s) =>
  String(s || '')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim()

export function searchNodes(nodes, query, limit = 6) {
  const q = fold(query)
  if (!q) return []
  const scored = []
  for (const n of nodes) {
    const name = fold(n.name)
    let score = -1
    if (name.startsWith(q)) score = 0
    else if (name.split(/[\s'’.-]+/).some((w) => w.startsWith(q))) score = 1
    else if (name.includes(q)) score = 2
    else if (fold(n.role).includes(q)) score = 3
    if (score >= 0) scored.push({ n, score })
  }
  scored.sort((a, b) => a.score - b.score || a.n.rank - b.n.rank || a.n.name.localeCompare(b.n.name))
  return scored.slice(0, limit).map((s) => s.n)
}

// Letters of any script count, as the portraits match them.
export const nameKey = (name) =>
  String(name || '')
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()

/** The star that bears this name: the whole name, else a name that ends the same way ("Dr. Ioanna Pappa"). */
export function findByName(nodes, name) {
  const key = nameKey(name)
  if (!key) return null
  let best = null
  for (const n of nodes) {
    const k = nameKey(n.name)
    if (k === key) return n
    if (!best && k.length > 3 && key.length > 3 && (k.endsWith(` ${key}`) || key.endsWith(` ${k}`))) best = n
  }
  return best
}

/**
 * The Web in words, for anyone who cannot see the picture: every name grouped
 * by role (in the legend's order) with whom the scroll ties them to, allied
 * with and at odds with.
 */
export function webInWords(model) {
  const byId = new Map(model.nodes.map((n) => [n.id, n]))
  const ties = new Map()
  const entry = (id) => {
    let e = ties.get(id)
    if (!e) {
      e = { tied: [], allied: [], atOdds: [] }
      ties.set(id, e)
    }
    return e
  }
  for (const l of model.links) {
    if (!l.structural) continue
    for (const [me, other] of [[l.source, l.target], [l.target, l.source]]) {
      const o = byId.get(other)
      if (!o) continue
      const e = entry(me)
      const list = l.stance === 'opposes' ? e.atOdds : l.stance === 'supports' ? e.allied : e.tied
      list.push(o)
    }
  }
  const byRank = (a, b) => a.rank - b.rank
  const names = (list) => list.sort(byRank).map((o) => o.name)
  return model.legend.map((g) => ({
    key: g.key,
    label: g.label,
    family: g.family,
    names: model.nodes
      .filter((n) => (n.type || '') === g.key)
      .sort(byRank)
      .map((n) => {
        const e = ties.get(n.id) || { tied: [], allied: [], atOdds: [] }
        return { id: n.id, name: n.name, type: n.type, role: n.role, family: n.family, tied: names(e.tied), allied: names(e.allied), atOdds: names(e.atOdds) }
      })
  }))
}

// ---------------------------------------------------------------------------
// Seeded randomness, so every visit opens on the same sky

export const hashString = (str) => {
  let h = 2166136261
  const s = String(str)
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const unit = (seed) => {
  let t = (seed + 0x6d2b79f5) >>> 0
  t = Math.imul(t ^ (t >>> 15), t | 1)
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}

// ---------------------------------------------------------------------------
// The layout: a small force simulation that keeps positions across readings

export function createWeb({ width = 600, height = 480 } = {}) {
  return {
    width,
    height,
    nodes: [],
    links: [],
    byId: new Map(),
    adjacency: new Map(),
    alpha: 0,
    alphaTarget: 0,
    scaleHint: 1,
    chatterVisible: false,
    synced: false
  }
}

const finite = (v) => typeof v === 'number' && Number.isFinite(v)

// Who is next to whom, by the ties that are drawn: the chatter counts only
// while its layer is showing. Every tie (drawn or not) shapes the layout.
const rebuildAdjacency = (state) => {
  const adj = new Map()
  const count = new Map()
  for (const l of state.links) {
    count.set(l.source, (count.get(l.source) || 0) + 1)
    count.set(l.target, (count.get(l.target) || 0) + 1)
    if (!l.structural && !state.chatterVisible) continue
    if (!adj.has(l.source)) adj.set(l.source, new Set())
    if (!adj.has(l.target)) adj.set(l.target, new Set())
    adj.get(l.source).add(l.target)
    adj.get(l.target).add(l.source)
  }
  state.adjacency = adj
  for (const n of state.nodes) n.links = count.get(n.id) || 0
}

/** Show or hide the chatter layer: neighbourhoods follow what is drawn. */
export function setChatterVisible(state, on) {
  state.chatterVisible = !!on
  rebuildAdjacency(state)
}

/**
 * Bring the sky up to date with a new reading of the Web. Names already in the
 * sky keep their place; newcomers stand beside the names they are tied to and
 * bloom; new ties arrive as a pulse. Returns what was added.
 *
 * options.now: a clock in ms for the bloom and pulse.
 * options.stored: { id: [x, y] } remembered positions (first reading only).
 * options.intro: stagger the first stars in by rank, like names lighting up.
 */
export function syncWeb(state, model, { now = 0, stored = null, intro = false } = {}) {
  const first = !state.synced
  const prev = state.byId
  const next = new Map()
  const added = []

  for (const m of model.nodes) {
    let n = prev.get(m.id)
    if (!n) {
      n = {
        id: m.id,
        x: NaN,
        y: NaN,
        vx: 0,
        vy: 0,
        fx: null,
        fy: null,
        phase: unit(hashString(m.id)) * Math.PI * 2,
        mobility: 1,
        em: 1,
        hot: 0,
        bornAt: first ? null : now,
        introAt: first && intro && model.nodes.length <= INTRO_MAX ? now + Math.min(m.rank, 40) * INTRO_STAGGER : null
      }
      const at = stored && stored[m.id]
      if (Array.isArray(at) && finite(at[0]) && finite(at[1])) {
        n.x = at[0]
        n.y = at[1]
        n.remembered = true
      }
      added.push(n)
    }
    n.name = m.name
    n.type = m.type
    n.role = m.role
    n.family = m.family
    n.degree = m.degree
    n.chatterDegree = m.chatterDegree
    n.r = m.r
    n.rank = m.rank
    n.top = m.top
    next.set(m.id, n)
  }

  const prevLinks = new Map(state.links.map((l) => [l.key, l]))
  const addedLinks = []
  const links = []
  for (const ml of model.links) {
    const s = next.get(ml.source)
    const t = next.get(ml.target)
    if (!s || !t) continue
    let l = prevLinks.get(ml.key)
    if (!l) {
      l = { key: ml.key, em: 1, hot: 0, bornAt: first ? null : now }
      addedLinks.push(l)
    } else if (!l.structural && ml.structural && !first) {
      // A tie that was only chatter becomes part of the shape: pulse it in.
      l.bornAt = now
    }
    l.source = ml.source
    l.target = ml.target
    l.s = s
    l.t = t
    l.structural = ml.structural
    l.chatter = ml.chatter
    l.stance = ml.stance
    links.push(l)
  }

  state.nodes = [...next.values()]
  state.byId = next
  state.links = links
  rebuildAdjacency(state)

  // Place the newcomers: beside their placed neighbours (by any tie), in
  // waves, so a cluster that arrives together grows out from what is there.
  const allNear = new Map()
  for (const l of links) {
    if (!allNear.has(l.source)) allNear.set(l.source, [])
    if (!allNear.has(l.target)) allNear.set(l.target, [])
    allNear.get(l.source).push(l.target)
    allNear.get(l.target).push(l.source)
  }
  const pending = added.filter((n) => !finite(n.x) || !finite(n.y))
  const placedIds = new Set(state.nodes.filter((n) => finite(n.x) && finite(n.y)).map((n) => n.id))
  let spread = 60
  if (placedIds.size) {
    let maxD = 0
    for (const n of state.nodes) if (placedIds.has(n.id)) maxD = Math.max(maxD, Math.hypot(n.x, n.y))
    spread = Math.max(60, maxD * 0.7)
  }
  for (let wave = 0; wave < 6 && pending.length; wave++) {
    for (let i = pending.length - 1; i >= 0; i--) {
      const n = pending[i]
      const near = (allNear.get(n.id) || []).map((id) => next.get(id)).filter((o) => o && placedIds.has(o.id))
      if (!near.length && wave < 5) continue
      const h = hashString(n.id)
      if (near.length) {
        const cx = near.reduce((s, o) => s + o.x, 0) / near.length
        const cy = near.reduce((s, o) => s + o.y, 0) / near.length
        const ang = unit(h) * Math.PI * 2
        const dist = 26 + unit(h + 1) * 18
        n.x = cx + Math.cos(ang) * dist
        n.y = cy + Math.sin(ang) * dist
      } else if (first && !placedIds.size) {
        // An empty sky: a sunflower spiral by rank, so the first layout is calm.
        const i2 = n.rank + 1
        const ang = i2 * 2.39996
        const rad = 22 * Math.sqrt(i2)
        n.x = Math.cos(ang) * rad
        n.y = Math.sin(ang) * rad
      } else {
        const ang = unit(h) * Math.PI * 2
        const rad = spread * (0.45 + 0.4 * unit(h + 7))
        n.x = Math.cos(ang) * rad
        n.y = Math.sin(ang) * rad
      }
      n.vx = 0
      n.vy = 0
      placedIds.add(n.id)
      pending.splice(i, 1)
    }
  }

  // Heat: a first sky settles from scratch (or barely, when remembered); a
  // growing sky only nudges, and the names already there move slowly.
  if (first) {
    const remembered = state.nodes.length > 0 && state.nodes.every((n) => n.remembered)
    state.alpha = remembered ? 0.06 : 1
  } else if (added.length || addedLinks.length) {
    for (const n of state.nodes) n.mobility = n.bornAt === now ? 1 : 0.35
    state.alpha = Math.max(state.alpha, added.length ? 0.32 : 0.16)
  }
  state.synced = true
  return { first, added: added.map((n) => n.id), addedLinks: addedLinks.map((l) => l.key) }
}

// How hard the sky pulls the names to its middle, across and down, so the
// constellation takes the shape of the pane it is in.
export const pullFor = (width, height) => {
  const aspect = Math.max(0.45, Math.min(2.2, width / Math.max(1, height)))
  const lean = Math.pow(aspect, 1.6)
  return { x: Math.min(0.16, 0.05 / lean), y: Math.min(0.16, 0.05 * lean) }
}

/** One tick of the forces. Returns the new alpha. */
export function stepWeb(state) {
  const { nodes, links } = state
  const alpha = state.alpha
  if (!(alpha > 0) || !nodes.length) {
    state.alpha = 0
    return 0
  }
  const k = Math.max(0.2, state.scaleHint || 1)
  const pull = pullFor(state.width, state.height)

  // Ties pull their ends toward a resting length; the chatter only faintly.
  for (const l of links) {
    const s = l.s
    const t = l.t
    let dx = t.x + t.vx - s.x - s.vx
    let dy = t.y + t.vy - s.y - s.vy
    let d = Math.hypot(dx, dy)
    if (d < 1e-3) {
      dx = (unit(hashString(l.key)) - 0.5) * 1e-2
      dy = 1e-3
      d = Math.hypot(dx, dy)
    }
    const structural = l.structural > 0
    const rest = (structural ? 70 : 110) + (s.r + t.r) / k
    const strength = (structural ? 0.6 : 0.05) / Math.max(1, Math.min(s.links || 1, t.links || 1))
    const f = ((d - rest) / d) * alpha * strength
    dx *= f
    dy *= f
    const bias = (s.links || 1) / ((s.links || 1) + (t.links || 1))
    t.vx -= dx * bias
    t.vy -= dy * bias
    s.vx += dx * (1 - bias)
    s.vy += dy * (1 - bias)
  }

  // Every name keeps a little distance from every other; a name the scroll
  // ties to no one pushes and is pushed less.
  const maxD2 = 460 * 460
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i]
    const ta = a.degree > 0
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j]
      const dx = b.x - a.x
      const dy = b.y - a.y
      let d2 = dx * dx + dy * dy
      if (d2 > maxD2) continue
      if (d2 < 25) d2 = 25
      const tb = b.degree > 0
      const q = ta && tb ? 240 : ta || tb ? 36 : 60
      const f = (-q * alpha) / d2
      a.vx += dx * f
      a.vy += dy * f
      b.vx -= dx * f
      b.vy -= dy * f
    }
  }

  // The pull to the middle. Names the scroll ties to no one (only the chatter,
  // or nothing) are drawn to a ring at the rim instead: faint outer stars that
  // neither flee to the edge of the sky nor fall into the hub.
  let cx = 0
  let cy = 0
  let tied = 0
  for (const n of nodes) {
    if (!(n.degree > 0)) continue
    cx += n.x
    cy += n.y
    tied++
  }
  cx = tied ? cx / tied : 0
  cy = tied ? cy / tied : 0
  let rim = 0
  for (const n of nodes) if (n.degree > 0) rim = Math.max(rim, Math.hypot(n.x - cx, n.y - cy))
  rim = tied > 1 ? rim * 0.9 + 14 : 70
  const rimPull = Math.max(pull.x, pull.y) * 2.5
  for (const n of nodes) {
    if (n.degree > 0) {
      n.vx += -n.x * pull.x * alpha
      n.vy += -n.y * pull.y * alpha
      continue
    }
    const ox = n.x - cx
    const oy = n.y - cy
    let d = Math.hypot(ox, oy)
    let ux = ox / (d || 1)
    let uy = oy / (d || 1)
    if (d < 1e-3) {
      const ang = unit(hashString(n.id)) * Math.PI * 2
      ux = Math.cos(ang)
      uy = Math.sin(ang)
      d = 0
    }
    const f = (rim - d) * rimPull * alpha
    n.vx += ux * f
    n.vy += uy * f
  }

  for (const n of nodes) {
    if (n.fx != null && n.fy != null) {
      n.x = n.fx
      n.y = n.fy
      n.vx = 0
      n.vy = 0
      continue
    }
    n.vx *= 0.58
    n.vy *= 0.58
    n.x += n.vx * (n.mobility ?? 1)
    n.y += n.vy * (n.mobility ?? 1)
  }

  // Stars never overlap, with room kept around each for its light.
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i]
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j]
        const min = (a.r + b.r + 16) / k
        let dx = b.x - a.x
        let dy = b.y - a.y
        let d = Math.hypot(dx, dy)
        if (d >= min) continue
        if (d < 1e-3) {
          const ang = unit(hashString(a.id + b.id)) * Math.PI * 2
          dx = Math.cos(ang)
          dy = Math.sin(ang)
          d = 1
        }
        const push = ((min - d) / d) * 0.5 * 0.7
        const ma = a.fx != null ? 0 : a.mobility ?? 1
        const mb = b.fx != null ? 0 : b.mobility ?? 1
        const tot = ma + mb || 1
        a.x -= dx * push * (2 * ma / tot)
        a.y -= dy * push * (2 * ma / tot)
        b.x += dx * push * (2 * mb / tot)
        b.y += dy * push * (2 * mb / tot)
      }
    }
  }

  state.alpha += (state.alphaTarget - state.alpha) * 0.028
  if (state.alpha < 0.004 && state.alphaTarget === 0) {
    state.alpha = 0
    for (const n of nodes) n.mobility = 1
  }
  return state.alpha
}

/** Run the forces until the sky is still (or maxSteps have passed). */
export function settleWeb(state, maxSteps = 400) {
  let i = 0
  while (state.alpha > 0 && i < maxSteps) {
    stepWeb(state)
    i++
  }
  return i
}

/**
 * Settle for at most budgetMs of the clock (and at most maxSteps), so a large
 * sky finds its places a slice at a time without holding up the page.
 * Returns the steps taken.
 */
export function settleFor(state, budgetMs, clock = () => Date.now(), maxSteps = Infinity) {
  const t0 = clock()
  let i = 0
  while (state.alpha > 0 && i < maxSteps) {
    stepWeb(state)
    i++
    if (clock() - t0 >= budgetMs) break
  }
  return i
}

/** How many steps a first settle may take: fewer as the sky grows, since each step costs more. */
export const settleCap = (count) => (count <= 80 ? 400 : Math.max(140, Math.round(400 * Math.sqrt(80 / count))))

export const neighbourhood = (state, id) => {
  const set = new Set([id])
  for (const o of state.adjacency.get(id) || []) set.add(o)
  return set
}

// ---------------------------------------------------------------------------
// Names beside their stars

// Where a name sits beside its star, in screen pixels.
export function labelRect(side, x, y, r, w, h = LABEL_H) {
  const g = LABEL_GAP
  switch (side) {
    case 'l':
      return { x0: x - r - g - w, x1: x - r - g, y0: y - h / 2, y1: y + h / 2 }
    case 'b':
      return { x0: x - w / 2, x1: x + w / 2, y0: y + r + 2, y1: y + r + 2 + h }
    case 'a':
      return { x0: x - w / 2, x1: x + w / 2, y0: y - r - 2 - h, y1: y - r - 2 }
    case 'rb':
      return { x0: x + r * 0.6 + g - 2, x1: x + r * 0.6 + g - 2 + w, y0: y + r * 0.45, y1: y + r * 0.45 + h }
    case 'ra':
      return { x0: x + r * 0.6 + g - 2, x1: x + r * 0.6 + g - 2 + w, y0: y - r * 0.45 - h, y1: y - r * 0.45 }
    case 'lb':
      return { x0: x - r * 0.6 - g + 2 - w, x1: x - r * 0.6 - g + 2, y0: y + r * 0.45, y1: y + r * 0.45 + h }
    case 'la':
      return { x0: x - r * 0.6 - g + 2 - w, x1: x - r * 0.6 - g + 2, y0: y - r * 0.45 - h, y1: y - r * 0.45 }
    default:
      return { x0: x + r + g, x1: x + r + g + w, y0: y - h / 2, y1: y + h / 2 }
  }
}

export const boxesMeet = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1

export const circleMeetsBox = (cx, cy, r, box) => {
  const nx = Math.max(box.x0, Math.min(cx, box.x1))
  const ny = Math.max(box.y0, Math.min(cy, box.y1))
  return Math.hypot(cx - nx, cy - ny) < r
}

const inflate = (b, p) => ({ x0: b.x0 - p, x1: b.x1 + p, y0: b.y0 - p, y1: b.y1 + p })

// Does the segment (x1,y1)-(x2,y2) pass through the box? (Liang-Barsky clip.)
export const segmentMeetsBox = (x1, y1, x2, y2, box) => {
  let t0 = 0
  let t1 = 1
  const dx = x2 - x1
  const dy = y2 - y1
  const edges = [
    [-dx, x1 - box.x0],
    [dx, box.x1 - x1],
    [-dy, y1 - box.y0],
    [dy, box.y1 - y1]
  ]
  for (const [p, q] of edges) {
    if (p === 0) {
      if (q < 0) return false
      continue
    }
    const r = q / p
    if (p < 0) {
      if (r > t1) return false
      if (r > t0) t0 = r
    } else {
      if (r < t0) return false
      if (r < t1) t1 = r
    }
  }
  return t0 <= t1
}

/**
 * Collision-aware placement. items: [{ id, x, y, r, w, h, forced, threads }] in
 * priority order (screen pixels; h defaults to LABEL_H), where threads are the star's own drawn ties
 * as [x1, y1, x2, y2] segments; stars: [{ id, x, y, r }] every star that a
 * name must not cover. A name never covers another name or star; it would
 * rather not lie across its own threads, and it keeps its previous side while
 * that still fits, so nothing jumps about. A name that fits nowhere is left
 * out, unless forced (the name being pointed at), which is printed anyway and
 * marked crowded. blocks: [{ x0, y0, x1, y1 }] screen areas no name may enter.
 * Returns Map id -> { side, x0, y0, x1, y1, crowded }.
 */
export function placeLabels(items, stars, { prev = null, bounds = null, pad = LABEL_PAD, blocks = null } = {}) {
  const out = new Map()
  // Anything else on the sky a name must keep out from under (a legend, say).
  const placed = blocks ? blocks.map((b) => ({ x0: b.x0, x1: b.x1, y0: b.y0, y1: b.y1 })) : []
  // Stars in a coarse grid, so a name is checked only against the stars near it.
  const CELL = 64
  const grid = new Map()
  let reach = 0
  for (const st of stars) {
    if (!Number.isFinite(st.x) || !Number.isFinite(st.y)) continue
    const key = `${Math.floor(st.x / CELL)},${Math.floor(st.y / CELL)}`
    const cell = grid.get(key)
    if (cell) cell.push(st)
    else grid.set(key, [st])
    reach = Math.max(reach, st.r + 1)
  }
  const starsNear = (box) => {
    const found = []
    const cx0 = Math.floor((box.x0 - reach) / CELL)
    const cx1 = Math.floor((box.x1 + reach) / CELL)
    const cy0 = Math.floor((box.y0 - reach) / CELL)
    const cy1 = Math.floor((box.y1 + reach) / CELL)
    for (let cx = cx0; cx <= cx1; cx++) {
      for (let cy = cy0; cy <= cy1; cy++) {
        const cell = grid.get(`${cx},${cy}`)
        if (cell) for (const st of cell) found.push(st)
      }
    }
    return found
  }
  for (const it of items) {
    const before = prev && prev.get(it.id)
    const order = before ? [before.side, ...SIDES.filter((s) => s !== before.side)] : SIDES
    let chosen = null
    let crossed = null
    const h = it.h || LABEL_H
    for (const side of order) {
      const rect = labelRect(side, it.x, it.y, it.r, it.w, h)
      const box = inflate(rect, pad)
      if (bounds && (rect.x0 < bounds.x0 || rect.x1 > bounds.x1 || rect.y0 < bounds.y0 || rect.y1 > bounds.y1)) continue
      if (placed.some((p) => boxesMeet(p, box))) continue
      let covers = false
      for (const s of starsNear(box)) {
        if (s.id === it.id) continue
        if (circleMeetsBox(s.x, s.y, s.r + 1, box)) {
          covers = true
          break
        }
      }
      if (covers) continue
      if (it.threads && it.threads.some((t) => segmentMeetsBox(t[0], t[1], t[2], t[3], rect))) {
        if (!crossed) crossed = { side, ...rect, crowded: false }
        continue
      }
      chosen = { side, ...rect, crowded: false }
      break
    }
    if (!chosen && crossed) chosen = crossed
    if (!chosen && it.forced) {
      let side = order[0]
      if (bounds) side = order.find((s) => {
        const r = labelRect(s, it.x, it.y, it.r, it.w, h)
        return r.x0 >= bounds.x0 && r.x1 <= bounds.x1
      }) || side
      chosen = { side, ...labelRect(side, it.x, it.y, it.r, it.w, h), crowded: true }
    }
    if (chosen) {
      out.set(it.id, chosen)
      placed.push(inflate(chosen, pad))
    }
  }
  return out
}

// ---------------------------------------------------------------------------
// The camera

const stretchOf = (view) => (view && view.s > 0 ? view.s : 1)

/**
 * The view that fits these stars (and, through labelsAt, their printed names)
 * into box = { x0, y0, x1, y1 } of the screen. Stars and names keep their
 * pixel size at any scale, so the fit is solved for the spread alone.
 * labelsAt(k, s) -> Map id -> rect relative to the star (screen px), or null.
 *
 * stretch > 1 lets a tall frame (a phone's sheet) draw the constellation out
 * downward by up to that factor, so the sky is filled rather than a band of it;
 * s fixes that stretch instead (a focus keeps the whole view's). The view is
 * { k, tx, ty, s }: screen x = x * k + tx, screen y = y * k * s + ty.
 */
export function fitView(nodes, box, { minK = 0.3, maxK = 2, labelsAt = null, stretch = 1, s: fixedS = 0 } = {}) {
  const availW = Math.max(40, box.x1 - box.x0)
  const availH = Math.max(40, box.y1 - box.y0)
  if (!nodes.length) return { k: 1, tx: box.x0 + availW / 2, ty: box.y0 + availH / 2, s: fixedS > 0 ? fixedS : 1 }
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    minX = Math.min(minX, n.x)
    maxX = Math.max(maxX, n.x)
    minY = Math.min(minY, n.y)
    maxY = Math.max(maxY, n.y)
  }
  const spanX = maxX - minX
  const spanY = maxY - minY
  let s = fixedS > 0 ? fixedS : 1

  const extentAt = (k) => {
    const rects = labelsAt ? labelsAt(k, s) : null
    let x0 = Infinity
    let x1 = -Infinity
    let y0 = Infinity
    let y1 = -Infinity
    for (const n of nodes) {
      const sx = n.x * k
      const sy = n.y * k * s
      x0 = Math.min(x0, sx - n.r - 4)
      x1 = Math.max(x1, sx + n.r + 4)
      y0 = Math.min(y0, sy - n.r - 4)
      y1 = Math.max(y1, sy + n.r + 4)
      const rect = rects && rects.get(n.id)
      if (rect) {
        x0 = Math.min(x0, sx + rect.x0)
        x1 = Math.max(x1, sx + rect.x1)
        y0 = Math.min(y0, sy + rect.y0)
        y1 = Math.max(y1, sy + rect.y1)
      }
    }
    return { x0, x1, y0, y1 }
  }

  const clampK = (k) => Math.max(minK, Math.min(maxK, k))
  // Extent is spread * k plus a fixed margin of pixels: solve for k.
  const solve = (k0) => {
    let k = k0
    let ext = extentAt(k)
    for (let i = 0; i < 6; i++) {
      const cx = ext.x1 - ext.x0 - spanX * k
      const cy = ext.y1 - ext.y0 - spanY * k * s
      const kx = spanX > 1 ? (availW - cx) / spanX : maxK
      const ky = spanY > 1 ? (availH - cy) / (spanY * s) : maxK
      const next = clampK(Math.min(kx, ky))
      if (Math.abs(next - k) / k < 0.005) break
      k = next
      ext = extentAt(k)
    }
    return [k, ext]
  }
  let [k, ext] = solve(clampK(Math.min(spanX > 1 ? (availW * 0.7) / spanX : maxK, spanY > 1 ? (availH * 0.85) / (spanY * s) : maxK)))

  if (!(fixedS > 0) && stretch > 1 && spanY > 1) {
    for (let i = 0; i < 4; i++) {
      const cy = ext.y1 - ext.y0 - spanY * k * s
      const want = Math.max(1, Math.min(stretch, (availH - cy) / (spanY * k)))
      if (Math.abs(want - s) < 0.01) break
      s = want
      ;[k, ext] = solve(k)
    }
  }

  const tx = box.x0 + (availW - (ext.x1 - ext.x0)) / 2 - ext.x0
  const ty = box.y0 + (availH - (ext.y1 - ext.y0)) / 2 - ext.y0
  return { k, tx, ty, s }
}

/**
 * The view that frames a chosen star's neighbourhood. It leans in from the
 * whole view (wholeK, wholeS) but never far. Beside a rail it keeps the whole
 * view's stretch. Above a sheet (a phone, a tablet, a narrow column) the strip
 * of sky left is short, so the view may pull back further and the stretch
 * relaxes: every tie of the chosen star stays in sight, for and against.
 */
export const focusView = (nodes, box, { wholeK = 1, wholeS = 1, sheet = false, labelsAt = null } = {}) =>
  fitView(nodes, box, {
    minK: wholeK * (sheet ? 0.45 : 0.85),
    maxK: Math.min(2.6, wholeK * 1.4),
    s: sheet ? Math.min(wholeS, 1.2) : wholeS,
    labelsAt
  })

export const toScreen = (view, x, y) => [x * view.k + view.tx, y * view.k * stretchOf(view) + view.ty]
export const toWorld = (view, sx, sy) => [(sx - view.tx) / view.k, (sy - view.ty) / (view.k * stretchOf(view))]

/** Ease the camera toward a target view; returns true while still moving. */
export function easeView(view, target, dt, snap = false) {
  const ts = stretchOf(target)
  if (snap) {
    view.k = target.k
    view.tx = target.tx
    view.ty = target.ty
    view.s = ts
    return false
  }
  const vs = stretchOf(view)
  const rate = 1 - Math.exp(-dt / 190)
  view.k += (target.k - view.k) * rate
  view.tx += (target.tx - view.tx) * rate
  view.ty += (target.ty - view.ty) * rate
  view.s = vs + (ts - vs) * rate
  const moving =
    Math.abs(target.k - view.k) > 0.0005 || Math.abs(target.tx - view.tx) > 0.2 || Math.abs(target.ty - view.ty) > 0.2 || Math.abs(ts - view.s) > 0.001
  if (!moving) {
    view.k = target.k
    view.tx = target.tx
    view.ty = target.ty
    view.s = ts
  }
  return moving
}

/** The star under a point on screen, or null. Slop widens the target for fingers. */
export function nodeAt(nodes, view, sx, sy, slop = 6) {
  let best = null
  let bestD = Infinity
  for (const n of nodes) {
    const [x, y] = toScreen(view, n.x, n.y)
    const d = Math.hypot(sx - x, sy - y)
    const reach = Math.max((n.face || 0) > 0.5 ? n.r + FACE_GROW : n.r + slop, 12)
    if (d <= reach && d < bestD) {
      best = n
      bestD = d
    }
  }
  return best
}

// ---------------------------------------------------------------------------
// Ambient life

/** The slow drift of a star, in screen pixels. Still under reduced motion. */
export const drift = (n, time, still) => {
  if (still) return [0, 0]
  const t = time / 1000
  return [Math.sin(t * 0.21 + n.phase) * 1.3, Math.cos(t * 0.17 + n.phase * 1.3) * 1.3]
}

const easeOutCubic = (e) => 1 - Math.pow(1 - e, 3)
const easeInOut = (e) => (e < 0.5 ? 2 * e * e : 1 - Math.pow(-2 * e + 2, 2) / 2)
const easeOutBack = (e) => {
  const c = 1.5
  return 1 + (c + 1) * Math.pow(e - 1, 3) + c * Math.pow(e - 1, 2)
}

/** How far a star has appeared: 0 before its bloom or intro, 1 once it is there. */
export const appearance = (n, now, still) => {
  if (still) return 1
  if (n.bornAt != null) {
    const e = (now - n.bornAt) / 560
    if (e <= 0) return 0
    return e >= 1 ? 1 : Math.max(0, easeOutBack(e))
  }
  if (n.introAt != null) {
    const e = (now - n.introAt) / INTRO_MS
    if (e <= 0) return 0
    return e >= 1 ? 1 : easeOutCubic(e)
  }
  return 1
}

/** Clear finished blooms and pulses; true while anything is still arriving. */
export function tidyArrivals(state, now) {
  let busy = false
  for (const n of state.nodes) {
    if (n.bornAt != null) {
      if (now - n.bornAt > BLOOM_MS) n.bornAt = null
      else busy = true
    }
    if (n.introAt != null) {
      if (now - n.introAt > INTRO_MS) n.introAt = null
      else busy = true
    }
  }
  for (const l of state.links) {
    if (l.bornAt != null) {
      if (now - l.bornAt > PULSE_MS + 200) l.bornAt = null
      else busy = true
    }
  }
  return busy
}

/**
 * Move each star's and tie's emphasis toward the focus: the neighbourhood of
 * `center` stays lit, everything else fades. Returns true while still fading.
 */
export function updateEmphasis(state, center, dt, snap = false, { only = null } = {}) {
  const near = center ? neighbourhood(state, center) : null
  // One kind of name lit from the legend (a type key; '' for things spoken of),
  // the rest dimmed, while no one is chosen.
  const kind = !near && only !== null && only !== undefined ? String(only) : null
  const ofKind = (n) => kind === null || (n && (n.type || '') === kind)
  const rate = snap ? 1 : 1 - Math.exp(-dt / 130)
  let moving = false
  const ease = (obj, key, target) => {
    const v = obj[key] ?? target
    const nv = v + (target - v) * rate
    obj[key] = Math.abs(nv - target) < 0.002 ? target : nv
    if (obj[key] !== target) moving = true
  }
  for (const n of state.nodes) {
    ease(n, 'em', (!near && ofKind(n)) || (near && near.has(n.id)) ? 1 : DIM)
    ease(n, 'hot', center === n.id ? 1 : 0)
  }
  for (const l of state.links) {
    const incident = !!center && (l.source === center || l.target === center)
    const lit = near ? incident : kind === null || ofKind(l.s) || ofKind(l.t)
    ease(l, 'em', lit ? 1 : LINK_DIM)
    ease(l, 'hot', incident ? 1 : 0)
  }
  return moving
}

/**
 * Faces: a star in `wanted` (ids whose portrait is ready) opens into its
 * citizen's face over FACE_MS, and closes again when let go. At once under
 * reduced motion. Returns true while any face is still opening or closing.
 */
export function updateFaces(state, wanted, dt, snap = false) {
  let moving = false
  const step = snap ? 1 : Math.max(0, dt) / FACE_MS
  for (const n of state.nodes) {
    const target = wanted && wanted.has(n.id) ? 1 : 0
    const v = n.face || 0
    if (v === target) continue
    n.face = target > v ? Math.min(1, v + step) : Math.max(0, v - step)
    if (n.face !== target) moving = true
  }
  return moving
}

/** The radius of a star's face disc as it opens. */
export const faceRadius = (n) => n.r + FACE_GROW * easeOutCubic(Math.max(0, Math.min(1, n.face || 0)))

/**
 * A beat in the square: the speaker's star blooms and the thread to whoever
 * they addressed lights. Returns false when the speaker is not in the sky.
 */
export function flashBeat(state, fromId, toId, now) {
  if (!fromId || !state.byId.has(fromId)) return false
  const flashes = (state.flashes || []).filter((f) => now - f.at < FLASH_MS)
  const to = toId && toId !== fromId && state.byId.has(toId) ? toId : null
  flashes.push({ from: fromId, to, at: now })
  state.flashes = flashes.slice(-12)
  return true
}

/** Clear spent beats; true while any is still showing. */
export function tidyFlashes(state, now) {
  if (!state.flashes || !state.flashes.length) return false
  state.flashes = state.flashes.filter((f) => now - f.at < FLASH_MS)
  return state.flashes.length > 0
}

/** Milliseconds until the last showing beat is spent. */
export const flashLeft = (state, now) => Math.max(0, ...(state.flashes || []).map((f) => FLASH_MS - (now - f.at)))

// A faint field of far stars behind the Web, in unit coordinates.
export function createDust(count = 140, seed = 399) {
  const out = []
  for (let i = 0; i < count; i++) {
    const h = hashString(`${seed}:${i}`)
    out.push({
      u: unit(h),
      v: unit(h + 1),
      r: unit(h + 2) < 0.85 ? 1 : 1.6,
      a: 0.05 + unit(h + 3) * 0.22,
      s: 0.3 + unit(h + 4) * 0.9,
      p: unit(h + 5) * Math.PI * 2
    })
  }
  return out
}

// ---------------------------------------------------------------------------
// Colour

export const parseColor = (value, fallback = [242, 237, 228]) => {
  const s = String(value || '').trim()
  let m = /^#([0-9a-f]{3})$/i.exec(s)
  if (m) return m[1].split('').map((c) => parseInt(c + c, 16))
  m = /^#([0-9a-f]{6})/i.exec(s)
  if (m) return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16))
  m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(s)
  if (m) return [Number(m[1]), Number(m[2]), Number(m[3])].map((v) => Math.round(v))
  return fallback
}

export const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`

/**
 * The sky's colours from the page's tokens. read(name) returns the value of a
 * CSS custom property such as '--p-gold' (resolve once, e.g. with getComputedStyle).
 */
export function resolvePalette(read = () => '') {
  const c = (name, fallback) => parseColor(read(name), parseColor(fallback))
  const gold = c('--p-gold', '#f0b660')
  const ink = c('--p-ink', '#f2ede4')
  const palette = {
    surface: c('--p-surface', '#11151c'),
    ink,
    ink2: c('--p-ink-2', '#d8d2c7'),
    ink3: c('--p-ink-3', '#a7a197'),
    ink4: c('--p-ink-4', '#8a847a'),
    gold,
    olive: c('--p-olive', '#a8b86a'),
    error: c('--p-error', '#f08a7a'),
    aegean: c('--p-aegean', '#8fb8d8'),
    ochre: c('--p-ochre', '#d9a25a')
  }
  palette.families = {
    people: palette.gold,
    institutions: palette.aegean,
    movements: palette.olive,
    machines: palette.ink,
    places: palette.ochre,
    things: palette.ink4
  }
  return palette
}

// ---------------------------------------------------------------------------
// Drawing
//
// Three layers, so the page can keep the still parts still:
//   drawAmbient: the far stars and the glow of each star, which twinkle;
//   drawConstellation: threads, stars, faces and names, which change only when
//     something moves (the page may paint it once to a canvas of its own);
//   drawOverlay: what passes over the sky (blooms, the chosen star's slow
//     pulse, beats from the square).
// drawWeb paints all three in order.

const colorOf = (P, n) => P.families[n.family] || P.families.things

/** Where each star stands on screen this frame, and how far it has appeared. */
export function placeStars(state, view, now = 0, still = false) {
  for (const n of state.nodes) {
    const [x, y] = toScreen(view, n.x, n.y)
    n.sx = x
    n.sy = y
    n.appear = appearance(n, now, still)
  }
}

// Gradients are made once and kept while their star or thread stays put; the
// fade is carried by globalAlpha, so emphasis never remakes them.
const cached = (obj, slot, key, make) => {
  if (obj[`${slot}Key`] !== key) {
    obj[slot] = make()
    obj[`${slot}Key`] = key
  }
  return obj[slot]
}
const q1 = (v) => Math.round(v * 10)

/** Whether a star's glow twinkles (drawn each ambient frame) or holds steady (drawn with the constellation). */
export const twinkles = (n) => (n.rank ?? 0) < TWINKLE_MAX

// The light around a star; tw is the twinkle (1 when steady).
const paintGlow = (ctx, P, n, tw, slot) => {
  if (!(n.appear > 0) || !Number.isFinite(n.sx)) return
  const col = colorOf(P, n)
  const em = n.em ?? 1
  const hot = n.hot || 0
  const r = Math.max(0.5, n.r * n.appear)
  const a = (0.32 * tw * em + 0.22 * hot) * Math.min(1, n.appear)
  if (a < 0.01) return
  const gr = r * 3.2 + 6 + hot * 6 + (n.face || 0) * FACE_GROW
  ctx.globalAlpha = Math.min(1, a)
  ctx.fillStyle = cached(n, slot, `${q1(n.sx)}|${q1(n.sy)}|${q1(r)}|${q1(gr)}|${col}`, () => {
    const g = ctx.createRadialGradient(n.sx, n.sy, Math.min(r * 0.4, gr * 0.5), n.sx, n.sy, gr)
    g.addColorStop(0, rgba(col, 1))
    g.addColorStop(1, rgba(col, 0))
    return g
  })
  ctx.beginPath()
  ctx.arc(n.sx, n.sy, gr, 0, Math.PI * 2)
  ctx.fill()
}

/**
 * The far stars and the twinkling light around the best-tied stars (the rest
 * glow steadily with the constellation, so a large sky costs no more to keep
 * alive). frame = { width, height, palette, time, still, dust, hide (only the
 * far stars, while the sky is still finding its places) }.
 */
export function drawAmbient(ctx, state, frame) {
  const { width, height, palette: P, time = 0, still = false, dust = null, hide = false } = frame
  ctx.clearRect(0, 0, width, height)
  ctx.save()
  if (dust) {
    for (const d of dust) {
      const tw = still ? 1 : 0.55 + 0.45 * Math.sin((time / 1000) * d.s + d.p)
      const [dx, dy] = drift({ phase: d.p }, time, still)
      ctx.fillStyle = rgba(P.ink, d.a * tw)
      ctx.fillRect(d.u * width + dx, d.v * height + dy, d.r, d.r)
    }
  }
  if (!hide) {
    ctx.globalCompositeOperation = 'lighter'
    const t = time / 1000
    for (const n of state.nodes) {
      if (!twinkles(n)) continue
      const tw = still ? 1 : 0.82 + 0.18 * Math.sin(t * (0.6 + (n.phase % 1) * 0.5) + n.phase)
      paintGlow(ctx, P, n, tw, '_glow')
    }
  }
  ctx.restore()
}

// A face in its disc, cropped like the coins elsewhere (a little above centre).
const drawFace = (ctx, img, x, y, R) => {
  const iw = img.naturalWidth || img.width || 0
  const ih = img.naturalHeight || img.height || 0
  if (!(iw > 0 && ih > 0)) return
  const side = Math.min(iw, ih)
  const sx = (iw - side) / 2
  const sy = (ih - side) * 0.3
  ctx.save()
  ctx.beginPath()
  ctx.arc(x, y, R, 0, Math.PI * 2)
  ctx.clip()
  ctx.drawImage(img, sx, sy, side, side, x - R, y - R, R * 2, R * 2)
  ctx.restore()
}

/**
 * Threads, stars, faces and names. frame = { width, height, palette, now,
 * still, chatter (draw the chatter layer), labels (Map id -> rect), center
 * (hovered, keyed or chosen id), focus (chosen id), faceOf(node) -> a loaded
 * image or null, fonts: { display, inscription }, clear (default true) }.
 */
export function drawConstellation(ctx, state, frame) {
  const { width, height, palette: P, now = 0, still = false, chatter = false, labels = null, center = null, focus = null, faceOf = null, clear = true } = frame
  const fonts = frame.fonts || { display: frame.font || 'serif', inscription: frame.font || 'serif' }
  if (clear) ctx.clearRect(0, 0, width, height)

  ctx.save()
  ctx.lineCap = 'round'
  ctx.globalCompositeOperation = 'lighter'

  // The chatter: faint gold stitches, beneath the threads.
  if (chatter) {
    ctx.setLineDash([2, 5])
    for (const l of state.links) {
      if (!l.chatter) continue
      const a = l.s
      const b = l.t
      const show = Math.min(a.appear, b.appear)
      if (!(show > 0)) continue
      const alpha = (0.17 * (l.em ?? 1) + 0.4 * (l.hot || 0)) * show
      if (alpha < 0.01) continue
      ctx.strokeStyle = rgba(P.gold, alpha)
      ctx.lineWidth = 0.8 + Math.min(1.2, Math.log2(1 + l.chatter) * 0.35)
      ctx.beginPath()
      ctx.moveTo(a.sx, a.sy)
      ctx.lineTo(b.sx, b.sy)
      ctx.stroke()
    }
    ctx.setLineDash([])
  }

  // The threads: structural ties, luminous, thicker where ties run in parallel.
  const pulses = []
  const crowded = state.links.length > CROWDED_TIES
  for (const l of state.links) {
    if (!l.structural) continue
    const a = l.s
    const b = l.t
    const show = Math.min(a.appear, b.appear)
    if (!(show > 0)) continue
    let grow = 1
    if (!still && l.bornAt != null) {
      const e = (now - l.bornAt) / PULSE_MS
      if (e <= 0) continue
      if (e < 1) {
        grow = easeInOut(e)
        pulses.push({ l, e: grow, fade: 1 - e })
      }
    }
    const ex = a.sx + (b.sx - a.sx) * grow
    const ey = a.sy + (b.sy - a.sy) * grow
    const em = l.em ?? 1
    const hot = l.hot || 0
    const alpha = (0.3 * em + 0.55 * hot) * show
    if (alpha < 0.01) continue
    const w = 0.7 + Math.min(2.2, Math.log2(1 + l.structural) * 0.75) + hot * 0.4
    let stroke
    if (l.stance === 'opposes' || l.stance === 'supports') {
      stroke = rgba(l.stance === 'opposes' ? P.error : P.olive, 1)
    } else {
      const ca = colorOf(P, a)
      const cb = colorOf(P, b)
      stroke = cached(l, '_grad', `${q1(a.sx)}|${q1(a.sy)}|${q1(b.sx)}|${q1(b.sy)}|${ca}|${cb}`, () => {
        const g = ctx.createLinearGradient(a.sx, a.sy, b.sx, b.sy)
        g.addColorStop(0, rgba(ca, 1))
        g.addColorStop(1, rgba(cb, 1))
        return g
      })
    }
    const lift = l.stance ? 1.3 : 1
    ctx.strokeStyle = stroke
    ctx.beginPath()
    ctx.moveTo(a.sx, a.sy)
    ctx.lineTo(ex, ey)
    // The light around the thread (on a crowded sky, only around the lit
    // ones, where it can be seen), then the thread.
    if (!crowded || hot > 0.05) {
      ctx.globalAlpha = Math.min(1, alpha * 0.16 * lift)
      ctx.lineWidth = w + 3.5
      ctx.stroke()
    }
    ctx.globalAlpha = Math.min(1, alpha * lift)
    ctx.lineWidth = w
    ctx.stroke()
  }
  ctx.globalAlpha = 1

  // The heads of arriving ties.
  for (const p of pulses) {
    const a = p.l.s
    const b = p.l.t
    const x = a.sx + (b.sx - a.sx) * p.e
    const y = a.sy + (b.sy - a.sy) * p.e
    const g = ctx.createRadialGradient(x, y, 0, x, y, 9)
    g.addColorStop(0, rgba(P.ink, 0.95 * p.fade + 0.2))
    g.addColorStop(0.35, rgba(P.gold, 0.5 * p.fade + 0.1))
    g.addColorStop(1, rgba(P.gold, 0))
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.arc(x, y, 9, 0, Math.PI * 2)
    ctx.fill()
  }

  // The steady glow of the stars that do not twinkle.
  for (const n of state.nodes) if (!twinkles(n)) paintGlow(ctx, P, n, 1, '_steady')
  ctx.globalAlpha = 1

  // The stars, small beneath large; faces over their embers.
  ctx.globalCompositeOperation = 'source-over'
  const order = [...state.nodes].sort((x, y) => (x.face || 0) - (y.face || 0) || (x.em ?? 1) - (y.em ?? 1) || x.r - y.r)
  for (const n of order) {
    if (!(n.appear > 0)) continue
    const col = colorOf(P, n)
    const em = n.em ?? 1
    const r = Math.max(0.5, n.r * n.appear)
    // Core: the ember, hot at the heart.
    ctx.globalAlpha = 0.28 + 0.72 * em
    ctx.fillStyle = cached(n, '_core', `${q1(n.sx)}|${q1(n.sy)}|${q1(r)}|${col}`, () => {
      const core = ctx.createRadialGradient(n.sx - r * 0.25, n.sy - r * 0.25, 0, n.sx, n.sy, r)
      core.addColorStop(0, rgba([255, 248, 232], 1))
      core.addColorStop(0.45, rgba(col, 1))
      core.addColorStop(1, rgba(col.map((v) => v * 0.72), 1))
      return core
    })
    ctx.beginPath()
    ctx.arc(n.sx, n.sy, r, 0, Math.PI * 2)
    ctx.fill()
    ctx.globalAlpha = 1

    // A face: the citizen's portrait in a disc, ringed in their role's colour.
    const face = Math.min(1, n.face || 0)
    let ringAt = r + 4.5
    if (face > 0 && faceOf) {
      const img = faceOf(n)
      if (img) {
        const R = faceRadius(n) * Math.min(1, n.appear)
        ctx.globalAlpha = face
        drawFace(ctx, img, n.sx, n.sy, R)
        ctx.strokeStyle = rgba(col, 0.95)
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.arc(n.sx, n.sy, R + 0.75, 0, Math.PI * 2)
        ctx.stroke()
        ctx.strokeStyle = rgba(col, 0.2)
        ctx.lineWidth = 3
        ctx.beginPath()
        ctx.arc(n.sx, n.sy, R + 3, 0, Math.PI * 2)
        ctx.stroke()
        ctx.globalAlpha = 1
        ringAt = R + 6.5
      }
    }
    // The chosen star wears a ring.
    if (focus === n.id) {
      ctx.strokeStyle = rgba(P.ink, 0.9)
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.arc(n.sx, n.sy, ringAt, 0, Math.PI * 2)
      ctx.stroke()
    }
  }

  // Names, with a dark halo so they read over threads and light. A name
  // outside the lit neighbourhood fades only to LABEL_FLOOR.
  if (labels && labels.size) {
    ctx.textBaseline = 'middle'
    ctx.textAlign = 'left'
    ctx.lineJoin = 'round'
    const spacing = 'letterSpacing' in ctx
    for (const [id, rect] of labels) {
      const n = state.byId.get(id)
      if (!n || !(n.appear > 0.05)) continue
      const lead = id === center || id === focus
      const em = n.em ?? 1
      const alpha = Math.min(1, n.appear) * (lead ? 1 : LABEL_FLOOR + (1 - LABEL_FLOOR) * em)
      const voice = labelVoice(n)
      const style = labelStyle(voice, fonts)
      ctx.font = style.font
      if (spacing) ctx.letterSpacing = `${style.tracking}px`
      const text = labelText(n)
      const x = rect.x0
      const y = (rect.y0 + rect.y1) / 2 + (voice === 'thing' ? 0.5 : 0)
      ctx.strokeStyle = rgba(P.surface, 0.92 * alpha)
      ctx.lineWidth = voice === 'thing' ? 3.5 : 4
      ctx.strokeText(text, x, y)
      ctx.fillStyle = rgba(voice === 'voice' && (lead || n.top) ? P.ink : P.ink2, alpha)
      ctx.fillText(text, x, y)
    }
    if (spacing) ctx.letterSpacing = '0px'
  }
  ctx.restore()
}

/**
 * What passes over the sky. frame = { palette, time, now, still, focus }.
 * Under reduced motion a beat is shown as a steady mark, without movement.
 */
export function drawOverlay(ctx, state, frame) {
  const { palette: P, time = 0, now = 0, still = false, focus = null } = frame
  ctx.save()
  ctx.lineCap = 'round'
  const t = time / 1000

  // The chosen star breathes a slow ring outward.
  const chosen = focus ? state.byId.get(focus) : null
  if (chosen && !still && chosen.appear > 0) {
    const e = (t % 2.4) / 2.4
    const base = (chosen.face || 0) > 0.01 ? faceRadius(chosen) + 6.5 : chosen.r + 5
    ctx.strokeStyle = rgba(colorOf(P, chosen), 0.45 * (1 - e))
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.arc(chosen.sx, chosen.sy, base + e * 14, 0, Math.PI * 2)
    ctx.stroke()
  }

  // A newcomer blooms: one ring opening out and fading.
  if (!still) {
    for (const n of state.nodes) {
      if (n.bornAt == null) continue
      const e = (now - n.bornAt) / BLOOM_MS
      if (!(e > 0 && e < 1)) continue
      const k = easeOutCubic(e)
      ctx.strokeStyle = rgba(colorOf(P, n), 0.75 * (1 - e))
      ctx.lineWidth = 1.5 * (1 - e) + 0.5
      ctx.beginPath()
      ctx.arc(n.sx, n.sy, n.r + 3 + k * 34, 0, Math.PI * 2)
      ctx.stroke()
    }
  }

  // Beats from the square: the speaker blooms, the thread to the one they
  // addressed lights and a spark crosses it.
  for (const f of state.flashes || []) {
    const a = state.byId.get(f.from)
    if (!a || !(a.appear > 0) || !Number.isFinite(a.sx)) continue
    const e = still ? 0 : Math.max(0, Math.min(1, (now - f.at) / FLASH_MS))
    const fade = still ? 0.85 : 1 - e
    const col = colorOf(P, a)
    const b = f.to ? state.byId.get(f.to) : null
    ctx.globalCompositeOperation = 'lighter'
    if (b && b.appear > 0 && Number.isFinite(b.sx)) {
      ctx.strokeStyle = rgba(col, 0.6 * fade)
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(a.sx, a.sy)
      ctx.lineTo(b.sx, b.sy)
      ctx.stroke()
      if (!still) {
        const p = easeInOut(Math.min(1, e / 0.7))
        const x = a.sx + (b.sx - a.sx) * p
        const y = a.sy + (b.sy - a.sy) * p
        const g = ctx.createRadialGradient(x, y, 0, x, y, 10)
        g.addColorStop(0, rgba(P.ink, 0.9 * fade))
        g.addColorStop(0.4, rgba(col, 0.5 * fade))
        g.addColorStop(1, rgba(col, 0))
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(x, y, 10, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.strokeStyle = rgba(colorOf(P, b), 0.5 * fade)
      ctx.lineWidth = 1.2
      ctx.beginPath()
      ctx.arc(b.sx, b.sy, b.r + 4, 0, Math.PI * 2)
      ctx.stroke()
    }
    const base = (a.face || 0) > 0.01 ? faceRadius(a) + 3 : a.r + 3
    const glow = ctx.createRadialGradient(a.sx, a.sy, 0, a.sx, a.sy, base + 16)
    glow.addColorStop(0, rgba(col, 0.5 * fade))
    glow.addColorStop(1, rgba(col, 0))
    ctx.fillStyle = glow
    ctx.beginPath()
    ctx.arc(a.sx, a.sy, base + 16, 0, Math.PI * 2)
    ctx.fill()
    ctx.globalCompositeOperation = 'source-over'
    ctx.strokeStyle = rgba(col, 0.85 * fade)
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.arc(a.sx, a.sy, base + (still ? 5 : easeOutCubic(e) * 24), 0, Math.PI * 2)
    ctx.stroke()
  }
  ctx.restore()
}

/**
 * Paint the whole sky at once. frame = {
 *   width, height (CSS px; the context is already scaled for the device),
 *   view: { k, tx, ty, s }, palette, time, now, still (reduced motion),
 *   chatter, labels, center, focus, dust, faceOf, fonts (see the layers above)
 * }
 */
export function drawWeb(ctx, state, frame) {
  placeStars(state, frame.view, frame.now || 0, !!frame.still)
  drawAmbient(ctx, state, frame)
  drawConstellation(ctx, state, { ...frame, clear: false })
  drawOverlay(ctx, state, frame)
}
