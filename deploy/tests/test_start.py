"""deploy/start.py (the entrypoint) and deploy/cpu_torch.py (the image's torch)."""

from __future__ import annotations

import http.server
import json
import os
import stat
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
import types
from pathlib import Path

import pytest

import cpu_torch
import start
from start import StartError, Supervisor

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- environment


def test_child_env_defaults_point_everything_into_the_data_folder(tmp_path):
    env = start.child_env({'PATH': '/bin'}, tmp_path, 8091, 5057)
    assert env['PARTHENON_DATA_DIR'] == str(tmp_path)
    assert env['PORT'] == '8091'
    assert env['GROK_BRIDGE_HOST'] == '127.0.0.1' and env['GROK_BRIDGE_PORT'] == '5057'
    assert env['LLM_BASE_URL'] == 'http://127.0.0.1:5057/v1'
    assert env['LLM_API_KEY'] and env['LLM_MODEL_NAME'] == 'parthenon-free'
    assert env['LOCAL_MEMORY_DB_PATH'] == str(tmp_path / 'uploads' / 'memory' / 'local_memory.sqlite3')
    assert env['HF_HOME'] == str(tmp_path / 'cache' / 'huggingface')
    assert env['GROK_BRIDGE_TOKEN_FILE'] == str(tmp_path / 'grok-oauth.json')
    assert env['MEMORY_BACKEND'] == 'local'
    assert env['PARTHENON_UPSTREAM'] == 'auto' and env['PARTHENON_BASE'] == '/parthenon'
    assert env['FLASK_DEBUG'] == 'false'
    assert env['PARTHENON_FRONTEND_DIR'].endswith('/frontend/dist')
    assert env['LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS'] == '3.5'  # auto without keys: OpenRouter's free tier
    assert env['PATH'] == '/bin'


def test_child_env_keeps_explicit_settings_but_never_a_public_bridge(tmp_path):
    env = start.child_env({
        'LLM_MODEL_NAME': 'mine', 'PARTHENON_UPSTREAM': 'xai', 'XAI_API_KEY': 'k',
        'GROK_BRIDGE_HOST': '0.0.0.0', 'FLASK_DEBUG': 'true', 'LOCAL_MEMORY_DB_PATH': '/elsewhere.db',
    }, tmp_path, 10000, 5055)
    assert env['LLM_MODEL_NAME'] == 'mine' and env['PARTHENON_UPSTREAM'] == 'xai'
    assert env['LOCAL_MEMORY_DB_PATH'] == '/elsewhere.db'
    assert env['GROK_BRIDGE_HOST'] == '127.0.0.1'
    assert env['FLASK_DEBUG'] == 'false'
    assert 'LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS' not in env


@pytest.mark.parametrize('environ, expected', [
    ({}, 'openrouter'),
    ({'PARTHENON_UPSTREAM': 'auto', 'ANTHROPIC_API_KEY': 'a', 'OPENAI_API_KEY': 'o'}, 'openai'),
    ({'XAI_API_KEY': 'x', 'OPENAI_API_KEY': 'o'}, 'xai'),
    ({'XAI_API_KEY': '  '}, 'openrouter'),
    ({'PARTHENON_UPSTREAM': 'Grok'}, 'grok'),
])
def test_effective_upstream_matches_the_bridges_auto(environ, expected):
    assert start.effective_upstream(environ) == expected


def _signed_in(path: Path, **extra) -> Path:
    path.write_text(json.dumps({'access_token': 'fake-access', 'refresh_token': 'fake-refresh', **extra}))
    return path


def test_auto_prefers_the_grok_sign_in_over_every_key(tmp_path):
    token = tmp_path / 'grok-oauth.json'
    keys = {'GROK_BRIDGE_TOKEN_FILE': str(token), 'XAI_API_KEY': 'x', 'OPENAI_API_KEY': 'o'}
    assert start.effective_upstream(keys) == 'xai'  # no sign-in yet
    _signed_in(token)
    assert start.effective_upstream(keys) == 'grok'
    assert start.effective_upstream({**keys, 'PARTHENON_UPSTREAM': 'openai'}) == 'openai'  # a choice stays
    _signed_in(token, revoked='invalid_grant')
    assert start.effective_upstream(keys) == 'xai'
    assert start.effective_upstream({'GROK_BRIDGE_TOKEN_FILE': str(token)}) == 'openrouter'
    token.write_text('{broken')
    assert start.effective_upstream({'GROK_BRIDGE_TOKEN_FILE': str(token)}) == 'openrouter'


def test_child_env_paces_the_hearing_only_for_the_free_models(tmp_path):
    assert start.child_env({}, tmp_path, 10000, 5055)['LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS'] == '3.5'
    _signed_in(tmp_path / 'grok-oauth.json')  # the default sign-in file
    env = start.child_env({}, tmp_path, 10000, 5055)
    assert 'LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS' not in env
    assert start.describe_upstream(env, start.effective_upstream(env)) == 'auto: the Grok subscription'


def test_the_render_blueprint_signs_in_where_the_entrypoint_looks():
    yaml = pytest.importorskip('yaml')
    service = yaml.safe_load((REPO / 'render.yaml').read_text())['services'][0]
    env = {item['key']: item for item in service['envVars']}
    data = Path(env['PARTHENON_DATA_DIR']['value'])
    assert service['disk']['mountPath'] == str(data)
    token = env['GROK_BRIDGE_TOKEN_FILE']['value']
    assert token == '/data/grok-oauth.json' == str(start.default_sign_in_file(data))
    assert start.sign_in_file({'GROK_BRIDGE_TOKEN_FILE': token}, data) == Path(token)
    assert env['PARTHENON_UPSTREAM']['value'] == 'auto'
    assert env['PARTHENON_INVITE_CODE'] == {'key': 'PARTHENON_INVITE_CODE', 'generateValue': True}
    assert env['PARTHENON_CONCURRENT_RUNS']['value'] == '1'
    assert env['PARTHENON_QUESTION_SECONDS']['value'] == '240'
    assert int(env['PARTHENON_REQUEST_SECONDS']['value']) < 100  # under Cloudflare's cut
    assert env['OPENROUTER_API_KEY'] == {'key': 'OPENROUTER_API_KEY', 'sync': False}  # the fallback
    for item in service['envVars']:  # no secret is ever written into the Blueprint
        if item['key'].endswith(('_KEY', '_TOKEN', 'INVITE_CODE')):
            assert 'value' not in item, item['key']


def test_the_render_blueprint_sets_the_limits_for_a_team_and_the_hearing_on_a_fast_grok():
    yaml = pytest.importorskip('yaml')
    env = {item['key']: item.get('value') for item in yaml.safe_load((REPO / 'render.yaml').read_text())
           ['services'][0]['envVars']}
    # A team behind one office address shares the per-visitor limits; the site-wide ones stay the backstop.
    assert int(env['PARTHENON_DAILY_PER_VISITOR']) >= 8
    assert int(env['PARTHENON_QUESTIONS_PER_HOUR']) >= 120
    assert env['PARTHENON_DAILY_GATHERINGS'] == '12' and env['PARTHENON_CONCURRENT_RUNS'] == '1'
    assert int(env['PARTHENON_DAILY_PER_VISITOR']) <= int(env['PARTHENON_DAILY_GATHERINGS'])
    # The memory model must be a Grok name: auto passes only those through on the subscription (anything
    # else becomes grok-4.7), and the fallbacks put their own model in its place (bridge tests).
    assert env['LOCAL_MEMORY_LLM_MODEL'].startswith('grok') and env['LOCAL_MEMORY_LLM_MODEL'] != 'grok-4.7'
    docs = (REPO / 'docs' / 'DEPLOY.md').read_text()
    assert '`LOCAL_MEMORY_LLM_MODEL`' in docs and 'one office address' in ' '.join(docs.split())
    for key in ('PARTHENON_DAILY_PER_VISITOR', 'PARTHENON_QUESTIONS_PER_HOUR'):
        assert f'| `{key}` | {env[key]} |' in docs  # the docs' table shows what the Blueprint sets


def test_the_docs_command_names_the_images_paths():
    docs = (REPO / 'docs' / 'DEPLOY.md').read_text()
    dockerfile = (REPO / 'Dockerfile.render').read_text()
    assert '/app/backend/.venv/bin/python /app/deploy/grok_signin.py signin' in docs
    assert 'COPY --from=python-deps /app/backend/.venv /app/backend/.venv' in dockerfile
    assert 'COPY deploy /app/deploy' in dockerfile
    assert 'render ssh parthenon' in docs and 'grok_signin.py status' in docs


def test_settings_reject_a_bad_port():
    with pytest.raises(StartError, match='PORT'):
        start.settings({'PORT': 'ten'})
    conf = start.settings({'PARTHENON_DATA_DIR': '/tmp/x/../y'})
    assert str(conf['data']).endswith('/y') and conf['port'] == 10000 and conf['bridge_port'] == 5055


# --------------------------------------------------------------------------- data folder


def test_prepare_data_lays_out_the_folder(tmp_path):
    start.prepare_data(tmp_path)
    for sub in start.DATA_LAYOUT:
        assert (tmp_path / sub).is_dir(), sub
    assert oct((tmp_path / 'uploads' / 'memory').stat().st_mode & 0o777) == '0o700'
    assert not (tmp_path / 'grok').exists()  # the sign-in is one file, <data>/grok-oauth.json


def test_link_into_makes_repoints_and_refuses(tmp_path):
    data = tmp_path / 'data'
    (data / 'uploads').mkdir(parents=True)
    other = tmp_path / 'other'
    other.mkdir()
    link = tmp_path / 'backend' / 'uploads'
    link.parent.mkdir()
    link.mkdir()  # an empty folder is replaced
    start.link_into(link, data / 'uploads')
    assert link.is_symlink() and os.readlink(link) == str(data / 'uploads')
    start.link_into(link, other)  # a link is re-pointed
    assert os.readlink(link) == str(other)
    link.unlink()
    link.mkdir()
    (link / 'proj_1').mkdir()  # a real folder with gatherings in it is never hidden
    with pytest.raises(StartError, match='real folder'):
        start.link_into(link, data / 'uploads')
    assert (link / 'proj_1').is_dir()


def test_link_backend_refuses_the_owners_own_uploads(tmp_path):
    app = tmp_path / 'app'
    (app / 'backend' / 'uploads' / 'projects').mkdir(parents=True)
    with pytest.raises(StartError):
        start.link_backend(app, tmp_path / 'data')
    assert (app / 'backend' / 'uploads' / 'projects').is_dir()


def test_prune_logs_keeps_recent_ones(tmp_path):
    old, new = tmp_path / 'old.log', tmp_path / 'new.log'
    old.write_text('x')
    new.write_text('y')
    os.utime(old, (time.time() - 30 * 86400,) * 2)
    assert start.prune_logs(tmp_path, 14) == 1
    assert not old.exists() and new.exists()
    assert start.prune_logs(tmp_path, 0) == 0


def _as_root(monkeypatch, calls, root_home):
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    import pwd

    monkeypatch.setattr(pwd, 'getpwnam', lambda name: types.SimpleNamespace(
        pw_uid=4242, pw_gid=4343, pw_dir='/home/parthenon'))
    monkeypatch.setattr(pwd, 'getpwuid', lambda uid: types.SimpleNamespace(pw_dir=str(root_home)))
    monkeypatch.setattr(os, 'lchown', lambda path, uid, gid: calls.append(('chown', Path(path).name, uid, gid)))
    monkeypatch.setattr(os, 'fchown', lambda fd, uid, gid: calls.append(('fchown', fd, uid, gid)))
    monkeypatch.setattr(os, 'setgroups', lambda groups: calls.append(('setgroups', groups)))
    monkeypatch.setattr(os, 'setgid', lambda gid: calls.append(('setgid', gid)))
    monkeypatch.setattr(os, 'setuid', lambda uid: calls.append(('setuid', uid)))
    monkeypatch.setenv('HOME', '/root')


def test_hand_over_gives_the_folder_away_then_drops_root(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    (data / 'uploads').mkdir(parents=True)
    (data / 'uploads' / 'a.json').write_text('{}')
    calls = []
    _as_root(monkeypatch, calls, tmp_path / 'root')
    assert start.hand_over(data, 'parthenon') == {'uid': 4242, 'gid': 4343, 'home': '/home/parthenon'}
    chowned = {c[1] for c in calls if c[0] == 'chown'}
    assert chowned == {'data', 'uploads', 'a.json'}
    order = [c[0] for c in calls if c[0] not in ('chown', 'fchown')]
    assert order == ['setgroups', 'setgid', 'setuid']  # the group before the user, or setgid would fail
    assert os.environ['HOME'] == '/home/parthenon'
    ssh = tmp_path / 'root' / '.ssh'  # Render's SSH into the container needs it
    assert ssh.is_dir() and stat.S_IMODE(ssh.stat().st_mode) == 0o700


def test_hand_over_makes_the_grok_sign_in_the_service_users_before_dropping_root(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    data.mkdir()
    token = _signed_in(data / 'grok-oauth.json')  # as a root shell would have left it
    os.chmod(token, 0o644)
    (tmp_path / 'root' / '.ssh').mkdir(parents=True, mode=0o755)
    os.chmod(tmp_path / 'root' / '.ssh', 0o755)
    calls = []
    _as_root(monkeypatch, calls, tmp_path / 'root')
    start.hand_over(data, 'parthenon', token)
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    names = [c[0] for c in calls]
    assert ('fchown', 4242, 4343) in [(c[0], c[2], c[3]) for c in calls if c[0] == 'fchown']
    assert max(i for i, n in enumerate(names) if n == 'fchown') < names.index('setuid')
    assert stat.S_IMODE((tmp_path / 'root' / '.ssh').stat().st_mode) == 0o700


def test_hand_over_leaves_a_link_in_place_of_the_sign_in(tmp_path, monkeypatch, capsys):
    data = tmp_path / 'data'
    data.mkdir()
    target = tmp_path / 'shadow'
    target.write_text('root only')
    os.chmod(target, 0o640)
    (data / 'grok-oauth.json').symlink_to(target)
    calls = []
    _as_root(monkeypatch, calls, tmp_path / 'root')
    start.hand_over(data, 'parthenon', data / 'grok-oauth.json')
    assert not [c for c in calls if c[0] == 'fchown']
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert 'is a link; left alone' in capsys.readouterr().out


@pytest.mark.parametrize('given, expected', [(None, 'grok-oauth.json'), ('elsewhere/token.json', 'elsewhere/token.json')])
def test_main_secures_the_sign_in_file_the_bridge_will_use(tmp_path, monkeypatch, given, expected):
    seen = {}

    def fake_hand_over(data, user, token_file=None):
        seen.update(data=data, user=user, token_file=token_file)
        raise StartError('stop here')

    monkeypatch.setattr(start, 'link_backend', lambda app, data: None)
    monkeypatch.setattr(start, 'hand_over', fake_hand_over)
    environ = {'PARTHENON_DATA_DIR': str(tmp_path), 'PARTHENON_USER': 'someone'}
    if given:
        environ['GROK_BRIDGE_TOKEN_FILE'] = str(tmp_path / given)
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        assert start.main(environ) == 1
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)
    data = tmp_path.resolve()
    assert seen['token_file'] == (tmp_path / given if given else data / expected)
    assert seen['user'] == 'someone'
    # The file made private is the very one the bridge is given.
    assert str(seen['token_file']) == start.child_env(environ, data, 1, 2)['GROK_BRIDGE_TOKEN_FILE']


def test_hand_over_is_a_no_op_when_not_root_but_keeps_the_sign_in_private(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'geteuid', lambda: 501)
    assert start.hand_over(tmp_path, 'parthenon') is None
    token = _signed_in(tmp_path / 'grok-oauth.json')
    os.chmod(token, 0o664)
    assert start.hand_over(tmp_path, 'parthenon', token) is None
    assert stat.S_IMODE(token.stat().st_mode) == 0o600


# --------------------------------------------------------------------------- processes

CHILD = textwrap.dedent('''
    import fcntl, os, signal, sys, time
    name, log, mode = sys.argv[1], sys.argv[2], sys.argv[3]
    def note(what):
        with open(log, 'a') as f:
            f.write(f'{time.monotonic():.6f} {name} {what}\\n')
    def on_term(signum, frame):
        note('term')
        if mode == 'stubborn':
            return
        time.sleep(0.3 if name == 'backend' else 0)
        note('exit')
        sys.exit(0)
    signal.signal(signal.SIGTERM, on_term)
    note('start')
    if mode.startswith('die'):
        time.sleep(0.2)
        sys.exit(int(mode[3:]))
    if mode.startswith('refreshing'):
        # As the bridge refreshes the Grok sign-in: the lock beside the file, from the request to the save.
        fd = os.open(sys.argv[4], os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        note('refresh-begin')
        time.sleep(float(mode[len('refreshing'):]))
        note('refresh-saved')
        fcntl.flock(fd, fcntl.LOCK_UN)
    while True:
        time.sleep(0.05)
''')


class FakeSupervisor(Supervisor):
    def __init__(self, tmp_path, backend_mode='run', bridge_mode='run', stop_timeout=5.0, **kwargs):
        super().__init__(sys.executable, dict(os.environ), tmp_path, stop_timeout, **kwargs)
        self.script = tmp_path / 'child.py'
        self.script.write_text(CHILD)
        self.log = tmp_path / 'events.log'
        self.modes = {'backend': backend_mode, 'bridge': bridge_mode}
        self.lock = start.sign_in_lock_file(tmp_path / 'grok-oauth.json')

    def _child(self, name):
        return subprocess.Popen(
            [sys.executable, str(self.script), name, str(self.log), self.modes[name], str(self.lock)],
        )

    def start_bridge(self):
        self.bridge = self._child('bridge')
        return self.bridge

    def start_backend(self):
        self.backend = self._child('backend')
        return self.backend

    def events(self):
        lines = self.log.read_text().split() if self.log.exists() else []
        return [(lines[i + 1], lines[i + 2]) for i in range(0, len(lines), 3)]

    def wait_started(self, *more):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if {('bridge', 'start'), ('backend', 'start'), *more} <= set(self.events()):
                return
            time.sleep(0.05)
        raise AssertionError('children did not start')


def test_a_stop_signal_stops_the_backend_before_the_bridge(tmp_path):
    sup = FakeSupervisor(tmp_path)
    sup.start_bridge()
    sup.start_backend()
    sup.wait_started()
    sup.on_signal(signal.SIGTERM, None)
    assert sup.run() == 0
    events = [e for e in sup.events() if e[1] != 'start']
    assert events[0] == ('backend', 'term')
    assert events.index(('backend', 'exit')) < events.index(('bridge', 'term'))


def test_when_the_backend_dies_the_bridge_is_stopped(tmp_path):
    sup = FakeSupervisor(tmp_path, backend_mode='die3')
    sup.start_bridge()
    sup.start_backend()
    assert sup.run() == 3
    assert ('bridge', 'term') in sup.events()
    assert sup.bridge.returncode is not None


def test_when_the_bridge_dies_the_backend_is_stopped(tmp_path):
    sup = FakeSupervisor(tmp_path, bridge_mode='die0')
    sup.start_bridge()
    sup.start_backend()
    assert sup.run() == 1  # an unexpected exit, even a clean one, is a failure
    assert ('backend', 'term') in sup.events()


def test_a_process_that_will_not_stop_is_killed(tmp_path):
    sup = FakeSupervisor(tmp_path, backend_mode='stubborn', stop_timeout=0.5)
    sup.start_bridge()
    sup.start_backend()
    sup.wait_started()
    began = time.monotonic()
    sup.on_signal(signal.SIGTERM, None)
    assert sup.run() == 0
    assert time.monotonic() - began < 5
    assert sup.backend.returncode == -signal.SIGKILL


def test_a_backend_that_will_not_stop_is_killed_alone_and_the_bridge_still_gets_its_sigterm(tmp_path):
    # A stop during a Gathering's preparation: the profile workers keep the backend alive past its grace.
    sup = FakeSupervisor(tmp_path, backend_mode='stubborn', stop_timeout=0.5, bridge_timeout=3.0)
    sup.start_bridge()
    sup.start_backend()
    sup.wait_started()
    began = time.monotonic()
    sup.on_signal(signal.SIGTERM, None)
    assert sup.run() == 0
    assert time.monotonic() - began < 3
    assert sup.backend.returncode == -signal.SIGKILL
    # The bridge was asked with SIGTERM, and went on its own before any SIGKILL could reach it.
    assert ('bridge', 'term') in sup.events() and ('bridge', 'exit') in sup.events()
    assert sup.bridge.returncode == 0


def test_a_bridge_that_will_not_stop_is_killed_after_its_own_grace(tmp_path):
    sup = FakeSupervisor(tmp_path, bridge_mode='stubborn', stop_timeout=5.0, bridge_timeout=0.6)
    sup.start_bridge()
    sup.start_backend()
    sup.wait_started()
    began = time.monotonic()
    sup.on_signal(signal.SIGTERM, None)
    assert sup.run() == 0
    assert time.monotonic() - began < 4
    assert sup.backend.returncode == 0  # the backend stopped on its own, first
    events = [e for e in sup.events() if e[1] != 'start']
    assert events.index(('backend', 'exit')) < events.index(('bridge', 'term'))
    assert sup.bridge.returncode == -signal.SIGKILL


def test_the_default_stop_fits_inside_renders_thirty_seconds():
    conf = start.settings({})
    assert conf['stop_timeout'] + conf['bridge_stop_timeout'] <= start.RENDER_STOP_SECONDS - 2
    assert conf['bridge_stop_timeout'] >= 3  # room for a token refresh to reach the disk


@pytest.mark.parametrize('guarded', [True, False])
def test_the_bridge_is_never_stopped_in_the_middle_of_a_grok_token_refresh(tmp_path, guarded):
    token = _signed_in(tmp_path / 'grok-oauth.json')  # fake tokens in a temporary file
    sup = FakeSupervisor(
        tmp_path, bridge_mode='refreshing1.0', stop_timeout=5.0, bridge_timeout=4.0,
        sign_in=token if guarded else None,
    )
    sup.start_bridge()
    sup.start_backend()
    sup.wait_started(('bridge', 'refresh-begin'))
    sup.on_signal(signal.SIGTERM, None)
    assert sup.run() == 0
    events = [e for e in sup.events() if e[1] != 'start']
    if guarded:
        # The rotated refresh token reached the disk before the bridge was asked to stop.
        assert events.index(('bridge', 'refresh-saved')) < events.index(('bridge', 'term'))
        assert sup.bridge.returncode == 0
    else:  # without the lock the stop would cut the refresh short: what the guard is for
        assert ('bridge', 'refresh-saved') not in events
    assert sup._sign_in_lock is None  # let go once the bridge is gone
    free = start.hold_sign_in_lock(token, time.monotonic())
    assert free is not None
    os.close(free)


def test_main_gives_the_supervisor_the_bridges_sign_in_and_both_graces(tmp_path, monkeypatch):
    seen = {}

    class Captured(Supervisor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen['sup'] = self

        def install_signal_handlers(self):
            pass

        def start_bridge(self):
            raise StartError('stop here')

    for name in ('GROK_BRIDGE_TOKEN_FILE', 'PARTHENON_STOP_TIMEOUT', 'PARTHENON_BRIDGE_STOP_TIMEOUT'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(start, 'link_backend', lambda app, data: None)
    monkeypatch.setattr(start, 'hand_over', lambda data, user, token_file=None: None)
    monkeypatch.setattr(start, 'seed_exhibits', lambda env, data: None)
    monkeypatch.setattr(start, 'Supervisor', Captured)
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        assert start.main({'PARTHENON_DATA_DIR': str(tmp_path), 'PARTHENON_BRIDGE_STOP_TIMEOUT': '4'}) == 1
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)
    sup = seen['sup']
    assert sup.stop_timeout == 20 and sup.bridge_timeout == 4
    # The lock it waits on is the one beside the very file the bridge is given.
    assert sup.sign_in == Path(sup.env['GROK_BRIDGE_TOKEN_FILE']) == tmp_path.resolve() / 'grok-oauth.json'


def test_hold_sign_in_lock(tmp_path):
    token = tmp_path / 'grok-oauth.json'
    assert start.hold_sign_in_lock(token, time.monotonic()) is None  # no sign-in: nothing to refresh
    assert not start.sign_in_lock_file(token).exists()
    _signed_in(token)
    held = start.hold_sign_in_lock(token, time.monotonic())
    assert held is not None
    assert stat.S_IMODE(os.stat(start.sign_in_lock_file(token)).st_mode) == 0o600
    began = time.monotonic()
    assert start.hold_sign_in_lock(token, began + 0.3) is None  # taken: waits until the deadline, no longer
    assert 0.25 < time.monotonic() - began < 2
    os.close(held)
    again = start.hold_sign_in_lock(token, time.monotonic())
    assert again is not None
    os.close(again)


def test_the_lock_is_the_real_bridges_refresh_lock(tmp_path):
    """The real bridge's TokenStore.file_lock (held from the refresh request to the save) keeps the supervisor
    waiting. The bridge runs from a copy in a folder of its own, so no .env of the owner's is ever loaded."""
    folder = tmp_path / 'real' / 'bridge'
    folder.mkdir(parents=True)
    (folder / 'grok_bridge.py').write_bytes((REPO / 'bridge' / 'grok_bridge.py').read_bytes())
    token = _signed_in(tmp_path / 'grok-oauth.json')  # fake tokens in a temporary file
    script = ('import sys, time; from pathlib import Path; import grok_bridge as b\n'
              'store = b.TokenStore(Path(sys.argv[1]), None)\n'
              'with store.file_lock():\n'
              '    print("locked", flush=True)\n'
              '    time.sleep(1.0)\n')
    child = subprocess.Popen(
        [sys.executable, '-c', script, str(token)], cwd=folder, stdout=subprocess.PIPE, text=True,
        env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(tmp_path)},
    )
    try:
        assert child.stdout.readline().strip() == 'locked'
        began = time.monotonic()
        held = start.hold_sign_in_lock(token, began + 20)
        waited = time.monotonic() - began
        assert held is not None
        os.close(held)
        assert 0.5 < waited < 10  # it waited for the bridge to let go, then took the lock
    finally:
        child.kill()
        child.wait()


def test_hold_sign_in_lock_never_follows_a_link(tmp_path):
    token = _signed_in(tmp_path / 'grok-oauth.json')
    elsewhere = tmp_path / 'elsewhere'
    start.sign_in_lock_file(token).symlink_to(elsewhere)
    assert start.hold_sign_in_lock(token, time.monotonic()) is None
    assert not elsewhere.exists()


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def test_wait_for_bridge(tmp_path):
    port = _free_port()

    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == '/health' else 404)
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(('127.0.0.1', port), Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    alive = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'])
    try:
        start.wait_for_bridge(port, alive, 5)
    finally:
        server.shutdown()
        alive.kill()
        alive.wait()
    dead = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(2)'])
    dead.wait()
    with pytest.raises(StartError, match='exited with status 2'):
        start.wait_for_bridge(_free_port(), dead, 5)
    silent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'])
    try:
        with pytest.raises(StartError, match='did not answer'):
            start.wait_for_bridge(_free_port(), silent, 0.5)
    finally:
        silent.kill()
        silent.wait()


# --------------------------------------------------------------------------- cpu torch


def test_the_cpu_torch_pin_matches_the_lock():
    locked, names = cpu_torch.excluded_packages((REPO / 'backend' / 'uv.lock').read_text())
    assert cpu_torch.pinned_version((REPO / 'deploy' / 'torch-cpu.txt').read_text()) == locked
    assert 'torch' in names and 'triton' in names
    assert any(n.startswith('nvidia-') for n in names)
    assert all(n in ('torch', 'triton') or n.startswith('nvidia-') for n in names)
    assert cpu_torch.main([str(REPO / 'backend' / 'uv.lock'), str(REPO / 'deploy' / 'torch-cpu.txt')]) == 0


def test_cpu_torch_stops_the_build_when_the_lock_moves(tmp_path, capsys):
    lock = tmp_path / 'uv.lock'
    lock.write_text('version = 1\n[[package]]\nname = "torch"\nversion = "9.9.9"\n'
                    '[[package]]\nname = "nvidia-cudnn-cu12"\nversion = "1"\n')
    pin = tmp_path / 'pin.txt'
    pin.write_text('torch==2.9.1+cpu \\\n    --hash=sha256:00\n')
    assert cpu_torch.main([str(lock), str(pin)]) == 1
    assert 'has torch 9.9.9' in capsys.readouterr().err
    pin.write_text('torch==9.9.9\n')
    assert cpu_torch.main([str(lock), str(pin)]) == 1


def test_the_image_files_agree():
    dockerfile = (REPO / 'Dockerfile.render').read_text()
    assert 'VITE_BASE=/parthenon/' in dockerfile
    assert 'deploy/start.py' in dockerfile and 'cpu_torch.py' in dockerfile
    assert '--frozen' in dockerfile
    for copied in ('backend/wsgi.py', 'backend/app', 'backend/scripts', 'bridge/grok_bridge.py', 'locales', 'deploy'):
        assert copied in dockerfile, copied
        assert f'!{copied}' in (REPO / '.dockerignore').read_text().split(), copied
    ignore = (REPO / '.dockerignore').read_text().split()
    assert ignore[ignore.index('*')] == '*'  # an allow-list
    assert '!backend/uploads' not in ignore and '!.env' not in ignore
    blueprint = (REPO / 'render.yaml').read_text()
    for key in ('PARTHENON_PUBLIC', 'PARTHENON_BASE', 'PARTHENON_DATA_DIR', 'PARTHENON_TRUST_PROXY',
                'PARTHENON_UPSTREAM', 'OPENROUTER_API_KEY', 'XAI_API_KEY', 'OPENAI_API_KEY',
                'ANTHROPIC_API_KEY', 'PARTHENON_ADMIN_KEY', 'PARTHENON_EXHIBITS_URL',
                'GROK_BRIDGE_TOKEN_FILE', 'PARTHENON_INVITE_CODE', 'PARTHENON_QUESTION_SECONDS'):
        assert f'key: {key}\n' in blueprint, key
    assert 'type: pserv' in blueprint and 'mountPath: /data' in blueprint
