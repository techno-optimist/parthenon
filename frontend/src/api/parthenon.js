import service from './index'

/**
 * Parts the Oracle can draft, in the order it drafts them.
 */
export const STAGE_PARTS = ['words', 'audience', 'question', 'title', 'happensNext']

/**
 * Ask the Oracle to draft the missing parts of a custom stage.
 *
 * @param {Object} stage - {
 *   title, format: 'speech'|'dialogue'|'panel'|'trial'|'assembly',
 *   era: 'ancient'|'now'|'future'|'custom', setting, topic,
 *   speakers: [{ name, role, ideas, voice, words }],
 *   audience: [{ name, description }], question, happensNext
 * }
 * @param {string[]} [fill] - parts to draft (see STAGE_PARTS); omit to draft
 *   every part that is still empty. Speakers who already have words are
 *   never redrafted.
 * @returns {Promise<{ success: true, data: {
 *   title: string|null,
 *   speakers: Array<{ name: string, words: string }>,
 *   audience: Array<{ name: string, description: string }>,
 *   question: string|null,
 *   happensNext: string|null,
 *   filled: string[]
 * } }>} Rejects with the backend's safe error message on failure.
 */
export const draftStage = (stage, fill) => {
  return service.post('/api/parthenon/stage/draft', { stage, fill })
}

/**
 * What this instance can run right now (no secrets).
 *
 * @returns {Promise<{ success: true, data: {
 *   zepConfigured: boolean, llmConfigured: boolean, upstream: string, model: string
 * } }>}
 */
export const getInstanceStatus = () => {
  return service.get('/api/parthenon/status')
}

/**
 * Narrator voices for a Chronicle film, in the order the picker shows them.
 */
export const FILM_VOICES = ['rex', 'eve', 'ara']

/**
 * Ask Grok to film a finished Chronicle: a screenplay, a painted and
 * animated shot per scene, and a narrator. Runs in the background.
 *
 * @param {string} reportId
 * @param {{ voice?: 'rex'|'eve'|'ara', shots?: number }} [options] - shots is 4..8;
 *   omit either to let the backend choose.
 * @returns {Promise<{ success: true, data: { status: 'running', report_id: string } }>}
 *   Rejects (409) when the Chronicle is not complete or a film is already running.
 */
export const startChronicleFilm = (reportId, options = {}) => {
  const body = {}
  if (options.voice) body.voice = options.voice
  if (Number.isInteger(options.shots)) body.shots = options.shots
  return service.post(`/api/parthenon/chronicle/${encodeURIComponent(reportId)}/film`, body)
}

/**
 * Where the Chronicle's film is: not started, running, completed or failed.
 *
 * @param {string} reportId
 * @returns {Promise<{ success: true, data: {
 *   status: 'none'|'running'|'completed'|'failed', stage: string|null,
 *   progress: number, message: string|null, title: string|null,
 *   logline: string|null, voice: string|null, duration: number|null,
 *   error: string|null,
 *   shots: Array<{ index: number, narration: string, status: string, thumb_url: string|null }>,
 *   video_url: string|null, poster_url: string|null, captions_url: string|null
 * } }>} Asset urls are backend-relative; pass them through filmAssetUrl.
 */
export const getChronicleFilm = (reportId) => {
  // A status read is quick; a short timeout keeps polling from stalling.
  return service.get(`/api/parthenon/chronicle/${encodeURIComponent(reportId)}/film`, { timeout: 30000 })
}

/**
 * Turn a backend-relative asset path (e.g. /api/parthenon/chronicle/<id>/film/film.mp4)
 * into a URL the page can load, using the same base URL as the API client.
 *
 * @param {string|null|undefined} path
 * @returns {string} '' when there is no path.
 */
export const filmAssetUrl = (path) => {
  if (!path || typeof path !== 'string') return ''
  if (/^https?:\/\//i.test(path)) return path
  const base = String(service.defaults.baseURL || '').replace(/\/+$/, '')
  return `${base}${path.startsWith('/') ? '' : '/'}${path}`
}

/**
 * Paint a portrait for every citizen of a gathering. Runs in the background;
 * a gathering already painted (or painting) is left as it is unless force.
 *
 * @param {string} simulationId
 * @param {{ force?: boolean }} [options]
 * @returns {Promise<{ success: true, data: { status: 'running'|'completed', simulation_id: string } }>}
 */
export const startCitizenPortraits = (simulationId, options = {}) => {
  const body = options.force ? { force: true } : {}
  return service.post(`/api/parthenon/gathering/${encodeURIComponent(simulationId)}/portraits`, body, { timeout: 30000 })
}

/**
 * The portraits of a gathering's citizens, as far as they are painted.
 *
 * @param {string} simulationId
 * @returns {Promise<{ success: true, data: {
 *   status: 'none'|'running'|'completed'|'failed', progress: number, error: string|null,
 *   portraits: Array<{ agent_id: number, name: string, entity_type: string|null,
 *     status: 'pending'|'painting'|'done'|'failed', url: string|null }>
 * } }>} urls are backend-relative; pass them through filmAssetUrl.
 */
export const getCitizenPortraits = (simulationId) => {
  return service.get(`/api/parthenon/gathering/${encodeURIComponent(simulationId)}/portraits`, { timeout: 30000 })
}

/**
 * Where a gathering stands, from any of its ids (project, simulation or report):
 * the furthest act reached and the ids of each act, for /gathering/:id links.
 *
 * @param {string} id - proj_…, sim_… or report_…
 * @returns {Promise<{ success: true, data: {
 *   project_id: string|null, simulation_id: string|null, report_id: string|null,
 *   act: 1|2|3|4|5, runner_status: string|null, report_status: string|null
 * } }>} 404 when nothing matches.
 */
export const resolveGathering = (id) => {
  return service.get(`/api/parthenon/gathering/${encodeURIComponent(id)}`, { timeout: 30000 })
}

/**
 * Speak an answer in the speaker's voice. A long answer comes in parts: play
 * part 0 and ask for the next while it plays.
 *
 * @param {{ text: string, voice?: 'scribe'|'elder'|'official'|'common'|'machine'|'plain',
 *   simulation_id?: string, agent_id?: number|string, name?: string, lang?: string, part?: number }} body
 * @returns {Promise<{ success: true, data: { url: string, voice: string, voice_id: string,
 *   language: string, part: number, parts: number, cached: boolean, truncated: boolean } }>}
 *   url is backend-relative (filmAssetUrl). Rejects 503 when no voice service is
 *   available; fall back to the browser's own voice then.
 */
export const speakWords = (body) => {
  return service.post('/api/parthenon/voice', body, { timeout: 60000 })
}

/**
 * Ask the Scribe to read where each citizen stood, period by period, after a run.
 *
 * @param {string} simulationId
 * @param {{ force?: boolean }} [options]
 * @returns {Promise<{ success: true, data: { status: 'reading'|'completed', simulation_id: string } }>}
 *   Rejects 409 when nobody has spoken yet.
 */
export const startCitizenStances = (simulationId, options = {}) => {
  const body = options.force ? { force: true } : {}
  return service.post(`/api/parthenon/gathering/${encodeURIComponent(simulationId)}/stances`, body, { timeout: 30000 })
}

/**
 * Where the citizens stood, and who moved.
 *
 * @param {string} simulationId
 * @returns {Promise<{ success: true, data: {
 *   status: 'none'|'reading'|'completed'|'failed', error: string|null, stale: boolean,
 *   through_round: number, minutes_per_round: number,
 *   periods: Array<{ period: number, from_round: number, to_round: number }>,
 *   citizens: Array<{ agent_id: number, name: string, entity_type: string|null,
 *     stance: string, spoke: boolean, final_stance: string, moved: boolean, turn: number|null,
 *     stance_history: Array<{ period: number, from_round: number, to_round: number, stance: string }> }>
 * } }>}
 */
export const getCitizenStances = (simulationId) => {
  return service.get(`/api/parthenon/gathering/${encodeURIComponent(simulationId)}/stances`, { timeout: 30000 })
}
