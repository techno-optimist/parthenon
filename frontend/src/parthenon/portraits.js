// Citizens' faces. One shared poll per gathering, however many components ask:
// the Gathering starts the painting, and every act reads the same map.
import { computed, getCurrentInstance, onBeforeUnmount, reactive, ref, unref, watch } from 'vue'
import { filmAssetUrl, getCitizenPortraits, startCitizenPortraits } from '../api/parthenon.js'

const POLL_MS = 4000
const galleries = new Map() // simulationId -> gallery

// Letters of any script count (Greek, Chinese...), so every citizen keeps their own face.
const nameKey = (name) => String(name || '').normalize('NFKD').replace(/\p{M}+/gu, '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()

const makeGallery = (simulationId) => {
  const state = reactive({ status: 'none', progress: 0, error: null, byName: {}, byId: {}, loaded: false })
  let timer = 0
  let users = 0
  let inflight = null

  const apply = (data) => {
    state.status = data?.status || 'none'
    state.progress = Number(data?.progress) || 0
    state.error = data?.error || null
    const byName = {}
    const byId = {}
    for (const p of data?.portraits || []) {
      if (p?.status !== 'done' || !p.url) continue
      const url = filmAssetUrl(p.url)
      const key = nameKey(p.name)
      if (key) byName[key] = url
      if (p.agent_id !== undefined && p.agent_id !== null) byId[String(p.agent_id)] = url
    }
    state.byName = byName
    state.byId = byId
    state.loaded = true
  }

  const refresh = async () => {
    if (inflight) return inflight
    inflight = getCitizenPortraits(simulationId)
      .then((res) => apply(res?.data))
      .catch(() => { state.loaded = true })
      .finally(() => { inflight = null })
    return inflight
  }

  const schedule = () => {
    clearTimeout(timer)
    if (!users || state.status !== 'running') return
    timer = setTimeout(async () => { await refresh(); schedule() }, POLL_MS)
  }

  // Returns 'started', 'not-ready' (the citizens are still being written) or 'failed'.
  const start = async ({ force = false } = {}) => {
    let outcome = 'started'
    try {
      const res = await startCitizenPortraits(simulationId, { force })
      if (res?.data?.status) state.status = res.data.status
    } catch (e) {
      const code = e?.response?.status || e?.status
      outcome = code === 409 ? 'not-ready' : 'failed'
      if (outcome === 'failed') state.error = e?.message || 'The painters could not start.'
    }
    await refresh()
    schedule()
    return outcome
  }

  return {
    state,
    start,
    refresh,
    acquire() { users += 1; refresh().then(schedule) },
    release() { users = Math.max(0, users - 1); if (!users) clearTimeout(timer) }
  }
}

// Painting costs the owner's subscription, so it starts on its own only when
// nothing has been painted yet, or when a restart cut a painting short. Any
// other failure waits for someone to ask again (start()). While the citizens
// are still being written the painters wait and try again, a few times.
const RESTARTED = /restart/i
const autoBegin = async (g, id, tries = 0) => {
  await g.refresh()
  const { status, error } = g.state
  const resume = status === 'failed' && RESTARTED.test(String(error || ''))
  if (status !== 'none' && !resume) return
  const outcome = await g.start()
  if (outcome === 'not-ready' && tries < 12) {
    setTimeout(() => { if (galleries.get(id) === g) autoBegin(g, id, tries + 1) }, 10000)
  }
}

/**
 * The portraits of a gathering. Pass a simulation id (or a ref to one).
 * autoStart: ask the painters to begin when nothing has been painted yet
 * (the Gathering does this; other acts only read).
 *
 * Returns { status, progress, error, portraitFor(nameOrAgentId), start(), refresh() }.
 * portraitFor returns a URL or null; always fall back to the citizen's initial.
 */
export function useCitizenPortraits(simulationIdRef, { autoStart = false } = {}) {
  const current = ref(null)

  const bind = (id) => {
    if (current.value) current.value.release()
    current.value = null
    if (!id) return
    if (!galleries.has(id)) galleries.set(id, makeGallery(id))
    const g = galleries.get(id)
    g.acquire()
    current.value = g
    if (autoStart) autoBegin(g, id)
  }

  watch(() => unref(simulationIdRef), bind, { immediate: true })

  // Release when the owning component unmounts.
  if (getCurrentInstance()) onBeforeUnmount(() => { current.value?.release(); current.value = null })

  const state = computed(() => current.value?.state || { status: 'none', progress: 0, error: null, byName: {}, byId: {} })

  const portraitFor = (nameOrId) => {
    const s = state.value
    if (nameOrId === undefined || nameOrId === null || nameOrId === '') return null
    const asId = String(nameOrId)
    if (/^\d+$/.test(asId) && s.byId[asId]) return s.byId[asId]
    return s.byName[nameKey(nameOrId)] || null
  }

  return {
    status: computed(() => state.value.status),
    progress: computed(() => state.value.progress),
    error: computed(() => state.value.error),
    portraitFor,
    start: (opts) => current.value?.start(opts),
    refresh: () => current.value?.refresh()
  }
}
