from __future__ import annotations

import json

import pytest

from clipagent.config import Settings
from clipagent.model_picker import (
    PROBE_TOOLS,
    ProbeResult,
    _extract_json,
    _param_size,
    candidate_models,
    read_cache,
    score_probe,
    write_cache,
)


# --- Filtres et tri --------------------------------------------------------
def test_param_size_extraction():
    assert _param_size("nvidia/nemotron-3-ultra-550b-a55b") == 550
    assert _param_size("llama-3.1-70b-instruct") == 70
    assert _param_size("petit-model") == 0


def test_candidate_models_excludes_non_chat(monkeypatch):
    import clipagent.model_picker as picker

    monkeypatch.setattr(
        "clipagent.service.list_models",
        lambda settings=None: [
            {"id": "nvidia/nemotron-3-ultra-550b-a55b"},
            {"id": "nvidia/llama-3.1-nemotron-70b-instruct"},
            {"id": "nvidia/nv-embedqa-e5-v5"},
            {"id": "nvidia/nemotron-parse-2.0"},
            {"id": "nvidia/nemotron-4-340b-reward"},
            {"id": "some/llama-3.2-90b-vision-instruct"},
        ],
    )
    settings = Settings.from_env(model="nvidia/nemotron-3-ultra-550b-a55b")
    candidates = candidate_models(settings, limit=10)
    assert candidates[0] == "nvidia/nemotron-3-ultra-550b-a55b"   # le modèle courant d'abord
    assert "nvidia/nv-embedqa-e5-v5" not in candidates
    assert "nvidia/nemotron-parse-2.0" not in candidates
    assert "nvidia/nemotron-4-340b-reward" not in candidates
    assert "nvidia/llama-3.1-nemotron-70b-instruct" in candidates


def test_candidate_models_prefers_bigger_models(monkeypatch):
    monkeypatch.setattr(
        "clipagent.service.list_models",
        lambda settings=None: [
            {"id": "vendor/small-8b-instruct"},
            {"id": "vendor/huge-405b-instruct"},
        ],
    )
    settings = Settings.from_env(model="vendor/huge-405b-instruct")
    candidates = candidate_models(settings, limit=5)
    assert candidates[0] == "vendor/huge-405b-instruct"


# --- Extraction JSON --------------------------------------------------------
def test_extract_json_from_plain_text():
    payload = _extract_json('Voici ma proposition : {"start": 10, "end": 40, "title": "Test"}')
    assert payload is not None
    assert payload["end"] == 40


def test_extract_json_handles_nested_and_noise():
    payload = _extract_json('texte {"a": {"b": 1}, "c": "x"} suite')
    assert payload == {"a": {"b": 1}, "c": "x"}


def test_extract_json_returns_none_when_absent():
    assert _extract_json("pas de json ici") is None
    assert _extract_json("") is None
    assert _extract_json("{json cassé") is None


# --- Notation ---------------------------------------------------------------
def test_score_probe_rewards_success_and_quality():
    good = ProbeResult(model="m", ok=True, latency=1.0, quality=1.0)
    poor = ProbeResult(model="m", ok=True, latency=30.0, quality=0.4)
    failed = ProbeResult(model="m", ok=False, latency=1.0, quality=0.0)
    assert score_probe(good) > score_probe(poor) > score_probe(failed)
    assert score_probe(failed) == 0.0


def test_probe_tool_schema_is_valid():
    assert PROBE_TOOLS[0]["type"] == "function"
    parameters = PROBE_TOOLS[0]["function"]["parameters"]
    assert parameters["type"] == "object"
    assert "start" in parameters["properties"]
    assert parameters["required"] == ["start", "end", "title"]


# --- Cache ------------------------------------------------------------------
def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("clipagent.model_picker.CACHE_FILE", tmp_path / "bench.json")
    write_cache("nvidia", [{"model": "m1", "score": 1.0}])
    cached = read_cache("nvidia")
    assert cached is not None
    assert cached[0]["model"] == "m1"
    assert read_cache("autre") is None


def test_cache_expires(tmp_path, monkeypatch):
    path = tmp_path / "bench.json"
    path.write_text(
        json.dumps({"provider": "nvidia", "timestamp": 0, "results": []}), encoding="utf-8"
    )
    monkeypatch.setattr("clipagent.model_picker.CACHE_FILE", path)
    assert read_cache("nvidia") is None
