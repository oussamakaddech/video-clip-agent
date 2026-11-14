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

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .browser import BrowserAnalyzer, BrowserError
from .chat import build_chat_context, extract_chat
from .config import Settings
from .ffmpeg import FFmpegError, concat_clips, render_clip
from .hooks import resolve_hook
from .models import Segment
from .pipeline import Plan, write_clip_ass
from .selection import validate_proposals
from .styles import ClipStyle, get_style
from .transcript import Transcript


# --- Détection de pics (délégué à clipagent.scoring) -----------------------
from .scoring import Candidate, detect_peaks, score_candidates

__all__ = [
    "BrowserOptions",
    "Candidate",
    "analyze_in_browser",
    "detect_peaks",
    "finalize_from_fragments",
    "score_candidates",
    "transcribe_media",
]


# --- Transcription locale ---------------------------------------------------
def transcribe_media(
    path: str | Path,
    *,
    model_name: str = "tiny",
    language: str | None = None,
    offset: float = 0.0,
) -> list[Segment]:
    """Transcrit un média local (Whisper) et renvoie des segments décalés."""
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
    window: float = 80.0
    num_clips: int = 6
    min_clip: float = 45.0
    max_clip: float = 75.0
    whisper_model: str = "tiny"
    language: str | None = None
    channel: str = "msedge"
    headless: bool = True
    style: str | None = None
    padding: float = 1.5
    use_chat: bool = True


def analyze_in_browser(
    url: str,
    settings: Settings,
    options: BrowserOptions | None = None,
    *,
    output_dir: str | Path | None = None,
    instruction: str = "",
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

        # Le chat replay est lu dans la page : signal sémantique gratuit pour
        # classer les fenêtres candidates (une vague de messages = moment fort).
        chat_messages: list = []
        if opts.use_chat:
            try:
                chat_messages = extract_chat(browser.page)
                print(f"  chat replay : {len(chat_messages)} message(s) lu(s)", flush=True)
            except Exception as exc:  # noqa: BLE001 - le chat est optionnel
                plan.warnings.append(f"Chat replay illisible ({exc.__class__.__name__}) : ignoré.")

        candidates = score_candidates(
            samples,
            chat_messages,
            count=opts.candidates,
            window=opts.window,
            min_gap=max(90.0, opts.window * 1.2),
        )
        print(
            f"  {len(candidates)} fenêtres candidates : "
            + ", ".join(f"{c.start:.0f}s(score {c.score:.2f})" for c in candidates),
            flush=True,
        )

        # --- Étape 3 : capture des fenêtres candidates ----------------------
        segments: list[Segment] = []
        candidate_spans: list[tuple[float, float]] = []
        for index, candidate in enumerate(candidates, start=1):
            start = max(0.0, candidate.start)
            end = min(duration, candidate.end)
            if end - start < 5:
                continue
            audio_path = work_dir / f"cand_{index:02d}.webm"
            print(f"→ capture candidate #{index} ({start:.0f}→{end:.0f} s)", flush=True)
            try:
                # Audio + vidéo à faible débit : le fragment pourra être réutilisé
                # pour le rendu final si l'extrait retenu est inclus dedans.
                browser.capture(start, end, audio_path, audio_only=False, bitrate=800_000)
            except BrowserError as exc:
                plan.warnings.append(f"Capture audio impossible ({start:.0f} s) : {exc}")
                continue
            candidate_spans.append((start, end))
            try:
                segments.extend(
                    transcribe_media(
                        audio_path,
                        model_name=opts.whisper_model,
                        language=opts.language or (settings.language if settings.language != "fr" else None),
                        offset=start,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                plan.warnings.append(f"Transcription impossible ({start:.0f} s) : {exc}")

        transcript = Transcript(segments=sorted(segments, key=lambda s: s.start), source=url)
        # Le transcript candidat est conservé : la sélection peut être refaite
        # (meilleur modèle, consignes différentes) sans re-capturer la vidéo.
        candidates_path = out_dir / "candidates.srt"
        candidates_path.write_text(transcript.to_srt(), encoding="utf-8")
        spans_path = out_dir / "candidates.json"
        spans_path.write_text(
            json.dumps(
                {
                    "spans": [
                        {"index": index, "start": start, "end": end,
                         "fragment": f"cand_{index:02d}.webm"}
                        for index, (start, end) in enumerate(candidate_spans, start=1)
                    ],
                    "duration": duration,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  transcript candidat : {candidates_path}", flush=True)
        if not transcript.segments:
            plan.warnings.append("Aucune transcription obtenue : aucun extrait ne peut être proposé.")
            plan.mode = "browser"
            return plan

        # --- Étape 4 : sélection par l'agent -------------------------------
        # Le chat replay donne à l'IA le contexte sémantique de chaque fenêtre
        # (ce que le public a réagi) : les titres et hooks en profitent.
        chat_context = build_chat_context(chat_messages, candidate_spans) if chat_messages else ""
        instruction = instruction or ""
        if chat_context:
            instruction = (
                f"{instruction}\n\n{chat_context}\n\n"
                "Tiens compte de l'activité du chat : une fenêtre très commentée "
                "est généralement un moment fort."
            ).strip()

        proposals = []
        try:
            from .llm import run_agent_chunked

            proposals, chunks = run_agent_chunked(
                transcript,
                settings,
                duration=duration,
                extra_instruction=instruction,
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
            # Réutilisation possible d'un fragment déjà capturé (le clip est
            # entièrement contenu dans une fenêtre candidate) : pas de re-capture.
            reusable = None
            for index, (cand_start, cand_end) in enumerate(candidate_spans, start=1):
                if clip.start >= cand_start and clip.end <= cand_end:
                    reusable = (work_dir / f"cand_{index:02d}.webm", cand_start)
                    break

            if reusable is not None:
                fragment, fragment_start = reusable
                offset = clip.start - fragment_start
                print(f"→ extrait #{clip.index} : fragment déjà capturé (offset {offset:.1f} s)", flush=True)
            else:
                start = max(0.0, clip.start - opts.padding)
                end = min(duration, clip.end + opts.padding)
                fragment = work_dir / f"clip_{clip.index:02d}.webm"
                print(f"→ capture finale #{clip.index} ({start:.0f}→{end:.0f} s)", flush=True)
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
            face_box = None
            if style_used.facecam_enabled:
                face_box = _detect_face(fragment, clip.duration + 2 * opts.padding)
                if face_box is None:
                    plan.warnings.append(f"Visage non détecté pour l'extrait #{clip.index} : rendu sans face cam.")
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
                    face_box=face_box,
                )
            except FFmpegError as exc:
                plan.warnings.append(f"Rendu de l'extrait #{clip.index} impossible : {exc}")
                out_path.unlink(missing_ok=True)   # fichier vide laissé par ffmpeg
                continue
            clip.path = str(out_path)
            rendered.append(str(out_path))
            # Le fragment est conservé : il permet de re-rendre sans re-capturer.
            ass_path.unlink(missing_ok=True)

    if len(rendered) > 1:
        try:
            concat_clips(rendered, out_dir / "best_of.mp4", settings=settings)
        except FFmpegError as exc:
            plan.warnings.append(f"Concaténation impossible : {exc}")

    return plan


def _load_candidate_spans(fragments: Path) -> list[dict]:
    """Charge les fenêtres candidates (candidates.json) si elles existent."""
    for candidate in (fragments / "candidates.json", fragments.parent / "candidates.json"):
        if candidate.exists():
            try:
                # utf-8-sig : tolère le BOM des fichiers écrits par PowerShell
                data = json.loads(candidate.read_text(encoding="utf-8-sig"))
                return list(data.get("spans", []))
            except (OSError, json.JSONDecodeError):
                return []
    return []


def _detect_face(fragment: Path, duration: float):
    """Cherche le visage du streamer dans le fragment (boîte élargie, carrée, bornée)."""
    try:
        from .facecam import detect_face_in_video

        box = detect_face_in_video(fragment, samples=8, duration=max(10.0, duration))
        if box is None:
            return None
        # Les dimensions de la frame sont connues (le lecteur peut changer de
        # qualité en cours de stream) : la boîte est bornée sur la frame réelle.
        return box.padded(0.6).square().clamped(box.frame_width, box.frame_height)
    except Exception:  # noqa: BLE001 - la face cam est optionnelle
        return None


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:48].strip("_") or "extrait"


def finalize_from_fragments(
    plan: Plan,
    fragments_dir: str | Path,
    settings: Settings,
    *,
    transcript: Transcript | None = None,
    output_dir: str | Path | None = None,
    padding: float = 1.5,
    style: ClipStyle | None = None,
    language: str | None = None,
) -> Plan:
    """Re-rend les clips à partir des fragments déjà capturés (pas de re-capture).

    Utile pour changer de style, corriger le hook ou les sous-titres sans
    retélécharger quoi que ce soit.
    """
    out_dir = Path(output_dir or settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fragments = Path(fragments_dir)
    style = style or get_style(settings.style)
    plan.style = style.name

    rendered: list[str] = []
    spans = _load_candidate_spans(fragments)
    if os.getenv("CLIPAGENT_DEBUG"):
        print(f"[debug] fragments={fragments} spans={len(spans)}", flush=True)
    for clip in plan.clips:
        fragment = fragments / f"clip_{clip.index:02d}.webm"
        offset = max(0.0, padding)

        if not fragment.exists() and spans:
            # Le clip peut être contenu dans une fenêtre candidate déjà capturée.
            for span in spans:
                if clip.start >= span["start"] and clip.end <= span["end"]:
                    candidate = fragments / span["fragment"]
                    if candidate.exists():
                        fragment = candidate
                        offset = clip.start - span["start"]
                        break
            if os.getenv("CLIPAGENT_DEBUG"):
                print(f"[debug] clip #{clip.index} {clip.start}-{clip.end} -> {fragment}", flush=True)

        if not fragment.exists():
            candidates = sorted(fragments.glob(f"clip_{clip.index:02d}.webm"))
            if not candidates:
                plan.warnings.append(f"Fragment manquant pour l'extrait #{clip.index} ({fragment}).")
                continue
            fragment = candidates[0]

        try:
            clip_segments = transcribe_media(
                fragment,
                model_name="tiny",
                language=language,
            )
        except Exception as exc:  # noqa: BLE001 - le clip reste rendu, sans sous-titres
            plan.warnings.append(
                f"Transcription impossible pour l'extrait #{clip.index} ({fragment.name}) : "
                f"{exc.__class__.__name__}"
            )
            clip_segments = []
        clip_transcript = Transcript(segments=clip_segments, source=str(fragment))

        style_used = style or get_style(settings.style)
        face_box = None
        if style_used.facecam_enabled:
            face_box = _detect_face(fragment, clip.duration)
            if face_box is None:
                plan.warnings.append(f"Visage non détecté pour l'extrait #{clip.index} : rendu sans face cam.")

        hook_text = ""
        if style_used.hook_enabled:
            hook_text = resolve_hook(
                clip,
                list(clip_transcript.segments),
                max_chars=style_used.hook_max_chars,
                uppercase=style_used.hook_uppercase,
            )
        clip.hook = hook_text

        ass_path = fragments / f"clip_{clip.index:02d}.ass"
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
                face_box=face_box,
            )
        except FFmpegError as exc:
            plan.warnings.append(f"Rendu de l'extrait #{clip.index} impossible : {exc}")
            out_path.unlink(missing_ok=True)
            continue
        clip.path = str(out_path)
        rendered.append(str(out_path))

    if len(rendered) > 1:
        try:
            concat_clips(rendered, out_dir / "best_of.mp4", settings=settings)
        except FFmpegError as exc:
            plan.warnings.append(f"Concaténation impossible : {exc}")
    return plan
