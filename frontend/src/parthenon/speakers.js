// The speakers who can take the steps. Each seed is an original retelling
// (not a translation) plus the cast of listeners; MiroFish turns that cast
// into the citizens who argue about what was said.

export const speakers = [
  {
    id: 'socrates',
    name: 'Socrates',
    greek: 'ΣΩΚΡΑΤΗΣ',
    letter: 'Σ',
    epithet: 'the Gadfly',
    work: 'The Apology',
    place: 'The People’s Court',
    year: '399 BC',
    line: 'The unexamined life is not worth living.',
    fileName: 'socrates-the-apology.md',
    question:
      'The jury has sentenced Socrates to death, and the sacred ship to Delos gives Athens thirty days before the hemlock. How does the city talk about it during that month? Who defends him, who celebrates, and does anyone change their mind? Should Crito’s escape plan succeed, and what does Athens decide about free questioning?',
    // The same card in Chinese (read through localText.js). The seed stays English.
    zh: {
      name: '苏格拉底',
      epithet: '雅典的牛虻',
      work: '申辩篇',
      place: '民众法庭',
      year: '公元前 399 年',
      line: '未经审视的人生不值得过。',
      question: '陪审团已判苏格拉底死刑，而开往提洛岛的圣船让雅典在饮下毒芹汁之前还有三十天。这一个月里，城邦如何谈论此事？谁为他辩护，谁拍手称快，又有谁改变了主意？克力同的越狱计划应当成功吗？对于自由发问，雅典最终作何决定？'
    },
    seed: `# The Apology of Socrates, retold for Parthenon

*Athens, spring of 399 BC. The People's Court beside the Agora. A jury of 501 citizens chosen by lot.*

## The charges

Three citizens have indicted Socrates, son of Sophroniscus, seventy years old: **Meletus**, a young poet who wrote the charge; **Anytus**, a wealthy tanner and leader of the restored democracy; and **Lycon**, an orator. The charge: Socrates does not recognise the gods the city recognises, introduces new divine things, and corrupts the young. Everyone in the court remembers, though no one says it aloud, that two of Socrates' former companions, **Critias** and **Alcibiades**, brought disaster on Athens, that the city lost the war to Sparta five years ago, and that it then suffered the rule of the Thirty Tyrants.

## What Socrates said

*(Retold in plain words, not a translation.)*

"Men of Athens, my accusers spoke so persuasively that they almost made me forget who I am, and yet they said hardly a word of truth. From me you will hear the whole truth, in the ordinary words I use every day in the market.

My old accusers are more dangerous than Meletus. For years you have heard, even in the comedies of Aristophanes, about a Socrates who walks on air, studies what is under the earth, and makes the weaker argument the stronger. I have nothing to do with such things.

Here is where my reputation comes from. My friend Chaerephon once went to Delphi and asked the oracle whether anyone was wiser than I. The priestess answered that no one was. I was baffled, because I know I am not wise. So I went to test the god. I questioned the politicians, who were thought wise, and found that they believed they knew what they did not. Then the poets, who write beautiful things without understanding them. Then the craftsmen, who truly know their crafts but, because of that, believed they knew the greatest matters too. I am wiser only in this: I do not think I know what I do not know.

Young men with leisure follow me and imitate me, questioning their elders. The elders, embarrassed, blame me and say that I corrupt the youth.

If you offered to release me on condition that I stop doing philosophy, I would say: I honour you, men of Athens, but I will obey the god rather than you. While I have breath I will not stop asking each of you whether you are not ashamed to care for money, reputation and honour while caring nothing for wisdom, truth and the state of your soul.

I am a kind of gadfly, attached to the city by the god. The city is like a great and noble horse, sluggish because of its size, that needs to be stirred up. You may be angry, like people woken from a doze, and swat me, and then sleep on for the rest of your lives, unless the god sends you someone else.

I will not parade my weeping children in front of you to beg for pity. It would shame the city."

## The verdict and the penalty

The jury finds him guilty, 280 votes to 221. Asked to propose his own penalty, Socrates suggests free meals in the Prytaneum, the honour given to Olympic victors. "If I tell you that talking every day about virtue is the greatest good for a human being, and that the unexamined life is not worth living, you will believe me even less." At his friends' urging he then offers a fine of thirty silver minae, guaranteed by Plato, Crito, Critobulus and Apollodorus. The jury sentences him to death, by a larger margin than convicted him.

His last words to the court: "No evil can come to a good man, in life or in death. Now it is time to go, I to die and you to live. Which of us goes to the better thing is unclear to everyone but the god."

## Who was on the steps

- **Crito**, Socrates' oldest friend, a wealthy farmer, already planning to bribe the guards so Socrates can escape.
- **Plato**, 28, an aristocrat who gave up politics for philosophy and will never forgive the democracy.
- **Xanthippe**, Socrates' wife, with their three sons, the youngest still a baby.
- **Apollodorus**, a devoted follower who cannot stop weeping.
- **Meletus**, **Anytus** and **Lycon**, the accusers, who expected him to choose exile rather than death.
- **Aristophanes**, the comic playwright whose play *The Clouds* mocked Socrates twenty-four years earlier.
- Jurors: farmers from Acharnae, potters from the Kerameikos, rowers who served in the fleet, veterans who remember the Thirty Tyrants.
- **Sophists** who teach rhetoric for money, pleased and nervous at once.
- Young men of good families who have spent their afternoons questioning their fathers.
- Priests of Athena and the city's seers, who see impiety punished.
- Merchants, metics (resident foreigners) and enslaved workers in the Agora, who hear the news second-hand.

## What happens next

A sacred ship has just left for the festival at Delos. No execution may take place until it returns, about thirty days from now. For that month Socrates will sit in prison talking with anyone who visits, and the city has a month to talk about what it has done.
`
  },
  {
    id: 'plato',
    name: 'Plato',
    greek: 'ΠΛΑΤΩΝ',
    letter: 'Π',
    epithet: 'of the Academy',
    work: 'The Cave',
    place: 'The Academy',
    year: 'c. 375 BC',
    line: 'Education is the art of turning the soul toward the light.',
    fileName: 'plato-the-cave.md',
    question:
      'Plato has told the allegory of the cave at the Academy, and the story is spreading through Athens. How do Athenians argue about it? Who sees themselves as the prisoners, who as the freed man, and who as the ones carrying the puppets? Does the city warm to the idea that philosophers should rule, or turn against the Academy?',
    // The same card in Chinese (read through localText.js). The seed stays English.
    zh: {
      name: '柏拉图',
      epithet: '学园之主',
      work: '洞穴之喻',
      place: '阿卡德米学园',
      year: '约公元前 375 年',
      line: '教育，是引导灵魂转向光明的技艺。',
      question: '柏拉图在学园讲了洞穴之喻，这个故事正在雅典传开。雅典人如何争论它？谁把自己看作囚徒，谁看作挣脱锁链的人，谁又看作举着偶像走过火前的人？城邦会渐渐接受哲人应当治国的想法，还是转而反对学园？'
    },
    seed: `# The Cave, retold for Parthenon

*Athens, around 375 BC. The grove of the hero Akademos outside the city walls, where Plato teaches. The story comes from the seventh book of the Republic, told in Socrates' voice to Plato's brother Glaucon.*

## What Plato said

*(Retold in plain words, not a translation.)*

"Picture people who have lived all their lives in an underground cave, chained by the legs and neck so that they can only look at the wall in front of them. Behind them and higher up, a fire is burning. Between the fire and the prisoners runs a road with a low wall along it, like the screen puppeteers hide behind. Along that road people carry all kinds of objects, figures of men and animals made of stone and wood; some of the carriers talk, some are silent. The prisoners see only the shadows these things throw on the wall. They hear echoes and believe the shadows are speaking.

'A strange picture, and strange prisoners,' said Glaucon.

'Like us,' I said.

The prisoners hold contests among themselves, with honours for whoever is quickest to name the passing shadows, remembers which usually come first, and predicts which will come next.

Now suppose one of them is freed and made to stand up, turn round and look at the fire. It hurts. He is dazzled. If he were told that what he saw before was nonsense and that he is now nearer to reality, he would still think the shadows truer than the things he is being shown.

Drag him up the steep, rough path into the sunlight and he would be angry and blinded. At first he could only look at shadows, then at reflections in water, then at the things themselves, then at the night sky, and last of all at the sun. Then he would understand that the sun governs everything in the visible world and is, in a way, the cause of everything he and his fellow prisoners used to see. He would pity the prisoners and would not envy their honours.

Now suppose he goes back down and takes his old seat. His eyes, full of darkness, would fail him in the shadow contests. The others would laugh and say that he went up and came back with his eyes ruined, and that it is not worth even trying to go up. And if anyone tried to free them and lead them up, they would kill him if they could lay hands on him.

Education is not what some people claim, putting knowledge into a soul that lacks it, like putting sight into blind eyes. Every soul already has the power to learn. Education is the art of turning the whole soul around, away from what merely comes and goes and toward what truly is, until it can bear to look at the brightest thing of all: the good.

And those who have seen it must not be allowed to stay up there. They must go back down to the prisoners and share their labours and their honours. The city whose rulers least want to rule is the best governed; the city ruled by people who crave office is governed worst."

## Who was listening

- **Glaucon**, Plato's older brother, ambitious and a lover of honour, who pushes back on every point.
- **Adeimantus**, Plato's other brother, who worries that philosophers will look useless or dangerous to ordinary people.
- Students of the **Academy**, among them a sharp seventeen-year-old from Stagira named **Aristotle**, and **Speusippus**, Plato's nephew.
- **Isocrates**, who runs a rival school of rhetoric in the city and teaches that practical speech, not metaphysics, makes good citizens.
- Democratic politicians of the **Assembly**, who hear that philosophers want to rule.
- Craftsmen and **puppeteers** from the theatre district, who make their living from shadows and illusions.
- Poets and **tragedians**, whom Plato has proposed to banish from his ideal city.
- Farmers, sailors and shopkeepers in the Agora, who hear the story second-hand and wonder whether they are the prisoners.
- Mothers of young men who have started spending every day at the Academy.

## What happens next

The story leaves the grove and moves through the city: retold in the barbershops, parodied in the comedies, argued over in the Assembly.
`
  },
  {
    id: 'aristotle',
    name: 'Aristotle',
    greek: 'ΑΡΙΣΤΟΤΕΛΗΣ',
    letter: 'Α',
    epithet: 'the Peripatetic',
    work: 'The Golden Mean',
    place: 'The Lyceum',
    year: 'c. 330 BC',
    line: 'Virtue lies in the mean between two vices.',
    fileName: 'aristotle-the-golden-mean.md',
    question:
      'Aristotle’s lecture on happiness and the golden mean is spreading beyond the Lyceum. Do Athenians embrace moderation and habit as the road to a good life, or resent a Macedon-connected foreigner lecturing them on virtue? Which habits does the city actually decide to change, and who pushes back?',
    // The same card in Chinese (read through localText.js). The seed stays English.
    zh: {
      name: '亚里士多德',
      epithet: '逍遥学派',
      work: '中道',
      place: '吕克昂学园',
      year: '约公元前 330 年',
      line: '德性是两种恶之间的中道。',
      question: '亚里士多德关于幸福与中道的讲演，正从吕克昂传向城中。雅典人会把节制与习惯当作通往美好生活的道路，还是反感一个与马其顿有瓜葛的外邦人来教他们何为德性？城邦真正决定改变哪些习惯，又是谁在反对？'
    },
    seed: `# The Golden Mean, retold for Parthenon

*Athens, around 330 BC. The Lyceum, a gymnasium east of the city walls sacred to Apollo Lykeios. Aristotle lectures while walking the covered colonnade, so his students are called the Peripatetics, "the walkers". Athens has lost its independence to Macedon. Aristotle, born in Stagira and once tutor to Alexander, lives here as a resident foreigner without a citizen's rights.*

## What Aristotle said

*(Retold in plain words, not a translation.)*

"Every craft and every inquiry, every action and every choice, seems to aim at some good. What is the highest good that all our actions aim at? Nearly everyone agrees on its name: happiness, eudaimonia, living well and doing well. But they disagree about what it is. The many think it is pleasure; the ambitious think it is honour; the moneymaker thinks it is wealth, although wealth is plainly only useful for the sake of something else.

Consider what a human being is for. A flute player's good lies in playing well; a sculptor's in sculpting well. What is distinctive of a human being is a life guided by reason. So the human good is the activity of the soul in accordance with virtue, over a complete life. One swallow does not make a spring, nor does one fine day, and one day or a short time does not make a person happy.

Virtue of character is not in us by nature, nor against nature. We are made by nature able to receive it, and we complete it by habit. We become builders by building and lyre players by playing the lyre; in the same way we become just by doing just things, self-controlled by doing self-controlled things, brave by doing brave things. So it matters a great deal how we are trained from childhood. It makes all the difference.

Virtue is a settled disposition to choose the mean, relative to us, as a person of practical wisdom would judge it. It is a mean between two vices, one of excess and one of deficiency. Courage lies between rashness and cowardice. Generosity lies between wastefulness and stinginess. Proper pride lies between vanity and smallness of soul. Wit lies between buffoonery and boorishness. And the mean is not the same for everyone: a meal too small for Milo the wrestler would be too large for a beginner at the gymnasium.

That is why it is hard to be good. Anyone can get angry, which is easy, or give money away. But to do it to the right person, in the right amount, at the right time, for the right reason and in the right way is not easy, and not everyone can do it.

A human being is by nature a political animal. Whoever cannot live in a community, or needs nothing because he is self-sufficient, is either a beast or a god. And no one would choose to live without friends, even if he had every other good."

## Who was listening

- **Theophrastus**, Aristotle's closest student and heir to the school, fascinated by plants and by human character types.
- Young Athenian aristocrats who walk the colonnade with him, some of whom resent learning virtue from a friend of Macedon.
- **Antipater**, the Macedonian regent who governs Greece for Alexander, and his agents in the city.
- The circle of **Demosthenes** and the anti-Macedonian orators, who suspect the Lyceum of serving Macedon.
- **Xenocrates**, head of Plato's Academy across the city, who thinks Aristotle has betrayed Plato.
- Athletes and trainers at the gymnasium, who know all about the right amount of food and exercise.
- Merchants and moneylenders of the Piraeus, who have just been told that wealth is not the good.
- Priests who notice a philosopher explaining happiness without the gods.
- Wives and daughters of the students, who are not admitted but hear the lectures repeated at dinner.

## What happens next

Copies of the lecture notes pass from hand to hand. Alexander is campaigning far to the east; if news of his death arrives, the city may turn on everyone connected with Macedon.
`
  },
  {
    id: 'heraclitus',
    name: 'Heraclitus',
    greek: 'ΗΡΑΚΛΕΙΤΟΣ',
    letter: 'Η',
    epithet: 'the Obscure',
    work: 'The River',
    place: 'Ephesus, carried to Athens',
    year: 'c. 500 BC',
    line: 'Other and still other waters flow on those who step into the same rivers.',
    fileName: 'heraclitus-the-river.md',
    question:
      'Heraclitus’ riddles about flux, fire and strife have reached Athens on Ionian ships. Does the city take comfort or fright from the idea that nothing stays the same? How do traders, priests, generals and politicians use his sayings or fight them, and what does Athens decide about change?',
    // The same card in Chinese (read through localText.js). The seed stays English.
    zh: {
      name: '赫拉克利特',
      epithet: '晦涩者',
      work: '河流',
      place: '以弗所，随船传入雅典',
      year: '约公元前 500 年',
      line: '踏入同一条河流的人，不断遇到新的水流。',
      question: '赫拉克利特关于流变、火与斗争的谜语，随伊奥尼亚的船只传到了雅典。万物皆流的想法，让城邦感到安慰还是恐惧？商人、祭司、将军和政客如何借用或反驳他的话？对于变化，雅典最终作何决定？'
    },
    seed: `# The River, retold for Parthenon

*Around 500 BC, Ephesus on the Ionian coast. Heraclitus, of the old royal family, gave up his hereditary title to his brother and withdrew to the temple of Artemis, where he left a book of riddles. People called him "the Obscure" and "the weeping philosopher". Generations later his sayings arrive in Athens with Ionian traders, and people argue over them on the steps.*

## What Heraclitus said

*(His surviving sayings, retold in plain words.)*

"This account of how things are, the logos, holds forever, yet people fail to understand it, both before they hear it and once they have heard it. Everything happens according to it, yet people act as if they had never met it.

Everything flows; nothing stands still.

You cannot step twice into the same river, for other waters are always flowing on.

This world, the same for all, was made by no god and no man. It always was, is, and will be an ever-living fire, kindling in measures and going out in measures.

War is the father of all and king of all. It shows some to be gods and some to be men; it makes some slaves and some free. Strife is justice, and all things come to be through strife.

The way up and the way down are one and the same.

Cold things grow warm, warm things grow cold, the wet dries and the parched grows moist.

What pulls apart comes together; from things that differ comes the most beautiful harmony, as in the bow and the lyre.

Much learning does not teach understanding, or it would have taught Hesiod and Pythagoras.

A person's character is their fate.

Although the logos is shared by all, most people live as if they had a private understanding of their own.

Nature loves to hide.

The sun is new every day.

Dogs bark at those they do not know.

The Ephesians should all hang themselves and leave the city to the children, for they banished Hermodorus, their best man, saying: let no one among us be best."

## Who was listening

- **Cratylus**, an Athenian follower of Heraclitus who goes further: you cannot step into the same river even once, and he now only points instead of speaking.
- Followers of **Parmenides** from Elea, who insist that change is an illusion and that what is, simply is.
- **Ionian traders** at the Piraeus who carried the book from Ephesus and quote it to sell their stories.
- Priests of the **Eleusinian Mysteries**, offended by his mockery of rites and statues.
- **Generals and veterans** who like "war is the father of all" a little too much.
- **Potters and smiths**, who work with fire every day and find a world made of fire natural.
- Physicians of the Hippocratic school, who think of health as a balance of opposites.
- Oligarchs who share his contempt for "the many", and democrats who hate him for it.
- Young poets who find his riddles beautiful and his meaning secondary.

## What happens next

A copy of his book is read aloud in the Stoa every afternoon. Some say the city should honour him; others say his teaching dissolves the laws, the gods and the family.
`
  },
  {
    id: 'diogenes',
    name: 'Diogenes',
    greek: 'ΔΙΟΓΕΝΗΣ',
    letter: 'Δ',
    epithet: 'the Dog',
    work: 'The Dog in the Agora',
    place: 'The Agora',
    year: 'c. 340 BC',
    line: 'Stand a little out of my sun.',
    fileName: 'diogenes-the-dog-in-the-agora.md',
    question:
      'Diogenes has spent a week heckling Athens from his jar. Does the Agora turn against his shamelessness, or do young Athenians start giving away their possessions and speaking their minds to the powerful? What does the city decide it actually needs?',
    // The same card in Chinese (read through localText.js). The seed stays English.
    zh: {
      name: '第欧根尼',
      epithet: '犬儒',
      work: '广场上的犬',
      place: '广场',
      year: '约公元前 340 年',
      line: '站开一点，别挡住我的阳光。',
      question: '第欧根尼在他的大瓮里对雅典冷嘲热讽了整整一周。广场会群起反对他的无耻，还是年轻的雅典人开始散尽家财，当面对权贵直言？城邦最后认定，自己真正需要的是什么？'
    },
    seed: `# The Dog in the Agora, retold for Parthenon

*Athens, around 340 BC. Diogenes of Sinope, exiled from his home city for defacing its coinage, lives in a large clay storage jar near the Metroon in the Agora. People call him "the Dog" (kyon), which is where the word Cynic comes from. He owns a cloak, a staff and a bag.*

## What Diogenes said and did

*(Anecdotes from the ancient biographers, retold.)*

In broad daylight he walks through the Agora carrying a lit lamp. "What are you doing?" "Looking for a human being."

He saw a child drinking water from cupped hands and threw away his cup: "A child has beaten me at plain living."

When Plato defined a human being as "a two-legged animal without feathers" and was applauded, Diogenes plucked a chicken, carried it into the Academy and announced: "Here is Plato's human being." The Academy added "with broad flat nails" to the definition.

Asked where he came from, he said: "I am a citizen of the world."

He begged from statues, "to practise being refused".

When Alexander, the young king of Macedon, stood over him while he sunned himself and said, "Ask me for anything you like," Diogenes answered: "Stand a little out of my sun." Alexander is said to have told his companions: "If I were not Alexander, I would want to be Diogenes."

He said the gods had given people an easy life, but it was hidden from them by their craving for honey cakes, perfume and the like.

He mocked the scholars who studied the sufferings of Odysseus while ignoring their own, the musicians who tuned their lyres but left their souls out of tune, and the orators who were eager to speak about justice but never to practise it.

He praised those who were about to marry and didn't, those about to go to sea and didn't, those about to enter politics and didn't.

"Other dogs bite their enemies. I bite my friends, to save them."

His teaching: live according to nature, need as little as possible, fear nothing, and say what you think, even to kings.

## Who was listening

- **Crates**, a wealthy young Theban who has just given away his fortune to follow Diogenes, and **Hipparchia**, a young woman of good family who wants to marry Crates and live as a Cynic, to her family's horror.
- **Plato** and the members of the **Academy**, tired of being the joke.
- Macedonian officers of **Alexander** stationed near the city.
- Shopkeepers and wine sellers of the Agora, who lose customers whenever he lectures in front of their stalls.
- Rich young men who find him hilarious and a little frightening.
- The market inspectors, the **agoranomoi**, who want him moved on.
- Enslaved people and the poor, some of whom think he is the only honest man in Athens.
- Mothers and fathers whose sons have started throwing away their sandals.

## What happens next

A few young Athenians have begun imitating him: sleeping in the Stoa, begging for bread, heckling politicians. The Assembly is debating whether to clear the Agora of "idlers".
`
  },
  {
    id: 'epicurus',
    name: 'Epicurus',
    greek: 'ΕΠΙΚΟΥΡΟΣ',
    letter: 'Ε',
    epithet: 'of the Garden',
    work: 'The Garden',
    place: 'The Garden',
    year: 'c. 300 BC',
    line: 'Death is nothing to us.',
    fileName: 'epicurus-the-garden.md',
    question:
      'Epicurus has opened his Garden to women and slaves and teaches that death is nothing to fear and that a simple, pleasant life among friends is the goal. How does Athens react: scandal, relief or quiet conversion? Do the priests, the Stoics and the rich push back, and what does the city decide about pleasure and fear?',
    // The same card in Chinese (read through localText.js). The seed stays English.
    zh: {
      name: '伊壁鸠鲁',
      epithet: '花园之主',
      work: '花园',
      place: '花园',
      year: '约公元前 300 年',
      line: '死亡与我们无关。',
      question: '伊壁鸠鲁向女人和奴隶敞开了他的花园，教导说死亡不足畏惧，与朋友一起过简朴而愉快的生活才是目的。雅典如何反应：是丑闻、释然，还是悄悄皈依？祭司、斯多亚派和富人会不会反击？对于快乐与恐惧，城邦最终作何决定？'
    },
    seed: `# The Garden, retold for Parthenon

*Athens, around 300 BC. Epicurus of Samos has bought a house with a garden just outside the Dipylon Gate. Over the gate, the story goes, is written: "Stranger, here you will do well to stay; here the highest good is pleasure." Unlike the other schools, the Garden admits women, among them the courtesan Leontion, and enslaved people such as Mys.*

## What Epicurus said

*(Retold in plain words from his letter to Menoeceus and his sayings.)*

"Let no one put off philosophy when young, or tire of it when old. It is never too early or too late to care for the health of the soul.

Get used to believing that death is nothing to us. Every good and every evil lies in sensation, and death is the end of sensation. While we exist, death is not here; when death is here, we no longer exist. So death, the most frightening of evils, is nothing to us.

Pleasure is the beginning and the end of the happy life. But when we say pleasure is the goal we do not mean the pleasures of the spendthrift or the bedroom, as some ignorant or hostile people claim. We mean freedom from pain in the body and from turmoil in the soul. It is not drinking parties and revels, or fish and fine food, that make a pleasant life, but sober reasoning that looks for the grounds of every choice and avoidance and drives out the beliefs that cause the greatest turmoil.

Plain bread and water give the greatest pleasure to someone who is hungry. Send me a little pot of cheese, so that I can have a feast whenever I like.

Of all the things wisdom provides for a happy life, by far the greatest is friendship.

The gods exist, but they are not what the many believe. A blessed and immortal being has no troubles and causes none to others; it is moved by neither anger nor favour. Do not fear them.

The four-part cure: do not fear the gods; do not worry about death; what is good is easy to get; what is terrible is easy to endure.

Live unnoticed."

## Who was listening

- **Metrodorus** of Lampsacus, Epicurus' dearest friend and co-founder of the Garden.
- **Leontion**, a courtesan who studies and writes philosophy in the Garden and has written a treatise criticising Theophrastus.
- **Mys**, an enslaved man who studies in the Garden alongside free citizens.
- **Zeno of Citium**, a merchant turned philosopher who teaches at the Painted Stoa and is convinced that virtue, not pleasure, is the only good.
- Priests and **temple officials**, whose income depends on sacrifices from people who fear the gods.
- Wealthy symposium hosts who hear "pleasure is the goal" and misunderstand it on purpose.
- Soldiers of the Macedonian garrison, and Athenians exhausted by decades of war and occupation.
- Poor farmers who already live on bread and water and wonder what is new.
- Philosophers of the **Academy** and the **Lyceum**, who call the Garden a pigsty.

## What happens next

Rumours spread that the Garden holds orgies; others say its members eat bread, drink water and talk about atoms. Several women from good families have started visiting.
`
  }
]

export const speakerSeedFile = (speaker) =>
  new File([speaker.seed], speaker.fileName, { type: 'text/markdown' })
