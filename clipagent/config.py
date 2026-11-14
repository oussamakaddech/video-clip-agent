"""Configuration du pipeline (profils + variables d'environnement + surcharge CLI)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "gpt-4o-mini"

# Préréglages par type de contenu.
PROFILES: dict[str, dict] = {
    "default": {"num_clips": 5, "min_clip_seconds": 20.0, "max_clip_seconds": 90.0},
    "short": {"num_clips": 3, "min_clip_seconds": 15.0, "max_clip_seconds": 45.0},
    "podcast": {"num_clips": 6, "min_clip_seconds": 30.0, "max_clip_seconds": 120.0},
    # Livestream / VOD longue : beaucoup de moments forts, formats sociaux.
    "livestream": {"num_clips": 12, "min_clip_seconds": 25.0, "max_clip_seconds": 90.0},
}

_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    """Charge le fichier .env du projet (une seule fois), sans écraser l'environnement."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dépendance optionnelle
        return
    load_dotenv(Path.cwd() / ".env", override=False)
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Réglages globaux de l'agent de clipping."""

    model: str = DEFAULT_MODEL
    api_key: str | None = None
    base_url: str | None = None
    chat_completions: bool = False
    strict_tools: bool = True
    tracing: bool = False
    min_clip_seconds: float = 20.0
    max_clip_seconds: float = 90.0
    num_clips: int = 5
    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    ffmpeg_binary: str | None = None
    burn_subtitles: bool = True
    subtitle_size: int = 14
    output_dir: Path = Path("output")
    language: str = "fr"
    instruction: str = ""
    verbose: bool = False
    profile: str = "default"
    style: str = "default"
    logo: str | None = None
    logo_size: int = 120
    hook_enabled: bool = True
    hook_duration: float = 3.0
    max_chunks: int = 12
    chunk_chars: int = 12_000
    download_dir: Path = Path("downloads")
    extra: dict = field(default_factory=dict)

    # --- Construction -----------------------------------------------------
    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        """Ordre de priorité : profil < variables d'environnement < arguments CLI."""
        _load_dotenv_once()
        settings = cls(profile=os.getenv("CLIPAGENT_PROFILE", "default"))
        settings.apply_profile()

        env_map = {
            "model": os.getenv("CLIPAGENT_MODEL"),
            "api_key": os.getenv("OPENAI_API_KEY") or os.getenv("CLIPAGENT_API_KEY"),
            "base_url": os.getenv("CLIPAGENT_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
            "chat_completions": _env_bool("CLIPAGENT_CHAT_COMPLETIONS"),
            "strict_tools": _env_bool("CLIPAGENT_STRICT_TOOLS"),
            "tracing": _env_bool("CLIPAGENT_TRACING"),
            "min_clip_seconds": _env_float("CLIPAGENT_MIN_CLIP"),
            "max_clip_seconds": _env_float("CLIPAGENT_MAX_CLIP"),
            "num_clips": _env_int("CLIPAGENT_NUM_CLIPS"),
            "aspect_ratio": os.getenv("CLIPAGENT_ASPECT"),
            "width": _env_int("CLIPAGENT_WIDTH"),
            "height": _env_int("CLIPAGENT_HEIGHT"),
            "ffmpeg_binary": os.getenv("FFMPEG_BINARY"),
            "burn_subtitles": _env_bool("CLIPAGENT_BURN_SUBTITLES"),
            "subtitle_size": _env_int("CLIPAGENT_SUBTITLE_SIZE"),
            "language": os.getenv("CLIPAGENT_LANGUAGE"),
            "instruction": os.getenv("CLIPAGENT_INSTRUCTION"),
            "verbose": _env_bool("CLIPAGENT_VERBOSE"),
            "max_chunks": _env_int("CLIPAGENT_MAX_CHUNKS"),
            "chunk_chars": _env_int("CLIPAGENT_CHUNK_CHARS"),
            "style": os.getenv("CLIPAGENT_STYLE"),
            "logo": os.getenv("CLIPAGENT_LOGO"),
            "logo_size": _env_int("CLIPAGENT_LOGO_SIZE"),
            "hook_enabled": _env_bool("CLIPAGENT_HOOK"),
            "hook_duration": _env_float("CLIPAGENT_HOOK_DURATION"),
        }
        for key, value in env_map.items():
            if value is not None:
                setattr(settings, key, value)

        for key, value in overrides.items():
            if value is not None:
                setattr(settings, key, value)
        return settings

    def apply_profile(self) -> None:
        """Applique le préréglage du profil courant."""
        preset = PROFILES.get(self.profile)
        if preset:
            for key, value in preset.items():
                setattr(self, key, value)

    @property
    def profile_names(self) -> list[str]:
        return list(PROFILES)
