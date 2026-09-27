"""
The steps as one site: the API and the built frontend under /parthenon.

PrefixMiddleware serves the same Flask app under PARTHENON_BASE (/parthenon)
and at the root, so /parthenon/api/... and /api/... are the same route (the
edge proxies the first; health checks may use either). The API's own URLs
stay backend-relative (/api/...): the page puts its base in front.

register_site() adds the frontend: /healthz, the built files (hashed
/assets/* cached for a year, /media/* for a day, with Range), and every
other path answered with index.html (the Vue router's history mode).
"""

import mimetypes
import os
from typing import Optional

from flask import Blueprint, current_app, jsonify, send_from_directory
from werkzeug.security import safe_join

from .words import refusal


for _extension, _type in (
    ('.webp', 'image/webp'), ('.avif', 'image/avif'), ('.woff2', 'font/woff2'),
    ('.woff', 'font/woff'), ('.vtt', 'text/vtt'), ('.m4a', 'audio/mp4'),
    ('.webm', 'video/webm'), ('.mjs', 'text/javascript'), ('.js', 'text/javascript'),
    ('.webmanifest', 'application/manifest+json'), ('.wasm', 'application/wasm'),
    ('.opus', 'audio/ogg'), ('.svg', 'image/svg+xml'), ('.mp3', 'audio/mpeg'),
    ('.mp4', 'video/mp4'), ('.json', 'application/json'),
):
    mimetypes.add_type(_type, _extension)

ASSET_MAX_AGE = 31536000  # hashed by Vite: a new build has new names
MEDIA_MAX_AGE = 86400
FILE_MAX_AGE = 3600
INDEX = 'index.html'


class PrefixMiddleware:
    """Serve one WSGI app under `base` and at the root; `base` alone redirects to `base/`."""

    def __init__(self, app, base: str):
        self.app = app
        self.base = base or ''

    def __call__(self, environ, start_response):
        base = self.base
        if base:
            path = environ.get('PATH_INFO') or '/'
            if path == base:
                query = environ.get('QUERY_STRING') or ''
                location = f'{base}/' + (f'?{query}' if query else '')
                start_response('308 Permanent Redirect', [
                    ('Location', location), ('Content-Length', '0'), ('Cache-Control', 'no-cache'),
                ])
                return [b'']
            if path.startswith(base + '/'):
                environ = dict(environ)
                environ['PATH_INFO'] = path[len(base):]
                environ['parthenon.prefixed'] = True
        return self.app(environ, start_response)


def _frontend_dir() -> str:
    return current_app.extensions['parthenon_site']['frontend_dir']


def _index():
    folder = _frontend_dir()
    if not os.path.isfile(os.path.join(folder, INDEX)):
        return refusal(503, 'stepsNotBuilt')
    response = send_from_directory(folder, INDEX, max_age=0)
    response.headers['Cache-Control'] = 'no-cache'
    return response


def _looks_like_a_file(path: str) -> bool:
    last = path.rsplit('/', 1)[-1]
    return '.' in last and not last.startswith('.')


site_bp = Blueprint('site', __name__)


@site_bp.route('/healthz', methods=['GET', 'HEAD'])
def healthz():
    return jsonify({'status': 'ok', 'service': 'parthenon'})


@site_bp.route('/', methods=['GET', 'HEAD'])
def index():
    return _index()


@site_bp.route('/<path:path>', methods=['GET', 'HEAD'])
def page(path: str):
    if path == 'api' or path.startswith('api/'):
        return refusal(404, 'notFound')
    folder = _frontend_dir()
    found: Optional[str] = safe_join(folder, path)
    if found and os.path.isfile(found):
        if path == INDEX:
            return _index()
        if path.startswith('assets/'):
            max_age = ASSET_MAX_AGE
        elif path.startswith('media/'):
            max_age = MEDIA_MAX_AGE
        else:
            max_age = FILE_MAX_AGE
        response = send_from_directory(folder, path, max_age=max_age, conditional=True)
        if max_age == ASSET_MAX_AGE:
            response.headers['Cache-Control'] = f'public, max-age={ASSET_MAX_AGE}, immutable'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    if _looks_like_a_file(path):
        return refusal(404, 'notFound')
    return _index()  # a page of the Vue router


def register_site(app, frontend_dir: str) -> None:
    """Serve the built frontend and /healthz from this app (after the API's blueprints)."""

    if 'parthenon_site' in app.extensions:
        return
    app.extensions['parthenon_site'] = {'frontend_dir': os.path.abspath(frontend_dir)}
    app.register_blueprint(site_bp)
