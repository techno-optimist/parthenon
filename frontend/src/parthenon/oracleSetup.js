// A complete proposal is only local review state. The Home page's existing
// explicit Begin action owns all project/graph/simulation creation.
import { composeStageSeed, FORMATS, ERAS, stageProblems, sourceContextBlock } from './composeStage.js'
import { figures, modernGuests } from './roster.js'
import { audiencePresets } from './audiences.js'

export const SETUP_FIGURES = ['socrates', 'plato', 'aristotle', 'diogenes', 'epicurus', 'hypatia', 'pericles', 'aspasia']
const durations = ['afternoon', 'day', 'threeDays', 'week']
const civilianNames = new Set(Object.values(audiencePresets).flat().map(a => a.name))
const clone = value => JSON.parse(JSON.stringify(value))
const string = (value, max, field, incomplete = false) => {
  if (typeof value !== 'string' || value.length > max || (!incomplete && !value.trim())) {
    throw new Error(`Review the ${field}; it must contain text within its limit.`)
  }
  return value
}

export function validateProposal(raw, { incomplete = false, advanced = false } = {}) {
  if (!raw || typeof raw !== 'object' || !raw.stage || typeof raw.stage !== 'object') throw new Error('The Oracle returned an incomplete proposal. Your work is kept.')
  const s = raw.stage
  const format = FORMATS.find(f => f.id === s.format)
  if (!format || !ERAS.some(e => e.id === s.era) || !durations.includes(raw.runLength)) throw new Error('The Oracle returned an unsupported format, era, or duration.')
  const stage = { format: s.format, era: s.era }
  for (const [key, max] of Object.entries({ title: 120, setting: 300, topic: 3000, question: 1500, happensNext: advanced ? 1500 : 1000 })) stage[key] = string(s[key], max, key, incomplete)
  if (!Array.isArray(s.speakers) || s.speakers.length < (advanced ? 0 : format.min) || s.speakers.length > (advanced ? 8 : Math.min(format.max, 4))) throw new Error('Review the number of speakers for this format.')
  const ids = new Set(), names = new Set()
  stage.speakers = s.speakers.map(sp => {
    if (advanced) {
      const speaker = { name: string(sp?.name, 80, 'speaker name', true), figureId: figures.some(f => f.id === sp?.figureId) ? sp.figureId : null, guestId: modernGuests.some(g => g.id === sp?.guestId) ? sp.guestId : null }
      for (const [key, max] of Object.entries({ role: 200, ideas: 1500, voice: 300, words: 4000 })) speaker[key] = string(sp[key], max, `speaker ${key}`, true)
      return speaker
    }
    const figure = figures.find(f => f.id === sp?.figureId && SETUP_FIGURES.includes(f.id))
    if (!figure || sp.name !== figure.name || ids.has(figure.id)) throw new Error('The Oracle returned a speaker outside the historical roster.')
    ids.add(figure.id); names.add(figure.name.toLowerCase())
    const speaker = { figureId: figure.id, name: figure.name }
    for (const [key, max] of Object.entries({ role: 200, ideas: 1500, voice: 300, words: 4000 })) speaker[key] = string(sp[key], max, `speaker ${key}`, incomplete)
    return speaker
  })
  if (!Array.isArray(s.audience) || s.audience.length < (advanced ? 0 : 8) || s.audience.length > (advanced ? 24 : 14)) throw new Error('The Oracle must propose 8-14 fictional civilian roles.')
  stage.audience = s.audience.map(member => {
    const name = string(member?.name, 80, 'civilian name', advanced)
    if (!advanced && !civilianNames.has(name)) throw new Error('The Oracle returned a civilian outside the generic role catalog.')
    const key = name.trim().replace(/\s+/g, ' ').toLowerCase()
    if (!advanced && names.has(key)) throw new Error('The Oracle returned duplicate citizen names.')
    names.add(key)
    return { name, description: string(member.description, 400, 'civilian description', incomplete) }
  })
  if (!Array.isArray(raw.assumptions) || raw.assumptions.length < 1 || raw.assumptions.length > 5) throw new Error('The Oracle must state its scenario assumptions.')
  if (!['hypothetical', 'user-supplied'].includes(raw.sourceBasis)) throw new Error('The Oracle did not label the scenario basis.')
  return { stage, runLength: raw.runLength, assumptions: raw.assumptions.map(a => string(a, 500, 'assumption')), sourceBasis: raw.sourceBasis,
    ...(advanced && raw.origin === 'advanced' ? { origin: 'advanced' } : {}) }
}

export function createProposalSession({ ask, wrapState = value => value }) {
  const state = wrapState({ pending: false, error: '', cityCode: '', notice: '', clarification: '', proposal: null })
  let token = 0, controller = null
  function cancel() {
    token++
    controller?.abort()
    controller = null
    state.pending = false
  }
  function edited() {
    if (state.pending) { cancel(); state.notice = 'Your edits are kept. Ask the Oracle again to use them.' }
  }
  async function request(payload) {
    if (state.pending) return false
    const ownToken = ++token
    controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    state.pending = true; state.error = ''; state.cityCode = ''; state.notice = ''; state.clarification = ''
    try {
      const result = await ask(clone(payload), controller ? { signal: controller.signal } : {})
      if (ownToken !== token) return false
      if (result?.success === false) throw new Error(result.error || 'The Oracle could not answer. Your work is kept.')
      const data = result?.data
      if (typeof data?.clarification === 'string' && data.clarification.trim() && data.clarification.length <= 300 && !data.proposal) {
        state.clarification = data.clarification
      } else {
        state.proposal = validateProposal(data?.proposal)
      }
      return true
    } catch (error) {
      if (ownToken === token) {
        state.error = String(error?.message || 'The Oracle could not answer. Your work is kept.')
        state.cityCode = String(error?.cityCode || '')
      }
      return false
    } finally {
      if (ownToken === token) { state.pending = false; controller = null }
    }
  }
  return { state, request, cancel, edited }
}

export function reviewProblems(proposal, allowedLengths, locale = 'en') {
  if (!proposal?.stage) return ['Ask the Oracle to propose a stage first.']
  const s = proposal.stage
  const problems = stageProblems(s, locale)
  for (const key of ['title', 'setting', 'topic', 'question', 'happensNext']) if (!String(s[key] || '').trim()) problems.push(`Add the ${key === 'happensNext' ? 'upcoming trigger' : key}.`)
  if (!s.audience?.length) problems.push('Add fictional civilians to the gathering.')
  if (s.speakers?.some(sp => !sp.words?.trim())) problems.push('Give each speaker opening words.')
  if (s.audience?.some(a => !a.name?.trim() || !a.description?.trim())) problems.push('Give each civilian a name and description.')
  if (!allowedLengths.includes(proposal.runLength)) problems.push('Choose an available run duration.')
  return problems
}

export function proposalSeed(proposal, sourceContext = '', existingSeed = null) {
  const seed = existingSeed || composeStageSeed(proposal.stage)
  const basis = sourceContext.trim()
    ? 'User-supplied source context, unverified. No web lookup was performed.'
    : 'A hypothetical scenario; contemporary details are assumptions.'
  const assumptions = sourceContextBlock(proposal.assumptions.join('\n\n'))
  const sources = sourceContext ? `\n\n## User-supplied source context (unverified)\n\n${sourceContextBlock(sourceContext)}` : ''
  const speech = existingSeed || proposal.origin === 'advanced'
    ? 'Speaker descriptions and supplied speech form a simulation, not actual testimony.'
    : 'Oracle-drafted opening speech is generated simulation; user edits may be included.'
  const notice = `*Simulation scenario. ${basis} ${speech} Civilian roles are fictional.*`
  const markdown = seed.markdown.replace(/\n\n/, `\n\n${notice}\n\n`) + `\n## Scenario assumptions\n\n${assumptions}${sources}\n`
  return { ...seed, markdown }
}
