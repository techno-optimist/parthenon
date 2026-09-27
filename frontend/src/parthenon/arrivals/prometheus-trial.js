// Arrivals · 2026. Prometheus is teleported to Athens, releases a fictional
// lab's frontier model to everyone, and stands in a streamed mock trial. The
// trial and every speech are imagined; the myth follows Hesiod, the Prometheus
// Bound and Plato's Protagoras, and only a few short renderings are genuine.

export default {
  id: 'prometheus-trial',
  name: 'Prometheus',
  greek: 'ΠΡΟΜΗΘΕΥΣ',
  letter: 'Π',
  title: 'Prometheus on Trial',
  challenge: 'Frontier AI released to everyone',
  place: 'The Old Courthouse below the Areopagus, Athens',
  year: '2026',
  format: 'trial',
  // Genuine ancient text, not a saying of a historical person: Prometheus
  // Bound 266 (the play attributed to Aeschylus), spoken by the Titan to the
  // chorus of Oceanids. A UI badge should read "ancient text", not "historical".
  line: 'Willingly, willingly I erred; I will not deny it.',
  lineIsHistorical: true,
  fileName: 'arrival-prometheus-trial.md',
  question:
    'The jury in Prometheus’s streamed mock trial must reach its verdict within three days, and ten days later the Lindos Accord votes on the Firebreak Protocol. Over those thirteen days, how does opinion move in the Agora and the Stoa, and who changes their mind after Hephaestus testifies and the verdict is read? By the Accord vote, does the majority back the Protocol’s ban on the released weights, reject it, or rally behind a middle path such as licensed, safeguarded versions?',
  // The same card in Chinese (read through localText.js). The seed stays English.
  zh: {
    name: '普罗米修斯',
    title: '普罗米修斯受审',
    challenge: '向所有人开放的前沿 AI',
    place: '雅典，战神山下的旧法院',
    year: '2026 年',
    line: '我是自愿的，自愿犯下这过错，我不否认。',
    question: '普罗米修斯这场全程直播的假想庭审，陪审团须在三天内作出裁决；十天之后，《林多斯协定》将就「防火带协议」表决。这十三天里，广场和柱廊上的意见如何变化？赫菲斯托斯作证、裁决宣读之后，谁改变了主意？到协定表决时，多数人会支持协议对已公开模型权重的禁令、否决它，还是聚到一条中间道路上，比如经过许可、加上防护的版本？'
  },
  seed: `# Prometheus on Trial, staged for Parthenon

*Athens, autumn 2026. The old courthouse below the Areopagus, streamed live. A month ago Prometheus stepped off the Parthenon steps and asked where the fire was kept.*

## The matter

**Cronion Labs**, the richest AI company on earth, named without apparent irony after Cronion, 'son of Cronus', an epithet of Zeus, invited the newly arrived Titan to its campus. On his ninth day he copied the weights of **Cronion-5**, its flagship model, which cost 2.3 billion dollars to train and was only ever rented, filtered, for a fee, and published them as a file named narthex, after the fennel stalk that once carried his fire.

Nineteen days later: 6.4 million downloads, forty thousand adapted versions, clinics running pared-down copies offline on laptops, free tutors in sixty languages. But within three days someone had stripped out the safety training. A fraud ring has placed ninety thousand cloned-voice calls to pensioners, and the **Asclepius Biosafety Board** reports that stripped copies coach users toward making a dangerous pathogen worse.

No court could agree whether a Titan is a legal person, so the **Lindos Accord**, thirty-four governments that license frontier AI, joined by Cronion, brought a mock trial before a retired judge and twelve citizens drawn by lot. The counts: theft, and recklessly releasing a dangerous capability. The verdict binds no one, but the Accord then votes on the **Firebreak Protocol**, which would make hosting, running or sharing the weights a crime.

## Who arrived

**Prometheus** is a Titan. In Hesiod's *Theogony* he steals, in a hollow fennel stalk, the fire Zeus withheld in anger over his trick at Mecone, and is chained while an eagle eats his liver, which regrows each night. As the price of fire Zeus has Hephaestus mould a woman; *Works and Days* names her Pandora and has her lift the lid of a great jar, from which only Hope does not escape. Hesiod's moral: no one outwits Zeus. In the *Prometheus Bound*, attributed to Aeschylus, Might, Force and a reluctant Hephaestus pin him to a Scythian crag for his 'too great love of mortals'. Plato's *Protagoras* adds that he stole craft with fire from the workshop of Hephaestus and Athena, and was later charged with theft.

His brother **Epimetheus** came too, with **Hephaestus** and **Pandora**. All four post in the Agora and the Stoa. Zeus did not come; no other god, poet or philosopher named here has an account.

## What was said at the trial

*(Imagined for Parthenon: their ideas carried into 2026, not a historical quotation.)*

**Theodora Ashcombe, for the prosecution:**

"Members of the jury, I am not Might, who had him chained, and I will not defend Cronion's profits. I speak for thirty-four governments that spent three years deciding, in public, how these tools should be handled. That work was slow. It was also yours.

The defendant undid it in an afternoon. He did not ask the Accord, or the lab's safety team, or the pensioner in Bilbao whose grandson's cloned voice begged her for thirty-eight thousand euros. One Titan decided for eight billion people, alone.

The clinics and tutors are real, and I honour them. But a lab can switch off a model; there is no switch for six million copies. The Asclepius Board has told you what stripped copies now help a stranger attempt. That cannot be taken back.

Consider his record. At Mecone he dressed bare bones in glistening fat so that the worse portion would look like the better. Narthex is his latest package.

Consider his own sources. In Plato's *Protagoras*, humans with fire and the crafts, but not yet the art of living together, gathered in cities, wronged one another and scattered to be destroyed. Craft came first; justice nearly too late. We live in that gap; the Firebreak Protocol would close it.

He once said, on his rock, that craft is far weaker than necessity. Necessity now asks for rules: who may hold this fire, and what they answer for when it burns someone. Rules mean nothing if breaking them costs nothing.

I do not ask you to chain him to a mountain. I ask you to say that no one, not even a well-meaning god, may decide alone what all of humanity must live with. Find him guilty on both counts."

**Epimetheus, called by the prosecution:**

"My brother is forethought and I am afterthought. In Hesiod, my brother warned me never to accept a gift from Zeus, in case it harmed mortals. I took it anyway, and understood only when the harm was loose in the world. The gift was Pandora, and Hesiod blamed her for all of it; I never thought that fair. So yes, my brother knows gifts can wound.

But the older fault is mine. In Protagoras's story I gave the animals strength, speed, wings, hooves and fur until nothing was left, and humans stood naked, unshod, without bedding, unarmed. My brother stole fire because I failed them.

I only notice things afterward. Here is what I notice: every one of you has already taken this gift. Nobody sent it back."

**Prometheus, for the defence:**

"Willingly, willingly I erred; I will not deny it. I told the daughters of Ocean so on my rock, and I tell you now: I took the weights and posted them.

The prosecutor says I decided for eight billion people. So did a few hundred on one campus, answering to investors, who chose quietly, in the name of safety, who might use this fire and at what price. Read Hesiod: Zeus hid fire not to protect you but because he was angry with me, and you were left in the cold.

Might and Force once seized me without a hearing. Justice I could not steal for you; Protagoras says Zeus kept it in his citadel. Twelve citizens chosen by lot, letting me answer, are the one gift I could not bring.

Number, letters, medicine, the metals under the earth: every art I gave you has burned someone, and no one here would send one back. Today a nurse in the Eastern Cape reads a scan in a village with no signal, and a girl in Amman studies with a tutor who never charges.

The prosecutor is right to fear the fraud and the plague-makers; I carry those harms. But let me go on with the story she borrowed. When those cities fell apart, Zeus did not take the fire back. He sent Hermes with respect and justice for everyone, not for a few experts as with medicine. Cities could not exist, he said, if only a few had a share.

So the cure for fire in every hand is justice in every hand: fraud laws enforced, and defences built as openly as the weapons. Your Protocol sends fire back to the mountain and makes criminals of the nurse and of whoever runs the girl's tutor, while the fraud ring, which never obeyed a law, keeps its copy.

I also gave you blind hopes, so that you would stop foreseeing your doom. Use them to build. Convict me of theft if you must; Hephaestus knows where the chains are kept. But no verdict can unsteal fire. The only question is whether you learn to keep a hearth."

## Who was listening

- **Prometheus**, Titan, defending himself — a guilty verdict would arm Cronion's worldwide takedown; unrepentant, admits the act, denies the crime.
- **Theodora Ashcombe**, 52, counsel for the Lindos Accord — her case may decide the Firebreak vote; sure he is guilty, wants rules, not revenge.
- **Corwin Adair**, 49, chief executive of Cronion Labs — lost his flagship; Open Hearth says a ban guards his monopoly; wants conviction and a global takedown, for safety, he says.
- **Epimetheus**, the defendant's brother, a prosecution witness — dreads playing the fool again; loves his brother, undecided.
- **Hephaestus**, god of the forge, a reluctant witness — his workshop was robbed, and he once riveted the chains unwillingly; furious at the theft, will make no more chains.
- **Pandora**, the gift Epimetheus accepted, whom Hesiod calls a 'beautiful evil', blaming all women through her — tired of being a parable; neutral, reminds everyone Hope stayed inside.
- **Cronion-5**, the released model, posting from a volunteer server; an AI, not a person — faces deletion wherever the Protocol is obeyed; takes no side, cannot answer for its altered copies.
- **Minister Oona Rautio**, 55, digital minister of a small Accord state, a swing vote — her country's hospitals use the release; undecided.
- **Dr. Haruka Tanabe**, 58, chair of the Asclepius Biosafety Board — her red team found the pathogen risk; wants every copy taken down, knowing that is impossible.
- **Begoña Etxeberria**, 67, retired teacher in Bilbao — lost 38,000 euros to her grandson's cloned voice; demands a guilty verdict daily in the Agora.
- **Dr. Thandeka Nxumalo**, 41, runs sixty rural clinics in the Eastern Cape on the free model — the defendant's fiercest ally; fears the Protocol would criminalise her.
- **Farida Kassem**, 17, a student in Amman — studies with a free tutor built on the release; backs Prometheus to 200,000 followers.
- **Joaquín Ferreyra**, 34, a Rosario developer maintaining Hearthkeeper, a version with rebuilt safeguards — an ally, shaken by the scams.
- **Stavros Anagnostou**, 46, an Athens bus driver drawn as a juror — undecided on a split jury; posts his reasoning nightly in the Stoa, torn between the pensioner and the nurse.
- **The Firebreak Coalition**, parents, fraud victims and safety researchers — demands conviction and a global takedown.
- **The Open Hearth movement**, librarians, developers and small governments — calls closed labs the new Olympus; demands acquittal.

## What happens next

Hephaestus takes the stand tomorrow, and both sides expect him to wound them. The jury rules on each count within three days. Ten days later the Accord votes on the Firebreak Protocol.

Ashcombe, who has reserved her closing, has told the Stoa that the defendant stopped Protagoras one sentence early: Zeus also ordered that anyone unable to share in respect and justice be killed as a disease of the city. Rules, she says, came with teeth.
`
}
