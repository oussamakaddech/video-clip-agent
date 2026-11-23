"""Pont GTA 6 : pilote les scripts du plugin gtavi-claudecode depuis ce dépôt.

Le plugin amont (MIT, https://github.com/Bodila51/gtavi-claudecode) est copié
tel quel dans ``integrations/gtavi/``. Ce fichier ne fait que :

1. préparer l'environnement local (binaire ``ffmpeg`` nommé correctement dans le
   ``PATH``, espace de travail ``output/gta6/``) ;
2. exposer les commandes amont avec des chemins déjà réglés ;
3. ajouter ``run`` : moments -> accroches -> rendu -> contrôle, avec un rapport
   prêt à publier (fichier, accroche, crédit, légende, résultat du contrôle).

Analyse complète : ``docs/gtavi-claudecode-analyse.md``.

Exemples :
    python scripts/gta6.py setup
    python scripts/gta6.py streams --query "gta 6"
    python scripts/gta6.py trends --hours 24
    python scripts/gta6.py moments <url|fichier> --top 8 --max-minutes 25
    python scripts/gta6.py cut <job> --pick 1 --layout blur --hook "..."
    python scripts/gta6.py check <clip.mp4>
    python scripts/gta6.py run <url> --clips 3 --max-minutes 25
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations" / "gtavi"
SCRIPTS = INTEGRATION / "scripts"
WORKSPACE = ROOT / "output" / "gta6"

sys.path.insert(0, str(SCRIPTS))

HYPE = re.compile(
    r"\b(no way|oh my god|omg|what|wait|bro|let'?s go|holy|insane|crazy|yo+|wtf|dude|"
    r"look at|nah|run|go go|shoot|police|cop|crash|money|car)\b",
    re.IGNORECASE,
)
FILLERS = re.compile(
    r"^(?:so|and|but|yeah|yeah so|okay|ok|well|i mean|like|right|alright|um+|uh+)\b[\s,]*",
    re.IGNORECASE,
)
STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "is", "it", "in", "i", "you", "that", "this",
    "on", "for", "with", "was", "are", "be", "so", "but", "not", "my", "me", "we", "he",
    "she", "they", "what", "just", "like", "at", "as", "if", "do", "get", "got", "him",
    "her", "them", "his", "hers", "there", "here", "then", "now", "then", "oh", "yeah",
}


# --------------------------------------------------------------------------- #
# Environnement
# --------------------------------------------------------------------------- #
def prepare_environment() -> dict:
    """Prépare le PATH + l'espace de travail, et renvoie un diagnostic."""
    import compat

    for folder in (WORKSPACE, WORKSPACE / "jobs"):
        folder.mkdir(parents=True, exist_ok=True)
    bin_dir = compat.ensure_path(WORKSPACE / "bin")
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("CLIP_DESK_HOME", str(WORKSPACE))
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    return {
        "workspace": str(WORKSPACE),
        "ffmpeg": compat.resolve_tool("ffmpeg") or "",
        "ffprobe": compat.resolve_tool("ffprobe") or "absent (repli PyAV)",
        "yt_dlp": _has_module("yt_dlp"),
        "faster_whisper": _has_module("faster_whisper"),
    }


def _has_module(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def run_script(name: str, args: list[str]) -> int:
    """Exécute un script amont dans un processus séparé, avec l'environnement prêt."""
    command = [sys.executable, str(SCRIPTS / name), *args]
    return subprocess.call(command, env=os.environ.copy(), cwd=str(WORKSPACE))


def job_path(raw: str) -> Path:
    """Accepte un chemin absolu, relatif au dépôt, ou relatif à l'espace de travail."""
    candidate = Path(raw)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    for base in (Path.cwd(), WORKSPACE, ROOT):
        path = base / raw
        if path.exists():
            return path
    return candidate


# --------------------------------------------------------------------------- #
# Accroches (heuristique, sans LLM)
# --------------------------------------------------------------------------- #
def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split()))
    return [p.strip(" .,-–—") for p in parts if p.strip(" .,-–—")]


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'’]+", text, re.UNICODE)


def _trim(text: str, max_words: int, max_chars: int = 52) -> str:
    words = _words(text)
    if not words:
        return ""
    kept: list[str] = []
    for word in words[:max_words]:
        candidate = " ".join([*kept, word])
        if len(candidate) > max_chars and kept:
            break
        kept.append(word)
    while len(kept) > 2 and kept[-1].lower() in STOPWORDS:
        kept.pop()  # une accroche ne finit pas sur « is », « the »…
    hook = " ".join(kept).strip(" .,-–—")
    if len(hook) > max_chars:
        hook = hook[: max_chars - 1].rstrip() + "…"
    return hook[:1].upper() + hook[1:] if hook else ""


def propose_hooks(text: str, *, max_options: int = 3) -> list[str]:
    """Trois accroches candidates tirées de la transcription de l'extrait.

    Heuristique assumée (pas de LLM ici) : ouverture réelle du clip, phrase la
    plus « énergique », version courte par mots-clés. À relire avant publication.
    """
    sentences = [FILLERS.sub("", s).strip(" .,-–—") for s in _sentences(text)]
    sentences = [s for s in sentences if _words(s)]
    if not sentences:
        return []
    options: list[str] = [_trim(sentences[0], 9)]
    if len(sentences) > 1:
        best = max(sentences[1:], key=lambda s: len(HYPE.findall(s)))
        if len(HYPE.findall(best)):
            options.append(_trim(best, 9))
    keywords = [
        word for word in _words(" ".join(sentences))
        if word.lower() not in STOPWORDS and len(word) > 2
    ]
    if keywords:
        options.append(_trim(" ".join(keywords[:5]), 5))
    seen: list[str] = []
    for option in options:
        if option and option.lower() not in {s.lower() for s in seen}:
            seen.append(option)
    return seen[:max_options]


def caption_for(info: dict, hook: str, *, platform: str = "tiktok") -> str:
    """Légende prête à publier, avec le crédit du créateur (exigence amont)."""
    channel = info.get("channel") or info.get("uploader") or "l'auteur de la vidéo"
    title = (info.get("title") or "").split("|")[0].strip()
    credit = f"Clip : {channel} — {info.get('webpage_url') or 'source dans le rapport'}"
    body = hook.strip().rstrip(".")
    if platform == "x":
        return f"{body}.\n{credit}"
    if platform == "instagram":
        return f"{body}.\n\n{credit}\n#GTA6 #GTAVI #gaming #RockstarGames"
    return f"{body}.\n\n{credit}\n#GTA6 #GTAVI #gaming #shorts"


# --------------------------------------------------------------------------- #
# Commandes
# --------------------------------------------------------------------------- #
def cmd_setup(args: argparse.Namespace) -> int:
    diag = prepare_environment()
    print("Espace de travail :", diag["workspace"])
    print("ffmpeg            :", diag["ffmpeg"] or "ABSENT")
    print("ffprobe           :", diag["ffprobe"])
    print("yt-dlp            :", "ok" if diag["yt_dlp"] else "ABSENT (pip install yt-dlp)")
    print("faster-whisper    :", "ok" if diag["faster_whisper"] else "ABSENT (pip install faster-whisper)")
    ok = bool(diag["ffmpeg"]) and diag["yt_dlp"] and diag["faster_whisper"]
    print("etat              :", "pret" if ok else "incomplet")
    return 0 if ok else 1


def cmd_streams(args: argparse.Namespace) -> int:
    prepare_environment()
    forward = ["--query", args.query, "--limit", str(args.limit)]
    forward += ["--out", str(WORKSPACE / "streams.md")]
    return run_script("streams.py", forward)


def cmd_trends(args: argparse.Namespace) -> int:
    prepare_environment()
    forward = ["--query", args.query, "--hours", str(args.hours), "--limit", str(args.limit)]
    forward += ["--out", str(WORKSPACE / "trends.md")]
    return run_script("trends.py", forward)


def cmd_moments(args: argparse.Namespace) -> int:
    prepare_environment()
    forward = [args.source, "--top", str(args.top), "--max-minutes", str(args.max_minutes)]
    if args.chat:
        forward += ["--chat", args.chat]
    return run_script("moments.py", forward)


def cmd_cut(args: argparse.Namespace) -> int:
    prepare_environment()
    forward = [str(job_path(args.job)), "--pick", str(args.pick), "--layout", args.layout]
    if args.hook:
        forward += ["--hook", args.hook]
    if args.cam:
        forward += ["--cam", args.cam]
    if args.title:
        forward += ["--title", args.title, "--title-style", args.title_style]
    if args.captions:
        forward += ["--captions", args.captions]
    if args.start is not None:
        forward += ["--start", str(args.start)]
    if args.end is not None:
        forward += ["--end", str(args.end)]
    return run_script("cut.py", forward)


def cmd_style(args: argparse.Namespace) -> int:
    """Rend un extrait avec le style GTA 6 (accroche animée, karaoké rose, étalonnage)."""
    prepare_environment()
    from gta6_style import render

    job = job_path(args.job)
    hook = args.hooks[0] if args.hooks else args.hook
    out = render(job, args.pick, hook, cta=args.cta, kicker=args.kicker,
                 layout=args.layout, start=args.start, end=args.end,
                 trim_bottom=getattr(args, "trim_bottom", 0.0),
                 cam=getattr(args, "cam", "auto"),
                 captions=getattr(args, "captions", "word") != "none")
    print(out)
    for index, alternative in enumerate(args.hooks[1:], 2):
        print(f"   variante d'accroche {index} : {alternative}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    prepare_environment()
    forward = [str(job_path(args.clip))]
    if args.campaign:
        forward += ["--campaign", args.campaign]
    if args.caption:
        forward += ["--caption", args.caption]
    return run_script("check.py", forward)


def cmd_plan(args: argparse.Namespace) -> int:
    """Affiche les candidats et les accroches proposées, sans rien rendre."""
    prepare_environment()
    job = job_path(args.job)
    data = json.loads((job / "candidates.json").read_text(encoding="utf-8"))
    info = data.get("info") or {}
    print(f"# {info.get('title', job.name)}")
    print(f"source : {info.get('webpage_url', data.get('source'))}")
    for candidate in data.get("candidates", [])[: args.top]:
        hooks = propose_hooks(candidate.get("text", ""))
        print(f"\n## {candidate['n']}. {_fmt(candidate['start'])}-{_fmt(candidate['end'])} "
              f"({candidate['end'] - candidate['start']:.0f}s) score {candidate['score']}")
        print("   pourquoi :", ", ".join(candidate.get("why") or []))
        print("   extrait  :", (candidate.get("text") or "")[:200])
        for index, hook in enumerate(hooks, 1):
            print(f"   accroche {index} : {hook}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Pipeline complet : moments -> accroches -> rendu -> contrôle -> rapport."""
    prepare_environment()
    print(f"[1/3] recherche des moments ({args.source})")
    code = run_script("moments.py", [args.source, "--top", str(args.top),
                                     "--max-minutes", str(args.max_minutes)])
    if code != 0:
        print("Echec de moments.py — voir la sortie ci-dessus.", file=sys.stderr)
        return code

    job = _latest_job()
    data = json.loads((job / "candidates.json").read_text(encoding="utf-8"))
    info = data.get("info") or {}
    candidates = data.get("candidates", [])[: args.clips]
    if not candidates:
        print("Aucun candidat retenu (transcription vide ou audio plat).", file=sys.stderr)
        return 2

    clips: list[dict] = []
    print(f"[2/3] rendu de {len(candidates)} extrait(s) depuis {job.name}")
    for candidate in candidates:
        hooks = propose_hooks(candidate.get("text", ""))
        hook = hooks[0] if hooks else ""
        styled = args.style == "gta6"
        if styled:
            from gta6_style import render as render_styled

            try:
                mp4 = render_styled(job, candidate["n"], hook, cta=args.cta,
                                    kicker=args.kicker, layout=args.layout)
                code = 0
            except Exception as exc:  # noqa: BLE001 - on continue avec les autres extraits
                print(f"  extrait {candidate['n']} : {exc}", file=sys.stderr)
                code = 1
        else:
            forward = [str(job), "--pick", str(candidate["n"]), "--layout", args.layout]
            if hook:
                forward += ["--hook", hook]
            if args.captions:
                forward += ["--captions", args.captions]
            code = run_script("cut.py", forward)
            mp4 = job / "edits" / f"clip_{candidate['n']}.mp4"
        if code != 0:
            print(f"  extrait {candidate['n']} : echec du rendu, ignore", file=sys.stderr)
            continue
        caption = caption_for(info, hook, platform=args.platform)
        print(f"[3/3] controle de {mp4.name}")
        check = run_script("check.py", [str(mp4), "--caption", caption])
        clips.append({
            "pick": candidate["n"],
            "file": str(mp4),
            "start": candidate["start"],
            "end": candidate["end"],
            "duration": round(candidate["end"] - candidate["start"], 2),
            "score": candidate["score"],
            "why": candidate.get("why") or [],
            "text": candidate.get("text", ""),
            "hook": hook,
            "hook_options": hooks,
            "caption_x": caption_for(info, hook, platform="x"),
            "caption_instagram": caption_for(info, hook, platform="instagram"),
            "caption_tiktok": caption_for(info, hook, platform="tiktok"),
            "check": "PASS" if check == 0 else "FAIL",
        })

    report = {
        "source": data.get("source"),
        "info": {key: info.get(key) for key in
                 ("id", "title", "channel", "uploader", "webpage_url", "duration", "view_count", "upload_date")},
        "signals": data.get("signals"),
        "job": str(job),
        "clips": clips,
    }
    (job / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (job / "report.md").write_text(_report_markdown(report), encoding="utf-8")
    print(f"\n{len(clips)} extrait(s) -> {job / 'report.md'}")
    return 0


def _fmt(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def _latest_job() -> Path:
    jobs = [p for p in (WORKSPACE / "jobs").iterdir() if p.is_dir()]
    if not jobs:
        raise SystemExit("aucun job dans output/gta6/jobs")
    return max(jobs, key=lambda p: (p / "candidates.json").stat().st_mtime
               if (p / "candidates.json").exists() else 0)


def _report_markdown(report: dict) -> str:
    info = report.get("info") or {}
    lines = [
        f"# Extraits — {info.get('title') or report.get('source')}",
        "",
        f"- source : {info.get('webpage_url') or report.get('source')}",
        f"- chaine : {info.get('channel') or info.get('uploader') or 'inconnue'}",
        f"- job : `{report.get('job')}`",
        "",
        "Les accroches sont générées par heuristique (pas de LLM) : à relire avant publication.",
        "Rien n'est publié automatiquement.",
        "",
    ]
    for clip in report.get("clips", []):
        lines += [
            f"## Extrait {clip['pick']} — {clip['duration']:.0f}s — {clip['start']:.1f} -> {clip['end']:.1f}",
            "",
            f"- fichier : `{clip['file']}`",
            f"- pourquoi : {', '.join(clip['why'])} (score {clip['score']})",
            f"- accroche retenue : **{clip['hook']}**",
            f"- autres accroches : {' · '.join(clip['hook_options'][1:]) or '—'}",
            f"- contrôle technique : **{clip['check']}**",
            "",
            "Légende X :",
            "",
            "```",
            clip["caption_x"],
            "```",
            "",
            "Légende Instagram :",
            "",
            "```",
            clip["caption_instagram"],
            "```",
            "",
            "Légende TikTok / Shorts :",
            "",
            "```",
            clip["caption_tiktok"],
            "```",
            "",
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gta6",
        description="Génère des extraits verticaux GTA 6 avec le plugin gtavi-claudecode (copie locale).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="vérifie ffmpeg / yt-dlp / faster-whisper et crée l'espace de travail"
                   ).set_defaults(func=cmd_setup)

    p = sub.add_parser("streams", help="streams live GTA 6, classés par spectateurs")
    p.add_argument("--query", default="gta 6")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_streams)

    p = sub.add_parser("trends", help="vidéos récentes classées par vues/heure")
    p.add_argument("--query", default="gta 6")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_trends)

    p = sub.add_parser("moments", help="détecte les meilleurs moments d'une VOD")
    p.add_argument("source", help="URL (YouTube, Twitch) ou fichier local")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--max-minutes", type=int, default=25,
                   help="ne télécharge que le début de la vidéo (défaut 25 min)")
    p.add_argument("--chat", help="chat.json TwitchDownloader")
    p.set_defaults(func=cmd_moments)

    p = sub.add_parser("cut", help="rend un candidat en extrait 1080x1920 sous-titré")
    p.add_argument("job")
    p.add_argument("--pick", type=int, default=1)
    p.add_argument("--layout", choices=["fill", "blur", "facecam", "react"], default="blur")
    p.add_argument("--hook", default="")
    p.add_argument("--cam", default=None, help="auto (visage) ou x:y:w:h")
    p.add_argument("--title", default="")
    p.add_argument("--title-style", choices=["box", "outline"], default="box")
    p.add_argument("--captions", choices=["word", "bubble", "none"], default=None)
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    p.set_defaults(func=cmd_cut)

    p = sub.add_parser("style", help="rend un candidat avec le style GTA 6 (accroche animée, karaoké rose)")
    p.add_argument("job")
    p.add_argument("--pick", type=int, default=1)
    p.add_argument("--hook", default="", help="accroche affichée (2 lignes de 21 caractères max)")
    p.add_argument("--hooks", nargs="*", default=[],
                   help="variantes d'accroche : la première est rendue, les suivantes sont listées")
    p.add_argument("--cta", default="", help="call-to-action affiché sur la fin (ex. « Follow for more »)")
    p.add_argument("--kicker", default="GTA 6", help="pastille en haut (vide pour la retirer)")
    p.add_argument("--layout", choices=["fill", "blur", "facecam"], default="fill")
    p.add_argument("--cam", default="auto",
                   help="--layout facecam : auto (visage détecté) ou x:y:w:h en fractions")
    p.add_argument("--captions", choices=["word", "none"], default="word",
                   help="word = sous-titres karaoké ; none = sans sous-titres (transcription illisible)")
    p.add_argument("--trim-bottom", type=float, default=0.0,
                   help="Retirer cette fraction de la hauteur source (0.08 = masque les "
                        "sous-titres déjà incrustés dans la VOD)")
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    p.set_defaults(func=cmd_style)

    p = sub.add_parser("check", help="contrôle avant publication")
    p.add_argument("clip")
    p.add_argument("--campaign")
    p.add_argument("--caption", default="")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("plan", help="affiche les candidats et les accroches proposées")
    p.add_argument("job")
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="pipeline complet : moments -> rendu -> contrôle -> rapport")
    p.add_argument("source")
    p.add_argument("--clips", type=int, default=3)
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--max-minutes", type=int, default=25)
    p.add_argument("--layout", choices=["fill", "blur", "facecam", "react"], default="blur")
    p.add_argument("--captions", choices=["word", "bubble", "none"], default=None)
    p.add_argument("--style", choices=["classic", "gta6"], default="classic",
                   help="classic = rendu amont ; gta6 = habillage animé (accroche + pastille)")
    p.add_argument("--cta", default="", help="call-to-action de fin (style gta6 uniquement)")
    p.add_argument("--kicker", default="GTA 6", help="pastille en haut (style gta6 uniquement)")
    p.add_argument("--platform", choices=["x", "instagram", "tiktok"], default="tiktok")
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
