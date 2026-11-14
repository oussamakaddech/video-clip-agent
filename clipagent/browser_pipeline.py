"""Orchestration du mode « navigateur » : analyser une VOD sans la télécharger.

Enchaînement
------------
1. storyboard dans le navigateur (images + mesure du mouvement) ;
2. pics de mouvement → fenêtres candidates ;
3. capture **audio seule** de chaque fenêtre → transcription locale (Whisper) ;
4. l'agent LLM choisit les extraits (titre + hook) à partir de ces transcriptions ;
5. capture **audio + vidéo** des seuls extraits retenus → sous-titres (transcription
   du fragment exact) → rendu vertical 1080×1920 par ffmpeg.

Aucun téléchargement de la VOD complète n'est effectué.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .browser import BrowserAnalyzer, BrowserError, FrameSample
from .config import Settings
from .ffmpeg import FFmpegError, concat_clips, render_clip
from .hooks import resolve_hook
from .models import Clip, Segment
from .pipeline import Plan, write_clip_ass
from .selection import validate_proposals
from .styles import ClipStyle, get_style
from .transcript import Transcript


# --- Détection de pics (logique pure, testable) ----------------------------
def detect_peaks(
    samples: list[FrameSample],
    *,
    count: int = 8,
    min_gap: float = 180.0,
) -> list[FrameSample]:
    """Retient les `count` échantillons les plus « mouvementés », bien espacés.

    Le score combine le mouvement brut et un bonus de pic local : un échantillon
    très actif surrounded d'échantillons calmes marque un moment fort.
    """
    if not samples:
        return []
    motions = [s.motion for s in samples]
    peak_bonus: dict[float, float] = {}
    for index, sample in enumerate(samples):
        before = motions[index - 1] if index > 0 else 0.0
        after = motions[index + 1] if index + 1 < len(motions) else 0.0
        neighbours = (before + after) / 2
        peak_bonus[sample.timestamp] = max(0.0, sample.motion - neighbours)

    scored = sorted(
        samples,
        key=lambda s: -(s.motion + 0.6 * peak_bonus[s.timestamp]),
    )

    chosen: list[FrameSample] = []
    for sample in scored:
        if all(abs(sample.timestamp - other.timestamp) >= min_gap for other in chosen):
            chosen.append(sample)
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda s: s.timestamp)


# --- Transcription locale ---------------------------------------------------
def transcribe_media(
    path: str | Path,
    *,
    model_name: str = "tiny",
    language: str | None = None,
    offset: float = 0.0,
) -> list[Segment]:
    """Transcrit un média local (Whisper) et renvoie des segments décalés."""
    from faster_whisper import WhisperModel

    model = _whisper_model(model_name)
    segments, _info = model.transcribe(str(path), language=language, vad_filter=True)
    return [
        Segment(index=i, start=s.start + offset, end=s.end + offset, text=s.text.strip())
        for i, s in enumerate(segments, start=1)
        if s.text and s.text.strip()
    ]


_WHISPER_CACHE: dict[str, object] = {}


def _whisper_model(model_name: str):
    if model_name not in _WHISPER_CACHE:
        from faster_whisper import WhisperModel

        _WHISPER_CACHE[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _WHISPER_CACHE[model_name]


# --- Pipeline complet -------------------------------------------------------
@dataclass
class BrowserOptions:
    """Réglages du mode navigateur."""

    step: float = 60.0
    candidates: int = 8
    window: float = 35.0
    num_clips: int = 6
    min_clip: float = 25.0
    max_clip: float = 90.0
    whisper_model: str = "tiny"
    language: str | None = None
    channel: str = "msedge"
    headless: bool = True
    style: str | None = None
    padding: float = 1.5


def analyze_in_browser(
    url: str,
    settings: Settings,
    options: BrowserOptions | None = None,
    *,
    output_dir: str | Path | None = None,
) -> Plan:
    """Analyse une VOD dans le navigateur et produit les extraits verticaux."""
    opts = options or BrowserOptions()
    out_dir = Path(output_dir or settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    style: ClipStyle = get_style(opts.style or settings.style)
    plan = Plan(model=settings.model, style=style.name)

    with BrowserAnalyzer(url, out_dir=out_dir / "browser", headless=opts.headless, channel=opts.channel) as browser:
        info = browser.open()
        duration = float(info.get("duration") or 0)
        plan.duration = duration
        plan.video = url

        print(f"→ storyboard (1 image / {opts.step:.0f} s)", flush=True)
        samples = browser.storyboard(step=opts.step)
        peaks = detect_peaks(samples, count=opts.candidates, min_gap=max(120.0, opts.window * 4))
        print(f"  {len(peaks)} fenêtres candidates : "
              + ", ".join(f"{p.timestamp:.0f}s" for p in peaks), flush=True)

        # --- Étape 3 : audio des fenêtres candidates -----------------------
        segments: list[Segment] = []
        for index, peak in enumerate(peaks, start=1):
            start = max(0.0, peak.timestamp - opts.window / 2)
            end = min(duration, peak.timestamp + opts.window / 2)
            if end - start < 5:
                continue
            audio_path = work_dir / f"cand_{index:02d}.webm"
            print(f"→ capture audio #{index} ({start:.0f}→{end:.0f} s)", flush=True)
            try:
                browser.capture(start, end, audio_path, audio_only=True, bitrate=64_000)
            except BrowserError as exc:
                plan.warnings.append(f"Capture audio impossible ({start:.0f} s) : {exc}")
                continue
            try:
                segments.extend(
                    transcribe_media(
                        audio_path,
                        model_name=opts.whisper_model,
                        language=opts.language or settings.language if settings.language != "fr" else opts.language,
                        offset=start,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                plan.warnings.append(f"Transcription impossible ({start:.0f} s) : {exc}")
            finally:
                audio_path.unlink(missing_ok=True)

        transcript = Transcript(segments=sorted(segments, key=lambda s: s.start), source=url)
        if not transcript.segments:
            plan.warnings.append("Aucune transcription obtenue : aucun extrait ne peut être proposé.")
            plan.mode = "browser"
            return plan

        # --- Étape 4 : sélection par l'agent -------------------------------
        proposals = []
        try:
            from .llm import run_agent_chunked

            proposals, chunks = run_agent_chunked(
                transcript,
                settings,
                duration=duration,
                max_chunks=settings.max_chunks,
            )
            plan.chunks = chunks
            plan.mode = "browser+llm"
        except Exception as exc:  # noqa: BLE001
            plan.warnings.append(f"Agent indisponible ({exc}) : sélection par mouvement seule.")
            plan.mode = "browser"

        if not proposals:
            from .selection import heuristic_proposals

            proposals = heuristic_proposals(
                list(transcript.segments),
                min_length=opts.min_clip,
                max_length=opts.max_clip,
                limit=opts.num_clips,
            )

        plan.clips = validate_proposals(
            proposals,
            duration=duration,
            min_length=opts.min_clip,
            max_length=opts.max_clip,
            limit=opts.num_clips,
            segments=list(transcript.segments),
        )

        # --- Étape 5 : capture finale + rendu ------------------------------
        rendered: list[str] = []
        for clip in plan.clips:
            start = max(0.0, clip.start - opts.padding)
            end = min(duration, clip.end + opts.padding)
            print(f"→ capture finale #{clip.index} ({start:.0f}→{end:.0f} s)", flush=True)
            fragment = work_dir / f"clip_{clip.index:02d}.webm"
            try:
                browser.capture(start, end, fragment, audio_only=False)
            except BrowserError as exc:
                plan.warnings.append(f"Capture de l'extrait #{clip.index} impossible : {exc}")
                continue

            offset = clip.start - start
            clip_segments = transcribe_media(
                fragment,
                model_name=opts.whisper_model,
                language=opts.language,
            )
            clip_transcript = Transcript(segments=clip_segments, source=str(fragment))

            style_used = style
            hook_text = ""
            if style_used.hook_enabled:
                hook_text = resolve_hook(
                    clip,
                    list(clip_transcript.segments),
                    max_chars=style_used.hook_max_chars,
                    uppercase=style_used.hook_uppercase,
                )
            clip.hook = hook_text

            ass_path = work_dir / f"clip_{clip.index:02d}.ass"
            write_clip_ass(
                clip_transcript,
                clip,
                ass_path,
                style_used,
                absolute=False,
                hook_text=hook_text,
                offset=offset,
            )

            out_path = out_dir / f"clip_{clip.index:02d}_{_safe(clip.title)}.mp4"
            try:
                render_clip(
                    fragment,
                    out_path,
                    start=offset,
                    end=offset + clip.duration,
                    settings=settings,
                    subtitles=ass_path,
                    style=style_used,
                )
            except FFmpegError as exc:
                plan.warnings.append(f"Rendu de l'extrait #{clip.index} impossible : {exc}")
                continue
            clip.path = str(out_path)
            rendered.append(str(out_path))
            fragment.unlink(missing_ok=True)
            ass_path.unlink(missing_ok=True)

    if len(rendered) > 1:
        try:
            concat_clips(rendered, out_dir / "best_of.mp4", settings=settings)
        except FFmpegError as exc:
            plan.warnings.append(f"Concaténation impossible : {exc}")

    return plan


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:48].strip("_") or "extrait"
