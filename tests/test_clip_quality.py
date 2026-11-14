from __future__ import annotations

from clipagent.models import Clip, ClipProposal, Segment
from clipagent.selection import (
    anchor_to_hook,
    enforce_diversity,
    hook_score,
    title_similarity,
    validate_proposals,
)


def _segments() -> list[Segment]:
    return [
        Segment(index=1, start=0.0, end=5.0, text="Alright so here we go."),
        Segment(index=2, start=5.0, end=12.0, text="The key is to always start with a hook."),
        Segment(index=3, start=12.0, end=20.0, text="We doubled the engagement in one month."),
        Segment(index=4, start=20.0, end=30.0, text="Why did you do it? Because of the cache."),
    ]


def test_hook_score_detects_question():
    assert hook_score("Why did you do it?") >= 0.35


def test_hook_score_detects_number():
    assert hook_score("We doubled the engagement in one month") > 0.15


def test_hook_score_low_for_flat_sentence():
    assert hook_score("Alright so here we go") < 0.2


def test_anchor_to_hook_moves_start_to_strong_sentence():
    segments = _segments()
    # départ sur une phrase plate (0 s) → doit se poser sur la phrase accrocheuse (5 s)
    assert anchor_to_hook(0.0, 30.0, segments) == 5.0


def test_anchor_to_hook_keeps_strong_start():
    segments = _segments()
    assert anchor_to_hook(12.0, 30.0, segments) == 12.0


def test_anchor_to_hook_without_segments():
    assert anchor_to_hook(10.0, 20.0, []) == 10.0


def test_title_similarity():
    assert title_similarity("Cutting API code with caching", "Cutting API code with caching") == 1.0
    assert title_similarity("Cutting API code", "Gardening tips") < 0.2


def test_enforce_diversity_drops_similar_titles():
    clips = [
        Clip(index=1, start=0, end=60, title="Cutting API code with model caching", score=0.9),
        Clip(index=2, start=200, end=260, title="Cutting API code with model caching", score=0.5),
        Clip(index=3, start=400, end=460, title="Gardening in small apartments", score=0.4),
    ]
    kept = enforce_diversity(clips)
    assert len(kept) == 2
    assert kept[0].score == 0.9


def test_validate_proposals_applies_anchor_and_diversity():
    segments = _segments()
    proposals = [
        ClipProposal(start=0.0, end=30.0, title="API caching", score=0.9),
        ClipProposal(start=100.0, end=130.0, title="API caching", score=0.8),
    ]
    clips = validate_proposals(proposals, duration=600, min_length=20, max_length=60, segments=segments)
    # le doublon de titre est écarté
    assert len(clips) == 1
    # le début est ancré sur une phrase accrocheuse
    assert clips[0].start >= 5.0
