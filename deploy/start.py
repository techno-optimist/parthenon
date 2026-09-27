#!/usr/bin/env python3
"""
The public container's entrypoint: the bridge, then the backend, watched.

    python deploy/start.py

1. Lays out the data folder (PARTHENON_DATA_DIR, default /data): uploads/
   (projects, simulations, reports, memory, voices), logs/, cache/huggingface,
   exhibits/ and run/ (the working directory).
2. Points the backend's own folders at it: backend/uploads and backend/logs
   become links into the data folder (the backend writes to them by paths
   relative to its source), and LOCAL_MEMORY_DB_PATH, HF_HOME and the Grok
   sign-in file (GROK_BRIDGE_TOKEN_FILE, default <data>/grok-oauth.json)
   default to places inside it.
3. Started as root (the Render disk is mounted root-owned), it hands the data
   folder to the unprivileged user PARTHENON_USER (default parthenon), makes
   the Grok sign-in file, when there is one, that user's with mode 0600 (it
   may have been written by root in a shell; deploy/grok_signin.py signs the
   server in), makes root's ~/.ssh for Render's SSH, and drops to that user
   before anything else runs.
4. Seeds the exhibits once from PARTHENON_EXHIBITS_URL (deploy/seed_exhibits.py);
   a failure is logged and the city starts without them.
5. Starts the bridge on 127.0.0.1:GROK_BRIDGE_PORT (default 5055, never
   public) with the provider settings (PARTHENON_UPSTREAM and the keys), waits
   for its /health, then starts the backend and the built frontend with
   waitress on 0.0.0.0:PORT (default 10000; deploy/serve.py).
6. Forwards SIGTERM/SIGINT/SIGHUP, reaps orphans, and exits as soon as either
   process dies, so the platform restarts the container. A stop goes in two
   steps, inside Render's 30 s: the backend first, so it can stop running
   simulations while the bridge still answers (PARTHENON_STOP_TIMEOUT, 20 s,
   then it alone is killed); then the bridge, never in the middle of a Grok
   token refresh (it holds the sign-in's lock file while it refreshes, and
   the rotated refresh token xAI hands back must reach the disk), with its own
   PARTHENON_BRIDGE_STOP_TIMEOUT (5 s).
"""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Mapping, MutableMapping, Optional

DEPLOY_DIR = Path(__file__).resolve().parent
APP_DIR = DEPLOY_DIR.parent
sys.path.insert(0, str(DEPLOY_DIR))

from grok_signin import default_sign_in_file, secure_sign_in_file, sign_in_file, sign_in_usable  # noqa: E402

DATA_LAYOUT = (
    'uploads/projects',
    'uploads/simulations',
    'uploads/reports',
    'uploads/memory',
    'uploads/voices',
    'logs',
    'cache/huggingface',
    'exhibits',
    'run',
)
PRIVATE_DIRS = ('uploads/memory',)
KEYED = (('XAI_API_KEY', 'xai'), ('OPENAI_API_KEY', 'openai'), ('ANTHROPIC_API_KEY', 'anthropic'))
RENDER_STOP_SECONDS = 30  # Render's SIGKILL follows its SIGTERM after this long (no delay allowed with a disk)


class StartError(Exception):
    pass


def log(message: str) -> None:
    print(f'start: {message}', flush=True)


def _int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = (environ.get(name) or '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise StartError(f'{name} is not an integer: {raw!r}') from error


def effective_upstream(environ: Mapping[str, str]) -> str:
    """What the bridge serves at this moment: PARTHENON_UPSTREAM, with auto resolved as the bridge resolves
    it (the Grok subscription when GROK_BRIDGE_TOKEN_FILE holds a usable sign-in, else the first key that is
    set, else OpenRouter). The bridge decides auto again when the sign-in appears or goes."""
    upstream = (environ.get('PARTHENON_UPSTREAM') or 'auto').strip().lower()
    if upstream != 'auto':
        return upstream
    token = (environ.get('GROK_BRIDGE_TOKEN_FILE') or '').strip()
    if token and sign_in_usable(Path(token).expanduser()):
        return 'grok'
    for key, name in KEYED:
        if (environ.get(key) or '').strip():
            return name
    return 'openrouter'


def describe_upstream(env: Mapping[str, str], upstream: str) -> str:
    chosen = 'the Grok subscription' if upstream == 'grok' else upstream
    asked = (env.get('PARTHENON_UPSTREAM') or 'auto').strip().lower()
    return f'{asked}: {chosen}' if asked == 'auto' else chosen


def settings(environ: Mapping[str, str]) -> Dict[str, object]:
    data = Path(environ.get('PARTHENON_DATA_DIR') or '/data').expanduser().resolve()
    return {
        'data': data,
        'port': _int(environ, 'PORT', 10000),
        'bridge_port': _int(environ, 'GROK_BRIDGE_PORT', 5055),
        'python': environ.get('PARTHENON_PYTHON') or sys.executable,
        'user': (environ.get('PARTHENON_USER') or 'parthenon').strip(),
        'bridge_wait': _int(environ, 'PARTHENON_BRIDGE_WAIT', 60),
        # A stop: the backend's grace, then the bridge's own. Render kills the container 30 s after its SIGTERM.
        'stop_timeout': _int(environ, 'PARTHENON_STOP_TIMEOUT', 20),
        'bridge_stop_timeout': _int(environ, 'PARTHENON_BRIDGE_STOP_TIMEOUT', 5),
        'log_days': _int(environ, 'PARTHENON_LOG_DAYS', 14),
    }


def child_env(environ: Mapping[str, str], data: Path, port: int, bridge_port: int) -> Dict[str, str]:
    """The environment both processes run with. Explicit settings win over these defaults."""
    env = dict(environ)
    env['PARTHENON_DATA_DIR'] = str(data)
    env['PORT'] = str(port)
    # The bridge spends the provider keys: it only ever listens on loopback.
    env['GROK_BRIDGE_HOST'] = '127.0.0.1'
    env['GROK_BRIDGE_PORT'] = str(bridge_port)
    env['FLASK_DEBUG'] = 'false'
    env.setdefault('PYTHONUNBUFFERED', '1')
    env.setdefault('PARTHENON_UPSTREAM', 'auto')
    env.setdefault('PARTHENON_BASE', '/parthenon')
    env.setdefault('PARTHENON_FRONTEND_DIR', str(APP_DIR / 'frontend' / 'dist'))
    env.setdefault('MEMORY_BACKEND', 'local')
    env.setdefault('LOCAL_MEMORY_DB_PATH', str(data / 'uploads' / 'memory' / 'local_memory.sqlite3'))
    env.setdefault('HF_HOME', str(data / 'cache' / 'huggingface'))
    env.setdefault('GROK_BRIDGE_TOKEN_FILE', str(default_sign_in_file(data)))
    # The backend and the simulations reach every model through the bridge,
    # which puts the provider's own model in place of this name.
    env.setdefault('LLM_BASE_URL', f'http://127.0.0.1:{bridge_port}/v1')
    env.setdefault('LLM_API_KEY', 'parthenon-bridge')
    env.setdefault('LLM_MODEL_NAME', 'parthenon-free')
    if effective_upstream(env) == 'openrouter':
        # Graph building paced for the free tier (see .env.example). Read once by the backend: after a
        # first Grok sign-in it stays until the next restart, which only makes the Hearing a little slower.
        env.setdefault('LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS', '3.5')
    return env


# --------------------------------------------------------------------------- data folder


def prepare_data(data: Path) -> None:
    for sub in DATA_LAYOUT:
        (data / sub).mkdir(parents=True, exist_ok=True)
    for sub in PRIVATE_DIRS:
        os.chmod(data / sub, 0o700)


def link_into(link: Path, target: Path) -> None:
    """Make `link` a symlink to `target`; an existing link is re-pointed, a real folder must be empty."""
    if link.is_symlink():
        if os.readlink(link) == str(target):
            return
        link.unlink()
    elif link.exists():
        if link.is_dir() and not any(link.iterdir()):
            link.rmdir()
        else:
            raise StartError(f'{link} is a real folder with files in it; not hiding it behind {target}')
    link.symlink_to(target, target_is_directory=True)


def link_backend(app_dir: Path, data: Path) -> None:
    backend = app_dir / 'backend'
    link_into(backend / 'uploads', data / 'uploads')
    link_into(backend / 'logs', data / 'logs')
    if os.path.realpath(backend / 'uploads') != os.path.realpath(data / 'uploads'):
        raise StartError('backend/uploads does not lead into the data folder')


def prune_logs(folder: Path, days: int, now: Optional[float] = None) -> int:
    if days <= 0 or not folder.is_dir():
        return 0
    cutoff = (now or time.time()) - days * 86400
    removed = 0
    for path in folder.iterdir():
        try:
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def secure_sign_in(token_file: Optional[Path], uid: Optional[int] = None, gid: Optional[int] = None) -> None:
    """The Grok sign-in file, when there is one: the service user's (given uid/gid), mode 0600."""
    if token_file is None:
        return
    for problem in secure_sign_in_file(token_file, uid, gid):
        log(f'Grok sign-in: {problem}')


def prepare_ssh_home() -> None:
    """As root: Render's SSH into a Docker service needs the running user's ~/.ssh, mode 0700."""
    import pwd

    try:
        home = Path(pwd.getpwuid(0).pw_dir or '/root')
    except KeyError:
        home = Path('/root')
    ssh = home / '.ssh'
    try:
        if ssh.is_symlink() or (ssh.exists() and not ssh.is_dir()):
            log(f'{ssh} is not a folder; Render SSH may not work')
        elif not ssh.exists():
            ssh.mkdir(mode=0o700, parents=True)
        elif ssh.stat().st_mode & 0o777 != 0o700:
            os.chmod(ssh, 0o700)
    except OSError as error:
        log(f'could not prepare {ssh}: {error}')


def hand_over(data: Path, user: str, token_file: Optional[Path] = None) -> Optional[Dict[str, object]]:
    """As root: give the data folder (and the Grok sign-in file) to `user` and become that user.
    Returns the user's details. Not root: only makes the sign-in file private."""
    if os.geteuid() != 0:
        secure_sign_in(token_file)
        return None
    import pwd

    prepare_ssh_home()
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        log(f'no user {user!r}; running as root')
        secure_sign_in(token_file)
        return None
    uid, gid = entry.pw_uid, entry.pw_gid
    for root, dirs, files in os.walk(data):
        for name in [root, *(os.path.join(root, d) for d in dirs), *(os.path.join(root, f) for f in files)]:
            try:
                st = os.lstat(name)
                if st.st_uid != uid or st.st_gid != gid:
                    os.lchown(name, uid, gid)
            except OSError as error:
                log(f'could not hand {name} over: {error}')
    secure_sign_in(token_file, uid, gid)
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    os.environ['HOME'] = entry.pw_dir
    os.environ['USER'] = os.environ['LOGNAME'] = user
    return {'uid': uid, 'gid': gid, 'home': entry.pw_dir}


def seed_exhibits(env: Mapping[str, str], data: Path) -> None:
    from seed_exhibits import SeedError, seed

    try:
        result = seed(
            data,
            env.get('PARTHENON_EXHIBITS_URL'),
            env.get('PARTHENON_EXHIBITS_SHA256'),
            memory_db=Path(env['LOCAL_MEMORY_DB_PATH']),
        )
    except Exception as error:  # never keep the city from starting
        kind = 'not installed' if isinstance(error, SeedError) else f'failed ({type(error).__name__})'
        log(f'exhibits {kind} this time: {error}')
        return
    if result == 'no-url':
        log('PARTHENON_EXHIBITS_URL is not set; no exhibits')
    elif result == 'present':
        log('exhibits already installed')


# --------------------------------------------------------------------------- processes


def wait_for_bridge(port: int, process: subprocess.Popen, timeout: float) -> None:
    url = f'http://127.0.0.1:{port}/health'
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StartError(f'the bridge exited with status {process.returncode} before it answered')
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise StartError(f'the bridge did not answer on 127.0.0.1:{port} within {timeout:.0f}s')


def sign_in_lock_file(token_file: Path) -> Path:
    """The lock the bridge holds beside the sign-in while it refreshes or saves it (TokenStore.file_lock)."""
    return token_file.with_name(token_file.name + '.lock')


def hold_sign_in_lock(token_file: Optional[Path], deadline: float, pause: float = 0.05) -> Optional[int]:
    """Take the bridge's sign-in lock, waiting until `deadline` (time.monotonic) at most, and return its
    descriptor (closing it lets go). While it is held no Grok token refresh is under way and none can begin:
    the bridge holds the same lock from its refresh request until the rotated refresh token is on the disk.
    None when there is no sign-in (nothing to refresh), the lock cannot be opened, or it stays taken."""
    if token_file is None or not os.path.lexists(token_file):
        return None
    lock = sign_in_lock_file(token_file)
    try:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except PermissionError:
        try:  # made by another user (a root sign-in): flock works on a read-only descriptor too
            fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as error:
            log(f'cannot open the Grok sign-in lock {lock} ({error}); stopping the bridge without it')
            return None
    except OSError as error:
        log(f'cannot open the Grok sign-in lock {lock} ({error}); stopping the bridge without it')
        return None
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                log('the bridge is still refreshing the Grok sign-in; stopping it anyway')
                os.close(fd)
                return None
            time.sleep(pause)
        except OSError as error:
            log(f'cannot take the Grok sign-in lock {lock} ({error}); stopping the bridge without it')
            os.close(fd)
            return None


class Supervisor:
    """Runs the bridge and the backend; stops both when either ends or a signal arrives.

    A stop gives the backend `stop_timeout` to finish its own cleanup (then kills it alone), and only then
    stops the bridge: it first waits (up to 60% of `bridge_timeout`) for any Grok token refresh under way,
    holding the sign-in's lock so none begins, then sends it SIGTERM, and kills it `bridge_timeout` after
    its turn began."""

    def __init__(
        self,
        python: str,
        env: Mapping[str, str],
        cwd: Path,
        stop_timeout: float,
        bridge_timeout: float = 5.0,
        sign_in: Optional[Path] = None,
    ):
        self.python = python
        self.env = dict(env)
        self.cwd = cwd
        self.stop_timeout = stop_timeout
        self.bridge_timeout = bridge_timeout
        self.sign_in = sign_in
        self.bridge: Optional[subprocess.Popen] = None
        self.backend: Optional[subprocess.Popen] = None
        self.stopping_since: Optional[float] = None
        self.bridge_stopping_since: Optional[float] = None
        self.signals = 0
        self._sign_in_lock: Optional[int] = None

    def spawn(self, args: List[str]) -> subprocess.Popen:
        return subprocess.Popen([self.python, *args], cwd=str(self.cwd), env=self.env)

    def start_bridge(self) -> subprocess.Popen:
        self.bridge = self.spawn([str(APP_DIR / 'bridge' / 'grok_bridge.py'), 'serve'])
        return self.bridge

    def start_backend(self) -> subprocess.Popen:
        self.backend = self.spawn([str(DEPLOY_DIR / 'serve.py')])
        return self.backend

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, self.on_signal)

    def on_signal(self, signum, _frame) -> None:
        self.signals += 1
        if self.signals == 1:
            log(f'signal {signum}: stopping the backend, then the bridge')
            self.stopping_since = time.monotonic()
            self._send(self.backend, signal.SIGTERM)
            if self.backend is None:
                # Still starting: nothing has asked the bridge for anything, so no refresh can be under way.
                self._send(self.bridge, signal.SIGTERM)
            # Otherwise run() stops the bridge once the backend is gone.
        else:
            log('second signal: stopping everything now')
            self._send(self.backend, signal.SIGKILL)
            self._send(self.bridge, signal.SIGKILL)

    def _stop_bridge(self) -> None:
        """The bridge's turn: wait out a Grok token refresh under way (holding the lock so none begins),
        then SIGTERM. run() kills it if it is still there `bridge_timeout` after its turn began."""
        began = self.bridge_stopping_since = time.monotonic()
        if self.bridge is None or self.bridge.poll() is not None:
            return
        self._sign_in_lock = hold_sign_in_lock(self.sign_in, began + 0.6 * self.bridge_timeout)
        self._send(self.bridge, signal.SIGTERM)

    def _let_go_of_sign_in(self) -> None:
        if self._sign_in_lock is not None:
            try:
                os.close(self._sign_in_lock)
            except OSError:
                pass
            self._sign_in_lock = None

    @staticmethod
    def _send(process: Optional[subprocess.Popen], sig: int) -> None:
        if process is not None and process.poll() is None:
            try:
                process.send_signal(sig)
            except ProcessLookupError:
                pass

    def _reap(self) -> None:
        """Collect exited children: ours (Popen notices) and orphans the container hands to PID 1."""
        for process in (self.backend, self.bridge):
            if process is not None:
                process.poll()
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                return
            for process in (self.backend, self.bridge):
                # One of ours ended between its poll() and this wait: keep its real status.
                if process is not None and process.pid == pid and process.returncode is None:
                    process.returncode = os.waitstatus_to_exitcode(status)

    def run(self) -> int:
        """Watch until both are gone. The exit status is the first unexpected death's, else 0."""
        status = 0
        backend_killed = bridge_killed = False
        reported = set()
        try:
            while True:
                self._reap()
                backend_done = self.backend is None or self.backend.returncode is not None
                bridge_done = self.bridge is None or self.bridge.returncode is not None
                if self.stopping_since is not None:
                    for name, process in (('backend', self.backend), ('bridge', self.bridge)):
                        if process is not None and process.returncode is not None and name not in reported:
                            reported.add(name)
                            log(f'the {name} stopped (status {process.returncode})')
                if backend_done and bridge_done:
                    return status
                if self.stopping_since is None and (backend_done or bridge_done):
                    name, process = ('backend', self.backend) if backend_done else ('bridge', self.bridge)
                    code = process.returncode if process is not None else None
                    status = code if code else 1
                    log(f'the {name} exited with status {code}; stopping the other')
                    reported.add(name)
                    self.stopping_since = time.monotonic()
                    if name == 'bridge':
                        self._send(self.backend, signal.SIGTERM)
                if self.stopping_since is not None:
                    now = time.monotonic()
                    if not backend_done:
                        if not backend_killed and now - self.stopping_since > self.stop_timeout:
                            # Only the backend: the bridge still gets its own turn, and its SIGTERM.
                            log(f'the backend is still running {self.stop_timeout:.0f}s after the stop; killing it')
                            self._send(self.backend, signal.SIGKILL)
                            backend_killed = True
                    elif self.bridge_stopping_since is None:
                        # The backend has finished its own cleanup (or was killed); the bridge goes last.
                        self._stop_bridge()
                    elif not bridge_killed and now - self.bridge_stopping_since > self.bridge_timeout:
                        log(f'the bridge is still running {self.bridge_timeout:.0f}s after its stop; killing it')
                        self._send(self.bridge, signal.SIGKILL)
                        bridge_killed = True
                time.sleep(0.2)
        finally:
            self._let_go_of_sign_in()


def _stop_during_setup(signum, _frame) -> None:
    raise KeyboardInterrupt(signum)


def main(environ: MutableMapping[str, str] = os.environ) -> int:
    # Until the processes run, a stop signal simply ends the setup (as PID 1
    # the entrypoint would otherwise ignore SIGTERM).
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _stop_during_setup)
    try:
        conf = settings(environ)
        data: Path = conf['data']  # type: ignore[assignment]
        prepare_data(data)
        link_backend(APP_DIR, data)
        token_file = sign_in_file(environ, data)
        dropped = hand_over(data, str(conf['user']), token_file)
        if dropped:
            log(f"running as {conf['user']} (uid {dropped['uid']})")
        removed = prune_logs(data / 'logs', int(conf['log_days']))  # type: ignore[arg-type]
        if removed:
            log(f'removed {removed} old log file(s)')
        env = child_env(os.environ, data, int(conf['port']), int(conf['bridge_port']))  # type: ignore[arg-type]
        upstream = effective_upstream(env)
        log(
            f"data {data}; bridge 127.0.0.1:{conf['bridge_port']} ({describe_upstream(env, upstream)}); "
            f"site 0.0.0.0:{conf['port']}{env['PARTHENON_BASE'].rstrip('/')}/"
        )
        token = Path(env['GROK_BRIDGE_TOKEN_FILE'])
        if (env.get('PARTHENON_UPSTREAM') or '').strip().lower() in ('auto', 'grok') and not sign_in_usable(token):
            log(f'no Grok sign-in in {token} yet; sign the server in with deploy/grok_signin.py signin '
                '(docs/DEPLOY.md)')
        seed_exhibits(env, data)

        stop, bridge_stop = float(conf['stop_timeout']), float(conf['bridge_stop_timeout'])  # type: ignore[arg-type]
        if stop + bridge_stop > RENDER_STOP_SECONDS - 2:
            log(f'PARTHENON_STOP_TIMEOUT ({stop:.0f}) and PARTHENON_BRIDGE_STOP_TIMEOUT ({bridge_stop:.0f}) '
                f'add up to more than Render allows a stop ({RENDER_STOP_SECONDS} s, then it kills everything)')
        supervisor = Supervisor(
            str(conf['python']), env, data / 'run', stop, bridge_timeout=bridge_stop, sign_in=token,
        )
        supervisor.install_signal_handlers()
        bridge = supervisor.start_bridge()
        try:
            wait_for_bridge(int(conf['bridge_port']), bridge, float(conf['bridge_wait']))  # type: ignore[arg-type]
        except StartError:
            supervisor._send(bridge, signal.SIGTERM)
            try:
                bridge.wait(10)
            except subprocess.TimeoutExpired:
                bridge.kill()
            if supervisor.stopping_since is not None:
                return 0  # stopped while the bridge was starting
            raise
        if supervisor.stopping_since is not None:
            return supervisor.run()
        log('the bridge answers; starting the site')
        supervisor.start_backend()
        return supervisor.run()
    except StartError as error:
        log(f'cannot start: {error}')
        return 1
    except KeyboardInterrupt:
        log('stopped during setup')
        return 0


if __name__ == '__main__':
    sys.exit(main())
