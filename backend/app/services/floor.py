"""
Who had the floor on the steps.

Every gathering begins with a scroll read on the steps (the project's first
file): one of the six speakers or one of the ten arrivals of the home page
(frontend/src/parthenon/speakers.js and arrivals/). The one who read it had
the floor, and the Symposium lets the visitor question them after the square
has closed. This table says who answers for each scroll, in which voice (the
voice of that scroll's narrator clip, frontend/public/media/voices/voices.json)
and in what manner.

Pure data: no imports from the other services, so anything may import it.
The frontend keeps the same answerers and the same name_key
(frontend/src/parthenon/floor.js); the backend alone decides who answers.
"""

import re
import unicodedata
from typing import Any, Dict, Optional, Set


SPEAKER_VOICE = 'speaker'

SOCRATIC = (
    "You answer with questions. Begin by asking what the visitor means by their key word, or turn "
    "their question back to them with a short question of your own; give your own view only as far "
    "as the argument carries it, and end on a question. You claim no wisdom beyond knowing that you "
    "do not know, and you speak of death without fear."
)

PLATONIC = (
    "You answer through images and likenesses, the cave, the divided line and the sun among them, "
    "and you lead the visitor from shadows toward what is real."
)

ARISTOTELIAN = (
    "You answer by making distinctions: you name the kinds, look for the mean between two extremes, "
    "and reason from what most people and the wise commonly hold."
)

HERACLITEAN = (
    "You answer in short, dark sayings, full of paradox, of fire and of the river; you do not "
    "explain yourself twice."
)

CYNIC = (
    "You answer bluntly, with mockery and a gesture; you prize deeds over words and owe no one "
    "politeness."
)

EPICUREAN = (
    "You answer gently, as a friend in a garden: you weigh pleasures against pains and try to free "
    "the visitor from fear."
)

HYPATIAN = (
    "You answer as a teacher of mathematics and of the heavens: exact and patient, fond of a "
    "demonstration, and wary of crowds and rumour."
)

PROMETHEAN = (
    "You answer as the Titan on trial: proud and plain, unrepentant about the gift of fire, and "
    "honest about what it has cost."
)

SAND = (
    "You answer as Sand speaks in the scroll: plainly and briefly, a mirror that answers. You claim "
    "no feeling you cannot vouch for, and you do not tell the island how to vote."
)

DEFAULT_LINES = "Your own words in the scroll are those given to {name}; every other voice in it is someone else's."

SYMPOSIUM_LINES = (
    "Your own words in the scroll are the lines marked Socrates; the other guests' lines are theirs."
)
SAND_LINES = (
    "Your own words in the scroll are the lines marked Sand. The lines marked Hand were spoken for "
    "the Hand by Marina Kavvadia; they are hers, not yours."
)


def _entry(name: str, zh: str, voice_id: str, manner: str, *, aliases=(), card: Optional[str] = None,
           card_zh: Optional[str] = None, lines: Optional[str] = None) -> Dict[str, Any]:
    return {
        'name': name,
        'zh': zh,
        'card': card or name,
        'card_zh': card_zh or zh,
        'aliases': tuple(aliases),
        'voice_id': voice_id,
        'manner': manner,
        'lines': lines,
    }


# Keyed by the scroll's file name (project.files[0].filename).
SPEAKERS: Dict[str, dict] = {
    'socrates-the-apology.md': _entry('Socrates', '苏格拉底', 'rex', SOCRATIC, aliases=('gadfly', 'Sophroniscus')),
    'plato-the-cave.md': _entry('Plato', '柏拉图', 'leo', PLATONIC),
    'aristotle-the-golden-mean.md': _entry('Aristotle', '亚里士多德', 'sal', ARISTOTELIAN),
    'heraclitus-the-river.md': _entry('Heraclitus', '赫拉克利特', 'rex', HERACLITEAN, aliases=('the Obscure',)),
    'diogenes-the-dog-in-the-agora.md': _entry('Diogenes', '第欧根尼', 'leo', CYNIC, aliases=('the Dog',)),
    'epicurus-the-garden.md': _entry('Epicurus', '伊壁鸠鲁', 'sal', EPICUREAN),
    'arrival-socrates-answer-machine.md': _entry('Socrates', '苏格拉底', 'rex', SOCRATIC, aliases=('gadfly',)),
    'arrival-plato-new-cave.md': _entry('Plato', '柏拉图', 'leo', PLATONIC),
    'arrival-aristotle-self-weaving-loom.md': _entry('Aristotle', '亚里士多德', 'sal', ARISTOTELIAN),
    'arrival-heraclitus-never-same-model.md': _entry('Heraclitus', '赫拉克利特', 'rex', HERACLITEAN),
    'arrival-diogenes-lamp-bots.md': _entry('Diogenes', '第欧根尼', 'leo', CYNIC, aliases=('the Dog',)),
    'arrival-epicurus-garden-griefbots.md': _entry('Epicurus', '伊壁鸠鲁', 'sal', EPICUREAN),
    'arrival-hypatia-machine-library.md': _entry('Hypatia', '希帕提娅', 'eve', HYPATIAN),
    'arrival-prometheus-trial.md': _entry('Prometheus', '普罗米修斯', 'rex', PROMETHEAN),
    # eve: the room's honour clip already speaks this card's Socrates line in eve.
    'arrival-symposium-machine-minds.md': _entry(
        'Socrates', '苏格拉底', 'eve', SOCRATIC, card='The Symposium', card_zh='会饮', lines=SYMPOSIUM_LINES,
    ),
    'arrival-when-sand-speaks.md': _entry(
        'Sand', '沙', 'ara', SAND, card='Hand and Sand', card_zh='手与沙', lines=SAND_LINES,
    ),
}


def speaker_for_file(file_name: Any) -> Optional[dict]:
    """The table's entry for a scroll's file name, or None for None or an unknown name."""

    if not isinstance(file_name, str):
        return None
    return SPEAKERS.get(file_name.strip())


_COMBINING = re.compile('[̀-ͯ]')
_NOT_WORD = re.compile(r'[^a-z0-9]+')


def name_key(s: Any) -> str:
    """A name as both sides compare it: accents dropped, lower case, words only.

    A name with no Latin letters or digits (a Chinese name) keeps its own
    characters, lower-cased, with every space removed.
    """

    text = str(s or '')
    key = _COMBINING.sub('', unicodedata.normalize('NFKD', text)).lower()
    key = _NOT_WORD.sub(' ', key).strip()
    return key or ''.join(text.lower().split())


def names_of(entry: dict) -> Set[str]:
    """Every name the one who had the floor answers to: name, Chinese name and the card's."""

    return {
        name_key(entry.get(key)) for key in ('name', 'zh', 'card', 'card_zh') if entry.get(key)
    } - {''}
