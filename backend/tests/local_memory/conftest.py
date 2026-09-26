"""Shared fixtures for the local memory backend tests (spec §10.2).

No test here touches the network: every LLM call goes through ``FakeLLM``.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Callable

import httpx
import openai
import pytest

from app.config import Config
from app.memory import (
    LocalMemorySettings,
    LocalZep,
    MemoryStore,
    clear_local_memory_clients,
    new_id,
    register_local_memory_client,
    utcnow_iso,
)
from app.memory.models import json_dumps
from app.memory.textnorm import alias_keys, name_key


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------

_TEXT_BLOCK_RE = re.compile(r"<<<\n?(?P<text>.*?)\n?>>>", re.S)
_CHUNK_MARKER_RE = re.compile(r"^\[(?:chunk|episode) (?P<n>\d+)[^\]]*\]\s*$")
_WORKS_FOR_RE = re.compile(r"(?P<person>[A-Z][\w .'-]*?) works for (?P<org>[A-Z][\w .&'-]*?)[.\n]")


def text_block(messages: list[dict[str, str]]) -> str:
    """The ``TEXT: <<< ... >>>`` block of the last user message ('' if none)."""

    for message in reversed(messages):
        if message.get("role") == "user":
            match = _TEXT_BLOCK_RE.search(message.get("content") or "")
            return match.group("text") if match else ""
    return ""


def works_for_extractor(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Default script: "X works for Y." becomes Person X -WORKS_FOR-> Organization Y."""

    entities: dict[str, dict[str, Any]] = {}
    relations: list[dict[str, Any]] = []
    chunk: int | None = None
    for line in text_block(messages).splitlines():
        marker = _CHUNK_MARKER_RE.match(line.strip())
        if marker:
            chunk = int(marker.group("n"))
            continue
        for match in _WORKS_FOR_RE.finditer(line + "\n"):
            person, org = match.group("person").strip(), match.group("org").strip()
            entities.setdefault(person, {"name": person, "type": "Person", "summary": f"{person} is a person."})
            entities.setdefault(org, {"name": org, "type": "Organization", "summary": f"{org} is an organization."})
            relations.append({
                "source": person,
                "target": org,
                "type": "WORKS_FOR",
                "fact": f"{person} works for {org}.",
                "chunks": [chunk] if chunk is not None else [],
            })
    return {"entities": list(entities.values()), "relations": relations, "invalidated_facts": []}


class FakeLLM:
    """Scripted stand-in for ``LLMClient`` (only ``chat_json`` is used).

    ``script`` is either a callable ``(messages) -> dict | Exception`` or a
    list consumed front to back whose items are dicts, exceptions (raised) or
    callables. With an empty list the ``default`` callable answers.
    ``calls`` records every request.
    """

    def __init__(self, script: Any = None,
                 default: Callable[[list[dict[str, str]]], Any] = works_for_extractor) -> None:
        self.script: Any = [] if script is None else script
        self.default = default
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def chat_json(self, messages: list[dict[str, str]], temperature: float = 0.3,
                  max_tokens: int | None = 4096, max_attempts: int = 1) -> dict[str, Any]:
        with self._lock:
            self.calls.append({
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "max_attempts": max_attempts,
            })
            if callable(self.script):
                step: Any = self.script
            elif self.script:
                step = self.script.pop(0)
            else:
                step = self.default
        result = step(messages) if callable(step) else step
        if isinstance(result, BaseException):
            raise result
        return result

    @property
    def call_count(self) -> int:
        return len(self.calls)


def make_openai_error(status: int, headers: dict[str, str] | None = None,
                      body: Any = None) -> openai.APIStatusError:
    """An ``openai`` status error as the SDK raises it (no network involved)."""

    request = httpx.Request("POST", "http://bridge/v1/chat/completions")
    response = httpx.Response(status, headers=headers or {}, request=request)
    classes: dict[int, type[openai.APIStatusError]] = {
        400: openai.BadRequestError,
        401: openai.AuthenticationError,
        403: openai.PermissionDeniedError,
        404: openai.NotFoundError,
        409: openai.ConflictError,
        422: openai.UnprocessableEntityError,
        429: openai.RateLimitError,
    }
    cls = classes.get(status) or (openai.InternalServerError if status >= 500 else openai.APIStatusError)
    return cls(f"HTTP {status}", response=response, body=body)


# ---------------------------------------------------------------------------
# Seeding helpers (raw rows; later stages use the client API instead)
# ---------------------------------------------------------------------------


class MemorySeeder:
    """Insert graphs, nodes, edges and episodes directly into a store."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def graph(self, graph_id: str = "g1", **fields: Any) -> str:
        with self.store.write() as conn:
            conn.execute(
                "INSERT INTO graphs(graph_id, uuid, name, description, created_at) VALUES (?, ?, ?, ?, ?)",
                (graph_id, new_id(), fields.get("name", graph_id), fields.get("description"), utcnow_iso()),
            )
        return graph_id

    def node(self, graph_id: str, name: str, entity_type: str | None = None, *,
             summary: str = "", aliases: tuple[str, ...] = (), attributes: dict | None = None) -> str:
        node_uuid = new_id()
        now = utcnow_iso()
        labels = ["Entity", entity_type] if entity_type else ["Entity"]
        attributes = attributes or {}
        with self.store.write() as conn:
            conn.execute(
                "INSERT INTO nodes(uuid, graph_id, name, name_key, entity_type, labels_json, summary, "
                "attributes_json, aliases_text, attributes_text, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (node_uuid, graph_id, name, name_key(name), entity_type, json_dumps(labels), summary,
                 json_dumps(attributes), " | ".join(aliases),
                 "\n".join(f"{k}: {v}" for k, v in attributes.items()), now, now),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO node_aliases(graph_id, alias_key, node_uuid) VALUES (?, ?, ?)",
                [(graph_id, key, node_uuid) for key in alias_keys(name, aliases)],
            )
        return node_uuid

    def edge(self, graph_id: str, source: str, target: str, name: str, fact: str, *,
             episodes: tuple[str, ...] = ()) -> str:
        edge_uuid = new_id()
        now = utcnow_iso()
        with self.store.write() as conn:
            conn.execute(
                "INSERT INTO edges(uuid, graph_id, name, fact, fact_key, source_node_uuid, "
                "target_node_uuid, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (edge_uuid, graph_id, name, fact, name_key(fact), source, target, now),
            )
            conn.executemany(
                "INSERT INTO edge_episodes(edge_uuid, episode_uuid, linked_at) VALUES (?, ?, ?)",
                [(edge_uuid, episode, now) for episode in episodes],
            )
        return edge_uuid

    def episode(self, graph_id: str, content: str, *, kind: str = "document",
                source_description: str = "") -> str:
        episode_uuid = new_id()
        now = utcnow_iso()
        with self.store.write() as conn:
            conn.execute(
                "INSERT INTO episodes(uuid, graph_id, kind, content, source, source_description, "
                "reference_time, created_at) VALUES (?, ?, ?, ?, 'text', ?, ?, ?)",
                (episode_uuid, graph_id, kind, content, source_description, now, now),
            )
        return episode_uuid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def openai_error() -> Callable[..., openai.APIStatusError]:
    """``make_openai_error`` as a fixture (tests/ is not a package, so it cannot be imported)."""

    return make_openai_error


@pytest.fixture
def memory_settings() -> LocalMemorySettings:
    """Small, fast values for tests."""

    return LocalMemorySettings(
        llm_concurrency=1,
        llm_max_attempts=3,
        window_chars=4000,
        lease_seconds=60.0,
        ingestion_timeout_seconds=30.0,
        activity_group_wait_seconds=0.0,
        busy_timeout_ms=2000,
        heartbeat_seconds=0.05,
    )


@pytest.fixture
def memory_db_path(tmp_path):
    return tmp_path / "mem.sqlite3"


@pytest.fixture
def memory_store(memory_db_path, memory_settings):
    store = MemoryStore(memory_db_path, busy_timeout_ms=memory_settings.busy_timeout_ms)
    yield store
    store.close()


@pytest.fixture
def local(memory_db_path, monkeypatch, fake_llm, memory_settings):
    """A ``LocalZep`` under test, selected in ``Config`` and shared by ``get_zep_client()``.

    Built with ``llm_client_factory=lambda: fake_llm``, ``autostart_worker=False``
    and a no-op ``sleep``; run background work with ``local.worker.drain()``.
    Services constructed during the test (``GraphBuilderService()``, ...)
    get this same instance.
    """

    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local", raising=False)
    monkeypatch.setattr(Config, "LOCAL_MEMORY_DB_PATH", str(memory_db_path), raising=False)
    client = LocalZep(
        db_path=memory_db_path,
        settings=memory_settings,
        llm_client_factory=lambda: fake_llm,
        autostart_worker=False,
        sleep=lambda _seconds: None,
    )
    register_local_memory_client(client)
    yield client
    clear_local_memory_clients()
    client.close()


@pytest.fixture
def seed(local) -> MemorySeeder:
    return MemorySeeder(local.store)
