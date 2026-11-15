"""Diagnostic du bouton de telechargement."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
JOB = sys.argv[1] if len(sys.argv) > 1 else "ff6118dc71bc"

with urllib.request.urlopen(f"http://127.0.0.1:8765/api/jobs/{JOB}", timeout=30) as response:
    job = json.loads(response.read())

clips = (job.get("result") or {}).get("clips", [])
print("clips :", [(c["index"], c.get("path")) for c in clips])

for clip in clips:
    url = f"http://127.0.0.1:8765/api/jobs/{JOB}/clips/{clip['index']}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
            print(f"clip #{clip['index']} : HTTP {response.status} · {len(data)} octets")
            print("   Content-Disposition :", response.headers.get("Content-Disposition"))
            print("   Content-Type       :", response.headers.get("Content-Type"))
            print("   Content-Length     :", response.headers.get("Content-Length"))
    except urllib.error.HTTPError as exc:
        print(f"clip #{clip['index']} : HTTP {exc.code} -> {exc.read()[:200]}")
    except Exception as exc:
        print(f"clip #{clip['index']} : ERREUR {type(exc).__name__} {str(exc)[:150]}")

# best-of
try:
    with urllib.request.urlopen(f"http://127.0.0.1:8765/api/jobs/{JOB}/best-of", timeout=120) as response:
        print("best-of :", response.status, len(response.read()), "octets")
except urllib.error.HTTPError as exc:
    print("best-of : HTTP", exc.code, exc.read()[:200])
except Exception as exc:
    print("best-of : ERREUR", type(exc).__name__, str(exc)[:150])

# rapport
try:
    with urllib.request.urlopen(f"http://127.0.0.1:8765/api/jobs/{JOB}/report", timeout=60) as response:
        print("rapport :", response.status, len(response.read()), "octets")
except Exception as exc:
    print("rapport : ERREUR", type(exc).__name__, str(exc)[:150])
