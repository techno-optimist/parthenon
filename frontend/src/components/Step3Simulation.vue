<template>
  <section class="agora" :class="[`mode-${mode}`, `tab-${tab}`]" aria-labelledby="agora-clock">
    <!-- The day clock: the round as the sun crossing the square, in words. -->
    <header ref="bandEl" class="clock-band">
      <div class="clock">
        <p id="agora-clock" class="clock-line">
          <span class="clock-round">{{ clockRound }}</span>
          <template v-if="mode !== 'idle' && mode !== 'loading'">
            <span class="clock-sep" aria-hidden="true">·</span>
            <span class="clock-day">{{ clockDay }}</span>
          </template>
          <span class="clock-sep" aria-hidden="true">·</span>
          <span class="clock-said">{{ clockSaid }}</span>
        </p>
        <!-- One polite voice per act: it speaks when the round turns, not on every poll. -->
        <p class="sr-only" aria-live="polite">{{ announcement }}</p>

        <div v-if="mode === 'done' || mode === 'error'" class="sun">
          <input
            v-model.number="scrubRound"
            type="range"
            class="sun-range"
            :min="0"
            :max="scrubMax"
            :step="1"
            :aria-label="unit.goTo"
            :aria-valuetext="scrubText"
            :disabled="!rounds.length"
            @input="goToRound(scrubRound)"
            @change="goToRound(scrubRound)"
          />
          <span class="sun-dot" :style="{ left: `${sunPercent}%` }" aria-hidden="true"></span>
        </div>
        <div
          v-else
          class="sun"
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
      </div>

      <div class="controls">
        <!-- Never run: one explicit act -->
        <template v-if="mode === 'idle'">
          <button type="button" class="p-button" :disabled="isStarting" @click="doStartSimulation(false)">
            {{ isStarting ? $t('agora.idle.opening') : $t('agora.idle.open') }}
          </button>
        </template>

        <!-- Live: stop and write, or leave it -->
        <template v-else-if="mode === 'live'">
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
        </template>

        <!-- Finished: the Chronicle, and the way to hold it again. A Chronicle
             the Scribe never finished is no Chronicle: it can be written again. -->
        <template v-else-if="mode === 'done' || mode === 'error'">
          <button v-if="hasChronicle" type="button" class="p-button" @click="readChronicle">{{ $t('agora.done.read') }}</button>
          <button v-else type="button" class="p-button" :disabled="isGeneratingReport || !rounds.length" @click="writeChronicle(true)">
            {{ isGeneratingReport ? $t('agora.done.writing') : scribeFailed ? $t('agora.done.writeAgain') : $t('agora.done.write') }}
          </button>
          <button type="button" class="p-button ghost" :aria-expanded="againOpen" :disabled="isStarting" @click="againOpen = !againOpen">
            {{ isStarting ? $t('agora.idle.opening') : $t('agora.done.again') }}
          </button>
        </template>
      </div>

      <!-- Holding the argument again has a cost, and it is named before anything is cleared. -->
      <div v-if="againOpen && (mode === 'done' || mode === 'error')" class="again">
        <p class="again-cost">{{ $t('agora.done.againCost') }}</p>
        <div class="again-actions">
          <button type="button" class="p-button small" :disabled="isStarting" @click="doStartSimulation(true)">{{ $t('agora.done.againConfirm') }}</button>
          <button type="button" class="p-button secondary small" @click="againOpen = false">{{ $t('agora.done.againCancel') }}</button>
        </div>
      </div>

      <!-- The Scribe's last attempt broke off: say so, with the cause behind a disclosure -->
      <div v-if="scribeFailed && !isGeneratingReport && (mode === 'done' || mode === 'error')" class="scribe-note">
        <p class="scribe-note-text">{{ $t('agora.done.scribeFailed') }}</p>
        <details v-if="reportTrouble" class="trouble-detail">
          <summary>{{ $t('agora.done.scribeWhy') }}</summary>
          <p>{{ reportTrouble }}</p>
        </details>
      </div>

      <!-- On wide screens, the two squares named above their columns -->
      <div v-if="mode !== 'idle'" class="square-heads" aria-hidden="true">
        <span class="square-head">{{ platformName('twitter', 'title') }}</span>
        <span class="square-head">{{ platformName('reddit', 'title') }}</span>
      </div>
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

    <!-- The gathered crowd, before the square opens -->
    <section v-if="mode === 'idle'" class="crowd" aria-labelledby="crowd-lede">
      <p class="p-eyebrow">{{ $t('agora.idle.eyebrow') }}</p>
      <h2 id="crowd-lede" class="crowd-lede">{{ profilesLoading ? $t('agora.idle.loading') : $t('agora.idle.lede', profiles.length) }}</h2>
      <p class="crowd-cost">{{ costLine }}</p>
      <ul v-if="profiles.length" class="crowd-list" role="list">
        <li v-for="p in profiles" :key="p.user_id ?? p.username ?? p.name" class="crowd-citizen">
          <span class="p-coin coin" :style="{ '--role': roleOf(p.user_id) }" aria-hidden="true">{{ initialOf(displayName(p.name, p.username)) }}</span>
          <span class="crowd-name">{{ displayName(p.name, p.username) }}</span>
          <span class="crowd-role">{{ roleWordOf(p.user_id) || p.profession || '' }}</span>
        </li>
      </ul>
    </section>

    <!-- Loading beat -->
    <p v-else-if="mode === 'loading'" class="quiet-note">{{ $t('common.loading') }}</p>

    <!-- The square: the argument, round by round, the Agora beside the Stoa -->
    <div v-else class="square">
      <!-- On phones, one column and a choice of square -->
      <div class="square-tabs" role="group" :aria-label="$t('agora.squares.which')">
        <button type="button" class="square-tab" :aria-pressed="tab === 'agora'" @click="tab = 'agora'">{{ platformName('twitter', 'title') }}</button>
        <button type="button" class="square-tab" :aria-pressed="tab === 'stoa'" @click="tab = 'stoa'">{{ platformName('reddit', 'title') }}</button>
      </div>

      <p v-if="!rounds.length && mode === 'live'" class="quiet-note">{{ $t('agora.live.opening') }}</p>
      <p v-else-if="!rounds.length" class="quiet-note">{{ $t('agora.empty.record') }}</p>

      <section
        v-for="round in rounds"
        :id="`round-${round.n}`"
        :key="round.n"
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
              <li v-for="e in round.agora" :key="e.id" class="entry" :class="e.kind" :data-stagger="e.stagger">
                <template v-if="e.kind === 'speech'">
                  <span class="who">
                    <span class="p-coin coin" :style="{ '--role': e.color }" aria-hidden="true">{{ e.initial }}</span>
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
              <li v-for="e in round.stoa" :key="e.id" class="entry" :class="[e.kind, { reply: e.reply }]" :data-stagger="e.stagger">
                <template v-if="e.kind === 'echo'">
                  <span class="echo-text">{{ e.text }}</span>
                </template>
                <template v-else-if="e.kind === 'speech'">
                  <span class="who">
                    <span class="p-coin coin" :style="{ '--role': e.color }" aria-hidden="true">{{ e.initial }}</span>
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
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  startSimulation,
  stopSimulation,
  getRunStatus,
  getRunStatusDetail,
  getSimulationActions,
  getSimulationTimeline,
  getSimulationProfiles
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

const { t } = useI18n()
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
  reportTrouble: { type: String, default: '' }
})

const emit = defineEmits(['add-log', 'update-status', 'finished'])

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
const announcement = ref('')

const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

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
const roleOf = (id) => citizensById.value.get(String(id))?.color || 'var(--p-gold)'
const roleWordOf = (id) => citizensById.value.get(String(id))?.role || ''
const displayName = (name, username) => citizenName(name, username)
const initialOf = (name) => (String(name || '').trim().charAt(0) || '?').toUpperCase()

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
  const fromRecord = rounds.value.length ? rounds.value[rounds.value.length - 1].n : 0
  return Math.max(runStatus.value.current_round || 0, fromRecord)
})
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
  return unitAt(currentRound.value, totalRounds.value)
})
const clockDay = computed(() => dayOf(mode.value === 'idle' || mode.value === 'loading' ? 0 : currentRound.value))
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
      return args.original_content ? `${base}: “${short(args.original_content, 90)}”` : base
    }
    case 'FOLLOW':
      return t('agora.quiet.follows', { who: who(args.target_user_name || args.target_user) })
    case 'UNFOLLOW':
      return t('agora.quiet.unfollows', { who: who(args.target_user_name || args.target_user) })
    case 'MUTE':
      return t('agora.quiet.mutes', { who: who(args.target_user_name || args.target_user) })
    case 'SEARCH_POSTS':
    case 'SEARCH':
      return t('agora.quiet.asksAround', { what: short(args.query, 60) })
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
    agentId: String(a.agent_id),
    name,
    initial: initialOf(name),
    color: citizen?.color || 'var(--p-gold)',
    stagger: a._stagger || 0
  }
  const content = args.content ?? args.quote_content ?? ''
  if (isSpeech(type) || (content && !['REPOST'].includes(type))) {
    const entry = { ...base, kind: 'speech', text: String(content), verbLine: actionVerb(type), reply: false, quoted: '', quotedWho: '' }
    if (type === 'CREATE_COMMENT' || type === 'COMMENT' || type === 'REPLY') {
      entry.reply = true
      entry.verbLine = t('agora.speech.answers')
    }
    if (type === 'QUOTE_POST' || type === 'QUOTE') {
      entry.verbLine = t('agora.speech.quotes', { who: who(args.original_author_name) })
      entry.quoted = short(args.original_content, 220)
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
    } else {
      out.push(entry)
    }
  }
  for (const e of out) if (e.kind === 'quiet') e.text = joinPhrases(e.phrases)
  return out
}

const rounds = computed(() => {
  const byRound = new Map()
  for (const a of sortedActions.value) {
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
    for (const e of r.agora) if (e.kind === 'speech') spokenInAgora.set(wordsKey(e), e)
    r.stoa = r.stoa.filter((e) => {
      if (e.kind !== 'speech') return true
      const twin = spokenInAgora.get(wordsKey(e))
      if (!twin) return true
      twin.alsoStoa = true
      r.echoed += 1
      return false
    })
    r.agora = settleColumn(r.agora)
    r.stoa = settleColumn(r.stoa)
    if (r.echoed) {
      r.stoa.unshift({ id: `echo-${r.n}`, kind: 'echo', agentId: '', stagger: 0, text: t('agora.empty.stoaEcho', { n: r.echoed }, r.echoed) })
    }
    r.said = r.agora.filter((e) => e.kind === 'speech').length + r.stoa.filter((e) => e.kind === 'speech').length
  }
  return list
})

// ---- The scrubber (replay) ----
const scrubMax = computed(() => Math.max(currentRound.value, rounds.value.length ? rounds.value[rounds.value.length - 1].n : 0, 0))
const scrubText = computed(() =>
  t('agora.scrubber.value', { unit: unit.value.cap, n: scrubRound.value, total: totalRounds.value || scrubMax.value, day: dayOf(scrubRound.value) })
)
const goToRound = (n) => {
  let target = null
  for (const r of rounds.value) {
    if (r.n <= n) target = r
    else break
  }
  if (!target) target = rounds.value[0]
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
  if (reduced) return
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
  for (const action of actions || []) {
    const id = action.id || `${action.timestamp}-${action.platform}-${action.agent_id}-${action.action_type}`
    if (actionIds.has(id)) continue
    actionIds.add(id)
    allActions.value.push({ ...action, _uniqueId: id, _stagger: batchIndex++ })
  }
}

const resetRecord = () => {
  runStatus.value = {}
  allActions.value = []
  actionIds.clear()
  prevTwitterRound = 0
  prevRedditRound = 0
  trouble.value = null
  stopPolling()
}

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

const fetchRunStatus = async () => {
  if (!props.simulationId) return
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
      await fetchRunStatusDetail()
      finishRun('failed', data)
    } else if (s === 'completed' || s === 'stopped') {
      await fetchRunStatusDetail()
      finishRun(s, data)
    }
  } catch (err) {
    console.warn('The square could not be read:', err)
  }
}

const fetchRunStatusDetail = async () => {
  if (!props.simulationId) return
  try {
    const res = await getRunStatusDetail(props.simulationId)
    if (res.success && res.data) absorb(res.data.all_actions || [])
  } catch (err) {
    console.warn('The record could not be read:', err)
  }
}

const finishRun = (how, data) => {
  stopPolling()
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
      getSimulationTimeline(props.simulationId, 0)
    ])
    absorb(actionsRes?.data?.actions || [])
    // The record spans every hour the square was open, quiet ones included.
    const span = Math.max(currentRound.value, timelineRes?.data?.rounds_count ?? 0, rounds.value.length)
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
      await fetchRunStatusDetail()
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

onUnmounted(() => stopPolling())

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
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 12px 32px;
  padding: 18px var(--p-gutter) 0;
  background: rgba(11, 14, 19, 0.92);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--p-line);
}

.clock { min-width: 0; }

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

/* The sun over the square: a rule, and a gold dot that crosses it. The strip
   is 32px tall so a thumb on a phone finds the scrubber. */
.sun {
  position: relative;
  height: 32px;
  margin-top: 6px;
}

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

/* Controls */
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px 12px;
  padding-bottom: 14px;
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
  grid-column: 1 / -1;
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
  grid-column: 1 / -1;
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

/* The two squares named above their columns */
.square-heads {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 32px;
}

.square-head {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
  padding: 6px 0 10px;
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

.coin {
  --role: var(--p-gold);
  border-color: var(--role);
  color: var(--role);
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

/* ---- The square ---- */
.square {
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
.entry { min-width: 0; }

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
  margin: 0 0 0 48px;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.quoted {
  margin: 8px 0 0 48px;
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
  padding-left: 48px;
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
    grid-template-columns: minmax(0, 1fr);
    padding: 14px 16px 0;
    gap: 10px;
    backdrop-filter: none;
  }

  .clock-line { font-size: var(--t-lg); }
  .controls { justify-content: flex-start; padding-bottom: 12px; }
  .control-with-hint { align-items: flex-start; }
  .square-heads { display: none; }

  .square-tabs {
    position: sticky;
    top: var(--p-header-h);
    z-index: 20;
    display: flex;
    margin: 0 -16px;
    padding: 0 16px;
    background: rgba(11, 14, 19, 0.94);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--p-line);
  }

  .crowd { padding: 28px 16px 40px; }
  .crowd-list { grid-template-columns: 1fr; gap: 0; }
  .square { padding: 0 16px 48px; }
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
}
</style>
