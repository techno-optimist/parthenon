"""The public steps as one site: /parthenon, the built frontend, /healthz, wsgi.py and the data folder."""

import json
import os
import subprocess
import sys

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

from app import create_app
from app.api import parthenon as parthenon_api
from app.config import Config
from app.models.project import ProjectManager
from app.public.settings import load_settings, normalize_base, parse_max_run
from app.public.site import PrefixMiddleware, register_site
from app.services.report_agent import ReportManager


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = '<!doctype html><title>Parthenon</title><div id="app"></div>'


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / 'dist'
    (folder / 'assets').mkdir(parents=True)
    (folder / 'media' / 'hero').mkdir(parents=True)
    (folder / 'index.html').write_text(INDEX_HTML)
    (folder / 'assets' / 'index-abc123.js').write_text('console.log("steps")')
    (folder / 'media' / 'hero' / 'dawn.mp4').write_bytes(bytes(range(256)) * 8)
    (folder / 'icon.png').write_bytes(b'\x89PNG\r\n')
    return folder


@pytest.fixture
def public_env(tmp_path, monkeypatch, dist):
    for name in list(os.environ):
        if name.startswith('PARTHENON_'):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PARTHENON_PUBLIC', '1')
    monkeypatch.setenv('PARTHENON_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('PARTHENON_FRONTEND_DIR', str(dist))
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'data' / 'uploads' / 'projects'))
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(tmp_path / 'data' / 'uploads' / 'reports'))
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path / 'data' / 'uploads'))
    monkeypatch.setattr(Config, 'LOCAL_MEMORY_DB_PATH', str(tmp_path / 'memory.sqlite3'))
    monkeypatch.setattr(Config, 'LLM_BASE_URL', 'https://llm.example.test/v1')
    monkeypatch.setattr(parthenon_api, '_zep_key_status', lambda: (True, None))
    return tmp_path


@pytest.fixture
def site(public_env, dist):
    app = create_app()
    app.config.update(TESTING=True)
    register_site(app, str(dist))
    return Client(PrefixMiddleware(app, '/parthenon'), Response)


def test_the_base_alone_goes_to_the_steps(site):
    response = site.get('/parthenon?x=1')
    assert response.status_code == 308
    assert response.headers['Location'] == '/parthenon/?x=1'


def test_the_steps_are_the_index(site):
    response = site.get('/parthenon/')
    assert response.status_code == 200
    assert 'Parthenon' in response.get_data(as_text=True)
    assert response.headers['Cache-Control'] == 'no-cache'
    assert response.mimetype == 'text/html'


def test_router_pages_fall_back_to_the_index(site):
    for path in ('/parthenon/process/proj_abc', '/parthenon/simulation/sim_x/start', '/parthenon/report/r'):
        response = site.get(path)
        assert response.status_code == 200, path
        assert 'Parthenon' in response.get_data(as_text=True)


def test_assets_are_kept_for_a_year(site):
    response = site.get('/parthenon/assets/index-abc123.js')
    assert response.status_code == 200
    assert 'immutable' in response.headers['Cache-Control']
    assert 'max-age=31536000' in response.headers['Cache-Control']
    assert response.mimetype == 'text/javascript'


def test_media_answers_ranges(site):
    response = site.get('/parthenon/media/hero/dawn.mp4', headers={'Range': 'bytes=0-99'})
    assert response.status_code == 206
    assert len(response.get_data()) == 100
    assert response.mimetype == 'video/mp4'
    assert 'max-age=86400' in response.headers['Cache-Control']


def test_a_missing_file_is_not_the_index(site):
    response = site.get('/parthenon/media/hero/missing.jpg')
    assert response.status_code == 404
    assert response.json['success'] is False


def test_no_way_out_of_the_frontend_folder(site):
    for path in ('/parthenon/../data/parthenon_public.sqlite3', '/parthenon/%2e%2e/secret.txt'):
        response = site.get(path)
        assert response.status_code in (200, 404)
        assert b'SQLite' not in response.get_data()


def test_the_api_under_the_base_and_at_the_root(site):
    under = site.get('/parthenon/api/parthenon/status')
    root = site.get('/api/parthenon/status')
    assert under.status_code == 200 and root.status_code == 200
    assert under.json['data']['public'] is True
    missing = site.get('/parthenon/api/nothing')
    assert missing.status_code == 404 and missing.json['success'] is False


def test_healthz(site):
    for path in ('/parthenon/healthz', '/healthz', '/parthenon/health'):
        response = site.get(path)
        assert response.status_code == 200, path
        assert response.json['status'] == 'ok'


def test_steps_not_built(public_env, tmp_path):
    app = create_app()
    register_site(app, str(tmp_path / 'nowhere'))
    response = Client(PrefixMiddleware(app, '/parthenon'), Response).get('/parthenon/')
    assert response.status_code == 503
    assert response.json['success'] is False


def test_wsgi_builds_the_whole_site(public_env, dist):
    sys.path.insert(0, BACKEND_DIR)
    import wsgi

    application = wsgi.create_application()

    assert isinstance(application, PrefixMiddleware)
    assert application.base == '/parthenon'
    client = Client(application, Response)
    assert client.get('/parthenon/').status_code == 200
    assert client.get('/parthenon/healthz').json['status'] == 'ok'


def test_the_owner_machine_serves_no_site(monkeypatch):
    monkeypatch.delenv('PARTHENON_PUBLIC', raising=False)
    app = create_app()
    assert 'site.index' not in app.view_functions


def test_settings_defaults(monkeypatch):
    settings = load_settings({})
    assert settings.public is False
    assert settings.base == '/parthenon'
    assert settings.daily_gatherings == 12 and settings.per_visitor == 2
    assert settings.max_citizens == 12 and settings.max_run == 'day' and settings.max_run_rounds == 24
    assert settings.concurrent_runs == 1 and settings.questions_per_hour == 30
    assert settings.max_scroll_chars == 20000
    assert settings.featured == ('proj_527f80721255', 'proj_ce8edd07eb88')
    assert 'hush' not in repr(load_settings({'PARTHENON_ADMIN_KEY': 'hush'}))


def test_settings_parse():
    assert normalize_base('/parthenon/') == '/parthenon'
    assert normalize_base('parthenon') == '/parthenon'
    assert normalize_base('/') == '' and normalize_base('') == ''
    assert parse_max_run('week') == ('week', 168)
    assert parse_max_run('THREEDAYS') == ('threeDays', 72)
    assert parse_max_run('12') == ('afternoon', 12)
    assert parse_max_run('36') == (36, 36)
    assert parse_max_run('forever') == ('day', 24)
    assert parse_max_run('-3') == ('day', 24)
    settings = load_settings({
        'PARTHENON_PUBLIC': 'true', 'PARTHENON_DAILY_GATHERINGS': 'lots', 'PARTHENON_FEATURED': ' proj_a, ,proj_b,proj_a',
        'PARTHENON_DATA_DIR': '/data', 'PARTHENON_BASE': '/',
    })
    assert settings.public is True
    assert settings.daily_gatherings == 12  # not a number: the default
    assert settings.featured == ('proj_a', 'proj_b')
    assert settings.db_path == os.path.join('/data', 'parthenon_public.sqlite3')
    assert settings.base == ''
    assert load_settings({'PARTHENON_FEATURED': ''}).featured == ()


PATHS_SCRIPT = """
import json
from app.config import Config
from app.models.project import ProjectManager
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import SimulationRunner
from app.services import citizen_portraits
print(json.dumps({
    'upload': Config.UPLOAD_FOLDER,
    'simulations': Config.OASIS_SIMULATION_DATA_DIR,
    'manager': SimulationManager.SIMULATION_DATA_DIR,
    'runner': SimulationRunner.RUN_STATE_DIR,
    'projects': ProjectManager.PROJECTS_DIR,
    'reports': ReportManager.REPORTS_DIR,
    'memory': Config.LOCAL_MEMORY_DB_PATH,
    'voices': citizen_portraits.voices_folder(),
}))
"""


def _paths(extra_env):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('PARTHENON_') and key != 'LOCAL_MEMORY_DB_PATH'}
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, '-c', PATHS_SCRIPT], cwd=BACKEND_DIR, env=env,
        capture_output=True, text=True, timeout=240,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_data_folder_moves_everything(tmp_path):
    data = str(tmp_path / 'data')
    paths = _paths({'PARTHENON_DATA_DIR': data})
    uploads = os.path.join(data, 'uploads')
    assert paths['upload'] == uploads
    for key in ('simulations', 'manager', 'runner'):
        assert paths[key] == os.path.join(uploads, 'simulations'), key
    assert paths['projects'] == os.path.join(uploads, 'projects')
    assert paths['reports'] == os.path.join(uploads, 'reports')
    assert paths['memory'] == os.path.join(uploads, 'memory', 'local_memory.sqlite3')
    assert paths['voices'] == os.path.join(uploads, 'voices')


def test_without_a_data_folder_the_paths_are_the_old_ones():
    paths = _paths({})
    app_dir = os.path.join(BACKEND_DIR, 'app')
    services = os.path.join(app_dir, 'services')
    assert paths['upload'] == os.path.join(app_dir, '../uploads')
    assert paths['simulations'] == os.path.join(app_dir, '../uploads/simulations')
    assert paths['manager'] == os.path.join(services, '../../uploads/simulations')
    assert paths['runner'] == os.path.join(services, '../../uploads/simulations')
    assert os.path.normpath(paths['projects']) == os.path.join(BACKEND_DIR, 'uploads', 'projects')
