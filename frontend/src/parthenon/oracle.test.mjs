// Run: cd frontend && node --test src/parthenon/oracle.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BLANK,
  FEATURED_FIGURES,
  LAST_NUMERAL,
  MAX_SPEAKERS,
  STEPS,
  SUMMARY,
  TRIPOD,
  allProblems,
  audienceLabel,
  audienceLine,
  audienceSuggestions,
  bareName,
  blankSpeakers,
  clampStep,
  defaultAudience,
  defaultSetting,
  featuredFigures,
  figureForName,
  figureLine,
  firstBlank,
  firstOpenStep,
  fitFormat,
  greekNumeral,
  guestLine,
  hasBlank,
  isDefaultAudience,
  isOfferedSetting,
  isUntouchedTemplate,
  joinNames,
  localSetting,
  mattersFor,
  moreFigures,
  placesFor,
  placeSetting,
  quarrelQuestion,
  quarrelsFor,
  quarrelText,
  questionSource,
  questionToOffer,
  speakerLabel,
  stepProblems,
  stepValid,
  suggestQuestionFor,
  templateFills,
  tripodMark,
  wordsTemplate,
} from './oracle.js'
import { emptyAudienceMember, emptySpeaker, emptyStage, speakerFromFigure, stageProblems, suggestQuestion } from './composeStage.js'
import { figures, modernGuests } from './roster.js'
import { audiencePresets } from './audiences.js'

const socrates = figures.find((f) => f.id === 'socrates')
const plato = figures.find((f) => f.id === 'plato')
const codes = (list) => list.map((p) => p.code)

// A stage answered through all five questions.
const answered = (overrides = {}) => {
  const st = {
    ...emptyStage(),
    format: 'speech',
    era: 'ancient',
    setting: defaultSetting('ancient', 'en'),
    speakers: [{ ...speakerFromFigure(socrates), words: 'I say the unexamined life is not worth living.' }],
    audience: defaultAudience('ancient'),
  }
  st.question = quarrelQuestion(st, quarrelsFor('ancient')[0], 'en')
  return { ...st, ...overrides }
}

// ---------------------------------------------------------------------------
test('five steps in order, each filling its own part of the stage', () => {
  assert.deepEqual(STEPS.map((s) => s.id), ['who', 'where', 'words', 'listeners', 'question'])
  assert.deepEqual(STEPS.map((s) => s.numeral), ['Α΄', 'Β΄', 'Γ΄', 'Δ΄', 'Ε΄'])
  assert.equal(SUMMARY, 5)
  assert.equal(LAST_NUMERAL, 'Ε΄')
  const filled = STEPS.flatMap((s) => s.fills)
  for (const part of ['speakers', 'format', 'era', 'setting', 'speakers.words', 'audience', 'question']) {
    assert.ok(filled.includes(part), part)
  }
  assert.equal(new Set(filled).size, filled.length, 'no part is filled by two steps')
})

test('greekNumeral and clampStep', () => {
  assert.equal(greekNumeral(1), 'Α΄')
  assert.equal(greekNumeral(5), 'Ε΄')
  assert.equal(greekNumeral(6), 'ΣΤ΄')
  assert.equal(clampStep(-3), 0)
  assert.equal(clampStep(99), SUMMARY)
  assert.equal(clampStep('2'), 2)
  assert.equal(clampStep('junk'), 0)
})

test('an empty stage opens on the first question', () => {
  const st = emptyStage()
  assert.equal(firstOpenStep(st), 0)
  assert.deepEqual(codes(stepProblems(st, 'who')), ['whoNone'])
})

// ---------------------------------------------------------------------------
test('who: the six painted philosophers come first, the rest wait behind More', () => {
  assert.deepEqual(featuredFigures().map((f) => f.id), FEATURED_FIGURES)
  const more = moreFigures()
  assert.equal(more.length + FEATURED_FIGURES.length, figures.length)
  assert.ok(more.every((f) => !FEATURED_FIGURES.includes(f.id)))
})

test('who: fitFormat keeps a format that fits and chooses one that does', () => {
  assert.equal(fitFormat('panel', 1), 'speech')
  assert.equal(fitFormat('speech', 2), 'dialogue')
  assert.equal(fitFormat('dialogue', 3), 'panel')
  assert.equal(fitFormat('panel', 2), 'panel')
  assert.equal(fitFormat('trial', 4), 'trial')
  assert.equal(fitFormat('assembly', 1), 'assembly')
  assert.equal(fitFormat('trial', 1), 'speech')
  assert.equal(fitFormat('nonsense', 0), 'speech')
})

test('who: problems for no one, a repeated name, a format that no longer fits', () => {
  const one = { ...emptyStage(), format: 'speech', speakers: [emptySpeaker({ name: 'Maya' })] }
  assert.equal(stepValid(one, 'who'), true)

  const twins = { ...one, format: 'dialogue', speakers: [emptySpeaker({ name: 'Maya' }), emptySpeaker({ name: ' maya ' })] }
  assert.deepEqual(codes(stepProblems(twins, 'who')), ['whoRepeated'])
  assert.equal(stepProblems(twins, 'who')[0].params.name, 'Maya')

  const misfit = { ...one, format: 'trial' }
  assert.deepEqual(codes(stepProblems(misfit, 'who')), ['whoFormat'])
  assert.equal(stepValid({ ...misfit, format: fitFormat(misfit.format, 1) }, 'who'), true)

  const markers = { ...one, speakers: [emptySpeaker({ name: '**' }), emptySpeaker({ name: '- ' })] }
  assert.deepEqual(codes(stepProblems(markers, 'who')), ['whoNone'])
})

test('who: names in the visitor language; written roster names are recognised', () => {
  const sp = speakerFromFigure(socrates)
  assert.equal(speakerLabel(sp, 'en'), 'Socrates')
  assert.equal(speakerLabel(sp, 'zh'), '苏格拉底')
  assert.equal(speakerLabel(emptySpeaker({ name: '  Maya Chen: ' }), 'zh'), 'Maya Chen')
  assert.equal(speakerLabel(emptySpeaker({ name: 'The Machine', guestId: 'machine' }), 'zh'), '机器')
  assert.equal(figureForName('socrates').id, 'socrates')
  assert.equal(figureForName('  Plato ').id, 'plato')
  assert.equal(figureForName('Pythia').id, 'pythia')
  assert.equal(figureForName('柏拉图').id, 'plato')
  assert.equal(figureForName('Maya Chen'), null)
  assert.equal(bareName('# Maya'), 'Maya')
  assert.equal(bareName('---'), '')
})

test('joinNames in both languages', () => {
  assert.equal(joinNames(['A'], 'en'), 'A')
  assert.equal(joinNames(['A', 'B'], 'en'), 'A and B')
  assert.equal(joinNames(['A', 'B', 'C'], 'en'), 'A, B and C')
  assert.equal(joinNames(['甲', '乙', '丙'], 'zh'), '甲、乙和丙')
  assert.equal(joinNames([], 'en'), '')
})

// ---------------------------------------------------------------------------
test('where: each age has a default place and offered places', () => {
  assert.equal(defaultSetting('ancient', 'en'), 'Athens, 399 BC, on the steps below the Parthenon')
  assert.match(defaultSetting('ancient', 'zh'), /雅典/)
  assert.equal(defaultSetting('custom', 'en'), '')
  for (const era of ['ancient', 'now', 'future', 'custom']) {
    const places = placesFor(era)
    assert.ok(places.length >= 3, era)
    for (const p of places) {
      assert.ok(p.label && p.setting && p.zh.label && p.zh.setting, `${era}/${p.id}`)
      assert.ok(isOfferedSetting(placeSetting(p, 'en')))
      assert.ok(isOfferedSetting(placeSetting(p, 'zh')))
    }
  }
  assert.equal(isOfferedSetting(''), true)
  assert.equal(isOfferedSetting('My grandmother’s kitchen in Thessaloniki'), false)
})

test('where: localSetting translates offered places and keeps the visitor’s own', () => {
  assert.equal(localSetting(defaultSetting('now', 'en'), 'zh'), defaultSetting('now', 'zh'))
  assert.equal(localSetting(defaultSetting('ancient', 'zh'), 'en'), defaultSetting('ancient', 'en'))
  const agora = placesFor('ancient').find((p) => p.id === 'agora')
  assert.equal(localSetting(placeSetting(agora, 'en'), 'zh'), placeSetting(agora, 'zh'))
  assert.equal(localSetting('My own square', 'zh'), 'My own square')
  assert.equal(localSetting('', 'zh'), '')
})

test('where: a place is needed', () => {
  assert.equal(stepValid({ ...emptyStage(), setting: 'A city in 2040' }, 'where'), true)
  assert.deepEqual(codes(stepProblems({ ...emptyStage(), era: 'custom', setting: '  ' }, 'where')), ['whereNone'])
})

// ---------------------------------------------------------------------------
test('words: the template has blanks the visitor must fill', () => {
  for (const era of ['ancient', 'now', 'future', 'custom']) {
    for (const loc of ['en', 'zh']) {
      const t = wordsTemplate(era, loc)
      assert.ok(t.includes(BLANK), `${era}/${loc}`)
      assert.ok(hasBlank(t))
      assert.ok(isUntouchedTemplate(t))
      assert.ok(!/[—–]/.test(t), 'no dashes in the city’s words')
    }
  }
  const t = wordsTemplate('ancient', 'en')
  const [a, b] = firstBlank(t)
  assert.equal(t.slice(a, b), BLANK)
  assert.equal(firstBlank('no blanks here'), null)
  assert.equal(isUntouchedTemplate(t.replace(BLANK, 'the city is sick')), false)
})

test('words: templateFills only fills empty words of named speakers', () => {
  const st = {
    ...emptyStage(),
    era: 'now',
    speakers: [emptySpeaker({ name: 'Maya' }), emptySpeaker({ name: 'Plato', words: 'Mine already.' }), emptySpeaker({ name: '' })],
  }
  const fills = templateFills(st, 'en')
  assert.equal(fills.length, 1)
  assert.equal(fills[0].key, st.speakers[0].key)
  assert.equal(fills[0].words, wordsTemplate('now', 'en'))
})

test('words: blanks must be filled; a speaker the city knows nothing of needs words', () => {
  const maya = emptySpeaker({ name: 'Maya' })
  const soc = speakerFromFigure(socrates)
  const st = { ...emptyStage(), format: 'dialogue', speakers: [maya, soc] }
  assert.deepEqual(codes(stepProblems(st, 'words')), ['wordsNeeded'], 'a figure may speak from their own ideas')
  maya.words = wordsTemplate('now', 'en')
  assert.deepEqual(codes(stepProblems(st, 'words')), ['wordsBlank'])
  assert.equal(stepProblems(st, 'words')[0].params.name, 'Maya')
  assert.deepEqual(blankSpeakers(st), ['Maya'])
  maya.words = 'I say the tutors free me to teach.'
  assert.equal(stepValid(st, 'words'), true)
  soc.words = 'Tell me, ______ ?'
  assert.deepEqual(codes(stepProblems(st, 'words')), ['wordsBlank'])
})

// ---------------------------------------------------------------------------
test('listeners: suggestions by age, featured first, with Chinese names', () => {
  const ancient = audienceSuggestions('ancient')
  assert.ok(ancient.length >= 10)
  assert.equal(ancient.filter((a) => a.featured).length, 8)
  assert.ok(ancient.slice(0, 8).every((a) => a.featured))
  assert.ok(ancient.every((a) => a.name && a.description && a.zh.name))
  assert.ok(ancient.every((a) => a.zh.name !== a.name), 'every ancient group has a Chinese name')
  const now = audienceSuggestions('now')
  assert.ok(now.every((a) => a.zh.name !== a.name), 'every modern group has a Chinese name')
  assert.deepEqual(audienceSuggestions('future').map((a) => a.name), now.map((a) => a.name))
  assert.equal(audienceLabel('Metics', 'zh'), '外邦居民')
  assert.equal(audienceLabel('Metics', 'en'), 'Metics')
  assert.equal(audienceLabel('My neighbours', 'zh'), 'My neighbours')
})

test('listeners: three are seated by default, recognised until touched', () => {
  const seated = defaultAudience('ancient')
  assert.equal(seated.length, 3)
  assert.equal(new Set(seated.map((a) => a.key)).size, 3, 'fresh keys')
  assert.equal(isDefaultAudience(seated, 'ancient'), true)
  assert.equal(isDefaultAudience(seated, 'now'), false)
  assert.equal(isDefaultAudience(seated.slice(1), 'ancient'), false)
  const edited = seated.map((a, i) => (i === 0 ? { ...a, description: 'changed' } : a))
  assert.equal(isDefaultAudience(edited, 'ancient'), false)
  assert.equal(isDefaultAudience([], 'ancient'), false)
  assert.equal(stepValid({ ...emptyStage(), audience: [] }, 'listeners'), true, 'the city at large may listen')
  const crowd = Array.from({ length: 25 }, (_, i) => emptyAudienceMember({ name: `Group ${i}` }))
  assert.deepEqual(codes(stepProblems({ ...emptyStage(), audience: crowd }, 'listeners')), ['listenersTooMany'])
})

// ---------------------------------------------------------------------------
test('question: quarrels by age, including the two the brief names', () => {
  assert.ok(quarrelsFor('ancient').some((q) => q.question === 'Should the city pay citizens to attend the Assembly?'))
  assert.ok(quarrelsFor('now').some((q) => q.question === 'Should the city let a machine draft its laws?'))
  for (const era of ['ancient', 'now', 'future', 'custom']) {
    const list = quarrelsFor(era)
    assert.ok(list.length >= 4, era)
    for (const q of list) {
      assert.match(q.question, /\?$/)
      assert.match(quarrelText(q, 'zh'), /？$/)
      assert.ok(!/[—–]/.test(q.question + q.zh.question))
    }
  }
})

test('question: the suggestion starts from composeStage, with a Chinese twin', () => {
  const st = answered({ question: '' })
  assert.equal(suggestQuestionFor(st, 'en'), suggestQuestion(st))
  const zh = suggestQuestionFor(st, 'zh')
  assert.match(zh, /苏格拉底/)
  assert.match(zh, /雅典/)
  assert.ok(!/[—–]/.test(zh))
  for (const format of ['speech', 'dialogue', 'panel', 'trial', 'assembly']) {
    assert.ok(suggestQuestionFor({ ...st, format }, 'zh').length > 20, format)
  }
})

test('question: a quarrel carries the names on the floor', () => {
  const st = answered({ question: '' })
  const q = quarrelQuestion(st, quarrelsFor('ancient')[0], 'en')
  assert.match(q, /^Should the city pay citizens to attend the Assembly\? After hearing Socrates, how does Athens decide/)
  const zh = quarrelQuestion(st, quarrelsFor('ancient')[0], 'zh')
  assert.match(zh, /^城邦应该付钱让公民出席公民大会吗？听了苏格拉底的话之后，雅典/)
  const nobody = quarrelQuestion({ ...emptyStage(), era: 'now' }, quarrelsFor('now')[0], 'en')
  assert.match(nobody, /After hearing the speakers, how does the city decide/)
})

test('question: questionSource tells offered questions from the visitor’s own', () => {
  const st = answered()
  assert.equal(questionSource(st, 'en'), 'assembly-pay')
  assert.equal(questionSource({ ...st, question: suggestQuestionFor(st, 'en') }, 'en'), 'suggestion')
  assert.equal(questionSource({ ...st, question: 'My own question?' }, 'en'), null)
  assert.equal(questionSource({ ...st, question: '' }, 'en'), null)
})

test('question: questionToOffer fills an empty box and refreshes an untouched offer', () => {
  const st = answered({ question: '' })
  assert.equal(questionToOffer(st, 'en'), suggestQuestion(st))

  // An offered quarrel, then a second speaker: the untouched question follows the names.
  const offered = quarrelQuestion(st, quarrelsFor('ancient')[1], 'en')
  const two = { ...st, format: 'dialogue', question: offered, speakers: [...st.speakers, speakerFromFigure(plato)] }
  const fresh = questionToOffer(two, 'en', offered)
  assert.match(fresh, /^Should the city choose its officials by lot or by vote\? After hearing Socrates and Plato/)

  // The suggestion, untouched, follows too.
  const sugg = suggestQuestionFor(st, 'en')
  assert.match(questionToOffer({ ...two, question: sugg }, 'en', sugg), /Socrates and Plato/)

  // Already current, or the visitor's own words: leave it.
  assert.equal(questionToOffer({ ...st, question: sugg }, 'en', sugg), null)
  assert.equal(questionToOffer({ ...two, question: 'Mine?' }, 'en', offered), null)
})

test('question: a question is needed, without blanks', () => {
  assert.deepEqual(codes(stepProblems({ ...emptyStage(), question: ' ' }, 'question')), ['questionNone'])
  assert.deepEqual(codes(stepProblems({ ...emptyStage(), question: 'Should ___ ?' }, 'question')), ['questionBlank'])
  assert.equal(stepValid({ ...emptyStage(), question: 'Should we?' }, 'question'), true)
})

// ---------------------------------------------------------------------------
test('a stage answered through all five questions is one composeStage accepts', () => {
  const st = answered()
  assert.deepEqual(allProblems(st), [])
  assert.equal(firstOpenStep(st), SUMMARY)
  assert.deepEqual(stageProblems(st), [])
})

test('whenever every step is answered, composeStage has no problems either', () => {
  const speakerSets = [
    [emptySpeaker({ name: 'Maya', words: 'Hear me.' })],
    [speakerFromFigure(socrates), emptySpeaker({ name: 'Maya', words: 'Hear me.' })],
    [speakerFromFigure(socrates), speakerFromFigure(plato), emptySpeaker({ name: 'Ion', role: 'a rhapsode' })],
    [],
  ]
  for (const format of ['speech', 'dialogue', 'panel', 'trial', 'assembly']) {
    for (const speakers of speakerSets) {
      for (const question of ['', 'Should we?']) {
        const st = { ...emptyStage(), format, speakers, question, setting: 'Somewhere' }
        if (allProblems(st).length === 0) assert.deepEqual(stageProblems(st), [], `${format}/${speakers.length}/${question}`)
        const fitted = { ...st, format: fitFormat(format, speakers.filter((s) => s.name).length) }
        if (speakers.length && question) assert.deepEqual(allProblems(fitted), [], `fitted ${format}/${speakers.length}`)
      }
    }
  }
})

test('firstOpenStep finds the first unanswered question', () => {
  assert.equal(firstOpenStep(answered({ setting: '' })), 1)
  assert.equal(firstOpenStep(answered({ question: '' })), 4)
  const blank = answered()
  blank.speakers = [{ ...blank.speakers[0], words: wordsTemplate('ancient', 'en') }]
  assert.equal(firstOpenStep(blank), 2)
  assert.deepEqual(allProblems(blank).map((p) => [p.stepId, p.code]), [['words', 'wordsBlank']])
})

test('nothing throws on junk', () => {
  for (const junk of [null, undefined, 42, 'x', [], { speakers: 'no', audience: {} }]) {
    for (const st of STEPS) assert.ok(Array.isArray(stepProblems(junk, st.id)))
    assert.ok(Array.isArray(allProblems(junk)))
    assert.equal(typeof suggestQuestionFor(junk, 'zh'), 'string')
    assert.equal(typeof suggestQuestionFor(junk, 'en'), 'string')
    assert.equal(questionToOffer(junk, 'en') === null || typeof questionToOffer(junk, 'en') === 'string', true)
  }
  assert.equal(speakerLabel(null, 'en'), '')
  assert.equal(MAX_SPEAKERS, 8)
})

const DASHES = /[\u2014\u2013]/

test('every figure, guest and group carries its Chinese words, with no dashes', () => {
  for (const f of figures) {
    assert.ok(f.zh && f.zh.name && f.zh.known && f.zh.lived, f.id)
    assert.ok(/[\u4e00-\u9fff]/.test(f.zh.known), `${f.id} known is Chinese`)
    assert.ok(!DASHES.test(f.zh.name + f.zh.known + f.zh.lived + f.known), f.id)
  }
  for (const g of modernGuests) {
    assert.ok(g.zh && g.zh.name && g.zh.role, g.id)
    assert.ok(!DASHES.test(g.zh.name + g.zh.role + g.role), g.id)
  }
  for (const pool of Object.values(audiencePresets)) {
    for (const p of pool) {
      assert.ok(p.zh && p.zh.name && p.zh.description, p.name)
      assert.notEqual(p.zh.description, p.description)
      assert.ok(!DASHES.test(p.zh.name + p.zh.description + p.description), p.name)
    }
  }
})

test('the Oracle says who a figure, a guest or a group is, in either language', () => {
  const en = figureLine(socrates, 'en')
  assert.equal(en.name, 'Socrates')
  assert.equal(en.when, 'c. 470-399 BC')
  assert.match(en.text, /gadfly/)
  const zh = figureLine(socrates, 'zh')
  assert.equal(zh.name, '苏格拉底')
  assert.match(zh.text, /牛虻/)
  assert.equal(figureLine(null, 'en'), null)

  const machine = modernGuests.find((g) => g.id === 'machine')
  assert.equal(guestLine(machine, 'en').text, machine.role)
  assert.equal(guestLine(machine, 'zh').name, '机器')
  assert.match(guestLine(machine, 'zh').text, /人工智能/)

  assert.match(audienceLine({ name: 'Metics' }, 'en').text, /^Free foreigners/)
  assert.equal(audienceLine({ name: 'Metics' }, 'zh').name, '外邦居民')
  assert.match(audienceLine({ name: 'Metics' }, 'zh').text, /外邦人/)
  assert.deepEqual(audienceLine({ name: 'My neighbours', description: 'Next door.' }, 'zh'), { name: 'My neighbours', when: '', text: 'Next door.' })
  assert.equal(audienceLine({ name: '  ' }, 'en'), null)

  assert.equal(figureForName('亚里士多德').id, 'aristotle')
  assert.ok(audienceSuggestions('now').every((g) => g.zh.description && g.zh.description !== g.description))
})

test('the full form takes up the quarrels of its own age', () => {
  for (const era of ['ancient', 'future', 'custom']) {
    const en = mattersFor(era, 'en')
    const zh = mattersFor(era, 'zh')
    assert.equal(en.length, quarrelsFor(era).length, era)
    assert.equal(zh.length, en.length)
    for (let i = 0; i < en.length; i++) {
      assert.ok(en[i].label && en[i].topic.length > 40, `${era}/${en[i].id}`)
      assert.ok(/[\u4e00-\u9fff]/.test(zh[i].label + zh[i].topic), `${era}/${zh[i].id} zh`)
      assert.ok(!DASHES.test(en[i].label + en[i].topic + zh[i].label + zh[i].topic))
    }
  }
  assert.ok(mattersFor('ancient', 'en').every((m) => !/\bAI\b|machine/i.test(m.topic)), '399 BC has no machines')
  assert.deepEqual(mattersFor('now', 'en'), [], "today's quarrels live in the locale files")
  assert.deepEqual(mattersFor('nowhere', 'en'), [])
})

test("the Oracle's mark is the tripod at Delphi, not a kettle grill", () => {
  const { legs, lip, bowl, rings, ringR, groundY, size } = TRIPOD
  const lean = ([x1, y1, x2, y2]) => (Math.atan2(Math.abs(x2 - x1), y2 - y1) * 180) / Math.PI
  // Three long straight legs, standing nearly upright
  for (const leg of [legs.left, legs.right, legs.rear]) assert.ok(lean(leg) < 6, `leans ${lean(leg).toFixed(1)} degrees`)
  for (const leg of [legs.left, legs.right]) {
    assert.ok(leg[3] - leg[1] > size * 0.6, 'the front legs run most of the height')
    assert.ok(leg[1] < lip.cy - lip.ry, 'and rise past the lip to carry the handles')
  }
  assert.ok(legs.rear[1] > bowl.top && legs.rear[3] < legs.left[3], 'the third leg hangs from the bowl, behind')
  // A deep cauldron with an open mouth: deeper than a half sphere, the lip an ellipse, no lid
  assert.ok(bowl.bottom - bowl.top > (bowl.right - bowl.left) / 2)
  assert.ok(lip.ry > 0 && lip.ry < lip.rx / 4)
  const straightRuns = TRIPOD.parts.filter((p) => /[HhLl]/.test(p.d)).map((p) => p.id)
  assert.deepEqual(straightRuns.sort(), ['cleft', 'paws'], 'only the ground and the paws lie flat')
  // The ring handles stand high, each on the top of a front leg
  for (const [cx, cy] of rings) {
    assert.ok(cy + ringR <= lip.cy - lip.ry, 'above the lip')
    assert.ok([legs.left, legs.right].some(([x, y]) => Math.abs(x - cx) < 0.2 && Math.abs(y - (cy + ringR)) < 0.2))
  }
  // The vapour rises from the cleft below and thins away before it reaches the bowl
  const threads = TRIPOD.parts.filter((p) => p.vapour)
  assert.equal(threads.length, 2)
  for (const p of threads) {
    const n = p.d.match(/-?\d*\.?\d+/g).map(Number)
    const [y0, y1] = [n[1], n[n.length - 1]]
    assert.ok(y0 > groundY, 'out of the rock')
    assert.ok(y1 < y0 && y1 > bowl.bottom, 'toward the bowl, never above it')
  }
})

test('tripodMark draws the same tripod at every size', () => {
  const ids = (list) => list.map((p) => p.id)
  assert.equal(new Set(ids(TRIPOD.parts)).size, TRIPOD.parts.length)
  assert.deepEqual(ids(tripodMark()), ids(TRIPOD.parts))
  assert.deepEqual(ids(tripodMark('still')).filter((id) => id.startsWith('vapour')), ['vapour'])
  const small = ids(tripodMark('small'))
  for (const id of ['legs', 'rear-leg', 'lebes', 'lip', 'rings']) assert.ok(small.includes(id), id)
  for (const id of ['vapour', 'vapour-late', 'cleft', 'paws']) assert.ok(!small.includes(id), id)
  assert.ok(Object.isFrozen(TRIPOD.parts) && TRIPOD.parts.every((p) => Object.isFrozen(p)))
  tripodMark().pop()
  assert.equal(tripodMark().length, TRIPOD.parts.length, 'each call hands out its own list')
})

import { stageForRecord } from './oracle.js'
import { composeStageSeed } from './composeStage.js'

// A stage a visitor reading Chinese built from the Oracle's offers alone.
const offeredInChinese = () => {
  const st = {
    ...emptyStage(),
    format: 'speech',
    era: 'ancient',
    setting: defaultSetting('ancient', 'zh'),
    topic: mattersFor('ancient', 'zh')[0].topic,
    speakers: [{ ...speakerFromFigure(socrates), words: 'I say the unexamined life is not worth living.' }],
    audience: defaultAudience('ancient'),
  }
  st.question = quarrelQuestion(st, quarrelsFor('ancient')[0], 'zh')
  return st
}
const HAN = /[㐀-鿿　-〿！-･]/

test('record: the Oracle\'s offers go into an English record in English', () => {
  const st = offeredInChinese()
  const kept = stageForRecord(st, 'zh', 'en')
  assert.equal(kept.topic, mattersFor('ancient', 'en')[0].topic)
  assert.equal(kept.setting, defaultSetting('ancient', 'en'))
  assert.equal(kept.question, quarrelQuestion(kept, quarrelsFor('ancient')[0], 'en'))
  const seed = composeStageSeed(kept)
  assert.ok(!HAN.test(seed.markdown), seed.markdown)
  assert.ok(!HAN.test(seed.question), seed.question)
  // The visitor's stage is left as they see it.
  assert.equal(st.setting, defaultSetting('ancient', 'zh'))
  assert.ok(HAN.test(st.question))

  // The Oracle's own question, and one of today's matters from the locale files.
  const today = { ...st, era: 'now', setting: defaultSetting('now', 'zh'), topic: '逝者聊天机器人的话题', question: '' }
  today.question = suggestQuestionFor(today, 'zh')
  const sparks = { en: ['Griefbots: the dead speak again.'], zh: ['逝者聊天机器人的话题'] }
  const now = stageForRecord(today, 'zh', 'en', { sparks })
  assert.equal(now.topic, 'Griefbots: the dead speak again.')
  assert.equal(now.question, suggestQuestion(now))
  assert.ok(!HAN.test(composeStageSeed(now).markdown))
})

test('record: what the visitor wrote stays as written, and nothing changes in their own language', () => {
  const st = { ...offeredInChinese(), topic: '我自己写的事情', setting: '我家门口', question: '我自己的问题？' }
  const kept = stageForRecord(st, 'zh', 'en')
  assert.equal(kept.topic, '我自己写的事情')
  assert.equal(kept.setting, '我家门口')
  assert.equal(kept.question, '我自己的问题？')
  // A record in the visitor's own language, or none named: the stage as it stands.
  const same = offeredInChinese()
  assert.deepEqual(stageForRecord(same, 'zh', 'zh'), same)
  assert.deepEqual(stageForRecord(same, 'zh', null), same)
  assert.notEqual(stageForRecord(same, 'zh', 'zh'), same)
  // An English visitor on steps that keep Chinese records.
  const en = answered()
  const zh = stageForRecord(en, 'en', 'zh')
  assert.equal(zh.question, quarrelQuestion(en, quarrelsFor('ancient')[0], 'zh'))
  assert.equal(zh.setting, defaultSetting('ancient', 'zh'))
})

test('record: an offer the Oracle put in the box counts after the names have changed', () => {
  const st = offeredInChinese()
  const offered = st.question
  const two = { ...st, format: 'dialogue', speakers: [...st.speakers, speakerFromFigure(plato)] }
  // The box still holds the offer made for Socrates alone.
  assert.equal(stageForRecord(two, 'zh', 'en').question, offered)
  const kept = stageForRecord(two, 'zh', 'en', { lastOffered: offered })
  assert.match(kept.question, /^Should the city pay citizens to attend the Assembly\? After hearing Socrates and Plato/)
})
