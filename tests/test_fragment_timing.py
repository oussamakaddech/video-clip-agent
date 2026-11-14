from __future__ import annotations

from clipagent.models import Clip
from clipagent.pipeline import write_clip_ass
from clipagent.styles import STYLES
from clipagent.transcript import Transcript, parse_srt

SRT = """1
00:00:10,000 --> 00:00:20,000
Première phrase de l'extrait.

2
00:00:20,000 --> 00:00:40,000
Deuxième phrase très importante.
"""


def test_relative_ass_uses_fragment_reference():
    """En mode fragment, les temps sont relatifs au fragment (début = clip.start - offset)."""
    transcript = Transcript(segments=parse_srt(SRT))
    clip = Clip(index=1, start=10.0, end=40.0, title="T")
    path = write_clip_ass(transcript, clip, "/tmp/clip.ass", STYLES["default"], absolute=False, offset=1.5)
    content = path.read_text(encoding="utf-8")
    # fragment : t=0 correspond à la source 8.5 s → segment 10 s => 1.5 s
    assert "0:00:01.50,0:00:11.50" in content
    # segment 20 s => 11.5 s
    assert "0:00:11.50,0:00:31.50" in content


def test_relative_ass_hook_starts_at_cut_offset():
    """L'accroche doit démarrer au début de la coupe (offset), pas au début du fragment."""
    transcript = Transcript(segments=parse_srt(SRT))
    clip = Clip(index=1, start=10.0, end=40.0, title="T")
    path = write_clip_ass(
        transcript, clip, "/tmp/clip2.ass", STYLES["tiktok"], absolute=False, offset=1.5, hook_text="HOOK"
    )
    content = path.read_text(encoding="utf-8")
    assert "Dialogue: 1,0:00:01.50," in content


def test_absolute_ass_keeps_source_times():
    transcript = Transcript(segments=parse_srt(SRT))
    clip = Clip(index=1, start=10.0, end=40.0, title="T")
    path = write_clip_ass(transcript, clip, "/tmp/clip3.ass", STYLES["default"], absolute=True)
    content = path.read_text(encoding="utf-8")
    assert "0:00:10.00,0:00:20.00" in content
