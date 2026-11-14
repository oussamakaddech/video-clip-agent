from __future__ import annotations

import json
from pathlib import Path

from clipagent.config import Settings
from clipagent.models import Clip
from clipagent.pipeline import Plan, plan_clips, save_report, write_clip_srt
from clipagent.transcript import Transcript, parse_srt

SRT = """1
00:00:00,000 --> 00:00:06,000
Bonjour, bienvenue dans cet épisode.

2
00:00:06,000 --> 00:00:18,000
La clé c'est de toujours commencer par une accroche forte.

3
00:00:18,000 --> 00:00:34,000
Le résultat est inattendu : nous avons doublé l'engagement en un mois.
"""


def test_write_clip_srt_shifts_timestamps(tmp_path):
    transcript = Transcript(segments=parse_srt(SRT))
    clip = Clip(index=1, start=6.0, end=18.0, title="Accroche")
    path = write_clip_srt(transcript, clip, tmp_path / "clip.srt", absolute=False)
    content = path.read_text(encoding="utf-8")
    assert content.startswith("1\n")
    assert "00:00:00,000 --> 00:00:12,000" in content


def test_write_clip_srt_keeps_absolute_timestamps(tmp_path):
    """Le filtre subtitles de ffmpeg attend les horodatages de la source."""
    transcript = Transcript(segments=parse_srt(SRT))
    clip = Clip(index=1, start=6.0, end=18.0, title="Accroche")
    path = write_clip_srt(transcript, clip, tmp_path / "clip_abs.srt", absolute=True)
    content = path.read_text(encoding="utf-8")
    assert "00:00:06,000 --> 00:00:18,000" in content


def test_plan_clips_uses_heuristic_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings.from_env(api_key=None, num_clips=2, min_clip_seconds=6, max_clip_seconds=14)
    transcript = Transcript(segments=parse_srt(SRT))
    plan = plan_clips(None, transcript, settings)
    assert plan.mode == "heuristic"
    assert plan.clips
    assert any("clé" in w or "OPENAI_API_KEY" in w for w in plan.warnings)
    for clip in plan.clips:
        assert 6 <= clip.duration <= 14


def test_plan_clips_records_agent_failure_as_warning(tmp_path, monkeypatch):
    settings = Settings.from_env(api_key="dummy", num_clips=2, min_clip_seconds=6, max_clip_seconds=14)
    transcript = Transcript(segments=parse_srt(SRT))

    import clipagent.llm as llm_module

    def boom(*args, **kwargs):
        raise RuntimeError("réseau indisponible")

    monkeypatch.setattr(llm_module, "run_agent_chunked", boom)
    plan = plan_clips(None, transcript, settings)
    assert plan.mode == "heuristic"
    assert any("réseau indisponible" in w for w in plan.warnings)


def test_save_report_writes_json_and_markdown(tmp_path):
    plan = Plan(
        video="v.mp4",
        duration=120.0,
        mode="llm",
        model="gpt-4o-mini",
        clips=[Clip(index=1, start=10, end=40, title="Moment fort", reason="Accroche", score=0.8)],
    )
    json_path, md_path = save_report(plan, tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["clips"][0]["title"] == "Moment fort"
    assert data["clips"][0]["duration"] == 30.0
    markdown = md_path.read_text(encoding="utf-8")
    assert "# Plan de clipping" in markdown
    assert "Moment fort" in markdown


def test_save_report_creates_directory(tmp_path):
    target = tmp_path / "nested" / "out"
    json_path, _ = save_report(Plan(), target)
    assert Path(json_path).exists()
