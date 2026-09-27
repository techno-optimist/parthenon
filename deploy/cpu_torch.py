#!/usr/bin/env python3
"""
The `uv sync` flags that leave the CUDA build of torch out of the container.

    python deploy/cpu_torch.py backend/uv.lock deploy/torch-cpu.txt

Prints one `--no-install-package=<name>` per line for torch, triton and every
nvidia-* package in the lock (the GPU stack torch pulls in on Linux x86_64),
after checking that deploy/torch-cpu.txt pins the same torch version as the
lock (with a +cpu local label). Exits 1 with a message when it does not.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import List, Tuple

GPU_PACKAGES = re.compile(r'^(torch|triton|nvidia-[a-z0-9-]+)$')
PIN = re.compile(r'^torch==([0-9][0-9A-Za-z.]*)\+cpu\b', re.MULTILINE)


class Mismatch(Exception):
    pass


def excluded_packages(lock_text: str) -> Tuple[str, List[str]]:
    """The lock's torch version and the names to leave out of `uv sync`."""
    lock = tomllib.loads(lock_text)
    names = sorted({p['name'] for p in lock.get('package', []) if GPU_PACKAGES.match(p.get('name', ''))})
    versions = {p['version'] for p in lock.get('package', []) if p.get('name') == 'torch'}
    if len(versions) != 1:
        raise Mismatch(f'expected one torch in the lock, found {sorted(versions) or "none"}')
    return versions.pop(), names


def pinned_version(requirements_text: str) -> str:
    match = PIN.search(requirements_text)
    if not match:
        raise Mismatch('torch-cpu.txt does not pin torch==<version>+cpu')
    return match.group(1)


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    lock_path, requirements_path = (Path(a) for a in argv)
    try:
        locked, names = excluded_packages(lock_path.read_text(encoding='utf-8'))
        pinned = pinned_version(requirements_path.read_text(encoding='utf-8'))
        if pinned != locked:
            raise Mismatch(
                f'backend/uv.lock has torch {locked} but deploy/torch-cpu.txt pins {pinned}+cpu: '
                'update the pin and both hashes from https://download.pytorch.org/whl/cpu/torch/'
            )
    except (OSError, ValueError, Mismatch) as error:
        print(f'cpu_torch: {error}', file=sys.stderr)
        return 1
    for name in names:
        print(f'--no-install-package={name}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
