"""Interface en ligne de commande de l'agent de clipping vidéo."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

from .config import PROFILES, Settings
from .ffmpeg import FFmpegError, probe, resolve_ffmpeg
from .models import Clip, Segment
from .pipeline import Plan, plan_clips, render_plan, save_report
from .transcript import Transcript, load_transcript


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """Construit les réglages : arguments de la CLI > environnement > profil."""
    overrides = {
        "model": getattr(args, "model", None),
        "api_key": getattr(args, "api_key", None),
        "base_url": getattr(args, "base_url", None),
        "chat_completions": True if getattr(args, "chat_completions", False) else None,
        "strict_tools": False if getattr(args, "non_strict_tools", False) else None,
        "profile": getattr(args, "profile", None),
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
    return Settings.from_env(**{k: v for k, v in overrides.items() if v is not None})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipagent",
        description="Agent IA de clipping vidéo : analyse une transcription, "
        "sélectionne les moments forts et rend des extraits verticaux.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, *, needs_video: bool = True, needs_transcript: bool = True):
        p.add_argument(
            "--video",
            required=needs_video,
            help="Chemin de la vidéo source (optionnel pour `plan` : sert à connaître la durée)",
        )
        if needs_transcript:
            p.add_argument("--transcript", required=True, help="Transcription (SRT/VTT)")
        p.add_argument("--url", help="URL de la VOD (Kick/YouTube/Twitch) : téléchargée automatiquement")
        p.add_argument("--profile", choices=sorted(PROFILES), help="Préréglage (livestream pour les VOD longues)")
        p.add_argument("--max-chunks", type=int, help="Nombre maximum de portions de transcript analysées")
        p.add_argument("--output", default="output", help="Dossier de sortie")
        p.add_argument("--model", help="Modèle LLM (défaut: gpt-4o-mini)")
        p.add_argument("--api-key", help="Clé API (défaut: OPENAI_API_KEY)")
        p.add_argument(
            "--base-url",
            help="Endpoint compatible OpenAI (NVIDIA: https://integrate.api.nvidia.com/v1, "
            "Ollama: http://localhost:11434/v1, vLLM: http://localhost:8000/v1)",
        )
        p.add_argument(
            "--chat-completions",
            action="store_true",
            help="Forcer l'API Chat Completions (obligatoire pour les endpoints sans /responses)",
        )
        p.add_argument(
            "--non-strict-tools",
            action="store_true",
            help="Ne pas envoyer le schéma JSON strict des outils (certains endpoints le refusent)",
        )
        p.add_argument("--num-clips", type=int, help="Nombre d'extraits (défaut: 5)")
        p.add_argument("--min-clip", type=float, help="Durée minimale en secondes")
        p.add_argument("--max-clip", type=float, help="Durée maximale en secondes")
        p.add_argument("--aspect", choices=["9:16", "16:9", "1:1"], help="Format de sortie")
        p.add_argument("--ffmpeg", help="Chemin de l'exécutable ffmpeg")
        p.add_argument("--instruction", help="Consigne complémentaire pour l'agent")
        p.add_argument("--no-subtitles", action="store_true", help="Ne pas incruster les sous-titres")

    p_plan = sub.add_parser("plan", help="Sélectionner les extraits sans rendre")
    add_common(p_plan, needs_video=False)
    p_plan.add_argument("--json", dest="json_out", help="Écrire le plan dans ce fichier JSON")

    p_render = sub.add_parser("render", help="Rendre un plan déjà construit")
    add_common(p_render, needs_transcript=False)
    p_render.add_argument("--transcript", help="Transcription (SRT/VTT) pour incruster les sous-titres")
    p_render.add_argument("--plan", required=True, help="Fichier JSON du plan")
    p_render.add_argument("--no-concat", action="store_true", help="Ne pas produire la vidéo best-of")

    p_run = sub.add_parser("run", help="Analyse + rendu en une commande")
    add_common(p_run)
    p_run.add_argument("--no-concat", action="store_true", help="Ne pas produire la vidéo best-of")
    p_run.add_argument("--dry-run", action="store_true", help="Ne rendre aucun fichier vidéo")

    p_trans = sub.add_parser("transcribe", help="Transcrire une vidéo (faster-whisper, optionnel)")
    p_trans.add_argument("--video", required=True)
    p_trans.add_argument("--output", default="transcript.srt")
    p_trans.add_argument("--model", default="base", help="Modèle Whisper (tiny/base/small/medium/large-v3)")
    p_trans.add_argument("--language", default="fr")
    p_trans.add_argument("--device", default="auto", help="auto | cpu | cuda")
    p_trans.add_argument("--compute-type", default="int8", help="int8 | int8_float16 | float16 | float32")

    p_info = sub.add_parser("info", help="Afficher les métadonnées d'une vidéo")
    p_info.add_argument("--video", required=True)

    p_doc = sub.add_parser("doctor", help="Vérifier l'environnement (ffmpeg, Whisper, modèle LLM)")
    p_doc.add_argument("--skip-llm", action="store_true", help="Ne pas tester l'endpoint LLM")

    p_fetch = sub.add_parser("fetch", help="Télécharger une VOD (Kick, YouTube, Twitch…)")
    p_fetch.add_argument("--url", required=True, help="URL de la VOD")
    p_fetch.add_argument("--out", default="downloads", help="Dossier de destination")
    p_fetch.add_argument("--cookies-from-browser", help="chrome|firefox|edge : cookies du navigateur")
    p_fetch.add_argument("--max-height", type=int, default=1080, help="Hauteur maximale (défaut: 1080)")

    return parser


def cmd_fetch(args: argparse.Namespace) -> int:
    """Télécharge une VOD et affiche le chemin du fichier."""
    from .download import download

    settings = _settings_from_args(args)
    path = download(
        args.url,
        settings=settings,
        out_dir=args.out,
        cookies_from_browser=args.cookies_from_browser,
        max_height=args.max_height,
    )
    print(f"VOD téléchargée : {path}")
    print(f"Suite : clipagent transcribe --video \"{path}\" --output .\\vod.srt --model small")
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

        print(f"Whisper       : {'OK (faster-whisper installé)' if importlib.util.find_spec('faster_whisper') else 'absent (optionnel)'}")
    except Exception:  # pragma: no cover
        print("Whisper       : inconnu")

    settings = _settings_from_args(args)
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


def _plan_from_json(path: str | Path) -> Plan:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = Plan(
        video=data.get("video"),
        transcript_source=data.get("transcript"),
        duration=float(data.get("duration", 0.0) or 0.0),
        mode=data.get("mode", "llm"),
        model=data.get("model"),
        warnings=list(data.get("warnings", []) or []),
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
            )
        )
    return plan


def _resolve_video(args: argparse.Namespace, settings: Settings) -> str | None:
    """Retourne la vidéo à traiter : fichier local, ou VOD téléchargée à la demande."""
    url = getattr(args, "url", None)
    if url:
        from .download import download

        print(f"Téléchargement de {url} …")
        path = download(url, settings=settings, out_dir=settings.download_dir)
        print(f"VOD téléchargée : {path}")
        return str(path)
    return getattr(args, "video", None)


def cmd_plan(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    transcript = load_transcript(args.transcript)
    video = _resolve_video(args, settings)
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
    settings = _settings_from_args(args)
    plan = _plan_from_json(args.plan)
    transcript = load_transcript(args.transcript) if getattr(args, "transcript", None) else None
    plan = render_plan(
        plan,
        args.video,
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
    settings = _settings_from_args(args)
    from .pipeline import run_pipeline

    video = _resolve_video(args, settings)
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

    model = None
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


COMMANDS = {
    "plan": cmd_plan,
    "render": cmd_render,
    "run": cmd_run,
    "transcribe": cmd_transcribe,
    "info": cmd_info,
    "doctor": cmd_doctor,
    "fetch": cmd_fetch,
}


def main(argv: list[str] | None = None) -> int:
    # La console Windows est souvent en cp1252 : on force l'UTF-8 pour les libellés.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - dépend du terminal
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except FFmpegError as exc:
        print(f"Erreur ffmpeg : {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("Interrompu.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
