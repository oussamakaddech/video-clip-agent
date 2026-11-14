from __future__ import annotations

import asyncio
import json

import pytest

from clipagent.config import Settings
from clipagent.llm import AgentContext, build_agent, parse_llm_json
from clipagent.models import ClipProposal
from clipagent.transcript import Transcript, parse_srt

SRT = """1
00:00:00,000 --> 00:00:06,000
Bonjour, voici une transcription de test.

2
00:00:06,000 --> 00:00:18,000
La clé c'est de commencer par une accroche forte et claire.
"""


def _context() -> AgentContext:
    transcript = Transcript(segments=parse_srt(SRT))
    return AgentContext(transcript=transcript, duration=18.0, min_clip=10, max_clip=30, max_clips=3)


def test_agent_context_add_counts_proposals():
    context = _context()
    assert context.add(ClipProposal(start=0, end=10, title="A")) == 1
    assert context.add(ClipProposal(start=20, end=30, title="B")) == 2
    assert len(context.proposals) == 2


def test_parse_llm_json_from_dict():
    proposals = parse_llm_json({"clips": [{"start": 1, "end": 5, "title": "T", "score": 0.9, "tags": ["x"]}]})
    assert len(proposals) == 1
    assert proposals[0].start == 1.0
    assert proposals[0].tags == ["x"]


def test_parse_llm_json_from_string():
    payload = json.dumps([{"start": "2", "end": "8", "title": "T"}])
    proposals = parse_llm_json(payload)
    assert proposals[0].start == 2.0
    assert proposals[0].end == 8.0


def test_parse_llm_json_ignores_garbage():
    assert parse_llm_json("pas du json") == []
    assert parse_llm_json(None) == []
    assert parse_llm_json([{"start": "x"}]) == []


def test_agent_is_built_with_expected_tools():
    pytest.importorskip("agents")
    settings = Settings.from_env(api_key="sk-test", model="gpt-4o-mini")
    agent = build_agent(settings, _context())
    names = [getattr(tool, "name", None) for tool in agent.tools]
    assert names == ["read_transcript", "read_transcript_head", "propose_clip", "finish_selection"]


def test_agent_tools_behave_as_expected():
    pytest.importorskip("agents")
    from agents.tool_context import ToolContext

    settings = Settings.from_env(api_key="sk-test")
    context = _context()
    agent = build_agent(settings, context)
    tools = {getattr(tool, "name", ""): tool for tool in agent.tools}

    async def invoke(name: str, args: dict):
        tool_context = ToolContext(
            context=context,
            tool_name=name,
            tool_call_id="call_test",
            tool_arguments=json.dumps(args),
        )
        return await tools[name].on_invoke_tool(tool_context, json.dumps(args))

    window = asyncio.run(invoke("read_transcript", {"start": 0, "end": 18}))
    assert "accroche" in window

    head = asyncio.run(invoke("read_transcript_head", {"limit": 1}))
    assert head.count("\n") == 0

    message = asyncio.run(
        invoke(
            "propose_clip",
            {"start": 6.0, "end": 18.0, "title": "Accroche", "reason": "fort", "score": 0.8, "tags": ["clé"]},
        )
    )
    assert "Proposition #1" in message
    assert context.proposals[0].title == "Accroche"

    done = asyncio.run(invoke("finish_selection", {}))
    assert "terminée" in done
    assert context.finished is True
