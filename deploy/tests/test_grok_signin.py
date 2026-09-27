"""deploy/grok_signin.py: signing the server in to Grok, with a fake bridge (never the real login)."""

from __future__ import annotations

import base64
import http.server
import io
import json
import os
import pwd
import socket
import stat
import subprocess
import sys
import textwrap
import threading
import time
import types
from pathlib import Path

import pytest

import grok_signin

ME = pwd.getpwuid(os.geteuid()).pw_name
FAKE_ACCESS = 'fake-access-token-never-printed'
FAKE_REFRESH = 'fake-refresh-token-never-printed'

# Stands in for bridge/grok_bridge.py: `login --no-browser` writes a fake sign-in (loosely, so the helper
# has to make it private), `logout` deletes it. It records how it was called beside itself.
FAKE_BRIDGE = textwrap.dedent(f'''
    import json, os, sys
    from pathlib import Path
    here = Path(__file__).resolve().parent
    token = Path(os.environ['GROK_BRIDGE_TOKEN_FILE'])
    umask = os.umask(0); os.umask(umask)
    with open(here / 'calls.jsonl', 'a') as log:
        log.write(json.dumps({{'argv': sys.argv[1:], 'env': sorted(os.environ), 'token': str(token),
                              'home': os.environ.get('HOME'), 'cwd': os.getcwd(), 'umask': umask}}) + '\\n')
    mode = (here / 'mode.txt').read_text().strip() if (here / 'mode.txt').exists() else 'ok'
    if sys.argv[1] == 'login':
        print('Sign in to Grok for Parthenon:')
        print('  1. Open https://accounts.x.ai/device?user_code=FAKE-CODE')
        print('  2. Check the code matches: FAKE-CODE')
        if mode == 'fail':
            print('Sign-in failed: access_denied')
            sys.exit(1)
        token.write_text(json.dumps({{'access_token': '{FAKE_ACCESS}', 'refresh_token': '{FAKE_REFRESH}'}}))
        os.chmod(token, 0o644)
        print(f'Signed in to Grok as someone. Sign-in saved to {{token}}')
    elif sys.argv[1] == 'logout':
        try:
            token.unlink()
            print('Signed out; the stored Grok sign-in was deleted.')
        except FileNotFoundError:
            print('Already signed out.')
    else:
        sys.exit(2)
''')


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class FakeServer:
    """The running bridge's /health and the site's status, deciding auto from the sign-in file as the bridge does."""

    def __init__(self, token: Path, provider_when_signed_in='grok-subscription'):
        self.token = token
        self.port = _free_port()
        self.grok_label = provider_when_signed_in
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                on_grok = grok_signin.sign_in_usable(server.token)
                if self.path == '/health':
                    body = ({'status': 'ok', 'upstream': 'grok', 'provider': server.grok_label, 'signed_in': True,
                             'imagine': True, 'voice': True} if on_grok else
                            {'status': 'ok', 'upstream': 'openrouter', 'provider': 'free', 'imagine': False,
                             'voice': False})
                elif self.path == '/parthenon/api/parthenon/status':
                    body = {'success': True, 'data': {
                        'public': True, 'provider': 'grok-subscription' if on_grok else 'free',
                        'features': {'portraits': on_grok, 'film': on_grok, 'voice': on_grok},
                        'invite_required': True}}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server_box(tmp_path):
    """A data folder, a fake app with the fake bridge, and the environment the helper would find."""
    data = tmp_path / 'data'
    data.mkdir()
    app = tmp_path / 'app'
    (app / 'bridge').mkdir(parents=True)
    bridge = app / 'bridge' / 'grok_bridge.py'
    bridge.write_text(FAKE_BRIDGE)
    token = data / 'grok-oauth.json'
    return types.SimpleNamespace(data=data, app=app, bridge=bridge, token=token, tmp=tmp_path)


def run(box, command, *extra, port=None, environ=None, proc=None, runner=subprocess.run, wait='5'):
    env = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'GROK_BRIDGE_TOKEN_FILE': str(box.token),
        'GROK_BRIDGE_PORT': str(port or _free_port()),
        'PORT': str(port or _free_port()),
        'OPENROUTER_API_KEY': 'fake-openrouter-key',
        'PARTHENON_INVITE_CODE': 'B0jr+hA/POY=, second-word',
    }
    env.update(environ or {})
    out = io.StringIO()
    code = grok_signin.main(
        [command, '--user', ME, '--bridge', str(box.bridge), '--python', sys.executable,
         '--wait', wait, '--every', '0.05', *extra],
        environ=env, proc=proc or box.tmp / 'no-proc', out=out, runner=runner,
    )
    return code, out.getvalue()


def calls(box):
    path = box.bridge.with_name('calls.jsonl')
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


# --------------------------------------------------------------------------- signin


def test_signin_runs_the_bridges_login_and_the_running_bridge_takes_it_up(server_box, capfd, monkeypatch):
    monkeypatch.setenv('XAI_API_KEY', 'fake-key-in-this-shell')  # the helper's own environment
    with FakeServer(server_box.token) as fake:
        code, out = run(server_box, 'signin', port=fake.port)
    assert code == 0, out
    assert 'on the Grok subscription now' in out and 'No restart needed' in out
    assert grok_signin.sign_in_usable(server_box.token)
    assert mode_of(server_box.token) == 0o600  # the fake bridge left it 0644
    [call] = calls(server_box)
    assert call['argv'] == ['login', '--no-browser']
    assert call['token'] == str(server_box.token)
    assert call['cwd'] == str(server_box.data.resolve()) or call['cwd'] == str(server_box.data)
    assert call['umask'] == 0o077
    # A clean environment: the sign-in file, never the server's keys.
    assert 'OPENROUTER_API_KEY' not in call['env'] and 'PARTHENON_INVITE_CODE' not in call['env']
    assert 'XAI_API_KEY' not in call['env']
    assert 'GROK_BRIDGE_TOKEN_FILE' in call['env']
    printed = out + ''.join(capfd.readouterr())
    assert 'FAKE-CODE' in printed  # the device code reaches the owner
    assert FAKE_ACCESS not in printed and FAKE_REFRESH not in printed


def test_signin_says_so_when_the_login_fails(server_box):
    server_box.bridge.with_name('mode.txt').write_text('fail')
    code, out = run(server_box, 'signin')
    assert code == 1 and 'nothing changed' in out
    assert not server_box.token.exists()


def test_signin_when_the_bridge_does_not_answer(server_box):
    code, out = run(server_box, 'signin', wait='0.2')
    assert code == 1
    assert 'The sign-in is saved' in out and 'does not answer' in out
    assert mode_of(server_box.token) == 0o600


def test_signin_when_the_bridge_is_not_on_auto(server_box):
    with FakeServer(server_box.token, provider_when_signed_in='free') as fake:
        code, out = run(server_box, 'signin', port=fake.port, wait='0.3',
                        environ={'PARTHENON_UPSTREAM': 'openrouter'})
    assert code == 1
    assert 'PARTHENON_UPSTREAM is openrouter' in out
    assert 'PARTHENON_UPSTREAM must be auto' in out


def test_signin_refuses_a_bridge_with_a_dotenv_beside_it(server_box):
    (server_box.app / '.env').write_text('# the owner machine\n')
    code, out = run(server_box, 'signin')
    assert code == 2 and 'npm run grok:login' in out
    assert calls(server_box) == []


def test_signin_refuses_a_shell_without_the_disk(server_box):
    code, out = run(server_box, 'signin', environ={
        'GROK_BRIDGE_TOKEN_FILE': str(server_box.tmp / 'no-disk' / 'grok-oauth.json')})
    assert code == 2 and 'not --ephemeral' in out
    assert calls(server_box) == []


def test_signin_refuses_a_link_in_place_of_the_file(server_box):
    target = server_box.tmp / 'elsewhere.json'
    target.write_text('{}')
    server_box.token.symlink_to(target)
    code, out = run(server_box, 'signin')
    assert code == 2 and 'not a plain file' in out
    assert calls(server_box) == []


def test_signin_refuses_another_non_root_account(server_box):
    out = io.StringIO()
    code = grok_signin.main(
        ['signin', '--user', 'daemon', '--bridge', str(server_box.bridge), '--python', sys.executable],
        environ={'GROK_BRIDGE_TOKEN_FILE': str(server_box.token)}, proc=server_box.tmp / 'no-proc', out=out)
    assert code == 2 and 'neither root nor daemon' in out.getvalue()
    assert calls(server_box) == []


def test_signin_as_root_runs_the_login_as_the_service_user(server_box, monkeypatch):
    seen = {}
    chowned = []

    def fake_runner(argv, **kwargs):
        seen['argv'] = argv
        seen.update(kwargs)
        Path(kwargs['env']['GROK_BRIDGE_TOKEN_FILE']).write_text(json.dumps({'access_token': FAKE_ACCESS}))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setattr(pwd, 'getpwnam', lambda name: types.SimpleNamespace(
        pw_uid=4242, pw_gid=4343, pw_dir='/home/parthenon', pw_name=name))
    monkeypatch.setattr(os, 'fchown', lambda fd, uid, gid: chowned.append((uid, gid)))
    with FakeServer(server_box.token) as fake:
        code, out = run(server_box, 'signin', port=fake.port, runner=fake_runner)
    assert code == 0, out
    assert seen['user'] == 4242 and seen['group'] == 4343 and seen['extra_groups'] == []
    assert seen['umask'] == 0o077
    assert seen['env']['HOME'] == '/home/parthenon' and seen['env']['USER'] == ME
    assert seen['env']['GROK_BRIDGE_TOKEN_FILE'] == str(server_box.token)
    assert 'OPENROUTER_API_KEY' not in seen['env']
    assert seen['argv'][-2:] == ['login', '--no-browser']
    assert (4242, 4343) in chowned
    assert mode_of(server_box.token) == 0o600


# --------------------------------------------------------------------------- status and signout


def test_status_on_the_grok_subscription(server_box):
    server_box.token.write_text(json.dumps({'access_token': FAKE_ACCESS}))
    os.chmod(server_box.token, 0o600)
    with FakeServer(server_box.token) as fake:
        code, out = run(server_box, 'status', port=fake.port)
    assert code == 0, out
    assert 'grok-subscription' in out and 'Signed in:    yes (Grok)' in out
    assert 'portraits on, film on, voice on' in out
    assert 'Invite:       required (2 codes)' in out
    assert '0600' in out and 'Warning' not in out
    assert FAKE_ACCESS not in out


def test_status_on_the_fallback_warns_about_a_loose_file(server_box):
    server_box.token.write_text(json.dumps({'access_token': FAKE_ACCESS, 'revoked': 'invalid_grant'}))
    os.chmod(server_box.token, 0o644)
    with FakeServer(server_box.token) as fake:
        code, out = run(server_box, 'status', port=fake.port)
    assert code == 1
    assert "free: OpenRouter's free models (the fallback)" in out
    assert 'portraits off' in out
    assert 'Warning:' in out and '0644' in out


def test_status_when_nothing_answers(server_box):
    code, out = run(server_box, 'status')
    assert code == 1
    assert 'the bridge does not answer' in out and 'Site:         does not answer' in out
    assert '(none: not signed in)' in out


def test_signout_falls_back(server_box):
    server_box.token.write_text(json.dumps({'access_token': FAKE_ACCESS}))
    with FakeServer(server_box.token) as fake:
        code, out = run(server_box, 'signout', port=fake.port)
    assert code == 0, out
    assert not server_box.token.exists()
    assert 'now on free' in out
    assert [c['argv'] for c in calls(server_box)] == [['logout']]


# --------------------------------------------------------------------------- invite link


def test_invite_link_escapes_a_generated_code(server_box):
    code, out = run(server_box, 'invite-link', environ={
        'PARTHENON_PUBLIC_ORIGIN': 'https://projectforty2.ai,https://www.projectforty2.ai',
        'PARTHENON_BASE': '/parthenon'})
    assert code == 0
    assert out.splitlines() == [
        'https://projectforty2.ai/parthenon?invite=B0jr%2BhA%2FPOY%3D',
        'https://projectforty2.ai/parthenon?invite=second-word',
    ]
    code, out = run(server_box, 'invite-link', '--site', 'http://localhost:8091/parthenon')
    assert out.splitlines()[0] == 'http://localhost:8091/parthenon?invite=B0jr%2BhA%2FPOY%3D'


def test_invite_link_without_a_code(server_box):
    code, out = run(server_box, 'invite-link', environ={'PARTHENON_INVITE_CODE': ' '})
    assert code == 1 and 'No invite code' in out


# --------------------------------------------------------------------------- the running server's settings


def _process(proc: Path, pid: int, argv, environ):
    folder = proc / str(pid)
    folder.mkdir(parents=True)
    (folder / 'cmdline').write_bytes('\0'.join(argv).encode() + b'\0')
    if environ is not None:
        (folder / 'environ').write_bytes(b''.join(f'{k}={v}'.encode() + b'\0' for k, v in environ.items()))


def test_server_environ_reads_the_running_bridge_and_keeps_no_keys(tmp_path):
    proc = tmp_path / 'proc'
    _process(proc, 1, ['python', '/app/deploy/start.py'], {'PARTHENON_DATA_DIR': '/data', 'PORT': '10000'})
    _process(proc, 30, ['/app/backend/.venv/bin/python', '/app/bridge/grok_bridge.py', 'login', '--no-browser'],
             {'GROK_BRIDGE_TOKEN_FILE': '/an/earlier/sign-in.json'})  # a login, not the running bridge
    _process(proc, 40, ['/app/backend/.venv/bin/python', '/app/deploy/serve.py'], {'PORT': '10000'})
    _process(proc, 57, ['/app/backend/.venv/bin/python', '/app/bridge/grok_bridge.py', 'serve'], {
        'GROK_BRIDGE_TOKEN_FILE': '/data/grok-oauth.json', 'GROK_BRIDGE_PORT': '5057',
        'XAI_API_KEY': 'secret', 'PARTHENON_ADMIN_KEY': 'secret', 'PARTHENON_INVITE_CODE': 'abc=',
    })
    (proc / 'self').mkdir()
    values, source = grok_signin.server_environ(proc)
    assert values == {'GROK_BRIDGE_TOKEN_FILE': '/data/grok-oauth.json', 'GROK_BRIDGE_PORT': '5057',
                      'PARTHENON_INVITE_CODE': 'abc='}
    assert source == 'the running bridge (pid 57)'


def test_server_environ_falls_back_to_the_entrypoint(tmp_path):
    proc = tmp_path / 'proc'
    _process(proc, 1, ['python', '/app/deploy/start.py'], {'PARTHENON_DATA_DIR': '/disk', 'SECRET_KEY': 's'})
    _process(proc, 57, ['python', '/app/bridge/grok_bridge.py', 'serve'], None)  # unreadable
    values, source = grok_signin.server_environ(proc)
    assert values == {'PARTHENON_DATA_DIR': '/disk'} and source == 'the entrypoint (pid 1)'
    assert grok_signin.server_environ(tmp_path / 'none') == ({}, '')


def test_the_running_server_wins_over_this_shell_and_a_flag_wins_over_both(tmp_path):
    proc = tmp_path / 'proc'
    _process(proc, 57, ['python', '/app/bridge/grok_bridge.py', 'serve'], {
        'GROK_BRIDGE_TOKEN_FILE': '/data/grok-oauth.json', 'GROK_BRIDGE_PORT': '5057', 'PORT': '10001'})
    args = types.SimpleNamespace(token_file=None, user=None, site=None, python=None, bridge=None)
    shell = {'GROK_BRIDGE_TOKEN_FILE': '/stale/token.json', 'GROK_BRIDGE_PORT': '9999', 'PARTHENON_USER': 'me'}
    conf = grok_signin.resolve(args, shell, proc)
    assert conf.token_file == Path('/data/grok-oauth.json') and conf.bridge_port == 5057
    assert conf.site_port == 10001 and conf.user == 'me'
    assert conf.status_url == 'http://127.0.0.1:10001/parthenon/api/parthenon/status'
    args.token_file, args.user = '/flag/token.json', 'flagged'
    conf = grok_signin.resolve(args, shell, proc)
    assert conf.token_file == Path('/flag/token.json') and conf.user == 'flagged'
    # Nothing anywhere: the entrypoint's defaults.
    args.token_file = args.user = None
    conf = grok_signin.resolve(args, {}, tmp_path / 'none')
    assert conf.token_file == Path('/data/grok-oauth.json') and conf.user == 'parthenon'
    assert (conf.bridge_port, conf.site_port) == (5055, 10000)
    assert conf.site == 'https://projectforty2.ai/parthenon' and conf.source == 'the defaults'


# --------------------------------------------------------------------------- the sign-in file


def test_sign_in_usable(tmp_path):
    path = tmp_path / 'grok-oauth.json'
    assert not grok_signin.sign_in_usable(path)
    path.write_text(json.dumps({'access_token': 'a', 'refresh_token': 'r'}))
    assert grok_signin.sign_in_usable(path)
    path.write_text(json.dumps({'access_token': 'a', 'revoked': 'invalid_grant'}))
    assert not grok_signin.sign_in_usable(path)
    path.write_text(json.dumps({'refresh_token': 'r'}))
    assert not grok_signin.sign_in_usable(path)

    def jwt(exp):
        claims = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
        return f'header.{claims}.signature'

    # Without a refresh token only an access token that has not expired will do (the bridge's usable_state).
    path.write_text(json.dumps({'access_token': jwt(time.time() - 60)}))
    assert not grok_signin.sign_in_usable(path)
    path.write_text(json.dumps({'access_token': jwt(time.time() + 600)}))
    assert grok_signin.sign_in_usable(path)
    path.write_text(json.dumps({'access_token': jwt(time.time() - 60), 'refresh_token': 'r'}))
    assert grok_signin.sign_in_usable(path)
    path.write_text('{not json')
    assert not grok_signin.sign_in_usable(path)
    good = tmp_path / 'good.json'
    good.write_text(json.dumps({'access_token': 'a'}))
    path.unlink()
    path.symlink_to(good)
    assert not grok_signin.sign_in_usable(path)


def test_secure_sign_in_file_makes_it_and_the_lock_private(tmp_path):
    path = tmp_path / 'grok-oauth.json'
    assert grok_signin.secure_sign_in_file(path) == []  # nothing there yet
    path.write_text('{}')
    lock = tmp_path / 'grok-oauth.json.lock'
    lock.write_text('')
    os.chmod(path, 0o644)
    os.chmod(lock, 0o666)
    assert grok_signin.secure_sign_in_file(path) == []
    assert mode_of(path) == 0o600 and mode_of(lock) == 0o600


def test_secure_sign_in_file_never_follows_a_link(tmp_path):
    target = tmp_path / 'target'
    target.write_text('x')
    os.chmod(target, 0o644)
    path = tmp_path / 'grok-oauth.json'
    path.symlink_to(target)
    problems = grok_signin.secure_sign_in_file(path, 4242, 4343)
    assert problems and 'link' in problems[0]
    assert mode_of(target) == 0o644
    path.unlink()
    path.mkdir()
    assert 'not a file' in grok_signin.secure_sign_in_file(path)[0]


def test_secure_sign_in_file_chowns_only_what_differs(tmp_path, monkeypatch):
    path = tmp_path / 'grok-oauth.json'
    path.write_text('{}')
    chowned = []
    monkeypatch.setattr(os, 'fchown', lambda fd, uid, gid: chowned.append((uid, gid)))
    st = os.stat(path)
    grok_signin.secure_sign_in_file(path, st.st_uid, st.st_gid)
    assert chowned == []
    grok_signin.secure_sign_in_file(path, 4242, 4343)
    assert chowned == [(4242, 4343)]


# --------------------------------------------------------------------------- against the real bridge's serve

REPO = Path(__file__).resolve().parents[2]


def _bridge_copy(tmp_path: Path) -> Path:
    """bridge/grok_bridge.py in a folder of its own: no .env beside it, so nothing of the owner's is loaded."""
    folder = tmp_path / 'real' / 'bridge'
    folder.mkdir(parents=True)
    copy = folder / 'grok_bridge.py'
    copy.write_bytes((REPO / 'bridge' / 'grok_bridge.py').read_bytes())
    return copy


def _clean_env(tmp_path: Path, **extra) -> dict:
    return {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(tmp_path), 'PYTHONUNBUFFERED': '1',
            **extra}


def test_sign_in_usable_agrees_with_the_bridge(tmp_path):
    bridge = _bridge_copy(tmp_path)

    def jwt(exp):
        claims = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
        return f'header.{claims}.signature'

    cases = {
        'good': {'access_token': 'a', 'refresh_token': 'r'},
        'revoked': {'access_token': 'a', 'refresh_token': 'r', 'revoked': 'invalid_grant'},
        'no-access': {'refresh_token': 'r'},
        'expired-no-refresh': {'access_token': jwt(time.time() - 60)},
        'fresh-no-refresh': {'access_token': jwt(time.time() + 600)},
        'expired-with-refresh': {'access_token': jwt(time.time() - 60), 'refresh_token': 'r'},
    }
    paths = {}
    for name, state in cases.items():
        paths[name] = tmp_path / f'{name}.json'
        paths[name].write_text(json.dumps(state))
    paths['broken'] = tmp_path / 'broken.json'
    paths['broken'].write_text('{broken')
    paths['missing'] = tmp_path / 'missing.json'
    script = ('import json, sys; from pathlib import Path; import grok_bridge as b; '
              'print(json.dumps({n: b.usable_sign_in(Path(p)) is not None for n, p in json.loads(sys.argv[1]).items()}))')
    result = subprocess.run(
        [sys.executable, '-c', script, json.dumps({n: str(p) for n, p in paths.items()})],
        cwd=bridge.parent, env=_clean_env(tmp_path), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-2000:]
    theirs = json.loads(result.stdout.strip().splitlines()[-1])
    ours = {name: grok_signin.sign_in_usable(path) for name, path in paths.items()}
    assert ours == theirs


def test_signing_in_switches_the_running_bridge_without_a_restart(server_box):
    """The real bridge's `serve` (auto, no keys, no network), the fake login: in, then out again."""
    bridge = _bridge_copy(server_box.tmp)
    port = _free_port()
    log = (server_box.tmp / 'bridge.log').open('w')
    serve = subprocess.Popen(
        [sys.executable, str(bridge), 'serve'], cwd=bridge.parent, stdout=log, stderr=subprocess.STDOUT,
        env=_clean_env(server_box.tmp, PARTHENON_UPSTREAM='auto', PARTHENON_PUBLIC='1',
                       GROK_BRIDGE_TOKEN_FILE=str(server_box.token), GROK_BRIDGE_PORT=str(port)))
    try:
        deadline = time.monotonic() + 30
        health = None
        while health is None and time.monotonic() < deadline and serve.poll() is None:
            health = grok_signin.get_json(f'http://127.0.0.1:{port}/health', timeout=1)
            time.sleep(0.1)
        assert health is not None, (server_box.tmp / 'bridge.log').read_text()[-2000:]
        assert health.get('provider') == 'free' and not grok_signin.on_grok(health)

        code, out = run(server_box, 'signin', port=port)
        assert code == 0, out + (server_box.tmp / 'bridge.log').read_text()[-2000:]
        health = grok_signin.get_json(f'http://127.0.0.1:{port}/health')
        assert health['provider'] == 'grok-subscription' and health.get('voice') is True
        assert health.get('imagine') is True

        code, out = run(server_box, 'signout', port=port)
        assert code == 0 and 'now on free' in out
        assert serve.poll() is None  # the same process throughout
    finally:
        serve.terminate()
        try:
            serve.wait(10)
        except subprocess.TimeoutExpired:
            serve.kill()
        log.close()
    assert FAKE_ACCESS not in (server_box.tmp / 'bridge.log').read_text()
