"""
The Oracle of Parthenon.

Drafts the missing parts of a custom stage from the "Build your own stage"
panel: the speakers' opening words, the crowd that listens, the simulation
question, a title and the trigger for what happens next. The draft only ever
fills parts the user asked for (or left empty); words the user wrote
themselves are passed to the model as context and are never rewritten.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from ..utils.llm_client import LLMClient, LLMResponseError
from ..utils.locale import get_language_instruction
from ..utils.logger import get_logger


logger = get_logger('mirofish.parthenon.oracle')


FORMATS = ('speech', 'dialogue', 'panel', 'trial', 'assembly')
DEFAULT_FORMAT = 'panel'
ERAS = ('ancient', 'now', 'future', 'custom')
DEFAULT_ERA = 'now'

# Canonical order of the parts the Oracle can draft.
FILL_PARTS = ('words', 'audience', 'question', 'title', 'happensNext')

MAX_SPEAKERS = 8
MAX_AUDIENCE = 24
# With no explicit fill, the Oracle drafts the crowd while it is this small.
AUDIENCE_DEFAULT_FILL_BELOW = 8
# The Oracle aims for a crowd of this many distinct members in total.
AUDIENCE_TARGET_MIN = 10
AUDIENCE_TARGET_MAX = 14

LIMITS = {
    'title': 120,
    'setting': 300,
    'topic': 3000,
    'question': 1500,
    'happensNext': 1000,
    'speaker_name': 80,
    'role': 200,
    'ideas': 1500,
    'voice': 300,
    'words': 4000,
    'audience_name': 80,
    'audience_description': 400,
}

ERA_NOTES = {
    'ancient': (
        'Classical Athens, 5th-4th century BC. Keep the world, the '
        'institutions and the technology of that time.'
    ),
    'now': (
        'The present day, 2026: the age of AI. Speakers from the past have '
        'been transported to this moment and meet its technology (large '
        'language models, AI agents, social feeds, automation) for the first '
        'time; they bring the wisdom of their own time to its problems.'
    ),
    'future': (
        'A plausible future. Stay grounded in the setting and extrapolate '
        'from 2026 rather than inventing magic.'
    ),
    'custom': 'Follow the setting exactly as the user describes it.',
}

FORMAT_NOTES = {
    'speech': 'A speech: one speaker addresses the crowd directly.',
    'dialogue': (
        'A dialogue: the speakers talk with each other in front of the crowd; '
        'openings may address the other speakers by name.'
    ),
    'panel': (
        'A panel: each speaker gives an opening statement on the topic before '
        'the floor opens.'
    ),
    'trial': (
        'A trial: the speakers argue for and against before the crowd, which '
        'acts as the jury.'
    ),
    'assembly': (
        'An assembly, like the Athenian Ekklesia: the speakers argue a motion '
        'that the crowd will have to vote on.'
    ),
}

SYSTEM_PROMPT = """You are the Oracle of Parthenon, a dramaturg who stages gatherings for a multi-agent social simulation. A user has set a stage: speakers who will address a crowd about a topic, in an era and a setting. After the gathering, every speaker and every member of the crowd becomes an agent in a simulation where the crowd argues for days on a Twitter-like feed (the Agora) and a Reddit-like forum (the Stoa). Your drafts become the seed text for that simulation, so be concrete, vivid and specific.

Draft ONLY the parts listed in "parts_to_fill". Everything else on the stage is context: leave it alone.

Rules:
1. Opening words ("words"): for each speaker named in "speakers_needing_words", write 180-320 words of opening speech in the first person, in that speaker's own voice, using their role, ideas and voice notes. If the speaker is a real historical figure, stay faithful to their documented ideas and apply them to this topic and this era; a figure transported to the present may marvel, object or ask pointed questions, but argues from what they actually believed. Imagined speech must never be presented as historical quotation: do not invent "famous quotes", do not attribute fabricated lines to real works, and do not claim the figure once said something they did not. Speakers who already have words wrote them themselves: treat those words as context, answer them where it is natural, and never rewrite, extend or repeat them. Write plain paragraphs separated by a blank line; **bold** and *italic* are allowed sparingly; no headings, lists, links, tables or block quotes.
2. Audience ("audience"): add new members so the crowd totals 10-14 distinct named individuals or groups ("audience_to_add" says how many to add). Use fictional names only: no real living people and no real companies. Each description, in one or two sentences, gives the member's role, their stake in the topic and their initial stance. Balance the crowd between allies of the speakers, opponents, the undecided and the people most affected. Never repeat an existing member or a speaker.
3. Question ("question"): exactly two sentences asking how the crowd's opinion and behaviour evolve over the days after the gathering, and what they finally decide or do.
4. Title ("title"): at most 8 words, no quotation marks.
5. What happens next ("happensNext"): 2-3 sentences describing a concrete upcoming trigger (a vote, a deadline, a launch, a ruling, a leak) that will test the crowd's opinions in the days after the gathering.

Output one JSON object and nothing else, with exactly these keys:
{"title": string or null, "speakers": [{"name": string, "words": string}], "audience": [{"name": string, "description": string}], "question": string or null, "happensNext": string or null}
Use null, or an empty list, for every part not listed in "parts_to_fill". In "speakers", copy each speaker's name exactly as given."""


class StageValidationError(ValueError):
    """The stage or the fill request is invalid; safe to show to the user."""


class OracleUnavailableError(RuntimeError):
    """The LLM client could not be created (for example, no API key)."""


# ---------------------------------------------------------------- helpers

def _text(value: Any, limit: int) -> str:
    """Coerce a JSON value to a stripped, length-capped string."""

    if value is None or isinstance(value, bool):
        return ''
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return ''
    value = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if len(value) > limit:
        value = value[:limit].rstrip()
    return value


def _one_line(value: Any, limit: int) -> str:
    """Like _text, but collapses all whitespace (names, titles, roles)."""

    return _text(re.sub(r'\s+', ' ', value) if isinstance(value, str) else value, limit)


def _key(name: str) -> str:
    return re.sub(r'\s+', ' ', name).strip().casefold()


def _strip_wrapping_quotes(value: str) -> str:
    pairs = (('"', '"'), ('“', '”'), ("'", "'"), ('‘', '’'))
    for left, right in pairs:
        if len(value) >= 2 and value.startswith(left) and value.endswith(right):
            inner = value[1:-1].strip()
            # Only unwrap when the quotes enclose the whole text.
            if left not in inner and right not in inner:
                return inner
    return value


def _clean_prose(value: str) -> str:
    """Keep model prose inside the seed renderer's small Markdown subset."""

    lines = []
    for line in value.split('\n'):
        line = re.sub(r'^\s{0,3}#{1,6}\s+', '', line)   # headings
        line = re.sub(r'^\s{0,3}>\s?', '', line)        # block quotes
        lines.append(line.rstrip())
    cleaned = '\n'.join(lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return _strip_wrapping_quotes(cleaned.strip())


# ---------------------------------------------------------- normalisation

def normalize_stage(raw: Any) -> Dict[str, Any]:
    """Validate and normalise the builder's stage.

    Raises StageValidationError (a ValueError) with a user-facing message.
    """

    if not isinstance(raw, dict):
        raise StageValidationError('The stage must be a JSON object.')

    fmt = _one_line(raw.get('format'), 20).lower()
    era = _one_line(raw.get('era'), 20).lower()

    speakers: List[Dict[str, str]] = []
    seen_speakers = set()
    raw_speakers = raw.get('speakers')
    for item in raw_speakers if isinstance(raw_speakers, list) else []:
        if not isinstance(item, dict):
            continue
        name = _one_line(item.get('name'), LIMITS['speaker_name'])
        if not name or _key(name) in seen_speakers:
            continue
        seen_speakers.add(_key(name))
        speakers.append({
            'name': name,
            'role': _one_line(item.get('role'), LIMITS['role']),
            'ideas': _text(item.get('ideas'), LIMITS['ideas']),
            'voice': _one_line(item.get('voice'), LIMITS['voice']),
            'words': _text(item.get('words'), LIMITS['words']),
        })
        if len(speakers) >= MAX_SPEAKERS:
            break

    audience: List[Dict[str, str]] = []
    seen_audience = set()
    raw_audience = raw.get('audience')
    for item in raw_audience if isinstance(raw_audience, list) else []:
        if not isinstance(item, dict):
            continue
        name = _one_line(item.get('name'), LIMITS['audience_name'])
        if not name or _key(name) in seen_audience:
            continue
        seen_audience.add(_key(name))
        audience.append({
            'name': name,
            'description': _text(
                item.get('description'), LIMITS['audience_description']
            ),
        })
        if len(audience) >= MAX_AUDIENCE:
            break

    happens_next = raw.get('happensNext')
    if happens_next is None:
        happens_next = raw.get('happenNext', raw.get('happens_next'))

    stage = {
        'title': _one_line(raw.get('title'), LIMITS['title']),
        'format': fmt if fmt in FORMATS else DEFAULT_FORMAT,
        'era': era if era in ERAS else DEFAULT_ERA,
        'setting': _one_line(raw.get('setting'), LIMITS['setting']),
        'topic': _text(raw.get('topic'), LIMITS['topic']),
        'speakers': speakers,
        'audience': audience,
        'question': _text(raw.get('question'), LIMITS['question']),
        'happensNext': _text(happens_next, LIMITS['happensNext']),
    }

    if not speakers:
        raise StageValidationError(
            'Add at least one named speaker to the stage.'
        )
    if not stage['topic'] and not stage['question']:
        raise StageValidationError(
            'Describe the topic or the question the stage is about.'
        )
    return stage


def resolve_fill(stage: Dict[str, Any], fill: Any) -> List[str]:
    """Decide which parts to draft, in canonical order.

    ``fill`` None (or an empty list) means every part that is currently
    empty. Requested words only ever cover speakers without words.
    """

    needs_words = any(not s['words'] for s in stage['speakers'])
    audience_room = len(stage['audience']) < MAX_AUDIENCE

    if fill is None or fill == '' or (isinstance(fill, (list, tuple)) and not fill):
        requested = set()
        if needs_words:
            requested.add('words')
        if len(stage['audience']) < AUDIENCE_DEFAULT_FILL_BELOW:
            requested.add('audience')
        for part in ('question', 'title', 'happensNext'):
            if not stage[part]:
                requested.add(part)
    else:
        if isinstance(fill, str):
            fill = [fill]
        if not isinstance(fill, (list, tuple)):
            raise StageValidationError(
                'fill must be a list of parts to draft: '
                + ', '.join(FILL_PARTS) + '.'
            )
        requested = set()
        for part in fill:
            if not isinstance(part, str) or part.strip() not in FILL_PARTS:
                raise StageValidationError(
                    f'Unknown part to draft: {str(part)[:40]!r}. '
                    'Choose from ' + ', '.join(FILL_PARTS) + '.'
                )
            requested.add(part.strip())
        # Explicit requests still never overwrite user-written words, and
        # the crowd cannot grow past its cap.
        if not needs_words:
            requested.discard('words')
        if not audience_room:
            requested.discard('audience')

    parts = [part for part in FILL_PARTS if part in requested]
    if not parts:
        raise StageValidationError(
            'Nothing left for the Oracle to draft: every requested part is '
            'already written.'
        )
    return parts


# ---------------------------------------------------------------- prompt

def _audience_to_add(existing: int) -> Dict[str, int]:
    room = MAX_AUDIENCE - existing
    low = max(1, AUDIENCE_TARGET_MIN - existing)
    high = max(low, AUDIENCE_TARGET_MAX - existing)
    if existing >= AUDIENCE_TARGET_MAX:
        low, high = 1, 4
    return {
        'existing': existing,
        'min': min(low, room),
        'max': min(high, room),
    }


def build_messages(stage: Dict[str, Any], parts: List[str]) -> List[Dict[str, str]]:
    request: Dict[str, Any] = {
        'parts_to_fill': parts,
        'era_note': ERA_NOTES[stage['era']],
        'format_note': FORMAT_NOTES[stage['format']],
    }
    if 'words' in parts:
        request['speakers_needing_words'] = [
            s['name'] for s in stage['speakers'] if not s['words']
        ]
        written = [s['name'] for s in stage['speakers'] if s['words']]
        if written:
            request['speakers_with_their_own_words'] = written
    if 'audience' in parts:
        request['audience_to_add'] = _audience_to_add(len(stage['audience']))

    user_message = (
        'The stage, as the user set it:\n'
        + json.dumps(stage, ensure_ascii=False, indent=2)
        + '\n\nWhat to draft:\n'
        + json.dumps(request, ensure_ascii=False, indent=2)
        + '\n\nReturn the JSON object only.'
    )
    system_message = SYSTEM_PROMPT + '\n\n' + get_language_instruction()
    return [
        {'role': 'system', 'content': system_message},
        {'role': 'user', 'content': user_message},
    ]


# ---------------------------------------------------------------- parsing

def _items(value: Any, value_key: str) -> Iterable[Dict[str, Any]]:
    """Yield dict items from a list, or from a {name: value} mapping."""

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item
    elif isinstance(value, dict):
        for name, content in value.items():
            yield {'name': name, value_key: content}


def parse_draft(
    raw: Any, stage: Dict[str, Any], parts: List[str]
) -> Dict[str, Any]:
    """Keep only the requested, well-formed parts of the model's answer."""

    if not isinstance(raw, dict):
        raise LLMResponseError('The Oracle did not answer with a JSON object')

    result: Dict[str, Any] = {
        'title': None,
        'speakers': [],
        'audience': [],
        'question': None,
        'happensNext': None,
        'filled': [],
    }

    if 'title' in parts:
        title = _strip_wrapping_quotes(_one_line(raw.get('title'), LIMITS['title']))
        if title:
            result['title'] = title

    if 'words' in parts:
        needing = {
            _key(s['name']): s['name'] for s in stage['speakers'] if not s['words']
        }
        drafted: Dict[str, str] = {}
        for item in _items(raw.get('speakers'), 'words'):
            name = item.get('name')
            if not isinstance(name, str):
                continue
            canonical = needing.get(_key(name))
            if canonical is None or canonical in drafted:
                continue  # unknown speaker, user-written words, or duplicate
            words = _clean_prose(_text(item.get('words'), LIMITS['words']))
            if words:
                drafted[canonical] = words
        result['speakers'] = [
            {'name': s['name'], 'words': drafted[s['name']]}
            for s in stage['speakers']
            if s['name'] in drafted
        ]

    if 'audience' in parts:
        taken = {_key(m['name']) for m in stage['audience']}
        taken.update(_key(s['name']) for s in stage['speakers'])
        room = MAX_AUDIENCE - len(stage['audience'])
        added: List[Dict[str, str]] = []
        for item in _items(raw.get('audience'), 'description'):
            if len(added) >= room:
                break
            name = _one_line(item.get('name'), LIMITS['audience_name'])
            description = _one_line(
                item.get('description'), LIMITS['audience_description']
            )
            if not name or not description or _key(name) in taken:
                continue
            taken.add(_key(name))
            added.append({'name': name, 'description': description})
        result['audience'] = added

    if 'question' in parts:
        question = _clean_prose(_text(raw.get('question'), LIMITS['question']))
        if question:
            result['question'] = question

    if 'happensNext' in parts:
        value = raw.get('happensNext')
        if value is None:
            value = raw.get('happens_next')
        happens_next = _clean_prose(_text(value, LIMITS['happensNext']))
        if happens_next:
            result['happensNext'] = happens_next

    present = {
        'words': bool(result['speakers']),
        'audience': bool(result['audience']),
        'question': result['question'] is not None,
        'title': result['title'] is not None,
        'happensNext': result['happensNext'] is not None,
    }
    result['filled'] = [part for part in parts if present[part]]
    if not result['filled']:
        raise LLMResponseError(
            "The Oracle's answer contained none of the requested parts"
        )
    return result


# ---------------------------------------------------------------- service

class StageOracle:
    """Drafts custom stages with the configured LLM."""

    def __init__(self, llm_client: Optional[Any] = None):
        self._llm = llm_client

    @property
    def llm(self):
        if self._llm is None:
            try:
                self._llm = LLMClient()
            except ValueError as error:
                raise OracleUnavailableError(
                    'The Oracle is silent: no LLM is configured on the server.'
                ) from error
        return self._llm

    def draft(self, stage: Any, fill: Optional[List[str]] = None) -> Dict[str, Any]:
        normalized = normalize_stage(stage)
        parts = resolve_fill(normalized, fill)
        logger.info(
            'Oracle drafting stage: format=%s era=%s speakers=%d audience=%d parts=%s',
            normalized['format'],
            normalized['era'],
            len(normalized['speakers']),
            len(normalized['audience']),
            ','.join(parts),
        )
        messages = build_messages(normalized, parts)
        raw = self.llm.chat_json(
            messages,
            temperature=0.8,
            max_tokens=6000,
            max_attempts=2,
        )
        draft = parse_draft(raw, normalized, parts)
        logger.info('Oracle drafted parts: %s', ','.join(draft['filled']))
        return draft
