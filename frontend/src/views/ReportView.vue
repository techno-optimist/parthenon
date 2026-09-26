<template>
  <ActShell :act="4" :status="shellStatus" :logs="systemLogs" :links="links">
    <Step4Report
      :reportId="currentReportId"
      :simulationId="simulationId"
      :report="reportData"
      :loadError="loadError"
      :plate="plate"
      @add-log="addLog"
      @update-status="updateStatus"
    />
  </ActShell>
</template>

<script setup>
// Act Δ΄, the Chronicle. The document is the whole stage: no Web pane here,
// the Chronicle is a thing to read. The view loads the Chronicle's record to
// learn which gathering it belongs to, so the Way can lead back to the earlier
// acts, and keeps the ledger for the shell. It also finds the scroll the
// gathering began from, so the title page can carry the face of the speaker
// or the painting of the stage.
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ActShell from '../components/ActShell.vue'
import Step4Report from '../components/Step4Report.vue'
import { getSimulation } from '../api/simulation'
import { getReport } from '../api/report'
import { getProject } from '../api/graph'
import { ACTS } from '../parthenon/vocabulary.js'
import { speakers } from '../parthenon/speakers.js'
import { arrivals } from '../parthenon/arrivals/index.js'

const route = useRoute()
const { t } = useI18n()

defineProps({
  reportId: String
})

const currentReportId = ref(route.params.reportId)
const simulationId = ref(null)
const projectId = ref(null)
const seedFile = ref('')
const seedKnown = ref(false) // the plate waits for the scroll's name, so it never flickers
const reportData = ref(null)
const loadError = ref('')
const systemLogs = ref([])
const currentStatus = ref('processing') // processing | completed | error

const shellStatus = computed(() => {
  if (currentStatus.value === 'error') return 'error'
  if (currentStatus.value === 'completed') return 'done'
  return 'working'
})

// Stations that can be revisited from here. The Symposium opens once the
// Chronicle is written.
const links = computed(() => {
  const out = {}
  if (projectId.value) out[1] = { name: 'Process', params: { projectId: projectId.value } }
  if (simulationId.value) {
    out[2] = { name: 'Simulation', params: { simulationId: simulationId.value } }
    out[3] = { name: 'SimulationRun', params: { simulationId: simulationId.value } }
  }
  if (currentStatus.value === 'completed' && currentReportId.value) {
    out[5] = { name: 'Interaction', params: { reportId: currentReportId.value } }
  }
  return out
})

// Ledger lines arrive as strings (stamped now) or as { time, message } from
// the engine's own console, which keeps its own clock. The same line said
// again in a row becomes one line with a count.
const addLog = (entry) => {
  const now = new Date()
  const stamp = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const line = entry && typeof entry === 'object'
    ? { time: entry.time || stamp, message: String(entry.message ?? '') }
    : { time: stamp, message: String(entry ?? '') }
  if (!line.message) return
  const last = systemLogs.value[systemLogs.value.length - 1]
  if (last && last.base === line.message) {
    last.count += 1
    last.message = t('parthenon.chronicle.ledger.repeated', { line: last.base, n: last.count })
    return
  }
  systemLogs.value.push({ ...line, base: line.message, count: 1 })
  if (systemLogs.value.length > 200) systemLogs.value.shift()
}

// The image beside the title: the philosopher who took the steps, the painted
// scene of an Arrival, or, for a stage of the visitor's own, the Scribe's desk.
const CHRONICLE_SCENE = ACTS[3].scene
const plate = computed(() => {
  if (!seedKnown.value) return null
  const file = seedFile.value
  const speaker = file ? speakers.find((s) => s.fileName === file) : null
  if (speaker) {
    return {
      kind: 'portrait',
      src: `/media/portraits/${speaker.id}.jpg`,
      name: speaker.name,
      greek: speaker.greek,
      caption: [speaker.work, [speaker.place, speaker.year].filter(Boolean).join(', ')].filter(Boolean).join(' · ')
    }
  }
  const arrival = file ? arrivals.find((a) => a.fileName === file) : null
  if (arrival) {
    return {
      kind: 'scene',
      src: `/media/scenes/arrival-${arrival.id}.jpg`,
      name: arrival.title,
      greek: arrival.greek,
      caption: [arrival.place, arrival.year].filter(Boolean).join(', ')
    }
  }
  return { kind: 'act', src: CHRONICLE_SCENE, name: '', greek: '', caption: '' }
})

// Which scroll the gathering began from: the project's first file.
const loadSeedFile = async (id) => {
  try {
    const res = await getProject(id)
    if (id !== projectId.value) return
    seedFile.value = res?.data?.files?.[0]?.filename || ''
  } catch {
    // Without the scroll's name the title page keeps the Scribe's desk.
  }
  if (id === projectId.value) seedKnown.value = true
}

const updateStatus = (status) => {
  currentStatus.value = status
}

const loadReportData = async () => {
  loadError.value = ''
  try {
    addLog(t('parthenon.chronicle.log.opened'))
    const reportRes = await getReport(currentReportId.value)
    if (reportRes.success && reportRes.data) {
      reportData.value = reportRes.data
      simulationId.value = reportRes.data.simulation_id || null
      if (reportRes.data.status === 'failed' || reportRes.data.error) {
        currentStatus.value = 'error'
      }
      if (simulationId.value) {
        try {
          const simRes = await getSimulation(simulationId.value)
          if (simRes.success && simRes.data?.project_id) {
            projectId.value = simRes.data.project_id
            loadSeedFile(simRes.data.project_id)
          } else {
            seedKnown.value = true
          }
        } catch (err) {
          seedKnown.value = true
          addLog(t('parthenon.chronicle.log.readFailed', { error: err.message }))
        }
      } else {
        seedKnown.value = true
      }
    } else {
      loadError.value = reportRes.error || t('parthenon.chronicle.notFound')
      seedKnown.value = true
      currentStatus.value = 'error'
      addLog(t('parthenon.chronicle.log.readFailed', { error: loadError.value }))
    }
  } catch (err) {
    const notFound = err?.response?.status === 404
    loadError.value = notFound ? t('parthenon.chronicle.notFound') : (err.message || t('common.unknownError'))
    seedKnown.value = true
    currentStatus.value = 'error'
    addLog(t('parthenon.chronicle.log.readFailed', { error: loadError.value }))
  }
}

watch(() => route.params.reportId, (newId) => {
  if (newId && newId !== currentReportId.value) {
    currentReportId.value = newId
    reportData.value = null
    simulationId.value = null
    projectId.value = null
    seedFile.value = ''
    seedKnown.value = false
    currentStatus.value = 'processing'
    loadReportData()
  }
})

loadReportData()
</script>
