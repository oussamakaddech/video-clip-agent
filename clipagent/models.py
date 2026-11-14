"""Structures de données partagées par le pipeline de clipping."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Segment:
    """Un segment de transcription horodaté."""

    index: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClipProposal:
    """Proposition d'extrait produite par l'agent (avant validation)."""

    start: float
    end: float
    title: str
    reason: str = ""
    score: float = 0.5
    tags: list[str] = field(default_factory=list)
    hook: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration"] = round(self.duration, 2)
        return data


@dataclass
class Clip:
    """Extrait final : proposition validée, rendu et rendu dans le rapport."""

    index: int
    start: float
    end: float
    title: str
    reason: str = ""
    score: float = 0.5
    tags: list[str] = field(default_factory=list)
    hook: str = ""
    path: str | None = None
    thumbnail: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "duration": round(self.duration, 2),
            "title": self.title,
            "reason": self.reason,
            "score": round(float(self.score), 3),
            "tags": list(self.tags),
            "hook": self.hook,
            "path": self.path,
            "thumbnail": self.thumbnail,
        }
