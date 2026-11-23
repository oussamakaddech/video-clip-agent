"""Tests du pont GTA 6 (`scripts/gta6.py`).

On teste uniquement la logique pure ajoutée par le pont (accroches, légendes) :
le rendu et la transcription sont couverts par les scripts amont et par les
essais manuels décrits dans `docs/gtavi-claudecode-analyse.md`.
"""

from __future__ import annotations

from scripts import gta6

INFO = {
    "title": "GTA 6 - Stealing a Jet | Part 3",
    "channel": "TmarTn2",
    "webpage_url": "https://www.youtube.com/watch?v=6E2cBXFCDyQ",
}


def test_propose_hooks_from_sentences():
    text = ("So the ATC is there which means the airport is in that direction. "
            "Oh my god bro look at that insane crash!")
    hooks = gta6.propose_hooks(text)
    assert hooks, "au moins une accroche attendue"
    assert hooks[0] == "The ATC is there which means the airport"
    assert len(hooks) <= 3
    assert all(len(hook) <= 52 for hook in hooks)


def test_propose_hooks_prefers_energetic_sentence():
    text = "We are driving around. Oh my god bro, look at that insane crash right now!"
    hooks = gta6.propose_hooks(text)
    assert any("insane" in hook for hook in hooks)


def test_propose_hooks_empty_text():
    assert gta6.propose_hooks("   ") == []


def test_propose_hooks_dedupes_options():
    hooks = gta6.propose_hooks("Look at that car. Look at that car.")
    assert len(hooks) == len({hook.lower() for hook in hooks})


def test_caption_credits_creator_on_every_platform():
    for platform in ("x", "instagram", "tiktok"):
        caption = gta6.caption_for(INFO, "Hidden car in plain sight", platform=platform)
        assert "TmarTn2" in caption
        assert INFO["webpage_url"] in caption
    assert "#GTA6" not in gta6.caption_for(INFO, "hook", platform="x")
    assert "#GTA6" in gta6.caption_for(INFO, "hook", platform="tiktok")


def test_caption_without_channel_does_not_crash():
    caption = gta6.caption_for({"title": "Sans chaine"}, "hook")
    assert "Sans chaine" not in caption  # le titre n'est pas un crédit
    assert "l'auteur de la vidéo" in caption
