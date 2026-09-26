<template>
  <div class="graph-panel" ref="graphContainer" :class="{ narrow: isNarrow }">
    <!-- The panel's own bar: what is here, and one small choice. The Web
         grows on its own while the city works; the shell shows and hides it. -->
    <div class="panel-top">
      <div class="panel-heading">
        <span v-if="!isNarrow" class="p-eyebrow panel-title">{{ $t('parthenon.web.title') }}</span>
        <span class="panel-sub" role="status" aria-live="polite">
          <span v-if="busy" class="ember" aria-hidden="true"></span>
          <span class="panel-sub-text">{{ subline }}</span>
          <button
            v-if="lateThreads && !busy"
            type="button"
            class="look-again"
            :disabled="loading"
            @click="onRefresh"
          >{{ $t('parthenon.web.lookAgain') }}</button>
        </span>
      </div>
      <div v-if="graphData" class="panel-tools">
        <button
          type="button"
          class="p-button ghost small chatter"
          :class="{ on: showChatter }"
          :aria-pressed="showChatter"
          :title="$t('parthenon.web.chatterHint')"
          @click="showChatter = !showChatter"
        >
          <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path d="M3 5.5h9M3 9h6M3 12.5h4" stroke-linecap="round" />
            <path d="M12.5 11.5 15 14l3.5-4.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>{{ showChatter ? $t('parthenon.web.chatterOn') : $t('parthenon.web.chatter') }}</span>
        </button>
      </div>
    </div>

    <!-- The sky: the constellation itself. -->
    <div class="sky" ref="sky">
      <svg
        ref="graphSvg"
        class="graph-svg"
        role="group"
        :aria-label="pictureLabel"
        :class="{ hidden: !graphData }"
      ></svg>

      <!-- Before the Web exists: one quiet sentence. -->
      <div v-if="!graphData" class="sky-state">
        <span v-if="loading" class="ember large" aria-hidden="true"></span>
        <span v-else class="star" aria-hidden="true"></span>
        <p>{{ loading ? $t('parthenon.web.reading') : $t('parthenon.web.notYet') }}</p>
      </div>

      <!-- The card: who this is, or what ties these two. Hover shows it; a choice pins it. -->
      <div
        v-if="card"
        class="web-card"
        :class="{ pinned: !!pinned, [`family-${card.family || 'tie'}`]: true }"
        :style="cardStyle"
      >
        <template v-if="card.kind === 'node'">
          <div class="card-head">
            <span class="card-dot" :style="{ background: card.colorVar }" aria-hidden="true"></span>
            <span class="card-role p-eyebrow">{{ card.role || $t('parthenon.web.thing') }}</span>
            <button v-if="pinned" type="button" class="card-close" :aria-label="$t('parthenon.web.closeCard')" @click.stop="clearPinned">
              <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" /></svg>
            </button>
          </div>
          <h3 class="card-name">{{ card.name }}</h3>
          <p v-if="card.summary" class="card-text">{{ card.summary }}</p>
          <p class="card-meta">{{ card.degree === 1 ? $t('parthenon.web.tieOne') : $t('parthenon.web.tiesOf', { n: card.degree }) }}</p>
        </template>
        <template v-else>
          <div class="card-head">
            <span class="card-dot tie" :class="card.stance" aria-hidden="true"></span>
            <span class="card-role p-eyebrow">{{ card.count === 1 ? $t('parthenon.web.tieOne') : $t('parthenon.web.tiesOf', { n: card.count }) }}</span>
            <button v-if="pinned" type="button" class="card-close" :aria-label="$t('parthenon.web.closeCard')" @click.stop="clearPinned">
              <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" /></svg>
            </button>
          </div>
          <ul class="card-ties" role="list">
            <li v-for="line in card.lines" :key="line.key">
              <span class="tie-from">{{ line.from }}</span>
              <span class="tie-word">{{ line.word }}</span>
              <span class="tie-to">{{ line.to }}</span>
              <span v-if="line.count > 1" class="tie-count">{{ $t('parthenon.web.times', { n: line.count }) }}</span>
            </li>
          </ul>
          <p v-if="card.more" class="card-meta">{{ $t('parthenon.web.andMore', { n: card.more }) }}</p>
          <p v-if="card.fact" class="card-text fact">{{ card.fact }}</p>
        </template>
      </div>

      <!-- Who is here: an inscription in the corner. -->
      <div v-if="graphData && legend.length" ref="legendEl" class="legend" :class="{ open: legendOpen }" :style="legendStyle">
        <button type="button" class="legend-head" :aria-expanded="legendOpen" @click="legendOpen = !legendOpen">
          <span class="p-eyebrow">{{ $t('parthenon.web.whoIsHere') }}</span>
          <span class="chev" aria-hidden="true"></span>
        </button>
        <ul v-show="legendOpen" class="legend-items" role="list">
          <li v-for="entry in legend" :key="entry.type" class="legend-item">
            <span class="legend-dot" :style="{ background: entry.colorVar }" aria-hidden="true"></span>
            <span class="legend-label">{{ entry.label }}</span>
            <span class="legend-count">{{ entry.count }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
// The Web of Athens, Phase I: a night-sky constellation of the names the scroll
// has tied together. Platform hubs are hidden, the chatter of the square is
// folded away behind one toggle, parallel ties are drawn once and thicker, and
// every name keeps its place from one poll to the next.
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import * as d3 from 'd3'
import {
  entityTypeName,
  roleFamily,
  roleColorVar,
  tieName,
  isActivityTie,
  isPlatformNode,
  citizenName,
  platformName,
  stripIds
} from '../parthenon/vocabulary.js'

const props = defineProps({
  graphData: Object,
  loading: Boolean,
  currentPhase: Number,
  isSimulating: Boolean
})

const emit = defineEmits(['refresh'])
const { t } = useI18n()

const graphContainer = ref(null)
const sky = ref(null)
const graphSvg = ref(null)
const legendEl = ref(null)

const showChatter = ref(false)
const legendOpen = ref(true)
const isNarrow = ref(false)
const compact = ref(false)
const hover = ref(null)
const pinned = ref(null)
const cardPos = ref({ x: 16, y: 16 })
const lateThreads = ref(false)
const wasSimulating = ref(false)
// How much of the sky's foot lies below the fold, behind the Way strip.
const hiddenBelow = ref(0)

// Every name is printed. The twelve best-tied are set in a heavier hand.
const TOP_LABELS = 12
const NAME_MAX = 22
const COMPACT_MAX = 16
const COMPACT_WIDTH = 420
const LATE_THREADS_MS = 90000
const UNTYPED_COLOR = 'var(--p-ink-4)'

// ---------------------------------------------------------------------------
// Words

// Facts arrive in the engine's words; the square has its own.
const cityWords = (text) => {
  let s = stripIds(text)
  if (!s) return ''
  s = s
    .replace(/\bOn (Twitter|X)\b/g, `In ${platformName('twitter')}`)
    .replace(/\bOn Reddit\b/g, `In ${platformName('reddit')}`)
    .replace(/\bTwitter\b/g, platformName('twitter'))
    .replace(/\bReddit\b/g, platformName('reddit'))
    .replace(/\bthe user [“"]([a-z0-9]+(?:_[a-z0-9]+)*)[”"]/gi, (m, handle) => citizenName('', handle))
    .replace(/[“"]([a-z0-9]+(?:_[a-z0-9]+)*_\d+)[”"]/g, (m, handle) => citizenName('', handle))
  return s
}

const shortName = (name, max = NAME_MAX) => (name.length > max ? name.slice(0, max - 1).trimEnd() + '…' : name)

// On a narrow sheet a citizen is "Despina N."; a thing keeps its name, cut short.
const compactName = (name, family) => {
  const words = name.split(/\s+/).filter(Boolean)
  if (family === 'people' && words.length >= 2) return `${words[0]} ${words[words.length - 1].charAt(0)}.`
  return shortName(name, COMPACT_MAX)
}

// ---------------------------------------------------------------------------
// The model: what the picture shows, derived from the engine's graph

const buildModel = (data, chatter) => {
  const empty = { nodes: [], links: [], legend: [], top: new Set(), signature: '', tieCount: 0, chatterCount: 0 }
  if (!data || !Array.isArray(data.nodes)) return empty

  const rawNodes = data.nodes.filter((n) => n && n.uuid && !isPlatformNode(n.name))
  const ids = new Set(rawNodes.map((n) => n.uuid))
  const rawEdges = (data.edges || []).filter(
    (e) => e && ids.has(e.source_node_uuid) && ids.has(e.target_node_uuid) && e.source_node_uuid !== e.target_node_uuid
  )

  const degree = new Map()
  const bundles = new Map()
  let chatterCount = 0

  for (const e of rawEdges) {
    const name = e.name || e.fact_type || 'RELATES_TO'
    const activity = isActivityTie(name)
    const a = e.source_node_uuid
    const b = e.target_node_uuid
    if (!activity) {
      degree.set(a, (degree.get(a) || 0) + 1)
      degree.set(b, (degree.get(b) || 0) + 1)
    } else {
      chatterCount++
      if (!chatter) continue
    }
    const key = a < b ? `${a}|${b}` : `${b}|${a}`
    let bundle = bundles.get(key)
    if (!bundle) {
      bundle = { key, source: a < b ? a : b, target: a < b ? b : a, count: 0, structural: false, stance: '', ties: new Map() }
      bundles.set(key, bundle)
    }
    bundle.count++
    if (!activity) bundle.structural = true
    if (name === 'SUPPORTS' && !bundle.stance) bundle.stance = 'supports'
    if (name === 'OPPOSES') bundle.stance = 'opposes'
    const tkey = `${name}>${a}`
    let tie = bundle.ties.get(tkey)
    if (!tie) {
      tie = { key: tkey, name, word: tieName(name), from: a, to: b, count: 0, fact: '', activity }
      bundle.ties.set(tkey, tie)
    }
    tie.count++
    if (!tie.fact && e.fact) tie.fact = cityWords(e.fact)
  }

  const maxDegree = Math.max(1, ...degree.values())
  const radius = d3.scaleSqrt().domain([0, maxDegree]).range([3.5, 10])

  const nodes = rawNodes.map((n) => {
    const type = (n.labels || []).find((l) => l && l !== 'Entity') || ''
    const role = type ? entityTypeName(type) : ''
    const name = citizenName(n.name) || n.name || ''
    const deg = degree.get(n.uuid) || 0
    const family = type ? roleFamily(type) : 'untyped'
    return {
      id: n.uuid,
      name,
      label: shortName(name),
      labelCompact: compactName(name, family),
      type,
      role,
      family,
      colorVar: type ? roleColorVar(type) : UNTYPED_COLOR,
      degree: deg,
      r: radius(deg),
      summary: cityWords(n.summary || ''),
      rank: 0,
      top: false
    }
  })

  // Rank by ties decides only the weight of a name and who is printed first.
  const ranked = [...nodes].sort((x, y) => y.degree - x.degree || x.name.localeCompare(y.name))
  ranked.forEach((n, i) => {
    n.rank = i
    n.top = i < TOP_LABELS
  })
  const top = new Set(ranked.slice(0, TOP_LABELS).map((n) => n.id))

  const links = [...bundles.values()].map((b) => ({
    key: b.key,
    source: b.source,
    target: b.target,
    count: b.count,
    structural: b.structural,
    stance: b.stance,
    ties: [...b.ties.values()].sort((x, y) => Number(x.activity) - Number(y.activity) || y.count - x.count)
  }))

  const byType = new Map()
  for (const n of nodes) {
    if (!n.type || !n.role) continue
    const entry = byType.get(n.type) || { type: n.type, label: n.role, colorVar: n.colorVar, count: 0 }
    entry.count++
    byType.set(n.type, entry)
  }
  const legend = [...byType.values()].sort((x, y) => y.count - x.count || x.label.localeCompare(y.label))

  const signature =
    nodes.map((n) => n.id).sort().join(',') + '#' + links.map((l) => `${l.key}:${l.count}`).sort().join(',')

  return { nodes, links, legend, top, signature, tieCount: links.length, chatterCount }
}

const model = computed(() => buildModel(props.graphData, showChatter.value))
const legend = computed(() => model.value.legend)

const busy = computed(() => props.currentPhase === 1 || props.isSimulating)

const subline = computed(() => {
  if (props.isSimulating) return t('parthenon.web.moving')
  if (props.currentPhase === 1 && !model.value.nodes.length) return t('parthenon.web.weaving')
  if (lateThreads.value) return t('parthenon.web.lateThreads')
  if (!props.graphData) return ''
  const m = model.value
  if (!m.nodes.length) return t('parthenon.web.empty')
  // On a narrow panel the chatter button already says whether the chatter is in.
  const key = isNarrow.value
    ? 'parthenon.web.countShort'
    : (showChatter.value ? 'parthenon.web.countChatter' : 'parthenon.web.count')
  return t(key, { names: m.nodes.length, ties: m.tieCount })
})

const pictureLabel = computed(() =>
  t('parthenon.web.picture', { names: model.value.nodes.length, ties: model.value.tieCount })
)

// The card reads from the pinned choice first, then from what the pointer is over.
const card = computed(() => pinned.value || hover.value)
const cardStyle = computed(() => ({ left: `${cardPos.value.x}px`, top: `${cardPos.value.y}px` }))
const legendStyle = computed(() => ({ bottom: `${12 + hiddenBelow.value}px` }))

// ---------------------------------------------------------------------------
// The picture: d3 on one svg, with joins so nothing is rebuilt on a poll

let svg = null
let root = null
let linkLayer = null
let nodeLayer = null
let sim = null
let zoom = null
let resizeObserver = null
let width = 600
let height = 480
let currentTransform = d3.zoomIdentity
let userZoomed = false
let lastSignature = ''
let hasLaidOut = false
let simNodes = []
let simLinks = []
let adjacency = new Map()
let paint = {}

// Every name keeps its place: node objects live here across polls, keyed by id.
const nodeById = new Map()

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

// How hard the sky pulls the names to its centre, across and down, so the
// constellation takes the shape of the pane it is in.
const pull = () => {
  if (isNarrow.value) return { x: 0.18, y: 0.015 }
  const aspect = Math.max(0.5, Math.min(2, width / Math.max(1, height)))
  return { x: Math.min(0.14, 0.055 / aspect), y: Math.min(0.14, 0.055 * aspect) }
}

const resolveVar = (expr, fallback) => {
  const el = graphContainer.value
  if (!el) return fallback
  const m = /var\((--[\w-]+)\)/.exec(expr || '')
  const name = m ? m[1] : expr
  const value = getComputedStyle(el).getPropertyValue(name).trim()
  return value || fallback
}

const readPaint = () => {
  paint = {
    surface: resolveVar('var(--p-surface)', '#11151c'),
    ink: resolveVar('var(--p-ink)', '#f2ede4'),
    ink2: resolveVar('var(--p-ink-2)', '#d8d2c7'),
    ink3: resolveVar('var(--p-ink-3)', '#a7a197'),
    ink4: resolveVar('var(--p-ink-4)', '#8a847a'),
    gold: resolveVar('var(--p-gold)', '#f0b660'),
    olive: resolveVar('var(--p-olive)', '#a8b86a'),
    error: resolveVar('var(--p-error)', '#f08a7a'),
    families: {
      people: resolveVar('var(--p-gold)', '#f0b660'),
      institutions: resolveVar('var(--p-aegean)', '#8fb8d8'),
      movements: resolveVar('var(--p-olive)', '#a8b86a'),
      machines: resolveVar('var(--p-ink)', '#f2ede4'),
      places: resolveVar('var(--p-ochre)', '#d9a25a'),
      untyped: resolveVar('var(--p-ink-4)', '#8a847a')
    }
  }
}

const nodeColor = (d) => paint.families[d.family] || paint.families.untyped

// Labels keep their 12px whatever the zoom, so the sky can be scaled to fit
// without the names growing or shrinking with it.
const LABEL_PX = 12
const LABEL_H = 14
const LABEL_GAP = 6 // between a coin and its name
const LABEL_PAD = 3 // kept clear around every printed name
const CHAR_W = 6.6
// Right of the coin, left, below, above; then the four corners as a last resort.
const SIDES = ['r', 'l', 'b', 'a', 'rb', 'ra', 'lb', 'la']
const CORNER_LIFT = 11 // how far a corner name sits above or below the coin's centre line
let fitScale = 1 // the scale the picture is heading for, so the forces can plan for it
const labelScale = () => 1 / (currentTransform.k || 1)
const plannedLabelScale = () => 1 / (fitScale || 1)

const labelText = (d) => (compact.value ? d.labelCompact : d.label) || ''

// The width of a printed name, measured once per string in the body face.
let measureCtx = null
const widthCache = new Map()
const labelWidth = (text) => {
  if (!text) return 0
  const cached = widthCache.get(text)
  if (cached != null) return cached
  let w = 0
  try {
    if (!measureCtx) {
      measureCtx = document.createElement('canvas').getContext('2d')
      const family = graphContainer.value ? getComputedStyle(graphContainer.value).getPropertyValue('--p-font-body').trim() : ''
      measureCtx.font = `500 ${LABEL_PX}px ${family || 'Geist, sans-serif'}`
    }
    w = measureCtx.measureText(text).width
  } catch (e) {
    w = 0
  }
  if (!(w > 0)) w = text.length * CHAR_W
  widthCache.set(text, w)
  return w
}

// Where a name sits beside its coin, in screen pixels from the coin's centre.
const labelBox = (d, side, k, w) => {
  const R = d.r * k
  const lift = side.length === 2 ? (side[1] === 'a' ? -CORNER_LIFT : CORNER_LIFT) : 0
  const gap = side.length === 2 ? R * 0.7 + LABEL_GAP : R + LABEL_GAP
  switch (side[0]) {
    case 'l':
      return { x0: -gap - w, x1: -gap, y0: lift - LABEL_H / 2, y1: lift + LABEL_H / 2 }
    case 'b':
      return { x0: -w / 2, x1: w / 2, y0: R + LABEL_PAD, y1: R + LABEL_PAD + LABEL_H }
    case 'a':
      return { x0: -w / 2, x1: w / 2, y0: -R - LABEL_PAD - LABEL_H, y1: -R - LABEL_PAD }
    default:
      return { x0: gap, x1: gap + w, y0: lift - LABEL_H / 2, y1: lift + LABEL_H / 2 }
  }
}

// The text attributes for a side, in the picture's units at label scale s.
const labelAnchor = (d, s) => {
  const side = d.side || 'r'
  const corner = side.length === 2
  const lift = corner ? (side[1] === 'a' ? -CORNER_LIFT : CORNER_LIFT) * s : 0
  const gap = corner ? d.r * 0.7 + LABEL_GAP * s : d.r + LABEL_GAP * s
  switch (side[0]) {
    case 'l':
      return { anchor: 'end', x: -gap, y: lift + 4 * s }
    case 'b':
      return { anchor: 'middle', x: 0, y: d.r + (LABEL_PAD + 11) * s }
    case 'a':
      return { anchor: 'middle', x: 0, y: -(d.r + (LABEL_PAD + 3) * s) }
    default:
      return { anchor: 'start', x: gap, y: lift + 4 * s }
  }
}

const boxesMeet = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1

const coinMeetsBox = (cx, cy, R, box) => {
  const nx = Math.max(box.x0, Math.min(cx, box.x1))
  const ny = Math.max(box.y0, Math.min(cy, box.y1))
  return Math.hypot(cx - nx, cy - ny) < R
}

const applyLabelScale = () => {
  if (!nodeLayer) return
  const s = labelScale()
  nodeLayer
    .selectAll('g.node text.label')
    .attr('font-size', LABEL_PX * s)
    .attr('stroke-width', 3 * s)
    .attr('text-anchor', (d) => labelAnchor(d, s).anchor)
    .attr('x', (d) => labelAnchor(d, s).x)
    .attr('y', (d) => labelAnchor(d, s).y)
  nodeLayer.selectAll('g.node').classed('crowded', (d) => !!d.crowded)
}

// Once the names have settled, each is printed on the first side of its coin
// where it covers neither another name nor another coin. The best-tied are
// printed first. A name that fits nowhere is held back until it is pointed at.
const placeLabels = (k) => {
  if (!simNodes.length || !(k > 0)) return
  const ranked = [...simNodes].sort((a, b) => a.rank - b.rank)
  const placed = []
  for (const d of ranked) {
    const w = labelWidth(labelText(d))
    const sx = d.x * k
    const sy = d.y * k
    // A name keeps the side it had when it still fits there, so nothing jumps about.
    const order = d.side ? [d.side, ...SIDES.filter((s) => s !== d.side)] : SIDES
    let chosen = null
    for (const side of order) {
      const b = labelBox(d, side, k, w)
      const box = { x0: sx + b.x0 - LABEL_PAD, x1: sx + b.x1 + LABEL_PAD, y0: sy + b.y0 - LABEL_PAD, y1: sy + b.y1 + LABEL_PAD }
      if (placed.some((p) => boxesMeet(p, box))) continue
      if (simNodes.some((o) => o !== d && coinMeetsBox(o.x * k, o.y * k, o.r * k + 1, box))) continue
      chosen = side
      placed.push(box)
      break
    }
    d.crowded = !chosen
    if (chosen) d.side = chosen
    else if (!d.side) d.side = 'r'
  }
  applyLabelScale()
}

// A small force that keeps other coins out of each name's rectangle.
const labelCollide = () => {
  let nodes = []
  const force = (alpha) => {
    const k = alpha * 0.9
    const s = plannedLabelScale()
    for (const a of nodes) {
      const box = labelBox(a, a.side || 'r', 1 / s, labelWidth(labelText(a)))
      const x0 = a.x + (box.x0 - 2) * s
      const x1 = a.x + (box.x1 + 2) * s
      const y0 = a.y + (box.y0 - 2) * s
      const y1 = a.y + (box.y1 + 2) * s
      for (const b of nodes) {
        if (b === a) continue
        const cx = Math.max(x0, Math.min(b.x, x1))
        const cy = Math.max(y0, Math.min(b.y, y1))
        const dx = b.x - cx
        const dy = b.y - cy
        const dist = Math.hypot(dx, dy)
        const min = b.r + 4 * s
        if (dist >= min) continue
        let ux
        let uy
        if (dist > 0.01) {
          ux = dx / dist
          uy = dy / dist
        } else {
          ux = 0
          uy = b.y >= a.y ? 1 : -1
        }
        const push = (min - dist) * k
        b.vx += ux * push
        b.vy += uy * push
        a.vx -= ux * push * 0.35
        a.vy -= uy * push * 0.35
      }
    }
  }
  force.initialize = (n) => { nodes = n }
  return force
}

const linkStroke = (d) => {
  if (d.stance === 'opposes') return paint.error
  if (d.stance === 'supports') return paint.olive
  return d.structural ? paint.ink2 : paint.gold
}

const linkOpacity = (d) => (d.structural ? 0.34 : 0.16)
const linkWidth = (d) => 1 + Math.min(3, Math.log2(Math.max(1, d.count)))

// Where the picture may sit: below the bar, above the legend, above the fold.
const fitInsets = () => {
  const legendH = legendEl.value ? legendEl.value.offsetHeight : 0
  const aboveLegend = legendOpen.value && !isNarrow.value ? Math.max(84, legendH + 24) : 48
  return { top: 12, right: 16, bottom: aboveLegend + hiddenBelow.value, left: 16 }
}

const storageKey = () => {
  const id = props.graphData?.graph_id
  return id ? `parthenon.web.pos.${id}` : ''
}

const loadPositions = () => {
  const key = storageKey()
  if (!key) return {}
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? JSON.parse(raw) : {}
  } catch (e) {
    return {}
  }
}

const savePositions = () => {
  const key = storageKey()
  if (!key || !simNodes.length) return
  try {
    const out = {}
    for (const n of simNodes) out[n.id] = [Math.round(n.x), Math.round(n.y)]
    sessionStorage.setItem(key, JSON.stringify(out))
  } catch (e) {
    /* a per-viewer convenience only */
  }
}

// While the pane is hidden (the phone sheet before it opens) the sky has no
// size; the first layout waits for the first real one.
let skyVisible = false
let pendingRender = false
let legendDecided = false

// The shell's Web pane can run below the fold before the visitor scrolls
// (it is as tall as the viewport but starts under the threshold band), and the
// Way strip covers whatever lies there. The picture keeps to the part that
// can be seen. In the phone sheet, which floats above the strip, nothing is hidden.
const inFixedLayer = (el) => {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    if (getComputedStyle(n).position === 'fixed') return true
  }
  return false
}

const measureFold = (rect) => {
  if (typeof window === 'undefined' || !graphContainer.value) return 0
  const wayH = parseFloat(getComputedStyle(graphContainer.value).getPropertyValue('--p-way-h')) || 0
  const floor = inFixedLayer(graphContainer.value) ? window.innerHeight : window.innerHeight - wayH
  const hidden = Math.max(0, Math.round(rect.bottom - floor))
  // Never take more than half the sky; past that the visitor has to scroll anyway.
  return Math.min(hidden, Math.round(rect.height / 2))
}

const measure = () => {
  const el = sky.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  skyVisible = rect.width > 0 && rect.height > 0
  width = Math.max(240, Math.round(rect.width) || 600)
  height = Math.max(240, Math.round(rect.height) || 480)
  isNarrow.value = width < 560
  compact.value = width < COMPACT_WIDTH
  hiddenBelow.value = skyVisible ? measureFold(rect) : 0
  // The inscription stands open only where the sky has room for it and every
  // name; on a short sky it waits, closed, for a click.
  if (skyVisible && !legendDecided) {
    legendDecided = true
    legendOpen.value = !isNarrow.value && height - hiddenBelow.value >= 600
  }
  if (svg) svg.attr('width', width).attr('height', height).attr('viewBox', `0 0 ${width} ${height}`)
  if (sim) {
    sim.force('x').x(width / 2)
    sim.force('y').y(height / 2)
  }
}

const SCALE_MIN = 0.3
const SCALE_MAX = 1.4

const availArea = () => {
  const ins = fitInsets()
  return { ins, availW: Math.max(120, width - ins.left - ins.right), availH: Math.max(120, height - ins.top - ins.bottom) }
}

// Where the picture must sit to fill the sky: a first guess from the coins
// alone, with a little room kept for the names.
const computeFit = () => {
  const xs = simNodes.map((n) => n.x)
  const ys = simNodes.map((n) => n.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const { ins, availW, availH } = availArea()
  const maxR = Math.max(...simNodes.map((n) => n.r || 4))
  // Labels keep their screen size, so the room they need is in screen pixels.
  const labelRoom = Math.min(110, Math.max(50, availW * 0.2))
  const padY = 24
  const spanX = Math.max(1, maxX - minX + maxR * 2)
  const spanY = Math.max(1, maxY - minY + maxR * 2)
  const scale = Math.max(SCALE_MIN, Math.min(SCALE_MAX, Math.min((availW - labelRoom) / spanX, (availH - padY) / spanY)))
  const cx = (minX - maxR + maxX + maxR + labelRoom / scale) / 2
  const cy = (minY + maxY) / 2
  const tx = ins.left + availW / 2 - cx * scale
  const ty = ins.top + availH / 2 - cy * scale
  return d3.zoomIdentity.translate(tx, ty).scale(scale)
}

// The screen-pixel bounds of coins and printed names at scale k, before translation.
const pictureBounds = (k) => {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const d of simNodes) {
    const sx = d.x * k
    const sy = d.y * k
    const R = d.r * k
    minX = Math.min(minX, sx - R)
    maxX = Math.max(maxX, sx + R)
    minY = Math.min(minY, sy - R)
    maxY = Math.max(maxY, sy + R)
    if (d.crowded) continue
    const b = labelBox(d, d.side || 'r', k, labelWidth(labelText(d)))
    minX = Math.min(minX, sx + b.x0)
    maxX = Math.max(maxX, sx + b.x1)
    minY = Math.min(minY, sy + b.y0)
    maxY = Math.max(maxY, sy + b.y1)
  }
  return { minX, minY, maxX, maxY }
}

// The names are placed at the planned scale and the fit is taken again with
// them counted, so no printed name ends up outside the frame.
const refineFit = (transform) => {
  let k = transform.k
  const { ins, availW, availH } = availArea()
  for (let i = 0; i < 4; i++) {
    placeLabels(k)
    const b = pictureBounds(k)
    const grow = Math.min(availW / Math.max(1, b.maxX - b.minX), availH / Math.max(1, b.maxY - b.minY))
    if (grow >= 0.98 && grow <= 1.08) break
    const next = Math.max(SCALE_MIN, Math.min(SCALE_MAX, k * (grow < 1 ? grow * 0.985 : Math.min(grow, 1.25))))
    if (Math.abs(next - k) < 0.005) break
    k = next
  }
  placeLabels(k)
  let b = pictureBounds(k)
  const over = Math.min(1, availW / Math.max(1, b.maxX - b.minX), availH / Math.max(1, b.maxY - b.minY))
  if (over < 0.995 && k > SCALE_MIN) {
    k = Math.max(SCALE_MIN, k * over)
    placeLabels(k)
    b = pictureBounds(k)
  }
  const bw = b.maxX - b.minX
  const bh = b.maxY - b.minY
  const tx = ins.left + (availW - bw) / 2 - b.minX
  const ty = ins.top + (availH - bh) / 2 - b.minY
  return d3.zoomIdentity.translate(tx, ty).scale(k)
}

// A few quiet ticks at the planned scale, so labels that grew in the picture's
// units when it was scaled down get their room back.
const settleLabels = () => {
  if (!sim || !simNodes.length) return
  const alpha = sim.alpha()
  sim.alpha(0.14)
  for (let i = 0; i < 60; i++) sim.tick()
  sim.alpha(alpha)
  tick()
}

// Fit the picture to the sky. With `settle`, the names first make room for
// their labels at the scale they are heading for, then the fit is taken again
// so nothing that moved ends up outside the frame.
const fit = (animate, settle = false) => {
  if (!svg || !zoom || !simNodes.length) return
  let transform = refineFit(computeFit())
  if (settle) {
    // Two rounds: the names are placed at the scale the picture will really
    // have, the coins make room for them, and the names that still fit nowhere
    // are placed again once the room is there.
    for (let round = 0; round < 2; round++) {
      fitScale = transform.k
      settleLabels()
      transform = refineFit(computeFit())
    }
  }
  fitScale = transform.k
  const target = animate && !reducedMotion() ? svg.transition().duration(700).ease(d3.easeCubicOut) : svg
  target.call(zoom.transform, transform)
}

const buildAdjacency = () => {
  adjacency = new Map()
  for (const l of simLinks) {
    const a = typeof l.source === 'object' ? l.source.id : l.source
    const b = typeof l.target === 'object' ? l.target.id : l.target
    if (!adjacency.has(a)) adjacency.set(a, new Set())
    if (!adjacency.has(b)) adjacency.set(b, new Set())
    adjacency.get(a).add(b)
    adjacency.get(b).add(a)
  }
}

// Focus: hovering or choosing a name lights its neighbourhood and dims the rest.
const applyFocus = () => {
  if (!nodeLayer || !linkLayer) return
  const focus = pinned.value || hover.value
  const nodes = nodeLayer.selectAll('g.node')
  const links = linkLayer.selectAll('g.link')
  if (!focus) {
    nodes.classed('lit', false).classed('dim', false).classed('chosen', false)
    links.classed('lit', false).classed('dim', false)
    return
  }
  if (focus.kind === 'node') {
    const near = adjacency.get(focus.id) || new Set()
    nodes
      .classed('lit', (d) => d.id === focus.id || near.has(d.id))
      .classed('dim', (d) => d.id !== focus.id && !near.has(d.id))
      .classed('chosen', (d) => !!pinned.value && d.id === focus.id)
    links
      .classed('lit', (d) => d.source.id === focus.id || d.target.id === focus.id)
      .classed('dim', (d) => d.source.id !== focus.id && d.target.id !== focus.id)
  } else {
    nodes
      .classed('lit', (d) => d.id === focus.a || d.id === focus.b)
      .classed('dim', (d) => d.id !== focus.a && d.id !== focus.b)
      .classed('chosen', false)
    links.classed('lit', (d) => d.key === focus.key).classed('dim', (d) => d.key !== focus.key)
  }
}

const nodeCard = (d) => ({
  kind: 'node',
  id: d.id,
  name: d.name,
  role: d.role,
  family: d.family,
  colorVar: d.colorVar,
  summary: d.summary,
  degree: d.degree
})

const linkCard = (d) => {
  const lines = d.ties.slice(0, 4).map((tie) => ({
    key: tie.key,
    from: nodeById.get(tie.from)?.name || '',
    word: tie.word,
    to: nodeById.get(tie.to)?.name || '',
    count: tie.count
  }))
  const withFact = d.ties.find((tie) => !tie.activity && tie.fact) || d.ties.find((tie) => tie.fact)
  return {
    kind: 'link',
    key: d.key,
    a: d.source.id,
    b: d.target.id,
    count: d.count,
    stance: d.stance,
    lines,
    more: Math.max(0, d.ties.length - lines.length),
    fact: withFact ? withFact.fact : ''
  }
}

const placeCardAt = (px, py) => {
  const cardW = 280
  const cardH = 190
  const x = Math.max(8, Math.min(px + 14, width - cardW - 8))
  const y = Math.max(8, Math.min(py + 14, height - cardH - 8))
  cardPos.value = { x, y }
}

const placeCardNear = (d) => {
  const [sx, sy] = currentTransform.apply([d.x, d.y])
  placeCardAt(sx + d.r * currentTransform.k, sy)
}

const pointerPos = (event) => {
  const rect = sky.value?.getBoundingClientRect()
  if (!rect) return [0, 0]
  return [event.clientX - rect.left, event.clientY - rect.top]
}

const clearPinned = () => {
  pinned.value = null
  applyFocus()
}

let lateTimer = null
const clearLateThreads = () => {
  lateThreads.value = false
  if (lateTimer) clearTimeout(lateTimer)
  lateTimer = null
}

const onRefresh = () => {
  clearLateThreads()
  emit('refresh')
}

// The names are printed again wherever they now fit, at the scale on screen.
const relabel = () => {
  if (!nodeLayer || !simNodes.length) return
  nodeLayer.selectAll('g.node text.label').text(labelText)
  if (userZoomed) placeLabels(currentTransform.k)
  else fit(false)
}

const tick = () => {
  linkLayer
    .selectAll('g.link')
    .selectAll('path')
    .attr('d', (d) => `M${d.source.x},${d.source.y}L${d.target.x},${d.target.y}`)
  nodeLayer.selectAll('g.node').attr('transform', (d) => `translate(${d.x},${d.y})`)
}

const onSettle = () => {
  if (userZoomed) placeLabels(currentTransform.k)
  else fit(true, true)
  savePositions()
}

const init = () => {
  svg = d3.select(graphSvg.value)
  root = svg.append('g').attr('class', 'root')
  linkLayer = root.append('g').attr('class', 'links')
  nodeLayer = root.append('g').attr('class', 'nodes')

  zoom = d3
    .zoom()
    .scaleExtent([0.25, 4])
    .on('zoom', (event) => {
      currentTransform = event.transform
      root.attr('transform', event.transform)
      applyLabelScale()
      if (event.sourceEvent) userZoomed = true
      if (pinned.value?.kind === 'node') {
        const d = nodeById.get(pinned.value.id)
        if (d) placeCardNear(d)
      }
    })
    // After the visitor's own zoom the names are printed again at the new size.
    .on('end', (event) => {
      if (event.sourceEvent) placeLabels(currentTransform.k)
    })
  svg.call(zoom).on('dblclick.zoom', null)

  svg.on('click', () => {
    pinned.value = null
    hover.value = null
    applyFocus()
  })

  sim = d3
    .forceSimulation()
    .force(
      'link',
      d3
        .forceLink()
        .id((d) => d.id)
        .distance((d) => (d.structural ? 104 : 132))
        .strength((d) => (d.structural ? 0.55 : 0.12))
    )
    // Names with no visible tie are pulled in and pushed less, so they hang
    // about the constellation like faint stars instead of fleeing to the edge,
    // yet far enough apart that each keeps room for its name.
    .force('charge', d3.forceManyBody().strength((d) => (d.shown ? -280 : -160)).distanceMax(460))
    .force('collide', d3.forceCollide().radius((d) => d.r + 14).strength(0.8))
    .force('labels', labelCollide())
    // A tall pane gets a tall constellation: the pull inward is stronger across
    // than down when the sky is taller than it is wide, and the other way about.
    .force('x', d3.forceX(width / 2).strength((d) => (d.shown ? pull().x : pull().x * 1.6)))
    .force('y', d3.forceY(height / 2).strength((d) => (d.shown ? pull().y : pull().y * 1.6)))
    .alphaDecay(0.035)
    .velocityDecay(0.42)
    .on('tick', tick)
    .on('end', onSettle)
  sim.stop()

  resizeObserver = new ResizeObserver(() => {
    const before = width + 'x' + height + '/' + hiddenBelow.value
    const wasVisible = skyVisible
    measure()
    if (skyVisible && !wasVisible && pendingRender) {
      pendingRender = false
      render()
      return
    }
    if (before !== width + 'x' + height + '/' + hiddenBelow.value && simNodes.length && !userZoomed) fit(false)
  })
  resizeObserver.observe(sky.value)
  window.addEventListener('scroll', onScroll, { passive: true })
  measure()
}

// As the page scrolls the fold moves; the picture follows it once per frame.
let scrollFrame = 0
const onScroll = () => {
  if (scrollFrame) return
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0
    const before = hiddenBelow.value
    measure()
    if (Math.abs(hiddenBelow.value - before) >= 6 && simNodes.length && !userZoomed) fit(!reducedMotion())
  })
}

const render = () => {
  if (!svg || !props.graphData) return
  if (!skyVisible) {
    pendingRender = true
    return
  }
  const m = model.value
  if (m.signature === lastSignature) return
  const firstLayout = !hasLaidOut
  const previousIds = new Set(simNodes.map((n) => n.id))
  lastSignature = m.signature
  readPaint()

  const stored = firstLayout ? loadPositions() : {}
  const newNodes = []

  simNodes = m.nodes.map((n) => {
    let obj = nodeById.get(n.id)
    if (!obj) {
      obj = { id: n.id }
      const at = stored[n.id]
      if (Array.isArray(at)) {
        obj.x = at[0]
        obj.y = at[1]
      }
      nodeById.set(n.id, obj)
      newNodes.push(obj)
    }
    Object.assign(obj, n)
    return obj
  })

  // Newcomers stand beside the names they are tied to, not in the middle of the sky.
  const known = new Set(previousIds)
  for (const n of newNodes) {
    if (Number.isFinite(n.x) && Number.isFinite(n.y)) continue
    const near = []
    for (const l of m.links) {
      const other = l.source === n.id ? l.target : l.target === n.id ? l.source : null
      if (!other) continue
      const o = nodeById.get(other)
      if (o && (known.has(other) || Number.isFinite(o.x)) && Number.isFinite(o.x)) near.push(o)
    }
    if (near.length) {
      n.x = d3.mean(near, (o) => o.x) + (Math.random() - 0.5) * 40
      n.y = d3.mean(near, (o) => o.y) + (Math.random() - 0.5) * 40
    } else {
      const angle = Math.random() * Math.PI * 2
      const spread = firstLayout ? Math.min(width, height) * 0.3 : 60
      n.x = width / 2 + Math.cos(angle) * spread * Math.random()
      n.y = height / 2 + Math.sin(angle) * spread * Math.random()
    }
    n.vx = 0
    n.vy = 0
  }

  simLinks = m.links.map((l) => ({ ...l }))
  buildAdjacency()
  simNodes.forEach((n) => { n.shown = (adjacency.get(n.id)?.size || 0) > 0 })
  sim.nodes(simNodes) // re-reads every force's accessors, so `shown` and `top` take effect
  sim.force('link').links(simLinks)

  const quiet = reducedMotion()
  const enterDuration = quiet ? 0 : 700

  // Ties
  const link = linkLayer.selectAll('g.link').data(simLinks, (d) => d.key)
  link.exit().remove()
  const linkEnter = link.enter().append('g').attr('class', 'link')
  linkEnter.append('path').attr('class', 'hit')
  linkEnter.append('path').attr('class', 'line')
  const linkAll = linkEnter.merge(link)
  linkAll.classed('chatter', (d) => !d.structural).attr('data-stance', (d) => d.stance || null)
  linkAll
    .select('path.line')
    .attr('stroke', linkStroke)
    .attr('stroke-opacity', linkOpacity)
    .attr('stroke-width', linkWidth)
    .attr('stroke-dasharray', (d) => (d.structural ? null : '2 5'))
  linkAll
    .select('path.hit')
    .on('mouseenter', (event, d) => {
      hover.value = linkCard(d)
      placeCardAt(...pointerPos(event))
      applyFocus()
    })
    .on('mousemove', (event) => {
      if (!pinned.value) placeCardAt(...pointerPos(event))
    })
    .on('mouseleave', () => {
      hover.value = null
      applyFocus()
    })
    .on('click', (event, d) => {
      event.stopPropagation()
      if (pinned.value?.kind === 'link' && pinned.value.key === d.key) {
        pinned.value = null
      } else {
        pinned.value = linkCard(d)
        placeCardAt(...pointerPos(event))
      }
      applyFocus()
    })
  if (!quiet) {
    linkEnter.select('path.line').attr('opacity', 0).transition().duration(enterDuration).attr('opacity', 1)
  }

  // Names
  const node = nodeLayer.selectAll('g.node').data(simNodes, (d) => d.id)
  node.exit().remove()
  const nodeEnter = node
    .enter()
    .append('g')
    .attr('class', 'node')
    .attr('tabindex', 0)
    .attr('role', 'button')
  nodeEnter.append('circle').attr('class', 'glow')
  nodeEnter.append('circle').attr('class', 'core')
  nodeEnter.append('text').attr('class', 'label')
  const nodeAll = nodeEnter.merge(node)
  nodeAll
    .classed('top', (d) => d.top)
    .attr('data-id', (d) => d.id)
    .attr('data-family', (d) => d.family)
    .attr('aria-label', (d) => (d.role ? `${d.name}, ${d.role}` : d.name))
    .attr('transform', (d) => `translate(${d.x || width / 2},${d.y || height / 2})`)
  nodeAll.select('circle.glow').attr('r', (d) => d.r * 2.4).attr('fill', nodeColor)
  nodeAll
    .select('circle.core')
    .attr('r', (d) => d.r)
    .attr('fill', nodeColor)
    .attr('stroke', paint.surface)
    .attr('stroke-width', 1.5)
  nodeAll.select('text.label').text(labelText)
  applyLabelScale()

  nodeAll
    .on('mouseenter', (event, d) => {
      hover.value = nodeCard(d)
      if (!pinned.value) placeCardAt(...pointerPos(event))
      applyFocus()
    })
    .on('mousemove', (event) => {
      if (!pinned.value) placeCardAt(...pointerPos(event))
    })
    .on('mouseleave', () => {
      hover.value = null
      applyFocus()
    })
    .on('focus', (event, d) => {
      hover.value = nodeCard(d)
      if (!pinned.value) placeCardNear(d)
      applyFocus()
    })
    .on('blur', () => {
      hover.value = null
      applyFocus()
    })
    .on('keydown', (event, d) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        togglePin(d)
      } else if (event.key === 'Escape' && pinned.value) {
        clearPinned()
      }
    })
    .on('click', (event, d) => {
      event.stopPropagation()
      togglePin(d)
    })
    .call(
      d3
        .drag()
        .on('start', (event, d) => {
          d._sx = event.x
          d._sy = event.y
          d._moved = false
        })
        .on('drag', (event, d) => {
          if (!d._moved && Math.hypot(event.x - d._sx, event.y - d._sy) > 3) {
            d._moved = true
            userZoomed = true
            sim.alphaTarget(0.12).restart()
          }
          if (d._moved) {
            d.fx = event.x
            d.fy = event.y
            if (pinned.value?.id === d.id) placeCardNear(d)
          }
        })
        .on('end', (event, d) => {
          if (d._moved) sim.alphaTarget(0)
          d.fx = null
          d.fy = null
        })
    )

  if (!quiet) {
    nodeEnter.attr('opacity', 0).transition().duration(enterDuration).attr('opacity', 1)
  }

  applyFocus()

  // The layout: settle quietly the first time, then only nudge for what is new.
  if (firstLayout) {
    hasLaidOut = true
    const restored = simNodes.every((n) => stored[n.id])
    if (restored) {
      sim.alpha(0.08)
      tick()
    } else {
      sim.alpha(1)
      sim.stop()
      const steps = quiet ? 300 : 140
      for (let i = 0; i < steps; i++) sim.tick()
      tick()
      sim.alpha(quiet ? 0 : 0.18)
    }
    fit(false, quiet)
    if (quiet) {
      savePositions()
      return
    }
    sim.restart()
    return
  }

  if (quiet) {
    sim.stop()
    for (let i = 0; i < 200; i++) sim.tick()
    tick()
    if (!userZoomed) fit(false, true)
    savePositions()
    return
  }
  sim.alpha(newNodes.length ? 0.35 : 0.22).restart()
}

const togglePin = (d) => {
  if (pinned.value?.kind === 'node' && pinned.value.id === d.id) {
    pinned.value = null
  } else {
    pinned.value = nodeCard(d)
    placeCardNear(d)
  }
  applyFocus()
}

// ---------------------------------------------------------------------------
// Wiring

watch(
  () => props.graphData,
  () => {
    if (!props.graphData) {
      clearLateThreads()
      lastSignature = ''
      hasLaidOut = false
      pendingRender = false
      simNodes = []
      simLinks = []
      if (nodeLayer) nodeLayer.selectAll('*').remove()
      if (linkLayer) linkLayer.selectAll('*').remove()
      return
    }
    nextTick(render)
  },
  { deep: true }
)

watch(showChatter, () => nextTick(render))

watch(legendOpen, () => {
  if (simNodes.length && !userZoomed) fit(true)
})

watch(compact, () => nextTick(relabel))

watch(isNarrow, (narrow) => {
  legendOpen.value = !narrow
  // The inward pull changes shape with the panel; re-read the forces and settle again.
  if (!sim || !simNodes.length) return
  sim.nodes(simNodes)
  if (reducedMotion()) {
    sim.stop()
    for (let i = 0; i < 160; i++) sim.tick()
    tick()
    if (!userZoomed) fit(false, true)
    return
  }
  sim.alpha(0.3).restart()
})

// When the square closes, the city's memory is still tying the last threads
// for a while. The act reads the Web once on its own; for the minutes after,
// the visitor can look again themselves.
watch(
  () => props.isSimulating,
  (now) => {
    if (wasSimulating.value && !now) {
      clearLateThreads()
      lateThreads.value = true
      lateTimer = setTimeout(clearLateThreads, LATE_THREADS_MS)
    }
    wasSimulating.value = now
  },
  { immediate: true }
)

onMounted(() => {
  init()
  if (props.graphData) nextTick(render)
  // Names measured before the body face arrived are measured again once it has.
  if (typeof document !== 'undefined' && document.fonts?.ready) {
    document.fonts.ready.then(() => {
      widthCache.clear()
      measureCtx = null
      if (simNodes.length) relabel()
    }).catch(() => {})
  }
})

onBeforeUnmount(() => {
  savePositions()
  clearLateThreads()
  window.removeEventListener('scroll', onScroll)
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  if (resizeObserver) resizeObserver.disconnect()
  if (sim) sim.stop()
})
</script>

<style scoped>
.graph-panel {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background-color: var(--p-surface);
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
  overflow: hidden;
}

/* Faint marble veining and a vignette, so the sky has depth without a grid. */
.graph-panel::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: var(--p-marble-texture);
  opacity: 0.45;
  pointer-events: none;
}

.graph-panel::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 50% 45%, transparent 45%, rgba(0, 0, 0, 0.42) 100%);
  pointer-events: none;
}

.panel-top {
  position: relative;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px 8px 16px;
  min-width: 0;
}

.panel-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.panel-title {
  white-space: nowrap;
}

.panel-sub {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.panel-tools {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.panel-tools .p-button.chatter.on {
  color: var(--p-gold);
}

.panel-tools .p-button.chatter span {
  white-space: nowrap;
}

.panel-sub-text {
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

/* One quiet verb, present only while the last threads are being tied. */
.look-again {
  flex-shrink: 0;
  margin: -6px -4px;
  padding: 6px 4px;
  background: transparent;
  border: 0;
  font: inherit;
  font-weight: 500;
  color: var(--p-gold);
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}

.look-again:hover {
  color: var(--p-ink);
}

.look-again:disabled {
  color: var(--p-ink-4);
  cursor: default;
}

.ember {
  width: 7px;
  height: 7px;
  border-radius: var(--p-radius-coin);
  background: var(--p-gold);
  box-shadow: 0 0 0 3px var(--p-terracotta-tint);
  animation: breathe 1.8s ease-in-out infinite;
  flex-shrink: 0;
}

.ember.large {
  width: 10px;
  height: 10px;
  margin-bottom: 14px;
}

.star {
  width: 6px;
  height: 6px;
  border-radius: var(--p-radius-coin);
  background: var(--p-ink-4);
  margin-bottom: 14px;
}

@keyframes breathe {
  0%, 100% { box-shadow: 0 0 0 2px var(--p-terracotta-tint); opacity: 0.8; }
  50% { box-shadow: 0 0 0 7px transparent; opacity: 1; }
}

/* The sky */
.sky {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  min-width: 0;
}

.graph-svg {
  display: block;
  width: 100%;
  height: 100%;
  touch-action: none;
}

.graph-svg.hidden {
  visibility: hidden;
}

.graph-svg :deep(g.node) {
  cursor: pointer;
  outline: none;
  transition: opacity 0.25s ease;
}

.graph-svg :deep(g.node.dim) {
  opacity: 0.28;
}

.graph-svg :deep(circle.glow) {
  opacity: 0.16;
  transition: opacity 0.25s ease;
}

.graph-svg :deep(g.node.lit circle.glow),
.graph-svg :deep(g.node:hover circle.glow) {
  opacity: 0.36;
}

.graph-svg :deep(g.node.chosen circle.core) {
  stroke: var(--p-ink);
  stroke-width: 2px;
}

.graph-svg :deep(g.node:focus-visible circle.core) {
  stroke: var(--p-gold);
  stroke-width: 3px;
}

/* Every name is printed. Size and halo are set as attributes so they hold
   their 12px through the zoom; the best-tied are set in a heavier hand. */
.graph-svg :deep(text.label) {
  font-family: var(--p-font-body);
  font-weight: 500;
  fill: var(--p-ink-2);
  paint-order: stroke;
  stroke: var(--p-surface);
  stroke-linejoin: round;
  pointer-events: none;
  opacity: 1;
  transition: opacity 0.2s ease;
}

.graph-svg :deep(g.node.top text.label) {
  font-weight: 600;
  fill: var(--p-ink);
}

/* A name that fits nowhere waits until its coin is pointed at. */
.graph-svg :deep(g.node.crowded text.label) {
  opacity: 0;
}

.graph-svg :deep(g.node.lit text.label),
.graph-svg :deep(g.node:hover text.label) {
  opacity: 1;
  fill: var(--p-ink);
}

.graph-svg :deep(g.link path.line) {
  fill: none;
  stroke-linecap: round;
  pointer-events: none; /* the wide invisible path beneath it takes the pointer */
  transition: opacity 0.25s ease, stroke-opacity 0.25s ease;
}

.graph-svg :deep(g.link path.hit) {
  fill: none;
  stroke: transparent;
  stroke-width: 14px;
  cursor: pointer;
  pointer-events: stroke;
}

.graph-svg :deep(g.link.dim path.line) {
  opacity: 0.35;
}

.graph-svg :deep(g.link.lit path.line) {
  stroke-opacity: 0.9;
}

/* Before the Web exists */
.sky-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px;
  color: var(--p-ink-3);
}

.sky-state p {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  max-width: 26em;
}

/* The card */
.web-card {
  position: absolute;
  z-index: 5;
  width: min(280px, calc(100% - 16px));
  padding: 12px 14px 12px;
  background: rgba(17, 21, 28, 0.94);
  border: 1px solid var(--p-line-strong);
  border-radius: var(--p-radius);
  box-shadow: var(--p-shadow-2);
  backdrop-filter: blur(8px);
  pointer-events: none;
  color: var(--p-ink-2);
}

.web-card.pinned {
  pointer-events: auto;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.card-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--p-radius-coin);
  flex-shrink: 0;
}

.card-dot.tie {
  background: var(--p-ink-3);
}

.card-dot.tie.supports { background: var(--p-olive); }
.card-dot.tie.opposes { background: var(--p-error); }

.card-role {
  color: var(--p-ink-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.card-close {
  margin-left: auto;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 0;
  color: var(--p-ink-3);
  cursor: pointer;
  flex-shrink: 0;
}

.card-close:hover { color: var(--p-gold); }

.card-name {
  margin: 4px 0 6px;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 500;
  line-height: 1.1;
  color: var(--p-ink);
}

.card-text {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-text.fact {
  margin-top: 8px;
  font-style: italic;
  color: var(--p-ink-3);
}

.card-meta {
  margin: 8px 0 0;
  font-size: var(--t-xs);
  color: var(--p-ink-4);
}

.card-ties {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-ties li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 6px;
  font-size: var(--t-sm);
  line-height: 1.35;
}

.tie-from,
.tie-to {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 500;
  color: var(--p-ink);
}

.tie-word {
  font-family: var(--p-font-serif);
  font-style: italic;
  color: var(--p-gold);
}

.tie-count {
  font-size: var(--t-xs);
  color: var(--p-ink-4);
}

/* The legend */
.legend {
  position: absolute;
  z-index: 4;
  left: 12px;
  bottom: 12px;
  max-width: calc(100% - 24px);
  background: rgba(17, 21, 28, 0.88);
  border: 1px solid var(--p-line);
  backdrop-filter: blur(6px);
}

.legend-head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  background: transparent;
  border: 0;
  cursor: pointer;
  text-align: left;
}

.legend-head .chev {
  width: 7px;
  height: 7px;
  border-right: 1.5px solid var(--p-ink-3);
  border-bottom: 1.5px solid var(--p-ink-3);
  transform: rotate(45deg);
  transition: transform 0.2s ease;
}

.legend.open .legend-head .chev {
  transform: rotate(-135deg);
}

.legend-items {
  list-style: none;
  margin: 0;
  padding: 0 12px 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px 14px;
  max-width: 360px;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--t-xs);
  color: var(--p-ink-2);
  white-space: nowrap;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--p-radius-coin);
  flex-shrink: 0;
}

.legend-count {
  color: var(--p-ink-4);
  font-variant-numeric: tabular-nums;
}

/* In a narrow column or the phone sheet */
.graph-panel.narrow .panel-top {
  padding: 8px 8px 6px 16px;
}

.graph-panel.narrow .legend-items {
  max-width: none;
  max-height: 128px;
  overflow: auto;
}

.graph-panel.narrow .web-card.pinned {
  left: 8px !important;
  right: 8px;
  top: auto !important;
  bottom: 52px;
  width: auto;
}

@media (prefers-reduced-motion: reduce) {
  .ember {
    animation: none;
  }

  .graph-svg :deep(g.node),
  .graph-svg :deep(text.label),
  .graph-svg :deep(circle.glow),
  .graph-svg :deep(g.link path.line) {
    transition: none;
  }
}
</style>
