"""Lecture et écriture de la configuration persistée (.env du projet)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# Clés que l'interface peut modifier.
EDITABLE: dict[str, str] = {
    "OPENAI_API_KEY": "Clé API du fournisseur (NVIDIA, OpenAI, Ollama…)",
    "CLIPAGENT_BASE_URL": "Endpoint du fournisseur (compatible OpenAI)",
    "CLIPAGENT_MODEL": "Modèle utilisé pour la sélection",
    "CLIPAGENT_PROVIDER": "Fournisseur (openai, nvidia, ollama, together, groq)",
    "CLIPAGENT_WHISPER_MODEL": "Modèle Whisper (tiny, base, small, medium, large-v3)",
    "CLIPAGENT_STYLE": "Style par défaut (streamer, tiktok, hype…)",
    "CLIPAGENT_NUM_CLIPS": "Nombre d'extraits par défaut",
    "CLIPAGENT_MIN_CLIP": "Durée minimale (s)",
    "CLIPAGENT_MAX_CLIP": "Durée maximale (s)",
    "CLIPAGENT_ENCODER": "Codec (libx264, libx265, libvpx-vp9)",
    "CLIPAGENT_CRF": "Qualité (CRF : plus bas = meilleur)",
    "CLIPAGENT_FPS": "Images par seconde",
    "CLIPAGENT_LANGUAGE": "Langue par défaut (fr, en, ar…)",
    "FFMPEG_BINARY": "Chemin de l'exécutable ffmpeg",
}

_SECRET = {"OPENAI_API_KEY"}


def read_env(path: Path | None = None) -> dict[str, str]:
    """Lit le fichier .env (sans l'interpréter)."""
    target = path or ENV_FILE
    values: dict[str, str] = {}
    if not target.exists():
        return values
    for line in target.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def write_env(values: dict[str, str], path: Path | None = None) -> Path:
    """Réécrit le .env en conservant les commentaires et l'ordre."""
    target = path or ENV_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if target.exists():
        lines = target.read_text(encoding="utf-8-sig").splitlines()

    updated: dict[str, str] = {}
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, _value = stripped.partition("=")
            key = key.strip()
            if key in values:
                updated[key] = str(values[key])
                output.append(f"{key}={values[key]}")
                continue
        output.append(line)

    for key, value in values.items():
        if key not in updated:
            output.append(f"{key}={value}")

    target.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return target


def current_config() -> dict[str, Any]:
    """Configuration effective (le .env l'emporte sur les valeurs par défaut)."""
    from .config import Settings

    settings = Settings.from_env()
    return {
        "model": settings.model,
        "provider": settings.provider or "",
        "base_url": settings.provider_base_url or settings.base_url or "",
        "whisper_model": settings.whisper_model,
        "style": settings.style,
        "num_clips": settings.num_clips,
        "min_clip": settings.min_clip_seconds,
        "max_clip": settings.max_clip_seconds,
        "encoder": settings.encoder,
        "crf": settings.crf,
        "fps": settings.fps,
        "language": settings.language,
        "has_key": bool(settings.api_key),
        "key_preview": (settings.api_key or "")[:6] + "…" if settings.api_key else "",
        "editable": EDITABLE,
        "env_file": str(ENV_FILE),
    }


def update_config(values: dict[str, str]) -> dict[str, Any]:
    """Applique des modifications au .env et recharge les variables d'environnement."""
    clean: dict[str, str] = {}
    for key, value in values.items():
        if key not in EDITABLE:
            continue
        clean[key] = str(value).strip()

    write_env(clean)
    for key, value in clean.items():
        if key == "OPENAI_API_KEY":
            os.environ["OPENAI_API_KEY"] = value
        else:
            os.environ[key] = value
    return current_config()
