"""Tunable settings for the local memory backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from typing import Any

logger = logging.getLogger("mirofish.memory.settings")

DEDUP_PASS_MODES = frozenset({"llm", "off"})
ACTIVITY_MODES = frozenset({"rules", "llm", "off"})

# Setting name -> Config attribute that feeds it in from_config().
_CONFIG_ATTRIBUTES: dict[str, str] = {
    "llm_model": "LOCAL_MEMORY_LLM_MODEL",
    "llm_concurrency": "LOCAL_MEMORY_LLM_CONCURRENCY",
    "llm_min_interval_seconds": "LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS",
    "llm_max_attempts": "LOCAL_MEMORY_LLM_MAX_ATTEMPTS",
    "llm_max_tokens": "LOCAL_MEMORY_LLM_MAX_TOKENS",
    "window_chars": "LOCAL_MEMORY_WINDOW_CHARS",
    "max_entities_per_window": "LOCAL_MEMORY_MAX_ENTITIES_PER_WINDOW",
    "max_relations_per_window": "LOCAL_MEMORY_MAX_RELATIONS_PER_WINDOW",
    "prompt_known_entities": "LOCAL_MEMORY_PROMPT_KNOWN_ENTITIES",
    "prompt_existing_facts": "LOCAL_MEMORY_PROMPT_EXISTING_FACTS",
    "max_failed_fraction": "LOCAL_MEMORY_MAX_FAILED_FRACTION",
    "dedup_pass": "LOCAL_MEMORY_DEDUP_PASS",
    "ingestion_timeout_seconds": "LOCAL_MEMORY_INGESTION_TIMEOUT_SECONDS",
    "lease_seconds": "LOCAL_MEMORY_LEASE_SECONDS",
    "activity_mode": "LOCAL_MEMORY_ACTIVITY_MODE",
    "activity_group_size": "LOCAL_MEMORY_ACTIVITY_GROUP_SIZE",
    "activity_group_chars": "LOCAL_MEMORY_ACTIVITY_GROUP_CHARS",
    "activity_group_wait_seconds": "LOCAL_MEMORY_ACTIVITY_GROUP_WAIT_SECONDS",
    "activity_max_pending_seconds": "LOCAL_MEMORY_ACTIVITY_MAX_PENDING_SECONDS",
    "activity_max_llm_calls": "LOCAL_MEMORY_ACTIVITY_MAX_LLM_CALLS",
    "summary_max_chars": "LOCAL_MEMORY_SUMMARY_MAX_CHARS",
    "search_invalid_penalty": "LOCAL_MEMORY_SEARCH_INVALID_PENALTY",
}


@dataclass(frozen=True)
class LocalMemorySettings:
    """Immutable settings snapshot for one ``LocalZep`` instance.

    Defaults match ``Config`` (spec §1.1). Construct directly in tests;
    use :meth:`from_config` in the application. The constructor raises
    ``ValueError`` for invalid values; ``from_config`` falls back to the
    default for an invalid value and logs a warning instead.
    """

    llm_model: str = ""
    llm_concurrency: int = 2
    llm_min_interval_seconds: float = 0.0
    llm_max_attempts: int = 3
    llm_max_tokens: int = 4096
    window_chars: int = 4000
    max_entities_per_window: int = 30
    max_relations_per_window: int = 50
    prompt_known_entities: int = 60
    prompt_existing_facts: int = 30
    max_failed_fraction: float = 0.5
    dedup_pass: str = "llm"
    ingestion_timeout_seconds: float = 1800.0
    lease_seconds: float = 180.0
    activity_mode: str = "rules"
    activity_group_size: int = 8
    activity_group_chars: int = 12000
    activity_group_wait_seconds: float = 15.0
    activity_max_pending_seconds: float = 300.0
    activity_max_llm_calls: int = 60
    summary_max_chars: int = 800
    search_invalid_penalty: float = 0.7
    # Internal knobs (not exposed through Config).
    pool_size: int = 8
    busy_timeout_ms: int = 10000
    heartbeat_seconds: float = 30.0

    def __post_init__(self) -> None:
        problems = _validate(self)
        if problems:
            raise ValueError("; ".join(problems))

    @classmethod
    def from_config(cls, config: Any = None, **overrides: Any) -> "LocalMemorySettings":
        """Build settings from ``Config`` (read at call time) plus overrides."""

        if config is None:
            from ..config import Config

            config = Config
        defaults = cls()
        values: dict[str, Any] = {}
        for name, attribute in _CONFIG_ATTRIBUTES.items():
            if hasattr(config, attribute):
                values[name] = getattr(config, attribute)
        values.update(overrides)

        accepted: dict[str, Any] = {}
        for name, value in values.items():
            candidate = {**accepted, name: _coerce(name, value, getattr(defaults, name, None))}
            try:
                cls(**candidate)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid local memory setting %s; using the default %r",
                    _CONFIG_ATTRIBUTES.get(name, name),
                    getattr(defaults, name, None),
                )
                continue
            accepted = candidate
        return cls(**accepted)

    def as_dict(self) -> dict[str, Any]:
        """Plain dict of every setting (for logs and diagnostics)."""

        return {field.name: getattr(self, field.name) for field in fields(self)}


def _coerce(name: str, value: Any, default: Any) -> Any:
    """Loosely convert ``value`` to the type of ``default`` (strings from env)."""

    if isinstance(default, str):
        text = "" if value is None else str(value).strip()
        return text if name == "llm_model" else text.lower()
    if isinstance(value, bool):
        return value  # bools are ints in Python; validation rejects them
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _validate(settings: LocalMemorySettings) -> list[str]:
    problems: list[str] = []

    def check_int(name: str, minimum: int) -> None:
        value = getattr(settings, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            problems.append(f"{name} must be an integer >= {minimum}")

    def check_float(name: str, minimum: float, maximum: float | None = None) -> None:
        value = getattr(settings, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{name} must be a number")
            return
        if value != value or value < minimum or (maximum is not None and value > maximum):
            bound = f">= {minimum}" if maximum is None else f"between {minimum} and {maximum}"
            problems.append(f"{name} must be {bound}")

    if not isinstance(settings.llm_model, str):
        problems.append("llm_model must be a string")
    for name in ("llm_concurrency", "llm_max_attempts", "llm_max_tokens", "window_chars",
                 "max_entities_per_window", "max_relations_per_window", "activity_group_size",
                 "activity_group_chars", "summary_max_chars", "pool_size"):
        check_int(name, 1)
    for name in ("prompt_known_entities", "prompt_existing_facts", "activity_max_llm_calls",
                 "busy_timeout_ms"):
        check_int(name, 0)
    check_float("llm_min_interval_seconds", 0.0)
    check_float("max_failed_fraction", 0.0, 1.0)
    check_float("ingestion_timeout_seconds", 1.0)
    check_float("lease_seconds", 1.0)
    check_float("activity_group_wait_seconds", 0.0)
    check_float("activity_max_pending_seconds", 0.0)
    check_float("search_invalid_penalty", 0.0, 1.0)
    check_float("heartbeat_seconds", 0.01)
    if settings.dedup_pass not in DEDUP_PASS_MODES:
        problems.append(f"dedup_pass must be one of {sorted(DEDUP_PASS_MODES)}")
    if settings.activity_mode not in ACTIVITY_MODES:
        problems.append(f"activity_mode must be one of {sorted(ACTIVITY_MODES)}")
    return problems
