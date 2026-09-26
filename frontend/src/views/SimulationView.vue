<template>
  <ActShell
    :act="2"
    :status="shellStatus"
    :lede="$t('parthenon.gathering.lede')"
    :logs="systemLogs"
    :links="links"
  >
    <template #web>
      <GraphPanel
        :graphData="graphData"
        :loading="graphLoading"
        :currentPhase="2"
        :simulation-id="currentSimulationId"
        @refresh="refreshGraph"
      />
    </template>

    <!-- A swarm already in the square: offer to watch it or stop it, never stop it silently. -->
    <div v-if="liveRun" class="live-notice" :class="{ closing: closingLive }" role="status">
      <span class="live-dot" aria-hidden="true"></span>
      <p v-if="closingLive" class="live-text">{{ $t('parthenon.gathering.live.closing') }}</p>
      <p v-else class="live-text">{{ $t('parthenon.gathering.live.text', { round: liveRun.current_round || 0, total: liveRun.total_rounds || '?' }) }}</p>
      <div v-if="!closingLive" class="live-actions">
        <button type="button" class="p-button small" @click="watchLiveRun">{{ $t('parthenon.gathering.live.watch') }}</button>
        <button type="button" class="p-button secondary small" :disabled="stoppingLive" @click="stopLiveRun">
          {{ stoppingLive ? $t('parthenon.gathering.live.stopping') : $t('parthenon.gathering.live.stop') }}
        </button>
      </div>
    </div>

    <Step2EnvSetup
      :simulationId="currentSimulationId"
      :projectData="projectData"
      :graphData="graphData"
      @go-back="handleGoBack"
      @next-step="handleNextStep"
      @add-log="addLog"
      @update-status="updateStatus"
    />
  </ActShell>
</template>

<script setup>
// Act Β΄, The Gathering: the Pnyx slope filling. This view owns the record of
// the gathering (which project, which Web) and the ledger; the stage itself is
// Step2EnvSetup.
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ActShell from '../components/ActShell.vue'
import GraphPanel from '../components/GraphPanel.vue'
import Step2EnvSetup from '../components/Step2EnvSetup.vue'
import { getProject, getGraphData } from '../api/graph'
import { getSimulation, stopSimulation, getRunStatus } from '../api/simulation'
import { RUN_LENGTHS, stripIds } from '../parthenon/vocabulary.js'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

defineProps({
  simulationId: String
})

const currentSimulationId = ref(route.params.simulationId)
const projectId = ref(null)
const projectData = ref(null)
const graphData = ref(null)
const graphLoading = ref(false)
const systemLogs = ref([])
const currentStatus = ref('processing') // processing | completed | error

// Where the Way can take the visitor back to.
const links = computed(() => (projectId.value ? { 1: { name: 'Process', params: { projectId: projectId.value } } } : {}))

const shellStatus = computed(() => {
  if (liveRun.value) return 'live'
  if (currentStatus.value === 'error') return 'error'
  if (currentStatus.value === 'completed') return 'done'
  return 'working'
})

// The ledger
const addLog = (message) => {
  const now = new Date()
  const time = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  systemLogs.value.push({ time, message })
  if (systemLogs.value.length > 120) systemLogs.value.shift()
}

const updateStatus = (status) => {
  currentStatus.value = status
}

const handleGoBack = () => {
  if (projectId.value) {
    router.push({ name: 'Process', params: { projectId: projectId.value } })
  } else {
    router.push('/')
  }
}

const handleNextStep = (params = {}) => {
  const length = RUN_LENGTHS.find((l) => l.rounds === params.maxRounds)
  addLog(t('parthenon.gathering.ledger.toAgora', {
    length: length ? t(`parthenon.gathering.length.names.${length.id}`) : t('parthenon.gathering.length.names.day'),
    rounds: params.maxRounds || '?'
  }))
  const routeParams = {
    name: 'SimulationRun',
    params: { simulationId: currentSimulationId.value }
  }
  if (params.maxRounds) routeParams.query = { maxRounds: params.maxRounds }
  router.push(routeParams)
}

// A live run is only shown here, with a choice to watch it or stop it.
const liveRun = ref(null)
const stoppingLive = ref(false)
const closingLive = ref(false)
let gone = false

const LIVE_STATES = ['starting', 'running']

const checkLiveRun = async () => {
  if (!currentSimulationId.value) return
  try {
    const res = await getRunStatus(currentSimulationId.value)
    const data = res?.success ? res.data : null
    liveRun.value = data && LIVE_STATES.includes(data.runner_status) ? data : null
    if (liveRun.value) addLog(t('parthenon.gathering.ledger.liveFound'))
  } catch (err) {
    console.warn('Could not read the run status:', err)
  }
}

const watchLiveRun = () => {
  router.push({ name: 'SimulationRun', params: { simulationId: currentSimulationId.value } })
}

// The engine answers a stop whose last writing outlives its wait with a
// pending reply that the API wrapper surfaces as a failure. Rather than
// reporting trouble for a square that is closing on its own, look again a
// few times and only then say it could not be stopped.
const CLOSING_CHECKS = 5
const CLOSING_EVERY_MS = 3000
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const waitForTheDoors = async () => {
  for (let i = 0; i < CLOSING_CHECKS; i += 1) {
    await pause(CLOSING_EVERY_MS)
    if (gone) return false
    try {
      const res = await getRunStatus(currentSimulationId.value)
      const data = res?.success ? res.data : null
      if (!data || !['starting', 'running', 'stopping'].includes(data.runner_status)) return true
    } catch {
      // look again
    }
  }
  return false
}

const stopLiveRun = async () => {
  if (!currentSimulationId.value || stoppingLive.value) return
  stoppingLive.value = true
  try {
    const res = await stopSimulation({ simulation_id: currentSimulationId.value })
    if (!res.success) throw new Error(res.error || t('common.unknownError'))
    addLog(t('parthenon.gathering.ledger.stopped'))
    liveRun.value = null
  } catch (err) {
    closingLive.value = true
    addLog(t('parthenon.gathering.ledger.stopPending'))
    const closed = await waitForTheDoors()
    closingLive.value = false
    if (gone) return
    if (closed) {
      addLog(t('parthenon.gathering.ledger.stopped'))
      liveRun.value = null
    } else {
      addLog(t('parthenon.gathering.ledger.stopFailed', { error: stripIds(err.message || t('common.unknownError')) }))
    }
  } finally {
    stoppingLive.value = false
  }
}

onUnmounted(() => {
  gone = true
})

const loadSimulationData = async () => {
  try {
    addLog(t('parthenon.gathering.ledger.readingRecord'))
    const simRes = await getSimulation(currentSimulationId.value)
    if (simRes.success && simRes.data) {
      const simData = simRes.data
      if (simData.project_id) {
        projectId.value = simData.project_id
        const projRes = await getProject(simData.project_id)
        if (projRes.success && projRes.data) {
          projectData.value = projRes.data
          addLog(t('parthenon.gathering.ledger.recordRead'))
          if (projRes.data.graph_id) await loadGraph(projRes.data.graph_id)
        }
      }
    } else {
      addLog(t('parthenon.gathering.ledger.recordMissing', { error: simRes.error || t('common.unknownError') }))
    }
  } catch (err) {
    addLog(t('parthenon.gathering.ledger.recordMissing', { error: err.message }))
  }
}

const loadGraph = async (graphId) => {
  graphLoading.value = true
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      addLog(t('parthenon.gathering.ledger.webRead', {
        nodes: res.data?.node_count ?? res.data?.nodes?.length ?? 0,
        edges: res.data?.edge_count ?? res.data?.edges?.length ?? 0
      }))
    }
  } catch (err) {
    addLog(t('parthenon.gathering.ledger.webFailed', { error: err.message }))
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (projectData.value?.graph_id) loadGraph(projectData.value.graph_id)
}

// Written during setup so it comes before the stage's own first line.
addLog(t('parthenon.gathering.ledger.opened'))

onMounted(async () => {
  await checkLiveRun()
  loadSimulationData()
})
</script>

<style scoped>
/* ActShell's .web-pane sets display:flex, which beats the UA [hidden] rule, so a
   closed Web still showed as a sheet on phones. Local guard until the shell fixes it. */
:deep(.web-pane[hidden]) {
  display: none !important;
}

.live-notice {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 16px;
  margin: 0;
  padding: 12px var(--p-gutter);
  background: var(--p-terracotta-tint);
  border-bottom: 1px solid var(--p-gold);
  color: var(--p-ink);
  min-width: 0;
}

.live-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--p-radius-coin);
  background: var(--p-gold);
  box-shadow: 0 0 0 4px var(--p-terracotta-tint);
  flex-shrink: 0;
}

.live-notice.closing .live-dot {
  background: var(--p-ink-3);
}

.live-text {
  flex: 1 1 240px;
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  min-width: 0;
}

.live-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 899px) {
  .live-notice { padding-inline: 16px; }

  /* ActShell's nowrap act title runs under the Web toggle at 390px. Local guard. */
  :deep(.act-subject) { overflow: hidden; }
  :deep(.act-name) { overflow: hidden; text-overflow: ellipsis; }
}
</style>
