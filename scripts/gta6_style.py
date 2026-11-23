"""Style visuel « GTA 6 » pour les extraits du pont (`scripts/gta6.py`).

Ce module est **local** (il ne vient pas de gtavi-claudecode). Il ne réécrit pas
le pipeline amont : il construit son propre fichier ASS et sa propre commande
ffmpeg, en réutilisant seulement le masquage des insultes de `cut.py`.

Ce que le style ajoute :

- **pastille « GTA 6 »** animée en haut du cadre (repère immédiat, 2,8 s) ;
- **accroche** blanche, contour noir épais, ombre rose, entrée en zoom
  (90 % -> 100 % en 150 ms) sur 2,8 s ;
- **sous-titres karaoké** : mot actif rose (#FF2E88) avec pop d'échelle, le
  reste en blanc contour noir ;
- **étalonnage** : saturation +10 %, contraste +5 %, vignettage doux, fondu
  d'entrée de 0,18 s (pose le rythme sans flash publicitaire) ;
- **call-to-action** optionnel en fin d'extrait (`--cta`).

Usage direct :
    python scripts/gta6_style.py <job> --pick 3 --hook "He walked into gator water"

Repères de conception : les hooks doivent tenir en 2 lignes de 21 caractères
(max ~42), sinon ils sont coupés — c'est la largeur lisible en Arial Black 78
sur 1080 px, au-dessus de la zone d'interface de TikTok/Reels/Shorts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDORED = ROOT / "integrations" / "gtavi" / "scripts"
if str(VENDORED) not in sys.path:
    sys.path.insert(0, str(VENDORED))

W, H = 1080, 1920

# Couleurs ASS = &HAABBGGRR (alpha, bleu, vert, rouge)
PINK = "&H00882EFF"    # #FF2E88, rose Vice City
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
INK = "&H000F0B0B"     # #0B0B0F, presque noir
SOFT_BLACK = "&H64000000"

# Positions verticales des textes, par cadrage.
# `facecam` empile la caméra du streamer en haut : tout le reste descend sous le
# raccord (CAM_H). Voir `POS` plus bas.
HAUTEUR_CAM = 608              # panneau caméra (aspect 16:9, comme la webcam)
HAUTEUR_JEU = H - HAUTEUR_CAM  # 1312 px de jeu sous la caméra
CAM_BOX = (0.695, 0.666, 0.232, 0.232)  # x:y:w:h du visage, en fractions

POS = {
    # layout : (kicker, hook, sous-titres, cta)
    "fill": (168, 300, 1380, 1640),
    "blur": (168, 300, 1460, 1640),
    "facecam": (690, 830, 1450, 1690),
}
HOOK_SECONDS = 2.8
CTA_SECONDS = 1.8
HOOK_MAX_CHARS = 22


def ts(t: float) -> str:
    """Horodatage ASS (H:MM:SS.cc)."""
    t = max(0.0, float(t))
    hours, rest = divmod(t, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{seconds:05.2f}"


def esc(text: str) -> str:
    """Neutralise ce qui casserait une ligne ASS."""
    return str(text).replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def wrap(text: str, width: int = HOOK_MAX_CHARS, max_lines: int = 2) -> list[str]:
    """Découpe l'accroche en lignes équilibrées, sans mot coupé.

    On cherche la coupure qui minimise l'écart de longueur entre les lignes :
    « He walked into / gator water » plutôt que « He walked into gator / water ».
    """
    words = str(text).split()
    if not words:
        return []
    if len(" ".join(words)) <= width:
        return [" ".join(words)]
    if max_lines == 2:
        best: tuple[int, list[str]] | None = None
        for split in range(1, len(words)):
            first, second = " ".join(words[:split]), " ".join(words[split:])
            if len(first) <= width and len(second) <= width:
                score = abs(len(first) - len(second))
                if best is None or score < best[0]:
                    best = (score, [first, second])
        if best:
            return best[1]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def _groups(words: list[dict], s0: float, e0: float, size: int = 3) -> list[list[dict]]:
    """Groupes de 3 mots max, coupés sur ponctuation ou pause > 0,6 s."""
    selected = [w for w in words if s0 <= w["s"] < e0 and w.get("w")]
    groups: list[list[dict]] = []
    current: list[dict] = []
    for word in selected:
        if current and (len(current) == size or word["s"] - current[-1]["e"] > 0.6
                        or current[-1]["w"][-1:] in ".?!,"):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def build_ass(
    words: list[dict],
    s0: float,
    e0: float,
    hook: str = "",
    *,
    kicker: str = "GTA 6",
    cta: str = "",
    layout: str = "fill",
    profanity: bool = False,
    captions: bool = True,
) -> str:
    """Construit le fichier ASS du style GTA 6 (aucune dépendance externe)."""
    from cut import clean  # masquage des insultes/insultes raciales de l'amont

    cap_y = POS.get(layout, POS["fill"])[2]
    kicker_y, hook_y, _, cta_y = POS.get(layout, POS["fill"])
    duration = max(0.1, e0 - s0)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial Black,92,{WHITE},{PINK},{BLACK},{SOFT_BLACK},-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Hook,Arial Black,78,{WHITE},{WHITE},{BLACK},{PINK},-1,0,0,0,100,100,0,0,1,10,5,8,60,60,0,1
Style: Kicker,Arial Black,40,{INK},{INK},{PINK},{PINK},-1,0,0,0,100,100,0,0,3,18,0,5,0,0,0,1
Style: Cta,Arial Black,52,{WHITE},{WHITE},{PINK},{PINK},-1,0,0,0,100,100,0,0,3,14,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    if kicker:
        events.append(
            f"Dialogue: 3,{ts(0)},{ts(HOOK_SECONDS)},Kicker,,0,0,0,,"
            f"{{\\pos({W // 2},{kicker_y})\\fad(80,150)\\fscx92\\fscy92\\t(0,140,\\fscx100\\fscy100)}}"
            f"{esc(kicker)}"
        )
    if hook:
        lines = wrap(hook)
        if " ".join(lines).split() != str(hook).split():
            lines[-1] = lines[-1].rstrip(" .,") + "…"  # signale la coupe, jamais silencieuse
        body = "\\N".join(esc(line) for line in lines)
        events.append(
            f"Dialogue: 2,{ts(0)},{ts(HOOK_SECONDS)},Hook,,0,0,0,,"
            f"{{\\pos({W // 2},{hook_y})\\fad(80,150)\\fscx90\\fscy90\\t(0,150,\\fscx100\\fscy100)}}{body}"
        )
    if cta:
        begin = max(0.0, duration - CTA_SECONDS)
        events.append(
            f"Dialogue: 4,{ts(begin)},{ts(duration)},Cta,,0,0,0,,"
            f"{{\\pos({W // 2},{cta_y})\\fad(120,0)\\fscx94\\fscy94\\t(0,120,\\fscx100\\fscy100)}}"
            f"{esc(cta)}"
        )

    if captions:
        groups = _groups(words, s0, e0)
    else:
        groups = []  # transcription illisible (dialecte) : on ne sous-titre pas
    for group_index, group in enumerate(groups):
        # Un seul groupe à l'écran : deux groupes superposés au même point
        # d'ancrage se chevauchent lettre à lettre (« THAT'SGOINGTO »).
        limit = (groups[group_index + 1][0]["s"] - s0) if group_index + 1 < len(groups) else duration
        last_end = group[-1]["e"] - s0
        tail = min(last_end + 0.35, limit)
        for index, word in enumerate(group):
            start = word["s"] - s0
            end = (group[index + 1]["s"] - s0) if index + 1 < len(group) else tail
            end = min(end, limit)
            if end <= start:
                continue
            parts = []
            for position, item in enumerate(group):
                text = esc(clean(item["w"], profanity).upper())
                if position == index:
                    parts.append("{\\c" + PINK + "&}" + text + "{\\c" + WHITE + "&}")
                else:
                    parts.append(text)
            events.append(
                f"Dialogue: 0,{ts(start)},{ts(end)},Cap,,0,0,0,,"
                f"{{\\pos({W // 2},{cap_y})}}{' '.join(parts)}"
            )
    return header + "\n".join(events) + "\n"


def video_filter(
    layout: str,
    ass_path: Path,
    *,
    trim_bottom: float = 0.0,
    cam: tuple[float, float, float, float] | None = None,
) -> str:
    """Graphe ffmpeg : cadrage + étalonnage + vignettage + fondu + sous-titres.

    ``trim_bottom`` retire une fraction de la hauteur source **avant** le
    cadrage : les rediffusions YouTube portent souvent leurs propres sous-titres
    incrustés en bas du cadre, qui se retrouveraient par-dessus les nôtres.

    ``facecam`` empile deux panneaux : la caméra du streamer en haut (recadrée
    sur le visage), le jeu en bas. ``cam`` donne le visage en fractions
    ``(x, y, w, h)`` de la source ; il est obligatoire pour ce cadrage.
    """
    sub = str(ass_path).replace("\\", "/").replace(":", "\\:")
    trim = 0.0 if trim_bottom <= 0 else min(0.25, max(0.02, float(trim_bottom)))
    head = f"[0:v]crop=iw:ih*{1 - trim:.4f}:0:0," if trim else "[0:v]"
    if layout == "blur":
        base = (
            f"{head}split[a][b];[a]scale=-2:{H},crop={W}:{H},boxblur=24:2,eq=brightness=-0.08[bg];"
            f"[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2-80[v]"
        )
    elif layout == "fill":
        base = f"{head}scale=-2:{H},crop={W}:{H}[v]"
    elif layout == "facecam":
        if not cam:
            raise ValueError("le cadrage facecam exige la position de la caméra (x:y:w:h)")
        x, y, w, h = (float(value) for value in cam)
        base = (
            f"{head}split[a][b];"
            f"[a]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f},"
            f"scale={W}:{HAUTEUR_CAM}:force_original_aspect_ratio=increase,"
            f"crop={W}:{HAUTEUR_CAM},setsar=1[cam];"
            f"[b]scale=-2:{HAUTEUR_JEU},crop={W}:{HAUTEUR_JEU},setsar=1[game];"
            f"[cam][game]vstack[v]"
        )
    else:
        raise ValueError(f"layout non géré par le style GTA 6 : {layout}")
    fade = "fade=t=in:st=0:d=0.18,"
    return (
        base
        + f";[v]setsar=1,eq=saturation=1.10:contrast=1.05,vignette=PI/5,{fade}fps=30,"
          f"subtitles='{sub}'[vo]"
    )


def detect_cam(source: str | Path, s0: float, e0: float) -> tuple[float, float, float, float]:
    """Trouve le visage du streamer (même détection OpenCV que l'amont).

    Renvoie la boîte en fractions ``(x, y, w, h)`` de l'image source. À défaut,
    on s'arrête avec un message explicite : deviner une caméra au hasard
    produirait un cadrage sur le décor.
    """
    from facecam import find_cam  # intégration : cv2 + YuNet

    window = max(4.0, min(40.0, float(e0) - float(s0)))
    result = find_cam(str(source), float(s0), float(s0) + window)
    box = result.get("box")
    if not box:
        raise SystemExit(
            "visage du streamer introuvable sur cette fenêtre — passer "
            "--cam x:y:w:h (fractions de l'image source)"
        )
    # La détection cadre le visage ; on remonte et on élargit un peu pour
    # garder le bonnet, les écouteurs et le menton dans le panneau.
    x, y, w, h = (float(value) for value in box)
    grow = 1.15
    w2 = min(1.0, w * grow)
    h2 = min(1.0, h * grow)
    x2 = min(max(0.0, x - (w2 - w) / 2), 1.0 - w2)
    y2 = min(max(0.0, y - 0.15 * h), 1.0 - h2)
    return (x2, y2, w2, h2)


def resolve_cam(
    source: str | Path, s0: float, e0: float, cam: str | tuple | None
) -> tuple[float, float, float, float]:
    """Position de la caméra : explicite (``x:y:w:h``), ``auto`` ou par défaut."""
    if isinstance(cam, (tuple, list)):
        return tuple(float(value) for value in cam)
    if cam and cam != "auto":
        parts = [float(value) for value in str(cam).split(":")]
        if len(parts) != 4:
            raise SystemExit("--cam attend x:y:w:h (fractions de 0 à 1)")
        return tuple(parts)
    if cam == "auto":
        return detect_cam(source, s0, e0)
    return CAM_BOX


def render(
    job: str | Path,
    pick: int,
    hook: str = "",
    *,
    cta: str = "",
    kicker: str = "GTA 6",
    layout: str = "fill",
    start: float | None = None,
    end: float | None = None,
    crf: int = 19,
    profanity: bool = False,
    trim_bottom: float = 0.0,
    cam: str | tuple | None = None,
    captions: bool = True,
) -> Path:
    """Rend un extrait avec le style GTA 6 et écrit son sidecar JSON."""
    import compat

    job = Path(job)
    candidates = json.loads((job / "candidates.json").read_text(encoding="utf-8"))
    candidate = next((x for x in candidates["candidates"] if x["n"] == pick), None)
    if candidate is None:
        raise SystemExit(f"candidat {pick} introuvable dans {job / 'candidates.json'}")
    s0 = float(start if start is not None else candidate["start"])
    e0 = float(end if end is not None else candidate["end"])
    words = json.loads((job / "transcript.json").read_text(encoding="utf-8"))

    edits = job / "edits"
    edits.mkdir(parents=True, exist_ok=True)
    ass_path = edits / f"clip_{pick}_gta6.ass"
    ass_path.write_text(
        build_ass(words, s0, e0, hook, kicker=kicker, cta=cta, layout=layout,
                  profanity=profanity, captions=captions),
        encoding="utf-8",
    )
    out = edits / f"clip_{pick}_gta6.mp4"
    ffmpeg = compat.resolve_tool("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg introuvable (voir `python scripts/gta6.py setup`)")
    cam_box = None
    if layout == "facecam":
        cam_box = resolve_cam(candidates["source"], s0, e0, cam)
        print(f"caméra : {cam_box[0]:.3f}:{cam_box[1]:.3f}:{cam_box[2]:.3f}:{cam_box[3]:.3f}")
    command = [
        ffmpeg, "-y", "-v", "error",
        "-ss", f"{s0:.2f}", "-to", f"{e0:.2f}", "-i", str(candidates["source"]),
        "-filter_complex",
        video_filter(layout, ass_path, trim_bottom=trim_bottom, cam=cam_box),
        "-map", "[vo]", "-map", "0:a?",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(command, check=True)

    source = candidates.get("info") or {}
    (edits / f"clip_{pick}_gta6.json").write_text(json.dumps({
        "file": str(out),
        "start": s0,
        "end": e0,
        "layout": layout,
        "style": "gta6",
        "hook": hook,
        "kicker": kicker,
        "cta": cta,
        "source_url": source.get("webpage_url"),
        "source_title": source.get("title"),
        "source_channel": source.get("channel") or source.get("uploader"),
        "cam": list(cam_box) if cam_box else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Rend un extrait avec le style GTA 6.")
    parser.add_argument("job", help="dossier job (contient candidates.json + transcript.json)")
    parser.add_argument("--pick", type=int, default=1)
    parser.add_argument("--hook", default="")
    parser.add_argument("--cta", default="")
    parser.add_argument("--kicker", default="GTA 6")
    parser.add_argument("--layout", choices=["fill", "blur", "facecam"], default="fill")
    parser.add_argument(
        "--cam",
        default="auto",
        help="position du visage pour --layout facecam : auto ou x:y:w:h (fractions)",
    )
    parser.add_argument("--start", type=float)
    parser.add_argument("--end", type=float)
    parser.add_argument("--crf", type=int, default=19)
    parser.add_argument(
        "--trim-bottom",
        type=float,
        default=0.0,
        help="Fraction de hauteur à retirer en bas (0.08 pour masquer des sous-titres incrustés)",
    )
    parser.add_argument("--allow-profanity", action="store_true")
    parser.add_argument("--captions", choices=["word", "none"], default="word",
                        help="word = karaoké depuis transcript.json ; none = pas de sous-titres")
    args = parser.parse_args(argv)
    out = render(args.job, args.pick, args.hook, cta=args.cta, kicker=args.kicker,
                 layout=args.layout, start=args.start, end=args.end, crf=args.crf,
                 profanity=args.allow_profanity, trim_bottom=args.trim_bottom,
                 cam=args.cam, captions=args.captions != "none")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
