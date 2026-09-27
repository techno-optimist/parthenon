// Run: cd frontend && node --test src/parthenon/tickets.test.mjs
//
// Questions as tickets: a 202 hands back a ticket; the page looks every 2 s,
// every 5 s after the first 30 s, until the answer is done, has failed, or the
// budget is spent; a done ticket is the route's own answer, byte for byte.
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  DEFAULT_QUESTION_SECONDS,
  TICKET_ENDS,
  TICKET_GRACE_MS,
  abortableSleep,
  markTicket,
  markedTicket,
  pollDelay,
  readTicket,
  settleTicket,
  ticketBudgetMs,
  ticketOf,
  waitForTicket
} from './tickets.js'

const ID = 'Zq3xY_abcdefghijklmnopqrstuvwxyz0123456789'

test('only a 202 that carries a ticket is one', () => {
  const body = { success: true, data: { ticket: ID, status: 'thinking' } }
  assert.equal(ticketOf(202, body), ID)
  assert.equal(ticketOf('202', body), ID)
  assert.equal(ticketOf(200, body), '', 'at home the route answers 200 with its answer')
  assert.equal(ticketOf(202, { success: true, data: { status: 'thinking' } }), '')
  assert.equal(ticketOf(202, { success: true, data: { ticket: 'no' } }), '', 'a ticket id is long and unguessable')
  assert.equal(ticketOf(202, { success: true, data: { ticket: '../../etc' } }), '')
  assert.equal(ticketOf(202, null), '')
  // The answers of the question routes at home never look like one.
  assert.equal(ticketOf(200, { success: true, data: { response: 'The city believes...' } }), '')
})

test('the API client marks a ticket; any other answer is left unmarked', () => {
  const ticket = markTicket({ success: true, data: { ticket: ID, status: 'thinking' } })
  assert.equal(markedTicket(ticket), ID)
  assert.equal(markedTicket({ success: true, data: { ticket: ID, status: 'thinking' } }), '', 'the shape alone is not a mark')
  assert.equal(markedTicket(null), '')
  assert.equal(markTicket(null), null)
})

test('a ticket reads bare or wrapped', () => {
  const result = { success: true, data: { response: 'hi' } }
  assert.deepEqual(readTicket({ status: 'done', result }), { status: 'done', result, error: '', code: '', retryAfter: 0, httpStatus: 0 })
  assert.deepEqual(readTicket({ success: true, data: { status: 'thinking' } }), { status: 'thinking', result: null, error: '', code: '', retryAfter: 0, httpStatus: 0 })
  assert.deepEqual(
    readTicket({ status: 'failed', error: 'The city needs a moment.', code: 'slow_down', retry_after_seconds: 60, http_status: 503 }),
    { status: 'failed', result: null, error: 'The city needs a moment.', code: 'slow_down', retryAfter: 60, httpStatus: 503 }
  )
  assert.equal(readTicket({ status: 'pending' }), null)
  assert.equal(readTicket({ success: false, error: 'Not found' }), null)
  assert.equal(readTicket('done'), null)
  assert.equal(readTicket(null), null)
})

test('the page looks every 2 s, then every 5 s after the first 30 s', () => {
  assert.equal(pollDelay(0), 2000)
  assert.equal(pollDelay(29999), 2000)
  assert.equal(pollDelay(30000), 5000)
  assert.equal(pollDelay(200000), 5000)
})

test('the budget is the city\'s (240 s unless it says) and a grace', () => {
  assert.equal(DEFAULT_QUESTION_SECONDS, 240)
  assert.equal(ticketBudgetMs(null), 240000 + TICKET_GRACE_MS)
  assert.equal(ticketBudgetMs({ question_seconds: 120 }), 120000 + TICKET_GRACE_MS)
  assert.equal(ticketBudgetMs({ question_seconds: 'x' }), 240000 + TICKET_GRACE_MS)
  assert.equal(ticketBudgetMs({ question_seconds: -5 }), 240000 + TICKET_GRACE_MS)
  // The budget the ticket was handed out with comes first.
  assert.equal(ticketBudgetMs({ question_seconds: 120 }, 300), 300000 + TICKET_GRACE_MS)
  assert.equal(ticketBudgetMs(null, '90'), 90000 + TICKET_GRACE_MS)
  assert.equal(ticketBudgetMs({ question_seconds: 120 }, 0), 120000 + TICKET_GRACE_MS)
  // The city says it ran out of time within 30 s of its budget; the page waits past that.
  assert.ok(TICKET_GRACE_MS > 30000)
})

// A clock that only moves when the waiter sleeps.
const fakeTime = () => {
  let t = 1000
  const sleeps = []
  return {
    now: () => t,
    sleep: async (ms) => {
      sleeps.push(ms)
      t += ms
    },
    sleeps,
    elapsed: () => t - 1000
  }
}

test('a ticket thought over is waited for, and its answer is the route\'s own', async () => {
  const clock = fakeTime()
  const answer = { success: true, data: { success: true, result: { results: { reddit_0: { response: 'Yes.' } } } } }
  let looks = 0
  const fetchTicket = async (id) => {
    assert.equal(id, ID)
    looks += 1
    return looks < 20 ? { success: true, data: { ticket: ID, status: 'thinking' } } : { status: 'done', result: answer }
  }
  const out = await waitForTicket(ID, { fetchTicket, now: clock.now, sleep: clock.sleep, budgetMs: 260000 })
  assert.equal(out.done, true)
  assert.equal(out.result, answer, 'the very object the city sent')
  assert.equal(looks, 20)
  // Fifteen looks 2 s apart fill the first 30 s; the rest are 5 s apart.
  assert.deepEqual(clock.sleeps.slice(0, 15), Array(15).fill(2000))
  assert.deepEqual(clock.sleeps.slice(15), Array(5).fill(5000))
  assert.deepEqual(settleTicket(out), { result: answer })
})

test('the wait ends calmly when the budget passes with no answer', async () => {
  const clock = fakeTime()
  const fetchTicket = async () => ({ status: 'thinking' })
  await assert.rejects(
    waitForTicket(ID, { fetchTicket, now: clock.now, sleep: clock.sleep, budgetMs: 60000 }),
    (err) => err.ticketEnd === TICKET_ENDS.gaveUp && err.cityCode === 'took_too_long'
  )
  assert.equal(clock.elapsed(), 60000, 'the last sleep is cut to the budget, never past it')
})

test('a failed ticket comes back with its state; the edge hiccuping is looked past', async () => {
  const clock = fakeTime()
  const seen = []
  const replies = [
    () => { throw Object.assign(new Error('Bad Gateway'), { response: { status: 502, data: '<html>' } }) },
    () => { throw new Error('Network Error') },
    () => ({ status: 'thinking' }),
    () => { throw Object.assign(new Error('x'), { response: { status: 500, data: { status: 'failed', error: 'The Scribe lost the thread.', code: '' } } }) }
  ]
  let i = 0
  const out = await waitForTicket(ID, { fetchTicket: async () => replies[i++](), now: clock.now, sleep: clock.sleep, onLook: (s) => seen.push(s && s.status), budgetMs: 260000 })
  assert.equal(out.failed, true)
  assert.equal(out.state.error, 'The Scribe lost the thread.')
  assert.deepEqual(seen, [null, null, 'thinking', 'failed'])
})

test('a ticket the city no longer knows (a restart, or expired) is lost, calmly', async () => {
  const clock = fakeTime()
  const gone = Object.assign(new Error('Not found'), { response: { status: 404, data: { success: false, error: 'Not found' } } })
  let looks = 0
  await assert.rejects(
    waitForTicket(ID, { fetchTicket: async () => { looks += 1; throw gone }, now: clock.now, sleep: clock.sleep, budgetMs: 260000 }),
    (err) => err.ticketEnd === TICKET_ENDS.lost && err.cityCode === 'answer_lost'
  )
  assert.equal(looks, 2, 'one 404 may be a hiccup; two in a row is a lost ticket')
})

test('the city\'s own word for a lost ticket (404 ticket_lost, with its state) ends the wait at once', async () => {
  const clock = fakeTime()
  const lost = Object.assign(new Error('x'), {
    response: { status: 404, data: { success: false, status: 'failed', result: null, code: 'ticket_lost', error: 'The answer was lost when the city restarted.' } }
  })
  let looks = 0
  const out = await waitForTicket(ID, { fetchTicket: async () => { looks += 1; throw lost }, now: clock.now, sleep: clock.sleep, budgetMs: 260000 })
  assert.equal(looks, 1)
  assert.equal(out.failed, true)
  assert.equal(out.state.code, 'ticket_lost')
  assert.deepEqual(settleTicket(out).refusal.body, { success: false, error: 'The answer was lost when the city restarted.', code: 'ticket_lost' })
})

test('the ticket as the city hands it out and answers it (backend app/public/tickets.py)', async () => {
  const handed = { success: true, data: { ticket: 'AbCdEfGhIjKlMnOpQrStUvWx', status: 'thinking', budget_seconds: 240, poll: '/api/parthenon/ticket/AbCdEfGhIjKlMnOpQrStUvWx', poll_seconds: 2 } }
  assert.equal(ticketOf(202, handed), 'AbCdEfGhIjKlMnOpQrStUvWx')
  const result = { success: true, data: { answer: 'I would say it again.', from_memory: true } }
  const answered = { success: true, ticket: 'AbCdEfGhIjKlMnOpQrStUvWx', status: 'done', result, http_status: 200, error: null, code: null, budget_seconds: 240, elapsed_seconds: 31.2 }
  const state = readTicket(answered)
  assert.equal(state.status, 'done')
  assert.equal(state.result, result)
  assert.equal(state.httpStatus, 200)
  const clock = fakeTime()
  const out = await waitForTicket('AbCdEfGhIjKlMnOpQrStUvWx', { fetchTicket: async () => answered, now: clock.now, sleep: clock.sleep })
  assert.deepEqual(settleTicket(out), { result })
  const timedOut = { success: true, status: 'failed', result: { success: false, error: 'It took too long.', code: 'slow_down', retry_after_seconds: 60 }, http_status: 503, error: 'It took too long.', code: 'slow_down', retry_after_seconds: 60 }
  const out2 = await waitForTicket('AbCdEfGhIjKlMnOpQrStUvWx', { fetchTicket: async () => timedOut, now: clock.now, sleep: clock.sleep })
  assert.deepEqual(settleTicket(out2), { refusal: { body: { success: false, error: 'It took too long.', code: 'slow_down', retry_after_seconds: 60 }, status: 503 } })
})

test('leaving stops the wait at once', async () => {
  const controller = new AbortController()
  let looks = 0
  const waiting = waitForTicket(ID, {
    fetchTicket: async () => { looks += 1; return { status: 'thinking' } },
    sleep: abortableSleep,
    signal: controller.signal,
    budgetMs: 260000
  })
  setTimeout(() => controller.abort(), 30)
  const started = Date.now()
  await assert.rejects(waiting, (err) => err.ticketEnd === TICKET_ENDS.abandoned)
  assert.ok(Date.now() - started < 1500, 'the 2 s sleep ended when the page left')
  assert.equal(looks, 0)
  const already = new AbortController()
  already.abort()
  await assert.rejects(waitForTicket(ID, { fetchTicket: async () => ({ status: 'done' }), signal: already.signal }), (err) => err.ticketEnd === TICKET_ENDS.abandoned)
})

test('what a finished wait amounts to', () => {
  // The route's own refusal inside a done ticket reads as that refusal.
  const refused = { success: false, error: 'This citizen cannot answer now.', from_memory: true }
  assert.deepEqual(settleTicket({ done: true, result: refused, state: { httpStatus: 503 } }), { refusal: { body: refused, status: 503 } })
  assert.deepEqual(settleTicket({ done: true, result: refused, state: {} }), { refusal: { body: refused, status: 500 } })
  // A failed ticket: its error, code and wait over whatever it carried.
  assert.deepEqual(
    settleTicket({ failed: true, state: { status: 'failed', result: { from_memory: true, error: 'old' }, error: 'The city needs a moment.', code: 'slow_down', retryAfter: 60, httpStatus: 0 } }),
    { refusal: { body: { from_memory: true, error: 'The city needs a moment.', success: false, code: 'slow_down', retry_after_seconds: 60 }, status: 503 } }
  )
  assert.deepEqual(settleTicket({ failed: true, state: { status: 'failed', result: null, error: '', code: '', retryAfter: 0, httpStatus: 502 } }), { refusal: { body: { success: false }, status: 502 } })
  // A done answer that is not a refusal is returned as it is, whatever it is.
  assert.deepEqual(settleTicket({ done: true, result: null, state: {} }), { result: null })
})

// ---- Every question route is waited on; nothing else is ----
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const API = join(dirname(fileURLToPath(import.meta.url)), '..', 'api')
const read = (name) => readFileSync(join(API, name), 'utf8')

test('the question routes go through the ticket waiter, and take a signal to stop it', () => {
  assert.match(read('simulation.js'), /export const interviewAgents = \(data, options\) => \{\s*return asked\(service\.post\('\/api\/simulation\/interview\/batch', data\), options\)/)
  assert.match(read('report.js'), /export const chatWithReport = \(data, options\) => \{\s*return asked\(service\.post\('\/api\/report\/chat', data\), options\)/)
  assert.match(read('parthenon.js'), /export const draftStage = \(stage, fill, options\) => \{\s*return asked\(service\.post\('\/api\/parthenon\/stage\/draft', \{ stage, fill \}\), options\)/)
  assert.match(read('parthenon.js'), /export const askSpeaker = \(simulationId, body, options\) =>\s*asked\(service\.post\(`\/api\/parthenon\/gathering\/\$\{encodeURIComponent\(simulationId\)\}\/speaker`/)
  // Only these four: a read, a start or a film is never waited on as a ticket.
  const all = ['simulation.js', 'report.js', 'parthenon.js', 'graph.js'].map(read).join('\n')
  assert.equal((all.match(/\basked\(/g) || []).length, 4)
  assert.match(read('tickets.js'), /\/api\/parthenon\/ticket\/\$\{encodeURIComponent\(id\)\}/)
})

test('the API client marks a 202 ticket, reads a ticket whole, and shows the word only on guarded calls', () => {
  const client = read('index.js')
  assert.match(client, /if \(ticketOf\(response\.status, res\)\) markTicket\(res\)/)
  assert.match(client, /if \(response\.config\?\.parthenonTicket\) return res/)
  assert.match(client, /access\.invite && \(access\.public \|\| access\.inviteRequired\) && isInvitedCall\(config\)/)
  assert.match(client, /if \(code === 'invite_needed'\) inviteRefused\(error\.config\?\.parthenonInvite \|\| ''\)/)
})
