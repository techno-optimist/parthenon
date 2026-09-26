<template>
  <div class="chronicle-stage">
    <!-- One polite live region for the act: the Scribe's progress, in words. -->
    <p class="visually-hidden" role="status" aria-live="polite">{{ statusLine }}</p>

    <div class="chronicle" :class="{ 'has-margin': wide && chapters.length }">
      <!-- The contents, in the margin on wide screens -->
      <nav
        v-if="wide && chapters.length"
        class="contents contents--margin"
        :aria-label="$t('parthenon.chronicle.chaptersNav')"
      >
        <span class="p-eyebrow contents-label">{{ $t('parthenon.chronicle.contents') }}</span>
        <ol class="contents-list">
          <li
            v-for="ch in chapters"
            :key="ch.index"
            class="contents-item"
            :class="[`is-${ch.state}`, { current: ch.index === activeChapter }]"
          >
            <button
              type="button"
              class="contents-link"
              :disabled="ch.state === 'pending'"
              :aria-current="ch.index === activeChapter ? 'true' : undefined"
              @click="goToChapter(ch.index)"
            >
              <span class="contents-num">{{ numeral(ch.index) }}</span>
              <span class="contents-title">{{ ch.title }}</span>
              <span v-if="ch.state !== 'done'" class="contents-note">{{ stateNote(ch.state) }}</span>
            </button>
          </li>
        </ol>
      </nav>

      <!-- The page itself: parchment held up in the dark -->
      <article class="p-paper page" :aria-labelledby="ids.title">
        <header class="title-page">
          <p class="p-eyebrow">{{ $t('parthenon.chronicle.eyebrow') }}</p>
          <h1 :id="ids.title" class="title">{{ title }}</h1>
          <p v-if="standfirst" class="standfirst">{{ standfirst }}</p>
          <div class="p-meander rule" aria-hidden="true"></div>
          <div v-if="question" class="question">
            <span class="p-eyebrow question-label">{{ $t('parthenon.chronicle.questionLabel') }}</span>
            <p class="question-text">{{ question }}</p>
          </div>
          <p v-if="dateLine" class="date">{{ dateLine }}</p>

          <div v-if="isComplete" class="actions">
            <button type="button" class="p-button" @click="goToInteraction">
              {{ $t('parthenon.chronicle.enterSymposium') }}
            </button>
            <button type="button" class="p-button secondary" @click="revealFilm">
              {{ $t('parthenon.chronicle.filmIt') }}
            </button>
          </div>
        </header>

        <!-- Trouble: the Scribe could not finish -->
        <section v-if="trouble" class="trouble" role="alert">
          <p class="trouble-title">{{ $t('parthenon.chronicle.troubleTitle') }}</p>
          <details class="trouble-why">
            <summary>{{ $t('parthenon.chronicle.troubleWhy') }}</summary>
            <p>{{ trouble }}</p>
          </details>
        </section>

        <!-- While the Scribe writes: one line, in words, and a breathing ink line -->
        <p v-else-if="!isComplete" class="scribe-status">
          <span class="ink-line" aria-hidden="true"></span>
          <span>{{ statusLine }}</span>
        </p>

        <!-- The contents, on the page, when there is no margin for them -->
        <nav
          v-if="!wide && chapters.length"
          class="contents contents--inline"
          :aria-label="$t('parthenon.chronicle.chaptersNav')"
        >
          <span class="p-eyebrow contents-label">{{ $t('parthenon.chronicle.contents') }}</span>
          <ol class="contents-list">
            <li
              v-for="ch in chapters"
              :key="ch.index"
              class="contents-item"
              :class="[`is-${ch.state}`, { current: ch.index === activeChapter }]"
            >
              <button
                type="button"
                class="contents-link"
                :disabled="ch.state === 'pending'"
                :aria-current="ch.index === activeChapter ? 'true' : undefined"
                @click="goToChapter(ch.index)"
              >
                <span class="contents-num">{{ numeral(ch.index) }}</span>
                <span class="contents-title">{{ ch.title }}</span>
                <span v-if="ch.state !== 'done'" class="contents-note">{{ stateNote(ch.state) }}</span>
              </button>
            </li>
          </ol>
        </nav>

        <!-- The chapters, as they are finished -->
        <section
          v-for="ch in visibleChapters"
          :key="ch.index"
          :id="chapterId(ch.index)"
          class="chapter"
          :class="`is-${ch.state}`"
          :aria-labelledby="chapterId(ch.index) + '-title'"
        >
          <header class="chapter-head">
            <span class="p-eyebrow chapter-num">{{ $t('parthenon.chronicle.chapter', { n: numeral(ch.index) }) }}</span>
            <h2 :id="chapterId(ch.index) + '-title'" class="chapter-title" tabindex="-1">{{ ch.title }}</h2>
          </header>

          <div v-if="ch.state === 'done'" class="chapter-body" v-html="ch.html"></div>
          <p v-else class="scribe-status chapter-writing">
            <span class="ink-line" aria-hidden="true"></span>
            <span>{{ $t('parthenon.chronicle.writingThis') }}</span>
          </p>

          <details v-if="ch.state === 'done' && ch.sources.length" class="how-found">
            <summary>{{ $t('parthenon.chronicle.howFound') }}</summary>
            <ul class="how-list">
              <li v-for="(line, i) in ch.sources" :key="i">{{ line }}</li>
            </ul>
          </details>
        </section>

        <!-- Colophon: the Scribe sets down her pen -->
        <footer v-if="isComplete" class="colophon">
          <div class="p-meander rule" aria-hidden="true"></div>
          <p class="colophon-line">{{ $t('parthenon.chronicle.colophon') }}</p>
          <button type="button" class="p-button" @click="goToInteraction">
            {{ $t('parthenon.chronicle.enterSymposium') }}
          </button>
        </footer>

        <!-- The film, as the epilogue of the document -->
        <ChronicleFilm v-if="!trouble" ref="filmPanel" :report-id="reportId" :ready="isComplete" />
      </article>
    </div>
  </div>
</template>

<script setup>
// Act Δ΄: the Chronicle, written by the Scribe of Athens. The engine writes
// chapter by chapter; the page reveals each one as it is finished and says,
// in one line, where the Scribe is. The engine's own account goes to the
// ledger through add-log.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getAgentLog, getConsoleLog, getReport } from '../api/report'
import { stripIds } from '../parthenon/vocabulary.js'
import ChronicleFilm from './ChronicleFilm.vue'

// Chapters are numbered the Greek way, with the keraia, as the Symposium's
// drawer numbers them. (A shared helper in vocabulary.js is requested.)
const GREEK = ['Α΄', 'Β΄', 'Γ΄', 'Δ΄', 'Ε΄', 'Ϛ΄', 'Ζ΄', 'Η΄', 'Θ΄', 'Ι΄', 'ΙΑ΄', 'ΙΒ΄', 'ΙΓ΄', 'ΙΔ΄', 'ΙΕ΄', 'ΙϚ΄', 'ΙΖ΄', 'ΙΗ΄', 'ΙΘ΄', 'Κ΄']
const greekNumeral = (n) => GREEK[n - 1] || String(n)

const router = useRouter()
const { t, locale } = useI18n()

const props = defineProps({
  reportId: String,
  simulationId: String,
  report: { type: Object, default: null },
  loadError: { type: String, default: '' }
})

const emit = defineEmits(['add-log', 'update-status'])

const uid = String(useId() || 'ch').replace(/[^A-Za-z0-9_-]/g, '')
const ids = { title: `${uid}-chronicle-title` }
const chapterId = (n) => `${uid}-chapter-${n}`

// Chinese counts its chapters in its own figures; everyone else reads Greek.
const numeral = (n) => (locale.value === 'zh' ? String(n) : greekNumeral(n))

// State from the Scribe's log
const reportOutline = ref(null)
const currentSectionIndex = ref(null)
const generatedSections = ref({})
const sourcesBySection = ref({})
const isComplete = ref(false)
const planningStarted = ref(false)
const agentLogLine = ref(0)
const consoleLogLine = ref(0)
// The Scribe's own word that she could not finish, from her log or her record.
const localTrouble = ref('')
let lastRecordCheck = 0

const filmPanel = ref(null)

// The document

const title = computed(() => reportOutline.value?.title || t('parthenon.chronicle.untitled'))
const standfirst = computed(() => reportOutline.value?.summary || '')
const question = computed(() => props.report?.simulation_requirement || '')

const dateLine = computed(() => {
  const finished = isComplete.value && props.report?.completed_at
  const raw = finished ? props.report.completed_at : props.report?.created_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  const tag = locale.value === 'zh' ? 'zh-CN' : 'en-GB'
  let text = ''
  try {
    text = new Intl.DateTimeFormat(tag, { day: 'numeric', month: 'long', year: 'numeric' }).format(date)
  } catch {
    text = date.toDateString()
  }
  return t(finished ? 'parthenon.chronicle.setDownOn' : 'parthenon.chronicle.begunOn', { date: text })
})

const trouble = computed(() => {
  if (props.loadError) return props.loadError
  if (localTrouble.value) return localTrouble.value
  const r = props.report
  if (r && (r.status === 'failed' || r.error)) return stripIds(r.error) || t('parthenon.chronicle.troubleFallback')
  return ''
})

// Each tool the Scribe used, in the city's words, with how often.
const KNOWN_SOURCES = ['insight_forge', 'panorama_search', 'interview_agents', 'quick_search', 'get_graph_statistics', 'get_entities_by_type']
const countWord = (n) => {
  if (n === 1) return t('parthenon.chronicle.once')
  if (n === 2) return t('parthenon.chronicle.twice')
  return t('parthenon.chronicle.times', { n })
}
const describeSources = (tools) => {
  const counts = new Map()
  for (const tool of tools || []) {
    const key = KNOWN_SOURCES.includes(tool) ? tool : 'other'
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()].map(([key, n]) => `${t(`parthenon.chronicle.sources.${key}`)}, ${countWord(n)}`)
}

const chapters = computed(() => {
  const sections = reportOutline.value?.sections || []
  return sections.map((section, i) => {
    const index = i + 1
    const content = generatedSections.value[index]
    let state = 'pending'
    if (content) state = 'done'
    else if (currentSectionIndex.value === index) state = 'writing'
    return {
      index,
      title: section.title || t('parthenon.chronicle.chapter', { n: index }),
      state,
      html: content ? renderMarkdown(content) : '',
      sources: content ? describeSources(sourcesBySection.value[index]) : []
    }
  })
})

const visibleChapters = computed(() => chapters.value.filter((ch) => ch.state !== 'pending'))

const totalSections = computed(() => chapters.value.length)
const completedSections = computed(() => chapters.value.filter((ch) => ch.state === 'done').length)

const statusLine = computed(() => {
  if (trouble.value) return t('parthenon.chronicle.troubleTitle')
  if (isComplete.value) return t('parthenon.chronicle.complete')
  if (!reportOutline.value) {
    return planningStarted.value ? t('parthenon.chronicle.planning') : t('parthenon.chronicle.reading')
  }
  const writing = chapters.value.find((ch) => ch.state === 'writing')
  const n = writing ? writing.index : Math.min(completedSections.value + 1, totalSections.value)
  if (completedSections.value >= totalSections.value) return t('parthenon.chronicle.finishing')
  return t('parthenon.chronicle.writing', { n, total: totalSections.value })
})

const stateNote = (state) =>
  state === 'writing' ? t('parthenon.chronicle.beingWritten') : t('parthenon.chronicle.toCome')

// Navigation

const goToInteraction = () => {
  if (props.reportId) router.push({ name: 'Interaction', params: { reportId: props.reportId } })
}

const revealFilm = () => {
  filmPanel.value?.reveal()
}

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const goToChapter = (n) => {
  const el = document.getElementById(chapterId(n))
  if (!el) return
  el.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })
  const heading = el.querySelector('.chapter-title')
  heading?.focus({ preventScroll: true })
}

// Which chapter the reader is in, for the contents.
const activeChapter = ref(null)
let scrollTicking = false
const updateActiveChapter = () => {
  scrollTicking = false
  const line = 160
  let current = null
  for (const ch of visibleChapters.value) {
    const el = document.getElementById(chapterId(ch.index))
    if (!el) continue
    if (el.getBoundingClientRect().top <= line) current = ch.index
  }
  activeChapter.value = current
}
const onScroll = () => {
  if (scrollTicking) return
  scrollTicking = true
  requestAnimationFrame(updateActiveChapter)
}

// Wide screens carry the contents in the margin.
const WIDE = '(min-width: 1200px)'
const wideQuery = typeof window !== 'undefined' ? window.matchMedia(WIDE) : null
const wide = ref(wideQuery ? wideQuery.matches : false)
const onWide = (e) => { wide.value = e.matches }

// Markdown, the Scribe's, into the page's HTML.

const escapeText = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;')

const renderMarkdown = (content) => {
  if (!content) return ''

  let text = escapeText(stripIds(content)).trim()
  // The chapter title is set by the page; a stray bold marker sometimes leads.
  text = text.replace(/^[ \t]*\*\*[ \t]*\n+/, '')
  text = text.replace(/^##\s+.+\n+/, '')
  text = text.replace(/^[ \t]*\*\*[ \t]*\n+/, '')

  let html = text.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')

  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>')
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  // A paragraph that is only bold is a sub-heading.
  html = html.replace(/^\*\*([^*\n]+?)\*\*\s*$/gm, '<h3 class="md-h3">$1</h3>')

  html = html.replace(/^> ?(.*)$/gm, '<blockquote class="md-quote">$1</blockquote>')
  html = html.replace(/<\/blockquote>\n<blockquote class="md-quote">/g, '<br>')

  html = html.replace(/^(\s*)[-*] (.+)$/gm, (match, indent, body) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-li" data-level="${level}">${body}</li>`
  })
  html = html.replace(/^(\s*)(\d+)\. (.+)$/gm, (match, indent, num, body) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-oli" data-level="${level}">${body}</li>`
  })
  html = html.replace(/(<li class="md-li"[^>]*>.*?<\/li>\s*)+/g, '<ul class="md-ul">$&</ul>')
  html = html.replace(/(<li class="md-oli"[^>]*>.*?<\/li>\s*)+/g, '<ol class="md-ol">$&</ol>')
  html = html.replace(/<\/li>\s+<li/g, '</li><li')
  html = html.replace(/<ul class="md-ul">\s+/g, '<ul class="md-ul">')
  html = html.replace(/<ol class="md-ol">\s+/g, '<ol class="md-ol">')
  html = html.replace(/\s+<\/ul>/g, '</ul>')
  html = html.replace(/\s+<\/ol>/g, '</ol>')

  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(^|[^*\w])\*([^*\n]+?)\*(?=[^*\w]|$)/gm, '$1<em>$2</em>')
  html = html.replace(/(^|[^\w])_([^_\n]+?)_(?=[^\w]|$)/gm, '$1<em>$2</em>')

  html = html.replace(/^---$/gm, '<hr class="md-hr">')

  html = html.replace(/\n\n+/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  html = '<p class="md-p">' + html + '</p>'

  html = html.replace(/<p class="md-p"><\/p>/g, '')
  html = html.replace(/<p class="md-p">(<h[2-5])/g, '$1')
  html = html.replace(/(<\/h[2-5]>)<\/p>/g, '$1')
  html = html.replace(/<p class="md-p">(<ul|<ol|<blockquote|<pre|<hr)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/pre>|<hr class="md-hr">)<\/p>/g, '$1')
  html = html.replace(/<br>\s*(<ul|<ol|<blockquote)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>)\s*<br>/g, '$1')
  html = html.replace(/<p class="md-p">(<br>\s*)+(<ul|<ol|<blockquote|<pre|<hr)/g, '$2')
  html = html.replace(/(<br>\s*){2,}/g, '<br>')
  html = html.replace(/<p class="md-p">(<br>\s*)+/g, '<p class="md-p">')
  html = html.replace(/(<br>\s*)+<\/p>/g, '</p>')
  html = html.replace(/<p class="md-p"><\/p>/g, '')

  // Ordered lists broken up by prose keep counting.
  const tokens = html.split(/(<ol class="md-ol">(?:<li class="md-oli"[^>]*>[\s\S]*?<\/li>)+<\/ol>)/g)
  let olCounter = 0
  let inSequence = false
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].startsWith('<ol class="md-ol">')) {
      const liCount = (tokens[i].match(/<li class="md-oli"/g) || []).length
      if (liCount === 1) {
        olCounter++
        if (olCounter > 1) tokens[i] = tokens[i].replace('<ol class="md-ol">', `<ol class="md-ol" start="${olCounter}">`)
        inSequence = true
      } else {
        olCounter = 0
        inSequence = false
      }
    } else if (inSequence && /<h[2-5]/.test(tokens[i])) {
      olCounter = 0
      inSequence = false
    }
  }
  return tokens.join('')
}

// The Scribe's log

const applyLog = (log) => {
  if (log.action === 'planning_start' || log.action === 'report_start') planningStarted.value = true

  if (log.action === 'planning_complete' && log.details?.outline) {
    reportOutline.value = log.details.outline
  }
  if (log.action === 'section_start') {
    currentSectionIndex.value = log.section_index
  }
  if (log.action === 'tool_call' && log.section_index) {
    const list = sourcesBySection.value[log.section_index] || []
    list.push(log.details?.tool_name || 'other')
    sourcesBySection.value = { ...sourcesBySection.value, [log.section_index]: list }
  }
  if (log.action === 'section_complete' && log.details?.content) {
    generatedSections.value = { ...generatedSections.value, [log.section_index]: log.details.content }
    if (currentSectionIndex.value === log.section_index) currentSectionIndex.value = null
  }
  if (log.action === 'report_complete') {
    isComplete.value = true
    currentSectionIndex.value = null
  }
  // The Scribe says so herself when she cannot finish.
  if (log.action === 'error' && !isComplete.value) {
    const why = scrub(log.details?.error || log.details?.message || '')
    localTrouble.value = why || t('parthenon.chronicle.troubleFallback')
    currentSectionIndex.value = null
  }
}

let agentLogTimer = null
let consoleLogTimer = null
let agentInFlight = false
let consoleInFlight = false

// A Chronicle on its record already: show it whole, and let the log fill in
// how the Scribe found it. A failed record is the Scribe's last word.
const adoptRecord = (r) => {
  if (!r) return
  if (r.status === 'failed' || r.error) {
    if (!isComplete.value) {
      localTrouble.value = scrub(r.error) || t('parthenon.chronicle.troubleFallback')
      currentSectionIndex.value = null
    }
    return
  }
  if (r.status !== 'completed' || isComplete.value) return
  const sections = r.outline?.sections || []
  if (!sections.length) return
  if (!reportOutline.value) {
    reportOutline.value = { title: r.outline.title, summary: r.outline.summary, sections: sections.map((s) => ({ title: s.title })) }
  }
  const done = { ...generatedSections.value }
  sections.forEach((s, i) => { if (s.content && !done[i + 1]) done[i + 1] = s.content })
  generatedSections.value = done
  if (sections.every((s, i) => done[i + 1])) {
    isComplete.value = true
    currentSectionIndex.value = null
    emit('update-status', 'completed')
  }
}

// The log says nothing when the Scribe is stopped from outside, so while she
// is still at work her record is read again now and then.
const RECORD_CHECK_MS = 15000
const checkRecord = async () => {
  const now = Date.now()
  if (now - lastRecordCheck < RECORD_CHECK_MS) return
  lastRecordCheck = now
  const reportId = props.reportId
  try {
    const res = await getReport(reportId)
    if (reportId !== props.reportId) return
    if (res.success && res.data) adoptRecord(res.data)
  } catch (err) {
    console.warn('Could not read the Chronicle\'s record:', err)
  }
}

const fetchAgentLog = async () => {
  if (!props.reportId || agentInFlight) return
  agentInFlight = true
  try {
    const res = await getAgentLog(props.reportId, agentLogLine.value)
    if (res.success && res.data) {
      const newLogs = res.data.logs || []
      const wasComplete = isComplete.value
      newLogs.forEach(applyLog)
      agentLogLine.value = res.data.from_line + newLogs.length
      if (isComplete.value && !wasComplete) emit('update-status', 'completed')
      if (isComplete.value && !res.data.has_more) stopAgentPolling()
      if (newLogs.length) nextTick(onScroll)
      if (!isComplete.value && !trouble.value && !res.data.has_more) checkRecord()
    }
  } catch (err) {
    console.warn('Failed to fetch the Scribe\'s log:', err)
  } finally {
    agentInFlight = false
  }
}

// The engine's console lines go to the ledger, with their own times, in the
// city's words. Bookkeeping is dropped; nothing with a hash in it passes.
const CONSOLE_LINE = /^\[(\d{2}:\d{2}:\d{2})\]\s*(INFO|WARNING|WARN|ERROR|DEBUG)\s*:?\s*(.*)$/
const scrub = (text) =>
  stripIds(
    String(text ?? '')
      .replace(/\b[0-9a-f]{8,}\b\.{0,3}/gi, '')
      .replace(/\bgraph(_id)?=\S+/gi, '')
      .replace(/\S+\.(json|csv|md|txt|log)\b/gi, '')
      .replace(/\bLLM\b/g, 'the Scribe')
      .replace(/\bagents?\b/gi, (w) => (w.endsWith('s') ? 'citizens' : 'citizen'))
  )
// A chapter by its title, from the outline the log gave us or from the record.
const chapterOf = (title) => {
  const wanted = String(title).trim()
  const known = chapters.value.find((ch) => ch.title === wanted)
  if (known) return known
  const sections = props.report?.outline?.sections || []
  const i = sections.findIndex((s) => String(s.title || '').trim() === wanted)
  return i >= 0 ? { index: i + 1, title: sections[i].title } : null
}
const chapterLine = (title, withIndex, withoutIndex) => {
  const ch = chapterOf(title)
  return ch
    ? t(withIndex, { n: numeral(ch.index), title: ch.title })
    : t(withoutIndex, { title: scrub(title) })
}
const toolLine = (tool) => {
  const key = KNOWN_SOURCES.includes(tool) ? tool : 'other'
  return t('parthenon.chronicle.ledger.tool', { what: t(`parthenon.chronicle.sources.${key}`) })
}
const LEDGER = [
  // Bookkeeping the city does not need to hear about.
  { re: /^(Report saved|Outline saved|Section saved|Full report assembled|ReportAgent initialized|Report folder deleted)/, drop: true },
  { re: /^Loaded \d+ /, drop: true },
  { re: /^Calling batch interview/, drop: true },
  { re: /^Fetching all (nodes|edges) for graph/, drop: true },
  { re: /^Graph search/, drop: true },
  { re: /^(PanoramaSearch|InsightForge|QuickSearch|InterviewAgents) /, drop: true, unless: /^InsightForge complete/ },
  { re: /^(LLM attempted|search_graph redirected|get_simulation_context redirected)/, drop: true },
  { re: /^Section .+ (round \d+:|: \d+ consecutive conflicts)/, drop: true },
  // What the Scribe did, in order.
  { re: /^Starting report outline planning/, say: () => t('parthenon.chronicle.log.began') },
  { re: /^Fetching simulation context/, say: () => t('parthenon.chronicle.ledger.readQuestion') },
  { re: /^Search complete: found (\d+)/, say: (m) => t('parthenon.chronicle.ledger.found', { n: m[1] }) },
  { re: /^Fetching statistics for graph/, say: () => t('parthenon.chronicle.ledger.counted') },
  { re: /^Fetched (\d+) nodes/, say: (m) => t('parthenon.chronicle.ledger.readNames', { n: m[1] }) },
  { re: /^Fetched (\d+) edges/, say: (m) => t('parthenon.chronicle.ledger.readTies', { n: m[1] }) },
  { re: /^Fetching node detail/, say: () => t('parthenon.chronicle.ledger.readName') },
  { re: /^Outline planning complete: (\d+)/, say: (m) => t('parthenon.chronicle.log.planned', { n: m[1] }) },
  { re: /^ReACT generating section: (.+)$/, say: (m) => chapterLine(m[1], 'parthenon.chronicle.log.chapterBegun', 'parthenon.chronicle.ledger.chapterBegunTitle') },
  { re: /^Executing tool: (\w+)/, say: (m) => toolLine(m[1]) },
  { re: /^Generated (\d+) sub-queries/, say: (m) => t('parthenon.chronicle.ledger.subQuestions', { n: m[1] }) },
  { re: /^InsightForge complete: (\d+) facts, (\d+) entities, (\d+) relationships/, say: (m) => t('parthenon.chronicle.ledger.searchClosed', { facts: m[1], names: m[2], ties: m[3] }) },
  { re: /^Selected (\d+) agents for interview/, say: (m) => t('parthenon.chronicle.ledger.chose', { n: m[1] }) },
  { re: /^Generated (\d+) interview questions/, say: (m) => t('parthenon.chronicle.ledger.questions', { n: m[1] }) },
  { re: /^Interview API returned: (\d+) results/, say: (m) => t(Number(m[1]) > 0 ? 'parthenon.chronicle.ledger.answered' : 'parthenon.chronicle.ledger.noAnswer') },
  { re: /^Interview API (call failed|returned failure|call exception)/, say: () => t('parthenon.chronicle.ledger.interviewFailed') },
  { re: /^Section (.+) reached max iterations/, say: (m) => t('parthenon.chronicle.ledger.ranLong', { title: scrub(m[1]) }) },
  { re: /^Section (.+) iteration \d+: LLM returned None/, say: (m) => t('parthenon.chronicle.ledger.paused', { title: scrub(m[1]) }) },
  { re: /^Section (.+) force-finish/, say: (m) => t('parthenon.chronicle.ledger.chapterFailed', { title: scrub(m[1]) }) },
  { re: /^Section (.+?) (generation complete|missing 'Final Answer:')/, say: (m) => chapterLine(m[1], 'parthenon.chronicle.log.chapterDone', 'parthenon.chronicle.ledger.chapterDoneTitle') },
  { re: /^Report generation complete/, say: () => t('parthenon.chronicle.log.done') },
  { re: /^Report generation failed:?\s*(.*)/, say: (m) => t('parthenon.chronicle.ledger.failed', { error: scrub(m[1]) }) },
  { re: /^Outline planning failed:?\s*(.*)/, say: (m) => t('parthenon.chronicle.ledger.planFailed', { error: scrub(m[1]) }) },
  { re: /^Tool execution failed: \w+, error:?\s*(.*)/, say: (m) => t('parthenon.chronicle.ledger.toolFailed', { error: scrub(m[1]) }) },
  { re: /^Failed to [^:]+:?\s*(.*)/, say: (m) => t('parthenon.chronicle.ledger.snag', { error: scrub(m[1]) }) }
]

const toLedger = (line) => {
  const m = CONSOLE_LINE.exec(String(line))
  const time = m ? m[1] : ''
  const level = m ? m[2] : 'INFO'
  const raw = (m ? m[3] : String(line)).trim()
  for (const rule of LEDGER) {
    if (!rule.re.test(raw)) continue
    if (rule.unless && rule.unless.test(raw)) continue
    if (rule.drop) return null
    const message = rule.say(rule.re.exec(raw))
    return message ? { time, message } : null
  }
  // Unknown lines: warnings are worth a word to the owner; the rest is noise.
  if (level === 'INFO' || level === 'DEBUG') return null
  const message = scrub(raw)
  return message ? { time, message: t('parthenon.chronicle.ledger.trouble', { message }) } : null
}

const fetchConsoleLog = async () => {
  if (!props.reportId || consoleInFlight) return
  consoleInFlight = true
  try {
    const res = await getConsoleLog(props.reportId, consoleLogLine.value)
    if (res.success && res.data) {
      const newLogs = res.data.logs || []
      newLogs.forEach((line) => {
        const entry = toLedger(line)
        if (entry) emit('add-log', entry)
      })
      consoleLogLine.value = res.data.from_line + newLogs.length
      if ((isComplete.value || trouble.value) && !res.data.has_more) stopConsolePolling()
    }
  } catch (err) {
    console.warn('Failed to fetch the engine\'s console:', err)
  } finally {
    consoleInFlight = false
  }
}

const startPolling = () => {
  if (agentLogTimer || consoleLogTimer) return
  lastRecordCheck = Date.now() // the view has just read the record
  // The Scribe's own log first, so the chapters are known before her console
  // lines name them.
  fetchAgentLog().then(fetchConsoleLog)
  agentLogTimer = setInterval(fetchAgentLog, 2000)
  consoleLogTimer = setInterval(fetchConsoleLog, 1500)
}

const stopAgentPolling = () => {
  if (agentLogTimer) {
    clearInterval(agentLogTimer)
    agentLogTimer = null
  }
}

const stopConsolePolling = () => {
  if (consoleLogTimer) {
    clearInterval(consoleLogTimer)
    consoleLogTimer = null
  }
}

const stopPolling = () => {
  stopAgentPolling()
  stopConsolePolling()
}

const resetState = () => {
  reportOutline.value = null
  currentSectionIndex.value = null
  generatedSections.value = {}
  sourcesBySection.value = {}
  isComplete.value = false
  planningStarted.value = false
  agentLogLine.value = 0
  consoleLogLine.value = 0
  activeChapter.value = null
  localTrouble.value = ''
  lastRecordCheck = 0
}

watch(() => props.report, (r) => {
  if (r && r.status === 'completed') adoptRecord(r)
}, { immediate: true })

// When the Scribe cannot finish, the polling stops and the Way shows Trouble.
// The console is read once more so her last words reach the ledger.
watch(trouble, (why) => {
  if (why) {
    stopAgentPolling()
    if (consoleLogTimer) {
      fetchConsoleLog().finally(stopConsolePolling)
    }
    emit('update-status', 'error')
  }
}, { immediate: true })

watch(() => props.reportId, (newId) => {
  stopPolling()
  resetState()
  if (newId && !trouble.value) startPolling()
}, { immediate: true })

onMounted(() => {
  wideQuery?.addEventListener('change', onWide)
  window.addEventListener('scroll', onScroll, { passive: true })
  nextTick(onScroll)
})

onBeforeUnmount(() => {
  stopPolling()
  wideQuery?.removeEventListener('change', onWide)
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.chronicle-stage {
  flex: 1;
  width: 100%;
  min-width: 0;
  padding: clamp(24px, 4vw, 56px) var(--p-gutter) 80px;
}

.visually-hidden {
  position: absolute !important;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}

.chronicle {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  justify-items: center;
  min-width: 0;
}

/* The page */
.page {
  width: 100%;
  max-width: 58rem;
  min-width: 0;
  padding: clamp(36px, 6vw, 84px) clamp(20px, 6vw, 92px) clamp(48px, 6vw, 92px);
  box-shadow: var(--p-shadow-2);
  font-family: var(--p-font-serif);
  font-size: 1.125rem;
  line-height: 1.68;
  overflow-wrap: anywhere;
}

/* Title page */
.title-page {
  max-width: 72ch;
  margin: 0 auto;
}

.title {
  margin: 14px 0 0;
  font-family: var(--p-font-display);
  font-size: var(--t-3xl);
  font-weight: 500;
  line-height: 1.04;
  letter-spacing: -0.01em;
  color: var(--p-ink);
  text-wrap: balance;
}

.standfirst {
  margin: 22px 0 0;
  max-width: 44em;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.rule {
  margin: 32px 0 28px;
  opacity: 0.55;
}

.question-label {
  display: block;
  margin-bottom: 8px;
}

.question-text {
  margin: 0;
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
}

.date {
  margin: 18px 0 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 30px;
}

/* The Scribe's status */
.scribe-status {
  display: flex;
  align-items: center;
  gap: 14px;
  max-width: 72ch;
  margin: 40px auto 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
}

.ink-line {
  flex: 0 0 auto;
  width: 44px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--p-gold) 40%, var(--p-gold) 60%, transparent);
  transform-origin: left center;
  animation: ink 2.6s ease-in-out infinite;
}

@keyframes ink {
  0%, 100% { transform: scaleX(0.35); opacity: 0.5; }
  50% { transform: scaleX(1); opacity: 1; }
}

/* Trouble */
.trouble {
  max-width: 72ch;
  margin: 40px auto 0;
  padding: 18px 20px;
  border-left: 2px solid var(--p-error);
  background: var(--p-error-tint);
}

.trouble-title {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  color: var(--p-error);
}

.trouble-why {
  margin-top: 8px;
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  color: var(--p-ink-2);
}

.trouble-why summary {
  cursor: pointer;
  color: var(--p-ink-3);
}

.trouble-why p {
  margin: 8px 0 0;
}

/* Contents */
.contents-label {
  display: block;
  margin-bottom: 12px;
}

.contents-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.contents-link {
  display: grid;
  grid-template-columns: 1.6em minmax(0, 1fr);
  column-gap: 8px;
  align-items: baseline;
  width: 100%;
  padding: 7px 8px 7px 10px;
  border: 0;
  border-left: 2px solid transparent;
  background: transparent;
  color: var(--p-ink-2);
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 500;
  line-height: 1.3;
  text-align: left;
  cursor: pointer;
}

.contents-link:hover {
  color: var(--p-gold);
}

.contents-link:disabled {
  cursor: default;
  color: var(--p-ink-4);
}

.contents-item.current .contents-link {
  border-left-color: var(--p-gold);
  color: var(--p-gold);
}

.contents-num {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  color: var(--p-gold);
}

.contents-link:disabled .contents-num {
  color: var(--p-ink-4);
}

.contents-note {
  grid-column: 2;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-xs);
  color: var(--p-ink-4);
}

.contents--inline {
  max-width: 72ch;
  margin: 40px auto 0;
  padding-top: 28px;
  border-top: 1px solid var(--p-line);
}

/* Chapters */
.chapter {
  max-width: 72ch;
  margin: 56px auto 0;
  scroll-margin-top: calc(var(--p-header-h) + 28px);
}

.chapter + .chapter {
  margin-top: 64px;
  padding-top: 52px;
  border-top: 1px solid var(--p-line);
}

.chapter.is-done {
  animation: arrive 0.7s ease both;
}

@keyframes arrive {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}

.chapter-head {
  margin-bottom: 26px;
}

.chapter-num {
  display: block;
}

.chapter-title {
  margin: 10px 0 0;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.1;
  color: var(--p-ink);
  text-wrap: balance;
}

.chapter-title:focus:not(:focus-visible) {
  outline: none;
}

.chapter-writing {
  margin-top: 8px;
  font-size: var(--t-md);
}

/* The Scribe's prose */
.chapter-body {
  color: var(--p-ink-2);
}

.chapter-body :deep(p) {
  margin: 0 0 1.15em;
}

.chapter-body :deep(p:last-child) {
  margin-bottom: 0;
}

.chapter-body :deep(> p:first-of-type)::first-letter {
  float: left;
  margin: 0.08em 0.12em 0 0;
  font-family: var(--p-font-display);
  font-size: 4.4em;
  font-weight: 500;
  line-height: 0.78;
  color: var(--p-terracotta);
}

.chapter-body :deep(h3),
.chapter-body :deep(h4),
.chapter-body :deep(h5) {
  margin: 1.8em 0 0.6em;
  font-family: var(--p-font-display);
  font-weight: 600;
  line-height: 1.2;
  color: var(--p-ink);
}

.chapter-body :deep(h3) { font-size: var(--t-lg); }
.chapter-body :deep(h4) { font-size: var(--t-md); }
.chapter-body :deep(h5) { font-size: var(--t-sm); }

.chapter-body :deep(blockquote) {
  margin: 1.3em 0;
  padding: 2px 0 2px 1.1em;
  border-left: 2px solid var(--p-gold);
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: 1.12em;
  line-height: 1.5;
  color: var(--p-ink);
}

.chapter-body :deep(ul),
.chapter-body :deep(ol) {
  margin: 0 0 1.15em;
  padding-left: 1.4em;
}

.chapter-body :deep(li) {
  margin: 0.3em 0;
}

.chapter-body :deep(li[data-level='1']) { margin-left: 1.2em; }
.chapter-body :deep(li[data-level='2']) { margin-left: 2.4em; }

.chapter-body :deep(strong) {
  font-weight: 600;
  color: var(--p-ink);
}

.chapter-body :deep(hr) {
  height: 1px;
  margin: 2em 0;
  border: 0;
  background: var(--p-line);
}

.chapter-body :deep(code) {
  font-family: var(--p-font-mono);
  font-size: 0.85em;
}

.chapter-body :deep(pre) {
  margin: 0 0 1.15em;
  padding: 12px 14px;
  overflow: auto;
  background: var(--p-surface-2);
  border: 1px solid var(--p-line);
}

/* How the Scribe found this */
.how-found {
  margin-top: 28px;
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.how-found summary {
  width: fit-content;
  min-height: 24px;
  padding: 8px 0;
  box-sizing: border-box;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ochre-deep);
  cursor: pointer;
}

.how-found summary:hover {
  color: var(--p-ink);
}

.how-list {
  margin: 10px 0 0;
  padding-left: 1.2em;
  line-height: 1.55;
}

/* Colophon */
.colophon {
  max-width: 72ch;
  margin: 64px auto 0;
}

.colophon-line {
  margin: 0 0 22px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
}

/* The film sits at the end of the page at reading measure */
.page :deep(.chronicle-film) {
  max-width: 72ch;
  margin-inline: auto;
}

/* Wide screens: the contents stand in the margin */
@media (min-width: 1200px) {
  .chronicle.has-margin {
    grid-template-columns: minmax(180px, 220px) minmax(0, 58rem) minmax(0, 1fr);
    column-gap: 40px;
    justify-items: stretch;
  }

  .contents--margin {
    grid-column: 1;
    position: sticky;
    top: calc(var(--p-header-h) + 36px);
    align-self: start;
    min-width: 0;
    padding-top: clamp(36px, 6vw, 84px);
  }

  .chronicle.has-margin .page {
    grid-column: 2;
  }
}

@media (min-width: 1400px) {
  .chronicle.has-margin {
    grid-template-columns: minmax(0, 1fr) minmax(0, 58rem) minmax(0, 1fr);
  }

  .contents--margin {
    justify-self: end;
    width: min(100%, 250px);
  }
}

/* Phones: the page is the document */
@media (max-width: 899px) {
  .chronicle-stage {
    padding: 20px 16px 72px;
  }

  .page {
    padding: 34px 20px 44px;
    font-size: 1.0625rem;
    line-height: 1.62;
  }

  .title {
    font-size: var(--t-2xl);
  }

  .chapter-title {
    font-size: var(--t-xl);
  }

  .chapter {
    margin-top: 44px;
  }

  .chapter + .chapter {
    margin-top: 48px;
    padding-top: 40px;
  }

  .actions .p-button {
    flex: 1 1 100%;
  }

  .chapter-body :deep(> p:first-of-type)::first-letter {
    font-size: 3.8em;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ink-line {
    animation: none;
    transform: none;
    opacity: 1;
  }

  .chapter.is-done {
    animation: none;
  }
}
</style>
