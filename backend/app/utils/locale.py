"""
The city's reading languages: English (the default everywhere) and Chinese.

A request reads in its Accept-Language ('en-US,en;q=0.9' is 'en'); a
background thread reads in the locale its launcher set with set_locale();
anything else reads in English. Nothing falls back to Chinese.
"""

import json
import os
import threading
from typing import Optional

from flask import request, has_request_context

DEFAULT_LOCALE = 'en'
READING_LANGUAGES = ('en', 'zh')

_thread_local = threading.local()

_locales_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'locales')

# Load language registry
with open(os.path.join(_locales_dir, 'languages.json'), 'r', encoding='utf-8') as f:
    _languages = json.load(f)

# Load translation files
_translations = {}
for filename in os.listdir(_locales_dir):
    if filename.endswith('.json') and filename != 'languages.json':
        locale_name = filename[:-5]
        with open(os.path.join(_locales_dir, filename), 'r', encoding='utf-8') as f:
            _translations[locale_name] = json.load(f)


def _reading_language(value) -> Optional[str]:
    """'en' or 'zh' for one language tag ('EN', 'en-US', 'zh_CN', 'zh-Hans', 'zh-TW'), else None."""

    code = str(value or '').split(';')[0].strip().lower().replace('_', '-').split('-')[0]
    return code if code in READING_LANGUAGES else None


def normalize_lang(value, default: Optional[str] = DEFAULT_LOCALE) -> Optional[str]:
    """'en' or 'zh' for a language code or a whole Accept-Language header; default for anything else.

    'en-US,en;q=0.9' is 'en' (the first tag that names a reading language
    wins); 'fr', '' and None are the default.
    """

    for part in str(value or '').split(','):
        found = _reading_language(part)
        if found:
            return found
    return default


def set_locale(locale: str):
    """Set locale for current thread. Call at the start of background threads."""
    _thread_local.locale = normalize_lang(locale)


def _thread_locale() -> Optional[str]:
    return getattr(_thread_local, 'locale', None)


def get_locale() -> str:
    """The reading language here: a request's Accept-Language, else this thread's locale, else English."""

    if has_request_context():
        header = request.headers.get('Accept-Language')
        if header and header.strip():
            return normalize_lang(header)
    return _thread_locale() or DEFAULT_LOCALE


def _lookup(locale: str, key: str):
    value = _translations.get(locale, {})
    for part in key.split('.'):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value if isinstance(value, str) else None


def t(key: str, locale: Optional[str] = None, **kwargs) -> str:
    """The words for key in locale (else this request's or thread's), then English, then Chinese, then the key."""

    wanted = normalize_lang(locale) if locale else get_locale()
    value = None
    for code in (wanted, DEFAULT_LOCALE, 'zh'):
        value = _lookup(code, key)
        if value is not None:
            break

    if value is None:
        return key

    if kwargs:
        for k, v in kwargs.items():
            value = value.replace(f'{{{k}}}', str(v))

    return value


def get_language_instruction() -> str:
    return language_instruction_for(get_locale())


def known_language(value) -> 'str | None':
    """The language code a value names ('en', 'zh-CN' -> 'zh'), or None when the city has no such language."""
    code = str(value or '').strip().lower().replace('_', '-').split('-')[0]
    return code if code in _languages else None


def language_instruction_for(code: str) -> str:
    """The model's language instruction for a reading language ('zh-CN' is Chinese; anything else English)."""
    return _languages[normalize_lang(code)]['llmInstruction']
