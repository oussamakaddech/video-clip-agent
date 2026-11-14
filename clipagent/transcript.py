"""Lecture et manipulation des transcriptions (SRT / VTT / texte brut)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Segment

_TIMESTAMP_RE = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[.,](?P<ms>\d{1,3})"
)
_TIME_LINE_RE = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)
_CUE_NUMBER_RE = re.compile(r"^\s*\d+\s*$")
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def parse_timestamp(value: str) -> float:
    """Convertit ``HH:MM:SS,mmm`` / ``MM:SS.mmm`` / ``SS`` en secondes."""
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = "0", parts[0], parts[1]
    else:
        hours, minutes, seconds = "0", "0", parts[0]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_timestamp(seconds: float, *, comma: bool = True) -> str:
    """Formate un nombre de secondes en ``HH:MM:SS,mmm``."""
    seconds = max(0.0, float(seconds))
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    separator = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _clean_text(text: str) -> str:
    text = _TAG_RE.sub("", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


def parse_srt(content: str) -> list[Segment]:
    """Parse un fichier SRT (index, horodatage, texte)."""
    segments: list[Segment] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if _CUE_NUMBER_RE.match(lines[0]):
            lines = lines[1:]
        if not lines:
            continue
        match = _TIME_LINE_RE.match(lines[0])
        if not match:
            continue
        text = _clean_text(" ".join(lines[1:]))
        if not text:
            continue
        segments.append(
            Segment(
                index=len(segments) + 1,
                start=parse_timestamp(match.group("start")),
                end=parse_timestamp(match.group("end")),
                text=text,
            )
        )
    return segments


def parse_vtt(content: str) -> list[Segment]:
    """Parse un fichier WebVTT (mêmes blocs que SRT, sans index obligatoire)."""
    content = re.sub(r"^WEBVTT.*$", "", content, count=1, flags=re.MULTILINE)
    content = re.sub(r"^(NOTE|STYLE|REGION)\b.*$", "", content, flags=re.MULTILINE)
    return parse_srt(content)


def parse_plain_text(content: str, *, duration: float | None = None, window: float = 6.0) -> list[Segment]:
    """Découpe un texte brut en segments réguliers (transcription sans timecodes)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", content) if s.strip()]
    if not sentences:
        return []
    segments: list[Segment] = []
    cursor = 0.0
    step = window if duration is None else max(window, duration / max(1, len(sentences)))
    for sentence in sentences:
        segments.append(Segment(index=len(segments) + 1, start=cursor, end=cursor + step, text=sentence))
        cursor += step
    return segments


@dataclass
class Transcript:
    """Transcription complète d'une vidéo, indexée par segment."""

    segments: list[Segment]
    source: str | None = None

    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self):
        return iter(self.segments)

    @property
    def duration(self) -> float:
        return max((s.end for s in self.segments), default=0.0)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments)

    def window(self, start: float, end: float, *, margin: float = 0.0) -> list[Segment]:
        """Segments chevauchant l'intervalle [start, end] (marge optionnelle)."""
        lo, hi = start - margin, end + margin
        return [s for s in self.segments if s.end > lo and s.start < hi]

    def window_text(self, start: float, end: float, *, margin: float = 0.0) -> str:
        """Texte horodaté du segment [start, end]."""
        lines = [
            f"[{format_timestamp(s.start)} --> {format_timestamp(s.end)}] {s.text}"
            for s in self.window(start, end, margin=margin)
        ]
        return "\n".join(lines)

    def to_markdown(self, *, max_chars: int = 60_000) -> str:
        """Rendu compact destiné au LLM."""
        out: list[str] = []
        used = 0
        for segment in self.segments:
            line = f"[{format_timestamp(segment.start)} - {format_timestamp(segment.end)}] {segment.text}"
            if used + len(line) > max_chars:
                out.append("... (transcription tronquée) ...")
                break
            out.append(line)
            used += len(line)
        return "\n".join(out)

    def to_srt(self) -> str:
        blocks = []
        for segment in self.segments:
            blocks.append(
                f"{segment.index}\n"
                f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}\n"
                f"{segment.text}\n"
            )
        return "\n".join(blocks)

    def to_vtt(self) -> str:
        blocks = ["WEBVTT", ""]
        for segment in self.segments:
            blocks.append(
                f"{format_timestamp(segment.start, comma=False)} --> "
                f"{format_timestamp(segment.end, comma=False)}\n{segment.text}\n"
            )
        return "\n".join(blocks)


def load_transcript(path: str | Path) -> Transcript:
    """Charge une transcription depuis un fichier (SRT, VTT ou texte brut)."""
    path = Path(path)
    content = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix == ".srt":
        segments = parse_srt(content)
    elif suffix in {".vtt", ".webvtt"}:
        segments = parse_vtt(content)
    else:
        segments = parse_plain_text(content)
    return Transcript(segments=segments, source=str(path))
