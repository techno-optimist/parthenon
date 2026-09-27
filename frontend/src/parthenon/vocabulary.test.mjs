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

import { setVocabularyLocale, getVocabularyLocale, followVocabularyLocale, RUN_LENGTHS, runLengthMinutes } from './vocabulary.js'

// Every zh case restores English, so the order of tests never matters.
const inChinese = (fn) => {
  const before = getVocabularyLocale()
  setVocabularyLocale('zh')
  try { fn() } finally { setVocabularyLocale(before) }
}

test('the words follow the visitor into Chinese', () => {
  assert.equal(getVocabularyLocale(), 'en')
  inChinese(() => {
    assert.equal(getVocabularyLocale(), 'zh')
    assert.equal(platformName('twitter'), '广场')
    assert.equal(platformName('Reddit', 'title'), '柱廊')
    assert.equal(platformName('mastodon'), 'mastodon')
    assert.equal(entityTypeName('Person'), '市民')
    assert.equal(entityTypeName('PublicOfficial'), '公职人员')
    assert.equal(entityTypeName('Aisystem'), 'AI 系统')
    assert.equal(entityTypeName('RetiredQuarryman'), '退休采石工')
    assert.equal(entityTypeName('AIResearchLab'), 'AI 研究实验室')
    assert.equal(entityTypeName('Entity'), '')
    assert.equal(entityTypeName('渔民'), '渔民')
    assert.equal(roleLabel('PublicOfficial'), '公职人员')
    assert.equal(roleLabel('Kilnwright'), 'Kilnwright')
    assert.equal(tieName('LIKED_POST_OF'), '点头赞同')
    assert.equal(tieName('OPPOSES'), '反对')
    assert.equal(tieName('SPONSORS'), '资助')
    assert.equal(actionVerb('CREATE_POST'), '发言')
    assert.equal(actionVerb('do_nothing'), '静听')
    assert.equal(actionVerb('SOMETHING_NEW'), '有所行动')
    assert.equal(stanceWords('supportive', 0.8), '支持')
    assert.equal(stanceWords('opposing', -0.9, 'phrase'), '坚决反对')
    assert.equal(stanceWords('observer', 0), '旁观')
  })
})

test('an explicit locale still wins over the visitor\'s', () => {
  inChinese(() => {
    assert.equal(platformName('twitter', 'name', 'en'), 'the Agora')
    assert.equal(entityTypeName('LocalBusinessOwner', 'en'), 'local business owner')
    assert.equal(roleLabel('PublicOfficial', 'en'), 'Public official')
    assert.equal(tieName('NEGOTIATES_WITH', 'en'), 'negotiates with')
    assert.equal(actionVerb('UPVOTE', 'en'), 'nods')
    assert.equal(stanceWords('supportive', 0.8, 'side', 'en'), 'For')
  })
  assert.equal(platformName('twitter', 'name', 'zh'), '广场')
  assert.equal(entityTypeName('Fisher', 'zh-CN'), '渔民')
  assert.equal(actionVerb('REPOST', 'zh'), '复述')
  assert.equal(platformName('twitter', 'name', 'fr'), 'the Agora')
})

test('families and voices do not change with the language', () => {
  inChinese(() => {
    assert.equal(roleFamily('ParentsCoalition'), 'movements')
    assert.equal(roleFamily('AIResearchLab'), 'machines')
    assert.equal(roleFamily('KilnCompact'), 'things')
    assert.equal(voiceOf('Philosopher'), 'elder')
    assert.equal(voiceOf('PublicOfficial'), 'official')
    assert.equal(voiceOf('Fisher'), 'common')
  })
})

test('run lengths and city words in Chinese', () => {
  assert.equal(RUN_LENGTHS[0].minutes, '8 to 12')
  assert.equal(RUN_LENGTHS[3].minutes, '2 to 3 hours')
  inChinese(() => {
    assert.equal(RUN_LENGTHS[0].minutes, '8 至 12')
    // A week is told in hours in Chinese too, and names its own unit.
    assert.equal(RUN_LENGTHS[3].minutes, '2 至 3 小时')
    assert.ok(spansHours(RUN_LENGTHS[3].minutes))
    // The shorter lengths stay in minutes, so no caller doubles a unit.
    for (const l of RUN_LENGTHS.slice(0, 3)) assert.ok(!spansHours(l.minutes), l.id)
    assert.equal({ ...RUN_LENGTHS[1] }.minutes, '15 至 25')
    assert.equal(cityWords('模拟智能体在 Twitter 上争论'), '市民在广场上争论')
    assert.equal(cityWords('知识图谱已构建，预测报告已生成'), '雅典之网已构建，编年史已生成')
    // English engine text stays English.
    assert.equal(cityWords('The simulated agents on Twitter disagreed in the simulation.'), 'The citizens on the Agora disagreed in the gathering.')
  })
  assert.equal(runLengthMinutes('week', 'zh'), '2 至 3 小时')
  assert.ok(spansHours(runLengthMinutes('week', 'en')))
  assert.equal(runLengthMinutes(RUN_LENGTHS[2], 'en'), '45 to 70')
  assert.equal(cityWords('模拟智能体', 'en'), '模拟智能体')
})

test('a live locale source is followed, and can be let go', () => {
  let live = 'zh'
  followVocabularyLocale(() => live)
  try {
    assert.equal(platformName('twitter'), '广场')
    live = 'en'
    assert.equal(platformName('twitter'), 'the Agora')
    assert.equal(getVocabularyLocale(), 'en')
    live = 'zh-CN'
    assert.equal(tieName('OPPOSES'), '反对')
  } finally {
    followVocabularyLocale(null)
    setVocabularyLocale('en')
  }
  assert.equal(platformName('twitter'), 'the Agora')
})

import { textLang, spansHours, undash, smartQuotes, gatheringStanding, bestGathering, wayLinks, standingRoute } from './vocabulary.js'

test('the Scribe speaks of the Agora and the Stoa, and reckons rather than predicts', () => {
  assert.equal(
    cityWords('Public discourse conducted largely through agora-style exchanges that appear on the platforms representing civic conversation.'),
    'Public discourse conducted largely through agora-style exchanges that appear in the Agora and the Stoa.'
  )
  assert.equal(cityWords('At the same time, agents identify potential benefits.'), 'At the same time, citizens identify potential benefits.')
  assert.equal(cityWords('Agents identify a risk.'), 'Citizens identify a risk.')
  assert.equal(cityWords('The debate spread across the platforms.'), 'The debate spread across the Agora and the Stoa.')
  assert.equal(cityWords('Both platforms saw the same split.'), 'The Agora and the Stoa saw the same split.')
  assert.equal(cityWords('The prediction in this interval holds.'), 'The reckoning in this interval holds.')
  assert.equal(cityWords('What the freeze predicts'), 'What the freeze foretells')
  assert.equal(cityWords('Predictions differ.'), 'Reckonings differ.')
  // Names the engine wrote are replaced as they stand, mid-sentence too.
  assert.equal(cityWords('Talk on Twitter grew.'), 'Talk on the Agora grew.')
})

test('the language of a gathering\'s own text', () => {
  assert.equal(textLang('The Hemlock Horizon: Athens\' Thirty-Day Reckoning'), 'en')
  assert.equal(textLang('雅典的三十天：一场审判'), 'zh')
  assert.equal(textLang('SB 1180 法案在参议院'), 'zh')
  assert.equal(textLang(''), 'en')
  assert.equal(textLang('Marina Kavvadia (玛丽娜) spoke on the quarry steps for an hour.'), 'en')
  // An English chapter quoting a few citizens in Chinese is still English.
  assert.equal(textLang(`${'In the thirty days, Crito moves swiftly from public lament to concrete action. '.repeat(30)}${'克力同计划贿赂狱卒让苏格拉底逃走。'.repeat(20)}`), 'en')
  assert.equal(textLang('玛丽娜·卡瓦迪亚在采石场的台阶上发言，Sand 随后回应。'), 'zh')
})

test('spans of hours carry their own unit in both languages', () => {
  assert.ok(spansHours('2 to 3 hours'))
  assert.ok(spansHours('2 至 3 小时'))
  assert.ok(!spansHours('15 to 25'))
  assert.ok(!spansHours('15 至 25'))
})

test('cast lists lose their dashes on the page', () => {
  assert.equal(
    undash('- **Plato**, testifying for SB 1180 — backs the labels — but insists on education.'),
    '- **Plato**, testifying for SB 1180: backs the labels, but insists on education.'
  )
  assert.equal(undash('No dash here.'), 'No dash here.')
  assert.equal(undash('A range 1990–2000 stays.'), 'A range 1990–2000 stays.')
})

test('quotes are set as a printer would', () => {
  assert.equal(smartQuotes('It was "not nothing," she said.'), 'It was “not nothing,” she said.')
  assert.equal(smartQuotes('"A written answer..." (the Scribe)'), '“A written answer...” (the Scribe)')
  assert.equal(smartQuotes('Athens\' youth and the city\'s \'best\' men'), 'Athens’ youth and the city’s ‘best’ men')
})

const ROW_ARGUED = {
  project_id: 'proj_527f80721255', simulation_id: 'sim_2c79002f1b0c', created_at: '2026-09-25T18:45:07',
  current_round: 17, total_rounds: 40, runner_status: 'stopped', status: 'stopped',
  report_id: 'report_53d558ea0a3d', report_status: 'completed', profiles_count: 20
}
const ROW_ORPHAN = {
  project_id: 'proj_527f80721255', simulation_id: 'sim_527a256e40af', created_at: '2026-09-25T23:17:30',
  current_round: 0, total_rounds: 168, runner_status: 'idle', status: 'ready', report_id: null, report_status: null, profiles_count: 20
}

test('where a gathering stands, and the Way it opens', () => {
  const s = gatheringStanding(ROW_ARGUED)
  assert.equal(s.act, 4)
  assert.ok(s.argued && s.written)
  assert.equal(gatheringStanding(ROW_ORPHAN).act, 2)
  assert.ok(!gatheringStanding(ROW_ORPHAN).argued)
  // A Chronicle already written is never hidden behind a later night left unargued.
  assert.equal(bestGathering([ROW_ORPHAN, ROW_ARGUED]).simulation_id, 'sim_2c79002f1b0c')
  assert.equal(bestGathering([]), null)
  const links = wayLinks(ROW_ARGUED)
  assert.deepEqual(Object.keys(links), ['1', '2', '3', '4', '5'])
  assert.deepEqual(links[5], { name: 'Interaction', params: { reportId: 'report_53d558ea0a3d' } })
  assert.deepEqual(Object.keys(wayLinks(ROW_ORPHAN)), ['1', '2'])
  assert.deepEqual(wayLinks(null, { projectId: 'proj_x' }), { 1: { name: 'Process', params: { projectId: 'proj_x' } } })
  assert.deepEqual(standingRoute(ROW_ARGUED), { name: 'Report', params: { reportId: 'report_53d558ea0a3d' } })
  assert.deepEqual(standingRoute(ROW_ORPHAN), { name: 'Simulation', params: { simulationId: 'sim_527a256e40af' } })
  // A Chronicle the Scribe could not finish still opens its page, but not the Symposium.
  const failed = { ...ROW_ARGUED, report_status: 'failed' }
  assert.equal(gatheringStanding(failed).act, 3)
  assert.ok(!wayLinks(failed)[5])
  assert.ok(wayLinks(failed)[4])
})
