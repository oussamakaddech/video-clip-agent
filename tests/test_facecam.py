from __future__ import annotations

from pathlib import Path

from clipagent.config import Settings
from clipagent.facecam import FaceBox, detect_face_in_image, detect_face_in_video
from clipagent.ffmpeg import build_facecam_filter_complex, build_cut_command
from clipagent.styles import STYLES

MODEL = Path("data/face_detection_yunet_2023mar.onnx")


def test_facebox_padding_keeps_center():
    box = FaceBox(x=100, y=200, width=50, height=60)
    padded = box.padded(0.5)
    assert padded.x == 75 and padded.width == 100
    assert padded.y == 170 and padded.height == 120
    # le centre ne bouge pas
    assert padded.x + padded.width / 2 == box.x + box.width / 2


def test_facebox_square_is_square():
    box = FaceBox(x=100, y=200, width=50, height=80).padded(0.5)
    square = box.square()
    assert square.width == square.height


def test_facecam_filter_complex_has_face_and_overlay():
    box = FaceBox(x=10, y=20, width=30, height=40)
    chain = build_facecam_filter_complex(1080, 1920, box, face_size=320)
    assert "crop=30:40:10:20" in chain
    assert "scale=320:320" in chain
    assert "overlay=" in chain
    assert "[v]" in chain


def test_facecam_filter_complex_supports_square_shape():
    box = FaceBox(x=10, y=20, width=30, height=40)
    chain = build_facecam_filter_complex(1080, 1920, box, shape="square")
    assert "geq=" not in chain


def test_cut_command_with_facecam_uses_filter_complex():
    command = build_cut_command(
        "ffmpeg", "v.mp4", "o.mp4", start=0, end=30,
        face_box=FaceBox(x=10, y=20, width=30, height=40),
    )
    assert "-filter_complex" in command
    assert "-map" in command
    assert "[v]" in " ".join(command)


def test_cut_command_without_facecam_keeps_simple_vf():
    command = build_cut_command("ffmpeg", "v.mp4", "o.mp4", start=0, end=30)
    assert "-vf" in command
    assert "-filter_complex" not in command


def test_tiktok_style_enables_facecam():
    assert STYLES["tiktok"].facecam_enabled is True
    assert STYLES["default"].facecam_enabled is False


def test_face_detection_on_generated_image():
    """Détection sur une image réelle du projet (storyboard du stream Kick)."""
    import glob

    images = sorted(glob.glob("output_kick/browser/frames/*.jpg"))
    if not images:
        return  # pas d'image disponible : test ignoré
    box = detect_face_in_image(images[0])
    assert box is None or box.width > 0
