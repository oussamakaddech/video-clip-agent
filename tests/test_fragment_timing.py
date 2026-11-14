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
    """En mode fragment, le transcript porte des temps relatifs au fragment.

    Le fragment téléchargé démarre à ``clip.start - offset`` : la sélection des
    segments se fait donc sur [offset, offset + durée] et les temps sont
    conservés tels quels (déjà relatifs au fragment).
    """
    transcript = Transcript(segments=parse_srt(SRT))
    clip = Clip(index=1, start=10.0, end=40.0, title="T")
    path = write_clip_ass(transcript, clip, "/tmp/clip.ass", STYLES["default"], absolute=False, offset=1.5)
    content = path.read_text(encoding="utf-8")
    # le segment 10→20 s du transcript (relatif au fragment) est conservé tel quel
    assert "0:00:10.00,0:00:20.00" in content
    # le segment 20→40 s est conservé également
    assert "0:00:20.00,0:00:31.50" in content


def test_relative_ass_selects_segments_inside_the_clip_window():
    """En mode fragment, seuls les segments situés dans la fenêtre du clip sont retenus."""
    transcript = Transcript(segments=parse_srt(SRT))
    clip = Clip(index=1, start=10.0, end=25.0, title="T")
    path = write_clip_ass(transcript, clip, "/tmp/clip4.ass", STYLES["default"], absolute=False, offset=1.5)
    content = path.read_text(encoding="utf-8")
    assert "0:00:10.00,0:00:16.50" in content   # fin découpée sur la fenêtre du clip
    # le second segment (20→40) est hors fenêtre : exclu
    assert "0:00:20.00,0:00:31.50" not in content


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
