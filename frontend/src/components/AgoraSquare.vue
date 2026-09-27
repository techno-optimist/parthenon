<template>
  <section
    class="agora-square"
    :class="{ narrow, compact, reduced, ribboning: ribbons.length > 0 || !!caption, pinning: !!pinId }"
    :aria-label="squareLabel"
    @keydown.esc="unpin"
  >
    <div class="square-frame">
      <div class="stage-col">
        <div ref="sceneEl" class="scene" :style="sceneStyle">
          <!-- The painted ground: the night, and the same square relit by day over it -->
          <img
            v-if="eraKnown"
            class="painting"
            :srcset="nightSrcset"
            :src="nightSrc"
            :sizes="SIZES"
            alt=""
            width="2560"
            height="1440"
            decoding="async"
            fetchpriority="high"
            :style="{ objectPosition }"
          />
          <img
            v-if="eraKnown && dayWanted"
            class="painting day"
            :srcset="daySrcset"
            :src="daySrc"
            :sizes="SIZES"
            alt=""
            width="2560"
            height="1440"
            decoding="async"
            :style="{ objectPosition, opacity: light.day, '--lift': `${dayLift}%` }"
          />
          <div class="shade" :style="{ opacity: 1 - light.day * 0.7 }" aria-hidden="true"></div>
          <div class="shade warm" :style="{ opacity: light.warm }" aria-hidden="true"></div>
          <!-- The long gold of the late afternoon, before the dusk takes the square -->
          <div class="shade gold" :style="{ opacity: golden }" aria-hidden="true"></div>

          <!-- The day clock: the sun by day, the moon by night, on a thin arc -->
          <div class="sky" aria-hidden="true">
            <svg class="arc" viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">
              <path :d="ARC_PATH" vector-effect="non-scaling-stroke" />
            </svg>
            <span class="body" :class="sky.body" :style="bodyStyle"></span>
            <span class="sky-words">{{ dayWords }}</span>
          </div>

          <!-- The citizens, standing where they stand. One stop for the keyboard; arrows walk the crowd. -->
          <div v-if="eraKnown" class="crowd" role="group" :aria-label="$t('agora.square.crowd')">
            <button
              v-for="(tk, i) in tokens"
              :key="tk.id"
              type="button"
              class="token"
              :class="{
                speaking: !!speaking[tk.id],
                listening: !!listening[tk.id],
                focus: focusId === tk.id,
                pinned: pinId === tk.id,
                ribboned: tk.ribboned,
                edgeStart: tk.left < 14,
                edgeEnd: tk.left > 86
              }"
              :style="{
                left: `${tk.homeLeft}%`,
                top: `${tk.homeTop}%`,
                zIndex: tk.z,
                '--dx': `${tk.dx}px`,
                '--dy': `${tk.dy}px`,
                '--depth': tk.depth,
                '--walk': `${walkMs[tk.id] || 700}ms`,
                '--arrive': `${Math.min(i, 24) * 45}ms`
              }"
              :data-citizen="tk.id"
              :tabindex="roveSquare === tk.id ? 0 : -1"
              :aria-label="tk.label"
              :aria-pressed="pinId === tk.id ? 'true' : 'false'"
              @click="togglePin(tk.id)"
              @focus="onFocus('square', tk.id)"
              @blur="onBlur(tk.id)"
              @keydown="onRove($event, 'square', tk.id)"
              @mouseenter="hoverId = tk.id"
              @mouseleave="hoverId = hoverId === tk.id ? null : hoverId"
            >
              <span class="token-body">
                <CitizenCoin :name="tk.name" :type="tk.type" :portrait="tk.portrait" :size="compact ? 'sm' : 'md'" />
                <span v-if="glints[tk.id]" :key="glints[tk.id].n" class="glint" :class="glints[tk.id].kind"></span>
              </span>
              <span class="plate" aria-hidden="true">{{ tk.name }}</span>
            </button>
          </div>

          <!-- What is being said. Wide: a few words above the speaker, one or two at a time. -->
          <TransitionGroup
            v-if="!narrow"
            name="ribbon"
            tag="div"
            class="ribbons"
            :css="!reduced"
            :style="paceStyle"
            aria-hidden="true"
          >
            <div
              v-for="r in ribbons"
              :key="r.key"
              class="ribbon"
              :class="[r.align, r.below ? 'below' : 'above', `voice-${r.voice}`, { landed: r.landed }]"
              :data-ribbon="r.key"
              :style="{ left: `${r.left}%`, top: `${r.top}%`, '--role': r.color, '--lift': `${r.lift}px` }"
            >
              <span class="ribbon-who">{{ r.name }}<span v-if="r.verb" class="ribbon-verb"> · {{ r.verb }}</span></span>
              <span class="ribbon-words" :lang="r.lang"><span v-if="r.lead" class="lead">{{ r.lead }}</span>{{ r.rest }}</span>
            </div>
          </TransitionGroup>

          <!-- Narrow: the line as a caption along the foot of the square, the speaker's coin lit -->
          <Transition v-else name="caption" :css="!reduced">
            <div
              v-if="caption"
              :key="caption.key"
              class="caption"
              :class="[`voice-${caption.voice}`, { landed: caption.landed }]"
              :data-ribbon="caption.key"
              :style="{ '--role': caption.color, ...paceStyle }"
              aria-hidden="true"
            >
              <CitizenCoin class="caption-coin" :name="caption.name" :type="caption.type" :portrait="caption.portrait" size="sm" />
              <span class="ribbon-who">{{ caption.name }}<span v-if="caption.verb" class="ribbon-verb"> · {{ caption.verb }}</span></span>
              <span class="ribbon-words" :lang="caption.lang"><span v-if="caption.lead" class="lead">{{ caption.lead }}</span>{{ caption.rest }}</span>
            </div>
          </Transition>

          <slot name="overlay"></slot>
        </div>

        <!-- Whatever the stage stands directly under the square (a finished run's moves, on phones) -->
        <slot name="under"></slot>

        <!-- A citizen held up: their name stays over them, their lines are lit in the record -->
        <div v-if="pinnedCitizen" class="hold">
          <CitizenCoin :name="pinnedCitizen.name" :type="pinnedCitizen.type" :portrait="faceOf(pinnedCitizen.id, pinnedCitizen.name)" size="sm" />
          <p class="hold-text">
            <span class="hold-name">{{ pinnedCitizen.name }}</span>
            <span class="hold-note">{{ sideNote(pinnedCitizen.id, pinnedCitizen.side) }} · {{ $t('agora.square.pin.lines') }}</span>
          </p>
          <span class="hold-actions">
            <router-link class="p-button ghost small" :to="cardLink(pinnedCitizen)">{{ $t('agora.square.pin.card') }}</router-link>
            <button type="button" class="p-button secondary small" @click="unpin">{{ $t('agora.square.pin.release') }}</button>
          </span>
        </div>

        <!-- The last words said: the head of the record, where each ribbon settles -->
        <section v-if="stripLines.length" class="strip" :aria-label="$t('agora.square.strip.label')">
          <p class="p-eyebrow strip-title" aria-hidden="true">{{ $t('agora.square.strip.title') }}</p>
          <ol ref="stripEl" class="strip-lines" role="list">
            <li
              v-for="l in stripLines"
              :key="l.key"
              class="strip-line"
              :class="[`voice-${l.voice}`, { pinned: pinId === l.from }]"
              :data-line="l.key"
              :style="{ '--role': l.color }"
            >
              <CitizenCoin :name="l.name" :type="l.type" :portrait="faceOf(l.from, l.name)" size="sm" />
              <span class="strip-who">{{ l.name }}<span v-if="l.verb" class="strip-verb"> · {{ l.verb }}</span></span>
              <span class="strip-words" :lang="l.lang"><span v-if="l.lead" class="lead">{{ l.lead }}</span>{{ l.rest }}</span>
            </li>
          </ol>
        </section>
      </div>

      <!-- Where they stood. Once the square has closed the Scribe reads, from each
           citizen's own words, who moved and where each one ended; while it is
           open only where they began is known. -->
      <div v-if="citizenCount" class="stood" :class="{ after: !!after }">
        <!-- One polite voice for the reading: it speaks when the Scribe starts and when it is done -->
        <p class="stood-live" aria-live="polite">{{ readAnnouncement }}</p>

        <template v-if="after">
          <div class="stood-head">
            <h2 class="p-eyebrow stood-title">{{ $t('agora.square.after.title') }}</h2>
            <p v-if="readDone" class="stood-note">{{ $t('agora.square.after.note') }}</p>
          </div>

          <p v-if="readingNow" class="stood-reading">{{ $t('agora.square.after.reading') }}</p>
          <div v-else-if="readFailed" class="stood-failed">
            <p class="stood-note">{{ $t('agora.square.after.failed') }}</p>
            <button type="button" class="p-button secondary small" @click="emit('reread')">{{ $t('agora.square.after.again') }}</button>
          </div>
          <template v-else>
            <ul v-if="after.moved.length" class="moved" role="list">
              <li v-for="m in after.moved" :key="m.id" class="moved-row">
                <button
                  type="button"
                  class="moved-button"
                  :aria-pressed="pinId === m.id ? 'true' : 'false'"
                  @click="togglePin(m.id)"
                  @focus="onFocus('moved', m.id)"
                  @blur="onBlur(m.id)"
                  @mouseenter="focusId = m.id"
                  @mouseleave="focusId = focusId === m.id ? null : focusId"
                >
                  <CitizenCoin :name="m.name" :type="m.type" :portrait="faceOf(m.id, m.name)" size="md" />
                  <!-- 'Sand' over 'began watching and came round in favour in the afternoon'.
                       Each part carries its own word space, so the name a listener
                       hears never runs two words together. -->
                  <I18nT :keypath="m.when ? 'agora.square.after.line' : 'agora.square.after.lineNoWhen'" tag="span" class="moved-line" scope="global">
                    <template #name><span class="moved-name">{{ m.name }}{{ gap }}</span></template>
                    <template #from><span class="moved-side">{{ movedFrom(m.from) }}</span></template>
                    <template #to><span class="moved-side">{{ movedTo(m.to) }}</span></template>
                    <template #when><span class="moved-when">{{ gap }}{{ whenWords(m.when) }}</span></template>
                  </I18nT>
                </button>
              </li>
            </ul>
            <p v-else class="stood-note stood-still">{{ $t('agora.square.after.none') }}</p>
          </template>

          <div v-if="readDone" class="stood-views" role="group" :aria-label="$t('agora.square.after.views')">
            <button type="button" class="stood-view" :aria-pressed="view === 'ended' ? 'true' : 'false'" @click="view = 'ended'">{{ $t('agora.square.after.ended') }}</button>
            <button type="button" class="stood-view" :aria-pressed="view === 'began' ? 'true' : 'false'" @click="view = 'began'">{{ $t('agora.square.after.began') }}</button>
          </div>
          <p v-else class="p-eyebrow stood-sub">{{ $t('agora.square.after.began') }}</p>
        </template>

        <!-- While the square is open (or nobody has spoken): where they began, and any later stance the gathering records -->
        <template v-else>
          <div class="stood-head">
            <h2 class="p-eyebrow stood-title">{{ ledger.knowsDrift ? $t('agora.square.ledger.moved') : $t('agora.square.ledger.stood') }}</h2>
            <p class="stood-note">{{ ledger.knowsDrift ? $t('agora.square.ledger.movedNote') : $t('agora.square.ledger.stoodNote') }}</p>
          </div>

          <template v-if="ledger.knowsDrift">
            <ul v-if="ledger.moved.length" class="moved" role="list">
              <li v-for="m in ledger.moved" :key="m.id" class="moved-row">
                <button
                  type="button"
                  class="moved-button"
                  :aria-pressed="pinId === m.id ? 'true' : 'false'"
                  @click="togglePin(m.id)"
                  @focus="onFocus('moved', m.id)"
                  @blur="onBlur(m.id)"
                  @mouseenter="focusId = m.id"
                  @mouseleave="focusId = focusId === m.id ? null : focusId"
                >
                  <CitizenCoin :name="m.name" :type="m.type" :portrait="faceOf(m.id, m.name)" size="sm" />
                  <span class="moved-line">
                    <span class="moved-name">{{ m.name }}</span>
                    {{ $t('agora.square.ledger.movedLine', { from: $t(`agora.square.ledger.sideWords.${m.from}`), to: $t(`agora.square.ledger.sideWords.${m.to}`) }) }}
                  </span>
                </button>
              </li>
            </ul>
            <p v-else class="stood-note">{{ $t('agora.square.ledger.noneMoved') }}</p>
            <p class="p-eyebrow stood-sub">{{ $t('agora.square.ledger.began') }}</p>
          </template>
        </template>

        <div class="stood-rows" role="group" :aria-label="rowsLabel">
          <div v-for="side in rowSides" :key="side" class="stood-row">
            <span class="stood-label">
              {{ rowLabel(side) }}
              <span class="stood-count">{{ rowsShown[side].length }}</span>
            </span>
            <span v-if="rowsShown[side].length" class="stood-coins">
              <button
                v-for="c in rowsShown[side]"
                :key="c.id"
                type="button"
                class="stood-coin"
                :class="{ focus: focusId === c.id, pinned: pinId === c.id, arrived: showsEnded && c.moved }"
                :tabindex="roveLedger === c.id ? 0 : -1"
                :aria-label="coinLabel(c, side)"
                :aria-pressed="pinId === c.id ? 'true' : 'false'"
                :data-ledger="c.id"
                @click="togglePin(c.id)"
                @focus="onFocus('ledger', c.id)"
                @blur="onBlur(c.id)"
                @keydown="onRove($event, 'ledger', c.id)"
                @mouseenter="focusId = c.id"
                @mouseleave="focusId = focusId === c.id ? null : focusId"
              >
                <CitizenCoin :name="c.name" :type="c.type" :portrait="faceOf(c.id, c.name)" size="sm" />
              </button>
            </span>
            <span v-else class="stood-none">{{ $t('agora.square.ledger.nobody') }}</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
// The Agora itself: the painted square with the citizens standing on it as
// coins. The stage above feeds it beats (who spoke, to whom) through
// perform(); the square walks the speaker part of the way toward whoever they
// answer, raises a ribbon of a few words, and lets it settle into the last
// words under the square. The sun or the moon crosses the top of the square
// with the hour, and the painting turns from night to day with it. Any coin
// can be held up (a tap, a click, Enter): its name stays over it and its lines
// are lit in the record. A murmur, when the visitor asks for it, follows the pace.
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, toRef, watch } from 'vue'
import { useI18n, I18nT } from 'vue-i18n'
import CitizenCoin from './CitizenCoin.vue'
import { useCitizenPortraits } from '../parthenon/portraits.js'
import { citizenName, roleColorVar, stanceWords, STANCE_SIDES, voiceOf } from '../parthenon/vocabulary.js'
import {
  homeSpots,
  walkToward,
  depthScale,
  viewWindow,
  toBox,
  skyAt,
  lightAt,
  arcPath,
  hourWords,
  ribbonWords,
  withoutOwnName,
  beatDuration,
  isRibbonBeat,
  stanceLedger,
  stanceSide,
  stanceReading,
  plateOf,
  plateSrcset,
  plateSrc,
  beatsPerSecond,
  murmurLevel
} from '../parthenon/square.js'
import { sound, murmurInput } from '../parthenon/sound.js'

const props = defineProps({
  simulationId: { type: String, default: '' },
  // The gathering as configured: { agent_id, entity_name, entity_type, stance, sentiment_bias, ... }
  citizens: { type: Array, default: () => [] },
  // The hour of the city's day (0..24, fractions allowed) and the day number
  hour: { type: Number, default: 0 },
  day: { type: Number, default: 1 },
  // Which Athens: 'now' (the square as it stands), 'ancient' (399 BC), or '' while it is not yet known
  era: { type: String, default: 'now' },
  // The last things said, from the record: { key, from, to, kind, place, words }
  recent: { type: Array, default: () => [] },
  // The visitor asked to hear the square
  murmur: { type: Boolean, default: false },
  // Once the square has closed: the Scribe's reading of where each citizen
  // ended, { status: 'reading' | 'completed' | 'failed', data } (data is the
  // stances reading); null while the square is open, or when there is none.
  reading: { type: Object, default: null },
  // The city's clock, for when a citizen moved: minutes of the city per round
  minutesPerRound: { type: Number, default: 60 }
})

const emit = defineEmits(['settle', 'pin', 'reread'])
const { t, locale } = useI18n()

const ARC_PATH = arcPath()
const SIDES = ['for', 'against', 'undecided']
const SIZES = '(max-width: 899px) 134vw, 80vw'

const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const NARROW = '(max-width: 899px)'
const narrowQuery = typeof window !== 'undefined' ? window.matchMedia(NARROW) : null
const narrow = ref(narrowQuery ? narrowQuery.matches : false)
const onNarrow = (e) => { narrow.value = e.matches }

// A small square (a phone, or a narrow stage beside the Web) carries smaller coins.
const sceneEl = ref(null)
const stripEl = ref(null)
const sceneW = ref(0)
const sceneH = ref(0)
const compact = computed(() => narrow.value || (sceneW.value > 0 && sceneW.value < 720))
let sceneObserver = null

// ---- The painting ----
const eraKnown = computed(() => props.era !== '')
const plate = computed(() => plateOf(props.era))
const ground = computed(() => plate.value.ground)
const nightSrcset = computed(() => plateSrcset(plate.value, 'night'))
const daySrcset = computed(() => plateSrcset(plate.value, 'day'))
const nightSrc = computed(() => plateSrc(plate.value, 'night'))
const daySrc = computed(() => plateSrc(plate.value, 'day'))
const objectPosition = computed(() => (narrow.value ? `${plate.value.phoneX * 100}% 50%` : '50% 50%'))
// The daylight paintings were made from the same camera a breath lower: the
// daylit square sits this far below the night's (in percent of the
// painting's height, measured by matching their edges). Lifted by it, the day
// lies exactly over the night, so the stoa never doubles at dawn or dusk and
// every citizen keeps standing on the same stone.
const DAY_LIFT = { now: 3.6, ancient: 0.55 }
const dayLift = computed(() => DAY_LIFT[props.era] ?? 0)

// ---- Faces ----
const { portraitFor } = useCitizenPortraits(toRef(props, 'simulationId'))
const faceOf = (id, name) => portraitFor(id) || portraitFor(name) || ''

// ---- The citizens ----
const people = computed(() =>
  (props.citizens || [])
    .filter((c) => c && c.agent_id !== undefined && c.agent_id !== null)
    .map((c) => ({
      id: String(c.agent_id),
      name: citizenName(c.entity_name || ''),
      type: c.entity_type || '',
      stance: c.stance || '',
      side: stanceSide(c.stance)
    }))
)
const byId = computed(() => {
  const m = new Map()
  for (const p of people.value) m.set(p.id, p)
  return m
})
const citizenCount = computed(() => people.value.length)
const homes = computed(() => homeSpots(people.value, { ground: ground.value }))

// The part of the painting this frame shows: 16:9 on wide screens, 4:3 on phones.
const win = computed(() => (narrow.value ? viewWindow(4 / 3, plate.value.phoneX) : viewWindow(16 / 9)))
const coinPx = computed(() => (compact.value ? 30 : 40))

// Where each coin is now (image coordinates); absent means at home.
const pos = reactive({})
const walkMs = reactive({})
const speaking = reactive({})
const listening = reactive({})
const glints = reactive({})
const hoverId = ref(null)
const focusId = ref(null)
const pinId = ref(null)

const tokens = computed(() => {
  // A speaker with a ribbon up is named by the ribbon; their plate stays down.
  const up = new Set(ribbons.value.map((r) => r.from))
  if (caption.value) up.add(caption.value.from)
  return people.value
    .filter((p) => homes.value[p.id])
    .map((p) => {
      const home = homes.value[p.id]
      const at = pos[p.id] || home
      const hb = toBox(home, win.value)
      const ab = at === home ? hb : toBox(at, win.value)
      const lifted = hoverId.value === p.id || focusId.value === p.id || pinId.value === p.id
      return {
        ...p,
        homeLeft: hb.left,
        homeTop: hb.top,
        left: ab.left,
        top: ab.top,
        // Walking is a transform: the coin's anchor never moves, so the page never lays out again.
        dx: Math.round(((ab.left - hb.left) / 100) * sceneW.value * 10) / 10,
        dy: Math.round(((ab.top - hb.top) / 100) * sceneH.value * 10) / 10,
        depth: depthScale(at.y, { ground: ground.value }),
        z: 10 + Math.round(at.y * 100) + (speaking[p.id] ? 100 : 0) + (lifted ? 120 : 0),
        portrait: faceOf(p.id, p.name),
        ribboned: up.has(p.id),
        label: t('agora.square.token', { name: p.name, side: sideNote(p.id, p.side) })
      }
    })
})

// ---- The sky and the light ----
const sky = computed(() => skyAt(props.hour))
const light = computed(() => lightAt(props.hour))
// From mid-afternoon the daylight turns to gold, deepest just before the
// dusk, gone once the night painting has the square.
const ease = (a, b, x) => {
  const k = Math.max(0, Math.min(1, (x - a) / (b - a)))
  return k * k * (3 - 2 * k)
}
const golden = computed(() => {
  const h = (((Number(props.hour) || 0) % 24) + 24) % 24
  return Math.round(ease(14.5, 17.6, h) * (1 - ease(18.3, 19.6, h)) * 1000) / 1000
})
// The day painting is fetched the first time the sun is up, and kept.
const dayWanted = ref(false)
watch(light, (l) => { if (l.day > 0 || l.warm > 0) dayWanted.value = true }, { immediate: true })

const hourText = computed(() => {
  const w = hourWords(props.hour)
  return t(`agora.square.hours.${w.key}`, { n: w.n })
})
const dayWords = computed(() => t('agora.square.dayAt', { d: props.day || 1, hour: hourText.value }))
const squareLabel = computed(() =>
  citizenCount.value
    ? t('agora.square.label', { hour: hourText.value, n: citizenCount.value })
    : t('agora.square.labelEmpty', { hour: hourText.value })
)
const sceneStyle = computed(() => ({ '--sun-x': `${sky.value.left}%` }))
// The sun and the moon move by transform, so the square never lays out again as the hour turns.
const bodyStyle = computed(() => ({
  transform: `translate(${Math.round((sky.value.left / 100) * sceneW.value * 10) / 10}px, ${Math.round((sky.value.top / 100) * sceneH.value * 10) / 10}px) translate(-50%, -50%)`
}))

// ---- Where they stood ----
const ledger = computed(() => stanceLedger(props.citizens))

// ---- Who moved: the Scribe's reading, once the square has closed ----
const readingNow = computed(() => props.reading?.status === 'reading')
const readFailed = computed(() => props.reading?.status === 'failed')
const readDone = computed(() => props.reading?.status === 'completed' && !!props.reading?.data)
const after = computed(() =>
  props.reading
    ? stanceReading(props.citizens, readDone.value ? props.reading.data : null, { minutesPerRound: props.minutesPerRound })
    : null
)
// Where they ended, or where they began: the visitor's choice, once both are known.
const view = ref('ended')
const showsEnded = computed(() => readDone.value && view.value === 'ended')
const rowSides = computed(() => (after.value ? STANCE_SIDES : SIDES))
const rowsShown = computed(() => {
  if (!after.value) return ledger.value.rows
  return showsEnded.value ? after.value.ended : after.value.began
})
const rowsLabel = computed(() => {
  if (after.value) return showsEnded.value ? t('agora.square.after.ended') : t('agora.square.after.began')
  return ledger.value.knowsDrift ? t('agora.square.ledger.began') : t('agora.square.ledger.stood')
})
const lang = computed(() => String(locale.value || 'en').slice(0, 2))
// 'For', 'Against', 'Undecided', 'Watching' as the city says them everywhere.
const rowLabel = (side) => (after.value ? stanceWords(side, null, 'side', lang.value) : t(`agora.square.ledger.sides.${side}`))
// The move in a sentence: 'began watching and came round in favour'.
const movedFrom = (side) => t(`agora.square.after.from.${side}`)
const movedTo = (side) => t(`agora.square.after.came.${side}`)
// The space between words, where the language has one.
const gap = computed(() => (lang.value === 'zh' ? '' : ' '))

// ---- The voices of the square ----
// Each class of citizen speaks in its own hand (the Pentiment lesson):
// philosophers and poets in italic, officials and bodies with a lead-in in
// small capitals, machines in mono, everyone else in the reading serif.
const HAN = /[㐀-鿿]/
const langOf = (text) => (HAN.test(String(text || '')) ? 'zh' : 'en')
const LEAD_MAX = 22
const leadIn = (words, voice) => {
  const text = String(words || '')
  if (voice !== 'official' || HAN.test(text)) return { lead: '', rest: text }
  const parts = text.split(' ')
  let lead = ''
  let n = 0
  while (n < parts.length - 1 && n < 3 && (lead ? `${lead} ${parts[n]}` : parts[n]).length <= LEAD_MAX) {
    lead = lead ? `${lead} ${parts[n]}` : parts[n]
    n++
  }
  if (!lead) return { lead: '', rest: text }
  return { lead, rest: ` ${parts.slice(n).join(' ')}` }
}
// A body that opens with its own name ('Ammolith Compute offers...') is not
// given a lead-in: the name above it already says who speaks.
const spoken = (words, type, name = '') => {
  const voice = voiceOf(type)
  const own = name && String(words || '').toLowerCase().startsWith(String(name).toLowerCase())
  return { voice, lang: langOf(words), words, ...leadIn(words, own ? '' : voice) }
}
// When they moved, by the city's clock: 'in the afternoon', 'on the evening of day 2'.
const whenWords = (when) => {
  if (!when) return ''
  return when.day > 1 ? t(`agora.square.after.whenOn.${when.part}`, { d: when.day }) : t(`agora.square.after.when.${when.part}`)
}
// 'Sand, began watching, ended in favour'
const sideNote = (id, fallbackSide) => {
  const known = after.value?.byId.get(String(id))
  if (!known) return t(`agora.square.began.${fallbackSide}`)
  const began = t(`agora.square.began.${known.began}`)
  return readDone.value ? t('agora.square.after.both', { began, ended: t(`agora.square.ended.${known.ended}`) }) : began
}
const coinLabel = (c, side) => t('agora.square.token', { name: c.name, side: sideNote(c.id, side) })
const ledgerOrder = computed(() => rowSides.value.flatMap((s) => rowsShown.value[s].map((c) => c.id)))

// Said once for those who cannot see it: the Scribe is reading, and then how many moved.
const readAnnouncement = computed(() => {
  if (readingNow.value) return t('agora.square.after.reading')
  if (readDone.value && after.value) return t('agora.square.after.announce', { n: after.value.moved.length }, after.value.moved.length)
  if (readFailed.value) return t('agora.square.after.failed')
  return ''
})

// ---- Holding a citizen up ----
const pinnedCitizen = computed(() => (pinId.value ? byId.value.get(pinId.value) || null : null))
const togglePin = (id) => {
  pinId.value = pinId.value === id ? null : id
}
const unpin = () => {
  if (pinId.value) pinId.value = null
}
watch(pinId, (id) => emit('pin', id))
const cardLink = (c) => ({ name: 'Simulation', params: { simulationId: props.simulationId }, query: { citizen: c.name } })

// ---- The keyboard: one stop in the square and one in the ledger; arrows walk ----
const squareOrder = computed(() =>
  tokens.value
    .slice()
    .sort((a, b) => a.homeLeft - b.homeLeft || a.homeTop - b.homeTop)
    .map((tk) => tk.id)
)
const roveSquareId = ref(null)
const roveLedgerId = ref(null)
const roveSquare = computed(() => (squareOrder.value.includes(roveSquareId.value) ? roveSquareId.value : squareOrder.value[0]))
const roveLedger = computed(() => (ledgerOrder.value.includes(roveLedgerId.value) ? roveLedgerId.value : ledgerOrder.value[0]))

const onFocus = (where, id) => {
  focusId.value = id
  if (where === 'square') roveSquareId.value = id
  if (where === 'ledger') roveLedgerId.value = id
}
const onBlur = (id) => {
  if (focusId.value === id) focusId.value = null
}
const onRove = (e, where, id) => {
  const order = where === 'square' ? squareOrder.value : ledgerOrder.value
  const i = order.indexOf(id)
  if (i < 0) return
  let next = null
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = order[(i + 1) % order.length]
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = order[(i - 1 + order.length) % order.length]
  else if (e.key === 'Home') next = order[0]
  else if (e.key === 'End') next = order[order.length - 1]
  if (!next) return
  e.preventDefault()
  const root = e.currentTarget?.closest('.agora-square')
  const el = root?.querySelector(where === 'square' ? `[data-citizen="${CSS.escape(next)}"]` : `[data-ledger="${CSS.escape(next)}"]`)
  el?.focus()
}

// ---- Staging a beat ----
let seq = 0
const timers = new Set()
const later = (fn, ms) => {
  const id = setTimeout(() => {
    timers.delete(id)
    fn()
  }, Math.max(0, ms))
  timers.add(id)
  return id
}
const cancel = (id) => {
  if (!id) return
  clearTimeout(id)
  timers.delete(id)
}
const returns = {} // citizen id -> the timer that walks them home

const move = (id, to, ms) => {
  walkMs[id] = Math.round(ms)
  if (to) pos[id] = { x: to.x, y: to.y }
  else delete pos[id]
}

const glint = (id, kind, ms) => {
  if (!id || !homes.value[id]) return
  const n = ++seq
  glints[id] = { n, kind }
  later(() => {
    if (glints[id]?.n === n) delete glints[id]
  }, ms)
}

// Wide: ribbons over the square. Narrow: one caption at its foot.
const ribbons = ref([])
const caption = ref(null)
// Ribbons rise and settle faster when the argument is played back faster.
const pace = ref(1)
const paceStyle = computed(() => ({
  '--ribbon-in': `${Math.round(380 / Math.sqrt(pace.value))}ms`,
  '--ribbon-out': `${Math.round(600 / Math.sqrt(pace.value))}ms`
}))
const RIBBON_EST = { wide: { w: 30, h: 16 }, compact: { w: 42, h: 21 } }

// ---- The last words: each settled line joins the head of the record ----
const landed = ref([])
const STRIP_MAX = computed(() => (narrow.value ? 2 : 3))
const lineOf = (beat, key) => {
  const who = byId.value.get(beat.from)
  if (!who) return null
  return {
    key: String(key),
    from: beat.from,
    name: who.name,
    type: who.type,
    color: roleColorVar(who.type),
    verb: verbOf(beat),
    ...spoken(withoutOwnName(String(beat.words || '').replace(/\s+/g, ' ').trim(), who.name), who.type, who.name)
  }
}
const stripLines = computed(() => {
  const own = landed.value.length ? landed.value : (props.recent || []).slice(-STRIP_MAX.value).reverse().map((b) => lineOf(b, b.key)).filter(Boolean)
  return own.slice(0, STRIP_MAX.value)
})

// Move each line from where it was (or, for a new one, from its ribbon) to
// where it now stands: the ribbon visibly comes down into the record.
const flip = async (flightKey, flightRect) => {
  const list = stripEl.value
  const before = new Map()
  if (list) for (const el of list.querySelectorAll('[data-line]')) before.set(el.dataset.line, el.getBoundingClientRect())
  await nextTick()
  if (reduced || !stripEl.value) return
  for (const el of stripEl.value.querySelectorAll('[data-line]')) {
    const now = el.getBoundingClientRect()
    const from = el.dataset.line === flightKey && flightRect ? flightRect : before.get(el.dataset.line)
    if (!from) continue
    const dx = from.left - now.left
    const dy = from.top - now.top
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue
    const ms = Math.round((el.dataset.line === flightKey ? 620 : 360) / Math.sqrt(pace.value))
    el.style.transition = 'none'
    el.style.transform = `translate(${dx}px, ${dy}px)`
    if (el.dataset.line === flightKey) el.style.opacity = '0.35'
    void el.offsetWidth
    el.style.transition = `transform ${ms}ms cubic-bezier(0.2, 0.7, 0.2, 1), opacity ${ms}ms ease`
    el.style.transform = ''
    el.style.opacity = ''
  }
}

const settle = (key) => {
  let r = null
  if (caption.value && caption.value.key === key) {
    r = caption.value
  } else {
    r = ribbons.value.find((x) => x.key === key) || null
  }
  if (!r) return
  cancel(r.timer)
  // Where the words were in the air, so the line can come down from there.
  const el = sceneEl.value?.querySelector(`[data-ribbon="${key}"] .ribbon-words`)
  const rect = el ? el.getBoundingClientRect() : null
  r.landed = true
  if (caption.value && caption.value.key === key) caption.value = null
  else ribbons.value.splice(ribbons.value.indexOf(r), 1)
  const line = lineOf(r.beat, key)
  if (line) {
    landed.value = [line, ...landed.value.filter((l) => l.key !== line.key)].slice(0, 3)
    flip(line.key, rect)
  }
  emit('settle', r.beatId)
}

const verbOf = (beat) => {
  const other = beat.to ? byId.value.get(beat.to)?.name : ''
  if (beat.kind === 'answer') return other ? t('agora.square.ribbon.answers', { who: other }) : t('agora.square.ribbon.answersAll')
  if (beat.kind === 'quote') return other ? t('agora.square.ribbon.quotes', { who: other }) : t('agora.square.ribbon.quotesAll')
  return beat.place === 'stoa' ? t('agora.square.ribbon.inStoa') : ''
}

const raiseRibbon = (beat, at, life) => {
  const who = byId.value.get(beat.from)
  const said = who ? withoutOwnName(beat.words, who.name) : beat.words
  const words = narrow.value ? ribbonWords(said, { maxChars: 92, maxWords: 18 }) : ribbonWords(said)
  if (!who || !words) {
    emit('settle', beat.id)
    return
  }
  const key = ++seq
  const base = {
    key,
    beatId: beat.id,
    beat,
    from: beat.from,
    name: who.name,
    type: who.type,
    portrait: faceOf(who.id, who.name),
    color: roleColorVar(who.type),
    verb: verbOf(beat),
    ...spoken(words, who.type, who.name),
    landed: false,
    timer: 0
  }

  // A phone has room for one line at a time, at the foot of the square.
  if (narrow.value) {
    if (caption.value) settle(caption.value.key)
    base.timer = later(() => settle(key), life)
    caption.value = base
    return
  }

  // One ribbon per speaker, never more than two at once: the oldest settles early.
  for (const r of ribbons.value.filter((x) => x.from === beat.from)) settle(r.key)
  while (ribbons.value.length >= 2) settle(ribbons.value[0].key)
  const box = toBox(at, win.value)
  const est = compact.value ? RIBBON_EST.compact : RIBBON_EST.wide
  const spanOf = (left, a) => (a === 'end' ? [left - est.w, left] : [left, left + est.w])
  const heightOf = (below, top) => (below ? [top + 4, top + 4 + est.h] : [top - 4 - est.h, top - 4])
  const clashOf = (a, b) => {
    const [x0, x1] = spanOf(box.left, a)
    const [y0, y1] = heightOf(b, box.top)
    return ribbons.value.some((r) => {
      const [rx0, rx1] = spanOf(r.left, r.align)
      const [ry0, ry1] = heightOf(r.below, r.top)
      return x0 < rx1 && rx0 < x1 && y0 < ry1 && ry0 < y1
    })
  }
  // The words go where they cover the fewest faces: above or below the
  // speaker, reading on from them or back toward them, counted before the
  // test against the other ribbon. Above and reading on is the way a line is
  // first looked for, so it wins a tie.
  const facesUnder = (a, b) => {
    const [x0, x1] = spanOf(box.left, a)
    const [y0, y1] = heightOf(b, box.top)
    let n = 0
    for (const tk of tokens.value) {
      if (tk.id === beat.from) continue
      if (tk.homeLeft > x0 - 2 && tk.homeLeft < x1 + 2 && tk.homeTop > y0 - 3 && tk.homeTop < y1 + 3) n++
    }
    return n
  }
  const places = []
  for (const a of ['start', 'end']) {
    for (const b of [false, true]) {
      const [x0, x1] = spanOf(box.left, a)
      const [y0, y1] = heightOf(b, box.top)
      if (x0 < -1 || x1 > 101 || y0 < 2 || y1 > 97) continue
      places.push({ align: a, below: b, cost: (clashOf(a, b) ? 100 : 0) + facesUnder(a, b) + (a === 'end' ? 0.3 : 0) + (b ? 0.2 : 0) })
    }
  }
  places.sort((p, q) => p.cost - q.cost)
  const align = places[0]?.align ?? (box.left > 100 - est.w - 3 ? 'end' : 'start')
  let below = places[0]?.below ?? box.top - est.h - 6 < 2
  if (!places.length && clashOf(align, below)) below = !below
  if (clashOf(align, below)) settle(ribbons.value[0].key)
  const scale = depthScale(at.y, { ground: ground.value })
  const ribbon = {
    ...base,
    left: box.left,
    top: box.top,
    align,
    below,
    lift: Math.round((coinPx.value / 2) * scale + 8)
  }
  ribbon.timer = later(() => settle(key), life)
  ribbons.value.push(ribbon)
}

// ---- The murmur ----
const beatTimes = []
const noteBeat = () => {
  const now = typeof performance !== 'undefined' ? performance.now() : Date.now()
  beatTimes.push(now)
  while (beatTimes.length && beatTimes[0] < now - 8000) beatTimes.shift()
  return now
}
// The murmur is one voice in the city's sound. Its few nodes stand on the
// shared context from parthenon/sound.js and feed its murmur bus, so the one
// Listen switch, the fade while the tab is hidden and the dip under any voice
// all reach it. The square only sets its own level, which follows the pace.
// The shared context is never suspended or closed here; it is not ours.
let audio = null
const murmurOn = computed(() => !!props.murmur)
const LOUD = 0.12

const buildAudio = () => {
  if (audio) return audio
  // Null until the visitor has chosen Listen and touched the page; asked again
  // when the switch moves, on the next beat, or on the next slow tick.
  const shared = murmurInput()
  if (!shared) return null
  const { ctx, input } = shared
  const made = []
  const keep = (node) => {
    made.push(node)
    return node
  }
  try {
    // Brown noise, shaped into the band of voices and set talking by slow pulses.
    const len = Math.floor(ctx.sampleRate * 4)
    const buf = ctx.createBuffer(1, len, ctx.sampleRate)
    const d = buf.getChannelData(0)
    let last = 0
    for (let i = 0; i < len; i++) {
      last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02
      d[i] = last * 3.2
    }
    const src = keep(ctx.createBufferSource())
    src.buffer = buf
    src.loop = true
    const master = keep(ctx.createGain())
    master.gain.value = 0
    const soft = keep(ctx.createBiquadFilter())
    soft.type = 'lowpass'
    soft.frequency.value = 1500
    soft.connect(master)
    const pulses = [230, 360, 540, 780, 1050].map((f, i) => {
      const band = keep(ctx.createBiquadFilter())
      band.type = 'bandpass'
      band.frequency.value = f
      band.Q.value = 1.8
      const voice = keep(ctx.createGain())
      voice.gain.value = 0.22
      const lfo = keep(ctx.createOscillator())
      lfo.frequency.value = 1.7 + i * 0.93
      const depth = keep(ctx.createGain())
      depth.gain.value = 0.18
      lfo.connect(depth)
      depth.connect(voice.gain)
      src.connect(band)
      band.connect(voice)
      voice.connect(soft)
      lfo.start()
      return lfo
    })
    src.start()
    master.connect(input)
    audio = { ctx, master, src, pulses, nodes: made }
  } catch (err) {
    for (const node of made) {
      try { node.disconnect() } catch (e) { /* never joined */ }
    }
    audio = null
  }
  return audio
}

const levelNow = () => {
  const now = typeof performance !== 'undefined' ? performance.now() : Date.now()
  return murmurLevel(beatsPerSecond(beatTimes, now))
}
const setMurmur = (swell = false) => {
  if (!murmurOn.value || !sound.enabled || !buildAudio()) return
  const { ctx, master } = audio
  const at = ctx.currentTime
  const level = levelNow() * LOUD
  master.gain.cancelScheduledValues(at)
  master.gain.setTargetAtTime(swell ? level * 1.7 : level, at, swell ? 0.12 : 0.9)
  if (swell) master.gain.setTargetAtTime(level, at + 0.6, 0.9)
}
// Off: the square falls quiet; the engine's own switch fades everything else.
const quietMurmur = () => {
  if (!audio) return
  const { ctx, master } = audio
  master.gain.cancelScheduledValues(ctx.currentTime)
  master.gain.setTargetAtTime(0, ctx.currentTime, 0.25)
}
// The square's nodes leave with the square, after a breath so nothing clicks.
const dropMurmur = () => {
  if (!audio) return
  const { ctx, master, src, pulses, nodes } = audio
  audio = null
  try {
    const at = ctx.currentTime
    master.gain.cancelScheduledValues(at)
    master.gain.setTargetAtTime(0, at, 0.04)
    src.stop(at + 0.25)
    pulses.forEach((o) => o.stop(at + 0.25))
  } catch (err) {
    // already stopped
  }
  setTimeout(() => {
    for (const node of nodes) {
      try { node.disconnect() } catch (e) { /* already gone */ }
    }
  }, 400)
}
watch(
  () => murmurOn.value && sound.enabled,
  (on) => (on ? setMurmur() : quietMurmur())
)
// In a dev build only: the square's own murmur, for the capture scripts.
const DEV_HOOK = typeof window !== 'undefined' && !!(import.meta.env && import.meta.env.DEV)
const murmurProbe = () => audio
// The bed settles back as the pace slows.
let murmurTick = 0

/**
 * Stage one beat of the argument. beat: { id, kind, from, to, place, words }
 * (see beatOf in square.js); words are already cleaned of tags and handles.
 */
const perform = (beat, { speed = 1 } = {}) => {
  if (!beat) return
  const ribbon = isRibbonBeat(beat)
  const from = beat.from && homes.value[beat.from] ? beat.from : null
  const to = beat.to && homes.value[beat.to] ? beat.to : null
  const D = beatDuration(beat, speed)
  const n = ++seq
  pace.value = Number(speed) || 1
  noteBeat()
  setMurmur(ribbon)

  if (!from) {
    if (ribbon) emit('settle', beat.id)
    return
  }

  if (beat.kind === 'nod' || beat.kind === 'repeat' || beat.kind === 'shake') {
    const ms = Math.max(420, Math.round(1100 / Math.sqrt(speed)))
    if (reduced) {
      // Still coins: the two are ringed for the beat instead of a glint.
      speaking[from] = n
      if (to) listening[to] = n
      later(() => {
        if (speaking[from] === n) delete speaking[from]
        if (to && listening[to] === n) delete listening[to]
      }, Math.max(D, 600))
      return
    }
    glint(from, beat.kind, ms)
    if (to) glint(to, beat.kind, ms)
    return
  }
  if (!ribbon) return

  // The speaker steps toward whoever they answer or quote; a speech in the
  // Stoa turns them toward its steps. Under reduced motion no one walks: the
  // words still rise, without a transition, and are held for the beat.
  const home = homes.value[from]
  let target = null
  if (!reduced) {
    if (to) target = walkToward(home, homes.value[to], { ground: ground.value })
    else if (beat.place === 'stoa') target = walkToward(home, { x: home.x, y: plate.value.stoaY - 0.2 }, { fraction: 0.35, keep: 0, ground: ground.value })
    if (target && Math.abs(target.x - home.x) + Math.abs(target.y - home.y) < 0.003) target = null
  }
  const walk = Math.max(160, Math.min(900, D * 0.3))
  cancel(returns[from])
  speaking[from] = n
  if (to) listening[to] = n
  if (target) move(from, target, walk)
  const delay = target ? walk * 0.55 : 0
  const life = Math.max(D * 1.45, 650)
  later(() => raiseRibbon(beat, target || home, life), delay)
  returns[from] = later(() => {
    if (speaking[from] === n) {
      delete speaking[from]
      move(from, null, walk * 1.25)
    }
  }, delay + life)
  if (to) later(() => { if (listening[to] === n) delete listening[to] }, delay + life)
}

// Everyone home, nothing in the air, the last words back to the record's.
const reset = () => {
  for (const id of timers) clearTimeout(id)
  timers.clear()
  ribbons.value = []
  caption.value = null
  landed.value = []
  for (const k of Object.keys(speaking)) delete speaking[k]
  for (const k of Object.keys(listening)) delete listening[k]
  for (const k of Object.keys(glints)) delete glints[k]
  for (const k of Object.keys(pos)) move(k, null, 420)
}

defineExpose({ perform, reset })

// A new gathering stands afresh.
watch(() => props.simulationId, () => {
  reset()
  pinId.value = null
})

// Crossing the breakpoint, a caption becomes a ribbon's place and back: let it land.
watch(narrow, () => {
  if (caption.value) settle(caption.value.key)
  for (const r of [...ribbons.value]) settle(r.key)
})

const measure = () => {
  sceneW.value = sceneEl.value ? sceneEl.value.offsetWidth : 0
  sceneH.value = sceneEl.value ? sceneEl.value.offsetHeight : 0
}

onMounted(() => {
  narrowQuery?.addEventListener('change', onNarrow)
  measure()
  if (typeof ResizeObserver !== 'undefined' && sceneEl.value) {
    sceneObserver = new ResizeObserver(measure)
    sceneObserver.observe(sceneEl.value)
  }
  setMurmur()
  murmurTick = setInterval(() => setMurmur(), 2000)
  if (DEV_HOOK) window.__parthenonMurmur = murmurProbe
})
onBeforeUnmount(() => {
  narrowQuery?.removeEventListener('change', onNarrow)
  sceneObserver?.disconnect()
  for (const id of timers) clearTimeout(id)
  timers.clear()
  if (murmurTick) clearInterval(murmurTick)
  dropMurmur()
  if (DEV_HOOK && window.__parthenonMurmur === murmurProbe) delete window.__parthenonMurmur
})
</script>

<style scoped>
.agora-square {
  container-type: inline-size;
  background: var(--p-bg);
  /* A line coming down from the square may start wide of the page; it never widens it. */
  overflow-x: clip;
}

.square-frame {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
}

.stage-col {
  min-width: 0;
}

/* ---- The scene: never taller than the screen leaves room for ---- */
.scene {
  position: relative;
  width: 100%;
  max-width: calc((100vh - 230px) * 16 / 9);
  margin-inline: auto;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  isolation: isolate;
  background: #0b0e13;
}

.painting {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  -webkit-mask-image: linear-gradient(to bottom, #000 80%, transparent 100%);
  mask-image: linear-gradient(to bottom, #000 80%, transparent 100%);
  user-select: none;
  pointer-events: none;
}

/* Lifted to lie exactly over the night (see DAY_LIFT); its fade into the page
   is moved with it, so both paintings melt into the stone at the same line. */
.painting.day {
  transform: translateY(calc(-1 * var(--lift, 0%)));
  -webkit-mask-image: linear-gradient(to bottom, #000 calc(80% + var(--lift, 0%)), transparent 100%);
  mask-image: linear-gradient(to bottom, #000 calc(80% + var(--lift, 0%)), transparent 100%);
  transition: opacity 1.4s ease;
}

/* A night grade that keeps the chrome legible; it lifts by day */
.shade {
  position: absolute;
  inset: 0;
  pointer-events: none;
  transition: opacity 1.4s ease;
  background:
    linear-gradient(to bottom, rgba(6, 10, 22, 0.34), rgba(6, 10, 22, 0.04) 36%, rgba(6, 10, 22, 0.12) 80%, rgba(11, 14, 19, 0.55));
}

/* The rose of dawn and the amber of dusk along the sky */
.shade.warm {
  background:
    linear-gradient(to bottom, rgba(255, 148, 98, 0.42), rgba(255, 176, 120, 0.18) 22%, rgba(255, 190, 140, 0) 48%),
    radial-gradient(70% 50% at var(--sun-x) 8%, rgba(255, 200, 140, 0.35), rgba(255, 200, 140, 0) 70%);
  mix-blend-mode: soft-light;
}

/* The late gold: the sunlit stone warmed and the shadows deepened toward amber */
.shade.gold {
  background:
    radial-gradient(90% 70% at var(--sun-x) 0%, rgba(255, 196, 120, 0.5), rgba(255, 196, 120, 0) 70%),
    linear-gradient(to bottom, rgba(255, 170, 90, 0.42), rgba(236, 140, 64, 0.34) 55%, rgba(120, 58, 24, 0.4));
  mix-blend-mode: soft-light;
}

/* ---- The sky ---- */
.sky {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 2;
}

.arc {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.arc path {
  fill: none;
  stroke: rgba(242, 237, 228, 0.34);
  stroke-width: 1;
  stroke-dasharray: 1 5;
  stroke-linecap: round;
}

.body {
  position: absolute;
  z-index: 1;
  left: 0;
  top: 0;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  transition: transform 1.2s ease, background 0.6s ease, box-shadow 0.6s ease;
}

.body.sun {
  width: 16px;
  height: 16px;
  background: #fff4dc;
  box-shadow: 0 0 0 3px rgba(255, 226, 160, 0.35), 0 0 26px 9px rgba(255, 214, 140, 0.7);
}

.body.moon {
  width: 12px;
  height: 12px;
  background: #e9e4da;
  box-shadow: inset -4px -1px 0 0 rgba(20, 26, 36, 0.85), 0 0 14px 2px rgba(220, 228, 240, 0.28);
}

.sky-words {
  position: absolute;
  z-index: 0;
  left: 16px;
  top: 12px;
  padding: 3px 8px 4px;
  background: rgba(8, 10, 14, 0.46);
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink);
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.9);
}

/* ---- The citizens ---- */
.crowd {
  position: absolute;
  inset: 0;
  z-index: 3;
}

/* The button is a point on the stone: its coin and its 44px reach sit around it. */
.token {
  position: absolute;
  width: 0;
  height: 0;
  padding: 0;
  margin: 0;
  border: 0;
  background: none;
  color: inherit;
  cursor: pointer;
  transform: translate3d(var(--dx, 0px), var(--dy, 0px), 0);
  transition: transform var(--walk) cubic-bezier(0.45, 0, 0.2, 1);
  animation: arrive 0.6s ease both;
  animation-delay: var(--arrive);
  -webkit-tap-highlight-color: transparent;
}

.token::after {
  content: '';
  position: absolute;
  left: -22px;
  top: -22px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
}

.token:focus-visible { outline: none; }

@keyframes arrive {
  from { opacity: 0; }
  to { opacity: 1; }
}

.token-body {
  position: absolute;
  left: 0;
  top: 0;
  display: block;
  line-height: 0;
  transform: translate(-50%, -50%) scale(var(--depth));
  transition: transform 0.3s ease, filter 0.3s ease;
}

/* A shadow on the stone under each coin */
.token-body::before {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -5px;
  width: 80%;
  height: 9px;
  transform: translateX(-50%);
  background: radial-gradient(ellipse at center, rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0) 70%);
  z-index: -1;
}

.token-body :deep(.citizen-coin) {
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.55);
}

.token.speaking .token-body {
  transform: translate(-50%, -62%) scale(calc(var(--depth) * 1.12));
}

/* While words are in the air the square is lit for the two who are talking:
   everyone else steps back into the dusk, so no face competes with the line. */
.ribboning .token:not(.speaking):not(.listening):not(.pinned):not(.focus) .token-body {
  filter: brightness(0.6) saturate(0.65);
}

.token.speaking .token-body :deep(.citizen-coin) {
  box-shadow: 0 0 0 2px var(--role), 0 0 22px 2px color-mix(in srgb, var(--role) 70%, transparent);
}

.token.listening .token-body :deep(.citizen-coin),
.token.focus .token-body :deep(.citizen-coin) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--role) 70%, transparent), 0 2px 10px rgba(0, 0, 0, 0.55);
}

.token.pinned .token-body :deep(.citizen-coin) {
  box-shadow: 0 0 0 2px var(--p-gold), 0 0 0 5px rgba(11, 14, 19, 0.7), 0 0 18px 4px rgba(240, 182, 96, 0.45);
}

.token:focus-visible .token-body :deep(.citizen-coin) {
  box-shadow: 0 0 0 2px var(--p-bg), 0 0 0 4px var(--p-gold);
}

.plate {
  position: absolute;
  left: 0;
  top: calc(var(--depth) * 22px + 6px);
  transform: translateX(-50%);
  padding: 2px 7px 3px;
  background: rgba(11, 14, 19, 0.84);
  color: var(--p-ink);
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  font-weight: 600;
  line-height: 1.3;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease;
}

.token.edgeStart .plate { transform: translateX(-12px); }
.token.edgeEnd .plate { transform: translateX(calc(-100% + 12px)); }

.token.speaking .plate,
.token.focus .plate,
.token.pinned .plate {
  opacity: 1;
}

.token.pinned .plate { box-shadow: inset 0 -1px 0 var(--p-gold); }

/* While words are in the air, the only names shown are the ones held up. */
.token.ribboned:not(.focus):not(.pinned) .plate,
.ribboning .token:not(.pinned):not(.focus) .plate { opacity: 0; }

@media (hover: hover) {
  .agora-square:not(.ribboning) .token:hover .plate { opacity: 1; }
}

/* Nods and repeats: a small glint on both coins */
.glint {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid var(--p-gold);
  pointer-events: none;
  animation: glint 0.9s ease-out forwards;
}

.glint.repeat { border-color: var(--p-olive-deep); }
.glint.shake { border-color: var(--p-error); }

@keyframes glint {
  0% { opacity: 0.95; transform: scale(0.85); }
  100% { opacity: 0; transform: scale(1.7); }
}

/* ---- Ribbons: words in the air, not boxes ---- */
.ribbons {
  position: absolute;
  inset: 0;
  z-index: 40;
  pointer-events: none;
}

.ribbon {
  --ty: calc(-100% - var(--lift));
  position: absolute;
  width: max-content;
  max-width: clamp(220px, 28%, 380px);
  padding: 2px 0 4px 12px;
  border-left: 2px solid var(--role);
  transform: translate(-1px, var(--ty));
}

.ribbon.end {
  padding: 2px 12px 4px 0;
  border-left: 0;
  border-right: 2px solid var(--role);
  text-align: right;
  transform: translate(calc(-100% + 1px), var(--ty));
}

.ribbon.below { --ty: var(--lift); }

/* A soft seat of shadow under the words, feathered into the stone: dark
   enough to carry a line over sunlit paving or a lit colonnade, never a box. */
.ribbon::before {
  content: '';
  position: absolute;
  inset: -16px -34px -16px -22px;
  z-index: -1;
  background: radial-gradient(ellipse 62% 64% at 42% 52%, rgba(9, 11, 16, 0.84), rgba(9, 11, 16, 0.62) 46%, rgba(9, 11, 16, 0.22) 76%, rgba(9, 11, 16, 0));
  pointer-events: none;
}

.ribbon.end::before {
  inset: -16px -22px -16px -34px;
  background: radial-gradient(ellipse 62% 64% at 58% 52%, rgba(9, 11, 16, 0.84), rgba(9, 11, 16, 0.62) 46%, rgba(9, 11, 16, 0.22) 76%, rgba(9, 11, 16, 0));
}

/* The thread down to the coin: the ribbon's own rule, carried on */
.ribbon::after {
  content: '';
  position: absolute;
  left: -2px;
  top: 100%;
  width: 2px;
  height: calc(var(--lift) - 14px);
  background: linear-gradient(var(--role), transparent);
  opacity: 0.8;
}

.ribbon.end::after { left: auto; right: -2px; }
.ribbon.below::after { top: auto; bottom: 100%; background: linear-gradient(transparent, var(--role)); }

/* The name in its role's colour, lifted toward the light so it holds over
   the day's pale stone as well as the night's. */
.ribbon-who {
  display: block;
  line-height: 1.35;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.11em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--role) 78%, #fff6e8);
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.95), 0 0 12px rgba(0, 0, 0, 0.8);
}

.ribbon-verb {
  color: var(--p-ink-2);
  letter-spacing: 0.08em;
}

.ribbon-words {
  display: block;
  max-width: 26ch;
  margin-top: 2px;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: 1.375rem;
  font-weight: 500;
  line-height: 1.15;
  color: var(--p-ink);
  text-wrap: balance;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.95), 0 0 16px rgba(0, 0, 0, 0.85), 0 0 30px rgba(0, 0, 0, 0.5);
}

.ribbon.end .ribbon-words { margin-left: auto; }

/* ---- The voices: each class of citizen speaks in its own hand ---- */
/* The common citizen: the reading serif, upright, a little smaller for its larger eye */
.voice-common .ribbon-words {
  font-family: var(--p-font-serif);
  font-style: normal;
  font-size: 1.1875rem;
  font-weight: 400;
  line-height: 1.24;
}

/* Officials and bodies: Cormorant upright, the opening words in small capitals */
.voice-official .ribbon-words { font-style: normal; font-weight: 500; }
.lead {
  font-variant-caps: all-small-caps;
  letter-spacing: 0.06em;
  font-weight: 600;
}

/* Machines: mono, upright, set a touch wider, a faint cool cast */
.voice-machine .ribbon-words {
  font-family: var(--p-font-mono);
  font-style: normal;
  font-size: 1rem;
  font-weight: 400;
  line-height: 1.34;
  letter-spacing: 0.01em;
  color: color-mix(in srgb, var(--p-ink) 88%, #9cc2e6);
}

/* Elders, poets, philosophers keep the italic of the display face (the default). */

.ribbon.landed,
.caption.landed { opacity: 0 !important; transition: none !important; }

.ribbon-enter-active { transition: opacity var(--ribbon-in, 0.38s) ease, transform var(--ribbon-in, 0.38s) cubic-bezier(0.2, 0.7, 0.2, 1); }
.ribbon-leave-active { transition: opacity var(--ribbon-out, 0.6s) ease; }
.ribbon-enter-from { opacity: 0; transform: translate(-1px, calc(var(--ty) + 12px)); }
.ribbon.end.ribbon-enter-from { transform: translate(calc(-100% + 1px), calc(var(--ty) + 12px)); }
.ribbon-leave-to { opacity: 0; }

/* ---- The caption band (phones) ---- */
.caption {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 40;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: 10px;
  align-items: center;
  padding: 28px 14px 10px;
  background: linear-gradient(to top, rgba(7, 9, 13, 0.94) 0%, rgba(7, 9, 13, 0.86) 58%, rgba(7, 9, 13, 0));
  pointer-events: none;
}

.caption-coin { grid-row: 1 / span 2; box-shadow: 0 0 0 2px var(--role), 0 0 14px 2px color-mix(in srgb, var(--role) 60%, transparent); }
.caption .ribbon-who { font-size: 13px; letter-spacing: 0.08em; }
.caption .ribbon-words { max-width: none; font-size: var(--t-md); line-height: 1.22; text-wrap: pretty; }
.caption.voice-common .ribbon-words { font-size: 0.9375rem; line-height: 1.32; }
.caption.voice-machine .ribbon-words { font-size: 0.875rem; line-height: 1.36; }

.caption-enter-active { transition: opacity var(--ribbon-in, 0.3s) ease, transform var(--ribbon-in, 0.3s) ease; }
.caption-leave-active { transition: opacity 0.2s ease; }
.caption-enter-from { opacity: 0; transform: translateY(8px); }
.caption-leave-to { opacity: 0; }

/* ---- A citizen held up ---- */
.hold {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  padding: 10px var(--p-gutter);
  border-bottom: 1px solid var(--p-line);
  background: var(--p-surface);
}

.hold-text {
  flex: 1 1 14rem;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
  margin: 0;
  min-width: 0;
}

.hold-name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  color: var(--p-ink);
}

.hold-note {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.hold-actions { display: inline-flex; flex-wrap: wrap; gap: 8px; }
.hold-actions .p-button { min-height: 40px; }

/* ---- The last words ---- */
.strip {
  position: relative;
  z-index: 5;
  padding: 12px var(--p-gutter) 4px;
  border-bottom: 1px solid var(--p-line);
}

.strip-title { margin: 0 0 6px; }

.strip-lines {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}

.strip-line {
  position: relative;
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  align-items: center;
  column-gap: 10px;
  min-height: 40px;
  padding: 3px 0 3px 10px;
  border-left: 2px solid var(--role);
  will-change: transform;
}

/* Older lines step back in tone, never below reading contrast: the words go
   from ink-2 to ink-3 to ink-4, the faces and the rule dim with them. */
.strip-line + .strip-line { border-left-color: color-mix(in srgb, var(--role) 62%, transparent); }
.strip-line + .strip-line + .strip-line { border-left-color: color-mix(in srgb, var(--role) 40%, transparent); }
.strip-line + .strip-line :deep(.citizen-coin) { filter: brightness(0.82) saturate(0.8); }
.strip-line + .strip-line + .strip-line :deep(.citizen-coin) { filter: brightness(0.66) saturate(0.6); }
.strip-line + .strip-line .strip-who { color: var(--p-ink-2); }
.strip-line + .strip-line .strip-words { color: var(--p-ink-3); }
.strip-line + .strip-line + .strip-line .strip-who { color: var(--p-ink-3); }
.strip-line + .strip-line + .strip-line .strip-words,
.strip-line + .strip-line .strip-verb { color: var(--p-ink-4); }
.strip-line.pinned { background: rgba(240, 182, 96, 0.08); border-left-color: var(--role); }
.strip-line.pinned :deep(.citizen-coin) { filter: none; }
.strip-line.pinned .strip-who { color: var(--p-ink); }
.strip-line.pinned .strip-words { color: var(--p-ink-2); }

.strip-who {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  color: var(--p-ink);
  white-space: nowrap;
}

.strip-verb {
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  font-weight: 500;
  color: var(--p-ink-3);
}

.strip-words {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-2);
}

/* The voices carry down into the record */
.voice-elder .strip-words { font-family: var(--p-font-display); font-style: italic; font-size: var(--t-md); }
.voice-official .strip-words { font-family: var(--p-font-display); font-size: var(--t-md); }
.voice-machine .strip-words { font-family: var(--p-font-mono); font-size: 0.8125rem; letter-spacing: 0.01em; }

/* Chinese has no italic and no small capitals: the voices stay upright in the serif */
.ribbon-words:lang(zh),
.strip-words:lang(zh) { font-style: normal; font-variant-caps: normal; }
.voice-elder .ribbon-words:lang(zh),
.voice-official .ribbon-words:lang(zh),
.voice-common .ribbon-words:lang(zh) { font-family: var(--p-font-serif); font-size: 1.1875rem; line-height: 1.4; }

/* ---- Where they stood ---- */
.stood {
  position: relative;
  padding: 18px var(--p-gutter) 6px;
  min-width: 0;
}

.stood-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 16px;
}

.stood-title { margin: 0; }

.stood-note {
  margin: 0;
  flex: 1 1 24em;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
  max-width: 62em;
}

.stood-sub { margin: 14px 0 0; }

.moved {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: grid;
  gap: 4px;
}

.stood-rows {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.stood-row {
  display: grid;
  grid-template-columns: 9.5rem minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.stood-label {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  color: var(--p-ink);
  line-height: 1.1;
}

.stood-count {
  margin-left: 6px;
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  font-weight: 500;
  color: var(--p-ink-3);
}

.stood-coins {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  min-width: 0;
}

/* Each face a 40px button around a small coin */
.stood-coin {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
  line-height: 0;
}

.stood-coin:hover :deep(.citizen-coin),
.stood-coin.focus :deep(.citizen-coin) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--role) 70%, transparent);
}

.stood-coin.pinned :deep(.citizen-coin) { box-shadow: 0 0 0 2px var(--p-gold); }
.stood-coin:focus-visible { outline: 2px solid var(--p-gold); outline-offset: -2px; }

.stood-none {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-4);
}

.moved-button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: 12px;
  align-items: center;
  width: 100%;
  min-height: 44px;
  padding: 6px 8px 6px 6px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.moved-button:hover { background: rgba(242, 237, 228, 0.04); }
.moved-button:focus-visible { outline: 2px solid var(--p-gold); outline-offset: 1px; }
.moved-button[aria-pressed='true'] { background: rgba(240, 182, 96, 0.08); }

/* 'Sand' over 'moved from watching to for in the afternoon' */
.moved-line {
  min-width: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.45;
  color: var(--p-ink-3);
}

.moved-name {
  display: block;
  margin-bottom: 1px;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  line-height: 1.15;
  color: var(--p-ink);
}

.moved-side {
  font-weight: 600;
  color: var(--p-ink-2);
}

/* The Scribe at work: words only, no spinner */
.stood-reading {
  margin: 12px 0 0;
  padding-left: 12px;
  border-left: 2px solid var(--p-gold);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  line-height: 1.5;
  color: var(--p-ink-2);
  animation: scribe-reading 2.8s ease-in-out infinite;
}

@keyframes scribe-reading {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.62; }
}

.stood-failed {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  margin-top: 10px;
}

.stood-failed .p-button { min-height: 40px; }
.stood-still { margin-top: 10px; }

/* Where they ended, or where they began */
.stood-views {
  display: inline-flex;
  margin-top: 16px;
  border: 1px solid var(--p-control-border);
  border-radius: 999px;
  padding: 2px;
  max-width: 100%;
}

.stood-view {
  min-height: 40px;
  padding: 6px 14px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--p-ink-3);
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  font-weight: 500;
  letter-spacing: 0.02em;
  cursor: pointer;
  white-space: nowrap;
}

.stood-view:hover { color: var(--p-ink); }
.stood-view[aria-pressed='true'] { background: rgba(240, 182, 96, 0.14); color: var(--p-ink); }
.stood-view:focus-visible { outline: 2px solid var(--p-gold); outline-offset: 1px; }

/* A citizen who came to this side during the argument */
.stood-coin.arrived :deep(.citizen-coin) { box-shadow: 0 0 0 1.5px var(--p-gold); }
.stood-coin.arrived.pinned :deep(.citizen-coin) { box-shadow: 0 0 0 2.5px var(--p-gold); }

.stood-live {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* A wide stage: the ledger stands beside the square */
@container (min-width: 1120px) {
  .square-frame { grid-template-columns: minmax(0, 1fr) 300px; }
  .stood { padding: 18px 24px 18px 20px; border-left: 1px solid var(--p-line); }
  .stood-head { display: block; }
  .stood-note { margin-top: 8px; }
  .stood-row { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .stood-views { display: flex; }
  .stood-view { flex: 1 1 0; padding-inline: 8px; }
}

/* ---- Phones and narrow stages ---- */
.compact .ribbon { max-width: 42%; }
.compact .ribbon-words { font-size: var(--t-lg); }
.compact .voice-common .ribbon-words { font-size: 1.0625rem; }
.compact .voice-machine .ribbon-words { font-size: 0.9375rem; }
.compact .plate { top: calc(var(--depth) * 16px + 5px); }

/* Chinese in the square's inscriptions: the serif, upright, lightly tracked */
.sky-words:lang(zh),
.ribbon-who:lang(zh),
.stood-title:lang(zh),
.stood-sub:lang(zh),
.strip-title:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}
.ribbon-who:lang(zh) { font-size: 13px; }

@media (max-width: 899px) {
  .scene { aspect-ratio: 4 / 3; max-width: none; }
  .sky-words { left: 10px; top: 8px; }
  .plate { top: calc(var(--depth) * 16px + 5px); }
  .hold { padding: 10px 16px; }
  .strip { padding: 10px 16px 4px; }
  .strip-line { grid-template-columns: auto minmax(0, 1fr); row-gap: 0; padding-block: 5px; }
  .strip-line :deep(.citizen-coin) { grid-row: 1 / span 2; }
  .strip-words { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .stood { padding: 16px 16px 4px; }
  .stood-row { grid-template-columns: 7.5rem minmax(0, 1fr); gap: 10px; }
  .stood-label { font-size: var(--t-md); }
  .moved-name { font-size: var(--t-md); }
}

/* ---- Reduced motion: still coins, words that appear and go without drifting ---- */
.reduced .token,
.reduced .token-body,
.reduced .body,
.reduced .shade,
.reduced .painting.day {
  transition: none;
  animation: none;
}

.reduced .token.speaking .token-body {
  transform: translate(-50%, -50%) scale(var(--depth));
}

@media (prefers-reduced-motion: reduce) {
  .token,
  .token-body,
  .body,
  .shade,
  .painting.day,
  .plate,
  .strip-line,
  .stood-reading {
    transition: none !important;
    animation: none !important;
  }
}
</style>
