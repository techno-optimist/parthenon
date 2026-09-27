<template>
  <section class="gathering">
    <!-- The summons: how many have come, and what the Scribe is doing. -->
    <header class="summons">
      <span class="p-eyebrow">{{ $t('parthenon.gathering.place') }}</span>
      <h2 class="summons-title" aria-live="polite">{{ countLine }}</h2>
      <p class="summons-lede">{{ stateLine }}</p>

      <!-- The painters: faces replace initials as they are finished. -->
      <div v-if="paintersLine" class="painters" :class="`is-${paintersState}`">
        <span class="painters-mark" aria-hidden="true"></span>
        <p class="painters-line" role="status">{{ paintersLine }}</p>
        <span v-if="paintersState === 'working'" class="painters-meter" aria-hidden="true">
          <span class="painters-fill" :style="{ width: `${paintedShare * 100}%` }"></span>
        </span>
        <button v-if="paintersState === 'failed' && mayPaint" type="button" class="p-button ghost small" @click="paintAgain">
          {{ $t('parthenon.gathering.painters.again') }}
        </button>
        <template v-if="paintersState === 'offer' && mayPaint">
          <button type="button" class="p-button ghost small" :aria-describedby="`${uid}-paint-cost`" @click="paintAgain">
            {{ $t('parthenon.gathering.painters.paint') }}
          </button>
          <span :id="`${uid}-paint-cost`" class="painters-cost">{{ $t('parthenon.gathering.painters.cost', { n: citizens.length }) }}</span>
        </template>
      </div>

      <!-- The long wait, in time, and leave to go. -->
      <p v-if="waiting" class="wait-note">
        <i18n-t keypath="parthenon.gathering.waitNote" tag="span" scope="global">
          <template #shelf>
            <router-link :to="{ name: 'Chronicles' }">{{ $t('parthenon.gathering.shelf') }}</router-link>
          </template>
        </i18n-t>
      </p>
    </header>

    <!-- A limit of the public steps, or a guest before the citizens are called: one calm line. -->
    <div v-if="calmMessage" class="calm-line calm-block">
      <p role="status">{{ calmMessage }}</p>
      <button v-if="control" type="button" class="p-button secondary small" @click="callAgain">{{ $t('parthenon.gathering.tryAgain') }}</button>
    </div>
    <p v-else-if="guestWaiting" class="calm-line" role="status">{{ $t('parthenon.public.guestWaiting') }}</p>

    <!-- Trouble, in the city's voice, with the cause behind a disclosure. -->
    <div v-if="troubleMessage" class="trouble" role="alert">
      <p class="trouble-title">{{ $t('parthenon.gathering.trouble') }}</p>
      <details class="trouble-why">
        <summary>{{ $t('parthenon.gathering.troubleWhy') }}</summary>
        <p>{{ troubleMessage }}</p>
      </details>
      <button v-if="control" type="button" class="p-button secondary small" @click="callAgain">{{ $t('parthenon.gathering.tryAgain') }}</button>
    </div>

    <!-- The slope: citizens arrive one by one; the seats still empty are drawn faint. -->
    <ol v-if="citizens.length || emptySeats" class="slope" :aria-label="$t('parthenon.gathering.citizens')">
      <li v-for="(c, i) in citizens" :key="c.key" class="seat" :style="{ '--i': Math.min(i, 24) }">
        <button type="button" class="citizen" :data-seat="c.key" :aria-label="$t('parthenon.gathering.openCard', { name: c.name })" @click="openCard(c, $event)">
          <CitizenCoin :name="c.name" :type="c.type || c.profession" :portrait="c.portrait" size="lg" />
          <span class="citizen-body">
            <span class="citizen-name">{{ c.name }}</span>
            <span class="citizen-role">{{ c.role }}</span>
            <span v-if="c.line" class="citizen-line">{{ c.line }}</span>
          </span>
        </button>
      </li>
      <li v-for="n in emptySeats" :key="'empty-' + n" class="seat empty" aria-hidden="true">
        <span class="p-coin ghost-coin"></span>
        <span class="citizen-body"><span class="ghost-line long"></span><span class="ghost-line"></span></span>
      </li>
    </ol>

    <!-- The city's hours, in words, with the day drawn as a strip of hours. -->
    <section v-if="hours" class="block hours">
      <span class="p-eyebrow">{{ $t('parthenon.gathering.hours.eyebrow') }}</span>
      <h3 class="block-title">{{ $t('parthenon.gathering.hours.title') }}</h3>
      <figure class="dial">
        <div class="dial-bars" role="img" :aria-label="`${$t('parthenon.gathering.hours.dial')}. ${hours.day}`">
          <span
            v-for="b in hours.bars"
            :key="b.hour"
            class="dial-bar"
            :class="`is-${b.kind}`"
            :style="{ '--h': b.height, '--i': b.hour }"
          ></span>
        </div>
        <div class="dial-marks" aria-hidden="true">
          <span style="--at: 0">{{ $t('parthenon.gathering.hours.marks.midnight') }}</span>
          <span style="--at: 0.25">{{ $t('parthenon.gathering.hours.marks.dawn') }}</span>
          <span style="--at: 0.5">{{ $t('parthenon.gathering.hours.marks.noon') }}</span>
          <span style="--at: 0.75">{{ $t('parthenon.gathering.hours.marks.dusk') }}</span>
          <span style="--at: 1">{{ $t('parthenon.gathering.hours.marks.midnight') }}</span>
        </div>
      </figure>
      <p class="prose">{{ hours.day }}</p>
      <p class="prose">{{ hours.awake }}</p>
      <p v-if="hours.first" class="prose">{{ hours.first }}</p>
      <p v-if="hours.last" class="prose">{{ hours.last }}</p>
      <div v-if="hours.loudest.length" class="loudest">
        <h4 class="loudest-lead">{{ $t('parthenon.gathering.hours.loudestLead') }}</h4>
        <ul class="voices">
          <li v-for="v in hours.loudest" :key="v.key">
            <button
              v-if="v.citizen"
              type="button"
              class="voice"
              :aria-label="$t('parthenon.gathering.openCard', { name: v.name })"
              @click="openCard(v.citizen, $event)"
            >
              <CitizenCoin :name="v.name" :type="v.citizen.type || v.citizen.profession" :portrait="v.citizen.portrait" size="sm" />
              <span class="voice-name">{{ v.name }}</span>
            </button>
            <span v-else class="voice">
              <CitizenCoin :name="v.name" :type="v.type" size="sm" />
              <span class="voice-name">{{ v.name }}</span>
            </span>
          </li>
        </ul>
      </div>
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
          <button
            v-if="o.citizen"
            type="button"
            class="opening-face"
            :aria-label="$t('parthenon.gathering.openCard', { name: o.name })"
            @click="openCard(o.citizen, $event)"
          >
            <CitizenCoin :name="o.name" :type="o.type" :portrait="o.citizen.portrait" size="md" />
          </button>
          <CitizenCoin v-else :name="o.name" :type="o.type" size="md" />
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

    <!-- A gathering already argued: what happened, not a choice that changes nothing. -->
    <section v-if="arguedFact" class="block argued">
      <span class="p-eyebrow">{{ $t('parthenon.gathering.argued.eyebrow') }}</span>
      <h3 class="block-title">{{ arguedFact }}</h3>
      <p class="prose muted">{{ arguedNote }}</p>
    </section>

    <!-- How long the city talks: story-sized lengths, honest minutes. -->
    <section v-else-if="simulationConfig" class="block length">
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
      <div v-if="arguedFact" class="door-main">
        <router-link
          :to="{ name: 'SimulationRun', params: { simulationId } }"
          class="p-button"
          :class="{ secondary: hasChronicle }"
        >{{ $t('parthenon.gathering.argued.toAgora') }}</router-link>
        <router-link
          v-if="hasChronicle"
          :to="{ name: 'Report', params: { reportId: argued.reportId } }"
          class="p-button"
        >{{ $t('parthenon.gathering.argued.toChronicle') }}</router-link>
      </div>
      <div v-else-if="control" class="door-main">
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
            tabindex="-1"
            @keydown="onCardKey"
          >
            <button ref="closeBtn" type="button" class="card-close" :aria-label="$t('parthenon.gathering.card.close')" @click="closeCard">
              <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 4l12 12M16 4L4 16" /></svg>
            </button>

            <div :key="selected.key" class="card-body">
              <div class="card-head">
                <CitizenCoin :name="selected.name" :type="selected.type || selected.profession" :portrait="selected.portrait" size="xl" />
                <div class="card-id">
                  <span class="p-eyebrow">{{ selected.title }}</span>
                  <h3 id="citizen-card-name" class="card-name">{{ selected.name }}</h3>
                  <p v-if="selected.profession && selected.profession !== selected.title" class="card-profession">{{ selected.profession }}</p>
                </div>
              </div>

              <div class="p-meander" aria-hidden="true"></div>

              <div v-if="selected.stand || selected.comes.length" class="card-facts">
                <section v-if="selected.stand" class="card-section">
                  <h4 class="p-eyebrow">{{ $t('parthenon.gathering.card.stand') }}</h4>
                  <p v-if="selected.stand.words" class="card-stand">{{ selected.stand.words }}</p>
                  <blockquote v-else class="card-quote">{{ selected.stand.quote }}</blockquote>
                  <div v-if="selected.stand.words" class="scale" :class="{ watching: selected.stand.watching }" aria-hidden="true">
                    <span class="scale-end">{{ $t('parthenon.gathering.card.scaleAgainst') }}</span>
                    <span class="scale-beam">
                      <span class="scale-mid"></span>
                      <span class="scale-mark" :style="{ left: `${selected.stand.at * 100}%` }"></span>
                    </span>
                    <span class="scale-end">{{ $t('parthenon.gathering.card.scaleFor') }}</span>
                  </div>
                </section>
                <section v-if="selected.comes.length" class="card-section">
                  <h4 class="p-eyebrow">{{ $t('parthenon.gathering.card.comes') }}</h4>
                  <p v-for="(line, i) in selected.comes" :key="i" class="card-note">{{ line }}</p>
                </section>
              </div>

              <section class="card-section">
                <h4 class="p-eyebrow">{{ $t('parthenon.gathering.card.past') }}</h4>
                <template v-if="selected.past.lead.length">
                  <p v-for="(para, i) in selected.past.lead" :key="'l' + i" class="card-prose">{{ para }}</p>
                  <div v-if="pastOpen" id="citizen-card-more" class="card-more">
                    <p v-for="(para, i) in selected.past.rest" :key="'r' + i" class="card-prose">{{ para }}</p>
                  </div>
                  <button
                    v-if="selected.past.rest.length"
                    type="button"
                    class="p-button ghost small card-toggle"
                    :aria-expanded="pastOpen"
                    aria-controls="citizen-card-more"
                    @click="pastOpen = !pastOpen"
                  >
                    {{ pastOpen ? $t('parthenon.gathering.card.readLess') : $t('parthenon.gathering.card.readMore') }}
                  </button>
                </template>
                <p v-else class="card-prose">{{ $t('parthenon.gathering.card.nothing') }}</p>
              </section>

              <section v-if="selected.topics.length" class="card-section">
                <h4 class="p-eyebrow">{{ $t('parthenon.gathering.card.cares') }}</h4>
                <ul class="card-topics">
                  <li v-for="topic in selected.topics" :key="topic" class="topic">{{ topic }}</li>
                </ul>
              </section>
            </div>

            <nav v-if="citizens.length > 1" class="card-walk">
              <button type="button" class="walk" :aria-label="$t('parthenon.gathering.card.prev', { name: neighbour(-1).name })" @click="walk(-1)">
                <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M12.5 4 6.5 10l6 6" /></svg>
                <CitizenCoin :name="neighbour(-1).name" :type="neighbour(-1).type || neighbour(-1).profession" :portrait="neighbour(-1).portrait" size="sm" />
                <span class="walk-name">{{ neighbour(-1).name }}</span>
              </button>
              <button type="button" class="walk next" :aria-label="$t('parthenon.gathering.card.next', { name: neighbour(1).name })" @click="walk(1)">
                <span class="walk-name">{{ neighbour(1).name }}</span>
                <CitizenCoin :name="neighbour(1).name" :type="neighbour(1).type || neighbour(1).profession" :portrait="neighbour(1).portrait" size="sm" />
                <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m7.5 4 6 6-6 6" /></svg>
              </button>
            </nav>
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
// visitor reads is the city's, every citizen has a face, and the wiring goes to
// the scribe's ledger.
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  prepareSimulation,
  getPrepareStatus,
  getSimulationProfilesRealtime,
  getSimulationConfigRealtime
} from '../api/simulation'
import pendingUpload from '../store/pendingUpload'
import {
  entityTypeName,
  roleLabel as roleTitle,
  citizenName,
  stripIds,
  spansHours,
  RUN_LENGTHS
} from '../parthenon/vocabulary.js'
import { useCitizenPortraits } from '../parthenon/portraits.js'
import { access, calmLine, canControl, featureOn } from '../parthenon/access.js'
import { allowedRunLengths } from '../parthenon/limits.js'
import { nameKey as foldName } from '../parthenon/web.js'
import CitizenCoin from './CitizenCoin.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const props = defineProps({
  simulationId: String,
  projectData: Object,
  graphData: Object,
  // How the gathering has been argued, read by the act from its run and the
  // shelf: { argued, live, runnerStatus, currentRound, totalRounds, reportId, reportStatus }
  argued: { type: Object, default: null }
})

const uid = `gathering-${Math.random().toString(36).slice(2, 8)}`

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
const selectedKey = ref(null)
const pastOpen = ref(false)
const showAllOpenings = ref(false)
const chosenLength = ref(carriedLength?.id || 'day')
// A limit of the public steps, said calmly in place of trouble.
const calmMessage = ref('')
// A guest at a gathering whose citizens have not been called yet.
const guestWaiting = ref(false)

// On the public steps only the one who began a gathering may call, paint or
// open it; a guest watches. At home, always.
const control = computed(() => canControl(props.simulationId, props.projectData?.project_id))
// The painters come only where they can work (a key for them) and for the one who began it.
const mayPaint = computed(() => control.value && featureOn('portraits'))

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

const nameKey = (name) => String(name || '').trim().toLowerCase()

// The Web of Athens knows each name's kind; the engine's citizen list does not.
const typeByName = computed(() => {
  const map = new Map()
  const put = (name, type) => {
    if (!name || !type) return
    map.set(nameKey(name), type)
  }
  for (const node of props.graphData?.nodes || []) {
    const labels = (node.labels || []).filter((l) => l !== 'Entity')
    put(node.name, labels[labels.length - 1] || (node.labels?.includes('Entity') ? 'Person' : ''))
  }
  for (const a of simulationConfig.value?.agent_configs || []) put(a.entity_name, a.entity_type)
  return map
})

const typeFor = (name) => typeByName.value.get(nameKey(name)) || ''

// How each citizen was set to behave, by name, falling back to their seat.
const agentConfigs = computed(() => simulationConfig.value?.agent_configs || [])
const configByName = computed(() => {
  const map = new Map()
  for (const a of agentConfigs.value) if (a?.entity_name) map.set(nameKey(a.entity_name), a)
  return map
})
const configFor = (profile, idx) => {
  const byName = configByName.value.get(nameKey(profile?.name))
  if (byName) return byName
  const seat = profile?.user_id ?? idx
  return agentConfigs.value.find((a) => Number(a?.agent_id) === Number(seat)) || null
}

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

const roleWords = (type, profession) => {
  const named = entityTypeName(type)
  if (named && named !== 'citizen') return named
  return shortProfession(profession) || named || t('parthenon.gathering.citizen')
}

const upperFirst = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)

// The title on the card: the role as the Web names it, or their trade when the
// Web only knows them as a person.
const cardTitle = (type, profession) => {
  const named = entityTypeName(type)
  if (named && named !== 'citizen') return roleTitle(type)
  const trade = shortProfession(profession)
  return trade ? upperFirst(trade) : t('parthenon.gathering.card.eyebrow')
}

// --- Their past, in the city's words ----------------------------------------

// Sentences, without stopping at "Dr." or "Mrs.".
const ABBREVIATION = /\b(Dr|Mr|Mrs|Ms|St|Fr|Prof|Sr|Jr|vs|etc|No|c|ca)\.$/i
const sentencesOf = (text) => {
  const out = []
  for (const block of String(text || '').split(/\n+/)) {
    let sentence = ''
    for (const part of block.trim().split(/(?<=[.!?])\s+|(?<=[。！？])/)) {
      if (!part) continue
      sentence = sentence ? `${sentence} ${part}` : part
      if (!ABBREVIATION.test(sentence)) {
        out.push(sentence.trim())
        sentence = ''
      }
    }
    if (sentence.trim()) out.push(sentence.trim())
  }
  return out.filter(Boolean)
}

// The pasts are written as if for a notice board: "Official account of...",
// "Basic Information:", talk of feeds and followers. The openers are cut, and
// any sentence still about the board rather than the person is left out.
const LABEL = /^(?:institution(?:al)? )?(?:basic information|background|personality|biography|summary|overview)\s*[:：]\s*/i
const OPENER = /^(?:this is |the account is |this account is )?(?:the |an? )?(?:official |verified(?:[- ]style)? )?(?:(?:civic|public|institutional|social[- ]media|verified) )*(?:account|channel|page|presence|office|profile)(?: biography)?(?: for the public channel)? (?:(?:maintained |kept )?in the name of|of|for) /i
const MEDIA_VOICE = /\b(?:official )?social[- ]media (?:account|voice|presence|channel|page)\b/gi
const FORMAL_NAME = /\bis the formal (?:public )?name (?:of|for) /i
const BOARD_WORDS = /\b(?:accounts?|channels?|social[- ]media|platforms?|feeds?|posts?|posting|hashtags?|handles?|usernames?|karma|MBTI|simulations?|simulated|entity|entities|persona|templates?|verified|profile|page|online|target audience|(?:core|primary|main) functions?|functions (?:include|involve)|basic information|speaking style|institution(?:al)? nature|establishment background|taboo topics?|common (?:expressions|phrases)|active hours|institutional memory|the tone is|(?:target )?audiences? (?:is|are|includes?))\b|^(?:its |the |our |her |his )?formal name\b/i

const BOARD_WORDS_ZH = /账号|账户|社交媒体|粉丝|帖子|发帖|平台|话题标签|人设|模拟|实体|目标受众|核心功能|说话风格/

const cleanPast = (text) =>
  sentencesOf(text)
    .map((s) => upperFirst(s.replace(LABEL, '').replace(OPENER, '').replace(MEDIA_VOICE, 'voice').replace(FORMAL_NAME, 'is ')))
    .filter((s) => s.length > 2 && !BOARD_WORDS.test(s) && !BOARD_WORDS_ZH.test(s))

// The engine cuts a short past mid-word; end it at the last clause instead.
const mended = (sentence) => {
  const s = String(sentence || '').trim()
  if (!s || /[.!?。！？"'”’)]$/.test(s)) return s
  const comma = s.lastIndexOf(',')
  if (comma >= 24) return `${s.slice(0, comma)}.`
  return `${s.replace(/\s+\S*$/, '')}…`
}

// One line of their past for the slope, without a leading repeat of their own
// name when a title follows it ("Despina Nomikou, Mayor of..." reads "Mayor of...").
const leadLine = (bio, persona, name) => {
  let line = mended(cleanPast(bio)[0] || cleanPast(persona)[0] || '')
  const n = String(name || '').trim()
  if (n && line.startsWith(`${n}, `)) {
    const rest = line.slice(n.length + 2)
    if (/^[A-Za-z]/.test(rest)) line = upperFirst(rest)
  }
  return line
}

// The past on the card: a few sentences to begin, the rest (trimmed) on request.
const PAST_LEAD = 460
const PAST_ALL = 2600
const pastParts = (bio, persona) => {
  let sentences = cleanPast(persona)
  if (sentences.length < 3) {
    const fromBio = cleanPast(bio).map(mended).filter((s) => !sentences.includes(s))
    sentences = [...fromBio, ...sentences]
  }
  const kept = []
  let length = 0
  for (const s of sentences) {
    if (kept.length && length + s.length > PAST_ALL) break
    kept.push(s)
    length += s.length + 1
  }
  const lead = []
  let leadLength = 0
  while (kept.length && (!lead.length || leadLength + kept[0].length <= PAST_LEAD)) {
    const s = kept.shift()
    lead.push(s)
    leadLength += s.length + 1
  }
  const rest = []
  for (let i = 0; i < kept.length; i += 3) rest.push(kept.slice(i, i + 3).join(' '))
  return { lead: lead.length ? [lead.join(' ')] : [], rest }
}

// --- Where they stand and when they come -------------------------------------

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x))

const standKey = (stance, bias) => {
  const s = String(stance || '').trim().toLowerCase()
  if (/^(support|for\b|pro\b|favou?r)/.test(s)) return bias >= 0.6 ? 'forFirm' : bias > 0 && bias < 0.2 ? 'forLean' : 'for'
  if (/^(oppos|against|anti\b|reject)/.test(s)) return bias <= -0.6 ? 'againstFirm' : bias < 0 && bias > -0.2 ? 'againstLean' : 'against'
  if (/^(observ|watch|onlook)/.test(s)) return 'watching'
  if (!s || /^(neutral|undecided|mixed|ambivalent|unsure|unknown)/.test(s)) {
    return bias >= 0.2 ? 'undecidedFor' : bias <= -0.2 ? 'undecidedAgainst' : 'undecided'
  }
  return null
}

// A short stance is said in words with its place on the beam; a long one is
// the citizen's own and is quoted as written.
const standOf = (cfg) => {
  if (!cfg) return null
  const stance = String(cfg.stance || '').trim()
  const bias = clamp(Number(cfg.sentiment_bias) || 0, -1, 1)
  const key = stance.length <= 40 ? standKey(stance, bias) : null
  if (!key) return stance ? { quote: stance } : null
  let lean = bias
  if (key.startsWith('for') && lean <= 0.05) lean = 0.4
  if (key.startsWith('against') && lean >= -0.05) lean = -0.4
  if (key === 'watching') lean = 0
  return {
    words: t(`parthenon.gathering.card.stance.${key}`),
    at: (lean + 1) / 2,
    watching: key === 'watching'
  }
}

// Contiguous runs of hours, joined across midnight: [[8, 13], [17, 21]].
const hourRuns = (hours) => {
  const set = [...new Set((hours || []).map(Number).filter((h) => h >= 0 && h < 24))].sort((a, b) => a - b)
  if (!set.length) return []
  if (set.length === 24) return [[0, 24]]
  const runs = []
  for (const h of set) {
    const last = runs[runs.length - 1]
    if (last && last[1] === h) last[1] = h + 1
    else runs.push([h, h + 1])
  }
  if (runs.length > 1 && runs[0][0] === 0 && runs[runs.length - 1][1] === 24) {
    const first = runs.shift()
    runs[runs.length - 1][1] = 24 + first[1]
  }
  return runs
}

// How much a citizen says in their waking day, to rank the voices by.
const dailyVoice = (cfg) =>
  ((Number(cfg?.posts_per_hour) || 0) + (Number(cfg?.comments_per_hour) || 0)) *
  Math.max(1, (cfg?.active_hours || []).length || 12)

const voiceRank = computed(() => {
  const sorted = agentConfigs.value.map(dailyVoice).sort((a, b) => b - a)
  return (cfg) => {
    if (!sorted.length) return 1
    const above = sorted.filter((v) => v > dailyVoice(cfg)).length
    return above / sorted.length
  }
})

const comesOf = (cfg) => {
  if (!cfg) return []
  const lines = []
  const runs = hourRuns(cfg.active_hours)
  if (runs.length === 1 && runs[0][1] - runs[0][0] >= 24) {
    lines.push(t('parthenon.gathering.card.always'))
  } else if (runs.length) {
    const spans = runs
      .map(([from, to]) => t('parthenon.gathering.card.span', { from: clockWord(from), to: clockWord(to) }))
      .join(t('parthenon.gathering.card.spanJoin'))
    lines.push(t('parthenon.gathering.card.inSquare', { spans }))
  }
  if (cfg.posts_per_hour !== undefined || cfg.comments_per_hour !== undefined) {
    const rank = voiceRank.value(cfg)
    const often = rank < 0.15 ? 'top' : rank < 0.5 ? 'high' : rank < 0.8 ? 'mid' : 'low'
    const posts = Number(cfg.posts_per_hour) || 0
    const answers = Number(cfg.comments_per_hour) || 0
    const manner = answers >= posts * 2 && answers > 0 ? 'answers' : posts > answers ? 'opens' : ''
    const slowest = Number(cfg.response_delay_min)
    const quickest = Number(cfg.response_delay_max)
    const pace = quickest > 0 && quickest <= 30 ? 'quick' : slowest >= 60 ? 'slow' : ''
    lines.push(t('parthenon.gathering.card.speaks', {
      often: t(`parthenon.gathering.card.often.${often}`),
      manner: manner ? t(`parthenon.gathering.card.manner.${manner}`) : '',
      pace: pace ? t(`parthenon.gathering.card.pace.${pace}`) : ''
    }))
  }
  return lines
}

// --- The citizens, with their faces -----------------------------------------

const citizenBase = computed(() =>
  profiles.value.map((p, idx) => {
    const name = citizenName(p.name, p.username) || t('parthenon.gathering.citizen')
    const type = typeFor(p.name)
    const cfg = configFor(p, idx)
    return {
      key: p.username || p.user_id || `${name}-${idx}`,
      seat: p.user_id ?? idx,
      rawName: p.name,
      name,
      type,
      role: roleWords(type, p.profession),
      title: cardTitle(type, p.profession),
      profession: String(p.profession || '').trim(),
      line: leadLine(p.bio, p.persona, name),
      past: pastParts(p.bio, p.persona),
      stand: standOf(cfg),
      comes: comesOf(cfg),
      topics: Array.isArray(p.interested_topics) ? p.interested_topics.filter(Boolean) : []
    }
  })
)

// The painters begin once every citizen has come; faces replace initials as
// they are finished. Other acts only read what is painted here.
const allArrived = computed(() => {
  const n = profiles.value.length
  if (!n) return false
  if (phase.value >= 2) return true
  const total = Number(expectedTotal.value) || 0
  return !!total && n >= total
})
const paintedGathering = computed(() => (allArrived.value && props.simulationId ? props.simulationId : null))

// Painting costs the owner's subscription. It begins on its own only for a
// crowd that arrived in this tab (summoned here, or arriving while the visitor
// watched); a gathering opened from the shelf or a link shows its initials and
// offers to paint, naming the cost. The mark survives a reload of this tab.
const ARRIVED_KEY = (id) => `parthenon.arrivedHere.${id}`
const readArrivedHere = (id) => {
  try { return !!id && sessionStorage.getItem(ARRIVED_KEY(id)) === '1' } catch { return false }
}
const arrivedHere = ref(readArrivedHere(props.simulationId))
const markArrivedHere = () => {
  arrivedHere.value = true
  try { sessionStorage.setItem(ARRIVED_KEY(props.simulationId), '1') } catch { /* this visit still knows */ }
}
const portraits = useCitizenPortraits(paintedGathering, { autoStart: () => arrivedHere.value && mayPaint.value })

const citizens = computed(() =>
  citizenBase.value.map((c) => ({
    ...c,
    portrait: portraits.portraitFor(c.rawName) || portraits.portraitFor(c.name) || portraits.portraitFor(c.seat) || ''
  }))
)

const citizenByName = computed(() => {
  const map = new Map()
  for (const c of citizens.value) {
    map.set(nameKey(c.rawName), c)
    map.set(nameKey(c.name), c)
  }
  return map
})

const emptySeats = computed(() => {
  const expected = Number(expectedTotal.value) || 0
  if (phase.value >= 4 || !expected) return 0
  return Math.max(0, Math.min(40, expected - profiles.value.length))
})

// --- The painters ------------------------------------------------------------

const facesDone = computed(() => citizens.value.filter((c) => c.portrait).length)
const paintedShare = computed(() => (citizens.value.length ? facesDone.value / citizens.value.length : 0))
const sawPainters = ref(false)
watch(() => portraits.status.value, (status) => {
  if (status === 'running') sawPainters.value = true
}, { immediate: true })

const paintersState = computed(() => {
  const status = portraits.status.value
  if (!citizens.value.length || !paintedGathering.value) return ''
  if (status === 'running') return 'working'
  if (status === 'failed') return 'failed'
  if (status === 'completed' && sawPainters.value) return 'done'
  if (status === 'none' && portraits.loaded.value && !featureOn('portraits')) return 'away'
  if (status === 'none' && portraits.loaded.value && !arrivedHere.value && mayPaint.value) return 'offer'
  return ''
})

const paintersLine = computed(() => {
  const done = facesDone.value
  const total = citizens.value.length
  switch (paintersState.value) {
    case 'working':
      return done
        ? t('parthenon.gathering.painters.working', { done, total })
        : t('parthenon.gathering.painters.starting')
    case 'failed':
      return t('parthenon.gathering.painters.failed', { done, total })
    case 'done':
      return done >= total
        ? t('parthenon.gathering.painters.done')
        : t('parthenon.gathering.painters.doneSome', { done, total })
    case 'offer':
      return t('parthenon.gathering.painters.offer')
    case 'away':
      // No painters on the public steps: the citizens keep their initials.
      return t('parthenon.public.features.portraits')
    default:
      return ''
  }
})

// Asked for: the painters begin now (and this tab remembers it asked).
const paintAgain = () => {
  if (!mayPaint.value) return
  sawPainters.value = true
  markArrivedHere()
  portraits.start()
}

// A second summons for the painters. They are called the moment the last
// citizen is counted, but the Scribe may not have closed the roll yet, and the
// painters then decline ("not ready") and wait. Once the hours are set the roll
// is surely closed: ask once more if nothing has been painted or begun. Only a
// gathering first called while citizens were still arriving (phase 1) needs
// this; from phase 2 on the roll is closed, and the first call is enough.
const painterSummons = new Map() // gathering -> 'early' (call again when ready) | 'done'
watch(
  () => [paintedGathering.value, phase.value >= 4],
  async ([gathering, ready]) => {
    if (!gathering || !arrivedHere.value || !mayPaint.value) return
    if (!painterSummons.has(gathering)) painterSummons.set(gathering, phase.value < 2 ? 'early' : 'done')
    if (!ready || painterSummons.get(gathering) !== 'early') return
    painterSummons.set(gathering, 'done')
    await portraits.refresh()
    if (paintedGathering.value === gathering && portraits.status.value === 'none') portraits.start()
  },
  { immediate: true }
)

// --- Words at the top --------------------------------------------------------

const countLine = computed(() => {
  const n = profiles.value.length
  const total = Number(expectedTotal.value) || 0
  if (!n) return t('parthenon.gathering.nobodyYet')
  if (total && n >= total) return t('parthenon.gathering.arrivedAll', { total })
  if (total) return t('parthenon.gathering.arrived', { n, total })
  return t('parthenon.gathering.arrivedSome', { n })
})

// The long wait (the citizens arriving) names its time and gives leave to go.
const waiting = computed(() => !troubleMessage.value && phase.value < 4 && phase.value >= 0 && !arguedFact.value)

// --- A gathering already argued ----------------------------------------------

const hasChronicle = computed(() => !!props.argued?.reportId && String(props.argued?.reportStatus || '').toLowerCase() !== 'failed')

const arguedFact = computed(() => {
  const a = props.argued
  if (!a || !a.argued) return ''
  const per = Number(simulationConfig.value?.time_config?.minutes_per_round) || 60
  const rounds = Math.max(0, Number(a.totalRounds) || 0)
  const at = Math.max(0, Number(a.currentRound) || 0)
  const totalHours = (rounds * per) / 60
  const currentHours = (Math.min(at, rounds || at) * per) / 60
  const inDays = totalHours >= 48
  const unit = inDays ? 24 : 1
  const total = Math.max(1, Math.round(totalHours / unit))
  let current = Math.max(1, inDays ? Math.floor(currentHours / unit) + (a.live ? 1 : 0) : Math.round(currentHours))
  const over = (rounds > 0 && at >= rounds) || String(a.runnerStatus || '').toLowerCase() === 'completed'
  const kind = a.live ? 'live' : over ? 'completed' : 'stopped'
  // A run that stopped early never reads as if it went the distance.
  if (kind === 'stopped' && current >= total) current = Math.max(1, total - 1)
  current = Math.min(current, total)
  return t(`parthenon.gathering.argued.${kind}${inDays ? 'Days' : 'Hours'}`, { current, total }, total)
})

const arguedNote = computed(() => {
  if (!arguedFact.value) return ''
  const chronicle = hasChronicle.value ? t('parthenon.gathering.argued.written') : t('parthenon.gathering.argued.notWritten')
  return `${chronicle} ${t('parthenon.gathering.argued.fixed')}`
})

const stateLine = computed(() => {
  if (troubleMessage.value) return t('parthenon.gathering.stateTrouble')
  if (phase.value >= 4 && arguedFact.value) return t('parthenon.gathering.argued.state')
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

// Up to three names, then "and N others".
const fewNames = (names) => {
  if (names.length <= 3) return joinNames(names)
  return joinNames([...names.slice(0, 3), t('parthenon.gathering.hours.others', { n: names.length - 3 })])
}

const hours = computed(() => {
  const tc = simulationConfig.value?.time_config
  if (!tc) return null
  const offPeak = new Set((tc.off_peak_hours || []).map(Number))
  const peakSet = new Set((tc.peak_hours || []).map(Number))
  const dayHours = Array.from({ length: 24 }, (_, h) => h).filter((h) => !offPeak.has(h))
  const start = dayHours.length ? Math.min(...dayHours) : 6
  const end = dayHours.length ? Math.max(...dayHours) + 1 : 22
  const peak = [...peakSet]
  const peakFrom = peak.length ? Math.min(...peak) : 18
  const peakTo = peak.length ? Math.max(...peak) + 1 : 22
  const peakPhrase = t('parthenon.gathering.hours.peakSpan', {
    part: partOfDay(peakFrom),
    from: hour12(peakFrom),
    to: clockWord(peakTo)
  })
  const configs = agentConfigs.value

  // The strip of hours: who is awake at each hour, weighted as the city is.
  const weightOf = (h) => {
    if (peakSet.has(h)) return Number(tc.peak_activity_multiplier) || 1.5
    if (offPeak.has(h)) return Number(tc.off_peak_activity_multiplier) || 0.05
    if ((tc.morning_hours || []).map(Number).includes(h)) return Number(tc.morning_activity_multiplier) || 0.4
    if ((tc.work_hours || []).map(Number).includes(h)) return Number(tc.work_activity_multiplier) || 0.7
    return 1
  }
  const raw = Array.from({ length: 24 }, (_, h) => {
    const awake = configs.length
      ? configs.reduce((sum, a) => sum + ((a.active_hours || []).map(Number).includes(h) ? Number(a.activity_level) || 0.5 : 0), 0)
      : 1
    return awake * weightOf(h)
  })
  const top = Math.max(...raw, 0.0001)
  const bars = raw.map((v, h) => ({
    hour: h,
    height: Math.max(0.06, v / top).toFixed(3),
    kind: peakSet.has(h) ? 'peak' : offPeak.has(h) ? 'quiet' : 'day'
  }))

  // The loudest voices, the first in and the last out.
  const loudest = [...configs]
    .filter((a) => a.entity_name)
    .sort((a, b) => dailyVoice(b) - dailyVoice(a))
    .slice(0, 3)
    .map((a) => {
      const name = citizenName(a.entity_name)
      return { key: a.entity_name, name, type: a.entity_type, citizen: citizenByName.value.get(nameKey(a.entity_name)) || null }
    })

  // Hours after midnight count as the night before, so a late sitter is not an early riser.
  const late = (h) => (h < 3 ? h + 24 : h)
  const spans = configs
    .filter((a) => a.entity_name && (a.active_hours || []).length && (a.active_hours || []).length < 24)
    .map((a) => {
      const hs = a.active_hours.map(Number).map(late)
      return { name: citizenName(a.entity_name), first: Math.min(...hs), last: Math.max(...hs) + 1 }
    })
  let first = ''
  let last = ''
  if (spans.length > 1) {
    const earliest = Math.min(...spans.map((s) => s.first))
    const latest = Math.max(...spans.map((s) => s.last))
    const early = spans.filter((s) => s.first === earliest).map((s) => s.name)
    const lateOnes = spans.filter((s) => s.last === latest).map((s) => s.name)
    if (early.length < spans.length) first = t('parthenon.gathering.hours.first', { time: clockWord(earliest), names: fewNames(early) })
    if (lateOnes.length < spans.length) last = t('parthenon.gathering.hours.last', { time: clockWord(latest), names: fewNames(lateOnes) })
  }

  return {
    bars,
    day: t('parthenon.gathering.hours.day', { start: partOfDay(start), end: partOfDay(end), peak: peakPhrase }),
    awake: t('parthenon.gathering.hours.awake', { max: tc.agents_per_hour_max ?? '?', min: tc.agents_per_hour_min ?? '?' }),
    loudest,
    first,
    last
  }
})

// --- The first words ---------------------------------------------------------

const topics = computed(() => (simulationConfig.value?.event_config?.hot_topics || []).map((x) => String(x || '').replace(/^#/, '')).filter(Boolean))

// Spoken words, not a notice board: a closing run of hashtags goes, a tag in
// the middle of a sentence keeps its word, and handles become names.
const spoken = (text) =>
  String(text || '')
    .replace(/(?:\s*#[\p{L}\p{N}_]+)+\s*$/u, '')
    .replace(/#([\p{L}\p{N}_]+)/gu, (m, word) => word.replace(/_/g, ' ').replace(/(\p{Ll})(\p{Lu})/gu, '$1 $2'))
    .replace(/@([A-Za-z0-9_]+)/g, (m, handle) => citizenName('', handle))
    .replace(/[ \t]{2,}/g, ' ')
    .trim()

const openings = computed(() =>
  (simulationConfig.value?.event_config?.initial_posts || []).map((post) => {
    const profile = profiles.value[post.poster_agent_id]
    const name = profile ? citizenName(profile.name, profile.username) : t('parthenon.gathering.saying.someone')
    const type = post.poster_type || typeFor(profile?.name)
    return {
      name,
      type: type || profile?.profession || '',
      role: roleWords(type, profile?.profession),
      citizen: profile ? citizens.value[post.poster_agent_id] || null : null,
      text: spoken(post.content)
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

// On the public steps the lengths stop at the longest a visitor may choose.
const openLengths = computed(() =>
  access.public && access.limits ? allowedRunLengths(RUN_LENGTHS, access.limits.max_run) : RUN_LENGTHS
)
const lengths = computed(() =>
  openLengths.value.map((l) => ({
    ...l,
    name: t(`parthenon.gathering.length.names.${l.id}`),
    hoursLabel: t('parthenon.gathering.length.hours', { hours: l.hours }),
    minutesLabel: spansHours(l.minutes)
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
  const chosen = openLengths.value.find((l) => l.id === chosenLength.value) || RUN_LENGTHS.find((l) => l.id === chosenLength.value) || RUN_LENGTHS[1]
  emit('next-step', { maxRounds: chosen.rounds })
}

// --- The citizen's card ------------------------------------------------------

const cardEl = ref(null)
const closeBtn = ref(null)
let returnFocusTo = null
let openedKey = null
let bodyOverflow = ''

const selectedIndex = computed(() => citizens.value.findIndex((c) => c.key === selectedKey.value))
const selected = computed(() => (selectedIndex.value >= 0 ? citizens.value[selectedIndex.value] : null))

const neighbour = (step) => {
  const list = citizens.value
  if (!list.length) return { name: '' }
  const at = selectedIndex.value < 0 ? 0 : selectedIndex.value
  return list[(at + step + list.length) % list.length]
}

const lockPage = (lock) => {
  if (typeof document === 'undefined') return
  if (lock) {
    bodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = bodyOverflow
  }
}

// A card opened from a seat puts focus on its close button; a card opened by
// name from another act (focusCard) puts it on the card itself, so its name is
// what is read first.
const openCard = (citizen, event, { focusCard = false } = {}) => {
  if (!citizen) return
  returnFocusTo = event?.currentTarget || null
  openedKey = citizen.key
  const wasOpen = !!selectedKey.value
  selectedKey.value = citizen.key
  pastOpen.value = false
  if (!wasOpen) lockPage(true)
  nextTick(() => (focusCard ? cardEl.value : closeBtn.value)?.focus())
}

// --- A card asked for by name ------------------------------------------------
// The Agora's "See their card" arrives as ?citizen=<name>. The card opens once
// that citizen is on the slope, matched without regard to case or accents (and
// "Ioanna Pappa" finds "Dr. Ioanna Pappa"). Closing it takes the name off the
// route in place, so Back does not open it again.
const askedFor = computed(() => {
  const q = route.query.citizen
  return String((Array.isArray(q) ? q[0] : q) || '').trim()
})

const findCitizen = (name) => {
  const key = foldName(name)
  if (!key) return null
  let near = null
  for (const c of citizens.value) {
    const keys = [c.name, c.rawName, c.key].map(foldName).filter(Boolean)
    if (keys.includes(key)) return c
    if (!near && key.length > 3 && keys.some((k) => k.length > 3 && (k.endsWith(` ${key}`) || key.endsWith(` ${k}`)))) near = c
  }
  return near
}

let answered = '' // the name last opened from the route, so a closed card stays closed

watch(
  [askedFor, () => citizens.value.length],
  ([name]) => {
    if (!name) {
      answered = ''
      return
    }
    if (name === answered) return
    const citizen = findCitizen(name)
    if (!citizen) return
    answered = name
    openCard(citizen, null, { focusCard: true })
  },
  { immediate: true }
)

const forgetAskedFor = () => {
  if (route.query.citizen === undefined) return
  const { citizen, ...rest } = route.query
  router.replace({ name: route.name, params: route.params, query: rest, hash: route.hash }).catch(() => {})
}

// Focus goes back where the visitor was, or, after walking the slope from the
// card (or arriving at it by name), to the seat of the citizen they last read.
const closeCard = () => {
  if (!selectedKey.value) return
  const last = selectedKey.value
  selectedKey.value = null
  lockPage(false)
  forgetAskedFor()
  nextTick(() => {
    const seat = last !== openedKey || !returnFocusTo
      ? Array.from(document.querySelectorAll('.slope .citizen')).find((el) => el.dataset.seat === String(last))
      : null
    const target = seat || returnFocusTo
    target?.focus?.()
    if (seat) seat.scrollIntoView({ block: 'nearest' })
  })
}

// Walk the slope from the card: the one before, the one after.
const walk = (step) => {
  const next = neighbour(step)
  if (!next?.key) return
  selectedKey.value = next.key
  pastOpen.value = false
  // The body is drawn anew for the next citizen; keep focus in the card.
  nextTick(() => {
    if (!cardEl.value?.contains(document.activeElement)) closeBtn.value?.focus()
  })
}

const onCardKey = (e) => {
  if (e.key === 'Escape') {
    e.preventDefault()
    closeCard()
    return
  }
  if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && !e.altKey && !e.metaKey && !e.ctrlKey) {
    e.preventDefault()
    walk(e.key === 'ArrowRight' ? 1 : -1)
    return
  }
  if (e.key !== 'Tab' || !cardEl.value) return
  const focusable = cardEl.value.querySelectorAll('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (e.shiftKey && (document.activeElement === first || document.activeElement === cardEl.value)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

// A citizen who leaves the list (a new call, a reload) closes their card.
watch(selected, (now) => {
  if (!now && selectedKey.value) {
    selectedKey.value = null
    lockPage(false)
  }
})

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

const handlePrepareFailure = (message, err = null) => {
  const calm = calmLine(err)
  if (calm) {
    // A limit of the public steps: said calmly, never as trouble.
    stopPolling()
    stopProfilesPolling()
    stopConfigPolling()
    calmMessage.value = calm
    addLog(calm)
    emit('update-status', 'error')
    return
  }
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

      // The crowd is arriving while the visitor watches: their faces follow on their own.
      markArrivedHere()
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
    handlePrepareFailure(err.message, err)
  }
}

const callAgain = () => {
  troubleMessage.value = ''
  calmMessage.value = ''
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
      } else if (data.status === 'not_started' && !control.value) {
        // A guest, and the one who began it has not called the citizens yet.
        stopPolling()
        stopProfilesPolling()
        phase.value = 0
        guestWaiting.value = true
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

// A guest never calls the citizens: they watch the preparation as it stands.
const watchAsGuest = () => {
  phase.value = 1
  addLog(t('parthenon.gathering.ledger.summoning'))
  startPolling()
  startProfilesPolling()
  pollPrepareStatus()
}

onMounted(() => {
  if (!props.simulationId) return
  if (control.value) startPrepareSimulation()
  else watchAsGuest()
})

onUnmounted(() => {
  stopPolling()
  stopProfilesPolling()
  stopConfigPolling()
  if (selectedKey.value) lockPage(false)
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

/* Chinese is not set in capitals with inscription tracking. */
.p-eyebrow:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
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

/* The painters */
.painters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-top: 6px;
  padding: 10px 14px;
  border: 1px solid var(--p-line);
  border-left: 2px solid var(--p-gold);
  background: var(--p-terracotta-tint);
  max-width: 44em;
  min-width: 0;
}

.painters.is-failed { border-left-color: var(--p-ink-4); background: var(--p-surface); }
.painters.is-done { background: transparent; }

.painters-mark {
  width: 8px;
  height: 8px;
  border-radius: var(--p-radius-coin);
  background: var(--p-gold);
  flex-shrink: 0;
}

.painters.is-working .painters-mark { animation: brush 1.6s ease-in-out infinite; }
.painters.is-failed .painters-mark { background: var(--p-ink-4); }

@keyframes brush {
  0%, 100% { box-shadow: 0 0 0 0 rgba(240, 182, 96, 0.5); }
  50% { box-shadow: 0 0 0 6px rgba(240, 182, 96, 0); }
}

.painters-line {
  flex: 1 1 220px;
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink);
  min-width: 0;
}

.painters-meter {
  flex: 0 0 120px;
  height: 2px;
  background: var(--p-line-strong);
  overflow: hidden;
}

.painters-fill {
  display: block;
  height: 100%;
  background: var(--p-gold);
  transition: width 0.8s ease;
}

.painters-cost {
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

.painters.is-offer { background: transparent; border-left-color: var(--p-ink-4); }
.painters.is-offer .painters-mark { background: var(--p-ink-4); }

.wait-note {
  margin: 4px 0 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
  max-width: 44em;
}

.wait-note a {
  color: var(--p-ink);
  text-decoration: underline;
  text-decoration-color: var(--p-gold);
  text-underline-offset: 3px;
}

/* Trouble */
.calm-block {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

.calm-block p {
  margin: 0;
}

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
  /* A thumb needs 40px; the marker is drawn here because a flex summary loses its own. */
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  list-style: none;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.trouble-why summary::-webkit-details-marker { display: none; }

.trouble-why summary::before {
  content: '';
  flex: none;
  width: 0;
  height: 0;
  border-block: 4px solid transparent;
  border-inline-start: 6px solid currentColor;
  transition: transform 0.2s ease;
}

.trouble-why[open] summary::before { transform: rotate(90deg); }

.trouble-why summary:hover { color: var(--p-ink-2); }

.trouble-why summary:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 3px;
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
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
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
  gap: 16px;
  align-items: start;
  padding: 16px;
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

.citizen:focus-visible,
.voice:focus-visible,
.opening-face:focus-visible,
.walk:focus-visible,
.card-close:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 2px;
}

/* A face arrives the way a citizen does: it settles in. */
.citizen :deep(.citizen-coin img),
.voice :deep(.citizen-coin img),
.opening-face :deep(.citizen-coin img) {
  animation: face-in 0.9s ease both;
}

@keyframes face-in {
  from { opacity: 0; transform: scale(1.08); filter: blur(3px); }
  to { opacity: 1; transform: scale(1); filter: none; }
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
  gap: 16px;
  align-items: start;
  padding: 16px;
  border: 1px dashed var(--p-line);
  opacity: 0.7;
}

.ghost-coin {
  width: 56px;
  height: 56px;
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

/* The strip of hours */
.dial {
  margin: 8px 0 10px;
  max-width: 44em;
  min-width: 0;
}

.dial-bars {
  display: grid;
  grid-template-columns: repeat(24, minmax(0, 1fr));
  gap: 3px;
  align-items: end;
  height: 72px;
  border-bottom: 1px solid var(--p-line-strong);
}

.dial-bar {
  height: calc(var(--h) * 100%);
  background: var(--p-ink-4);
  opacity: 0.5;
  transform-origin: bottom;
  animation: rise 0.9s cubic-bezier(0.2, 0.7, 0.2, 1) both;
  animation-delay: calc(var(--i, 0) * 22ms);
}

.dial-bar.is-peak {
  background: var(--p-gold);
  opacity: 1;
}

.dial-bar.is-quiet { opacity: 0.25; }

@keyframes rise {
  from { transform: scaleY(0); }
  to { transform: scaleY(1); }
}

.dial-marks {
  position: relative;
  height: 18px;
  margin-top: 6px;
  font-family: var(--p-font-inscription);
  font-size: 0.6875rem;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.dial-marks span {
  position: absolute;
  top: 0;
  left: calc(var(--at) * 100%);
  transform: translateX(-50%);
  white-space: nowrap;
}

.dial-marks span:first-child { transform: none; }
.dial-marks span:last-child { transform: translateX(-100%); }

/* The loudest voices */
.loudest {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 6px;
}

.loudest-lead {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  font-weight: 400;
  color: var(--p-ink-2);
}

.voices {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.voices li { min-width: 0; max-width: 100%; }

.voice {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  max-width: 100%;
  padding: 6px 14px 6px 6px;
  background: var(--p-surface);
  border: 1px solid var(--p-line-strong);
  border-radius: var(--p-radius);
  color: var(--p-ink);
  font: inherit;
  cursor: pointer;
  transition: border-color 0.2s ease;
}

span.voice { cursor: default; }
button.voice:hover { border-color: var(--p-gold); }

.voice-name {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  line-height: 1.2;
  text-align: left;
  overflow-wrap: anywhere;
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
  gap: 16px;
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

.opening-face {
  display: inline-flex;
  padding: 2px;
  margin: -2px;
  background: transparent;
  border: 0;
  border-radius: var(--p-radius-coin);
  cursor: pointer;
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

/* The small button is 34px tall; a thumb needs 40. */
.saying > .p-button,
.painters .p-button,
.trouble .p-button,
.card-toggle { min-height: 40px; }

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
  outline: none;
  width: min(100%, 680px);
  max-height: min(88vh, 900px);
  display: flex;
  flex-direction: column;
  box-shadow: var(--p-shadow-2);
  border-radius: var(--p-radius);
  overflow: hidden;
}

.card-close {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 2;
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--p-surface) 88%, transparent);
  border: 1px solid transparent;
  border-radius: var(--p-radius);
  color: var(--p-ink-3);
  cursor: pointer;
}

.card-close:hover { color: var(--p-ink); border-color: var(--p-line-strong); }

.card-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 28px 32px 28px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* The scroller must not squeeze its rows; the empty Greek key band would vanish. */
.card-body > * { flex-shrink: 0; }

.card-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 22px;
  align-items: center;
  padding-right: 40px;
}

.card-id {
  display: flex;
  flex-direction: column;
  gap: 6px;
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

.card-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 20px 28px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--p-line);
}

.card-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.card-section h4 { margin: 0; }

.card-stand {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  line-height: 1.25;
  color: var(--p-ink);
}

.card-quote {
  margin: 0;
  padding-left: 14px;
  border-left: 2px solid var(--p-terracotta);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--p-ink);
}

.card-note {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.55;
  color: var(--p-ink-2);
}

/* The beam: against on the left, for on the right. */
.scale {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}

.scale-end {
  font-family: var(--p-font-inscription);
  font-size: 0.6875rem;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.scale-beam {
  position: relative;
  height: 14px;
}

.scale-beam::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  height: 1px;
  background: var(--p-line-strong);
}

.scale-mid {
  position: absolute;
  left: 50%;
  top: 2px;
  bottom: 2px;
  width: 1px;
  background: var(--p-control-border);
}

.scale-mark {
  position: absolute;
  top: 50%;
  width: 11px;
  height: 11px;
  background: var(--p-terracotta);
  transform: translate(-50%, -50%) rotate(45deg);
}

.scale.watching .scale-mark {
  background: var(--p-surface);
  border: 1.5px solid var(--p-ink-3);
}

.card-prose {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.7;
  color: var(--p-ink-2);
  max-width: 36em;
}

.card-more {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card-toggle { align-self: flex-start; }

.card-topics {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
}

/* Walking the slope from the card */
.card-walk {
  flex: 0 0 auto;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--p-line-strong);
  background: var(--p-surface-2);
}

.walk {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  min-width: 0;
  max-width: 48%;
  padding: 4px 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--p-radius);
  color: var(--p-ink-2);
  font: inherit;
  cursor: pointer;
}

.walk:hover { border-color: var(--p-line-strong); color: var(--p-ink); }
.walk svg { flex-shrink: 0; }

.walk-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
}

.card-enter-active,
.card-leave-active { transition: opacity 0.25s ease; }

.card-enter-active .card,
.card-leave-active .card { transition: transform 0.3s cubic-bezier(0.2, 0.7, 0.2, 1); }

.card-enter-from,
.card-leave-to { opacity: 0; }

.card-enter-from .card,
.card-leave-to .card { transform: translateY(14px); }

/* With motion reduced every seat is taken at once: the global rule shortens
   the animation but not its delay, and "both" would hold each card unseen
   until its turn. The same holds for the hours and the faces. */
@media (prefers-reduced-motion: reduce) {
  .seat,
  .opening,
  .dial-bar,
  .painters.is-working .painters-mark,
  .citizen :deep(.citizen-coin img),
  .voice :deep(.citizen-coin img),
  .opening-face :deep(.citizen-coin img) {
    animation: none;
  }

  .citizen,
  .length-option,
  .voice,
  .painters-fill,
  .trouble-why summary::before {
    transition: none;
  }

  .card-enter-from .card,
  .card-leave-to .card { transform: none; }
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
  .card { width: 100%; max-height: 92vh; max-height: 92dvh; }
  .card-body { padding: 22px 16px 24px; gap: 18px; }
  .card-head { gap: 16px; }
  .card-name { font-size: var(--t-xl); }
  .card-walk { padding: 6px 8px calc(6px + env(safe-area-inset-bottom, 0px)); }
  .painters-meter { flex-basis: 100%; }

  /* Capitals with wide tracking crowd each other at phone width. */
  .dial-marks {
    font-family: var(--p-font-serif);
    font-style: italic;
    font-size: var(--t-xs);
    letter-spacing: 0;
    text-transform: none;
  }
}
</style>
