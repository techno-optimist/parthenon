"""
Whose gathering is it: owner keys and the lineage of ids.

A gathering begins as a project (proj_…). Its crowd is a simulation
(sim_…, state.json names the project) and its Chronicle a report
(report_…, meta.json names the simulation). The key handed back when the
project is made (owner_token) is kept only as a sha256 on the project record,
and every later simulation and report is owned through that lineage.
"""

import hashlib
import hmac
import os
import re
import secrets
from typing import Iterable, List, Optional, Set

from ..utils.json_files import read_json



def _managers():
    # Imported when first needed: app/__init__ imports this package early.
    from ..models.project import ProjectManager
    from ..services.report_agent import ReportManager
    from ..services.simulation_manager import SimulationManager

    return ProjectManager, SimulationManager, ReportManager


ID_PATTERNS = {
    'proj': re.compile(r'proj_[A-Za-z0-9_-]{1,120}'),
    'sim': re.compile(r'sim_[A-Za-z0-9_-]{1,120}'),
    'report': re.compile(r'report_[A-Za-z0-9_-]{1,120}'),
}
GATHERING_ID = re.compile(r'(proj|sim|report)_[A-Za-z0-9_-]{1,120}')
GRAPH_ID = re.compile(r'[A-Za-z0-9_-]{1,160}')
TASK_ID = re.compile(r'[A-Za-z0-9_-]{1,160}')
TOKEN = re.compile(r'[A-Za-z0-9_\-.~+/=]{16,256}')
MAX_LISTED_IDS = 100


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def valid_id(value, kind: Optional[str] = None) -> bool:
    if not isinstance(value, str):
        return False
    pattern = ID_PATTERNS.get(kind) if kind else GATHERING_ID
    return bool(pattern and pattern.fullmatch(value))


def parse_id_list(raw: Optional[str]) -> List[str]:
    """Well-formed gathering ids from a comma list (X-Parthenon-Owned), in order, at most 100."""

    found = []
    for item in str(raw or '').split(','):
        item = item.strip()
        if valid_id(item) and item not in found:
            found.append(item)
        if len(found) >= MAX_LISTED_IDS:
            break
    return found


def _read_json(path: str):
    """The record at path, or None; a record caught half written is read again once."""

    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def simulation_record(simulation_id: str):
    if not valid_id(simulation_id, 'sim'):
        return None
    return _read_json(os.path.join(_managers()[1].SIMULATION_DATA_DIR, simulation_id, 'state.json'))


def report_record(report_id: str):
    if not valid_id(report_id, 'report'):
        return None
    return _read_json(os.path.join(_managers()[2].REPORTS_DIR, report_id, 'meta.json'))


def project_record(project_id: str):
    if not valid_id(project_id, 'proj'):
        return None
    return _read_json(os.path.join(_managers()[0].PROJECTS_DIR, project_id, 'project.json'))


def project_of(gathering_id: str) -> Optional[str]:
    """The project a proj_/sim_/report_ id belongs to, or None when there is none."""

    if valid_id(gathering_id, 'proj'):
        return gathering_id if project_record(gathering_id) is not None else None
    if valid_id(gathering_id, 'sim'):
        state = simulation_record(gathering_id)
        project_id = state.get('project_id') if state else None
        return project_id if valid_id(project_id, 'proj') and project_record(project_id) is not None else None
    if valid_id(gathering_id, 'report'):
        meta = report_record(gathering_id)
        simulation_id = meta.get('simulation_id') if meta else None
        return project_of(simulation_id) if valid_id(simulation_id, 'sim') else None
    return None


def simulation_of(report_id: str) -> Optional[str]:
    meta = report_record(report_id)
    simulation_id = meta.get('simulation_id') if meta else None
    return simulation_id if valid_id(simulation_id, 'sim') else None


def projects_of_graph(graph_id: str) -> List[str]:
    """Every project whose graph this is."""

    if not isinstance(graph_id, str) or not GRAPH_ID.fullmatch(graph_id):
        return []
    try:
        return [project.project_id for project in _managers()[0].find_projects_by_graph_id(graph_id)]
    except Exception:  # noqa: BLE001 - an unreadable project owns nothing
        return []


def owner_hash_of(project_id: str) -> Optional[str]:
    record = project_record(project_id)
    value = record.get('owner_token_hash') if record else None
    return value if isinstance(value, str) and value else None


def token_owns(token: Optional[str], project_id: Optional[str]) -> bool:
    """Whether the key is the one handed out when this project was begun."""

    if not token or not isinstance(token, str) or not TOKEN.fullmatch(token) or not project_id:
        return False
    stored = owner_hash_of(project_id)
    if not stored:
        return False
    return hmac.compare_digest(stored, token_hash(token))


def expand_ids(ids: Iterable[str]) -> Set[str]:
    """The ids given plus the simulation of every report among them (for the shelf)."""

    found = set()
    for item in ids:
        found.add(item)
        if valid_id(item, 'report'):
            simulation_id = simulation_of(item)
            if simulation_id:
                found.add(simulation_id)
    return found
