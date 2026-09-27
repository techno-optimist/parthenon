"""
The public steps' entry: waitress serving the API and the built frontend.

    python wsgi.py

listens on 0.0.0.0:$PORT (10000 by default) and serves, under
PARTHENON_BASE (/parthenon) and at the root alike:

    /parthenon/             the frontend (index.html; the Vue router's pages too)
    /parthenon/assets/*     the built bundle, cached for a year
    /parthenon/media/*      the footage, paintings and sound, with Range
    /parthenon/api/*        the API
    /parthenon/healthz      {"status": "ok"}

The frontend is read from PARTHENON_FRONTEND_DIR (default ../frontend/dist,
else /app/frontend/dist). `waitress-serve --call wsgi:create_application`
serves the same thing.

One process, many threads (PARTHENON_THREADS, default 24): the backend's
background work (builds, runs, films) and its simulation subprocesses belong
to the process that started them, so it must never be forked into workers.
Gatherings take minutes to begin and questions can take a few, so there are
enough threads that the pages keep loading meanwhile.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.public import load_settings  # noqa: E402
from app.public.site import PrefixMiddleware, register_site  # noqa: E402


DEFAULT_PORT = 10000
DEFAULT_THREADS = 24


def create_application():
    """The WSGI application: the Flask app with the frontend, under the base and at the root.

    The Flask app itself is the returned object's .app.
    """

    settings = load_settings()
    app = create_app()
    register_site(app, settings.frontend_dir)
    return PrefixMiddleware(app, settings.base)


def _int_env(name, default):
    try:
        value = int(os.environ.get(name) or default)
    except ValueError:
        return default
    return value if value > 0 else default


def main():
    errors = Config.validate()
    if errors:
        print('Configuration errors:')
        for error in errors:
            print(f'  - {error}')
        sys.exit(1)
    for warning in Config.warnings():
        print(f'WARNING: {warning}')

    from waitress import serve

    application = create_application()
    serve(
        application,
        host=os.environ.get('HOST') or '0.0.0.0',
        port=_int_env('PORT', DEFAULT_PORT),
        threads=_int_env('PARTHENON_THREADS', DEFAULT_THREADS),
        ident='parthenon',
    )


if __name__ == '__main__':
    main()
