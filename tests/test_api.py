"""Tests de l'API et de la couche de service."""

from __future__ import annotations

import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from clipagent.api.jobs import JobManager  # noqa: E402
from clipagent.api.schemas import ClipJobRequest  # noqa: E402
from clipagent.service import ClipRequest, available_profiles, available_styles  # noqa: E402


# --- Schémas ---------------------------------------------------------------
def test_request_accepts_valid_payload():
    payload = ClipJobRequest(url="https://kick.com/x/videos/y", num_clips=5, min_clip=30, max_clip=60)
    assert payload.num_clips == 5
    assert payload.max_clip > payload.min_clip


def test_request_rejects_bad_url():
    with pytest.raises(Exception):
        ClipJobRequest(url="kick.com/x")


def test_request_rejects_max_below_min():
    with pytest.raises(Exception):
        ClipJobRequest(num_clips=3, min_clip=60, max_clip=30)


def test_request_rejects_out_of_range_clip_count():
    with pytest.raises(Exception):
        ClipJobRequest(num_clips=99)


# --- Service ---------------------------------------------------------------
def test_available_styles_contains_reference_layout():
    styles = {s["name"]: s for s in available_styles()}
    assert "streamer" in styles
    assert styles["streamer"]["facecam"] is True
    assert styles["tiktok"]["hook"] is True


def test_available_profiles_contains_livestream():
    profiles = {p["name"]: p for p in available_profiles()}
    assert "livestream" in profiles
    assert profiles["livestream"]["num_clips"] == 12


def test_clip_request_builds_settings():
    request = ClipRequest(style="hype", num_clips=4, min_clip=20, max_clip=50, subtitles=False)
    settings = request.settings()
    assert settings.style == "hype"
    assert settings.num_clips == 4
    assert settings.burn_subtitles is False


def test_unique_output_dir_is_unique(tmp_path):
    from clipagent.service import unique_output_dir

    first = unique_output_dir(tmp_path)
    second = unique_output_dir(tmp_path)
    assert first != second
    assert first.exists()


# --- Gestion des tâches ---------------------------------------------------
def test_job_manager_submit_and_complete(tmp_path):
    manager = JobManager(tmp_path)

    class _Fake:
        plan = type("P", (), {"clips": [], "mode": "test", "style": "default", "duration": 0.0, "warnings": []})()
        to_dict = lambda self: {"clips": []}  # noqa: E731

    manager._run = lambda job, render: (  # type: ignore[method-assign]
        setattr(job, "status", "done"),
        setattr(job, "progress", 1.0),
        setattr(job, "result", {"clips": []}),
    )
    job = manager.submit(ClipRequest(url="https://example.com/x"))
    for _ in range(50):
        if job.status in {"done", "error"}:
            break
        time.sleep(0.05)
    assert job.status == "done"
    assert manager.get(job.id) is not None
    assert job.to_dict()["id"] == job.id


def test_job_manager_cancel_marks_running_job(tmp_path):
    manager = JobManager(tmp_path)
    job = manager.submit(ClipRequest(url="https://example.com/x"))
    job.status = "running"
    assert manager.cancel(job.id) is True
    assert job.cancelled is True


# --- API ------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path):
    from clipagent.api.server import create_app

    app = create_app(tmp_path)
    return TestClient(app)


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_styles_endpoint(client):
    response = client.get("/api/styles")
    assert response.status_code == 200
    data = response.json()
    assert any(s["name"] == "streamer" for s in data["styles"])
    assert any(p["name"] == "livestream" for p in data["profiles"])


def test_job_creation_and_listing(client):
    response = client.post(
        "/api/jobs",
        json={"url": "https://kick.com/x/videos/y", "num_clips": 3, "render": False},
    )
    assert response.status_code == 200
    job_id = response.json()["id"]

    listing = client.get("/api/jobs")
    assert listing.status_code == 200
    assert any(j["id"] == job_id for j in listing.json())

    detail = client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == job_id


def test_unknown_job_returns_404(client):
    assert client.get("/api/jobs/inexistant").status_code == 404


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "clipagent" in response.text


def test_static_assets_are_served(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
