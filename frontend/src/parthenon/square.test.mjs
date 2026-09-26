import test from 'node:test'
import assert from 'node:assert/strict'
import {
  GROUND,
  IMAGE_RATIO,
  pointInPolygon,
  homeSpots,
  walkToward,
  depthScale,
  viewWindow,
  toBox,
  hourAt,
  skyAt,
  arcPath,
  hourWords,
  cleanSpeech,
  nameKey,
  ribbonWords,
  withoutOwnName,
  indexPosts,
  beatOf,
  isRibbonBeat,
  beatDuration,
  roundPause,
  lightAt,
  murmurLevel,
  beatsPerSecond,
  PLATES,
  plateOf,
  plateSrcset,
  gatheringEra,
  stanceSide,
  stanceLedger,
  partOfDay,
  turnOf,
  stanceReading,
  hashString
} from './square.js'

const citizens = [
  { id: 0, name: 'Sand', stance: 'observer' },
  { id: 1, name: 'Despina Nomikou', stance: 'neutral' },
  { id: 2, name: 'Marina Kavvadia', stance: 'opposing' },
  { id: 3, name: 'Ammolith Compute', stance: 'supportive' },
  { id: 4, name: 'Anneke Visser', stance: 'supportive' },
  { id: 5, name: 'Yes for Psammos', stance: 'supportive' },
  { id: 6, name: 'The Cold Bay Campaign', stance: 'opposing' },
  { id: 9, name: 'Stelios Moraitis', stance: 'opposing' },
  { id: 11, name: 'Mirela Dervishi', stance: 'supportive' },
  { id: 12, name: 'Yannis Frangiadakis', stance: 'supportive' },
  { id: 14, name: 'Manolis Syrigos', stance: 'opposing' },
  { id: 18, name: 'Father Serafeim Delatolas', stance: 'neutral' }
]

const seenDist = (a, b) => Math.hypot((a.x - b.x) * IMAGE_RATIO, a.y - b.y)

test('home spots stand on the ground, one per citizen', () => {
  const spots = homeSpots(citizens)
  assert.equal(Object.keys(spots).length, citizens.length)
  for (const c of citizens) {
    const p = spots[String(c.id)]
    assert.ok(p, `spot for ${c.name}`)
    assert.ok(pointInPolygon(p.x, p.y, GROUND), `${c.name} stands on the ground`)
  }
})

test('home spots are deterministic by name, whatever the order', () => {
  const a = homeSpots(citizens)
  const b = homeSpots([...citizens].reverse())
  assert.deepEqual(a, b)
  assert.deepEqual(homeSpots(citizens), a)
})

test('home spots leave room between coins', () => {
  const spots = Object.values(homeSpots(citizens))
  let min = Infinity
  for (let i = 0; i < spots.length; i++) for (let j = i + 1; j < spots.length; j++) min = Math.min(min, seenDist(spots[i], spots[j]))
  assert.ok(min > 0.07, `closest pair ${min.toFixed(3)} is too close`)
})

test('twenty citizens still fit with room', () => {
  const many = Array.from({ length: 20 }, (_, i) => ({ id: i, name: `Citizen ${i}`, stance: ['supportive', 'opposing', 'neutral'][i % 3] }))
  const spots = Object.values(homeSpots(many))
  assert.equal(spots.length, 20)
  let min = Infinity
  for (let i = 0; i < spots.length; i++) for (let j = i + 1; j < spots.length; j++) min = Math.min(min, seenDist(spots[i], spots[j]))
  assert.ok(min > 0.06, `closest pair ${min.toFixed(3)} is too close`)
})

test('supporters lean left and the opposed lean right', () => {
  const spots = homeSpots(citizens)
  const mean = (side) => {
    const xs = citizens.filter((c) => stanceSide(c.stance) === side).map((c) => spots[String(c.id)].x)
    return xs.reduce((s, x) => s + x, 0) / xs.length
  }
  assert.ok(mean('for') < mean('against'))
})

test('an empty gathering has no spots', () => {
  assert.deepEqual(homeSpots([]), {})
  assert.deepEqual(homeSpots(null), {})
})

test('walking toward someone stops short and stays on the ground', () => {
  const from = { x: 0.25, y: 0.5 }
  const to = { x: 0.7, y: 0.6 }
  const p = walkToward(from, to)
  assert.ok(pointInPolygon(p.x, p.y, GROUND))
  assert.ok(seenDist(p, to) < seenDist(from, to), 'closer than before')
  assert.ok(seenDist(p, to) >= 0.11, 'never onto them')
  assert.deepEqual(walkToward(from, from), from)
  assert.deepEqual(walkToward(from, { x: 0.26, y: 0.5 }), from, 'already beside them')
  assert.equal(walkToward(null, to), null)
  assert.deepEqual(walkToward(from, null), from)
})

test('coins further off are smaller', () => {
  assert.ok(depthScale(0.37) < depthScale(0.8))
  assert.ok(depthScale(0.0) >= 0.8)
  assert.ok(depthScale(1.0) <= 1.1)
})

test('the frame shows the right part of the painting', () => {
  const wide = viewWindow(16 / 9)
  assert.equal(wide.w, 1)
  assert.equal(wide.x0, 0)
  const phone = viewWindow(4 / 3, 0.32)
  assert.equal(phone.w, 0.75)
  assert.ok(Math.abs(phone.x0 - 0.08) < 1e-9)
  // The whole ground is inside the phone frame.
  for (const [x, y] of GROUND) {
    const b = toBox({ x, y }, phone)
    assert.ok(b.left > 0 && b.left < 100, `ground x ${x} inside the phone frame`)
    assert.ok(b.top > 0 && b.top < 100)
  }
  assert.deepEqual(toBox({ x: 0.5, y: 0.5 }, wide), { left: 50, top: 50 })
})

test('the hour follows the rounds', () => {
  assert.equal(hourAt(0), 0)
  assert.equal(hourAt(17), 17)
  assert.equal(hourAt(30), 6)
  assert.equal(hourAt(5, 30), 2.5)
  assert.equal(hourAt(6, 60, 0.5), 6.5)
})

test('the sun crosses by day and the moon by night', () => {
  const dawn = skyAt(6)
  assert.equal(dawn.body, 'sun')
  assert.equal(dawn.t, 0)
  const noon = skyAt(12)
  assert.equal(noon.body, 'sun')
  assert.equal(noon.altitude, 1)
  assert.equal(noon.left, 50)
  assert.ok(noon.top < dawn.top, 'higher at noon')
  const dusk = skyAt(17.99)
  assert.ok(dusk.left > 90)
  const night = skyAt(0)
  assert.equal(night.body, 'moon')
  assert.equal(night.altitude, 1)
  assert.equal(night.daylight, 0)
  assert.equal(skyAt(18).body, 'moon')
  assert.equal(skyAt(18).t, 0)
  assert.equal(skyAt(-1).body, 'moon')
  assert.ok(arcPath().startsWith('M 3.00 17.00'))
})

test('the day painting shows by day and eases through dawn and dusk', () => {
  assert.deepEqual(lightAt(0), { day: 0, warm: 0 })
  assert.equal(lightAt(12).day, 1)
  assert.equal(lightAt(12).warm, 0)
  assert.equal(lightAt(23).day, 0)
  const dawn = lightAt(6.25)
  assert.ok(dawn.day > 0 && dawn.day < 1, 'half lit at dawn')
  assert.ok(dawn.warm > 0.8, 'warm at dawn')
  assert.ok(lightAt(18.2).warm > 0.9, 'warm at dusk')
  assert.ok(lightAt(18.5).day < lightAt(17.5).day, 'the light goes at dusk')
  assert.equal(lightAt(24).day, lightAt(0).day)
})

test('the murmur follows the pace', () => {
  assert.equal(murmurLevel(0), 0.25)
  assert.ok(murmurLevel(0.5) < murmurLevel(2))
  assert.ok(murmurLevel(100) <= 1)
  assert.equal(beatsPerSecond([1000, 5000, 6000, 9000], 10000, 6000), 0.5)
  assert.equal(beatsPerSecond([], 10000), 0)
})

test('each Athens has its painting, and a gathering knows its era', () => {
  for (const plate of Object.values(PLATES)) {
    assert.ok(plate.ground.length >= 5)
    for (const [x, y] of plate.ground) assert.ok(x > 0.15 && x < 0.85 && y > 0.3 && y < 0.92, `${plate.key} ground inside the painting`)
    assert.ok(plate.stoaY < Math.min(...plate.ground.map((p) => p[1])), `${plate.key} Stoa above its ground`)
    const spots = homeSpots(citizens, { ground: plate.ground })
    for (const p of Object.values(spots)) assert.ok(pointInPolygon(p.x, p.y, plate.ground))
    // A phone's 4:3 crop keeps the whole ground in frame.
    const phone = viewWindow(4 / 3, plate.phoneX)
    for (const [x, y] of plate.ground) {
      const b = toBox({ x, y }, phone)
      assert.ok(b.left > 2 && b.left < 98, `${plate.key} ground x ${x} inside the phone frame`)
    }
  }
  assert.equal(plateOf('ancient').key, 'ancient')
  assert.equal(plateOf('').key, 'now')
  assert.equal(plateSrcset(PLATES.now, 'day').split(', ').length, 3)
  assert.ok(plateSrcset(PLATES.ancient).includes('agora-ancient-night-2560.jpg 2560w'))
  const scrolls = ['socrates-the-apology.md', 'plato-the-cave.md']
  assert.equal(gatheringEra({ files: [{ filename: 'socrates-the-apology.md' }] }, scrolls), 'ancient')
  assert.equal(gatheringEra({ files: [{ filename: 'arrival-when-sand-speaks.md' }], requirement: 'Plato, 399 BC' }, scrolls), 'now')
  assert.equal(gatheringEra({ files: ['stage-the-trial.md'], summary: 'The trial of Socrates in ancient Athens.' }, scrolls), 'ancient')
  assert.equal(gatheringEra({ files: ['stage-the-quarry.md'], requirement: 'Should the island sign the lease?' }, scrolls), 'now')
  assert.equal(gatheringEra({}, scrolls), 'now')
})

test('the hour in words', () => {
  assert.deepEqual(hourWords(0), { key: 'midnight', n: 12 })
  assert.deepEqual(hourWords(12.5), { key: 'noon', n: 12 })
  assert.deepEqual(hourWords(3), { key: 'night', n: 3 })
  assert.deepEqual(hourWords(7), { key: 'morning', n: 7 })
  assert.deepEqual(hourWords(15), { key: 'afternoon', n: 3 })
  assert.deepEqual(hourWords(19), { key: 'evening', n: 7 })
  assert.deepEqual(hourWords(23), { key: 'lateNight', n: 11 })
})

test('hashtags keep the word and handles become names', () => {
  assert.equal(cleanSpeech('Justice is done. #ImpietyPunished'), 'Justice is done. Impiety Punished')
  assert.equal(cleanSpeech('#cold_bay now'), 'cold bay now')
  assert.equal(cleanSpeech('Read it, @despina_nomikou_466.'), 'Read it, Despina Nomikou.')
  assert.equal(cleanSpeech('@yannis: no'), 'Yannis: no')
  assert.equal(cleanSpeech('write to a@b.org'), 'write to a@b.org')
  assert.equal(cleanSpeech('We are #1 on the list'), 'We are #1 on the list')
  assert.equal(cleanSpeech('C# and &#39;'), 'C# and &#39;')
  const known = (h) => (nameKey(h) === 'mirela dervishi' ? 'Mirela Dervishi' : null)
  assert.equal(cleanSpeech('Thank you @mirela.dervishi', known), 'Thank you Mirela Dervishi')
  assert.equal(cleanSpeech(''), '')
  assert.equal(cleanSpeech(null), '')
})

test('names match however they are written', () => {
  assert.equal(nameKey('Despina Nomikou'), 'despina nomikou')
  assert.equal(nameKey('despina_nomikou_466'), 'despina nomikou')
  assert.equal(nameKey('@Despina.Nomikou'), 'despina nomikou')
  assert.equal(nameKey("Psammos Fishermen's Cooperative"), 'psammos fishermen s cooperative')
})

test('a ribbon carries a few words of the line', () => {
  assert.equal(ribbonWords('The council meets Wednesday, October 14. I hold the casting vote.'), 'The council meets Wednesday, October 14.')
  assert.equal(ribbonWords('Correction.\n\nPoints now circulating are not the Compact.'), 'Correction. Points now circulating are not the Compact.')
  const long = ribbonWords('Forty-five permanent jobs and a roof that does not drip on two hundred and twelve pupils are a first year, not a fairy tale')
  assert.ok(long.endsWith('…'))
  assert.ok(long.length <= 73 && long.split(' ').length <= 14)
  assert.ok(!/[,\s]…$/.test(long))
  // A cut falls at a clause when one fits, else at a word, never on a word that leads nowhere.
  assert.equal(
    ribbonWords('If the Compact passes as written, the quarry becomes a server hall and the bay a radiator for twenty-five years, and nobody asked the fishermen.'),
    'If the Compact passes as written, the quarry becomes a server hall…'
  )
  const words = 'We, the fishermen of the north cove, who have watched the water warm for twenty summers, say no to this and to every lease like it'
  for (const max of [40, 56, 72, 96]) {
    const r = ribbonWords(words, { maxChars: max, maxWords: 40 })
    assert.ok(r.length <= max + 1, `fits ${max}`)
    assert.ok(words.startsWith(r.slice(0, -1).replace(/[,.]$/, '')), `whole words only at ${max}: ${r}`)
    assert.ok(!/\b(the|and|of|to|a)…$/i.test(r), `no dangling word at ${max}: ${r}`)
  }
  // A colon carries the line on to what it announces.
  assert.equal(ribbonWords('Ammolith offers Psammos a lease: jobs, water, a school.'), 'Ammolith offers Psammos a lease: jobs, water, a school.')
  const label = ribbonWords('The Cold Bay Campaign: we will not trade the bay that feeds us for a radiator the size of a quarry, not for any lease.')
  assert.ok(label.startsWith('The Cold Bay Campaign: we will not'), label)
  assert.equal(withoutOwnName('Yes for Psammos: about 600 young parents.', 'Yes for Psammos'), 'About 600 young parents.')
  assert.equal(withoutOwnName('Yes for Psammos is wrong.', 'Yes for Psammos'), 'Yes for Psammos is wrong.')
  assert.equal(withoutOwnName('Hello', ''), 'Hello')
  assert.equal(ribbonWords(''), '')
  assert.equal(ribbonWords('Yes'), 'Yes')
})

const record = [
  { agent_id: 11, agent_name: 'Mirela Dervishi', platform: 'reddit', action_type: 'CREATE_POST', action_args: { post_id: 15, content: 'I clean the rooms.' }, round_num: 7 },
  { agent_id: 12, agent_name: 'Yannis Frangiadakis', platform: 'reddit', action_type: 'CREATE_COMMENT', action_args: { comment_id: 55, content: 'Twenty years on the floors.' }, round_num: 14 },
  { agent_id: 12, agent_name: 'Yannis Frangiadakis', platform: 'reddit', action_type: 'LIKE_POST', action_args: { post_id: 15, post_author_name: 'Mirela Dervishi' }, round_num: 14 },
  { agent_id: 4, agent_name: 'Anneke Visser', platform: 'twitter', action_type: 'QUOTE_POST', action_args: { new_post_id: 56, original_author_name: 'The Cold Bay Campaign', quote_content: 'Correction.' }, round_num: 9 },
  { agent_id: 3, agent_name: 'Ammolith Compute', platform: 'twitter', action_type: 'DO_NOTHING', action_args: {}, round_num: 17 },
  { agent_id: 12, agent_name: 'Yannis Frangiadakis', platform: 'reddit', action_type: 'FOLLOW', action_args: { target_user_name: 'Mirela Dervishi' }, round_num: 14 },
  { agent_id: 12, agent_name: 'Yannis Frangiadakis', platform: 'twitter', action_type: 'REPOST', action_args: { original_author_name: 'Anneke Visser' }, round_num: 14 },
  { agent_id: 9, agent_name: 'Stelios Moraitis', platform: 'reddit', action_type: 'DISLIKE_POST', action_args: { post_author_name: 'Anneke Visser' }, round_num: 14 }
]
const ids = { 'mirela dervishi': '11', 'yannis frangiadakis': '12', 'anneke visser': '4', 'the cold bay campaign': '6', 'ammolith compute': '3', 'stelios moraitis': '9' }
const idOfName = (n) => ids[nameKey(n)] ?? null

test('the record says who said which post', () => {
  const posts = indexPosts(record, idOfName)
  assert.equal(posts.get('stoa:15'), '11')
  assert.equal(posts.get('agora:56'), '4')
  assert.equal(posts.get('agora:15'), undefined)
})

test('each action becomes a beat of the square', () => {
  const posts = indexPosts(record, idOfName)
  const ctx = {
    idOfName,
    postAuthor: (place, id) => posts.get(`${place}:${id}`) ?? null,
    commentPost: (place, id) => (place === 'stoa' && id === 55 ? 15 : null)
  }
  const [speak, answer, nod, quote, quiet, follow, repeat, shake] = record.map((a) => beatOf(a, ctx))
  assert.deepEqual([speak.kind, speak.from, speak.place, speak.words], ['speak', '11', 'stoa', 'I clean the rooms.'])
  assert.deepEqual([answer.kind, answer.from, answer.to], ['answer', '12', '11'])
  assert.deepEqual([nod.kind, nod.to], ['nod', '11'])
  assert.deepEqual([quote.kind, quote.to, quote.place, quote.words], ['quote', '6', 'agora', 'Correction.'])
  assert.equal(quiet.kind, 'quiet')
  assert.deepEqual([follow.kind, follow.to], ['follow', '11'])
  assert.deepEqual([repeat.kind, repeat.to], ['repeat', '4'])
  assert.deepEqual([shake.kind, shake.to], ['shake', '4'])
  assert.ok(isRibbonBeat(answer) && isRibbonBeat(quote) && isRibbonBeat(speak))
  assert.ok(!isRibbonBeat(nod) && !isRibbonBeat(quiet))
})

test('an answer to no one known stands where it is', () => {
  const b = beatOf({ agent_id: 1, platform: 'reddit', action_type: 'CREATE_COMMENT', action_args: { comment_id: 999, content: 'Hm.' } }, { idOfName })
  assert.equal(b.kind, 'answer')
  assert.equal(b.to, null)
  const self = beatOf({ agent_id: 4, platform: 'twitter', action_type: 'QUOTE_POST', action_args: { original_author_name: 'Anneke Visser', quote_content: 'Again.' } }, { idOfName })
  assert.equal(self.to, null, 'quoting yourself is no walk')
})

test('the replay keeps a pace at every speed', () => {
  const speak = { kind: 'speak' }
  assert.ok(beatDuration(speak, 1) > beatDuration(speak, 4))
  assert.ok(beatDuration(speak, 4) > beatDuration(speak, 16))
  assert.ok(beatDuration({ kind: 'quiet' }, 16) >= 60)
  assert.ok(beatDuration({ kind: 'nod' }, 1) < beatDuration(speak, 1))
  assert.ok(roundPause(1) > roundPause(16))
})

test('stances fall on three sides', () => {
  assert.equal(stanceSide('supportive'), 'for')
  assert.equal(stanceSide('opposing'), 'against')
  assert.equal(stanceSide('neutral'), 'undecided')
  assert.equal(stanceSide('observer'), 'undecided')
  assert.equal(stanceSide(''), 'undecided')
  assert.equal(stanceSide(null), 'undecided')
})

test('where they stood, when only the beginning is known', () => {
  const agents = [
    { agent_id: 3, entity_name: 'Ammolith Compute', entity_type: 'TechCompany', stance: 'supportive', sentiment_bias: 0.8 },
    { agent_id: 11, entity_name: 'Mirela Dervishi', entity_type: 'Person', stance: 'supportive', sentiment_bias: 0.4 },
    { agent_id: 9, entity_name: 'Stelios Moraitis', entity_type: 'Fisher', stance: 'opposing', sentiment_bias: -0.9 },
    { agent_id: 6, entity_name: 'The Cold Bay Campaign', entity_type: 'CivicCampaign', stance: 'opposing', sentiment_bias: -0.88 },
    { agent_id: 0, entity_name: 'Sand', entity_type: 'Aisystem', stance: 'observer' },
    { agent_id: 1, entity_name: 'despina_nomikou_466', entity_type: 'PublicOfficial', stance: 'neutral' }
  ]
  const ledger = stanceLedger(agents)
  assert.equal(ledger.knowsDrift, false)
  assert.deepEqual(ledger.moved, [])
  assert.deepEqual(ledger.rows.for.map((r) => r.name), ['Ammolith Compute', 'Mirela Dervishi'])
  assert.deepEqual(ledger.rows.against.map((r) => r.name), ['Stelios Moraitis', 'The Cold Bay Campaign'])
  assert.deepEqual(ledger.rows.undecided.map((r) => r.name), ['Despina Nomikou', 'Sand'])
})

test('who moved, when the gathering records it', () => {
  const ledger = stanceLedger([
    { agent_id: 1, entity_name: 'Despina Nomikou', stance: 'neutral', current_stance: 'supportive' },
    { agent_id: 2, entity_name: 'Marina Kavvadia', stance: 'opposing', stance_history: ['opposing', { stance: 'opposing' }] },
    { agent_id: 3, entity_name: 'Froso Leontari', stance: 'neutral', stance_history: [{ stance: 'opposing' }] }
  ])
  assert.equal(ledger.knowsDrift, true)
  assert.deepEqual(ledger.moved.map((m) => [m.name, m.from, m.to]), [
    ['Despina Nomikou', 'undecided', 'for'],
    ['Froso Leontari', 'undecided', 'against']
  ])
})

test('hashing is stable', () => {
  assert.equal(hashString('Sand'), hashString('Sand'))
  assert.notEqual(hashString('Sand'), hashString('Sane'))
})

test('the time of day at the end of a round, by the city clock', () => {
  assert.deepEqual(partOfDay(14, 60), { day: 1, part: 'afternoon' })
  assert.deepEqual(partOfDay(4, 60), { day: 1, part: 'night' })
  assert.deepEqual(partOfDay(9, 60), { day: 1, part: 'morning' })
  assert.deepEqual(partOfDay(20, 60), { day: 1, part: 'evening' })
  assert.deepEqual(partOfDay(30, 60), { day: 2, part: 'morning' })
  assert.deepEqual(partOfDay(40, 30), { day: 1, part: 'evening' })
  assert.deepEqual(partOfDay(14), { day: 1, part: 'afternoon' })
  assert.equal(partOfDay(null, 60), null)
  assert.equal(partOfDay('soon', 60), null)
})

test('a turn is the start of the last stretch on the side they ended', () => {
  const h = (period, to, stance) => ({ period, from_round: to - 4, to_round: to, stance })
  assert.deepEqual(turnOf([h(1, 4, 'neutral'), h(2, 9, 'neutral'), h(3, 14, 'supportive')], 'for'), h(3, 14, 'supportive'))
  assert.deepEqual(turnOf([h(1, 4, 'supportive'), h(2, 9, 'opposing'), h(3, 14, 'supportive'), h(4, 17, 'supportive')], 'for'), h(3, 14, 'supportive'))
  assert.deepEqual(turnOf([h(3, 14, 'neutral')], 'undecided'), h(3, 14, 'neutral'))
  assert.equal(turnOf([h(1, 4, 'opposing')], 'for'), null)
  assert.equal(turnOf(undefined, 'for'), null)
  assert.equal(turnOf(['supportive'], 'for'), null)
})

// The Psammos reading, as the Scribe returned it.
const psammosAgents = [
  { agent_id: 0, entity_name: 'Sand', entity_type: 'Aisystem', stance: 'observer', sentiment_bias: 0 },
  { agent_id: 2, entity_name: 'Marina Kavvadia', entity_type: 'CulturalPractitioner', stance: 'opposing', sentiment_bias: -0.6 },
  { agent_id: 7, entity_name: 'The Psammos Association of Athens', entity_type: 'CivicCampaign', stance: 'neutral', sentiment_bias: 0 },
  { agent_id: 8, entity_name: 'Council', entity_type: 'Organization', stance: 'observer', sentiment_bias: 0 },
  { agent_id: 9, entity_name: 'Stelios Moraitis', entity_type: 'Fisher', stance: 'opposing', sentiment_bias: -0.4 },
  { agent_id: 11, entity_name: 'Mirela Dervishi', entity_type: 'Person', stance: 'supportive', sentiment_bias: 0.5 },
  { agent_id: 16, entity_name: 'Katerina Roussou', entity_type: 'Person', stance: 'supportive', sentiment_bias: 0.3 }
]
const period = (p, from, to, stance) => ({ period: p, from_round: from, to_round: to, stance })
const psammosReading = {
  status: 'completed',
  minutes_per_round: 60,
  citizens: [
    { agent_id: 0, name: 'Sand', stance: 'observer', final_stance: 'supportive', moved: true, stance_history: [period(1, 0, 4, 'neutral'), period(2, 5, 9, 'neutral'), period(3, 10, 14, 'supportive')] },
    { agent_id: 2, name: 'Marina Kavvadia', stance: 'opposing', final_stance: 'supportive', moved: true, stance_history: [period(1, 0, 4, 'opposing'), period(2, 5, 9, 'opposing'), period(3, 10, 14, 'supportive')] },
    { agent_id: 7, name: 'The Psammos Association of Athens', stance: 'neutral', final_stance: null, moved: false, stance_history: [] },
    { agent_id: 8, name: 'Council', stance: 'observer', final_stance: 'neutral', moved: false, stance_history: [period(3, 10, 14, 'neutral')] },
    { agent_id: 9, name: 'Stelios Moraitis', stance: 'opposing', final_stance: 'opposing', moved: false, stance_history: [period(1, 0, 4, 'neutral'), period(3, 10, 14, 'opposing')] },
    { agent_id: 11, name: 'Mirela Dervishi', stance: 'supportive', final_stance: 'supportive', moved: false, stance_history: [period(1, 0, 4, 'supportive')] },
    { agent_id: 16, name: 'Katerina Roussou', stance: 'supportive', final_stance: 'neutral', moved: true, stance_history: [period(3, 10, 14, 'neutral')] }
  ]
}

test('who moved, from the Scribe\'s reading, on four sides', () => {
  const r = stanceReading(psammosAgents, psammosReading)
  assert.deepEqual(r.moved.map((m) => [m.name, m.from, m.to, m.round, m.when?.part]), [
    ['Katerina Roussou', 'for', 'undecided', 14, 'afternoon'],
    ['Marina Kavvadia', 'against', 'for', 14, 'afternoon'],
    ['Sand', 'watching', 'for', 14, 'afternoon']
  ])
  // An onlooker read as neutral has not moved; a citizen never read ends where they began.
  assert.deepEqual(r.byId.get('8'), { began: 'watching', ended: 'watching', moved: false })
  assert.deepEqual(r.byId.get('7'), { began: 'undecided', ended: 'undecided', moved: false })
  assert.deepEqual(Object.keys(r.ended), ['for', 'against', 'undecided', 'watching'])
  assert.deepEqual(r.began.for.map((c) => c.name), ['Mirela Dervishi', 'Katerina Roussou'])
  assert.deepEqual(r.began.watching.map((c) => c.name), ['Council', 'Sand'])
  assert.deepEqual(r.ended.for.map((c) => c.name), ['Mirela Dervishi', 'Sand', 'Marina Kavvadia'])
  assert.deepEqual(r.ended.against.map((c) => c.name), ['Stelios Moraitis'])
  assert.deepEqual(r.ended.undecided.map((c) => c.name), ['Katerina Roussou', 'The Psammos Association of Athens'])
  assert.deepEqual(r.ended.watching.map((c) => c.name), ['Council'])
  const count = (rows) => Object.values(rows).reduce((n, list) => n + list.length, 0)
  assert.equal(count(r.began), psammosAgents.length)
  assert.equal(count(r.ended), psammosAgents.length)
})

test('a reading without its own moved flag is judged by side, onlookers kept', () => {
  const reading = {
    minutes_per_round: 30,
    citizens: [
      { agent_id: 1, final_stance: 'supportive', stance_history: [{ period: 2, from_round: 20, to_round: 40, stance: 'supportive' }] },
      { agent_id: 2, final_stance: 'neutral', stance_history: [{ period: 1, to_round: 10, stance: 'neutral' }] }
    ]
  }
  const r = stanceReading([
    { agent_id: 1, entity_name: 'despina_nomikou_466', stance: 'neutral' },
    { agent_id: 2, entity_name: 'Council', stance: 'observer' }
  ], reading)
  assert.deepEqual(r.moved.map((m) => [m.name, m.from, m.to, m.when]), [['Despina Nomikou', 'undecided', 'for', { day: 1, part: 'evening' }]])
  assert.equal(r.byId.get('2').moved, false)
})

test('no reading yet: everyone ends where they began, nobody moved', () => {
  const r = stanceReading(psammosAgents, null)
  assert.deepEqual(r.moved, [])
  assert.deepEqual(r.ended, r.began)
  // The reading alone is enough when the gathering is not known.
  const alone = stanceReading([], psammosReading)
  assert.equal(alone.moved.length, 3)
})
