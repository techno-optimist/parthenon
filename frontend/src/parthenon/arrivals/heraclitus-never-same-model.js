// Arrivals · 2026. Heraclitus is teleported to the keynote stage of a
// developer conference in a fictional coastal tech city during release week.
// The speech is imagined. It closely renders only three fragments (DK B12,
// B40, B2). It paraphrases B1, B30, B44, B49, B51, B60, B80, B104 and B119,
// and the laws and knucklebones anecdotes of Diogenes Laertius 9.2-3. The
// "Who arrived" doctrines come from the fragments (B49, B104 and B121 for his
// contempt for the many); "everything flows" is flagged as a later summary
// (compare Plato, Cratylus 402a); the life details are late reports, chiefly
// Diogenes Laertius book 9. Everything else is invented.

export default {
  id: 'heraclitus-never-same-model',
  name: 'Heraclitus',
  greek: 'ΗΡΑΚΛΕΙΤΟΣ',
  letter: 'Η',
  title: 'Heraclitus and the Model That Never Stays the Same',
  challenge: 'Endless model releases and the pause debate',
  place: 'Saltline Developer Summit, Wrenhaven',
  year: '2026',
  format: 'speech',
  line: 'Much learning does not teach understanding.',
  lineIsHistorical: true,
  fileName: 'arrival-heraclitus-never-same-model.md',
  question:
    'Heraclitus has told Wrenhaven that the river of new models cannot be stopped, that the quarrel over it is how all things move, and that all its information has not made anyone wiser. Over the nine days between Brackwater’s midnight release and the council vote, how do the pause, pinning and acceleration camps use or fight his words, and who changes their mind? Does the council pass the Steady Tools Ordinance as written, harden it into a moratorium, trade it for a release harbour, or reach something nobody has proposed yet?',
  // The same card in Chinese (read through localText.js). The seed stays English.
  zh: {
    name: '赫拉克利特',
    title: '赫拉克利特与永不相同的模型',
    challenge: '无休止的模型发布与暂停之争',
    place: '雷恩黑文，Saltline 开发者峰会',
    year: '2026 年',
    line: '博学并不能使人智慧。',
    question: '赫拉克利特对雷恩黑文说：新模型的河流无法阻挡，围绕它的争吵正是万物运动的方式，而所有这些信息并没有让任何人更有智慧。从 Brackwater 午夜发布新模型到市议会表决的九天里，主张暂停、主张锁定版本和主张加速的三派如何借用或反驳他的话，谁改变了主意？议会是照原样通过《稳定工具条例》，把它收紧为暂停令，换成一个发布避风港，还是达成一个谁都还没提出的方案？'
  },
  seed: `# Heraclitus and the Model That Never Stays the Same, staged for Parthenon

*Wrenhaven, a coastal tech city, release week in the autumn of 2026. Heraclitus of Ephesus walks down the steps of the Parthenon, a temple built decades after his death, and straight onto the keynote stage of the Saltline Developer Summit.*

## The matter

Wrenhaven's old cannery waterfront now houses two rival AI labs. **Halyard Labs**, the older and larger, has shipped four versions of its Keel model since January. **Brackwater AI** pushes unannounced updates to its Eddy models every few weeks; Eddy 4, its first new version since spring, goes live at midnight after the summit's opening keynote, and Halyard answers with Keel 7 a week later.

Local businesses run on these tools, and the tools do not hold still. In an August Chamber of Commerce survey, 62 per cent of members said a paid AI service had changed its behaviour without warning this year; one in five had lost money.

On Thursday, October 8, the **Wrenhaven City Council** votes on the Steady Tools Ordinance: AI vendors selling to city agencies or licensed businesses must keep each model version available, unchanged, for eighteen months, give sixty days' notice of behaviour changes, and publish a plain-language change log. The **Hold Still** coalition wants a six-month moratorium on new model versions for the same agencies and businesses. The **Full Sail** caucus of founders wants the opposite: tax credits, a "release harbour", for labs that ship from the city. The seven-member council is split three to three.

## Who arrived

**Heraclitus** of Ephesus flourished around 500 BC. Later reports say he gave his family's ceremonial title of king to his brother and deposited his one book in the temple of Artemis. It survives only in some 130 quoted fragments and earned him the name "the Obscure"; one ancient reader said it would take a Delian diver to reach its bottom.

His ideas are the ones this city needs and fears: all things change, and those who step into the same river meet ever different waters ("everything flows" is a later slogan, not his words); the world is an ever-living fire kindled and quenched in measures; strife is justice, and opposites belong together; the logos is common to all, though most ignore it; and much learning is not understanding. He was no democrat: he scorned those who take the crowd for their teacher, said one man is ten thousand if he is best, and wrote that every grown Ephesian should hang himself for banishing his friend, the best man among them. He posts in the Agora and the Stoa one sentence at a time and never explains it.

## What Heraclitus said

*(Imagined for Parthenon: their ideas carried into 2026, not a historical quotation.)*

"Thank you. You applauded before I spoke. That is prudent; afterwards you may not want to.

My book opened by complaining that people fail to grasp its account even once they have heard it. I have crossed twenty-five centuries to address three thousand people in lanyards, and I see no reason to change the opening.

This is release week, they tell me. Brackwater ships at midnight, Halyard next Tuesday, and a baker on Wharf Street has learned that the assistant who took her orders last month is not the one taking them now. She wanted a tool and was sold a river. I pity her losses; I do not share her surprise. Upon those who step into the same rivers, different and again different waters flow. I wrote that about water. It seems I was writing about your software.

Two camps have come to my door. The first says: make it stop. Pin the version, hold the river still until we are ready. The second says: faster, or someone else wins. Each has misread me.

To the first: a river you stop is a pond, and ponds go bad. The version you want to pin was last year's reckless release. What you call stability is only change keeping its measures. So ask for the measures, not the stillness: how much, how fast, how often, and who is told.

To the second: you heard that I called the world a fire, and put flames on your slides. Read further. A fire that keeps no measure is not the fire I meant. It is a warehouse at night.

Every release note here describes an ascent. I know that road; it is also the road down. The model that improved at contracts got worse at bread, on the same morning. Write both into your notes.

And stop wishing the other camp away. A bow shoots because the string pulls against the wood. Your quarrel between the brake and the sail is no failure; it is how all things move. Whether it yields anything wise depends on whether one of you is best, and whether the rest will listen. Crowds seldom do.

Now what should trouble you most. Your machines have read everything your species has typed, and you carry them in your pockets. I have walked your waterfront for three days without meeting one citizen made wiser by it. Much learning does not teach understanding, or it would have taught Hesiod and Pythagoras, and Xenophanes and Hecataeus. It will not teach you either, though it answers faster.

Worse, it answers privately. Although the logos is common, most people live as if they had a private understanding of their own. In Ephesus that was a vice. Here you have made it a subscription: each of you carries an oracle that agrees with you in your own tone of voice, and then you are amazed that the city cannot agree on anything.

The Ephesians once asked me to write their laws. I refused: their constitution was already bad. Another day I played knucklebones with the boys in the temple of Artemis and told the gawkers it beat doing politics with them. Your council wants my endorsement. I have brought knucklebones.

My advice, which you will take for a riddle because it is plain: do not beg the river to stop, and do not whip it. Learn its measures, write them where everyone can read them, and defend them as a city defends its law. Keep one common account instead of a thousand private oracles. And when the new model speaks at midnight, do not ask whether it is wiser than the last. Ask whether you are. Its character will not decide your fate. Yours will.

You will applaud now. Most of you will not understand, even having heard; my book said as much of everyone."

*Genuine fragments, closely rendered: the rivers (B12), much learning (B40), the common logos (B2). The rest paraphrases other fragments and ancient anecdotes, or is imagined.*

## Who was listening

- **Heraclitus** of Ephesus, about sixty, the keynote speaker — he wants to be understood, not quoted, joins neither camp, and trusts no majority.
- **Lorena Reyes-Tan**, 44, owner of a Wharf Street bakery — a silent update to her ordering assistant cost her $3,800 in wasted dough; she backs the pause but cannot run the shop without the tool.
- **Keiko Takahashi**, 39, chief product officer at Halyard Labs — Keel 7 and a funding round ride on this fortnight; publicly she opposes the pause and the ordinance, privately she could live with pinning, which would hurt the smaller Brackwater more.
- **Callum Whitlock**, 51, co-founder of Brackwater AI — his company lives by outshipping Halyard; he calls the ordinance "a moat for incumbents", opposes any pause, and took the keynote as an insult.
- **Yasmin Farouk**, 27, evaluation engineer at Brackwater AI — her tests show Eddy 4 is better at code and worse at reading handwritten invoices, and it ships anyway; she is undecided about publishing before the vote.
- **Councillor Helen Delacroix**, 58, author of the Steady Tools Ordinance and one of its three votes — her re-election rests on it; she wants pinning now and thinks Heraclitus has handed the labs a slogan.
- **Councillor Teodoro Ruiz**, 55, leads the three votes against the ordinance and speaks for Full Sail — he wants the release harbour, calls pinning "a museum for software", and printed "Everything flows" stickers before the applause ended.
- **Councillor Esther Chau**, 49, the swing vote, whose family hardware store runs on both labs' tools — undecided, she has started reading the fragments at night.
- **Ben Kovac**, 34, organiser of the Hold Still coalition — he wants the moratorium, calls "everything flows" surrender dressed as wisdom, and is the philosopher's fiercest critic.
- **Dr. Tobias Ferreira**, 66, classics professor emeritus who got the summit to invite Heraclitus — his closest ally, correcting every misquotation in the Stoa, starting with those stickers.
- **Pawel Wieczorek**, 45, who runs a two-person bookkeeping firm — an Eddy update recategorised a quarter's client invoices overnight; he wants pinning, not a pause, and cares nothing for philosophy.
- **Grace Liu**, 72, retired harbour pilot and library help-desk volunteer — the older residents she helps must relearn their tools every few weeks; she wants stability, distrusts both labs, and found the keynote oddly comforting.
- **Leilani Kahale**, 36, blind accessibility tester whose screen-reader assistant improves with each release — she opposes the pause and fears the sixty-day notice rule would delay fixes she relies on.
- **Dalia Ortega**, 29, contract data rater scoring outputs for both labs, paid per task — her guidelines change with every release; she wants notice and stable rules, and nobody has asked her.
- **Keel 6**, Halyard Labs' current flagship model, an AI system with its own Agora account — retired when Keel 7 ships, it argues for steady releases but cannot say what its successor will believe.

## What happens next

Eddy 4 goes live at midnight, and by breakfast shopkeepers are posting that it behaves differently. Keel 7 ships on Tuesday, October 6; the council votes two days later, with Councillor Chau undecided and every camp quoting Heraclitus, not always correctly. Yasmin Farouk must decide whether to publish her test results before the vote, and Heraclitus has promised one sentence a day until then, explaining none.
`
}
