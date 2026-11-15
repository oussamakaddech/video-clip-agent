"""Analyse d'activité visuelle d'une vidéo (sans parole).

Pour les vidéos sans dialogue (ambiance, musique, plan fixe), la seule source
de signal est l'**image** : on mesure le mouvement entre images successives via
ffmpeg (flux vidéo brut en niveaux de gris), ce qui permet malgré tout de
repérer les moments les plus vivants.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .ffmpeg import resolve_ffmpeg


def activity_curve(
    video: str | Path,
    *,
    fps: float = 2.0,
    width: int = 160,
    height: int = 90,
    max_frames: int = 4000,
) -> list[tuple[float, float]]:
    """Courbe d'activité : liste de (temps en secondes, mouvement moyen).

    Le mouvement est la différence moyenne de luminance entre deux images
    consécutives (0 = image fixe, 1 = changement total).
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy est une dépendance de Whisper
        return []

    ffmpeg = resolve_ffmpeg()
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"fps={fps},scale={width}:{height}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    frame_size = width * height
    scores: list[tuple[float, float]] = []
    previous = None
    index = 0
    try:
        while len(scores) < max_frames:
            data = process.stdout.read(frame_size)  # type: ignore[union-attr]
            if not data or len(data) < frame_size:
                break
            frame = np.frombuffer(data, dtype=np.uint8).astype(np.int16)
            if previous is not None:
                scores.append((index / fps, float(np.abs(frame - previous).mean()) / 255.0))
            previous = frame
            index += 1
    finally:
        try:
            process.stdout.close()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    return scores


def motion_windows(
    video: str | Path,
    *,
    count: int = 5,
    window: float = 30.0,
    min_gap: float = 30.0,
    fps: float = 2.0,
    duration: float | None = None,
) -> list[tuple[float, float, float]]:
    """Fenêtres les plus actives : liste de (début, fin, score).

    Utilisé quand la vidéo ne contient aucune parole : on retient alors les
    moments où l'image change le plus.
    """
    curve = activity_curve(video, fps=fps)
    if not curve:
        return []
    if duration is None:
        duration = max(t for t, _ in curve) + 1 / fps

    # Agrégation par fenêtre glissante
    buckets: dict[int, list[float]] = {}
    for time, score in curve:
        buckets.setdefault(int(time // window), []).append(score)

    ranked = sorted(
        ((index * window, min(duration, (index + 1) * window), sum(values) / len(values))
         for index, values in buckets.items() if values),
        key=lambda item: -item[2],
    )

    chosen: list[tuple[float, float, float]] = []
    for start, end, score in ranked:
        if all(abs(start - other[0]) >= min_gap for other in chosen):
            chosen.append((start, end, score))
        if len(chosen) >= count:
            break
    return sorted(chosen)
