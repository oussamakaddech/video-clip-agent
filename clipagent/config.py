"""Configuration du pipeline (variables d'environnement + surcharge CLI)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "gpt-4o-mini"


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Réglages globaux de l'agent de clipping."""

    model: str = DEFAULT_MODEL
    api_key: str | None = None
    base_url: str | None = None
    chat_completions: bool = False
    strict_tools: bool = True
    min_clip_seconds: float = 20.0
    max_clip_seconds: float = 90.0
    num_clips: int = 5
    aspect_ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    ffmpeg_binary: str | None = None
    burn_subtitles: bool = True
    output_dir: Path = Path("output")
    language: str = "fr"
    instruction: str = ""
    verbose: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        settings = cls(
            model=os.getenv("CLIPAGENT_MODEL", DEFAULT_MODEL),
            api_key=os.getenv("OPENAI_API_KEY") or os.getenv("CLIPAGENT_API_KEY"),
            base_url=os.getenv("CLIPAGENT_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
            chat_completions=_env_bool("CLIPAGENT_CHAT_COMPLETIONS", False),
            strict_tools=_env_bool("CLIPAGENT_STRICT_TOOLS", True),
            min_clip_seconds=_env_float("CLIPAGENT_MIN_CLIP", 20.0),
            max_clip_seconds=_env_float("CLIPAGENT_MAX_CLIP", 90.0),
            num_clips=_env_int("CLIPAGENT_NUM_CLIPS", 5),
            aspect_ratio=os.getenv("CLIPAGENT_ASPECT", "9:16"),
            width=_env_int("CLIPAGENT_WIDTH", 1080),
            height=_env_int("CLIPAGENT_HEIGHT", 1920),
            ffmpeg_binary=os.getenv("FFMPEG_BINARY"),
            burn_subtitles=_env_bool("CLIPAGENT_BURN_SUBTITLES", True),
            output_dir=Path(os.getenv("CLIPAGENT_OUTPUT_DIR", "output")),
            language=os.getenv("CLIPAGENT_LANGUAGE", "fr"),
            instruction=os.getenv("CLIPAGENT_INSTRUCTION", ""),
            verbose=_env_bool("CLIPAGENT_VERBOSE", False),
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(settings, key, value)
        return settings
