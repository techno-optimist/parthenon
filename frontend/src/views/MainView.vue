<template>
  <ActShell :act="1" :status="shellStatus" :logs="systemLogs" :links="{}">
    <template #web>
      <GraphPanel
        :graphData="graphData"
        :loading="graphLoading"
        :currentPhase="currentPhase"
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
      :error="error"
      :noScroll="noScroll"
      @log="addLog"
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
import { getPendingUpload, clearPendingUpload } from '../store/pendingUpload'
import { speakers } from '../parthenon/speakers.js'
import { arrivals } from '../parthenon/arrivals/index.js'
import { stripIds, isPlatformNode, isActivityTie } from '../parthenon/vocabulary.js'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// The court's state
const currentProjectId = ref(route.params.projectId)
const graphLoading = ref(false)
const error = ref('')
const noScroll = ref(false)
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

const shellStatus = computed(() => {
  if (error.value) return 'error'
  if (noScroll.value) return 'ready'
  if (currentPhase.value >= 2) return 'done'
  return 'working'
})

// --- The ledger -------------------------------------------------------------

// Engine progress lines arrive in the engine's words; the ledger keeps the
// city's. Identifiers never reach the page.
const inVoice = (msg) =>
  stripIds(String(msg ?? ''))
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
// arrival's title, a stage the visitor built, or the visitor's own scroll.
// The file's name never reaches the page.
const scrollSource = computed(() => {
  const file = seedName.value
  if (!file) return null
  const speaker = speakers.find((s) => s.fileName === file)
  if (speaker) return { kind: 'speaker', name: speaker.name, work: speaker.work || '' }
  const arrival = arrivals.find((a) => a.fileName === file)
  if (arrival) return { kind: 'arrival', title: arrival.title || arrival.name || '' }
  if (/^stage-/i.test(file)) return { kind: 'stage' }
  return { kind: 'own' }
})

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
    return
  }

  try {
    currentPhase.value = 0
    seedName.value = pending.files[0]?.name || ''
    seedText.value = await readPendingScroll(pending.files)
    addLog(t('parthenon.hearing.ledger.handed'))

    const formData = new FormData()
    pending.files.forEach((f) => formData.append('files', f))
    formData.append('simulation_requirement', pending.simulationRequirement)

    const res = await generateOntology(formData)
    if (res.success) {
      clearPendingUpload()
      currentProjectId.value = res.data.project_id
      projectData.value = res.data
      rememberScroll(res.data.project_id, seedText.value)

      router.replace({ name: 'Process', params: { projectId: res.data.project_id } })
      addLog(t('parthenon.hearing.ledger.read'))
      await startBuildGraph()
    } else {
      error.value = res.error || t('common.unknownError')
      addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
    }
  } catch (err) {
    error.value = err.message
    addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
  }
}

const loadProject = async () => {
  try {
    const res = await getProject(currentProjectId.value)
    if (res.success) {
      projectData.value = res.data
      updatePhaseByStatus(res.data.status)
      recoverScroll()

      if (res.data.status === 'ontology_generated' && !res.data.graph_id) {
        addLog(t('parthenon.hearing.ledger.read'))
        await startBuildGraph()
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
      error.value = res.error
      addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
    }
  } catch (err) {
    error.value = err.message
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
      error.value = res.error
      addLog(t('parthenon.hearing.ledger.trouble', { error: error.value }))
    }
  } catch (err) {
    error.value = err.message
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

// The count the Web itself draws, so the status line, the ledger and the Web
// panel never disagree: the platform nodes are the squares, not names; a tie
// to nothing or to oneself is dropped; parallel ties between the same two
// names are one tie; and the square's own chatter (who spoke, nodded, quoted)
// is counted apart from the shape of the city.
const countWeb = (data) => {
  const nodes = (Array.isArray(data?.nodes) ? data.nodes : []).filter((n) => n && n.uuid && !isPlatformNode(n.name))
  const ids = new Set(nodes.map((n) => n.uuid))
  const pairs = new Set()
  let chatter = 0
  for (const e of Array.isArray(data?.edges) ? data.edges : []) {
    const a = e?.source_node_uuid
    const b = e?.target_node_uuid
    if (!ids.has(a) || !ids.has(b) || a === b) continue
    if (isActivityTie(e.name || e.fact_type || 'RELATES_TO')) {
      chatter++
      continue
    }
    pairs.add(a < b ? `${a}|${b}` : `${b}|${a}`)
  }
  return { names: nodes.length, ties: pairs.size, chatter }
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
        error.value = task.error
        addLog(t('parthenon.hearing.ledger.trouble', { error: task.error }))
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
      addLog(t('parthenon.hearing.ledger.trouble', { error: res.error }))
    }
  } catch (e) {
    addLog(t('parthenon.hearing.ledger.trouble', { error: e.message }))
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
