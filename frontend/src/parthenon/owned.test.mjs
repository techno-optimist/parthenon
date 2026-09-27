// Run: cd frontend && node --test src/parthenon/owned.test.mjs
//
// The gatherings this browser began: which ids it keeps under which key, the
// key it shows on a call about one of them, and what it learns from answers.
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  OWNED_KEY,
  ADMIN_KEY,
  isGatheringId,
  parseOwned,
  readOwned,
  writeOwned,
  readAdmin,
  addOwned,
  tokenFor,
  listedIds,
  idsInRequest,
  idsInResponse,
  tokenInResponse,
  learnFromResponse,
  ownsAny
} from './owned.js'

const TOKEN = 'k3y-0f-the-gathering_abcdefghijklmnopqrstu'
const OTHER = 'another-key-entirely_0123456789abcdefghij'

const memoryStorage = (initial = {}) => {
  const data = { ...initial }
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v) },
    removeItem: (k) => { delete data[k] }
  }
}

test('a gathering id is proj_, sim_ or report_ and letters or digits', () => {
  assert.ok(isGatheringId('proj_527f80721255'))
  assert.ok(isGatheringId('sim_2c79002f1b0c'))
  assert.ok(isGatheringId('report_53d558ea0a3d'))
  assert.ok(!isGatheringId('new'))
  assert.ok(!isGatheringId('graph_1234abcd'))
  assert.ok(!isGatheringId('sim_'))
  assert.ok(!isGatheringId('sim_12/../x'))
  assert.ok(!isGatheringId(null))
})

test('only well-formed pairs are kept from storage', () => {
  assert.deepEqual(parseOwned(null), {})
  assert.deepEqual(parseOwned('not json'), {})
  assert.deepEqual(parseOwned('[1,2]'), {})
  assert.deepEqual(
    parseOwned(JSON.stringify({ proj_527f80721255: TOKEN, sim_2c79002f1b0c: 7, 'evil key': TOKEN, report_53d558ea0a3d: 'short' })),
    { proj_527f80721255: TOKEN }
  )
})

test('the map is read and written under parthenon.owned; a broken storage is survived', () => {
  const storage = memoryStorage()
  assert.equal(OWNED_KEY, 'parthenon.owned')
  assert.deepEqual(readOwned(storage), {})
  assert.ok(writeOwned(storage, { proj_527f80721255: TOKEN }))
  assert.deepEqual(JSON.parse(storage.data[OWNED_KEY]), { proj_527f80721255: TOKEN })
  assert.deepEqual(readOwned(storage), { proj_527f80721255: TOKEN })
  const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
  assert.deepEqual(readOwned(broken), {})
  assert.equal(writeOwned(broken, {}), false)
  assert.deepEqual(readOwned(null), {})
})

test('the admin key is read from parthenon.admin, when there is one', () => {
  assert.equal(ADMIN_KEY, 'parthenon.admin')
  assert.equal(readAdmin(memoryStorage()), '')
  assert.equal(readAdmin(memoryStorage({ [ADMIN_KEY]: '  s3cret  ' })), 's3cret')
  assert.equal(readAdmin(memoryStorage({ [ADMIN_KEY]: 'x'.repeat(600) })), '')
})

test('ids are kept under the key that began them, and never re-keyed', () => {
  const a = addOwned({}, ['proj_527f80721255'], TOKEN)
  assert.deepEqual(a, { proj_527f80721255: TOKEN })
  const b = addOwned(a, ['proj_527f80721255', 'sim_2c79002f1b0c'], OTHER)
  assert.equal(b.proj_527f80721255, TOKEN, 'the first key stays')
  assert.equal(b.sim_2c79002f1b0c, OTHER)
  assert.equal(addOwned(b, ['proj_527f80721255'], TOKEN), b, 'nothing new: the same map')
  assert.equal(addOwned(b, ['sim_ffffffffffff'], 'bad'), b, 'a malformed key keeps nothing')
  assert.equal(addOwned(b, ['new'], TOKEN), b, 'not an id')
})

test('the key shown is the first held for any of the ids', () => {
  const map = { sim_2c79002f1b0c: TOKEN }
  assert.equal(tokenFor(map, ['proj_000000000000', 'sim_2c79002f1b0c']), TOKEN)
  assert.equal(tokenFor(map, ['report_53d558ea0a3d']), '')
  assert.equal(tokenFor(map, []), '')
  assert.equal(tokenFor({}, ['sim_2c79002f1b0c']), '')
  assert.ok(ownsAny(map, ['sim_2c79002f1b0c', undefined]))
  assert.ok(!ownsAny(map, ['new']))
})

test('the shelf is told the ids asked for first, then the ones kept, newest first', () => {
  const map = { proj_aaaaaaaaaaaa: TOKEN, sim_bbbbbbbbbbbb: TOKEN, report_cccccccccccc: TOKEN }
  assert.deepEqual(listedIds(map), ['report_cccccccccccc', 'sim_bbbbbbbbbbbb', 'proj_aaaaaaaaaaaa'])
  assert.deepEqual(listedIds(map, ['sim_dddddddddddd', 'sim_bbbbbbbbbbbb', 'nope']), [
    'sim_dddddddddddd',
    'sim_bbbbbbbbbbbb',
    'report_cccccccccccc',
    'proj_aaaaaaaaaaaa'
  ])
  const many = Object.fromEntries(Array.from({ length: 90 }, (_, i) => [`sim_${String(i).padStart(12, '0')}`, TOKEN]))
  assert.equal(listedIds(many).length, 60, 'the header stays short')
})

test('a request names its gathering in its path, its query or its body', () => {
  assert.deepEqual(idsInRequest({ url: '/api/simulation/sim_2c79002f1b0c/run-status' }), ['sim_2c79002f1b0c'])
  assert.deepEqual(idsInRequest({ url: '/api/parthenon/chronicle/report_53d558ea0a3d/film' }), ['report_53d558ea0a3d'])
  assert.deepEqual(idsInRequest({ url: '/api/report/by-simulation/sim_2c79002f1b0c' }), ['sim_2c79002f1b0c'])
  assert.deepEqual(idsInRequest({ url: '/api/graph/project/proj_527f80721255' }), ['proj_527f80721255'])
  assert.deepEqual(idsInRequest({ url: '/api/report/generate/status', params: { report_id: 'report_53d558ea0a3d' } }), ['report_53d558ea0a3d'])
  assert.deepEqual(idsInRequest({ url: '/api/x?simulation_id=sim_2c79002f1b0c&limit=3' }), ['sim_2c79002f1b0c'])
  assert.deepEqual(
    idsInRequest({ url: '/api/simulation/start', data: { simulation_id: 'sim_2c79002f1b0c', max_rounds: 24 } }),
    ['sim_2c79002f1b0c']
  )
  assert.deepEqual(
    idsInRequest({ url: '/api/simulation/create', data: JSON.stringify({ project_id: 'proj_527f80721255', graph_id: 'g_1' }) }),
    ['proj_527f80721255']
  )
  const form = new FormData()
  form.append('simulation_requirement', 'What should Athens do?')
  form.append('project_id', 'proj_527f80721255')
  assert.deepEqual(idsInRequest({ url: '/api/graph/ontology/generate', data: form }), ['proj_527f80721255'])
  // Nothing about a gathering: the history, a new scroll, the status.
  assert.deepEqual(idsInRequest({ url: '/api/simulation/history', params: { limit: 60 } }), [])
  assert.deepEqual(idsInRequest({ url: '/api/parthenon/status' }), [])
  assert.deepEqual(idsInRequest({ url: '/api/graph/data/mirofish_4a1b2c3d' }), [])
  assert.deepEqual(idsInRequest({}), [])
})

test('a response names ids in its data object, never in a list', () => {
  assert.deepEqual(idsInResponse({ success: true, data: { simulation_id: 'sim_2c79002f1b0c', project_id: 'proj_527f80721255' } }).sort(), [
    'proj_527f80721255',
    'sim_2c79002f1b0c'
  ])
  assert.deepEqual(idsInResponse({ success: true, data: [{ simulation_id: 'sim_2c79002f1b0c' }] }), [])
  assert.deepEqual(idsInResponse({ success: true, data: { simulation_id: '../../etc' } }), [])
  assert.deepEqual(idsInResponse(null), [])
})

test('a gathering just begun hands back its key, on the body or in its data', () => {
  assert.equal(tokenInResponse({ success: true, owner_token: TOKEN, data: {} }), TOKEN)
  assert.equal(tokenInResponse({ success: true, data: { owner_token: TOKEN } }), TOKEN)
  assert.equal(tokenInResponse({ success: true, data: { owner_token: 'x' } }), '')
  assert.equal(tokenInResponse(undefined), '')
})

test('the begin flow keeps the scroll, its crowd and its Chronicle under one key', () => {
  let map = {}
  // POST /api/graph/ontology/generate: the scroll is heard, and its key comes back.
  map = learnFromResponse(map, { body: { success: true, data: { project_id: 'proj_527f80721255', owner_token: TOKEN } } })
  assert.deepEqual(map, { proj_527f80721255: TOKEN })
  // POST /api/simulation/create, sent with the key: the crowd is kept too.
  const create = { url: '/api/simulation/create', data: { project_id: 'proj_527f80721255' } }
  const sent = tokenFor(map, idsInRequest(create))
  assert.equal(sent, TOKEN)
  map = learnFromResponse(map, { sentToken: sent, body: { success: true, data: { simulation_id: 'sim_2c79002f1b0c', project_id: 'proj_527f80721255' } } })
  // POST /api/report/generate, sent with the key: the Chronicle is kept too.
  const generate = { url: '/api/report/generate', data: { simulation_id: 'sim_2c79002f1b0c' } }
  map = learnFromResponse(map, { sentToken: tokenFor(map, idsInRequest(generate)), body: { success: true, data: { simulation_id: 'sim_2c79002f1b0c', report_id: 'report_53d558ea0a3d' } } })
  assert.deepEqual(map, { proj_527f80721255: TOKEN, sim_2c79002f1b0c: TOKEN, report_53d558ea0a3d: TOKEN })
})

test('an answer about someone else\'s gathering teaches nothing', () => {
  const map = { proj_527f80721255: TOKEN }
  // No key was shown (not this browser's), and none came back.
  const next = learnFromResponse(map, { sentToken: '', body: { success: true, data: { simulation_id: 'sim_999999999999', project_id: 'proj_888888888888' } } })
  assert.equal(next, map)
})
