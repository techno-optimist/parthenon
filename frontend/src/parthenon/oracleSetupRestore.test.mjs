import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { ERAS, FORMATS } from './composeStage.js'
import { RUN_LENGTHS } from './vocabulary.js'
import { allowedRunLengths, clampRunLength } from './limits.js'
import { TRIPOD, tripodMark } from './oracle.js'
import { createProposalSession, proposalSeed, reviewProblems, validateProposal } from './oracleSetup.js'
import { createDictation } from './dictation.js'
import { audiencePresets } from './audiences.js'

// Exercise the actual SFC setup, reactivity and lifecycle without an inference
// provider or browser microphone. Compile its script exactly as Vue does.
const source = readFileSync(new URL('../components/OracleSetup.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = compileScript(descriptor, { id: 'oracle-restoration-test' }).content
const executable = script.replace(/^import .*$/gm, '').replace('export default', 'return')

const proposal = () => ({
  stage: { title: 'The original title', format: 'dialogue', era: 'now', setting: 'A hypothetical council', topic: 'AI tutors',
    speakers: [
      { figureId: 'socrates', name: 'Socrates', role: 'Questioner', ideas: 'Knowledge', voice: 'Questions', words: 'What is learning?' },
      { figureId: 'aristotle', name: 'Aristotle', role: 'Philosopher', ideas: 'Practice', voice: 'Precise', words: 'Learning takes practice.' },
    ],
    audience: audiencePresets.now.slice(0, 8).map(a => ({ name: a.name, description: 'A fictional role.' })),
    question: 'Who changes their mind?', happensNext: 'The council votes tomorrow.',
  }, runLength: 'day', assumptions: ['A hypothetical vote.'], sourceBasis: 'hypothetical',
})

function mountSetup(storage, ask = async () => ({ success: true, data: { proposal: proposal() } })) {
  const mounted = [], unmounted = [], listeners = new Map(), timers = new Map()
  let timerId = 0
  const dependencies = {
    computed, reactive, ref, watch, useId: () => 'restore-test',
    onMounted: fn => mounted.push(fn), onBeforeUnmount: fn => unmounted.push(fn),
    useI18n: () => ({ locale: ref('en'), t: key => key }),
    StageBuilder: {}, InviteLine: {}, proposeStage: ask,
    access: reactive({ public: false, limits: null }), inviteNeeded: () => false,
    ERAS, FORMATS, RUN_LENGTHS, allowedRunLengths, clampRunLength, TRIPOD, tripodMark,
    createProposalSession, proposalSeed, reviewProblems, validateProposal, createDictation,
    window: {
      isSecureContext: false,
      localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
      addEventListener: (name, fn) => listeners.set(name, fn),
      removeEventListener: name => listeners.delete(name),
    },
    setTimeout: fn => { const id = ++timerId; timers.set(id, fn); return id },
    clearTimeout: id => timers.delete(id),
  }
  const component = new Function(...Object.keys(dependencies), executable)(...Object.values(dependencies))
  const scope = effectScope()
  const vm = scope.run(() => component.setup({ disabled: false }, { expose() {}, emit() {} }))
  mounted.forEach(fn => fn())
  return {
    vm,
    async flushSave() { await nextTick(); const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()) },
    pagehide() { listeners.get('pagehide')?.() },
    dispose() { scope.stop(); timers.clear() },
    unmount() { unmounted.forEach(fn => fn()); scope.stop(); timers.clear() },
  }
}

test('reload during advanced editing retains the newest stage and compact edits still round-trip', async () => {
  const storage = new Map()
  const first = mountSetup(storage)
  first.vm.brief.value = 'A council considers AI tutors.'
  await first.vm.askOracle()
  first.vm.toggleAdvanced()
  first.vm.advancedChanged({ ...first.vm.advancedDraft.value, title: 'The newer advanced title' })
  await first.flushSave()
  first.dispose() // Reload while advanced is open, without a Vue unmount.
  const reloaded = mountSetup(storage)
  reloaded.vm.toggleAdvanced()
  assert.equal(reloaded.vm.advancedDraft.value.title, 'The newer advanced title')
  reloaded.vm.toggleAdvanced()
  reloaded.vm.state.proposal.stage.title = 'A later compact edit'
  reloaded.vm.toggleAdvanced()
  assert.equal(reloaded.vm.advancedDraft.value.title, 'A later compact edit')
  reloaded.unmount()
})

test('reload after an essential clarifier restores the visible question and resumable original context', async () => {
  const storage = new Map()
  const first = mountSetup(storage, async () => ({ data: { clarification: 'Which city should face this decision?' } }))
  first.vm.brief.value = 'Explore AI tutors in a city.'
  await first.vm.askOracle()
  await first.flushSave()
  first.dispose()
  const sent = []
  const reloaded = mountSetup(storage, async payload => { sent.push(payload); return { data: { proposal: proposal() } } })
  assert.equal(reloaded.vm.state.clarification, 'Which city should face this decision?')
  assert.equal(reloaded.vm.brief.value, '')
  reloaded.vm.brief.value = 'Athens'
  await reloaded.vm.askOracle()
  assert.match(sent[0].brief, /Explore AI tutors in a city/)
  assert.match(sent[0].brief, /Which city should face this decision/)
  assert.match(sent[0].brief, /Athens/)
  reloaded.unmount()
})

test('pagehide flushes an advanced edit before the save debounce runs', async () => {
  const storage = new Map()
  const first = mountSetup(storage)
  first.vm.brief.value = 'A council considers AI tutors.'
  await first.vm.askOracle()
  first.vm.toggleAdvanced()
  first.vm.advancedChanged({ ...first.vm.advancedDraft.value, title: 'Saved on immediate reload' })
  first.pagehide()
  first.dispose()
  const reloaded = mountSetup(storage)
  assert.equal(reloaded.vm.state.proposal?.stage.title, 'Saved on immediate reload')
  reloaded.unmount()
})
