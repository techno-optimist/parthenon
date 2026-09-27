#!/usr/bin/env python3
"""
Sign the public server in to Grok, and see which provider it is on.

Run inside the running service (`render ssh parthenon`, never --ephemeral: an
ephemeral instance has no disk). An SSH session does not carry the image's
PATH, so name the image's Python:

    /app/backend/.venv/bin/python /app/deploy/grok_signin.py signin
    /app/backend/.venv/bin/python /app/deploy/grok_signin.py status
    /app/backend/.venv/bin/python /app/deploy/grok_signin.py signout
    /app/backend/.venv/bin/python /app/deploy/grok_signin.py invite-link

signin       runs the bridge's own `login --no-browser` (xAI's OAuth device
             code: it prints a link and a code, which the owner approves at
             x.ai) as the service user (PARTHENON_USER, default parthenon),
             writing the server's sign-in file (GROK_BRIDGE_TOKEN_FILE,
             default <data>/grok-oauth.json). The file is then made the
             service user's, mode 0600, and the helper waits until the running
             bridge has taken it up. No restart.
status       which provider the running server is on (the bridge's /health
             and the site's status), and the sign-in file's owner and mode.
             Exit 0 only when the server is on the Grok subscription.
signout      runs the bridge's `logout` the same way; the server falls back to
             an API key, else OpenRouter's free models.
invite-link  the link to hand out, with each PARTHENON_INVITE_CODE encoded for
             a URL (a generated code is base64: + / and = must be escaped).

The sign-in is the server's own grant, never a copy of another machine's:
xAI rotates the refresh token on every refresh, so two holders of one grant
sign each other out. This never prints a token.

Settings are read from the running bridge's environment (/proc/<pid>/environ),
then this shell's, then the defaults the entrypoint uses.
"""

from __future__ import annotations

import argparse
import base64
import errno
import json
import os
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

DEPLOY_DIR = Path(__file__).resolve().parent
APP_DIR = DEPLOY_DIR.parent
BRIDGE_SCRIPT = APP_DIR / 'bridge' / 'grok_bridge.py'

TOKEN_NAME = 'grok-oauth.json'
TOKEN_MODE = 0o600
DEFAULT_DATA = '/data'
DEFAULT_USER = 'parthenon'
DEFAULT_SITE = 'https://projectforty2.ai/parthenon'
GROK = 'grok-subscription'  # the bridge's /health provider label for the subscription

# Only these are taken from the running server's environment; its keys are never kept.
SERVER_KEYS = (
    'GROK_BRIDGE_TOKEN_FILE', 'PARTHENON_DATA_DIR', 'GROK_BRIDGE_PORT', 'PORT', 'PARTHENON_BASE',
    'PARTHENON_USER', 'PARTHENON_INVITE_CODE', 'PARTHENON_PUBLIC_ORIGIN', 'PARTHENON_UPSTREAM',
)
# The login child gets a clean environment: these, plus the sign-in file and the user's HOME.
PASSED_TO_LOGIN = (
    'PATH', 'LANG', 'LC_ALL', 'TZ', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
    'HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'NO_PROXY', 'no_proxy',
)

PROVIDERS = {
    GROK: 'the Grok subscription (this server\'s own sign-in)',
    'grok': 'xAI with XAI_API_KEY',
    'openai': 'OpenAI with OPENAI_API_KEY',
    'claude': 'Anthropic with ANTHROPIC_API_KEY',
    'free': "OpenRouter's free models (the fallback)",
}


# --------------------------------------------------------------------------- the sign-in file


def default_sign_in_file(data: Path) -> Path:
    return Path(data) / TOKEN_NAME


def sign_in_file(environ: Mapping[str, str], data: Path) -> Path:
    """GROK_BRIDGE_TOKEN_FILE, else <data>/grok-oauth.json (what the entrypoint gives the bridge)."""
    raw = (environ.get('GROK_BRIDGE_TOKEN_FILE') or '').strip()
    return Path(raw).expanduser() if raw else default_sign_in_file(data)


def _jwt_exp(token: object) -> Optional[float]:
    try:
        payload = str(token).split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except (IndexError, ValueError, TypeError):
        return None
    exp = claims.get('exp') if isinstance(claims, dict) else None
    return float(exp) if isinstance(exp, (int, float)) else None


def sign_in_usable(path: Path) -> bool:
    """Whether `path` holds a sign-in the bridge would use, as its TokenStore.usable_state decides: an access
    token, not revoked, and a refresh token or an access token that has not expired. Reads, never prints."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return False
        state = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(state, dict) or not state.get('access_token') or state.get('revoked'):
        return False
    if not state.get('refresh_token'):
        exp = _jwt_exp(state['access_token'])
        if exp is not None and exp <= time.time():
            return False
    return True


def _siblings(path: Path) -> Tuple[Path, ...]:
    # The bridge keeps a lock file and writes through a temporary file beside the sign-in.
    return (path, path.with_name(path.name + '.lock'), path.with_name(path.name + '.tmp'))


def secure_sign_in_file(path: Path, uid: Optional[int] = None, gid: Optional[int] = None) -> List[str]:
    """Make the sign-in file (and the bridge's lock and temporary files beside it) mode 0600 and, given
    uid/gid (as root), owned by the service user. Links and non-files are left alone. Returns the problems."""
    problems: List[str] = []
    for candidate in _siblings(Path(path)):
        try:
            fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0))
        except FileNotFoundError:
            continue
        except OSError as error:
            if error.errno == errno.ELOOP:
                problems.append(f'{candidate} is a link; left alone')
            else:
                problems.append(f'{candidate} could not be opened ({error.strerror})')
            continue
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                problems.append(f'{candidate} is not a file; left alone')
                continue
            if uid is not None and gid is not None and (st.st_uid != uid or st.st_gid != gid):
                os.fchown(fd, uid, gid)
            if stat.S_IMODE(st.st_mode) != TOKEN_MODE:
                os.fchmod(fd, TOKEN_MODE)
        except OSError as error:
            problems.append(f'{candidate} could not be made private ({error.strerror})')
        finally:
            os.close(fd)
    return problems


def describe_file(path: Path, uid: Optional[int]) -> Tuple[str, List[str]]:
    """A line about the sign-in file (never its contents) and what is wrong with it."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return f'{path} (none: not signed in)', []
    except OSError as error:
        return f'{path} (cannot be read: {error.strerror})', []
    if not stat.S_ISREG(st.st_mode):
        return f'{path} (not a file)', ['the sign-in path is not a plain file']
    try:
        import pwd

        owner = pwd.getpwuid(st.st_uid).pw_name
    except (ImportError, KeyError):
        owner = str(st.st_uid)
    mode = stat.S_IMODE(st.st_mode)
    warnings = []
    if mode != TOKEN_MODE:
        warnings.append(f'its mode is {mode:04o}, not 0600')
    if uid is not None and st.st_uid != uid:
        warnings.append(f'it belongs to {owner}, not the service user, so the bridge may not read it')
    return f'{path} ({owner}, {mode:04o})', warnings


# --------------------------------------------------------------------------- the running server


def _read_nul(path: Path) -> List[str]:
    return [part for part in path.read_bytes().decode('utf-8', 'replace').split('\0') if part]


def server_environ(proc: Path = Path('/proc')) -> Tuple[Dict[str, str], str]:
    """SERVER_KEYS from the running bridge's environment (else the entrypoint's), and where they came from.
    An SSH session does not carry the service's environment; the processes the container started do."""
    found: Dict[str, Tuple[Path, str]] = {}
    try:
        entries = sorted((p for p in proc.iterdir() if p.name.isdigit()), key=lambda p: int(p.name))
    except OSError:
        return {}, ''
    for entry in entries:
        try:
            argv = _read_nul(entry / 'cmdline')
        except OSError:
            continue
        names = [Path(arg).name for arg in argv]
        if 'grok_bridge.py' in names and 'serve' in argv:
            found.setdefault('bridge', (entry, 'the running bridge'))
        elif 'start.py' in names and any(arg.endswith('deploy/start.py') for arg in argv):
            found.setdefault('start', (entry, 'the entrypoint'))
    for kind in ('bridge', 'start'):
        if kind not in found:
            continue
        entry, label = found[kind]
        try:
            pairs = _read_nul(entry / 'environ')
        except OSError:
            continue
        values = {}
        for pair in pairs:
            name, sep, value = pair.partition('=')
            if sep and name in SERVER_KEYS:
                values[name] = value
        return values, f'{label} (pid {entry.name})'
    return {}, ''


def get_json(url: str, timeout: float = 5.0) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- settings


@dataclass
class Settings:
    data: Path
    token_file: Path
    user: str
    bridge_port: int
    site_port: int
    base: str
    site: str
    invite_codes: List[str]
    python: str
    bridge: Path
    source: str = ''
    upstream: str = 'auto'
    passthrough: Dict[str, str] = field(default_factory=dict)

    @property
    def health_url(self) -> str:
        return f'http://127.0.0.1:{self.bridge_port}/health'

    @property
    def status_url(self) -> str:
        return f"http://127.0.0.1:{self.site_port}{self.base.rstrip('/')}/api/parthenon/status"


def _port(raw: str, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def resolve(args: argparse.Namespace, environ: Mapping[str, str], proc: Path) -> Settings:
    server, source = server_environ(proc)

    def pick(name: str, default: str = '') -> str:
        for place in (server, environ):
            value = (place.get(name) or '').strip()
            if value:
                return value
        return default

    data = Path(pick('PARTHENON_DATA_DIR', DEFAULT_DATA))
    token = Path(args.token_file).expanduser() if args.token_file else sign_in_file(
        {'GROK_BRIDGE_TOKEN_FILE': pick('GROK_BRIDGE_TOKEN_FILE')}, data)
    base = '/' + pick('PARTHENON_BASE', '/parthenon').strip('/')
    origin = pick('PARTHENON_PUBLIC_ORIGIN').split(',')[0].strip().rstrip('/')
    site = args.site or (f"{origin}{base.rstrip('/')}" if origin.startswith('https://') else DEFAULT_SITE)
    codes = [code.strip() for code in pick('PARTHENON_INVITE_CODE').split(',') if code.strip()]
    return Settings(
        data=data,
        token_file=token,
        user=args.user or pick('PARTHENON_USER', DEFAULT_USER),
        bridge_port=_port(pick('GROK_BRIDGE_PORT'), 5055),
        site_port=_port(pick('PORT'), 10000),
        base=base,
        site=site,
        invite_codes=codes,
        python=args.python or sys.executable,
        bridge=Path(args.bridge) if args.bridge else BRIDGE_SCRIPT,
        source=source or ('this shell' if environ.get('GROK_BRIDGE_TOKEN_FILE') else 'the defaults'),
        upstream=pick('PARTHENON_UPSTREAM', 'auto').lower(),
        passthrough={k: environ[k] for k in PASSED_TO_LOGIN if environ.get(k)},
    )


# --------------------------------------------------------------------------- running the bridge's commands


def service_account(user: str) -> Optional[Tuple[int, int, str]]:
    """(uid, gid, home) of `user` when this runs as root; None otherwise."""
    if os.geteuid() != 0:
        return None
    import pwd

    entry = pwd.getpwnam(user)  # KeyError: no such user
    return entry.pw_uid, entry.pw_gid, entry.pw_dir


def someone_else(user: str) -> Optional[str]:
    """Why this account must not write the sign-in: not root, and not the service user (when it exists here)."""
    if os.geteuid() == 0:
        return None
    try:
        import pwd

        uid = pwd.getpwnam(user).pw_uid
    except (ImportError, KeyError):
        return None  # no such user here: the file is this account's, as the bridge's will be
    if uid == os.geteuid():
        return None
    return (f'This shell is neither root nor {user}, so the file would not be readable by the bridge. '
            f'Run it as root (the image\'s user) or as {user}.')


def run_bridge(conf: Settings, command: Sequence[str], runner: Callable = subprocess.run) -> int:
    """The bridge's own CLI (`login --no-browser`, `logout`) as the service user, on the server's sign-in file."""
    env = dict(conf.passthrough)
    env.setdefault('PATH', '/usr/local/bin:/usr/bin:/bin')
    env.update({'GROK_BRIDGE_TOKEN_FILE': str(conf.token_file), 'PYTHONUNBUFFERED': '1'})
    kwargs = {'env': env, 'cwd': str(conf.token_file.parent), 'umask': 0o077}
    account = service_account(conf.user)
    if account is not None:
        uid, gid, home = account
        env.update({'HOME': home, 'USER': conf.user, 'LOGNAME': conf.user})
        kwargs.update({'user': uid, 'group': gid, 'extra_groups': []})
    elif os.environ.get('HOME'):
        env['HOME'] = os.environ['HOME']
    result = runner([conf.python, str(conf.bridge), *command], **kwargs)
    return int(result.returncode)


def wait_for_health(conf: Settings, done: Callable[[dict], bool], timeout: float, every: float) -> Optional[dict]:
    """Poll the bridge's /health until `done` says so or the time is up; the last answer (None: no answer)."""
    deadline = time.monotonic() + timeout
    health = get_json(conf.health_url)
    while not (health is not None and done(health)) and time.monotonic() < deadline:
        time.sleep(every)
        health = get_json(conf.health_url)
    return health


def on_grok(health: Optional[dict]) -> bool:
    return bool(health) and health.get('provider') == GROK and health.get('signed_in') is not False


def provider_words(health: Optional[dict]) -> str:
    if not health:
        return 'unknown (the bridge does not answer)'
    provider = str(health.get('provider') or health.get('upstream') or '?')
    return f"{provider}: {PROVIDERS.get(provider, 'an upstream this helper does not know')}"


# --------------------------------------------------------------------------- commands


def _refuse_a_local_env(conf: Settings, out) -> bool:
    env_file = conf.bridge.resolve().parent.parent / '.env'
    if env_file.exists():
        print(f'{env_file} exists beside this bridge, and the bridge loads it over these settings.', file=out)
        print('This helper signs in the public server. On your own machine, use `npm run grok:login`.', file=out)
        return True
    return False


def _check_place(conf: Settings, out) -> bool:
    parent = conf.token_file.parent
    if not parent.is_dir():
        print(f'There is no {parent} here, so this is not the running service with its disk.', file=out)
        print('Connect with `render ssh parthenon` (not --ephemeral), then run this again.', file=out)
        return False
    if conf.token_file.is_symlink() or (conf.token_file.exists() and not conf.token_file.is_file()):
        print(f'{conf.token_file} is not a plain file; move it aside first.', file=out)
        return False
    if not conf.bridge.is_file():
        print(f'The bridge is not at {conf.bridge}.', file=out)
        return False
    return True


def cmd_signin(conf: Settings, args: argparse.Namespace, out, runner: Callable = subprocess.run) -> int:
    if _refuse_a_local_env(conf, out) or not _check_place(conf, out):
        return 2
    try:
        account = service_account(conf.user)
    except KeyError:
        print(f'There is no user {conf.user!r} here to sign in as.', file=out)
        return 2
    wrong = someone_else(conf.user)
    if wrong:
        print(wrong, file=out)
        return 2
    print(f'Signing the server in to Grok. Sign-in file: {conf.token_file} (settings from {conf.source}).', file=out)
    if sign_in_usable(conf.token_file):
        print('The server already has a Grok sign-in; approving a new one replaces it.', file=out)
    if conf.upstream not in ('auto', 'grok'):
        print(f'Note: PARTHENON_UPSTREAM is {conf.upstream}, so the server will not use the sign-in until it is '
              'auto.', file=out)
    print('Open the link below on any device, check the code, and approve with the account that has the '
          'Grok subscription.', file=out, flush=True)
    try:
        code = run_bridge(conf, ['login', '--no-browser'], runner)
    except KeyboardInterrupt:
        print('\nStopped; nothing changed.', file=out)
        return 130
    if code != 0:
        print('The sign-in did not finish; nothing changed.', file=out)
        return code
    uid, gid = (account[0], account[1]) if account else (None, None)
    for problem in secure_sign_in_file(conf.token_file, uid, gid):
        print(f'Warning: {problem}', file=out)
    print('Waiting for the running bridge to take up the sign-in...', file=out, flush=True)
    health = wait_for_health(conf, on_grok, args.wait, args.every)
    if on_grok(health):
        print('The server is on the Grok subscription now: portraits, film and voices are on. No restart needed.',
              file=out)
        return 0
    if health is None:
        print(f'The sign-in is saved. The bridge does not answer on {conf.health_url}; it uses the sign-in '
              'when it starts.', file=out)
        return 1
    print(f'The sign-in is saved, but the bridge reports {provider_words(health)}.', file=out)
    print('PARTHENON_UPSTREAM must be auto (or grok) for the server to use it; a restart also takes it up.', file=out)
    return 1


def cmd_signout(conf: Settings, args: argparse.Namespace, out, runner: Callable = subprocess.run) -> int:
    if _refuse_a_local_env(conf, out) or not _check_place(conf, out):
        return 2
    wrong = someone_else(conf.user)
    if wrong:
        print(wrong, file=out)
        return 2
    try:
        code = run_bridge(conf, ['logout'], runner)
    except KeyError:
        print(f'There is no user {conf.user!r} here to sign out as.', file=out)
        return 2
    if code != 0:
        return code
    health = wait_for_health(conf, lambda h: not on_grok(h), args.wait, args.every)
    print(f'The server is now on {provider_words(health)}.', file=out)
    return 0


def cmd_status(conf: Settings, _args: argparse.Namespace, out) -> int:
    health = get_json(conf.health_url)
    site = get_json(conf.status_url)
    data = (site or {}).get('data') if isinstance((site or {}).get('data'), dict) else {}
    print(f'Provider:     {provider_words(health)}', file=out)
    if health and ('grok_signed_in' in health or 'signed_in' in health):
        signed_in = health.get('grok_signed_in', health.get('signed_in'))
        print(f"Signed in:    {'yes' if signed_in else 'no'} (Grok)", file=out)
    features = data.get('features') if isinstance(data.get('features'), dict) else None
    if features is not None:
        print('Features:     ' + ', '.join(
            f"{name} {'on' if features.get(name) else 'off'}" for name in ('portraits', 'film', 'voice')), file=out)
    elif health:
        print(f"Imagine:      {'yes' if health.get('imagine') else 'no'}; "
              f"voice: {'yes' if health.get('voice') else 'no'}", file=out)
    if site is None:
        print(f'Site:         does not answer on {conf.status_url}', file=out)
    elif 'invite_required' in data:
        codes = len(conf.invite_codes)
        told = f' ({codes} code{"s" if codes != 1 else ""})' if codes else ''
        print(f"Invite:       {'required' + told if data.get('invite_required') else 'not required'}", file=out)
    try:
        account = service_account(conf.user)
    except KeyError:
        account = None
    line, warnings = describe_file(conf.token_file, account[0] if account else None)
    print(f'Sign-in file: {line}', file=out)
    for warning in warnings:
        print(f'Warning:      {warning}; run signin again, or restart the service (the entrypoint repairs it).',
              file=out)
    if health is None:
        return 1
    if not on_grok(health) and sign_in_usable(conf.token_file):
        print('The file holds a sign-in the bridge is not using: PARTHENON_UPSTREAM may not be auto, '
              'or xAI no longer accepts it (sign in again).', file=out)
    return 0 if on_grok(health) else 1


def cmd_invite_link(conf: Settings, _args: argparse.Namespace, out) -> int:
    if not conf.invite_codes:
        print('No invite code is set (PARTHENON_INVITE_CODE): anyone with the link may begin gatherings.', file=out)
        return 1
    for code in conf.invite_codes:
        print(f"{conf.site}?invite={urllib.parse.quote(code, safe='')}", file=out)
    return 0


def main(argv: Optional[Sequence[str]] = None, *, environ: Mapping[str, str] = os.environ,
         proc: Path = Path('/proc'), out=None, runner: Callable = subprocess.run) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description='Sign the public Parthenon server in to Grok.')
    parser.add_argument('command', choices=('signin', 'status', 'signout', 'invite-link'))
    parser.add_argument('--token-file', help='the sign-in file (default: what the running bridge uses)')
    parser.add_argument('--user', help='the service user (default PARTHENON_USER, else parthenon)')
    parser.add_argument('--site', help=f'the public address for invite-link (default {DEFAULT_SITE})')
    parser.add_argument('--wait', type=float, default=30.0, help='seconds to wait for the bridge (default 30)')
    parser.add_argument('--every', type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument('--python', help=argparse.SUPPRESS)
    parser.add_argument('--bridge', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    conf = resolve(args, environ, proc)
    if args.command == 'signin':
        return cmd_signin(conf, args, out, runner)
    if args.command == 'signout':
        return cmd_signout(conf, args, out, runner)
    if args.command == 'status':
        return cmd_status(conf, args, out)
    return cmd_invite_link(conf, args, out)


if __name__ == '__main__':
    sys.exit(main())
