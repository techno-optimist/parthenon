import test from 'node:test'
import assert from 'node:assert/strict'
import { createProposalSession, validateProposal, proposalSeed, reviewProblems } from './oracleSetup.js'
import { audiencePresets } from './audiences.js'

const sample = () => ({
  stage: { title: 'The tutor vote', format: 'dialogue', era: 'now', setting: 'A hypothetical council', topic: 'AI tutors',
    speakers: [
      { figureId: 'socrates', name: 'Socrates', role: 'Questioner', ideas: 'Examine knowledge', voice: 'Questions', words: 'What is learning?' },
      { figureId: 'aristotle', name: 'Aristotle', role: 'Philosopher', ideas: 'Practice', voice: 'Precise', words: 'Learning takes practice.' },
    ],
    audience: audiencePresets.now.slice(0, 8).map(a => ({ name: a.name, description: 'A fictional role with a stake.' })),
    question: 'Who changes their mind?', happensNext: 'The council votes tomorrow.',
  }, runLength: 'day', assumptions: ['A hypothetical vote.'], sourceBasis: 'hypothetical',
})

test('validates complete supported stage and rejects unsafe or malformed output', () => {
  assert.deepEqual(validateProposal(sample()), sample())
  for (const mutate of [p => p.runLength = 'forever', p => p.stage.format = 'bad', p => p.stage.speakers[0].name = 'Private Person', p => p.stage.question = '', p => p.stage.audience = []]) {
    const p = sample(); mutate(p)
    assert.throws(() => validateProposal(p))
  }
})

test('a proposal is local review state and creates no file or run until handoff', async () => {
  const session = createProposalSession({ ask: async () => ({ success: true, data: { proposal: sample() } }) })
  assert.equal(await session.request({ brief: 'AI tutors' }), true)
  assert.equal(session.state.proposal.stage.title, 'The tutor vote')
  assert.equal(session.state.pending, false)
})

test('edited work survives stale response and cancellation even if provider ignores abort', async () => {
  let resolve
  const session = createProposalSession({ ask: () => new Promise(r => { resolve = r }) })
  session.state.proposal = sample()
  const pending = session.request({ brief: 'AI tutors' })
  session.edited()
  session.state.proposal.stage.title = 'My title'
  resolve({ success: true, data: { proposal: sample() } })
  assert.equal(await pending, false)
  assert.equal(session.state.proposal.stage.title, 'My title')
})

test('failure preserves proposal; repeated explicit click cannot duplicate in-flight request', async () => {
  let reject, calls = 0
  const session = createProposalSession({ ask: () => { calls++; return new Promise((_, r) => { reject = r }) } })
  session.state.proposal = sample()
  const pending = session.request({ brief: 'Refine', current: sample() })
  assert.equal(await session.request({ brief: 'Refine' }), false)
  reject(new Error('The Oracle is unavailable.'))
  assert.equal(await pending, false)
  assert.equal(calls, 1)
  assert.equal(session.state.proposal.stage.title, 'The tutor vote')
  assert.match(session.state.error, /unavailable/)
})

test('stale invite failure is kept as a recoverable access code without automatic resend', async () => {
  const err = Object.assign(new Error('Bring the word.'), { cityCode: 'invite_needed' })
  const session = createProposalSession({ ask: async () => { throw err } })
  await session.request({ brief: 'AI tutors' })
  assert.equal(session.state.cityCode, 'invite_needed')
  assert.equal(session.state.pending, false)
})

test('clarification preserves existing review and malformed replies do not overwrite it', async () => {
  const session = createProposalSession({ ask: async () => ({ data: { clarification: 'Which decision?' } }) })
  session.state.proposal = sample()
  await session.request({ brief: 'Brief' })
  assert.equal(session.state.clarification, 'Which decision?')
  assert.equal(session.state.proposal.stage.title, 'The tutor vote')
})

test('handoff marks generated speech and scenario basis as simulation', () => {
  const seed = proposalSeed(sample())
  assert.match(seed.markdown, /Simulation scenario/)
  assert.match(seed.markdown, /Imagined for Parthenon/)
  assert.match(seed.markdown, /hypothetical/i)
  assert.match(seed.markdown, /fictional/i)
})

test('handoff retains accepted source excerpts including their final reference', () => {
  const context = 'A supplied excerpt. '.repeat(350) + '\nReference: https://example.org/final-reference'
  const seed = proposalSeed({ ...sample(), sourceBasis: 'user-supplied' }, context)
  assert.match(seed.markdown, /https:\/\/example.org\/final-reference/)
  assert.match(seed.markdown, /unverified/)
})

test('handoff never splits a source URL across paragraphs and labels newly attached context', () => {
  const url = 'https://example.org/source-that-must-remain-whole'
  const seed = proposalSeed(sample(), 'a'.repeat(1190) + '\n' + url)
  assert.ok(seed.markdown.includes(url))
  assert.match(seed.markdown, /User-supplied source context, unverified/)
})

test('advanced seed keeps its record-language question and permissive stage', () => {
  const p = sample(); p.stage.audience = []; p.stage.speakers[0].words = ''
  const previous = { title: 'Kept', fileName: 'kept.md', question: 'Kept question', markdown: '# Existing record\n\nA record-language opening.\n' }
  const seed = proposalSeed(p, '', previous)
  assert.equal(seed.question, 'Kept question')
  assert.match(seed.markdown, /A record-language opening/)
  assert.doesNotMatch(seed.markdown, /All opening speech is generated/)
})

test('advanced edits and removed context do not carry inaccurate provenance', () => {
  const p = { ...sample(), origin: 'advanced', sourceBasis: 'user-supplied' }
  const seed = proposalSeed(p)
  assert.doesNotMatch(seed.markdown, /All opening speech is generated/)
  assert.match(seed.markdown, /hypothetical scenario/)
  assert.doesNotMatch(seed.markdown, /User-supplied source context, unverified/)
})

test('review requires complete editable fields and an available run length', () => {
  assert.deepEqual(reviewProblems(sample(), ['afternoon', 'day']), [])
  assert.ok(reviewProblems(sample(), ['afternoon']).length)
  const p = sample(); p.stage.speakers[0].words = ''
  assert.ok(reviewProblems(p, ['day']).length)
})

test('restore preserves incomplete advanced edits while strict model replies remain bounded', () => {
  const p = sample()
  p.stage.title = ''
  p.stage.speakers[0] = { name: 'The Schoolteacher', figureId: null, guestId: 'teacher', role: 'Teacher', ideas: 'Practice', voice: 'Patient', words: '' }
  p.stage.audience = [{ name: 'A custom fictional listener', description: '' }]
  const restored = validateProposal(p, { incomplete: true, advanced: true })
  assert.equal(restored.stage.title, '')
  assert.equal(restored.stage.speakers[0].guestId, 'teacher')
  assert.equal(restored.stage.audience[0].description, '')
  assert.throws(() => validateProposal(p))
})
