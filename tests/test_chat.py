from __future__ import annotations

from clipagent.chat import (
    ChatMessage,
    build_chat_context,
    chat_heat,
    chat_timeline,
    parse_video_timestamp,
    summarize_window,
)
from clipagent.browser import FrameSample
from clipagent.browser_pipeline import score_candidates


# --- Horodatages ------------------------------------------------------------
def test_parse_video_timestamp():
    assert parse_video_timestamp("03:19:38") == 3 * 3600 + 19 * 60 + 38
    assert parse_video_timestamp("19:38") == 19 * 60 + 38
    assert parse_video_timestamp("1:02:03") == 3600 + 123
    assert parse_video_timestamp("18:21") == 18 * 60 + 21


def test_parse_video_timestamp_invalid():
    assert parse_video_timestamp("hello") is None
    assert parse_video_timestamp("99:99") is None
    assert parse_video_timestamp("") is None


# --- Densité ----------------------------------------------------------------
def _messages(timestamps: list[float]) -> list[ChatMessage]:
    return [ChatMessage(timestamp=t, text=f"message {i}") for i, t in enumerate(timestamps)]


def test_chat_heat_counts_per_minute():
    messages = _messages([0, 10, 20, 30, 40, 50])
    # 6 messages sur 60 s => 6 par minute
    assert chat_heat(messages, 0, 60) == 6.0
    # aucune message dans la fenêtre
    assert chat_heat(messages, 600, 660) == 0.0


def test_chat_heat_window_selection():
    messages = _messages([10, 20, 700])
    assert chat_heat(messages, 0, 60) == 2.0
    assert chat_heat(messages, 690, 750) == 1.0


def test_chat_timeline_buckets():
    messages = _messages([10, 20, 30])
    timeline = chat_timeline(messages, duration=120, buckets=4)
    assert len(timeline) == 4
    assert sum(timeline) == 3


def test_chat_timeline_invalid():
    assert chat_timeline([], duration=0) == []
    assert chat_timeline([], duration=100, buckets=0) == []


# --- Contexte pour le prompt ------------------------------------------------
def test_summarize_window_keeps_longest_messages():
    messages = [
        ChatMessage(timestamp=10, text="short"),
        ChatMessage(timestamp=20, text="a much longer and more explicit message about the topic"),
        ChatMessage(timestamp=25, text="mid length message"),
    ]
    entries = summarize_window(messages, 0, 60, limit=2)
    assert len(entries) == 2
    assert "much longer" in entries[0]


def test_build_chat_context_lists_windows():
    messages = _messages([10, 20])
    context = build_chat_context(messages, [(0, 60), (600, 660)])
    assert "ACTIVITÉ DU CHAT" in context
    assert "00:00" in context
    # la fenêtre sans message n'apparaît pas
    assert context.count("→") == 1


def test_build_chat_context_empty():
    assert build_chat_context([], [(0, 60)]) == ""
    assert build_chat_context(_messages([10]), []) == ""


# --- Classement composite ---------------------------------------------------
def _samples() -> list[FrameSample]:
    return [
        FrameSample(timestamp=0.0, motion=0.1),
        FrameSample(timestamp=600.0, motion=0.9),
        FrameSample(timestamp=1200.0, motion=0.2),
    ]


def test_score_candidates_uses_motion():
    candidates = score_candidates(_samples(), count=2, window=80, min_gap=100)
    assert len(candidates) == 2
    # la fenêtre la plus mouvementée est retenue
    assert any(abs(c.start + 40 - 600) < 1 for c in candidates)


def test_score_candidates_boosts_chat_activity():
    messages = _messages([600, 610, 620, 630, 640, 650])
    with_chat = score_candidates(_samples(), messages, count=1, window=80, min_gap=100)
    without_chat = score_candidates(_samples(), [], count=1, window=80, min_gap=100)
    assert with_chat[0].chat > without_chat[0].chat
    assert with_chat[0].score >= without_chat[0].score


def test_score_candidates_respects_min_gap():
    samples = [FrameSample(timestamp=float(i * 10), motion=0.9) for i in range(20)]
    candidates = score_candidates(samples, count=5, window=80, min_gap=120)
    for i in range(len(candidates) - 1):
        assert candidates[i + 1].start - candidates[i].start >= 120


def test_score_candidates_empty():
    assert score_candidates([], count=3) == []
