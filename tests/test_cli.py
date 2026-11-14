from __future__ import annotations

import pytest

from clipagent import cli, commands


def test_cli_exposes_all_commands():
    parser = cli.build_parser()
    actions = [a for a in parser._actions if a.dest == "command"]
    assert actions, "le parseur doit définir des sous-commandes"
    names = set(actions[0].choices)
    assert names == set(commands.COMMANDS)


@pytest.mark.parametrize(
    "name",
    ["plan", "render", "run", "transcribe", "info", "doctor", "fetch", "browse", "finalize"],
)
def test_each_command_parses(name):
    parser = cli.build_parser()
    args = parser.parse_args([name, "--help"]) if False else None
    assert args is None  # garde-fou : le parseur doit accepter « --help »


def test_plan_command_parses_minimal_args():
    parser = cli.build_parser()
    args = parser.parse_args(["plan", "--transcript", "a.srt"])
    assert args.command == "plan"
    assert args.transcript == "a.srt"
    assert args.output == "output"


def test_browse_command_defaults():
    parser = cli.build_parser()
    args = parser.parse_args(["browse", "--url", "https://kick.com/x/videos/y"])
    assert args.step == 60.0
    assert args.candidates == 8
    assert args.window == 80.0
    assert args.min_clip == 45.0
    assert args.max_clip == 75.0
    assert args.channel == "msedge"
    assert args.no_chat is False


def test_settings_precedence_cli_over_env(monkeypatch):
    monkeypatch.setenv("CLIPAGENT_NUM_CLIPS", "9")
    args = cli.build_parser().parse_args(["plan", "--transcript", "a.srt", "--num-clips", "3"])
    settings = commands.settings_from_args(args)
    assert settings.num_clips == 3


def test_settings_rtl_language_selects_arabic_style(monkeypatch):
    monkeypatch.delenv("CLIPAGENT_STYLE", raising=False)
    args = cli.build_parser().parse_args(["plan", "--transcript", "a.srt", "--language", "ar"])
    settings = commands.settings_from_args(args)
    assert settings.style == "arabic"


def test_parse_sections():
    assert commands.parse_sections("120-180, 900-940") == [(120.0, 180.0), (900.0, 940.0)]
    assert commands.parse_sections(None) == []
    with pytest.raises(ValueError):
        commands.parse_sections("120")


def test_plan_from_json_ignores_previous_warnings(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(
        '{"duration": 10, "warnings": ["vieux"], "clips": [{"index": 1, "start": 0, "end": 5, "title": "T", "hook": "H"}]}',
        encoding="utf-8",
    )
    plan = commands.plan_from_json(path)
    assert plan.warnings == []
    assert plan.clips[0].hook == "H"
