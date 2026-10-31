"""FEAT-783 TASK-4993 — Codex usage codec (AC-8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import AsyncMock

import pytest

from parrot.core.events.lifecycle.events.client import AfterClientCallEvent
from parrot.flows.dev_loop import (
    CodexCodeDispatcher,
    CodexCodeDispatchProfile,
    DevelopmentOutput,
    DispatchExecutionError,
    ResearchOutput,
)
from parrot.flows.dev_loop.dispatchers.codex_usage import CodexUsageCodec

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "codex_usage"


def _feed(name: str) -> CodexUsageCodec:
    codec = CodexUsageCodec()
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            codec.observe(json.loads(line))
    return codec


def test_terminal_usage_is_reported() -> None:
    codec = _feed("terminal.jsonl")
    usage = codec.result()

    assert usage is not None
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 300
    assert usage.cache_read_tokens == 800
    assert usage.reasoning_output_tokens == 125
    assert codec.source_cost_usd == pytest.approx(0.0025)
    assert codec.pricing_policy() == "subscription"


def test_nested_usage_is_found() -> None:
    codec = _feed("nested.jsonl")
    usage = codec.result()

    assert usage is not None
    assert usage.input_tokens == 42
    assert usage.output_tokens == 9
    assert usage.cache_read_tokens == 12
    assert usage.reasoning_output_tokens == 3
    assert codec.source_cost_usd == pytest.approx(0.00075)
    assert codec.pricing_policy() == "billed"


def test_missing_usage_returns_none() -> None:
    assert _feed("missing.jsonl").result() is None


def test_repeated_terminal_not_double_counted() -> None:
    usage = _feed("repeated.jsonl").result()

    assert usage is not None
    assert usage.input_tokens == 75
    assert usage.output_tokens == 20
    assert usage.cache_read_tokens == 25
    assert usage.reasoning_output_tokens == 5


def test_last_terminal_observation_wins() -> None:
    codec = CodexUsageCodec()
    codec.observe({"usage": {"input_tokens": 10, "output_tokens": 2}})
    codec.observe({"usage": {"input_tokens": 20, "output_tokens": 4}})

    usage = codec.result()
    assert usage is not None
    assert usage.input_tokens == 20
    assert usage.output_tokens == 4


class _AsyncBytesStream:
    """Minimal stdout/stderr stream used by the dispatcher regression test."""

    def __init__(self, chunks: Sequence[str]) -> None:
        self._chunks = [chunk.encode("utf-8") for chunk in chunks]

    async def readline(self) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    async def read(self, _size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        chunks, self._chunks = self._chunks, []
        return b"".join(chunks)


class _FakeProcess:
    """Codex process double that exits unsuccessfully after yielding usage."""

    def __init__(self, stdout_lines: Sequence[str]) -> None:
        self.stdout = _AsyncBytesStream(stdout_lines)
        self.stderr = _AsyncBytesStream(["provider rejected output"])

    async def wait(self) -> int:
        return 2


class _CapturingRegistry:
    """Event-registry double retaining both local and global-forward calls."""

    def __init__(self) -> None:
        self.events: list[Any] = []
        self.forwarded: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)

    def forward_to_global(self, event: Any) -> None:
        self.forwarded.append(event)


@pytest.mark.asyncio
async def test_dispatcher_emits_one_event_on_failure_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [f"{line}\n" for line in (FIXTURES / "terminal.jsonl").read_text(encoding="utf-8").splitlines()]
    process = _FakeProcess(lines)
    registry = _CapturingRegistry()
    dispatcher = CodexCodeDispatcher(
        max_concurrent=1,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")
    monkeypatch.setattr(dispatcher, "_ensure_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(dispatcher, "_create_process", AsyncMock(return_value=process))
    monkeypatch.setattr("parrot.flows.dev_loop.dispatchers.codex.conf.WORKTREE_BASE_PATH", str(tmp_path))
    dispatcher.set_event_registry_resolver({"run-1": registry}.get)

    brief = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/example.spec.md",
        feat_id="FEAT-1",
        branch_name="feat-example",
        worktree_path=str(tmp_path),
        log_excerpts=[],
    )

    with pytest.raises(DispatchExecutionError, match="exit code 2"):
        await dispatcher.dispatch(
            brief=brief,
            profile=CodexCodeDispatchProfile(model="gpt-5.5"),
            output_model=DevelopmentOutput,
            run_id="run-1",
            node_id="development.w1",
            cwd=str(tmp_path),
        )

    assert dispatcher.event_registry_resolver is not None
    assert len(registry.events) == 1
    assert registry.forwarded == registry.events
    event = registry.events[0]
    assert isinstance(event, AfterClientCallEvent)
    assert event.client_name == "codex"
    assert event.model == "gpt-5.5"
    assert event.input_tokens == 1200
    assert event.output_tokens == 300
    assert event.cache_read_tokens == 800
    assert event.reasoning_output_tokens == 125
    assert event.source_cost_usd == pytest.approx(0.0025)
    assert event.pricing_policy == "subscription"


def test_real_codex_exec_stream() -> None:
    """Spike S1: a stream captured from a real ``codex exec --json`` run (codex CLI, 2026-11-01)."""
    usage = _feed("real_exec.jsonl").result()

    assert usage is not None
    assert usage.input_tokens == 30115
    assert usage.cache_read_tokens == 27008
    assert usage.output_tokens == 51


def test_structured_tool_output_is_not_mistaken_for_usage() -> None:
    """A usage-shaped dict inside an item payload (MCP tool result) is ignored."""
    codec = _feed("structured_tool_decoy.jsonl")
    usage = codec.result()

    assert usage is not None
    assert usage.input_tokens == 30115
    assert codec.source_cost_usd is None
    assert codec.pricing_policy() is None
