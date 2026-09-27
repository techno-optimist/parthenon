// Run: cd frontend && node --test src/parthenon/answers.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  MEMORY_HISTORY_TURNS,
  answerFrom,
  canQuestion,
  cityError,
  conversationFor,
  isRemembering,
  troubleFrom
} from './answers.js'

test('a first question is the prompt itself, with no history', () => {
  assert.deepEqual(conversationFor([], 'Why?'), { prompt: 'Why?', question: 'Why?', history: [] })
  assert.equal(MEMORY_HISTORY_TURNS, 6)
})

test('a follow-up keeps the live prompt byte for byte and six clean turns', () => {
  const prior = Array.from({ length: 8 }, (_, i) => ({
    role: i % 2 === 0 ? 'user' : 'assistant',
    content: `line ${i}`,
    timestamp: 't'
  }))
  const convo = conversationFor(prior, 'And then?')
  // As the Symposium built it before: the history with the new question pushed, less that question.
  const chatHistory = [...prior, { role: 'user', content: 'And then?' }]
  const legacy = `Earlier in our conversation:\n${chatHistory
    .slice(0, -1)
    .slice(-6)
    .map((msg) => `${msg.role === 'user' ? 'Questioner' : 'You'}: ${msg.content}`)
    .join('\n')}\n\nNow my next question is: And then?`
  assert.equal(convo.prompt, legacy)
  assert.equal(
    convo.prompt,
    'Earlier in our conversation:\nQuestioner: line 2\nYou: line 3\nQuestioner: line 4\nYou: line 5\nQuestioner: line 6\nYou: line 7\n\nNow my next question is: And then?'
  )
  assert.equal(convo.question, 'And then?')
  assert.equal(convo.history.length, 6)
  assert.deepEqual(convo.history[0], { role: 'user', content: 'line 2' })
  assert.deepEqual(Object.keys(convo.history[5]), ['role', 'content'])
})

test('a failed line stays in the prompt and out of the history', () => {
  const prior = [
    { role: 'user', content: 'Were you there?' },
    { role: 'assistant', content: 'The city did not answer. Try again in a moment.', failed: true },
    { role: 'user', content: 'Were you there?' },
    { role: 'assistant', content: 'I was.' },
    { role: 'assistant', content: '   ' }
  ]
  const convo = conversationFor(prior, 'Why?')
  assert.ok(convo.prompt.includes('You: The city did not answer. Try again in a moment.'))
  assert.deepEqual(convo.history, [
    { role: 'user', content: 'Were you there?' },
    { role: 'user', content: 'Were you there?' },
    { role: 'assistant', content: 'I was.' }
  ])
})

test('answerFrom reads the live dual shape, the Stoa first, with no mark', () => {
  const live = { result: { results: { twitter_0: { response: 't' }, reddit_0: { response: 'r' } } } }
  assert.deepEqual(answerFrom(live, 0), { text: 'r', memory: false, error: '' })
})

test('answerFrom reads the live single shape by square', () => {
  const single = { result: { platforms: { twitter: { response: 't' }, reddit: { response: 'r' } } } }
  assert.equal(answerFrom(single, 3).text, 'r')
})

test('answerFrom marks a remembered answer', () => {
  const memory = {
    success: true,
    from_memory: true,
    result: {
      from_memory: true,
      unanswered: [],
      results: { reddit_2: { agent_id: 2, response: 'I asked for it.', platform: 'reddit', from_memory: true, timestamp: 't' } }
    }
  }
  assert.deepEqual(answerFrom(memory, 2), { text: 'I asked for it.', memory: true, error: '' })
  // The flag on the data alone is enough.
  assert.equal(answerFrom({ from_memory: true, result: { results: { reddit_2: { response: 'x' } } } }, 2).memory, true)
})

test('an unanswered entry gives its own sentence and no text', () => {
  const data = {
    from_memory: true,
    result: {
      from_memory: true,
      unanswered: [5],
      results: {
        reddit_5: {
          agent_id: 5,
          response: null,
          platform: 'reddit',
          from_memory: true,
          timestamp: 't',
          error: 'Froso Leontari had not answered when the time ran out.'
        }
      }
    }
  }
  assert.deepEqual(answerFrom(data, 5), { text: '', memory: false, error: 'Froso Leontari had not answered when the time ran out.' })
})

test('a live entry never lends its error to the room', () => {
  const live = { result: { results: { reddit_3: { agent_id: 3, response: null, platform: 'reddit', error: 'reddit平台不可用' } } } }
  assert.deepEqual(answerFrom(live, 3), { text: '', memory: false, error: '' })
  const dual = { result: { platforms: { twitter: { platform: 'twitter', error: 'Traceback: boom' } } } }
  assert.deepEqual(answerFrom(dual, 0, { anyFallback: true }), { text: '', memory: false, error: '' })
  const listLive = { results: [{ agent_id: 2, response: null, error: 'str(e)' }] }
  assert.equal(answerFrom(listLive, 2).error, '')
  // The same entry, remembered, keeps its own sentence (the flag on the entry alone is enough).
  const entryOnly = { result: { results: { reddit_3: { agent_id: 3, response: null, from_memory: true, error: 'Froso Leontari had not answered when the time ran out.' } } } }
  assert.equal(answerFrom(entryOnly, 3).error, 'Froso Leontari had not answered when the time ran out.')
})

test('the list shape is found by agent id; anyFallback takes the first', () => {
  const list = { results: [{ agent_id: 1, response: 'one' }, { agent_id: 4, response: 'four' }] }
  assert.equal(answerFrom(list, 4).text, 'four')
  assert.equal(answerFrom(list, 9).text, '')
  assert.equal(answerFrom(list, 9, { anyFallback: true }).text, 'one')
  const dict = { results: { twitter_7: { response: 'seven' } } }
  assert.equal(answerFrom(dict, 2).text, '')
  assert.equal(answerFrom(dict, 2, { anyFallback: true }).text, 'seven')
  assert.deepEqual(answerFrom(null, 0), { text: '', memory: false, error: '' })
})

test('troubleFrom shows only the city\'s words', () => {
  const fallback = 'Try again in a moment.'
  assert.equal(troubleFrom(cityError('x'), fallback), 'x')
  assert.equal(troubleFrom({ response: { data: { from_memory: true, error: 'y' } } }, fallback), 'y')
  assert.equal(troubleFrom({ response: { data: { from_memory: true, error: '  ' } } }, fallback), fallback)
  assert.equal(
    troubleFrom(
      {
        message: 'Simulation environment not running or closed.',
        response: { status: 400, data: { error: 'Simulation environment not running or closed.' } }
      },
      fallback
    ),
    fallback
  )
  assert.equal(troubleFrom(new Error('Network Error'), fallback), fallback)
  assert.equal(troubleFrom(undefined, fallback), fallback)
  assert.equal(cityError('z').cityWords, true)
  assert.ok(cityError('z') instanceof Error)
})

test('canQuestion and isRemembering', () => {
  const table = [
    ['unknown', false, true, false],
    ['unknown', true, true, false],
    ['awake', false, true, false],
    ['awake', true, true, false],
    ['asleep', false, false, false],
    ['asleep', true, true, true],
    ['asleep', undefined, false, false]
  ]
  for (const [state, ready, can, remembering] of table) {
    assert.equal(canQuestion(state, ready), can, `canQuestion ${state} ${ready}`)
    assert.equal(isRemembering(state, ready), remembering, `isRemembering ${state} ${ready}`)
  }
})

test('a remembered error the visitor cannot read gives way to the room\'s own words', () => {
  const data = { from_memory: true, result: { results: { reddit_5: { agent_id: 5, response: '', error: '弗罗索没有回答。' } } } }
  assert.equal(answerFrom(data, 5).error, '')
  const err = { response: { data: { from_memory: true, error: '记忆尚未准备好' } } }
  assert.equal(troubleFrom(err, 'Try again.'), 'Try again.')
})
