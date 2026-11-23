"""Recherche YouTube via yt-dlp et affichage compact des résultats.

Usage : python scripts/yt_search.py "requête" [n]
"""

from __future__ import annotations

import json
import subprocess
import sys


def main(argv: list[str]) -> int:
    query = argv[1] if len(argv) > 1 else "GTA 6 stream gameplay"
    count = int(argv[2]) if len(argv) > 2 else 15
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist", "-J", f"ytsearch{count}:{query}",
        "--no-warnings",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        print(out.stderr[-800:])
        return 1
    data = json.loads(out.stdout)
    for entry in data.get("entries") or []:
        duration = entry.get("duration") or 0
        views = entry.get("view_count") or 0
        minutes = f"{int(duration) // 60}m" if duration else "  ?  "
        print(
            f"{minutes:>5} | {views:>9} vues | {entry.get('channel') or entry.get('uploader')}"
            f" | {entry.get('title')[:70]}"
        )
        print(f"        {entry.get('url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
