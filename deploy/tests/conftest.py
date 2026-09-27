"""Shared helpers for the deploy tests.

Run with the backend's environment:
    cd backend && .venv/bin/python -m pytest -q ../deploy/tests
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

DEPLOY_DIR = Path(__file__).resolve().parent.parent
REPO = DEPLOY_DIR.parent
for path in (DEPLOY_DIR, REPO / 'backend'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

NOW = '2026-09-27T00:00:00Z'


def make_memory(path: Path, graphs: dict) -> None:
    """A memory database with the backend's real schema (FTS and triggers) and a few rows per graph."""
    from app.memory.store import MemoryStore

    MemoryStore(str(path)).close()
    conn = sqlite3.connect(str(path))
    conn.execute('PRAGMA foreign_keys=ON')
    for graph_id, node_count in graphs.items():
        conn.execute(
            'INSERT INTO graphs (graph_id, uuid, name, created_at) VALUES (?, ?, ?, ?)',
            (graph_id, str(uuid.uuid4()), graph_id, NOW),
        )
        episode = str(uuid.uuid4())
        conn.execute(
            'INSERT INTO episodes (uuid, graph_id, kind, content, source, reference_time, created_at, '
            "extraction_status) VALUES (?, ?, 'document', ?, 'text', ?, ?, 'succeeded')",
            (episode, graph_id, f'The scroll of {graph_id}', NOW, NOW),
        )
        nodes = []
        for index in range(node_count):
            node = str(uuid.uuid4())
            nodes.append(node)
            conn.execute(
                'INSERT INTO nodes (uuid, graph_id, name, name_key, labels_json, created_at, updated_at) '
                "VALUES (?, ?, ?, ?, '[\"Citizen\"]', ?, ?)",
                (node, graph_id, f'Citizen {index} of {graph_id}', f'citizen {index} {graph_id}', NOW, NOW),
            )
            conn.execute('INSERT INTO node_episodes (node_uuid, episode_uuid) VALUES (?, ?)', (node, episode))
            conn.execute(
                'INSERT INTO node_aliases (graph_id, alias_key, node_uuid) VALUES (?, ?, ?)',
                (graph_id, f'alias {index}', node),
            )
        for source, target in zip(nodes, nodes[1:]):
            edge = str(uuid.uuid4())
            conn.execute(
                'INSERT INTO edges (uuid, graph_id, name, fact, fact_key, source_node_uuid, target_node_uuid, '
                "created_at) VALUES (?, ?, 'ANSWERS', ?, ?, ?, ?, ?)",
                (edge, graph_id, f'{source} answers {target}', f'{source}-{target}', source, target, NOW),
            )
            conn.execute(
                'INSERT INTO edge_episodes (edge_uuid, episode_uuid, linked_at) VALUES (?, ?, ?)',
                (edge, episode, NOW),
            )
        batch = f'batch-{graph_id}'
        conn.execute(
            "INSERT INTO batches (batch_id, status, created_at, updated_at) VALUES (?, 'succeeded', ?, ?)",
            (batch, NOW, NOW),
        )
        conn.execute(
            'INSERT INTO batch_items (item_id, batch_id, sequence_index, graph_id, episode_uuid, status, '
            "created_at, updated_at) VALUES (?, ?, 0, ?, ?, 'succeeded', ?, ?)",
            (str(uuid.uuid4()), batch, graph_id, episode, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO usage (scope_kind, scope_id, updated_at) VALUES ('graph', ?, ?)", (graph_id, NOW)
        )
    conn.commit()
    conn.close()


def graph_ids(path: Path) -> list:
    conn = sqlite3.connect(str(path))
    try:
        return sorted(row[0] for row in conn.execute('SELECT graph_id FROM graphs'))
    finally:
        conn.close()


def count(path: Path, table: str, graph_id: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f'SELECT COUNT(*) FROM {table} WHERE graph_id = ?', (graph_id,)).fetchone()[0]
    finally:
        conn.close()


def fts_problems(path: Path) -> list:
    from app.memory.store import MemoryStore

    store = MemoryStore(str(path))
    try:
        return store.fts_integrity_check()
    finally:
        store.close()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


def make_gathering(uploads: Path, n: int, graph_id: str) -> tuple:
    """A finished gathering's three folders; returns (project_id, simulation_id, report_id)."""
    project_id, simulation_id, report_id = f'proj_{n:012d}', f'sim_{n:012d}', f'report_{n:012d}'
    write_json(uploads / 'projects' / project_id / 'project.json', {'project_id': project_id, 'graph_id': graph_id})
    (uploads / 'projects' / project_id / 'files').mkdir(parents=True)
    (uploads / 'projects' / project_id / 'files' / 'scroll.md').write_text('# The scroll\n', encoding='utf-8')
    sim = uploads / 'simulations' / simulation_id
    write_json(sim / 'state.json', {'simulation_id': simulation_id, 'project_id': project_id, 'graph_id': graph_id})
    write_json(sim / 'stances.json', {'stances': []})
    (sim / 'portraits').mkdir(parents=True)
    (sim / 'portraits' / '0.jpg').write_bytes(b'\xff\xd8portrait\xff\xd9')
    (sim / 'simulation.log').write_text('/Users/someone/private/path\n', encoding='utf-8')
    (sim / 'ipc_commands').mkdir()
    (sim / 'ipc_commands' / 'cmd.json').write_text('{}', encoding='utf-8')
    rep = uploads / 'reports' / report_id
    write_json(rep / 'meta.json', {
        'report_id': report_id, 'simulation_id': simulation_id, 'graph_id': graph_id, 'status': 'completed',
    })
    (rep / 'film').mkdir(parents=True)
    (rep / 'film' / 'film.mp4').write_bytes(b'\x00\x00\x00\x18ftypmp42' + bytes(range(256)) * 40)
    return project_id, simulation_id, report_id


@pytest.fixture
def city(tmp_path):
    """Three finished gatherings and a memory database with their three graphs (and one more)."""
    uploads = tmp_path / 'uploads'
    ids = [make_gathering(uploads, n, f'mirofish_graph{n}') for n in (1, 2, 3)]
    memory = uploads / 'memory' / 'local_memory.sqlite3'
    memory.parent.mkdir(parents=True)
    make_memory(memory, {'mirofish_graph1': 3, 'mirofish_graph2': 2, 'mirofish_graph3': 4, 'mirofish_other': 2})
    specs = [f'Exhibit {n}={ids[n - 1][1]}:{ids[n - 1][2]}' for n in (1, 2)]
    return {'uploads': uploads, 'memory': memory, 'ids': ids, 'specs': specs, 'root': tmp_path}
