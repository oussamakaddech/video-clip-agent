from __future__ import annotations

from pathlib import Path

from clipagent.ffmpeg import (
    build_concat_command,
    build_crop_filter,
    build_cut_command,
    build_thumbnail_command,
    escape_filter_path,
    write_concat_file,
)


def test_build_cut_command_contains_expected_flags():
    command = build_cut_command(
        "ffmpeg",
        "video.mp4",
        "out.mp4",
        start=12.5,
        end=42.0,
        width=1080,
        height=1920,
        aspect="9:16",
    )
    assert command[0] == "ffmpeg"
    assert "-ss" in command and "12.500" in command
    assert "-t" in command and "29.500" in command
    video_filter = command[command.index("-vf") + 1]
    assert "scale=1080:1920" in video_filter
    assert "crop=1080:1920" in video_filter
    assert command[-1] == "out.mp4"


def test_build_cut_command_fast_uses_input_seek():
    command = build_cut_command("ffmpeg", "v.mp4", "o.mp4", start=5, end=25, fast=True)
    assert command.index("-ss") < command.index("-i")


def test_build_cut_command_embeds_subtitles():
    command = build_cut_command(
        "ffmpeg",
        "v.mp4",
        "o.mp4",
        start=0,
        end=30,
        subtitles=Path("C:/tmp/clip.srt"),
    )
    video_filter = command[command.index("-vf") + 1]
    assert "subtitles=" in video_filter
    assert "force_style" in video_filter


def test_build_crop_filter_variants():
    assert "crop=1080:1920" in build_crop_filter(1080, 1920)
    assert "(iw-ow)/2" in build_crop_filter(1080, 1920)
    # alignement vertical en haut, centrage horizontal conservé
    assert "crop=1080:1920:(iw-ow)/2:0" in build_crop_filter(1080, 1920, crop="top")
    assert "crop=1080:1920" in build_crop_filter(1080, 1920, crop="fill")


def test_escape_filter_path_handles_windows():
    escaped = escape_filter_path(r"C:\Users\oussama\clip.srt")
    assert "C\\:/Users/oussama/clip.srt" == escaped
    assert "\\[" not in escaped


def test_build_thumbnail_command():
    command = build_thumbnail_command("ffmpeg", "v.mp4", "t.jpg", timestamp=3.5)
    assert "3.500" in command
    assert command[-1] == "t.jpg"


def test_write_concat_file_and_command(tmp_path):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    list_file = write_concat_file(clips, tmp_path / "list.txt")
    content = list_file.read_text(encoding="utf-8")
    assert content.count("file '") == 2
    command = build_concat_command("ffmpeg", list_file, tmp_path / "out.mp4")
    assert "-f" in command and "concat" in command
    assert command[-1] == str(tmp_path / "out.mp4")
