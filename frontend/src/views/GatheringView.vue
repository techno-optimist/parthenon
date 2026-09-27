<template>
  <div class="gathering-link" :class="`is-${state}`" :style="sceneStyle">
    <div class="gl-scene" aria-hidden="true"></div>
    <div class="gl-shade" aria-hidden="true"></div>

    <header class="gl-bar">
      <router-link to="/" class="gl-brand" :aria-label="$t('parthenon.navHome')"><ParthenonBrand /></router-link>
      <router-link :to="{ name: 'Chronicles' }" class="gl-bar-link">{{ $t('history.title') }}</router-link>
    </header>

    <main class="gl-stage">
      <!-- A beat of night with the act's numeral while the shelf is searched -->
      <div v-if="state === 'finding'" class="gl-finding" role="status" aria-live="polite">
        <h1 class="visually-hidden">{{ $t('parthenon.permalink.finding') }}</h1>
        <span class="gl-numeral" aria-hidden="true">{{ numeral }}</span>
        <p v-if="actName" class="gl-act" aria-hidden="true">{{ actName }}</p>
        <p class="gl-line">{{ $t('parthenon.permalink.finding') }}</p>
      </div>

      <!-- Not on the shelf, or the city did not answer -->
      <section v-else class="gl-lost" :aria-labelledby="titleId">
        <svg class="gl-tablet" viewBox="0 0 64 80" aria-hidden="true">
          <rect x="6" y="4" width="52" height="72" fill="none" stroke="currentColor" stroke-width="1.4" />
          <path d="M12 14h40M12 22h32M12 30h36M12 38h22" stroke="currentColor" stroke-width="1" opacity=".5" />
          <path d="M36 4 30 24l8 10-9 16 6 12-3 14" fill="none" stroke="currentColor" stroke-width="1.4" />
        </svg>
        <p class="p-eyebrow">{{ $t('history.title') }}</p>
        <h1 :id="titleId" ref="titleEl" class="gl-title" tabindex="-1">
          {{ state === 'missing' ? $t('parthenon.permalink.missingTitle') : $t('parthenon.permalink.quietTitle') }}
        </h1>
        <p class="gl-lede">
          {{ state === 'missing' ? $t('parthenon.permalink.missingLede') : $t('parthenon.permalink.quietLede') }}
        </p>
        <div class="gl-actions">
          <router-link class="p-button" :to="{ name: 'Chronicles' }">{{ $t('parthenon.permalink.toChronicles') }}</router-link>
          <button v-if="state === 'unreachable'" type="button" class="p-button secondary" @click="find">
            {{ $t('parthenon.permalink.retry') }}
          </button>
          <router-link v-else class="p-button secondary" to="/">{{ $t('parthenon.permalink.home') }}</router-link>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
// A gathering's permanent link: /gathering/<project, gathering or Chronicle id>
// finds where the gathering stands and steps aside for that act. With a
// station (/gathering/<id>/agora) it opens that act instead. The city's own
// lookup answers first; until the backend knows it, or when it cannot say,
// the shelf and each act's record answer instead.
import { computed, nextTick, ref, useId, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ParthenonBrand from '../components/ParthenonBrand.vue'
import { resolveGathering } from '../api/parthenon'
import { getSimulation, getSimulationHistory } from '../api/simulation'
import { getReport } from '../api/report'
import { getProject } from '../api/graph'
import { ACTS } from '../parthenon/vocabulary.js'

const props = defineProps({
  id: { type: String, required: true },
  station: { type: String, default: '' }
})

const router = useRouter()
const { tm } = useI18n()
const titleId = `gathering-${useId()}`
const titleEl = ref(null)

const state = ref('finding') // finding | missing | unreachable
const act = ref(0)

// Stations by name, in the city's words and the Chronicles' filmstrip words.
const STATIONS = {
  hearing: 'hearing', scroll: 'hearing',
  gathering: 'gathering', crowd: 'gathering',
  agora: 'agora', argument: 'agora',
  chronicle: 'chronicle',
  film: 'film',
  symposium: 'symposium'
}
const ACT_OF = { hearing: 1, gathering: 2, agora: 3, chronicle: 4, film: 4, symposium: 5 }
const stationKey = computed(() => STATIONS[String(props.station || '').toLowerCase()] || '')

// Before the answer, the numeral is a good guess from the link itself.
const guessAct = (id) => {
  if (stationKey.value) return ACT_OF[stationKey.value]
  if (/^report_/.test(id)) return 4
  if (/^sim_/.test(id)) return 2
  return 1
}
const shownAct = computed(() => act.value || guessAct(props.id))
const actInfo = computed(() => ACTS[Math.min(5, Math.max(1, shownAct.value)) - 1])
const numeral = computed(() => actInfo.value.numeral)
const actName = computed(() => {
  const names = tm('main.stepNames')
  return Array.isArray(names) ? names[actInfo.value.n - 1] || '' : ''
})
const sceneStyle = computed(() => ({ '--scene': `url(${actInfo.value.scene})` }))

// ---- Where a gathering stands, from the shelf ----
// The same reading as the city's own lookup: a Chronicle (unless it failed)
// is act 4, any run at all is act 3, a gathering never run is act 2.
const RAN = ['running', 'stopping', 'paused', 'stopped', 'completed']
const actOfRecord = (p) => {
  const report = String(p.report_status || '').toLowerCase()
  if (p.report_id && report !== 'failed') return 4
  const runner = String(p.runner_status || '').toLowerCase()
  const ran = (runner && runner !== 'idle') || Number(p.current_round) > 0 || RAN.includes(String(p.status || '').toLowerCase())
  if (ran || p.report_id) return 3
  return p.simulation_id ? 2 : 1
}

const standing = (p, actNo) => ({
  project_id: p.project_id || null,
  simulation_id: p.simulation_id || null,
  report_id: p.report_id || null,
  act: actNo,
  runner_status: p.runner_status || null,
  report_status: p.report_status || null
})

// Each lookup notes whether the city answered at all, so a closed door and a
// missing gathering read differently.
let answered = false
const ask = async (call) => {
  try {
    const res = await call()
    answered = true
    return res
  } catch (error) {
    if (error?.response) answered = true
    return null
  }
}

const fromShelf = async (id) => {
  const shelf = await ask(() => getSimulationHistory(500, { ids: [id] }))
  const list = Array.isArray(shelf?.data) ? shelf.data : []
  const matches = list.filter((p) => p.simulation_id === id || p.report_id === id || p.project_id === id)
  if (matches.length) {
    // A project stands where its furthest night stands: the highest act, then
    // the newest, as the city's own lookup chooses. A Chronicle already
    // written is never hidden behind a later night prepared and then left.
    const ranked = matches.map((p) => ({ p, act: actOfRecord(p) }))
    ranked.sort((a, b) =>
      b.act - a.act ||
      String(b.p.created_at || '').localeCompare(String(a.p.created_at || '')) ||
      String(b.p.simulation_id || '').localeCompare(String(a.p.simulation_id || ''))
    )
    return standing(ranked[0].p, ranked[0].act)
  }
  // Older than the shelf's pages: ask the act's own record.
  if (/^report_/.test(id)) {
    const report = await ask(() => getReport(id))
    if (!report?.data) return null
    const simId = report.data.simulation_id || null
    const sim = simId ? await ask(() => getSimulation(simId)) : null
    return standing({ report_id: id, simulation_id: simId, project_id: sim?.data?.project_id }, 4)
  }
  if (/^sim_/.test(id)) {
    const sim = await ask(() => getSimulation(id))
    if (!sim?.data) return null
    return standing({ simulation_id: id, project_id: sim.data.project_id }, 2)
  }
  if (/^proj_/.test(id)) {
    const project = await ask(() => getProject(id))
    if (!project?.data) return null
    return standing({ project_id: id }, 1)
  }
  return null
}

const lookUp = async (id) => {
  answered = false
  try {
    const res = await resolveGathering(id)
    answered = true
    if (res?.data && (res.data.project_id || res.data.simulation_id || res.data.report_id)) return res.data
  } catch (error) {
    // The city's own lookup said plainly that nothing matches.
    if (error?.response?.status === 404 && error.response.data?.success === false) {
      answered = true
      return null
    }
    // Otherwise it may not know the question yet: the shelf answers instead.
  }
  return fromShelf(id)
}

// ---- The act to open ----
const targetFor = (g) => {
  const p = g.project_id
  const s = g.simulation_id
  const r = g.report_id
  const routes = {
    hearing: p && { name: 'Process', params: { projectId: p } },
    gathering: s && { name: 'Simulation', params: { simulationId: s } },
    agora: s && { name: 'SimulationRun', params: { simulationId: s } },
    chronicle: r && { name: 'Report', params: { reportId: r } },
    film: r && { name: 'Report', params: { reportId: r }, hash: '#film' },
    symposium: r && { name: 'Interaction', params: { reportId: r } }
  }
  if (stationKey.value && routes[stationKey.value]) return routes[stationKey.value]
  // The furthest act reached. A finished gathering opens on its Chronicle,
  // the record of what Athens came to believe; the Symposium is one step on.
  const reached = Number(g.act) || 1
  const order =
    reached >= 4 ? ['chronicle', 'agora', 'gathering', 'hearing']
      : reached === 3 ? ['agora', 'gathering', 'hearing']
        : reached === 2 ? ['gathering', 'hearing']
          : ['hearing', 'gathering']
  for (const key of order) if (routes[key]) return routes[key]
  return null
}

let token = 0
const find = async () => {
  const mine = ++token
  state.value = 'finding'
  act.value = 0
  const id = String(props.id || '').trim()
  if (!/^[A-Za-z0-9_-]{3,80}$/.test(id)) {
    state.value = 'missing'
    return
  }
  const found = await lookUp(id)
  if (mine !== token) return
  const target = found ? targetFor(found) : null
  if (target) {
    act.value = stationKey.value ? ACT_OF[stationKey.value] : Math.min(5, Math.max(1, Number(found.act) || 1))
    router.replace(target)
    return
  }
  state.value = answered ? 'missing' : 'unreachable'
  await nextTick()
  titleEl.value?.focus()
}

watch(() => [props.id, props.station], find, { immediate: true })
</script>

<style scoped>
.gathering-link {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--p-bg);
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
  isolation: isolate;
}

/* The act's scene, barely there: a lamp seen through the dark */
.gl-scene {
  position: absolute;
  inset: -4%;
  z-index: -2;
  background-image: var(--scene);
  background-size: cover;
  background-position: center 45%;
  opacity: 0.2;
  filter: saturate(0.7) blur(1px);
  animation: drift 14s ease-out forwards;
}

.gl-shade {
  position: absolute;
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(ellipse 60% 55% at 50% 48%, rgba(11, 14, 19, 0.2), rgba(11, 14, 19, 0.92) 78%),
    linear-gradient(180deg, rgba(11, 14, 19, 0.6), rgba(11, 14, 19, 0.2) 40%, rgba(11, 14, 19, 0.95));
}

.is-missing .gl-scene,
.is-unreachable .gl-scene {
  opacity: 0.12;
}

@keyframes drift {
  from { transform: scale(1.06); }
  to { transform: scale(1); }
}

.gl-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: var(--p-header-h);
  padding: 0 var(--p-gutter);
}

.gl-brand {
  display: inline-flex;
  align-items: center;
  min-width: 40px;
  min-height: 40px;
  text-decoration: none;
  color: inherit;
}

.gl-bar-link {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink);
  text-decoration: none;
}

.gl-bar-link:hover {
  color: var(--p-gold);
}

.gl-stage {
  flex: 1;
  display: grid;
  place-items: center;
  padding: 24px 16px calc(var(--p-header-h) + 24px);
}

.gl-finding {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
}

.gl-numeral {
  font-family: var(--p-font-inscription);
  font-size: clamp(72px, 13vw, 148px);
  line-height: 1;
  letter-spacing: -0.1em;
  color: var(--p-gold);
  text-shadow: 0 0 42px rgba(240, 182, 96, 0.35);
  animation: breathe 2.4s ease-in-out infinite;
}

.gl-act {
  margin: 6px 0 0;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.05;
  color: var(--p-ink);
}

.gl-line {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

@keyframes breathe {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}

.gl-lost {
  width: min(560px, 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.gl-tablet {
  width: 52px;
  height: 66px;
  margin-bottom: 22px;
  color: var(--p-gold);
  opacity: 0.8;
}

.gl-lost .p-eyebrow {
  margin: 0 0 12px;
}

.gl-title {
  margin: 0 0 14px;
  font-family: var(--p-font-display);
  font-size: var(--t-3xl);
  font-weight: 500;
  line-height: 1.04;
  color: var(--p-ink);
  text-wrap: balance;
}

.gl-title:focus {
  outline: none;
}

.gl-lede {
  margin: 0 0 28px;
  max-width: 44ch;
  font-family: var(--p-font-serif);
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.gl-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}

.gl-actions .p-button {
  min-width: 200px;
}

.visually-hidden {
  position: absolute !important;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 640px) {
  .gl-bar {
    padding-inline: 16px;
  }

  .gl-bar :deep(.p-brand-word) {
    display: none;
  }

  .gl-actions {
    flex-direction: column;
    width: 100%;
  }

  .gl-actions .p-button {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .gl-scene,
  .gl-numeral {
    animation: none;
  }

  .gl-numeral {
    opacity: 1;
  }
}
</style>
