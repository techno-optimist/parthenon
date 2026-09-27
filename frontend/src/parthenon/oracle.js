// "Build your own stage" as a conversation with the Oracle at the bema: five
// questions, one per screen, then the stage held up as a small scroll.
//
//   Α΄ who       Who takes the floor?          speakers (and the format that fits them)
//   Β΄ where     When and where?               era, setting
//   Γ΄ words     What do they say?             each speaker's words
//   Δ΄ listeners Who listens?                  audience
//   Ε΄ question  What should Athens decide?    question
//
// Pure module: no Vue, no DOM. It reads and returns plain stage objects in the
// shape composeStage.js edits, so the conversation and the full form share one
// stage. Problems come back as codes with params; the component words them in
// the visitor's language (parthenon.builder.oracle.problems.<code>).
//
// Language: what the visitor types or edits as text (the place, the words, the
// question) is written in their language. What they pick as a token (a figure,
// a group of listeners) keeps its English record for the scroll and is only
// shown in their language, as speakers.js and the arrivals do.

import { audiencePresets } from './audiences.js'
import { FORMATS, emptyAudienceMember, suggestQuestion } from './composeStage.js'
import { localText } from './localText.js'
import { figures, modernGuests } from './roster.js'

// ---------------------------------------------------------------------------
// Steps

export const STEPS = [
  { id: 'who', numeral: 'Α΄', fills: ['speakers', 'format'] },
  { id: 'where', numeral: 'Β΄', fills: ['era', 'setting'] },
  { id: 'words', numeral: 'Γ΄', fills: ['speakers.words'] },
  { id: 'listeners', numeral: 'Δ΄', fills: ['audience'] },
  { id: 'question', numeral: 'Ε΄', fills: ['question'] },
]

// The screen after the five questions: the stage as a scroll, and one button.
export const SUMMARY = STEPS.length
export const LAST_NUMERAL = STEPS[STEPS.length - 1].numeral

export const MAX_SPEAKERS = Math.max(...FORMATS.map((f) => f.max))
export const MAX_AUDIENCE = 24

const GREEK = ['Α΄', 'Β΄', 'Γ΄', 'Δ΄', 'Ε΄', 'ΣΤ΄', 'Ζ΄', 'Η΄', 'Θ΄', 'Ι΄']
export const greekNumeral = (n) => GREEK[n - 1] || String(n)

export const stepIndex = (id) => STEPS.findIndex((s) => s.id === id)
export const clampStep = (n) => {
  const i = Number.isFinite(Number(n)) ? Math.trunc(Number(n)) : 0
  return Math.min(Math.max(i, 0), SUMMARY)
}

// ---------------------------------------------------------------------------
// Small helpers

const str = (v) => (typeof v === 'string' ? v : '')
const norm = (v) => str(v).trim().replace(/\s+/g, ' ').toLowerCase()
const isZh = (locale) => String(locale || '').toLowerCase().startsWith('zh')
const pick = (item, locale) => (isZh(locale) && item.zh ? item.zh : item)

// A name as the scroll will print it: no Markdown markers, no trailing ':;,'.
// Mirrors composeStage's plainLine closely enough to count names the same way.
export const bareName = (name) => {
  let out = str(name).replace(/[`*\u0000-\u001f\u007f​-‍﻿]/g, ' ').replace(/\s+/g, ' ').trim()
  for (let i = 0; i < 20; i++) {
    const next = out.replace(/^\s*(?:#+|>+|[-*+•](?=\s|$))\s*/, '')
    if (next === out) break
    out = next
  }
  if (/^[-=_*~\s]{3,}$/.test(out)) return ''
  return out.replace(/[\s:;,]+$/, '')
}

export const namedSpeakers = (stage) => (Array.isArray(stage && stage.speakers) ? stage.speakers : []).filter((s) => s && bareName(s.name))
const namedAudience = (stage) => (Array.isArray(stage && stage.audience) ? stage.audience : []).filter((a) => a && str(a.name).trim())

export function joinNames(names, locale) {
  const list = names.filter(Boolean)
  if (list.length <= 1) return list[0] || ''
  if (isZh(locale)) return `${list.slice(0, -1).join('、')}和${list[list.length - 1]}`
  if (list.length === 2) return `${list[0]} and ${list[1]}`
  return `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`
}

// ---------------------------------------------------------------------------
// Α΄ Who takes the floor?

// The six who stand painted on the steps come first; the rest wait behind "More".
export const FEATURED_FIGURES = ['socrates', 'plato', 'aristotle', 'heraclitus', 'diogenes', 'epicurus']

export const featuredFigures = () => FEATURED_FIGURES.map((id) => figures.find((f) => f.id === id)).filter(Boolean)
export const moreFigures = () => figures.filter((f) => !FEATURED_FIGURES.includes(f.id))
export const guests = () => modernGuests.slice()

// Names and lines in the visitor's language come from the roster's own zh objects.
export const figureName = (figure, locale) => (figure ? localText(figure, 'name', locale) : '')
export const guestName = (guest, locale) => (guest ? localText(guest, 'name', locale) : '')

// The line the Oracle says about someone on the roster: who they were, and when.
export function figureLine(figure, locale) {
  if (!figure) return null
  return { name: figureName(figure, locale), when: localText(figure, 'lived', locale), text: localText(figure, 'known', locale) }
}
export function guestLine(guest, locale) {
  if (!guest) return null
  return { name: guestName(guest, locale), when: '', text: localText(guest, 'role', locale) }
}

// A speaker's name in the visitor's language: roster figures and guests are
// translated, names the visitor wrote are shown as written.
export function speakerLabel(speaker, locale) {
  if (!speaker) return ''
  const figure = speaker.figureId ? figures.find((f) => f.id === speaker.figureId) : null
  if (figure) return figureName(figure, locale)
  const guest = speaker.guestId ? modernGuests.find((g) => g.id === speaker.guestId) : null
  if (guest) return guestName(guest, locale)
  return bareName(speaker.name)
}

// A name the visitor wrote that belongs to someone on the roster, in either language.
export function figureForName(name) {
  const key = norm(bareName(name)).replace(/^the /, '')
  if (!key) return null
  return (
    figures.find((f) => norm(f.name).replace(/^the /, '') === key || (f.zh && f.zh.name === key)) ||
    null
  )
}

export const formatFits = (format, count) => {
  const f = FORMATS.find((x) => x.id === format)
  return !!f && count >= f.min && count <= f.max
}

// Keep the format while it fits the voices on the floor; otherwise choose the
// one that does: one voice is a speech, two a dialogue, more a symposium.
export function fitFormat(format, count) {
  if (formatFits(format, count)) return format
  if (count <= 1) return 'speech'
  if (count === 2) return 'dialogue'
  return 'panel'
}

// ---------------------------------------------------------------------------
// Β΄ When and where?

export const ERA_IDS = ['ancient', 'now', 'future', 'custom']

const ERA_SETTINGS = {
  ancient: {
    en: 'Athens, 399 BC, on the steps below the Parthenon',
    zh: '公元前399年的雅典，帕特农神庙下的台阶上',
  },
  now: {
    en: 'A city square in 2026; the speakers have stepped off the Parthenon steps into the present',
    zh: '2026年的一座城市广场；发言者们走下帕特农神庙的台阶，来到了当下',
  },
  future: { en: 'A city in 2040', zh: '2040年的一座城市' },
  custom: { en: '', zh: '' },
}

export const defaultSetting = (era, locale) => {
  const s = ERA_SETTINGS[era] || ERA_SETTINGS.now
  return isZh(locale) ? s.zh : s.en
}

// Places the Oracle offers for each age; each writes the setting line.
const PLACES = {
  ancient: [
    { id: 'steps', label: 'The Parthenon steps', setting: ERA_SETTINGS.ancient.en, zh: { label: '帕特农神庙的台阶', setting: ERA_SETTINGS.ancient.zh } },
    { id: 'agora', label: 'The Agora', setting: 'Athens, 399 BC, in the Agora beside the Painted Stoa', zh: { label: '广场', setting: '公元前399年的雅典，广场上，彩绘柱廊旁' } },
    { id: 'pnyx', label: 'The Pnyx', setting: 'Athens, 399 BC, on the Pnyx, where the Assembly meets', zh: { label: '普尼克斯山', setting: '公元前399年的雅典，公民大会集会的普尼克斯山上' } },
    { id: 'theatre', label: 'The Theatre of Dionysus', setting: 'Athens, 399 BC, in the Theatre of Dionysus below the Acropolis', zh: { label: '狄俄尼索斯剧场', setting: '公元前399年的雅典，卫城脚下的狄俄尼索斯剧场' } },
    { id: 'piraeus', label: 'The Piraeus', setting: 'The harbour of the Piraeus, 399 BC, among the ships and the merchants', zh: { label: '比雷埃夫斯港', setting: '公元前399年的比雷埃夫斯港，在船只与商人之间' } },
  ],
  now: [
    { id: 'square', label: 'A city square', setting: ERA_SETTINGS.now.en, zh: { label: '城市广场', setting: ERA_SETTINGS.now.zh } },
    { id: 'steps', label: 'The Parthenon steps at dusk', setting: 'Athens in 2026, on the steps below the Parthenon at dusk, among the visitors and the floodlights', zh: { label: '黄昏的帕特农台阶', setting: '2026年的雅典，黄昏时分帕特农神庙下的台阶上，游人与泛光灯之间' } },
    { id: 'school', label: 'A school hall', setting: 'A school hall in 2026, on a weekday evening, with parents in the seats', zh: { label: '学校礼堂', setting: '2026年一个工作日的傍晚，学校礼堂里坐满了家长' } },
    { id: 'townhall', label: 'A town hall', setting: 'A town hall meeting in 2026, open to anyone who comes', zh: { label: '市政厅', setting: '2026年的一次市政厅会议，任何人都可以来' } },
  ],
  future: [
    { id: 'city', label: 'A city in 2040', setting: ERA_SETTINGS.future.en, zh: { label: '2040年的城市', setting: ERA_SETTINGS.future.zh } },
    { id: 'chamber', label: 'A council chamber', setting: 'A council chamber in 2040, where citizens and machines sit side by side', zh: { label: '议事厅', setting: '2040年的议事厅，公民与机器并肩而坐' } },
    { id: 'square', label: 'A square under screens', setting: 'A city square in 2040, under screens that show every vote as it is cast', zh: { label: '屏幕下的广场', setting: '2040年的城市广场，头顶的屏幕实时显示每一张选票' } },
  ],
  custom: [
    { id: 'village', label: 'A village square', setting: 'A village square on market day', zh: { label: '村口广场', setting: '赶集日的村口广场' } },
    { id: 'ship', label: 'A ship at sea', setting: 'The deck of a ship far out at sea, with no port for weeks', zh: { label: '海上的船', setting: '远洋船只的甲板上，数周之内都不会靠岸' } },
    { id: 'kitchen', label: 'A kitchen table', setting: 'A family kitchen table, late at night', zh: { label: '厨房餐桌', setting: '深夜，一家人的厨房餐桌旁' } },
  ],
}

export const placesFor = (era) => (PLACES[era] || PLACES.now).map((p) => ({ ...p }))
export const placeLabel = (place, locale) => pick(place, locale).label
export const placeSetting = (place, locale) => pick(place, locale).setting

// True when the setting line is one the Oracle wrote (an era default or a
// place), so changing the age may replace it without losing the visitor's words.
export function isOfferedSetting(setting) {
  const s = str(setting).trim()
  if (!s) return true
  for (const era of Object.values(ERA_SETTINGS)) if (era.en === s || era.zh === s) return true
  for (const list of Object.values(PLACES)) for (const p of list) if (p.setting === s || p.zh.setting === s) return true
  return false
}

// An offered setting in the visitor's language (the same place, translated);
// a setting the visitor wrote comes back as written.
export function localSetting(setting, locale) {
  const s = str(setting).trim()
  if (!s) return s
  for (const era of Object.values(ERA_SETTINGS)) {
    if (era.en === s || era.zh === s) return isZh(locale) ? era.zh : era.en
  }
  for (const list of Object.values(PLACES)) {
    for (const p of list) if (p.setting === s || p.zh.setting === s) return placeSetting(p, locale)
  }
  return s
}

// ---------------------------------------------------------------------------
// Γ΄ What do they say?

export const BLANK = '___'

const TEMPLATES = {
  ancient: { en: `Athenians, hear me. I say that ${BLANK}, because ${BLANK}.`, zh: `雅典人啊，听我说。我认为${BLANK}，因为${BLANK}。` },
  now: { en: `Friends, hear me. I say that ${BLANK}, because ${BLANK}.`, zh: `朋友们，听我说。我认为${BLANK}，因为${BLANK}。` },
  future: { en: `Citizens, hear me. I say that ${BLANK}, because ${BLANK}.`, zh: `公民们，听我说。我认为${BLANK}，因为${BLANK}。` },
  custom: { en: `Hear me. I say that ${BLANK}, because ${BLANK}.`, zh: `听我说。我认为${BLANK}，因为${BLANK}。` },
}

export const wordsTemplate = (era, locale) => {
  const t = TEMPLATES[era] || TEMPLATES.now
  return isZh(locale) ? t.zh : t.en
}

export const hasBlank = (text) => /_{3,}/.test(str(text))

// [start, end] of the first blank, so the page can select it and typing replaces it.
export function firstBlank(text) {
  const m = /_{3,}/.exec(str(text))
  return m ? [m.index, m.index + m[0].length] : null
}

export function isUntouchedTemplate(text) {
  const s = str(text).trim()
  if (!s) return false
  return Object.values(TEMPLATES).some((t) => t.en === s || t.zh === s)
}

// A speaker the city knows nothing about unless they are given words.
export const knowsNothingOf = (speaker) => !str(speaker.role).trim() && !str(speaker.ideas).trim()

// The speakers step Γ΄ asks for, with the template already in place for each
// one whose words are empty. Returns [{ key, words }] changes to apply.
export function templateFills(stage, locale) {
  const era = stage && stage.era
  return namedSpeakers(stage)
    .filter((s) => !str(s.words).trim())
    .map((s) => ({ key: s.key, words: wordsTemplate(era, locale) }))
}

// ---------------------------------------------------------------------------
// Δ΄ Who listens?

// Every preset group by its English name, from either age.
const PRESET_BY_NAME = new Map(
  [...(audiencePresets.ancient || []), ...(audiencePresets.now || [])].map((p) => [p.name, p])
)

// Which presets show first for each age, and which three stand listening before
// the visitor chooses (they can remove every one).
const FEATURED_AUDIENCE = {
  ancient: [
    'Jurors of the People’s Court',
    'Rowers of the fleet',
    'Women at the fountain house',
    'Potters of the Kerameikos',
    'Metics',
    'Enslaved workers',
    'Farmers from Acharnae',
    'Merchants of the Piraeus',
  ],
  now: [
    'Parents of school-age children',
    'Software engineers',
    'Retirees',
    'High school and college students',
    'Schoolteachers',
    'Artists and writers',
    'Gig workers',
    'Journalists',
  ],
}
const DEFAULT_COUNT = 3

const poolKey = (era) => (era === 'ancient' ? 'ancient' : 'now')

export function audienceSuggestions(era) {
  const pool = audiencePresets[poolKey(era)] || []
  const featured = FEATURED_AUDIENCE[poolKey(era)]
  const byName = new Map(pool.map((p) => [p.name, p]))
  const first = featured.map((n) => byName.get(n)).filter(Boolean)
  const rest = pool.filter((p) => !featured.includes(p.name))
  const withZh = (p, isFeatured) => ({
    name: p.name,
    description: p.description,
    featured: isFeatured,
    zh: { name: (p.zh && p.zh.name) || p.name, description: (p.zh && p.zh.description) || p.description },
  })
  return [...first.map((p) => withZh(p, true)), ...rest.map((p) => withZh(p, false))]
}

// A listener group's name in the visitor's language (groups they named stay as written).
export function audienceLabel(name, locale) {
  const n = str(name).trim()
  const preset = PRESET_BY_NAME.get(n)
  return preset ? localText(preset, 'name', locale) : n
}

// What a group stands to gain or lose, as the Oracle says it. A group the
// visitor named keeps the description they gave it, if any.
export function audienceLine(group, locale) {
  const name = str(group && group.name).trim()
  if (!name) return null
  const preset = PRESET_BY_NAME.get(name)
  const text = preset ? localText(preset, 'description', locale) : str(group && group.description).trim()
  return { name: audienceLabel(name, locale), when: '', text }
}

export const defaultAudienceNames = (era) => FEATURED_AUDIENCE[poolKey(era)].slice(0, DEFAULT_COUNT)

// The three groups the Oracle seats for an age, as audience members.
export function defaultAudience(era) {
  const pool = audiencePresets[poolKey(era)] || []
  return defaultAudienceNames(era)
    .map((n) => pool.find((p) => p.name === n))
    .filter(Boolean)
    .map((p) => emptyAudienceMember({ name: p.name, description: p.description }))
}

// True when the crowd is exactly the Oracle's seating for that age, untouched,
// so a change of age may re-seat it.
export function isDefaultAudience(audience, era) {
  const names = (Array.isArray(audience) ? audience : []).map((a) => str(a && a.name).trim())
  const want = defaultAudienceNames(era)
  if (names.length !== want.length) return false
  const pool = audiencePresets[poolKey(era)] || []
  return names.every((n, i) => {
    if (n !== want[i]) return false
    const preset = pool.find((p) => p.name === n)
    return !!preset && str(audience[i].description).trim() === preset.description
  })
}

// ---------------------------------------------------------------------------
// Ε΄ What should Athens decide?

// Quarrels each age might put to its citizens. The 399 BC ones are real:
// Assembly pay had just been brought in, and the Long Walls were rebuilt in 394 BC.
const QUARRELS = {
  ancient: [
    {
      id: 'assembly-pay',
      label: 'Pay to sit in the Assembly',
      question: 'Should the city pay citizens to attend the Assembly?',
      topic: 'The Assembly has begun paying an obol to the citizens who come, so that the poor can leave their work and vote. Some say it saves the democracy; others say a paid vote is a bought vote.',
      zh: { label: '出席公民大会领钱', question: '城邦应该付钱让公民出席公民大会吗？', topic: '公民大会开始给前来的公民发一个奥波尔，好让穷人放下活计来投票。有人说这救了民主，也有人说领钱的一票就是买来的一票。' },
    },
    {
      id: 'lot',
      label: 'By lot or by vote',
      question: 'Should the city choose its officials by lot or by vote?',
      topic: 'Most offices in Athens go to citizens drawn by lot, so that any man may rule and be ruled in turn. Some now say the city should vote for those who know the work, as it already does for its generals.',
      zh: { label: '抽签还是投票', question: '城邦的官员应该抽签产生，还是投票选出？', topic: '雅典的大多数官职由抽签选出的公民担任，好让任何人都能轮流治理与被治理。如今有人说，城邦应当投票选出懂行的人，就像它选将军那样。' },
    },
    {
      id: 'women',
      label: 'Women in the Assembly',
      question: 'Should women speak in the Assembly?',
      topic: 'Women run the households that every decision lands on, yet none may speak or vote in the Assembly. A speaker proposes that they be heard.',
      zh: { label: '妇女进入公民大会', question: '妇女应该在公民大会上发言吗？', topic: '妇女操持着每一项决定最终落到的家庭，却没有一个能在公民大会上发言或投票。一位发言者提议让她们的声音被听到。' },
    },
    {
      id: 'walls',
      label: 'Rebuild the Long Walls',
      question: 'Should Athens rebuild the Long Walls to the sea?',
      topic: 'Sparta tore down the Long Walls five years ago, to the music of flutes. Rebuilding them would cost a fortune and might start a new war; without them, the city cannot be sure of its grain from the sea.',
      zh: { label: '重建长墙', question: '雅典应该重建通往大海的长墙吗？', topic: '五年前，斯巴达人伴着笛声拆毁了长墙。重建它要耗费巨资，还可能招来新的战争；没有它，城邦就保不住经海路运来的粮食。' },
    },
    {
      id: 'questions',
      label: 'Too many questions',
      question: 'Should a citizen be punished for asking too many questions?',
      topic: 'A citizen has spent years stopping people in the Agora and asking questions until their certainties fall apart. Some call it impiety and a danger to the young; others call it the best thing in the city.',
      zh: { label: '问题太多', question: '一个公民该因为问了太多问题而受罚吗？', topic: '有位公民多年来在广场上拦住行人发问，直到他们的笃定土崩瓦解。有人说这是不敬神、会败坏青年；也有人说这是城里最好的事。' },
    },
  ],
  now: [
    { id: 'machine-laws', question: 'Should the city let a machine draft its laws?', zh: { question: '城邦应该让机器起草它的法律吗？' } },
    { id: 'tutors', question: 'Should every child learn from a machine tutor?', zh: { question: '每个孩子都应该跟着机器家教学习吗？' } },
    { id: 'phones', question: 'Should children under sixteen be kept off social media?', zh: { question: '十六岁以下的孩子应该远离社交媒体吗？' } },
    { id: 'marbles', question: 'Should the Parthenon marbles come home to Athens?', zh: { question: '帕特农神庙的石雕应该回到雅典吗？' } },
    { id: 'lot', question: 'Should citizens chosen by lot help write the city’s laws?', zh: { question: '抽签选出的公民应该参与制定城邦的法律吗？' } },
  ],
  future: [
    {
      id: 'machine-vote',
      label: 'A vote for a machine',
      question: 'Should a machine have a vote?',
      topic: 'A machine that has advised the council for ten years asks for a vote of its own. It pays no tax and cannot die, but it knows the city better than anyone.',
      zh: { label: '给机器一票', question: '机器应该拥有投票权吗？', topic: '一台为议事会出谋划策十年的机器，要求拥有自己的一票。它不纳税，也不会死，却比任何人都了解这座城市。' },
    },
    {
      id: 'wage',
      label: 'A wage for everyone',
      question: 'Should the city pay every citizen a wage once machines do the work?',
      topic: 'Machines now do most of the paid work in the city. The council must decide whether to pay every citizen a wage from what the machines earn, and what people will do with their days.',
      zh: { label: '人人一份收入', question: '当机器承担了工作，城邦应该给每位公民发一份收入吗？', topic: '如今城里大部分有偿的工作都由机器承担。议事会必须决定，是否从机器挣来的钱里给每位公民发一份收入，以及人们将如何度过自己的日子。' },
    },
    {
      id: 'dead',
      label: 'The dead who speak',
      question: 'Should the dead be allowed to speak through machines?',
      topic: 'A service rebuilds the dead from their messages and their voices, and they can now speak at their own funerals and in court. The city must decide whether to let them.',
      zh: { label: '开口的逝者', question: '应该允许逝者借机器开口说话吗？', topic: '有一种服务能用逝者的讯息和声音重建他们，如今他们能在自己的葬礼上、甚至在法庭上开口。城邦必须决定是否允许。' },
    },
    {
      id: 'machine-judge',
      label: 'A machine on the bench',
      question: 'Should a machine sit as judge in the city’s courts?',
      topic: 'A machine judge has cleared a year of backlog in a month, and its verdicts are appealed less often than any human judge’s. Some say justice needs a face; others say it needs to be fast and fair.',
      zh: { label: '坐上法官席的机器', question: '机器应该在城邦的法庭上担任法官吗？', topic: '一位机器法官用一个月清完了积压一年的案子，它的判决被上诉的次数比任何人类法官都少。有人说正义需要一张面孔，也有人说正义需要又快又公平。' },
    },
  ],
  custom: [
    {
      id: 'unjust-law',
      label: 'An unjust law',
      question: 'Is it ever right to break an unjust law?',
      topic: 'A law that everyone agrees is unjust is still the law. A citizen has broken it in public and waits to be judged.',
      zh: { label: '不公正的法律', question: '违反不公正的法律，有时是对的吗？', topic: '一条人人都认为不公正的法律，仍然是法律。一位公民当众违反了它，正等候审判。' },
    },
    {
      id: 'the-few',
      label: 'The few or the many',
      question: 'Should the few who know rule the many who do not?',
      topic: 'Those who understand a problem best are few, and those who must live with the answer are many. Who should decide?',
      zh: { label: '少数还是多数', question: '懂的少数人应该统治不懂的多数人吗？', topic: '最懂一个问题的人是少数，而必须承受答案的人是多数。该由谁来决定？' },
    },
    {
      id: 'pleasure',
      label: 'A pleasant life',
      question: 'Is a good life a pleasant life?',
      topic: 'A friend has given up every ambition for a quiet, pleasant life among friends and gardens. Is that wisdom, or waste?',
      zh: { label: '愉快的生活', question: '美好的生活就是愉快的生活吗？', topic: '一位朋友放弃了一切抱负，只求在朋友和花园之间过安静愉快的日子。这是智慧，还是浪费？' },
    },
    {
      id: 'strangers',
      label: 'Strangers at the gate',
      question: 'Should the city open its gates to strangers?',
      topic: 'A ship of strangers has come in, fleeing a war. The city has room, but not much, and not everyone wants them to stay.',
      zh: { label: '门前的陌生人', question: '城邦应该向陌生人敞开大门吗？', topic: '一船逃离战火的陌生人来到了这里。城里有地方，但不多，也不是每个人都愿意他们留下。' },
    },
  ],
}

export const quarrelsFor = (era) => (QUARRELS[era] || QUARRELS.now).map((q) => ({ ...q }))
export const quarrelText = (quarrel, locale) => pick(quarrel, locale).question

// The full form's Γ΄ offers the same quarrels as matters to argue: a short label
// and the situation behind it, in the visitor's language. Today's quarrels
// live in the locale files (parthenon.builder.sparks), so 'now' has none here.
export function mattersFor(era, locale) {
  if (!Object.prototype.hasOwnProperty.call(QUARRELS, era) || era === 'now') return []
  return QUARRELS[era]
    .filter((q) => q.label && q.topic)
    .map((q) => ({ id: q.id, label: pick(q, locale).label || q.label, topic: pick(q, locale).topic || q.topic }))
}

const namesFor = (stage, locale) => namedSpeakers(stage).map((s) => speakerLabel(s, locale))

function topicLine(stage) {
  const line = (str(stage && stage.topic).split('\n').find((l) => l.trim()) || '').replace(/\s+/g, ' ').trim()
  return line.length > 80 ? `${line.slice(0, 79).replace(/\s+\S*$/, '')}…` : line
}

// The quarrel first, then what the Chronicle should find out about it.
export function quarrelQuestion(stage, quarrel, locale) {
  const q = quarrelText(quarrel, locale)
  const names = joinNames(namesFor(stage, locale).slice(0, 3), locale)
  const ancient = stage && stage.era === 'ancient'
  if (isZh(locale)) {
    const who = names || '发言者们'
    const city = ancient ? '雅典' : '这座城市'
    return `${q}听了${who}的话之后，${city}在接下来的几天里如何抉择？谁改变了主意，哪些论点占了上风，城邦最终作出了什么决定？`
  }
  const who = names || 'the speakers'
  const city = ancient ? 'Athens' : 'the city'
  return `${q} After hearing ${who}, how does ${city} decide over the following days? Who changes their mind, which arguments carry the day, and what does the city resolve?`
}

// The Oracle's own question, from composeStage's suggestion (and its Chinese twin).
export function suggestQuestionFor(stage, locale) {
  if (!isZh(locale)) return suggestQuestion(stage)
  const names = joinNames(namesFor(stage, locale).slice(0, 3), locale)
  const topic = topicLine(stage)
  const on = topic ? `关于“${topic}”` : ''
  const crowd = stage && stage.era === 'ancient' ? '雅典' : '人们'
  const format = FORMATS.find((f) => f.id === (stage && stage.format)) ? stage.format : 'panel'
  switch (format) {
    case 'speech':
      return `听了${names || '发言者'}${on}的发言之后，${crowd}在接下来的几天里作何反应？谁被说服，谁在反驳，哪些论点传播开来？`
    case 'dialogue':
      return `${names || '两位发言者'}${on}相互诘问之后，${crowd}在接下来的几天里站在哪一边？谁改变了主意，哪些论点传播开来，大家最终作出了什么决定？`
    case 'trial':
      return `听了${names || '控方与辩方'}${on}的陈词之后，公民陪审团如何投票，为什么？在宣判前的几天里，哪些论点打动了陪审员，大家是否接受这个判决？`
    case 'assembly':
      return `听了${names || '发言者们'}${on}的发言之后，公民大会在周末如何投票，为什么？哪些论点赢得了选票，谁改变了主意，大家是否接受这个结果？`
    default:
      return `听了${names || '发言者们'}${on}的发言之后，${crowd}在接下来的几天里作何反应？谁改变了主意，哪些论点传播开来，大家最终作出了什么决定？`
  }
}

// Which offered question the current one is, if the visitor has not changed it:
// 'suggestion', a quarrel id, or null (their own words).
export function questionSource(stage, locale) {
  const q = str(stage && stage.question).trim()
  if (!q) return null
  if (q === suggestQuestionFor(stage, locale).trim()) return 'suggestion'
  const quarrel = quarrelsFor(stage && stage.era).find((x) => q === quarrelQuestion(stage, x, locale).trim())
  return quarrel ? quarrel.id : null
}

// On arriving at Ε΄: the question to put in the box, or null to leave it.
// An empty box gets the Oracle's suggestion; an offered question the visitor
// never touched (lastOffered) is rewritten for the names now on the floor.
export function questionToOffer(stage, locale, lastOffered = '') {
  const q = str(stage && stage.question).trim()
  if (!q) return suggestQuestionFor(stage, locale)
  if (lastOffered && q === str(lastOffered).trim()) {
    const quarrel = quarrelsFor(stage.era).find((x) => {
      const text = quarrelText(x, locale)
      return q.startsWith(text)
    })
    const fresh = quarrel ? quarrelQuestion(stage, quarrel, locale) : suggestQuestionFor(stage, locale)
    return fresh === q ? null : fresh
  }
  return null
}

// ---------------------------------------------------------------------------
// Validity, step by step

// Problems that keep the visitor on a step, as { code, params }.
export function stepProblems(stage, stepId) {
  const s = stage && typeof stage === 'object' ? stage : {}
  const named = namedSpeakers(s)
  const problems = []
  switch (stepId) {
    case 'who': {
      if (!named.length) {
        problems.push({ code: 'whoNone', params: {} })
        break
      }
      const counts = new Map()
      for (const sp of named) {
        const key = norm(bareName(sp.name))
        counts.set(key, (counts.get(key) || 0) + 1)
      }
      for (const sp of named) {
        const key = norm(bareName(sp.name))
        if (counts.get(key) > 1) {
          problems.push({ code: 'whoRepeated', params: { name: bareName(sp.name) } })
          counts.set(key, 0)
        }
      }
      if (named.length > MAX_SPEAKERS) problems.push({ code: 'whoTooMany', params: { max: MAX_SPEAKERS } })
      else if (!formatFits(s.format, named.length)) {
        const f = FORMATS.find((x) => x.id === s.format)
        problems.push({ code: 'whoFormat', params: { format: f ? f.id : 'panel', count: named.length } })
      }
      break
    }
    case 'where':
      if (!str(s.setting).trim()) problems.push({ code: 'whereNone', params: {} })
      break
    case 'words':
      for (const sp of named) {
        const words = str(sp.words).trim()
        if (hasBlank(words)) problems.push({ code: 'wordsBlank', params: { key: sp.key, name: bareName(sp.name) } })
        else if (!words && knowsNothingOf(sp)) problems.push({ code: 'wordsNeeded', params: { key: sp.key, name: bareName(sp.name) } })
      }
      break
    case 'listeners':
      if (namedAudience(s).length > MAX_AUDIENCE) problems.push({ code: 'listenersTooMany', params: { max: MAX_AUDIENCE } })
      break
    case 'question':
      if (!str(s.question).trim()) problems.push({ code: 'questionNone', params: {} })
      else if (hasBlank(s.question)) problems.push({ code: 'questionBlank', params: {} })
      break
    default:
      break
  }
  return problems
}

export const stepValid = (stage, stepId) => stepProblems(stage, stepId).length === 0

// The first step that still needs an answer, or SUMMARY when all are answered.
export function firstOpenStep(stage) {
  const i = STEPS.findIndex((st) => !stepValid(stage, st.id))
  return i === -1 ? SUMMARY : i
}

// Every problem left, each with the step it belongs to.
export const allProblems = (stage) =>
  STEPS.flatMap((st, i) => stepProblems(stage, st.id).map((p) => ({ ...p, step: i, stepId: st.id })))

// Words still holding a blank, for the full form's list of problems.
export const blankSpeakers = (stage) => namedSpeakers(stage).filter((s) => hasBlank(s.words)).map((s) => bareName(s.name))

// ---------------------------------------------------------------------------
// The Oracle's mark: the tripod at Delphi as the vase painters drew it. A deep
// bronze cauldron (lebes) hangs between three long straight legs; its two ring
// handles stand high on the legs above the lip; the legs end in lion's paws,
// the third one seen behind; and below, from the cleft in the rock, a thin
// thread of vapour rises toward the bowl. Plain path data in a 40 x 40 box, so
// the walk, the full form and the small return button draw the same tripod.
// Parts marked `fine` are left out of the small mark; `vapour` parts are the
// threads the walk lets rise (one early, one late) and holds still under
// reduced motion.

const r2 = (v) => Math.round(v * 100) / 100
const ringPath = ([cx, cy], r) => `M${r2(cx - r)} ${cy}a${r} ${r} 0 1 0 ${r2(2 * r)} 0a${r} ${r} 0 1 0 ${r2(-2 * r)} 0Z`
const ellipsePath = ({ cx, cy, rx, ry }) => `M${r2(cx - rx)} ${cy}a${rx} ${ry} 0 1 0 ${r2(2 * rx)} 0a${rx} ${ry} 0 1 0 ${r2(-2 * rx)} 0Z`
const legPath = ([x1, y1, x2, y2]) => `M${x1} ${y1} ${x2} ${y2}`
// A lion's paw at the foot of a front leg: the ankle swells and the paw rests
// low and round on the ground, toes turned outward (side -1 left, +1 right).
const pawPath = ([, , x, y], ground, side) => {
  const X = (dx) => r2(x + dx * side)
  const Y = (dy) => r2(ground + dy)
  const g = ground - y // the leg stops where the ankle begins
  return (
    `M${X(-0.35)} ${Y(-g)}C${X(-0.5)} ${Y(-1.2)} ${X(-0.9)} ${Y(-0.2)} ${X(-0.7)} ${Y(0)}` +
    `H${X(1.7)}C${X(2.2)} ${Y(0)} ${X(2.2)} ${Y(-0.9)} ${X(1.5)} ${Y(-1.1)}` +
    `C${X(0.9)} ${Y(-1.3)} ${X(0.5)} ${Y(-1.5)} ${X(0.35)} ${Y(-g)}` +
    `M${X(1.05)} ${Y(0)}C${X(1.05)} ${Y(-0.4)} ${X(1.2)} ${Y(-0.7)} ${X(1.5)} ${Y(-0.9)}`
  )
}

const TRIPOD_LIP = Object.freeze({ cx: 20, cy: 10.3, rx: 7.9, ry: 1.15 })
// The cauldron below its lip, deeper than a half sphere.
const TRIPOD_BOWL = Object.freeze({ left: 12.9, right: 27.1, top: 10.9, bottom: 19.2 })
// [x1, y1, x2, y2] from the top of each leg to its paw; the rear leg hangs from the bowl.
const TRIPOD_LEGS = Object.freeze({
  left: Object.freeze([12.3, 7.4, 9.9, 34.6]),
  right: Object.freeze([27.7, 7.4, 30.1, 34.6]),
  rear: Object.freeze([23.4, 18.2, 23.9, 32.8]),
})
const TRIPOD_GROUND = 36.6
// The ring handles stand high, on the tops of the two front legs.
const TRIPOD_RING_R = 1.9
const TRIPOD_RINGS = Object.freeze([Object.freeze([12.3, 5.5]), Object.freeze([27.7, 5.5])])

export const TRIPOD = Object.freeze({
  viewBox: '0 0 40 40',
  size: 40,
  lip: TRIPOD_LIP,
  bowl: TRIPOD_BOWL,
  legs: TRIPOD_LEGS,
  rings: TRIPOD_RINGS,
  ringR: TRIPOD_RING_R,
  groundY: TRIPOD_GROUND,
  parts: Object.freeze(
    [
      {
        id: 'vapour',
        vapour: 'early',
        fine: true,
        d: 'M19.2 37C17.8 35.4 19.8 33.8 18.6 31.8C17.6 30.2 19.4 28.6 18.6 26.6C18.2 25.4 18.8 24.2 19.4 23.2',
      },
      {
        id: 'vapour-late',
        vapour: 'late',
        fine: true,
        d: 'M19.4 37.2C20.8 35.8 19.2 34.2 20.2 32.4C21 31 19.8 29.4 20.4 27.6C20.7 26.6 20.3 25.6 19.8 24.8',
      },
      // The ground between the paws, split by the cleft.
      { id: 'cleft', fine: true, d: 'M12.8 36.6H16.8L17.7 37.4 18.4 37 19.2 38.5 19.9 37.1 20.6 37.4 21.6 36.6H27.2' },
      { id: 'legs', d: [TRIPOD_LEGS.left, TRIPOD_LEGS.right].map(legPath).join('') },
      { id: 'rear-leg', d: legPath(TRIPOD_LEGS.rear) },
      {
        id: 'paws',
        fine: true,
        d:
          pawPath(TRIPOD_LEGS.left, TRIPOD_GROUND, -1) +
          pawPath(TRIPOD_LEGS.right, TRIPOD_GROUND, 1) +
          // the rear paw, seen from behind the cleft
          'M23.1 33.7C23.2 32.8 24.6 32.8 24.7 33.7Z',
      },
      {
        id: 'lebes',
        d: `M${TRIPOD_BOWL.left} ${TRIPOD_BOWL.top}C13.2 15.8 16.2 ${TRIPOD_BOWL.bottom} 20 ${TRIPOD_BOWL.bottom}C23.8 ${TRIPOD_BOWL.bottom} 26.8 15.8 ${TRIPOD_BOWL.right} ${TRIPOD_BOWL.top}`,
      },
      { id: 'lip', d: ellipsePath(TRIPOD_LIP) },
      { id: 'rings', d: TRIPOD_RINGS.map((c) => ringPath(c, TRIPOD_RING_R)).join('') },
    ].map((p) => Object.freeze(p)),
  ),
})

// 'full': both threads of vapour (the walk, where they rise in turn);
// 'still': one thread, drawn at rest (the full form's altar);
// 'small': the tripod alone, for marks of about 20px.
export function tripodMark(size = 'full') {
  if (size === 'small') return TRIPOD.parts.filter((p) => !p.fine)
  if (size === 'still') return TRIPOD.parts.filter((p) => p.vapour !== 'late')
  return TRIPOD.parts.slice()
}
