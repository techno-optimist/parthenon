"""
Run the public site with waitress: the backend's API and the built frontend.

    python deploy/serve.py

The application is the backend's own (backend/wsgi.py create_application():
the Flask app with the frontend, /healthz and the /parthenon prefix). This
adds what the container needs around it:

- a refusal to start when PARTHENON_DATA_DIR is set but the uploads folder or
  the memory database would resolve outside it (so a copy of the app can
  never write into someone's own backend/uploads);
- waitress tuned for the edge in front of it: one process (the backend's
  background threads and simulation subprocesses assume one), a thread pool,
  a connection cap, a request body cap, and, with
  PARTHENON_TRUST_PROXY=1, the X-Forwarded-* headers left for the backend to
  read (waitress 3 strips them otherwise; CF-Connecting-IP always passes).

Settings (environment):
  PORT (10000), PARTHENON_HOST (0.0.0.0), PARTHENON_THREADS (24),
  WAITRESS_CONNECTION_LIMIT (200), WAITRESS_CHANNEL_TIMEOUT (120 s),
  WAITRESS_MAX_BODY (64 MB), PARTHENON_TRUST_PROXY, PARTHENON_DATA_DIR.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEPLOY_DIR = Path(__file__).resolve().parent
APP_DIR = DEPLOY_DIR.parent
BACKEND_DIR = APP_DIR / 'backend'

TRUE = ('1', 'true', 'yes', 'on')


def _flag(name: str) -> bool:
    return (os.environ.get(name) or '').strip().lower() in TRUE


def _int(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.environ.get(name) or '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f'serve: {name} is not an integer; using {default}', file=sys.stderr)
        return default
    return value if value >= minimum else default


def _inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def check_data_dir(config, data_dir: str | None, backend_dir: Path = BACKEND_DIR) -> list[str]:
    """Where the backend will write, checked against PARTHENON_DATA_DIR (empty list: fine)."""
    if not data_dir:
        return []
    problems = []
    uploads = os.path.join(data_dir, 'uploads')
    if os.path.realpath(config.UPLOAD_FOLDER) != os.path.realpath(uploads):
        problems.append(
            f'the uploads folder resolves to {os.path.realpath(config.UPLOAD_FOLDER)}, '
            f'not {os.path.realpath(uploads)}'
        )
    if not _inside(config.LOCAL_MEMORY_DB_PATH, data_dir):
        problems.append(f'the memory database {config.LOCAL_MEMORY_DB_PATH} is outside {data_dir}')
    legacy = Path(backend_dir) / 'uploads'
    if os.path.lexists(legacy) and os.path.realpath(legacy) != os.path.realpath(uploads):
        problems.append(f'{legacy} does not lead into {uploads}')
    return problems


def build_application():
    """The backend's WSGI application, after the data folder and the configuration check out."""
    sys.path.insert(0, str(BACKEND_DIR))
    from app.config import Config  # noqa: E402  (after the path is set)

    problems = check_data_dir(Config, os.environ.get('PARTHENON_DATA_DIR'))
    if problems:
        for problem in problems:
            print(f'serve: refusing to start: {problem}', file=sys.stderr)
        sys.exit(1)
    errors = Config.validate()
    if errors:
        print('serve: configuration errors:', file=sys.stderr)
        for error in errors:
            print(f'  - {error}', file=sys.stderr)
        sys.exit(1)
    for warning in Config.warnings():
        print(f'WARNING: {warning}', file=sys.stderr)

    import wsgi  # noqa: E402  (backend/wsgi.py)

    return wsgi.create_application()


def waitress_options() -> dict:
    trust_proxy = _flag('PARTHENON_TRUST_PROXY')
    return {
        'host': (os.environ.get('PARTHENON_HOST') or '0.0.0.0').strip(),
        'port': _int('PORT', 10000),
        'threads': _int('PARTHENON_THREADS', 24),
        'connection_limit': _int('WAITRESS_CONNECTION_LIMIT', 200),
        'channel_timeout': _int('WAITRESS_CHANNEL_TIMEOUT', 120),
        # Waitress buffers a request body before the app sees it; the backend
        # caps uploads at 50 MB (MAX_CONTENT_LENGTH).
        'max_request_body_size': _int('WAITRESS_MAX_BODY', 64 * 1024 * 1024),
        # Waitress 3 strips X-Forwarded-For and friends unless told otherwise;
        # the backend reads the client address itself (CF-Connecting-IP, then
        # the first X-Forwarded-For) when PARTHENON_TRUST_PROXY=1.
        'clear_untrusted_proxy_headers': not trust_proxy,
        'ident': 'parthenon',
    }


def main() -> int:
    application = build_application()
    from waitress import serve

    options = waitress_options()
    base = (os.environ.get('PARTHENON_BASE') or '/parthenon').rstrip('/')
    print(
        f"serve: parthenon on http://{options['host']}:{options['port']}{base}/ ({options['threads']} threads)",
        flush=True,
    )
    serve(application, **options)
    return 0


if __name__ == '__main__':
    sys.exit(main())
