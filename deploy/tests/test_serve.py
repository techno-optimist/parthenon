"""deploy/serve.py: the waitress settings and the data folder check."""

from __future__ import annotations

import types

import pytest
from werkzeug.test import Client

import serve


# --------------------------------------------------------------------------- serve


def test_waitress_keeps_forwarded_headers_only_behind_a_trusted_proxy(monkeypatch):
    for name in ('PARTHENON_TRUST_PROXY', 'PORT', 'PARTHENON_THREADS', 'PARTHENON_HOST'):
        monkeypatch.delenv(name, raising=False)
    options = serve.waitress_options()
    assert options['clear_untrusted_proxy_headers'] is True
    assert options['port'] == 10000 and options['host'] == '0.0.0.0' and options['threads'] == 24
    monkeypatch.setenv('PARTHENON_TRUST_PROXY', '1')
    monkeypatch.setenv('PORT', '8091')
    monkeypatch.setenv('PARTHENON_THREADS', 'many')
    options = serve.waitress_options()
    assert options['clear_untrusted_proxy_headers'] is False
    assert options['port'] == 8091 and options['threads'] == 24


def test_waitress_hands_cf_connecting_ip_and_forwarded_for_through(monkeypatch):
    """What the backend gets for the client address, through waitress's own header handling."""
    pytest.importorskip('waitress')
    from waitress.proxy_headers import proxy_headers_middleware

    monkeypatch.setenv('PARTHENON_TRUST_PROXY', '1')
    seen = {}

    def backend(environ, start_response):
        seen.update(environ)
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'ok']

    options = serve.waitress_options()
    app = proxy_headers_middleware(backend, clear_untrusted=options['clear_untrusted_proxy_headers'])
    edge = {'REMOTE_ADDR': '10.0.0.7'}
    Client(app).get('/', headers={'CF-Connecting-IP': '203.0.113.9', 'X-Forwarded-For': '198.51.100.1'},
                    environ_base=edge)
    assert seen['HTTP_CF_CONNECTING_IP'] == '203.0.113.9'
    assert seen['HTTP_X_FORWARDED_FOR'] == '198.51.100.1'
    monkeypatch.delenv('PARTHENON_TRUST_PROXY')
    seen.clear()
    app = proxy_headers_middleware(backend, clear_untrusted=serve.waitress_options()['clear_untrusted_proxy_headers'])
    Client(app).get('/', headers={'CF-Connecting-IP': '203.0.113.9', 'X-Forwarded-For': '198.51.100.1'},
                    environ_base=edge)
    assert seen['HTTP_CF_CONNECTING_IP'] == '203.0.113.9'
    assert 'HTTP_X_FORWARDED_FOR' not in seen


def test_serve_refuses_a_backend_that_would_write_outside_the_data_folder(tmp_path):
    data = tmp_path / 'data'
    (data / 'uploads').mkdir(parents=True)
    backend = tmp_path / 'app' / 'backend'
    elsewhere = backend / 'uploads'
    elsewhere.mkdir(parents=True)
    config = types.SimpleNamespace(
        UPLOAD_FOLDER=str(elsewhere), LOCAL_MEMORY_DB_PATH=str(elsewhere / 'memory' / 'db.sqlite3')
    )
    problems = serve.check_data_dir(config, str(data), backend)
    assert len(problems) == 3
    # The container: backend/uploads is a link onto the disk, and the backend's own paths agree.
    elsewhere.rmdir()
    elsewhere.symlink_to(data / 'uploads')
    config = types.SimpleNamespace(
        UPLOAD_FOLDER=str(data / 'uploads'),
        LOCAL_MEMORY_DB_PATH=str(data / 'uploads' / 'memory' / 'local_memory.sqlite3'),
    )
    assert serve.check_data_dir(config, str(data), backend) == []
    config.UPLOAD_FOLDER = str(elsewhere / '..' / 'uploads')  # through the link
    assert serve.check_data_dir(config, str(data), backend) == []
    assert serve.check_data_dir(config, None, backend) == []
    # A copy of the app next to someone's own uploads folder never starts.
    elsewhere.unlink()
    (elsewhere / 'projects').mkdir(parents=True)
    config.UPLOAD_FOLDER = str(data / 'uploads')
    assert serve.check_data_dir(config, str(data), backend) == [f'{elsewhere} does not lead into {data / "uploads"}']
