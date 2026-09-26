"""GET /api/simulation/history carries what the Chronicles shelf shows.

For every run: the question that was asked, the newest Chronicle's title and
status, and its film (a status, and a poster once the film is complete), next
to every field the endpoint already returned.
"""

import json
import os

import pytest

from app import create_app
from app.api import simulation as simulation_api
from app.models.project import ProjectManager
from app.services import chronicle_film as film
from app.services.report_agent import (
    Report,
    ReportManager,
    ReportOutline,
    ReportSection,
    ReportStatus,
)
from app.services.simulation_manager import (
    SimulationManager,
    SimulationState,
    SimulationStatus,
)
from app.services.simulation_runner import SimulationRunner

SIM_ID = "sim_shelf_marble"
OTHER_SIM_ID = "sim_shelf_bread"
REPORT_ID = "report_shelf_marble"
QUESTION = "Should Athens rebuild its temple with public money?"
TITLE = "The Marble Question"
HISTORY_URL = "/api/simulation/history"

# What the endpoint returned before the shelf was added; none of it may go.
EXISTING_FIELDS = {
    "simulation_id", "project_id", "graph_id", "status", "entities_count",
    "profiles_count", "entity_types", "created_at", "updated_at",
    "simulation_requirement", "total_simulation_hours", "current_round",
    "runner_status", "total_rounds", "files", "report_id", "version",
    "created_date",
}


@pytest.fixture
def shelf(tmp_path, monkeypatch):
    """Reports and projects in temp folders (simulations already are, see conftest).

    The shelf finds a run's newest Chronicle through
    _get_report_id_for_simulation, which looks in the live uploads folder by
    a path of its own; here it looks in the temp reports folder instead.
    """

    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))

    def newest_report_id(simulation_id):
        reports = ReportManager.list_reports(simulation_id=simulation_id, limit=1)
        return reports[0].report_id if reports else None

    monkeypatch.setattr(simulation_api, "_get_report_id_for_simulation", newest_report_id)
    for simulation_id in (SIM_ID, OTHER_SIM_ID):
        SimulationRunner._run_states.pop(simulation_id, None)
    yield tmp_path
    for simulation_id in (SIM_ID, OTHER_SIM_ID):
        SimulationRunner._run_states.pop(simulation_id, None)
    with film._jobs_lock:
        film._active_jobs.discard(REPORT_ID)


@pytest.fixture
def client(shelf):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _save_simulation(simulation_id=SIM_ID, question=QUESTION, run=None):
    manager = SimulationManager()
    manager._save_simulation_state(
        SimulationState(
            simulation_id=simulation_id,
            project_id="proj_shelf",
            graph_id="graph_shelf",
            status=SimulationStatus.COMPLETED,
            entities_count=20,
            profiles_count=20,
            entity_types=["Citizen", "Council"],
            created_at="2026-09-25T09:00:00",
        )
    )
    sim_dir = manager._get_simulation_dir(simulation_id)
    with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "simulation_requirement": question,
                "time_config": {"total_simulation_hours": 17, "minutes_per_round": 60},
            },
            f,
        )
    if run:
        run_dir = os.path.join(SimulationRunner.RUN_STATE_DIR, simulation_id)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "run_state.json"), "w", encoding="utf-8") as f:
            json.dump(run, f)


def _save_report(report_id=REPORT_ID, simulation_id=SIM_ID,
                 status=ReportStatus.COMPLETED, outline=True):
    report = Report(
        report_id=report_id,
        simulation_id=simulation_id,
        graph_id="graph_shelf",
        simulation_requirement=QUESTION,
        status=status,
        outline=ReportOutline(
            title=TITLE,
            summary="The assembly split, then voted to build.",
            sections=[ReportSection(title="The vote", content="The city voted to build.")],
        ) if outline else None,
        markdown_content="# The Marble Question\n\nIctinus argued for marble; the farmers for bread.",
        created_at="2026-09-25T10:00:00",
    )
    ReportManager.save_report(report)
    return report


def _write_film(report_id=REPORT_ID, status="completed", poster=True):
    folder = film.film_folder(report_id)
    film.write_manifest(
        folder, {**film.empty_manifest(), "status": status, "title": "Frozen Before the Mark"}
    )
    if poster:
        with open(os.path.join(folder, film.POSTER_NAME), "wb") as f:
            f.write(b"\xff\xd8\xff\xd9")


def _shelf(client, **params):
    response = client.get(HISTORY_URL, query_string=params)
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["count"] == len(body["data"])
    return {entry["simulation_id"]: entry for entry in body["data"]}


def test_a_finished_run_with_a_filmed_chronicle_fills_the_shelf(client):
    _save_simulation(run={"runner_status": "completed", "current_round": 17, "total_rounds": 17})
    _save_report()
    _write_film()

    entry = _shelf(client)[SIM_ID]

    assert entry["question"] == QUESTION
    assert entry["report_id"] == REPORT_ID
    assert entry["report_title"] == TITLE
    assert entry["report_status"] == "completed"
    assert entry["film"]["status"] == "completed"
    poster_url = entry["film"]["poster_url"]
    assert poster_url.startswith(f"/api/parthenon/chronicle/{REPORT_ID}/film/poster.jpg?v=")
    # The same address the film page uses, so the shelf's poster is served.
    assert client.get(poster_url).status_code == 200

    # Nothing the old shelf relied on has gone.
    assert EXISTING_FIELDS <= set(entry)
    assert entry["simulation_requirement"] == QUESTION
    assert entry["runner_status"] == "completed"
    assert entry["current_round"] == 17 and entry["total_rounds"] == 17
    assert entry["entities_count"] == 20
    assert entry["created_date"] == "2026-09-25"
    assert entry["files"] == []


def test_a_run_without_a_chronicle_has_an_empty_shelf_entry(client):
    _save_simulation()

    entry = _shelf(client)[SIM_ID]

    assert entry["question"] == QUESTION
    assert entry["report_id"] is None
    assert entry["report_title"] is None
    assert entry["report_status"] is None
    assert entry["film"] == {"status": "none", "poster_url": None}
    assert entry["runner_status"] == "idle"
    assert entry["total_rounds"] == 17  # recommended from the time config


@pytest.mark.parametrize(
    ("manifest_status", "poster", "expected"),
    [
        (None, False, "none"),              # never filmed
        ("running", False, "failed"),       # left running by a backend that restarted
        ("failed", False, "failed"),
        ("completed", False, "completed"),  # finished, but the poster file is gone
    ],
)
def test_only_a_finished_film_offers_its_poster(client, manifest_status, poster, expected):
    _save_simulation()
    _save_report()
    if manifest_status:
        _write_film(status=manifest_status, poster=poster)

    entry = _shelf(client)[SIM_ID]

    assert entry["film"] == {"status": expected, "poster_url": None}
    if manifest_status:
        # The shelf only reads the manifest; the film page is what records a restart.
        assert film.read_manifest(REPORT_ID)["status"] == manifest_status


def test_a_film_still_being_made_is_running(client):
    _save_simulation()
    _save_report()
    _write_film(status="running", poster=False)
    with film._jobs_lock:
        film._active_jobs.add(REPORT_ID)

    assert _shelf(client)[SIM_ID]["film"] == {"status": "running", "poster_url": None}


def test_the_title_comes_from_the_outline_while_the_chronicle_is_being_written(client):
    _save_simulation()
    _save_report(status=ReportStatus.GENERATING, outline=False)
    ReportManager.save_outline(REPORT_ID, ReportOutline(title=TITLE, summary="", sections=[]))

    entry = _shelf(client)[SIM_ID]

    assert entry["report_status"] == "generating"
    assert entry["report_title"] == TITLE


def test_a_chronicle_that_cannot_be_read_does_not_break_the_shelf(client, monkeypatch):
    _save_simulation()
    folder = ReportManager._ensure_report_folder(REPORT_ID)
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    monkeypatch.setattr(simulation_api, "_get_report_id_for_simulation", lambda _sid: REPORT_ID)

    entry = _shelf(client)[SIM_ID]

    assert entry["report_id"] == REPORT_ID
    assert entry["report_title"] is None
    assert entry["report_status"] is None
    assert entry["film"] == {"status": "none", "poster_url": None}


def test_each_run_gets_its_own_chronicle(client):
    _save_simulation()
    _save_simulation(simulation_id=OTHER_SIM_ID, question="Bread before marble?")
    _save_report()

    entries = _shelf(client)

    assert entries[SIM_ID]["report_title"] == TITLE
    assert entries[OTHER_SIM_ID]["report_id"] is None
    assert entries[OTHER_SIM_ID]["report_title"] is None
    assert entries[OTHER_SIM_ID]["question"] == "Bread before marble?"
    assert len(_shelf(client, limit=1)) == 1
