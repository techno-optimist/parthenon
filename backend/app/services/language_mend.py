"""
Records already written in the wrong language, put right in place.

Before each gathering had one record language (Project.language, see
language_guard), a record was written in whatever language the thread that
wrote it happened to have: the citizens' interview answers quoted in Chinese
in an English Chronicle, a note the backend left at startup, a profile's
country, the rules facts of a Web. scan() finds such strings without the
model and without writing anything; mend() puts them in the record's
language. Nothing else changes, and a record whose language is Chinese is
never touched.

Scopes: 'all'; 'report:<id>', 'simulation:<id>' and 'graph:<graph_id>' (that
record alone); 'project:<id>' (the whole gathering: the project, its crowds,
their Chronicles and its Web).

Per record, only strings with Han characters or full-width CJK punctuation
(language_guard.foreign_script) are mended:
- reports/<id>: meta.json, outline.json, progress.json, full_report.md,
  section_*.md, console_log.txt and agent_log.jsonl (section titles and every
  row's details: the Chronicle and the Symposium read their chapters and
  outline from the log first, and the notes on how the Scribe found each
  chapter from its search topics);
- simulations/<id>: state.json, run_state.json, stances.json,
  simulation_config.json, reddit_profiles.json, twitter_profiles.csv and the
  portraits' records;
- projects/<id>/project.json;
- the local memory store (Config.LOCAL_MEMORY_DB_PATH): a graph's facts, its
  nodes' summaries and its activity episodes.

Left as they are, and named in the summary with the reason: names, ids and
codes the rest of the record joins on; the visitor's own question; a tool's
raw result in the agent log (the page reads only its counts and the citizens'
names from it, and it is the record of what the Scribe read); the film's
text (the film speaks it); the citizens' own posts in a run's recent
actions; the scroll's own text in the memory store.

How: a note the backend wrote from a locale key (a run note, a status) is
written again from that key in the record's language; the rules text of the
memory store (activity facts, hub and account summaries, activity lines) is
rendered again with the engine's own templates (memory.activity); the rest
goes to the model in one translate-only call per record
(language_guard.ensure_language_many), so a line that appears in several
copies gets the same translation in each. A record is written only when every
call for it came back whole (a line for each line sent, none of them still in
the wrong script, nothing the guard had to cut or could not translate) and
none of its files changed while the model was at work; otherwise nothing of
it is written and it is left for the next run.

A record whose language is only a guess (language_guard.record_language_source:
a gathering older than the stored language, guessed from its question or
English for want of one) is mended only when its own text agrees. When what
a reader reads of it (a Chronicle's markdown; a crowd's stances and
profiles; a project's summary and ontology; a Web's facts and summaries
from the model) reads as Chinese, the guess is doubted: nothing of it is
translated or written, and the summary lists it as uncertain. A request
that names it with lang decides:
- its own scope with lang ('en') settles a guess that lang agrees with: it
  is then mended to that language. A lang that differs from the guess is
  refused there, since the rest of its gathering would still be guessed
  the other way;
- 'project:<id>' with lang decides the language of the whole gathering:
  every record of it takes lang in place of the guess, and applying keeps
  lang on its project (project.json 'language', copied first like every
  file it rewrites), so record_language agrees with the records afterwards.
  Its project is mended first; when it could not keep lang (busy, missing,
  changed meanwhile, or its own lines did not come back whole), nothing
  else of the gathering is written under that lang.
lang never changes a language the gathering keeps or the site sets; a
request naming such a record in another language leaves it as it is.

mend() is a dry run unless apply is true: it translates (the translations are
kept in this process, so applying afterwards costs no further calls) and says
what it would write. Applying first copies every file it rewrites to
<upload folder>/_mend_backups/<UTC stamp>/<its path under the upload folder>
(the memory store through SQLite's backup), then replaces each file at once
(write, then rename) and writes a graph's rows in one transaction. A second
run finds nothing left to mend.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..config import Config
from ..utils import locale as locale_utils
from ..utils.json_files import read_json, write_json_atomic
from ..utils.locale import normalize_lang, t
from . import language_guard
from .language_guard import HAN_RE, ensure_language_many, foreign_script, guess_language, record_language_source

logger = logging.getLogger('mirofish.language_mend')

SCOPE_ALL = 'all'
SCOPE_KINDS = ('report', 'simulation', 'project', 'graph')
BACKUP_DIR_NAME = '_mend_backups'

# How much of what changed a summary shows.
PREVIEW_LIMIT = 200
PREVIEW_CHARS = 600
WHERE_LIMIT = 8
# A note the backend wrote from a locale key is short; longer text is prose.
MAX_NOTE_CHARS = 1000
# The locale namespaces the backend writes notes from (t() in app/).
NOTE_NAMESPACES = ('api', 'progress', 'report', 'console', 'scribe', 'common')

_ID_PATTERNS = {
    'report': re.compile(r'report_[A-Za-z0-9_-]{1,120}'),
    'simulation': re.compile(r'sim_[A-Za-z0-9_-]{1,120}'),
    'project': re.compile(r'proj_[A-Za-z0-9_-]{1,120}'),
    'graph': re.compile(r'[A-Za-z0-9_-]{1,160}'),
}

# Why a string is left as it is.
JOINS = 'a name, id or code the rest of the record joins on'
VISITOR = "the question in the visitor's own words"
TOOL_RESULT = (
    "a tool's raw result: the page reads only its counts and the citizens' names from it, "
    "and it is the record of what the Scribe read"
)
FILM = 'the film speaks it: make the film again to change it'
POSTS = "the citizens' own posts, as the square recorded them"
SCROLL = 'the scroll as it was handed in'
ACTIVITY = "the raw activity log: its templates are put in the record's language, never what the citizens wrote"
UNTRANSLATED = 'the model did not translate it whole: nothing of this record was written, run the mend again'
MOVED = 'it changed while it was being mended: nothing of this record was written, run the mend again'
UNREADABLE_ROW = 'a log row that does not read as JSON'
LANGUAGE_UNCERTAIN = (
    'its question reads English (or it has none) but its record was written in Chinese, and its gathering '
    "keeps no language of its own: nothing of it was written; mend it explicitly with scope=<this record> and lang='en', "
    'or decide its whole gathering with scope=project:<id> and lang, which the gathering then keeps'
)
GUESS_KEPT = (
    "its language is only a guess ('{language}'): lang '{lang}' changes a guess only for its whole gathering, "
    'named with scope=project:<id>, which then keeps that language'
)
UNDECIDED = (
    "its gathering could not keep lang '{lang}' (see project:{project_id}): nothing of it was written, "
    'run the mend again'
)

# How a record's language was found (language_guard.record_language_source), and 'explicit' when a
# request that names the record decided it. Only a guess is doubted, and only a guess gives way to lang.
GUESSED_SOURCES = frozenset({'guessed', 'default'})
EXPLICIT = 'explicit'
# The weakest source wins for a Web several gatherings share.
_SOURCE_STRENGTH = {'configured': 3, 'stored': 2, 'guessed': 1, 'default': 0}
_KEPT = {
    'configured': 'PARTHENON_RECORD_LANGUAGE sets its language',
    'stored': 'its gathering keeps its language',
}

# Keys (at any depth) whose strings are names, ids, codes or times: the rest
# of the record joins on them or the code compares them. Never translated.
JOIN_KEYS = frozenset({
    'id', 'uuid', 'report_id', 'simulation_id', 'project_id', 'graph_id', 'task_id', 'entity_uuid',
    'source_node_uuid', 'target_node_uuid', 'user_id', 'agent_id', 'graph_build_task_id',
    'zep_batch_id', 'zep_batch_operation_id', 'owner_token_hash',
    'name', 'username', 'user_name', 'realname', 'agent_name', 'entity_name', 'author', 'author_name',
    'entity_type', 'entity_types', 'poster_type', 'type', 'kind', 'labels', 'source', 'target',
    'source_type', 'target_type', 'platform', 'stance', 'final_stance', 'status', 'runner_status',
    'twitter_status', 'reddit_status', 'stage', 'current_stage', 'action', 'action_type', 'tool_name',
    'voice', 'mbti', 'language', 'created_at', 'updated_at', 'completed_at', 'generated_at',
    'started_at', 'timestamp', 'llm_model', 'llm_base_url', 'model', 'files', 'file', 'filename',
    'original_filename', 'path', 'thumb', 'url',
})
VISITOR_KEYS = frozenset({'simulation_requirement', 'requirement', 'additional_context'})

# twitter_profiles.csv columns the rest of the crowd joins on.
CSV_JOIN_COLUMNS = frozenset({'user_id', 'name', 'username'})

FINISHED_REPORT = frozenset({'completed', 'failed'})
BUSY_SIMULATION = frozenset({'preparing', 'running', 'stopping', 'paused'})
# A project still reading its scroll ('created') or building its Web.
BUSY_PROJECT = frozenset({'created', 'graph_building'})

CONTEXTS = {
    'report': 'a Chronicle (a report on a simulated gathering), its outline and the notes of the one who wrote it',
    'simulation': "a simulated crowd's records: its citizens' profiles, stances and run notes",
    'project': "a gathering's record: what its scroll is about",
    'graph': "the facts and summaries of a gathering's memory graph",
}


class ScopeError(ValueError):
    """A scope that names no record."""


class LanguageError(ValueError):
    """A lang that names neither English nor Chinese."""


class MendBusy(RuntimeError):
    """Another mend is at work in this process."""


_mend_lock = threading.Lock()


# ---------------------------------------------------------------- where records live

def _reports_dir() -> str:
    from .report_agent import ReportManager

    return ReportManager.REPORTS_DIR


def _simulations_dir() -> str:
    from .simulation_manager import SimulationManager

    return SimulationManager.SIMULATION_DATA_DIR


def _run_state_dir() -> str:
    from .simulation_runner import SimulationRunner

    return SimulationRunner.RUN_STATE_DIR


def _projects_dir() -> str:
    from ..models.project import ProjectManager

    return ProjectManager.PROJECTS_DIR


def _memory_db_path() -> str:
    return Config.LOCAL_MEMORY_DB_PATH


def _activity():
    from ..memory import activity

    return activity


def parse_scope(scope) -> Tuple[str, Optional[str]]:
    """('all', None) or (kind, id) for 'report:<id>', 'simulation:<id>', 'project:<id>', 'graph:<graph_id>'."""

    text = str(scope if scope is not None else SCOPE_ALL).strip()
    if text.lower() == SCOPE_ALL:
        return SCOPE_ALL, None
    kind, _, ident = text.partition(':')
    kind, ident = kind.strip().lower(), ident.strip()
    pattern = _ID_PATTERNS.get(kind)
    if pattern is None or not pattern.fullmatch(ident):
        raise ScopeError(
            "The scope is 'all', 'report:<id>', 'simulation:<id>', 'project:<id>' or 'graph:<graph_id>'."
        )
    return kind, ident


def parse_lang(lang) -> Optional[str]:
    """None when no lang was asked for, else 'en' or 'zh' ('en-US' and 'zh_CN' too). LanguageError for the rest."""

    if lang is None or (isinstance(lang, str) and not lang.strip()):
        return None
    found = None
    if isinstance(lang, str) and ',' not in lang and ';' not in lang:
        found = normalize_lang(lang.strip(), default=None)
    if found is None:
        raise LanguageError("lang is 'en' or 'zh'.")
    return found


def _names(kind: str, ident: Optional[str], record_kind: str, record_id: str) -> bool:
    """Whether a scope names a record: the record's own scope, or 'project:<id>' for its whole gathering."""

    return kind == 'project' or (kind, ident) == (record_kind, record_id)


def _read_record(path: str) -> Optional[Any]:
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def _record_ids(folder: str, kind: str, marker: str) -> List[str]:
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    pattern = _ID_PATTERNS[kind]
    return [
        name for name in names
        if pattern.fullmatch(name) and os.path.isfile(os.path.join(folder, name, marker))
    ]


def _simulations_of(project_id: str) -> List[str]:
    folder = _simulations_dir()
    return [
        simulation_id for simulation_id in _record_ids(folder, 'simulation', 'state.json')
        if (_read_record(os.path.join(folder, simulation_id, 'state.json')) or {}).get('project_id') == project_id
    ]


def _reports_of(simulation_ids: Iterable[str]) -> List[str]:
    wanted = set(simulation_ids)
    folder = _reports_dir()
    return [
        report_id for report_id in _record_ids(folder, 'report', 'meta.json')
        if (_read_record(os.path.join(folder, report_id, 'meta.json')) or {}).get('simulation_id') in wanted
    ]


def _graph_of(path: str) -> Optional[str]:
    graph_id = (_read_record(path) or {}).get('graph_id')
    return graph_id if isinstance(graph_id, str) and _ID_PATTERNS['graph'].fullmatch(graph_id) else None


def _plan(kind: str, ident: Optional[str]) -> List[Tuple[str, str]]:
    """The records a scope covers, as (kind, id): projects, then crowds, Chronicles and graphs."""

    if kind == 'project':
        simulations = _simulations_of(ident)
        reports = _reports_of(simulations)
        graphs = [_graph_of(os.path.join(_projects_dir(), ident, 'project.json'))]
        graphs += [_graph_of(os.path.join(_simulations_dir(), sid, 'state.json')) for sid in simulations]
        planned = [('project', ident)]
        planned += [('simulation', sid) for sid in simulations] + [('report', rid) for rid in reports]
        return planned + [('graph', gid) for gid in sorted({gid for gid in graphs if gid})]
    if kind != SCOPE_ALL:
        return [(kind, ident)]
    projects = _record_ids(_projects_dir(), 'project', 'project.json')
    simulations = _record_ids(_simulations_dir(), 'simulation', 'state.json')
    reports = _record_ids(_reports_dir(), 'report', 'meta.json')
    graphs = {_graph_of(os.path.join(_projects_dir(), pid, 'project.json')) for pid in projects}
    graphs |= {_graph_of(os.path.join(_simulations_dir(), sid, 'state.json')) for sid in simulations}
    return (
        [('project', pid) for pid in projects] + [('simulation', sid) for sid in simulations]
        + [('report', rid) for rid in reports] + [('graph', gid) for gid in sorted(g for g in graphs if g)]
    )


@dataclass
class _Decision:
    """A request that names a whole gathering ('project:<id>') with lang, when the gathering's language is
    only a guess: its records take lang in place of the guess, and applying keeps lang on its project.
    standing turns false when the project could not keep it; nothing else is then written under it."""

    project_id: str
    lang: str
    standing: bool = True


def _decide(kind: str, ident: Optional[str], lang: Optional[str]) -> Optional[_Decision]:
    if kind != 'project' or lang is None:
        return None
    _language, how = record_language_source(project_id=ident)
    return _Decision(ident, lang) if how in GUESSED_SOURCES else None


def _language_of(
    kind: str, ident: str, decision: Optional[_Decision] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(the record's language, how it was found, None) or (None, None, why it has none).

    How: 'configured', 'stored', 'guessed' or 'default' (record_language_source),
    or 'explicit' where decision gives a guessed gathering its language (a
    decision is only ever passed for the records of its own gathering);
    a Web takes its gatherings' language, found no more surely than the least sure of them.
    """

    def found(language: str, how: str, decided: bool) -> Tuple[str, str]:
        return (decision.lang, EXPLICIT) if decided and how in GUESSED_SOURCES else (language, how)

    if kind == 'report':
        return (*found(*record_language_source(report_id=ident), decision is not None), None)
    if kind == 'simulation':
        return (*found(*record_language_source(simulation_id=ident), decision is not None), None)
    if kind == 'project':
        return (*found(*record_language_source(project_id=ident), decision is not None), None)
    from ..models.project import ProjectManager

    try:
        owners = [project.project_id for project in ProjectManager.find_projects_by_graph_id(ident)]
    except Exception:  # noqa: BLE001 - an unreadable project owns nothing
        owners = []
    if not owners:
        return None, None, 'no gathering on record owns this graph'
    languages_of = [
        found(*record_language_source(project_id=project_id),
              decision is not None and project_id == decision.project_id)
        for project_id in owners
    ]
    languages = {language for language, _how in languages_of}
    if len(languages) > 1:
        return None, None, 'gatherings in different languages share this graph'
    hows = [how for _language, how in languages_of]
    # A Web of a decided gathering is decided with it, whatever its other owners only guess.
    how = EXPLICIT if EXPLICIT in hows else min(hows, key=lambda how: _SOURCE_STRENGTH.get(how, 0))
    return languages.pop(), how, None


# ---------------------------------------------------------------- notes the backend wrote from a key

_PLACEHOLDER_RE = re.compile(r'\{(\w+)\}')
_notes_lock = threading.Lock()
_notes: Optional[List[Tuple[str, 're.Pattern[str]', Dict[str, str]]]] = None


def _flatten(tree: Any, prefix: str = '') -> Iterable[Tuple[str, str]]:
    if isinstance(tree, dict):
        for key, value in tree.items():
            yield from _flatten(value, f'{prefix}.{key}' if prefix else str(key))
    elif isinstance(tree, str):
        yield prefix, tree


def _note_pattern(template: str) -> Tuple['re.Pattern[str]', Dict[str, str], int]:
    """A locale template as a whole-text pattern: (pattern, {placeholder: group}, Han characters in its words)."""

    parts: List[str] = []
    groups: Dict[str, str] = {}
    words = ''
    position = 0
    for found in _PLACEHOLDER_RE.finditer(template):
        literal = template[position:found.start()]
        parts.append(re.escape(literal))
        words += literal
        name = found.group(1)
        if name in groups:
            parts.append(f'(?P={groups[name]})')
        else:
            groups[name] = f'g{len(groups)}'
            parts.append(f'(?P<{groups[name]}>.+?)')
        position = found.end()
    parts.append(re.escape(template[position:]))
    words += template[position:]
    return re.compile(''.join(parts), re.DOTALL), groups, len(HAN_RE.findall(words))


def _note_patterns():
    global _notes
    with _notes_lock:
        if _notes is None:
            found = []
            for key, template in _flatten(locale_utils._translations.get('zh', {})):
                if key.split('.', 1)[0] not in NOTE_NAMESPACES:
                    continue
                pattern, groups, han = _note_pattern(template)
                # A template of placeholders around a word or two would claim any sentence.
                if han >= 2:
                    found.append((key, pattern, groups, len(template)))
            # The longest template first: a shorter one never claims a longer note.
            found.sort(key=lambda item: -item[3])
            _notes = [(key, pattern, groups) for key, pattern, groups, _length in found]
        return _notes


def _whole_note(text: str, lang: str) -> Optional[str]:
    for key, pattern, groups in _note_patterns():
        found = pattern.fullmatch(text)
        if found is None:
            continue
        rendered = t(key, locale=lang, **{name: found.group(group) for name, group in groups.items()})
        if rendered and rendered != key and rendered != text:
            return rendered
    return None


def known_note(text: Any, lang: str) -> Optional[str]:
    """text in lang when it is a note the backend wrote from a Chinese locale template, else None.

    '该运行停留在「stopping」状态（第 136/336 轮）…' is api.simRunInterrupted, written
    again with its own numbers in lang; so is a note after an English lead-in
    ('Interview API call failed: 模拟环境未运行或已关闭…'). What a placeholder held
    stays as it was (it may still need the model).
    """

    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or len(stripped) > MAX_NOTE_CHARS or not foreign_script(stripped, lang):
        return None
    rendered = _whole_note(stripped, lang)
    if rendered is not None:
        return rendered
    head, colon, tail = stripped.partition(': ')
    if colon and head and not foreign_script(head, lang):
        rendered = _whole_note(tail.strip(), lang)
        if rendered is not None:
            return f'{head}: {rendered}'
    return None


# ---------------------------------------------------------------- files

def _write_text_atomic(path: str, text: str) -> None:
    """text into path all at once (a temporary file beside it, then os.replace), keeping its mode."""

    folder = os.path.dirname(os.path.abspath(path))
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o644
    handle, temp_path = tempfile.mkstemp(prefix=f'.{os.path.basename(path)}.', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='') as out:
            out.write(text)
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def _json_style(raw: str) -> Tuple[Optional[int], bool]:
    """(indent, ensure_ascii) the file was written with, so a mended file reads as it did."""

    indent = None
    newline = raw.find('\n')
    if newline >= 0:
        rest = raw[newline + 1:]
        indent = (len(rest) - len(rest.lstrip(' '))) or 2
    return indent, raw.isascii() and '\\u' in raw


class _Doc:
    """One file of a record: loaded once, changed in memory, saved whole."""

    def __init__(self, rel: str, path: str):
        self.rel = rel
        self.path = path
        self.dirty = False

    def save(self) -> None:
        raise NotImplementedError


class _JsonDoc(_Doc):
    def __init__(self, rel, path, data, raw, leave=None):
        super().__init__(rel, path)
        self.data = data
        self.indent, self.ensure_ascii = _json_style(raw)
        self.leave = leave or _default_leave

    def save(self) -> None:
        write_json_atomic(self.path, self.data, ensure_ascii=self.ensure_ascii, indent=self.indent)


class _TextDoc(_Doc):
    def __init__(self, rel, path, text):
        super().__init__(rel, path)
        self.text = text

    def save(self) -> None:
        _write_text_atomic(self.path, self.text)


class _JsonlDoc(_Doc):
    """agent_log.jsonl: a row that changes is written again; every other line stays byte for byte."""

    def __init__(self, rel, path, raw):
        super().__init__(rel, path)
        # Rows end at '\n' alone, as the log's readers split it: a row may hold U+2028 or U+0085 raw
        # (json.dumps(ensure_ascii=False) leaves them), which splitlines() would also break on.
        self.lines = [line for line in re.split(r'(?<=\n)', raw) if line]
        self.rows: List[Optional[Any]] = []
        for line in self.lines:
            try:
                self.rows.append(json.loads(line))
            except ValueError:
                self.rows.append(None)
        self.changed: set = set()

    def save(self) -> None:
        out = []
        for index, line in enumerate(self.lines):
            if index in self.changed:
                ending = line[len(line.rstrip('\r\n')):]
                out.append(json.dumps(self.rows[index], ensure_ascii=False) + (ending or ''))
            else:
                out.append(line)
        _write_text_atomic(self.path, ''.join(out))


class _CsvDoc(_Doc):
    def __init__(self, rel, path, rows):
        super().__init__(rel, path)
        self.rows = rows

    def save(self) -> None:
        buffer = io.StringIO()
        csv.writer(buffer).writerows(self.rows)
        _write_text_atomic(self.path, buffer.getvalue())


# ---------------------------------------------------------------- a record and its strings

@dataclass
class _Slot:
    """One string to mend: where it is, what it says, and how to put the new words back."""

    where: str
    text: str
    put: Callable[[str], None]
    doc: str  # the file (or store) it lives in, for the summary
    rendered: Optional[str] = None  # written again without the model: a known note, the rules' templates
    model: bool = True  # whether what is still foreign may go to the model
    result: Optional[str] = None


@dataclass
class _GraphRows:
    """What a graph's mend writes: (row id, old text, new text) per table."""

    graph_id: str
    edges: List[Tuple[int, str, str]] = field(default_factory=list)
    nodes: List[Tuple[int, str, str]] = field(default_factory=list)
    episodes: List[Tuple[int, str, str]] = field(default_factory=list)


@dataclass
class _Record:
    kind: str
    ident: str
    language: Optional[str] = None
    source: Optional[str] = None  # how its language was found, or 'explicit'
    uncertain: bool = False  # its language is a guess its own text doubts: left as it is
    decided: bool = False  # its language is the one a request decided for its whole gathering (_Decision)
    keeps: Optional[str] = None  # a decided gathering's project: the language it keeps when applied
    skipped: Optional[str] = None
    docs: List[_Doc] = field(default_factory=list)
    slots: List[_Slot] = field(default_factory=list)
    left: Dict[str, List[str]] = field(default_factory=dict)
    found: int = 0
    graph: Optional[_GraphRows] = None
    failed: bool = False
    calls: int = 0
    error: Optional[str] = None
    written: List[str] = field(default_factory=list)
    rows_written: Optional[Dict[str, int]] = None
    # Every file the record was read from: path -> (its name for the summary, its text then, None if absent).
    seen: Dict[str, Tuple[str, Optional[str]]] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f'{self.kind}:{self.ident}'

    def hold(self, doc: '_Doc', raw: Optional[str]) -> None:
        """doc is one of the record's files, as read from raw."""

        self.docs.append(doc)
        self.seen[doc.path] = (doc.rel, raw)

    def moved(self) -> List[str]:
        """The files that no longer read as they did when the record was collected."""

        return [rel for path, (rel, raw) in self.seen.items() if _read_text(path) != raw]

    def add(self, slot: _Slot) -> None:
        self.found += 1
        self.slots.append(slot)

    def leave(self, reason: str, where: str, *, counted: bool = True) -> None:
        if counted:
            self.found += 1
        self.left.setdefault(reason, []).append(where)

    @property
    def changed(self) -> List[_Slot]:
        if self.failed:
            return []
        return [slot for slot in self.slots if slot.result is not None and slot.result != slot.text]


def _nearest_key(path: Tuple[Any, ...]) -> Optional[str]:
    for part in reversed(path):
        if isinstance(part, str):
            return part
    return None


def _default_leave(path: Tuple[Any, ...]) -> Optional[str]:
    key = _nearest_key(path)
    if key in VISITOR_KEYS:
        return VISITOR
    if key in JOIN_KEYS:
        return JOINS
    return None


def _json_strings(value: Any, path: Tuple[Any, ...] = ()) -> Iterable[Tuple[Tuple[Any, ...], str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _json_strings(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _json_strings(item, path + (index,))
    elif isinstance(value, str):
        yield path, value


def _path_label(path: Tuple[Any, ...]) -> str:
    label = ''
    for part in path:
        label += f'[{part}]' if isinstance(part, int) else (f'.{part}' if label else str(part))
    return label


def _container(root: Any, path: Tuple[Any, ...]) -> Any:
    node = root
    for part in path[:-1]:
        node = node[part]
    return node


def _load_json(record: _Record, rel: str, path: str, leave=None) -> Optional[_JsonDoc]:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    doc = _JsonDoc(rel, path, data, raw, leave)
    record.hold(doc, raw)
    return doc


def _take_json(record: _Record, doc, *, row: Optional[int] = None, leave=None) -> None:
    """Every foreign string of a JSON document (or of one row of a JSONL one) as a slot, or left with its reason."""

    if doc is None:
        return
    data = doc.rows[row] if row is not None else doc.data
    leave = leave or doc.leave
    for path, text in _json_strings(data):
        if not path or not foreign_script(text, record.language):
            continue
        where = f'{doc.rel}:{row + 1} {_path_label(path)}' if row is not None else f'{doc.rel} {_path_label(path)}'
        reason = leave(path)
        if reason:
            record.leave(reason, where)
            continue

        def put(new, doc=doc, data=data, path=path):
            parent = _container(data, path)
            parent[path[-1]] = new
            # A length kept beside the text ('content_length') follows it.
            if isinstance(parent, dict) and isinstance(parent.get(f'{path[-1]}_length'), int):
                parent[f'{path[-1]}_length'] = len(new)
            doc.dirty = True
            if row is not None:
                doc.changed.add(row)

        record.add(_Slot(where, text, put, doc.rel, rendered=known_note(text, record.language)))


def _take_text(record: _Record, rel: str, path: str, reason: Optional[str] = None) -> None:
    text = _read_text(path)
    if text is None or not foreign_script(text, record.language):
        return
    if reason:
        record.leave(reason, rel)
        return
    doc = _TextDoc(rel, path, text)
    record.hold(doc, text)

    def put(new, doc=doc):
        doc.text = new
        doc.dirty = True

    record.add(_Slot(rel, text, put, rel))


# A console line: '[14:40:01] WARNING: ' then the message (the Chronicle's ledger reads both).
_CONSOLE_LINE = re.compile(r'^(\[[^\]\n]*\]\s*[A-Z]+\s*:?\s*)(.*)$', re.DOTALL)


def _take_console(record: _Record, rel: str, path: str) -> None:
    """console_log.txt line by line: the time and level stay, the message is mended."""

    text = _read_text(path)
    if text is None or not foreign_script(text, record.language):
        return
    doc = _TextDoc(rel, path, text)
    record.hold(doc, text)
    lines = text.split('\n')
    for index, line in enumerate(lines):
        if not foreign_script(line, record.language):
            continue
        found = _CONSOLE_LINE.match(line)
        head, message = (found.group(1), found.group(2)) if found else ('', line)

        def put(new, index=index, head=head):
            lines[index] = head + new
            doc.text = '\n'.join(lines)
            doc.dirty = True

        record.add(_Slot(f'{rel}:{index + 1}', message, put, rel, rendered=known_note(message, record.language)))


# ---------------------------------------------------------------- a Chronicle

def _agent_log_leave(row: Any) -> Callable[[Tuple[Any, ...]], Optional[str]]:
    """What the mend leaves in one row of the Scribe's log: a tool's raw result, and what it always leaves."""

    def leave(path: Tuple[Any, ...]) -> Optional[str]:
        if isinstance(row, dict) and row.get('action') == 'tool_result' and path[:2] == ('details', 'result'):
            return TOOL_RESULT
        return _default_leave(path)

    return leave


def _collect_report(record: _Record) -> None:
    report_id = record.ident
    folder = os.path.join(_reports_dir(), report_id)
    rel = f'reports/{report_id}'
    meta = _load_json(record, f'{rel}/meta.json', os.path.join(folder, 'meta.json'))
    if meta is None or not isinstance(meta.data, dict):
        record.skipped = 'no Chronicle of that id on record'
        return
    if meta.data.get('status') not in FINISHED_REPORT:
        record.skipped = 'the Scribe is still writing it'
        return
    _take_json(record, meta)
    for name in ('outline.json', 'progress.json'):
        _take_json(record, _load_json(record, f'{rel}/{name}', os.path.join(folder, name)))
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    sections = [name for name in names if re.fullmatch(r'section_\d+\.md', name)]
    for name in ['full_report.md', *sections]:
        _take_text(record, f'{rel}/{name}', os.path.join(folder, name))
    _take_console(record, f'{rel}/console_log.txt', os.path.join(folder, 'console_log.txt'))

    log_path = os.path.join(folder, 'agent_log.jsonl')
    raw = _read_text(log_path)
    if raw is not None and foreign_script(raw, record.language):
        log = _JsonlDoc(f'{rel}/agent_log.jsonl', log_path, raw)
        record.hold(log, raw)
        for index, row in enumerate(log.rows):
            if row is not None:
                _take_json(record, log, row=index, leave=_agent_log_leave(row))
            elif foreign_script(log.lines[index], record.language):
                record.leave(UNREADABLE_ROW, f'{log.rel}:{index + 1}')

    # The film is left: its voice speaks this text.
    for name in ('film.json', 'screenplay.json'):
        data = _read_record(os.path.join(folder, 'film', name))
        for path, text in _json_strings(data):
            if foreign_script(text, record.language):
                record.leave(FILM, f'{rel}/film/{name} {_path_label(path)}')
    _take_text(record, f'{rel}/film/captions.vtt', os.path.join(folder, 'film', 'captions.vtt'), reason=FILM)


# ---------------------------------------------------------------- a crowd

def _run_state_leave(path: Tuple[Any, ...]) -> Optional[str]:
    if path and path[0] == 'recent_actions':
        return POSTS
    return _default_leave(path)


def _active_runner_statuses() -> frozenset:
    from .simulation_runner import ACTIVE_RUNNER_STATUSES

    return frozenset(getattr(status, 'value', status) for status in ACTIVE_RUNNER_STATUSES)


def _running_in_memory(simulation_id: str) -> bool:
    """Whether this process's runner holds a run of the crowd that is still going."""

    from .simulation_runner import SimulationRunner

    live = SimulationRunner._run_states.get(simulation_id)
    status = getattr(live, 'runner_status', None)
    return getattr(status, 'value', status) in _active_runner_statuses()


def _collect_simulation(record: _Record) -> None:
    simulation_id = record.ident
    folder = os.path.join(_simulations_dir(), simulation_id)
    rel = f'simulations/{simulation_id}'
    state_path = os.path.join(folder, 'state.json')
    run_path = os.path.join(_run_state_dir(), simulation_id, 'run_state.json')
    state = _load_json(record, f'{rel}/state.json', state_path)
    if state is None or not isinstance(state.data, dict):
        record.skipped = 'no crowd of that id on record'
        return
    run = _load_json(record, f'{rel}/run_state.json', run_path, leave=_run_state_leave)
    if run is None:
        # No run on record yet: one that starts while the model is at work shows as a change.
        record.seen[run_path] = (f'{rel}/run_state.json', _read_text(run_path))
    busy = state.data.get('status') in BUSY_SIMULATION or _running_in_memory(simulation_id) or (
        run is not None and isinstance(run.data, dict) and run.data.get('runner_status') in _active_runner_statuses()
    )
    if busy:
        record.skipped = 'the crowd is still at work'
        return
    _take_json(record, state)
    _take_json(record, run)
    stances = _load_json(record, f'{rel}/stances.json', os.path.join(folder, 'stances.json'))
    if stances is not None and not (isinstance(stances.data, dict) and stances.data.get('status') == 'reading'):
        _take_json(record, stances)
    for name in ('simulation_config.json', 'reddit_profiles.json'):
        _take_json(record, _load_json(record, f'{rel}/{name}', os.path.join(folder, name)))
    portraits = _load_json(record, f'{rel}/portraits/portraits.json', os.path.join(folder, 'portraits', 'portraits.json'))
    if portraits is not None and not (isinstance(portraits.data, dict) and portraits.data.get('status') == 'running'):
        _take_json(record, portraits)
        _take_json(record, _load_json(record, f'{rel}/portraits/cast.json', os.path.join(folder, 'portraits', 'cast.json')))
    _take_csv(record, f'{rel}/twitter_profiles.csv', os.path.join(folder, 'twitter_profiles.csv'))


def _take_csv(record: _Record, rel: str, path: str) -> None:
    raw = _read_text(path)
    if raw is None or not foreign_script(raw, record.language):
        return
    rows = list(csv.reader(io.StringIO(raw, newline='')))
    if not rows:
        return
    doc = _CsvDoc(rel, path, rows)
    record.hold(doc, raw)
    header = rows[0]
    for row_index, row in enumerate(rows[1:], start=1):
        for column, text in enumerate(row):
            if not foreign_script(text, record.language):
                continue
            name = header[column] if column < len(header) else str(column)
            where = f'{rel} row {row_index} {name}'
            if name in CSV_JOIN_COLUMNS:
                record.leave(JOINS, where)
                continue

            def put(new, row=row, column=column, doc=doc):
                row[column] = new
                doc.dirty = True

            record.add(_Slot(where, text, put, rel))


# ---------------------------------------------------------------- a project

def _collect_project(record: _Record) -> None:
    project_id = record.ident
    rel = f'projects/{project_id}/project.json'
    doc = _load_json(record, rel, os.path.join(_projects_dir(), project_id, 'project.json'))
    if doc is None or not isinstance(doc.data, dict):
        record.skipped = 'no project of that id on record'
        return
    if doc.data.get('status') in BUSY_PROJECT:
        record.skipped = 'its scroll is still being read or its Web built'
        return
    _take_json(record, doc)


# ---------------------------------------------------------------- a Web in the memory store

def _read_only(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(os.path.abspath(path)).as_uri() + '?mode=ro', uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _activity_record_in(group: List[str], lang: str, activity) -> Optional[List[str]]:
    """One activity record (a header line and its continuation lines) with the target templates, or None."""

    header = activity.ACTIVITY_HEADER_RE.match(group[0].rstrip('\r'))
    if header is None:
        return None
    parsed = activity.parse_activity_text('\n'.join(group)).lines
    if len(parsed) != 1 or parsed[0].language == lang:
        return None  # its template is already the record's: what is foreign is a citizen's own words
    description = activity.rerender_description(parsed[0].description, lang)
    if not description:
        return None
    last = len(group)
    while last > 1 and not group[last - 1].strip():
        last -= 1
    return (group[0][:header.start('desc')] + description).split('\n') + group[last:]


def activity_text_in(content: str, lang: str) -> Tuple[str, int]:
    """An activity episode with each record's template in lang, and how many foreign lines are still in it.

    Only the templates change (memory.activity.rerender_description): names
    and what the citizens wrote stay as the square recorded them.
    """

    activity = _activity()
    target = activity.activity_language(lang) or activity.LANG_EN
    groups: List[List[str]] = []
    for line in content.split('\n'):
        if not groups or activity.ACTIVITY_HEADER_RE.match(line.rstrip('\r')):
            groups.append([line])
        else:
            groups[-1].append(line)
    out: List[str] = []
    for group in groups:
        if foreign_script('\n'.join(group), lang):
            group = _activity_record_in(group, target, activity) or group
        out.extend(group)
    return '\n'.join(out), sum(1 for line in out if foreign_script(line, lang))


def _collect_graph(record: _Record, db_path: str) -> None:
    graph_id = record.ident
    lang = record.language
    if not db_path or not os.path.isfile(db_path):
        record.skipped = 'no local memory store here'
        return
    activity = _activity()
    rows = record.graph = _GraphRows(graph_id)
    store_rel = f'memory/{os.path.basename(db_path)}'
    conn = _read_only(db_path)
    try:
        if conn.execute('SELECT 1 FROM graphs WHERE graph_id = ?', (graph_id,)).fetchone() is None:
            record.skipped = 'no graph of that id in the memory store'
            return
        for row in conn.execute(
            'SELECT id, uuid, fact, origin FROM edges WHERE graph_id = ? ORDER BY id', (graph_id,)
        ).fetchall():
            fact = row['fact']
            if not foreign_script(fact, lang):
                continue
            rendered = activity.rerender_fact(fact, lang) if row['origin'] == activity.RULES_ORIGIN else None
            record.add(_Slot(
                f'{store_rel} edge {row["uuid"]} fact', fact,
                lambda new, row_id=row['id'], old=fact: rows.edges.append((row_id, old, new)),
                store_rel, rendered=rendered,
            ))
        for row in conn.execute(
            'SELECT id, uuid, name, summary FROM nodes WHERE graph_id = ? ORDER BY id', (graph_id,)
        ).fetchall():
            where = f'{store_rel} node {row["uuid"]}'
            if foreign_script(row['name'], lang):
                record.leave(JOINS, f'{where} name')
            summary = row['summary']
            if not foreign_script(summary, lang):
                continue
            record.add(_Slot(
                f'{where} summary', summary,
                lambda new, row_id=row['id'], old=summary: rows.nodes.append((row_id, old, new)),
                store_rel, rendered=activity.rerender_summary(summary, lang),
            ))
        for row in conn.execute(
            'SELECT id, uuid, kind, content FROM episodes WHERE graph_id = ? ORDER BY id', (graph_id,)
        ).fetchall():
            content = row['content']
            if not foreign_script(content, lang):
                continue
            where = f'{store_rel} episode {row["uuid"]}'
            if row['kind'] != 'activity':
                record.leave(SCROLL, where)
                continue
            rendered, still = activity_text_in(content, lang)
            if rendered != content:
                record.add(_Slot(
                    where, content,
                    lambda new, row_id=row['id'], old=content: rows.episodes.append((row_id, old, new)),
                    store_rel, rendered=rendered, model=False,
                ))
            if still:
                record.leave(ACTIVITY, f'{where} ({still} line(s))', counted=rendered == content)
    finally:
        conn.close()


def _write_graph(db_path: str, rows: _GraphRows) -> Dict[str, int]:
    """The graph's new text, in one transaction of the store's own: fact keys follow the facts, and the
    episodes' search index is kept (its trigger follows only source_description)."""

    from ..memory.resolution import bump_graph_version
    from ..memory.store import FTS_TABLES, MemoryStore
    from ..memory.textnorm import name_key

    written = {'edges': 0, 'nodes': 0, 'episodes': 0}
    store = MemoryStore(db_path)
    try:
        with store.write() as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            spec = next((item for item in FTS_TABLES if item.table == 'episodes'), None)
            index = spec if spec is not None and spec.fts in tables else None
            for row_id, old, new in rows.edges:
                written['edges'] += conn.execute(
                    'UPDATE edges SET fact = ?, fact_key = ? WHERE id = ? AND graph_id = ? AND fact = ?',
                    (new, name_key(new), row_id, rows.graph_id, old),
                ).rowcount
            for row_id, old, new in rows.nodes:
                written['nodes'] += conn.execute(
                    'UPDATE nodes SET summary = ? WHERE id = ? AND graph_id = ? AND summary = ?',
                    (new, row_id, rows.graph_id, old),
                ).rowcount
            for row_id, old, new in rows.episodes:
                row = conn.execute(
                    'SELECT * FROM episodes WHERE id = ? AND graph_id = ?', (row_id, rows.graph_id)
                ).fetchone()
                if row is None or row['content'] != old:
                    continue  # changed since it was read
                if index is not None:
                    columns = ', '.join(index.columns)
                    marks = ', '.join('?' for _ in index.columns)
                    before = [row[column] for column in index.columns]
                    after = [new if column == 'content' else row[column] for column in index.columns]
                    conn.execute(
                        f"INSERT INTO {index.fts}({index.fts}, rowid, {columns}) VALUES ('delete', ?, {marks})",
                        (row_id, *before),
                    )
                conn.execute('UPDATE episodes SET content = ? WHERE id = ?', (new, row_id))
                if index is not None:
                    conn.execute(f'INSERT INTO {index.fts}(rowid, {columns}) VALUES (?, {marks})', (row_id, *after))
                written['episodes'] += 1
            if any(written.values()):
                bump_graph_version(conn, rows.graph_id)
    finally:
        store.close()
    return written


# ---------------------------------------------------------------- a guessed language, doubted

def _prose(data: Any) -> List[str]:
    """The strings of a JSON record a reader reads as its text: no name, id or code, not the visitor's
    question, not a note the backend wrote from a key (it tells the locale of a thread, not of the record)."""

    return [
        text for path, text in _json_strings(data)
        if path and text.strip() and _default_leave(path) is None and known_note(text, 'en') is None
    ]


def _report_prose(report_id: str) -> List[str]:
    """The Chronicle as its reader reads it: full_report.md, else the markdown on record, else its outline."""

    folder = os.path.join(_reports_dir(), report_id)
    markdown = _read_text(os.path.join(folder, 'full_report.md'))
    if markdown and markdown.strip():
        return [markdown]
    meta = _read_record(os.path.join(folder, 'meta.json'))
    meta = meta if isinstance(meta, dict) else {}
    markdown = meta.get('markdown_content')
    if isinstance(markdown, str) and markdown.strip():
        return [markdown]
    outline = meta.get('outline')
    if not isinstance(outline, dict):
        outline = _read_record(os.path.join(folder, 'outline.json'))
    return _prose(outline)


def _simulation_prose(simulation_id: str) -> List[str]:
    """A crowd's stances and its citizens' profiles (not their names)."""

    folder = os.path.join(_simulations_dir(), simulation_id)
    texts: List[str] = []
    for name in ('stances.json', 'reddit_profiles.json'):
        texts += _prose(_read_record(os.path.join(folder, name)))
    raw = _read_text(os.path.join(folder, 'twitter_profiles.csv'))
    rows = list(csv.reader(io.StringIO(raw, newline=''))) if raw else []
    if rows:
        header = rows[0]
        texts += [
            cell for row in rows[1:] for column, cell in enumerate(row)
            if cell.strip() and (header[column] if column < len(header) else '') not in CSV_JOIN_COLUMNS
        ]
    return texts


def _graph_prose(graph_id: str, db_path: str) -> List[str]:
    """What the model wrote into a Web: its facts and summaries, not the rules' templates."""

    activity = _activity()
    conn = _read_only(db_path)
    try:
        facts = [row[0] for row in conn.execute(
            "SELECT fact FROM edges WHERE graph_id = ? AND COALESCE(origin, '') != ?",
            (graph_id, activity.RULES_ORIGIN),
        )]
        summaries = [row[0] for row in conn.execute('SELECT summary FROM nodes WHERE graph_id = ?', (graph_id,))]
    finally:
        conn.close()
    summaries = [text for text in summaries if isinstance(text, str) and activity.rerender_summary(text, 'en') is None]
    return [text for text in facts + summaries if isinstance(text, str) and text.strip()]


def _reads_chinese(record: _Record, db_path: str) -> bool:
    """Whether what a reader reads of the record reads as Chinese (language_guard.guess_language)."""

    if record.kind == 'report':
        texts = _report_prose(record.ident)
    elif record.kind == 'simulation':
        texts = _simulation_prose(record.ident)
    elif record.kind == 'project':
        texts = _prose(_read_record(os.path.join(_projects_dir(), record.ident, 'project.json')))
    else:
        texts = _graph_prose(record.ident, db_path)
    return guess_language('\n'.join(texts)) == 'zh'


def _doubt(record: _Record) -> None:
    """The record's guessed language is doubted: every string it would mend is left, with the reason."""

    record.uncertain = True
    record.left.setdefault(LANGUAGE_UNCERTAIN, []).extend(slot.where for slot in record.slots)
    record.slots = []


# ---------------------------------------------------------------- the model

def _whole_line(line: Any, lang: str) -> bool:
    """Whether one line of an answer is a translation the mend can write: one line, in lang throughout.

    The guard would cut what is still foreign out of a line (or drop it), and
    that is not a translation of the record: the quote or heading would be lost.
    """

    if not isinstance(line, str) or not line.strip() or '\n' in line.strip():
        return False
    finished = language_guard.to_ascii_punct(line.strip()) if lang == 'en' else line
    return not foreign_script(finished, lang)


def _usable(answer: Any, messages: Any, lang: str) -> bool:
    """Whether a translate call came back whole: a line in lang for each line it was sent."""

    try:
        expected = len(json.loads(messages[-1]['content'])['lines'])
    except (ValueError, TypeError, KeyError, IndexError):
        expected = None
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            return False
    if isinstance(answer, dict):
        lines = answer.get('lines')
        if not isinstance(lines, list):
            lists = [value for value in answer.values() if isinstance(value, list)]
            lines = lists[0] if len(lists) == 1 else None
        answer = lines
    if not isinstance(answer, list) or (expected is not None and len(answer) != expected):
        return False
    return all(_whole_line(line, lang) for line in answer)


class _CountedTranslator:
    """The translator, counted: remembers whether any call failed, came back short or left a line foreign."""

    def __init__(self, llm, lang: str):
        self._llm = llm
        self.lang = lang
        self.calls = 0
        self.failed = 0

    def chat_json(self, messages, temperature=0.0, max_tokens=None):
        self.calls += 1
        try:
            if self._llm is None:
                self._llm = language_guard.default_translator()
            if hasattr(self._llm, 'chat_json'):
                answer = self._llm.chat_json(messages=messages, temperature=temperature, max_tokens=max_tokens)
            else:
                answer = self._llm.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
        except Exception:
            self.failed += 1
            raise
        if not _usable(answer, messages, self.lang):
            self.failed += 1
        return answer


class _GuardFallbacks(logging.Handler):
    """The guard's warnings on this thread while the mend's call runs.

    The guard says so whenever it cut foreign script out of a line instead of
    translating it (a failed or unusable call, or its own last resort), and it
    never raises: a warning is how the mend learns that a text came back cut.
    """

    def __init__(self):
        super().__init__(logging.WARNING)
        self.thread = threading.get_ident()
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread == self.thread:
            self.count += 1


def _translate(record: _Record, llm) -> None:
    """Every slot's new text: its rendering, and the model for what is still foreign (one call)."""

    pending: List[Tuple[_Slot, str]] = []
    for slot in record.slots:
        base = slot.rendered if slot.rendered is not None else slot.text
        if slot.model and foreign_script(base, record.language):
            pending.append((slot, base))
        else:
            slot.result = base
    if not pending:
        return
    translator = _CountedTranslator(llm, record.language)
    fallbacks = _GuardFallbacks()
    untranslated: List[int] = []  # the guard's own word for a text it could not translate whole
    language_guard.logger.addHandler(fallbacks)
    try:
        texts = ensure_language_many(
            [base for _slot, base in pending], record.language, llm=translator, context=CONTEXTS[record.kind],
            untranslated=untranslated,
        )
    finally:
        language_guard.logger.removeHandler(fallbacks)
    record.calls = translator.calls
    # Three ways to hear that a text did not come back whole: a call that failed, came back short or
    # left a line foreign; a warning that the guard cut foreign script out; the guard's untranslated list.
    if translator.failed or fallbacks.count or untranslated:
        record.failed = True
        record.left.setdefault(UNTRANSLATED, []).extend(slot.where for slot, _base in pending)
        return
    for (slot, _base), text in zip(pending, texts):
        slot.result = text


# ---------------------------------------------------------------- backups

class _Backups:
    """<upload folder>/_mend_backups/<UTC stamp>/, made when the first file is copied."""

    def __init__(self):
        self.root: Optional[str] = None

    def _folder(self) -> str:
        if self.root is None:
            base = os.path.join(Config.UPLOAD_FOLDER, BACKUP_DIR_NAME)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            root, count = os.path.join(base, stamp), 1
            while os.path.exists(root):
                count += 1
                root = os.path.join(base, f'{stamp}-{count}')
            os.makedirs(root)
            self.root = root
        return self.root

    def _target(self, rel: str) -> str:
        target = os.path.join(self._folder(), *rel.split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        return target

    def copy(self, path: str, rel: str) -> None:
        shutil.copy2(path, self._target(rel))

    def database(self, path: str, rel: str) -> None:
        source = _read_only(path)
        target = sqlite3.connect(self._target(rel))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    @property
    def label(self) -> Optional[str]:
        """Where the copies are, under the upload folder (no server path)."""

        return os.path.relpath(self.root, Config.UPLOAD_FOLDER).replace(os.sep, '/') if self.root else None


def _keep_language(record: _Record) -> None:
    """A decided gathering's project keeps its language ('language' in project.json), so record_language
    reads it from then on instead of guessing. Written by _apply with the project's other changes."""

    if record.keeps is None:
        return
    for doc in record.docs:
        if isinstance(doc, _JsonDoc) and isinstance(doc.data, dict):
            doc.data['language'] = record.keeps
            doc.dirty = True


def _apply(record: _Record, backups: _Backups, db_path: str, state: dict) -> None:
    from .simulation_runner import SimulationRunner

    if record.graph is not None:
        if not (record.graph.edges or record.graph.nodes or record.graph.episodes):
            return
        rel = f'memory/{os.path.basename(db_path)}'
        if not state.get('database_copied'):
            backups.database(db_path, rel)
            state['database_copied'] = True
        record.rows_written = _write_graph(db_path, record.graph)
        record.written.append(rel)
        return
    dirty = [doc for doc in record.docs if doc.dirty]
    if not dirty:
        return
    # The model may have taken a while: a file written meanwhile (a build finished, a run or a
    # reading began) is newer than the copy in hand, and saving the copy would undo it.
    moved = record.moved()
    if record.kind == 'simulation' and _running_in_memory(record.ident):
        moved.append('a run of this crowd began')
    if moved:
        record.failed = True
        record.left.setdefault(MOVED, []).extend(moved)
        return
    for doc in dirty:
        backups.copy(doc.path, doc.rel)
    for doc in dirty:
        doc.save()
        record.written.append(doc.rel)
    if (
        record.kind == 'simulation' and any(doc.rel.endswith('/run_state.json') for doc in dirty)
        and not _running_in_memory(record.ident)
    ):
        # The runner keeps run states in memory: read the mended one next time.
        SimulationRunner._run_states.pop(record.ident, None)


# ---------------------------------------------------------------- the summary

def _clip(text: Optional[str]) -> Optional[str]:
    if text is None or len(text) <= PREVIEW_CHARS:
        return text
    return text[:PREVIEW_CHARS - 1] + '…'


def _preview(slots: List[_Slot]) -> List[Dict[str, Any]]:
    """Each distinct changed line once, with where it was first seen."""

    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for slot in slots:
        before, after = slot.text.split('\n'), slot.result.split('\n')
        pairs = zip(before, after) if len(before) == len(after) else [(slot.text, slot.result)]
        for old, new in pairs:
            if old == new or (old, new) in seen:
                continue
            if len(seen) >= PREVIEW_LIMIT:
                return list(seen.values())
            seen[(old, new)] = {'where': slot.where, 'before': _clip(old), 'after': _clip(new)}
    return list(seen.values())


def _files_of(slots: Iterable[_Slot], record: Optional[_Record] = None) -> List[str]:
    """The files the slots live in, and the project a decided gathering keeps its language on."""

    files = {slot.doc for slot in slots}
    if record is not None and record.keeps is not None and not record.failed:
        files |= {doc.rel for doc in record.docs}
    return sorted(files)


def _left(record: _Record) -> List[Dict[str, Any]]:
    return [
        {'reason': reason, 'count': len(wheres), 'where': wheres[:WHERE_LIMIT]}
        for reason, wheres in record.left.items()
    ]


def _entry(record: _Record, *, scanning: bool, apply: bool) -> Dict[str, Any]:
    entry: Dict[str, Any] = {'record': record.key, 'language': record.language}
    if record.source:
        entry['language_source'] = record.source
    if record.uncertain:
        entry['uncertain'] = True
    if record.skipped:
        entry['skipped'] = record.skipped
        return entry
    if record.keeps is not None:
        entry['keeps_language'] = record.keeps
    entry['found'] = record.found
    if not record.found and record.keeps is None:
        return entry
    if scanning:
        by_rules = [
            slot for slot in record.slots
            if slot.rendered is not None and not foreign_script(slot.rendered, record.language)
        ]
        entry['to_mend'] = len(record.slots)
        entry['by_rules'] = len(by_rules)
        entry['for_model'] = sum(
            1 for slot in record.slots
            if slot.model and foreign_script(slot.rendered if slot.rendered is not None else slot.text, record.language)
        )
        entry['files'] = _files_of(record.slots, record)
    else:
        changed = record.changed
        entry['changed'] = len(changed)
        entry['files'] = record.written if apply else _files_of(changed, record)
        entry['llm_calls'] = record.calls
        entry['preview'] = _preview(changed)
        if record.rows_written is not None:
            entry['rows'] = record.rows_written
    entry['left'] = _left(record)
    if record.error:
        entry['error'] = record.error
    return entry


# ---------------------------------------------------------------- scan and mend

def _collect(
    kind: str, ident: str, db_path: str, lang: Optional[str] = None, decision: Optional[_Decision] = None,
) -> _Record:
    """One record and what in it is to mend.

    lang: the language a request that names the record asked for. decision: the
    language a request decided for the record's whole gathering (_Decision).
    """

    record = _Record(kind, ident)
    language, source, why = _language_of(kind, ident, decision)
    if language is None:
        record.skipped = why
        return record
    record.decided = source == EXPLICIT
    if lang is not None and source in GUESSED_SOURCES:
        if lang != language:
            # Only its whole gathering can change a guess: this record alone would split it.
            record.language, record.source = language, source
            record.skipped = GUESS_KEPT.format(language=language, lang=lang)
            return record
        source = EXPLICIT
    record.language, record.source = language, source
    if lang is not None and lang != language:
        record.skipped = f"{_KEPT.get(source, 'its language is set')} ('{language}'): lang never changes it"
        return record
    if record.decided and not decision.standing:
        record.skipped = UNDECIDED.format(lang=decision.lang, project_id=decision.project_id)
        return record
    if record.decided and kind == 'project':
        record.keeps = language
    if language == 'zh' and record.keeps is None:
        record.skipped = 'written in Chinese: its record language, so nothing to mend'
        return record
    try:
        if kind == 'report':
            _collect_report(record)
        elif kind == 'simulation':
            _collect_simulation(record)
        elif kind == 'project':
            _collect_project(record)
        else:
            _collect_graph(record, db_path)
        if not record.skipped and record.slots and source in GUESSED_SOURCES and _reads_chinese(record, db_path):
            _doubt(record)
    except Exception as error:  # noqa: BLE001 - one unreadable record never stops the rest
        logger.warning('Could not read %s for the mend: %s', record.key, type(error).__name__)
        record.skipped = f'could not be read ({type(error).__name__})'
    return record


def _collect_all(
    kind: str, ident: Optional[str], lang: Optional[str], db_path: str, decision: Optional[_Decision] = None,
) -> Iterable[_Record]:
    """Each record of the scope, collected when the one before it is done with (a decided gathering's
    project comes first: the rest of it is written only if the project kept the language)."""

    for record_kind, record_id in _plan(kind, ident):
        named = lang if _names(kind, ident, record_kind, record_id) else None
        record = _collect(record_kind, record_id, db_path, named, decision)
        if record.keeps is not None and record.skipped:
            decision.standing = False  # no project to keep it, or its Web is still being built
        yield record


def scan(scope: Any = SCOPE_ALL, lang: Any = None) -> Dict[str, Any]:
    """What is written in the wrong language within scope, and what mend() would do. No model, no writes.

    lang as for mend(). Raises ScopeError and LanguageError.
    """

    kind, ident = parse_scope(scope)
    lang = parse_lang(lang)
    records = list(_collect_all(kind, ident, lang, _memory_db_path(), _decide(kind, ident, lang)))
    entries = [_entry(record, scanning=True, apply=False) for record in records]
    return {
        'scope': scope if isinstance(scope, str) else SCOPE_ALL,
        'lang': lang,
        'records': entries,
        'found': sum(entry.get('found', 0) for entry in entries),
        'to_mend': sum(entry.get('to_mend', 0) for entry in entries),
        'uncertain': [record.key for record in records if record.uncertain],
    }


def mend(scope: Any = SCOPE_ALL, apply: bool = False, llm=None, lang: Any = None) -> Dict[str, Any]:
    """Put what scope holds in the wrong language in each record's language; a dry run unless apply.

    Returns per record the strings found, changed and left (with the
    reasons), the files written (or that would be), the model calls made,
    and each distinct changed line; with the backup folder (under the upload
    folder) when anything was written, and the records left as uncertain.
    lang ('en' or 'zh') decides the language of the records the scope names
    when that language is only a guess: a record's own scope settles a guess
    lang agrees with (and refuses one it does not); 'project:<id>' decides
    the whole gathering, every record of it takes lang, and applying keeps
    lang on its project so its records and record_language agree. It never
    changes a language the gathering keeps or the site sets. Raises
    ScopeError for a scope that names no record, LanguageError for a lang
    that names neither language, and MendBusy while another mend is at work.
    """

    kind, ident = parse_scope(scope)
    lang = parse_lang(lang)
    if not _mend_lock.acquire(blocking=False):
        raise MendBusy('A mend is already at work.')
    try:
        db_path = _memory_db_path()
        backups = _Backups()
        state: dict = {}
        records = []
        decision = _decide(kind, ident, lang)
        for record in _collect_all(kind, ident, lang, db_path, decision):
            records.append(record)
            if record.skipped or not (record.slots or record.keeps):
                continue
            if record.slots:
                _translate(record, llm)
            if not record.failed:
                for slot in record.changed:
                    slot.put(slot.result)
                _keep_language(record)
                if apply:
                    try:
                        _apply(record, backups, db_path, state)
                    except Exception as error:  # noqa: BLE001 - reported per record; the backups stay
                        logger.error(
                            'The mend could not write %s: %s', record.key, type(error).__name__, exc_info=error,
                        )
                        record.error = f'could not be written ({type(error).__name__})'
            if record.keeps is not None and (record.failed or record.error):
                # The project did not keep the language: the rest of its gathering waits with it.
                decision.standing = False
        entries = [_entry(record, scanning=False, apply=apply) for record in records]
        written = [rel for record in records for rel in record.written]
        if written:
            logger.info('The mend wrote %d file(s); copies in %s', len(written), backups.label)
        return {
            'scope': scope if isinstance(scope, str) else SCOPE_ALL,
            'apply': bool(apply),
            'lang': lang,
            'records': entries,
            'found': sum(entry.get('found', 0) for entry in entries),
            'changed': sum(entry.get('changed', 0) for entry in entries),
            'files_written': written,
            'backup_dir': backups.label,
            'llm_calls': sum(record.calls for record in records),
            'uncertain': [record.key for record in records if record.uncertain],
        }
    finally:
        _mend_lock.release()
