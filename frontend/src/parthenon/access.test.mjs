// Run: cd frontend && node --test src/parthenon/access.test.mjs
//
// What a visitor may do: everything at home; on the public steps, steer only
// the gatherings this browser began, and make only what the city can make.
import test from 'node:test'
import assert from 'node:assert/strict'
import 'vue'
import { access, applyStatus, canControl, featureOn, ownsGathering, calmLine, calmCode, cityCodeOf, noteResponseError, CITY_CODES } from './access.js'

const TOKEN = 'k3y-0f-the-gathering_abcdefghijklmnopqrstu'
const reset = () => {
  access.loaded = false
  access.public = false
  access.provider = ''
  access.features = { portraits: true, film: true, voice: true }
  access.limits = null
  access.owned = {}
  access.admin = ''
}

test('at home every control and every feature is on, as always', () => {
  reset()
  assert.equal(canControl('sim_2c79002f1b0c'), true)
  assert.equal(canControl(), true)
  for (const f of ['portraits', 'film', 'voice']) assert.equal(featureOn(f), true)
  // Even a status that reports features off leaves home as it was.
  applyStatus({ public: false, features: { portraits: false, film: false, voice: false } })
  assert.equal(featureOn('portraits'), true)
  assert.equal(canControl('sim_2c79002f1b0c'), true)
})

test('on the public steps only the one who began a gathering steers it', () => {
  reset()
  applyStatus({ public: true, provider: 'free', features: { portraits: false, film: false, voice: false }, limits: { today_left: 3 } })
  assert.equal(access.loaded, true)
  assert.equal(access.provider, 'free')
  assert.deepEqual(access.limits, { today_left: 3 })
  assert.equal(canControl('sim_2c79002f1b0c'), false)
  access.owned = { proj_527f80721255: TOKEN, sim_2c79002f1b0c: TOKEN }
  assert.equal(canControl('sim_2c79002f1b0c'), true)
  assert.equal(canControl(undefined, 'proj_527f80721255'), true)
  assert.equal(canControl('report_53d558ea0a3d'), false)
  assert.equal(ownsGathering(['report_53d558ea0a3d', 'sim_2c79002f1b0c']), true)
  // The city's keeper steers any gathering.
  access.admin = 'keeper'
  assert.equal(canControl('report_53d558ea0a3d'), true)
})

test('on the public steps only what the city can make is offered', () => {
  reset()
  applyStatus({ public: true, features: { portraits: true, film: false } })
  assert.equal(featureOn('portraits'), true)
  assert.equal(featureOn('film'), false)
  assert.equal(featureOn('voice'), false, 'a feature not named is off')
  // An older backend that names no features can make everything.
  applyStatus({ public: true })
  assert.equal(featureOn('film'), true)
})

test('a limit answer reads as the city\'s calm words; anything else reads as nothing', () => {
  assert.deepEqual(CITY_CODES, ['city_full', 'come_back_tomorrow', 'slow_down', 'too_long', 'not_yours', 'not_on_public_steps', 'invite_needed', 'ticket_lost'])
  const limit = Object.assign(new Error('Athens has held all the gatherings it can today.'), { cityCode: 'come_back_tomorrow' })
  assert.equal(calmLine(limit), 'Athens has held all the gatherings it can today.')
  assert.equal(calmCode(limit), 'come_back_tomorrow')
  assert.equal(calmLine(new Error('Traceback (most recent call last)')), '')
  assert.equal(calmCode(null), '')
})

test('a response body names a city code only when it is one of the city\'s refusals', () => {
  assert.equal(cityCodeOf({ success: false, code: 'slow_down', retry_after_seconds: 40 }), 'slow_down')
  assert.equal(cityCodeOf({ success: false, code: 'too_long' }), 'too_long')
  assert.equal(cityCodeOf({ success: false, code: 'KeyError' }), '')
  assert.equal(cityCodeOf({ success: false, code: 42 }), '')
  assert.equal(cityCodeOf({ success: false, error: 'boom' }), '')
  assert.equal(cityCodeOf('city_full'), '')
  assert.equal(cityCodeOf(null), '')
  assert.equal(cityCodeOf(undefined), '')
})

const recorder = () => {
  const seen = []
  return {
    seen,
    con: {
      error: (...args) => seen.push(['error', ...args]),
      info: (...args) => seen.push(['info', ...args]),
      debug: (...args) => seen.push(['debug', ...args])
    }
  }
}

test('an expected refusal is noted quietly, never as a console error', () => {
  for (const [code, status] of [['slow_down', 429], ['too_long', 413], ['come_back_tomorrow', 429], ['city_full', 429], ['not_yours', 403], ['not_on_public_steps', 403]]) {
    const { seen, con } = recorder()
    const error = Object.assign(new Error(`Request failed with status code ${status}`), {
      config: { method: 'post', url: '/api/report/chat' },
      response: { status, data: { success: false, error: 'the city\'s words', code } }
    })
    noteResponseError(error, con)
    assert.equal(seen.length, 1)
    assert.equal(seen[0][0], 'info', `${code} is not an error`)
    assert.equal(seen[0].length, 2, 'one line, no error object (no stack)')
    assert.equal(seen[0][1], `The city declined POST /api/report/chat: ${code} (${status})`)
  }
})

test('a real failure is still a console error, as it always was', () => {
  const cases = [
    Object.assign(new Error('Request failed with status code 500'), {
      config: { method: 'get', url: '/api/graph/project/x' },
      response: { status: 500, data: { success: false, error: 'Traceback', code: 'KeyError' } }
    }),
    Object.assign(new Error('Request failed with status code 404'), { response: { status: 404, data: '<html>' } }),
    Object.assign(new Error('Network Error'), { config: { url: '/api/x' } }),
    new Error('timeout of 300000ms exceeded')
  ]
  for (const error of cases) {
    const { seen, con } = recorder()
    noteResponseError(error, con)
    assert.deepEqual(seen, [['error', 'Response error:', error]])
  }
  // Nothing to go on at all: still noted, still an error.
  const { seen, con } = recorder()
  noteResponseError(undefined, con)
  assert.deepEqual(seen, [['error', 'Response error:', undefined]])
})

test('a refusal with no call recorded still reads as one line', () => {
  const { seen, con } = recorder()
  noteResponseError({ response: { data: { code: 'city_full' } } }, con)
  assert.deepEqual(seen, [['info', 'The city declined: city_full']])
})

// ---- The word that opens the steps to speech ----
import { inviteNeeded, giveInvite, inviteRefused } from './access.js'

const resetInvite = () => {
  reset()
  access.inviteRequired = false
  access.invite = ''
  access.inviteWrong = false
}

test('when the city asks for no word nothing changes, at home or on the public steps', () => {
  resetInvite()
  assert.equal(inviteNeeded(), false)
  applyStatus({ public: true, features: {} })
  assert.equal(access.inviteRequired, false)
  assert.equal(inviteNeeded(), false)
  applyStatus({ public: false, invite_required: false })
  assert.equal(inviteNeeded(), false)
})

test('a city that asks for the word asks only a visitor who has not brought it', () => {
  resetInvite()
  applyStatus({ public: true, invite_required: true })
  assert.equal(access.inviteRequired, true)
  assert.equal(inviteNeeded(), true)
  assert.equal(giveInvite('   '), false, 'no word is not a word')
  assert.equal(giveInvite('one,two'), false)
  assert.equal(inviteNeeded(), true)
  assert.equal(giveInvite('  athens  '), true)
  assert.equal(access.invite, 'athens')
  assert.equal(inviteNeeded(), false)
  // The city's keeper passes without one.
  access.invite = ''
  access.admin = 'keeper'
  assert.equal(inviteNeeded(), false)
  // Only a true invite_required asks.
  access.admin = ''
  applyStatus({ public: true, invite_required: 'yes' })
  assert.equal(inviteNeeded(), false)
})

test('a word the city did not know is forgotten, and the next ask says so', () => {
  resetInvite()
  applyStatus({ public: true, invite_required: true })
  giveInvite('wrong-word')
  inviteRefused('wrong-word')
  assert.equal(access.invite, '')
  assert.equal(access.inviteWrong, true)
  assert.equal(inviteNeeded(), true)
  // Bringing another clears the calm line.
  giveInvite('right-word')
  assert.equal(access.inviteWrong, false)
  assert.equal(inviteNeeded(), false)
})

test('an invite_needed with no word shown only learns that the city asks for one', () => {
  resetInvite()
  // The status had not said (it did not arrive); the refusal teaches it.
  assert.equal(access.inviteRequired, false)
  inviteRefused('')
  assert.equal(access.inviteRequired, true)
  assert.equal(access.inviteWrong, false, 'nothing was wrong: nothing was brought')
  assert.equal(inviteNeeded(), true)
  // A refusal of an older word (another tab changed it since) keeps the newer one.
  giveInvite('newer')
  inviteRefused('older')
  assert.equal(access.invite, 'newer')
})

test('the city names the one language it keeps its records in, or none', () => {
  applyStatus({ public: true, recordLanguage: 'en' })
  assert.equal(access.recordLanguage, 'en')
  applyStatus({ public: true, recordLanguage: 'zh-CN' })
  assert.equal(access.recordLanguage, 'zh')
  applyStatus({ public: false, recordLanguage: null })
  assert.equal(access.recordLanguage, null)
  // An older city says nothing of it; nothing is assumed.
  applyStatus({ public: true })
  assert.equal(access.recordLanguage, null)
  applyStatus({ public: true, recordLanguage: 'fr' })
  assert.equal(access.recordLanguage, null)
})
