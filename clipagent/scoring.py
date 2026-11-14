"""Classement des fenêtres candidates d'une VOD (logique pure, testable).

Deux signaux complémentaires :
- le **mouvement** de l'image (mesuré dans le navigateur pendant le storyboard) ;
- l'**activité du chat replay** (une vague de messages signale un moment fort).

Le score final mélange les deux, puis espace les fenêtres retenues pour
couvrir toute la durée du live.
"""

from __future__ import annotations

from dataclasses import dataclass

from .browser import FrameSample


@dataclass
class Candidate:
    """Une fenêtre candidate, avec son score composite (image + chat)."""

    start: float
    end: float
    motion: float = 0.0
    chat: float = 0.0
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "motion": round(self.motion, 3),
            "chat": round(self.chat, 2),
            "score": round(self.score, 3),
        }


def peak_bonus(samples: list[FrameSample]) -> list[float]:
    """Bonus de pic local : un échantillon actif entre deux échantillons calmes."""
    motions = [s.motion for s in samples]
    bonuses: list[float] = []
    for index, sample in enumerate(samples):
        before = motions[index - 1] if index > 0 else 0.0
        after = motions[index + 1] if index + 1 < len(motions) else 0.0
        bonuses.append(max(0.0, sample.motion - (before + after) / 2))
    return bonuses


def detect_peaks(
    samples: list[FrameSample],
    *,
    count: int = 8,
    min_gap: float = 180.0,
) -> list[FrameSample]:
    """Retient les échantillons les plus « mouvementés », bien espacés."""
    if not samples:
        return []
    bonuses = peak_bonus(samples)
    bonus_by_time = {s.timestamp: b for s, b in zip(samples, bonuses)}
    scored = sorted(samples, key=lambda s: -(s.motion + 0.6 * bonus_by_time[s.timestamp]))

    chosen: list[FrameSample] = []
    for sample in scored:
        if all(abs(sample.timestamp - other.timestamp) >= min_gap for other in chosen):
            chosen.append(sample)
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda s: s.timestamp)


def score_candidates(
    samples: list[FrameSample],
    chat_messages: list | None = None,
    *,
    count: int = 8,
    window: float = 80.0,
    min_gap: float = 120.0,
    motion_weight: float = 0.55,
) -> list[Candidate]:
    """Classe les fenêtres candidates : mouvement de l'image + activité du chat.

    Score final = ``motion_weight`` × mouvement normalisé
                 + (1 - ``motion_weight``) × activité du chat normalisée.
    """
    from .chat import chat_heat

    chat_messages = chat_messages or []
    if not samples:
        return []

    bonuses = peak_bonus(samples)
    max_motion = max(s.motion for s in samples) or 1.0
    heats = [chat_heat(chat_messages, s.timestamp, s.timestamp + window) for s in samples]
    max_chat = max(heats, default=0.0) or 1.0

    ranked = []
    for sample, bonus, heat in zip(samples, bonuses, heats):
        motion_score = (sample.motion + 0.6 * bonus) / max_motion
        chat_score = heat / max_chat
        score = motion_weight * motion_score + (1 - motion_weight) * chat_score
        ranked.append((sample.timestamp, score, sample.motion, heat))
    ranked.sort(key=lambda item: -item[1])

    chosen: list[Candidate] = []
    for timestamp, score, motion, heat in ranked:
        if all(abs(timestamp - other.start) >= min_gap for other in chosen):
            chosen.append(
                Candidate(
                    start=max(0.0, timestamp - window / 2),
                    end=timestamp + window / 2,
                    motion=motion,
                    chat=heat,
                    score=score,
                )
            )
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda c: c.start)
