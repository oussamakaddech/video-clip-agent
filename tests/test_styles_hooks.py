from __future__ import annotations

from clipagent.hooks import (
    clean_hook,
    hook_from_transcript,
    hook_lines,
    is_rtl_language,
    resolve_hook,
)
from clipagent.models import Clip, Segment
from clipagent.styles import STYLES, get_style, style_for_language, style_names


# --- Styles ---------------------------------------------------------------
def test_styles_are_registered():
    names = style_names()
    for expected in ("default", "tiktok", "hype", "podcast", "clean", "reels", "arabic"):
        assert expected in names


def test_get_style_falls_back_to_default():
    assert get_style("inconnu").name == "default"
    assert get_style(None).name == "default"
    assert get_style("TIKTOK").name == "tiktok"


def test_tiktok_style_has_hook_and_zoom():
    style = STYLES["tiktok"]
    assert style.hook_enabled is True
    assert style.zoom > 1.0
    assert style.hook_style.alignment == 8      # haut de l'image
    assert style.subtitle.bold is True


def test_podcast_style_has_no_hook():
    assert STYLES["podcast"].hook_enabled is False


def test_style_for_language_picks_arabic():
    assert style_for_language("ar").name == "arabic"
    assert style_for_language("ar-EG").name == "arabic"
    assert style_for_language("fr").name == "default"
    assert style_for_language("fr", "hype").name == "hype"


def test_arabic_style_is_rtl():
    assert STYLES["arabic"].is_rtl() is True
    assert STYLES["default"].is_rtl() is False


def test_ass_color_conversion():
    style = STYLES["default"].subtitle
    line = style.to_ass_style("Sub")
    assert line.startswith("Style: Sub,")
    assert "&H00FFFFFF" in line   # blanc
    assert "&H00000000" in line   # contour noir


# --- Hook -----------------------------------------------------------------
def test_clean_hook_removes_fillers_and_caps_length():
    assert clean_hook("Bonjour à tous, on va parler de ça") == "ON VA PARLER DE ÇA"
    long = "un " * 40
    assert len(clean_hook(long, max_chars=30)) <= 30


def test_clean_hook_keeps_arabic_as_is():
    text = "هل يمكن للذكاء الاصطناعي أن يقص الفيديو؟"
    assert clean_hook(text) == text


def test_clean_hook_empty():
    assert clean_hook("") == ""


def test_hook_lines_splits_short_text():
    assert hook_lines("Un hook court") == ["Un hook court"]


def test_hook_lines_splits_long_text():
    text = "Et si l'intelligence artificielle faisait tout le montage de la video"
    lines = hook_lines(text, max_chars_per_line=20)
    assert 1 < len(lines) <= 2
    # aucun mot ne doit être perdu
    assert " ".join(lines).split() == text.split()


def test_hook_lines_keeps_last_line_complete():
    lines = hook_lines("LA REPONSE TIENT EN UNE PHRASE", max_chars_per_line=21)
    assert lines == ["LA REPONSE TIENT EN", "UNE PHRASE"]


def test_hook_from_transcript_uses_clip_opening():
    segments = [
        Segment(index=1, start=0.0, end=5.0, text="Bonjour, voici le point clé du jour."),
        Segment(index=2, start=5.0, end=12.0, text="Nous avons doublé l'engagement."),
    ]
    hook = hook_from_transcript(segments, 0.0, 12.0, max_chars=40)
    assert "POINT CLÉ" in hook
    assert not hook.startswith("BONJOUR")


def test_resolve_hook_prefers_agent_hook():
    segments = [Segment(index=1, start=0.0, end=5.0, text="Phrase de début.")]
    clip = Clip(index=1, start=0.0, end=5.0, title="T", hook="Et si l'IA faisait tout ?")
    assert resolve_hook(clip, segments) == "ET SI L'IA FAISAIT TOUT ?"


def test_resolve_hook_falls_back_to_transcript():
    segments = [Segment(index=1, start=0.0, end=5.0, text="Phrase de début ici.")]
    clip = Clip(index=1, start=0.0, end=5.0, title="T")
    assert "PHRASE DE DÉBUT" in resolve_hook(clip, segments)


def test_is_rtl_language():
    assert is_rtl_language("ar") is True
    assert is_rtl_language("AR-EG") is True
    assert is_rtl_language("fr") is False
    assert is_rtl_language(None) is False
