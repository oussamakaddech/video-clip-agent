from __future__ import annotations

from clipagent.models import Clip
from clipagent.pipeline import write_clip_ass
from clipagent.styles import STYLES
from clipagent.transcript import Transcript, parse_srt

SRT = """1
00:00:00,000 --> 00:00:06,000
Bonjour, voici une transcription de test.

2
00:00:06,000 --> 00:00:18,000
La clé c'est de toujours commencer par une accroche forte.
"""

ARABIC_SRT = """1
00:00:00,000 --> 00:00:06,000
مرحبا بكم في هذه الحلقة.

2
00:00:06,000 --> 00:00:18,000
المفتاح هو أن تبدأ دائماً بخطاف قوي.
"""


def _transcript(content: str) -> Transcript:
    return Transcript(segments=parse_srt(content))


def test_write_clip_ass_contains_two_styles(tmp_path):
    transcript = _transcript(SRT)
    clip = Clip(index=1, start=0.0, end=18.0, title="Test")
    path = write_clip_ass(transcript, clip, tmp_path / "clip.ass", STYLES["tiktok"])
    content = path.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "Style: Sub," in content
    assert "Style: Hook," in content
    assert "[Events]" in content
    assert "Dialogue: 0," in content


def test_write_clip_ass_includes_hook_event(tmp_path):
    transcript = _transcript(SRT)
    clip = Clip(index=1, start=0.0, end=18.0, title="Test")
    path = write_clip_ass(transcript, clip, tmp_path / "clip.ass", STYLES["tiktok"], hook_text="LE HOOK")
    content = path.read_text(encoding="utf-8")
    assert "Dialogue: 1," in content
    assert "LE HOOK" in content
    assert ",Hook,,0,0,0,," in content


def test_write_clip_ass_without_hook_has_no_hook_event(tmp_path):
    transcript = _transcript(SRT)
    clip = Clip(index=1, start=0.0, end=18.0, title="Test")
    path = write_clip_ass(transcript, clip, tmp_path / "clip.ass", STYLES["podcast"], hook_text="")
    content = path.read_text(encoding="utf-8")
    assert "Dialogue: 1," not in content


def test_write_clip_ass_uses_absolute_timestamps(tmp_path):
    transcript = _transcript(SRT)
    clip = Clip(index=1, start=6.0, end=18.0, title="Test")
    path = write_clip_ass(transcript, clip, tmp_path / "clip.ass", STYLES["default"])
    content = path.read_text(encoding="utf-8")
    assert "0:00:06.00,0:00:18.00" in content


def test_write_clip_ass_handles_arabic(tmp_path):
    transcript = _transcript(ARABIC_SRT)
    clip = Clip(index=1, start=0.0, end=18.0, title="اختبار")
    path = write_clip_ass(transcript, clip, tmp_path / "clip.ass", STYLES["arabic"], hook_text="هل يمكن؟")
    content = path.read_text(encoding="utf-8")
    assert "مرحبا بكم" in content
    assert "هل يمكن؟" in content
    # l'événement est bien formé (texte avec ":" et "،" conservés)
    assert "Dialogue: 0," in content


def test_write_clip_ass_fallback_when_transcript_is_empty(tmp_path):
    transcript = Transcript(segments=[])
    clip = Clip(index=1, start=10.0, end=20.0, title="Titre de secours")
    path = write_clip_ass(transcript, clip, tmp_path / "clip.ass", STYLES["default"])
    content = path.read_text(encoding="utf-8")
    assert "Titre de secours" in content
