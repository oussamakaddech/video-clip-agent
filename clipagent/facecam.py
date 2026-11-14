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
    frame_width: int = 0      # dimensions de l'image d'origine (0 = inconnu)
    frame_height: int = 0

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
            frame_width=self.frame_width,
            frame_height=self.frame_height,
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
            frame_width=self.frame_width,
            frame_height=self.frame_height,
        )

    def clamped(self, frame_width: int, frame_height: int) -> "FaceBox":
        """Ramène la boîte à l'intérieur de l'image (un crop hors cadre échoue)."""
        frame_width = frame_width or self.frame_width
        frame_height = frame_height or self.frame_height
        if frame_width <= 0 or frame_height <= 0:
            return self
        width = max(8, min(self.width, frame_width))
        height = max(8, min(self.height, frame_height))
        x = max(0, min(self.x, frame_width - width))
        y = max(0, min(self.y, frame_height - height))
        return FaceBox(
            x=x, y=y, width=width, height=height, score=self.score,
            frame_width=frame_width, frame_height=frame_height,
        )

    def camera_region(self, ratio: float = 1.2) -> "FaceBox":
        """Région « caméra » élargie autour du visage (tête + épaules).

        C'est la zone recadrée pour le layout « caméra plein cadre en bas » :
        le visage seul est trop serré pour un rendu naturel.
        """
        width = int(self.width * (1 + 2 * ratio))
        height = int(self.height * (1 + 2 * ratio))
        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        region = FaceBox(
            x=int(max(0, cx - width / 2)),
            y=int(max(0, cy - height / 2)),
            width=width,
            height=height,
            score=self.score,
            frame_width=self.frame_width,
            frame_height=self.frame_height,
        )
        return region.clamped(self.frame_width, self.frame_height)

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


def detect_faces_in_image(path: str | Path) -> list[FaceBox]:
    """Renvoie **tous** les visages détectés dans une image."""
    import cv2

    image = cv2.imread(str(path))
    if image is None:
        return []
    height, width = image.shape[:2]
    detector = _detector()
    detector.setInputSize((width, height))
    _ok, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        return []
    boxes: list[FaceBox] = []
    for face in faces:
        box = FaceBox(
            x=int(face[0]),
            y=int(face[1]),
            width=int(face[2]),
            height=int(face[3]),
            score=float(face[-1]),
            frame_width=width,
            frame_height=height,
        )
        boxes.append(box.clamped(width, height))
    return boxes


def detect_face_in_image(path: str | Path) -> FaceBox | None:
    """Cherche un visage dans une image (le plus grand trouvé).

    La boîte est bornée à l'image : une détection sur une image périmée ou
    d'une résolution différente ne peut pas casser le recadrage ffmpeg.
    """
    boxes = detect_faces_in_image(path)
    if not boxes:
        return None
    return max(boxes, key=lambda b: b.width * b.height)


def _region_motion(current, previous, box: FaceBox) -> float:
    """Variation moyenne des pixels dans la boîte entre deux images."""
    import numpy as np

    if previous is None:
        return 0.0
    x, y = box.x, box.y
    w, h = box.width, box.height
    a = current[y : y + h, x : x + w]
    b = previous[y : y + h, x : x + w]
    if a.size == 0 or b.size == 0 or a.shape != b.shape:
        return 0.0
    return float(np.abs(a.astype("int16") - b.astype("int16")).mean() / 255.0)


def detect_face_in_video(
    video: str | Path,
    *,
    samples: int = 12,
    start: float = 0.0,
    duration: float | None = None,
    min_size: int = 14,
) -> FaceBox | None:
    """Cherche le visage du streamer dans la vidéo.

    Un stream contient souvent plusieurs visages : l'illustration d'un site,
    une photo de profil, etc. On privilégie la **webcam du streamer**, donc la
    face la plus **persistante** (présente dans le plus d'images) et la plus
    **mobile** (une vraie caméra bouge, une illustration reste figée).
    """
    import cv2

    video = Path(video)
    if not video.exists():
        return None

    total = duration or _probe_duration(video)
    if total <= 0:
        # Les webm produits par MediaRecorder n'ont pas de durée dans l'en-tête
        # (« Duration: N/A ») : on échantillonne le début du fragment.
        total = 30.0

    times = [start + (i + 0.5) * (total / max(1, samples)) for i in range(samples)]
    tmp_dir = Path(video).parent / "_facecam_frames"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    detections: dict[tuple, list[tuple[FaceBox, float]]] = {}
    previous_image = None

    try:
        for index, moment in enumerate(times):
            frame_path = tmp_dir / f"probe_{index:02d}.jpg"
            frame_path.unlink(missing_ok=True)   # pas de frame périmée
            if not _extract_frame(video, moment, frame_path):
                continue
            image = cv2.imread(str(frame_path))
            if image is None:
                continue
            for box in detect_faces_in_image(frame_path):
                if box.width < min_size or box.height < min_size:
                    continue
                motion = _region_motion(image, previous_image, box)
                key = (box.x // 24, box.y // 24, box.width // 24, box.height // 24)
                detections.setdefault(key, []).append((box, motion))
            previous_image = image
            frame_path.unlink(missing_ok=True)
    finally:
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    if not detections:
        return None

    def group_score(entries) -> float:
        presence = len(entries)
        motion = sum(m for _box, m in entries) / presence
        # présence × mobilité : la webcam du streamer gagne sur une illustration
        return presence * (1.0 + motion * 6.0)

    best_entries = max(detections.values(), key=group_score)
    return best_entries[0][0]


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

    target.unlink(missing_ok=True)
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
        return target.exists() and target.stat().st_size > 0
    except Exception:  # noqa: BLE001
        target.unlink(missing_ok=True)
        return False
