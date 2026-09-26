<template>
  <section ref="rootRef" class="symposium" :class="{ 'crowd-mode': mode === 'crowd' }">
    <!-- The room band: who is here, and the two doors out of the ordinary conversation. -->
    <header class="room-band">
      <div class="room-copy">
        <span class="p-eyebrow">{{ t('step5.symposium.room') }}</span>
        <h2 class="room-title">{{ t('step5.symposium.whoIsHere') }}</h2>
        <p class="room-line">{{ companyLine }}</p>
      </div>
      <div class="room-actions">
        <button
          type="button"
          class="p-button secondary"
          :aria-pressed="mode === 'crowd'"
          @click="toggleCrowdMode"
        >{{ mode === 'crowd' ? t('step5.symposium.backToTable') : t('step5.symposium.askCrowd') }}</button>
        <button
          ref="chronicleToggle"
          type="button"
          class="p-button secondary"
          :aria-expanded="chronicleOpen"
          aria-controls="chronicle-drawer"
          @click="openChronicle"
        >{{ t('step5.symposium.readChronicle') }}</button>
      </div>
    </header>

    <div class="room">
      <!-- The couches: the Scribe at the head, the citizens along the wall. -->
      <div class="couches" role="group" :aria-label="t('step5.symposium.couches')">
        <p class="couches-hint" aria-live="polite">{{ mode === 'crowd' ? t('step5.symposium.chooseCrowd') : t('step5.symposium.chooseSeat') }}</p>

        <button
          type="button"
          class="couch head"
          :class="{ seated: mode === 'chat' && chatTarget === 'report_agent' }"
          :aria-pressed="mode === 'chat' ? chatTarget === 'report_agent' : undefined"
          :disabled="mode === 'crowd'"
          @click="sitWithScribe"
        >
          <span class="p-coin couch-coin scribe-coin" aria-hidden="true">Σ</span>
          <span class="couch-text">
            <span v-if="mode === 'chat' && chatTarget === 'report_agent'" class="couch-badge">{{ t('step5.symposium.seated') }}</span>
            <span v-else-if="mode === 'crowd'" class="couch-badge quiet">{{ t('step5.symposium.scribeListens') }}</span>
            <span class="couch-name">{{ t('step5.symposium.scribe') }}</span>
            <span class="couch-role">{{ t('step5.symposium.scribeRole') }}</span>
            <span class="couch-line">{{ t('step5.symposium.scribeLine') }}</span>
          </span>
        </button>

        <ul id="symposium-couches" class="couch-list" role="list">
          <li v-for="citizen in visibleCitizens" :key="citizen.key">
            <button
              type="button"
              class="couch"
              :class="{
                seated: mode === 'chat' && selectedAgentIndex === citizen.idx,
                chosen: mode === 'crowd' && selectedAgents.has(citizen.idx),
                away: !cityAwake
              }"
              :style="{ '--role': citizen.color }"
              :aria-pressed="mode === 'crowd' ? selectedAgents.has(citizen.idx) : selectedAgentIndex === citizen.idx && chatTarget === 'agent'"
              @click="mode === 'crowd' ? toggleAgentSelection(citizen.idx) : sitWith(citizen, citizen.idx)"
            >
              <span class="p-coin couch-coin" aria-hidden="true">{{ citizen.initial }}</span>
              <span class="couch-text">
                <span v-if="mode === 'chat' && selectedAgentIndex === citizen.idx && chatTarget === 'agent'" class="couch-badge">{{ t('step5.symposium.seated') }}</span>
                <span v-else-if="mode === 'crowd' && selectedAgents.has(citizen.idx)" class="couch-badge">{{ t('step5.symposium.willAnswer') }}</span>
                <span v-else-if="!cityAwake" class="couch-badge quiet">{{ t('step5.symposium.away') }}</span>
                <span class="couch-name">{{ citizen.name }}</span>
                <span class="couch-role">{{ citizen.role }}</span>
                <span v-if="citizen.line" class="couch-line">{{ citizen.line }}</span>
              </span>
            </button>
          </li>
        </ul>

        <!-- On phones the couches are a short column: the Scribe and six citizens, the rest behind one button. -->
        <div v-if="couchesFolded || couchesUnfolded" class="couches-more">
          <p v-if="couchesFolded" class="couches-hidden">{{ capital(t('step5.symposium.moreOnCouches', { n: hiddenCount, w: inWords(hiddenCount) })) }}</p>
          <button
            type="button"
            class="p-button ghost small"
            :aria-expanded="couchesOpen"
            aria-controls="symposium-couches"
            @click="toggleCouches"
          >{{ couchesOpen ? t('step5.symposium.seeFewer') : t('step5.symposium.seeAll', { n: citizens.length, w: inWords(citizens.length) }) }}</button>
        </div>
      </div>

      <!-- The table: one conversation, staged as dialogue. -->
      <div v-if="mode === 'chat'" class="table">
        <div class="table-band">
          <span class="p-coin band-coin" :class="{ 'scribe-coin': chatTarget === 'report_agent' }" :style="companion ? { '--role': companion.color } : null" aria-hidden="true">{{ companion ? companion.initial : 'Σ' }}</span>
          <div class="band-text">
            <span class="p-eyebrow">{{ t('step5.symposium.seatedWith') }}</span>
            <h3 class="band-name">{{ companion ? companion.name : t('step5.symposium.scribe') }}</h3>
            <p class="band-role">{{ companion ? companion.role : t('step5.symposium.scribeRole') }}</p>
            <p class="band-line">{{ companion ? companion.line : t('step5.symposium.scribeLine') }}</p>
          </div>
        </div>
        <div class="p-meander table-rule" aria-hidden="true"></div>

        <ol class="dialogue" role="log" aria-live="polite" aria-relevant="additions">
          <li v-if="chatHistory.length === 0 && !isSending" class="dialogue-empty">
            <p>{{ chatTarget === 'report_agent' ? t('step5.symposium.emptyScribe') : t('step5.symposium.emptyCitizen', { name: companion ? companion.name : '' }) }}</p>
          </li>
          <li
            v-for="(msg, idx) in chatHistory"
            :key="idx"
            class="line"
            :class="msg.role === 'user' ? 'asked' : 'answered'"
          >
            <template v-if="msg.role === 'user'">
              <div class="asked-text">{{ msg.content }}</div>
              <span class="line-meta"><span class="line-who">{{ t('step5.symposium.you') }}</span> {{ formatTime(msg.timestamp) }}</span>
            </template>
            <template v-else>
              <span class="p-coin line-coin" :class="{ 'scribe-coin': chatTarget === 'report_agent' }" :style="companion ? { '--role': companion.color } : null" aria-hidden="true">{{ companion ? companion.initial : 'Σ' }}</span>
              <div class="answered-body">
                <span class="line-meta"><span class="line-who">{{ companion ? companion.name : t('step5.symposium.scribe') }}</span> {{ formatTime(msg.timestamp) }}</span>
                <div class="answered-text" v-html="renderMarkdown(msg.content)"></div>
              </div>
            </template>
          </li>
          <li v-if="isSending" class="line answered thinking">
            <span class="p-coin line-coin" :class="{ 'scribe-coin': chatTarget === 'report_agent' }" :style="companion ? { '--role': companion.color } : null" aria-hidden="true">{{ companion ? companion.initial : 'Σ' }}</span>
            <div class="answered-body">
              <span class="line-meta"><span class="line-who">{{ workingText }}</span></span>
              <span class="ellipsis" aria-hidden="true"><i></i><i></i><i></i></span>
            </div>
          </li>
        </ol>

        <div class="prompt" :class="{ stuck: chatHistory.length > 0 }">
          <p v-if="!cityAwake && chatTarget === 'agent'" class="asleep-note" role="status">
            {{ t('step5.symposium.asleepCitizen', { name: companion ? companion.name : '' }) }}
            <button type="button" class="p-button ghost small" @click="sitWithScribe">{{ t('step5.symposium.sitWithScribe') }}</button>
          </p>

          <!-- Socratic questions: they are placed in the mouth, not sent. -->
          <div
            v-if="Array.isArray(socraticPrompts)"
            class="socratic-row"
            role="group"
            :aria-label="t('step5.socraticLabel')"
          >
            <span class="p-eyebrow socratic-label">{{ t('step5.socraticLabel') }}</span>
            <button
              v-for="(question, qIdx) in socraticPrompts"
              :key="qIdx"
              type="button"
              class="socratic-chip"
              :disabled="isChatInputDisabled"
              @click="insertSocraticPrompt(question)"
            >{{ question }}</button>
          </div>

          <form class="ask" @submit.prevent="sendMessage">
            <label class="sr-only" for="symposium-ask">{{ chatTarget === 'report_agent' ? t('step5.symposium.placeholderScribe') : t('step5.symposium.placeholder') }}</label>
            <textarea
              id="symposium-ask"
              ref="chatInputRef"
              v-model="chatInput"
              class="ask-input"
              :placeholder="chatTarget === 'report_agent' ? t('step5.symposium.placeholderScribe') : t('step5.symposium.placeholder')"
              rows="1"
              :disabled="isChatInputDisabled"
              @keydown.enter.exact.prevent="sendMessage"
              @input="growInput"
            ></textarea>
            <button
              type="submit"
              class="p-button ask-send"
              :disabled="!chatInput.trim() || isChatInputDisabled"
            >{{ isSending ? t('step5.symposium.sending') : t('step5.symposium.send') }}</button>
          </form>
        </div>
      </div>

      <!-- The crowd: one question, many voices. -->
      <div v-else class="table crowd">
        <div class="crowd-head">
          <span class="p-eyebrow">{{ t('step5.symposium.askCrowd') }}</span>
          <h3 class="band-name">{{ t('step5.symposium.crowdTitle') }}</h3>
          <p class="band-line">{{ t('step5.symposium.crowdHint') }}</p>
        </div>
        <div class="p-meander table-rule" aria-hidden="true"></div>

        <div class="crowd-pick">
          <p class="crowd-count" aria-live="polite">{{ crowdCountLine }}</p>
          <div class="crowd-links">
            <button type="button" class="p-button ghost small" :disabled="!citizens.length" @click="selectAllAgents">{{ t('step5.symposium.everyone') }}</button>
            <button type="button" class="p-button ghost small" :disabled="!selectedAgents.size" @click="clearAgentSelection">{{ t('step5.symposium.noOne') }}</button>
          </div>
        </div>
        <ul v-if="chosenCitizens.length" class="faces" role="list" :aria-label="t('step5.symposium.chooseCrowd')">
          <li v-for="c in chosenCitizens" :key="c.key" class="face">
            <span class="p-coin face-coin" :style="{ '--role': c.color }" aria-hidden="true">{{ c.initial }}</span>
            <span class="face-name">{{ c.name }}</span>
          </li>
        </ul>

        <form class="ask crowd-ask" @submit.prevent="submitSurvey">
          <label class="sr-only" for="symposium-crowd">{{ t('step5.symposium.crowdPlaceholder') }}</label>
          <textarea
            id="symposium-crowd"
            v-model="surveyQuestion"
            class="ask-input"
            :placeholder="t('step5.symposium.crowdPlaceholder')"
            rows="2"
            :disabled="isSurveying || !cityAwake"
          ></textarea>
          <div class="crowd-submit">
            <button
              type="submit"
              class="p-button"
              :disabled="!canAskCrowd"
            >{{ isSurveying ? t('step5.symposium.crowdAnswering') : t('step5.symposium.askTheCrowd') }}</button>
            <span v-if="crowdReason" class="ask-reason">{{ crowdReason }}</span>
          </div>
        </form>

        <div v-if="surveyResults.length" class="answers">
          <div class="answers-head">
            <span class="p-eyebrow">{{ t('step5.symposium.answers') }}</span>
            <p class="crowd-count">{{ answersCountLine }}</p>
          </div>
          <ul class="faces" role="list">
            <li v-for="r in surveyResults" :key="r.agent_id" class="face">
              <span class="p-coin face-coin" :style="{ '--role': r.color }" aria-hidden="true">{{ r.initial }}</span>
              <span class="face-name">{{ r.name }}</span>
            </li>
          </ul>
          <p class="answers-question">{{ surveyResults[0].question }}</p>
          <ul class="reply-list" role="list">
            <li v-for="r in surveyResults" :key="`reply-${r.agent_id}`" class="reply">
              <span class="p-coin line-coin" :style="{ '--role': r.color }" aria-hidden="true">{{ r.initial }}</span>
              <div class="answered-body">
                <span class="line-meta"><span class="line-who">{{ r.name }}</span> {{ r.role }}</span>
                <div class="answered-text" v-html="renderMarkdown(r.answer)"></div>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- The Chronicle, held up in the dark: a page of parchment that slides in from the side. -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="chronicleOpen" class="drawer-root">
          <div class="drawer-backdrop" aria-hidden="true" @click="closeChronicle"></div>
          <aside
            id="chronicle-drawer"
            class="chronicle p-paper"
            role="dialog"
            aria-modal="true"
            :aria-label="t('step5.symposium.chronicle')"
            @keydown.esc.prevent="closeChronicle"
            @keydown.tab="trapFocus"
          >
            <div class="chronicle-bar">
              <span class="p-eyebrow">Δ΄ · {{ t('step5.symposium.chronicle') }}</span>
              <button ref="chronicleClose" type="button" class="p-button ghost small" @click="closeChronicle">{{ t('step5.symposium.closeChronicle') }}</button>
            </div>
            <div class="chronicle-page">
              <template v-if="reportOutline">
                <h1 class="chronicle-title">{{ reportOutline.title }}</h1>
                <p v-if="reportOutline.summary" class="chronicle-summary">{{ reportOutline.summary }}</p>
                <div v-if="question" class="chronicle-question">
                  <span class="p-eyebrow">{{ t('step5.symposium.theQuestion') }}</span>
                  <p>{{ question }}</p>
                </div>
                <div class="p-meander chronicle-rule" aria-hidden="true"></div>
                <article v-for="(section, idx) in reportOutline.sections" :key="idx" class="chapter">
                  <span class="p-eyebrow">{{ t('step5.symposium.chapter') }} {{ greekNumeral(idx + 1) }}</span>
                  <h2 class="chapter-title">{{ section.title }}</h2>
                  <div v-if="generatedSections[idx + 1]" class="chapter-body" v-html="renderMarkdown(generatedSections[idx + 1])"></div>
                  <p v-else class="chapter-pending">{{ t('step5.symposium.chapterPending') }}</p>
                </article>
              </template>
              <p v-else class="chronicle-waiting">{{ t('step5.symposium.chronicleWaiting') }}</p>
              <router-link v-if="reportId" class="p-button secondary chronicle-link" :to="{ name: 'Report', params: { reportId } }">{{ t('step5.symposium.openChronicleAct') }}</router-link>
            </div>
          </aside>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup>
// Act Ε΄, the Symposium. The citizens sit on couches along the wall, the Scribe
// at the head; the visitor sits down with one of them and the conversation is
// staged as dialogue, or puts one question to the whole crowd. Every call the
// old workbench made (chat with the Scribe, interviews, the Chronicle's pages,
// the citizens' profiles) is kept; only the room around them is new.
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { chatWithReport, getReport, getAgentLog } from '../api/report'
import { interviewAgents, getSimulationProfilesRealtime, getEnvStatus } from '../api/simulation'
import { citizenName, entityTypeName, roleFamily, ROLE_COLOR_VAR } from '../parthenon/vocabulary.js'

const { t, tm } = useI18n()

const props = defineProps({
  reportId: String,
  simulationId: String
})

const emit = defineEmits(['add-log', 'update-status'])

// Room state
const mode = ref('chat') // chat | crowd
const chatTarget = ref('report_agent') // report_agent | agent
const selectedAgent = ref(null)
const selectedAgentIndex = ref(null)
const cityAwake = ref(true)

// Chat state
const chatInput = ref('')
const chatHistory = ref([])
const chatHistoryCache = ref({}) // { report_agent: [], agent_0: [], ... }
const isSending = ref(false)
const chatInputRef = ref(null)

// Crowd state
const selectedAgents = ref(new Set())
const surveyQuestion = ref('')
const surveyResults = ref([])
const isSurveying = ref(false)

// The Chronicle
const reportOutline = ref(null)
const generatedSections = ref({})
const question = ref('')
const profiles = ref([])
const chronicleOpen = ref(false)
const chronicleToggle = ref(null)
const chronicleClose = ref(null)
const rootRef = ref(null)

// Narrow rooms (phones and small tablets): the couches stand in one column and
// fold after the Scribe and six citizens, so the table is never far below.
const NARROW = '(max-width: 1023px)'
const COUCH_PEEK = 6
const narrowQuery = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(NARROW) : null
const isNarrow = ref(narrowQuery ? narrowQuery.matches : false)
const onNarrowChange = (e) => { isNarrow.value = e.matches }
const couchesOpen = ref(false)

const socraticPrompts = computed(() => tm('step5.socraticPrompts'))

// Words for small numbers: the city counts in words.
const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty']
const inWords = (n) => (n >= 0 && n < WORDS.length ? WORDS[n] : String(n))
const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
const GREEK = ['Α΄', 'Β΄', 'Γ΄', 'Δ΄', 'Ε΄', 'Ϛ΄', 'Ζ΄', 'Η΄', 'Θ΄', 'Ι΄', 'ΙΑ΄', 'ΙΒ΄']
const greekNumeral = (n) => GREEK[n - 1] || String(n)

// A citizen as the room sees them: a name without a suffix, a role in words,
// one line of their own, and the colour of their family.
const ACCOUNT_PREFIX = /^(this is )?(the )?(official )?(civic |public |municipal )?(account|channel|office|desk|page|profile|biography)( biography)?( for the public channel)?( of)?\s*/i
const familyOf = (name, profession) => {
  const text = `${name} ${profession}`
  if (/\b(campaign|movement|coalition)\b/i.test(text)) return 'movements'
  if (/\b(compute|company|firm|corporation|council|cooperative|association|secretariat|school|ministry|outlet|agency|authority)\b/i.test(text)) return 'institutions'
  return roleFamily(profession)
}
const roleLine = (p) => {
  const raw = String(p.profession || '').trim()
  if (raw) return capital(raw.split(/[,;(]/)[0].trim())
  const typed = entityTypeName(p.entity_type || p.type)
  return typed ? capital(typed) : ''
}
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const bioLine = (p, name) => {
  let text = String(p.bio || p.persona || '').replace(/\s+/g, ' ').trim()
  text = text.replace(ACCOUNT_PREFIX, '')
  if (name) text = text.replace(new RegExp(`^(the )?${escapeRe(name)}\\s*(,|:|is|was)?\\s*`, 'i'), '')
  const first = text.split(/(?<=[.!?])\s+/)[0] || ''
  return capital(first.length > 160 ? `${first.slice(0, 157).replace(/\s+\S*$/, '')}...` : first)
}
const citizens = computed(() =>
  profiles.value.map((p, idx) => {
    const name = citizenName(p.name, p.username) || `Citizen ${idx + 1}`
    const profession = String(p.profession || '')
    return {
      key: p.user_id ?? p.username ?? idx,
      idx,
      name,
      initial: name.replace(/^(the|dr\.?|father|mother)\s+/i, '').charAt(0).toUpperCase() || 'Α',
      role: roleLine(p) || t('step2.unknownProfession'),
      line: bioLine(p, name),
      color: ROLE_COLOR_VAR[familyOf(name, profession)] || ROLE_COLOR_VAR.people
    }
  })
)
const couchesFolded = computed(() => isNarrow.value && !couchesOpen.value && citizens.value.length > COUCH_PEEK)
const couchesUnfolded = computed(() => isNarrow.value && couchesOpen.value && citizens.value.length > COUCH_PEEK)
const visibleCitizens = computed(() => (couchesFolded.value ? citizens.value.slice(0, COUCH_PEEK) : citizens.value))
const hiddenCount = computed(() => Math.max(0, citizens.value.length - COUCH_PEEK))
const companion = computed(() => (chatTarget.value === 'agent' && selectedAgentIndex.value !== null ? citizens.value[selectedAgentIndex.value] : null))
const chosenCitizens = computed(() => citizens.value.filter((c) => selectedAgents.value.has(c.idx)))

const companyLine = computed(() => {
  const n = citizens.value.length
  if (!n) return t('step5.symposium.companyScribeOnly')
  if (n === 1) return t('step5.symposium.companyOne')
  return t('step5.symposium.company', { n, w: inWords(n) })
})
const crowdCountLine = computed(() => {
  const n = selectedAgents.value.size
  if (!n) return t('step5.symposium.crowdNone')
  if (n === 1) return t('step5.symposium.crowdCountOne')
  return capital(t('step5.symposium.crowdCount', { n, w: inWords(n) }))
})
const answersCountLine = computed(() => {
  const n = surveyResults.value.length
  if (n === 1) return t('step5.symposium.answersCountOne')
  return capital(t('step5.symposium.answersCount', { n, w: inWords(n) }))
})
const workingText = computed(() =>
  chatTarget.value === 'report_agent'
    ? t('step5.symposium.scribeWriting')
    : t('step5.symposium.thinking', { name: companion.value ? companion.value.name : '' })
)

const isChatInputDisabled = computed(() =>
  isSending.value || (chatTarget.value === 'agent' && (selectedAgentIndex.value === null || !cityAwake.value))
)
const canAskCrowd = computed(() => cityAwake.value && selectedAgents.value.size > 0 && !!surveyQuestion.value.trim() && !isSurveying.value)
const crowdReason = computed(() => {
  if (isSurveying.value) return ''
  if (!cityAwake.value) return t('step5.symposium.asleep')
  if (!selectedAgents.value.size) return t('step5.symposium.needCrowd')
  if (!surveyQuestion.value.trim()) return t('step5.symposium.needQuestion')
  return ''
})

const addLog = (msg) => emit('add-log', msg)
const setStatus = (status, text = '') => emit('update-status', status, text)

// Seats
const saveChatHistory = () => {
  if (chatTarget.value === 'report_agent') {
    chatHistoryCache.value.report_agent = [...chatHistory.value]
  } else if (selectedAgentIndex.value !== null) {
    chatHistoryCache.value[`agent_${selectedAgentIndex.value}`] = [...chatHistory.value]
  }
}

const sitWithScribe = () => {
  saveChatHistory()
  mode.value = 'chat'
  chatTarget.value = 'report_agent'
  selectedAgent.value = null
  selectedAgentIndex.value = null
  chatHistory.value = chatHistoryCache.value.report_agent || []
  addLog(t('step5.symposium.ledger.sat', { name: t('step5.symposium.scribe') }))
  revealTable()
  focusInput()
}

const sitWith = (citizen, idx) => {
  saveChatHistory()
  mode.value = 'chat'
  selectedAgent.value = profiles.value[idx]
  selectedAgentIndex.value = idx
  chatTarget.value = 'agent'
  chatHistory.value = chatHistoryCache.value[`agent_${idx}`] || []
  addLog(t('step5.symposium.ledger.sat', { name: citizen.name }))
  if (!cityAwake.value) checkCity()
  revealTable()
  focusInput()
}

const focusInput = () => {
  nextTick(() => {
    const el = chatInputRef.value
    if (el && !el.disabled) el.focus({ preventScroll: true })
  })
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

// On a phone the table stands below the couches; sitting down carries the
// visitor to it, so the dialogue is where they look, not a scroll away.
const revealTable = () => {
  if (!isNarrow.value) return
  nextTick(() => {
    const el = rootRef.value ? rootRef.value.querySelector('.table') : null
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'start', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
    }
  })
}

// Unfold the couches; keyboard visitors land on the first newly shown citizen.
const toggleCouches = () => {
  const opening = !couchesOpen.value
  couchesOpen.value = opening
  nextTick(() => {
    const root = rootRef.value
    if (!root) return
    const cards = root.querySelectorAll('.couch-list .couch')
    const target = opening ? cards[COUCH_PEEK] : cards[0]
    if (target) target.focus({ preventScroll: !opening })
  })
}

const toggleCrowdMode = () => {
  if (mode.value === 'crowd') {
    mode.value = 'chat'
    focusInput()
  } else {
    saveChatHistory()
    mode.value = 'crowd'
    if (!cityAwake.value) checkCity()
  }
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

const growInput = () => {
  const el = chatInputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

// What the Scribe and the citizens write comes as Markdown.
const renderMarkdown = (content) => {
  if (!content) return ''

  let processedContent = content.replace(/^##\s+.+\n+/, '')
  let html = processedContent.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>')
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>')
  html = html.replace(/^> (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')

  html = html.replace(/^(\s*)- (.+)$/gm, (match, indent, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-li" data-level="${level}">${text}</li>`
  })
  html = html.replace(/^(\s*)(\d+)\. (.+)$/gm, (match, indent, num, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-oli" data-level="${level}">${text}</li>`
  })

  html = html.replace(/(<li class="md-li"[^>]*>.*?<\/li>\s*)+/g, '<ul class="md-ul">$&</ul>')
  html = html.replace(/(<li class="md-oli"[^>]*>.*?<\/li>\s*)+/g, '<ol class="md-ol">$&</ol>')

  html = html.replace(/<\/li>\s+<li/g, '</li><li')
  html = html.replace(/<ul class="md-ul">\s+/g, '<ul class="md-ul">')
  html = html.replace(/<ol class="md-ol">\s+/g, '<ol class="md-ol">')
  html = html.replace(/\s+<\/ul>/g, '</ul>')
  html = html.replace(/\s+<\/ol>/g, '</ol>')

  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/_(.+?)_/g, '<em>$1</em>')
  html = html.replace(/^---$/gm, '<hr class="md-hr">')
  html = html.replace(/\n\n/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  html = '<p class="md-p">' + html + '</p>'
  html = html.replace(/<p class="md-p"><\/p>/g, '')
  html = html.replace(/<p class="md-p">(<h[2-5])/g, '$1')
  html = html.replace(/(<\/h[2-5]>)<\/p>/g, '$1')
  html = html.replace(/<p class="md-p">(<ul|<ol|<blockquote|<pre|<hr)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/pre>)<\/p>/g, '$1')
  html = html.replace(/<br>\s*(<ul|<ol|<blockquote)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>)\s*<br>/g, '$1')
  html = html.replace(/<p class="md-p">(<br>\s*)+(<ul|<ol|<blockquote|<pre|<hr)/g, '$2')
  html = html.replace(/(<br>\s*){2,}/g, '<br>')
  html = html.replace(/(<\/ol>|<\/ul>|<\/blockquote>)<br>(<p|<div)/g, '$1$2')

  // Ordered lists split by prose keep counting.
  const tokens = html.split(/(<ol class="md-ol">(?:<li class="md-oli"[^>]*>[\s\S]*?<\/li>)+<\/ol>)/g)
  let olCounter = 0
  let inSequence = false
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].startsWith('<ol class="md-ol">')) {
      const liCount = (tokens[i].match(/<li class="md-oli"/g) || []).length
      if (liCount === 1) {
        olCounter++
        if (olCounter > 1) {
          tokens[i] = tokens[i].replace('<ol class="md-ol">', `<ol class="md-ol" start="${olCounter}">`)
        }
        inSequence = true
      } else {
        olCounter = 0
        inSequence = false
      }
    } else if (inSequence) {
      if (/<h[2-5]/.test(tokens[i])) {
        olCounter = 0
        inSequence = false
      }
    }
  }
  html = tokens.join('')

  return html
}

// The Socratic chips insert a question at the end of what is written; they never send.
const insertSocraticPrompt = (q) => {
  if (isChatInputDisabled.value) return
  const current = chatInput.value.replace(/\s+$/, '')
  chatInput.value = current ? `${current}\n${q}` : q
  nextTick(() => {
    const el = chatInputRef.value
    if (!el) return
    growInput()
    el.focus()
    const end = el.value.length
    el.setSelectionRange(end, end)
    el.scrollTop = el.scrollHeight
  })
}

// Asking
const sendMessage = async () => {
  if (!chatInput.value.trim() || isChatInputDisabled.value) return

  const message = chatInput.value.trim()
  chatInput.value = ''
  nextTick(growInput)

  chatHistory.value.push({ role: 'user', content: message, timestamp: new Date().toISOString() })
  isSending.value = true
  setStatus('working', workingText.value)
  scrollToEnd()

  try {
    if (chatTarget.value === 'report_agent') {
      await sendToScribe(message)
    } else {
      await sendToCitizen(message)
    }
    setStatus('ready')
  } catch (err) {
    addLog(t('step5.symposium.ledger.failed', { error: err.message }))
    chatHistory.value.push({
      role: 'assistant',
      content: t('step5.symposium.trouble', { error: err.message }),
      timestamp: new Date().toISOString()
    })
    setStatus('error')
  } finally {
    isSending.value = false
    saveChatHistory()
    scrollToEnd()
    focusInput()
  }
}

const sendToScribe = async (message) => {
  addLog(t('step5.symposium.ledger.asked', { name: t('step5.symposium.scribe'), q: message.substring(0, 60) }))

  const historyForApi = chatHistory.value
    .slice(0, -1)
    .slice(-10)
    .map((msg) => ({ role: msg.role, content: msg.content }))

  const res = await chatWithReport({
    simulation_id: props.simulationId,
    message,
    chat_history: historyForApi
  })

  if (res.success && res.data) {
    chatHistory.value.push({
      role: 'assistant',
      content: res.data.response || res.data.answer || t('step5.noResponse'),
      timestamp: new Date().toISOString()
    })
    addLog(t('step5.symposium.ledger.answered', { name: t('step5.symposium.scribe') }))
  } else {
    throw new Error(res.error || t('step5.requestFailed'))
  }
}

const sendToCitizen = async (message) => {
  if (!selectedAgent.value || selectedAgentIndex.value === null || !companion.value) {
    throw new Error(t('step5.symposium.needSeat'))
  }
  const name = companion.value.name
  addLog(t('step5.symposium.ledger.asked', { name, q: message.substring(0, 60) }))

  // The citizen is reminded of the conversation so far.
  let prompt = message
  if (chatHistory.value.length > 1) {
    const historyContext = chatHistory.value
      .slice(0, -1)
      .slice(-6)
      .map((msg) => `${msg.role === 'user' ? 'Questioner' : 'You'}: ${msg.content}`)
      .join('\n')
    prompt = `Earlier in our conversation:\n${historyContext}\n\nNow my next question is: ${message}`
  }

  const res = await interviewAgents({
    simulation_id: props.simulationId,
    interviews: [{ agent_id: selectedAgentIndex.value, prompt }]
  })

  if (res.success && res.data) {
    // Results come as a dictionary keyed by platform and seat: { reddit_0: {...}, twitter_0: {...} }
    const resultData = res.data.result || res.data
    const resultsDict = resultData.results || resultData
    let responseContent = null
    const agentId = selectedAgentIndex.value

    if (typeof resultsDict === 'object' && !Array.isArray(resultsDict)) {
      const agentResult = resultsDict[`reddit_${agentId}`] || resultsDict[`twitter_${agentId}`] || Object.values(resultsDict)[0]
      if (agentResult) responseContent = agentResult.response || agentResult.answer
    } else if (Array.isArray(resultsDict) && resultsDict.length > 0) {
      responseContent = resultsDict[0].response || resultsDict[0].answer
    }

    if (responseContent) {
      chatHistory.value.push({ role: 'assistant', content: responseContent, timestamp: new Date().toISOString() })
      addLog(t('step5.symposium.ledger.answered', { name }))
    } else {
      throw new Error(t('step5.noResponse'))
    }
  } else {
    throw new Error(res.error || t('step5.requestFailed'))
  }
}

const scrollToEnd = () => {
  nextTick(() => {
    const lines = document.querySelectorAll('.symposium .dialogue > .line')
    const last = lines[lines.length - 1]
    if (last && typeof last.scrollIntoView === 'function') last.scrollIntoView({ block: 'nearest' })
  })
}

// The crowd
const toggleAgentSelection = (idx) => {
  const next = new Set(selectedAgents.value)
  if (next.has(idx)) next.delete(idx)
  else next.add(idx)
  selectedAgents.value = next
}

const selectAllAgents = () => {
  selectedAgents.value = new Set(profiles.value.map((_, idx) => idx))
}

const clearAgentSelection = () => {
  selectedAgents.value = new Set()
}

const submitSurvey = async () => {
  if (!canAskCrowd.value) return

  isSurveying.value = true
  setStatus('working', t('step5.symposium.crowdAnswering'))
  addLog(t('step5.symposium.ledger.crowdAsked', { n: selectedAgents.value.size }))

  try {
    const questionText = surveyQuestion.value.trim()
    const interviews = Array.from(selectedAgents.value).map((idx) => ({ agent_id: idx, prompt: questionText }))

    const res = await interviewAgents({
      simulation_id: props.simulationId,
      interviews
    })

    if (res.success && res.data) {
      const resultData = res.data.result || res.data
      const resultsDict = resultData.results || resultData
      const list = []

      for (const interview of interviews) {
        const agentIdx = interview.agent_id
        const citizen = citizens.value[agentIdx]
        let responseContent = t('step5.symposium.noAnswer')

        if (typeof resultsDict === 'object' && !Array.isArray(resultsDict)) {
          const agentResult = resultsDict[`reddit_${agentIdx}`] || resultsDict[`twitter_${agentIdx}`]
          if (agentResult) responseContent = agentResult.response || agentResult.answer || t('step5.symposium.noAnswer')
        } else if (Array.isArray(resultsDict)) {
          const matched = resultsDict.find((r) => r.agent_id === agentIdx)
          if (matched) responseContent = matched.response || matched.answer || t('step5.symposium.noAnswer')
        }

        list.push({
          agent_id: agentIdx,
          name: citizen ? citizen.name : `Citizen ${agentIdx + 1}`,
          initial: citizen ? citizen.initial : 'Α',
          role: citizen ? citizen.role : '',
          color: citizen ? citizen.color : ROLE_COLOR_VAR.people,
          question: questionText,
          answer: responseContent
        })
      }

      surveyResults.value = list
      addLog(t('step5.symposium.ledger.crowdAnswered', { n: list.length }))
      setStatus('ready')
    } else {
      throw new Error(res.error || t('step5.requestFailed'))
    }
  } catch (err) {
    addLog(t('step5.symposium.ledger.failed', { error: err.message }))
    setStatus('error')
  } finally {
    isSurveying.value = false
  }
}

// The Chronicle
const loadReportData = async () => {
  if (!props.reportId) return
  try {
    const reportRes = await getReport(props.reportId)
    if (reportRes.success && reportRes.data) {
      const record = reportRes.data
      question.value = record.simulation_requirement || ''
      await loadAgentLogs()
      // The finished record carries the chapters too, should the Scribe's notes be missing.
      if (!reportOutline.value && record.outline) {
        reportOutline.value = record.outline
        ;(record.outline.sections || []).forEach((s, i) => {
          if (s.content && !generatedSections.value[i + 1]) generatedSections.value[i + 1] = s.content
        })
      }
      if (reportOutline.value) addLog(t('step5.symposium.ledger.chronicle'))
    } else {
      addLog(t('step5.symposium.ledger.chronicleMissing', { error: reportRes.error || t('common.unknownError') }))
    }
  } catch (err) {
    addLog(t('step5.symposium.ledger.chronicleMissing', { error: err.message }))
  }
}

const loadAgentLogs = async () => {
  if (!props.reportId) return
  try {
    const res = await getAgentLog(props.reportId, 0)
    if (res.success && res.data) {
      const logs = res.data.logs || []
      logs.forEach((log) => {
        if (log.action === 'planning_complete' && log.details?.outline) {
          reportOutline.value = log.details.outline
        }
        if (log.action === 'section_complete' && log.section_index < 100 && log.details?.content) {
          generatedSections.value[log.section_index] = log.details.content
        }
      })
    }
  } catch (err) {
    addLog(t('step5.symposium.ledger.chronicleMissing', { error: err.message }))
  }
}

const loadProfiles = async () => {
  if (!props.simulationId) return
  try {
    const res = await getSimulationProfilesRealtime(props.simulationId)
    if (res.success && res.data) {
      profiles.value = res.data.profiles || []
      addLog(t('step5.symposium.ledger.profiles', { n: profiles.value.length }))
    }
  } catch (err) {
    addLog(t('step5.symposium.ledger.profilesMissing', { error: err.message }))
  }
}

// Whether the citizens can be questioned tonight: only while the city is awake.
let lastCityCheck = 0
let cityKnown = false
const checkCity = async () => {
  if (!props.simulationId) return
  const now = Date.now()
  if (now - lastCityCheck < 15000) return
  lastCityCheck = now
  try {
    const res = await getEnvStatus({ simulation_id: props.simulationId })
    const awake = !!(res.success && res.data && res.data.env_alive)
    if (!cityKnown || awake !== cityAwake.value) {
      addLog(t(awake ? 'step5.symposium.ledger.awake' : 'step5.symposium.ledger.asleep'))
    }
    cityAwake.value = awake
    cityKnown = true
  } catch {
    // Leave the room as it was; the ask itself will say if it fails.
  }
}

// The drawer
let previousOverflow = ''
const openChronicle = () => {
  chronicleOpen.value = true
  try {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } catch { /* nothing to lock */ }
  nextTick(() => chronicleClose.value?.focus())
}

// Tab cycles inside the open Chronicle; the room behind it waits.
const trapFocus = (e) => {
  const root = e.currentTarget
  if (!root) return
  const focusable = Array.from(root.querySelectorAll('button, [href], textarea, input, select, [tabindex]:not([tabindex="-1"])')).filter((el) => !el.disabled)
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

const closeChronicle = () => {
  chronicleOpen.value = false
  try { document.body.style.overflow = previousOverflow } catch { /* nothing to restore */ }
  nextTick(() => chronicleToggle.value?.focus())
}

// Lifecycle
onMounted(() => {
  if (narrowQuery) {
    if (narrowQuery.addEventListener) narrowQuery.addEventListener('change', onNarrowChange)
    else if (narrowQuery.addListener) narrowQuery.addListener(onNarrowChange)
  }
  loadReportData()
  loadProfiles()
  checkCity()
})

onBeforeUnmount(() => {
  if (narrowQuery) {
    if (narrowQuery.removeEventListener) narrowQuery.removeEventListener('change', onNarrowChange)
    else if (narrowQuery.removeListener) narrowQuery.removeListener(onNarrowChange)
  }
  if (chronicleOpen.value) {
    try { document.body.style.overflow = previousOverflow } catch { /* nothing to restore */ }
  }
})

watch(() => props.reportId, (newId, oldId) => {
  if (newId && newId !== oldId) loadReportData()
})

watch(() => props.simulationId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    lastCityCheck = 0
    loadProfiles()
    checkCity()
  }
})
</script>

<style scoped>
.symposium {
  width: 100%;
  max-width: 1360px;
  margin: 0 auto;
  padding: 28px var(--p-gutter) 48px;
  box-sizing: border-box;
  font-family: var(--p-font-body);
  color: var(--p-ink-2);
  min-width: 0;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* The room band */
.room-band {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--p-line);
  min-width: 0;
}

.room-copy { min-width: 0; }

.room-title {
  margin: 6px 0 4px;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1;
  color: var(--p-ink);
}

.room-line {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

.room-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  flex-shrink: 0;
}

.room-actions .p-button[aria-pressed='true'] {
  border-color: var(--p-gold);
  color: var(--p-gold);
}

/* The room: couches along the wall, the table in the middle */
.room {
  display: grid;
  grid-template-columns: minmax(0, 6fr) minmax(0, 7fr);
  gap: 40px;
  padding-top: 26px;
  align-items: start;
}

.couches {
  position: sticky;
  top: calc(var(--p-header-h) + 14px);
  max-height: calc(100vh - var(--p-header-h) - var(--p-way-h) - 28px);
  overflow: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: var(--p-line-strong) transparent;
}

.couches-hint {
  margin: 0 0 6px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-4);
}

.couch-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(236px, 1fr));
  gap: 10px;
}

.couch {
  --role: var(--p-gold);
  position: relative;
  width: 100%;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding: 16px 16px 16px 14px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  border-left: 2px solid var(--role);
  color: var(--p-ink-2);
  text-align: left;
  cursor: pointer;
  font: inherit;
  min-width: 0;
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease;
}

.couch:hover { border-color: var(--p-line-strong); background: var(--p-surface-2); }
.couch.seated,
.couch.chosen { border-color: var(--p-gold); background: var(--p-surface-2); }
.couch:disabled { cursor: default; opacity: 0.7; }
.couch.away .couch-coin { opacity: 0.6; }
.couch.away .couch-name { color: var(--p-ink-3); }

.couch.head {
  grid-template-columns: auto minmax(0, 1fr);
  border-left-color: var(--p-gold);
  background: linear-gradient(90deg, var(--p-terracotta-tint), transparent 60%), var(--p-surface);
}

.couch-coin {
  --p-gold: var(--role);
  width: 40px;
  height: 40px;
  font-size: var(--t-lg);
  border-color: var(--role);
  color: var(--role);
}


.couch-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }

.couch-name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  line-height: 1.1;
  color: var(--p-ink);
  overflow-wrap: anywhere;
}

.couch-role {
  font-size: var(--t-xs);
  color: var(--p-ink-3);
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.couch-line {
  margin-top: 4px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.4;
  color: var(--p-ink-3);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.couch.head .couch-line { -webkit-line-clamp: 3; color: var(--p-ink-2); }

.couch-badge {
  margin-bottom: 3px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-gold);
}

.couch-badge.quiet { color: var(--p-ink-3); }

/* The fold on phones: how many are still on the couches, and the one button that shows them. */
.couches-more {
  display: none;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding-top: 6px;
}

.couches-hidden {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

/* The Scribe's coin: gold, with the sigma cut into it. Declared after the
   size variants so it wins wherever it appears. */
.p-coin.scribe-coin {
  border-color: var(--p-gold);
  color: #1f1a16;
  background: var(--p-gold);
  font-family: var(--p-font-inscription);
  font-weight: 700;
}

/* The table */
.table {
  min-width: 0;
  display: flex;
  flex-direction: column;
  scroll-margin-top: calc(var(--p-header-h) + 12px);
}

.table-band {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 20px;
  align-items: start;
  padding-bottom: 18px;
}

.band-coin {
  --role: var(--p-gold);
  width: 56px;
  height: 56px;
  font-size: var(--t-xl);
  border-color: var(--role);
  color: var(--role);
}

.band-text { min-width: 0; }

.band-name {
  margin: 4px 0 2px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.05;
  color: var(--p-ink);
}

.band-role {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.band-line {
  margin: 8px 0 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  line-height: 1.5;
  color: var(--p-ink-2);
  max-width: 48em;
}

/* The Greek key under the seated card: gold, twice the tile, faint enough to be a
   rule rather than a row of glyphs on the night ground. */
.table-rule {
  width: 144px;
  height: 24px;
  margin-bottom: 8px;
  background-image: var(--p-meander);
  background-size: 48px 24px;
  background-repeat: repeat-x;
  background-position: left center;
  opacity: 0.35;
}

/* The dialogue */
.dialogue {
  list-style: none;
  margin: 0;
  padding: 18px 0 10px;
  display: flex;
  flex-direction: column;
  gap: 26px;
}

.dialogue-empty {
  padding: 22px 0 14px;
  text-align: center;
}

.dialogue-empty p {
  margin: 0 auto;
  max-width: 30em;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
}

.line { display: flex; min-width: 0; }

.line.asked {
  flex-direction: column;
  align-items: flex-end;
  padding-left: 14%;
}

.asked-text {
  max-width: 100%;
  padding: 14px 18px;
  background: var(--p-surface-3);
  border: 1px solid var(--p-line);
  font-family: var(--p-font-body);
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--p-ink);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.line.answered {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  padding-right: 6%;
}

.line-coin {
  --role: var(--p-gold);
  width: 40px;
  height: 40px;
  font-size: var(--t-lg);
  border-color: var(--role);
  color: var(--role);
}

.answered-body { min-width: 0; }

.line-meta {
  display: block;
  margin: 0 0 6px;
  font-size: var(--t-xs);
  color: var(--p-ink-4);
}

.line.asked .line-meta { margin: 6px 4px 0; }

.line-who {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  color: var(--p-ink);
  margin-right: 8px;
}

.line.asked .line-who { font-size: var(--t-sm); font-family: var(--p-font-body); color: var(--p-ink-3); }

.answered-text {
  font-family: var(--p-font-serif);
  font-size: 1.0625rem;
  line-height: 1.7;
  color: var(--p-ink-2);
  max-width: 62ch;
}

.answered-text :deep(p) { margin: 0 0 1em; }
.answered-text :deep(p:last-child) { margin-bottom: 0; }
.answered-text :deep(.md-h2),
.answered-text :deep(.md-h3),
.answered-text :deep(.md-h4),
.answered-text :deep(.md-h5) {
  font-family: var(--p-font-display);
  font-weight: 600;
  color: var(--p-ink);
  margin: 1.2em 0 0.5em;
}
.answered-text :deep(.md-h2) { font-size: var(--t-xl); }
.answered-text :deep(.md-h3) { font-size: var(--t-lg); }
.answered-text :deep(.md-h4),
.answered-text :deep(.md-h5) { font-size: var(--t-md); }
.answered-text :deep(.md-ul),
.answered-text :deep(.md-ol) { padding-left: 1.4em; margin: 0 0 1em; }
.answered-text :deep(li) { margin-bottom: 0.4em; }
.answered-text :deep(.md-quote) {
  margin: 1em 0;
  padding-left: 16px;
  border-left: 2px solid var(--p-gold);
  font-style: italic;
  color: var(--p-ink-3);
}
.answered-text :deep(strong) { color: var(--p-ink); font-weight: 600; }
.answered-text :deep(.code-block),
.answered-text :deep(.inline-code) {
  font-family: var(--p-font-mono);
  font-size: var(--t-xs);
  background: var(--p-surface-2);
  border: 1px solid var(--p-line);
}
.answered-text :deep(.code-block) { padding: 10px; overflow-x: auto; }
.answered-text :deep(.inline-code) { padding: 1px 4px; }
.answered-text :deep(.md-hr) { border: 0; border-top: 1px solid var(--p-line); margin: 1.2em 0; }

/* Thinking */
.ellipsis { display: inline-flex; gap: 5px; padding: 6px 0; }
.ellipsis i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--p-ink-4);
  animation: breathe 1.2s ease-in-out infinite;
}
.ellipsis i:nth-child(2) { animation-delay: 0.2s; }
.ellipsis i:nth-child(3) { animation-delay: 0.4s; }

@keyframes breathe {
  0%, 100% { opacity: 0.3; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-3px); }
}

/* The prompt row and the question */
.prompt {
  padding: 14px 0 12px;
}

.prompt.stuck {
  position: sticky;
  bottom: var(--p-way-h);
  z-index: 5;
  background: linear-gradient(180deg, transparent, var(--p-bg) 18px);
}

.asleep-note {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  margin: 0 0 12px;
  padding: 12px 14px;
  border: 1px solid var(--p-line);
  background: var(--p-surface);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-2);
}

.socratic-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.socratic-label { margin-right: 4px; color: var(--p-ink-4); }

.socratic-chip {
  padding: 7px 12px;
  background: transparent;
  border: 1px solid var(--p-line-strong);
  color: var(--p-ink-2);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease;
}

.socratic-chip:hover:not(:disabled) { border-color: var(--p-gold); color: var(--p-gold); }
.socratic-chip:disabled { opacity: 0.5; cursor: not-allowed; }

.ask {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: end;
}

.ask-input {
  width: 100%;
  min-height: 48px;
  max-height: 200px;
  padding: 13px 16px;
  box-sizing: border-box;
  background: var(--p-surface);
  border: 1px solid var(--p-line-strong);
  color: var(--p-ink);
  font-family: var(--p-font-body);
  font-size: var(--t-md);
  line-height: 1.4;
  resize: none;
}

.ask-input::placeholder { color: var(--p-ink-4); }
.ask-input { overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--p-line-strong) transparent; }
.ask-input:focus { outline: 2px solid var(--p-gold); outline-offset: 2px; }
.ask-input:disabled { opacity: 0.6; cursor: not-allowed; }

.ask-send { min-width: 92px; }

/* The crowd */
.crowd-head { padding-bottom: 14px; }

.crowd-pick {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  padding: 12px 0 6px;
}

.crowd-count {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-2);
}

.crowd-links { display: flex; gap: 4px; }

.faces {
  list-style: none;
  margin: 8px 0 16px;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
}

.face {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.face-coin {
  --role: var(--p-gold);
  width: 30px;
  height: 30px;
  font-size: var(--t-sm);
  border-color: var(--role);
  color: var(--role);
}

.face-name {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  color: var(--p-ink);
}

.crowd-ask { grid-template-columns: minmax(0, 1fr); }

.crowd-submit {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
}

.ask-reason {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.answers {
  margin-top: 34px;
  padding-top: 22px;
  border-top: 1px solid var(--p-line);
}

.answers-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 16px; margin-bottom: 6px; }

.answers-question {
  margin: 0 0 22px;
  padding-left: 16px;
  border-left: 2px solid var(--p-gold);
  font-family: var(--p-font-body);
  font-size: var(--t-md);
  color: var(--p-ink);
  white-space: pre-wrap;
}

.reply-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
  gap: 18px;
}

.reply {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding: 18px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  min-width: 0;
}

.reply .answered-text { font-size: var(--t-md); }

/* The Chronicle drawer */
.drawer-root {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
}

.drawer-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(5, 7, 10, 0.72);
}

.chronicle {
  position: relative;
  width: min(760px, 100%);
  height: 100%;
  display: flex;
  flex-direction: column;
  box-shadow: var(--p-shadow-2);
  min-width: 0;
}

.chronicle-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px 12px 28px;
  border-bottom: 1px solid var(--p-line);
  background: var(--p-surface-2);
}

.chronicle-page {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: 36px clamp(20px, 5vw, 56px) 64px;
}

.chronicle-title {
  margin: 0 0 14px;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 600;
  line-height: 1.08;
  color: var(--p-ink);
  text-wrap: balance;
}

.chronicle-summary {
  margin: 0 0 22px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.chronicle-question { margin: 0 0 22px; }
.chronicle-question p {
  margin: 6px 0 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
}

.chronicle-rule { width: 144px; margin: 0 0 30px; }

.chapter { margin-bottom: 40px; }

.chapter-title {
  margin: 6px 0 14px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.15;
  color: var(--p-ink);
}

.chapter-body {
  font-family: var(--p-font-serif);
  font-size: 1.0625rem;
  line-height: 1.75;
  color: var(--p-ink-2);
  max-width: 64ch;
}

.chapter-body :deep(p) { margin: 0 0 1em; }
.chapter-body :deep(.md-h2),
.chapter-body :deep(.md-h3),
.chapter-body :deep(.md-h4),
.chapter-body :deep(.md-h5) {
  font-family: var(--p-font-display);
  font-weight: 600;
  color: var(--p-ink);
  margin: 1.4em 0 0.5em;
}
.chapter-body :deep(.md-h3) { font-size: var(--t-lg); }
.chapter-body :deep(.md-h4),
.chapter-body :deep(.md-h5) { font-size: var(--t-md); }
.chapter-body :deep(.md-quote) {
  margin: 1.2em 0;
  padding-left: 18px;
  border-left: 2px solid var(--p-terracotta);
  font-style: italic;
  color: var(--p-ink-3);
}
.chapter-body :deep(.md-ul),
.chapter-body :deep(.md-ol) { padding-left: 1.4em; margin: 0 0 1em; }
.chapter-body :deep(strong) { color: var(--p-ink); font-weight: 600; }
.chapter-body :deep(.md-hr) { border: 0; border-top: 1px solid var(--p-line); margin: 1.4em 0; }
.chapter-body :deep(.code-block),
.chapter-body :deep(.inline-code) {
  font-family: var(--p-font-mono);
  font-size: var(--t-xs);
  background: var(--p-surface-2);
  border: 1px solid var(--p-line);
}

.chapter-pending,
.chronicle-waiting {
  font-family: var(--p-font-serif);
  font-style: italic;
  color: var(--p-ink-3);
}

.chronicle-link { margin-top: 8px; text-decoration: none; }

.drawer-enter-active,
.drawer-leave-active { transition: opacity 0.3s ease; }
.drawer-enter-active .chronicle,
.drawer-leave-active .chronicle { transition: transform 0.35s ease; }
.drawer-enter-from,
.drawer-leave-to { opacity: 0; }
.drawer-enter-from .chronicle,
.drawer-leave-to .chronicle { transform: translateX(40px); }

/* Phones and narrow rooms: one column; the couches stand in a short column that
   folds after the Scribe and six citizens, every card keeping its quote. */
@media (max-width: 1023px) {
  .symposium { padding-top: 22px; }

  .room-band { flex-direction: column; align-items: flex-start; gap: 16px; }
  .room-actions { width: 100%; }
  .room-actions .p-button { flex: 1 1 auto; min-width: 0; }

  .room { grid-template-columns: minmax(0, 1fr); gap: 26px; }

  .couches {
    position: static;
    max-height: none;
    overflow: visible;
    padding-right: 0;
  }

  .couch-list { grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); }
  .couch-list li { min-width: 0; }
  .couch-list .couch { height: 100%; box-sizing: border-box; }

  .couches-more { display: flex; }
  .couches-more .p-button { align-self: stretch; }

  .line.asked { padding-left: 8%; }
  .line.answered { padding-right: 0; }

  /* The Socratic questions become one row along the table edge, so the prompt stays short. */
  .socratic-row {
    flex-wrap: nowrap;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    padding-bottom: 4px;
    margin-inline: -16px;
    padding-inline: 16px;
    scrollbar-width: none;
  }
  .socratic-row::-webkit-scrollbar { display: none; }
  .socratic-label { flex: 0 0 auto; }
  .socratic-chip { flex: 0 0 auto; white-space: nowrap; }
}

@media (max-width: 599px) {
  .symposium { padding-inline: 16px; }
  .room-title { font-size: var(--t-xl); }
  .couch { padding: 12px 12px 12px 12px; gap: 12px; }
  .couch-coin { width: 36px; height: 36px; font-size: var(--t-md); }
  .couch-role { -webkit-line-clamp: 1; }
  .couch.head .couch-line { -webkit-line-clamp: 2; }
  .couches { gap: 8px; }
  .couch-list { gap: 8px; }
  .band-coin { width: 46px; height: 46px; font-size: var(--t-lg); }
  .ask-send { min-width: 72px; padding-inline: 14px; }
  .chronicle-bar { padding: 10px 12px 10px 16px; }
  .chronicle-page { padding: 28px 16px 56px; }
}

@media (prefers-reduced-motion: reduce) {
  .ellipsis i { animation: none; opacity: 0.7; }
  .couch { transition: none; }
}
</style>
