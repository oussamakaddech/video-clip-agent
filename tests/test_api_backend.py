from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from clipagent.api.jobs import JobManager  # noqa: E402
from clipagent.service import ClipRequest, validate_request  # noqa: E402


# --- Validation ------------------------------------------------------------
def test_validate_request_accepts_complete_request():
    request = ClipRequest(url="https://kick.com/x/videos/y")
    assert validate_request(request) == []


def test_validate_request_requires_a_source():
    problems = validate_request(ClipRequest())
    assert any("Fournissez" in p for p in problems)


def test_validate_request_detects_missing_file():
    problems = validate_request(ClipRequest(video_path="C:/absent/video.mp4"))
    assert any("introuvable" in p for p in problems)


def test_validate_request_detects_bad_duration_range():
    problems = validate_request(ClipRequest(url="https://x.com/v", min_clip=90, max_clip=30))
    assert any("maximale" in p for p in problems)


def test_validate_request_detects_bad_url():
    problems = validate_request(ClipRequest(url="kick.com/x"))
    assert any("http" in p for p in problems)


# --- Concurrence / rétention ------------------------------------------------
def test_job_manager_limits_concurrency(tmp_path):
    manager = JobManager(tmp_path, max_concurrent=1)
    assert manager.max_concurrent == 1
    assert manager.running == 0


def test_job_manager_purge_keeps_recent(tmp_path):
    manager = JobManager(tmp_path)
    for index in range(5):
        job = manager.submit(ClipRequest(url="https://example.com/x"))
        job.status = "done"
    removed = manager.purge(keep=2)
    assert removed >= 1
    assert len(manager.list()) <= 3


def test_job_manager_running_counts_active(tmp_path):
    manager = JobManager(tmp_path)
    job = manager.submit(ClipRequest(url="https://example.com/x"))
    job.status = "running"
    assert manager.running == 1
    job.status = "done"
    assert manager.running == 0


# --- API -------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path):
    from clipagent.api.server import create_app

    return TestClient(create_app(tmp_path))


def test_api_rejects_invalid_job(client):
    response = client.post("/api/jobs", json={"num_clips": 3})
    assert response.status_code == 422
    assert "Fournissez" in response.json()["detail"]


def test_api_rejects_missing_file(client):
    response = client.post("/api/jobs", json={"video_path": "C:/absent/x.mp4"})
    assert response.status_code == 422


def test_provider_endpoint(client, monkeypatch):
    # Sans clé : le endpoint ne doit pas lancer d'appel réseau.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("CLIPAGENT_API_KEY", "")
    response = client.get("/api/provider")
    assert response.status_code == 200
    data = response.json()
    assert "model" in data
    assert "reachable" in data
    assert data["reachable"] is False
