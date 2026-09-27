// Run: cd frontend && node --test src/parthenon/limits.test.mjs
//
// The public steps' limits as the page reads them: the longest run a visitor
// may choose, and how many gatherings are left today.
import test from 'node:test'
import assert from 'node:assert/strict'
import { maxRunHours, allowedRunLengths, clampRunLength, gatheringsLeft, retryMinutes } from './limits.js'
import { RUN_LENGTHS } from './vocabulary.js'

const ids = (list) => list.map((l) => l.id)

test('the longest run is a length\'s id, a number of hours, or no limit', () => {
  assert.equal(maxRunHours('day', RUN_LENGTHS), 24)
  assert.equal(maxRunHours('afternoon', RUN_LENGTHS), 12)
  assert.equal(maxRunHours(72, RUN_LENGTHS), 72)
  assert.equal(maxRunHours('72', RUN_LENGTHS), 72)
  assert.equal(maxRunHours(undefined, RUN_LENGTHS), Infinity)
  assert.equal(maxRunHours('', RUN_LENGTHS), Infinity)
  assert.equal(maxRunHours('forever', RUN_LENGTHS), Infinity)
  assert.equal(maxRunHours(0, RUN_LENGTHS), Infinity)
})

test('a visitor chooses among the lengths up to the longest allowed', () => {
  assert.deepEqual(ids(allowedRunLengths(RUN_LENGTHS, 'day')), ['afternoon', 'day'])
  assert.deepEqual(ids(allowedRunLengths(RUN_LENGTHS, 72)), ['afternoon', 'day', 'threeDays'])
  assert.deepEqual(ids(allowedRunLengths(RUN_LENGTHS, null)), ['afternoon', 'day', 'threeDays', 'week'])
  assert.deepEqual(ids(allowedRunLengths(RUN_LENGTHS, 6)), ['afternoon'], 'never none: the shortest stays')
})

test('a choice beyond the limit becomes the longest allowed', () => {
  assert.equal(clampRunLength('week', RUN_LENGTHS, 'day'), 'day')
  assert.equal(clampRunLength('afternoon', RUN_LENGTHS, 'day'), 'afternoon')
  assert.equal(clampRunLength('day', RUN_LENGTHS, undefined), 'day')
})

test('the gatherings left today: the smaller of the city\'s and the visitor\'s', () => {
  assert.equal(gatheringsLeft(null), null)
  assert.equal(gatheringsLeft({}), null)
  assert.deepEqual(gatheringsLeft({ today_left: 9, visitor_left: 2 }), { city: 9, visitor: 2, left: 2, closed: false, who: '' })
  assert.deepEqual(gatheringsLeft({ today_left: 1, visitor_left: 2 }), { city: 1, visitor: 2, left: 1, closed: false, who: '' })
  assert.deepEqual(gatheringsLeft({ today_left: 0, visitor_left: 2 }), { city: 0, visitor: 2, left: 0, closed: true, who: 'city' })
  assert.deepEqual(gatheringsLeft({ today_left: 5, visitor_left: 0 }), { city: 5, visitor: 0, left: 0, closed: true, who: 'visitor' })
  assert.deepEqual(gatheringsLeft({ today_left: '4' }), { city: 4, visitor: null, left: 4, closed: false, who: '' })
  assert.deepEqual(gatheringsLeft({ today_left: -3, visitor_left: 1 }).closed, true)
})

test('a wait is said in whole minutes, at least one', () => {
  assert.equal(retryMinutes(undefined), 0)
  assert.equal(retryMinutes(0), 0)
  assert.equal(retryMinutes(5), 1)
  assert.equal(retryMinutes(60), 1)
  assert.equal(retryMinutes(61), 2)
  assert.equal(retryMinutes('1800'), 30)
})
