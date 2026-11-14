"""Téléchargement d'une VOD (Kick, YouTube, Twitch…) via yt-dlp."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .config import Settings


class DownloadError(RuntimeError):
    """Erreur de téléchargement (URL invalide, contenu protégé, réseau…)."""


def ensure_yt_dlp() -> list[str]:
    """Commande yt-dlp : exécutable du PATH, sinon le module Python du projet."""
    found = shutil.which("yt-dlp")
    if found:
        return [found]
    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise DownloadError(
            "yt-dlp est requis pour télécharger une VOD : pip install yt-dlp"
        ) from exc
    return [sys.executable, "-m", "yt_dlp"]


def build_command(
    url: str,
    *,
    out_dir: Path,
    cookies_from_browser: str | None = None,
    format_selector: str | None = None,
    max_height: int = 1080,
    audio_only: bool = False,
    sections: list[tuple[float, float]] | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Commande yt-dlp (testable sans réseau).

    ``audio_only`` : on ne récupère que la piste audio (≈ 100 Mo pour 4 h).
    ``sections``   : on ne récupère que les plages [début, fin] demandées
    (yt-dlp fait des requêtes HTTP partielles : la vidéo complète n'est pas
    téléchargée).
    """
    if format_selector is None:
        if audio_only:
            format_selector = "ba/b"
        else:
            format_selector = (
                f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b/bv*+ba"
            )
    command = [
        *ensure_yt_dlp(),
        "--no-playlist",
        "--no-progress",
        "--continue",
        "--merge-output-format", "mp4",
        "-f", format_selector,
    ]
    if sections:
        for start, end in sections:
            command += ["--download-sections", f"*{start:.3f}-{end:.3f}"]
        command += ["--force-keyframes-at-cuts"]
    command += ["-o", str(Path(out_dir) / "%(id)s_%(title).120B.%(ext)s")]
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
    audio_only: bool = False,
    sections: list[tuple[float, float]] | None = None,
) -> Path:
    """Télécharge une VOD (ou une partie) et renvoie le chemin du fichier obtenu."""
    import subprocess

    target = Path(out_dir or settings.download_dir)
    target.mkdir(parents=True, exist_ok=True)

    command = build_command(
        url,
        out_dir=target,
        cookies_from_browser=cookies_from_browser,
        max_height=max_height,
        audio_only=audio_only,
        sections=sections,
    )
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-8:]
        raise DownloadError("Téléchargement impossible :\n" + "\n".join(tail))

    extensions = {".mp4", ".mkv", ".webm", ".mov", ".ts"}
    if audio_only:
        extensions |= {".m4a", ".mp3", ".opus", ".aac", ".wav", ".ogg"}
    candidates = [
        path
        for path in sorted(target.iterdir())
        if path.suffix.lower() in extensions
    ]
    if not candidates:
        raise DownloadError("Téléchargement terminé mais aucun fichier trouvé.")
    return candidates[-1]


def download_section(
    url: str,
    start: float,
    end: float,
    *,
    settings: Settings,
    out_dir: Path | str | None = None,
    cookies_from_browser: str | None = None,
    max_height: int = 1080,
) -> Path:
    """Télécharge uniquement la plage [start, end] de la vidéo (weak-connection mode)."""
    target = Path(out_dir or settings.download_dir)
    return download(
        url,
        settings=settings,
        out_dir=target,
        cookies_from_browser=cookies_from_browser,
        max_height=max_height,
        sections=[(start, end)],
    )
