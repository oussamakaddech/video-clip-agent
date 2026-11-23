"""Tests du découpage narratif (`clipagent.narrative`).

Tout est logique pure : aucune dépendance à un modèle, un binaire ou le réseau.
L'algorithme est celui de ClipsAI (TextTiling) porté sur des vecteurs lexicaux.
"""

from __future__ import annotations

import pytest

from clipagent import narrative
from clipagent.config import Settings
from clipagent.models import Segment
from clipagent.pipeline import plan_clips
from clipagent.transcript import Transcript

SCENES = [
    [
        "The jet is still parked on the runway.",
        "Nobody is guarding the jet right now.",
        "We run to the jet and open the canopy.",
        "The jet engine starts on the first try.",
        "We roll the jet toward the runway.",
        "The jet climbs over the fence.",
    ],
    [
        "The swamp water is dark and warm.",
        "A gator watches us from the swamp.",
        "Jason steps into the swamp anyway.",
        "The gator slides into the swamp water.",
        "Jason says the swamp is fine, bro.",
        "We keep walking through the swamp.",
    ],
    [
        "Vice City is full of neon tonight.",
        "The neon reflects on the wet street.",
        "Traffic in Vice City never stops.",
        "We land the jet above Vice City.",
        "Vice City looks unreal from up here.",
        "The whole city is orange at sunset.",
    ],
]


def _dialogue(step: float = 4.2, pause: float = 1.2) -> list[Segment]:
    """Trois scènes de six phrases, avec une vraie pause entre les scènes."""
    segments: list[Segment] = []
    time = 0.0
    for scene in SCENES:
        for line in scene:
            segments.append(
                Segment(index=len(segments), start=round(time, 2), end=round(time + 4.0, 2), text=line)
            )
            time += step
        time += pause
    return segments


def test_split_sentences_groups_by_punctuation():
    segments = _dialogue()
    sentences = narrative.split_sentences(segments)
    assert len(sentences) == len(segments)  # une phrase prononcée = un segment ici
    assert sentences[0].text.startswith("The jet")


def test_split_sentences_merges_short_fragments():
    segments = [
        Segment(index=0, start=0.0, end=1.0, text="so the jet"),
        Segment(index=1, start=1.0, end=2.0, text="is parked out there."),
    ]
    sentences = narrative.split_sentences(segments)
    assert len(sentences) == 1
    assert sentences[0].end == 2.0


def test_split_sentences_starts_a_new_sentence_after_a_pause():
    segments = [
        Segment(index=0, start=0.0, end=2.0, text="the jet is parked out there."),
        Segment(index=1, start=6.0, end=8.0, text="the gator is watching us."),
    ]
    assert len(narrative.split_sentences(segments)) == 2


def test_tokenize_drops_stopwords_and_short_words():
    assert narrative.tokenize("The jet is in the sky") == ["jet", "sky"]


def test_vector_is_normalised():
    item = narrative.vector("jet jet runway")
    assert abs(sum(value * value for value in item.values()) - 1.0) < 1e-9
    assert narrative.vector("the and of") == {}


def test_cosine_ranges_from_zero_to_one():
    assert narrative.cosine(narrative.vector("jet runway"), narrative.vector("jet runway")) == pytest.approx(1.0)
    assert narrative.cosine(narrative.vector("jet runway"), narrative.vector("gator swamp")) == 0.0


def test_smooth_keeps_the_signal_length():
    values = [0.9, 0.8, 0.1, 0.8, 0.9]
    assert len(narrative.smooth(values, 3)) == len(values)
    assert narrative.smooth([0.5, 0.5, 0.5], 3) == [0.5, 0.5, 0.5]


def test_depth_scores_peak_at_the_dip():
    depths = narrative.depth_scores([0.9, 0.9, 0.1, 0.9, 0.9])
    assert depths.index(max(depths)) == 2


def test_text_tile_marks_the_topic_change():
    segments = _dialogue()
    sentences = narrative.split_sentences(segments)
    vectors = [narrative.vector(sentence.text) for sentence in sentences]
    times = [(sentence.start, sentence.end) for sentence in sentences]
    marks = narrative.text_tile(vectors, 5, times=times)
    assert marks[-1] == 1
    assert any(mark == 1 for mark in marks[:-1])  # au moins une frontière interne


def test_find_clips_stays_inside_the_duration_window():
    sentences = narrative.split_sentences(_dialogue())
    clips = narrative.find_clips(sentences, min_length=20, max_length=45)
    assert clips
    for clip in clips:
        duration = clip["end"] - clip["start"]
        assert 20 <= duration <= 45


def test_narrative_proposals_are_sorted_and_do_not_overlap():
    proposals = narrative.narrative_proposals(_dialogue(), min_length=20, max_length=45, limit=4)
    assert proposals
    assert [p.start for p in proposals] == sorted(p.start for p in proposals)
    for first, second in zip(proposals, proposals[1:]):
        assert second.start >= first.end - 1e-6


def test_narrative_proposals_tag_and_reason():
    proposals = narrative.narrative_proposals(_dialogue(), min_length=20, max_length=45, limit=2)
    assert all("narrative" in proposal.tags for proposal in proposals)
    assert all("TextTiling" in proposal.reason for proposal in proposals)


def test_narrative_proposals_hook_fits_a_hook_card():
    proposals = narrative.narrative_proposals(_dialogue(), min_length=20, max_length=45, limit=3)
    for proposal in proposals:
        assert 0 < len(proposal.hook) <= 42


def test_narrative_proposals_returns_empty_when_transcript_is_too_short():
    segments = [Segment(index=0, start=0.0, end=3.0, text="Just one line, no story.")]
    assert narrative.narrative_proposals(segments) == []


def test_plan_clips_falls_back_to_narrative_without_api_key():
    transcript = Transcript(segments=_dialogue(), source="dialogue.srt")
    settings = Settings(api_key=None, min_clip_seconds=20.0, max_clip_seconds=45.0, num_clips=3)
    plan = plan_clips(None, transcript, settings)
    assert plan.mode == "narrative"
    assert plan.clips
    assert all(20.0 <= clip.duration <= 45.0 for clip in plan.clips)
