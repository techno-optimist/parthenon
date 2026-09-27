<template>
  <ActShell :act="1" :status="shellStatus" :status-text="shellStatusText" :logs="systemLogs" :links="links">
    <template #web>
      <GraphPanel
        :graphData="graphData"
        :loading="graphLoading"
        :currentPhase="currentPhase"
        :hold="heldName"
        @refresh="refreshGraph"
      />
    </template>

    <Step1GraphBuild
      :currentPhase="currentPhase"
      :projectData="projectData"
      :graphData="graphData"
      :web="webCounts"
      :seedText="seedText"
      :seedName="seedName"
      :source="scrollSource"
      :host="host"
      :error="error"
      :noScroll="noScroll"
      :notFound="notFound"
      :recovery="recovery"
      :gatherings="gatherings"
      :gatheringsRead="gatheringsRead"
      :autoSummon="autoSummon"
      :calm="calm"
      :control="control"
      :invite="inviteAsk"
      @invite-given="onInviteGiven"
      @log="addLog"
      @rehand="rehand"
      @summoned="onSummoned"
      @hold="heldName = $event"
    />
  </ActShell>
</template>

<script setup>
// Act Α΄ The Hearing: the court at night. The scroll is handed to the court
// (the pending upload), the court reads it and carves its inscription, the
// city's memory takes in the names, and the citizens can be summoned.
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ActShell from '../components/ActShell.vue'
import GraphPanel from '../components/GraphPanel.vue'
import Step1GraphBuild from '../components/Step1GraphBuild.vue'
import { generateOntology, getProject, buildGraph, getTaskStatus, getGraphData } from '../api/graph'
import { findGatherings } from '../api/simulation'
import pendingUpload, { getPendingUpload, clearPendingUpload, setPendingUpload } from '../store/pendingUpload'
import { speakers, speakerSeedFile } from '../parthenon/speakers.js'
import { arrivals, arrivalSeedFile } from '../parthenon/arrivals/index.js'
import { localText } from '../parthenon/localText.js'
import { speakerFaceUrl } from '../parthenon/portraits.js'
import { stripIds, readable, bestGathering, wayLinks } from '../parthenon/vocabulary.js'
import { buildWebModel } from '../parthenon/web.js'
import { calmCode, calmLine, canControl, inviteNeeded } from '../parthenon/access.js'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

// The court's state
const currentProjectId = ref(route.params.projectId)
const graphLoading = ref(false)
const error = ref('')
// A limit of the public steps (the day's gatherings, a scroll too long), said calmly in place of trouble.
const calm = ref('')
// On steps that ask for the word: the scroll is held until the visitor brings it.
const inviteAsk = ref(false)
const noScroll = ref(false)
// An address with no scroll behind it (a mistyped or forgotten link).
const notFound = ref(false)
const projectData = ref(null)
const graphData = ref(null)
const currentPhase = ref(-1) // -1: handed over, 0: being read, 1: taken in, 2: known
const buildProgress = ref(null)
const systemLogs = ref([])

// The scroll itself, for the parchment
const seedText = ref('')
const seedName = ref('')

let pollTimer = null
let graphPollTimer = null

// Only the one who began a gathering may steer it on the public steps (always, at home).
const control = computed(() => canControl(currentProjectId.value))

const shellStatus = computed(() => {
  if (notFound.value) return 'ready'
  if (calm.value || inviteAsk.value) return 'ready'
  if (error.value) return 'error'
  if (noScroll.value) return 'ready'
  if (currentPhase.value >= 2) return 'done'
  return 'working'
})
const shellStatusText = computed(() => (notFound.value ? t('parthenon.hearing.notFoundStatus') : ''))

// A name held in the Hearing's list lights its star in the Web beside it.
const heldName = ref('')

// ---- The gatherings this scroll has already called ----
// A revisited Hearing leads back to them (the Way's later stations and the
// door out of the court) instead of summoning a new crowd by default.
const gatherings = ref([])
const gatheringsRead = ref(false)
let gatheringsFor = ''
const readGatherings = async () => {
  const id = currentProjectId.value
  if (!id || id === 'new') return
  gatheringsFor = id
  try {
    const rows = await findGatherings({ projectId: id })
    if (gatheringsFor !== id) return
    gatherings.value = rows
  } catch (err) {
    // The shelf is quiet: the court offers to summon, as before.
  } finally {
    if (gatheringsFor === id) gatheringsRead.value = true
  }
}

const links = computed(() => {
  const id = currentProjectId.value && currentProjectId.value !== 'new' ? currentProjectId.value : ''
  return wayLinks(bestGathering(gatherings.value), { projectId: id })
})

// ---- Let Athens speak, carried through ----
// A Hearing begun from the steps in this tab summons the citizens on its own
// once the court has finished, so the visitor is carried into the Gathering.
// The mark survives a reload of this tab; a Hearing revisited later (or with
// gatherings of its own already) never summons by itself.
const FROM_STEPS_KEY = 'parthenon.hearing.fromSteps'
const startedHere = ref(false)
const markFromSteps = (id) => {
  startedHere.value = true
  try { sessionStorage.setItem(FROM_STEPS_KEY, id) } catch (e) { /* this visit still carries it */ }
}
const readFromSteps = (id) => {
  try { return !!id && sessionStorage.getItem(FROM_STEPS_KEY) === id } catch (e) { return false }
}
const onSummoned = () => {
  startedHere.value = false
  try { sessionStorage.removeItem(FROM_STEPS_KEY) } catch (e) { /* nothing kept */ }
}
const autoSummon = computed(() =>
  startedHere.value && gatheringsRead.value && !gatherings.value.length && currentPhase.value >= 2 && !error.value
)

// --- The ledger -------------------------------------------------------------

// Engine progress lines arrive in the engine's words; the ledger keeps the
// city's. Identifiers never reach the page, nor a line in a language the
// visitor does not read.
const inVoice = (msg) =>
  readable(stripIds(String(msg ?? '')), '')
    .replace(/\bZep\b/gi, "the city's memory")
    .replace(/\bGraphRAG\b/gi, 'the Web of Athens')
    .replace(/\bknowledge graph\b/gi, 'the Web of Athens')
    .replace(/\bmemory graph\b/gi, "the city's memory")
    .replace(/\bgraph build\b/gi, 'weaving of the Web')
    .replace(/\bgraph\b/gi, 'Web')
    .replace(/\bontology definition\b/gi, 'inscription')
    .replace(/\bontology\b/gi, 'inscription')
    .replace(/\bentities\b/gi, 'names')
    .replace(/\bentity\b/gi, 'name')
    .replace(/\bepisodes?\b/gi, (m) => (m.endsWith('s') ? 'passages' : 'passage'))
    .replace(/\bchunks?\b/gi, (m) => (m.endsWith('s') ? 'passages' : 'passage'))
    .replace(/\bchunking\b/gi, 'dividing')
    .replace(/\bagents?\b/gi, (m) => (m.endsWith('s') ? 'citizens' : 'citizen'))
    .replace(/\bLLM\b/g, 'the Oracle')
    .replace(/\btask\b/gi, 'work')

// What the engine gave as its reason, in words the visitor reads.
const engineWords = (text) => readable(stripIds(String(text ?? '')), t('common.otherTongue'))

const addLog = (msg) => {
  const now = new Date()
  const time = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const message = inVoice(msg)
  if (!message) return
  systemLogs.value.push({ time, message })
  if (systemLogs.value.length > 100) systemLogs.value.shift()
}

// --- The scroll -------------------------------------------------------------

const SCROLL_KEY = (id) => `parthenon.scroll.${id}`
const isTextFile = (f) => /^text\//.test(f?.type || '') || /\.(md|txt|markdown)$/i.test(f?.name || '')

// The seed on a prepared scroll lives in the front end, so a revisit can show
// it again by its file name. A visitor's own scroll is remembered for this
// browser session only.
const rememberedScroll = (id) => {
  try { return sessionStorage.getItem(SCROLL_KEY(id)) || '' } catch (e) { return '' }
}
const rememberScroll = (id, text) => {
  if (!id || !text) return
  try { sessionStorage.setItem(SCROLL_KEY(id), text) } catch (e) { /* per-viewer convenience only */ }
}
const preparedScroll = (fileName) => {
  if (!fileName) return ''
  const match = [...speakers, ...arrivals].find((item) => item.fileName === fileName)
  return match?.seed || ''
}

const readPendingScroll = async (files) => {
  const texts = []
  for (const f of files) {
    if (!isTextFile(f) || typeof f.text !== 'function') continue
    try { texts.push(await f.text()) } catch (e) { /* the parchment shows what the court heard instead */ }
  }
  return texts.join('\n\n')
}

const recoverScroll = () => {
  const first = projectData.value?.files?.[0]
  seedName.value = first?.filename || ''
  if (!seedText.value) seedText.value = preparedScroll(seedName.value) || rememberedScroll(currentProjectId.value)
}

// Where the scroll came from, in words: the speaker and their work, the
// arrival's title, a stage the visitor built, or the visitor's own scroll, in
// the visitor's language. The file's name never reaches the page.
const scrollSource = computed(() => {
  const file = seedName.value
  if (!file) return null
  const lang = locale.value
  const speaker = speakers.find((s) => s.fileName === file)
  if (speaker) return { kind: 'speaker', name: localText(speaker, 'name', lang), work: localText(speaker, 'work', lang) }
  const arrival = arrivals.find((a) => a.fileName === file)
  if (arrival) return { kind: 'arrival', title: localText(arrival, 'title', lang) || localText(arrival, 'name', lang) }
  if (/^stage-/i.test(file)) return { kind: 'stage' }
  return { kind: 'own' }
})

// The philosopher who took the steps keeps the floor at the Hearing.
const host = computed(() => {
  const file = seedName.value
  const speaker = file ? speakers.find((s) => s.fileName === file) : null
  if (!speaker) return null
  const lang = locale.value
  return {
    id: speaker.id,
    name: localText(speaker, 'name', lang),
    greek: speaker.greek,
    line: localText(speaker, 'line', lang),
    portrait: speakerFaceUrl(speaker.id) // the face of the figure on the steps
  }
})

// ---- A scroll handed over and lost to a reload ----
// The first reading can outlast a phone's patience: switching apps often
// reloads the tab before the court has named the scroll. What was handed over
// is kept in this tab so the court can be given it again: a prepared scroll
// by its name, the visitor's own text or built stage whole. A PDF must be
// chosen again.
const PENDING_KEY = 'parthenon.hearing.pending'
const PENDING_FOR_MS = 12 * 60 * 60 * 1000
const recovery = ref(null) // { question, files: [{ name, kind }], ready }

const preparedFile = (name) => {
  const speaker = speakers.find((s) => s.fileName === name)
  if (speaker) return speakerSeedFile(speaker)
  const arrival = arrivals.find((a) => a.fileName === name)
  return arrival ? arrivalSeedFile(arrival) : null
}

const keepPending = async (pending) => {
  const files = []
  for (const f of pending.files) {
    if (preparedScroll(f.name)) {
      files.push({ name: f.name, kind: 'prepared' })
      continue
    }
    let text = ''
    if (isTextFile(f) && typeof f.text === 'function') {
      try { text = await f.text() } catch (e) { text = '' }
    }
    files.push(text ? { name: f.name, kind: 'text', type: f.type || 'text/markdown', text } : { name: f.name, kind: 'other' })
  }
  const record = {
    files,
    question: pending.simulationRequirement || '',
    maxRounds: Number(route.query.maxRounds) || Number(pendingUpload.maxRounds) || null,
    at: Date.now()
  }
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(record))
  } catch (e) {
    // Too large to keep, or storage refused: without it only the question is kept.
    try { sessionStorage.setItem(PENDING_KEY, JSON.stringify({ ...record, files: files.map(({ text, ...rest }) => ({ ...rest, kind: rest.kind === 'text' ? 'other' : rest.kind })) })) } catch (e2) { /* nothing kept */ }
  }
}

const forgetPending = () => {
  try { sessionStorage.removeItem(PENDING_KEY) } catch (e) { /* nothing kept */ }
}

const readKeptPending = () => {
  try {
    const record = JSON.parse(sessionStorage.getItem(PENDING_KEY) || 'null')
    if (!record || !Array.isArray(record.files) || !record.files.length) return null
    if (Date.now() - Number(record.at || 0) > PENDING_FOR_MS) return null
    return record
  } catch (e) {
    return null
  }
}

let keptRecord = null
const offerRecovery = () => {
  keptRecord = readKeptPending()
  if (!keptRecord) return
  recovery.value = {
    question: keptRecord.question,
    files: keptRecord.files.map((f) => ({ name: f.name, kind: f.kind })),
    ready: keptRecord.files.every((f) => f.kind === 'prepared' || (f.kind === 'text' && f.text))
  }
}

// Hand the kept scroll to the court again, as the steps would have.
const rehand = async () => {
  const record = keptRecord || readKeptPending()
  if (!record) return
  const files = record.files
    .map((f) => (f.kind === 'prepared' ? preparedFile(f.name) : f.kind === 'text' && f.text ? new File([f.text], f.name, { type: f.type || 'text/markdown' }) : null))
    .filter(Boolean)
  if (!files.length || files.length !== record.files.length) return
  setPendingUpload(files, record.question || '')
  if (record.maxRounds) pendingUpload.maxRounds = record.maxRounds
  recovery.value = null
  noScroll.value = false
  await handleNewProject()
}

// --- The court --------------------------------------------------------------

const initProject = async () => {
  addLog(t('parthenon.hearing.ledger.opened'))
  if (currentProjectId.value === 'new') {
    await handleNewProject()
  } else {
    await loadProject()
  }
}

const handleNewProject = async () => {
  const pending = getPendingUpload()
  if (!pending.isPending || pending.files.length === 0) {
    noScroll.value = true
    offerRecovery()
    return
  }
  // The steps ask for the word before a scroll is heard: ask here, and hold the scroll.
  if (inviteNeeded()) {
    inviteAsk.value = true
    return
  }
  inviteAsk.value = false

  try {
    currentPhase.value = 0
    seedName.value = pending.files[0]?.name || ''
    seedText.value = await readPendingScroll(pending.files)
    await keepPending(pending)
    addLog(t('parthenon.hearing.ledger.handed'))

    const formData = new FormData()
    pending.files.forEach((f) => formData.append('files', f))
    formData.append('simulation_requirement', pending.simulationRequirement)

    const res = await generateOntology(formData)
    if (res.success) {
      clearPendingUpload()
      forgetPending()
      currentProjectId.value = res.data.project_id
      projectData.value = res.data
      rememberScroll(res.data.project_id, seedText.value)
      markFromSteps(res.data.project_id)
      gatheringsRead.value = true // a scroll heard for the first time has called no one yet

      router.replace({ name: 'Process', params: { projectId: res.data.project_id }, query: route.query })
      if (res.data.status === 'created' && res.data.task_id) {
        // On the public steps the court reads the scroll in a task of its own
        // and then weaves the Web in the same task: the page follows it.
        currentPhase.value = 0
        startPollingTask(res.data.task_id)
        startGraphPolling()
      } else {
        addLog(t('parthenon.hearing.ledger.read'))
        await startBuildGraph()
      }
    } else {
      error.value = engineWords(res.error) || t('common.unknownError')
      addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
    }
  } catch (err) {
    // The word was not brought, or not known: the scroll is held, and the word asked for in place.
    if (calmCode(err) === 'invite_needed') {
      currentPhase.value = -1
      inviteAsk.value = true
      return
    }
    if (sayCalmly(err)) return
    error.value = engineWords(err.message)
    addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
  }
}

// The word given: the held scroll is handed to the court again.
const onInviteGiven = () => {
  inviteAsk.value = false
  handleNewProject()
}

// A limit of the public steps: one calm line in place, never a raw error.
const sayCalmly = (err) => {
  const line = calmLine(err)
  if (!line) return false
  calm.value = line
  addLog(line)
  return true
}

const loadProject = async () => {
  startedHere.value = readFromSteps(currentProjectId.value)
  readGatherings()
  try {
    const res = await getProject(currentProjectId.value)
    if (res.success) {
      projectData.value = res.data
      updatePhaseByStatus(res.data.status)
      recoverScroll()

      if (res.data.status === 'created' && res.data.hearing_task_id) {
        // On the public steps the scroll is read in a task of its own, which
        // then weaves the Web: a page reloaded meanwhile follows that task again.
        currentPhase.value = 0
        startPollingTask(res.data.hearing_task_id)
        startGraphPolling()
      } else if (res.data.status === 'ontology_generated' && !res.data.graph_id) {
        addLog(t('parthenon.hearing.ledger.read'))
        // Only the one who began it carries the reading on; a guest sees where it stands
        // (and, on the public steps, follows the task that reads and weaves it).
        if (control.value) await startBuildGraph()
        else if (res.data.hearing_task_id) {
          startPollingTask(res.data.hearing_task_id)
          startGraphPolling()
        }
      } else if (res.data.status === 'graph_building' && res.data.graph_build_task_id) {
        currentPhase.value = 1
        addLog(t('parthenon.hearing.ledger.memoryBegins'))
        startPollingTask(res.data.graph_build_task_id)
        startGraphPolling()
      } else if (res.data.status === 'graph_completed' && res.data.graph_id) {
        currentPhase.value = 2
        await loadGraph(res.data.graph_id)
      }
    } else {
      error.value = engineWords(res.error)
      addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
    }
  } catch (err) {
    if (err?.response?.status === 404) {
      notFound.value = true
      addLog(t('parthenon.hearing.notFound'))
      return
    }
    error.value = engineWords(err.message)
    addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
  }
}

const updatePhaseByStatus = (status) => {
  switch (status) {
    case 'created':
    case 'ontology_generated': currentPhase.value = 0; break
    case 'graph_building': currentPhase.value = 1; break
    case 'graph_completed': currentPhase.value = 2; break
    case 'failed': error.value = t('parthenon.hearing.trouble.body'); break
  }
}

const startBuildGraph = async () => {
  try {
    currentPhase.value = 1
    buildProgress.value = { progress: 0, message: '' }
    addLog(t('parthenon.hearing.ledger.memoryBegins'))

    const res = await buildGraph({ project_id: currentProjectId.value })
    if (res.success) {
      if (res.data.reused && res.data.graph_id) {
        currentPhase.value = 2
        buildProgress.value = null
        addLog(t('parthenon.hearing.ledger.memoryKnown'))
        const projectRes = await getProject(currentProjectId.value)
        if (projectRes.success) {
          projectData.value = projectRes.data
          recoverScroll()
        }
        await loadGraph(res.data.graph_id)
        return
      }

      startPollingTask(res.data.task_id)
      startGraphPolling()
    } else {
      error.value = engineWords(res.error)
      addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
    }
  } catch (err) {
    if (sayCalmly(err)) return
    error.value = engineWords(err.message)
    addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
  }
}

// While the memory takes the scroll in, the Web is read every ten seconds so
// the names light up as they arrive.
const startGraphPolling = () => {
  if (graphPollTimer) return
  addLog(t('parthenon.hearing.ledger.watching'))
  fetchGraphData()
  graphPollTimer = setInterval(fetchGraphData, 10000)
}

// The count the Web itself draws, from the Web's own reading, so the status
// line, the ledger and the Web panel never disagree: the platform nodes are
// the squares, not names; a tie to nothing or to oneself is dropped; parallel
// ties between the same two names are one tie; and the square's own chatter
// (who spoke, nodded, quoted) is counted apart, one thread for each.
const countWeb = (data) => {
  const m = buildWebModel(data)
  return { names: m.nodes.length, ties: m.tieCount, chatter: m.chatterThreads }
}

const webCounts = computed(() => countWeb(graphData.value))

// The ledger says what the Web shows, and names the chatter only when there is any.
const webLine = (key, counts) =>
  t(`parthenon.hearing.ledger.${counts.chatter ? `${key}Chatter` : key}`, counts)

let lastCounts = ''
const fetchGraphData = async () => {
  try {
    const projRes = await getProject(currentProjectId.value)
    if (projRes.success && projRes.data.graph_id) {
      if (!projectData.value?.graph_id) projectData.value = projRes.data
      const gRes = await getGraphData(projRes.data.graph_id)
      if (gRes.success) {
        graphData.value = gRes.data
        const counts = countWeb(gRes.data)
        const mark = `${counts.names}/${counts.ties}/${counts.chatter}`
        if (mark !== lastCounts) {
          lastCounts = mark
          addLog(webLine('soFar', counts))
        }
      }
    }
  } catch (err) {
    console.warn('Graph fetch error:', err)
  }
}

const startPollingTask = (taskId) => {
  pollTaskStatus(taskId)
  pollTimer = setInterval(() => pollTaskStatus(taskId), 2000)
}

const pollTaskStatus = async (taskId) => {
  try {
    const res = await getTaskStatus(taskId)
    if (res.success) {
      const task = res.data

      if (task.message && task.message !== buildProgress.value?.message) {
        addLog(task.message)
      }

      buildProgress.value = { progress: task.progress || 0, message: task.message }
      // A scroll read in its own task (the public steps): past the reading, the memory takes it in.
      if (currentPhase.value === 0 && Number(task.progress) > 5 && task.status !== 'failed') currentPhase.value = 1

      if (task.status === 'completed') {
        addLog(t('parthenon.hearing.ledger.memoryDone'))
        stopPolling()
        stopGraphPolling()
        currentPhase.value = 2

        const projRes = await getProject(currentProjectId.value)
        if (projRes.success && projRes.data.graph_id) {
          projectData.value = projRes.data
          recoverScroll()
          await loadGraph(projRes.data.graph_id)
        }
      } else if (task.status === 'failed') {
        stopPolling()
        stopGraphPolling()
        error.value = engineWords(task.error)
        addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
      }
    }
  } catch (e) {
    console.error(e)
  }
}

const loadGraph = async (graphId) => {
  graphLoading.value = true
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      addLog(webLine('webRead', countWeb(res.data)))
    } else {
      addLog(t('parthenon.hearing.ledger.trouble', { error: engineWords(res.error) }))
    }
  } catch (e) {
    addLog(t('parthenon.hearing.ledger.trouble', { error: engineWords(e.message) }))
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (projectData.value?.graph_id) {
    addLog(t('parthenon.hearing.ledger.webAgain'))
    loadGraph(projectData.value.graph_id)
  }
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const stopGraphPolling = () => {
  if (graphPollTimer) {
    clearInterval(graphPollTimer)
    graphPollTimer = null
    addLog(t('parthenon.hearing.ledger.restWatching'))
  }
}

onMounted(() => {
  initProject()
})

onUnmounted(() => {
  stopPolling()
  stopGraphPolling()
})
</script>

<style scoped>
/* The shell's Web pane keeps display: flex while [hidden], so the sheet showed
   open on phones. Until ActShell carries this rule, the Hearing closes it here. */
.act-shell :deep(.web-pane[hidden]) {
  display: none;
}

/* At phone width the brand and the act name run into the Web toggle; the name
   yields first. ActShell should carry this once, for every act. */
@media (max-width: 480px) {
  .act-shell :deep(.act-subject) {
    min-width: 0;
    overflow: hidden;
    gap: 8px;
  }

  .act-shell :deep(.act-name) {
    font-size: var(--t-md);
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
</style>
