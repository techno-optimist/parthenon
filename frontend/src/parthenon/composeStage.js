// "Build your own stage": turns what the user described in the builder
// (speakers, a crowd, a question) into a seed scroll in the same shape as the
// retold scrolls in speakers.js, ready for the graph, the swarm and the Chronicle.
//
// Pure module: no Vue, no DOM. The Markdown it writes uses only what the home
// page renderer understands ('# ', '## ', blank-line paragraphs, blocks where
// every line starts with '- ', **bold** and *italic*), and user text is
// neutralised so it cannot open headings or bullet blocks of its own.

// `zh` holds what the builder shows in Chinese (read through localText); the
// scroll is written from the English fields.
export const FORMATS = [
  { id: 'speech', label: 'A speech', blurb: 'One voice addresses the city.', min: 1, max: 1, zh: { label: '一场演说', blurb: '一个声音向全城发言。' } },
  { id: 'dialogue', label: 'A dialogue', blurb: 'Two minds question each other in public.', min: 2, max: 2, zh: { label: '一场对话', blurb: '两个头脑当众相互诘问。' } },
  { id: 'panel', label: 'A symposium', blurb: 'A panel of voices takes turns on one question.', min: 2, max: 8, zh: { label: '一场研讨会', blurb: '几个声音轮流谈同一个问题。' } },
  { id: 'trial', label: 'A trial', blurb: 'Accusers and defenders argue; a jury of citizens decides.', min: 2, max: 6, zh: { label: '一场审判', blurb: '控方与辩方争辩，由公民陪审团裁决。' } },
  { id: 'assembly', label: 'An assembly', blurb: 'A proposal is put to the people and every voice may speak.', min: 1, max: 8, zh: { label: '一场公民大会', blurb: '一项提案交付人民，人人都可以发言。' } },
]

export const ERAS = [
  { id: 'ancient', label: 'Ancient Athens', setting: 'Athens, 399 BC, on the steps below the Parthenon', zh: { label: '古代雅典' } },
  { id: 'now', label: 'Today, 2026', setting: 'A city square in 2026; the speakers have stepped off the Parthenon steps into the present', zh: { label: '今天，2026年' } },
  { id: 'future', label: 'The near future', setting: 'A city in 2040', zh: { label: '不久的将来' } },
  { id: 'custom', label: 'Anywhere', setting: '', zh: { label: '任何地方' } },
]

const isZh = (locale) => String(locale || '').toLowerCase().startsWith('zh')
const labelOf = (item, locale) => (isZh(locale) && item.zh && item.zh.label) || item.label

// ---------------------------------------------------------------------------
// Shapes the builder edits

let keySeq = 0
const newKey = (prefix) =>
  `${prefix}-${Date.now().toString(36)}-${(keySeq++).toString(36)}-${Math.random().toString(36).slice(2, 7)}`

export function emptyStage() {
  return {
    title: '',
    format: 'panel',
    era: 'now',
    setting: eraById('now').setting,
    topic: '',
    speakers: [],
    audience: [],
    question: '',
    happensNext: '',
  }
}

export function emptySpeaker(partial = {}) {
  const speaker = { key: newKey('speaker'), name: '', role: '', ideas: '', voice: '', words: '', figureId: null, ...(partial || {}) }
  if (!speaker.key) speaker.key = newKey('speaker')
  return speaker
}

export function emptyAudienceMember(partial = {}) {
  const member = { key: newKey('listener'), name: '', description: '', ...(partial || {}) }
  if (!member.key) member.key = newKey('listener')
  return member
}

// Roster figure {id, name, lived, from, known, ideas, voice, aiLens} -> speaker.
export function speakerFromFigure(figure) {
  const f = figure && typeof figure === 'object' ? figure : {}
  const known = asText(f.known).trim()
  const where = [asText(f.lived).trim(), asText(f.from).trim()].filter(Boolean).join(', ')
  const role = known && where ? `${known} (${where})` : known || where
  const ideas = [asText(f.ideas).trim(), asText(f.aiLens).trim()].filter(Boolean).join(' ')
  return emptySpeaker({
    name: asText(f.name).trim(),
    role,
    ideas,
    voice: asText(f.voice).trim(),
    figureId: f.id != null && f.id !== '' ? f.id : null,
  })
}

// ---------------------------------------------------------------------------
// Checks

// Blocking: the stage cannot run until these are fixed. Worded in the
// visitor's language ('en' or 'zh').
export function stageProblems(stage, locale = 'en') {
  const st = readStage(stage)
  const { format } = st
  const count = st.named.length
  const problems = []

  if (isZh(locale)) {
    const label = labelOf(format, locale)
    if (count < format.min) {
      if (format.min === 1) problems.push(`${label}需要一位有名字的发言者；目前还没有人有名字。`)
      else {
        const have = count === 0 ? '目前还没有人有名字' : `目前只有 ${count} 位有名字`
        problems.push(`${label}需要${format.min === format.max ? '' : '至少'} ${format.min} 位有名字的发言者；${have}。`)
      }
    }
    if (count > format.max) {
      const alt = FORMATS.find((f) => f.id !== format.id && count >= f.min && count <= f.max)
      const instead = alt ? `，或改为${labelOf(alt, locale)}` : ''
      problems.push(`${label}只容得下 ${format.max} 位发言者，而不是 ${count} 位。请移除 ${count - format.max} 位${instead}。`)
    }
    if (!st.topic && !st.question) problems.push('说说这次集会讨论什么：给它一道难题或一个问题。')
    return problems
  }

  if (count < format.min) {
    if (format.min === 1) {
      problems.push(`${format.label} needs a named speaker; no speaker has a name yet.`)
    } else {
      const have = count === 0 ? 'none has a name yet' : `only ${numberWord(count)} ${count === 1 ? 'has' : 'have'} a name so far`
      problems.push(`${format.label} needs ${format.min === format.max ? '' : 'at least '}${numberWord(format.min)} named speakers; ${have}.`)
    }
  }

  if (count > format.max) {
    const room = format.max === 1 ? 'one speaker' : `${numberWord(format.max)} speakers`
    const alt = FORMATS.find((f) => f.id !== format.id && count >= f.min && count <= f.max)
    const instead = alt ? ` or make it ${alt.label.toLowerCase()}` : ''
    problems.push(`${format.label} has room for ${room}, not ${numberWord(count)}. Remove ${numberWord(count - format.max)}${instead}.`)
  }

  if (!st.topic && !st.question) {
    problems.push('Say what the gathering is about: give it a topic or a question.')
  }

  return problems
}

// Non-blocking: the stage runs, but these would make it better. In Chinese the
// page may pass its own suggested question and a way to name each speaker
// (roster figures have Chinese names the scroll does not use).
export function stageHints(stage, locale = 'en', { suggestion = '', nameOf = null } = {}) {
  const st = readStage(stage)
  const hints = []

  if (isZh(locale)) {
    const name = (s) => (typeof nameOf === 'function' && nameOf(s)) || s.name
    const join = (list) => (list.length <= 1 ? list[0] || '' : `${list.slice(0, -1).join('、')}和${list[list.length - 1]}`)
    if (!st.audience.length) hints.push('台阶上还没有人群。求问神谕，或挑选一个群体；否则整座城市都会聆听。')
    const silent = st.named.filter((s) => !s.words)
    if (silent.length) hints.push(`${join(silent.map(name))}还没有开场白。神谕可以代为起草，否则市民们只能依据介绍来理解他们。`)
    if (st.unnamed.length) hints.push(`${st.unnamed.length} 位没有名字的发言者将不会登台。`)
    if (!st.question) hints.push(`还没有问题，所以城邦将被问到：${suggestion || suggestQuestion(stage)}`)
    return hints
  }

  if (!st.audience.length) {
    hints.push('No crowd on the steps yet. Ask the Oracle or pick a preset to add one; otherwise the city at large will listen.')
  }

  const silent = st.named.filter((s) => !s.words)
  if (silent.length) {
    const verb = silent.length === 1 ? 'has' : 'have'
    hints.push(`${listNames(silent.map((s) => s.name))} ${verb} no opening words yet. The Oracle can draft them, or the citizens will work from the descriptions alone.`)
  }

  if (st.unnamed.length) {
    const n = st.unnamed.length
    hints.push(`${capitalise(numberWord(n))} speaker${n === 1 ? '' : 's'} without a name will be left off the stage.`)
  }

  if (!st.question) {
    hints.push(`No question yet, so the city will be asked: ${suggestion || suggestQuestion(stage)}`)
  }

  return hints
}

// ---------------------------------------------------------------------------
// Question, slug and seed

export function suggestQuestion(stage) {
  const st = readStage(stage)
  const names = listNames(st.named.map((s) => s.name))
  const topic = topicPhrase(st.topic, 80)
  const on = topic ? ` on “${topic}”` : ''
  const crowd = st.era && st.era.id === 'ancient' ? 'Athens' : 'the crowd'

  switch (st.format.id) {
    case 'speech':
      return `After hearing ${names || 'the speaker'} speak${on}, how does ${crowd} react over the following days? Who is persuaded, who pushes back, and which arguments spread?`
    case 'dialogue':
      return `After ${names || 'the two speakers'} question each other${on}, whose side does ${crowd} take over the following days? Who changes their mind, which arguments spread, and what does the community decide?`
    case 'trial':
      return `After hearing ${names || 'the accusers and the defenders'}${on}, how does the jury of citizens vote, and why? Which arguments sway the jurors in the days before the verdict, and does the community accept it?`
    case 'assembly':
      return `After hearing ${names || 'the speakers'}${on}, how does the assembly vote at the end of the week, and why? Which arguments win votes, who changes their mind, and does the community accept the result?`
    default:
      return `After hearing ${names || 'the speakers'}${on}, how does ${crowd} react over the following days? Who changes their mind, which arguments spread, and what does the community decide?`
  }
}

export function slugify(text) {
  const slug = asText(text)
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/['’]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  if (slug.length <= 60) return slug || 'stage'
  const cut = slug.slice(0, 61)
  const lastHyphen = cut.lastIndexOf('-')
  const capped = (lastHyphen >= 20 ? cut.slice(0, lastHyphen) : slug.slice(0, 60)).replace(/-+$/g, '')
  return capped || 'stage'
}

const NEXT_BY_FORMAT = {
  trial: 'The jury retires to deliberate; the verdict will be read in three days.',
  assembly: 'The assembly will vote at the end of the week.',
}
const NEXT_DEFAULT = 'Word spreads through the Agora and the Stoa over the following days.'
const NEXT_ZH = {
  trial: '陪审团退庭评议；三天后宣读判决。',
  assembly: '公民大会将在本周末投票。',
  default: '接下来的几天里，消息在广场和柱廊之间传开。',
}

// The line "What happens next" falls back to when it is left blank. The scroll
// always carries the English line; the Chinese one is what the form shows.
export function defaultNext(format, locale = 'en') {
  const id = formatById(format).id
  if (isZh(locale)) return NEXT_ZH[id] || NEXT_ZH.default
  return NEXT_BY_FORMAT[id] || NEXT_DEFAULT
}

export function composeStageSeed(stage) {
  const st = readStage(stage)
  const title = st.title || fallbackTitle(st)
  const heading = /for parthenon$/i.test(title) ? title : `${title}, staged for Parthenon`
  const blocks = []

  blocks.push(`# ${heading}`)
  blocks.push(`*${[st.setting && sentence(st.setting), st.format.blurb].filter(Boolean).join(' ')}*`)

  blocks.push('## The matter')
  const matter = paragraphs(st.topic).length ? paragraphs(st.topic) : paragraphs(st.question)
  blocks.push(...(matter.length ? matter : ['The speakers have not yet said what the gathering is about.']))

  blocks.push('## Who takes the stage')
  const hasFigure = st.named.some((s) => s.figureId)
  if (hasFigure && st.era && (st.era.id === 'now' || st.era.id === 'future')) {
    blocks.push('*Those who lived long ago have stepped out of their own centuries. They remember their own lives and ideas, and they are meeting this world for the first time.*')
  }
  blocks.push(st.named.length ? st.named.map(speakerBullet).join('\n') : 'No one has taken the stage yet.')

  blocks.push('## What was said')
  if (hasFigure) blocks.push('*(Imagined for Parthenon, not a historical record.)*')
  for (const s of st.named) {
    const said = paragraphs(s.words)
    if (said.length) blocks.push(`**${s.name}:**`, ...said)
    else blocks.push(`*${s.name} has not spoken yet; their views are described above.*`)
  }
  if (!st.named.length) blocks.push('*Nothing has been said yet.*')

  blocks.push('## Who was listening')
  blocks.push(st.audience.length
    ? st.audience.map(audienceBullet).join('\n')
    : 'The city at large: citizens of every kind, who will decide for themselves.')

  blocks.push('## What happens next')
  const next = paragraphs(st.happensNext)
  blocks.push(...(next.length ? next : [NEXT_BY_FORMAT[st.format.id] || NEXT_DEFAULT]))

  const markdown = `${blocks.join('\n\n').replace(/\n{3,}/g, '\n\n').trim()}\n`
  return {
    title,
    fileName: `stage-${slugify(title)}.md`,
    question: st.question || suggestQuestion(stage),
    markdown,
  }
}

// ---------------------------------------------------------------------------
// Internals

const CAP = {
  title: 120,
  name: 80,
  role: 200,
  ideas: 1500,
  voice: 300,
  words: 4000,
  description: 400,
  topic: 3000,
  question: 1500,
  setting: 300,
  happensNext: 1500,
}

const eraById = (id) => ERAS.find((e) => e.id === id) || null
const formatById = (id) => FORMATS.find((f) => f.id === id) || FORMATS.find((f) => f.id === 'panel')

function readStage(stage) {
  const s = stage && typeof stage === 'object' ? stage : {}
  const era = eraById(s.era)
  const speakers = listOf(s.speakers).map(readSpeaker)
  return {
    format: formatById(s.format),
    era,
    setting: plainLine(s.setting, CAP.setting) || (era ? era.setting : ''),
    title: plainLine(s.title, CAP.title),
    topic: cleanBlock(s.topic, CAP.topic),
    question: cleanBlock(s.question, CAP.question),
    happensNext: cleanBlock(s.happensNext, CAP.happensNext),
    named: speakers.filter((sp) => sp.name),
    unnamed: speakers.filter((sp) => !sp.name && (sp.role || sp.ideas || sp.voice || sp.words)),
    audience: listOf(s.audience).map(readListener).filter((a) => a.name || a.description),
  }
}

function readSpeaker(sp) {
  return {
    name: plainLine(sp.name, CAP.name),
    role: cleanLine(sp.role, CAP.role),
    ideas: cleanLine(sp.ideas, CAP.ideas),
    voice: cleanLine(sp.voice, CAP.voice),
    words: cleanBlock(sp.words, CAP.words),
    figureId: sp.figureId != null && sp.figureId !== '' ? sp.figureId : null,
    guestId: sp.guestId != null && sp.guestId !== '' ? sp.guestId : null,
  }
}

function readListener(a) {
  return {
    name: plainLine(a.name, CAP.name),
    description: cleanLine(a.description, CAP.description),
  }
}

function speakerBullet(s) {
  const parts = [sentence(s.role ? `**${s.name}**, ${s.role}` : `**${s.name}**`)]
  if (s.ideas) parts.push(sentence(s.ideas))
  if (s.voice) parts.push(sentence(`How they speak: ${s.voice}`))
  return `- ${parts.join(' ')}`
}

function audienceBullet(a) {
  if (a.name && a.description) return `- **${a.name}**, ${sentence(a.description)}`
  if (a.name) return `- **${a.name}**`
  return `- ${sentence(a.description)}`
}

function fallbackTitle(st) {
  const [noun, about, withWhom] = {
    speech: ['A Speech', 'on', 'by'],
    dialogue: ['A Dialogue', 'on', 'between'],
    trial: ['A Trial', 'over', 'with'],
    assembly: ['An Assembly', 'on', 'with'],
  }[st.format.id] || ['A Symposium', 'on', 'with']
  // Short noun phrases read well bare ("on AI tutors"); questions and whole sentences get quotes.
  const quoteIfAsked = (text) => (/[?!…]$/.test(text) || text.split(' ').length > 6 ? `“${text}”` : text)

  const topic = topicPhrase(st.topic, 60)
  if (topic) return cap(`${noun} ${about} ${quoteIfAsked(topic)}`, CAP.title)
  if (st.named.length) return cap(`${noun} ${withWhom} ${listNames(st.named.map((s) => s.name))}`, CAP.title)
  const question = topicPhrase(st.question, 60)
  if (question) return cap(`${noun} ${about} ${quoteIfAsked(question)}`, CAP.title)
  return noun
}

// First sentence of the first line, shortened, without a trailing full stop.
function topicPhrase(text, max) {
  const line = (text.split('\n').find((l) => l.trim()) || '').replace(/\s+/g, ' ').trim()
  const first = (line.match(/^.{12,}?[.!?](?=\s+[A-Z“"'(])/) || [line])[0]
  return cap(first.replace(/[\s.,;:]+$/, ''), max)
}

function listOf(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : []
}

function asText(value) {
  if (typeof value === 'string') return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

// Leading Markdown markers a line of user text may not keep: headings,
// blockquotes and bullets ('- ', '* ', '+ ', '• ').
const LEAD_MARKER = /^\s*(?:#+|>+|[-*+•](?=\s|$))\s*/
const RULE_LINE = /^[-=_*~\s]{3,}$/

function neutraliseLine(line) {
  let out = line
  for (let i = 0; i < 50; i++) {
    const next = out.replace(LEAD_MARKER, '')
    if (next === out) break
    out = next
  }
  if (RULE_LINE.test(out)) return ''
  return out.replace(/[ \u00a0]+/g, ' ').trim()
}

// Multi-paragraph text: paragraph breaks survive, at most one blank line in a row.
function cleanBlock(value, max = Infinity) {
  const text = asText(value)
    .replace(/\r\n?|[\u000b\u000c\u0085\u2028\u2029]/g, '\n')
    .replace(/`/g, '')
    .replace(/\t/g, ' ')
    .replace(/[\u0000-\u0008\u000e-\u001f\u007f\u200b-\u200d\ufeff]/g, '')
  const joined = text.split('\n').map(neutraliseLine).join('\n').replace(/\n{3,}/g, '\n\n').trim()
  return cap(joined, max)
}

// Supplied source excerpts use the same seed prose rules without the topic's
// smaller cap. Preserve URLs and the full accepted 8000-character context.
export const sourceContextBlock = value => cleanBlock(value, 8000)

// Single-line text (it lives inside a bullet or a heading).
function cleanLine(value, max = Infinity) {
  return cap(neutraliseLine(cleanBlock(value).replace(/\s+/g, ' ')), max)
}

// Single-line text that sits inside **bold** or *italic* markers.
function plainLine(value, max = Infinity) {
  return cap(neutraliseLine(cleanBlock(value).replace(/\*+/g, '').replace(/\s+/g, ' ')).replace(/[\s:;,]+$/, ''), max)
}

function cap(text, max) {
  if (!Number.isFinite(max) || text.length <= max) return text
  let cut = text.slice(0, max - 1)
  const lastSpace = Math.max(cut.lastIndexOf(' '), cut.lastIndexOf('\n'))
  if (lastSpace >= max * 0.6) cut = cut.slice(0, lastSpace)
  if (/[\ud800-\udbff]$/.test(cut)) cut = cut.slice(0, -1)
  return `${cut.replace(/[\s,;:.\-–—(]+$/, '')}…`
}

function paragraphs(text) {
  return text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
}

function sentence(text) {
  const t = text.trim()
  if (!t) return ''
  return /[.!?…]["'”’)\]]*$/.test(t) ? t : `${t}.`
}

function listNames(names, shown = 3) {
  const list = names.filter(Boolean)
  if (list.length <= 1) return list[0] || ''
  if (list.length <= shown) return `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`
  const rest = list.length - shown
  return `${list.slice(0, shown).join(', ')} and ${numberWord(rest)} other${rest === 1 ? '' : 's'}`
}

const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
const numberWord = (n) => WORDS[n] || String(n)
const capitalise = (text) => text.charAt(0).toUpperCase() + text.slice(1)
