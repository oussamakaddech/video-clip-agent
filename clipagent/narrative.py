"""Découpage narratif : TextTiling de Hearst, adapté de ClipsAI.

ClipsAI (https://github.com/ClipsAI/clipsai, MIT) découpe une longue vidéo en
extraits en cherchant les **changements de sujet** dans la transcription, puis en
fusionnant progressivement les phrases en extraits de durée croissante. C'est un
complément utile à la sélection actuelle (densité de mots, chat, volume) : un
extrait narratif commence et finit sur une idée complète.

ClipsAI calcule ces frontières avec des plongements de phrases
(`sentence-transformers`) puis un TextTiling sur tenseurs PyTorch. Ici on garde
**l'algorithme**, pas les dépendances : les vecteurs sont lexicaux (sac de mots
normalisé, comme le TextTiling original de Hearst, 1997). Aucun modèle, aucun
réseau, quelques millisecondes — et donc testable comme le reste de
`clipagent.selection`.

Références :
- Hearst, *TextTiling: Segmenting Text into Multi-paragraph Subtopic Passages*,
  Computational Linguistics 23(1), 1997.
- ClipsAI, `clipsai/clip/texttiler.py` et `clipfinder.py` (copie datée dans
  `integrations/clipsai/`).
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass

from .models import ClipProposal, Segment
from .selection import overlap_ratio, score_segment

# Mots vides : ils ne portent pas le sujet, ils polluent la similarité.
STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are aren't as at be because
    been before being below between both but by can can't cannot could couldn't did
    didn't do does doesn't doing don't down during each few for from further had
    hadn't has hasn't have haven't having he he'd he'll he's her here here's hers
    herself him himself his how how's i i'd i'll i'm i've if in into is isn't it
    it's its itself let's me more most mustn't my myself no nor not of off on once
    only or other ought our ours ourselves out over own same shan't she she'd she'll
    she's should shouldn't so some such than that that's the their theirs them
    themselves then there there's these they they'd they'll they're they've this
    those through to too under until up very was wasn't we we'd we'll we're we've
    were weren't what what's when when's where where's which while who who's whom
    why why's with won't would wouldn't you you'd you'll you're you've your yours
    yourself yourselves
    au aux avec ce ces cet cette dans de des du elle elles en est et eux il ils je
    la le les leur lui ma mais me mes moi mon ne nos notre nous on ou par pas pour
    qu que qui sa se ses si son sur ta te tes toi ton tu un une vos votre vous y
    est-ce c'est j'ai j'sais ben bah bon ouais quoi ça ca fait genre juste
    """.split()
)

TOKEN_RE = re.compile(r"[0-9a-zA-ZÀ-ÖØ-öø-ÿ']+")
SENTENCE_END = re.compile(r"[.!?…]+\s*$")

# Paramètres de ClipsAI conservés tels quels.
CUTOFF_POLICY = "high"        # frontière = creux plus profond que moyenne + écart-type
SMOOTHING_WIDTH = 3
MIN_UNITS = 2                 # on arrête de fusionner sous ce nombre d'unités
DEDUPE_TOLERANCE = 15.0       # deux extraits à moins de 15 s d'écart sont le même


@dataclass(frozen=True)
class Sentence:
    """Une phrase horodatée, unité de base du TextTiling."""

    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def split_sentences(
    segments: list[Segment],
    *,
    max_chars: int = 240,
    pause: float = 1.1,
) -> list[Sentence]:
    """Rassemble les segments SRT en phrases (fin de phrase, pause ou longueur)."""
    sentences: list[Sentence] = []
    start: float | None = None
    end = 0.0
    parts: list[str] = []

    def flush() -> None:
        nonlocal start, end, parts
        text = " ".join(parts).strip()
        if text and start is not None:
            sentences.append(Sentence(start=round(start, 3), end=round(end, 3), text=text))
        start, parts = None, []

    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        if start is None:
            start = segment.start
        elif segment.start - end > pause and parts:
            flush()
            start = segment.start
        parts.append(text)
        end = segment.end
        length = len(" ".join(parts))
        if SENTENCE_END.search(text) or length >= max_chars:
            flush()
    flush()
    # Une phrase qui en suit une autre de très près ne doit pas se coller à elle.
    return [s for s in sentences if s.text]


def tokenize(text: str) -> list[str]:
    """Mots significatifs en minuscules (mots vides retirés)."""
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if token.lower() not in STOPWORDS and len(token) > 2
    ]


def vector(text_or_tokens: str | list[str]) -> dict[str, float]:
    """Sac de mots normalisé (norme L2 = 1), suffisant pour un cosinus."""
    tokens = tokenize(text_or_tokens) if isinstance(text_or_tokens, str) else text_or_tokens
    counts: dict[str, float] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0.0) + 1.0
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0:
        return {}
    return {token: value / norm for token, value in counts.items()}


def cosine(first: dict[str, float], second: dict[str, float]) -> float:
    """Similarité cosinus de deux vecteurs creux (0 = rien en commun)."""
    if not first or not second:
        return 0.0
    return sum(value * second.get(token, 0.0) for token, value in first.items())


def _mean(vectors: list[dict[str, float]]) -> dict[str, float]:
    """Vecteur moyen d'une fenêtre (utilisation : comparer deux fenêtres)."""
    total: dict[str, float] = {}
    for item in vectors:
        for token, value in item.items():
            total[token] = total.get(token, 0.0) + value
    count = max(1, len(vectors))
    return {token: value / count for token, value in total.items()}


def gap_scores(vectors: list[dict[str, float]], k: int = 7) -> list[float]:
    """Similarité entre les k unités à gauche et à droite de chaque frontière."""
    n = len(vectors)
    if n < 2:
        return []
    scores: list[float] = []
    for gap in range(n - 1):
        left = _mean(vectors[max(0, gap - k + 1) : gap + 1])
        right = _mean(vectors[gap + 1 : min(gap + 1 + k, n)])
        scores.append(cosine(left, right))
    return scores


def cohesion_scores(
    vectors: list[dict[str, float]],
    times: list[tuple[float, float]],
    k: int = 7,
    *,
    pause_weight: float = 0.35,
    pause_scale: float = 1.2,
) -> list[float]:
    """Similarité lexicale corrigée par la pause entre deux unités.

    Sur des vecteurs lexicaux, deux blocs voisins qui ne partagent aucun mot
    obtiennent 0 partout : plus aucun creux, plus aucune frontière. La pause
    (silence entre deux phrases) est alors le seul signal fiable — et c'est
    aussi le meilleur marqueur d'un changement de sujet à l'oral. On la
    retranche, donc une longue pause creuse le score de cohésion.
    """
    scores = gap_scores(vectors, k)
    for gap, score in enumerate(scores):
        pause = max(0.0, times[gap + 1][0] - times[gap][1])
        scores[gap] = score - pause_weight * min(1.0, pause / pause_scale)
    return scores


def smooth(values: list[float], window_len: int = SMOOTHING_WIDTH) -> list[float]:
    """Moyenne glissante centrée, bords reflétés (le lissage du TextTiling)."""
    n = len(values)
    if window_len < 3 or n < window_len:
        return [float(value) for value in values]
    half = window_len // 2
    padded = (
        [2 * values[0] - value for value in reversed(values[1 : half + 1])]
        + list(values)
        + [2 * values[-1] - value for value in reversed(values[-half - 1 : -1])]
    )
    return [
        sum(padded[index : index + window_len]) / window_len
        for index in range(n)
    ]


def depth_scores(values: list[float]) -> list[float]:
    """Profondeur de chaque creux : écart aux deux pics qui l'encadrent."""
    depths: list[float] = []
    for gap, value in enumerate(values):
        left_peak = value
        for index in range(gap, -1, -1):
            if values[index] >= left_peak:
                left_peak = values[index]
            else:
                break
        right_peak = value
        for index in range(gap, len(values)):
            if values[index] >= right_peak:
                right_peak = values[index]
            else:
                break
        depths.append((left_peak - value) + (right_peak - value))
    return depths


def boundaries(
    depths: list[float],
    *,
    policy: str = CUTOFF_POLICY,
) -> list[int]:
    """1 après l'unité i quand i+1 commence un nouveau sujet (dernier = 1)."""
    n = len(depths) + 1
    if not depths:
        return [1]
    mean = statistics.fmean(depths)
    stdev = statistics.pstdev(depths)
    cutoff = {"average": mean, "high": mean + stdev, "low": mean - stdev}.get(policy)
    if cutoff is None:
        raise ValueError(f"cutoff_policy inconnu : {policy!r}")

    marks = [0] * n
    for index, depth in enumerate(depths):
        left = depths[max(0, index - 1)]
        right = depths[min(index + 1, len(depths) - 1)]
        if depth <= cutoff or depth < left or depth < right:
            continue
        if depth == left and depth == right:
            continue
        marks[index] = 1
    marks[-1] = 1
    return marks


def text_tile(
    vectors: list[dict[str, float]],
    k: int = 7,
    *,
    policy: str = CUTOFF_POLICY,
    times: list[tuple[float, float]] | None = None,
) -> list[int]:
    """TextTiling complet sur une liste de vecteurs (fenêtres de k unités)."""
    n = len(vectors)
    if n < 2:
        return [1]
    if k >= n:
        k = max(n // 5, 2)
    gaps = cohesion_scores(vectors, times, k) if times else gap_scores(vectors, k)
    if len(gaps) < SMOOTHING_WIDTH:
        smoothed = gaps
    else:
        smoothed = smooth(gaps, SMOOTHING_WIDTH)
    return boundaries(depth_scores(smoothed), policy=policy)


def _merge(units: list[dict], marks: list[int]) -> list[dict]:
    """Fusionne les unités entre deux frontières en unités plus grandes."""
    merged: list[dict] = []
    current: list[dict] = []

    def close() -> None:
        if not current:
            return
        members = list(current)
        # Cohérence = similarité moyenne entre unités voisines du groupe.
        # Deux paragraphes collés par erreur (sujets différents) la font chuter.
        coherence = (
            statistics.fmean(
                cosine(first["vector"], second["vector"])
                for first, second in zip(members, members[1:])
            )
            if len(members) > 1
            else 1.0
        )
        merged.append(
            {
                "start": members[0]["start"],
                "end": members[-1]["end"],
                "text": " ".join(item["text"] for item in members),
                "vector": _mean([item["vector"] for item in members]),
                "coherence": coherence,
                "parts": members,
            }
        )
        current.clear()

    for unit, mark in zip(units, marks):
        current.append(unit)
        if mark:
            close()
    close()  # sécurité : la dernière unité est toujours une frontière
    return merged


def find_clips(
    sentences: list[Sentence],
    *,
    min_length: float = 20.0,
    max_length: float = 90.0,
    k_values: tuple[int, ...] = (5, 7),
    max_rounds: int = 6,
) -> list[dict]:
    """Extraits narratifs : fusion hiérarchique jusqu'aux durées demandées.

    À chaque passe, on tile les unités courantes, on fusionne selon les
    frontières, et on retient les unités dont la durée tombe dans la fenêtre
    [min_length, max_length]. On recommence sur les unités fusionnées pour
    obtenir des extraits de plus en plus longs.
    """
    if not sentences:
        return []

    found: list[dict] = []
    for k in k_values:
        units = [
            {
                "start": sentence.start,
                "end": sentence.end,
                "text": sentence.text,
                "vector": vector(sentence.text),
                "coherence": 1.0,
            }
            for sentence in sentences
        ]
        for _ in range(max_rounds):
            if len(units) <= MIN_UNITS:
                break
            merged: list[dict] = []
            # Le seuil « high » de ClipsAI suppose des plongements sémantiques ;
            # sur des vecteurs lexicaux il peut ne rien détecter. On relâche donc
            # le seuil jusqu'à obtenir au moins une frontière, au lieu de tout
            # fusionner en un seul bloc.
            for policy in ("high", "average", "low"):
                marks = text_tile(
                    [unit["vector"] for unit in units],
                    k,
                    policy=policy,
                    times=[(unit["start"], unit["end"]) for unit in units],
                )
                merged = _merge(units, marks)
                if len(merged) > 1:
                    break
            if len(merged) == len(units):
                break
            for unit in merged:
                _collect(unit, min_length, max_length, found)
            units = merged

    return found


def _collect(unit: dict, min_length: float, max_length: float, found: list[dict]) -> None:
    """Retient l'unité, ou la redécoupe si elle dépasse la durée maximale.

    Une fusion TextTiling peut sauter de 19 s à 79 s : sans ce redécoupage, la
    fenêtre [min, max] d'un extrait court serait franchie sans candidat.
    """
    duration = unit["end"] - unit["start"]
    if duration < min_length:
        return
    if duration <= max_length:
        if not _is_duplicate(unit, found):
            found.append(unit)
        return
    parts = unit.get("parts") or []
    if len(parts) < 2:
        return
    for part in parts:
        _collect(part, min_length, max_length, found)


def _is_duplicate(candidate: dict, found: list[dict]) -> bool:
    """Deux découpages à quelques secondes près racontent la même chose."""
    for item in found:
        distance = abs(candidate["start"] - item["start"]) + abs(candidate["end"] - item["end"])
        if distance < DEDUPE_TOLERANCE:
            return True
    return False


def _title(text: str, limit: int = 70) -> str:
    """Titre court : première phrase, sans point final."""
    first = re.split(r"(?<=[.!?…])\s+", text.strip())[0] if text.strip() else ""
    first = first.strip().rstrip(".")
    return first[:limit].rstrip() or "Extrait"


def narrative_proposals(
    segments: list[Segment],
    *,
    min_length: float = 20.0,
    max_length: float = 90.0,
    limit: int = 5,
) -> list[ClipProposal]:
    """Propositions d'extraits fondées sur les changements de sujet.

    Interface identique à ``selection.heuristic_proposals`` : le plan peut donc
    basculer d'un mode à l'autre sans changer le reste du pipeline.
    """
    if not segments:
        return []

    sentences = split_sentences(segments)
    if len(sentences) < 4:
        return []

    clips = find_clips(sentences, min_length=min_length, max_length=max_length)
    if not clips:
        return []

    proposals: list[ClipProposal] = []
    for clip in clips:
        # Le score mélange cohérence lexicale et signaux d'accroche : un extrait
        # hors sujet mais « punchy » ne doit pas passer devant un extrait net.
        punch = score_segment(
            Segment(index=0, start=clip["start"], end=clip["end"], text=clip["text"])
        )
        score = round(min(1.0, 0.65 * clip.get("coherence", 0.0) + 0.45 * punch), 3)
        proposals.append(
            ClipProposal(
                start=round(clip["start"], 3),
                end=round(clip["end"], 3),
                title=_title(clip["text"]),
                reason="Découpage narratif (changement de sujet, TextTiling)",
                score=score,
                tags=["narrative"],
                hook=_title(clip["text"], 42),
            )
        )

    proposals.sort(key=lambda item: (-item.score, item.start))
    selected: list[ClipProposal] = []
    for proposal in proposals:
        if len(selected) >= limit:
            break
        if all(
            overlap_ratio(proposal.start, proposal.end, kept.start, kept.end) < 0.35
            for kept in selected
        ):
            selected.append(proposal)
    return sorted(selected, key=lambda item: item.start)
