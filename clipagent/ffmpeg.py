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
    y_offset = "(ih-oh)/2" if crop != "top" else "0"
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)/2:{y_offset},"
        f"setsar=1,format=yuv420p"
    )


def build_zoom_filter(width: int, height: int, zoom: float, *, fps: int = 25) -> str:
    """Filtre de zoom progressif (effet Ken Burns) : 1.0 = pas de zoom."""
    if zoom is None or zoom <= 1.001:
        return ""
    step = max(0.0005, (zoom - 1.0) / (fps * 3))
    return (
        f"zoompan=z='min(zoom+{step:.5f},{zoom:.3f})':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
    )


def build_facecam_filter_complex(
    width: int,
    height: int,
    face: "object",
    *,
    face_size: int = 320,
    position: str = "bottom-center",
    shape: str = "circle",
    margin: int = 140,
    content_top: bool = True,
    subs: str | None = None,
    layout: str = "split",
    top_ratio: float = 0.67,
    sharpen: float = 0.6,
    enhance: bool = True,
) -> str:
    """Chaîne de filtres « face cam ».

    - ``layout="split"`` : écran divisé — contenu sur les 2/3 du haut,
      visage du streamer sur le 1/3 du bas (format court) ;
    - ``layout="blurred"`` : contenu net en haut sur un fond flouté ;
    - ``shape="circle"`` : le visage est détouré en cercle (alpha via ``geq``).

    Les webm produits par MediaRecorder déclarent parfois une résolution
    d'en-tête fausse (ex. 284x160 pour des frames en 1280x720) : on normalise
    donc la taille **avant** le recadrage, sinon ffmpeg refuse le crop.
    """
    x = int(max(0, face.x))  # type: ignore[attr-defined]
    y = int(max(0, face.y))  # type: ignore[attr-defined]
    w = int(max(8, face.width))  # type: ignore[attr-defined]
    h = int(max(8, face.height))  # type: ignore[attr-defined]
    frame_w = int(getattr(face, "frame_width", 0) or 0)
    frame_h = int(getattr(face, "frame_height", 0) or 0)
    normalize = f"scale={frame_w}:{frame_h}," if frame_w > 0 and frame_h > 0 else ""

    face_chain = f"[face]{normalize}crop={w}:{h}:{x}:{y},scale={face_size}:{face_size}"
    if shape == "circle":
        radius = face_size / 2
        face_chain += (
            ",format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='if(lt(pow(X-{radius:.0f},{2})+pow(Y-{radius:.0f},{2}),{radius * radius:.0f}),255,0)'"
        )
    face_chain += "[facec]"

    parts: list[str] = []
    quality_chain = ""
    sharpen_filter = build_sharpen_filter(sharpen)
    if sharpen_filter:
        quality_chain += sharpen_filter + ","
    if enhance:
        quality_chain += build_enhance_filter() + ","

    if layout == "cam-bottom":
        # Layout « référence » : contenu sur le haut (couvre la zone),
        # caméra du streamer PLEIN CADRE sur la bande du bas.
        top_h = int(height * top_ratio)
        band = height - top_h
        parts.append(
            f"[main]split=2[ct][cam];"
            f"[ct]{normalize}scale={width}:{top_h}:force_original_aspect_ratio=increase,"
            f"crop={width}:{top_h}:(iw-ow)/2:(ih-oh)/2,{quality_chain}setsar=1,"
            f"pad={width}:{height}:0:0:color=black[ctop];"
            f"[cam]{normalize}crop={w}:{h}:{x}:{y},"
            f"scale={width}:{band}:force_original_aspect_ratio=increase,"
            f"crop={width}:{band}:(iw-ow)/2:(ih-oh)/2,{quality_chain}setsar=1[camc]"
        )
        parts.append(f"[ctop][camc]overlay=0:{top_h}[ov]")
    elif layout == "split":
        # Écran divisé : contenu net sur les 2/3 du haut (fond flouté pour
        # combler la letterbox), visage du streamer dans le 1/3 du bas.
        face_y = height - face_size - margin
        parts.append(
            f"[main]split=3[bg][ct][face];"
            f"[bg]{normalize}scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,boxblur=24:3[blurred];"
            f"[ct]{normalize}scale={width}:-2[ctop];"
            f"[blurred][ctop]overlay=0:0[bg2]"
        )
        parts.append(face_chain)
        parts.append(f"[bg2][facec]overlay=(W-w)/2:{face_y}[ov]")
    elif content_top:
        # Fond flouté (copie agrandie) + contenu net en haut.
        parts.append(
            f"[main]split=3[bg][ct][face];"
            f"[bg]{normalize}scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,boxblur=24:3[blurred];"
            f"[ct]{normalize}scale={width}:-2[ctop];"
            f"[blurred][ctop]overlay=0:0[bg2]"
        )
        parts.append(face_chain)
        parts.append("[bg2][facec]overlay=" + _overlay_position(position, margin) + "[ov]")
    else:
        parts.append(
            f"[main]{normalize}scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,setsar=1,format=yuv420p[bg]"
        )
        parts.append(face_chain)
        parts.append("[bg][facec]overlay=" + _overlay_position(position, margin) + "[ov]")

    if subs:
        sub_path = escape_filter_path(subs)
        if str(subs).lower().endswith(".ass"):
            # Un ASS porte ses propres styles : ne surtout pas les écraser
            # (sinon l'accroche et les sous-titres perdent leur position).
            parts.append(f"[ov]subtitles='{sub_path}'[v]")
        else:
            style = (
                "FontName=Arial,FontSize=48,PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,MarginV=90,Alignment=2"
            )
            parts.append(f"[ov]subtitles='{sub_path}':force_style='{style}'[v]")
    else:
        parts.append("[ov]null[v]")
    return ";".join(parts)


def _overlay_position(position: str, margin: int) -> str:
    if position == "bottom-left":
        return f"40:H-h-{margin}"
    if position == "bottom-right":
        return f"W-w-40:H-h-{margin}"
    return f"(W-w)/2:H-h-{margin}"


def find_font(name: str = "arialbd.ttf") -> str | None:
    """Retrouve un fichier de police TrueType (pour le filtre drawtext)."""
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name,
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate).replace("\\", "/").replace(":", "\\:")
    return None


def build_overlay_chain(
    video_label: str,
    *,
    width: int,
    height: int,
    logo: str | Path | None = None,
    logo_size: int = 120,
    logo_margin: int = 40,
) -> tuple[str, list[str]]:
    """Badge logo posé en haut à gauche (comme sur la vidéo de référence).

    Renvoie l'étiquette de sortie et les entrées ffmpeg supplémentaires.
    """
    parts: list[str] = []
    extra_inputs: list[str] = []
    current = video_label

    if logo:
        logo_path = Path(logo)
        if logo_path.exists():
            extra_inputs.append(str(logo_path))
            parts.append(f"[1:v]scale={logo_size}:-1[logo_s]")
            parts.append(f"[{current}][logo_s]overlay={logo_margin}:{logo_margin}[ov_logo]")
            current = "ov_logo"

    return current, extra_inputs


def build_sharpen_filter(strength: float = 0.6) -> str:
    """Accentuation après agrandissement : compense le flou de l'upscale.

    Une source 360p montée en 1080×1920 est molle ; un ``unsharp`` mesuré
    rend le texte lisible à nouveau.
    """
    if strength <= 0:
        return ""
    return f"unsharp=5:5:{strength:.2f}:5:5:0.0"


def build_enhance_filter(
    *,
    contrast: float = 1.06,
    brightness: float = 0.012,
    saturation: float = 1.08,
) -> str:
    """Ajustement léger du rendu (les écrans de stream sont souvent ternes)."""
    return (
        f"eq=contrast={contrast:.3f}:brightness={brightness:.3f}:saturation={saturation:.3f}"
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
    subtitle_size: int | None = None,
    zoom: float = 1.0,
    fps: int = 30,
    face_box: object | None = None,
    face_size: int = 320,
    face_position: str = "bottom-center",
    face_shape: str = "circle",
    face_margin: int = 140,
    face_layout: str = "split",
    face_top_ratio: float = 0.67,
    logo: str | Path | None = None,
    logo_size: int = 120,
    sharpen: float = 0.6,
    enhance: bool = True,
    crf: int = 18,
    encoder: str = "libx264",
    preset: str = "slow",
    audio_bitrate: str = "192k",
) -> list[str]:
    """Commande de découpe d'un extrait (recodage + recadrage + sous-titres)."""
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if fast:
        command += ["-ss", f"{max(0.0, start):.3f}", "-i", str(video)]
    else:
        command += ["-i", str(video), "-ss", f"{max(0.0, start):.3f}"]
    command += ["-t", f"{max(0.1, end - start):.3f}"]

    if face_box is not None:
        # Face cam : contenu en haut, caméra du streamer en bas.
        chain = build_facecam_filter_complex(
            width,
            height,
            face_box,
            face_size=face_size,
            position=face_position,
            shape=face_shape,
            margin=face_margin,
            content_top=True,
            subs=subtitles,
            layout=face_layout,
            top_ratio=face_top_ratio,
            sharpen=sharpen,
            enhance=enhance,
        )
        label, logo_inputs = build_overlay_chain(
            "v", width=width, height=height, logo=logo, logo_size=logo_size
        )
        if logo_inputs:
            chain += ";".join([
                "[v][1:v]scale={}:-1[logo_s]".format(logo_size),
                "[v][logo_s]overlay={}:{}[ov_logo]".format(40, 40),
                "[ov_logo]null[v]",
            ])
            command += ["-filter_complex", chain]
            command += ["-i", *logo_inputs]
        else:
            command += ["-filter_complex", chain]
        command += ["-map", "[v]", "-map", "0:a?"]
    else:
        filters = []
        if aspect == "9:16":
            filters.append(build_crop_filter(width, height, crop=crop))
        else:
            filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:-1:-1,format=yuv420p")

        zoom_filter = build_zoom_filter(width, height, zoom, fps=fps)
        if zoom_filter:
            filters.append(zoom_filter)

        sharpen_filter = build_sharpen_filter(sharpen)
        if sharpen_filter:
            filters.append(sharpen_filter)
        if enhance:
            filters.append(build_enhance_filter())

        sharpen_filter = build_sharpen_filter(sharpen)
        if sharpen_filter:
            filters.append(sharpen_filter)
        if enhance:
            filters.append(build_enhance_filter())

        if subtitles:
            sub_path = escape_filter_path(subtitles)
            is_ass = str(subtitles).lower().endswith(".ass")
            if is_ass:
                # Un fichier ASS porte ses propres styles : ne surtout pas les écraser.
                filters.append(f"subtitles='{sub_path}'")
            else:
                size = subtitle_size if subtitle_size else 14
                style = (
                    f"FontName=Arial,FontSize={size},PrimaryColour=&H00FFFFFF,"
                    "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=48,Alignment=2"
                )
                filters.append(f"subtitles='{sub_path}':force_style='{style}'")

        label, logo_inputs = build_overlay_chain(
            "0:v", width=width, height=height, logo=logo, logo_size=logo_size
        )
        if logo_inputs:
            filters.append(f"[{label}][1:v]scale={logo_size}:-1[logo_s]")
            filters.append(f"[{label}][logo_s]overlay=40:40[v]")
            command += ["-filter_complex", ";".join(filters)]
            command += ["-i", *logo_inputs]
            command += ["-map", "[v]", "-map", "0:a?"]
        else:
            command += ["-vf", ",".join(filters)]

    # Encodage : le codec est au choix (H.264 universel, H.265 plus compact,
    # VP9 pour YouTube). CRF = qualité (plus bas = mieux), preset = vitesse.
    if encoder == "libx265":
        video_args = ["-c:v", "libx265", "-preset", preset, "-crf", str(crf), "-tag:v", "hvc1"]
    elif encoder == "libvpx-vp9":
        video_args = ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-row-mt", "1"]
    else:
        video_args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]

    command += video_args + [
        "-profile:v", "high",
        "-level", "4.1",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-ar", "48000",
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
    style=None,
    face_box: object | None = None,
    encoder: str = "libx264",
    preset: str = "slow",
    audio_bitrate: str = "192k",
) -> Path:
    """Rend un extrait et renvoie le chemin du fichier produit."""
    ffmpeg = resolve_ffmpeg(settings.ffmpeg_binary)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    zoom = 1.0
    crop = "center"
    face_size = 320
    face_position = "bottom-center"
    face_shape = "circle"
    face_margin = 140
    face_layout = "split"
    face_top_ratio = 0.67
    if style is not None:
        zoom = getattr(style, "zoom", 1.0) or 1.0
        crop = getattr(style, "crop", "center") or "center"
        face_size = getattr(style, "facecam_size", 320) or 320
        face_position = getattr(style, "facecam_position", "bottom-center")
        face_shape = getattr(style, "facecam_shape", "circle")
        face_margin = getattr(style, "facecam_margin", 140)
        face_layout = getattr(style, "facecam_layout", "split")
        face_top_ratio = getattr(style, "facecam_top_ratio", 0.67)

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
        crop=crop,
        zoom=zoom,
        face_box=face_box,
        face_size=face_size,
        face_position=face_position,
        face_shape=face_shape,
        face_margin=face_margin,
        face_layout=face_layout,
        face_top_ratio=face_top_ratio,
        logo=settings.logo,
        logo_size=settings.logo_size,
        encoder=encoder,
        preset=preset,
        audio_bitrate=audio_bitrate,
        crf=getattr(settings, "crf", 18),
        fps=getattr(settings, "fps", 30),
        sharpen=getattr(settings, "sharpen", 0.6),
        enhance=getattr(settings, "enhance", True),
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
