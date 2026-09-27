"""
The city's words for the public steps' refusals, in English or Chinese.

Every limit and access error has the one shape the frontend reads:
{"success": false, "error": "<the city's words>", "code": "...",
"retry_after_seconds"?: n}. The codes: city_full, come_back_tomorrow,
slow_down, too_long, not_yours, not_on_public_steps, invite_needed (403: the
invite word is missing or wrong) and ticket_lost (404: a question's ticket
that expired or was lost with a restart). The language is the request's own: a "lang"
field or query parameter, else Accept-Language, else English. The words
live in locales/*.json under api.public.
"""

from typing import Optional

from flask import jsonify, request

from ..utils import locale as locale_utils


PUBLIC_LANGUAGES = ('en', 'zh')

CITY_FULL = 'city_full'
COME_BACK_TOMORROW = 'come_back_tomorrow'
SLOW_DOWN = 'slow_down'
TOO_LONG = 'too_long'
NOT_YOURS = 'not_yours'
NOT_ON_PUBLIC_STEPS = 'not_on_public_steps'
INVITE_NEEDED = 'invite_needed'
TICKET_LOST = 'ticket_lost'


def _language_of(value) -> Optional[str]:
    code = locale_utils.known_language(value)
    return code if code in PUBLIC_LANGUAGES else None


def request_language() -> str:
    """'en' or 'zh' for this request."""

    try:
        body = request.get_json(silent=True) if request.is_json else None
    except Exception:  # noqa: BLE001 - an unreadable body has no language
        body = None
    candidates = []
    if isinstance(body, dict):
        candidates.append(body.get('lang'))
    candidates.append(request.args.get('lang'))
    # A form body (the scroll's upload) is not parsed for this: Accept-Language says it.
    header = request.headers.get('Accept-Language') or ''
    candidates.extend(part.split(';')[0] for part in header.split(','))
    for candidate in candidates:
        found = _language_of(candidate)
        if found:
            return found
    return 'en'


def header_language(header: Optional[str]) -> str:
    """'en' or 'zh' for an Accept-Language header ('en-US,en;q=0.9' is 'en'); English when it names neither."""

    for part in str(header or '').split(','):
        found = _language_of(part.split(';')[0])
        if found:
            return found
    return 'en'


def settle_request_language() -> None:
    """Read a browser's own Accept-Language as the city's code, for the whole request.

    The backend's t() takes the header as an exact locale code and falls
    back to Chinese, so 'en-US' was answered in Chinese. On the public steps
    the header becomes 'en' or 'zh' before any view reads it (the page itself
    already sends one of the two).
    """

    header = request.headers.get('Accept-Language')
    code = header_language(header)
    if header != code:
        request.environ['HTTP_ACCEPT_LANGUAGE'] = code


def in_other_language(text: str, lang: str) -> bool:
    """Whether a message is plainly not in the visitor's language (Chinese for 'en', no Chinese for 'zh')."""

    if not isinstance(text, str) or not text.strip():
        return False
    chinese = any('\u4e00' <= ch <= '\u9fff' for ch in text)
    if lang == 'zh':
        return not chinese and any(ch.isalpha() for ch in text)
    return chinese


def words(key: str, lang: Optional[str] = None, **kwargs) -> str:
    lang = lang or request_language()
    for code in (lang, 'en'):
        value = locale_utils._translations.get(code, {})
        for part in ('api', 'public', key):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, str):
            for name, filler in kwargs.items():
                value = value.replace('{' + name + '}', str(filler))
            return value
    return key


def refusal(status: int, key: str, code: Optional[str] = None, retry_after: Optional[int] = None,
            extra: Optional[dict] = None, **kwargs):
    """A response in the contract's shape (code left out for a plain not found); sets Retry-After too.

    extra adds fields to the body (an invite refusal says whether the word was
    missing or wrong); the keyword arguments fill the words.
    """

    body = {'success': False, 'error': words(key, **kwargs)}
    if code:
        body['code'] = code
    if retry_after is not None:
        body['retry_after_seconds'] = int(retry_after)
    for name, value in (extra or {}).items():
        body.setdefault(name, value)
    response = jsonify(body)
    response.status_code = status
    if retry_after is not None:
        response.headers['Retry-After'] = str(int(retry_after))
    return response
