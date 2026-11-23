"""Classe des extraits audio par énergie (action/densité de parole).

Usage : python scripts/audio_energy.py <dossier>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy


def rms(path: Path) -> float:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
    ).stdout
    samples = numpy.frombuffer(raw, dtype=numpy.int16).astype(numpy.float32) / 32768.0
    if samples.size == 0:
        return -99.0
    # Énergie des 10 % les plus forts : une voix calme a peu de pics.
    frames = samples[: samples.size // 1600 * 1600].reshape(-1, 1600)
    energies = numpy.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    peak = numpy.percentile(energies, 90)
    return float(20 * numpy.log10(peak + 1e-9))


def main(argv: list[str]) -> int:
    folder = Path(argv[1])
    rows = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in {".webm", ".m4a", ".mp4", ".opus"}:
            rows.append((rms(path), path.name))
    for energy, name in sorted(rows, reverse=True):
        print(f"{energy:6.1f} dB  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
