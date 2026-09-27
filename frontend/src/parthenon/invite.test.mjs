// Run: cd frontend && node --test src/parthenon/invite.test.mjs
//
// The word that opens the steps to speech: kept whole, taken from a link and
// cleared from it, and shown only on the calls the city guards with it.
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  INVITE_KEY,
  INVITE_HEADER,
  cleanInvite,
  readInvite,
  writeInvite,
  forgetInvite,
  inviteInLink,
  apiPathOf,
  isInvitedCall,
  presentSlip,
  showSlip
} from './invite.js'
import { readFileSync } from 'node:fs'

const memory = (init = {}) => {
  const data = { ...init }
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v) },
    removeItem: (k) => { delete data[k] }
  }
}
const refusing = {
  getItem: () => { throw new Error('blocked') },
  setItem: () => { throw new Error('blocked') },
  removeItem: () => { throw new Error('blocked') }
}

test('the names are the contract\'s', () => {
  assert.equal(INVITE_KEY, 'parthenon.invite')
  assert.equal(INVITE_HEADER, 'X-Parthenon-Invite')
})

test('a word is kept trimmed and whole; what cannot be a header value is not a word', () => {
  assert.equal(cleanInvite('  athens-399  '), 'athens-399')
  assert.equal(cleanInvite('open sesame'), 'open sesame')
  assert.equal(cleanInvite('aB3+/x=='), 'aB3+/x==', 'a base64 word keeps its + / =')
  assert.equal(cleanInvite(''), '')
  assert.equal(cleanInvite('   '), '')
  assert.equal(cleanInvite('one,two'), '', 'the owner\'s list is comma separated')
  assert.equal(cleanInvite('λόγος'), '', 'a header carries ASCII only')
  assert.equal(cleanInvite('a\nb'), '')
  assert.equal(cleanInvite('x'.repeat(256)), 'x'.repeat(256))
  assert.equal(cleanInvite('x'.repeat(257)), '')
  assert.equal(cleanInvite(null), '')
  assert.equal(cleanInvite(42), '')
})

test('the word is kept in, read from and forgotten by the storage; a refusing storage is survived', () => {
  const s = memory()
  assert.equal(readInvite(s), '')
  assert.equal(writeInvite(s, ' word-1 '), true)
  assert.equal(s.data[INVITE_KEY], 'word-1')
  assert.equal(readInvite(s), 'word-1')
  assert.equal(writeInvite(s, 'bad,word'), false)
  assert.equal(readInvite(s), 'word-1', 'a word that cannot be one never replaces the kept one')
  assert.equal(forgetInvite(s), true)
  assert.equal(readInvite(s), '')
  assert.equal(readInvite(memory({ [INVITE_KEY]: 'a,b' })), '', 'a tampered value reads as none')
  assert.equal(readInvite(refusing), '')
  assert.equal(writeInvite(refusing, 'w'), false)
  assert.equal(forgetInvite(refusing), false)
  assert.equal(readInvite(null), '')
})

test('a link that carries the word gives it, and the address keeps everything else', () => {
  assert.deepEqual(inviteInLink('https://projectforty2.ai/parthenon?invite=CODE'), { code: 'CODE', url: '/parthenon' })
  assert.deepEqual(inviteInLink('https://projectforty2.ai/parthenon/?invite=CODE'), { code: 'CODE', url: '/parthenon/' })
  assert.deepEqual(
    inviteInLink('https://projectforty2.ai/parthenon/symposium/report_8e64c6bfab2f?lang=zh&invite=w%2Fx%3D&x=a+b#seat'),
    { code: 'w/x=', url: '/parthenon/symposium/report_8e64c6bfab2f?lang=zh&x=a+b#seat' },
    'other parameters are kept byte for byte, the hash too'
  )
  assert.deepEqual(inviteInLink('http://localhost:3000/?invite=aB3+/x=='), { code: 'aB3+/x==', url: '/' }, 'a + stays a +')
  assert.deepEqual(inviteInLink('http://localhost:3000/?invite=%20spaced%20'), { code: 'spaced', url: '/' })
})

test('a link without the word is left alone; a broken word is still cleared from the address', () => {
  assert.deepEqual(inviteInLink('https://projectforty2.ai/parthenon/'), { code: '', url: '' })
  assert.deepEqual(inviteInLink('https://projectforty2.ai/parthenon/?lang=zh'), { code: '', url: '' })
  assert.deepEqual(inviteInLink('https://projectforty2.ai/parthenon/?invited=1'), { code: '', url: '' })
  assert.deepEqual(inviteInLink('https://projectforty2.ai/parthenon/?invite='), { code: '', url: '/parthenon/' })
  assert.deepEqual(inviteInLink('https://projectforty2.ai/parthenon/?invite'), { code: '', url: '/parthenon/' })
  assert.deepEqual(inviteInLink('https://projectforty2.ai/parthenon/?invite=%E0%A4%A'), { code: '', url: '/parthenon/' })
  assert.deepEqual(inviteInLink('https://projectforty2.ai/?invite=a,b&q=1'), { code: '', url: '/?q=1' })
  assert.deepEqual(inviteInLink('https://projectforty2.ai/?invite=first&invite=second'), { code: 'first', url: '/' })
  assert.deepEqual(inviteInLink('not a url'), { code: '', url: '' })
  assert.deepEqual(inviteInLink(undefined), { code: '', url: '' })
})

test('the API path of a request, whatever stands in front of it', () => {
  assert.equal(apiPathOf('/api/report/chat'), '/api/report/chat')
  assert.equal(apiPathOf('/parthenon/api/report/chat?x=1'), '/api/report/chat')
  assert.equal(apiPathOf('http://localhost:5001/api/parthenon/voice#a'), '/api/parthenon/voice')
  assert.equal(apiPathOf('/media/x.jpg'), '')
  assert.equal(apiPathOf(undefined), '')
})

test('the word is shown on every call the city guards with it', () => {
  const guarded = [
    '/api/graph/ontology/generate',
    '/api/simulation/interview',
    '/api/simulation/interview/batch',
    '/api/simulation/interview/all',
    '/api/report/chat',
    '/api/parthenon/stage/draft',
    '/api/parthenon/voice',
    '/api/parthenon/gathering/sim_909e9d58b157/speaker',
    '/api/parthenon/gathering/sim_909e9d58b157/portraits',
    '/api/parthenon/gathering/sim_909e9d58b157/stances',
    '/api/parthenon/chronicle/report_8e64c6bfab2f/film'
  ]
  for (const url of guarded) {
    assert.equal(isInvitedCall({ method: 'post', url }), true, url)
    assert.equal(isInvitedCall({ method: 'POST', url: `/parthenon${url}` }), true, `under the base: ${url}`)
  }
})

test('reading never shows the word', () => {
  const reads = [
    ['get', '/api/parthenon/gathering/sim_909e9d58b157/portraits'],
    ['get', '/api/parthenon/gathering/sim_909e9d58b157/stances'],
    ['get', '/api/parthenon/chronicle/report_8e64c6bfab2f/film'],
    ['get', '/api/parthenon/chronicle/report_8e64c6bfab2f/film/film.mp4'],
    ['get', '/api/parthenon/voice/abc.mp3'],
    ['get', '/api/parthenon/ticket/Zq3xY_abcdefghij'],
    ['get', '/api/parthenon/status'],
    ['post', '/api/simulation/prepare/status'],
    ['post', '/api/simulation/env-status'],
    ['post', '/api/simulation/interview/history'],
    ['post', '/api/simulation/start'],
    ['post', '/api/graph/build'],
    ['post', '/api/report/generate'],
    ['post', '/api/parthenon/gathering/sim_909e9d58b157/portraits/extra'],
    [undefined, '/api/report/chat']
  ]
  for (const [method, url] of reads) assert.equal(isInvitedCall({ method, url }), false, `${method} ${url}`)
  assert.equal(isInvitedCall(), false)
})

// On a phone the slip appears near the foot of the page, where the fixed act
// bar lies: the slip is brought into view first, and the field then takes the
// caret without a scroll of its own (which could leave it under the bar).
const fakeSlip = (log, { throws = false } = {}) => ({
  scrollIntoView: (opts) => {
    log.push(['scroll', opts])
    if (throws) throw new Error('no view')
  }
})
const fakeField = (log, { throws = false } = {}) => ({
  focus: (opts) => {
    log.push(['focus', opts])
    if (throws) throw new Error('no focus')
  }
})

test('the slip comes into view whole before its field takes the caret, without a second scroll', () => {
  const log = []
  assert.equal(presentSlip(fakeSlip(log), fakeField(log)), true)
  assert.deepEqual(log, [
    ['scroll', { block: 'nearest', inline: 'nearest', behavior: 'auto' }],
    ['focus', { preventScroll: true }]
  ])
  // At once, never smooth: a smooth scroll cut short (the keyboard rising, a
  // tab out of sight) would leave the field where it was, under the bar.
  const again = []
  presentSlip(fakeSlip(again), fakeField(again), { smooth: true })
  assert.equal(again[0][1].behavior, 'auto')
})

test('the slip is a courtesy: a view that cannot scroll or a field that cannot focus breaks nothing', () => {
  const log = []
  assert.equal(presentSlip(fakeSlip(log, { throws: true }), fakeField(log)), true)
  assert.deepEqual(log.map(([k]) => k), ['scroll', 'focus'])
  assert.equal(presentSlip({}, fakeField([])), true)
  assert.equal(presentSlip(null, fakeField([])), true)
  assert.equal(presentSlip(fakeSlip([]), null), false)
  assert.equal(presentSlip(fakeSlip([]), {}), false)
  assert.equal(presentSlip(fakeSlip([]), fakeField([], { throws: true })), false)
  assert.equal(presentSlip(), false)
})

test('a calm line at the slip\'s foot brings the slip into view again, at once, without taking the caret', () => {
  const log = []
  assert.equal(showSlip(fakeSlip(log)), true)
  assert.deepEqual(log, [['scroll', { block: 'nearest', inline: 'nearest', behavior: 'auto' }]])
  assert.equal(showSlip(fakeSlip([], { throws: true })), false)
  assert.equal(showSlip({}), false)
  assert.equal(showSlip(null), false)
  assert.equal(showSlip(), false)
})

test('the slip keeps clear of the fixed header and the act bar, and presents itself before focusing', () => {
  const vue = readFileSync(new URL('../components/InviteLine.vue', import.meta.url), 'utf8')
  const margin = vue.match(/\.invite-line\s*\{[^}]*scroll-margin:\s*([^;]+);/)
  assert.ok(margin, 'the slip has a scroll-margin')
  assert.match(margin[1], /var\(--p-header-h/)
  assert.match(margin[1], /var\(--p-way-h/)
  assert.match(margin[1], /safe-area-inset-bottom/)
  assert.match(vue, /presentSlip\(slip\.value, field\.value/)
  assert.doesNotMatch(vue, /preventScroll:\s*false/)
  // The calm line (a word not known, a limit) is shown too, not said under the bar.
  assert.match(vue, /watch\(line,[\s\S]*?showSlip\(slip\.value\)/)
})
