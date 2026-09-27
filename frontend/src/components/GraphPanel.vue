<template>
  <div
    ref="panel"
    class="graph-panel"
    :class="{ narrow: isNarrow, sheet: inSheet, 'card-open': panelOpen, [`card-${cardMode}`]: panelOpen }"
    @keydown.esc="onEscape"
    @pointermove.passive="stir"
    @focusin="stir"
  >
    <!-- The panel's own bar: what is here, a way to find a name, and two small
         choices. The Web grows on its own while the city works. -->
    <div class="panel-top">
      <div class="panel-heading">
        <span v-if="!isNarrow && !inSheet" class="p-eyebrow panel-title">{{ $t('parthenon.web.title') }}</span>
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

      <div v-if="hasSky" class="panel-tools">
        <div class="finder" role="search">
          <label class="sr-only" :for="searchId">{{ $t('parthenon.web.findLabel') }}</label>
          <svg class="finder-icon" viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <circle cx="8.5" cy="8.5" r="5.5" /><path d="m12.7 12.7 4.3 4.3" stroke-linecap="round" />
          </svg>
          <input
            :id="searchId"
            ref="searchEl"
            v-model="query"
            type="search"
            class="finder-input"
            :placeholder="$t('parthenon.web.find')"
            autocomplete="off"
            spellcheck="false"
            role="combobox"
            aria-autocomplete="list"
            :aria-expanded="showMatches ? 'true' : 'false'"
            :aria-controls="listId"
            :aria-activedescendant="showMatches && matches.length ? `${listId}-${activeMatch}` : undefined"
            @keydown="onSearchKey"
            @focus="searchOpen = true"
            @blur="searchOpen = false"
          />
          <ul v-show="showMatches" :id="listId" class="finder-list" role="listbox" :aria-label="$t('parthenon.web.findLabel')">
            <li
              v-for="(m, i) in matches"
              :id="`${listId}-${i}`"
              :key="m.id"
              role="option"
              class="finder-option"
              :class="{ active: i === activeMatch }"
              :aria-selected="i === activeMatch ? 'true' : 'false'"
              @mousedown.prevent="chooseMatch(m)"
              @mousemove="activeMatch = i"
            >
              <CitizenCoin :name="m.name" :type="m.type || 'Entity'" :portrait="portraitOf(m)" size="sm" />
              <span class="opt-text">
                <span class="opt-name">{{ m.name }}</span>
                <span class="opt-role">{{ m.role || $t('parthenon.web.thing') }}</span>
              </span>
            </li>
            <li v-if="!matches.length" class="finder-none" role="option" aria-disabled="true" aria-selected="false">{{ $t('parthenon.web.noMatch') }}</li>
          </ul>
        </div>
        <button
          type="button"
          class="tool"
          :class="{ on: showChatter }"
          :aria-pressed="showChatter ? 'true' : 'false'"
          :title="$t('parthenon.web.chatterHint')"
          @click="showChatter = !showChatter"
        >
          <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path d="M3 5.5h9M3 9h6M3 12.5h4" stroke-linecap="round" />
            <path d="M12.5 11.5 15 14l3.5-4.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>{{ $t('parthenon.web.chatterShort') }}</span>
        </button>
        <button type="button" class="tool" :aria-label="$t('parthenon.web.fitLabel')" :title="$t('parthenon.web.fitLabel')" @click="fitAll">
          <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path d="M3 7V3h4M13 3h4v4M17 13v4h-4M7 17H3v-4" stroke-linecap="round" stroke-linejoin="round" />
            <circle cx="10" cy="10" r="1.6" />
          </svg>
          <span class="tool-text" aria-hidden="true">{{ $t('parthenon.web.fit') }}</span>
        </button>
      </div>
    </div>

    <!-- Who was just chosen, for those who listen rather than look. -->
    <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">{{ announcement }}</p>

    <!-- The sky -->
    <div ref="sky" class="sky">
      <!-- Three layers: the far stars and twinkling glows; the constellation,
           painted only when something changes; what passes over it. -->
      <canvas ref="ambientCanvas" class="sky-canvas sky-layer" :class="{ hidden: !hasSky }" aria-hidden="true"></canvas>
      <canvas
        ref="canvas"
        class="sky-canvas"
        :class="{ hidden: !hasSky, pointing: !!hoverId && !grabbing, grabbing }"
        aria-hidden="true"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerCancel"
        @pointerleave="onPointerLeave"
      ></canvas>
      <canvas ref="overlayCanvas" class="sky-canvas sky-layer" :class="{ hidden: !hasSky }" aria-hidden="true"></canvas>

      <!-- The whole Web in words: first for the keyboard, unseen until reached. -->
      <button
        v-if="hasSky"
        ref="listToggleEl"
        type="button"
        class="list-toggle"
        :aria-expanded="listOpen ? 'true' : 'false'"
        :aria-controls="listPanelId"
        @click="toggleList"
      >{{ listOpen ? $t('parthenon.web.closeList') : $t('parthenon.web.readAsList') }}</button>

      <!-- The best-tied names, as keys the keyboard can reach. Each sits over its star. -->
      <div v-if="hasSky" class="star-keys" role="group" :aria-label="pictureLabel" :aria-describedby="keysHintId">
        <button
          v-for="n in keyNodes"
          :key="n.id"
          :ref="(el) => setKeyEl(n.id, el)"
          type="button"
          class="star-key"
          :style="keyStyle(n)"
          :tabindex="n.id === rovingKeyId ? 0 : -1"
          :aria-label="n.role ? `${n.name}, ${n.role}` : n.name"
          :aria-pressed="focusId === n.id ? 'true' : 'false'"
          @click="onKeyChoose(n.id, $event)"
          @keydown="onKeyWalk($event, n.id)"
          @focus="onKeyFocus(n.id)"
          @blur="onKeyBlur(n.id)"
        ></button>
        <span :id="keysHintId" class="sr-only">{{ $t('parthenon.web.keys') }}</span>
      </div>

      <!-- The card: who this is and what the scroll says of them, on parchment
           held up in the dark. A rail at the right of the sky, or a sheet from
           the foot on a phone. -->
      <aside
        v-if="dossier"
        ref="cardEl"
        class="web-card p-paper"
        :class="`as-${cardMode}`"
        :style="cardStyle"
        :aria-labelledby="cardNameId"
        @animationend="wake"
      >
        <div class="card-head">
          <CitizenCoin
            :name="dossier.node.name"
            :type="dossier.node.type || 'Entity'"
            :portrait="portraitOf(dossier.node)"
            :size="cardMode === 'rail' ? 'lg' : 'md'"
          />
          <div class="card-id">
            <span class="card-role p-eyebrow" :style="{ color: familyColorVar(dossier.node.family) }">{{ dossier.node.role || $t('parthenon.web.thing') }}</span>
            <h3 :id="cardNameId" ref="cardNameEl" class="card-name" tabindex="-1">{{ dossier.node.name }}</h3>
            <span class="card-meta">{{ tieLine(dossier) }}</span>
          </div>
          <button ref="closeEl" type="button" class="card-close" :aria-label="$t('parthenon.web.closeCard')" @click="closeCard">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" /></svg>
          </button>
        </div>
        <div class="p-meander card-rule" aria-hidden="true"></div>

        <div class="card-body">
          <h4 class="card-section p-eyebrow">{{ $t('parthenon.web.scrollSays') }}</h4>
          <ul v-if="dossier.facts.length" class="card-facts" role="list">
            <li v-for="f in dossier.facts" :key="f.key" class="fact" :class="f.stance && `is-${f.stance}`">
              <span class="fact-mark" :style="{ background: f.stance ? undefined : familyColorVar(f.otherFamily) }" aria-hidden="true"></span>
              <p :lang="textLang(f.text)">{{ f.text }}</p>
            </li>
          </ul>
          <p v-else class="card-none">{{ $t('parthenon.web.noFacts') }}</p>

          <template v-if="dossier.node.summary">
            <h4 class="card-section p-eyebrow">{{ $t('parthenon.web.whoTheyAre') }}</h4>
            <p :id="summaryId" class="card-bio" :class="{ clamped: longSummary && !summaryOpen }" :lang="textLang(dossier.node.summary)">{{ dossier.node.summary }}</p>
            <button
              v-if="longSummary"
              type="button"
              class="card-more-toggle"
              :aria-expanded="summaryOpen ? 'true' : 'false'"
              :aria-controls="summaryId"
              @click="summaryOpen = !summaryOpen"
            >{{ summaryOpen ? $t('parthenon.web.readLess') : $t('parthenon.web.readMore') }}</button>
          </template>

          <template v-if="showChatter && dossier.chatterFacts.length">
            <h4 class="card-section p-eyebrow">{{ $t('parthenon.web.inSquare') }}</h4>
            <ul class="card-facts chatter" role="list">
              <li v-for="f in dossier.chatterFacts.slice(0, CHATTER_FACTS)" :key="f.key" class="fact">
                <span class="fact-mark" aria-hidden="true"></span>
                <p :lang="textLang(f.text)">{{ f.text }}</p>
              </li>
            </ul>
            <p v-if="dossier.chatterFacts.length > CHATTER_FACTS" class="card-more">{{ $t('parthenon.web.andMore', { n: dossier.chatterFacts.length - CHATTER_FACTS }) }}</p>
          </template>

          <template v-if="tiedTo.length">
            <h4 class="card-section p-eyebrow">{{ $t('parthenon.web.tiedTo') }}</h4>
            <ul class="card-ties" role="list">
              <li v-for="nb in tiedTo" :key="nb.id">
                <button type="button" class="tie-chip" @click="choose(nb.id, { moveFocus: true })">
                  <CitizenCoin :name="nb.name" :type="nb.type || 'Entity'" :portrait="portraitOf(nb)" size="sm" />
                  <span>{{ nb.name }}</span>
                </button>
              </li>
            </ul>
          </template>
        </div>
      </aside>

      <!-- The Web in words: every name by role, and whom the scroll ties them to. -->
      <section
        v-if="listOpen && hasSky"
        v-show="!dossier"
        :id="listPanelId"
        ref="listEl"
        class="web-list p-paper"
        :class="`as-${cardMode}`"
        :style="cardStyle"
        :aria-labelledby="listHeadId"
        @animationend="wake"
      >
        <div class="card-head list-head">
          <div class="card-id">
            <span class="p-eyebrow">{{ $t('parthenon.web.listTitle') }}</span>
            <h3 :id="listHeadId" ref="listHeadEl" class="card-name" tabindex="-1">{{ $t('parthenon.web.countShort', { names: model.nodes.length, ties: model.tieCount }) }}</h3>
          </div>
          <button type="button" class="card-close" :aria-label="$t('parthenon.web.closeList')" @click="closeList">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" /></svg>
          </button>
        </div>
        <div class="p-meander card-rule" aria-hidden="true"></div>
        <div class="card-body">
          <section v-for="group in words" :key="group.key || '_'" class="list-group">
            <h4 class="card-section p-eyebrow" :style="{ color: familyColorVar(group.family) }">{{ group.label || $t('parthenon.web.things') }}</h4>
            <ul class="list-names" role="list">
              <li v-for="n in group.names" :key="n.id" class="list-item">
                <button type="button" class="list-name" @click="choose(n.id, { from: $event.currentTarget, moveFocus: true })">
                  <CitizenCoin :name="n.name" :type="n.type || 'Entity'" :portrait="portraitOf(n)" size="sm" />
                  <span>{{ n.name }}</span>
                </button>
                <p class="list-ties">{{ tiesInWords(n) }}</p>
              </li>
            </ul>
          </section>
        </div>
      </section>

      <!-- Before the Web exists: one quiet sentence. -->
      <div v-if="!hasSky" class="sky-state">
        <span v-if="loading" class="ember large" aria-hidden="true"></span>
        <span v-else class="star" aria-hidden="true"></span>
        <p>{{ loading ? $t('parthenon.web.reading') : (graphData ? $t('parthenon.web.empty') : $t('parthenon.web.notYet')) }}</p>
      </div>

      <!-- Who is here: an inscription in the corner. -->
      <div
        v-if="hasSky && legend.length"
        v-show="!(panelOpen && cardMode === 'sheet')"
        ref="legendEl"
        class="legend"
        :class="{ open: legendOpen }"
        :style="legendStyle"
      >
        <button type="button" class="legend-head" :aria-expanded="legendOpen ? 'true' : 'false'" @click="legendOpen = !legendOpen">
          <span class="p-eyebrow">{{ $t('parthenon.web.whoIsHere') }}</span>
          <span class="chev" aria-hidden="true"></span>
        </button>
        <div v-show="legendOpen" class="legend-body">
          <ul class="legend-items" role="list" :aria-label="$t('parthenon.web.legendKinds')">
            <li v-for="(entry, i) in legend" :key="entry.key || '_'">
              <button
                :ref="(el) => setKindEl(i, el)"
                type="button"
                class="legend-item"
                :class="{ on: legendOnly === entry.key, dim: legendOnly !== null && legendOnly !== entry.key }"
                :tabindex="i === rovingKind ? 0 : -1"
                :aria-pressed="legendOnly === entry.key ? 'true' : 'false'"
                @click="toggleKind(entry.key)"
                @keydown="onKindWalk($event, i)"
                @focus="rovingKind = i"
              >
                <span class="legend-dot" :style="{ background: familyColorVar(entry.family) }" aria-hidden="true"></span>
                <span class="legend-label">{{ entry.label || $t('parthenon.web.things') }}</span>
                <span class="legend-count">{{ entry.count }}</span>
              </button>
            </li>
          </ul>
          <p class="legend-threads">
            <span class="thread-sample"><svg viewBox="0 0 24 6" width="24" height="6" aria-hidden="true"><path d="M1 3h22" class="ts-tie" /></svg>{{ $t('parthenon.web.threads.tie') }}</span>
            <span class="thread-sample"><svg viewBox="0 0 24 6" width="24" height="6" aria-hidden="true"><path d="M1 3h22" class="ts-allied" /></svg>{{ $t('parthenon.web.threads.allied') }}</span>
            <span class="thread-sample"><svg viewBox="0 0 24 6" width="24" height="6" aria-hidden="true"><path d="M1 3h22" class="ts-odds" /></svg>{{ $t('parthenon.web.threads.atOdds') }}</span>
            <span v-if="showChatter" class="thread-sample"><svg viewBox="0 0 24 6" width="24" height="6" aria-hidden="true"><path d="M1 3h22" class="ts-chatter" /></svg>{{ $t('parthenon.web.threads.chatter') }}</span>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// The Web of Athens, Phase III: the night sky itself. A canvas of ember stars
// drawn by parthenon/web.js (layout, growth, drawing); this component feeds it
// the city's graph, carries the pointer and the keyboard, and holds up the
// card of whoever is chosen. Positions persist across polls and visits; the
// sky never re-explodes.
//
// The sky is painted in layers: the constellation (threads, stars, faces,
// names) is drawn to a canvas of its own only when something changes; each
// frame lays it over the twinkling far stars and glows. The twinkle runs at
// about ten frames a second and rests after a while with no one about.
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import CitizenCoin from './CitizenCoin.vue'
import { ROLE_COLOR_VAR, textLang } from '../parthenon/vocabulary.js'
import { useCitizenPortraits } from '../parthenon/portraits.js'
import {
  buildWebModel,
  focusView,
  nodeDossier,
  searchNodes,
  webInWords,
  findByName,
  createWeb,
  syncWeb,
  stepWeb,
  settleCap,
  setChatterVisible,
  neighbourhood,
  placeLabels,
  fitView,
  easeView,
  toScreen,
  toWorld,
  nodeAt,
  updateEmphasis,
  updateFaces,
  tidyArrivals,
  flashBeat,
  tidyFlashes,
  flashLeft,
  createDust,
  resolvePalette,
  placeStars,
  drawAmbient,
  drawConstellation,
  drawOverlay,
  labelVoice,
  labelText,
  labelStyle,
  clearance,
  keyRadius,
  TOP_LABELS,
  INTRO_MAX,
  LABEL_PX,
  THING_PX,
  LABEL_GAP
} from '../parthenon/web.js'

const props = defineProps({
  graphData: Object,
  loading: Boolean,
  currentPhase: Number,
  isSimulating: Boolean,
  // The gathering whose citizens have faces; the route's is used when absent.
  simulationId: { type: String, default: '' },
  // A beat in the square: { from: name, to: name or null, key }. Each new
  // object blooms the speaker's star and lights the thread to whoever they
  // addressed, so the sky answers the square beside it.
  pulse: { type: Object, default: null },
  // A name held elsewhere in the act (a citizen held in the square, a name
  // opened in the Hearing's list): its star is lit with its ties and face,
  // and its name printed, without opening the card.
  hold: { type: String, default: '' }
})

const emit = defineEmits(['refresh'])
const i18n = useI18n()
const { t } = i18n
const route = useRoute()

const uid = Math.random().toString(36).slice(2, 8)
const searchId = `web-find-${uid}`
const listId = `web-found-${uid}`
const keysHintId = `web-keys-${uid}`
const summaryId = `web-summary-${uid}`
const cardNameId = `web-card-name-${uid}`
const listPanelId = `web-list-${uid}`
const listHeadId = `web-list-head-${uid}`

const CHATTER_FACTS = 5
const TIED_TO_MAX = 12
const LATE_THREADS_MS = 90000

const panel = ref(null)
const sky = ref(null)
const canvas = ref(null)
const ambientCanvas = ref(null)
const overlayCanvas = ref(null)
const legendEl = ref(null)
const cardEl = ref(null)
const listEl = ref(null)
const searchEl = ref(null)
const closeEl = ref(null)
const cardNameEl = ref(null)
const listHeadEl = ref(null)
const listToggleEl = ref(null)

const inSheet = inject('parthenonWebSheet', ref(false))

const showChatter = ref(false)
const legendOpen = ref(true)
const isNarrow = ref(false)
const skyWidth = ref(600)
const hoverId = ref(null)
const keyFocusId = ref(null)
const focusId = ref(null)
const grabbing = ref(false)
const query = ref('')
const searchOpen = ref(false)
const activeMatch = ref(0)
const lateThreads = ref(false)
const wasSimulating = ref(false)
const listOpen = ref(false)
const announcement = ref('')
// How much of the sky's foot lies below the fold, behind the Way strip.
const hiddenBelow = ref(0)

// ---------------------------------------------------------------------------
// Faces

const simId = computed(() => props.simulationId || route?.params?.simulationId || '')
const { portraitFor } = useCitizenPortraits(simId)
const portraitOf = (n) => (n && portraitFor(n.name)) || ''

// ---------------------------------------------------------------------------
// The model

const model = computed(() => buildWebModel(props.graphData))
const hasSky = computed(() => model.value.nodes.length > 0)
const legend = computed(() => model.value.legend)
const familyColorVar = (family) => ROLE_COLOR_VAR[family] || ROLE_COLOR_VAR.things

const busy = computed(() => props.currentPhase === 1 || props.isSimulating)

const subline = computed(() => {
  if (props.isSimulating) return t('parthenon.web.moving')
  if (props.currentPhase === 1 && !model.value.nodes.length) return t('parthenon.web.weaving')
  if (lateThreads.value) return t('parthenon.web.lateThreads')
  if (!props.graphData) return ''
  const m = model.value
  if (!m.nodes.length) return t('parthenon.web.empty')
  if (showChatter.value) {
    // The same units as the Hearing's lede and ledger: ties, then threads of chatter.
    const counts = { names: m.nodes.length, ties: m.tieCount, chatter: m.chatterThreads }
    return isNarrow.value ? t('parthenon.web.countShortChatter', counts) : t('parthenon.web.countChatter', counts)
  }
  return t(isNarrow.value ? 'parthenon.web.countShort' : 'parthenon.web.count', { names: m.nodes.length, ties: m.tieCount })
})

const pictureLabel = computed(() => t('parthenon.web.picture', { names: model.value.nodes.length, ties: model.value.tieCount }))

// The keys: the best-tied names, and whoever is chosen.
const keyNodes = computed(() => {
  const nodes = model.value.nodes
  const top = nodes.filter((n) => n.rank < TOP_LABELS).sort((a, b) => a.rank - b.rank)
  if (focusId.value && !top.some((n) => n.id === focusId.value)) {
    const f = nodes.find((n) => n.id === focusId.value)
    if (f) top.push(f)
  }
  return top
})
const keyStyle = (n) => {
  const d = `${Math.round(keyRadius(n) * 2)}px`
  return { width: d, height: d }
}

// The keys are one stop for the keyboard: the chosen name's key (or the one
// last reached, or the best-tied) takes Tab; arrows walk the sky from there.
const lastKeyId = ref(null)
const rovingKeyId = computed(() => {
  const ids = keyNodes.value.map((n) => n.id)
  if (focusId.value && ids.includes(focusId.value)) return focusId.value
  if (lastKeyId.value && ids.includes(lastKeyId.value)) return lastKeyId.value
  return ids[0] || null
})

// The nearest key in the direction pressed; by rank when none lies that way.
const keyToward = (fromId, dir) => {
  const list = keyNodes.value
  const at = list.findIndex((n) => n.id === fromId)
  if (dir === 'first') return list[0]?.id || null
  if (dir === 'last') return list[list.length - 1]?.id || null
  const a = web.byId.get(fromId)
  let best = null
  let bestScore = Infinity
  if (a && Number.isFinite(a.sx)) {
    for (const n of list) {
      if (n.id === fromId) continue
      const b = web.byId.get(n.id)
      if (!b || !Number.isFinite(b.sx)) continue
      const dx = b.sx - a.sx
      const dy = b.sy - a.sy
      const along = dir === 'right' ? dx : dir === 'left' ? -dx : dir === 'down' ? dy : -dy
      const across = dir === 'right' || dir === 'left' ? Math.abs(dy) : Math.abs(dx)
      if (along <= 4) continue
      const score = along + across * 2
      if (score < bestScore) {
        bestScore = score
        best = n.id
      }
    }
  }
  if (best) return best
  const step = dir === 'right' || dir === 'down' ? 1 : -1
  const next = list[(Math.max(0, at) + step + list.length) % list.length]
  return next ? next.id : null
}

const WALK = { ArrowRight: 'right', ArrowLeft: 'left', ArrowDown: 'down', ArrowUp: 'up', Home: 'first', End: 'last' }
const onKeyWalk = (event, id) => {
  const dir = WALK[event.key]
  if (!dir || event.altKey || event.metaKey || event.ctrlKey) return
  event.preventDefault()
  const next = keyToward(id, dir)
  if (!next) return
  lastKeyId.value = next
  nextTick(() => keyEls.get(next)?.focus({ preventScroll: true }))
}

// A name held elsewhere in the act, found in the sky.
const heldId = computed(() => {
  const name = String(props.hold || '').trim()
  if (!name) return null
  return findByName(model.value.nodes, name)?.id || null
})

// The legend lights one kind of name at a time; it is one stop for the
// keyboard, arrows walk the kinds.
const legendOnly = ref(null)
const rovingKind = ref(0)
const kindEls = new Map()
const setKindEl = (i, el) => {
  if (el) kindEls.set(i, el)
  else kindEls.delete(i)
}
const toggleKind = (key) => {
  legendOnly.value = legendOnly.value === key ? null : key
  wake()
}
const onKindWalk = (event, i) => {
  const n = legend.value.length
  if (!n) return
  let next = null
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (i + 1) % n
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (i - 1 + n) % n
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = n - 1
  if (next === null) return
  event.preventDefault()
  rovingKind.value = next
  nextTick(() => kindEls.get(next)?.focus())
}
watch(legend, (list) => {
  if (legendOnly.value !== null && !list.some((e) => e.key === legendOnly.value)) legendOnly.value = null
  if (rovingKind.value >= list.length) rovingKind.value = 0
})

const dossier = computed(() => (focusId.value ? nodeDossier(model.value, focusId.value) : null))
const panelOpen = computed(() => !!dossier.value || (listOpen.value && hasSky.value))
const summaryOpen = ref(false)
const longSummary = computed(() => (dossier.value?.node.summary || '').length > 180)
watch(focusId, () => { summaryOpen.value = false })
const tiedTo = computed(() => {
  if (!dossier.value) return []
  return dossier.value.neighbours.filter((nb) => nb.structural > 0 || showChatter.value).slice(0, TIED_TO_MAX)
})
// Ties are counted as the bar counts them: one for each name tied to, however
// many threads run between the two.
const tieLine = (d) => {
  const n = d.neighbours.filter((nb) => nb.structural > 0 || (showChatter.value && nb.chatter > 0)).length
  return n === 1 ? t('parthenon.web.tieOne') : t('parthenon.web.tiesOf', { n })
}

// The Web in words
const words = computed(() => (listOpen.value ? webInWords(model.value) : []))
const joinNames = (names) => {
  try {
    return new Intl.ListFormat(String(i18n.locale?.value || 'en'), { style: 'long', type: 'conjunction' }).format(names)
  } catch (e) {
    return names.join(', ')
  }
}
const tiesInWords = (n) => {
  const parts = []
  if (n.tied.length) parts.push(t('parthenon.web.listTied', { names: joinNames(n.tied) }))
  if (n.allied.length) parts.push(t('parthenon.web.listAllied', { names: joinNames(n.allied) }))
  if (n.atOdds.length) parts.push(t('parthenon.web.listAtOdds', { names: joinNames(n.atOdds) }))
  return parts.length ? parts.join(' ') : t('parthenon.web.listAlone')
}

// Search
const matches = computed(() => searchNodes(model.value.nodes, query.value, 6))
const showMatches = computed(() => searchOpen.value && query.value.trim().length > 0)
watch(query, () => { activeMatch.value = 0 })

// ---------------------------------------------------------------------------
// Layout of the panel: where the card sits and what it covers

const cardMode = computed(() => (inSheet.value || skyWidth.value < 520 ? 'sheet' : 'rail'))
const railWidth = computed(() => Math.round(Math.max(240, Math.min(320, skyWidth.value * 0.42))))
const cardStyle = computed(() => {
  if (cardMode.value === 'rail') return { width: `${railWidth.value}px`, bottom: `${hiddenBelow.value}px` }
  return { bottom: `${hiddenBelow.value}px` }
})
const legendStyle = computed(() => {
  const style = { bottom: `${12 + hiddenBelow.value}px` }
  if (panelOpen.value && cardMode.value === 'rail') style.maxWidth = `calc(100% - ${railWidth.value + 24}px)`
  return style
})

// ---------------------------------------------------------------------------
// The sky's machinery (not reactive: it runs every frame)

const web = createWeb()
const view = { k: 1, tx: 300, ty: 240, s: 1 }
let target = { k: 1, tx: 300, ty: 240, s: 1 }
let camMode = 'fit' // fit | focus | free
let snapNext = true
let labels = new Map()
let palette = null
let fonts = { display: 'serif', inscription: 'serif' }
const dust = createDust(150)
let ctx = null // the constellation
let actx = null // the far stars and twinkling glows
let octx = null // what passes over the sky
let overlayDrawn = false
let constellationShown = false
let dpr = 1
let width = 600
let height = 480
let skyVisible = false
let pendingRender = false
let legendDecided = false
let lastSignature = ''
let raf = 0
let idleTimer = 0
let lastFrame = 0
let dirty = true
let fitTick = 0
let still = false
let settle = null // a layout being found a slice at a time
let ambientUntil = 0
let faceSet = new Set()
let flashNamed = new Set() // speakers whose names are printed while their beat shows
let returnEl = null
let motionQuery = null
let resizeObserver = null
const keyEls = new Map()

const AMBIENT_MS = 100 // the twinkle alone: about ten frames a second
const AMBIENT_FOR = 20000 // then the sky rests until someone is about again
const OVERLAY_MS = 33 // beats from the square: about thirty frames a second
const SLICE_MS = 8 // the most a frame spends finding places
const ROOMY_LABELS = 48 // the most names a sheet tries to print at once

const setKeyEl = (id, el) => {
  if (el) {
    if (!keyEls.has(id)) dirty = true
    keyEls.set(id, el)
  } else keyEls.delete(id)
}

// Every CSS token is read once from the page; the canvas cannot read them itself.
const readTokens = () => {
  const el = panel.value
  if (!el) return
  const cs = getComputedStyle(el)
  palette = resolvePalette((name) => cs.getPropertyValue(name).trim())
  fonts = {
    display: cs.getPropertyValue('--p-font-display').trim() || 'serif',
    inscription: cs.getPropertyValue('--p-font-inscription').trim() || 'serif'
  }
  measureCache.clear()
}

// Names are measured in the faces they are set in.
const measureCache = new Map()
const measure = (text, voice = 'voice') => {
  const key = `${voice}\u0000${text}`
  const hit = measureCache.get(key)
  if (hit != null) return hit
  const style = labelStyle(voice, fonts)
  let w = text.length * (voice === 'thing' ? 8.4 : 7.2)
  if (ctx) {
    ctx.save()
    ctx.font = style.font
    if ('letterSpacing' in ctx) ctx.letterSpacing = `${style.tracking}px`
    w = ctx.measureText(text).width || w
    ctx.restore()
  }
  measureCache.set(key, w)
  return w
}
const labelSize = (n) => {
  const voice = labelVoice(n)
  return { w: measure(labelText(n), voice), h: labelStyle(voice, fonts).h }
}

// A portrait for each star that has one, loaded once and kept.
const faceImages = new Map()
const imageFor = (n) => {
  const url = portraitOf(n)
  if (!url || typeof Image === 'undefined') return null
  let img = faceImages.get(url)
  if (!img) {
    img = new Image()
    img.decoding = 'async'
    img.onload = () => wake()
    img.src = url
    faceImages.set(url, img)
  }
  return img.complete && img.naturalWidth > 0 ? img : null
}
watch(
  () => model.value.nodes.map((n) => portraitOf(n)).join('|'),
  () => { for (const n of model.value.nodes) imageFor(n) }
)

// ---------------------------------------------------------------------------
// Positions remembered for this viewer across acts and visits

const storageKey = () => {
  const id = props.graphData?.graph_id
  return id ? `parthenon.web.sky.${id}` : ''
}

const loadPositions = () => {
  const key = storageKey()
  if (!key) return null
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch (e) {
    return null
  }
}

const savePositions = () => {
  const key = storageKey()
  if (!key || !web.nodes.length) return
  try {
    const out = {}
    for (const n of web.nodes) out[n.id] = [Math.round(n.x), Math.round(n.y)]
    sessionStorage.setItem(key, JSON.stringify(out))
  } catch (e) {
    /* a per-viewer convenience only */
  }
}

// ---------------------------------------------------------------------------
// Measuring the sky

// The shell's Web pane can run below the fold, and the Way strip covers
// whatever lies there. The picture keeps to the part that can be seen. In the
// phone sheet, which floats above the strip, nothing is hidden.
const inFixedLayer = (el) => {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    if (getComputedStyle(n).position === 'fixed') return true
  }
  return false
}

const measureFold = (rect) => {
  if (typeof window === 'undefined' || !panel.value) return 0
  const wayH = parseFloat(getComputedStyle(panel.value).getPropertyValue('--p-way-h')) || 0
  const floor = inFixedLayer(panel.value) ? window.innerHeight : window.innerHeight - wayH
  const hidden = Math.max(0, Math.round(rect.bottom - floor))
  return Math.min(hidden, Math.round(rect.height / 2))
}

const measureSky = () => {
  const el = sky.value
  const cv = canvas.value
  if (!el || !cv) return
  const rect = el.getBoundingClientRect()
  skyVisible = rect.width > 0 && rect.height > 0
  if (!skyVisible) return
  width = Math.max(200, Math.round(rect.width))
  height = Math.max(200, Math.round(rect.height))
  skyWidth.value = width
  isNarrow.value = width < 560
  hiddenBelow.value = measureFold(rect)
  if (!legendDecided) {
    legendDecided = true
    legendOpen.value = !isNarrow.value && !inSheet.value && height - hiddenBelow.value >= 600
  }
  dpr = Math.min(2, window.devicePixelRatio || 1)
  const pw = Math.round(width * dpr)
  const ph = Math.round(height * dpr)
  if (cv.width !== pw || cv.height !== ph) {
    cv.width = pw
    cv.height = ph
    dirty = true
  }
  for (const layerEl of [ambientCanvas.value, overlayCanvas.value]) {
    if (layerEl && (layerEl.width !== pw || layerEl.height !== ph)) {
      layerEl.width = pw
      layerEl.height = ph
      dirty = true
      overlayDrawn = true
    }
  }
  web.width = width
  web.height = height
}

// A phone's sheet (or a narrow column) has room to spare: the constellation is
// drawn out to its height, and every name that fits is printed.
const roomy = () => inSheet.value || isNarrow.value
const fitStretch = () => (roomy() ? 1.8 : 1.25)

// The part of the sky the constellation may fill: clear of the bar's edge, the
// legend, the card and the fold.
const frameBox = ({ bare = false } = {}) => {
  const box = { x0: 18, y0: 14, x1: width - 18, y1: height - 14 - hiddenBelow.value }
  const open = bare && camMode !== 'fit' ? false : panelOpen.value
  if (open && cardMode.value === 'rail') box.x1 = width - railWidth.value - 18
  if (open && cardMode.value === 'sheet') {
    const el = cardEl.value || listEl.value
    const h = el ? el.offsetHeight : Math.round(height * 0.5)
    box.y1 = Math.max(box.y0 + 120, height - hiddenBelow.value - h - 10)
  } else if (legendEl.value && legendOpen.value && !isNarrow.value) {
    box.y1 -= legendEl.value.offsetHeight + 8
  } else if (legendEl.value) {
    box.y1 -= 44
  }
  return box
}

// Names printed at scale k (and stretch s) around the origin, for the fit to
// count them: the best-tied and the forced, or only the forced.
const labelsForFit = (nodes, k, s, forced, onlyForced = false) => {
  const items = []
  const stars = nodes.map((n) => ({ id: n.id, x: n.x * k, y: n.y * k * s, r: n.r }))
  const byId = new Map(stars.map((st) => [st.id, st]))
  const ties = drawnTies()
  const sorted = [...nodes].sort((a, b) => Number(!!forced?.has(b.id)) - Number(!!forced?.has(a.id)) || a.rank - b.rank)
  for (const n of sorted) {
    const isForced = !!forced?.has(n.id)
    if (!isForced && (onlyForced || n.rank >= fitLabels())) continue
    const st = byId.get(n.id)
    const size = labelSize(n)
    const r = isForced ? clearance(n, { face: !!imageFor(n), chosen: true }) : n.r
    items.push({ id: n.id, x: st.x, y: st.y, r, w: size.w, h: size.h, forced: isForced, threads: threadsOf(n.id, byId, ties) })
  }
  const placed = placeLabels(items, stars)
  const rel = new Map()
  for (const [id, r] of placed) {
    const st = byId.get(id)
    rel.set(id, { x0: r.x0 - st.x, x1: r.x1 - st.x, y0: r.y0 - st.y, y1: r.y1 - st.y })
  }
  return rel
}

// How many names the whole view makes room for: all the best-tied on a wide
// sky, the first few on a phone (the rest are printed wherever they fit).
const fitLabels = () => (width < 480 ? 7 : TOP_LABELS)

let wholeK = 0 // the scale at which the whole Web fits, for focus to lean in from
let wholeS = 1

const fitWhole = () => {
  const v = fitView(web.nodes, frameBox({ bare: true }), {
    minK: 0.18,
    maxK: 2.4,
    stretch: fitStretch(),
    labelsAt: (k, s) => labelsForFit(web.nodes, k, s, null)
  })
  wholeK = v.k
  wholeS = v.s
  return v
}

const computeTarget = () => {
  if (camMode === 'focus' && focusId.value && web.byId.has(focusId.value)) {
    // Focus leans in from the whole view (never far), frames the chosen star's
    // neighbourhood where it can, and always keeps the star and its name in sight.
    const box = frameBox()
    if (!wholeK) fitWhole()
    const chosen = web.byId.get(focusId.value)
    const near = neighbourhood(web, focusId.value)
    const nodes = web.nodes.filter((n) => near.has(n.id))
    const only = new Set([chosen.id])
    // Above a sheet the strip of sky is short: the view may pull back further
    // and draw the stretch in, so the ties for and against stay in sight.
    const v = focusView(nodes, box, {
      wholeK,
      wholeS,
      sheet: cardMode.value === 'sheet',
      labelsAt: (k, s) => labelsForFit(nodes, k, s, only, true)
    })
    const [sx, sy] = toScreen(v, chosen.x, chosen.y)
    const reach = clearance(chosen, { face: !!imageFor(chosen), chosen: true }) + 4
    const nameRight = reach + LABEL_GAP + labelSize(chosen).w
    if (sx + nameRight > box.x1) v.tx -= sx + nameRight - box.x1
    if (sx - reach < box.x0) v.tx += box.x0 - (sx - reach)
    if (sy + reach + 10 > box.y1) v.ty -= sy + reach + 10 - box.y1
    if (sy - reach - 10 < box.y0) v.ty += box.y0 - (sy - reach - 10)
    return v
  }
  return fitWhole()
}

const retarget = ({ snap = false } = {}) => {
  if (!web.nodes.length || camMode === 'free') return
  target = computeTarget()
  web.scaleHint = wholeK || target.k
  if (snap) snapNext = true
  wake()
}

// ---------------------------------------------------------------------------
// Names and faces on screen

const centerId = () => hoverId.value || keyFocusId.value || focusId.value || heldId.value

// Each star's drawn ties, indexed once per pass over the names.
const drawnTies = () => {
  const out = new Map()
  const add = (id, l) => {
    const list = out.get(id)
    if (list) list.push(l)
    else out.set(id, [l])
  }
  for (const l of web.links) {
    if (!l.structural && !showChatter.value) continue
    add(l.source, l)
    add(l.target, l)
  }
  return out
}

// A star's own drawn ties as segments, so its name is not laid across them.
const threadsOf = (id, starOf, ties) => {
  const out = []
  for (const l of (ties ? ties.get(id) : null) || []) {
    const a = starOf.get(l.source)
    const b = starOf.get(l.target)
    if (a && b) out.push(l.source === id ? [a.x, a.y, b.x, b.y] : [b.x, b.y, a.x, a.y])
  }
  return out
}

// Whose faces show: whoever is pointed at, keyed or chosen, and the best-tied
// once the visitor leans in close.
const facesWanted = () => {
  const out = new Set()
  const want = (id) => {
    const n = id && web.byId.get(id)
    if (n && imageFor(n)) out.add(id)
  }
  want(hoverId.value)
  want(keyFocusId.value)
  want(focusId.value)
  want(heldId.value)
  if (wholeK && view.k > wholeK * 1.4) {
    let shown = 0
    const ranked = [...web.nodes].sort((a, b) => a.rank - b.rank)
    for (const n of ranked) {
      if (shown >= 12) break
      if (!Number.isFinite(n.sx) || n.sx < 0 || n.sx > width || n.sy < 0 || n.sy > height) continue
      if (imageFor(n)) {
        out.add(n.id)
        shown++
      }
    }
  }
  faceSet = out
  return out
}

const clearanceOf = (n) =>
  clearance(n, {
    face: (n.face || 0) > 0.01 || faceSet.has(n.id),
    key: n.id === keyFocusId.value,
    chosen: n.id === focusId.value
  })

const computeLabels = () => {
  const center = centerId()
  const near = center ? neighbourhood(web, center) : null
  const items = []
  const seen = new Set()
  const stars = web.nodes.map((n) => ({ id: n.id, x: n.sx, y: n.sy, r: (n.face || 0) > 0.01 || faceSet.has(n.id) ? clearance(n, { face: true }) - 2 : n.r }))
  const starOf = new Map(stars.map((st) => [st.id, st]))
  const ties = drawnTies()
  const push = (n, forced) => {
    if (!n || seen.has(n.id)) return
    seen.add(n.id)
    const st = starOf.get(n.id)
    if (!st || !Number.isFinite(st.x)) return
    // A star beyond the edge of the sky keeps its name to itself.
    if (st.x < -n.r || st.x > width + n.r || st.y < -n.r || st.y > height + n.r) return
    const size = labelSize(n)
    items.push({ id: n.id, x: st.x, y: st.y, r: clearanceOf(n), w: size.w, h: size.h, forced, threads: threadsOf(n.id, starOf, ties) })
  }
  push(web.byId.get(focusId.value), true)
  push(web.byId.get(center), true)
  push(web.byId.get(heldId.value), true)
  // Whoever speaks in the square is named while their star blooms.
  flashNamed = new Set()
  for (const f of web.flashes || []) {
    if (!f?.from) continue
    flashNamed.add(f.from)
    push(web.byId.get(f.from), true)
  }
  if (near) {
    for (const n of web.nodes.filter((m) => near.has(m.id)).sort((a, b) => a.rank - b.rank)) push(n, false)
  }
  const ranked = [...web.nodes].sort((a, b) => a.rank - b.rank)
  for (const n of ranked) if (n.top) push(n, false)
  // With room to spare (a sheet, a narrow column, or a tall sky), every name
  // that fits, up to a sky's worth of them; a name that would collide is left out.
  if (roomy() || height - hiddenBelow.value >= 560) {
    for (const n of ranked) {
      if (items.length >= ROOMY_LABELS) break
      push(n, false)
    }
  }
  const bounds = { x0: 4, y0: 4, x1: width - 4, y1: height - 4 - hiddenBelow.value }
  if (panelOpen.value && cardMode.value === 'rail') bounds.x1 = width - railWidth.value - 4
  labels = placeLabels(items, stars, { prev: labels, bounds, blocks: legendBlock() })
}

// Names keep out from under the legend in the corner and an open sheet.
const legendBlock = () => {
  const box = sky.value
  if (!box) return []
  const b = box.getBoundingClientRect()
  const out = []
  for (const el of [legendEl.value, cardMode.value === 'sheet' ? cardEl.value || listEl.value : null]) {
    if (!el || !el.offsetParent) continue
    const a = el.getBoundingClientRect()
    out.push({ x0: a.left - b.left - 4, x1: a.right - b.left + 4, y0: a.top - b.top - 4, y1: a.bottom - b.top + 4 })
  }
  return out
}

// ---------------------------------------------------------------------------
// The frame loop. Anything that changes the picture marks it dirty and the
// constellation is painted again; the twinkle alone only lays the painted
// constellation over the far stars, ten times a second, for a while after the
// last sign of someone about. Under reduced motion only change is drawn.

const canRun = () => !!ctx && skyVisible && !(typeof document !== 'undefined' && document.hidden)

const schedule = (delay = 0) => {
  if (raf) return
  if (delay > 0) {
    if (idleTimer) return
    idleTimer = setTimeout(() => {
      idleTimer = 0
      if (!raf && canRun()) raf = requestAnimationFrame(frame)
    }, delay)
    return
  }
  if (idleTimer) {
    clearTimeout(idleTimer)
    idleTimer = 0
  }
  raf = requestAnimationFrame(frame)
}

// Someone is about: the twinkle runs for a while longer.
const stir = () => {
  const now = performance.now()
  const resting = now >= ambientUntil
  ambientUntil = now + AMBIENT_FOR
  if (resting && !still && canRun()) schedule(AMBIENT_MS)
}

// Something changed: the constellation is painted again.
const wake = () => {
  dirty = true
  stir()
  if (canRun()) schedule()
}

// Only what passes over the sky moves (a beat from the square).
const nudge = () => {
  stir()
  if (canRun()) schedule()
}

const stop = () => {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
  if (idleTimer) clearTimeout(idleTimer)
  idleTimer = 0
  lastFrame = 0
}

const paintConstellation = (now) => {
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  constellationShown = true
  drawConstellation(ctx, web, {
    width,
    height,
    palette,
    now,
    still,
    chatter: showChatter.value,
    labels,
    center: centerId(),
    focus: focusId.value,
    faceOf: imageFor,
    fonts
  })
}

// The layers beneath and above the constellation. Each is its own canvas, so
// the constellation is never copied: the page lays them one over another.
const compose = (now, { hide = false } = {}) => {
  const time = still ? 0 : now
  if (actx) {
    actx.setTransform(dpr, 0, 0, dpr, 0, 0)
    drawAmbient(actx, web, { width, height, palette, time, still, dust, hide })
  }
  if (hide && constellationShown && ctx) {
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, canvas.value.width, canvas.value.height)
    constellationShown = false
  }
  // The overlay is drawn only while something passes over; else cleared once.
  if (!octx) return
  const passing = !hide && ((!!focusId.value && !still) || (web.flashes && web.flashes.length > 0) || (!still && web.nodes.some((n) => n.bornAt != null)))
  if (!passing && !overlayDrawn) return
  octx.setTransform(dpr, 0, 0, dpr, 0, 0)
  octx.clearRect(0, 0, width, height)
  if (passing) drawOverlay(octx, web, { palette, time, now, still, focus: focusId.value })
  overlayDrawn = passing
}

const frame = () => {
  raf = 0
  if (!ctx || !palette || !skyVisible) return
  const now = performance.now()
  const dt = lastFrame ? Math.min(64, now - lastFrame) : 16
  lastFrame = now

  if (settle) {
    runSettle(now)
    if (settle) {
      // Still finding their places: the far stars show, and any picture
      // already painted stays as it was.
      compose(now, { hide: settle.hide })
      schedule()
      return
    }
  }

  let moving = false
  if (web.alpha > 0) {
    stepWeb(web)
    moving = true
    fitTick++
    if (camMode !== 'free' && (fitTick % 5 === 0 || web.alpha === 0)) {
      target = computeTarget()
      web.scaleHint = wholeK || target.k
    }
    if (web.alpha === 0) savePositions()
  }
  if (updateEmphasis(web, centerId(), dt, still, { only: legendOnly.value })) moving = true
  if (updateFaces(web, facesWanted(), dt, still)) moving = true
  if (easeView(view, target, dt, still || snapNext)) moving = true
  snapNext = false
  if (tidyArrivals(web, now)) moving = true

  if (moving || dirty) {
    placeStars(web, view, now, still)
    computeLabels()
    paintConstellation(now)
    placeKeys()
    // A moving frame is followed by one more, so what came to rest is drawn at rest.
    dirty = moving
  }
  const flashing = tidyFlashes(web, now)
  // A beat that has passed takes its speaker's name with it.
  if (flashNamed.size && [...flashNamed].some((id) => !(web.flashes || []).some((f) => f.from === id))) dirty = true
  compose(now)

  if (moving || dirty) schedule()
  else if (flashing) schedule(still ? Math.min(flashLeft(web, now) + 16, 1200) : OVERLAY_MS)
  else if (!still && now < ambientUntil) schedule(AMBIENT_MS)
}

// The keys follow their stars, kept inside the sky so focus never scrolls it.
const placeKeys = () => {
  for (const [id, el] of keyEls) {
    const n = web.byId.get(id)
    if (!n || !Number.isFinite(n.sx)) continue
    const half = keyRadius(n)
    const x = Math.max(half, Math.min(width - half, n.sx))
    const y = Math.max(half, Math.min(height - half, n.sy))
    el.style.transform = `translate(${(x - half).toFixed(1)}px, ${(y - half).toFixed(1)}px)`
  }
}

// ---------------------------------------------------------------------------
// Finding places a slice at a time, so a large sky never holds up the page.
// A first sky stays dark (the far stars only) until its stars have their
// places; under reduced motion a growing sky keeps its old picture until the
// new one is ready, then changes once.

const beginSettle = ({ first = false, full = false } = {}) => {
  const cap = settleCap(web.nodes.length)
  settle = full
    ? { first, full, stage: 1, left: Math.round(cap * 0.4), second: Math.round(cap * 0.6), hide: first, startedAt: performance.now() }
    : { first, full, stage: 2, left: cap, second: 0, hide: first, startedAt: performance.now() }
  wake()
}

const finishSettle = (now) => {
  const s = settle
  settle = null
  // After a first settle a small sky keeps a breath of life; a large one, or
  // any under reduced motion (or when the steps ran out), stops where it is.
  if (s.full) web.alpha = still || web.nodes.length > INTRO_MAX ? 0 : 0.03
  else if (still) web.alpha = 0
  if (web.alpha === 0) for (const n of web.nodes) n.mobility = 1
  if (s.first) {
    // The stars light up in turn from the moment the sky is ready.
    const shift = now - s.startedAt
    for (const n of web.nodes) if (n.introAt != null) n.introAt += shift
  }
  if (web.alpha === 0) savePositions()
  retarget({ snap: s.first || still })
  dirty = true
}

const runSettle = (now) => {
  const t0 = performance.now()
  while (settle && performance.now() - t0 < SLICE_MS) {
    if (web.alpha > 0 && settle.left > 0) {
      stepWeb(web)
      settle.left--
      continue
    }
    if (settle.stage === 1) {
      // Plan for the scale the sky will have, and settle again.
      web.scaleHint = computeTarget().k
      web.alpha = Math.max(web.alpha, 0.3)
      settle.stage = 2
      settle.left = settle.second
      continue
    }
    finishSettle(now)
  }
}

// ---------------------------------------------------------------------------
// A new reading of the Web

const render = () => {
  if (!props.graphData || !ctx) return
  measureSky()
  if (!skyVisible) {
    pendingRender = true
    return
  }
  const m = model.value
  if (m.signature === lastSignature) return
  lastSignature = m.signature
  if (!palette) readTokens()
  const first = !web.synced
  const stored = first ? loadPositions() : null
  syncWeb(web, m, { now: performance.now(), stored, intro: first && !still })
  if (focusId.value && !web.byId.has(focusId.value)) focusId.value = null
  for (const n of m.nodes) imageFor(n)

  if (first && web.alpha >= 0.5) beginSettle({ first: true, full: true })
  else if (still && web.alpha > 0) beginSettle({ first })
  else if (web.alpha === 0) savePositions()
  retarget({ snap: first })
  if (first) snapNext = true
  wake()
}

const resetSky = () => {
  lastSignature = ''
  pendingRender = false
  settle = null
  focusId.value = null
  hoverId.value = null
  web.nodes = []
  web.links = []
  web.byId = new Map()
  web.adjacency = new Map()
  web.flashes = []
  web.synced = false
  web.alpha = 0
  labels = new Map()
  camMode = 'fit'
  wake()
}

// ---------------------------------------------------------------------------
// Choosing a name

const announce = (id) => {
  const d = nodeDossier(model.value, id)
  if (!d) return
  announcement.value = ''
  nextTick(() => {
    announcement.value = t('parthenon.web.announce', { name: d.node.name, ties: tieLine(d) })
  })
}

const focusNode = async (id) => {
  if (!web.byId.has(id)) return false
  focusId.value = id
  hoverId.value = null
  camMode = 'focus'
  await nextTick()
  retarget()
  return true
}

// A choice made from a key, the finder, the list or a tie takes the keyboard
// to the card's name; a star touched in the sky leaves it where it was.
const choose = async (id, { from = null, moveFocus = false } = {}) => {
  if (from) returnEl = from
  const ok = await focusNode(id)
  if (!ok) return
  announce(id)
  if (moveFocus) cardNameEl.value?.focus({ preventScroll: true })
}

const clearFocus = () => {
  if (!focusId.value) return
  focusId.value = null
  if (camMode === 'focus') camMode = 'fit'
  nextTick(() => retarget())
  wake()
}

const toggleFocus = (id) => {
  if (focusId.value === id) clearFocus()
  else {
    returnEl = null
    focusNode(id).then((ok) => ok && announce(id))
  }
}

const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0

// Letting a card go returns the keyboard to where the choice was made.
const closeCard = () => {
  const id = focusId.value
  const active = typeof document !== 'undefined' ? document.activeElement : null
  const within = !active || active === document.body || !!cardEl.value?.contains(active)
  clearFocus()
  if (!within) return
  nextTick(() => {
    const back = [returnEl, id && keyEls.get(id), listOpen.value ? listToggleEl.value : null, searchEl.value].find(visible)
    back?.focus({ preventScroll: true })
    returnEl = null
  })
}

const onKeyChoose = (id, event) => {
  if (focusId.value === id) closeCard()
  else choose(id, { from: event.currentTarget, moveFocus: true })
}

// Fit shows the whole Web again; whoever is chosen stays chosen.
const fitAll = () => {
  camMode = 'fit'
  retarget()
}

const onKeyFocus = (id) => {
  keyFocusId.value = id
  lastKeyId.value = id
  wake()
}

const onKeyBlur = (id) => {
  if (keyFocusId.value === id) keyFocusId.value = null
  wake()
}

const openList = async () => {
  // The list shows at once: a card held open lets go first.
  if (focusId.value) clearFocus()
  listOpen.value = true
  await nextTick()
  listHeadEl.value?.focus({ preventScroll: true })
  retarget()
}

const closeList = () => {
  listOpen.value = false
  nextTick(() => {
    listToggleEl.value?.focus({ preventScroll: true })
    retarget()
  })
}

const toggleList = () => (listOpen.value ? closeList() : openList())

const onEscape = (event) => {
  if (event.target === searchEl.value && query.value) {
    event.stopPropagation()
    query.value = ''
    return
  }
  if (focusId.value) {
    event.stopPropagation()
    closeCard()
    return
  }
  if (listOpen.value) {
    event.stopPropagation()
    closeList()
  }
}

const chooseMatch = (m) => {
  if (!m) return
  query.value = ''
  choose(m.id, { from: searchEl.value, moveFocus: true })
}

const onSearchKey = (event) => {
  const n = matches.value.length
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (n) activeMatch.value = (activeMatch.value + 1) % n
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (n) activeMatch.value = (activeMatch.value - 1 + n) % n
  } else if (event.key === 'Enter') {
    event.preventDefault()
    chooseMatch(matches.value[activeMatch.value])
  }
}

// ---------------------------------------------------------------------------
// A beat in the square, seen in the sky

const onPulse = (beat) => {
  if (!beat || !beat.from || !web.nodes.length) return
  const from = findByName(web.nodes, beat.from)
  if (!from) return
  const to = beat.to ? findByName(web.nodes, beat.to) : null
  if (!flashBeat(web, from.id, to ? to.id : null, performance.now())) return
  // A speaker whose name is not yet printed is named for the length of the beat.
  if (labels.has(from.id)) nudge()
  else wake()
}
watch(() => props.pulse, onPulse)
defineExpose({ pulse: onPulse })

// ---------------------------------------------------------------------------
// Pointer: hover lights a neighbourhood, a tap chooses, a drag pans or moves a
// star, a wheel or a pinch zooms.

const pointers = new Map()
let gesture = null

const localPoint = (event) => {
  const rect = canvas.value.getBoundingClientRect()
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

const zoomAround = (p, k) => {
  const nk = Math.max(0.15, Math.min(5, k))
  const [wx, wy] = toWorld(view, p.x, p.y)
  view.k = nk
  view.tx = p.x - wx * nk
  view.ty = p.y - wy * nk * (view.s || 1)
  target = { ...view }
  camMode = 'free'
  wake()
}

const setHover = (id) => {
  if (hoverId.value === id) return
  hoverId.value = id
  wake()
}

const onPointerDown = (event) => {
  if (event.button != null && event.button > 0) return
  const p = localPoint(event)
  try { canvas.value.setPointerCapture(event.pointerId) } catch (e) { /* not every pointer can be captured */ }
  pointers.set(event.pointerId, p)
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()]
    gesture = { kind: 'pinch', d0: Math.hypot(a.x - b.x, a.y - b.y) || 1, k0: view.k }
    return
  }
  const hit = nodeAt(web.nodes, view, p.x, p.y, event.pointerType === 'mouse' ? 6 : 14)
  gesture = { kind: 'press', id: hit ? hit.id : null, x0: p.x, y0: p.y, tx0: view.tx, ty0: view.ty, moved: false }
}

const onPointerMove = (event) => {
  const p = localPoint(event)
  if (pointers.has(event.pointerId)) pointers.set(event.pointerId, p)
  if (!gesture) {
    if (event.pointerType === 'mouse') {
      const hit = nodeAt(web.nodes, view, p.x, p.y, 6)
      setHover(hit ? hit.id : null)
    }
    return
  }
  if (gesture.kind === 'pinch') {
    if (pointers.size < 2) return
    const [a, b] = [...pointers.values()]
    const d = Math.hypot(a.x - b.x, a.y - b.y) || 1
    zoomAround({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, gesture.k0 * (d / gesture.d0))
    return
  }
  if (!gesture.moved && Math.hypot(p.x - gesture.x0, p.y - gesture.y0) > 5) {
    gesture.moved = true
    grabbing.value = true
    if (gesture.id) {
      web.alphaTarget = 0.06
      web.alpha = Math.max(web.alpha, 0.12)
    }
  }
  if (!gesture.moved) return
  if (gesture.id) {
    const n = web.byId.get(gesture.id)
    if (n) {
      const [wx, wy] = toWorld(view, p.x, p.y)
      n.fx = wx
      n.fy = wy
      if (still) {
        n.x = wx
        n.y = wy
      }
    }
    if (camMode === 'fit') camMode = 'free'
  } else {
    view.tx = gesture.tx0 + (p.x - gesture.x0)
    view.ty = gesture.ty0 + (p.y - gesture.y0)
    target = { ...view }
    camMode = 'free'
  }
  wake()
}

const endGesture = (event, tap) => {
  pointers.delete(event.pointerId)
  if (!gesture) return
  if (gesture.kind === 'press') {
    if (!gesture.moved && tap) {
      if (gesture.id) toggleFocus(gesture.id)
      else clearFocus()
    } else if (gesture.id) {
      const n = web.byId.get(gesture.id)
      if (n) {
        n.fx = null
        n.fy = null
      }
      web.alphaTarget = 0
      if (still && web.alpha > 0) beginSettle()
      savePositions()
    }
    gesture = null
  } else if (pointers.size < 2) {
    gesture = null
  }
  grabbing.value = false
  wake()
}

const onPointerUp = (event) => endGesture(event, true)
const onPointerCancel = (event) => endGesture(event, false)
const onPointerLeave = (event) => {
  if (event.pointerType === 'mouse' && !gesture) setHover(null)
}

const onWheel = (event) => {
  if (!hasSky.value) return
  event.preventDefault()
  const p = localPoint(event)
  const unit = event.deltaMode === 1 ? 0.05 : 0.0018
  zoomAround(p, view.k * Math.exp(-event.deltaY * unit))
}

// ---------------------------------------------------------------------------
// Late threads and refresh

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

// ---------------------------------------------------------------------------
// Wiring

watch(
  () => props.graphData,
  (data) => {
    if (!data) {
      clearLateThreads()
      resetSky()
      return
    }
    nextTick(render)
  }
)

// A name held elsewhere lights its star (and its ties and face) at once.
watch(heldId, () => wake())

watch(showChatter, (on) => {
  setChatterVisible(web, on)
  if (camMode === 'focus') nextTick(() => retarget())
  wake()
})

watch(legendOpen, () => nextTick(() => retarget()))

watch(isNarrow, (narrow) => {
  if (narrow) legendOpen.value = false
})

// The card changes the room the sky has; its size is measured once it is drawn.
watch(cardMode, () => nextTick(() => retarget()))

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

let scrollFrame = 0
const onScroll = () => {
  if (scrollFrame) return
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0
    const before = hiddenBelow.value
    measureSky()
    if (Math.abs(hiddenBelow.value - before) >= 6) retarget()
  })
}

// A star chosen with the pointer leaves the keyboard on the page (or on the
// phone's sheet around the panel); Escape still lets the card go first, before
// anything around it closes. Heard in the capture phase for that reason.
const onWindowKey = (event) => {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  if (!focusId.value && !listOpen.value) return
  const active = document.activeElement
  if (panel.value?.contains(active)) return // the panel's own handler has it
  const around = !active || active === document.body || (!!panel.value && active.contains(panel.value))
  if (!around) return
  event.stopPropagation()
  if (focusId.value) clearFocus()
  else closeList()
}

const onVisibility = () => {
  if (document.hidden) stop()
  else wake()
}

const onMotion = (e) => {
  still = e.matches
  if (still && web.alpha > 0) beginSettle()
  snapNext = true
  wake()
}

// The display and inscription faces, loaded before names are measured.
const loadType = () => {
  if (!document.fonts?.load) return
  Promise.all([
    document.fonts.load(`600 ${LABEL_PX}px ${fonts.display}`),
    document.fonts.load(`600 ${THING_PX}px ${fonts.inscription}`)
  ])
    .then(() => {
      measureCache.clear()
      labels = new Map()
      retarget()
      wake()
    })
    .catch(() => {})
}

onMounted(() => {
  ctx = canvas.value.getContext('2d')
  actx = ambientCanvas.value?.getContext('2d') || null
  octx = overlayCanvas.value?.getContext('2d') || null
  motionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null
  still = !!motionQuery?.matches
  motionQuery?.addEventListener?.('change', onMotion)
  readTokens()
  measureSky()

  resizeObserver = new ResizeObserver(() => {
    const before = `${width}x${height}/${hiddenBelow.value}/${skyVisible}`
    const wasVisible = skyVisible
    measureSky()
    if (!skyVisible) {
      stop()
      return
    }
    if (!wasVisible) {
      snapNext = true
      if (pendingRender) {
        pendingRender = false
        render()
        return
      }
    }
    if (before !== `${width}x${height}/${hiddenBelow.value}/${skyVisible}`) retarget({ snap: !wasVisible })
    wake()
  })
  resizeObserver.observe(sky.value)
  canvas.value.addEventListener('wheel', onWheel, { passive: false })
  window.addEventListener('scroll', onScroll, { passive: true })
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('keydown', onWindowKey, true)

  if (props.graphData) nextTick(render)
  loadType()
  // Names measured before every face arrived are measured again once they have.
  if (document.fonts?.ready) {
    document.fonts.ready
      .then(() => {
        measureCache.clear()
        labels = new Map()
        retarget()
        wake()
      })
      .catch(() => {})
  }
})

onBeforeUnmount(() => {
  savePositions()
  clearLateThreads()
  stop()
  window.removeEventListener('scroll', onScroll)
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('keydown', onWindowKey, true)
  motionQuery?.removeEventListener?.('change', onMotion)
  canvas.value?.removeEventListener('wheel', onWheel)
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  if (resizeObserver) resizeObserver.disconnect()
  for (const img of faceImages.values()) img.onload = null
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
  /* The night sky: a deep blue well over the surface, darker at the rim. */
  background:
    radial-gradient(ellipse 80% 60% at 55% 42%, rgba(143, 184, 216, 0.07), transparent 70%),
    radial-gradient(ellipse 60% 45% at 30% 75%, rgba(240, 182, 96, 0.035), transparent 70%),
    linear-gradient(180deg, #0d1219 0%, var(--p-surface) 55%, #0c1016 100%);
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
  overflow: hidden;
}

.graph-panel::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 50% 45%, transparent 50%, rgba(0, 0, 0, 0.45) 100%);
  pointer-events: none;
  z-index: 0;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* The bar */
.panel-top {
  position: relative;
  z-index: 6;
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

/* The status line may take two lines rather than lose its end. */
.panel-sub {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 2px 8px;
  font-size: var(--t-xs);
  line-height: 1.4;
  color: var(--p-ink-3);
  min-width: 0;
}

.panel-sub .ember {
  margin-top: 0.3em;
}

.panel-sub-text {
  flex: 1 1 10em;
  min-width: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.panel-tools {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.tool {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 40px;
  min-height: 40px;
  padding: 0 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--p-radius);
  color: var(--p-ink-2);
  font: inherit;
  font-size: var(--t-xs);
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease;
}

.tool:hover {
  color: var(--p-gold);
}

.tool.on {
  color: var(--p-gold);
  border-color: color-mix(in srgb, var(--p-gold) 45%, transparent);
}

/* Finding a name */
.finder {
  position: relative;
  width: 176px;
}

.finder-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--p-ink-3);
  pointer-events: none;
}

/* 16px, so a phone does not zoom the page when the field is touched. */
.finder-input {
  width: 100%;
  height: 40px;
  padding: 0 10px 0 32px;
  background: rgba(11, 14, 19, 0.6);
  border: 1px solid var(--p-control-border);
  border-radius: var(--p-radius);
  color: var(--p-ink);
  font: inherit;
  font-size: var(--t-md);
}

.finder-input::placeholder {
  color: var(--p-ink-3);
}

.finder-input:focus {
  outline: none;
  border-color: var(--p-gold);
}

.finder-input:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 2px;
}

.finder-input::-webkit-search-cancel-button {
  filter: invert(0.8);
}

.finder-list {
  position: absolute;
  z-index: 20;
  top: calc(100% + 4px);
  left: 0;
  width: max(100%, 260px);
  max-width: calc(100vw - 32px);
  margin: 0;
  padding: 4px 0;
  list-style: none;
  background: rgba(17, 21, 28, 0.97);
  border: 1px solid var(--p-line-strong);
  box-shadow: var(--p-shadow-2);
}

.finder-option {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 6px 12px;
  cursor: pointer;
}

.finder-option.active {
  background: var(--p-surface-3);
}

.opt-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.opt-name {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  line-height: 1.2;
  color: var(--p-ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.opt-role {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

.finder-none {
  padding: 10px 12px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

/* One quiet verb, present only while the last threads are being tied. */
.look-again {
  flex-shrink: 0;
  min-height: 40px;
  margin: -12px -4px;
  padding: 0 4px;
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
  box-shadow: 0 0 12px 2px rgba(242, 237, 228, 0.12);
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
  overflow: hidden;
}

.sky-canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  touch-action: none;
  cursor: grab;
}

.sky-canvas.pointing {
  cursor: pointer;
}

.sky-canvas.grabbing {
  cursor: grabbing;
}

.sky-canvas.hidden {
  visibility: hidden;
}

/* The far stars below and what passes over above: seen, never touched. */
.sky-layer {
  pointer-events: none;
}

/* Reading the Web as a list: unseen until the keyboard reaches it. */
.list-toggle {
  position: absolute;
  z-index: 10;
  left: 12px;
  top: 8px;
  min-height: 40px;
  padding: 0 14px;
  background: var(--p-surface-2);
  border: 1px solid var(--p-gold);
  border-radius: var(--p-radius);
  color: var(--p-ink);
  font: inherit;
  font-size: var(--t-xs);
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  clip-path: inset(50%);
  width: 1px;
  height: 1px;
  overflow: hidden;
}

.list-toggle:focus {
  clip-path: none;
  width: auto;
  min-width: 44px;
  height: auto;
  overflow: visible;
}

.star-keys {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

/* A key is invisible until the keyboard reaches it; then a gold ring shows
   which star it stands for, just outside the face it opens. */
.star-key {
  position: absolute;
  left: 0;
  top: 0;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 0;
  border-radius: var(--p-radius-coin);
  background: transparent;
  pointer-events: none;
  will-change: transform;
}

.star-key:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 0;
  box-shadow: 0 0 0 4px rgba(11, 14, 19, 0.55);
}

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

/* The legend */
.legend {
  position: absolute;
  z-index: 4;
  left: 12px;
  bottom: 12px;
  max-width: calc(100% - 24px);
  background: rgba(13, 17, 23, 0.86);
  border: 1px solid var(--p-line);
  backdrop-filter: blur(6px);
}

.legend-head {
  width: 100%;
  min-height: 40px;
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
  padding: 0 8px 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 0 4px;
  max-width: 380px;
}

/* A toggle is a target: 40px tall on every screen, as a thumb needs. */
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 40px;
  padding: 2px 8px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--p-radius);
  font: inherit;
  font-size: var(--t-xs);
  color: var(--p-ink-2);
  white-space: nowrap;
  cursor: pointer;
  transition: opacity 0.2s ease, border-color 0.2s ease;
}

.legend-item:hover,
.legend-item.on {
  border-color: var(--p-line-strong);
}

.legend-item.on {
  color: var(--p-ink);
}

.legend-item.dim {
  opacity: 0.5;
}

.legend-item:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 1px;
}

/* How the threads read: a tie, allied, at odds, and the chatter's stitches */
.legend-threads {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 0;
  padding: 6px 14px 10px;
  border-top: 1px solid var(--p-line);
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

.thread-sample {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.thread-sample path {
  fill: none;
  stroke-width: 1.6;
  stroke-linecap: round;
}

.ts-tie { stroke: var(--p-gold); opacity: 0.7; }
.ts-allied { stroke: var(--p-olive); }
.ts-odds { stroke: var(--p-error); }
.ts-chatter { stroke: var(--p-gold); stroke-dasharray: 1.5 3.5; opacity: 0.85; }

/* Chinese is not set in capitals with inscription tracking. */
.graph-panel .p-eyebrow:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--p-radius-coin);
  box-shadow: 0 0 6px 1px currentColor;
  color: rgba(242, 237, 228, 0.12);
  flex-shrink: 0;
}

.legend-count {
  color: var(--p-ink-4);
  font-variant-numeric: tabular-nums;
}

/* The card and the list: parchment held up in the dark, like the Gathering's
   citizen card. */
.web-card,
.web-list {
  position: absolute;
  z-index: 8;
  display: flex;
  flex-direction: column;
  min-height: 0;
  color: var(--p-ink-2);
  box-shadow: var(--p-shadow-2);
  animation: card-in 0.32s cubic-bezier(0.2, 0.7, 0.2, 1);
}

.web-card {
  z-index: 9;
}

.web-card.as-rail,
.web-list.as-rail {
  top: 0;
  right: 0;
}

.web-card.as-sheet,
.web-list.as-sheet {
  left: 0;
  right: 0;
  /* The card's body scrolls; the sky above keeps room for the chosen name's ties. */
  max-height: 46%;
  animation-name: sheet-in;
}

.web-list.as-sheet {
  max-height: 72%;
}

@keyframes card-in {
  from { opacity: 0; transform: translateX(16px); }
  to { opacity: 1; transform: none; }
}

@keyframes sheet-in {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: none; }
}

.card-head {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 14px;
  padding: 18px 48px 14px 18px;
  flex-shrink: 0;
}

.list-head {
  grid-template-columns: minmax(0, 1fr);
}

.as-sheet .card-head {
  padding: 12px 48px 10px 16px;
  gap: 12px;
}

.card-id {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.card-role {
  overflow-wrap: anywhere;
}

.card-name {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  line-height: 1.05;
  color: var(--p-ink);
  overflow-wrap: anywhere;
}

.card-name:focus {
  outline: none;
}

.card-name:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 3px;
}

.as-sheet .card-name {
  font-size: var(--t-lg);
}

.card-meta {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

.card-close {
  position: absolute;
  top: 8px;
  right: 6px;
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid transparent;
  color: var(--p-ink-3);
  cursor: pointer;
}

.card-close:hover {
  color: var(--p-ink);
  border-color: var(--p-line-strong);
}

.card-rule {
  flex-shrink: 0;
  margin: 0 18px;
}

.as-sheet .card-rule {
  margin: 0 16px;
}

.card-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 6px 18px 20px;
}

.as-sheet .card-body {
  padding: 4px 16px 18px;
}

.card-section {
  margin: 16px 0 8px;
}

/* One serif voice for everything the scroll says and who they are. */
.card-facts {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.fact {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.fact p {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--p-ink);
}

.fact-mark {
  width: 6px;
  height: 6px;
  margin-top: 0.66em;
  border-radius: var(--p-radius-coin);
  background: var(--p-ink-4);
}

.fact.is-supports .fact-mark { background: var(--p-olive); }
.fact.is-opposes .fact-mark { background: var(--p-error); }

.card-facts.chatter .fact p {
  font-size: var(--t-sm);
  font-style: italic;
  color: var(--p-ink-2);
}

.card-facts.chatter .fact-mark {
  background: transparent;
  border: 1px solid var(--p-gold);
}

.card-bio {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
}

.card-bio.clamped {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-more-toggle {
  min-height: 40px;
  margin: 0 0 -6px;
  padding: 0;
  background: transparent;
  border: 0;
  color: var(--p-gold);
  font: inherit;
  font-size: var(--t-xs);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}

.card-more-toggle:hover {
  color: var(--p-ink);
}

.card-none,
.card-more {
  margin: 8px 0 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.card-ties {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tie-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  max-width: 100%;
  padding: 4px 12px 4px 5px;
  background: transparent;
  border: 1px solid var(--p-line-strong);
  border-radius: var(--p-radius-coin);
  color: var(--p-ink);
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  line-height: 1.1;
  cursor: pointer;
}

.tie-chip span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tie-chip:hover {
  border-color: var(--p-gold);
}

/* The Web in words */
.list-group + .list-group .card-section {
  margin-top: 20px;
}

.list-names {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.list-name {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  max-width: 100%;
  padding: 2px 8px 2px 0;
  background: transparent;
  border: 0;
  color: var(--p-ink);
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  line-height: 1.15;
  text-align: left;
  cursor: pointer;
}

.list-name:hover span {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.list-ties {
  margin: 0 0 0 40px;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
}

/* In a narrow column or the phone sheet: the tools take the whole bar, and
   the finder takes what the tools leave. */
.graph-panel.narrow .panel-top {
  flex-direction: column-reverse;
  align-items: stretch;
  gap: 6px;
  padding: 8px 12px 6px 16px;
}

.graph-panel.narrow .panel-tools {
  width: 100%;
}

.graph-panel.narrow .finder {
  flex: 1;
  width: auto;
  min-width: 0;
}

.graph-panel.narrow .tool .tool-text {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.graph-panel.narrow .legend-items {
  max-width: none;
  max-height: 128px;
  overflow: auto;
}

@media (prefers-reduced-motion: reduce) {
  .ember {
    animation: none;
  }

  .web-card,
  .web-card.as-sheet,
  .web-list,
  .web-list.as-sheet {
    animation: none;
  }

  .legend-head .chev,
  .tool {
    transition: none;
  }
}
</style>
