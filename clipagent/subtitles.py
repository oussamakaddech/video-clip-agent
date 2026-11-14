"""Génération des fichiers de sous-titres ASS (sous-titres + accroche).

Un fichier ASS porte **deux styles** : celui des sous-titres et celui de
l'accroche TikTok (police, taille, position, contour et fond propres). Le
rendu passe par libass, qui assure aussi la mise en forme (shaping) des
caractères arabes.

Deux référentiels de temps coexistent :
- ``absolute=True``  : les temps du transcript sont ceux de la SOURCE (rendu sur
  le fichier complet, seek de sortie) ;
- ``absolute=False`` : les temps du transcript sont ceux du FRAGMENT téléchargé
  (début du fragment = ``offset``), le clip occupant ``[offset, offset+durée]``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .hooks import hook_lines
from .models import Clip
from .transcript import Transcript


def _ass_time(seconds: float) -> str:
    """Horodatage ASS ``H:MM:SS.cc``."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rest = seconds % 60
    return f"{hours}:{minutes:02d}:{rest:05.2f}"


def subtitle_style_line(style, *, canvas_height: int = 1920) -> str:
    """Ligne de style ASS des sous-titres.

    Quand la face cam est active, les sous-titres remontent au-dessus du
    bandeau du visage (sinon ils passent dessous).
    """
    subtitle = style.subtitle
    if getattr(style, "facecam_enabled", False):
        bottom = int(canvas_height * (1 - getattr(style, "facecam_top_ratio", 0.67)))
        subtitle = replace(subtitle, margin_v=bottom + 30)
    return subtitle.to_ass_style("Sub")


def write_clip_ass(
    transcript: Transcript,
    clip: Clip,
    path: str | Path,
    style,
    *,
    absolute: bool = True,
    hook_text: str = "",
    offset: float = 0.0,
) -> Path:
    """Écrit le fichier ASS d'un extrait (sous-titres + accroche)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        subtitle_style_line(style),
        style.hook_style.to_ass_style("Hook"),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    if absolute:
        win_start, win_end = clip.start, clip.end
    else:
        win_start, win_end = offset, offset + clip.duration

    events: list[str] = []
    for segment in transcript.window(win_start, win_end):
        if absolute:
            start, end = segment.start, segment.end
        else:
            start = max(0.0, segment.start)
            end = min(offset + clip.duration, segment.end)
        if end <= start:
            continue
        text = segment.text.replace("\n", "\\N")
        if style.subtitle.uppercase:
            text = text.upper()
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Sub,,0,0,0,,{text}")

    if hook_text:
        lines = hook_lines(hook_text, max_chars_per_line=max(18, style.hook_max_chars // 2))
        # Auto-cale : une ligne trop longue réduirait la police pour tenir dans la largeur.
        longest = max((len(line) for line in lines), default=0)
        reference = max(18, style.hook_max_chars // 2)
        font_size = style.hook_style.size
        if longest > reference:
            font_size = max(40, int(style.hook_style.size * reference / longest))
        payload = "\\N".join(f"{{\\fs{font_size}}}{line}" for line in lines)
        # L'accroche doit démarrer au début de la coupe (output 0 s).
        hook_start = clip.start if absolute else offset
        events.append(
            f"Dialogue: 1,{_ass_time(hook_start)},{_ass_time(hook_start + style.hook_duration)},"
            f"Hook,,0,0,0,,{payload}"
        )

    if not events:
        fallback_start = clip.start if absolute else offset
        events.append(
            f"Dialogue: 0,{_ass_time(fallback_start)},"
            f"{_ass_time(fallback_start + clip.duration)},Sub,,0,0,0,,{clip.title}"
        )

    path.write_text("\n".join(header + events) + "\n", encoding="utf-8")
    return path
