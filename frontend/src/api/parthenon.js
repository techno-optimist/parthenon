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
