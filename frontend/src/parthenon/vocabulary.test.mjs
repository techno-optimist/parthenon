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

import { stanceWords, stanceKey, greekNumeral, cityWords, voiceOf } from './vocabulary.js'

test('stances read the same in every act', () => {
  assert.equal(stanceWords('supportive', 0.8), 'For')
  assert.equal(stanceWords('opposing', -0.9, 'phrase'), 'stood firmly against it')
  assert.equal(stanceWords('observer', 0), 'Watching')
  assert.equal(stanceKey('neutral', 0.6), 'undecided')
  assert.equal(stanceKey('', 0.6), 'for')
  assert.equal(stanceWords('supportive', 0.5, 'side', 'zh'), '支持')
})

test('greek numerals and city words', () => {
  assert.equal(greekNumeral(1), 'Α΄')
  assert.equal(greekNumeral(6), 'ΣΤ΄')
  assert.equal(cityWords('The simulated agents on Twitter disagreed in the simulation.'), 'The citizens on the Agora disagreed in the gathering.')
  assert.equal(cityWords('Reddit threads'), 'the Stoa threads')
})

test('voices by class and spaced names', () => {
  assert.equal(voiceOf('Aisystem'), 'machine')
  assert.equal(voiceOf('PublicOfficial'), 'official')
  assert.equal(voiceOf('Philosopher'), 'elder')
  assert.equal(voiceOf('Fisher'), 'common')
  assert.equal(citizenName('CitizenJury'), 'Citizen Jury')
})
