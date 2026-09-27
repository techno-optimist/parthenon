// The gatherings this browser began, and the keys that let it steer them.
//
// On the public steps anyone may watch a gathering and put questions to it,
// but only the one who began it may start, stop, film or rewrite it. The
// backend hands a key (owner_token) back when a gathering is begun; the page
// keeps { id: key } for the scroll and for every later id of the same
// gathering (its crowd, its Chronicle) in localStorage 'parthenon.owned', and
// shows the key (X-Parthenon-Owner) on every call about one of those ids. The
// shelf is told which ids this browser knows (X-Parthenon-Owned), so a
// visitor's own gatherings stand on it beside the featured ones.
//
// Pure functions over a storage and a request, so they can be tested in node.

export const OWNED_KEY = 'parthenon.owned'
export const ADMIN_KEY = 'parthenon.admin'
export const OWNER_HEADER = 'X-Parthenon-Owner'
export const OWNED_HEADER = 'X-Parthenon-Owned'
export const ADMIN_HEADER = 'X-Parthenon-Admin'

// The ids a gathering is known by: proj_…, sim_…, report_….
const ID_SOURCE = '(?:proj|sim|report)_[A-Za-z0-9]{4,64}'
const ID_EXACT = new RegExp(`^${ID_SOURCE}$`)
const ID_ANYWHERE = () => new RegExp(`(?:^|[^A-Za-z0-9_])(${ID_SOURCE})(?![A-Za-z0-9])`, 'g')
const TOKEN = /^[A-Za-z0-9_\-.~+/=]{8,256}$/
const ID_FIELDS = ['project_id', 'simulation_id', 'report_id']
// A shelf header stays short: the newest ids first, never more than these.
const MAX_LISTED = 60

export const isGatheringId = (id) => typeof id === 'string' && ID_EXACT.test(id)

/** { id: token } from what the storage held, keeping only well-formed pairs. */
export const parseOwned = (raw) => {
  let data = raw
  if (typeof raw === 'string') {
    try {
      data = JSON.parse(raw)
    } catch {
      return {}
    }
  }
  const out = {}
  if (!data || typeof data !== 'object' || Array.isArray(data)) return out
  for (const [id, token] of Object.entries(data)) {
    if (isGatheringId(id) && typeof token === 'string' && TOKEN.test(token)) out[id] = token
  }
  return out
}

export const readOwned = (storage) => {
  try {
    return parseOwned(storage?.getItem(OWNED_KEY) ?? null)
  } catch {
    return {}
  }
}

export const writeOwned = (storage, map) => {
  try {
    storage?.setItem(OWNED_KEY, JSON.stringify(parseOwned(map)))
    return true
  } catch {
    return false
  }
}

export const readAdmin = (storage) => {
  try {
    const key = String(storage?.getItem(ADMIN_KEY) || '').trim()
    return key && key.length <= 512 ? key : ''
  } catch {
    return ''
  }
}

/**
 * The map with every id given kept under the token. Returns the same map when
 * nothing changes (so a caller can skip writing), else a new one. An id kept
 * under another token keeps its first one: the key that began it.
 */
export const addOwned = (map, ids, token) => {
  if (typeof token !== 'string' || !TOKEN.test(token)) return map
  let next = map
  for (const id of ids || []) {
    if (!isGatheringId(id) || next[id]) continue
    if (next === map) next = { ...map }
    next[id] = token
  }
  return next
}

/** The first token held for any of the ids, or ''. */
export const tokenFor = (map, ids) => {
  for (const id of ids || []) {
    if (map && isGatheringId(id) && map[id]) return map[id]
  }
  return ''
}

/** The ids to list on a shelf call: the ones given first, then the ones kept, newest last kept first. */
export const listedIds = (map, extra = []) => {
  const seen = new Set()
  const out = []
  const push = (id) => {
    if (isGatheringId(id) && !seen.has(id)) {
      seen.add(id)
      out.push(id)
    }
  }
  for (const id of extra || []) push(id)
  for (const id of Object.keys(map || {}).reverse()) push(id)
  return out.slice(0, MAX_LISTED)
}

const idsIn = (text, into) => {
  if (typeof text !== 'string' || !text) return
  for (const m of text.matchAll(ID_ANYWHERE())) into.add(m[1])
}

const fieldsOf = (obj, into) => {
  if (!obj || typeof obj !== 'object') return
  for (const field of ID_FIELDS) {
    const value = typeof obj.get === 'function' && !(field in obj) ? obj.get(field) : obj[field]
    if (isGatheringId(value)) into.add(value)
  }
}

/**
 * Every gathering id a request is about: in its path, its query and its body
 * (an object, a JSON string or a FormData).
 */
export const idsInRequest = (config = {}) => {
  const found = new Set()
  const url = String(config.url || '')
  idsIn(url.split('?')[0], found)
  const query = url.includes('?') ? url.slice(url.indexOf('?') + 1) : ''
  if (query) {
    try {
      fieldsOf(new URLSearchParams(query), found)
    } catch {
      // not a query we can read
    }
  }
  fieldsOf(config.params, found)
  let data = config.data
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data)
    } catch {
      data = null
    }
  }
  if (data && typeof data === 'object' && !Array.isArray(data)) fieldsOf(data, found)
  return [...found]
}

/** The gathering ids a response names (its data object, not a list). */
export const idsInResponse = (body) => {
  const found = new Set()
  const data = body && typeof body === 'object' ? body.data : null
  if (data && typeof data === 'object' && !Array.isArray(data)) fieldsOf(data, found)
  return [...found]
}

/** A token the response hands back for a gathering just begun. */
export const tokenInResponse = (body) => {
  const candidates = [body?.owner_token, body?.data?.owner_token]
  for (const token of candidates) {
    if (typeof token === 'string' && TOKEN.test(token)) return token
  }
  return ''
}

/**
 * What a response teaches about ownership, as the next map:
 * - a gathering just begun hands back its token: every id it names is kept under it;
 * - a call made with a token (about a gathering this browser began) that names
 *   new ids (its crowd, its Chronicle) keeps them under the same token.
 */
export const learnFromResponse = (map, { sentToken = '', body } = {}) => {
  const ids = idsInResponse(body)
  const handed = tokenInResponse(body)
  let next = map
  if (handed) next = addOwned(next, ids, handed)
  if (sentToken) next = addOwned(next, ids, sentToken)
  return next
}

/** Is any of the ids one this browser began? */
export const ownsAny = (map, ids) => !!tokenFor(map, (ids || []).filter(Boolean))
