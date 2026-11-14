"""Couche de service : les opérations de haut niveau, partagées par le CLI et l'API.

Chaque fonction prend un rappel ``on_progress(message, ratio)`` pour que
l'interface web puisse suivre l'avancement en direct.
"""

from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Protocol

from .config import Settings
from .pipeline import Plan, plan_clips, render_plan, save_report
from .styles import STYLES, ClipStyle, get_style
from .transcript import Transcript, load_transcript

Progress = Callable[[str, float], None]


class ProgressSink(Protocol):
    """Objet qui reçoit les messages d'avancement."""

    def __call__(self, message: str, ratio: float = 0.0) -> None: ...


def _noop(message: str, ratio: float = 0.0) -> None:  # pragma: no cover
    return None


@dataclass
class ClipRequest:
    """Demande de clipping (source + options)."""

    url: str | None = None
    video_path: str | None = None
    transcript_path: str | None = None
    style: str = "default"
    profile: str = "default"
    language: str | None = None
    num_clips: int = 6
    min_clip: float = 45.0
    max_clip: float = 75.0
    whisper_model: str = "base"
    instruction: str = ""
    logo: str | None = None
    subtitles: bool = True
    facecam: bool | None = None

    def settings(self) -> Settings:
        """Construit les réglages à partir de la demande + de l'environnement."""
        settings = Settings.from_env(
            style=self.style,
            profile=self.profile,
            language=self.language,
            num_clips=self.num_clips,
            min_clip_seconds=self.min_clip,
            max_clip_seconds=self.max_clip,
            instruction=self.instruction,
            logo=self.logo,
            burn_subtitles=self.subtitles,
        )
        return settings


@dataclass
class ClipResult:
    """Résultat complet d'une demande."""

    plan: Plan
    output_dir: Path
    report_json: Path | None = None
    report_md: Path | None = None
    elapsed: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "clips": [clip.to_dict() for clip in self.plan.clips],
            "output_dir": str(self.output_dir),
            "report_json": str(self.report_json) if self.report_json else None,
            "report_md": str(self.report_md) if self.report_md else None,
            "elapsed": round(self.elapsed, 1),
            "mode": self.plan.mode,
            "style": self.plan.style,
            "duration": round(self.plan.duration, 1),
            "warnings": self.warnings,
        }


def unique_output_dir(base: str | Path, prefix: str = "job") -> Path:
    """Crée un dossier de sortie unique (horodaté + suffixe)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = Path(base) / f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"
    target.mkdir(parents=True, exist_ok=True)
    return target


def transcribe_media(
    video: str | Path,
    *,
    model: str = "base",
    language: str | None = None,
    output: str | Path | None = None,
    on_progress: Progress = _noop,
) -> Path:
    """Transcrit un média et écrit le SRT."""
    from .browser_pipeline import transcribe_media as _transcribe

    on_progress("Transcription en cours…", 0.1)
    segments = _transcribe(video, model_name=model, language=language)
    transcript = Transcript(segments=segments, source=str(video))
    target = Path(output or Path(video).with_suffix(".srt"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(transcript.to_srt(), encoding="utf-8")
    on_progress(f"Transcription terminée ({len(segments)} segments)", 1.0)
    return target


def validate_request(request: ClipRequest) -> list[str]:
    """Vérifie la demande avant de lancer une tâche (retourne les anomalies)."""
    problems: list[str] = []
    if not (request.url or request.video_path or request.transcript_path):
        problems.append("Fournissez une URL, un fichier vidéo ou une transcription.")
    if request.video_path and not Path(request.video_path).exists():
        problems.append(f"Vidéo introuvable : {request.video_path}")
    if request.transcript_path and not Path(request.transcript_path).exists():
        problems.append(f"Transcription introuvable : {request.transcript_path}")
    if request.max_clip < request.min_clip:
        problems.append("La durée maximale doit être supérieure à la durée minimale.")
    if request.url and not request.url.startswith(("http://", "https://")):
        problems.append("L'URL doit commencer par http:// ou https://.")
    free = free_space(".") // (1024 * 1024)
    if free < 2048:
        problems.append(f"Espace disque faible : {free} Mo libres.")
    return problems


def analyze(
    request: ClipRequest,
    *,
    output_dir: str | Path | None = None,
    on_progress: Progress = _noop,
) -> ClipResult:
    """Analyse une source (URL ou fichier) et produit le plan de clipping."""
    started = time.time()
    problems = validate_request(request)
    if problems:
        raise ValueError(" ; ".join(problems))

    settings = request.settings()
    out_dir = Path(output_dir) if output_dir else unique_output_dir("output")
    out_dir.mkdir(parents=True, exist_ok=True)

    video = request.video_path
    transcript_path = request.transcript_path

    if request.url and not (video or transcript_path):
        on_progress("Téléchargement de la VOD…", 0.05)
        from .download import download

        video = str(download(request.url, settings=settings, out_dir=settings.download_dir))

    if not transcript_path:
        if not video:
            raise ValueError("Fournissez une URL de VOD, un fichier vidéo ou une transcription.")
        on_progress("Transcription de la vidéo…", 0.15)
        transcript_path = str(
            transcribe_media(video, model=request.whisper_model, language=request.language, on_progress=on_progress)
        )

    on_progress("Analyse et sélection des extraits…", 0.5)
    transcript = load_transcript(transcript_path)
    plan = plan_clips(video, transcript, settings, instruction=request.instruction)
    report_json, report_md = save_report(plan, out_dir)
    on_progress(f"{len(plan.clips)} extrait(s) sélectionné(s)", 0.7)
    return ClipResult(
        plan=plan,
        output_dir=out_dir,
        report_json=report_json,
        report_md=report_md,
        elapsed=time.time() - started,
        warnings=list(plan.warnings),
    )


def render(
    request: ClipRequest,
    plan: Plan,
    *,
    output_dir: str | Path | None = None,
    on_progress: Progress = _noop,
) -> ClipResult:
    """Rend les extraits d'un plan (source locale ou fragments déjà capturés)."""
    started = time.time()
    settings = request.settings()
    out_dir = Path(output_dir or "output")
    out_dir.mkdir(parents=True, exist_ok=True)

    transcript = None
    if request.transcript_path:
        transcript = load_transcript(request.transcript_path)

    style: ClipStyle = get_style(request.style)
    if request.facecam is not None:
        # Activation/désactivation explicite de la face cam (le style reste la base).
        style = replace(style, facecam_enabled=request.facecam)

    on_progress("Rendu des extraits…", 0.2)
    if request.video_path:
        plan = render_plan(plan, request.video_path, settings, transcript=transcript, output_dir=out_dir, style=style)
    else:
        from .browser_pipeline import finalize_from_fragments

        plan = finalize_from_fragments(
            plan,
            out_dir / "work",
            settings,
            transcript=transcript,
            output_dir=out_dir,
            style=style,
            language=request.language,
            whisper_model=request.whisper_model,
        )
    report_json, report_md = save_report(plan, out_dir)
    on_progress(f"{len([c for c in plan.clips if c.path])} extrait(s) rendu(s)", 1.0)
    return ClipResult(
        plan=plan,
        output_dir=out_dir,
        report_json=report_json,
        report_md=report_md,
        elapsed=time.time() - started,
        warnings=list(plan.warnings),
    )


def download_video(
    url: str,
    *,
    settings: Settings | None = None,
    out_dir: str | Path | None = None,
    audio_only: bool = False,
    on_progress: Progress = _noop,
) -> Path:
    """Télécharge une VOD (utile avant analyse hors-ligne)."""
    from .download import download as _download

    settings = settings or Settings.from_env()
    on_progress(f"Téléchargement de {url}…", 0.2)
    path = _download(url, settings=settings, out_dir=out_dir, audio_only=audio_only)
    on_progress(f"Téléchargement terminé ({path.stat().st_size // (1024 * 1024)} Mo)", 1.0)
    return path


def available_styles() -> list[dict]:
    """Catalogue des styles pour l'interface."""
    return [
        {
            "name": style.name,
            "label": style.label,
            "description": style.description,
            "facecam": style.facecam_enabled,
            "hook": style.hook_enabled,
        }
        for style in STYLES.values()
    ]


def available_profiles() -> list[dict]:
    """Catalogue des profils."""
    from .config import PROFILES

    return [{"name": name, **values} for name, values in PROFILES.items()]


def disk_usage(path: str | Path) -> int:
    """Taille cumulée d'un dossier (octets)."""
    total = 0
    for item in Path(path).rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def free_space(path: str | Path = ".") -> int:
    """Espace libre sur le disque (octets)."""
    return shutil.disk_usage(str(path)).free
