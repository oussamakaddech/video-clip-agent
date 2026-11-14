"""Téléchargement d'une VOD (Kick, YouTube, Twitch…) via yt-dlp."""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import Settings


class DownloadError(RuntimeError):
    """Erreur de téléchargement (URL invalide, contenu protégé, réseau…)."""


def ensure_yt_dlp() -> str:
    """Vérifie que yt-dlp est disponible et renvoie le chemin de l'exécutable."""
    found = shutil.which("yt-dlp")
    if found:
        return found
    try:
        import yt_dlp  # noqa: F401

        return "yt-dlp"
    except ImportError as exc:
        raise DownloadError(
            "yt-dlp est requis pour télécharger une VOD : pip install yt-dlp"
        ) from exc


def build_command(
    url: str,
    *,
    out_dir: Path,
    cookies_from_browser: str | None = None,
    format_selector: str = "bv*+ba/b",
    max_height: int = 1080,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Commande yt-dlp (testable sans réseau)."""
    command = [
        ensure_yt_dlp(),
        "--no-playlist",
        "--no-progress",
        "--continue",
        "--merge-output-format", "mp4",
        "-f", format_selector,
        "--max-height", str(max_height),
        "-o", str(Path(out_dir) / "%(id)s_%(title).120B.%(ext)s"),
    ]
    if cookies_from_browser:
        command += ["--cookies-from-browser", cookies_from_browser]
    command += extra_args or []
    command.append(url)
    return command


def download(
    url: str,
    *,
    settings: Settings,
    out_dir: Path | str | None = None,
    cookies_from_browser: str | None = None,
    max_height: int = 1080,
) -> Path:
    """Télécharge une VOD et renvoie le chemin du fichier obtenu."""
    import subprocess

    target = Path(out_dir or settings.download_dir)
    target.mkdir(parents=True, exist_ok=True)

    command = build_command(
        url,
        out_dir=target,
        cookies_from_browser=cookies_from_browser,
        max_height=max_height,
    )
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-8:]
        raise DownloadError("Téléchargement impossible :\n" + "\n".join(tail))

    candidates = [
        path
        for path in sorted(target.iterdir())
        if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".ts"}
    ]
    if not candidates:
        raise DownloadError("Téléchargement terminé mais aucun fichier vidéo trouvé.")
    return candidates[-1]
