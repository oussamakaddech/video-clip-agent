from __future__ import annotations

from clipagent.transcript import (
    Transcript,
    format_timestamp,
    load_transcript,
    parse_plain_text,
    parse_srt,
    parse_timestamp,
    parse_vtt,
)

SRT = """1
00:00:00,000 --> 00:00:04,500
Bonjour à tous, aujourd'hui on parle de <b>clipping</b> vidéo.

2
00:00:04,500 --> 00:00:09,250
La clé c'est de toujours commencer par l'accroche.

3
00:00:09,250 --> 00:00:15,000
Voici le résultat : nous avons doublé l'engagement.
"""


def test_parse_timestamp_variants():
    assert parse_timestamp("00:00:04,500") == 4.5
    assert parse_timestamp("00:01:30.000") == 90.0
    assert parse_timestamp("01:02,500") == 62.5
    assert parse_timestamp("12.25") == 12.25


def test_format_timestamp_roundtrip():
    assert format_timestamp(3661.5) == "01:01:01,500"
    assert format_timestamp(4.5, comma=False) == "00:00:04.500"
    assert format_timestamp(0) == "00:00:00,000"


def test_parse_srt_extracts_segments():
    segments = parse_srt(SRT)
    assert len(segments) == 3
    assert segments[0].start == 0.0
    assert segments[0].end == 4.5
    assert segments[0].text == "Bonjour à tous, aujourd'hui on parle de clipping vidéo."
    assert segments[2].end == 15.0


def test_parse_vtt_without_index():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000
Bonjour
"""
    segments = parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].start == 1.0
    assert segments[0].text == "Bonjour"


def test_parse_plain_text_splits_sentences():
    segments = parse_plain_text("Bonjour. Ca va ? Oui !")
    assert len(segments) == 3
    assert segments[0].text == "Bonjour."


def test_transcript_window_and_text():
    transcript = Transcript(segments=parse_srt(SRT))
    assert transcript.duration == 15.0
    # la fenêtre retient tout segment qui chevauche l'intervalle
    assert len(transcript.window(0, 5)) == 2
    assert len(transcript.window(0, 4.5)) == 1
    assert len(transcript.window(5, 9)) == 1
    assert len(transcript.window(100, 200)) == 0
    assert "clé" in transcript.window_text(4.0, 9.5)
    assert "[00:00:04,500 --> 00:00:09,250]" in transcript.window_text(4.0, 9.5)
    # un segment qui chevauche la fenêtre est inclus
    assert "Bonjour" in transcript.window_text(4.0, 9.5)


def test_transcript_to_srt_is_reparsable():
    transcript = Transcript(segments=parse_srt(SRT))
    again = parse_srt(transcript.to_srt())
    assert [s.text for s in again] == [s.text for s in transcript.segments]
    assert again[1].start == transcript.segments[1].start


def test_transcript_to_vtt_has_header():
    transcript = Transcript(segments=parse_srt(SRT))
    assert transcript.to_vtt().startswith("WEBVTT")


def test_load_transcript_dispatches_on_extension(tmp_path):
    srt_path = tmp_path / "demo.srt"
    srt_path.write_text(SRT, encoding="utf-8")
    transcript = load_transcript(srt_path)
    assert len(transcript) == 3
    assert transcript.source == str(srt_path)

    txt_path = tmp_path / "demo.txt"
    txt_path.write_text("Une phrase. Une autre phrase.", encoding="utf-8")
    assert len(load_transcript(txt_path)) == 2
