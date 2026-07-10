import pytest
from fastapi.testclient import TestClient

from aetheris.api.app import create_app
from aetheris.api.state import AppState
from aetheris.controller.queue import TaskState


@pytest.fixture
def client(tmp_path):
    state = AppState.create(root=str(tmp_path / "data"))
    app = create_app(state=state, auto_tick=False)
    with TestClient(app) as c:
        c.app_state = app.state.aetheris
        yield c


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_post_task_enqueues(client):
    r = client.post("/tasks", json={"task": "hello there"})
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "queued" and body["task"] == "hello there"
    listing = client.get("/tasks").json()
    assert any(t["id"] == body["id"] for t in listing)


def test_get_task_by_id_and_404(client):
    created = client.post("/tasks", json={"task": "read path=/x"}).json()
    assert client.get(f"/tasks/{created['id']}").status_code == 200
    assert client.get("/tasks/task-9999-nope").status_code == 404


def test_empty_task_rejected_422(client):
    assert client.post("/tasks", json={"task": ""}).status_code == 422


def test_task_runs_through_to_done_via_executive(client):
    created = client.post("/tasks", json={"task": "just chatting"}).json()
    for _ in range(5):
        client.app_state.executive.run_once()
    got = client.get(f"/tasks/{created['id']}").json()
    assert got["state"] == TaskState.DONE.value


def test_unsafe_task_is_blocked_not_bypassed(client):
    created = client.post("/tasks", json={"task": "create path=out.txt content=hi"}).json()
    for _ in range(5):
        client.app_state.executive.run_once()
    got = client.get(f"/tasks/{created['id']}").json()
    assert got["state"] == TaskState.BLOCKED.value


def test_events_recent_reflects_activity(client):
    client.post("/tasks", json={"task": "hello"})
    events = client.get("/events/recent").json()
    assert any(e["kind"] == "queue_transition" for e in events)


def test_evaluation_summary_shape(client):
    r = client.get("/evaluation/summary")
    assert r.status_code == 200
    assert "pass_rate" in r.json()


def test_memory_and_learning_endpoints(client):
    assert client.get("/memory/knowledge").status_code == 200
    assert client.get("/memory/experience").status_code == 200
    ls = client.get("/learning/state").json()
    assert "extra_keywords" in ls and "steps" in ls


def test_trigger_improve_endpoint(client):
    r = client.post("/learning/improve")
    assert r.status_code == 200
    body = r.json()
    assert "improved" in body
    assert isinstance(body["improved"], bool)


def test_revert_endpoint_on_empty_is_not_reverted(client):
    r = client.post("/learning/revert")
    assert r.status_code == 200
    assert r.json()["reverted"] is False


def test_trigger_improve_endpoint(client):
    r = client.post("/learning/improve")
    assert r.status_code == 200
    body = r.json()
    assert "improved" in body
    assert isinstance(body["improved"], bool)


def test_revert_endpoint_on_empty_is_not_reverted(client):
    r = client.post("/learning/revert")
    assert r.status_code == 200
    assert r.json()["reverted"] is False
