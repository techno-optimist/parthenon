import test from 'node:test'
import assert from 'node:assert/strict'
import { roleLabel, platformName, entityTypeName, roleFamily, tieName, actionVerb, citizenName, stripIds, isPlatformNode, isActivityTie } from './vocabulary.js'

test('platforms are the Agora and the Stoa', () => {
  assert.equal(platformName('twitter'), 'the Agora')
  assert.equal(platformName('Reddit', 'title'), 'The Stoa')
  assert.equal(platformName('mastodon'), 'mastodon')
})

test('entity types read as plain words', () => {
  assert.equal(entityTypeName('Aisystem'), 'AI system')
  assert.equal(entityTypeName('LocalBusinessOwner'), 'local business owner')
  assert.equal(entityTypeName('RetiredQuarryman'), 'retired quarryman')
  assert.equal(entityTypeName('AIResearchLab'), 'AI research lab')
  assert.equal(entityTypeName('Entity'), '')
  assert.equal(roleLabel('PublicOfficial'), 'Public official')
  assert.equal(roleLabel('Aisystem'), 'AI system')
})

test('role families cover known and unknown types', () => {
  assert.equal(roleFamily('Fisher'), 'people')
  assert.equal(roleFamily('TechCompany'), 'institutions')
  assert.equal(roleFamily('CivicCampaign'), 'movements')
  assert.equal(roleFamily('Aisystem'), 'machines')
  assert.equal(roleFamily('ParentsCoalition'), 'movements')
  assert.equal(roleFamily('SchoolBoard'), 'institutions')
  assert.equal(roleFamily('Somebody'), 'people')
  assert.equal(roleFamily('Entity'), 'things')
  assert.equal(roleFamily('KilnCompact'), 'things')
})

test('ties and actions are verbs', () => {
  assert.equal(tieName('LIKED_POST_OF'), 'nodded to')
  assert.equal(tieName('NEGOTIATES_WITH'), 'negotiates with')
  assert.equal(tieName('SPONSORS'), 'sponsors')
  assert.equal(actionVerb('CREATE_POST'), 'speaks')
  assert.equal(actionVerb('do_nothing'), 'listens')
  assert.equal(actionVerb('UPVOTE'), 'nods')
  assert.ok(isActivityTie('POSTED'))
  assert.ok(!isActivityTie('OPPOSES'))
})

test('citizens have names, not handles', () => {
  assert.equal(citizenName('Despina Nomikou', 'despina_nomikou_466'), 'Despina Nomikou')
  assert.equal(citizenName('despina_nomikou_466'), 'Despina Nomikou')
  assert.equal(citizenName('', 'sand_105'), 'Sand')
  assert.equal(citizenName('@yes_for_psammos_12'), 'Yes For Psammos')
  assert.ok(isPlatformNode('Twitter'))
  assert.ok(!isPlatformNode('Marina Kavvadia'))
})

test('engine ids are stripped from log lines', () => {
  assert.equal(stripIds('Loading project proj_527f80721255...'), 'Loading project...')
  assert.equal(stripIds('Report saved: report_53d558ea0a3d'), 'Report saved')
  assert.equal(stripIds('Graph data loaded successfully.'), 'Graph data loaded successfully.')
})
