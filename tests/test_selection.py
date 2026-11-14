from __future__ import annotations

from clipagent.models import ClipProposal, Segment
from clipagent.selection import (
    clamp_clip,
    dedupe_clips,
    heuristic_proposals,
    iou,
    overlap_seconds,
    score_segment,
    snap_to_sentence_boundaries,
    validate_proposals,
)


def _proposal(start: float, end: float, score: float = 0.5, title: str = "Extrait") -> ClipProposal:
    return ClipProposal(start=start, end=end, title=title, score=score)


def test_overlap_and_iou():
    assert overlap_seconds(0, 10, 5, 15) == 5
    assert overlap_seconds(0, 5, 10, 15) == 0
    assert round(iou(0, 10, 0, 10), 3) == 1.0
    assert round(iou(0, 10, 5, 15), 3) == round(5 / 15, 3)


def test_clamp_clip_respects_bounds():
    start, end = clamp_clip(-5, 500, duration=100, min_length=10, max_length=60)
    assert start >= 0
    assert end <= 100
    assert 10 <= end - start <= 60


def test_clamp_clip_forces_minimum_duration():
    start, end = clamp_clip(10, 10.5, duration=100, min_length=20, max_length=60)
    assert end - start == 20


def test_clamp_clip_truncates_to_maximum():
    start, end = clamp_clip(0, 500, duration=1000, min_length=20, max_length=90)
    assert end - start == 90


def test_dedupe_clips_keeps_best_score():
    clips = [_proposal(0, 40, 0.4), _proposal(2, 42, 0.9), _proposal(100, 140, 0.7)]
    kept = dedupe_clips(clips)
    assert len(kept) == 2
    assert kept[0].score == 0.9


def test_validate_proposals_limits_and_clamps():
    proposals = [_proposal(0, 1000, 0.9), _proposal(0, 1000, 0.5), _proposal(200, 240, 0.8)]
    clips = validate_proposals(proposals, duration=600, min_length=20, max_length=60, limit=2)
    assert len(clips) == 2
    assert clips[0].duration <= 60
    assert clips[0].end <= 600
    assert [c.index for c in clips] == [1, 2]


def test_validate_proposals_empty():
    assert validate_proposals([]) == []


def test_validate_proposals_snaps_to_sentence_boundaries():
    segments = [
        Segment(index=1, start=0.0, end=5.0, text="Phrase une."),
        Segment(index=2, start=5.0, end=10.0, text="Phrase deux."),
        Segment(index=3, start=10.0, end=20.0, text="Phrase trois."),
    ]
    clips = validate_proposals(
        [_proposal(6.0, 18.0)],
        duration=30,
        min_length=5,
        max_length=30,
        segments=segments,
        snap=True,
    )
    assert clips[0].start == 5.0
    assert clips[0].end == 20.0


def test_snap_to_sentence_boundaries_respects_max_shift():
    segments = [Segment(index=1, start=0.0, end=5.0, text="a.")]
    start, end = snap_to_sentence_boundaries(50.0, 60.0, segments, max_shift=3.0)
    assert (start, end) == (50.0, 60.0)


def test_score_segment_rewards_hooks():
    dense = Segment(index=1, start=0, end=5, text=" ".join(["mot"] * 30))
    weak = Segment(index=2, start=0, end=5, text="Bonjour")
    assert score_segment(dense) > score_segment(weak)
    hooked = Segment(index=3, start=0, end=5, text="La clé c'est de retenir ceci")
    assert score_segment(hooked) > 0.5


def test_heuristic_proposals_respects_bounds():
    segments = [
        Segment(index=i, start=float(i * 4), end=float(i * 4 + 4), text=f"Phrase numéro {i} avec des mots.")
        for i in range(1, 41)
    ]
    proposals = heuristic_proposals(segments, min_length=20, max_length=40, limit=3)
    assert proposals
    assert len(proposals) <= 3
    for proposal in proposals:
        assert 20 <= proposal.duration <= 40
        assert proposal.title


def test_heuristic_proposals_empty_transcript():
    assert heuristic_proposals([]) == []
