"""Accroche « hook » : la phrase qui fait rester l'utilisateur dans les 2-3
premières secondes d'un clip (format TikTok / Reels / Shorts).

Deux sources possibles :
1. le hook rédigé par l'agent LLM (via l'outil `propose_clip`) ;
2. à défaut, la première phrase de l'extrait, nettoyée et raccourcie.
"""

from __future__ import annotations

import re

from .models import Clip, Segment

_SENTENCE_RE = re.compile(r"(?<=[.!?…؟।])\s+")
_WORD_RE = re.compile(r"[\w؀-ۿऀ-ॿ]+", re.UNICODE)

# Mots inutiles en ouverture d'un short.
_FILLERS = re.compile(
    r"^(?:bonjour|salut|bonsoir|eh bien|du coup|alors|voil[àa]|bienvenue|hey|hello)\b[\s,]*",
    re.IGNORECASE,
)
_FILLERS_2 = re.compile(
    r"^(?:[àa] tous|[àa] toutes|[àa] vous|tout le monde|everyone|a todos|مرحبا بكم)\b[\s,]*",
    re.IGNORECASE,
)


def is_rtl_language(language: str | None) -> bool:
    """Vrai pour les langues écrites de droite à gauche."""
    code = (language or "").lower().split("-")[0]
    return code in {"ar", "fa", "he", "ur", "ps", "sd", "yi"}


def clean_hook(text: str, *, max_chars: int = 52, uppercase: bool = True) -> str:
    """Nettoie une accroche : une phrase, sans mots de remplissage, bornée."""
    if not text:
        return ""
    cleaned = " ".join(str(text).split())
    cleaned = _FILLERS.sub("", cleaned).strip()
    cleaned = _FILLERS_2.sub("", cleaned).strip()
    sentences = [s.strip() for s in _SENTENCE_RE.split(cleaned) if s.strip()]
    if sentences:
        cleaned = sentences[0]
    cleaned = cleaned.strip(" .,-–—")
    if len(cleaned) > max_chars:
        cut = cleaned[: max_chars - 1]
        space = cut.rfind(" ")
        if space > max_chars * 0.6:
            cut = cut[:space]
        cleaned = cut.rstrip() + "…"
    if uppercase and not _is_rtl(cleaned):
        cleaned = cleaned.upper()
    return cleaned


def _is_rtl(text: str) -> bool:
    """Détecte la présence de caractères arabes (pas de mise en capitales)."""
    return bool(re.search(r"[؀-ۿ]", text))


def hook_from_transcript(
    segments: list[Segment],
    start: float,
    end: float,
    *,
    max_chars: int = 52,
    uppercase: bool = True,
) -> str:
    """Construit une accroche à partir du début de l'extrait (sans LLM)."""
    texts = [s.text for s in segments if s.end > start and s.start < end]
    if not texts:
        return ""
    opening = " ".join(texts).strip()
    sentences = [s.strip() for s in _SENTENCE_RE.split(opening) if s.strip()]
    first = sentences[0] if sentences else opening
    words = _WORD_RE.findall(first)
    # On garde la phrase d'ouverture, sans les mots de remplissage.
    return clean_hook(" ".join(words[:9]), max_chars=max_chars, uppercase=uppercase)


def hook_lines(text: str, *, max_lines: int = 2, max_chars_per_line: int = 26) -> list[str]:
    """Découpe une accroche en 2 lignes maximum (lecture verticale).

    Aucun mot n'est perdu : au-delà de ``max_lines - 1``, les mots restants
    rejoignent la dernière ligne.
    """
    words = str(text).split()
    if not words:
        return []
    if len(" ".join(words)) <= max_chars_per_line:
        return [" ".join(words)]

    lines: list[str] = []
    current = ""
    for index, word in enumerate(words):
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars_per_line:
            if len(lines) == max_lines - 1:
                # dernière ligne : on accepte le reste des mots
                lines.append(" ".join(words[index - len(current.split()) :]))
                current = ""
                break
            lines.append(current)
            current = word
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def resolve_hook(clip: Clip, segments: list[Segment], *, max_chars: int = 52, uppercase: bool = True) -> str:
    """Hook de l'extrait : celui de l'agent s'il existe, sinon déduit du transcript."""
    if clip.hook:
        return clean_hook(clip.hook, max_chars=max_chars, uppercase=uppercase)
    return hook_from_transcript(
        segments,
        clip.start,
        clip.end,
        max_chars=max_chars,
        uppercase=uppercase,
    )
