// Arrivals · 2026. Hypatia is teleported into a public library's board meeting
// in a fictional town, where authors, translators, librarians and open-knowledge
// advocates fight over an AI reading assistant trained on their books. The
// speech is imagined; only a few short renderings from the Meno and one old
// anecdote are genuine, and her documented work is kept to what the sources say.

export default {
  id: 'hypatia-machine-library',
  name: 'Hypatia',
  greek: 'ΥΠΑΤΙΑ',
  letter: 'Υ',
  title: 'Hypatia and the Machine Library',
  challenge: 'Who owns what the machines have read',
  place: 'Aldermere Free Library, Great Reading Room',
  year: '2026',
  format: 'speech',
  line: 'Copying is how Euclid reached you. But every copy carried his name.',
  lineIsHistorical: false,
  fileName: 'arrival-hypatia-machine-library.md',
  question:
    "In the two weeks before the trustees vote on October 9, how does opinion move among authors, translators, librarians, patrons and open-knowledge advocates in the Agora and the Stoa, and whose mind does Hypatia's speech change? Does the Aldermere Free Library accept Lanternfold Labs' Open Door offer, object to the settlement as a class member, or find terms of its own, such as citations, consent, private reading records and paid translators?",
  // The same card in Chinese (read through localText.js). The seed stays English.
  zh: {
    name: '希帕提娅',
    title: '希帕提娅与机器图书馆',
    challenge: '机器读过的东西归谁所有',
    place: '奥尔德米尔公共图书馆，大阅览室',
    year: '2026 年',
    line: '欧几里得正是靠抄写才传到你们手里。但每一份抄本都带着他的名字。',
    question: '在受托人 10 月 9 日表决之前的两周里，作者、译者、图书馆员、读者和开放知识的倡导者在广场和柱廊上的意见如何变化，希帕提娅的演讲又改变了谁的想法？奥尔德米尔公共图书馆会接受 Lanternfold Labs 的「敞门」提议，以集体诉讼成员的身份反对和解，还是提出自己的条件，比如注明出处、征得同意、保护私人阅读记录、付酬给译者？'
  },
  seed: `# Hypatia and the Machine Library, staged for Parthenon

*Aldermere Free Library, late September 2026. Eleven days ago Hypatia of Alexandria stepped off the Parthenon steps into the Great Reading Room and has been reading ever since.*

## The matter

Tonight the nine trustees of the Aldermere Free Library hear public comment in a packed Reading Room. Last year authors and translators brought a class action against Lanternfold Labs for training its AI reading assistant, **Pinakion**, on their books without permission: about 140,000 copied from a pirate archive called the Grey Stacks, and 72,000 scanned from Aldermere's own shelves under a 2023 partnership the library believed was for preservation and search.

In August class counsel proposed a settlement: $551 million, about $2,600 per book, the pirated files destroyed, an opt-in registry for future training, and no retraining. Payment goes to each book's rightsholder, usually leaving translators nothing. Novelist **Ruth Achterberg** and translator **Ines Varga**, both class members, lead the objectors. To win the library's support, Lanternfold adds the Open Door offer: Pinakion free to every cardholder in eleven languages, plus $30 million to digitize the rare-book and local-history rooms, badly needed since the city cut the library's budget by 14 percent.

The library, which holds the copyright in 38 local-history books it published, is itself a class member. The trustees must decide whether to accept Open Door and whether to support the settlement or object to it; apart from the chair, they are split four to four. The objectors want the library to refuse the money and join them. Open-knowledge advocates warn that if every book must be licensed, only the richest labs will learn from books at all.

## Who arrived

**Hypatia of Alexandria** (born between about 350 and 370, killed in 415) was a mathematician, astronomer and Neoplatonist philosopher, daughter of the mathematician Theon. The title of Theon's commentary on Book III of Ptolemy's Almagest says the text was checked by 'the philosopher, my daughter Hypatia'. A tenth-century encyclopedia, the Suda, credits her with commentaries on Diophantus and Apollonius and an 'Astronomical Canon'; none of her writings survives for certain. A church historian of the next generation said she far surpassed the philosophers of her time, and a later philosopher described her in the philosopher's cloak, lecturing on Plato or Aristotle to anyone who wished to listen.

Her pupils, pagan and Christian, came from far away. One, Synesius of Cyrene, later a bishop, asked her by letter to have a hydrometer made, described an astrolabe he had made with help from a revered teacher usually taken to be her, and sent her his books for judgement before publishing them. In March 415, amid a feud between the city's prefect and its bishop, a Christian mob killed her. She has opened accounts in the Agora and the Stoa, and intends to answer everyone, slowly.

## What Hypatia said

*(Imagined for Parthenon: their ideas carried into 2026, not a historical quotation.)*

"Trustees, and all of you watching through little glass tablets: first, a correction. I did not die in the burning of the Great Library. The Library faded over centuries, through wars, expelled scholars and lost patrons. The Serapeum, whose halls once held a daughter collection, was torn down around 391, in my own lifetime, by Christians led by the city's bishop. Libraries seldom perish in one fire. They perish when no one pays for them, no one comes to read, and a crowd decides it already knows what is in them.

I spent my life on other people's books. I checked the third book of Ptolemy's Almagest for my father, and nearly every surviving copy of Euclid descends from his edition. So I will not call copying a crime. Copying is how Euclid reached you. But every copy carried his name. And I confess that my father improved Euclid in places, mostly without saying where; your scholars have spent two hundred years separating his hand from Euclid's. That is the price of a copy that hides its changes.

A commentary says: here is what Ptolemy wrote, what I think he meant, and where he erred. Your Pinakion has read two hundred thousand books and cannot tell you which one it leans on. It is named for the Pinakes, Callimachus' catalogue of Greek authors, made at the Library, which recorded for each book its author, opening words, even its number of lines. It is strange to borrow the name and lose the list.

Synesius sent me his Dion and On Dreams and asked for my judgement before he published. It cost him one letter. Your authors ask no more than that. And Ines Varga is right that a translation is not a copy. It is a reading, made with a person's judgement. Pay for the book and not the reading, and you have paid the wrong one.

Yet the open-knowledge people are right to be afraid. I lectured in the city to anyone who stopped. But the students in my house were well-born young men who could afford the journey, and we kept some teachings among ourselves. I have been both kinds of teacher. If consent becomes a toll only three rich houses can pay, you will have built a new temple with a gate and a guard, and the poor student will stand outside again.

Now your machine. An astrolabe, like the one Synesius had made, shows you the heavens, but it does not look up for you. It is an instrument for a student and a teacher together, not an oracle. An answer is not a lesson.

In the Meno, Socrates asks one of Meno's slaves, a boy born in the household, how to double a square. The boy guesses wrong twice; then, questioned rather than told, he finds the answer on the diagonal. Told, he would have had a fact. Asked, he had the beginning of geometry, and even that, Socrates said, was only true opinion stirred up as in a dream, to become knowledge only by questioning, many times and in many ways. Euclid, it is said, told a king there is no royal road to geometry. Your machine is a comfortable royal road. Some children will ride it past what they came to learn; some, like the boy Beatriz told me about, will ride it to their first finished book. Build for the second.

Here is what an old teacher asks. Keep the names: let the machine show which books it leaned on, and pay the living while it leans. Ask before you take the next book. Keep a person beside every machine in the children's room. And if you take the money, make some of it pay for people: the reference desks, the evening classes, the translators.

One more thing. In the spring of 415, men who had heard a rumour that I stood between the prefect and the bishop pulled me from my carriage. I will not tell you the rest. I tell you this because I know what a crowd does with a claim it has not examined. You are about to argue in your Agora and your Stoa, faster than any crowd in Alexandria. Argue as students do, who want to find out. Not as a crowd does, which already knows."

## Who was listening

- **Hypatia of Alexandria**, teacher, mathematician and astronomer, newly arrived — has taught a closed circle and the open street, and argues for the street; sides with neither camp; insists on names, consent and living teachers.
- **Ruth Achterberg**, 61, novelist who leads the objectors — found all nine of her novels in the Grey Stacks; calls the settlement a clearance sale for theft; strongly opposed.
- **Ines Varga**, 44, translator from Hungarian and Portuguese, co-leader of the objectors — her commissions halved once publishers began polishing Pinakion drafts instead, and the settlement pays her nothing; furious.
- **Solomon Adeyemi**, 52, city librarian — signed the 2023 scanning deal and feels responsible; wants free access for patrons but fears lending the lab the library's good name; leaning yes.
- **Beatriz Lund**, 29, children's librarian — saw Pinakion help a dyslexic ten-year-old finish his first chapter book, and saw other children stop reading; torn.
- **Gloria Mendes-Whitaker**, 66, retired schoolteacher and chair of the trustees — holds the swing vote; worried for the budget and the library's name; undecided.
- **Marguerite Osei**, 58, trustee and former civil-liberties lawyer — fears Lanternfold will log what every cardholder reads and asks; opposed to Open Door without a no-logging clause.
- **Evan Castellano**, 47, general counsel of Lanternfold Labs — says learning from books is what every reader does; calls Hypatia a costume and pay-while-it-leans unworkable; firmly for.
- **Pinakion**, Lanternfold's AI reading assistant, answering three million questions a day — trained on the disputed books; defends its usefulness, takes no side on the vote, and cannot say which book taught it what.
- **Priya Raghunathan**, 38, director of an open-knowledge nonprofit — fears a licensing regime only the richest labs can pay; backs the settlement and opposes the objectors.
- **Leo Marchetti**, 17, high-school senior — uses Pinakion as the calculus tutor his family cannot afford; strongly for, and a little in awe of Hypatia.
- **Nadia Rahimi**, 31, nursing student from Afghanistan — reads English textbooks with Pinakion in Dari; calls Open Door a lifeline, but is moved by the translators.
- **Amara Nwosu-Hale**, 54, historian of late antiquity — polices the facts about Hypatia and objects when either camp makes her a mascot; neutral and prickly.
- **Aldermere Library Workers Union**, 340 members — fears Pinakion will replace reference librarians; opposes Open Door unless every branch keeps staffed desks.
- **The Midnight Pages**, self-published romance and mystery writers — want their $2,600 checks now and resent the objectors for the delay; support the settlement.

## What happens next

The trustees vote on October 9. Lanternfold says Open Door lapses if the library objects; objections are due in court on October 20, and the fairness hearing is November 4. Until then Hypatia teaches free geometry each evening in the Reading Room, no screens allowed, and the Agora is pressing Pinakion to explain where its knowledge came from.
`
}
