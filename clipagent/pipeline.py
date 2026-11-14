"""Orchestration : transcription -> sélection (agent) -> rendu (ffmpeg) -> rapport."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg import FFmpegError, concat_clips, probe, render_clip, render_thumbnail
from .hooks import hook_lines, resolve_hook
from .models import Clip
from .selection import heuristic_proposals, validate_proposals
from .styles import ClipStyle, get_style
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
    style: str = "default"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video": self.video,
            "transcript": self.transcript_source,
            "duration": round(self.duration, 2),
            "mode": self.mode,
            "model": self.model,
            "chunks": self.chunks,
            "style": self.style,
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


def _ass_time(seconds: float) -> str:
    """Horodatage ASS ``H:MM:SS.cc``."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rest = seconds % 60
    return f"{hours}:{minutes:02d}:{rest:05.2f}"


def write_clip_ass(
    transcript: Transcript,
    clip: Clip,
    path: str | Path,
    style,
    *,
    absolute: bool = True,
    hook_text: str = "",
    offset: float = 0.0,
) -> Path:
    """Écrit un fichier ASS (sous-titres + accroche) pour un extrait.

    ``absolute=True`` conserve les horodatages de la source : c'est ce qu'attend
    le filtre ``subtitles`` quand la découpe se fait en seek de sortie
    (``-ss`` après ``-i``), car les images filtrées portent encore l'horodatage
    d'origine. En seek d'entrée, ou sur un fragment téléchargé séparément
    (``absolute=False``), les temps sont relatifs au fragment (``offset``).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style.subtitle.to_ass_style("Sub"),
        style.hook_style.to_ass_style("Hook"),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: list[str] = []
    # En mode relatif, les temps sont exprimés dans le référentiel du fragment
    # téléchargé : fragment_start = clip.start - offset.
    base = (clip.start - offset) if not absolute else 0.0
    for segment in transcript.window(clip.start, clip.end):
        if absolute:
            start, end = segment.start, segment.end
        else:
            start = max(0.0, segment.start - base)
            end = min(clip.duration + offset, segment.end - base)
        if end <= start:
            continue
        text = segment.text.replace("\n", "\\N")
        if style.subtitle.uppercase:
            text = text.upper()
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Sub,,0,0,0,,{text}"
        )

    if hook_text:
        lines = hook_lines(hook_text, max_chars_per_line=max(18, style.hook_max_chars // 2))
        # Auto-cale : une ligne trop longue réduirait la police pour tenir dans la largeur.
        longest = max((len(line) for line in lines), default=0)
        reference = max(18, style.hook_max_chars // 2)
        font_size = style.hook_style.size
        if longest > reference:
            font_size = max(40, int(style.hook_style.size * reference / longest))
        payload = "\\N".join(f"{{\\fs{font_size}}}{line}" for line in lines)
        # L'accroche doit démarrer au début de la coupe (output 0 s).
        hook_start = clip.start if absolute else offset
        events.append(
            f"Dialogue: 1,{_ass_time(hook_start)},{_ass_time(hook_start + style.hook_duration)},"
            f"Hook,,0,0,0,,{payload}"
        )

    if not events:
        fallback_start = clip.start if absolute else offset
        events.append(
            f"Dialogue: 0,{_ass_time(fallback_start)},"
            f"{_ass_time(fallback_start + clip.duration)},Sub,,0,0,0,,{clip.title}"
        )

    path.write_text("\n".join(header + events) + "\n", encoding="utf-8")
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
        style=get_style(settings.style).name,
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


def _detect_face(video: Path, duration: float):
    """Cherche le visage du streamer dans la source (boîte élargie et carrée)."""
    try:
        from .facecam import detect_face_in_video

        box = detect_face_in_video(video, samples=8, duration=max(10.0, duration))
        if box is None:
            return None
        return box.padded(0.6).square()
    except Exception:  # noqa: BLE001 - la face cam est optionnelle
        return None


def render_plan(
    plan: Plan,
    video: str | Path,
    settings: Settings,
    *,
    transcript: Transcript | None = None,
    output_dir: str | Path | None = None,
    make_concat: bool = True,
    style: ClipStyle | None = None,
) -> Plan:
    """Rend chaque extrait (recadré vertical + sous-titres + hook) et les vignettes."""
    if not video:
        raise ValueError("Une vidéo est nécessaire pour le rendu.")
    out_dir = Path(output_dir or settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video).stem
    style = style or get_style(settings.style)
    plan.style = style.name

    rendered: list[str] = []
    for clip in plan.clips:
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in clip.title)[:48].strip("_") or "extrait"
        clip_path = out_dir / f"{stem}_{clip.index:02d}_{safe_title}.mp4"
        ass_path: Path | None = None
        hook_text = ""
        if transcript is not None:
            if style.hook_enabled:
                hook_text = resolve_hook(
                    clip,
                    list(transcript.segments),
                    max_chars=style.hook_max_chars,
                    uppercase=style.hook_uppercase,
                )
            if settings.burn_subtitles or hook_text:
                ass_path = write_clip_ass(
                    transcript,
                    clip,
                    out_dir / f"{stem}_{clip.index:02d}.ass",
                    style,
                    hook_text=hook_text,
                )
        clip.hook = hook_text
        face_box = None
        if style.facecam_enabled and video:
            face_box = _detect_face(Path(video), clip.duration)
            if face_box is None:
                plan.warnings.append(f"Visage non détecté pour l'extrait #{clip.index} : rendu sans face cam.")
        try:
            render_clip(
                video,
                clip_path,
                start=clip.start,
                end=clip.end,
                settings=settings,
                subtitles=ass_path,
                style=style,
                face_box=face_box,
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


def render_plan_remote(
    plan: Plan,
    url: str,
    settings: Settings,
    *,
    transcript: Transcript | None = None,
    output_dir: str | Path | None = None,
    make_concat: bool = True,
    style: ClipStyle | None = None,
    cookies_from_browser: str | None = None,
    padding: float = 2.0,
) -> Plan:
    """Rend les extraits **sans télécharger la VOD complète**.

    Pour chaque extrait, seule la plage utile est téléchargée (yt-dlp fait des
    requêtes HTTP partielles), puis la coupe finale est faite en local.
    Mode « connexion faible ».
    """
    from .download import download_section

    out_dir = Path(output_dir or settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(settings.download_dir) / "sections"
    cache_dir.mkdir(parents=True, exist_ok=True)
    style = style or get_style(settings.style)
    plan.style = style.name

    rendered: list[str] = []
    for clip in plan.clips:
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in clip.title)[:48].strip("_") or "extrait"
        clip_path = out_dir / f"clip_{clip.index:02d}_{safe_title}.mp4"
        section_start = max(0.0, clip.start - padding)
        section_end = clip.end + padding

        try:
            section_file = download_section(
                url,
                section_start,
                section_end,
                settings=settings,
                out_dir=cache_dir,
                cookies_from_browser=cookies_from_browser,
            )
        except Exception as exc:  # noqa: BLE001
            plan.warnings.append(f"Téléchargement du fragment #{clip.index} impossible : {exc}")
            continue

        # Le fragment téléchargé démarre à section_start : on coupe au bon offset.
        offset = max(0.0, clip.start - section_start)
        ass_path: Path | None = None
        hook_text = ""
        if transcript is not None:
            if style.hook_enabled:
                hook_text = resolve_hook(
                    clip,
                    list(transcript.segments),
                    max_chars=style.hook_max_chars,
                    uppercase=style.hook_uppercase,
                )
            if settings.burn_subtitles or hook_text:
                ass_path = write_clip_ass(
                    transcript,
                    clip,
                    out_dir / f"clip_{clip.index:02d}.ass",
                    style,
                    absolute=False,   # le fragment démarre à 0
                    hook_text=hook_text,
                    offset=offset,
                )
        clip.hook = hook_text
        try:
            render_clip(
                section_file,
                clip_path,
                start=offset,
                end=offset + clip.duration,
                settings=settings,
                subtitles=ass_path,
                style=style,
            )
        except FFmpegError as exc:
            plan.warnings.append(f"Rendu de l'extrait #{clip.index} impossible : {exc}")
            continue

        clip.path = str(clip_path)
        rendered.append(str(clip_path))
        try:
            section_file.unlink(missing_ok=True)   # on ne garde que le clip final
        except OSError:
            pass

    if make_concat and len(rendered) > 1:
        try:
            concat_clips(rendered, out_dir / "best_of.mp4", settings=settings)
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
