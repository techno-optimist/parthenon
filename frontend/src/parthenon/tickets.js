// Questions as tickets.
//
// On the public steps a question (to a citizen, the crowd, the Scribe, the one
// who had the floor, or the Oracle) can take longer to answer than the site's
// edge holds a request open (Cloudflare cuts at 100 s). There the city answers
// 202 at once with a ticket ({ success: true, data: { ticket, status:
// 'thinking' } }) and thinks in the background; the page asks after the
// ticket (GET /api/parthenon/ticket/<id>) every 2 s, every 5 s after the
// first 30 s, until it is done, has failed, or the question's budget is spent.
// A done ticket carries exactly the answer the route gives at home, so every
// caller reads it as it always has. At home the routes answer at once, as
// always, and none of this runs.
//
// Pure: the fetching, the waiting and the clock are handed in, so node can
// test the whole loop.

export const TICKET_STATES = ['thinking', 'done', 'failed']
export const DEFAULT_QUESTION_SECONDS = 240
// The city gives up on its own at the budget (and says so within half a
// minute of it); the page waits a little longer, so the city's own word (a
// calm refusal) arrives first.
export const TICKET_GRACE_MS = 45000
export const FAST_POLL_MS = 2000
export const SLOW_POLL_MS = 5000
export const FAST_FOR_MS = 30000
// A ticket id is unguessable (secrets.token_urlsafe).
const TICKET_ID = /^[A-Za-z0-9_-]{8,128}$/

// Answers that came back as a ticket (the API client marks them).
const marked = new WeakSet()

/** The ticket id a response hands back, or ''. Only a 202 carrying one counts. */
export const ticketOf = (status, body) => {
  if (Number(status) !== 202 || !body || typeof body !== 'object') return ''
  const data = body.data
  const id = data && typeof data === 'object' ? data.ticket : undefined
  return typeof id === 'string' && TICKET_ID.test(id) ? id : ''
}

/** Mark a response body as a ticket (called by the API client for a 202). */
export const markTicket = (body) => {
  if (body && typeof body === 'object') marked.add(body)
  return body
}

/** The ticket id of a body the API client marked, or ''. */
export const markedTicket = (body) => (body && typeof body === 'object' && marked.has(body) ? ticketOf(202, body) : '')

/**
 * A ticket's state out of what GET /api/parthenon/ticket/<id> returned, as
 * { status, result, error, code, retryAfter, httpStatus }, or null when it is not one.
 * Read bare ({ status, result, ... }) or wrapped ({ success, data: { ... } }).
 */
export const readTicket = (body) => {
  if (!body || typeof body !== 'object') return null
  const inner = TICKET_STATES.includes(body.status) ? body : body.data && typeof body.data === 'object' && TICKET_STATES.includes(body.data.status) ? body.data : null
  if (!inner) return null
  const retry = Number(inner.retry_after_seconds ?? body.retry_after_seconds)
  return {
    status: inner.status,
    result: inner.result === undefined ? null : inner.result,
    error: typeof inner.error === 'string' ? inner.error : '',
    code: typeof inner.code === 'string' ? inner.code : typeof body.code === 'string' ? body.code : '',
    retryAfter: Number.isFinite(retry) && retry > 0 ? retry : 0,
    // The status the route would have answered with at home, when the city says.
    httpStatus: Number(inner.http_status ?? inner.status_code) || 0
  }
}

/** How long to wait before the next look: 2 s at first, 5 s after the first 30 s. */
export const pollDelay = (elapsedMs) => (elapsedMs < FAST_FOR_MS ? FAST_POLL_MS : SLOW_POLL_MS)

/**
 * How long the page waits for one question: the budget the ticket was handed
 * out with (data.budget_seconds), else the city's (status limits.question_seconds),
 * else 240 s; and a grace.
 */
export const ticketBudgetMs = (limits, handedSeconds) => {
  const pick = [handedSeconds, limits?.question_seconds].map(Number).find((n) => Number.isFinite(n) && n > 0)
  return (pick || DEFAULT_QUESTION_SECONDS) * 1000 + TICKET_GRACE_MS
}

// How a wait can end without an answer. Each is an Error the callers already
// know how to read: a calm one carries cityCode (and its words are set by the
// page); a failed answer carries response.data like a refused request would.
export const TICKET_ENDS = {
  gaveUp: 'took_too_long', // the budget passed with no answer
  lost: 'answer_lost', // the city no longer knows the ticket (a restart, or it expired)
  abandoned: 'abandoned' // the page stopped waiting (the visitor left)
}

export const ticketEnd = (kind, message = '') =>
  Object.assign(new Error(message || kind), { cityCode: kind, ticketEnd: kind })

/**
 * Wait for a ticket's answer.
 *
 * @param {string} id
 * @param {{
 *   fetchTicket: (id: string) => Promise<any>,  // resolves the GET body; rejects like axios
 *   sleep?: (ms: number, signal?: AbortSignal) => Promise<void>,
 *   now?: () => number,
 *   budgetMs?: number,
 *   signal?: AbortSignal,
 *   onLook?: (state: object|null) => void
 * }} deps
 * @returns {Promise<{ done: true, result: any, state: object } | { failed: true, state: object }>}
 *   Rejects with ticketEnd('took_too_long' | 'answer_lost' | 'abandoned').
 *   A failed ticket resolves { failed, state } so the caller shapes the error.
 */
export const waitForTicket = async (id, deps = {}) => {
  const now = deps.now || (() => Date.now())
  const sleep = deps.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)))
  const budget = Number.isFinite(deps.budgetMs) ? deps.budgetMs : ticketBudgetMs(null)
  const { signal } = deps
  const started = now()
  let misses = 0
  for (;;) {
    if (signal?.aborted) throw ticketEnd(TICKET_ENDS.abandoned)
    const elapsed = now() - started
    if (elapsed >= budget) throw ticketEnd(TICKET_ENDS.gaveUp)
    await sleep(Math.min(pollDelay(elapsed), Math.max(0, budget - elapsed)), signal)
    if (signal?.aborted) throw ticketEnd(TICKET_ENDS.abandoned)
    let state = null
    try {
      state = readTicket(await deps.fetchTicket(id))
      misses = 0
    } catch (err) {
      // A failed ticket may come back as a refusal that still carries its state.
      state = readTicket(err?.response?.data)
      if (!state) {
        // The city no longer knows this ticket: it was lost (a restart) or expired.
        const status = err?.response?.status
        if (status === 404 || status === 410) {
          misses += 1
          if (misses >= 2) throw ticketEnd(TICKET_ENDS.lost)
        }
        // Anything else (the edge hiccuped, the network dropped): look again.
      }
    }
    if (deps.onLook) deps.onLook(state)
    if (!state || state.status === 'thinking') continue
    if (state.status === 'done') return { done: true, result: state.result, state }
    return { failed: true, state }
  }
}

/**
 * What a finished wait amounts to: the route's own answer ({ result }), or a
 * refusal to raise as the same call would have been refused at once
 * ({ refusal: { body, status } }, body shaped { success: false, error, code, ... }).
 * A done ticket whose answer is itself a refusal ({ success: false }) is read
 * as that refusal; a failed ticket's error, code and wait are laid over
 * whatever it carried.
 */
export const settleTicket = (outcome) => {
  if (outcome?.done) {
    const result = outcome.result
    if (result && typeof result === 'object' && result.success === false) {
      return { refusal: { body: result, status: outcome.state?.httpStatus || 500 } }
    }
    return { result }
  }
  const state = outcome?.state || {}
  const body = { ...(state.result && typeof state.result === 'object' ? state.result : {}), success: false }
  if (state.error) body.error = state.error
  if (state.code) body.code = state.code
  if (state.retryAfter) body.retry_after_seconds = state.retryAfter
  return { refusal: { body, status: state.httpStatus || 503 } }
}

/** A sleep that ends early when the signal aborts. */
export const abortableSleep = (ms, signal) =>
  new Promise((resolve) => {
    if (signal?.aborted) return resolve()
    const timer = setTimeout(done, ms)
    function done() {
      clearTimeout(timer)
      signal?.removeEventListener?.('abort', done)
      resolve()
    }
    signal?.addEventListener?.('abort', done, { once: true })
  })
