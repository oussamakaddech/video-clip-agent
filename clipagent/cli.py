"""Interface en ligne de commande de l'agent de clipping vidéo.

Ce module ne contient que l'analyse des arguments et le dispatch ; les
implémentations des commandes vivent dans ``clipagent.commands``.
"""

from __future__ import annotations

import argparse
import sys

from .commands import COMMANDS
from .config import PROFILES
from .styles import STYLES


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
        p.add_argument("--cookies-from-browser", help="chrome|firefox|edge : cookies pour les VOD protégées")
        p.add_argument("--profile", choices=sorted(PROFILES), help="Préréglage (livestream pour les VOD longues)")
        p.add_argument("--style", choices=sorted(STYLES), help="Style visuel des extraits (tiktok, arabic…)")
        p.add_argument("--language", help="Langue du contenu (fr, ar, en…) : pilote le prompt et le style")
        p.add_argument("--no-hook", action="store_true", help="Ne pas incruster l'accroche TikTok")
        p.add_argument("--hook-duration", type=float, help="Durée de l'accroche en secondes (défaut: 3)")
        p.add_argument("--max-chunks", type=int, help="Nombre maximum de portions de transcript analysées")
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
        p.add_argument("--num-clips", type=int, help="Nombre d'extraits")
        p.add_argument("--min-clip", type=float, help="Durée minimale en secondes")
        p.add_argument("--max-clip", type=float, help="Durée maximale en secondes")
        p.add_argument("--aspect", choices=["9:16", "16:9", "1:1"], help="Format de sortie")
        p.add_argument("--ffmpeg", help="Chemin de l'exécutable ffmpeg")
        p.add_argument("--output", default="output", help="Dossier de sortie")
        p.add_argument("--instruction", help="Consigne complémentaire pour l'agent")
        p.add_argument("--no-subtitles", action="store_true", help="Ne pas incruster les sous-titres")
        p.add_argument("--logo", help="Image de logo (PNG/JPG) posée en haut à gauche")
        p.add_argument("--logo-size", type=int, help="Largeur du logo en pixels (défaut: 120)")

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
    p_fetch.add_argument(
        "--audio-only",
        action="store_true",
        help="Ne télécharger que l'audio (≈ 100 Mo pour 4 h) : idéal pour analyser sans bande passante",
    )
    p_fetch.add_argument(
        "--sections",
        help="Plages à télécharger uniquement, ex « 120-180,900-940 » (secondes)",
    )

    p_browse = sub.add_parser(
        "browse",
        help="Analyser une VOD dans le navigateur (Edge/Chrome) SANS la télécharger",
    )
    p_browse.add_argument("--url", required=True, help="URL de la VOD (Kick, YouTube…)")
    p_browse.add_argument("--output", default="output", help="Dossier de sortie")
    p_browse.add_argument("--step", type=float, default=60.0, help="Pas du storyboard en secondes")
    p_browse.add_argument("--candidates", type=int, default=8, help="Nombre de fenêtres candidates")
    p_browse.add_argument("--window", type=float, default=80.0, help="Durée d'une fenêtre candidate (s)")
    p_browse.add_argument("--num-clips", type=int, help="Nombre d'extraits finaux")
    p_browse.add_argument("--min-clip", type=float, default=45.0, help="Durée minimale d'un extrait")
    p_browse.add_argument("--max-clip", type=float, default=75.0, help="Durée maximale d'un extrait")
    p_browse.add_argument("--whisper", default="tiny", help="Modèle Whisper local (tiny, base, small)")
    p_browse.add_argument("--language", help="Langue de la VOD (auto si absent)")
    p_browse.add_argument("--channel", default="msedge", choices=["msedge", "chrome", "chromium", "auto"])
    p_browse.add_argument("--headed", action="store_true", help="Afficher le navigateur (débogage)")
    p_browse.add_argument("--style", choices=sorted(STYLES), help="Style visuel des extraits")
    p_browse.add_argument("--instruction", help="Consigne complémentaire pour l'agent")
    p_browse.add_argument(
        "--no-chat",
        action="store_true",
        help="Ignorer le chat replay de la VOD (désactive le classement par activité)",
    )

    p_final = sub.add_parser(
        "finalize",
        help="Re-rendre les clips depuis les fragments déjà capturés (mode navigateur)",
    )
    p_final.add_argument("--plan", required=True, help="Plan JSON (clips_plan.json)")
    p_final.add_argument("--fragments", required=True, help="Dossier des fragments capturés")
    p_final.add_argument("--output", default="output", help="Dossier de sortie")
    p_final.add_argument("--transcript", help="Transcript SRT/VTT (sinon, sous-titres déduits du fragment)")
    p_final.add_argument("--style", choices=sorted(STYLES), help="Style visuel")
    p_final.add_argument("--language", help="Langue de la transcription (ex: en)")
    p_final.add_argument(
        "--whisper",
        default="small",
        help="Modèle Whisper pour les sous-titres (tiny, base, small, medium) — small = meilleur compromis",
    )
    p_final.add_argument("--padding", type=float, default=1.5, help="Marge avant/après (s)")
    p_final.add_argument(
        "--url",
        help="URL de la VOD : les clips non couverts par un fragment sont capturés à la demande",
    )

    return parser


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
    except KeyboardInterrupt:  # pragma: no cover
        print("Interrompu.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - l'CLI ne doit jamais sortir avec une trace brute
        from .ffmpeg import FFmpegError

        if isinstance(exc, FFmpegError):
            print(f"Erreur ffmpeg : {exc}", file=sys.stderr)
        else:
            print(f"Erreur : {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
