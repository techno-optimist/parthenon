"""Dockerfile.render's film tools: the image carries what features.film and the title card look for.

The image cannot be built here (no Docker), so the step that installs and checks the tools is
lifted out of the Dockerfile and run with /bin/sh, apt replaced by nothing and ffmpeg by stubs.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / 'Dockerfile.render'
FILM = REPO / 'backend' / 'app' / 'services' / 'chronicle_film.py'
PROVIDERS = REPO / 'backend' / 'app' / 'public' / 'providers.py'
FONTS = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',  # fonts-dejavu-core
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',  # fonts-noto-cjk
)
PACKAGES = ('ffmpeg', 'fonts-dejavu-core', 'fonts-noto-cjk')


def runtime_stage() -> str:
    """The last stage: the image that runs."""
    return DOCKERFILE.read_text().rsplit('\nFROM ', 1)[1]


def film_step() -> str:
    """The RUN after ARG PARTHENON_FILM_TOOLS, joined the way Docker joins its continued lines."""
    lines = runtime_stage().splitlines()
    start = lines.index('ARG PARTHENON_FILM_TOOLS=1') + 1
    assert lines[start].startswith('RUN ')
    step = []
    for line in lines[start:]:
        step.append(line)
        if not line.endswith('\\'):
            break
    return '\n'.join(step)[len('RUN '):].replace('\\\n', '')


def test_the_running_image_installs_the_film_tools_and_fonts():
    step = film_step()
    install = step.split('apt-get install', 1)[1].split('&&', 1)[0].split()
    for package in PACKAGES:
        assert package in install, package
    assert '--no-install-recommends' in install
    assert 'rm -rf /var/lib/apt/lists/*' in step
    # The film tools are installed in the final stage (the build stages do not
    # reach the image), and the build stage's compiler stays out of it.
    final = DOCKERFILE.read_text().rsplit('\nFROM ', 1)[1]
    assert step in final.replace('\\\n', '')
    assert 'gcc' not in final


def test_the_image_has_exactly_what_the_backend_looks_for():
    providers = PROVIDERS.read_text(encoding='utf-8')
    assert "find_tool('ffmpeg')" in providers and "find_tool('ffprobe')" in providers
    film = FILM.read_text(encoding='utf-8')
    step = film_step()
    for font in FONTS:
        assert font in film, f'the title card no longer looks for {font}'
        assert f'test -f {font}' in step
    # Every encoder and filter the build checks is one the film really uses.
    for encoder in ('libx264', 'aac'):
        assert f"'{encoder}'" in film and f"' {encoder} '" in step
    checked = step.split('for filter in ', 1)[1].split(';', 1)[0].split()
    assert len(checked) >= 6
    for name in checked:
        assert f'{name}=' in film or f'{name},' in film or f'{name}[' in film, name


def write_stub(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text('#!/bin/sh\n' + body, encoding='utf-8')
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def run_step(tmp_path: Path, *, filters: list, encoders=('libx264', 'aac'), fonts=True, env=None):
    """The film step with apt as a no-op, ffmpeg/ffprobe as stubs and the fonts in tmp_path."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    listing = ''.join(f' V....D {name:<20} {name}\\n' for name in encoders)
    filter_listing = ''.join(f' ... {name:<16} A->A       {name}\\n' for name in filters)
    write_stub(bin_dir, 'ffmpeg', (
        'echo "$@" >> "$CALLS"\n'
        f'case "$2" in -encoders) printf "{listing}" ;; -filters) printf "{filter_listing}" ;; esac\n'
    ))
    write_stub(bin_dir, 'ffprobe', 'echo "ffprobe $@" >> "$CALLS"\n')
    write_stub(bin_dir, 'apt-get', 'echo "apt-get $@" >> "$CALLS"\n')
    write_stub(bin_dir, 'rm', 'echo "rm $@" >> "$CALLS"\n')  # never the host's apt lists
    step = film_step()
    for number, font in enumerate(FONTS):
        local = tmp_path / f'font{number}'
        if fonts:
            local.write_bytes(b'font')
        step = step.replace(font, str(local))
    calls = tmp_path / 'calls.txt'
    calls.write_text('')
    shell = shutil.which('dash') or '/bin/sh'
    result = subprocess.run(
        [shell, '-c', step], capture_output=True, text=True, timeout=30,
        env={'PATH': f'{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin', 'CALLS': str(calls), **(env or {})},
    )
    return result, calls.read_text()


FILTERS = ['zoompan', 'xfade', 'acrossfade', 'loudnorm', 'tpad', 'apad', 'amix', 'atempo']


def test_the_film_step_passes_with_a_complete_ffmpeg(tmp_path):
    result, calls = run_step(tmp_path, filters=FILTERS)
    assert result.returncode == 0, result.stderr
    assert 'apt-get update' in calls
    assert 'apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fonts-noto-cjk' in calls
    assert 'ffprobe -hide_banner -version' in calls
    assert 'rm -rf /var/lib/apt/lists/' in calls


@pytest.mark.parametrize('missing', ['xfade', 'loudnorm'])
def test_the_film_step_stops_the_build_when_ffmpeg_lacks_a_filter(tmp_path, missing):
    result, _ = run_step(tmp_path, filters=[name for name in FILTERS if name != missing])
    assert result.returncode != 0
    assert f'ffmpeg lacks the {missing} filter' in result.stderr


def test_the_film_step_stops_the_build_without_libx264(tmp_path):
    result, _ = run_step(tmp_path, filters=FILTERS, encoders=('aac',))
    assert result.returncode != 0


def test_the_film_step_stops_the_build_without_the_fonts(tmp_path):
    result, _ = run_step(tmp_path, filters=FILTERS, fonts=False)
    assert result.returncode != 0


def test_film_tools_can_be_left_out(tmp_path):
    result, calls = run_step(tmp_path, filters=[], encoders=(), fonts=False, env={'PARTHENON_FILM_TOOLS': '0'})
    assert result.returncode == 0, result.stderr
    assert calls == ''


def test_film_needs_both_tools_on_the_path(tmp_path, monkeypatch):
    """Why the image carries them: with Grok Imagine available, film is offered only when both are found."""
    from app.public import providers
    from app.services import chronicle_film

    health = {'features': {'portraits': True, 'film': True, 'voice': True}}
    monkeypatch.setattr(chronicle_film, 'TOOL_FALLBACK_DIRS', ())
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    monkeypatch.setenv('PATH', str(bin_dir))
    assert providers.features_of(health)['film'] is False
    write_stub(bin_dir, 'ffmpeg', 'exit 0\n')
    assert providers.features_of(health)['film'] is False
    write_stub(bin_dir, 'ffprobe', 'exit 0\n')
    assert providers.features_of(health) == {'portraits': True, 'film': True, 'voice': True}


def test_the_blueprint_builds_with_the_film_tools():
    blueprint = (REPO / 'render.yaml').read_text()
    assert '- key: PARTHENON_FILM_TOOLS\n        value: "1"\n' in blueprint
