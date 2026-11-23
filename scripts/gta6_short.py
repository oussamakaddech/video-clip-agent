"""Montage court « à la Viceprint » : voix off + plans courts + texte plein cadre.

Le short de référence (`youtube.com/shorts/uz-Iq7nCfnA`, 57 s, 11,8 M de vues)
n'est pas un extrait de VOD : c'est un **montage scripté** — une voix off
continue, des plans de 1 à 3 s, un texte énorme qui reprend la phrase, et un
appel à l'action final. Ce module construit le même objet à partir de nos
sources : chaque « beat » est un couple (plan, phrase).

Principe : **la voix commande le montage**. Chaque phrase est synthétisée
(System.Speech, hors ligne), sa durée réelle devient celle du plan (plus une
petite respiration). Impossible de désynchroniser le texte et l'image : le
timeline est calculé après la synthèse, pas avant.

    python scripts/gta6_short.py --spec short.json --out output/gta6/shorts/demo.mp4

Le fichier de spec :

    {
      "credit": "@IShowSpeed",
      "cta": "Follow for more GTA 6",
      "voice": "Microsoft David Desktop",
      "rate": 1,
      "beats": [
        {"source": "…\\source.mp4", "start": 1117, "end": 1124,
         "text": "This is the last mission of GTA 6.", "label": "THE LAST MISSION"}
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from gta6_style import H, W, esc, ts, wrap  # noqa: E402

PINK = "&H00882EFF"
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"

LINE_Y = 470          # zone haute : au-dessus de l'interface TikTok/Reels
CREDIT_Y = 262        # sous le logo du streamer (présent dans l'image source)
CTA_Y = 1640
GAP = 0.22            # respiration après chaque phrase
MIN_BEAT = 1.2
MAX_LABEL = 22        # caractères par ligne de texte plein cadre


@dataclass
class Beat:
    """Un plan et la phrase qui l'accompagne."""

    source: str
    start: float
    end: float
    text: str
    label: str = ""

    @property
    def caption(self) -> str:
        """Texte affiché : l'étiquette si elle existe, sinon la phrase."""
        return (self.label or self.text).strip()

    @property
    def window(self) -> float:
        return max(0.0, float(self.end) - float(self.start))


@dataclass
class Shot:
    """Un plan résolu : fenêtre source + durée finale."""

    beat: Beat
    start: float
    length: float
    t0: float = 0.0
    t1: float = 0.0


# --- Construction pure (testable sans binaire) -----------------------------

def voice_duration(path: str | Path) -> float:
    """Durée d'un WAV de synthèse (secondes)."""
    with wave.open(str(path)) as handle:
        return handle.getnframes() / float(handle.getframerate())


def plan_shots(beats: list[Beat], durations: list[float], *, gap: float = GAP) -> list[Shot]:
    """Durée de chaque plan = durée de sa phrase + respiration.

    Si la fenêtre demandée est plus courte que la phrase, on l'**allonge** dans
    la même source (on reste sur le plan) ; si elle est plus longue, on garde la
    phrase et on coupe le plan : c'est la voix qui décide du rythme.
    """
    if len(beats) != len(durations):
        raise ValueError("une durée de voix par beat attendue")
    shots: list[Shot] = []
    cursor = 0.0
    for beat, duration in zip(beats, durations):
        length = max(MIN_BEAT, round(duration + gap, 3))
        start = beat.start
        available = beat.window
        if available < length:
            # On étire le plan plutôt que de figer l'image sur la fin.
            end = start + length
            if end > start + 30:  # garde-fou : jamais 30 s de plus
                end = start + max(available, MIN_BEAT)
            length = max(MIN_BEAT, min(length, end - start))
            beat = Beat(beat.source, start, end, beat.text, beat.label)
        shot = Shot(beat=beat, start=start, length=length, t0=cursor, t1=cursor + length)
        shots.append(shot)
        cursor += length
    return shots


def total_duration(shots: list[Shot]) -> float:
    return round(shots[-1].t1, 3) if shots else 0.0


def _lines(text: str, width: int = MAX_LABEL) -> str:
    """Texte sur 1 à 3 lignes équilibrées, échappé pour ASS."""
    lines = wrap(text, width, max_lines=3)
    if not lines:
        return esc(text)
    return "\\N".join(esc(line) for line in lines)


def build_ass(
    shots: list[Shot],
    *,
    credit: str = "",
    cta: str = "",
    total: float | None = None,
) -> str:
    """ASS du montage : un texte par plan + crédit constant + CTA final."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Line,Arial Black,88,{WHITE},{WHITE},{BLACK},&H64000000,-1,0,0,0,100,100,-1,0,1,9,5,5,50,50,0,1
Style: Small,Arial Black,34,{WHITE},{WHITE},{BLACK},&H64000000,-1,0,0,0,100,100,0,0,1,5,3,5,40,40,0,1
Style: Cta,Arial Black,54,{WHITE},{WHITE},{PINK},{PINK},-1,0,0,0,100,100,0,0,3,16,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    end_of_video = total if total is not None else total_duration(shots)
    for index, shot in enumerate(shots):
        first = index == 0
        style_size = 96 if first else 88
        text = _lines(shot.beat.caption)
        events.append(
            f"Dialogue: 1,{ts(shot.t0)},{ts(shot.t1)},Line,,0,0,0,,"
            f"{{\\pos({W // 2},{LINE_Y})\\fs{style_size}\\fad(70,90)"
            f"\\fscx92\\fscy92\\t(0,140,\\fscx100\\fscy100)}}{text}"
        )
    if credit:
        events.append(
            f"Dialogue: 2,{ts(0)},{ts(end_of_video)},Small,,0,0,0,,"
            f"{{\\pos({W // 2},{CREDIT_Y})\\alpha&H40&}}{esc(credit)}"
        )
    if cta and shots:
        start = max(0.0, shots[-1].t0 - 0.6)
        events.append(
            f"Dialogue: 3,{ts(start)},{ts(end_of_video)},Cta,,0,0,0,,"
            f"{{\\pos({W // 2},{CTA_Y})\\fad(120,0)}}{esc(cta)}"
        )
    return header + "\n".join(events) + "\n"


def build_command(
    shots: list[Shot],
    ass_path: str | Path,
    out_path: str | Path,
    *,
    ffmpeg: str = "ffmpeg",
    layout: str = "fill",
    voice_track: str | Path | None = None,
    crf: int = 19,
    total: float | None = None,
) -> list[str]:
    """Commande ffmpeg complète : N plans + voix, une seule passe d'encodage."""
    if not shots:
        raise ValueError("aucun plan à monter")
    duration = total if total is not None else total_duration(shots)
    sub = str(ass_path).replace("\\", "/").replace(":", "\\:")

    command = [ffmpeg, "-y", "-v", "error"]
    for shot in shots:
        command += [
            "-ss", f"{shot.start:.2f}",
            "-t", f"{shot.length:.2f}",
            "-i", shot.beat.source,
        ]
    if voice_track:
        command += ["-i", str(voice_track)]

    graph: list[str] = []
    for index, shot in enumerate(shots):
        if layout == "blur":
            graph.append(
                f"[{index}:v]split[a{index}][b{index}];"
                f"[a{index}]scale=-2:{H},crop={W}:{H},boxblur=24:2,eq=brightness=-0.08[bg{index}];"
                f"[b{index}]scale={W}:-2[fg{index}];"
                f"[bg{index}][fg{index}]overlay=(W-w)/2:(H-h)/2-90,setsar=1,fps=30[v{index}]"
            )
        else:
            graph.append(
                f"[{index}:v]scale=-2:{H},crop={W}:{H},setsar=1,fps=30[v{index}]"
            )
        graph.append(f"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{index}]")

    video_inputs = "".join(f"[v{index}]" for index in range(len(shots)))
    audio_inputs = "".join(f"[a{index}]" for index in range(len(shots)))
    graph.append(
        f"{video_inputs}concat=n={len(shots)}:v=1:a=0[vc];"
        f"{audio_inputs}concat=n={len(shots)}:v=0:a=1[ac]"
    )
    graph.append(
        f"[vc]eq=saturation=1.10:contrast=1.05,vignette=PI/5,"
        f"fade=t=in:st=0:d=0.18,subtitles='{sub}'[vo]"
    )
    graph.append("[ac]volume=0.16[game]")
    if voice_track:
        graph.append(
            f"[{len(shots)}:a]aformat=sample_rates=48000:channel_layouts=stereo[voice];"
            f"[voice][game]amix=inputs=2:duration=first:dropout_transition=0,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        )
    else:
        graph.append("[game]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    command += [
        "-filter_complex", ";".join(graph),
        "-map", "[vo]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    return command


# --- Synthèse vocale et rendu ---------------------------------------------

TTS_SCRIPT = SCRIPTS / "tts.ps1"


def synth(text: str, out: str | Path, *, voice: str, rate: int = 0) -> Path:
    """Synthétise une phrase en WAV (System.Speech, 100 % hors ligne)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(TTS_SCRIPT),
            "-Text", text, "-Out", str(out), "-Voice", voice, "-Rate", str(rate),
        ],
        check=True,
        capture_output=True,
    )
    return out


def build_voice_track(
    voice_paths: list[Path],
    lengths: list[float],
    out: str | Path,
    *,
    ffmpeg: str = "ffmpeg",
) -> Path:
    """Assemble la voix off sur le timeline : chaque phrase, puis son silence."""
    if len(voice_paths) != len(lengths):
        raise ValueError("une durée par phrase attendue")
    out = Path(out)
    command = [ffmpeg, "-y", "-v", "error"]
    for path in voice_paths:
        command += ["-i", str(path)]
    graph = []
    for index, length in enumerate(lengths):
        graph.append(
            f"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"apad=whole_dur={length:.3f},atrim=duration={length:.3f}[p{index}]"
        )
    graph.append(
        "".join(f"[p{index}]" for index in range(len(lengths)))
        + f"concat=n={len(lengths)}:v=0:a=1[aout]"
    )
    command += ["-filter_complex", ";".join(graph), "-map", "[aout]",
                "-c:a", "pcm_s16le", str(out)]
    subprocess.run(command, check=True)
    return out


def render(
    spec: dict,
    out: str | Path,
    *,
    work: str | Path | None = None,
    ffmpeg: str = "ffmpeg",
) -> Path:
    """Monte le short décrit par `spec` (voir la doc du module)."""
    raw = spec.get("beats") or []
    if not raw:
        raise SystemExit("spec sans beats")
    beats = [
        Beat(
            source=str(item["source"]),
            start=float(item["start"]),
            end=float(item.get("end", float(item["start"]) + 4.0)),
            text=str(item.get("text", "")),
            label=str(item.get("label", "")),
        )
        for item in raw
    ]
    out = Path(out)
    work = Path(work) if work else out.with_suffix("")
    work.mkdir(parents=True, exist_ok=True)

    voice = spec.get("voice") or "Microsoft David Desktop"
    rate = int(spec.get("rate", 0))
    voice_paths: list[Path] = []
    durations: list[float] = []
    for index, beat in enumerate(beats):
        path = synth(beat.text, work / f"vo_{index:02d}.wav", voice=voice, rate=rate)
        voice_paths.append(path)
        durations.append(voice_duration(path))
        print(f"  {index + 1:>2}. {durations[-1]:5.2f}s  {beat.text}")

    shots = plan_shots(beats, durations)
    total = total_duration(shots)
    print(f"montage : {len(shots)} plans, {total:.2f}s")

    ass_path = work / "short.ass"
    ass_path.write_text(
        build_ass(shots, credit=spec.get("credit", ""), cta=spec.get("cta", ""), total=total),
        encoding="utf-8",
    )
    voice_track = build_voice_track(
        voice_paths, [shot.length for shot in shots], work / "voice.wav", ffmpeg=ffmpeg
    )
    command = build_command(
        shots, ass_path, out,
        ffmpeg=ffmpeg,
        layout=spec.get("layout", "fill"),
        voice_track=voice_track,
        total=total,
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monte un short scripté (voix off + plans courts).")
    parser.add_argument("--spec", required=True, help="fichier JSON du short")
    parser.add_argument("--out", required=True)
    parser.add_argument("--work", help="dossier de travail (voix, ASS)")
    parser.add_argument("--ffmpeg", default=None)
    args = parser.parse_args(argv)

    ffmpeg = args.ffmpeg
    if not ffmpeg:
        import compat  # pont local : ffmpeg embarqué si absent du PATH

        ffmpeg = compat.resolve_tool("ffmpeg") or "ffmpeg"
    # utf-8-sig : PowerShell écrit un BOM avec `Set-Content -Encoding UTF8`.
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8-sig"))
    out = render(spec, args.out, work=args.work, ffmpeg=ffmpeg)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
