import atexit
import logging
import os
import shutil
import tempfile

import pytest

# Importing app creates the "mirofish" loggers, each with a file handler in
# backend/logs: the same daily file the running backend writes. Point them,
# and every logger created later, at a throwaway directory so test runs never
# add lines (fake simulation IDs, simulated reconciliations) to the live log.
from app.utils import logger as logger_utils

_TEST_LOG_DIR = tempfile.mkdtemp(prefix="parthenon-test-logs-")
atexit.register(shutil.rmtree, _TEST_LOG_DIR, True)


def _redirect_file_logging(log_dir):
    real_dir = os.path.realpath(logger_utils.LOG_DIR)
    logger_utils.LOG_DIR = log_dir
    for candidate in list(logging.Logger.manager.loggerDict.values()):
        if not isinstance(candidate, logging.Logger):
            continue
        for handler in list(candidate.handlers):
            if not isinstance(handler, logging.FileHandler):
                continue
            if os.path.dirname(os.path.realpath(handler.baseFilename)) != real_dir:
                continue
            replacement = logging.FileHandler(
                os.path.join(log_dir, os.path.basename(handler.baseFilename)),
                encoding="utf-8",
            )
            replacement.setLevel(handler.level)
            replacement.setFormatter(handler.formatter)
            candidate.removeHandler(handler)
            handler.close()
            candidate.addHandler(replacement)


_redirect_file_logging(_TEST_LOG_DIR)

from app.config import Config  # noqa: E402
from app.utils import locale as locale_utils  # noqa: E402


@pytest.fixture(autouse=True)
def _pin_cloud_memory_backend(monkeypatch):
    """Legacy suites assert Zep Cloud semantics; local-backend tests opt in explicitly."""

    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep", raising=False)


@pytest.fixture(autouse=True)
def _isolate_simulation_data(monkeypatch, tmp_path_factory):
    """Keep every test away from the real uploads/simulations directory.

    create_app() reconciles interrupted runs on startup and the runner syncs
    state.json through SimulationManager; both default to real user data.
    Tests that need their own layout still monkeypatch these attributes.
    """

    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner

    root = str(tmp_path_factory.mktemp("simulations"))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", root)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", root)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", root)


@pytest.fixture(autouse=True)
def _default_thread_locale():
    """Start and end every test on the default ('zh') thread locale.

    Background jobs call set_locale() on their own thread. A test that runs
    such a job inline (the chronicle film pipeline, for one) would otherwise
    leave its locale on the main thread for every later test, and simulation
    episode text follows the thread locale.
    """

    vars(locale_utils._thread_local).pop("locale", None)
    yield
    vars(locale_utils._thread_local).pop("locale", None)
