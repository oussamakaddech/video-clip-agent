"""Orchestration : transcription -> sélection (agent) -> rendu (ffmpeg) -> rapport."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg import FFmpegError, concat_clips, probe, render_clip, render_thumbnail
from .models import Clip
from .selection import heuristic_proposals, validate_proposals
from .transcript import Transcript, format_timestamp, load_transcript


@dataclass
class Plan:
    """Plan de clipping : les extraits retenus + les métadonnées du traitement."""

    clips: list[Clip] = field(default_factory=list)
    video: str | None = None
    transcript_source: str | None = None
    duration: float = 0.0
    mode: str = "llm"
    model: str | None = None
    chunks: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video": self.video,
            "transcript": self.transcript_source,
            "duration": round(self.duration, 2),
            "mode": self.mode,
            "model": self.model,
            "chunks": self.chunks,
            "warnings": list(self.warnings),
            "clips": [clip.to_dict() for clip in self.clips],
        }


def write_clip_srt(
    transcript: Transcript,
    clip: Clip,
    path: str | Path,
    *,
    absolute: bool = True,
) -> Path:
    """Écrit un SRT pour l'extrait, à incruster par ffmpeg.

    ``absolute=True`` conserve les horodatages de la source : c'est ce qu'attend
    le filtre ``subtitles`` quand la découpe se fait en seek de sortie
    (``-ss`` placé après ``-i``), car les images filtrées portent encore le
    horodatage d'origine. En seek d'entrée, utiliser ``absolute=False``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    index = 1
    for segment in transcript.window(clip.start, clip.end):
        if absolute:
            start, end = segment.start, segment.end
        else:
            start = max(0.0, segment.start - clip.start)
            end = min(clip.duration, segment.end - clip.start)
        if end <= start:
            continue
        blocks.append(
            f"{index}\n"
            f"{format_timestamp(start)} --> {format_timestamp(end)}\n"
            f"{segment.text}\n"
        )
        index += 1
    if not blocks:
        blocks.append(
            f"1\n{format_timestamp(clip.start)} --> {format_timestamp(clip.end)}\n{clip.title}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def plan_clips(
    video: str | Path | None,
    transcript: Transcript,
    settings: Settings,
    *,
    instruction: str = "",
    duration: float | None = None,
    use_llm: bool | None = None,
) -> Plan:
    """Sélectionne les extraits : via l'agent LLM, ou en repli heuristique."""
    media_duration = duration or 0.0
    if video and not media_duration:
        try:
            media_duration = probe(video, ffprobe_binary=None).duration
        except (FFmpegError, Exception):  # noqa: BLE001 - la sonde est optionnelle
            media_duration = 0.0
    if not media_duration:
        media_duration = transcript.duration

    plan = Plan(
        video=str(video) if video else None,
        transcript_source=transcript.source,
        duration=media_duration,
        model=settings.model,
    )

    proposals = []
    want_llm = settings.api_key if use_llm is None else use_llm
    if want_llm:
        try:
            from .llm import run_agent_chunked

            proposals, chunks = run_agent_chunked(
                transcript,
                settings,
                duration=media_duration,
                extra_instruction=instruction or settings.instruction,
                max_chunks=settings.max_chunks,
            )
            plan.chunks = chunks
            if not proposals:
                plan.warnings.append("L'agent n'a proposé aucun extrait : repli heuristique utilisé.")
        except Exception as exc:  # noqa: BLE001 - on ne doit jamais perdre le pipeline
            plan.warnings.append(f"Agent LLM indisponible ({exc.__class__.__name__}: {exc}) : repli heuristique utilisé.")
            proposals = []
    else:
        plan.warnings.append("Aucune clé OPENAI_API_KEY : sélection heuristique (sans LLM).")

    if not proposals:
        plan.mode = "heuristic"
        proposals = heuristic_proposals(
            transcript.segments,
            min_length=settings.min_clip_seconds,
            max_length=settings.max_clip_seconds,
            limit=settings.num_clips,
        )
    else:
        plan.mode = "llm"

    plan.clips = validate_proposals(
        proposals,
        duration=media_duration or None,
        min_length=settings.min_clip_seconds,
        max_length=settings.max_clip_seconds,
        limit=settings.num_clips,
        segments=list(transcript.segments),
    )
    if not plan.clips:
        plan.warnings.append("Aucun extrait valide après validation.")
    return plan


def render_plan(
    plan: Plan,
    video: str | Path,
    settings: Settings,
    *,
    transcript: Transcript | None = None,
    output_dir: str | Path | None = None,
    make_concat: bool = True,
) -> Plan:
    """Rend chaque extrait (recadré vertical + sous-titres) et les vignettes."""
    if not video:
        raise ValueError("Une vidéo est nécessaire pour le rendu.")
    out_dir = Path(output_dir or settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video).stem

    rendered: list[str] = []
    for clip in plan.clips:
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in clip.title)[:48].strip("_") or "extrait"
        clip_path = out_dir / f"{stem}_{clip.index:02d}_{safe_title}.mp4"
        srt_path: Path | None = None
        if settings.burn_subtitles and transcript is not None:
            srt_path = write_clip_srt(transcript, clip, out_dir / f"{stem}_{clip.index:02d}.srt")
        try:
            render_clip(
                video,
                clip_path,
                start=clip.start,
                end=clip.end,
                settings=settings,
                subtitles=srt_path,
            )
        except FFmpegError as exc:
            plan.warnings.append(f"Rendu de l'extrait #{clip.index} impossible : {exc}")
            continue
        clip.path = str(clip_path)
        rendered.append(str(clip_path))
        try:
            thumb = render_thumbnail(video, out_dir / f"{stem}_{clip.index:02d}.jpg", timestamp=clip.start + 1.0, settings=settings)
            clip.thumbnail = str(thumb)
        except FFmpegError:
            pass

    if make_concat and len(rendered) > 1:
        try:
            concat_clips(rendered, out_dir / f"{stem}_best_of.mp4", settings=settings)
        except FFmpegError as exc:
            plan.warnings.append(f"Concaténation impossible : {exc}")
    return plan


def save_report(plan: Plan, output_dir: str | Path) -> tuple[Path, Path]:
    """Écrit le rapport JSON et Markdown du plan."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "clips_plan.json"
    json_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Plan de clipping", ""]
    if plan.video:
        lines.append(f"- **Vidéo** : `{plan.video}`")
    if plan.transcript_source:
        lines.append(f"- **Transcription** : `{plan.transcript_source}`")
    lines.append(f"- **Durée** : {plan.duration:.1f} s")
    lines.append(f"- **Mode de sélection** : {plan.mode}" + (f" ({plan.model})" if plan.model and plan.mode == "llm" else ""))
    if plan.chunks:
        lines.append(f"- **Portions analysées** : {plan.chunks}")
    lines.append("")
    if plan.warnings:
        lines += ["## Avertissements", ""] + [f"- {w}" for w in plan.warnings] + [""]
    lines += ["## Extraits", "", "| # | Début | Fin | Durée | Titre | Score | Fichier |", "|---|---|---|---|---|---|---|"]
    for clip in plan.clips:
        lines.append(
            f"| {clip.index} | {format_timestamp(clip.start)} | {format_timestamp(clip.end)} | "
            f"{clip.duration:.1f} s | {clip.title} | {clip.score:.2f} | "
            f"{Path(clip.path).name if clip.path else '—'} |"
        )
    lines.append("")
    for clip in plan.clips:
        if clip.reason:
            lines.append(f"- **{clip.index}. {clip.title}** — {clip.reason}")
    md_path = out_dir / "clips_plan.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run_pipeline(
    video: str | Path | None,
    transcript_path: str | Path,
    settings: Settings,
    *,
    instruction: str = "",
    output_dir: str | Path | None = None,
    render: bool = True,
    make_concat: bool = True,
) -> Plan:
    """Chaîne complète : analyse puis rendu."""
    transcript = load_transcript(transcript_path)
    out_dir = Path(output_dir or settings.output_dir)
    plan = plan_clips(video, transcript, settings, instruction=instruction)
    if render and video:
        plan = render_plan(plan, video, settings, transcript=transcript, output_dir=out_dir, make_concat=make_concat)
    save_report(plan, out_dir)
    return plan
