"""Implémentation des commandes de la CLI (séparée du parseur d'arguments)."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import Settings
from .ffmpeg import FFmpegError, probe, resolve_ffmpeg
from .hooks import is_rtl_language
from .models import Clip, Segment
from .pipeline import Plan, plan_clips, render_plan, save_report
from .styles import style_for_language
from .transcript import Transcript, load_transcript


def settings_from_args(args: argparse.Namespace) -> Settings:
    """Construit les réglages : arguments de la CLI > environnement > profil."""
    overrides = {
        "model": getattr(args, "model", None),
        "api_key": getattr(args, "api_key", None),
        "base_url": getattr(args, "base_url", None),
        "chat_completions": True if getattr(args, "chat_completions", False) else None,
        "strict_tools": False if getattr(args, "non_strict_tools", False) else None,
        "profile": getattr(args, "profile", None),
        "style": getattr(args, "style", None),
        "language": getattr(args, "language", None),
        "hook_enabled": False if getattr(args, "no_hook", False) else None,
        "hook_duration": getattr(args, "hook_duration", None),
        "max_chunks": getattr(args, "max_chunks", None),
        "min_clip_seconds": getattr(args, "min_clip", None),
        "max_clip_seconds": getattr(args, "max_clip", None),
        "num_clips": getattr(args, "num_clips", None),
        "aspect_ratio": getattr(args, "aspect", None),
        "ffmpeg_binary": getattr(args, "ffmpeg", None),
        "output_dir": Path(args.output) if getattr(args, "output", None) else None,
        "burn_subtitles": False if getattr(args, "no_subtitles", False) else None,
        "instruction": getattr(args, "instruction", None),
    }
    settings = Settings.from_env(**{k: v for k, v in overrides.items() if v is not None})
    # Langue RTL sans style explicite → style arabe (police et alignement adaptés).
    if not getattr(args, "style", None) and is_rtl_language(settings.language):
        settings.style = style_for_language(settings.language).name
    return settings


def plan_from_json(path: str | Path) -> Plan:
    """Relit un plan JSON (les avertissements du run précédent ne sont pas rejoués)."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    plan = Plan(
        video=data.get("video"),
        transcript_source=data.get("transcript"),
        duration=float(data.get("duration", 0.0) or 0.0),
        mode=data.get("mode", "llm"),
        model=data.get("model"),
        style=data.get("style", "default"),
        warnings=[],
    )
    for item in data.get("clips", []) or []:
        plan.clips.append(
            Clip(
                index=int(item.get("index", 0)),
                start=float(item.get("start", 0.0)),
                end=float(item.get("end", 0.0)),
                title=str(item.get("title", "Extrait")),
                reason=str(item.get("reason", "")),
                score=float(item.get("score", 0.5)),
                tags=list(item.get("tags", []) or []),
                hook=str(item.get("hook", "") or ""),
            )
        )
    return plan


def parse_sections(value: str | None) -> list[tuple[float, float]]:
    """Parse « 120-180,900-940 » → [(120.0, 180.0), (900.0, 940.0)]."""
    if not value:
        return []
    sections: list[tuple[float, float]] = []
    for chunk in value.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" not in chunk:
            raise ValueError(f"Plage invalide : {chunk!r} (attendu : debut-fin)")
        start, end = chunk.split("-", 1)
        sections.append((float(start), float(end)))
    return sections


def resolve_video(args: argparse.Namespace, settings: Settings) -> str | None:
    """Vidéo à traiter : fichier local, ou VOD téléchargée à la demande."""
    url = getattr(args, "url", None)
    if url:
        from .download import download

        print(f"Téléchargement de {url} …")
        path = download(url, settings=settings, out_dir=settings.download_dir)
        print(f"VOD téléchargée : {path}")
        return str(path)
    return getattr(args, "video", None)


# --- Commandes -------------------------------------------------------------
def cmd_plan(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    transcript = load_transcript(args.transcript)
    video = resolve_video(args, settings)
    plan = plan_clips(video, transcript, settings, instruction=args.instruction or "")
    json_path, md_path = save_report(plan, args.output)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(plan.clips)} extrait(s) sélectionné(s) — mode: {plan.mode}")
    for clip in plan.clips:
        print(f"  #{clip.index} {clip.start:7.1f}s → {clip.end:7.1f}s  {clip.title}")
    for warning in plan.warnings:
        print(f"  ! {warning}")
    print(f"Rapport : {json_path} / {md_path}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    plan = plan_from_json(args.plan)
    transcript = load_transcript(args.transcript) if getattr(args, "transcript", None) else None

    # Mode « connexion faible » : on ne télécharge que les fragments retenus.
    url = getattr(args, "url", None)
    if url and not getattr(args, "video", None):
        from .pipeline import render_plan_remote

        print("Mode distant : téléchargement des seuls extraits retenus…")
        plan = render_plan_remote(
            plan,
            url,
            settings,
            transcript=transcript,
            output_dir=args.output,
            make_concat=not args.no_concat,
            cookies_from_browser=getattr(args, "cookies_from_browser", None),
        )
    else:
        video = resolve_video(args, settings)
        plan = render_plan(
            plan,
            video,
            settings,
            transcript=transcript,
            output_dir=args.output,
            make_concat=not args.no_concat,
        )
    save_report(plan, args.output)
    print(f"{len([c for c in plan.clips if c.path])} extrait(s) rendu(s) dans {args.output}")
    for warning in plan.warnings:
        print(f"  ! {warning}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    settings = settings_from_args(args)
    from .pipeline import run_pipeline

    video = resolve_video(args, settings)
    plan = run_pipeline(
        video,
        args.transcript,
        settings,
        instruction=args.instruction or "",
        output_dir=args.output,
        render=not args.dry_run,
        make_concat=not args.no_concat,
    )
    print(f"{len(plan.clips)} extrait(s) — mode: {plan.mode}")
    for clip in plan.clips:
        state = Path(clip.path).name if clip.path else "(non rendu)"
        print(f"  #{clip.index} {clip.start:7.1f}s → {clip.end:7.1f}s  {clip.title}  → {state}")
    for warning in plan.warnings:
        print(f"  ! {warning}")
    print(f"Rapport : {Path(args.output) / 'clips_plan.md'}")
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "Transcription automatique indisponible : installez `faster-whisper` "
            "(pip install faster-whisper) ou fournissez un fichier SRT/VTT.",
            file=sys.stderr,
        )
        return 2

    # Contrôle préalable : une vidéo sans piste audio ne peut pas être transcrite.
    try:
        media = probe(args.video)
        if not media.has_audio:
            print(
                f"Cette vidéo n'a pas de piste audio ({media.aspect_ratio}, "
                f"{media.duration:.0f} s) : rien à transcrire.\n"
                "Les enregistrements d'écran (Playwright/observatoire) sont muets : "
                "fournissez une vidéo avec du son, ou un fichier SRT/VTT déjà prêt.",
                file=sys.stderr,
            )
            return 3
    except FFmpegError:
        pass

    device = args.device
    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    elif device == "cuda" and not _cuda_available():
        print("CUDA indisponible (cublas absent) → repli CPU.", file=sys.stderr)
        device = "cpu"

    try:
        model = WhisperModel(args.model, device=device, compute_type=args.compute_type)
    except Exception as exc:  # noqa: BLE001
        print(f"Chargement du modèle impossible : {exc}", file=sys.stderr)
        return 4

    print(f"Transcription en cours (modèle {args.model}, {device}) …", file=sys.stderr)
    try:
        segments, info = model.transcribe(args.video, language=args.language, vad_filter=True)
        collected = [
            Segment(index=i, start=s.start, end=s.end, text=s.text.strip())
            for i, s in enumerate(segments, start=1)
        ]
    except RuntimeError as exc:
        if device != "cpu":
            print(f"Échec GPU ({exc}) → nouvelle tentative sur CPU…", file=sys.stderr)
            model = WhisperModel(args.model, device="cpu", compute_type="int8")
            segments, info = model.transcribe(args.video, language=args.language, vad_filter=True)
            collected = [
                Segment(index=i, start=s.start, end=s.end, text=s.text.strip())
                for i, s in enumerate(segments, start=1)
            ]
        else:
            print(f"Transcription impossible : {exc}", file=sys.stderr)
            return 4

    transcript = Transcript(segments=collected, source=str(args.video))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(transcript.to_srt(), encoding="utf-8")
    print(f"Transcription écrite dans {out} ({len(collected)} segments, langue : {info.language})")
    return 0


def _cuda_available() -> bool:
    """Vérifie que les bibliothèques CUDA nécessaires à ctranslate2 sont chargeables."""
    if os.name != "nt":
        try:
            import ctranslate2

            return ctranslate2.get_cuda_device_count() > 0
        except Exception:  # pragma: no cover
            return False
    for dll in ("cublas64_12.dll", "cublas64_11.dll", "cublas64_10.dll"):
        try:
            ctypes.WinDLL(dll)
            return True
        except OSError:
            continue
    return False


def cmd_info(args: argparse.Namespace) -> int:
    info = probe(args.video)
    print(json.dumps({
        "video": args.video,
        "duration": round(info.duration, 2),
        "resolution": info.aspect_ratio,
        "fps": round(info.fps, 3),
        "has_audio": info.has_audio,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnostic complet de l'environnement."""
    import platform

    print(f"Python        : {platform.python_version()} ({platform.system()})")
    try:
        ffmpeg = resolve_ffmpeg()
        version = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        print(f"ffmpeg        : OK — {version}")
    except Exception as exc:  # noqa: BLE001
        print(f"ffmpeg        : MANQUANT — {exc}")

    try:
        import importlib.util

        has_whisper = bool(importlib.util.find_spec("faster_whisper"))
        print(f"Whisper       : {'OK (faster-whisper installé)' if has_whisper else 'absent (optionnel)'}")
    except Exception:  # pragma: no cover
        print("Whisper       : inconnu")

    settings = settings_from_args(args)
    print(f"Modèle        : {settings.model}")
    print(f"Base URL      : {settings.base_url or 'https://api.openai.com/v1 (défaut)'}")
    print(f"Clé API       : {'présente' if settings.api_key else 'ABSENTE (mode heuristique)'}")

    if args.skip_llm:
        return 0
    if not settings.api_key:
        print("Test LLM      : ignoré (pas de clé)")
        return 0

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url or None,
            timeout=60.0,
        )
        response = client.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        print(f"Test LLM      : OK — {response.choices[0].message.content!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"Test LLM      : ECHEC — {exc.__class__.__name__}: {exc}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """Télécharge une VOD (complète, audio seul, ou seulement des fragments)."""
    from .download import download

    settings = settings_from_args(args)
    sections = parse_sections(getattr(args, "sections", None))
    path = download(
        args.url,
        settings=settings,
        out_dir=args.out,
        cookies_from_browser=args.cookies_from_browser,
        max_height=args.max_height,
        audio_only=getattr(args, "audio_only", False),
        sections=sections or None,
    )
    print(f"Téléchargement terminé : {path}")
    if getattr(args, "audio_only", False):
        print(f"Suite : clipagent transcribe --video \"{path}\" --output .\\vod.srt --model base")
    else:
        print(f"Suite : clipagent transcribe --video \"{path}\" --output .\\vod.srt --model small")
    return 0


def cmd_browse(args: argparse.Namespace) -> int:
    """Analyse une VOD dans le navigateur, sans la télécharger."""
    from .browser_pipeline import BrowserOptions, analyze_in_browser

    settings = settings_from_args(args)
    options = BrowserOptions(
        step=args.step,
        candidates=args.candidates,
        window=args.window,
        num_clips=args.num_clips or settings.num_clips,
        min_clip=args.min_clip or settings.min_clip_seconds,
        max_clip=args.max_clip or settings.max_clip_seconds,
        whisper_model=args.whisper,
        language=args.language,
        channel=args.channel,
        headless=not args.headed,
        style=args.style or settings.style,
        use_chat=not getattr(args, "no_chat", False),
    )
    started = time.time()
    plan = analyze_in_browser(
        args.url,
        settings,
        options,
        output_dir=args.output,
        instruction=getattr(args, "instruction", "") or "",
    )
    save_report(plan, args.output)
    print(f"\n{len([c for c in plan.clips if c.path])} extrait(s) en {(time.time()-started)/60:.1f} min")
    for clip in plan.clips:
        state = Path(clip.path).name if clip.path else "(non rendu)"
        print(f"  #{clip.index} {clip.start:8.1f}s → {clip.end:8.1f}s  {clip.title}  → {state}")
    for warning in plan.warnings:
        print(f"  ! {warning}")
    print(f"Rapport : {Path(args.output) / 'clips_plan.md'}")
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    """Re-rend les clips à partir des fragments déjà capturés (pas de re-capture)."""
    from .browser_pipeline import finalize_from_fragments

    settings = settings_from_args(args)
    plan = plan_from_json(args.plan)
    transcript = load_transcript(args.transcript) if getattr(args, "transcript", None) else None
    plan = finalize_from_fragments(
        plan,
        Path(args.fragments),
        settings,
        transcript=transcript,
        output_dir=args.output,
        padding=args.padding,
        language=args.language,
    )
    save_report(plan, args.output)
    print(f"{len([c for c in plan.clips if c.path])} extrait(s) re-rendu(s) dans {args.output}")
    for warning in plan.warnings:
        print(f"  ! {warning}")
    return 0


COMMANDS = {
    "plan": cmd_plan,
    "render": cmd_render,
    "run": cmd_run,
    "transcribe": cmd_transcribe,
    "info": cmd_info,
    "doctor": cmd_doctor,
    "fetch": cmd_fetch,
    "browse": cmd_browse,
    "finalize": cmd_finalize,
}
