"""
The last line against a record in the wrong language.

Each gathering has one record language, fixed when its project is created
(Project.language): everything written into the record is written in it.
record_language() reads it. ensure_language() is the guard every reader-facing
model output passes before it is saved or returned: for a target that is not
Chinese, the lines that still carry Han characters or full-width CJK
punctuation are translated (one translate-only call for all of them), and a
quotation is translated like any other line, since a quote in another
language is not one the reader can read. When that call fails the foreign
spans are removed instead, so an English reader is never handed Chinese. A
Chinese target is never touched.

Translations are kept in this process for text of the same kind (the
caller's context) and only from calls that came back clean. A caller that
shows what it would write and writes it later keeps its own memo of the
translations it showed (ensure_language_many's memo).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import unicodedata
from collections import OrderedDict
from typing import Any, Iterable, List, Optional, Tuple

from ..utils.locale import language_instruction_for, normalize_lang

logger = logging.getLogger('mirofish.language_guard')

RECORD_LANGUAGE_ENV = 'PARTHENON_RECORD_LANGUAGE'
TRANSLATE_MODEL_ENV = 'PARTHENON_TRANSLATE_MODEL'

# Han ideographs: the unified block and extension A, the compatibility block,
# the radicals, and the supplementary planes' extensions.
HAN_RE = re.compile(
    '[⺀-⻿⼀-⿟㐀-䶿一-鿿豈-﫿\U00020000-\U0002fa1f]'
)
# CJK punctuation and full-width forms: 、。「」『』【】《》 and the ideographic
# space; ，：；！？（）～ and the full-width letters and digits; the vertical
# and small forms.
CJK_PUNCT_RE = re.compile('[　-〿︐-︙︰-﹯！-･￠-￮]')

LANGUAGE_NAMES = {'en': 'English', 'zh': 'Simplified Chinese'}

# A batch longer than this goes to the model in parts (a very long answer is
# cut short, and then every line of it would be lost to the fallback).
MAX_LINES_PER_CALL = 80
MAX_CHARS_PER_CALL = 12000

# Translations kept in this process, by (language, context, line): a line's
# translation is served again only to text of the same kind, and only when the
# whole call it came back from was clean (see _translate).
_CACHE_SIZE = 4096
_cache: 'OrderedDict[Tuple[str, str, str], str]' = OrderedDict()
_cache_lock = threading.Lock()


# ---------------------------------------------------------------- the checks

def foreign_script(text, lang) -> bool:
    """Whether text carries script its reader cannot read: Han or full-width CJK punctuation, for any
    target but Chinese. A Chinese target is never foreign."""

    if not isinstance(text, str) or not text:
        return False
    if normalize_lang(lang) == 'zh':
        return False
    return bool(HAN_RE.search(text) or CJK_PUNCT_RE.search(text))


def guess_language(text) -> str:
    """'zh' when text reads as Chinese, else 'en'.

    Each Han character and each full-width CJK mark counts against each word
    in another script (a run of letters, however long): Chinese carries its
    brand and technical names in Latin letters ('Apple 和 Microsoft 谁会赢得
    AI 竞赛？' is Chinese), and English carries a Chinese name or phrase in Han
    ('Will 苏格拉底 flee Athens?' is English). Chinese wins only on more,
    and only with a Han character in it.
    """

    if not isinstance(text, str):
        return 'en'
    han = marks = words = 0
    in_word = False
    for ch in text:
        if HAN_RE.match(ch):
            han += 1
            in_word = False
        elif CJK_PUNCT_RE.match(ch):
            marks += 1
            in_word = False
        elif ch.isalpha():
            if not in_word:
                words += 1
            in_word = True
        else:
            # An apostrophe, hyphen or digit inside a word keeps it one word ("don't", "GPT-4o").
            in_word = in_word and (ch in "'’-" or ch.isdigit())
    return 'zh' if han and han + marks > words else 'en'


def configured_record_language() -> Optional[str]:
    """PARTHENON_RECORD_LANGUAGE as 'en' or 'zh', or None when it is unset or names neither."""

    return normalize_lang(os.environ.get(RECORD_LANGUAGE_ENV), default=None)


# ---------------------------------------------------------------- the record's language

_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


def _usable_id(value) -> Optional[str]:
    value = str(value or '').strip()
    return value if _ID_RE.match(value) else None


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _report_record(report_id: str) -> Optional[dict]:
    from .report_agent import ReportManager

    data = _read_json(ReportManager._get_report_path(report_id))
    if data is None:  # the older layout: reports/<id>.json
        data = _read_json(os.path.join(ReportManager.REPORTS_DIR, f'{report_id}.json'))
    return data


def _simulation_record(simulation_id: str) -> Optional[dict]:
    from .simulation_manager import SimulationManager

    # Read directly: the manager's own loader makes the folder of an ID it is asked about.
    return _read_json(os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id, 'state.json'))


def _gathering_records(project_id=None, simulation_id=None, report_id=None):
    """(project or None, requirement or None) for the most specific ID given, following report -> simulation -> project."""

    from ..models.project import ProjectManager

    requirement = None
    project_id = _usable_id(project_id)
    simulation_id = _usable_id(simulation_id)
    report_id = _usable_id(report_id)
    if not project_id and not simulation_id and report_id:
        report = _report_record(report_id) or {}
        simulation_id = _usable_id(report.get('simulation_id'))
        if isinstance(report.get('simulation_requirement'), str):
            requirement = report['simulation_requirement']
    if not project_id and simulation_id:
        project_id = _usable_id((_simulation_record(simulation_id) or {}).get('project_id'))
    project = ProjectManager.get_project(project_id) if project_id else None
    if project is not None and isinstance(project.simulation_requirement, str) and requirement is None:
        requirement = project.simulation_requirement
    return project, requirement


def record_language(*, project_id=None, simulation_id=None, report_id=None, requirement=None) -> str:
    """The language a gathering's record is written in: 'en' or 'zh'. Never raises.

    PARTHENON_RECORD_LANGUAGE when it names one (the public steps write
    English), else the language stored on the gathering's project (a report
    leads to its simulation, a simulation to its project), else a guess from
    the requirement's text (given, or the one on record) for a project older
    than the stored language, else English.
    """

    return record_language_source(
        project_id=project_id, simulation_id=simulation_id, report_id=report_id, requirement=requirement,
    )[0]


def record_language_source(*, project_id=None, simulation_id=None, report_id=None, requirement=None) -> Tuple[str, str]:
    """(record_language, how it was found): 'configured', 'stored', 'guessed' or 'default'. Never raises.

    A caller that would rewrite a record can tell a language the gathering
    keeps from one only guessed for a gathering older than it.
    """

    configured = configured_record_language()
    if configured:
        return configured, 'configured'
    stored_requirement = None
    try:
        if project_id or simulation_id or report_id:
            project, stored_requirement = _gathering_records(project_id, simulation_id, report_id)
            stored = normalize_lang(getattr(project, 'language', None), default=None)
            if stored:
                return stored, 'stored'
    except Exception as error:  # noqa: BLE001 - an unreadable record reads as unknown
        logger.warning('Could not read the record language: %s', type(error).__name__)
    text = requirement if isinstance(requirement, str) and requirement.strip() else stored_requirement
    if isinstance(text, str) and text.strip():
        return guess_language(text), 'guessed'
    return 'en', 'default'


# ---------------------------------------------------------------- punctuation

# A mark that closes: no space before it, one after it before a word. The
# two-em dash stands for Chinese's doubled dash, which reads as a comma.
_CLOSING = {
    '\uff0c': ',', '\u3001': ',', '\uff64': ',', '\u3002': '.', '\uff0e': '.', '\uff61': '.',
    '\uff1a': ':', '\uff1b': ';', '\uff01': '!', '\uff1f': '?', '\u2e3a': ',',
    '\uff09': ')', '\u3011': ']', '\u3015': ')', '\u3017': ']', '\u3019': ']', '\u301b': ']',
    '\uff3d': ']', '\uff5d': '}', '\u300b': '"', '\u3009': '"', '\u300d': '"', '\uff63': '"',
    '\u300f': "'", '\u301e': '"', '\u301f': '"',
}
# A mark that opens: one space before it after a word, none after it.
_OPENING = {
    '\uff08': '(', '\u3010': '[', '\u3014': '(', '\u3016': '[', '\u3018': '[', '\u301a': '[',
    '\uff3b': '[', '\uff5b': '{', '\u300a': '"', '\u3008': '"', '\u300c': '"', '\uff62': '"',
    '\u300e': "'", '\u301d': '"',
}
# Marks that change in place: curly quotes, which are also the apostrophe (so
# they take no spacing), the ellipsis, the ideographic space, the tildes.
_PLAIN = {
    '\u201c': '"', '\u201d': '"', '\u2018': "'", '\u2019': "'", '\u3000': ' ',
    '\u2026': '...', '\uff5e': '~', '\u301c': '~', '\uff65': '-',
}
_NO_SPACE_BEFORE = set(',.:;!?)]}"\'') | {'\n', '\r', '\t', ' ', '\u201d', '\u2019'}
_TIGHT_BETWEEN_DIGITS = {'\uff0c', '\uff1a', '\uff0e'}
# The vertical, small and full-width sign forms: NFKC gives their plain mark.
_COMPAT_FORMS = re.compile('[\ufe10-\ufe19\ufe30-\ufe6f\uffe0-\uffee]')


def to_ascii_punct(text: str) -> str:
    """Chinese and full-width punctuation as ASCII, spaced the way English is set.

    '他说：「好。」' becomes '他说: "好."'; ，。：；！？（）「」『』、【】《》,
    the doubled dash and ellipsis and the full-width letters and digits all
    change; '2，000' and '10：30' stay tight; curly quotes become straight.
    """

    if not isinstance(text, str) or not text:
        return text
    text = _COMPAT_FORMS.sub(lambda m: unicodedata.normalize('NFKC', m.group(0)), text)
    text = text.replace('\u2014\u2014', '\u2e3a').replace('\u2026\u2026', '\u2026')
    out: List[str] = []
    space_due = False  # a closing mark wants a space before the next word
    tight = False  # an opening mark: the spaces right after it go
    just_opened = False
    length = len(text)
    for index, ch in enumerate(text):
        after = text[index + 1] if index + 1 < length else ''
        if tight and ch in ' \t':
            continue
        tight = False
        if space_due:
            space_due = False
            if ch not in _NO_SPACE_BEFORE and ch not in _CLOSING and ch not in _OPENING:
                out.append(' ')
        if ch in _CLOSING:
            plain = _CLOSING[ch]
            before = out[-1] if out else ''
            just_opened = False
            if ch in _TIGHT_BETWEEN_DIGITS and before.isdigit() and after.isdigit():
                out.append(plain)
                continue
            # The spaces before it go, but never a line's own indentation.
            spaces = 0
            while spaces < len(out) and out[-1 - spaces] in (' ', '\t'):
                spaces += 1
            if spaces and spaces < len(out) and out[-1 - spaces] != '\n':
                del out[-spaces:]
            out.append(plain)
            space_due = bool(after)
            continue
        if ch in _OPENING:
            before = out[-1] if out else ''
            if before and not before.isspace() and not just_opened:
                out.append(' ')
            out.append(_OPENING[ch])
            tight = just_opened = True
            continue
        just_opened = False
        if ch in _PLAIN:
            out.append(_PLAIN[ch])
            continue
        if '\uff01' <= ch <= '\uff5e':  # a full-width letter, digit or sign
            out.append(chr(ord(ch) - 0xfee0))
            continue
        out.append(ch)
    return ''.join(out)


# ---------------------------------------------------------------- line anatomy

# A line's markdown lead: indentation, quote marks, bullets, headings, numbers.
_MARKDOWN_LEAD = re.compile(r'^[ \t]*(?:(?:>[ \t]?|[-*+][ \t]+|#{1,6}[ \t]+|\d{1,3}[.)][ \t]+))*')
# A speaker's lead-in after it: '**Crito:**', '**Crito**:' or 'Crito:'.
_SPEAKER_LEAD = re.compile(
    r"^(?:\*\*[^*\n]{1,48}?[:：][ \t]*\*\*[ \t]*"
    r"|\*\*[^*\n]{1,48}?\*\*[ \t]*[:：][ \t]*"
    r"|[A-Z][\w .'’-]{0,40}?:[ \t]+)"
)
_TRAILING_SPACE = re.compile(r'[ \t\r]+$')


def _split_line(line: str) -> Tuple[str, str, str]:
    """(kept lead, body to translate, trailing whitespace) of one line."""

    trail = _TRAILING_SPACE.search(line)
    end = trail.group(0) if trail else ''
    core = line[:len(line) - len(end)] if end else line
    lead = _MARKDOWN_LEAD.match(core).group(0)
    rest = core[len(lead):]
    speaker = _SPEAKER_LEAD.match(rest)
    if speaker and not foreign_script(speaker.group(0), 'en'):
        lead += speaker.group(0)
        rest = rest[len(speaker.group(0)):]
    return lead, rest, end


_FOREIGN_RUN = re.compile(
    '(?:[⺀-⻿⼀-⿟　-〿㐀-䶿一-鿿豈-﫿'
    '︐-︙︰-﹯！-･￠-￮\U00020000-\U0002fa1f…—“”‘’]+)'
)
# A quotation (or a title in 《》) with Han in it: when it cannot be
# translated it goes whole, marks and all, so no quote is left attributed to
# a speaker who never said what remains of it. A single straight quote counts
# only where it cannot be an apostrophe.
_QUOTED = re.compile(
    r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」'
    r'|『[^』\n]*』|《[^》\n]*》|〈[^〉\n]*〉'
    r"|(?<![\w'])'[^'\n]*'(?![\w'])"
)
# A pair of quotes or brackets left with nothing between them.
_EMPTY_PAIRS = re.compile(r'(?:(?<=\s)|^)(?:"\s*"|\'\s*\'|\(\s*\)|\[\s*\]|\{\s*\})(?=\s|$|[,.:;!?])')
_SPACE_RUN = re.compile(r'(?<=\S)[ \t]{2,}(?=\S)')
_SPACE_BEFORE_MARK = re.compile(r'(?<=\S)[ \t]+(?=[,.:;!?)\]])')
# Marks the removed words leave doubled: 'Athena,.' and ', ,' and '(, RMB,)'.
_MARK_BEFORE_STOP = re.compile(r'[,;:]+(?=[ \t]*[.!?)\]])')
_MARKS_REPEATED = re.compile(r'([,;:])(?:[ \t]*[,;:])+')
_MARK_AFTER_OPEN = re.compile(r'(?<=[(\[])[ \t]*[,;:]+[ \t]*')
_MARK_AT_END = re.compile(r'[ \t]*[,;]+$')
_WORD = re.compile(r'[^\W_]+')


def _strip_foreign(body: str) -> str:
    """body without its Han, tidied; '' when nothing worth reading is left.

    A quotation with Han in it goes whole; the other Han runs go with the CJK
    marks and quotes around them. What remains is dropped when it is only a
    fragment of what the line said: a lone word (a name, 'Crito,'), or fewer
    letters than the Han characters taken out of it; a line with a figure in
    it keeps it. A table row keeps its cells, so its table keeps its shape.
    """

    han = len(HAN_RE.findall(body))
    kept = _QUOTED.sub(lambda m: ' ' if HAN_RE.search(m.group(0)) else m.group(0), body)
    kept = _FOREIGN_RUN.sub(lambda m: ' ' if HAN_RE.search(m.group(0)) else m.group(0), kept)
    kept = to_ascii_punct(kept)
    kept = HAN_RE.sub(' ', CJK_PUNCT_RE.sub(' ', kept))
    previous = None
    while previous != kept:
        previous = kept
        kept = _EMPTY_PAIRS.sub('', kept)
    kept = _SPACE_BEFORE_MARK.sub('', _SPACE_RUN.sub(' ', kept)).strip()
    kept = _MARK_AFTER_OPEN.sub('', _MARKS_REPEATED.sub(r'\1', _MARK_BEFORE_STOP.sub('', kept)))
    kept = _MARK_AT_END.sub('', kept)
    if kept.startswith('|'):
        return kept
    kept = re.sub(r'^[,.:;!?\s]+', '', kept)
    if not any(ch.isalnum() for ch in kept):
        return ''
    if han and not any(ch.isdigit() for ch in kept):
        letters = sum(1 for ch in kept if ch.isalpha())
        if len(_WORD.findall(kept)) <= 1 or letters <= han:
            return ''
    return kept


# ---------------------------------------------------------------- the model

def default_translator():
    """The model that translates: PARTHENON_TRANSLATE_MODEL, else the app's own model."""

    from ..utils.llm_client import LLMClient

    return LLMClient(model=os.environ.get(TRANSLATE_MODEL_ENV) or None)


def _cached(lang: str, context: str, body: str) -> Optional[str]:
    key = (lang, context, body)
    with _cache_lock:
        value = _cache.get(key)
        if value is not None:
            _cache.move_to_end(key)
        return value


def _remember(lang: str, context: str, body: str, translation: str) -> None:
    key = (lang, context, body)
    with _cache_lock:
        _cache[key] = translation
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _translate_prompt(lang: str, context: str) -> str:
    name = LANGUAGE_NAMES.get(lang, 'English')
    about = f' The lines come from {context}.' if context else ''
    return (
        f'You translate lines of text into {name}. Translate only: never add, drop, merge, '
        'explain or summarize.' + about + '\n'
        'You receive a JSON object {"lines": [...]}. Answer with one JSON object '
        '{"lines": [...]} holding exactly as many strings, in the same order, each the '
        f'{name} translation of the line at the same place.\n'
        'Keep proper names (a Chinese name in its usual English form), numbers, markdown '
        '(**bold**, *italics*, links) and a speaker\'s lead-in such as "Crito:" at the start '
        f'of a line. Translate quotations too: a quotation must be in {name}, inside '
        f'{name} quotation marks. Use {name} punctuation.\n'
        + language_instruction_for(lang)
    )


def _parse_lines(answer: Any, expected: int) -> Optional[List[Any]]:
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            return None
    if isinstance(answer, dict):
        lines = answer.get('lines')
        if not isinstance(lines, list):
            lists = [value for value in answer.values() if isinstance(value, list)]
            lines = lists[0] if len(lists) == 1 else None
        answer = lines
    if not isinstance(answer, list) or len(answer) != expected:
        return None
    return answer


def _ask(llm, bodies: List[str], lang: str, context: str) -> Optional[List[Any]]:
    messages = [
        {'role': 'system', 'content': _translate_prompt(lang, context)},
        {'role': 'user', 'content': json.dumps({'lines': bodies}, ensure_ascii=False)},
    ]
    if hasattr(llm, 'chat_json'):
        answer = llm.chat_json(messages=messages, temperature=0.0, max_tokens=None)
    else:
        answer = llm.chat(messages=messages, temperature=0.0, max_tokens=None)
    return _parse_lines(answer, len(bodies))


def _parts(bodies: List[str]) -> Iterable[List[str]]:
    part: List[str] = []
    size = 0
    for body in bodies:
        if part and (len(part) >= MAX_LINES_PER_CALL or size + len(body) > MAX_CHARS_PER_CALL):
            yield part
            part, size = [], 0
        part.append(body)
        size += len(body)
    if part:
        yield part


# A link the line did not have: a translation never adds one.
_LINK_RE = re.compile(r'(?:https?://|www\.)[^\s)\]>"\']+', re.IGNORECASE)
_QUOTE_MARKS = '"\'\u201c\u2018\u300c\u300e\u300a\u3008'


def _suspect(body: str, translated: str) -> bool:
    """Whether translated cannot be a translation of body: far longer, or with a link body has not."""

    if len(translated) > 8 * len(body) + 200:
        return True
    return bool(set(_LINK_RE.findall(translated)) - set(_LINK_RE.findall(body)))


def _faithful(body: str, translated: str) -> bool:
    """Whether translated keeps body's shape well enough to be served again (cached): a sane length,
    the same bold marks, and a quotation still opened as one."""

    if not (len(body) / 4 <= len(translated) <= 5 * len(body) + 40):
        return False
    if body.count('**') != translated.count('**'):
        return False
    opens_quote = body.lstrip()[:1] in _QUOTE_MARKS
    return not opens_quote or translated.lstrip()[:1] in _QUOTE_MARKS


def _translate(bodies: List[str], lang: str, llm, context: str) -> Tuple[dict, set]:
    """({body: its text} for the bodies the model answered usably, the bodies of those only half translated).

    A half-translated line keeps what the reader can read of it ('' when that
    is nothing, and the line goes). A reply that cannot be a translation
    (_suspect) is not used at all. The lines of a call are cached only when
    every one of them came back a clean, faithful translation: a line steered
    by the others in its call is never served to other text.
    """

    done: dict = {}
    partial: set = set()
    if not bodies:
        return done, partial
    try:
        llm = llm if llm is not None else default_translator()
    except Exception as error:  # noqa: BLE001 - no model: the fallback takes over
        logger.warning('No model to translate %d line(s) into %s: %s', len(bodies), lang, type(error).__name__)
        return done, partial
    for part in _parts(bodies):
        try:
            answer = _ask(llm, part, lang, context)
        except Exception as error:  # noqa: BLE001 - a failed call: the fallback takes over
            logger.warning(
                'Translating %d line(s) into %s failed: %s', len(part), lang, type(error).__name__
            )
            continue
        if answer is None:
            logger.warning('The translation of %d line(s) into %s was unusable', len(part), lang)
            continue
        clean = []
        for body, translated in zip(part, answer):
            if not isinstance(translated, str) or not translated.strip():
                clean = None
                continue
            translated = _finish(translated.strip(), lang)
            if _suspect(body, translated):
                logger.warning('A translation into %s did not read as one; it was not used', lang)
                clean = None
                continue
            if foreign_script(translated, lang):
                # Partly translated: keep what the reader can read ('' drops the line).
                clean = None
                translated = _strip_foreign(translated)
                partial.add(body)
            elif clean is not None:
                if _faithful(body, translated):
                    clean.append((body, translated))
                else:
                    clean = None
            done[body] = translated
        for body, translated in clean or ():
            _remember(lang, context, body, translated)
    return done, partial


def _finish(text: str, lang: str) -> str:
    return to_ascii_punct(text) if lang == 'en' else text


# ---------------------------------------------------------------- the guard

def ensure_language_many(texts, lang, *, llm=None, context: str = '', memo=None, untranslated=None) -> List[Any]:
    """Every text in lang, with one translate-only call for all their foreign lines (see ensure_language).

    A text that is not a string, or has nothing foreign in it, comes back as it was.

    memo: a dict the caller keeps, {lang: {line: its text}}. Read before the
    process cache and the model, and filled with every line this call puts
    in lang (from the model or the cache): a caller that shows what it would
    write and writes it later hands the same memo back and gets the same
    text, without another call. A line the guard had to strip because the
    call failed is not put in it, so a later call tries it again.

    untranslated: a list the index of each text is appended to when a line of
    it could not be translated whole and lost its foreign spans instead; a
    caller writing a record can keep its original or try again.
    """

    texts = list(texts or [])
    try:
        return _ensure_many(texts, lang, llm, context, memo, untranslated)
    except Exception as error:  # noqa: BLE001 - the guard never fails its caller
        logger.warning('The language guard failed (%s); removing foreign script instead', type(error).__name__)
        results = [_stripped_text(text, lang) for text in texts]
        if isinstance(untranslated, list):
            untranslated.extend(
                index for index, (text, result) in enumerate(zip(texts, results)) if result is not text
            )
        return results


def ensure_language(text, lang, *, llm=None, context: str = '', memo=None, untranslated=None) -> Any:
    """text in lang: unchanged when nothing in it is foreign, else its foreign lines translated.

    Only the lines carrying Han or full-width CJK punctuation go to the model
    (in one call), each without its markdown lead ('>', '-', '#', '1.') or
    its speaker's lead-in ('**Crito:**', 'Crito:'), which stay as they were;
    names and meaning stay, quotations are translated too, and the
    punctuation becomes English. Translations are cached in this process. A
    failed or unusable call removes the foreign spans instead (a quotation
    with Han in it goes whole, and a line left empty or a mere fragment
    goes). Never raises; a Chinese target is returned untouched. memo and
    untranslated as for ensure_language_many (untranslated gets 0).
    """

    return ensure_language_many(
        [text], lang, llm=llm, context=context, memo=memo, untranslated=untranslated,
    )[0]


def _memo_book(memo, lang: str) -> Optional[dict]:
    if not isinstance(memo, dict):
        return None
    book = memo.setdefault(lang, {})
    return book if isinstance(book, dict) else None


def _ensure_many(texts: List[Any], lang, llm, context: str, memo=None, untranslated=None) -> List[Any]:
    lang = normalize_lang(lang)
    context = context or ''
    book = _memo_book(memo, lang) if any(foreign_script(text, lang) for text in texts) else None
    plans = []  # per text: None (unchanged) or its lines with the foreign ones marked
    wanted: List[str] = []
    known = {}  # body -> its remembered text (the caller's memo, then the cache), held for this batch
    seen = set()
    for text in texts:
        if not foreign_script(text, lang):
            plans.append(None)
            continue
        lines = text.split('\n')
        marked = []
        for index, line in enumerate(lines):
            if not foreign_script(line, lang):
                continue
            if not HAN_RE.search(line):
                tidied = _finish(line, lang)
                if not foreign_script(tidied, lang):
                    lines[index] = tidied
                    continue
            lead, body, end = _split_line(line)
            marked.append((index, lead, body, end))
            if not body or body in seen or body in known:
                continue
            remembered = book.get(body) if book is not None else None
            if not isinstance(remembered, str):
                remembered = _cached(lang, context, body)
            if remembered is not None:
                known[body] = remembered
            else:
                seen.add(body)
                wanted.append(body)
        plans.append((lines, marked))

    translated, partial = _translate(wanted, lang, llm, context) if wanted else ({}, set())
    translated.update(known)
    if book is not None:
        book.update(translated)

    results = []
    for position, (text, plan) in enumerate(zip(texts, plans)):
        if plan is None:
            results.append(text)
            continue
        lines, marked = plan
        dropped = set()
        stripped = 0
        for index, lead, body, end in marked:
            new_body = translated.get(body)
            if new_body is None:
                new_body = _strip_foreign(body)
                stripped += 1
            elif body in partial:
                stripped += 1
            if not new_body:
                dropped.add(index)
                continue
            lines[index] = f'{lead}{new_body}{end}'
        if stripped:
            logger.warning(
                'Removed foreign script from %d line(s) it could not translate into %s%s',
                stripped, lang, f' ({context})' if context else '',
            )
            if isinstance(untranslated, list):
                untranslated.append(position)
        results.append('\n'.join(line for index, line in enumerate(lines) if index not in dropped))
    return results


def _stripped_text(text, lang) -> Any:
    """The fallback for the whole text: every foreign line without its foreign spans."""

    if not foreign_script(text, lang):
        return text
    try:
        kept = []
        for line in text.split('\n'):
            if not foreign_script(line, lang):
                kept.append(line)
                continue
            lead, body, end = _split_line(line)
            body = _strip_foreign(body)
            if body:
                kept.append(f'{lead}{body}{end}')
        return '\n'.join(kept)
    except Exception:  # noqa: BLE001 - the last resort
        return CJK_PUNCT_RE.sub(' ', HAN_RE.sub('', text))
