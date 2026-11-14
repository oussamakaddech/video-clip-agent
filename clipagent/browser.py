"""Analyse et capture **dans le navigateur** : la VOD n'est jamais téléchargée en entier.

Principe
--------
1. la page Kick est ouverte dans Edge/Chrome (Playwright, codecs H.264 nécessaires) ;
2. *storyboard* : une image JPEG par N secondes, et le mouvement est mesuré
   **dans la page** (canvas) → coût réseau négligeable ;
3. les pics de mouvement deviennent des candidats ;
4. seule la fenêtre de chaque candidat est **capturée** (MediaRecorder) :
   l'audio seul pour la transcription, puis l'audio+vidéo des extraits retenus ;
5. ffmpeg transforme ces fenêtres en clips verticaux sous-titrés.

Le téléchargement de la VOD complète (plusieurs Go) n'est jamais nécessaire.
"""

from __future__ import annotations

import base64
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # console Windows : cp1252 ne sait pas écrire « → »
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

CHROMIUM_ARGS = [
    "--autoplay-policy=no-user-gesture-required",
    "--disable-blink-features=AutomationControlled",
    "--mute-audio=false",
    "--no-sandbox",
]

# Canaux navigateur : Chromium de Playwright n'a PAS les codecs H.264
# (Kick sert en HLS/H.264) → Edge ou Chrome sont obligatoires.
BROWSER_CHANNELS = ("msedge", "chrome", "chromium")

# --- JavaScript injecté ----------------------------------------------------

JS_STORYBOARD = """
async (opts) => {
  const pick = () => {
    const videos = Array.from(document.querySelectorAll('video'));
    let best = null, bestDuration = 0;
    for (const v of videos) { if (isFinite(v.duration) && v.duration > bestDuration) { bestDuration = v.duration; best = v; } }
    return best || videos[0] || null;
  };
  const v = pick();
  if (!v) throw new Error('element video introuvable');
  const seek = (t) => new Promise((resolve) => {
    const onSeeked = () => { v.removeEventListener('seeked', onSeeked); resolve(); };
    v.addEventListener('seeked', onSeeked);
    try { v.currentTime = t; } catch (e) { resolve(); }
  });

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  let previous = null;
  const samples = [];

  for (const t of opts.times) {
    await seek(t);
    await new Promise(r => setTimeout(r, opts.settle));
    const w = opts.width;
    const h = Math.max(2, Math.round(w * (v.videoHeight || 9) / (v.videoWidth || 16)));
    canvas.width = w; canvas.height = h;
    ctx.drawImage(v, 0, 0, w, h);
    const pixels = ctx.getImageData(0, 0, w, h).data;
    let motion = 0;
    if (previous) {
      let sum = 0, count = 0;
      for (let i = 0; i < pixels.length; i += 4 * 37) {
        sum += Math.abs(pixels[i] - previous[i])
              + Math.abs(pixels[i + 1] - previous[i + 1])
              + Math.abs(pixels[i + 2] - previous[i + 2]);
        count++;
      }
      motion = count ? sum / (count * 765) : 0;
    }
    previous = pixels.slice();
    samples.push({ t, motion, data: canvas.toDataURL('image/jpeg', opts.quality) });
  }
  return samples;
}
"""

JS_CAPTURE = """
async (opts) => {
  const pick = () => {
    const videos = Array.from(document.querySelectorAll('video'));
    let best = null, bestDuration = 0;
    for (const v of videos) { if (isFinite(v.duration) && v.duration > bestDuration) { bestDuration = v.duration; best = v; } }
    return best || videos[0] || null;
  };
  const v = pick();
  if (!v) throw new Error('element video introuvable');

  const seek = (t) => new Promise((resolve) => {
    const onSeeked = () => { v.removeEventListener('seeked', onSeeked); resolve(); };
    v.addEventListener('seeked', onSeeked);
    try { v.currentTime = t; } catch (e) { resolve(); }
  });

  await seek(opts.start);
  await new Promise(r => setTimeout(r, 250));

  const stream = v.captureStream(30);
  const videoTracks = stream.getVideoTracks();
  const audioTracks = stream.getAudioTracks();
  let tracks = opts.audioOnly ? audioTracks : videoTracks.concat(audioTracks);
  if (!tracks.length) {
    if (opts.audioOnly) throw new Error('aucune piste audio capturee');
    tracks = videoTracks;
  }
  const target = new MediaStream(tracks);

  const mime = opts.audioOnly ? 'audio/webm' : 'video/webm;codecs=vp8,opus';
  let recorder;
  try {
    recorder = new MediaRecorder(target, { mimeType: mime, videoBitsPerSecond: opts.bitrate });
  } catch (e) {
    recorder = new MediaRecorder(target);
  }
  const chunks = [];
  recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
  const stopped = new Promise((resolve) => { recorder.onstop = resolve; });

  await v.play();
  recorder.start(500);
  const duration = Math.max(300, (opts.end - opts.start) * 1000);
  const started = Date.now();
  while (Date.now() - started < duration) {
    await new Promise(r => setTimeout(r, 120));
  }
  recorder.stop();
  await stopped;
  try { v.pause(); } catch (e) {}

  const blob = new Blob(chunks, { type: opts.audioOnly ? 'audio/webm' : 'video/webm' });
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return { base64: btoa(binary), audio: audioTracks.length > 0, video: videoTracks.length > 0 };
}
"""

JS_SELECT_VIDEO = """
() => {
  const videos = Array.from(document.querySelectorAll('video'));
  let best = null, bestDuration = 0;
  for (const v of videos) {
    const d = v.duration;
    if (isFinite(d) && d > bestDuration) { bestDuration = d; best = v; }
  }
  if (!best) best = videos[0] || null;
  if (!best) return null;
  window.__clipVideo = best;
  return {
    duration: best.duration,
    width: best.videoWidth,
    height: best.videoHeight,
    readyState: best.readyState,
    count: videos.length,
  };
}
"""


class BrowserError(RuntimeError):
    """Erreur liée au pilotage du navigateur."""


@dataclass
class FrameSample:
    """Une image du storyboard, avec son horodatage et son niveau de mouvement."""

    timestamp: float
    motion: float
    path: Path | None = None


@dataclass
class BrowserAnalyzer:
    """Pilote un navigateur réel pour analyser et capturer une VOD sans la télécharger."""

    url: str
    out_dir: Path = Path("output/browser")
    headless: bool = True
    channel: str = "msedge"
    width: int = 512
    quality: float = 0.6
    settle_ms: int = 320
    log: bool = True
    info: dict = field(default_factory=dict)
    _playwright: object | None = None
    _browser: object | None = None
    _context: object | None = None
    _page: object | None = None

    # --- Cycle de vie ------------------------------------------------------
    def __enter__(self) -> "BrowserAnalyzer":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise BrowserError(
                "Playwright est requis pour le mode navigateur : "
                "pip install 'playwright==1.49.1'"
            ) from exc

        self._playwright = sync_playwright().start()
        self._browser = self._launch()
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )
        self._page = self._context.new_page()
        return self

    def _launch(self):
        from playwright.sync_api import sync_playwright  # noqa: F401

        channels = [self.channel] if self.channel != "auto" else list(BROWSER_CHANNELS)
        last_error: Exception | None = None
        for channel in channels:
            try:
                self._say(f"→ navigateur : {channel}")
                return self._playwright.chromium.launch(  # type: ignore[union-attr]
                    channel=channel,
                    headless=self.headless,
                    args=CHROMIUM_ARGS,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise BrowserError(
            "Aucun navigateur compatible trouvé (Edge ou Chrome requis pour les codecs H.264) : "
            f"{last_error}"
        )

    def __exit__(self, *exc_info) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass

    # --- Utilitaires -------------------------------------------------------
    def _say(self, message: str) -> None:
        if self.log:
            print(message, flush=True)

    # --- Étape 1 : ouverture ----------------------------------------------
    def open(self) -> dict:
        """Ouvre la page et attend le lecteur."""
        assert self._page is not None
        self._say(f"→ ouverture de {self.url}")
        self._page.goto(self.url, wait_until="domcontentloaded", timeout=120_000)

        for attempt in range(30):
            self._page.wait_for_timeout(2000)
            try:
                self._page.evaluate(
                    """() => { document.querySelectorAll('video').forEach(v => {
                         try { v.muted = false; v.play().catch(()=>{}); } catch (e) {} }); }"""
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                info = self._page.evaluate(JS_SELECT_VIDEO)
            except Exception:  # noqa: BLE001
                info = None
            if info and info.get("duration") and info["duration"] > 30:
                self.info = info
                self._say(
                    f"  lecteur détecté : {info['duration']:.0f} s "
                    f"({info['duration']/60:.0f} min), {info['width']}x{info['height']}"
                )
                return info
            if attempt == 4:
                try:  # certains lecteurs exigent un clic
                    self._page.click("video", timeout=3000)
                except Exception:  # noqa: BLE001
                    pass
        raise BrowserError(
            "Aucun lecteur exploitable sur cette page (VOD privée, connexion requise, "
            "ou codecs H.264 indisponibles ?)."
        )

    # --- Étape 2 : storyboard ---------------------------------------------
    def storyboard(self, *, step: float = 20.0, max_frames: int = 240) -> list[FrameSample]:
        """Balaye la vidéo : une image par intervalle, mouvement mesuré dans la page."""
        assert self._page is not None
        duration = float(self.info.get("duration") or 0)
        if duration <= 0:
            raise BrowserError("Durée inconnue : balayage impossible.")

        count = int(duration // step)
        if count > max_frames:
            step = duration / max_frames
            count = max_frames
        times = [round(min(duration - 1.0, i * step + step / 2), 2) for i in range(count)]

        self._say(f"→ storyboard : {len(times)} images (1 toutes les {step:.0f} s)")
        raw = self._page.evaluate(
            JS_STORYBOARD,
            {"times": times, "width": self.width, "quality": self.quality, "settle": self.settle_ms},
        )

        frames_dir = Path(self.out_dir) / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        samples: list[FrameSample] = []
        for item in raw:
            path = None
            if item.get("data"):
                path = frames_dir / f"frame_{int(item['t']):07d}.jpg"
                path.write_bytes(base64.b64decode(item["data"].split(",", 1)[-1]))
            samples.append(FrameSample(timestamp=float(item["t"]), motion=float(item["motion"]), path=path))
        self._say(f"  {len(samples)} images enregistrées dans {frames_dir}")
        return samples

    # --- Étape 3 : capture d'une fenêtre ----------------------------------
    def capture(
        self,
        start: float,
        end: float,
        target: Path,
        *,
        audio_only: bool = False,
        bitrate: int = 2_000_000,
    ) -> Path:
        """Capture la fenêtre [start, end] depuis le lecteur (sans télécharger la VOD)."""
        assert self._page is not None
        result = self._page.evaluate(
            JS_CAPTURE,
            {
                "start": float(start),
                "end": float(end),
                "audioOnly": bool(audio_only),
                "bitrate": bitrate,
            },
        )
        payload = result["base64"] if isinstance(result, dict) else result
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(payload))
        if isinstance(result, dict):
            self._say(
                f"  capture {start:.0f}→{end:.0f} s : {target.stat().st_size // 1024} Ko "
                f"(audio={'oui' if result.get('audio') else 'non'}, vidéo={'oui' if result.get('video') else 'non'})"
            )
        return target
