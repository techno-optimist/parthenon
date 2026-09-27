"""
What a model hands back, checked before a visitor reads it.

Small models (the free ones the public steps run on) sometimes answer with
their own machinery instead of words: a tool call in their native markup
(`<|tool_call_start|>[panorama_search(query=...)]<|tool_call_end|>`,
`<function=...><parameter=...>`), their planning ("I'll structure it
something like..."), or text that has fallen apart into a soup of fragments
("C C C They C C ... dom dom gira ña"). The Scribe's chapters and answers
pass through here: markup is stripped, and a text that still has one of
these problems is named, so the caller can ask once more or say the
fallback line instead of saving or showing it.

Everything here is pure (no model, no files).
"""

import ast
import re
from typing import Any, Dict, List, Optional

# ------------------------------------------------------------------ tool-call markup

# LFM (Liquid) and similar: <|tool_call_start|>[name(arg='v'), ...]<|tool_call_end|>
_SPECIAL_CALL = re.compile(
    r'<\|tool_?call_?start\|>\s*(.*?)\s*(?:<\|tool_?call_?end\|>|$)', re.S | re.I
)
# Qwen coder style: <function=name><parameter=key>value</parameter></function>
_FUNCTION_BLOCK = re.compile(r'<function=([A-Za-z_][\w-]*)>(.*?)(?:</function>|$)', re.S)
_PARAMETER = re.compile(r'<parameter=([A-Za-z_][\w-]*)>\s*(.*?)\s*</parameter>', re.S)
_TOOL_CALL_BLOCK = re.compile(r'<tool_call>.*?(?:</tool_call>|$)', re.S | re.I)
_TOOL_CALL_TAG = re.compile(r'</?tool_call>', re.I)
_BRACKET_TOOL_CALL = re.compile(r'\[TOOL_CALLS?\].*?(?:\)|\]|$)', re.S)
# Any leftover special token: <|...|> (tool_call_end, im_start, eot_id, python_tag ...)
_SPECIAL_TOKEN = re.compile(r'<\|[^<>|\n]{1,40}\|>')
_FUNCTION_TAGS = re.compile(r'</?(?:function|parameter)(?:=[^>\n]*)?>')

# A search named as a call in the text: the model meant to search, not to answer.
TOOL_NAMES = (
    'panorama_search', 'quick_search', 'insight_forge', 'interview_agents', 'interview_citizens',
)
_BARE_CALL = re.compile(
    r'\b(?:' + '|'.join(name.replace('_', '_?') for name in TOOL_NAMES) + r')\s*\(', re.I
)
_MARKERS = re.compile(
    r'<\|tool_?call|<tool_call|</tool_call>|<function=|<parameter=|\[TOOL_CALLS?\]|<\|[a-z_]{2,30}\|>',
    re.I,
)


def pythonic_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Calls written as <|tool_call_start|>[name(key='value'), ...]<|tool_call_end|>, parsed without eval."""

    calls: List[Dict[str, Any]] = []
    for match in _SPECIAL_CALL.finditer(text or ''):
        body = match.group(1).strip()
        if not body:
            continue
        if not body.startswith('['):
            body = f'[{body}]'
        try:
            tree = ast.parse(body, mode='eval')
        except (SyntaxError, ValueError):
            continue
        items = tree.body.elts if isinstance(tree.body, (ast.List, ast.Tuple)) else []
        for item in items:
            if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Name):
                continue
            parameters: Dict[str, Any] = {}
            for keyword in item.keywords:
                if keyword.arg is None:
                    continue
                try:
                    parameters[keyword.arg] = ast.literal_eval(keyword.value)
                except (ValueError, SyntaxError, TypeError):
                    continue
            if not parameters and item.args:
                try:
                    parameters['query'] = ast.literal_eval(item.args[0])
                except (ValueError, SyntaxError, TypeError):
                    pass
            calls.append({'name': item.func.id, 'parameters': parameters})
    return calls


def function_tag_calls(text: str) -> List[Dict[str, Any]]:
    """Calls written as <function=name><parameter=key>value</parameter></function>."""

    calls: List[Dict[str, Any]] = []
    for match in _FUNCTION_BLOCK.finditer(text or ''):
        parameters: Dict[str, Any] = {}
        for key, value in _PARAMETER.findall(match.group(2)):
            value = value.strip()
            if re.fullmatch(r'-?\d{1,9}', value):
                parameters[key] = int(value)
            else:
                parameters[key] = value
        calls.append({'name': match.group(1), 'parameters': parameters})
    return calls


def strip_markup(text: str) -> str:
    """The text without tool-call blocks, special tokens or function tags."""

    if not text:
        return text or ''
    cleaned = _SPECIAL_CALL.sub('', text)
    cleaned = _TOOL_CALL_BLOCK.sub('', cleaned)
    cleaned = _FUNCTION_BLOCK.sub('', cleaned)
    cleaned = _BRACKET_TOOL_CALL.sub('', cleaned)
    cleaned = _SPECIAL_TOKEN.sub('', cleaned)
    cleaned = _FUNCTION_TAGS.sub('', cleaned)
    cleaned = _TOOL_CALL_TAG.sub('', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


# ------------------------------------------------------------------ leaked planning

# Said about the chapter or the answer rather than in it. Checked in the
# opening of a text (and a few anywhere: they are never part of a chapter).
_WORK = (
    r'(?:write|structure|start|begin|compose|draft|search|use|check|list|look|find|call|gather'
    r'|review|consult|query|quote|include|make sure|think|plan|outline|search for)\b'
)
_PLANNING_OPENING = re.compile(
    r'^\s*["\'“”]?\s*(?:then the (?:chapter|answer)\b'
    r'|(?:okay|ok|alright)[,.]?\s+(?:so\s+)?(?:i|let me|let\'s)\b'
    r'|let me (?:now |first )?' + _WORK + r'|let\'s (?:now |first )?' + _WORK
    + r'|i will (?:now |first )?' + _WORK + r'|i\'ll (?:now |first )?' + _WORK
    + r'|(?:i|we) (?:need|have|want) to ' + _WORK + r'|i should ' + _WORK
    + r'|the user\b|my plan\b|thought\s*:|action\s*:|observation\s*:|user safety\s*:|safety\s*:)',
    re.I,
)
_PLANNING_ANYWHERE = re.compile(
    r'(?:I\'ll structure it|I will structure it|Let\'s list the quotes|I need to make sure the quotes'
    r'|I now have enough (?:material|information)|Let me compose it|Final Answer\s*:'
    r'|\bthe user (?:wants|asked|asks|is asking)\b|User Safety\s*:)',
    re.I,
)


def leaked_planning(text: str) -> bool:
    opening = (text or '')[:400]
    return bool(_PLANNING_OPENING.search(opening) or _PLANNING_ANYWHERE.search(text or ''))


# ------------------------------------------------------------------ text that fell apart

# The commonest short words of the city's written languages (Latin script):
# prose is thick with them; a soup of fragments is not.
_COMMON_WORDS = frozenset('''
a about after all also an and any are as at be been before but by can could did do does each even for
from had has have he her him his how i if in into is it its just like made many may me more most much
must my no not now of on one only or other our out over said she should so some such than that the
their them then there these they this those through to too two up upon us very was we were what when
where which while who whom why will with would you your
el la los las de del y en que un una por con para es se lo al su sus como pero más
le les des du et est une pour dans qui pas au aux ce il elle sur par plus ne sont avec
der die das und ist nicht ein eine zu den mit von im sich auf dem für als auch es
o os da do das dos em um uma não para com por mais
'''.split())
# Measured on the Chronicles written so far (1,564 windows of 60 words): no
# window of real prose had fewer than 52% distinct words, any bare symbols
# (Markdown's marks aside) or fewer than 25% common words; the soup of
# report_c9d23068fad0 had up to 32% bare symbols and as few as 7% common
# words. The distinct-word floor is low on purpose: a chapter may repeat a
# short sentence, and one token over and over is caught by _repeated_run.
_WINDOW = 60
_MIN_COMMON = 0.12
_MIN_UNIQUE = 0.10
_MAX_BARE = 0.15
# Markdown's own marks are not bare symbols (tables, quotes, rules, bullets).
_MARKDOWN_MARKS = frozenset(('|', '>', '-', '*', '#', '##', '###', '---', '***', '**', '—', '–', '•', '+'))


def _cjk_share(text: str) -> float:
    letters = [ch for ch in text if not ch.isspace()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if '　' <= ch <= '鿿' or '가' <= ch <= '힯') / len(letters)


def _word(token: str) -> str:
    return token.strip('.,;:!?"\'“”‘’()[]{}*_`~<>«»—–-…').lower()


def degenerate(text: str) -> bool:
    """Whether a stretch of the text has fallen apart (a soup of fragments, or one token over and over)."""

    if not text:
        return False
    tokens = text.split()
    if len(tokens) < _WINDOW:
        return _repeated_run(text)
    # Chinese (and Japanese, Korean) prose has few spaces: only its repeats are checked,
    # and any long Latin stretch inside it the same way as Latin prose.
    step = _WINDOW // 2
    for start in range(0, max(1, len(tokens) - _WINDOW + 1), step):
        window = tokens[start:start + _WINDOW]
        joined = ' '.join(window)
        if _cjk_share(joined) > 0.3:
            continue
        words = [_word(token) for token in window]
        unique = len(set(words)) / len(words)
        bare = sum(
            1 for token, word in zip(window, words)
            if token not in _MARKDOWN_MARKS and not any(ch.isalnum() for ch in word)
        ) / len(words)
        common = sum(1 for word in words if word in _COMMON_WORDS) / len(words)
        if unique < _MIN_UNIQUE or bare > _MAX_BARE or common < _MIN_COMMON:
            return True
    return _repeated_run(text)


_REPEAT = re.compile(r'(.{2,40}?)(?:\s*\1){7,}', re.S)


def _repeated_run(text: str) -> bool:
    """A few letters eight times or more in a row ('C C C C ...', '哈哈哈哈...'); a rule of
    '=====' or '* * * *' is not one."""

    return any(any(ch.isalpha() for ch in match.group(1)) for match in _REPEAT.finditer(text or ''))


# ------------------------------------------------------------------ the verdict

def problem(text: str) -> Optional[str]:
    """Why this text cannot be shown ('empty', 'markup', 'planning', 'degenerate'), or None.

    Pass the text after strip_markup(): markup left in it then means a call
    in a form that could not be taken apart.
    """

    if not text or not text.strip():
        return 'empty'
    if _MARKERS.search(text) or _BARE_CALL.search(text):
        return 'markup'
    if leaked_planning(text):
        return 'planning'
    if degenerate(text):
        return 'degenerate'
    return None
