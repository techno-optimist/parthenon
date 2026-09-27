// Run: cd frontend && node --test src/parthenon/floor.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'

import { FLOOR_OVERRIDES, floorName, floorOf, floorSeat, nameKey } from './floor.js'

test('the Apology gives Socrates, a speaker', () => {
  const f = floorOf('socrates-the-apology.md')
  assert.equal(f.name, 'Socrates')
  assert.equal(f.zhName, '苏格拉底')
  assert.equal(f.kind, 'speaker')
  assert.equal(f.id, 'socrates')
  assert.equal(f.fileName, 'socrates-the-apology.md')
})

test('When Sand Speaks answers as Sand, not the card', () => {
  const f = floorOf('arrival-when-sand-speaks.md')
  assert.equal(f.name, 'Sand')
  assert.equal(f.zhName, '沙')
  assert.equal(f.kind, 'arrival')
  assert.equal(f.id, 'when-sand-speaks')
})

test('the Symposium arrival answers as Socrates', () => {
  const f = floorOf('arrival-symposium-machine-minds.md')
  assert.equal(f.name, 'Socrates')
  assert.equal(f.zhName, '苏格拉底')
  assert.equal(f.kind, 'arrival')
})

test('an arrival without an override keeps its own names', () => {
  const f = floorOf('arrival-prometheus-trial.md')
  assert.equal(f.name, 'Prometheus')
  assert.equal(f.zhName, '普罗米修斯')
  assert.equal(f.kind, 'arrival')
})

test('an unknown scroll, or none, has no floor', () => {
  assert.equal(floorOf('stage-x.md'), null)
  assert.equal(floorOf(''), null)
  assert.equal(floorOf(undefined), null)
})

test('overrides name only scrolls that exist', () => {
  for (const file of Object.keys(FLOOR_OVERRIDES)) assert.ok(floorOf(file), file)
})

test('floorOf reads the lists it is given', () => {
  const lists = { speakers: [], arrivals: [{ id: 'x', name: 'Xeno', fileName: 'x.md' }] }
  assert.deepEqual(floorOf('x.md', lists), { fileName: 'x.md', kind: 'arrival', id: 'x', name: 'Xeno', zhName: '' })
})

test('floorName speaks the visitor\'s language', () => {
  const f = floorOf('socrates-the-apology.md')
  assert.equal(floorName(f, 'zh-CN'), '苏格拉底')
  assert.equal(floorName(f, 'zh'), '苏格拉底')
  assert.equal(floorName(f, 'en'), 'Socrates')
  assert.equal(floorName(null, 'en'), '')
  assert.equal(floorName({ name: 'Xeno', zhName: '' }, 'zh'), 'Xeno')
})

test('floorSeat finds the couch that bears the name', () => {
  const sand = floorOf('arrival-when-sand-speaks.md')
  assert.equal(floorSeat(sand, [{ idx: 0, name: 'Sand' }, { idx: 2, name: 'Marina Kavvadia' }]), 0)
  assert.equal(floorSeat(sand, [{ idx: 2, name: 'Marina Kavvadia' }]), null)
  assert.equal(floorSeat(sand, [{ idx: 4, name: '沙' }]), 4)
  assert.equal(floorSeat(floorOf('socrates-the-apology.md'), [{ idx: 1, name: 'Sócrates' }]), 1)
  assert.equal(floorSeat(null, [{ idx: 0, name: 'Sand' }]), null)
})

test('nameKey matches the backend\'s name_key', () => {
  assert.equal(nameKey('Sócrates'), 'socrates')
  assert.equal(nameKey(' 苏格拉底 '), '苏格拉底')
  assert.equal(nameKey('Hand  and--Sand'), 'hand and sand')
  assert.equal(nameKey('手 与 沙'), '手与沙')
  assert.equal(nameKey(''), '')
  assert.equal(nameKey(null), '')
})
