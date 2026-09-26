<template>
  <ActShell :act="3" :status="shellStatus" :logs="systemLogs" :links="links" :lede="$t('agora.lede')">
    <template #web>
      <GraphPanel
        :graphData="graphData"
        :loading="graphLoading"
        :currentPhase="3"
        :isSimulating="isSimulating"
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
      @add-log="addLog"
      @update-status="updateStatus"
      @finished="onFinished"
    />
  </ActShell>
</template>

<script setup>
// Act Γ΄, the Agora, on the shell: the Web of Athens beside the square, the
// scribe's ledger below it, the Way at the foot. The stage decides for itself
// whether to watch, read back or wait; this view feeds it what the city knows.
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ActShell from '../components/ActShell.vue'
import GraphPanel from '../components/GraphPanel.vue'
import Step3Simulation from '../components/Step3Simulation.vue'
import { getProject, getGraphData } from '../api/graph'
import { getSimulation, getSimulationConfig, getSimulationHistory } from '../api/simulation'
import { getReport } from '../api/report'
import service from '../api/index'
import { stripIds } from '../parthenon/vocabulary.js'

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

const isSimulating = computed(() => shellStatus.value === 'live')

// Stations that can be revisited from the Way
const links = computed(() => ({
  1: projectData.value?.project_id ? { name: 'Process', params: { projectId: projectData.value.project_id } } : null,
  2: { name: 'Simulation', params: { simulationId: currentSimulationId.value } }
}))

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
    const res = await getSimulationHistory(50)
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
    const res = await service.get(`/api/report/by-simulation/${id}`)
    if (res?.success && res.data?.report_id) return { id: res.data.report_id, status: res.data.status || '', trouble: res.data.error || '' }
  } catch (err) {
    // No Chronicle of this run anywhere: the stage offers to write one.
  }
  return null
}

const onFinished = async (how, { fresh } = {}) => {
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
  reportTrouble.value = stripIds(found.trouble)
  if (found.status === 'failed') addLog(t('agora.log.scribeFailed'))
}

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
      addLog(t('agora.log.trouble', { error: simRes.error || t('common.unknownError') }))
      return
    }
    const simData = simRes.data

    try {
      const configRes = await getSimulationConfig(currentSimulationId.value)
      const cfg = configRes.success ? configRes.data : null
      if (cfg?.time_config?.minutes_per_round) minutesPerRound.value = cfg.time_config.minutes_per_round
      if (cfg?.time_config?.total_simulation_hours) totalHours.value = cfg.time_config.total_simulation_hours
      if (Array.isArray(cfg?.agent_configs)) {
        citizens.value = cfg.agent_configs.map((a) => ({
          agent_id: a.agent_id,
          entity_name: a.entity_name,
          entity_type: a.entity_type,
          stance: a.stance
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
        if (projRes.data.graph_id) await loadGraph(projRes.data.graph_id)
      }
    }
  } catch (err) {
    addLog(t('agora.log.trouble', { error: err.message }))
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
