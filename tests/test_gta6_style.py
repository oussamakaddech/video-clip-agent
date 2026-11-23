"""Tests du style GTA 6 (`scripts/gta6_style.py`).

Logique pure uniquement : construction ASS, découpe des accroches, graphe de
filtres. Aucun binaire externe, aucun réseau.
"""

from __future__ import annotations

import pytest

from scripts import gta6_style as style

WORDS = [
    {"w": "He", "s": 1.0, "e": 1.2},
    {"w": "walked", "s": 1.2, "e": 1.6},
    {"w": "into", "s": 1.6, "e": 1.9},
    {"w": "gator", "s": 1.9, "e": 2.3},
    {"w": "water.", "s": 2.3, "e": 2.7},
]


def test_ts_formats_ass_timestamps():
    assert style.ts(0) == "0:00:00.00"
    assert style.ts(81.36) == "0:01:21.36"
    assert style.ts(3725.5) == "1:02:05.50"


def test_wrap_balances_two_lines():
    assert style.wrap("He walked into gator water") == ["He walked into", "gator water"]


def test_wrap_keeps_short_hook_on_one_line():
    assert style.wrap("South Beach from a jet") == ["South Beach from a jet"]


def test_wrap_never_splits_a_word():
    text = "An unbelievably long hook about Leonida at night"
    lines = style.wrap(text)
    assert all(len(line) <= style.HOOK_MAX_CHARS for line in lines)
    for word in " ".join(lines).split():
        assert word in text.split()


def test_too_long_hook_is_truncated_with_ellipsis():
    ass = style.build_ass(WORDS, 0.0, 3.0, "An unbelievably long hook about Leonida at night")
    assert "…" in ass
    assert "\\N" in ass


def test_build_ass_contains_style_kicker_hook_and_colors():
    ass = style.build_ass(WORDS, 0.0, 3.0, "He walked into gator water", cta="Follow for more")
    assert "Style: Hook,Arial Black,78" in ass
    assert "Style: Kicker,Arial Black,40" in ass
    assert "Style: Cta,Arial Black,52" in ass
    assert "GTA 6" in ass
    assert "He walked into\\Ngator water" in ass
    # couleur ASS complète (esperluette finale obligatoire)
    assert style.PINK + "&}" in ass
    assert "\\fad(80,150)" in ass


def test_build_ass_marks_current_word_and_limits_hook():
    ass = style.build_ass(WORDS, 0.0, 3.0, "")
    assert "{\\c" + style.PINK + "&}HE" in ass
    assert "\\N" not in ass  # pas d'accroche
    assert "Style: Kicker" in ass and "GTA 6" in ass


def test_build_ass_cta_starts_before_the_end():
    ass = style.build_ass(WORDS, 0.0, 10.0, "", cta="Follow for more")
    assert "0:00:08.20" in ass  # 10 - 1,8 s


def test_build_ass_escapes_braces_and_backslashes():
    ass = style.build_ass(WORDS, 0.0, 3.0, "hook {with} \\ tags")
    assert "{with}" not in ass
    assert "\\ tags" not in ass


def test_video_filter_has_grading_and_subtitles():
    graph = style.video_filter("fill", __import__("pathlib").Path("C:/tmp/clip.ass"))
    assert "eq=saturation=1.10" in graph
    assert "vignette=PI/5" in graph
    assert "subtitles=" in graph
    assert graph.endswith("[vo]")


def test_video_filter_rejects_unsupported_layout():
    with pytest.raises(ValueError):
        style.video_filter("react", __import__("pathlib").Path("clip.ass"))


def test_captions_can_be_disabled_for_unreadable_transcripts():
    """Dialecte mal transcrit : mieux vaut aucune ligne que du bruit."""
    ass = style.build_ass(WORDS, 0.0, 3.0, "He walked into gator water", captions=False)
    assert "Dialogue: 0," not in ass
    assert "He walked into" in ass  # l'accroche reste


def test_facecam_stacks_camera_over_game():
    graph = style.video_filter(
        "facecam", __import__("pathlib").Path("clip.ass"), cam=(0.695, 0.666, 0.232, 0.232)
    )
    assert "crop=iw*0.2320:ih*0.2320:iw*0.6950:ih*0.6660" in graph
    assert f"scale={style.W}:{style.HAUTEUR_CAM}" in graph
    assert f"crop={style.W}:{style.HAUTEUR_JEU}" in graph
    assert "vstack" in graph
    assert graph.endswith("[vo]")


def test_facecam_requires_a_camera_box():
    """Sans position de caméra, le cadrage facecam n'a pas de sens."""
    with pytest.raises(ValueError):
        style.video_filter("facecam", __import__("pathlib").Path("clip.ass"))


def test_facecam_texts_sit_below_the_camera():
    kicker, hook, cap, cta = style.POS["facecam"]
    assert kicker > style.HAUTEUR_CAM
    assert hook > kicker
    assert cap > hook
    assert cta > cap
    ass = style.build_ass(WORDS, 0.0, 3.0, "He walked into gator water", layout="facecam")
    assert f"\\pos({style.W // 2},{hook})" in ass
    assert f"\\pos({style.W // 2},{cap})" in ass


def test_resolve_cam_accepts_explicit_fractions():
    assert style.resolve_cam("source.mp4", 10.0, 20.0, "0.1:0.2:0.3:0.4") == (
        pytest.approx(0.1),
        pytest.approx(0.2),
        pytest.approx(0.3),
        pytest.approx(0.4),
    )


def test_resolve_cam_defaults_to_the_streamer_box():
    assert style.resolve_cam("source.mp4", 10.0, 20.0, None) == style.CAM_BOX


def test_video_filter_trims_the_bottom_when_asked():
    """Les rediffusions portent souvent leurs propres sous-titres incrustés."""
    graph = style.video_filter("fill", __import__("pathlib").Path("clip.ass"), trim_bottom=0.08)
    assert "crop=iw:ih*0.9200:0:0" in graph


def test_video_filter_trim_is_bounded():
    graph = style.video_filter("fill", __import__("pathlib").Path("clip.ass"), trim_bottom=5.0)
    assert "crop=iw:ih*0.7500:0:0" in graph  # plancher à 25 %


def _cap_intervals(ass: str) -> list[tuple[float, float]]:
    """Extrait (début, fin) des événements de sous-titre, en secondes."""
    def seconds(stamp: str) -> float:
        hours, minutes, rest = stamp.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(rest)

    intervals = []
    for line in ass.splitlines():
        if not line.startswith("Dialogue: 0,"):
            continue
        parts = line.split(",", 3)
        intervals.append((seconds(parts[1]), seconds(parts[2])))
    return intervals


def test_caption_events_never_overlap():
    """Deux groupes au même point d'ancrage se chevauchent lettre à lettre."""
    ass = style.build_ass(WORDS, 0.0, 4.0, "")
    intervals = sorted(_cap_intervals(ass))
    for (_, previous_end), (start, _) in zip(intervals, intervals[1:]):
        assert start >= previous_end, intervals


def test_caption_groups_are_clamped_on_speech_overlap():
    """Parole qui se chevauche (deux locuteurs) : jamais deux boîtes à la fois."""
    words = [
        {"w": "That's", "s": 1.40, "e": 1.58},
        {"w": "going", "s": 1.58, "e": 1.66},
        {"w": "to", "s": 1.66, "e": 2.10},
        {"w": "be", "s": 1.70, "e": 1.78},
        {"w": "our", "s": 1.78, "e": 1.88},
        {"w": "best", "s": 1.88, "e": 2.44},
    ]
    intervals = sorted(_cap_intervals(style.build_ass(words, 0.0, 3.0, "")))
    for (_, previous_end), (start, _) in zip(intervals, intervals[1:]):
        assert start >= previous_end

