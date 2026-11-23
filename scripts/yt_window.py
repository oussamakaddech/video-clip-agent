"""Choisit une fenêtre de VOD à analyser d'après la heatmap « most replayed ».

Usage : python scripts/yt_window.py <url> [--window 20] [--top 3]
"""

from __future__ import annotations

import json
import subprocess
import sys


def main(argv: list[str]) -> int:
    url = argv[1]
    window = 20.0
    top = 3
    for index, value in enumerate(argv):
        if value == "--window":
            window = float(argv[index + 1])
        elif value == "--top":
            top = int(argv[index + 1])

    out = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--skip-download", "-J", url, "--no-warnings"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        print(out.stderr[-800:])
        return 1
    info = json.loads(out.stdout)
    duration = info.get("duration") or 0
    print(f"{info.get('title')} — {info.get('channel')} — {duration / 60:.0f} min")
    heat = info.get("heatmap")
    if not heat:
        print("pas de heatmap")
        return 2

    # Densité de « replays » par seconde, puis meilleure fenêtre glissante.
    buckets = sorted(heat.get("available_at") or [])
    if not buckets:
        print("heatmap vide")
        return 3
    step = duration / len(buckets)
    scores = [(bucket.get("value") or 0.0) for bucket in buckets]
    span = max(1, int(round(window * 60 / step)))
    best: list[tuple[float, int]] = []
    for start in range(0, max(1, len(scores) - span + 1)):
        best.append((sum(scores[start : start + span]), start))
    best.sort(reverse=True)
    for total, start in best[:top]:
        begin = int(start * step)
        print(f"{begin // 60:>5} min → {(begin + window * 60) // 60:>5} min  (densité {total / span:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
