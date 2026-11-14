from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from clipagent.models import Clip  # noqa: E402
from clipagent.pipeline import Plan  # noqa: E402
from clipagent.service import (  # noqa: E402
    PROVIDERS,
    available_providers,
    compare_styles,
    list_models,
    update_clip,
)


# --- Service ---------------------------------------------------------------
def test_update_clip_changes_title_and_hook():
    plan = Plan(clips=[Clip(index=1, start=0, end=60, title="Ancien", hook="Vieux")])
    clip = update_clip(plan, 1, title="Nouveau titre", hook="Nouvelle accroche")
    assert clip is not None
    assert clip.title == "Nouveau titre"
    assert clip.hook == "Nouvelle accroche"


def test_update_clip_unknown_index_returns_none():
    plan = Plan(clips=[Clip(index=1, start=0, end=60, title="A")])
    assert update_clip(plan, 7, title="X") is None


def test_update_clip_keeps_title_when_only_hook_given():
    plan = Plan(clips=[Clip(index=1, start=0, end=60, title="Titre")])
    clip = update_clip(plan, 1, hook="Accroche")
    assert clip.title == "Titre"
    assert clip.hook == "Accroche"


def test_available_providers_cover_main_vendors():
    names = {p["name"] for p in available_providers()}
    assert {"openai", "nvidia", "ollama", "together", "groq"} <= names
    for provider in PROVIDERS.values():
        assert provider["base_url"].startswith("http")


def test_list_models_without_key_returns_defaults():
    from clipagent.config import Settings

    models = list_models(Settings.from_env(api_key=None))
    assert isinstance(models, list)


def test_compare_styles_requires_existing_clip(tmp_path):
    with pytest.raises(ValueError):
        compare_styles(
            Plan(clips=[]),
            3,
            ["tiktok"],
            settings=Settings_for_test(),
            fragments_dir=tmp_path,
            output_dir=tmp_path,
        )


def Settings_for_test():
    from clipagent.config import Settings

    return Settings.from_env(api_key=None)


# --- API -------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path):
    from clipagent.api.server import create_app

    return TestClient(create_app(tmp_path))


def test_options_endpoint_exposes_all_choices(client):
    data = client.get("/api/options").json()
    assert "yunet" in data["opencv"]["detectors"]
    assert "small" in data["whisper"]["models"]
    assert "libx264" in data["encoder"]["codecs"]
    assert len(data["providers"]) >= 5
    assert data["ffmpeg"]["path"]
    assert "ffmpeg" in (data["ffmpeg"]["version"] or "")


def test_models_endpoint_lists_providers(client):
    data = client.get("/api/models?provider=nvidia").json()
    assert "providers" in data
    assert "current" in data


def test_edit_clip_endpoint(client):
    # une tâche sans plan ne doit pas planter
    response = client.patch("/api/jobs/inconnu/clips/1", json={"title": "x"})
    assert response.status_code == 404


def test_style_endpoint_rejects_unknown_style(client):
    response = client.patch("/api/jobs/inconnu/style", json={"style": "inconnu"})
    assert response.status_code in {404, 422}


def test_compare_endpoint_without_fragments_returns_conflict(client):
    response = client.post("/api/jobs/inconnu/compare", json={"clip_index": 1})
    assert response.status_code in {404, 409}


def test_compare_file_endpoint_rejects_path_traversal(client):
    response = client.get("/api/jobs/inconnu/compare-file?path=../../etc/passwd")
    assert response.status_code in {404, 409}
