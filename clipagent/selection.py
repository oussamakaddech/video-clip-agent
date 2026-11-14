"""Sélection et validation des extraits : logique pure, sans dépendance externe.

Cette couche est le garde-fou de l'agent : le LLM propose, ce module valide
bornes, durées, chevauchements et doublons.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Clip, ClipProposal, Segment

# Mots-clés qui signalent un moment fort dans un flux de parole.
HOOK_PATTERNS = [
    r"\b(?:la clé|le point clé|ce qu'il faut retenir|à retenir|le secret|la méthode)\b",
    r"\b(?:tout le monde|jamais|personne|personne ne|incroyable|exceptionnellement)\b",
    r"\b(?:premier(?:e)? fois|record|dépass|jamais atteint)\b",
    r"\b(?:je vais montrer|on va voir|regardez|attention|surveillez)\b",
    r"\b(?:résumé|en résumé|conclusion|bilan|ce qu'on retient)\b",
    r"\b(?:question|réponse|problème|solution|erreur|attention)\b",
]
_HOOK_RE = re.compile("|".join(HOOK_PATTERNS), re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_WORD_RE = re.compile(r"[\wÀ-ÿ']+")


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Durée d'intersection entre deux intervalles."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Intersection sur union de deux intervalles."""
    inter = overlap_seconds(a_start, a_end, b_start, b_end)
    union = (a_end - a_start) + (b_end - b_start) - inter
    return inter / union if union > 0 else 0.0


def clamp_clip(
    start: float,
    end: float,
    *,
    duration: float | None = None,
    min_length: float = 5.0,
    max_length: float = 120.0,
) -> tuple[float, float]:
    """Borne les bornes dans [0, duration] et force une durée acceptable."""
    start = max(0.0, float(start))
    end = max(0.0, float(end))
    if duration is not None and duration > 0:
        start = min(start, duration)
        end = min(end, duration)
    if end <= start:
        end = start + min_length
    if end - start > max_length:
        end = start + max_length
    if end - start < min_length:
        end = start + min_length
        if duration is not None and duration > 0 and end > duration:
            end = duration
            start = max(0.0, end - min_length)
    return round(start, 3), round(end, 3)


def snap_to_sentence_boundaries(
    start: float,
    end: float,
    segments: list[Segment],
    *,
    max_shift: float = 3.0,
) -> tuple[float, float]:
    """Recale les bornes sur les limites de phrases (phrases de la transcription)."""
    if not segments:
        return start, end

    def nearest(boundary: float, candidates: list[float]) -> float:
        best, best_delta = boundary, None
        for candidate in candidates:
            delta = abs(candidate - boundary)
            if best_delta is None or delta < best_delta:
                best, best_delta = candidate, delta
        return best

    starts = [s.start for s in segments]
    ends = [s.end for s in segments]
    new_start = nearest(start, starts)
    new_end = nearest(end, ends)
    if abs(new_start - start) > max_shift:
        new_start = start
    if abs(new_end - end) > max_shift:
        new_end = end
    if new_end <= new_start:
        return start, end
    return round(new_start, 3), round(new_end, 3)


def overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Part de l'extrait le plus court qui est recouverte par l'autre."""
    inter = overlap_seconds(a_start, a_end, b_start, b_end)
    shortest = min(a_end - a_start, b_end - b_start)
    return inter / shortest if shortest > 0 else 0.0


def dedupe_clips(clips: list[ClipProposal], *, threshold: float = 0.35) -> list[ClipProposal]:
    """Supprime les propositions qui se recouvrent fortement (garde le meilleur score).

    Le recouvrement est mesuré sur l'extrait le plus court : deux extraits qui
    partagent plus de ``threshold`` de leur durée commune sont considérés
    comme redondants.
    """
    ordered = sorted(clips, key=lambda c: (-float(c.score), c.start))
    kept: list[ClipProposal] = []
    for clip in ordered:
        duplicate = False
        for existing in kept:
            if overlap_ratio(clip.start, clip.end, existing.start, existing.end) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(clip)
    return sorted(kept, key=lambda c: c.start)


def validate_proposals(
    proposals: list[ClipProposal],
    *,
    duration: float | None = None,
    min_length: float = 20.0,
    max_length: float = 90.0,
    limit: int = 5,
    segments: list[Segment] | None = None,
    snap: bool = True,
) -> list[Clip]:
    """Nettoie les propositions du LLM et les convertit en clips exploitables."""
    if not proposals:
        return []

    cleaned: list[ClipProposal] = []
    for proposal in proposals:
        start, end = clamp_clip(
            proposal.start,
            proposal.end,
            duration=duration,
            min_length=min_length,
            max_length=max_length,
        )
        if segments and snap:
            start, end = snap_to_sentence_boundaries(start, end, segments)
            start, end = clamp_clip(
                start,
                end,
                duration=duration,
                min_length=min_length,
                max_length=max_length,
            )
        cleaned.append(
            ClipProposal(
                start=start,
                end=end,
                title=(proposal.title or "Extrait").strip()[:120],
                reason=(proposal.reason or "").strip(),
                score=max(0.0, min(1.0, float(proposal.score))),
                tags=[t.strip() for t in (proposal.tags or []) if str(t).strip()][:8],
                hook=(proposal.hook or "").strip()[:120],
            )
        )

    unique = dedupe_clips(cleaned)
    selected = unique[: max(1, limit)]
    return [
        Clip(
            index=i,
            start=clip.start,
            end=clip.end,
            title=clip.title,
            reason=clip.reason,
            score=clip.score,
            tags=clip.tags,
            hook=clip.hook,
        )
        for i, clip in enumerate(selected, start=1)
    ]


def score_segment(segment: Segment) -> float:
    """Score heuristique d'un segment (0..1) : densité de mots + signaux rhétoriques."""
    words = _WORD_RE.findall(segment.text)
    if not words:
        return 0.0
    density = min(1.0, len(words) / 25)
    hook = 0.40 if _HOOK_RE.search(segment.text) else 0.0
    punch = 0.15 if any(t in segment.text for t in ("!", "?")) else 0.0
    return round(min(1.0, 0.55 * density + hook + punch), 3)


def heuristic_proposals(
    segments: list[Segment],
    *,
    min_length: float = 20.0,
    max_length: float = 90.0,
    limit: int = 5,
) -> list[ClipProposal]:
    """Sélection de repli sans LLM : on assemble les meilleurs segments consécutifs."""
    if not segments:
        return []

    scored = [(segment, score_segment(segment)) for segment in segments]
    window = max(1, int(round(min_length / max(1e-6, _median_segment_length(segments)))))
    candidates: list[ClipProposal] = []

    for i in range(len(scored) - window + 1):
        chunk = scored[i : i + window]
        start = chunk[0][0].start
        end = chunk[-1][0].end
        if end - start < min_length:
            continue
        if end - start > max_length:
            end = start + max_length
        mean_score = sum(score for _, score in chunk) / len(chunk)
        text = " ".join(seg.text for seg, _ in chunk)
        candidates.append(
            ClipProposal(
                start=round(start, 3),
                end=round(end, 3),
                title=_short_title(text),
                reason="Sélection heuristique (densité de mots + signaux d'accroche)",
                score=round(mean_score, 3),
                tags=[],
            )
        )

    if not candidates:
        return []

    candidates.sort(key=lambda c: -c.score)
    best = candidates[0]
    selected = [best]
    for candidate in candidates[1:]:
        if len(selected) >= limit:
            break
        if all(
            overlap_ratio(candidate.start, candidate.end, c.start, c.end) < 0.35
            for c in selected
        ):
            selected.append(candidate)
    return sorted(selected, key=lambda c: c.start)


def _median_segment_length(segments: list[Segment]) -> float:
    lengths = sorted(s.duration for s in segments if s.duration > 0)
    if not lengths:
        return 3.0
    return lengths[len(lengths) // 2]


def _short_title(text: str, limit: int = 70) -> str:
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    head = sentences[0] if sentences else text
    head = head.strip().rstrip(".")
    if len(head) > limit:
        head = head[: limit - 1].rstrip() + "…"
    return head
