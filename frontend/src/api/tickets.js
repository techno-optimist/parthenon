import i18n from '../i18n'
import service, { explainRefusal } from './index'
import { access } from '../parthenon/access.js'
import { TICKET_ENDS, abortableSleep, markedTicket, settleTicket, ticketBudgetMs, ticketEnd, waitForTicket } from '../parthenon/tickets.js'

/**
 * Where a question stands on the public steps (see parthenon/tickets.js).
 * @param {string} id - the ticket the question route handed back
 * @returns {Promise<{ status: 'thinking'|'done'|'failed', result?: Object, error?: string, code?: string }>}
 *   Read bare or wrapped in { success, data }; readTicket takes either.
 */
export const getTicket = (id) =>
  service.get(`/api/parthenon/ticket/${encodeURIComponent(id)}`, { timeout: 30000, parthenonTicket: true })

// The words for a wait that ended without an answer.
const END_WORDS = {
  [TICKET_ENDS.gaveUp]: 'parthenon.public.ticket.gaveUp',
  [TICKET_ENDS.lost]: 'parthenon.public.ticket.lost'
}

// A failed answer, shaped as the same refusal would have come at once (and
// marked as one that came through a ticket: the question was put, and is kept).
const refusal = (body, status) => {
  const err = new Error(String(body?.error || 'Error'))
  err.response = { status: status || 500, data: body, headers: {} }
  err.config = {}
  err.fromTicket = true
  return explainRefusal(err)
}

/**
 * Ask, and wait for the answer however it comes. At home (and whenever the
 * route answers at once) this is the route's own answer, untouched. On the
 * public steps a route that answers 202 with a ticket is waited on: the answer
 * resolves exactly as the route's own JSON; a failure rejects as the same
 * refusal would have; a wait past the budget, or a ticket the city lost,
 * rejects calmly (error.cityCode 'took_too_long' | 'answer_lost'), in the
 * city's words. Aborting the signal stops the wait ('abandoned').
 *
 * @param {Promise<Object>} request - the question's call through the API client
 * @param {{ signal?: AbortSignal }} [options]
 */
export const asked = async (request, { signal } = {}) => {
  const res = await request
  const id = markedTicket(res)
  if (!id) return res
  let outcome
  try {
    outcome = await waitForTicket(id, {
      fetchTicket: getTicket,
      sleep: abortableSleep,
      budgetMs: ticketBudgetMs(access.limits, res?.data?.budget_seconds),
      signal
    })
  } catch (err) {
    const key = END_WORDS[err?.ticketEnd]
    if (key) err.message = i18n.global.t(key)
    throw err
  }
  const settled = settleTicket(outcome)
  // The city no longer knows the ticket (a restart, or it expired): lost, calmly.
  if (settled.refusal?.body?.code === 'ticket_lost') {
    throw ticketEnd(TICKET_ENDS.lost, settled.refusal.body.error || i18n.global.t(END_WORDS[TICKET_ENDS.lost]))
  }
  if (settled.refusal) throw refusal(settled.refusal.body, settled.refusal.status)
  return settled.result
}
