<template>
  <section
    class="agora"
    :class="[`mode-${mode}`, `tab-${tab}`, { reduced, replaying: replayActive }]"
    :style="{ '--band-h': `${bandH}px` }"
    aria-labelledby="agora-clock"
  >
    <!-- The day clock: the round as the sun crossing the square, in words. -->
    <header ref="bandEl" class="clock-band">
      <div class="clock">
        <p id="agora-clock" class="clock-line">
          <span class="clock-round">{{ clockRound }}</span>
          <span class="clock-sep" aria-hidden="true">·</span>
          <span class="clock-said">{{ clockSaid }}</span>
          <!-- The day and the hour are written on the square itself, and read here once. -->
          <span v-if="mode !== 'idle' && mode !== 'loading'" class="sr-only">, {{ clockDay }}</span>
        </p>
        <!-- One polite voice per act: it speaks when the round turns, not on every poll. -->
        <p class="sr-only" aria-live="polite">{{ announcement }}</p>
      </div>

      <div v-if="mode === 'idle' || mode === 'live'" class="controls">
        <!-- Never run: one explicit act -->
        <template v-if="mode === 'idle'">
          <button type="button" class="p-button" :disabled="isStarting" @click="doStartSimulation(false)">
            {{ isStarting ? $t('agora.idle.opening') : $t('agora.idle.open') }}
          </button>
        </template>

        <!-- Live: stop and write, or leave it -->
        <template v-else>
          <span class="control-with-hint">
            <button
              type="button"
              class="p-button"
              :disabled="!canStop || isStopping"
              :aria-describedby="!canStop ? 'stop-hint' : undefined"
              @click="handleStopAndWrite"
            >
              {{ isStopping ? $t('agora.live.stopping') : $t('agora.live.stop') }}
            </button>
            <span v-if="!canStop" id="stop-hint" class="control-hint">{{ $t('agora.live.stopWhen', { unit: unit.low }) }}</span>
          </span>
          <button type="button" class="p-button secondary" @click="leaveRunning">{{ $t('agora.live.leave') }}</button>
          <button
            v-if="!reduced"
            type="button"
            class="listen"
            :aria-pressed="listen ? 'true' : 'false'"
            :title="$t('agora.listen.title')"
            @click="toggleListen"
          >
            <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M3 8h3l4-3.5v11L6 12H3z" fill="currentColor" /><path v-if="listen" d="M13 7.2a4 4 0 0 1 0 5.6M15.2 5a7 7 0 0 1 0 10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg>
            <span>{{ $t('agora.listen.label') }}</span>
          </button>
        </template>
      </div>

      <!-- Finished: the scrubber, and the argument played back at a chosen pace -->
      <div v-if="mode === 'done' || mode === 'error'" class="sun-row">
        <button
          v-if="canReplay"
          type="button"
          class="replay-toggle"
          :aria-label="playLabel"
          :title="playLabel"
          @click="togglePlay"
        >
          <svg v-if="replay.status === 'playing'" viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
            <rect x="5" y="4" width="3.2" height="12" fill="currentColor" />
            <rect x="11.8" y="4" width="3.2" height="12" fill="currentColor" />
          </svg>
          <svg v-else viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
            <path d="M6 3.8v12.4L16 10z" fill="currentColor" />
          </svg>
        </button>
        <div class="sun">
          <input
            v-model.number="scrubRound"
            type="range"
            class="sun-range"
            :min="0"
            :max="scrubMax"
            :step="1"
            :aria-label="unit.goTo"
            :aria-valuetext="scrubText"
            :disabled="!allRounds.length"
            @input="onScrub"
            @change="onScrub"
          />
          <span class="sun-dot" :style="{ left: `${sunPercent}%` }" aria-hidden="true"></span>
        </div>
        <div v-if="canReplay" class="speeds" role="group" :aria-label="$t('agora.replay.speeds')">
          <button
            v-for="s in SPEEDS"
            :key="s"
            type="button"
            class="speed"
            :aria-pressed="replay.speed === s"
            :aria-label="s === 1 ? $t('agora.replay.speedOne') : $t('agora.replay.speedName', { n: s })"
            @click="replay.speed = s"
          >{{ $t('agora.replay.speed', { n: s }) }}</button>
        </div>
        <button
          v-if="canReplay && !reduced"
          type="button"
          class="listen"
          :aria-pressed="listen ? 'true' : 'false'"
          :title="$t('agora.listen.title')"
          @click="toggleListen"
        >
          <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M3 8h3l4-3.5v11L6 12H3z" fill="currentColor" /><path v-if="listen" d="M13 7.2a4 4 0 0 1 0 5.6M15.2 5a7 7 0 0 1 0 10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg>
          <span>{{ $t('agora.listen.label') }}</span>
        </button>
        <button v-if="replayActive" type="button" class="p-button ghost small whole" @click="endReplay">{{ $t('agora.replay.whole') }}</button>
      </div>
      <div
        v-else
        class="sun sun-row"
        role="progressbar"
        :aria-label="$t('agora.clock.sun')"
        :aria-valuemin="0"
        :aria-valuemax="totalRounds || 1"
        :aria-valuenow="currentRound"
        :aria-valuetext="`${clockRound}, ${clockDay}`"
      >
        <span class="sun-line" aria-hidden="true"></span>
        <span class="sun-dot" :class="{ rising: mode === 'live' }" :style="{ left: `${sunPercent}%` }" aria-hidden="true"></span>
      </div>

      <!-- Finished: the Chronicle, and the way to hold it again. A Chronicle the
           Scribe never finished is no Chronicle: it can be written again. On a
           phone these stand under the square, so the square comes first. -->
      <Teleport v-if="mode === 'done' || mode === 'error'" defer :to="`#${belowId}`" :disabled="!narrowScreen">
        <div class="controls done-controls">
          <button v-if="hasChronicle" type="button" class="p-button" @click="readChronicle">{{ $t('agora.done.read') }}</button>
          <button v-else type="button" class="p-button" :disabled="isGeneratingReport || !allRounds.length" @click="writeChronicle(true)">
            {{ isGeneratingReport ? $t('agora.done.writing') : scribeFailed ? $t('agora.done.writeAgain') : $t('agora.done.write') }}
          </button>
          <button type="button" class="p-button ghost" :aria-expanded="againOpen" :disabled="isStarting" @click="againOpen = !againOpen">
            {{ isStarting ? $t('agora.idle.opening') : $t('agora.done.again') }}
          </button>
        </div>

        <!-- Holding the argument again has a cost, and it is named before anything is cleared. -->
        <div v-if="againOpen" class="again">
          <p class="again-cost">{{ $t('agora.done.againCost') }}</p>
          <div class="again-actions">
            <button type="button" class="p-button small" :disabled="isStarting" @click="doStartSimulation(true)">{{ $t('agora.done.againConfirm') }}</button>
            <button type="button" class="p-button secondary small" @click="againOpen = false">{{ $t('agora.done.againCancel') }}</button>
          </div>
        </div>

        <!-- The Scribe's last attempt broke off: say so, with the cause behind a disclosure -->
        <div v-if="scribeFailed && !isGeneratingReport" class="scribe-note">
          <p class="scribe-note-text">{{ $t('agora.done.scribeFailed') }}</p>
          <details v-if="reportTrouble" class="trouble-detail">
            <summary>{{ $t('agora.done.scribeWhy') }}</summary>
            <p>{{ reportTrouble }}</p>
          </details>
        </div>
      </Teleport>

    </header>

    <!-- Trouble, in voice, with the cause behind a disclosure -->
    <div v-if="trouble" class="trouble" role="alert">
      <p class="trouble-title">{{ trouble.title }}</p>
      <p v-if="trouble.body" class="trouble-body">{{ trouble.body }}</p>
      <details v-if="trouble.detail" class="trouble-detail">
        <summary>{{ $t('agora.trouble.detail') }}</summary>
        <p>{{ trouble.detail }}</p>
      </details>
    </div>

    <!-- The square itself: the painted Agora with the citizens standing on it -->
    <AgoraSquare
      ref="squareRef"
      :simulation-id="simulationId"
      :citizens="citizens"
      :hour="squareClock.hour"
      :day="squareClock.day"
      :era="era"
      :recent="recentLines"
      :murmur="listen"
      :reading="mode === 'done' || mode === 'error' ? reading : null"
      :minutes-per-round="minutesPerRound"
      @settle="onSettle"
      @pin="pinnedAgent = $event"
      @reread="emit('reread')"
    >
      <template #overlay>
        <button v-if="canReplay && replay.status === 'rest'" type="button" class="square-invite" @click="play">
          <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M6 3.8v12.4L16 10z" fill="currentColor" /></svg>
          <span>{{ $t('agora.square.invite') }}</span>
        </button>
      </template>
      <!-- On phones, the finished run's moves stand here, right under the square -->
      <template #under>
        <div :id="belowId" class="below-square"></div>
      </template>
    </AgoraSquare>

    <!-- The gathered crowd, before the square opens -->
    <section v-if="mode === 'idle'" class="crowd" aria-labelledby="crowd-lede">
      <p class="p-eyebrow">{{ $t('agora.idle.eyebrow') }}</p>
      <h2 id="crowd-lede" class="crowd-lede">{{ profilesLoading ? $t('agora.idle.loading') : $t('agora.idle.lede', profiles.length) }}</h2>
      <p class="crowd-cost">{{ costLine }}</p>
      <ul v-if="profiles.length" class="crowd-list" role="list">
        <li v-for="p in profiles" :key="p.user_id ?? p.username ?? p.name" class="crowd-citizen">
          <CitizenCoin
            class="coin"
            :name="displayName(p.name, p.username)"
            :type="typeOf(p.user_id)"
            :portrait="faceOf(p.user_id, displayName(p.name, p.username))"
          />
          <span class="crowd-name">{{ displayName(p.name, p.username) }}</span>
          <span class="crowd-role">{{ roleWordOf(p.user_id) || p.profession || '' }}</span>
        </li>
      </ul>
    </section>

    <!-- Loading beat -->
    <p v-else-if="mode === 'loading'" class="quiet-note">{{ $t('common.loading') }}</p>

    <!-- The record: the argument, round by round, the Agora beside the Stoa -->
    <div v-else ref="recordEl" class="record">
      <!-- On phones, one column and a choice of square -->
      <div class="square-tabs" role="group" :aria-label="$t('agora.squares.which')">
        <button type="button" class="square-tab" :aria-pressed="tab === 'agora'" @click="tab = 'agora'">{{ platformName('twitter', 'title') }}</button>
        <button type="button" class="square-tab" :aria-pressed="tab === 'stoa'" @click="tab = 'stoa'">{{ platformName('reddit', 'title') }}</button>
      </div>

      <!-- On wide screens, the two squares named above their columns -->
      <div class="square-heads" aria-hidden="true">
        <span class="square-head">{{ platformName('twitter', 'title') }}</span>
        <span class="square-head">{{ platformName('reddit', 'title') }}</span>
      </div>

      <p v-if="!allRounds.length && mode === 'live'" class="quiet-note">{{ $t('agora.live.opening') }}</p>
      <p v-else-if="!allRounds.length" class="quiet-note">{{ $t('agora.empty.record') }}</p>

      <section
        v-for="round in rounds"
        :id="`round-${round.n}`"
        :key="round.n"
        v-memo="[round.sig, litIn(round), pinnedIn(round), facesKey, tab, locale]"
        class="round"
        :aria-label="`${round.label}, ${round.day}`"
      >
        <h2 class="round-head">
          <span class="p-eyebrow">{{ round.label }}</span>
          <span class="round-day">{{ round.day }}</span>
          <span class="round-said">{{ $t('agora.clock.said', round.said) }}</span>
        </h2>

        <div class="cols">
          <div class="col agora-col">
            <TransitionGroup name="entry" tag="ol" class="entries" role="list" @before-enter="onBeforeEnter" @after-enter="onAfterEnter">
              <li
                v-for="e in round.agora"
                :key="e.id"
                class="entry"
                :class="[e.kind, { lit: litEntry === e.id, held: !!pinnedAgent && e.agentId === pinnedAgent }]"
                :data-stagger="e.stagger"
                :data-entry="e.id"
              >
                <template v-if="e.kind === 'speech'">
                  <span class="who">
                    <CitizenCoin class="coin" :name="e.name" :type="e.type" :portrait="faceOf(e.agentId, e.name)" />
                    <span class="name">{{ e.name }}</span>
                    <span class="verb">
                      {{ e.verbLine }}<span v-if="e.alsoStoa" class="also"> · {{ $t('agora.empty.alsoStoa') }}</span>
                    </span>
                  </span>
                  <p class="words">{{ e.text }}</p>
                  <blockquote v-if="e.quoted" class="quoted">
                    <span class="quoted-who">{{ e.quotedWho }}</span>
                    <span class="quoted-text">{{ e.quoted }}</span>
                  </blockquote>
                </template>
                <template v-else>
                  <span class="quiet-name">{{ e.name }}</span>
                  <span class="quiet-text">{{ e.text }}.</span>
                </template>
              </li>
            </TransitionGroup>
            <p v-if="!round.agora.length" class="col-empty">{{ $t('agora.empty.agoraRound', { unit: unit.low }) }}</p>
          </div>

          <div class="col stoa-col">
            <TransitionGroup name="entry" tag="ol" class="entries" role="list" @before-enter="onBeforeEnter" @after-enter="onAfterEnter">
              <li
                v-for="e in round.stoa"
                :key="e.id"
                class="entry"
                :class="[e.kind, { reply: e.reply, lit: litEntry === e.id, held: !!pinnedAgent && e.agentId === pinnedAgent }]"
                :data-stagger="e.stagger"
                :data-entry="e.id"
              >
                <template v-if="e.kind === 'echo'">
                  <span class="echo-text">{{ e.text }}</span>
                </template>
                <template v-else-if="e.kind === 'speech'">
                  <span class="who">
                    <CitizenCoin class="coin" :name="e.name" :type="e.type" :portrait="faceOf(e.agentId, e.name)" />
                    <span class="name">{{ e.name }}</span>
                    <span class="verb">{{ e.verbLine }}</span>
                  </span>
                  <p class="words">{{ e.text }}</p>
                  <blockquote v-if="e.quoted" class="quoted">
                    <span class="quoted-who">{{ e.quotedWho }}</span>
                    <span class="quoted-text">{{ e.quoted }}</span>
                  </blockquote>
                </template>
                <template v-else>
                  <span class="quiet-name">{{ e.name }}</span>
                  <span class="quiet-text">{{ e.text }}.</span>
                </template>
              </li>
            </TransitionGroup>
            <p v-if="!round.stoa.length" class="col-empty">{{ $t('agora.empty.stoaRound', { unit: unit.low }) }}</p>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
// Act Γ΄, the Agora: the square itself. A run already open is watched, a run
// that has ended is read back round by round, and a crowd that has never
// argued waits for one explicit act. Nothing starts on mount.
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick, toRef } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AgoraSquare from './AgoraSquare.vue'
import CitizenCoin from './CitizenCoin.vue'
import {
  startSimulation,
  stopSimulation,
  getRunStatus,
  getRunStatusDetail,
  getSimulationActions,
  getSimulationTimeline,
  getSimulationProfiles,
  getSimulationComments
} from '../api/simulation'
import { generateReport } from '../api/report'
import {
  platformName,
  actionVerb,
  isSpeech,
  citizenName,
  entityTypeName,
  roleColorVar,
  stripIds,
  RUN_LENGTHS
} from '../parthenon/vocabulary.js'
import { useCitizenPortraits } from '../parthenon/portraits.js'
import {
  beatOf,
  indexPosts,
  isRibbonBeat,
  cleanSpeech,
  nameKey,
  placeOf,
  beatDuration,
  roundPause,
  SPEEDS
} from '../parthenon/square.js'

const { t, locale } = useI18n()
const router = useRouter()

const props = defineProps({
  simulationId: String,
  maxRounds: Number, // asked for at the Gathering, if a length was chosen
  minutesPerRound: { type: Number, default: 60 }, // the engine's own default: an hour a turn
  totalHours: { type: Number, default: 0 },
  // The citizens as the Gathering configured them: { agent_id, entity_name, entity_type }
  citizens: { type: Array, default: () => [] },
  // A Chronicle already written for this run, if the archive knows one, and
  // how it stands: '' | 'completed' | 'generating' | 'failed' (the engine's word)
  reportId: { type: String, default: '' },
  reportStatus: { type: String, default: '' },
  reportTrouble: { type: String, default: '' },
  // Which Athens the gathering stands in: 'now' or 'ancient' (399 BC)
  era: { type: String, default: 'now' },
  // The Scribe's reading of where each citizen ended, once the run has ended:
  // null | { status: 'reading' | 'completed' | 'failed', data } (see SimulationRunView)
  reading: { type: Object, default: null }
})

// beat: each move of the square as it is staged, { from, to, kind, key } by
// name, for the Web beside it. reread: ask the Scribe to read the stances again.
const emit = defineEmits(['add-log', 'update-status', 'finished', 'beat', 'reread'])

// ---- State ----
const mode = ref('loading') // loading | idle | live | done | error
const endedHow = ref(null) // completed | stopped | failed
const runStatus = ref({})
const allActions = ref([])
const actionIds = new Set()
const profiles = ref([])
const profilesLoading = ref(false)
const isStarting = ref(false)
const isStopping = ref(false)
const isGeneratingReport = ref(false)
const trouble = ref(null)
const againOpen = ref(false)
const tab = ref('agora')
const scrubRound = ref(0)
const bandEl = ref(null)
const bandH = ref(0)
const recordEl = ref(null)
const squareRef = ref(null)
const announcement = ref('')

const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

// Phones put the square first: a finished run's moves stand under it.
const narrowQuery = typeof window !== 'undefined' ? window.matchMedia('(max-width: 899px)') : null
const narrowScreen = ref(narrowQuery ? narrowQuery.matches : false)
const onNarrowScreen = (e) => { narrowScreen.value = e.matches }
let belowSeq = 0
const belowId = `agora-below-${++belowSeq}-${Math.random().toString(36).slice(2, 7)}`

// The murmur of the square: off until asked for, remembered for this visitor.
const LISTEN_KEY = 'parthenon.agora.listen'
const readListen = () => {
  try {
    return window.localStorage.getItem(LISTEN_KEY) === '1'
  } catch (err) {
    return false
  }
}
const listen = ref(!reduced && typeof window !== 'undefined' && readListen())
const toggleListen = () => {
  listen.value = !listen.value
  try {
    window.localStorage.setItem(LISTEN_KEY, listen.value ? '1' : '0')
  } catch (err) {
    // A private window keeps no memory; the choice holds for this visit.
  }
}

// A citizen held up in the square: their lines are lit in the record.
const pinnedAgent = ref(null)

const addLog = (msg) => emit('add-log', msg)
const setStatus = (s) => emit('update-status', s)

// ---- Citizens: name, role word and role colour by id ----
const citizensById = computed(() => {
  const map = new Map()
  for (const c of props.citizens || []) {
    map.set(String(c.agent_id), {
      name: c.entity_name,
      type: c.entity_type,
      color: roleColorVar(c.entity_type),
      role: entityTypeName(c.entity_type)
    })
  }
  return map
})
const roleWordOf = (id) => citizensById.value.get(String(id))?.role || ''
const typeOf = (id) => citizensById.value.get(String(id))?.type || ''
const displayName = (name, username) => citizenName(name, username)
const initialOf = (name) => (String(name || '').trim().charAt(0) || '?').toUpperCase()

// A citizen by any spelling of their name, and their face.
const nameIndex = computed(() => {
  const map = new Map()
  for (const c of props.citizens || []) {
    const key = nameKey(citizenName(c.entity_name || ''))
    if (key && !map.has(key)) map.set(key, { id: String(c.agent_id), name: citizenName(c.entity_name || '') })
  }
  return map
})
const idOfName = (name) => nameIndex.value.get(nameKey(citizenName(name || '')))?.id ?? null
const resolveHandle = (handle) => nameIndex.value.get(nameKey(handle))?.name || null
const clean = (text) => cleanSpeech(text, resolveHandle)

const { portraitFor } = useCitizenPortraits(toRef(props, 'simulationId'))
const faceOf = (id, name) => portraitFor(id) || portraitFor(name) || ''
// Which faces have arrived: a memoised hour re-renders when one does.
const facesKey = computed(() => (props.citizens || []).map((c) => (portraitFor(String(c.agent_id)) || portraitFor(citizenName(c.entity_name || '')) ? 1 : 0)).join(''))

// ---- The Chronicle on the shelf ----
const scribeFailed = computed(() => !!props.reportId && props.reportStatus === 'failed')
const hasChronicle = computed(() => !!props.reportId && !scribeFailed.value)

// ---- The unit of the city's time ----
// The engine counts in rounds; the city counts in hours. With sixty minutes a
// round they are the same thing, and the label follows the Scribe's setting
// so it stays honest at thirty ('Half-hour 3 of 80') or anything else ('Turn').
const unitKey = computed(() => {
  const m = Number(props.minutesPerRound) || 60
  if (m === 60) return 'hour'
  if (m === 30) return 'halfHour'
  if (m === 15) return 'quarterHour'
  return 'turn'
})
const unit = computed(() => {
  const k = unitKey.value
  const m = Number(props.minutesPerRound) || 60
  return {
    key: k,
    cap: t(`agora.units.${k}.cap`),
    low: t(`agora.units.${k}.low`),
    goTo: t(`agora.units.${k}.goTo`),
    span: t(`agora.units.${k}.span`, { m }),
    count: (n) => t(`agora.units.${k}.count`, { n }, n)
  }
})
// 'Hour 17 of 40', 'Hour 17', and 'The opening' for the seed hour before the first turn
const unitAt = (n, total) => (total ? t('agora.clock.at', { unit: unit.value.cap, n, total }) : t('agora.clock.atOnly', { unit: unit.value.cap, n }))
const roundLabel = (n) => (n === 0 ? t('agora.clock.opening') : t('agora.clock.atOnly', { unit: unit.value.cap, n }))

// ---- The day clock ----
const currentRound = computed(() => {
  if (mode.value === 'live') return runStatus.value.current_round || 0
  const fromRecord = allRounds.value.length ? allRounds.value[allRounds.value.length - 1].n : 0
  return Math.max(runStatus.value.current_round || 0, fromRecord)
})
// The hour on the clock: the replay's hour while the argument is played back.
const shownRound = computed(() => (replayActive.value ? replay.round : currentRound.value))
const plannedRounds = computed(() => {
  if (props.maxRounds) return props.maxRounds
  if (props.totalHours && props.minutesPerRound) return Math.round((props.totalHours * 60) / props.minutesPerRound)
  return 0
})
const totalRounds = computed(() => runStatus.value.total_rounds || plannedRounds.value || 0)

const dayOf = (round) => {
  const hours = (round * (props.minutesPerRound || 60)) / 60
  const d = Math.floor(hours / 24) + 1
  const h = Math.floor(hours % 24)
  const part = h < 6 ? 'night' : h < 12 ? 'morning' : h < 18 ? 'afternoon' : 'evening'
  return t('agora.clock.day', { d, part: t(`agora.clock.parts.${part}`) })
}

// The same words spoken in both squares in the same hour are one thing said.
const speechCount = computed(() => rounds.value.reduce((sum, r) => sum + r.said, 0))
const clockRound = computed(() => {
  if (mode.value === 'idle' || mode.value === 'loading') return t('agora.clock.before', { unit: unit.value.low })
  if (replayActive.value && shownRound.value === 0) return t('agora.clock.opening')
  return unitAt(shownRound.value, totalRounds.value)
})
const clockDay = computed(() => dayOf(mode.value === 'idle' || mode.value === 'loading' ? 0 : shownRound.value))
const clockSaid = computed(() => t('agora.clock.said', speechCount.value))
const sunPercent = computed(() => {
  const total = totalRounds.value || 1
  const n = mode.value === 'done' || mode.value === 'error' ? scrubRound.value : currentRound.value
  return Math.max(0, Math.min(100, (n / total) * 100))
})

// ---- The record, grouped by round ----
const sortedActions = computed(() =>
  [...allActions.value].sort((a, b) => (a.round_num - b.round_num) || String(a.timestamp).localeCompare(String(b.timestamp)))
)

const who = (name) => (name ? citizenName(name) : t('agora.quiet.someone'))
const short = (text, n = 110) => {
  const s = String(text || '').replace(/\s+/g, ' ').trim()
  return s.length > n ? `${s.slice(0, n).trimEnd()}…` : s
}

// A quiet action is the crowd moving: one phrase, never a card.
const quietPhrase = (a) => {
  const args = a.action_args || {}
  switch (String(a.action_type || '').toUpperCase()) {
    case 'LIKE_POST':
    case 'UPVOTE_POST':
      return t('agora.quiet.nods', { who: who(args.post_author_name) })
    case 'LIKE_COMMENT':
    case 'UPVOTE_COMMENT':
      return t('agora.quiet.nods', { who: who(args.comment_author_name) })
    case 'DISLIKE_POST':
    case 'DOWNVOTE_POST':
      return t('agora.quiet.shakes', { who: who(args.post_author_name) })
    case 'DISLIKE_COMMENT':
    case 'DOWNVOTE_COMMENT':
      return t('agora.quiet.shakes', { who: who(args.comment_author_name) })
    case 'REPOST': {
      const base = t('agora.quiet.repeats', { who: who(args.original_author_name) })
      return args.original_content ? `${base}: “${short(clean(args.original_content), 90)}”` : base
    }
    case 'FOLLOW':
      return t('agora.quiet.follows', { who: who(args.target_user_name || args.target_user) })
    case 'UNFOLLOW':
      return t('agora.quiet.unfollows', { who: who(args.target_user_name || args.target_user) })
    case 'MUTE':
      return t('agora.quiet.mutes', { who: who(args.target_user_name || args.target_user) })
    case 'SEARCH_POSTS':
    case 'SEARCH':
      return t('agora.quiet.asksAround', { what: short(clean(args.query), 60) })
    case 'SEARCH_USER':
      return t('agora.quiet.asksAfter', { who: who(args.query) })
    case 'DO_NOTHING':
    case 'IDLE':
      return t('agora.quiet.listens')
    case 'REFRESH':
    case 'TREND':
      return t('agora.quiet.looks')
    default:
      return actionVerb(a.action_type)
  }
}

const joinPhrases = (phrases) => {
  if (phrases.length <= 1) return phrases[0] || ''
  return `${phrases.slice(0, -1).join(', ')} ${t('agora.quiet.and')} ${phrases[phrases.length - 1]}`
}

const toEntry = (a) => {
  const type = String(a.action_type || '').toUpperCase()
  const args = a.action_args || {}
  const citizen = citizensById.value.get(String(a.agent_id))
  const name = citizen?.name ? citizenName(citizen.name) : citizenName(a.agent_name)
  const base = {
    id: a._uniqueId,
    ids: [a._uniqueId],
    agentId: String(a.agent_id),
    name,
    type: citizen?.type || '',
    initial: initialOf(name),
    color: citizen?.color || 'var(--p-gold)',
    // Read whole, a batch staggers in; played back, each line arrives on its own beat.
    stagger: a._stagger || 0
  }
  const content = args.content ?? args.quote_content ?? ''
  if (isSpeech(type) || (content && !['REPOST'].includes(type))) {
    const entry = { ...base, kind: 'speech', text: clean(content), verbLine: actionVerb(type), reply: false, quoted: '', quotedWho: '' }
    if (type === 'CREATE_COMMENT' || type === 'COMMENT' || type === 'REPLY') {
      entry.reply = true
      entry.verbLine = t('agora.speech.answers')
    }
    if (type === 'QUOTE_POST' || type === 'QUOTE') {
      entry.verbLine = t('agora.speech.quotes', { who: who(args.original_author_name) })
      entry.quoted = short(clean(args.original_content), 220)
      entry.quotedWho = who(args.original_author_name)
    }
    return entry
  }
  return { ...base, kind: 'quiet', phrases: [quietPhrase(a)] }
}

const wordsKey = (e) => `${e.agentId}\n${String(e.text).replace(/\s+/g, ' ').trim().toLowerCase()}`

// One column's raw entries, with the crowd's quiet moves run together.
const settleColumn = (raw) => {
  const out = []
  for (const entry of raw) {
    const last = out[out.length - 1]
    if (entry.kind === 'quiet' && last && last.kind === 'quiet' && last.agentId === entry.agentId) {
      last.phrases.push(...entry.phrases)
      last.ids.push(...entry.ids)
    } else {
      out.push(entry)
    }
  }
  for (const e of out) if (e.kind === 'quiet') e.text = joinPhrases(e.phrases)
  return out
}

const buildRounds = (actions) => {
  const byRound = new Map()
  for (const a of actions) {
    const n = Number(a.round_num) || 0
    if (!byRound.has(n)) byRound.set(n, { n, label: roundLabel(n), day: dayOf(n), said: 0, echoed: 0, agora: [], stoa: [] })
    const round = byRound.get(n)
    const column = String(a.platform).toLowerCase() === 'reddit' ? round.stoa : round.agora
    column.push(toEntry(a))
  }
  const list = [...byRound.values()].sort((x, y) => x.n - y.n)
  for (const r of list) {
    // The engine posts the opening words to both squares. A citizen who says
    // the same words in both places in the same hour is shown once, in the
    // Agora, with a mark; the Stoa says in one line that it heard them too.
    const spokenInAgora = new Map()
    const echoedIds = []
    for (const e of r.agora) if (e.kind === 'speech') spokenInAgora.set(wordsKey(e), e)
    r.stoa = r.stoa.filter((e) => {
      if (e.kind !== 'speech') return true
      const twin = spokenInAgora.get(wordsKey(e))
      if (!twin) return true
      twin.alsoStoa = true
      twin.ids.push(...e.ids)
      echoedIds.push(...e.ids)
      r.echoed += 1
      return false
    })
    r.agora = settleColumn(r.agora)
    r.stoa = settleColumn(r.stoa)
    if (r.echoed) {
      r.stoa.unshift({ id: `echo-${r.n}`, ids: [], echoOf: echoedIds, kind: 'echo', agentId: '', stagger: 0, text: t('agora.empty.stoaEcho', { n: r.echoed }, r.echoed) })
    }
    r.said = r.agora.filter((e) => e.kind === 'speech').length + r.stoa.filter((e) => e.kind === 'speech').length
    r.agents = new Set([...r.agora, ...r.stoa].map((e) => e.agentId).filter(Boolean))
    r.sig = `${r.agora.length}.${r.stoa.length}.${r.said}`
  }
  return list
}

// The whole record, and what of it the page shows: while the argument is
// played back, only what has been said so far (a line still in the air as a
// ribbon arrives when the ribbon settles). The record is built once; a replay
// only releases its entries as the cursor passes them, so a beat adds to one
// hour of the page instead of rebuilding them all.
const allRounds = computed(() => buildRounds(sortedActions.value))
const actionIndex = computed(() => {
  const map = new Map()
  sortedActions.value.forEach((a, i) => map.set(a._uniqueId, i))
  return map
})
const releaseOf = (e) => {
  const ids = e.ids && e.ids.length ? e.ids : e.echoOf || []
  let first = Infinity
  for (const id of ids) {
    const i = actionIndex.value.get(id)
    if (i !== undefined && i < first) first = i
  }
  return first
}
const releases = computed(() => {
  const map = new Map()
  for (const r of allRounds.value) for (const e of [...r.agora, ...r.stoa]) map.set(e, releaseOf(e))
  return map
})
const replayRounds = computed(() => {
  const cursor = replay.cursor
  const out = []
  for (const r of allRounds.value) {
    const rel = releases.value
    const shown = (e) => rel.get(e) <= cursor && !(e.kind === 'speech' && e.ids.some((id) => inTheAir.has(id)))
    const agora = r.agora.filter(shown)
    const stoa = r.stoa.filter(shown)
    if (!agora.length && !stoa.length) continue
    const said = agora.filter((e) => e.kind === 'speech').length + stoa.filter((e) => e.kind === 'speech').length
    out.push({ ...r, agora, stoa, said, sig: `${agora.length}.${stoa.length}.${said}` })
  }
  return out
})
const rounds = computed(() => (replayActive.value ? replayRounds.value : allRounds.value))

// What a memoised hour must still watch: its lit line and its held-up citizen.
const entryRound = computed(() => {
  const map = new Map()
  for (const r of allRounds.value) for (const e of [...r.agora, ...r.stoa]) map.set(e.id, r.n)
  return map
})
const litIn = (round) => (litEntry.value && entryRound.value.get(litEntry.value) === round.n ? litEntry.value : '')
const pinnedIn = (round) => (pinnedAgent.value && round.agents?.has(pinnedAgent.value) ? pinnedAgent.value : '')

// The last things said, for the head of the record under the square.
const recentLines = computed(() => {
  const list = replayActive.value ? sortedActions.value.slice(0, Math.max(0, replay.cursor + 1)) : sortedActions.value
  const out = []
  for (let i = list.length - 1; i >= 0 && out.length < 3; i--) {
    const a = list[i]
    if (inTheAir.has(a._uniqueId)) continue
    const beat = beatFor(a)
    if (!isRibbonBeat(beat) || !beat.words) continue
    out.unshift({ key: a._uniqueId, from: beat.from, to: beat.to, kind: beat.kind, place: beat.place, words: beat.words })
  }
  return out
})

// Which entry of the page holds each action (a quiet run of moves, or a
// speech heard in both squares, is one entry).
const entryOfAction = computed(() => {
  const map = new Map()
  for (const r of rounds.value) {
    for (const e of r.agora) for (const id of e.ids || []) map.set(id, e.id)
    for (const e of r.stoa) for (const id of e.ids || []) map.set(id, e.id)
  }
  return map
})

// ---- The scrubber (replay) ----
const scrubMax = computed(() => Math.max(currentRound.value, allRounds.value.length ? allRounds.value[allRounds.value.length - 1].n : 0, 0))
const scrubText = computed(() =>
  t('agora.scrubber.value', { unit: unit.value.cap, n: scrubRound.value, total: totalRounds.value || scrubMax.value, day: dayOf(scrubRound.value) })
)
const onScrub = () => (replayActive.value ? seek(scrubRound.value) : goToRound(scrubRound.value))
const goToRound = (n) => {
  let target = null
  for (const r of allRounds.value) {
    if (r.n <= n) target = r
    else break
  }
  if (!target) target = allRounds.value[0]
  if (!target) return
  const el = document.getElementById(`round-${target.n}`)
  if (!el) return
  const headerH = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--p-header-h')) || 64
  const bandH = bandEl.value ? bandEl.value.offsetHeight : 0
  const top = el.getBoundingClientRect().top + window.scrollY - headerH - bandH - 8
  window.scrollTo({ top, behavior: reduced ? 'auto' : 'smooth' })
}

// ---- Entering: fade and rise, with a stagger ----
const onBeforeEnter = (el) => {
  if (reduced || replayActive.value) return
  const i = Math.min(Number(el.dataset.stagger || 0), 12)
  el.style.transitionDelay = `${i * 45}ms`
}
const onAfterEnter = (el) => {
  el.style.transitionDelay = ''
}

// ---- The gathered crowd ----
const costLine = computed(() => {
  const planned = plannedRounds.value
  if (!planned) return t('agora.idle.costUnknown')
  const hours = (planned * (props.minutesPerRound || 60)) / 60
  let span
  if (hours < 24) span = t('agora.idle.spanHours', { h: Math.round(hours) })
  else if (hours < 36) span = t('agora.idle.spanDay')
  else if (Math.round(hours) === 168) span = t('agora.idle.spanWeek')
  else span = t('agora.idle.spanDays', { d: Math.round(hours / 24) })
  // Honest minutes: the story sizes carry measured ranges; anything else is
  // scaled from them at roughly 40 to 60 seconds a turn.
  const known = RUN_LENGTHS.find((l) => l.rounds === planned)
  let time
  if (known) {
    time = /hour/i.test(known.minutes) ? known.minutes : t('agora.idle.timeMinutes', { m: known.minutes })
  } else {
    const low = Math.max(1, Math.round((planned * 40) / 60))
    const high = Math.max(low + 1, Math.round(planned))
    time = high >= 90
      ? t('agora.idle.timeHours', { h: `${Math.max(1, Math.floor(low / 60))} to ${Math.ceil(high / 60)}` })
      : t('agora.idle.timeMinutes', { m: `${low} to ${high}` })
  }
  // '12 hours of the city's time, 12 hours' would say it twice.
  if (hours < 24 && unitKey.value === 'hour') return t('agora.idle.costShort', { span, time })
  return t('agora.idle.cost', { span, count: unit.value.count(planned), time })
})

const loadCrowd = async () => {
  profilesLoading.value = true
  try {
    const res = await getSimulationProfiles(props.simulationId)
    profiles.value = res?.data?.profiles || []
    addLog(t('agora.log.crowd', { n: profiles.value.length }))
  } catch (err) {
    addLog(t('agora.log.crowdTrouble', { error: stripIds(err.message) }))
  } finally {
    profilesLoading.value = false
  }
}

// ---- Adding to the record ----
let batchIndex = 0
const absorb = (actions) => {
  batchIndex = 0
  const added = []
  for (const action of actions || []) {
    const id = action.id || `${action.timestamp}-${action.platform}-${action.agent_id}-${action.action_type}`
    if (actionIds.has(id)) continue
    actionIds.add(id)
    const kept = { ...action, _uniqueId: id, _stagger: batchIndex++ }
    allActions.value.push(kept)
    added.push(kept)
  }
  return added
}

const resetRecord = () => {
  runStatus.value = {}
  allActions.value = []
  actionIds.clear()
  commentPosts.value = new Map()
  prevTwitterRound = 0
  prevRedditRound = 0
  trouble.value = null
  stopPolling()
  stopReplay()
  stopLive()
}

// ---- The square: who answers whom ----
// An answer in the Stoa names only its thread; the thread names its speaker.
// Each read adds to what is known: a read that fails (a busy record while the
// run writes) must not forget the threads already found.
const commentPosts = ref(new Map())
let commentsReadAt = 0
let commentsInFlight = null
const loadComments = () => {
  if (!props.simulationId) return Promise.resolve()
  if (commentsInFlight) return commentsInFlight
  commentsReadAt = Date.now()
  const found = []
  commentsInFlight = Promise.all(['reddit', 'twitter'].map(async (platform) => {
    try {
      const res = await getSimulationComments(props.simulationId, { platform, limit: 10000 })
      for (const c of res?.data?.comments || []) {
        if (c.comment_id !== undefined && c.comment_id !== null && c.post_id !== undefined && c.post_id !== null) {
          found.push([`${placeOf(platform)}:${c.comment_id}`, c.post_id])
        }
      }
    } catch (err) {
      // Without the threads, an answerer speaks where they stand.
    }
  })).then(() => {
    if (found.length) {
      const map = new Map(commentPosts.value)
      for (const [k, v] of found) map.set(k, v)
      commentPosts.value = map
    }
  }).finally(() => {
    commentsInFlight = null
  })
  return commentsInFlight
}

const postIndex = computed(() => indexPosts(sortedActions.value, idOfName))
const beatCtx = {
  idOfName: (name) => idOfName(name),
  postAuthor: (place, postId) => postIndex.value.get(`${place}:${postId}`) ?? null,
  commentPost: (place, commentId) => commentPosts.value.get(`${place}:${commentId}`) ?? null
}

// The opening words said in both squares are staged once, in the Agora.
const speechWords = (a) => String(a.action_args?.content ?? a.action_args?.quote_content ?? '').replace(/\s+/g, ' ').trim().toLowerCase()
const echoIds = computed(() => {
  const said = new Set()
  const out = new Set()
  for (const a of sortedActions.value) {
    if (placeOf(a.platform) === 'agora' && isSpeech(a.action_type)) said.add(`${a.round_num}\n${a.agent_id}\n${speechWords(a)}`)
  }
  for (const a of sortedActions.value) {
    if (placeOf(a.platform) === 'stoa' && isSpeech(a.action_type) && said.has(`${a.round_num}\n${a.agent_id}\n${speechWords(a)}`)) out.add(a._uniqueId)
  }
  return out
})

const beatFor = (a) => {
  const beat = beatOf(a, beatCtx)
  if (echoIds.value.has(a._uniqueId)) return { ...beat, kind: 'quiet', words: '' }
  if (beat.words) beat.words = clean(beat.words)
  return beat
}

// ---- The Web answers the square: each staged move blooms its speaker's star ----
const nameOfId = (id) => (id === null || id === undefined ? '' : citizensById.value.get(String(id))?.name || '')
const pulseWeb = (beat) => {
  if (!beat || beat.kind === 'quiet') return
  const from = nameOfId(beat.from)
  if (!from) return
  emit('beat', { from, to: beat.to != null ? nameOfId(beat.to) || null : null, kind: beat.kind, key: beat.id })
}

// ---- Playing the argument back ----
// rest: the whole record is shown; playing / paused: the record as it stood
// at the cursor, the square staging each beat at the chosen pace.
const replay = reactive({ status: 'rest', cursor: -1, round: 0, speed: 1 })
const replayActive = computed(() => replay.status !== 'rest')
const canReplay = computed(() => (mode.value === 'done' || mode.value === 'error') && sortedActions.value.length > 0)
const inTheAir = reactive(new Set()) // lines raised as ribbons that have not yet settled
let replayTimer = 0

const playLabel = computed(() =>
  replay.status === 'playing' ? t('agora.replay.pause') : replay.status === 'paused' ? t('agora.replay.resume') : t('agora.replay.play')
)

const lastIndexBefore = (n) => {
  const list = sortedActions.value
  let i = -1
  for (let k = 0; k < list.length; k++) {
    if ((Number(list[k].round_num) || 0) < n) i = k
    else break
  }
  return i
}

const clearReplayTimer = () => {
  if (replayTimer) clearTimeout(replayTimer)
  replayTimer = 0
}

const step = () => {
  replayTimer = 0
  if (replay.status !== 'playing') return
  const list = sortedActions.value
  const next = replay.cursor + 1
  if (next >= list.length) {
    finishReplay()
    return
  }
  const a = list[next]
  const round = Number(a.round_num) || 0
  replay.cursor = next
  replay.round = round
  scrubRound.value = round
  const beat = beatFor(a)
  // Even under reduced motion the words are held in the square for their beat before they land.
  if (squareRef.value && isRibbonBeat(beat) && beat.words) inTheAir.add(a._uniqueId)
  squareRef.value?.perform(beat, { speed: replay.speed })
  pulseWeb(beat)
  let wait = beatDuration(beat, replay.speed)
  const after = list[next + 1]
  if (after && (Number(after.round_num) || 0) !== round) wait += roundPause(replay.speed)
  replayTimer = setTimeout(step, wait)
}

const finishReplay = () => {
  // Let the last words settle, then give back the whole record.
  replay.status = 'ending'
  replayTimer = setTimeout(() => {
    replayTimer = 0
    replay.status = 'rest'
    replay.cursor = -1
    inTheAir.clear()
    scrubRound.value = scrubMax.value
  }, Math.max(1400, Math.round(4200 / replay.speed)))
}

const play = () => {
  const list = sortedActions.value
  if (!list.length) return
  if (replay.status === 'rest' || replay.status === 'ending') {
    clearReplayTimer()
    const first = Number(list[0].round_num) || 0
    const n = scrubRound.value
    const fromStart = replay.status === 'ending' || n >= scrubMax.value || n <= first
    squareRef.value?.reset()
    inTheAir.clear()
    replay.cursor = fromStart ? -1 : lastIndexBefore(n)
    replay.round = fromStart ? first : n
    scrubRound.value = replay.round
    replay.status = 'playing'
    announcement.value = t('agora.replay.from', { when: `${unitAt(replay.round, totalRounds.value)}, ${dayOf(replay.round)}` })
    nextTick(bringSquareIntoView)
    replayTimer = setTimeout(step, reduced ? 200 : 700)
  } else if (replay.status === 'paused') {
    replay.status = 'playing'
    clearReplayTimer()
    replayTimer = setTimeout(step, 200)
  }
}

const pause = () => {
  if (replay.status !== 'playing') return
  replay.status = 'paused'
  clearReplayTimer()
}

const togglePlay = () => (replay.status === 'playing' ? pause() : play())

const seek = (n) => {
  squareRef.value?.reset()
  inTheAir.clear()
  replay.cursor = lastIndexBefore(n)
  replay.round = n
  if (replay.status === 'ending') replay.status = 'paused'
  if (replay.status === 'playing') {
    clearReplayTimer()
    replayTimer = setTimeout(step, 300)
  }
}

const stopReplay = () => {
  clearReplayTimer()
  replay.status = 'rest'
  replay.cursor = -1
  inTheAir.clear()
  squareRef.value?.reset()
}

const endReplay = () => {
  stopReplay()
  scrubRound.value = scrubMax.value
}

const bringSquareIntoView = () => {
  const el = squareRef.value?.$el
  if (!el || typeof window === 'undefined') return
  const headerH = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--p-header-h')) || 64
  const sticky = window.matchMedia('(min-width: 900px)').matches ? bandEl.value?.offsetHeight || 0 : 0
  const r = el.getBoundingClientRect()
  if (r.top >= headerH + sticky - 2 && r.top < window.innerHeight * 0.45) return
  window.scrollTo({ top: Math.max(0, r.top + window.scrollY - headerH - sticky), behavior: reduced ? 'auto' : 'smooth' })
}

// ---- Watching live: the square stages what arrives, at a pace that keeps up ----
let liveQueue = []
let liveTimer = 0
let livePrimed = false

const stageLive = (added) => {
  const fresh = [...(added || [])].sort((a, b) => (a.round_num - b.round_num) || String(a.timestamp).localeCompare(String(b.timestamp)))
  if (!fresh.length) return
  // Joining a run already under way: the last words said, not the whole history.
  let list = fresh
  if (!livePrimed) {
    livePrimed = true
    list = fresh.filter((a) => isRibbonBeat(beatFor(a))).slice(-2)
  }
  liveQueue.push(...list)
  if (liveQueue.length > 40) liveQueue = liveQueue.filter((a) => isRibbonBeat(beatFor(a))).slice(-20)
  if (!liveTimer) drainLive()
}

const drainLive = () => {
  liveTimer = 0
  const a = liveQueue.shift()
  if (!a) return
  const beat = beatFor(a)
  const backlog = liveQueue.length
  const speed = backlog > 12 ? 4 : backlog > 4 ? 2 : 1
  squareRef.value?.perform(beat, { speed })
  pulseWeb(beat)
  liveTimer = setTimeout(drainLive, beatDuration(beat, speed))
}

const stopLive = () => {
  if (liveTimer) clearTimeout(liveTimer)
  liveTimer = 0
  liveQueue = []
  livePrimed = false
}

// ---- A ribbon settles into the record: its line is lit for a moment ----
const litEntry = ref('')
let litTimer = 0

const lightEntry = (actionId, { follow = false } = {}) => {
  const entryId = entryOfAction.value.get(actionId)
  if (!entryId) return
  litEntry.value = entryId
  if (litTimer) clearTimeout(litTimer)
  litTimer = 0
  // Under reduced motion the line stays lit until the next one.
  if (!reduced) litTimer = setTimeout(() => { if (litEntry.value === entryId) litEntry.value = '' }, 2800)
  if (follow) followEntry(entryId)
}

// A reader who has scrolled down to the record's end is kept at the end as it grows.
const readingTheEnd = () => {
  const rec = recordEl.value
  const sq = squareRef.value?.$el
  if (!rec || !sq || typeof window === 'undefined') return false
  const s = sq.getBoundingClientRect()
  const r = rec.getBoundingClientRect()
  return s.top + s.height / 2 < 0 && r.bottom <= window.innerHeight + 160
}

const followEntry = (entryId) => {
  const el = recordEl.value?.querySelector(`[data-entry="${CSS.escape(entryId)}"]`)
  if (!el) return
  const way = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--p-way-h')) || 52
  const r = el.getBoundingClientRect()
  const over = r.bottom - (window.innerHeight - way - 16)
  if (over > 0) window.scrollBy({ top: over, behavior: reduced ? 'auto' : 'smooth' })
}

const onSettle = async (actionId) => {
  if (!actionId) return
  const follow = replayActive.value && readingTheEnd()
  inTheAir.delete(actionId)
  await nextTick()
  lightEntry(actionId, { follow })
}

// The hour over the square: the replay's hour, the live hour, or the scrubber's.
const roundSpans = computed(() => {
  const spans = new Map()
  sortedActions.value.forEach((a, i) => {
    const r = Number(a.round_num) || 0
    const s = spans.get(r)
    if (!s) spans.set(r, { first: i, last: i })
    else s.last = i
  })
  return spans
})
const squareClock = computed(() => {
  const m = Number(props.minutesPerRound) || 60
  let at = 0
  if (mode.value === 'live') at = runStatus.value.current_round || 0
  else if (mode.value === 'done' || mode.value === 'error') {
    if (replayActive.value) {
      const span = roundSpans.value.get(replay.round)
      const within = span && replay.cursor >= span.first ? (replay.cursor - span.first + 1) / (span.last - span.first + 2) : 0
      at = replay.round + within
    } else at = scrubRound.value
  }
  const hours = (at * m) / 60
  return { hour: hours % 24, day: Math.floor(hours / 24) + 1 }
})

// ---- Opening the square ----
const doStartSimulation = async (force = false) => {
  if (!props.simulationId || isStarting.value) return
  againOpen.value = false
  isStarting.value = true
  trouble.value = null
  setStatus('working')
  try {
    const params = {
      simulation_id: props.simulationId,
      platform: 'parallel',
      force: !!force,
      enable_graph_memory_update: true
    }
    if (props.maxRounds) params.max_rounds = props.maxRounds
    const res = await startSimulation(params)
    if (res.success && res.data) {
      resetRecord()
      livePrimed = true // a square opened under our eyes stages every beat
      endedHow.value = null
      if (res.data.force_restarted) addLog(t('agora.log.cleared'))
      runStatus.value = res.data
      mode.value = 'live'
      scrubRound.value = 0
      addLog(res.data.total_rounds || props.maxRounds
        ? t('agora.log.opened', { count: unit.value.count(res.data.total_rounds || props.maxRounds) })
        : t('agora.log.openedAuto'))
      setStatus('live')
      startPolling()
    } else {
      failToStart(res.error || t('common.unknownError'))
    }
  } catch (err) {
    failToStart(err.message)
  } finally {
    isStarting.value = false
  }
}

const failToStart = (message) => {
  const detail = stripIds(message)
  trouble.value = { title: t('agora.trouble.start'), body: '', detail }
  addLog(t('agora.log.trouble', { error: detail }))
  setStatus(mode.value === 'idle' ? 'ready' : mode.value === 'error' ? 'error' : 'done')
}

// ---- Watching a live run ----
let statusTimer = null
let detailTimer = null
let prevTwitterRound = 0
let prevRedditRound = 0

const startPolling = () => {
  stopPolling()
  fetchRunStatusDetail()
  statusTimer = setInterval(fetchRunStatus, 2000)
  detailTimer = setInterval(fetchRunStatusDetail, 3000)
}
const stopPolling = () => {
  if (statusTimer) clearInterval(statusTimer)
  if (detailTimer) clearInterval(detailTimer)
  statusTimer = null
  detailTimer = null
}

const canStop = computed(() => (runStatus.value.current_round || 0) >= 1)

let statusInFlight = false
const fetchRunStatus = async () => {
  if (!props.simulationId || statusInFlight) return
  statusInFlight = true
  try {
    const res = await getRunStatus(props.simulationId)
    if (!res.success || !res.data) return
    const data = res.data
    runStatus.value = data
    if (data.twitter_current_round > prevTwitterRound) {
      prevTwitterRound = data.twitter_current_round
      addLog(t('agora.log.round', {
        square: platformName('twitter', 'title'),
        unit: unit.value.low,
        n: data.twitter_current_round,
        total: data.total_rounds || '?',
        said: t('agora.clock.said', speechCount.value)
      }))
    }
    if (data.reddit_current_round > prevRedditRound) {
      prevRedditRound = data.reddit_current_round
      addLog(t('agora.log.round', {
        square: platformName('reddit', 'title'),
        unit: unit.value.low,
        n: data.reddit_current_round,
        total: data.total_rounds || '?',
        said: t('agora.clock.said', speechCount.value)
      }))
    }
    // runner_status is authoritative: the engine only publishes a terminal
    // state once everything the citizens said has been kept.
    const s = data.runner_status
    if (s === 'failed') {
      await fetchRunStatusDetail(true)
      if (mode.value === 'live') finishRun('failed', data)
    } else if (s === 'completed' || s === 'stopped') {
      await fetchRunStatusDetail(true)
      if (mode.value === 'live') finishRun(s, data)
    }
  } catch (err) {
    console.warn('The square could not be read:', err)
  } finally {
    statusInFlight = false
  }
}

// One read of the record at a time: a slow read (threads included) must not
// be overtaken by the next poll, or the square would stage a later batch first.
let detailInFlight = null
const fetchRunStatusDetail = (fresh = false) => {
  if (!props.simulationId) return Promise.resolve()
  // A closing read must see the last words: it waits for the read under way, then reads again.
  if (detailInFlight) return fresh === true ? detailInFlight.then(() => fetchRunStatusDetail()) : detailInFlight
  detailInFlight = (async () => {
    try {
      const res = await getRunStatusDetail(props.simulationId)
      if (res.success && res.data) {
        const added = absorb(res.data.all_actions || [])
        if (mode.value === 'live' && added.length) {
          // A new answer names its thread; read the threads again to know whom it answers.
          const answers = added.some((a) => /COMMENT|REPLY/i.test(String(a.action_type || '')))
          if (answers && Date.now() - commentsReadAt > 5000) await loadComments()
          stageLive(added)
        }
      }
    } catch (err) {
      console.warn('The record could not be read:', err)
    } finally {
      detailInFlight = null
    }
  })()
  return detailInFlight
}

const finishRun = (how, data) => {
  stopPolling()
  stopLive()
  endedHow.value = how
  runStatus.value = data || runStatus.value
  scrubRound.value = currentRound.value
  if (how === 'failed') {
    mode.value = 'error'
    trouble.value = { title: t('agora.trouble.title'), body: t('agora.trouble.body'), detail: stripIds(data?.error || '') }
    addLog(t('agora.log.failed'))
    setStatus('error')
  } else {
    mode.value = 'done'
    addLog(how === 'stopped' ? t('agora.log.stoppedEarly', { unit: unit.value.low, n: currentRound.value }) : t('agora.log.finished'))
    setStatus('done')
  }
  // A fresh finish has no Chronicle yet; the shelf is only consulted for a run read back.
  emit('finished', how, { fresh: true })
}

// A swarm already running (opened from the Archive, a link or a reload) is
// watched, never restarted: a restart would throw its rounds away.
const attachToLiveRun = async (data) => {
  resetRecord()
  endedHow.value = null
  mode.value = 'live'
  runStatus.value = data
  prevTwitterRound = data.twitter_current_round || 0
  prevRedditRound = data.reddit_current_round || 0
  const at = data.current_round || 0
  addLog(at === 0 && data.total_rounds
    ? t('agora.log.attachedOpening', { total: unit.value.count(data.total_rounds) })
    : t('agora.log.attached', { unit: unit.value.low, n: at, total: data.total_rounds || '?' }))
  setStatus('live')
  startPolling()
}

// A run that has ended is read back whole.
const openReplay = async (data) => {
  resetRecord()
  runStatus.value = data
  const how = data.runner_status === 'failed' ? 'failed' : data.runner_status
  endedHow.value = how
  mode.value = how === 'failed' ? 'error' : 'done'
  setStatus(how === 'failed' ? 'error' : 'done')
  if (how === 'failed') {
    trouble.value = { title: t('agora.trouble.title'), body: t('agora.trouble.body'), detail: stripIds(data.error || '') }
  }
  try {
    const [actionsRes, timelineRes] = await Promise.all([
      getSimulationActions(props.simulationId, { limit: 10000, offset: 0 }),
      getSimulationTimeline(props.simulationId, 0),
      loadComments()
    ])
    absorb(actionsRes?.data?.actions || [])
    // The record spans every hour the square was open, quiet ones included.
    const span = Math.max(currentRound.value, timelineRes?.data?.rounds_count ?? 0, allRounds.value.length)
    addLog(t('agora.log.record', { said: t('agora.clock.said', speechCount.value), count: unit.value.count(span) }))
  } catch (err) {
    addLog(t('agora.log.recordTrouble', { error: stripIds(err.message) }))
  }
  await nextTick()
  scrubRound.value = currentRound.value
  emit('finished', how, { fresh: false })
}

// ---- Closing the square ----
const handleStopAndWrite = async () => {
  if (!props.simulationId || isStopping.value) return
  isStopping.value = true
  trouble.value = null
  addLog(t('agora.log.stopping'))
  setStatus('working')
  try {
    const res = await stopSimulation({ simulation_id: props.simulationId })
    if (res.success) {
      await fetchRunStatusDetail(true)
      finishRun('stopped', res.data)
      await writeChronicle(true)
    } else {
      throw new Error(res.error || t('common.unknownError'))
    }
  } catch (err) {
    // A close that is still pending arrives here too: the polling will catch
    // the square closing on its own.
    const detail = stripIds(err.message)
    trouble.value = { title: t('agora.trouble.stop'), body: t('agora.trouble.stopBody'), detail }
    addLog(t('agora.log.trouble', { error: detail }))
    if (mode.value === 'live') setStatus('live')
  } finally {
    isStopping.value = false
  }
}

const leaveRunning = () => {
  addLog(t('agora.log.leave'))
  router.push('/')
}

// ---- The Chronicle ----
const readChronicle = () => {
  if (!props.reportId) return
  router.push({ name: 'Report', params: { reportId: props.reportId } })
}

const writeChronicle = async (force = true) => {
  if (!props.simulationId || isGeneratingReport.value) return
  isGeneratingReport.value = true
  trouble.value = null
  try {
    const res = await generateReport({ simulation_id: props.simulationId, force_regenerate: !!force })
    if (res.success && res.data?.report_id) {
      addLog(res.data.already_generated ? t('agora.log.scribeExisting') : t('agora.log.scribe'))
      router.push({ name: 'Report', params: { reportId: res.data.report_id } })
    } else {
      throw new Error(res.error || t('common.unknownError'))
    }
  } catch (err) {
    const detail = stripIds(err.message)
    trouble.value = { title: t('agora.trouble.chronicle'), body: '', detail }
    addLog(t('agora.log.trouble', { error: detail }))
    isGeneratingReport.value = false
  }
}

// ---- Arrival ----
onMounted(async () => {
  addLog(t('agora.log.arrived'))
  if (!props.simulationId) return
  let data = null
  try {
    const res = await getRunStatus(props.simulationId)
    data = res?.success ? res.data : null
  } catch (err) {
    addLog(t('agora.log.trouble', { error: stripIds(err.message) }))
  }
  const s = data?.runner_status || 'idle'
  if (['starting', 'running', 'paused', 'stopping'].includes(s)) {
    await attachToLiveRun(data)
  } else if (['completed', 'stopped', 'failed'].includes(s)) {
    await openReplay(data)
  } else {
    mode.value = 'idle'
    setStatus('ready')
    loadCrowd()
  }
})

// The record's column names stick under the clock band; the band's height is measured.
let bandObserver = null
onMounted(() => {
  narrowQuery?.addEventListener('change', onNarrowScreen)
  if (typeof ResizeObserver === 'undefined' || !bandEl.value) return
  bandObserver = new ResizeObserver(() => { bandH.value = bandEl.value ? bandEl.value.offsetHeight : 0 })
  bandObserver.observe(bandEl.value)
})

onUnmounted(() => {
  narrowQuery?.removeEventListener('change', onNarrowScreen)
  stopPolling()
  clearReplayTimer()
  stopLive()
  if (litTimer) clearTimeout(litTimer)
  bandObserver?.disconnect()
})

watch(currentRound, (n, was) => {
  if (mode.value !== 'live') return
  scrubRound.value = n
  if (n !== was && n > 0) announcement.value = `${clockRound.value}, ${clockDay.value}`
})
</script>

<style scoped>
.agora {
  flex: 1 0 auto;
  display: flex;
  flex-direction: column;
  min-width: 0;
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
}

/* ---- The clock band ---- */
.clock-band {
  position: sticky;
  top: var(--p-header-h);
  z-index: 20;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 32px;
  padding: 16px var(--p-gutter) 0;
  background: var(--p-bg);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--p-line);
}

.clock { flex: 1 1 260px; min-width: 0; }

.clock-line {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  line-height: 1.15;
  color: var(--p-ink);
  text-wrap: balance;
}

.clock-round { color: var(--p-gold); }
.clock-sep { margin: 0 0.45em; color: var(--p-ink-4); }
.clock-said { color: var(--p-ink-2); }
/* The line breaks only between its parts, never inside one */
.clock-round,
.clock-said { white-space: nowrap; }

/* The sun over the square: a rule, and a gold dot that crosses it. The strip
   is 32px tall so a thumb on a phone finds the scrubber. */
.sun {
  position: relative;
  height: 32px;
  margin-top: 6px;
}

/* Play, the scrubber, the pace: one row under the clock, the band's full width */
.sun-row {
  flex: 1 0 100%;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  margin: 0 0 10px;
}

.sun.sun-row { display: block; margin: 0 0 8px; }

.sun-row .sun {
  flex: 1 1 220px;
  min-width: 160px;
  margin-top: 0;
}

.replay-toggle {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 1px solid var(--p-gold);
  border-radius: 50%;
  background: var(--p-terracotta-tint);
  color: var(--p-gold);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.replay-toggle:hover {
  background: var(--p-gold);
  color: #1f1a16;
}

.speeds {
  flex: 0 0 auto;
  display: inline-flex;
  border: 1px solid var(--p-control-border);
}

.speed {
  min-width: 44px;
  height: 40px;
  padding: 0 10px;
  border: 0;
  background: transparent;
  color: var(--p-ink-3);
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}

.speed + .speed { border-left: 1px solid var(--p-line-strong); }
.speed:hover { color: var(--p-ink); }

.speed[aria-pressed='true'] {
  background: var(--p-terracotta-tint);
  color: var(--p-gold);
}

.whole { min-height: 40px; }

.sun-line {
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  height: 1px;
  background: linear-gradient(90deg, var(--p-line-strong), var(--p-gold) 50%, var(--p-line-strong));
  opacity: 0.6;
}

.sun-dot {
  position: absolute;
  top: 50%;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--p-gold);
  box-shadow: 0 0 0 4px var(--p-terracotta-tint), 0 0 18px rgba(240, 182, 96, 0.55);
  transform: translate(-50%, -50%);
  transition: left 0.6s ease;
  pointer-events: none;
}

.sun-dot.rising { animation: breathe 2.4s ease-in-out infinite; }

@keyframes breathe {
  0%, 100% { box-shadow: 0 0 0 4px var(--p-terracotta-tint), 0 0 18px rgba(240, 182, 96, 0.55); }
  50% { box-shadow: 0 0 0 7px transparent, 0 0 26px rgba(240, 182, 96, 0.8); }
}

.sun-range {
  appearance: none;
  -webkit-appearance: none;
  width: 100%;
  height: 32px;
  margin: 0;
  background: transparent;
  cursor: pointer;
}

.sun-range:disabled { cursor: default; opacity: 0.5; }

.sun-range::-webkit-slider-runnable-track {
  height: 1px;
  background: linear-gradient(90deg, var(--p-line-strong), var(--p-gold) 50%, var(--p-line-strong));
  opacity: 0.6;
}

.sun-range::-moz-range-track {
  height: 1px;
  background: var(--p-line-strong);
}

.sun-range::-webkit-slider-thumb {
  appearance: none;
  -webkit-appearance: none;
  width: 28px;
  height: 28px;
  margin-top: -14px;
  border-radius: 50%;
  background: transparent;
  border: 0;
}

.sun-range::-moz-range-thumb {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: transparent;
  border: 0;
}

.sun-range:focus-visible { outline: 2px solid var(--p-gold); outline-offset: 2px; }

/* The murmur: a quiet toggle beside the pace */
.listen {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--p-control-border);
  background: transparent;
  color: var(--p-ink-3);
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  font-weight: 600;
  cursor: pointer;
}

.listen:hover { color: var(--p-ink); }
.listen[aria-pressed='true'] { background: var(--p-terracotta-tint); color: var(--p-gold); border-color: var(--p-gold); }
.listen:focus-visible,
.speed:focus-visible,
.replay-toggle:focus-visible { outline: 2px solid var(--p-gold); outline-offset: 2px; }

/* Controls */
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  flex: 0 1 auto;
  justify-content: flex-end;
  gap: 10px 12px;
}

.control-with-hint {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.control-hint {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  font-style: italic;
  font-family: var(--p-font-serif);
}

.again {
  flex: 1 0 100%;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  padding: 12px 16px;
  margin-bottom: 14px;
  border: 1px solid var(--p-line-strong);
  background: var(--p-surface-2);
}

.again-cost {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  color: var(--p-ink-2);
  max-width: 48em;
}

.again-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* The Scribe's last attempt broke off */
.scribe-note {
  flex: 1 0 100%;
  margin-bottom: 14px;
  padding: 10px 16px;
  border-left: 2px solid var(--p-ochre);
  background: var(--p-surface-2);
}

.scribe-note-text {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-2);
  max-width: 48em;
}

/* A finished run's moves sit at the right of the clock on wide screens */
@media (min-width: 900px) {
  .clock-band > .clock { order: 0; }
  .clock-band > .controls { order: 1; }
  .clock-band > .sun-row { order: 2; }
  .clock-band > .again,
  .clock-band > .scribe-note { order: 3; }
}

/* On phones they stand under the square, one row at the gutter */
.below-square:empty { display: none; }
.below-square {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px 4px;
  border-bottom: 1px solid var(--p-line);
}
.below-square .controls { justify-content: flex-start; flex-wrap: nowrap; gap: 8px; padding: 0; }
.below-square .controls .p-button { flex: 1 1 0; min-width: 0; padding-inline: 12px; }
.below-square .again,
.below-square .scribe-note { margin: 0; }

/* The two squares named above their columns, held under the clock band */
.square-heads {
  position: sticky;
  top: calc(var(--p-header-h) + var(--band-h, 0px));
  z-index: 15;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 32px;
  margin: 0 calc(-1 * var(--p-gutter));
  padding: 0 var(--p-gutter);
  background: var(--p-bg);
  border-bottom: 1px solid var(--p-line);
}

.square-head {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
  padding: 10px 0;
}

.square-heads .square-head:last-child { padding-left: 32px; border-left: 1px solid var(--p-line); }

.square-tabs {
  display: none;
  gap: 0;
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

.square-tab {
  flex: 1;
  min-width: 0;
  min-height: 44px;
  padding: 10px 8px 12px;
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--p-ink-3);
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  cursor: pointer;
}

.square-tab[aria-pressed='true'] {
  color: var(--p-gold);
  border-bottom-color: var(--p-gold);
}

/* ---- Trouble ---- */
.trouble {
  margin: 20px var(--p-gutter) 0;
  padding: 14px 18px;
  border: 1px solid var(--p-error);
  background: var(--p-error-tint);
}

.trouble-title {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  color: var(--p-ink);
}

.trouble-body {
  margin: 4px 0 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  color: var(--p-ink-2);
}

.trouble-detail { margin-top: 8px; font-size: var(--t-xs); color: var(--p-ink-3); }
.trouble-detail summary { cursor: pointer; color: var(--p-ink-2); }
.trouble-detail p { margin: 6px 0 0; font-family: var(--p-font-mono); letter-spacing: var(--track-mono); word-break: break-word; }

/* ---- The crowd, before the square opens ---- */
.crowd {
  padding: 40px var(--p-gutter) 48px;
  max-width: 1100px;
}

.crowd-lede {
  margin: 8px 0 8px;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.1;
  color: var(--p-ink);
  text-wrap: balance;
}

.crowd-cost {
  margin: 0 0 28px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
  max-width: 40em;
}

.crowd-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px 20px;
}

.crowd-citizen {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: auto auto;
  column-gap: 12px;
  align-items: center;
  padding: 10px 0;
  border-top: 1px solid var(--p-line);
  min-width: 0;
}

.crowd-citizen .coin { grid-row: 1 / span 2; }

.crowd-name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  color: var(--p-ink);
  line-height: 1.1;
  overflow-wrap: anywhere;
}

.crowd-role {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}


.quiet-note {
  margin: 0;
  padding: 48px var(--p-gutter);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
  text-align: center;
}

/* ---- The invitation over the square, once the argument is over ---- */
/* The corner is trees and altar in both paintings, off the walkable ground,
   so the invitation never covers a citizen. */
.square-invite {
  position: absolute;
  left: 3%;
  bottom: 4%;
  z-index: 60;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 0 20px;
  border: 1px solid var(--p-gold);
  background: rgba(11, 14, 19, 0.78);
  -webkit-backdrop-filter: blur(6px);
  backdrop-filter: blur(6px);
  color: var(--p-ink);
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-style: italic;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
  transition: background 0.2s ease, color 0.2s ease;
}

.square-invite svg { color: var(--p-gold); flex-shrink: 0; }
.square-invite:hover { background: rgba(240, 182, 96, 0.18); }

/* ---- The record ---- */
.record {
  padding: 8px var(--p-gutter) 56px;
}

.round { scroll-margin-top: 0; }

.round-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 16px;
  margin: 28px 0 10px;
  padding-top: 14px;
  border-top: 1px solid var(--p-line-strong);
  font-weight: 400;
}

.round:first-child .round-head { margin-top: 12px; }

.round-day {
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink);
}

.round-said {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  margin-left: auto;
}

.cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 32px;
}

.col { min-width: 0; }
.stoa-col { border-left: 1px solid var(--p-line); padding-left: 32px; }

.entries {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.col-empty {
  margin: 8px 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-4);
}

/* Speech: the coin, the name, the verb, the words */
.entry {
  position: relative;
  isolation: isolate;
  min-width: 0;
}

/* The line a ribbon settled into: lit for a moment */
.entry.lit::before {
  content: '';
  position: absolute;
  inset: -8px -12px;
  z-index: -1;
  background: rgba(240, 182, 96, 0.14);
  box-shadow: inset 2px 0 0 var(--p-gold);
  pointer-events: none;
  animation: lit 2.8s ease-out forwards;
}

@keyframes lit {
  0%, 35% { opacity: 1; }
  100% { opacity: 0; }
}

.reduced .entry.lit::before { animation: none; opacity: 1; }

/* A citizen held up in the square: every line of theirs carries a gold rule */
.entry.held::after {
  content: '';
  position: absolute;
  top: -4px;
  bottom: -4px;
  left: -12px;
  width: 2px;
  background: var(--p-gold);
  pointer-events: none;
}

.who {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: 12px;
  align-items: center;
  margin-bottom: 6px;
}

.who .coin { grid-row: 1 / span 2; }

.name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  line-height: 1.1;
  color: var(--p-ink);
  overflow-wrap: anywhere;
}

.verb {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  line-height: 1.3;
}

.also { color: var(--p-ochre-deep, var(--p-ochre)); }

/* The Stoa heard the same words: one quiet line, not twenty cards */
.entry.echo {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.words {
  margin: 0 0 0 52px;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.quoted {
  margin: 8px 0 0 52px;
  padding: 2px 0 2px 14px;
  border-left: 1px solid var(--p-line-strong);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.55;
  color: var(--p-ink-3);
}

.quoted-who {
  display: block;
  font-family: var(--p-font-display);
  font-style: normal;
  font-weight: 600;
  font-size: var(--t-md);
  color: var(--p-ink-2);
}

/* Stoa answers sit indented under an ochre rule */
.entry.reply {
  margin-left: 18px;
  padding-left: 16px;
  border-left: 2px solid var(--p-ochre);
}

/* The crowd moving: one quiet line */
.entry.quiet {
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
  padding-left: 52px;
}

.quiet-name {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  color: var(--p-ink-2);
  margin-right: 0.35em;
}

/* Arrival: fade and rise, 240ms, staggered by the hook */
.entry-enter-active { transition: opacity 0.24s ease, transform 0.24s ease; }
.entry-enter-from { opacity: 0; transform: translateY(8px); }
.entry-leave-active { transition: opacity 0.16s ease; }
.entry-leave-to { opacity: 0; }

/* ---- Phones and narrow stages ---- */
@media (max-width: 899px) {
  /* The band reads once and scrolls away; only the choice of square stays. */
  .clock-band {
    position: static;
    padding: 14px 16px 0;
    gap: 10px;
    backdrop-filter: none;
  }

  .clock-line { font-size: var(--t-lg); }
  .clock { flex-basis: 100%; }
  .controls { order: 2; flex-basis: 100%; justify-content: flex-start; padding-bottom: 12px; }
  .sun-row { order: 1; }
  .again, .scribe-note { order: 3; }
  .control-with-hint { align-items: flex-start; }
  .square-heads { display: none; }

  .square-tabs {
    position: sticky;
    top: var(--p-header-h);
    z-index: 20;
    display: flex;
    margin: 0 -16px;
    padding: 0 16px;
    background: var(--p-bg);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--p-line);
  }

  .crowd { padding: 28px 16px 40px; }
  .crowd-list { grid-template-columns: 1fr; gap: 0; }
  .record { padding: 0 16px 48px; }
  .sun-row { gap: 8px 10px; }
  .sun-row .sun { flex-basis: 160px; }
  .square-invite { font-size: var(--t-md); padding: 0 14px; bottom: 3%; left: 3%; }
  .cols { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .stoa-col { border-left: 0; padding-left: 0; }
  .tab-agora .stoa-col { display: none; }
  .tab-stoa .agora-col { display: none; }
  .words, .quoted { margin-left: 0; }
  .entry.quiet { padding-left: 0; }
  .entry.reply { margin-left: 8px; padding-left: 12px; }
  .quiet-note { padding: 32px 16px; }
  .trouble { margin-inline: 16px; }
}

/* A narrow stage beside the open Web: one column too */
@media (min-width: 900px) and (max-width: 1280px) {
  .cols { gap: 24px; }
  .stoa-col { padding-left: 24px; }
  .square-heads { gap: 24px; }
  .square-heads .square-head:last-child { padding-left: 24px; }
}

@media (prefers-reduced-motion: reduce) {
  .sun-dot { transition: none; animation: none; }
  .entry.lit::before { animation: none; opacity: 1; }
}
</style>
