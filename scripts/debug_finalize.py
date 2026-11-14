"""Diagnostic : résolution des fragments dans finalize_from_fragments."""

from pathlib import Path

from clipagent.browser_pipeline import finalize_from_fragments
from clipagent.cli import _plan_from_json
from clipagent.config import Settings

plan = _plan_from_json("output_kick2/clips_plan.json")
settings = Settings.from_env(style="tiktok")
plan = finalize_from_fragments(
    plan,
    Path("output_kick2/work"),
    settings,
    output_dir="output_kick2_test",
    padding=1.5,
    language="en",
)
for warning in plan.warnings:
    print(" !", warning[:130])
for clip in plan.clips:
    print(" #", clip.index, clip.path)
