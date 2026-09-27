"""
Records on disk that are read while they are written.

The project, crowd and Chronicle records (project.json, state.json,
run_state.json, meta.json, ...) are rewritten while the page polls them from
other threads. Written in place (open 'w', then json.dump), a reader can
catch the file empty or half written and fail on it. write_json_atomic()
writes the same bytes to a temporary file beside the record and moves it into
place with os.replace, so a reader sees the old record or the new one, never
a torn one. read_json() reads one, trying once more when it catches a torn
file written some other way.
"""

import json
import os
import tempfile
import time
from typing import Any

# A new record gets the mode open(path, 'w') gives under the usual umask.
NEW_FILE_MODE = 0o644
# How long a reader waits before trying a torn file again.
RETRY_DELAY_SECONDS = 0.05


def write_json_atomic(path: str, data: Any, *, ensure_ascii: bool = False, indent: Any = 2) -> None:
    """json.dump(data) into path, all at once (the bytes are those json.dump would write)."""

    folder = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = NEW_FILE_MODE
    handle, temp_path = tempfile.mkstemp(prefix=f'.{base}.', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            json.dump(data, out, ensure_ascii=ensure_ascii, indent=indent)
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def read_json(path: str, *, retries: int = 1) -> Any:
    """json.load(path), tried again `retries` times when the file is caught half written.

    OSError (no such file) is raised at once; a JSON error is raised when the
    last try still fails.
    """

    attempt = 0
    while True:
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except json.JSONDecodeError:
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(RETRY_DELAY_SECONDS)
