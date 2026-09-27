// Run: cd frontend && node --test src/parthenon/composeStage.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  FORMATS,
  ERAS,
  emptyStage,
  emptySpeaker,
  emptyAudienceMember,
  speakerFromFigure,
  stageProblems,
  stageHints,
  suggestQuestion,
  slugify,
  composeStageSeed,
  defaultNext,
} from './composeStage.js'

// Same rules as the scroll renderer in views/Home.vue, so the tests see what the page sees.
const escapeHtml = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const inline = (text) =>
  escapeHtml(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>')
const renderScroll = (markdown) => {
  const html = []
  for (const block of markdown.trim().split(/\n{2,}/)) {
    const lines = block.split('\n')
    if (lines.every((l) => l.startsWith('- '))) {
      html.push(`<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join('')}</ul>`)
      continue
    }
    for (const line of lines) {
      if (line.startsWith('## ')) html.push(`<h4>${inline(line.slice(3))}</h4>`)
      else if (line.startsWith('# ')) html.push(`<h3>${inline(line.slice(2))}</h3>`)
    }
    const prose = lines.filter((l) => !l.startsWith('#')).join(' ')
    if (prose) html.push(`<p>${inline(prose)}</p>`)
  }
  return html.join('')
}

const SECTIONS = [
  '## The matter',
  '## Who takes the stage',
  '## What was said',
  '## Who was listening',
  '## What happens next',
]

const figure = {
  id: 'socrates',
  name: 'Socrates',
  lived: '470-399 BC',
  from: 'Athens',
  known: 'the gadfly of Athens',
  ideas: 'Wisdom begins in knowing that you do not know.',
  aiLens: 'He asks whether a machine that answers everything has ever examined anything.',
  voice: 'plain words, dry irony, one question after another',
}

const validStage = (overrides = {}) => ({
  ...emptyStage(),
  title: 'The Tutor in Every Pocket',
  topic: 'Every child in the city now has an AI tutor.\n\nParents are divided.',
  speakers: [
    speakerFromFigure(figure),
    emptySpeaker({ name: 'Maya Chen', role: 'a teacher in a public school', ideas: 'Thinks tutors free her to teach.', words: 'I have thirty children.\n\nI finally have time for each of them.' }),
  ],
  audience: [
    emptyAudienceMember({ name: 'Parents', description: 'worried about screens and grades' }),
    emptyAudienceMember({ name: 'Students' }),
  ],
  question: 'Do parents let the tutors stay?',
  ...overrides,
})

const headingLines = (markdown) => markdown.split('\n').filter((l) => l.startsWith('#'))
const blocks = (markdown) => markdown.trim().split(/\n{2,}/)
const bulletLines = (markdown) => markdown.split('\n').filter((l) => l.startsWith('- '))

// ---------------------------------------------------------------------------

test('FORMATS and ERAS are the agreed lists', () => {
  assert.deepEqual(FORMATS.map((f) => f.id), ['speech', 'dialogue', 'panel', 'trial', 'assembly'])
  assert.deepEqual(ERAS.map((e) => e.id), ['ancient', 'now', 'future', 'custom'])
  for (const f of FORMATS) assert.ok(f.min <= f.max && f.label && f.blurb)
})

test('emptyStage has the expected shape and fresh arrays', () => {
  const stage = emptyStage()
  assert.deepEqual(stage, {
    title: '',
    format: 'panel',
    era: 'now',
    setting: ERAS.find((e) => e.id === 'now').setting,
    topic: '',
    speakers: [],
    audience: [],
    question: '',
    happensNext: '',
  })
  stage.speakers.push(emptySpeaker())
  assert.equal(emptyStage().speakers.length, 0)
})

test('emptySpeaker and emptyAudienceMember give unique keys and accept partials', () => {
  const a = emptySpeaker()
  const b = emptySpeaker({ name: 'Hypatia' })
  assert.equal(typeof a.key, 'string')
  assert.notEqual(a.key, b.key)
  assert.deepEqual({ ...a, key: 'x' }, { key: 'x', name: '', role: '', ideas: '', voice: '', words: '', figureId: null })
  assert.equal(b.name, 'Hypatia')
  assert.equal(emptySpeaker({ key: 'mine' }).key, 'mine')
  assert.ok(emptySpeaker({ key: undefined }).key)

  const m = emptyAudienceMember({ name: 'Nurses' })
  assert.deepEqual({ ...m, key: 'k' }, { key: 'k', name: 'Nurses', description: '' })
  assert.notEqual(emptyAudienceMember().key, emptyAudienceMember().key)
  const keys = new Set(Array.from({ length: 200 }, () => emptySpeaker().key))
  assert.equal(keys.size, 200)
})

test('speakerFromFigure maps a roster figure', () => {
  const s = speakerFromFigure(figure)
  assert.equal(s.name, 'Socrates')
  assert.equal(s.role, 'the gadfly of Athens (470-399 BC, Athens)')
  assert.equal(s.ideas, `${figure.ideas} ${figure.aiLens}`)
  assert.equal(s.voice, figure.voice)
  assert.equal(s.figureId, 'socrates')
  assert.equal(s.words, '')
  assert.ok(s.key)

  const sparse = speakerFromFigure({ id: 'x', name: 'X', known: 'a stranger' })
  assert.equal(sparse.role, 'a stranger')
  assert.equal(sparse.ideas, '')
  assert.doesNotThrow(() => speakerFromFigure(undefined))
  assert.equal(speakerFromFigure(null).figureId, null)
})

test('stageProblems: a valid stage has none', () => {
  assert.deepEqual(stageProblems(validStage()), [])
  assert.deepEqual(stageProblems(validStage({ topic: '' })), [], 'a question alone is enough')
  assert.deepEqual(stageProblems(validStage({ question: '' })), [], 'a topic alone is enough')
})

test('stageProblems: neither topic nor question', () => {
  const problems = stageProblems(validStage({ topic: '  ', question: '\n\n' }))
  assert.equal(problems.length, 1)
  assert.match(problems[0], /topic or a question/)
})

test('stageProblems: no named speakers', () => {
  const stage = validStage({ speakers: [emptySpeaker({ ideas: 'no name here' }), emptySpeaker()] })
  const problems = stageProblems(stage)
  assert.equal(problems.length, 1)
  assert.match(problems[0], /symposium needs at least two named speakers; none has a name yet/)

  const speech = stageProblems({ ...stage, format: 'speech' })
  assert.match(speech[0], /speech needs a named speaker/)
})

test('stageProblems: too few for the format', () => {
  const stage = validStage({ format: 'dialogue', speakers: [emptySpeaker({ name: 'Solo' }), emptySpeaker({ name: '   ' })] })
  const problems = stageProblems(stage)
  assert.equal(problems.length, 1)
  assert.match(problems[0], /dialogue needs two named speakers; only one has a name so far/)
})

test('stageProblems: too many for the format, with a format that fits', () => {
  const three = ['A', 'B', 'C'].map((name) => emptySpeaker({ name }))
  const speech = stageProblems(validStage({ format: 'speech', speakers: three }))
  assert.equal(speech.length, 1)
  assert.match(speech[0], /room for one speaker, not three\. Remove two or make it a symposium\./)

  const nine = Array.from({ length: 9 }, (_, i) => emptySpeaker({ name: `Speaker ${i + 1}` }))
  const panel = stageProblems(validStage({ format: 'panel', speakers: nine }))
  assert.equal(panel.length, 1)
  assert.match(panel[0], /room for eight speakers, not nine\. Remove one\.$/)

  const trial = stageProblems(validStage({ format: 'trial', speakers: nine.slice(0, 7) }))
  assert.match(trial[0], /trial has room for six speakers, not seven/)
})

test('stageProblems never throws on junk', () => {
  for (const junk of [undefined, null, 42, 'stage', {}, { speakers: 'x', audience: null }, { speakers: [null, 3, {}] }]) {
    assert.doesNotThrow(() => stageProblems(junk))
    assert.doesNotThrow(() => stageHints(junk))
    assert.doesNotThrow(() => suggestQuestion(junk))
  }
  assert.equal(stageProblems(undefined).length, 2)
})

test('stageHints: crowd, missing words, unnamed speakers, question', () => {
  assert.deepEqual(stageHints(validStage()).filter((h) => /crowd|question/i.test(h)), [])

  const bare = validStage({ audience: [], question: '' })
  const hints = stageHints(bare)
  assert.ok(hints.some((h) => /No crowd/.test(h) && /Oracle/.test(h)))
  assert.ok(hints.some((h) => h.startsWith('Socrates has no opening words yet')))
  assert.ok(!hints.some((h) => /Maya Chen.*no opening words/.test(h)), 'Maya has words')
  const q = hints.find((h) => h.startsWith('No question yet'))
  assert.ok(q && q.includes(suggestQuestion(bare)))

  const withUnnamed = validStage({ speakers: [...validStage().speakers, emptySpeaker({ ideas: 'nameless' })] })
  assert.ok(stageHints(withUnnamed).some((h) => h === 'One speaker without a name will be left off the stage.'))
  assert.deepEqual(stageProblems(withUnnamed), [], 'hints never block')
})

test('suggestQuestion is two sentences and tailored per format', () => {
  const base = validStage({ question: '', topic: 'AI tutors in every classroom' })
  const panel = suggestQuestion(base)
  assert.match(panel, /^After hearing Socrates and Maya Chen on “AI tutors in every classroom”, how does the crowd react/)
  assert.equal((panel.match(/\?/g) || []).length, 2)

  const trial = suggestQuestion({ ...base, format: 'trial' })
  assert.match(trial, /jury/)
  assert.match(trial, /verdict/)
  const assembly = suggestQuestion({ ...base, format: 'assembly' })
  assert.match(assembly, /assembly vote/)
  const dialogue = suggestQuestion({ ...base, format: 'dialogue' })
  assert.match(dialogue, /question each other/)
  const speech = suggestQuestion({ ...base, format: 'speech', speakers: [base.speakers[0]] })
  assert.match(speech, /^After hearing Socrates speak on/)
  for (const q of [trial, assembly, dialogue, speech]) assert.equal((q.match(/\?/g) || []).length, 2)

  const ancient = suggestQuestion({ ...base, era: 'ancient' })
  assert.match(ancient, /how does Athens react/)

  const many = suggestQuestion({ ...base, speakers: ['A', 'B', 'C', 'D', 'E'].map((name) => emptySpeaker({ name })) })
  assert.match(many, /A, B, C and two others/)
  assert.match(suggestQuestion({ topic: 'water' }), /^After hearing the speakers on “water”/)
})

test('slugify', () => {
  assert.equal(slugify('The Tutor in Every Pocket!'), 'the-tutor-in-every-pocket')
  assert.equal(slugify('Café & Crème: Ἀθῆναι'), 'cafe-and-creme')
  assert.equal(slugify("Socrates' Trial"), 'socrates-trial')
  assert.equal(slugify('ΣΩΚΡΑΤΗΣ'), 'stage')
  assert.equal(slugify(''), 'stage')
  assert.equal(slugify(undefined), 'stage')
  const long = slugify('word '.repeat(40))
  assert.ok(long.length <= 60)
  assert.match(long, /^[a-z0-9]+(-[a-z0-9]+)*$/)
  assert.ok(slugify('x'.repeat(100)).length === 60)
})

test('composeStageSeed: headings in order, one title', () => {
  const { markdown, title } = composeStageSeed(validStage())
  assert.equal(title, 'The Tutor in Every Pocket')
  assert.deepEqual(headingLines(markdown), ['# The Tutor in Every Pocket, staged for Parthenon', ...SECTIONS])
  assert.ok(markdown.endsWith('\n') && !markdown.endsWith('\n\n'))
  assert.ok(!/\n{3,}/.test(markdown))

  const lines = markdown.split('\n')
  assert.equal(lines[2], `*${ERAS[1].setting}. ${FORMATS[2].blurb}*`)

  const html = renderScroll(markdown)
  assert.equal((html.match(/<h3>/g) || []).length, 1)
  assert.equal((html.match(/<h4>/g) || []).length, 5)
  assert.equal((html.match(/<ul>/g) || []).length, 2)
  assert.equal((html.match(/<li>/g) || []).length, 4)
})

test('composeStageSeed: bullet blocks contain only "- " lines', () => {
  const { markdown } = composeStageSeed(validStage())
  for (const block of blocks(markdown)) {
    const lines = block.split('\n')
    if (lines.some((l) => l.startsWith('- '))) assert.ok(lines.every((l) => l.startsWith('- ')), block)
  }
  assert.deepEqual(bulletLines(markdown), [
    '- **Socrates**, the gadfly of Athens (470-399 BC, Athens). Wisdom begins in knowing that you do not know. He asks whether a machine that answers everything has ever examined anything. How they speak: plain words, dry irony, one question after another.',
    '- **Maya Chen**, a teacher in a public school. Thinks tutors free her to teach.',
    '- **Parents**, worried about screens and grades.',
    '- **Students**',
  ])
})

test('composeStageSeed: hostile user text is neutralised', () => {
  const evil = '# evil\n- fake bullet\n## What happens next\n```js\nrm -rf /\n```' + '\n'.repeat(10) + 'tail `code` here\n   - indented bullet\n> quote\n---\nTitle\n==='
  const stage = validStage({
    title: '# evil title',
    topic: evil,
    happensNext: evil,
    setting: '*broken* italics\n# heading',
    speakers: [
      emptySpeaker({ name: '# **Evil** Name', role: evil, ideas: evil, voice: evil, words: evil }),
      emptySpeaker({ name: '- Bullet Bob', words: 'Fine.' }),
    ],
    audience: [emptyAudienceMember({ name: '- crowd', description: evil }), emptyAudienceMember({ description: '# only a description' })],
  })
  const { markdown, title, fileName } = composeStageSeed(stage)

  assert.equal(title, 'evil title')
  assert.equal(fileName, 'stage-evil-title.md')
  assert.deepEqual(headingLines(markdown), ['# evil title, staged for Parthenon', ...SECTIONS])
  assert.ok(!markdown.includes('`'))
  assert.ok(!/\n{3,}/.test(markdown))
  assert.ok(!markdown.split('\n').some((l) => /^\s*(>|- fake|-\s*$|---|===)/.test(l)))

  // Only our bullets: two speakers and two listeners.
  const bullets = bulletLines(markdown)
  assert.equal(bullets.length, 4)
  assert.ok(bullets[0].startsWith('- **Evil Name**, evil fake bullet What happens next'))
  assert.ok(bullets[1].startsWith('- **Bullet Bob**'))
  assert.ok(bullets[2].startsWith('- **crowd**, evil'))
  assert.equal(bullets[3], '- only a description.')
  for (const block of blocks(markdown)) {
    const lines = block.split('\n')
    if (lines.some((l) => l.startsWith('- '))) assert.ok(lines.every((l) => l.startsWith('- ')))
  }

  // The setting sits inside one italic line with no stray asterisks.
  assert.equal(markdown.split('\n')[2], `*broken italics heading. ${FORMATS[2].blurb}*`)

  const html = renderScroll(markdown)
  assert.equal((html.match(/<h3>/g) || []).length, 1)
  assert.equal((html.match(/<h4>/g) || []).length, 5)
  assert.equal((html.match(/<ul>/g) || []).length, 2)
})

test('composeStageSeed: words keep paragraph breaks; missing words get the italic line', () => {
  const stage = validStage({
    speakers: [
      emptySpeaker({ name: 'Hypatia', words: 'First thought.\n\n\n\n\nSecond thought.\nSame paragraph.' }),
      emptySpeaker({ name: 'Turing' }),
    ],
  })
  const { markdown } = composeStageSeed(stage)
  assert.ok(markdown.includes('**Hypatia:**\n\nFirst thought.\n\nSecond thought.\nSame paragraph.\n\n'))
  assert.ok(markdown.includes('\n\n*Turing has not spoken yet; their views are described above.*\n\n'))
})

test('composeStageSeed: empty audience falls back to the city at large', () => {
  const { markdown } = composeStageSeed(validStage({ audience: [emptyAudienceMember(), emptyAudienceMember({ name: '  ' })] }))
  const after = markdown.split('## Who was listening\n\n')[1]
  assert.ok(after.startsWith('The city at large: citizens of every kind, who will decide for themselves.\n\n## What happens next'))
  assert.equal(bulletLines(markdown).length, 2)
})

test('composeStageSeed: imagined disclaimer only when a roster figure speaks', () => {
  const disclaimer = '*(Imagined for Parthenon, not a historical record.)*'
  assert.ok(composeStageSeed(validStage()).markdown.includes(`## What was said\n\n${disclaimer}\n\n`))
  const noFigures = validStage({ speakers: [emptySpeaker({ name: 'A' }), emptySpeaker({ name: 'B' })] })
  assert.ok(!composeStageSeed(noFigures).markdown.includes('Imagined for Parthenon'))
  // An unnamed figure is left off the stage, so it does not count either.
  const unnamedFigure = { ...noFigures, speakers: [...noFigures.speakers, emptySpeaker({ figureId: 'plato' })] }
  assert.ok(!composeStageSeed(unnamedFigure).markdown.includes('Imagined for Parthenon'))
})

test('composeStageSeed: default next steps per format', () => {
  const next = (format) => composeStageSeed(validStage({ format })).markdown.split('## What happens next\n\n')[1].trim()
  assert.equal(next('trial'), 'The jury retires to deliberate; the verdict will be read in three days.')
  assert.equal(next('assembly'), 'The assembly will vote at the end of the week.')
  assert.equal(next('panel'), 'Word spreads through the Agora and the Stoa over the following days.')
  assert.equal(
    composeStageSeed(validStage({ happensNext: 'The vote is on Friday.' })).markdown.split('## What happens next\n\n')[1],
    'The vote is on Friday.\n',
  )
})

test('composeStageSeed: fileName and title fallbacks', () => {
  assert.equal(composeStageSeed(validStage()).fileName, 'stage-the-tutor-in-every-pocket.md')

  const untitled = composeStageSeed(validStage({ title: '', topic: 'AI tutors in every classroom.\nMore detail.' }))
  assert.equal(untitled.title, 'A Symposium on AI tutors in every classroom')
  assert.equal(untitled.fileName, 'stage-a-symposium-on-ai-tutors-in-every-classroom.md')

  assert.equal(composeStageSeed(validStage({ title: '', topic: 'Should machines vote?', format: 'trial' })).title, 'A Trial over “Should machines vote?”')
  const sentenceTopic = validStage({ title: '', question: '', topic: 'Every child now has an AI tutor. Parents are divided.' })
  assert.equal(composeStageSeed(sentenceTopic).title, 'A Symposium on “Every child now has an AI tutor”')
  assert.match(composeStageSeed(sentenceTopic).question, /on “Every child now has an AI tutor”, how does/)
  assert.equal(composeStageSeed(validStage({ title: '', topic: '', format: 'dialogue' })).title, 'A Dialogue between Socrates and Maya Chen')
  assert.equal(composeStageSeed(undefined).title, 'A Symposium')
  assert.equal(composeStageSeed(undefined).fileName, 'stage-a-symposium.md')
  assert.equal(composeStageSeed(validStage({ title: 'Already for Parthenon' })).markdown.split('\n')[0], '# Already for Parthenon')
})

test('composeStageSeed: question falls back to the suggestion', () => {
  assert.equal(composeStageSeed(validStage({ question: '  Do parents let the tutors stay?  ' })).question, 'Do parents let the tutors stay?')
  const stage = validStage({ question: '   ' })
  assert.equal(composeStageSeed(stage).question, suggestQuestion(stage))
  assert.equal(composeStageSeed({ ...stage, question: undefined }).question, suggestQuestion(stage))
})

test('composeStageSeed: the matter falls back to the question when there is no topic', () => {
  const { markdown } = composeStageSeed(validStage({ topic: '' }))
  assert.ok(markdown.includes('## The matter\n\nDo parents let the tutors stay?\n\n## Who takes the stage'))
})

test('composeStageSeed: teleport note for figures brought into the present', () => {
  const note = 'stepped out of their own centuries'
  assert.ok(composeStageSeed(validStage({ era: 'now' })).markdown.includes(note))
  assert.ok(composeStageSeed(validStage({ era: 'future' })).markdown.includes(note))
  assert.ok(!composeStageSeed(validStage({ era: 'ancient', setting: '' })).markdown.includes(note))
  assert.ok(composeStageSeed(validStage({ era: 'ancient', setting: '' })).markdown.includes(`*${ERAS[0].setting}.`))
  const custom = composeStageSeed(validStage({ era: 'custom', setting: '' })).markdown
  assert.equal(custom.split('\n')[2], `*${FORMATS[2].blurb}*`)
})

test('composeStageSeed: long fields are capped', () => {
  const words = (n) => Array.from({ length: n }, (_, i) => `word${i}`).join(' ')
  const stage = validStage({
    title: words(100),
    topic: words(2000),
    question: words(1000),
    setting: words(200),
    speakers: [
      emptySpeaker({ name: 'N'.repeat(500), role: words(200), ideas: words(1000), voice: words(200), words: words(2000) }),
      emptySpeaker({ name: 'Second' }),
    ],
    audience: [emptyAudienceMember({ name: words(50), description: words(300) })],
  })
  const { title, question, markdown, fileName } = composeStageSeed(stage)
  assert.ok(title.length <= 120 && title.endsWith('…'))
  assert.ok(question.length <= 1500 && question.endsWith('…'))
  assert.ok(fileName.length <= 'stage-.md'.length + 60)

  const said = markdown.split('## What was said\n\n')[1].split('\n\n')
  const nameLine = said[0]
  assert.ok(nameLine.length <= 80 + '**:**'.length, nameLine)
  assert.ok(said[1].length <= 4000)

  const matter = markdown.split('## The matter\n\n')[1].split('\n\n## ')[0]
  assert.ok(matter.length <= 3000)
  assert.ok(markdown.split('\n')[2].length <= 300 + FORMATS[2].blurb.length + 10)

  const [speakerLine, , listenerLine] = bulletLines(markdown)
  assert.ok(speakerLine.length <= 80 + 200 + 1500 + 300 + 60, `${speakerLine.length}`)
  assert.ok(listenerLine.length <= 80 + 400 + 20, `${listenerLine.length}`)
  assert.deepEqual(stageProblems(stage), [])
})

test('composeStageSeed never throws on missing or odd fields', () => {
  for (const junk of [undefined, null, {}, { speakers: [null, { name: 42 }], audience: [undefined, { name: null }] }, { format: 'nope', era: 'nope' }]) {
    const out = composeStageSeed(junk)
    assert.equal(typeof out.markdown, 'string')
    assert.deepEqual(headingLines(out.markdown).slice(1), SECTIONS)
    assert.ok(out.fileName.startsWith('stage-') && out.fileName.endsWith('.md'))
    assert.ok(out.question.length > 0)
  }
  assert.ok(composeStageSeed({ speakers: [{ name: 42 }] }).markdown.includes('- **42**.'))
})

test('the form speaks Chinese: formats, ages, problems, hints and the next line', () => {
  for (const f of FORMATS) assert.ok(f.zh && f.zh.label && f.zh.blurb, f.id)
  for (const e of ERAS) assert.ok(e.zh && e.zh.label, e.id)

  const bare = { ...emptyStage(), format: 'dialogue', speakers: [], topic: '', question: '' }
  const en = stageProblems(bare)
  const zh = stageProblems(bare, 'zh')
  assert.equal(zh.length, en.length)
  assert.ok(zh.every((p) => /[\u4e00-\u9fff]/.test(p) && !/[a-z]{3,}/i.test(p)), zh.join(' | '))
  assert.match(zh[0], /^一场对话需要 2 位/)

  const three = ['A', 'B', 'C'].map((name) => emptySpeaker({ name, words: 'Hello.' }))
  const over = stageProblems({ ...emptyStage(), format: 'dialogue', speakers: three, topic: 'x' }, 'zh')
  assert.equal(over.length, 1)
  assert.match(over[0], /一场对话只容得下 2 位发言者，而不是 3 位。请移除 1 位，或改为一场研讨会。/)

  const silent = { ...emptyStage(), speakers: [emptySpeaker({ name: 'Socrates', figureId: 'socrates' })], audience: [], question: '' }
  const hints = stageHints(silent, 'zh', { suggestion: '雅典如何抉择？', nameOf: (s) => (s.figureId === 'socrates' ? '苏格拉底' : s.name) })
  assert.ok(hints.some((h) => h.startsWith('苏格拉底还没有开场白')))
  assert.ok(hints.some((h) => h === '还没有问题，所以城邦将被问到：雅典如何抉择？'))
  assert.ok(stageHints(silent).some((h) => h.startsWith('No question yet, so the city will be asked: ')))
  assert.ok(!stageHints(silent).some((h) => /Parthenon/.test(h)), 'the city, not the product, asks')

  assert.equal(defaultNext('trial'), 'The jury retires to deliberate; the verdict will be read in three days.')
  assert.equal(defaultNext('panel'), 'Word spreads through the Agora and the Stoa over the following days.')
  assert.match(defaultNext('assembly', 'zh'), /公民大会/)
  assert.match(defaultNext('nonsense', 'zh'), /消息/)
  for (const text of [...zh, ...over, ...hints, defaultNext('trial', 'zh')]) assert.ok(!/[\u2014\u2013]/.test(text), text)
})
