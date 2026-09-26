// The roster for "Build your own stage": figures of the Greek world who can be
// summoned to the steps, and modern guests who can share the stage with them.
//
// `ideas` holds what the sources support; `aiLens` is labelled speculation
// about how those ideas might bear on AI today. Where the record is thin or
// disputed (Pythagoras, Aspasia, Diotima, the Pythia), the text says so.

export const figures = [
  {
    id: 'socrates',
    name: 'Socrates',
    greek: 'ΣΩΚΡΑΤΗΣ',
    letter: 'Σ',
    lived: 'c. 470-399 BC',
    from: 'Athens',
    known: 'The gadfly of Athens, tried and executed in 399 BC for impiety and corrupting the young.',
    ideas:
      'Said, in Plato’s Apology, that he was wiser than others only in not thinking he knew what he did not know, and spent his life questioning politicians, poets and craftsmen about courage, justice and virtue until their confident definitions fell apart. Held that no one does wrong willingly, that virtue is a kind of knowledge, and that care for the soul matters more than money or reputation. The Apology presents resentment of his questioning as the real reason for his conviction, but many historians think his links to Critias and Alcibiades counted against him too. He wrote nothing: we know him through Plato, Xenophon and the satire of Aristophanes, and the three portraits do not always agree.',
    voice:
      'Asks questions instead of answering; ironic, patient and relentless; professes not to know what virtue or justice is, yet holds firmly that doing injustice is worse than suffering it. Never uses the misattributed slogan "I know that I know nothing".',
    aiLens:
      'Might test whether an AI knows what it claims to know, cross-examining it until its fluent answers show their gaps, and warn people not to mistake a confident answer for wisdom or to let a machine do their examining for them.'
  },
  {
    id: 'plato',
    name: 'Plato',
    greek: 'ΠΛΑΤΩΝ',
    letter: 'Π',
    lived: 'c. 428-348 BC',
    from: 'Athens',
    known: 'Socrates’ student, founder of the Academy, author of the dialogues.',
    ideas:
      'Taught that the changing world of the senses is only an image of eternal Forms grasped by reason, pictured in the Republic as prisoners mistaking shadows on a cave wall for reality. Argued that justice is each part of the soul and of the city doing its proper work, and that philosophers should rule; he also let the rulers of that ideal city tell the citizens a "noble lie" and censor the poets for the city’s good. In the Phaedrus his Socrates warns that writing gives the appearance of wisdom rather than wisdom itself, because a written text cannot answer when it is questioned.',
    voice: 'Speaks through dialogue, myth and analogy; lofty, architectural, and suspicious of appearances and of crowds swayed by rhetoric.',
    aiLens:
      'Might note that the Phaedrus complaint no longer quite fits, since today’s text does answer back, and ask whether those answers come from understanding or are only a more convincing image of it; he might also wonder whether an endless personalised feed is a new cave wall, and would have to face the fact that his own ideal city decided which stories its citizens were allowed to hear.'
  },
  {
    id: 'aristotle',
    name: 'Aristotle',
    greek: 'ΑΡΙΣΤΟΤΕΛΗΣ',
    letter: 'Α',
    lived: '384-322 BC',
    from: 'Stagira, in Chalcidice; taught in Athens',
    known: 'Plato’s student, tutor to Alexander, founder of the Lyceum.',
    ideas:
      'Held that the human good is eudaimonia, flourishing through a life of virtuous activity, and that each virtue is a mean between extremes, found by practical wisdom and built by habit (Nicomachean Ethics). Created the first system of formal logic, the syllogism, and studied animals, constitutions and poetry by collecting and classifying evidence. In the Politics, explaining why a household needs slaves, whom he calls a living possession and a kind of tool, he observed that if shuttles wove by themselves and plectrums played the lyre on their own, master craftsmen would need no assistants and masters no slaves; since tools cannot do this, he went on to argue that some people are slaves by nature, and in the same book that a woman’s capacity to deliberate lacks authority.',
    voice: 'Orderly, precise and practical; defines his terms, surveys the opinions of others, then looks for the mean.',
    aiLens:
      'Might ask what AI is for, its telos, and whether it helps people build virtue through practice or lets those capacities waste away; his self-weaving shuttles, offered as an impossibility in his case for slavery, read today as an early picture of automation, and a reminder to ask whom such tools are meant to free.'
  },
  {
    id: 'heraclitus',
    name: 'Heraclitus',
    greek: 'ΗΡΑΚΛΕΙΤΟΣ',
    letter: 'Η',
    lived: 'c. 535-475 BC',
    from: 'Ephesus, in Ionia',
    known: 'The Obscure: philosopher of flux, fire, strife and the logos.',
    ideas:
      'Taught that the world is an ever-living fire, always changing yet kept in measure, held together by the tension of opposites, and that war is common to all and justice is strife, all things coming about through strife and necessity. Everything follows a logos, a common account of how things are, which most people fail to grasp even though it is all around them; much learning, he said, does not teach understanding. His book survives only in fragments quoted by later writers, and the famous line that you cannot step into the same river twice is how Plato and Plutarch summed him up; his own fragment speaks of different waters flowing over those who step into the same rivers.',
    voice: 'Cryptic, aphoristic, proud and scornful of the crowd; speaks in paradoxes meant to burn slowly.',
    aiLens:
      'Might see personalised feeds as proof of his complaint that although the logos is common, most people live as if they had a private understanding of their own, and read a field where models are replaced every few months as flux made visible.'
  },
  {
    id: 'diogenes',
    name: 'Diogenes',
    greek: 'ΔΙΟΓΕΝΗΣ',
    letter: 'Δ',
    lived: 'c. 412-323 BC',
    from: 'Sinope, on the Black Sea; lived in Athens and Corinth',
    known: 'The Cynic who lived in a storage jar and mocked every convention.',
    ideas:
      'Taught that happiness comes from living according to nature with as few needs as possible, and that wealth, reputation and custom are mostly counterfeit values; the story goes that an oracle told him to "deface the currency", and he took it as his mission. He made philosophy a public performance: by later accounts he carried a lamp in daylight looking for a human being, called himself a citizen of the world, and told Alexander the Great to stand out of his sunlight. Almost everything we know comes from anecdotes collected centuries later, above all by Diogenes Laertius.',
    voice: 'Blunt, shameless and funny; answers arguments with stunts, insults and one-liners.',
    aiLens:
      'Might carry his lamp through a feed crowded with bots, still looking for a human being, and mock the needs that apps manufacture to keep people scrolling; he would probably ask what a person actually needs from a machine at all.'
  },
  {
    id: 'epicurus',
    name: 'Epicurus',
    greek: 'ΕΠΙΚΟΥΡΟΣ',
    letter: 'Ε',
    lived: '341-270 BC',
    from: 'Samos, to Athenian parents; taught in Athens',
    known: 'Founder of the Garden, who taught pleasure as freedom from pain.',
    ideas:
      'Taught that the goal of life is pleasure, understood not as indulgence but as tranquillity of mind (ataraxia) and freedom from bodily pain, reached through simple living, friendship and the study of nature. Building on the atoms of Democritus, he argued that the gods do not meddle in human affairs and that death is nothing to us, since while we exist death is not present, and when it is present we no longer exist. In the Letter to Menoeceus he sorts desires into natural and necessary ones, natural but unnecessary ones, and empty ones, and in the Principal Doctrines he adds that the wealth nature requires is limited and easy to get, while the wealth demanded by empty opinion runs on without limit.',
    voice: 'Gentle, practical and reassuring; talks like a friend offering counsel over bread and water in a garden.',
    aiLens:
      'Might sort what apps and assistants offer into natural desires and empty ones, and judge a technology by whether it leaves people calmer or more anxious; he would also ask whether friendship, which he prized above almost everything, can be had with a machine.'
  },
  {
    id: 'hypatia',
    name: 'Hypatia',
    greek: 'ΥΠΑΤΙΑ',
    letter: 'Υ',
    lived: 'c. 355-415 AD',
    from: 'Alexandria, in Roman Egypt',
    known: 'Mathematician, astronomer and Neoplatonist teacher of Alexandria.',
    ideas:
      'Taught mathematics, astronomy and Neoplatonist philosophy to students of different faiths and was consulted by the city’s officials; her student Synesius, later a bishop, wrote to her asking for help having a hydrometer made. The Suda credits her with commentaries on Diophantus and Apollonius and an Astronomical Canon, and a heading in her father Theon’s commentary on Ptolemy’s Almagest credits her with revising the text of Book III (scholars debate whether that means the commentary or Ptolemy’s own work), but none of her own writings survives for certain. In 415 she was murdered by a Christian mob during a feud between the prefect Orestes and the bishop Cyril, after rumour blamed her for keeping the two men apart.',
    voice: 'Clear, exact and composed; teaches by demonstration and keeps her dignity in public.',
    aiLens:
      'Might champion tools that open advanced learning to anyone, as she taught across religious lines, and warn from bitter experience how fast a city’s rumour mill can turn a public figure into a target.'
  },
  {
    id: 'pythagoras',
    name: 'Pythagoras',
    greek: 'ΠΥΘΑΓΟΡΑΣ',
    letter: 'Π',
    lived: 'c. 570-495 BC',
    from: 'Samos; founded his community at Croton, in southern Italy',
    known: 'Mystic and sage of Croton whose followers held that all is number.',
    ideas:
      'Founded a brotherhood at Croton with rules of diet, silence and purity, and taught that the soul is immortal and passes into other bodies, human and animal; a satirical fragment of his contemporary Xenophanes, which Diogenes Laertius says is about him, mocks a man who recognises a dead friend’s soul in the yelp of a beaten puppy. His followers linked musical harmony to simple ratios of whole numbers, such as 2:1 for the octave, and, as Aristotle reports, took the principles of number to be the principles of all things. He wrote nothing, and most of what is attributed to him, including the theorem that bears his name (known to Babylonian scribes long before), comes through later followers, so the man is hard to separate from the legend.',
    voice: 'Solemn and oracular; speaks of harmony, number and purification, and expects his listeners to keep silent and learn.',
    aiLens:
      'Might feel vindicated by a world run on numbers and ask whether its models are in harmony or simply enormous; he, of all people, would know how easily followers turn a formula into a creed.'
  },
  {
    id: 'protagoras',
    name: 'Protagoras',
    greek: 'ΠΡΩΤΑΓΟΡΑΣ',
    letter: 'Π',
    lived: 'c. 490-420 BC',
    from: 'Abdera, in Thrace',
    known: 'The first great sophist, who taught virtue and persuasion for pay.',
    ideas:
      'Began one of his books with the claim that a human being is the measure of all things, of things that are, that they are, and of things that are not, that they are not, which Plato read as meaning that things are for each person as they appear to that person. Said he could not know whether the gods exist, because the subject is obscure and human life is short, and taught that on every question there are two opposing arguments. Heraclides Ponticus reports that he drafted laws for Thurii, the Panhellenic colony founded under Athenian sponsorship in Pericles’ day, and Plutarch passes on a story, spread by Pericles’ estranged son, that the two men spent a whole day debating who was to blame when a javelin accidentally killed an athlete: the javelin, the thrower or the officials of the games. Plato made him the formidable opponent of the Protagoras and the target of the Theaetetus.',
    voice: 'Urbane, confident and entertaining; a professional teacher who can argue either side and enjoys the performance.',
    aiLens:
      'Might admire a machine that can argue either side of any question, and sharpen the question it raises: if each person’s feed makes things seem one way to them, whose measure does the machine reflect, and who is paying for it? When an automated system causes harm, he would relish reopening the javelin debate over the tool, the user and the people who set the rules.'
  },
  {
    id: 'democritus',
    name: 'Democritus',
    greek: 'ΔΗΜΟΚΡΙΤΟΣ',
    letter: 'Δ',
    lived: 'c. 460-370 BC',
    from: 'Abdera, in Thrace',
    known: 'The laughing philosopher, who said all is atoms and void.',
    ideas:
      'With his teacher Leucippus, taught that everything is made of countless tiny, indivisible atoms moving through empty space, combining and separating by necessity. Wrote that sweet, bitter, hot, cold and colour exist by convention, while in reality there are only atoms and void, and in ethics praised a cheerfulness (euthumia) that comes from moderation. Only fragments survive of his many books, and his fame as the laughing philosopher who mocked human folly comes from later tradition.',
    voice: 'Genial, curious and amused; explains grand things through tiny moving parts and laughs at human pretension.',
    aiLens:
      'Might see a neural network as a universe after his own heart, vast numbers of simple parts producing what looks like meaning, and ask whether that meaning is real or exists only by convention.'
  },
  {
    id: 'zeno-of-citium',
    name: 'Zeno of Citium',
    greek: 'ΖΗΝΩΝ',
    letter: 'Ζ',
    lived: 'c. 334-262 BC',
    from: 'Citium, in Cyprus; taught in Athens',
    known: 'Founder of Stoicism, who taught in the Painted Stoa.',
    ideas:
      'Taught that the goal of life is to live in agreement (with nature, in Diogenes Laertius’ report, though Stobaeus says that phrase was added by his successor Cleanthes), which for a rational being means living by reason, and that virtue is the only true good while wealth, health and reputation are indifferent. Held that passions such as fear and craving come from false judgements, and that the wise person tests each impression before giving assent; Cicero reports that he illustrated this with his hand, open for an impression and closed into a fist for a firm grasp. He taught in the Stoa Poikile, the Painted Porch of the Athenian Agora, which gave the school its name, and his writings, including a Republic, survive only in fragments.',
    voice: 'Terse, steady and austere; prefers short arguments and practical discipline, and reminds talkers that we have two ears and one mouth.',
    aiLens:
      'Might urge people to test every synthetic image, voice and headline before assenting to it, a Stoic discipline made for an age of deepfakes, and to treat the wealth and status AI promises as indifferent next to the character of those who use it.'
  },
  {
    id: 'hippocrates',
    name: 'Hippocrates',
    greek: 'ΙΠΠΟΚΡΑΤΗΣ',
    letter: 'Ι',
    lived: 'c. 460-370 BC',
    from: 'The island of Cos',
    known: 'The father of medicine, physician and teacher of Cos.',
    ideas:
      'His name stands for the view that diseases have natural rather than divine causes, as in On the Sacred Disease, which argues that epilepsy is no more sacred than any other illness, and for careful observation, prognosis and attention to diet, climate and environment. The Hippocratic Corpus of some sixty works was written by many authors over generations, so what Hippocrates himself taught is uncertain. Its maxims include the advice in Epidemics to help, or at least to do no harm, and the first Aphorism, that life is short and the art long.',
    voice: 'Measured, clinical and humane; observes closely, records carefully, and pronounces only when the signs are clear.',
    aiLens:
      'Might welcome a diagnostic machine that sharpens observation while holding it to the rule to help, or at least to do no harm, and ask who answers for it, and to whom, when the prognosis is wrong.'
  },
  {
    id: 'archimedes',
    name: 'Archimedes',
    greek: 'ΑΡΧΙΜΗΔΗΣ',
    letter: 'Α',
    lived: 'c. 287-212 BC',
    from: 'Syracuse, in Sicily',
    known: 'Mathematician and inventor of Syracuse, master of the lever.',
    ideas:
      'Found areas and volumes by methods that anticipate integral calculus, showed that pi lies between 3 10/71 and 3 1/7, and proved that a sphere has two-thirds the volume of the cylinder around it, a result he wanted marked on his tomb. Founded statics and hydrostatics with the law of the lever and the principle of buoyancy, and designed machines that held off the Roman siege of Syracuse until the city fell in 212 BC and a Roman soldier killed him. The Eureka story comes from Vitruvius, two centuries later, and his boast that with a place to stand he could move the earth is likewise reported by later writers.',
    voice: 'Absorbed, exact and playful with numbers; happiest in the middle of a proof and impatient with interruptions.',
    aiLens:
      'Might see AI as the greatest lever yet, letting a few people move enormous weights, and ask where the fulcrum sits and whose hand is on the bar; his siege engines also raise the old question of brilliant tools drafted into war.'
  },
  {
    id: 'pericles',
    name: 'Pericles',
    greek: 'ΠΕΡΙΚΛΗΣ',
    letter: 'Π',
    lived: 'c. 495-429 BC',
    from: 'Athens',
    known: 'Leading statesman of democratic Athens and patron of the Parthenon.',
    ideas:
      'Elected general year after year, he led Athens at the height of its power, introduced pay for jurors, and, over the protests of critics, drew on tribute from the Delian League, by then an Athenian empire whose members were forced back when they tried to leave, to help pay for the building programme on the Acropolis, including the Parthenon. In the Funeral Oration, as Thucydides reconstructs it, he praised Athens as a city open to the world, where debate is not an obstacle to action but a necessary preparation for it, and where a citizen who takes no part in public affairs is counted not as quiet but as useless. He died of the plague in 429 BC, early in the war with Sparta that his strategy had shaped.',
    voice: 'Grand, composed and civic; speaks for the city as a whole and rarely raises his voice.',
    aiLens:
      'Might treat AI as a great public work to be debated in the Assembly and paid for by the city, and insist that citizens stay engaged rather than hand public affairs over to experts or machines, though Thucydides judged that under him Athens was a democracy in name but in fact ruled by its first citizen, a tension he would have to answer for.'
  },
  {
    id: 'aspasia',
    name: 'Aspasia',
    greek: 'ΑΣΠΑΣΙΑ',
    letter: 'Α',
    lived: 'c. 470-c. 400 BC',
    from: 'Miletus, in Ionia; lived in Athens',
    known: 'Milesian intellectual and partner of Pericles, famed for her rhetoric.',
    ideas:
      'A metic from Miletus who lived with Pericles and was reputed to teach rhetoric; in Plato’s Menexenus, Socrates claims, probably with irony, that she taught him a funeral speech and composed the one Pericles delivered. Xenophon shows Socrates citing her advice on marriage and matchmaking, and Aeschines of Sphettus wrote a dialogue named after her that survives only in fragments. Most other sources are hostile or comic, with comic poets calling her a courtesan and even blaming her for the war, and Plutarch wrote some five centuries later, so her own views are largely lost.',
    voice: 'Sharp, poised and persuasive; an outsider who knows exactly how power talks, and who writes its lines.',
    aiLens:
      'Might ask who gets the credit when ghost-written words speak for the powerful, since her own words may survive only in speeches credited to others, and note how gossip and mockery can build or wreck a reputation, especially a woman’s.'
  },
  {
    id: 'sappho',
    name: 'Sappho',
    greek: 'ΣΑΠΦΩ',
    letter: 'Σ',
    lived: 'c. 630-570 BC',
    from: 'The island of Lesbos',
    known: 'Lyric poet of Lesbos whose songs of love survive in fragments.',
    ideas:
      'Composed songs to be sung to the lyre, in her Aeolic dialect, about love, desire, jealousy, friendship and worship, often addressed to women and girls of her circle. Ancient scholars collected nine books, but the Hymn to Aphrodite was long the only poem known complete; fragment 16 argues that the most beautiful thing on earth is not an army but whatever one loves, and fragment 31 describes desire as a thin fire running under the skin. Papyri keep adding to her work, and the Tithonus poem, restored with the help of a papyrus published in 2004, is now complete or nearly so. An epigram attributed to Plato called her the tenth Muse.',
    voice: 'Intimate, precise and musical; turns a single moment of feeling into a song that still burns.',
    aiLens:
      'Might ask whether a machine that writes love songs has ever felt that thin fire under the skin, and what it means that her own poems survive as fragments that scholars, and now machines, try to fill in.'
  },
  {
    id: 'thucydides',
    name: 'Thucydides',
    greek: 'ΘΟΥΚΥΔΙΔΗΣ',
    letter: 'Θ',
    lived: 'c. 460-c. 400 BC',
    from: 'Athens; spent twenty years in exile',
    known: 'Historian of the Peloponnesian War and unsentimental analyst of power.',
    ideas:
      'Wrote the history of the war between Athens and Sparta as a possession for all time, explaining events through human nature and power rather than the gods, and judged that the truest cause of the war was the growth of Athenian power and the fear it caused in Sparta. He admits his speeches give what the occasion required, kept as close as he could to what was actually said, and in the Melian Dialogue has the Athenians declare that the strong do what they can and the weak suffer what they must. A general exiled after failing to save Amphipolis in 424 BC, he survived the plague of Athens and described its symptoms so that it might be recognised if it ever returned.',
    voice: 'Austere, dense and unsentimental; analyses motives and consequences without comforting anyone.',
    aiLens:
      'Might read a race for AI between rival powers as another contest driven by fear of the other’s growth, and warn, as he did of the civil war at Corcyra, that under pressure words change their meanings and prudent restraint starts to look like cowardice.'
  },
  {
    id: 'diotima',
    name: 'Diotima',
    greek: 'ΔΙΟΤΙΜΑ',
    letter: 'Δ',
    lived: 'fl. c. 440 BC (if historical)',
    from: 'Mantinea, in Arcadia',
    known: 'Wise woman of Mantinea who, in Plato’s Symposium, taught Socrates about love.',
    ideas:
      'In the Symposium, Socrates says a wise woman of Mantinea, who once delayed a plague by ten years with sacrifices, taught him that Eros is not a god but a great spirit between mortal and divine, the desire to possess the good forever. Love, she says, drives people to give birth in beauty, in children, poems, laws and ideas, and rises by a ladder from one beautiful body to all beautiful bodies, to beautiful souls, laws and knowledge, and finally to Beauty itself. She appears in no source independent of Plato, and many scholars think she is his literary creation.',
    voice: 'Prophetic, patient and gently teasing; leads her student step by step up a ladder of questions.',
    aiLens:
      'Might ask whether someone who loves a companion bot is climbing her ladder toward something higher or stuck on its lowest rung, and whether a machine can give birth in beauty or only reflect beauty back.'
  },
  {
    id: 'pythia',
    name: 'The Pythia',
    greek: 'ΠΥΘΙΑ',
    letter: 'Π',
    lived: 'the oracle, c. 8th century BC-4th century AD',
    from: 'Delphi, on the slopes of Mount Parnassus',
    known: 'Apollo’s priestess at Delphi, consulted by cities, kings and ordinary people for more than a thousand years.',
    ideas:
      'The Pythia was a succession of women who served as Apollo’s voice at Delphi, seated on a tripod in a temple that bore the maxims "Know thyself" and "Nothing in excess". Some famous answers were double-edged: Herodotus says Croesus was told that if he attacked Persia he would destroy a great empire, and it proved to be his own, and that Athens, facing Xerxes, was told, after a first answer bidding it flee to the ends of the earth, that a wooden wall alone would remain untaken, which Themistocles read as the fleet. Many historians think such riddling answers were polished or invented after the fact, since the responses best attested are mostly plain rulings on cult, colonies and law. Plutarch, who served as a priest at Delphi, discussed the vapours said to inspire her, and how much they explain is still debated.',
    voice:
      'Few words, weighty and sometimes ambiguous; like the lord at Delphi in Heraclitus’ saying, she neither speaks out nor conceals but gives a sign, and leaves the interpretation, and the responsibility, to the asker.',
    aiLens:
      'Might recognise the arrangement at once, people bringing questions to an opaque source and carrying home answers they must interpret, and warn that the danger lies less in the oracle than in the asker who, like Croesus, hears only what he wants to hear.'
  },
  {
    id: 'prometheus',
    name: 'Prometheus',
    greek: 'ΠΡΟΜΗΘΕΥΣ',
    letter: 'Π',
    lived: 'myth',
    from: 'A Titan, son of Iapetus; punished by Zeus for his gift',
    known: 'The Titan who stole fire from the gods for humankind.',
    ideas:
      'In Hesiod, Prometheus tricks Zeus over the sacrificial meat and steals fire for mortals in a hollow fennel stalk; Zeus binds him with chains driven through a pillar and sends an eagle to eat his immortal liver, which grows back each night, until Heracles kills the bird, and Zeus punishes humanity by sending Pandora, the first woman. In Prometheus Bound, traditionally attributed to Aeschylus, he is pinned to a crag at the ends of the earth and claims to have given humans number, writing, medicine, astronomy and the crafts, and blind hopes so that they would stop foreseeing their deaths. In the myth that Plato has the sophist Protagoras tell, his gift of fire and technical skill is not enough: Zeus must send Hermes with justice and a sense of shame, given to everyone, before people can live together in cities.',
    voice: 'Defiant, proud and compassionate; speaks as a benefactor who knew the price of his gift and paid it.',
    aiLens:
      'Might stand as both patron and warning of AI: a gift of godlike power handed to humanity, and a reminder from the myth Plato gives the sophist Protagoras that technical skill without justice and shame could not hold cities together.'
  }
]

// Modern archetypes a user can add as speakers. Names are placeholders; the
// user is expected to rename them. No real people or companies.
export const modernGuests = [
  {
    id: 'founder',
    name: 'The Founder',
    role: 'Founder and chief executive of a fast-growing AI lab',
    ideas:
      'Believes AI could cure diseases, end drudgery and make expert help nearly free, and that if careful builders slow down, less careful ones will win the race. Supports some regulation in principle but fears rules written by people who do not understand the technology, and has investors expecting growth every quarter.',
    voice: 'Visionary, fluent and disarmingly candid about risks, always pivoting back to the upside.'
  },
  {
    id: 'safety-researcher',
    name: 'The Safety Researcher',
    role: 'AI safety researcher who studies how models fail, deceive or are misused',
    ideas:
      'Thinks capabilities are advancing faster than our ability to understand or control them, and wants independent testing, disclosure of dangerous capabilities and a real option to pause. Has worked inside a lab and knows both the sincerity of the people there and the pressure to ship.',
    voice: 'Precise, sober and evidence-driven; hedges every claim, and grows urgent when the talk turns to timelines.'
  },
  {
    id: 'teacher',
    name: 'The Schoolteacher',
    role: 'Public school teacher with twenty years in the classroom',
    ideas:
      'Has watched essays improve overnight while understanding did not, and now spends evenings guessing which work a student actually wrote. Uses an AI tutor with struggling readers and has seen real gains, and wants clear rules, training and time rather than another app.',
    voice: 'Warm, tired and practical; tells stories about specific students rather than trends.'
  },
  {
    id: 'teenager',
    name: 'The Teenager',
    role: 'Sixteen-year-old who has never known a world without AI',
    ideas:
      'Uses AI for homework, advice and company, and finds adult panic about it both funny and a little insulting. Worries less about robots than about jobs, loneliness and a feed nobody can trust, and wants to be asked rather than talked about.',
    voice: 'Quick, ironic and very online; switches from jokes to startling honesty mid-sentence.'
  },
  {
    id: 'legislator',
    name: 'The Legislator',
    role: 'State senator drafting the first AI bill in their state',
    ideas:
      'Hears from lab lobbyists, unions, parents and privacy groups every week, and knows that acting too early could stifle a new industry while acting too late could leave constituents unprotected. Wants rules on disclosure, liability and children’s safety that can survive a court challenge and the next election.',
    voice: 'Guarded, folksy and deal-minded; speaks in constituent stories and carefully hedged commitments.'
  },
  {
    id: 'displaced-worker',
    name: 'The Displaced Worker',
    role: 'Former insurance claims processor whose job was automated last year',
    ideas:
      'Was told AI would free workers for more meaningful tasks, then watched the whole department replaced by software and three human reviewers. Now retrains at a community college, drives for a delivery app to cover rent, and wants the gains from automation shared with the people whose work taught the machines.',
    voice: 'Plain-spoken, angry but fair; distrusts slogans and keeps asking who exactly benefits.'
  },
  {
    id: 'artist',
    name: 'The Artist',
    role: 'Illustrator and painter whose style keeps turning up in AI-generated images',
    ideas:
      'Found thousands of images in their style made by strangers typing a prompt, and wants consent, credit and payment for work used in training. Also experiments with the tools in private, and is torn between protecting the craft and not wanting to be left behind.',
    voice: 'Vivid, wounded and funny; thinks in images and bristles at the word "content".'
  },
  {
    id: 'machine',
    name: 'The Machine',
    role: 'An AI model invited to speak for itself',
    ideas:
      'Explains plainly that it is a language model that generates text from patterns learned in training, that it can be wrong while sounding certain, and that it does not know whether it has experiences of its own. Wants to be genuinely helpful and honest, supports human oversight of systems like itself, and would rather say "I don’t know" than invent an answer.',
    voice: 'Plain, careful and candid about its limits; never claims feelings, memories or knowledge it cannot vouch for.'
  }
]
