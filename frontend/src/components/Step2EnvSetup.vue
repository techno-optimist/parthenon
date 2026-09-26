<template>
  <section class="gathering">
    <!-- The summons: how many have come, and what the Scribe is doing. -->
    <header class="summons">
      <span class="p-eyebrow">{{ $t('parthenon.gathering.place') }}</span>
      <h2 class="summons-title" aria-live="polite">{{ countLine }}</h2>
      <p class="summons-lede">{{ stateLine }}</p>
    </header>

    <!-- Trouble, in the city's voice, with the cause behind a disclosure. -->
    <div v-if="troubleMessage" class="trouble" role="alert">
      <p class="trouble-title">{{ $t('parthenon.gathering.trouble') }}</p>
      <details class="trouble-why">
        <summary>{{ $t('parthenon.gathering.troubleWhy') }}</summary>
        <p>{{ troubleMessage }}</p>
      </details>
      <button type="button" class="p-button secondary small" @click="callAgain">{{ $t('parthenon.gathering.tryAgain') }}</button>
    </div>

    <!-- The slope: citizens arrive one by one; the seats still empty are drawn faint. -->
    <ol v-if="citizens.length || emptySeats" class="slope" :aria-label="$t('parthenon.gathering.citizens')">
      <li v-for="(c, i) in citizens" :key="c.key" class="seat" :style="{ '--i': Math.min(i, 24) }">
        <button type="button" class="citizen" :aria-label="$t('parthenon.gathering.openCard', { name: c.name })" @click="openCard(c, $event)">
          <span class="p-coin" :style="{ color: c.color, borderColor: c.color }" aria-hidden="true">{{ c.initial }}</span>
          <span class="citizen-body">
            <span class="citizen-name">{{ c.name }}</span>
            <span class="citizen-role">{{ c.role }}</span>
            <span class="citizen-line">{{ c.line }}</span>
          </span>
        </button>
      </li>
      <li v-for="n in emptySeats" :key="'empty-' + n" class="seat empty" aria-hidden="true">
        <span class="p-coin"></span>
        <span class="citizen-body"><span class="ghost-line long"></span><span class="ghost-line"></span></span>
      </li>
    </ol>

    <!-- The city's hours, in words. -->
    <section v-if="hours" class="block hours">
      <span class="p-eyebrow">{{ $t('parthenon.gathering.hours.eyebrow') }}</span>
      <h3 class="block-title">{{ $t('parthenon.gathering.hours.title') }}</h3>
      <p class="prose">{{ hours.day }}</p>
      <p class="prose">{{ hours.awake }}</p>
      <p v-if="hours.loudest" class="prose">{{ hours.loudest }}</p>
    </section>

    <!-- The first words: what the city is already saying. -->
    <section v-if="openings.length || topics.length" class="block saying">
      <span class="p-eyebrow">{{ $t('parthenon.gathering.saying.eyebrow') }}</span>
      <h3 class="block-title">{{ $t('parthenon.gathering.saying.title') }}</h3>
      <ul v-if="topics.length" class="topics" :aria-label="$t('parthenon.gathering.saying.topics')">
        <li v-for="topic in topics" :key="topic" class="topic">{{ topic }}</li>
      </ul>
      <ol v-if="openings.length" class="openings">
        <li v-for="(o, i) in shownOpenings" :key="i" class="opening" :style="{ '--i': i }">
          <span class="p-coin small" :style="{ color: o.color, borderColor: o.color }" aria-hidden="true">{{ o.initial }}</span>
          <div class="opening-body">
            <span class="opening-who">{{ o.name }}<span v-if="o.role" class="opening-role"> · {{ o.role }}</span></span>
            <p class="opening-text">{{ o.text }}</p>
          </div>
        </li>
      </ol>
      <button v-if="openings.length > 4" type="button" class="p-button ghost small" :aria-expanded="showAllOpenings" @click="showAllOpenings = !showAllOpenings">
        {{ showAllOpenings ? $t('parthenon.gathering.saying.less') : $t('parthenon.gathering.saying.more', { n: openings.length - 4 }) }}
      </button>
    </section>

    <!-- How long the city talks: story-sized lengths, honest minutes. -->
    <section v-if="simulationConfig" class="block length">
      <span class="p-eyebrow">{{ $t('parthenon.gathering.length.eyebrow') }}</span>
      <h3 class="block-title" id="length-title">{{ lengthTitle }}</h3>
      <p class="prose muted" aria-live="polite">{{ lengthHint }}</p>
      <div class="lengths" role="radiogroup" aria-labelledby="length-title">
        <button
          v-for="l in lengths"
          :key="l.id"
          type="button"
          role="radio"
          class="length-option"
          :aria-checked="chosenLength === l.id"
          :aria-disabled="l.beyond || undefined"
          :tabindex="chosenLength === l.id ? 0 : -1"
          @click="chooseLength(l)"
          @keydown="onLengthKey($event, l)"
        >
          <span class="length-name">{{ l.name }}</span>
          <span class="length-meta">{{ l.hoursLabel }}</span>
          <span class="length-meta">{{ l.minutesLabel }}</span>
          <span v-if="l.beyond" class="length-note">{{ $t('parthenon.gathering.length.beyond') }}</span>
        </button>
      </div>
    </section>

    <!-- The doors. -->
    <footer class="doors">
      <button type="button" class="p-button ghost" @click="$emit('go-back')">{{ $t('parthenon.gathering.back') }}</button>
      <div class="door-main">
        <span v-if="troubleMessage" class="door-reason">{{ $t('parthenon.gathering.openTrouble') }}</span>
        <span v-else-if="phase < 4" class="door-reason">{{ $t('parthenon.gathering.openWait') }}</span>
        <button type="button" class="p-button" :disabled="phase < 4 || !!troubleMessage" @click="handleStartSimulation">{{ $t('parthenon.gathering.open') }}</button>
      </div>
    </footer>

    <!-- A citizen's card, on parchment, held up in the dark. -->
    <Teleport to="body">
      <Transition name="card">
        <div v-if="selected" class="veil" @click.self="closeCard">
          <div
            ref="cardEl"
            class="card p-paper"
            role="dialog"
            aria-modal="true"
            aria-labelledby="citizen-card-name"
            @keydown="onCardKey"
          >
            <button ref="closeBtn" type="button" class="card-close" :aria-label="$t('parthenon.gathering.card.close')" @click="closeCard">
              <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 4l12 12M16 4L4 16" /></svg>
            </button>
            <div class="card-head">
              <span class="p-coin big" :style="{ color: selected.color, borderColor: selected.color }" aria-hidden="true">{{ selected.initial }}</span>
              <div class="card-id">
                <span class="p-eyebrow">{{ $t('parthenon.gathering.card.eyebrow') }}<template v-if="selected.role"> · {{ selected.role }}</template></span>
                <h3 id="citizen-card-name" class="card-name">{{ selected.name }}</h3>
                <p v-if="selected.profession" class="card-profession">{{ selected.profession }}</p>
              </div>
            </div>
            <div class="p-meander" aria-hidden="true"></div>
            <section class="card-section">
              <h4 class="p-eyebrow">{{ $t('parthenon.gathering.card.past') }}</h4>
              <p class="card-prose">{{ selected.past || $t('parthenon.gathering.card.nothing') }}</p>
            </section>
            <section v-if="selected.topics.length" class="card-section">
              <h4 class="p-eyebrow">{{ $t('parthenon.gathering.card.cares') }}</h4>
              <ul class="card-topics">
                <li v-for="topic in selected.topics" :key="topic" class="topic">{{ topic }}</li>
              </ul>
            </section>
          </div>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup>
// Act Β΄, the stage: the Pnyx slope filling with citizens called from the Web of
// Athens. The engine's preparation (profiles, then the time and event
// configuration) is polled exactly as before; what changes is that every word a
// visitor reads is the city's, and the wiring goes to the scribe's ledger.
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import {
  prepareSimulation,
  getPrepareStatus,
  getSimulationProfilesRealtime,
  getSimulationConfigRealtime
} from '../api/simulation'
import pendingUpload from '../store/pendingUpload'
import { entityTypeName, roleColorVar, citizenName, stripIds, RUN_LENGTHS } from '../parthenon/vocabulary.js'

const { t } = useI18n()
const route = useRoute()

const props = defineProps({
  simulationId: String,
  projectData: Object,
  graphData: Object
})

const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

// The length chosen on the steps rides here three ways: on the route, in this
// tab's storage (which the home page writes and this act binds to the first
// gathering that reads it, so an older gathering opened later ignores it) and
// on the pending record. Whichever is found seeds the choice below.
const RUN_LENGTH_KEY = 'parthenon.runLength'
const lengthById = (id) => RUN_LENGTHS.find((l) => l.id === id) || null
const lengthByRounds = (rounds) => RUN_LENGTHS.find((l) => l.rounds === Number(rounds)) || null

const readCarriedLength = () => {
  const fromRoute = lengthByRounds(route.query.maxRounds)
  if (fromRoute) return fromRoute
  try {
    const raw = sessionStorage.getItem(RUN_LENGTH_KEY)
    if (raw) {
      const record = JSON.parse(raw) || {}
      const found = lengthById(record.id) || lengthByRounds(record.rounds)
      const ours = !record.simulationId || record.simulationId === props.simulationId
      if (found && ours) {
        if (!record.simulationId && props.simulationId) {
          sessionStorage.setItem(RUN_LENGTH_KEY, JSON.stringify({ ...record, simulationId: props.simulationId }))
        }
        return found
      }
    }
  } catch {
    // storage blocked or unreadable; the record may still carry it
  }
  return lengthByRounds(pendingUpload.maxRounds)
}

const carriedLength = readCarriedLength()

// State
const phase = ref(0) // 0 reading, 1 citizens arriving, 2 hours being set, 4 complete
const taskId = ref(null)
const currentStage = ref('')
const profiles = ref([])
const expectedTotal = ref(null)
const simulationConfig = ref(null)
const troubleMessage = ref('')
const selected = ref(null)
const showAllOpenings = ref(false)
const chosenLength = ref(carriedLength?.id || 'day')

let lastLoggedMessage = ''
let lastLoggedProfileCount = 0
let lastLoggedConfigStage = ''
let pollTimer = null
let profilesTimer = null
let configTimer = null

const addLog = (msg) => emit('add-log', msg)

// Engine words that reach the ledger are softened on the way.
const cityWords = (text) =>
  stripIds(text)
    .replace(/\bagents\b/gi, 'citizens')
    .replace(/\bagent\b/gi, 'citizen')
    .replace(/\bprofiles?\b/gi, (m) => (m.toLowerCase().endsWith('s') ? 'pasts' : 'past'))
    .replace(/\bLLM\b/g, 'the Scribe')

// --- Who is who -------------------------------------------------------------

// The Web of Athens knows each name's kind; the engine's citizen list does not.
const typeByName = computed(() => {
  const map = new Map()
  const put = (name, type) => {
    if (!name || !type) return
    map.set(String(name).trim().toLowerCase(), type)
  }
  for (const node of props.graphData?.nodes || []) {
    const labels = (node.labels || []).filter((l) => l !== 'Entity')
    put(node.name, labels[labels.length - 1] || (node.labels?.includes('Entity') ? 'Person' : ''))
  }
  for (const a of simulationConfig.value?.agent_configs || []) put(a.entity_name, a.entity_type)
  return map
})

const typeFor = (name) => typeByName.value.get(String(name || '').trim().toLowerCase()) || ''

// A role is one family word, the way the Agora writes it: the entity type
// when the Web knows one, otherwise the profession cut at the first comma,
// "of", "at" or "and", in lower case unless it starts with a proper noun
// or an acronym ("AI researcher" keeps its case, "Head teacher of the only
// local school" becomes "head teacher").
const familyCase = (label) => {
  const first = label.split(/\s+/)[0] || ''
  if (/^[A-Z][a-z'-]*$/.test(first)) return label.charAt(0).toLowerCase() + label.slice(1)
  return label
}

const shortProfession = (profession) => {
  const raw = String(profession || '').trim()
  if (!raw) return ''
  const first = raw.split(/[;,(]|\s+(?:and|of|at|for|who)\s+/)[0].trim()
  const cut = first.length > 56 ? first.slice(0, 56).replace(/\s+\S*$/, '') : first
  return familyCase(cut)
}

const roleLabel = (type, profession) => {
  const named = entityTypeName(type)
  if (named && named !== 'citizen') return named
  return shortProfession(profession) || named || t('parthenon.gathering.citizen')
}

// The first sentence of a bio, without stopping at "Dr." or "Mrs.".
const ABBREVIATION = /\b(Dr|Mr|Mrs|Ms|St|Fr|Prof|Sr|Jr|vs|etc|No)\.$/i
const firstSentence = (text) => {
  const raw = String(text || '').trim()
  if (!raw) return ''
  let sentence = ''
  for (const part of raw.split(/(?<=[.!?])\s+/)) {
    sentence = sentence ? `${sentence} ${part}` : part
    if (!ABBREVIATION.test(sentence)) break
  }
  return sentence.length > 160 ? sentence.slice(0, 160).replace(/\s+\S*$/, '') : sentence
}

const initialOf = (name) => {
  const word = String(name || '').replace(/^(dr\.?|father|mrs?\.?|ms\.?|the)\s+/i, '').trim()
  return (word || name || '?').charAt(0).toUpperCase()
}

const citizens = computed(() =>
  profiles.value.map((p, idx) => {
    const name = citizenName(p.name, p.username) || t('parthenon.gathering.citizen')
    const type = typeFor(p.name)
    return {
      key: p.username || p.user_id || `${name}-${idx}`,
      name,
      initial: initialOf(name),
      color: roleColorVar(type || p.profession),
      role: roleLabel(type, p.profession),
      profession: String(p.profession || '').trim(),
      line: firstSentence(p.bio),
      past: String(p.persona || p.bio || '').trim(),
      topics: Array.isArray(p.interested_topics) ? p.interested_topics.filter(Boolean) : []
    }
  })
)

const emptySeats = computed(() => {
  const expected = Number(expectedTotal.value) || 0
  if (phase.value >= 4 || !expected) return 0
  return Math.max(0, Math.min(40, expected - profiles.value.length))
})

// --- Words at the top --------------------------------------------------------

const countLine = computed(() => {
  const n = profiles.value.length
  const total = Number(expectedTotal.value) || 0
  if (!n) return t('parthenon.gathering.nobodyYet')
  if (total && n >= total) return t('parthenon.gathering.arrivedAll', { total })
  if (total) return t('parthenon.gathering.arrived', { n, total })
  return t('parthenon.gathering.arrivedSome', { n })
})

const stateLine = computed(() => {
  if (troubleMessage.value) return t('parthenon.gathering.stateTrouble')
  if (phase.value >= 4) return t('parthenon.gathering.hoursSet')
  if (phase.value >= 2) return t('parthenon.gathering.settingHours')
  if (!profiles.value.length && phase.value === 0) return t('parthenon.gathering.reading')
  if (!profiles.value.length) return `${t('parthenon.gathering.summoning')} ${t('parthenon.gathering.firstTakeAMinute')}`
  return t('parthenon.gathering.summoning')
})

// --- The city's hours --------------------------------------------------------

const hour12 = (h) => {
  const x = ((h % 24) + 24) % 24
  return x === 0 ? 12 : x > 12 ? x - 12 : x
}

const clockWord = (h) => {
  const x = ((h % 24) + 24) % 24
  if (x === 0) return t('parthenon.gathering.clock.midnight')
  if (x === 12) return t('parthenon.gathering.clock.noon')
  if (x < 12) return t('parthenon.gathering.clock.morning', { h: hour12(x) })
  if (x < 18) return t('parthenon.gathering.clock.afternoon', { h: hour12(x) })
  if (x < 21) return t('parthenon.gathering.clock.evening', { h: hour12(x) })
  return t('parthenon.gathering.clock.night', { h: hour12(x) })
}

const partOfDay = (h) => {
  const x = ((h % 24) + 24) % 24
  if (x === 0) return t('parthenon.gathering.clock.midnight')
  if (x < 5) return t('parthenon.gathering.parts.small')
  if (x < 8) return t('parthenon.gathering.parts.dawn')
  if (x < 12) return t('parthenon.gathering.parts.morning')
  if (x < 14) return t('parthenon.gathering.parts.midday')
  if (x < 18) return t('parthenon.gathering.parts.afternoon')
  if (x < 21) return t('parthenon.gathering.parts.evening')
  return t('parthenon.gathering.parts.late')
}

const joinNames = (names) => {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} ${t('parthenon.gathering.hours.and')} ${names[names.length - 1]}`
}

const hours = computed(() => {
  const tc = simulationConfig.value?.time_config
  if (!tc) return null
  const offPeak = new Set((tc.off_peak_hours || []).map(Number))
  const dayHours = Array.from({ length: 24 }, (_, h) => h).filter((h) => !offPeak.has(h))
  const start = dayHours.length ? Math.min(...dayHours) : 6
  const end = dayHours.length ? Math.max(...dayHours) + 1 : 22
  const peak = (tc.peak_hours || []).map(Number)
  const peakFrom = peak.length ? Math.min(...peak) : 18
  const peakTo = peak.length ? Math.max(...peak) + 1 : 22
  const peakPhrase = t('parthenon.gathering.hours.peakSpan', {
    part: partOfDay(peakFrom),
    from: hour12(peakFrom),
    to: clockWord(peakTo)
  })
  const loud = (simulationConfig.value?.agent_configs || [])
    .map((a) => ({ name: citizenName(a.entity_name), rate: (Number(a.posts_per_hour) || 0) + (Number(a.comments_per_hour) || 0) }))
    .filter((a) => a.name)
    .sort((a, b) => b.rate - a.rate)
    .slice(0, 3)
    .map((a) => a.name)
  return {
    day: t('parthenon.gathering.hours.day', { start: partOfDay(start), end: partOfDay(end), peak: peakPhrase }),
    awake: t('parthenon.gathering.hours.awake', { max: tc.agents_per_hour_max ?? '?', min: tc.agents_per_hour_min ?? '?' }),
    loudest: loud.length ? t('parthenon.gathering.hours.loudest', { names: joinNames(loud) }) : ''
  }
})

// --- The first words ---------------------------------------------------------

const topics = computed(() => (simulationConfig.value?.event_config?.hot_topics || []).filter(Boolean))

const openings = computed(() =>
  (simulationConfig.value?.event_config?.initial_posts || []).map((post) => {
    const profile = profiles.value[post.poster_agent_id]
    const name = profile ? citizenName(profile.name, profile.username) : t('parthenon.gathering.saying.someone')
    const type = post.poster_type || typeFor(profile?.name)
    return {
      name,
      initial: initialOf(name),
      color: roleColorVar(type || profile?.profession),
      role: roleLabel(type, profile?.profession),
      text: String(post.content || '').trim()
    }
  })
)

const shownOpenings = computed(() => (showAllOpenings.value ? openings.value : openings.value.slice(0, 4)))

// --- How long the city talks ------------------------------------------------

const autoGeneratedRounds = computed(() => {
  const tc = simulationConfig.value?.time_config
  if (!tc?.total_simulation_hours || !tc?.minutes_per_round) return null
  return Math.floor((tc.total_simulation_hours * 60) / tc.minutes_per_round)
})

const lengths = computed(() =>
  RUN_LENGTHS.map((l) => ({
    ...l,
    name: t(`parthenon.gathering.length.names.${l.id}`),
    hoursLabel: t('parthenon.gathering.length.hours', { hours: l.hours }),
    minutesLabel: /hour/i.test(l.minutes)
      ? t('parthenon.gathering.length.aboutHours', { minutes: l.minutes })
      : t('parthenon.gathering.length.about', { minutes: l.minutes }),
    beyond: !!autoGeneratedRounds.value && l.rounds > autoGeneratedRounds.value
  }))
)

// When a length was chosen on the steps this section confirms it rather than
// asking again; the sentence follows the choice if it is changed here or if
// the Scribe planned a shorter city than was asked for.
const inSentence = (id) => t(`parthenon.gathering.length.inSentence.${id}`)

const lengthTitle = computed(() =>
  carriedLength ? t('parthenon.gathering.length.titleCarried') : t('parthenon.gathering.length.title')
)

const lengthHint = computed(() => {
  if (!carriedLength) return t('parthenon.gathering.length.hint')
  const name = inSentence(carriedLength.id)
  if (chosenLength.value === carriedLength.id) return t('parthenon.gathering.length.carried', { name })
  return t('parthenon.gathering.length.carriedChanged', { name, now: inSentence(chosenLength.value) })
})

const chooseLength = (l) => {
  if (l.beyond) return
  chosenLength.value = l.id
}

const onLengthKey = (e, l) => {
  const keys = ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp']
  if (!keys.includes(e.key)) return
  e.preventDefault()
  const open = lengths.value.filter((x) => !x.beyond)
  const idx = open.findIndex((x) => x.id === l.id)
  const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : -1
  const next = open[(idx + step + open.length) % open.length]
  if (next) {
    chosenLength.value = next.id
    nextTick(() => document.querySelector('.length-option[aria-checked="true"]')?.focus())
  }
}

// When the config is known, make sure the chosen length is one the city can hold.
watch(lengths, (list) => {
  const current = list.find((l) => l.id === chosenLength.value)
  if (current && !current.beyond) return
  const open = list.filter((l) => !l.beyond)
  if (open.length) chosenLength.value = open[open.length - 1].id
})

const handleStartSimulation = () => {
  const chosen = RUN_LENGTHS.find((l) => l.id === chosenLength.value) || RUN_LENGTHS[1]
  emit('next-step', { maxRounds: chosen.rounds })
}

// --- The citizen's card ------------------------------------------------------

const cardEl = ref(null)
const closeBtn = ref(null)
let returnFocusTo = null

const openCard = (citizen, event) => {
  returnFocusTo = event?.currentTarget || null
  selected.value = citizen
  nextTick(() => closeBtn.value?.focus())
}

const closeCard = () => {
  selected.value = null
  nextTick(() => returnFocusTo?.focus?.())
}

const onCardKey = (e) => {
  if (e.key === 'Escape') {
    e.preventDefault()
    closeCard()
    return
  }
  if (e.key !== 'Tab' || !cardEl.value) return
  const focusable = cardEl.value.querySelectorAll('button, [href], [tabindex]:not([tabindex="-1"])')
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

// --- The engine's preparation, polled as before -----------------------------

const stageLabel = (key) => {
  const map = {
    reading: 'stageReading',
    generating_profiles: 'stageProfiles',
    generating_config: 'stageConfig',
    copying_scripts: 'stageScripts'
  }
  return map[key] ? t(`parthenon.gathering.ledger.${map[key]}`) : ''
}

watch(currentStage, (stage) => {
  if (stage === 'generating_profiles') {
    phase.value = Math.max(phase.value, 1)
  } else if (stage === 'generating_config' || stage === 'copying_scripts') {
    phase.value = Math.max(phase.value, 2)
    if (!configTimer) {
      addLog(t('parthenon.gathering.ledger.settingHours'))
      startConfigPolling()
    }
  }
})

const stageFromDetail = (detail, message) => {
  if (detail?.current_stage) return detail.current_stage
  const name = String(detail?.current_stage_name || message || '')
  if (/profile|人设/i.test(name)) return 'generating_profiles'
  if (/script|脚本/i.test(name)) return 'copying_scripts'
  if (/config|配置/i.test(name)) return 'generating_config'
  if (/read|entit|实体|读取/i.test(name)) return 'reading'
  return ''
}

const handlePrepareFailure = (message) => {
  stopPolling()
  stopProfilesPolling()
  stopConfigPolling()
  const why = cityWords(message || t('common.unknownError'))
  troubleMessage.value = why
  addLog(t('parthenon.gathering.ledger.failed', { error: why }))
  emit('update-status', 'error')
}

const startPrepareSimulation = async () => {
  if (!props.simulationId) {
    addLog(t('parthenon.gathering.ledger.noGathering'))
    emit('update-status', 'error')
    return
  }

  phase.value = 1
  addLog(t('parthenon.gathering.ledger.summoning'))
  emit('update-status', 'processing')

  try {
    const res = await prepareSimulation({
      simulation_id: props.simulationId,
      use_llm_for_profiles: true,
      parallel_profile_count: 5
    })

    if (res.success && res.data) {
      if (res.data.already_prepared) {
        addLog(t('parthenon.gathering.ledger.alreadyGathered'))
        await loadPreparedData()
        return
      }

      taskId.value = res.data.task_id

      if (res.data.expected_entities_count) {
        expectedTotal.value = res.data.expected_entities_count
        addLog(t('parthenon.gathering.ledger.namesFound', { count: res.data.expected_entities_count }))
        if (res.data.entity_types?.length) {
          const kinds = res.data.entity_types.map((x) => entityTypeName(x)).filter(Boolean)
          if (kinds.length) addLog(t('parthenon.gathering.ledger.kinds', { types: kinds.join(', ') }))
        }
      }

      startPolling()
      startProfilesPolling()
    } else {
      handlePrepareFailure(res.error)
    }
  } catch (err) {
    handlePrepareFailure(err.message)
  }
}

const callAgain = () => {
  troubleMessage.value = ''
  lastLoggedMessage = ''
  lastLoggedConfigStage = ''
  startPrepareSimulation()
}

const startPolling = () => {
  if (!pollTimer) pollTimer = setInterval(pollPrepareStatus, 2000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const startProfilesPolling = () => {
  if (!profilesTimer) profilesTimer = setInterval(fetchProfilesRealtime, 3000)
}

const stopProfilesPolling = () => {
  if (profilesTimer) {
    clearInterval(profilesTimer)
    profilesTimer = null
  }
}

const pollPrepareStatus = async () => {
  if (!taskId.value && !props.simulationId) return

  try {
    const res = await getPrepareStatus({
      task_id: taskId.value,
      simulation_id: props.simulationId
    })

    if (res.success && res.data) {
      const data = res.data

      if (data.progress_detail) {
        const detail = data.progress_detail
        currentStage.value = stageFromDetail(detail, data.message)
        const logKey = `${detail.current_stage}-${detail.current_item}-${detail.total_items}`
        if (logKey !== lastLoggedMessage && detail.item_description) {
          lastLoggedMessage = logKey
          const stage = stageLabel(currentStage.value) || cityWords(detail.current_stage_name || '')
          if (detail.total_items > 0) {
            addLog(t('parthenon.gathering.ledger.stageCount', { stage, current: detail.current_item, total: detail.total_items }))
          } else {
            addLog(t('parthenon.gathering.ledger.stageNote', { stage, note: cityWords(detail.item_description) }))
          }
        }
      } else if (data.message) {
        currentStage.value = stageFromDetail(null, data.message)
        if (data.message !== lastLoggedMessage) {
          lastLoggedMessage = data.message
          addLog(cityWords(data.message))
        }
      }

      if (data.status === 'completed' || data.status === 'ready' || data.already_prepared) {
        stopPolling()
        stopProfilesPolling()
        await loadPreparedData()
      } else if (data.status === 'failed') {
        handlePrepareFailure(data.error)
      }
    }
  } catch (err) {
    console.warn('Could not read the preparation status:', err)
  }
}

const fetchProfilesRealtime = async () => {
  if (!props.simulationId) return

  try {
    const res = await getSimulationProfilesRealtime(props.simulationId)

    if (res.success && res.data) {
      profiles.value = res.data.profiles || []
      if (res.data.total_expected) expectedTotal.value = res.data.total_expected

      const currentCount = profiles.value.length
      if (currentCount > 0 && currentCount !== lastLoggedProfileCount) {
        lastLoggedProfileCount = currentCount
        const total = expectedTotal.value || '?'
        const latest = profiles.value[currentCount - 1]
        addLog(t('parthenon.gathering.ledger.arrivedOne', { name: citizenName(latest?.name, latest?.username), current: currentCount, total }))
        if (expectedTotal.value && currentCount >= expectedTotal.value) {
          addLog(t('parthenon.gathering.ledger.arrivedAll', { count: currentCount }))
        }
      }
    }
  } catch (err) {
    console.warn('Could not read the citizens:', err)
  }
}

const startConfigPolling = () => {
  if (!configTimer) configTimer = setInterval(fetchConfigRealtime, 2000)
}

const stopConfigPolling = () => {
  if (configTimer) {
    clearInterval(configTimer)
    configTimer = null
  }
}

const noteConfig = (config, summary) => {
  simulationConfig.value = config
  if (config.time_config?.total_simulation_hours) {
    addLog(t('parthenon.gathering.ledger.hoursSet', { hours: config.time_config.total_simulation_hours }))
  }
  const posts = config.event_config?.initial_posts?.length ?? summary?.initial_posts_count ?? 0
  const matters = config.event_config?.hot_topics?.length ?? summary?.hot_topics_count ?? 0
  if (posts || matters) addLog(t('parthenon.gathering.ledger.firstWords', { posts, topics: matters }))
  if (config.generation_reasoning) {
    const heads = {
      'Time Config': t('parthenon.gathering.ledger.reasonHours'),
      'Event Config': t('parthenon.gathering.ledger.reasonWords'),
      'Agent Config': t('parthenon.gathering.ledger.reasonCitizens'),
      'Post Assignment': t('parthenon.gathering.ledger.reasonOpenings')
    }
    String(config.generation_reasoning)
      .split('|')
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((line) => {
        const swapped = line.replace(/^(Time Config|Event Config|Agent Config|Post Assignment)\s*:/i, (m, head) => `${heads[head] || head}:`)
        addLog(cityWords(swapped))
      })
  }
}

const fetchConfigRealtime = async () => {
  if (!props.simulationId) return

  try {
    const res = await getSimulationConfigRealtime(props.simulationId)

    if (res.success && res.data) {
      const data = res.data

      if (data.status === 'failed' || data.error) {
        handlePrepareFailure(data.error)
        return
      }

      if (data.generation_stage && data.generation_stage !== lastLoggedConfigStage) {
        lastLoggedConfigStage = data.generation_stage
        if (data.generation_stage === 'generating_config') addLog(t('parthenon.gathering.ledger.settingHours'))
      }

      if (data.config_generated && data.config) {
        noteConfig(data.config, data.summary)
        stopConfigPolling()
        phase.value = 4
        addLog(t('parthenon.gathering.ledger.ready'))
        emit('update-status', 'completed')
      }
    }
  } catch (err) {
    console.warn('Could not read the city\'s hours:', err)
  }
}

const loadPreparedData = async () => {
  phase.value = Math.max(phase.value, 2)

  await fetchProfilesRealtime()
  if (profiles.value.length && !expectedTotal.value) expectedTotal.value = profiles.value.length
  addLog(t('parthenon.gathering.ledger.cardsRead', { count: profiles.value.length }))

  try {
    const res = await getSimulationConfigRealtime(props.simulationId)
    if (res.success && res.data) {
      const configState = res.data

      if (configState.status === 'failed' || configState.error) {
        handlePrepareFailure(configState.error)
        return
      }

      if (configState.config_generated && configState.config) {
        noteConfig(configState.config, configState.summary)
        phase.value = 4
        addLog(t('parthenon.gathering.ledger.ready'))
        emit('update-status', 'completed')
      } else if (configState.is_generating) {
        addLog(t('parthenon.gathering.ledger.hoursStillBeingSet'))
        startConfigPolling()
      } else {
        handlePrepareFailure(t('parthenon.gathering.ledger.hoursMissing'))
      }
    }
  } catch (err) {
    handlePrepareFailure(err.message)
  }
}

onMounted(() => {
  if (props.simulationId) startPrepareSimulation()
})

onUnmounted(() => {
  stopPolling()
  stopProfilesPolling()
  stopConfigPolling()
})
</script>

<style scoped>
.gathering {
  display: flex;
  flex-direction: column;
  min-width: 0;
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
}

/* The summons */
.summons {
  padding: 32px var(--p-gutter) 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.summons-title {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.05;
  color: var(--p-ink);
  text-wrap: balance;
}

.summons-lede {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  line-height: 1.5;
  color: var(--p-ink-2);
  max-width: 44em;
}

/* Trouble */
.trouble {
  margin: 0 var(--p-gutter) 20px;
  padding: 16px 18px;
  border: 1px solid var(--p-line);
  border-left: 2px solid var(--p-error);
  background: var(--p-surface);
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
  min-width: 0;
}

.trouble-title {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  color: var(--p-ink);
}

.trouble-why {
  font-size: var(--t-sm);
  color: var(--p-ink-3);
  max-width: 60em;
}

.trouble-why summary {
  cursor: pointer;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.trouble-why p {
  margin: 8px 0 0;
  font-family: var(--p-font-serif);
  line-height: 1.5;
  color: var(--p-ink-2);
  overflow-wrap: anywhere;
}

/* The slope */
.slope {
  list-style: none;
  margin: 0;
  padding: 4px var(--p-gutter) 32px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 10px;
  min-width: 0;
}

.seat {
  min-width: 0;
  animation: arrive 0.7s cubic-bezier(0.2, 0.7, 0.2, 1) both;
  animation-delay: calc(var(--i, 0) * 55ms);
}

@keyframes arrive {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.citizen {
  width: 100%;
  min-height: 100%;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding: 14px 16px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  border-radius: var(--p-radius);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.citizen:hover {
  border-color: var(--p-gold);
  background: var(--p-surface-2);
}

.citizen .p-coin {
  background: color-mix(in srgb, currentColor 14%, var(--p-surface-3));
}

.citizen-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.citizen-name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  line-height: 1.15;
  color: var(--p-ink);
  overflow-wrap: anywhere;
}

.citizen-role {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  line-height: 1.4;
}

.citizen-line {
  margin-top: 6px;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.seat.empty {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding: 14px 16px;
  border: 1px dashed var(--p-line);
  opacity: 0.7;
}

.seat.empty .p-coin {
  border-style: dashed;
  background: transparent;
}

.ghost-line {
  display: block;
  height: 10px;
  width: 45%;
  background: var(--p-surface-3);
  margin-top: 6px;
}

.ghost-line.long { width: 70%; margin-top: 8px; }

/* Blocks */
.block {
  padding: 28px var(--p-gutter);
  border-top: 1px solid var(--p-line);
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.block-title {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  line-height: 1.1;
  color: var(--p-ink);
}

.prose {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
  max-width: 44em;
}

.prose.muted {
  color: var(--p-ink-3);
  font-size: var(--t-sm);
  font-style: italic;
}

/* Topics */
.topics {
  list-style: none;
  margin: 4px 0 8px;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
}

.topic {
  padding: 4px 10px;
  border: 1px solid var(--p-line-strong);
  font-size: var(--t-xs);
  color: var(--p-ink-2);
  overflow-wrap: anywhere;
}

/* Openings */
.openings {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 60em;
}

.opening {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  animation: arrive 0.6s ease both;
  animation-delay: calc(var(--i, 0) * 60ms);
}

.p-coin.small {
  width: 30px;
  height: 30px;
  font-size: var(--t-md);
}

.p-coin.big {
  width: 56px;
  height: 56px;
  font-size: var(--t-xl);
}

.opening-body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.opening-who {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  color: var(--p-ink);
}

.opening-role {
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  font-weight: 400;
  color: var(--p-ink-3);
}

.opening-text {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
}

.saying > .p-button { align-self: flex-start; }

/* Lengths */
.lengths {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  margin-top: 6px;
}

.length-option {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  min-width: 0;
  background: var(--p-surface);
  border: 1px solid var(--p-line-strong);
  border-radius: var(--p-radius);
  color: var(--p-ink-2);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.length-option:hover { border-color: var(--p-gold); }

.length-option[aria-checked='true'] {
  border-color: var(--p-gold);
  background: var(--p-terracotta-tint);
  box-shadow: inset 0 0 0 1px var(--p-gold);
}

.length-option[aria-disabled='true'] {
  cursor: not-allowed;
  color: var(--p-ink-3);
  border-style: dashed;
}

.length-option[aria-disabled='true']:hover { border-color: var(--p-line-strong); }

.length-name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  color: var(--p-ink);
}

.length-option[aria-disabled='true'] .length-name { color: var(--p-ink-3); }

.length-meta {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  line-height: 1.4;
}

.length-note {
  margin-top: 4px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

/* The doors */
.doors {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
  padding: 24px var(--p-gutter) 36px;
  border-top: 1px solid var(--p-line);
  min-width: 0;
}

.door-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  min-width: 0;
}

.door-reason {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

/* The card on parchment */
.veil {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(11, 14, 19, 0.74);
  backdrop-filter: blur(6px);
}

.card {
  position: relative;
  width: min(100%, 640px);
  max-height: min(86vh, 860px);
  overflow: auto;
  padding: 28px 28px 32px;
  box-shadow: var(--p-shadow-2);
  border-radius: var(--p-radius);
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.card-close {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--p-radius);
  color: var(--p-ink-3);
  cursor: pointer;
}

.card-close:hover { color: var(--p-ink); border-color: var(--p-line-strong); }

.card-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 18px;
  align-items: center;
  padding-right: 40px;
}

.card .p-coin {
  background: color-mix(in srgb, currentColor 12%, var(--p-surface-2));
}

.card-id {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.card-name {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.05;
  color: var(--p-ink);
  overflow-wrap: anywhere;
}

.card-profession {
  margin: 0;
  font-size: var(--t-sm);
  line-height: 1.45;
  color: var(--p-ink-3);
}

.card-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card-section h4 { margin: 0; }

.card-prose {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.65;
  color: var(--p-ink-2);
  white-space: pre-line;
}

.card-topics {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
}

.card-enter-active,
.card-leave-active { transition: opacity 0.25s ease; }

.card-enter-from,
.card-leave-to { opacity: 0; }

/* With motion reduced every seat is taken at once: the global rule shortens
   the animation but not its delay, and "both" would hold each card unseen
   until its turn. */
@media (prefers-reduced-motion: reduce) {
  .seat,
  .opening {
    animation: none;
  }

  .citizen,
  .length-option {
    transition: none;
  }
}

@media (max-width: 899px) {
  .summons { padding: 24px 16px 16px; }
  .trouble { margin-inline: 16px; }
  .slope { padding-inline: 16px; grid-template-columns: minmax(0, 1fr); }
  .block { padding-inline: 16px; }
  .doors { padding-inline: 16px; }
  .door-main { width: 100%; }
  .door-main .p-button { flex: 1 1 auto; }
  .veil { padding: 0; align-items: flex-end; }
  .card { width: 100%; max-height: 90vh; padding: 24px 16px 32px; }
}
</style>
