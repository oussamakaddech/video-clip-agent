"""Détection du visage du streamer (« face cam ») pour le format vertical.

Le visage est cherché dans les images de la vidéo (OpenCV YuNet), puis la zone
est recadrée et superposée **en bas** du format vertical — le format classique
des shorts avec le streamer en picture-in-picture.

Si aucun visage n'est trouvé, le clip est rendu normalement (sans face cam).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "face_detection_yunet_2023mar.onnx"


@dataclass(frozen=True)
class FaceBox:
    """Rectangle du visage, en pixels de la source."""

    x: int
    y: int
    width: int
    height: int
    score: float = 0.0

    def padded(self, ratio: float = 0.6) -> "FaceBox":
        """Rectangle élargi autour du visage (le visage seul est trop serré)."""
        pad_x = int(self.width * ratio)
        pad_y = int(self.height * ratio)
        return FaceBox(
            x=max(0, self.x - pad_x),
            y=max(0, self.y - pad_y),
            width=self.width + 2 * pad_x,
            height=self.height + 2 * pad_y,
            score=self.score,
        )

    def square(self) -> "FaceBox":
        """Boîte carrée (pour un affichage rond)."""
        side = max(self.width, self.height)
        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        return FaceBox(
            x=int(max(0, cx - side / 2)),
            y=int(max(0, cy - side / 2)),
            width=int(side),
            height=int(side),
            score=self.score,
        )

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height, "score": round(self.score, 3)}


def _detector():
    import cv2

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Modèle de détection absent : {MODEL_PATH}. "
            "Télécharger face_detection_yunet_2023mar.onnx dans le dossier data/."
        )
    return cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (320, 320), 0.6, 0.3, 5000)


def detect_face_in_image(path: str | Path) -> FaceBox | None:
    """Cherche un visage dans une image (le plus grand trouvé)."""
    import cv2

    image = cv2.imread(str(path))
    if image is None:
        return None
    height, width = image.shape[:2]
    detector = _detector()
    detector.setInputSize((width, height))
    _ok, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        return None
    best = max(faces, key=lambda f: float(f[2] * f[3]))
    return FaceBox(
        x=int(best[0]),
        y=int(best[1]),
        width=int(best[2]),
        height=int(best[3]),
        score=float(best[-1]),
    )


def detect_face_in_video(
    video: str | Path,
    *,
    samples: int = 12,
    start: float = 0.0,
    duration: float | None = None,
    min_size: int = 14,
) -> FaceBox | None:
    """Cherche un visage dans la vidéo en échantillonnant quelques images.

    On garde la boîte la plus fréquemment détectée (le visage du streamer reste
    au même endroit pendant tout le stream).
    """
    video = Path(video)
    if not video.exists():
        return None

    total = duration or _probe_duration(video)
    if total <= 0:
        # Les webm produits par MediaRecorder n'ont pas de durée dans l'en-tête
        # (« Duration: N/A ») : on échantillonne le début du fragment.
        total = 30.0

    times = [start + (i + 0.5) * (total / max(1, samples)) for i in range(samples)]
    boxes: list[FaceBox] = []
    tmp_dir = Path(video).parent / "_facecam_frames"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, moment in enumerate(times):
            frame_path = tmp_dir / f"probe_{index:02d}.jpg"
            ok = _extract_frame(video, moment, frame_path)
            if not ok:
                continue
            box = detect_face_in_image(frame_path)
            if box and box.width >= min_size and box.height >= min_size:
                boxes.append(box)
            frame_path.unlink(missing_ok=True)
    finally:
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    if not boxes:
        return None

    # boîte médiane (plus stable qu'une moyenne)
    boxes.sort(key=lambda b: b.x)
    median_x = boxes[len(boxes) // 2]
    return median_x


def _probe_duration(video: Path) -> float:
    from .ffmpeg import resolve_ffmpeg

    try:
        ffmpeg = resolve_ffmpeg()
        result = subprocess.run(
            [ffmpeg, "-i", str(video)], capture_output=True, text=True
        )
        for line in (result.stderr or "").splitlines():
            if "Duration:" in line:
                stamp = line.split("Duration:")[1].split(",")[0].strip()
                if stamp.startswith("N/A"):
                    continue
                parts = stamp.split(":")
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _extract_frame(video: Path, timestamp: float, target: Path) -> bool:
    from .ffmpeg import resolve_ffmpeg

    try:
        ffmpeg = resolve_ffmpeg()
        subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{max(0.0, timestamp):.3f}",
                "-i", str(video),
                "-frames:v", "1",
                "-q:v", "3",
                str(target),
            ],
            capture_output=True,
            check=True,
        )
        return target.exists()
    except Exception:  # noqa: BLE001
        return False
