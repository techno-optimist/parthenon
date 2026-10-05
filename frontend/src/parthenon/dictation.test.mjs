import test from 'node:test'
import assert from 'node:assert/strict'
import { createDictation } from './dictation.js'

class Recognition {
  static last
  constructor() { Recognition.last = this; this.starts = 0; this.stops = 0 }
  start() { this.starts++ }
  stop() { this.stops++ }
  abort() { this.aborted = true }
}

test('unsupported or insecure dictation cannot request microphone', () => {
  assert.equal(createDictation({ Recognition, secure: false }).supported, false)
  assert.equal(createDictation({ secure: true }).start(), false)
})

test('dictation starts only explicitly; final speech is delivered once and stop is real', () => {
  const words = [], statuses = []
  const d = createDictation({ Recognition, secure: true, onText: x => words.push(x), onStatus: x => statuses.push(x) })
  assert.equal(Recognition.last?.starts || 0, 0)
  assert.equal(d.start('en-US'), true)
  const r = Recognition.last
  assert.equal(r.starts, 1)
  r.onstart()
  r.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: 'AI tutors' }], { isFinal: true })] })
  assert.deepEqual(words, ['AI tutors'])
  d.stop()
  assert.equal(r.stops, 1)
  r.onend()
  assert.equal(statuses.at(-1), 'idle')
})

test('permission denial is reported and disposal ignores late transcription', () => {
  const errors = [], words = []
  const d = createDictation({ Recognition, secure: true, onError: x => errors.push(x), onText: x => words.push(x) })
  d.start()
  const r = Recognition.last
  r.onerror({ error: 'not-allowed' })
  assert.deepEqual(errors, ['not-allowed'])
  d.dispose()
  r.onresult?.({ resultIndex: 0, results: [Object.assign([{ transcript: 'Late' }], { isFinal: true })] })
  assert.deepEqual(words, [])
})
