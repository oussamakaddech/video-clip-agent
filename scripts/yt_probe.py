"""Sonde un VOD YouTube : métadonnées + formats vidéo disponibles."""

from __future__ import annotations

import json
import subprocess
import sys


def main(url: str) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--skip-download", "-J", url, "--no-warnings"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(result.stderr[-2000:])
        return result.returncode
    info = json.loads(result.stdout)
    for key in ("title", "duration", "upload_date", "view_count", "channel"):
        print(f"{key:12}: {info.get(key)}")
    print(f"{'thumbnail':12}: {info.get('thumbnail')}")
    for fmt in info.get("formats", []):
        if fmt.get("vcodec") == "none":
            continue
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        print(
            f"{fmt['format_id']:>7} {str(fmt.get('height')) + 'p':>6} "
            f"{str(fmt.get('fps')):>5} {str(fmt.get('vcodec'))[:16]:16} "
            f"{(str(round(size / 1e6)) + ' Mo') if size else '?':>10}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
