from types import SimpleNamespace

import pytest

from app import create_app
from app.api import report as report_api
from app.services.report_agent import ReportStatus


class FakeTask:
    def __init__(self, status):
        self.status = status

    def to_dict(self):
        return {"task_id": "task-new", "status": self.status, "progress": 40}


@pytest.fixture
def client(monkeypatch):
    # The simulation already has a finished Chronicle from an earlier run.
    finished = SimpleNamespace(report_id="report_old", status=ReportStatus.COMPLETED)
    monkeypatch.setattr(report_api.ReportManager, "get_report_by_simulation", staticmethod(lambda _sid: finished))
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _status(client, **body):
    return client.post("/api/report/generate/status", json=body)


def test_a_regenerate_reports_its_own_progress_not_the_old_chronicle(client, monkeypatch):
    monkeypatch.setattr(report_api.TaskManager, "get_task", lambda _self, task_id: FakeTask("processing") if task_id == "task-new" else None)

    data = _status(client, task_id="task-new", simulation_id="sim_1").get_json()["data"]

    assert data["status"] == "processing"
    assert data["task_id"] == "task-new"


def test_without_a_live_task_the_finished_chronicle_is_reported(client, monkeypatch):
    monkeypatch.setattr(report_api.TaskManager, "get_task", lambda _self, _task_id: None)

    data = _status(client, task_id="task-gone", simulation_id="sim_1").get_json()["data"]

    assert data["status"] == "completed"
    assert data["report_id"] == "report_old"
    assert data["already_completed"] is True


def test_an_unknown_task_without_a_simulation_is_not_found(client, monkeypatch):
    monkeypatch.setattr(report_api.TaskManager, "get_task", lambda _self, _task_id: None)

    assert _status(client, task_id="task-gone").status_code == 404


def test_neither_id_is_a_bad_request(client):
    assert _status(client).status_code == 400
