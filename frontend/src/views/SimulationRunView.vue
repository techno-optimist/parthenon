<template>
  <ActShell bare web-default="closed" :act="3" :status="shellStatus" :status-text="shellStatusText" :logs="systemLogs" :links="links" :lede="$t('agora.lede')">
    <template #web>
      <GraphPanel
        :graphData="graphData"
        :loading="graphLoading"
        :currentPhase="3"
        :isSimulating="isSimulating"
        :simulationId="currentSimulationId"
        :pulse="webPulse"
        :hold="heldName"
        @refresh="refreshGraph"
      />
    </template>

    <Step3Simulation
      :simulationId="currentSimulationId"
      :maxRounds="maxRounds"
      :minutesPerRound="minutesPerRound"
      :totalHours="totalHours"
      :citizens="citizens"
      :reportId="reportId"
      :reportStatus="reportStatus"
      :reportTrouble="reportTrouble"
      :era="era"
      :reading="reading"
      @add-log="addLog"
      @update-status="updateStatus"
      @finished="onFinished"
      @beat="webPulse = $event"
      @hold="heldName = $event || ''"
      @reread="readStances"
    />
  </ActShell>
</template>

<script setup>
// The painted square is the scene, so the Agora's shell is bare: no threshold band above it.
// Keep the template to one root element: the route transition cannot animate a fragment.
// Act Γ΄, the Agora, on the shell: the Web of Athens beside the square, the
// scribe's ledger below it, the Way at the foot. The painted square is the
// act's scene, so the shell stands bare. The stage decides for itself whether
// to watch, read back or wait; this view feeds it what the city knows.
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ActShell from '../components/ActShell.vue'
import GraphPanel from '../components/GraphPanel.vue'
import Step3Simulation from '../components/Step3Simulation.vue'
import { getProject, getGraphData } from '../api/graph'
import { getSimulation, getSimulationConfig, getSimulationHistory } from '../api/simulation'
import { getReport, getReportBySimulation } from '../api/report'
import { getCitizenStances, startCitizenStances } from '../api/parthenon'
import { canControl } from '../parthenon/access.js'
import { stripIds, readable } from '../parthenon/vocabulary.js'
import { gatheringEra } from '../parthenon/square.js'
import { speakers } from '../parthenon/speakers.js'

const { t } = useI18n()
const route = useRoute()

defineProps({
  simulationId: String
})

// ---- State ----
const currentSimulationId = ref(route.params.simulationId)
const maxRounds = ref(route.query.maxRounds ? parseInt(route.query.maxRounds) : null)
const minutesPerRound = ref(60) // the engine's own default until the Scribe's setting is read
const totalHours = ref(0)
const citizens = ref([])
const reportId = ref('')
const reportStatus = ref('') // '' | completed | generating | failed
const reportTrouble = ref('')
const projectData = ref(null)
const graphData = ref(null)
const graphLoading = ref(false)
const systemLogs = ref([])
const shellStatus = ref('working') // ready | working | live | done | error
// A run stopped before its last hour is finished, but not complete: say so.
const endedHow = ref('')
const shellStatusText = computed(() => (shellStatus.value === 'done' && endedHow.value === 'stopped' ? t('agora.status.stopped') : ''))

const isSimulating = computed(() => shellStatus.value === 'live')

// Each move the square stages, by name: the Web blooms the speaker's star.
const webPulse = ref(null)
// A citizen held in the square is lit in the Web beside it, by name.
const heldName = ref('')

// Which Athens the square is painted as: a speaker's scroll from the steps
// stands in 399 BC, an Arrival stands today.
const SCROLLS = speakers.map((s) => s.fileName)
const projectRead = ref(false)
const era = computed(() => {
  const p = projectData.value
  // Until the scroll is known the square waits, rather than show the wrong Athens.
  if (!p) return projectRead.value ? 'now' : ''
  return gatheringEra({ files: p.files || [], requirement: p.simulation_requirement || '', summary: p.analysis_summary || '' }, SCROLLS)
})

// Stations that can be revisited from the Way: every one this gathering has
// reached, the Chronicle and the Symposium included once they exist.
const links = computed(() => {
  const out = {
    1: projectData.value?.project_id ? { name: 'Process', params: { projectId: projectData.value.project_id } } : null,
    2: { name: 'Simulation', params: { simulationId: currentSimulationId.value } }
  }
  if (reportId.value) {
    out[4] = { name: 'Report', params: { reportId: reportId.value } }
    if (reportStatus.value === 'completed') out[5] = { name: 'Interaction', params: { reportId: reportId.value } }
  }
  return out
})

// ---- The ledger ----
const addLog = (message) => {
  const now = new Date()
  const time = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  systemLogs.value.push({ time, message: stripIds(message) })
  if (systemLogs.value.length > 200) systemLogs.value.shift()
}

const updateStatus = (status) => {
  shellStatus.value = status
}

// When a run read back from the record has ended, the archive may already
// hold its Chronicle. A run that ended under our eyes has none yet, and a
// previous run's Chronicle must not be offered as this one's. A Chronicle the
// Scribe never finished is found too, so the stage can offer to write it again.
const lookedUpReport = ref(false)

// The shelf names each run's newest Chronicle and, once the backend carries
// it, how it stands. Until then the Chronicle itself is asked. A run older
// than the shelf shows is looked up by the run alone.
const findChronicle = async () => {
  const id = currentSimulationId.value
  try {
    const res = await getSimulationHistory(50, { ids: [id] })
    const items = Array.isArray(res?.data) ? res.data : []
    const mine = items.find((s) => s.simulation_id === id)
    if (mine) {
      if (!mine.report_id) return null
      if (mine.report_status) return { id: mine.report_id, status: mine.report_status, trouble: mine.report_error || '' }
      try {
        const rep = await getReport(mine.report_id)
        return { id: mine.report_id, status: rep?.data?.status || '', trouble: rep?.data?.error || '' }
      } catch (err) {
        return { id: mine.report_id, status: '', trouble: '' }
      }
    }
  } catch (err) {
    addLog(t('agora.log.shelfTrouble', { error: stripIds(err.message) }))
  }
  try {
    const res = await getReportBySimulation(id)
    if (res?.success && res.data?.report_id) return { id: res.data.report_id, status: res.data.status || '', trouble: res.data.error || '' }
  } catch (err) {
    // No Chronicle of this run anywhere: the stage offers to write one.
  }
  return null
}

const onFinished = async (how, { fresh } = {}) => {
  endedHow.value = how || ''
  // Who moved: the Scribe reads each citizen's own words once the square has closed.
  if (how === 'completed' || how === 'stopped') readStances()
  if (fresh) {
    reportId.value = ''
    reportStatus.value = ''
    reportTrouble.value = ''
    lookedUpReport.value = true
    return
  }
  if (lookedUpReport.value) return
  lookedUpReport.value = true
  const found = await findChronicle()
  if (!found) return
  reportId.value = found.id
  reportStatus.value = found.status
  reportTrouble.value = readable(stripIds(found.trouble), t('common.otherTongue'))
  if (found.status === 'failed') addLog(t('agora.log.scribeFailed'))
}

// ---- Who moved ----
// Once the square has closed, the Scribe reads where each citizen ended from
// their own words. A reading already made is shown at once; a missing or
// stale one is asked for once, then looked at every five seconds until it is
// done. null keeps the square's own view of where they began (a live run, a
// run nobody spoke in, a gathering the Scribe cannot find).
const reading = ref(null) // null | { status: 'reading' | 'completed' | 'failed', data }
const STANCE_EVERY = 5000
const STANCE_LOOKS = 360 // half an hour of looking before the page stops waiting
let stanceTimer = 0
let stanceRun = 0

const stopStances = () => {
  stanceRun++
  if (stanceTimer) clearTimeout(stanceTimer)
  stanceTimer = 0
}

const readStances = () => {
  const id = currentSimulationId.value
  if (!id) return
  stopStances()
  const run = stanceRun
  const current = () => run === stanceRun
  let asked = false
  let misses = 0
  let looks = 0
  const again = () => { stanceTimer = setTimeout(look, STANCE_EVERY) }
  const fail = () => { reading.value = { status: 'failed', data: null } }

  const ask = async () => {
    asked = true
    reading.value = { status: 'reading', data: null }
    try {
      const res = await startCitizenStances(id)
      if (!current()) return
      if (res?.data?.status === 'completed') look()
      else again()
    } catch (err) {
      if (!current()) return
      // Nobody has spoken yet: there is nothing to read, and the square keeps where they began.
      if (err?.response?.status === 409) reading.value = null
      else fail()
    }
  }

  const look = async () => {
    stanceTimer = 0
    if (!current()) return
    looks++
    let data = null
    try {
      const res = await getCitizenStances(id)
      data = res?.data || null
      misses = 0
    } catch (err) {
      if (!current()) return
      if (err?.response?.status === 404) {
        reading.value = null
        return
      }
      misses++
    }
    if (!current()) return
    if (!data) {
      if (misses >= 3 || looks >= STANCE_LOOKS) fail()
      else again()
      return
    }
    const s = data.status
    if (s === 'completed' && (!data.stale || asked)) {
      reading.value = { status: 'completed', data }
      return
    }
    if (!asked && (s === 'none' || s === 'failed' || data.stale)) {
      // Only the one who began the gathering asks the Scribe to read (on the
      // public steps); a guest sees the reading there is, or the square's own view.
      if (canControl(id, projectData.value?.project_id)) ask()
      else reading.value = s === 'completed' ? { status: 'completed', data } : null
      return
    }
    if (s === 'failed' || looks >= STANCE_LOOKS) {
      fail()
      return
    }
    reading.value = { status: 'reading', data: null }
    again()
  }

  look()
}

// A square opened again throws the old reading away; the new one is read when it closes.
watch(shellStatus, (s) => {
  if (s !== 'live') return
  stopStances()
  reading.value = null
})

// The unit of the city's time, for the ledger: an hour at sixty minutes a turn.
const spanOfTurn = (minutes) => {
  const m = Number(minutes) || 60
  const key = m === 60 ? 'hour' : m === 30 ? 'halfHour' : m === 15 ? 'quarterHour' : 'turn'
  return t(`agora.units.${key}.span`, { m })
}
const countOfTurns = (n, minutes) => {
  const m = Number(minutes) || 60
  const key = m === 60 ? 'hour' : m === 30 ? 'halfHour' : m === 15 ? 'quarterHour' : 'turn'
  return t(`agora.units.${key}.count`, { n }, n)
}

// ---- What the city knows ----
const loadSimulationData = async () => {
  try {
    const simRes = await getSimulation(currentSimulationId.value)
    if (!simRes.success || !simRes.data) {
      addLog(t('agora.log.trouble', { error: readable(simRes.error, t('common.otherTongue')) || t('common.unknownError') }))
      return
    }
    const simData = simRes.data

    try {
      const configRes = await getSimulationConfig(currentSimulationId.value)
      const cfg = configRes.success ? configRes.data : null
      if (cfg?.time_config?.minutes_per_round) minutesPerRound.value = cfg.time_config.minutes_per_round
      if (cfg?.time_config?.total_simulation_hours) totalHours.value = cfg.time_config.total_simulation_hours
      if (Array.isArray(cfg?.agent_configs)) {
        // Where each citizen began, how strongly, and any later stance the
        // gathering records: the square's 'who moved' ledger reads these.
        citizens.value = cfg.agent_configs.map((a) => ({
          agent_id: a.agent_id,
          entity_name: a.entity_name,
          entity_type: a.entity_type,
          stance: a.stance,
          sentiment_bias: a.sentiment_bias,
          ...(a.stance_history ? { stance_history: a.stance_history } : {}),
          ...(a.current_stance ? { current_stance: a.current_stance } : {}),
          ...(a.final_stance ? { final_stance: a.final_stance } : {})
        }))
      }
      addLog(t('agora.log.hours', { span: spanOfTurn(minutesPerRound.value) }))
      if (citizens.value.length) addLog(t('agora.log.gathering', { n: citizens.value.length }))
    } catch (configErr) {
      addLog(t('agora.log.gatheringTrouble', { error: configErr.message }))
    }

    if (maxRounds.value) addLog(t('agora.log.planned', { count: countOfTurns(maxRounds.value, minutesPerRound.value) }))

    if (simData.project_id) {
      const projRes = await getProject(simData.project_id)
      if (projRes.success && projRes.data) {
        projectData.value = projRes.data
        projectRead.value = true
        if (projRes.data.graph_id) await loadGraph(projRes.data.graph_id)
      }
    }
  } catch (err) {
    addLog(t('agora.log.trouble', { error: err.message }))
  } finally {
    projectRead.value = true
  }
}

const loadGraph = async (graphId) => {
  // While the square is open the Web is redrawn quietly, without a loading veil.
  if (!isSimulating.value) graphLoading.value = true
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      if (!isSimulating.value) addLog(t('agora.log.webRead'))
    }
  } catch (err) {
    addLog(t('agora.log.webTrouble', { error: err.message }))
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (projectData.value?.graph_id) loadGraph(projectData.value.graph_id)
}

// ---- The Web grows while the square is open ----
let graphRefreshTimer = null

const startGraphRefresh = () => {
  if (graphRefreshTimer) return
  addLog(t('agora.log.web'))
  graphRefreshTimer = setInterval(refreshGraph, 30000)
}

const stopGraphRefresh = () => {
  if (!graphRefreshTimer) return
  clearInterval(graphRefreshTimer)
  graphRefreshTimer = null
  addLog(t('agora.log.webStill'))
  refreshGraph()
}

watch(isSimulating, (live) => {
  if (live) startGraphRefresh()
  else stopGraphRefresh()
})

onMounted(() => {
  loadSimulationData()
})

onUnmounted(() => {
  if (graphRefreshTimer) clearInterval(graphRefreshTimer)
  graphRefreshTimer = null
  stopStances()
})
</script>

<style scoped>
/* The shell's Web pane sets display: flex, which outranks the hidden
   attribute it toggles on phones; until the shell carries this rule, the
   Agora keeps the sheet closed itself. */
:deep(.web-pane[hidden]) {
  display: none !important;
}

/* On phones the act's name would run under the Web toggle; until the shell
   clips it, the Agora clips it here as the Hearing and the Gathering do. */
@media (max-width: 899px) {
  :deep(.act-subject) { overflow: hidden; }
  :deep(.act-name) { overflow: hidden; text-overflow: ellipsis; }
}
</style>
