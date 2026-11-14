"""Couche ffmpeg : sonde, découpe, recadrage vertical, sous-titres, concat.

Les fonctions ``build_*`` renvoient des listes d'arguments testables sans
exécuter ffmpeg ; ``render_*`` les exécutent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Settings


class FFmpegError(RuntimeError):
    """Erreur levée quand ffmpeg est introuvable ou échoue."""


def resolve_ffmpeg(explicit: str | None = None) -> str:
    """Retrouve l'exécutable ffmpeg (variable d'env, PATH, puis imageio-ffmpeg)."""
    candidates = [explicit, os.getenv("FFMPEG_BINARY")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # dépend optionnelle, fournit un binaire embarqué
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        raise FFmpegError(
            "ffmpeg introuvable. Installez-le (winget install Gyan.FFmpeg) "
            "ou `pip install imageio-ffmpeg`, ou définissez FFMPEG_BINARY."
        ) from exc


def resolve_ffprobe(explicit: str | None = None) -> str | None:
    """Retrouve ffprobe (optionnel : sinon on retombe sur ffmpeg -i)."""
    for candidate in (explicit, os.getenv("FFPROBE_BINARY")):
        if candidate and Path(candidate).exists():
            return str(candidate)
    found = shutil.which("ffprobe")
    if found:
        return found
    return None


def run(command: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess:
    """Exécute une commande et lève une erreur lisible en cas d'échec."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"Commande expirée : {' '.join(command[:3])}…") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-8:]
        raise FFmpegError("Échec ffmpeg :\n" + "\n".join(tail))
    return result


@dataclass
class MediaInfo:
    """Métadonnées minimales d'un média."""

    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False

    @property
    def aspect_ratio(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        return f"{self.width}x{self.height}"


def probe(video: str | Path, *, ffprobe_binary: str | None = None) -> MediaInfo:
    """Récupère durée / résolution / présence audio."""
    video = Path(video)
    ffprobe = resolve_ffprobe(ffprobe_binary)
    if ffprobe:
        command = [
            ffprobe,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video),
        ]
        data = json.loads(run(command).stdout or "{}")
        info = MediaInfo()
        info.duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and not info.width:
                info.width = int(stream.get("width", 0) or 0)
                info.height = int(stream.get("height", 0) or 0)
                rate = stream.get("avg_frame_rate", "0/1")
                try:
                    num, den = rate.split("/")
                    info.fps = float(num) / float(den) if float(den) else 0.0
                except (ValueError, ZeroDivisionError):
                    info.fps = 0.0
            elif stream.get("codec_type") == "audio":
                info.has_audio = True
        return info

    # Repli : ffmpeg -i et lecture de "Duration" sur stderr.
    ffmpeg = resolve_ffmpeg()
    result = subprocess.run([ffmpeg, "-i", str(video)], capture_output=True, text=True)
    text = result.stderr or ""
    info = MediaInfo()
    for line in text.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:")[1].split(",")[0].strip()
            parts = stamp.split(":")
            if len(parts) == 3:
                info.duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if "Stream #" in line and "Video:" in line and "x" in line:
            for token in line.split():
                if "x" in token and token.replace("x", "").isdigit():
                    w, h = token.split("x")
                    info.width, info.height = int(w), int(h)
                    break
        if "Stream #" in line and "Audio:" in line:
            info.has_audio = True
    return info


def escape_filter_path(path: str | Path) -> str:
    """Échappe un chemin Windows pour les filtres ffmpeg (``subtitles=``)."""
    text = str(path).replace("\\", "/")
    text = text.replace(":", "\\:").replace("'", "\\'").replace("[", "\\[").replace("]", "\\]")
    return text


def build_crop_filter(width: int, height: int, *, crop: str | None = "center") -> str:
    """Filtre de recadrage 9:16 (ou 16:9) centré sur la source."""
    if crop and crop not in {"center", "top"}:
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    y_offset = "(ih-ow)/2" if crop != "top" else "0"
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)/2:{y_offset},"
        f"setsar=1,format=yuv420p"
    )


def build_cut_command(
    ffmpeg: str,
    video: str | Path,
    output: str | Path,
    *,
    start: float,
    end: float,
    width: int = 1080,
    height: int = 1920,
    aspect: str = "9:16",
    subtitles: str | Path | None = None,
    fast: bool = False,
    crop: str | None = "center",
) -> list[str]:
    """Commande de découpe d'un extrait (recodage + recadrage + sous-titres)."""
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if fast:
        command += ["-ss", f"{max(0.0, start):.3f}", "-i", str(video)]
    else:
        command += ["-i", str(video), "-ss", f"{max(0.0, start):.3f}"]
    command += ["-t", f"{max(0.1, end - start):.3f}"]

    filters = []
    if aspect == "9:16":
        filters.append(build_crop_filter(width, height, crop=crop))
    else:
        filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:-1:-1,format=yuv420p")

    if subtitles:
        sub_path = escape_filter_path(subtitles)
        style = (
            "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=48,Alignment=2"
        )
        filters.append(f"subtitles='{sub_path}':force_style='{style}'")

    command += ["-vf", ",".join(filters)]
    command += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "21",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output),
    ]
    return command


def build_thumbnail_command(
    ffmpeg: str,
    video: str | Path,
    output: str | Path,
    *,
    timestamp: float,
    width: int = 720,
) -> list[str]:
    """Commande d'extraction d'une image de couverture."""
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, timestamp):.3f}",
        "-i", str(video),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "3",
        str(output),
    ]


def build_concat_command(ffmpeg: str, list_file: str | Path, output: str | Path) -> list[str]:
    """Commande de concaténation (liste de segments)."""
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output),
    ]


def write_concat_file(paths: list[str | Path], target: str | Path) -> Path:
    """Écrit une liste de concat compatible ffmpeg."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for item in paths:
        absolute = str(Path(item).resolve()).replace("'", "'\\''")
        lines.append(f"file '{absolute}'")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def render_clip(
    video: str | Path,
    output: str | Path,
    *,
    start: float,
    end: float,
    settings: Settings,
    subtitles: str | Path | None = None,
    fast: bool = False,
) -> Path:
    """Rend un extrait et renvoie le chemin du fichier produit."""
    ffmpeg = resolve_ffmpeg(settings.ffmpeg_binary)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = build_cut_command(
        ffmpeg,
        video,
        output,
        start=start,
        end=end,
        width=settings.width,
        height=settings.height,
        aspect=settings.aspect_ratio,
        subtitles=subtitles,
        fast=fast,
    )
    run(command)
    return output


def render_thumbnail(
    video: str | Path,
    output: str | Path,
    *,
    timestamp: float,
    settings: Settings,
) -> Path:
    """Extrait une image de couverture pour un extrait."""
    ffmpeg = resolve_ffmpeg(settings.ffmpeg_binary)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    run(build_thumbnail_command(ffmpeg, video, output, timestamp=timestamp))
    return output


def concat_clips(clips: list[str | Path], output: str | Path, *, settings: Settings) -> Path:
    """Concatène plusieurs extraits déjà rendus en un seul fichier."""
    if not clips:
        raise FFmpegError("Aucun extrait à concaténer.")
    ffmpeg = resolve_ffmpeg(settings.ffmpeg_binary)
    list_file = Path(output).with_suffix(".concat.txt")
    write_concat_file(clips, list_file)
    run(build_concat_command(ffmpeg, list_file, output))
    return Path(output)
