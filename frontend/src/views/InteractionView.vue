<template>
  <ActShell
    :act="5"
    :reached="missing ? 0 : null"
    :status="shellStatus"
    :status-text="shellStatusText"
    :logs="systemLogs"
    :links="links"
  >
    <Step5Interaction
      :reportId="currentReportId"
      :simulationId="simulationId"
      @add-log="addLog"
      @update-status="updateStatus"
    />
  </ActShell>
</template>

<script setup>
// Act Ε΄, the Symposium: a room with couches. The view finds the gathering
// behind the Chronicle (report -> simulation -> project) so the Way can lead
// back to the earlier acts, and hands the stage to Step5Interaction.
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ActShell from '../components/ActShell.vue'
import Step5Interaction from '../components/Step5Interaction.vue'
import { getSimulation } from '../api/simulation'
import { getReport } from '../api/report'
import { readable } from '../parthenon/vocabulary.js'

const route = useRoute()
const { t } = useI18n()

defineProps({
  reportId: String
})

const currentReportId = ref(route.params.reportId)
const simulationId = ref(null)
const projectId = ref(null)
const systemLogs = ref([])
const currentStatus = ref('ready') // ready | working | error
const statusText = ref('')
// No Chronicle at this address: the header says so plainly, and the Way
// leads nowhere a missing Chronicle would claim.
const missing = ref(false)
const isMissing = (err) => err?.response?.status === 404 || /not found|不存在/i.test(String(err?.engineMessage || err?.message || err || ''))

const shellStatus = computed(() => (missing.value ? 'ready' : currentStatus.value))
const shellStatusText = computed(() => (missing.value ? t('parthenon.chronicle.notFoundStatus') : statusText.value))

// Where the Way can lead back to.
const links = computed(() => {
  const out = {}
  if (missing.value) return out
  if (projectId.value) out[1] = { name: 'Process', params: { projectId: projectId.value } }
  if (simulationId.value) {
    out[2] = { name: 'Simulation', params: { simulationId: simulationId.value } }
    out[3] = { name: 'SimulationRun', params: { simulationId: simulationId.value } }
  }
  if (currentReportId.value) out[4] = { name: 'Report', params: { reportId: currentReportId.value } }
  return out
})

const addLog = (msg) => {
  if (!msg) return
  // The Symposium and this view may both say the Chronicle is missing: once is enough.
  if (msg === t('parthenon.chronicle.notFound') && systemLogs.value.some((l) => l.message === msg)) return
  const now = new Date()
  const time = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  systemLogs.value.push({ time, message: msg })
  if (systemLogs.value.length > 200) systemLogs.value.shift()
}

const updateStatus = (status, text = '') => {
  currentStatus.value = status
  statusText.value = text
}

const loadReportData = async () => {
  missing.value = false
  const asked = currentReportId.value
  try {
    const reportRes = await getReport(asked)
    if (asked !== currentReportId.value) return
    if (reportRes.success && reportRes.data) {
      simulationId.value = reportRes.data.simulation_id || null
      if (simulationId.value) {
        try {
          const simRes = await getSimulation(simulationId.value)
          if (simRes.success && simRes.data) {
            projectId.value = simRes.data.project_id || null
          }
        } catch {
          // Without the gathering the Way leads back only to the Chronicle.
        }
      }
    } else if (isMissing(reportRes.error)) {
      missing.value = true
      addLog(t('parthenon.chronicle.notFound'))
    } else {
      addLog(t('step5.symposium.ledger.chronicleMissing', { error: readable(reportRes.error, t('common.otherTongue')) || t('common.unknownError') }))
    }
  } catch (err) {
    if (asked !== currentReportId.value) return
    if (isMissing(err)) {
      missing.value = true
      addLog(t('parthenon.chronicle.notFound'))
      return
    }
    addLog(t('step5.symposium.ledger.chronicleMissing', { error: err.message }))
  }
}

watch(() => route.params.reportId, (newId) => {
  if (newId && newId !== currentReportId.value) {
    currentReportId.value = newId
    simulationId.value = null
    projectId.value = null
    loadReportData()
  }
})

onMounted(() => {
  addLog(t('step5.symposium.ledger.opened'))
  loadReportData()
})
</script>

