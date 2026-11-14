"""Interface en ligne de commande de l'agent de clipping vidéo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .ffmpeg import FFmpegError, probe
from .models import Clip
from .pipeline import Plan, plan_clips, render_plan, save_report
from .transcript import load_transcript


def _settings_from_args(args: argparse.Namespace) -> Settings:
    overrides = {
        "model": args.model,
        "api_key": args.api_key,
        "base_url": args.base_url,
        "chat_completions": True if getattr(args, "chat_completions", False) else None,
        "strict_tools": False if getattr(args, "non_strict_tools", False) else None,
        "min_clip_seconds": args.min_clip,
        "max_clip_seconds": args.max_clip,
        "num_clips": args.num_clips,
        "aspect_ratio": args.aspect,
        "ffmpeg_binary": args.ffmpeg,
        "output_dir": Path(args.output) if args.output else None,
        "burn_subtitles": False if args.no_subtitles else None,
        "instruction": args.instruction,
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
        if needs_video:
            p.add_argument("--video", required=True, help="Chemin de la vidéo source")
        if needs_transcript:
            p.add_argument("--transcript", required=True, help="Transcription (SRT/VTT)")
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

    return parser


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


def cmd_plan(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    transcript = load_transcript(args.transcript)
    plan = plan_clips(getattr(args, "video", None), transcript, settings, instruction=args.instruction or "")
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

    plan = run_pipeline(
        args.video,
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
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    segments, info = model.transcribe(args.video, language=args.language, vad_filter=True)
    from .transcript import Transcript
    from .models import Segment

    transcript = Transcript(
        segments=[
            Segment(index=i, start=s.start, end=s.end, text=s.text.strip())
            for i, s in enumerate(segments, start=1)
        ],
        source=str(args.video),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(transcript.to_srt(), encoding="utf-8")
    print(f"Transcription écrite dans {out} (langue détectée : {info.language})")
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
