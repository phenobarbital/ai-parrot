"""Unit tests for the devloop console engine."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from parrot.cli.devloop.console import DevLoopConsole


# ── Stub models ─────────────────────────────────────────────────────────────

@dataclass
class StubGate:
    gate_id: str = "gate-1"
    kind: str = "plan_approval"
    status: str = "pending"
    title: str = "Approve the plan"
    instructions: str = ""
    node_id: str = "research"
    expires_at: Optional[float] = None


@dataclass
class StubState:
    run_id: str = "run-test"
    phase: str = "research"
    summary: str = "Test"
    work_kind: str = "bug"
    jira_issue_key: str = ""
    pr_url: str = ""
    gates: Dict[str, StubGate] = field(default_factory=dict)
    created_at: float = 0.0
    finished_at: Optional[float] = None


@dataclass
class StubHost:
    state: StubState = field(default_factory=StubState)
    _envelopes: list = field(default_factory=list)

    def replay_since(self, last_seq: int):
        return [e for e in self._envelopes if e.server_seq > last_seq]

    def snapshot(self):
        return None


@dataclass
class StubFlowResult:
    status: str = "completed"
    responses: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)


@dataclass
class StubRuntime:
    runner: Any = None
    flow: Any = None
    dispatcher: Any = None
    jira_toolkit: Any = None
    redis_url: str = ""
    reporter: str = "test@example.com"
    escalation_assignee: str = "escalation@example.com"


class StubRunner:
    def __init__(self):
        self._hosts: Dict[str, StubHost] = {}
        self._active: Set[str] = set()
        self._resolve_gate_calls: list = []
        self._cancel_calls: list = []

    def get_host(self, run_id: str):
        return self._hosts.get(run_id)

    def active_runs(self) -> Set[str]:
        return set(self._active)

    def registry_state(self):
        return MagicMock()

    async def run(self, brief, run_id=None, **kwargs):
        host = StubHost(state=StubState(run_id=run_id or "run-stub"))
        self._hosts[run_id or "run-stub"] = host
        self._active.add(run_id or "run-stub")
        await asyncio.sleep(0.05)
        self._active.discard(run_id or "run-stub")
        return StubFlowResult()

    async def run_revision(self, brief, run_id=None, **kwargs):
        host = StubHost(state=StubState(run_id=run_id or "run-rev"))
        self._hosts[run_id or "run-rev"] = host
        self._active.add(run_id or "run-rev")
        await asyncio.sleep(0.05)
        self._active.discard(run_id or "run-rev")
        return StubFlowResult()

    async def resolve_gate(self, run_id, gate_id, resolution, resolved_by, comment="", **kwargs):
        self._resolve_gate_calls.append({
            "run_id": run_id, "gate_id": gate_id,
            "resolution": resolution, "resolved_by": resolved_by,
            "comment": comment,
        })

    async def cancel_run(self, run_id, requested_by):
        self._cancel_calls.append({"run_id": run_id, "requested_by": requested_by})


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_console(inputs: List[str]) -> tuple[DevLoopConsole, Console, StubRunner]:
    session = AsyncMock()
    session.prompt_async = AsyncMock(side_effect=inputs)
    console = Console(record=True, force_terminal=True, width=120)
    runner = StubRunner()
    dc = DevLoopConsole(console=console, session=session)
    dc._runtime = StubRuntime(runner=runner)
    return dc, console, runner


# ── Tests ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_console_cmd_help():
    dc, console, _ = _make_console([])
    await dc._cmd_help("")
    output = console.export_text()
    assert "Commands" in output
    assert "/runs" in output


@pytest.mark.asyncio
async def test_console_cmd_runs_empty():
    dc, console, _ = _make_console([])
    await dc._cmd_runs("")
    output = console.export_text()
    assert "No runs" in output


@pytest.mark.asyncio
async def test_console_cmd_runs_with_runs():
    dc, console, runner = _make_console([])
    # Add a completed run
    async def fake_run():
        return StubFlowResult()
    task = asyncio.create_task(fake_run())
    await task  # let it complete
    dc._runs["run-123"] = task
    await dc._cmd_runs("")
    output = console.export_text()
    assert "run-123" in output


@pytest.mark.asyncio
async def test_console_cmd_attach():
    dc, console, runner = _make_console([])
    host = StubHost()
    runner._hosts["run-abc"] = host
    from parrot.cli.devloop.renderer import RunView
    dc._views["run-abc"] = RunView(host, console, run_id="run-abc")
    await dc._cmd_attach("run-abc")
    assert dc._active_run_id == "run-abc"
    assert dc._active_view is not None


@pytest.mark.asyncio
async def test_console_cmd_attach_not_found():
    dc, console, _ = _make_console([])
    await dc._cmd_attach("nonexistent")
    output = console.export_text()
    assert "not found" in output


@pytest.mark.asyncio
async def test_console_cmd_cancel():
    dc, console, runner = _make_console([])
    dc._active_run_id = "run-x"
    await dc._cmd_cancel("")
    assert len(runner._cancel_calls) == 1
    assert runner._cancel_calls[0]["run_id"] == "run-x"


@pytest.mark.asyncio
async def test_console_handle_gate_approve():
    dc, console, runner = _make_console(["a", "looks good"])
    dc._active_run_id = "run-g"
    gates = {"gate-1": StubGate(gate_id="gate-1")}
    await dc._handle_gates(gates)
    assert len(runner._resolve_gate_calls) == 1
    call = runner._resolve_gate_calls[0]
    assert call["resolution"] == "approved"
    assert call["comment"] == "looks good"


@pytest.mark.asyncio
async def test_console_handle_gate_reject():
    dc, console, runner = _make_console(["r", "needs work"])
    dc._active_run_id = "run-g"
    gates = {"gate-1": StubGate(gate_id="gate-1")}
    await dc._handle_gates(gates)
    assert len(runner._resolve_gate_calls) == 1
    assert runner._resolve_gate_calls[0]["resolution"] == "rejected"


@pytest.mark.asyncio
async def test_console_handle_gate_conflict():
    dc, console, runner = _make_console(["a", ""])
    dc._active_run_id = "run-g"
    # Make resolve_gate raise
    runner.resolve_gate = AsyncMock(side_effect=ValueError("gate already resolved"))
    gates = {"gate-1": StubGate(gate_id="gate-1")}
    await dc._handle_gates(gates)
    output = console.export_text()
    assert "failed" in output.lower()


@pytest.mark.asyncio
async def test_console_dispatch_command_unknown():
    dc, console, _ = _make_console([])
    await dc._dispatch_command("/foobar")
    output = console.export_text()
    assert "Unknown command" in output


@pytest.mark.asyncio
async def test_console_cmd_quit():
    dc, console, _ = _make_console([])
    await dc._cmd_quit("")
    assert dc._stop is True


@pytest.mark.asyncio
async def test_console_load_brief_file(tmp_path):
    from pydantic import BaseModel, Field

    class SimpleBrief(BaseModel):
        title: str
        count: int = 1

    brief_file = tmp_path / "brief.json"
    brief_file.write_text('{"title": "test brief", "count": 5}')

    dc, _, _ = _make_console([])
    result = dc._load_brief_file(str(brief_file), SimpleBrief)
    assert result.title == "test brief"
    assert result.count == 5
