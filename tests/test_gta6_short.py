"""Tests du montage court « à la Viceprint » (`scripts/gta6_short.py`).

Logique pure uniquement : plan des prises, ASS, commande ffmpeg. Aucune synthèse
vocale, aucun binaire externe, aucun réseau.
"""

from __future__ import annotations

import pytest

from scripts import gta6_short as short

SRC = "source.mp4"


def beat(start: float, end: float, text: str = "A line.", label: str = "") -> short.Beat:
    return short.Beat(SRC, start, end, text, label)


def test_shot_length_follows_voice_plus_breath():
    shots = short.plan_shots([beat(10, 20)], [2.0])
    assert shots[0].length == pytest.approx(2.0 + short.GAP)


def test_shot_never_shorter_than_minimum():
    shots = short.plan_shots([beat(10, 20)], [0.2])
    assert shots[0].length == pytest.approx(short.MIN_BEAT)


def test_short_window_is_extended_in_the_same_source():
    """Fenêtre plus courte que la phrase : on allonge le plan, pas de gel d'image."""
    shots = short.plan_shots([beat(10, 11)], [4.0])
    assert shots[0].length == pytest.approx(4.0 + short.GAP)
    assert shots[0].beat.end == pytest.approx(10 + 4.0 + short.GAP)
    assert shots[0].beat.start == 10


def test_long_window_is_cut_to_the_voice():
    """La voix décide du rythme : un plan de 20 s se coupe à la durée de la phrase."""
    shots = short.plan_shots([beat(10, 30)], [2.0])
    assert shots[0].length == pytest.approx(2.0 + short.GAP)


def test_shots_are_contiguous_and_start_at_zero():
    shots = short.plan_shots([beat(0, 5), beat(20, 25), beat(40, 45)], [1.0, 2.0, 1.5])
    assert shots[0].t0 == 0.0
    for previous, current in zip(shots, shots[1:]):
        assert current.t0 == pytest.approx(previous.t1)
    assert short.total_duration(shots) == pytest.approx(sum(s.length for s in shots))


def test_plan_rejects_mismatched_durations():
    with pytest.raises(ValueError):
        short.plan_shots([beat(0, 5)], [1.0, 2.0])


def test_caption_falls_back_to_speech_text():
    assert beat(0, 5, "Some words.", "").caption == "Some words."
    assert beat(0, 5, "Some words.", "A LABEL").caption == "A LABEL"


def test_ass_has_one_line_per_shot_and_no_gap():
    shots = short.plan_shots([beat(0, 5), beat(10, 15)], [1.5, 2.0])
    ass = short.build_ass(shots, total=short.total_duration(shots))
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue: 1,")]
    assert len(lines) == 2
    assert "0:00:00.00" in lines[0]
    assert "0:00:01.72" in lines[1]  # 1,5 s de phrase + 0,22 s de respiration
    assert lines[1].startswith("Dialogue: 1,0:00:01.72,0:00:03.94")
    assert "A line." in lines[0]


def test_first_line_is_bigger_than_the_rest():
    shots = short.plan_shots([beat(0, 5), beat(10, 15)], [1.0, 1.0])
    ass = short.build_ass(shots, total=short.total_duration(shots))
    assert "\\fs96" in ass and "\\fs88" in ass


def test_ass_carries_credit_and_cta():
    shots = short.plan_shots([beat(0, 5), beat(10, 15)], [1.0, 1.0])
    total = short.total_duration(shots)
    ass = short.build_ass(shots, credit="@IShowSpeed", cta="Follow for more", total=total)
    assert "@IShowSpeed" in ass
    assert "Follow for more" in ass
    assert "Style: Cta" in ass


def test_ass_wraps_long_labels():
    shots = short.plan_shots([beat(0, 5, "x", "COPS ON EVERY FLOOR TONIGHT")], [2.0])
    ass = short.build_ass(shots, total=short.total_duration(shots))
    assert "\\N" in ass


def test_ass_escapes_ass_syntax():
    shots = short.plan_shots([beat(0, 5, "x", "hook {with} \\ tags")], [1.0])
    ass = short.build_ass(shots, total=short.total_duration(shots))
    assert "{with}" not in ass
    assert "\\ tags" not in ass


def test_command_concatenates_every_shot_and_mixes_the_voice():
    shots = short.plan_shots([beat(0, 5), beat(10, 15)], [1.0, 1.0])
    command = short.build_command(
        shots, "clip.ass", "out.mp4", voice_track="voice.wav", total=short.total_duration(shots)
    )
    text = " ".join(command)
    assert text.count("-i source.mp4") == 2
    assert "concat=n=2:v=1:a=0" in text
    assert "concat=n=2:v=0:a=1" in text
    assert "[2:a]aformat" in text          # la voix arrive après les plans
    assert "amix=inputs=2" in text
    assert "loudnorm=I=-14" in text
    assert "subtitles=" in text


def test_command_without_voice_keeps_the_game_audio():
    shots = short.plan_shots([beat(0, 5)], [1.0])
    text = " ".join(short.build_command(shots, "clip.ass", "out.mp4", total=2.0))
    assert "amix" not in text
    assert "loudnorm=I=-14" in text


def test_command_requires_at_least_one_shot():
    with pytest.raises(ValueError):
        short.build_command([], "clip.ass", "out.mp4")


def test_command_escapes_the_subtitle_path_for_ffmpeg():
    shots = short.plan_shots([beat(0, 5)], [1.0])
    text = " ".join(
        short.build_command(shots, r"C:\tmp\short.ass", "out.mp4", total=2.0)
    )
    assert "C\\:/tmp/short.ass" in text


def test_voice_duration_reads_a_wav(tmp_path):
    import wave

    path = tmp_path / "vo.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\x00\x00" * 48000)
    assert short.voice_duration(path) == pytest.approx(1.0)
