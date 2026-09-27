// The public steps' limits, read from GET /api/parthenon/status (data.limits),
// as the page needs them. Pure: no Vue, no DOM.

const count = (value) => {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : null
}

/**
 * The longest run a visitor may choose, in hours. max_run is a run length's
 * id ('day'), a number of hours (24 or '24'), or nothing (no limit: Infinity).
 */
export const maxRunHours = (maxRun, lengths = []) => {
  if (maxRun === null || maxRun === undefined || maxRun === '') return Infinity
  const byId = lengths.find((l) => l && l.id === maxRun)
  if (byId) return Number(byId.hours)
  const n = Number(maxRun)
  return Number.isFinite(n) && n > 0 ? n : Infinity
}

/** The run lengths a visitor may choose; never none (the shortest stays). */
export const allowedRunLengths = (lengths = [], maxRun) => {
  const cap = maxRunHours(maxRun, lengths)
  const open = lengths.filter((l) => Number(l.hours) <= cap)
  return open.length ? open : lengths.slice(0, 1)
}

/** The chosen length if it may be chosen, else the longest that may. */
export const clampRunLength = (id, lengths = [], maxRun) => {
  const open = allowedRunLengths(lengths, maxRun)
  if (open.some((l) => l.id === id)) return id
  return open.length ? open[open.length - 1].id : id
}

/**
 * How many gatherings are left today: { city, visitor, left, closed, who }.
 * city and visitor are null when the city does not say. left is the smaller;
 * closed is true when nothing is left; who says whose limit closed it
 * ('city' | 'visitor' | '').
 */
export const gatheringsLeft = (limits) => {
  if (!limits || typeof limits !== 'object') return null
  const city = count(limits.today_left)
  const visitor = count(limits.visitor_left)
  if (city === null && visitor === null) return null
  const known = [city, visitor].filter((n) => n !== null)
  const left = Math.min(...known)
  const who = left > 0 ? '' : city === 0 ? 'city' : 'visitor'
  return { city, visitor, left, closed: left <= 0, who }
}

/** Whole minutes to wait (at least one), from a retry-after in seconds; 0 when unknown. */
export const retryMinutes = (seconds) => {
  const s = Number(seconds)
  if (!Number.isFinite(s) || s <= 0) return 0
  return Math.max(1, Math.ceil(s / 60))
}
