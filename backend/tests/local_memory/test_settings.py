"""LocalMemorySettings and the LOCAL_MEMORY_* Config attributes."""

from __future__ import annotations

import logging
import os
from dataclasses import fields

import pytest

import app.config as config_module
from app.config import Config
from app.memory import LocalMemorySettings
from app.memory.settings import _CONFIG_ATTRIBUTES


def test_defaults_match_config_defaults():
    defaults = LocalMemorySettings()
    for name, attribute in _CONFIG_ATTRIBUTES.items():
        assert hasattr(Config, attribute), attribute
    assert defaults.llm_concurrency == 2
    assert defaults.window_chars == 4000
    assert defaults.max_failed_fraction == 0.5
    assert defaults.ingestion_timeout_seconds == 1800.0
    assert defaults.activity_mode == "rules"
    assert defaults.dedup_pass == "llm"
    assert defaults.search_invalid_penalty == 0.7


def test_from_config_reads_class_attributes_at_call_time(monkeypatch):
    monkeypatch.setattr(Config, "LOCAL_MEMORY_LLM_CONCURRENCY", 5)
    monkeypatch.setattr(Config, "LOCAL_MEMORY_ACTIVITY_MODE", "LLM")
    monkeypatch.setattr(Config, "LOCAL_MEMORY_LLM_MODEL", " grok-4 ")
    monkeypatch.setattr(Config, "LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS", "3.5")

    settings = LocalMemorySettings.from_config()

    assert settings.llm_concurrency == 5
    assert settings.activity_mode == "llm"
    assert settings.llm_model == "grok-4"
    assert settings.llm_min_interval_seconds == 3.5


def test_from_config_falls_back_to_defaults_for_invalid_values(monkeypatch, caplog):
    monkeypatch.setattr(Config, "LOCAL_MEMORY_ACTIVITY_MODE", "sometimes")
    monkeypatch.setattr(Config, "LOCAL_MEMORY_DEDUP_PASS", "maybe")
    monkeypatch.setattr(Config, "LOCAL_MEMORY_WINDOW_CHARS", 0)
    monkeypatch.setattr(Config, "LOCAL_MEMORY_MAX_FAILED_FRACTION", 3)
    # The "mirofish" logger does not propagate to root, so listen on the module logger.
    logger = logging.getLogger("mirofish.memory.settings")
    logger.addHandler(caplog.handler)
    try:
        settings = LocalMemorySettings.from_config()
    finally:
        logger.removeHandler(caplog.handler)

    defaults = LocalMemorySettings()
    assert settings.activity_mode == defaults.activity_mode
    assert settings.dedup_pass == defaults.dedup_pass
    assert settings.window_chars == defaults.window_chars
    assert settings.max_failed_fraction == defaults.max_failed_fraction
    assert "LOCAL_MEMORY_ACTIVITY_MODE" in caplog.text


def test_from_config_accepts_overrides():
    settings = LocalMemorySettings.from_config(llm_concurrency=1, lease_seconds=5)
    assert settings.llm_concurrency == 1
    assert settings.lease_seconds == 5.0


@pytest.mark.parametrize("kwargs", [
    {"llm_concurrency": 0},
    {"activity_mode": "sometimes"},
    {"dedup_pass": "on"},
    {"max_failed_fraction": 1.5},
    {"search_invalid_penalty": -0.1},
    {"window_chars": True},
    {"lease_seconds": 0},
])
def test_constructor_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        LocalMemorySettings(**kwargs)


def test_settings_are_immutable_and_serializable():
    settings = LocalMemorySettings()
    with pytest.raises(Exception):
        settings.llm_concurrency = 3  # type: ignore[misc]
    assert set(settings.as_dict()) == {field.name for field in fields(settings)}


def test_config_env_parsing_is_defensive(monkeypatch):
    monkeypatch.setenv("PARTHENON_TEST_INT", "not-a-number")
    assert config_module._env_int("PARTHENON_TEST_INT", 2, minimum=1) == 2
    monkeypatch.setenv("PARTHENON_TEST_INT", "0")
    assert config_module._env_int("PARTHENON_TEST_INT", 2, minimum=1) == 2
    monkeypatch.setenv("PARTHENON_TEST_INT", " 7 ")
    assert config_module._env_int("PARTHENON_TEST_INT", 2, minimum=1) == 7

    for bad in ("nan", "inf", "-5", "x"):
        monkeypatch.setenv("PARTHENON_TEST_FLOAT", bad)
        assert config_module._env_float("PARTHENON_TEST_FLOAT", 0.5, minimum=0.0) == 0.5
    monkeypatch.setenv("PARTHENON_TEST_FLOAT", "3.5")
    assert config_module._env_float("PARTHENON_TEST_FLOAT", 0.5, minimum=0.0) == 3.5

    monkeypatch.setenv("PARTHENON_TEST_STR", "   ")
    assert config_module._env_str("PARTHENON_TEST_STR", "auto") == "auto"
    monkeypatch.setenv("PARTHENON_TEST_STR", " Local ")
    assert config_module._env_str("PARTHENON_TEST_STR", "auto") == "Local"
    monkeypatch.delenv("PARTHENON_TEST_STR")
    assert config_module._env_str("PARTHENON_TEST_STR", "auto") == "auto"


def test_default_db_path_is_under_uploads_memory():
    if os.environ.get("LOCAL_MEMORY_DB_PATH"):
        pytest.skip("LOCAL_MEMORY_DB_PATH is set in the environment")
    expected = os.path.normpath(os.path.join(Config.UPLOAD_FOLDER, "memory", "local_memory.sqlite3"))
    assert Config.LOCAL_MEMORY_DB_PATH == expected
    assert Config.LOCAL_MEMORY_DB_PATH.endswith(os.path.join("uploads", "memory", "local_memory.sqlite3"))


@pytest.mark.parametrize("mode, key, expected", [
    ("auto", None, "local"),
    ("auto", "PASTE_YOUR_KEY_HERE", "local"),
    ("auto", "z_real_key", "zep"),
    ("local", "z_real_key", "local"),
    ("zep", None, "zep"),
    (" ZEP ", None, "zep"),
])
def test_memory_backend_resolution(monkeypatch, mode, key, expected):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", mode)
    monkeypatch.setattr(Config, "ZEP_API_KEY", key)
    assert Config.memory_backend() == expected


def test_memory_backend_explicit_key_and_invalid_mode(monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "auto")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    assert Config.memory_backend(" test-key ") == "zep"
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "cloud")
    with pytest.raises(ValueError):
        Config.memory_backend()
