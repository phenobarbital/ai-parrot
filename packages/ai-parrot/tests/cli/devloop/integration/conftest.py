"""Fixtures for devloop console integration tests.

Provides a scripted runner that exercises the console↔runner↔host
pipeline without requiring Redis, claude CLI, Jira, or any external
services.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock

import pytest
from rich.console import Console


# ── Scripted SessionHost stub ─────────────────────────────────────────────

@dataclass
class StubGate:
    gate_id: str = "gate-plan"
    kind: str = "plan_approval"
    status: str = "pending"
    title: str = "Approve the execution plan"
    instructions: str = "Review the plan and approve."
    node_id: str = "research"
    expires_at: Optional[float] = None


@dataclass
class StubState:
    run_id: str = ""
    phase: str = "research"
    summary: str = "Integration test run"
    work_kind: str = "bug"
    jira_issue_key: str = ""
    pr_url: str = ""
    gates: Dict[str, StubGate] = field(default_factory=dict)
    created_at: float = 0.0
    finished_at: Optional[float] = None


@dataclass
class StubAction:
    type: str = ""
    ts: float = 0.0

    def __getattr__(self, name: str) -> Any:
        return getattr(self, name, "")


@dataclass
class StubEnvelope:
    channel: str = ""
    server_seq: int = 0
    action: Any = field(default_factory=StubAction)
    origin: Any = None


class StubHost:
    """Scripted host that emits a pre-programmed sequence of envelopes."""

    def __init__(self, run_id: str, script: List[StubEnvelope] | None = None):
        self.state = StubState(run_id=run_id)
        self._script = list(script or [])

    def replay_since(self, last_seq: int) -> List[StubEnvelope]:
        return [e for e in self._script if e.server_seq > last_seq]

    def snapshot(self) -> None:
        return None


@dataclass
class StubFlowResult:
    status: str = "completed"
    responses: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    output: Any = None


# ── Scripted Runner ───────────────────────────────────────────────────────

class ScriptedRunner:
    """A runner that simulates flow execution with scripted envelopes.

    The ``gate_event`` is set when a gate is opened so the test can drive
    gate resolution through the console.
    """

    def __init__(self):
        self._hosts: Dict[str, StubHost] = {}
        self._active: Set[str] = set()
        self._resolve_calls: List[dict] = []
        self._cancel_calls: List[dict] = []
        self.gate_event: asyncio.Event = asyncio.Event()

    def get_host(self, run_id: str) -> Optional[StubHost]:
        return self._hosts.get(run_id)

    def active_runs(self) -> Set[str]:
        return set(self._active)

    @property
    def registry_state(self):
        return None

    async def run(self, brief: Any, *, run_id: str | None = None, **kwargs) -> StubFlowResult:
        rid = run_id or "run-integ"
        script = _make_action_script(rid)
        host = StubHost(rid, script=script)
        self._hosts[rid] = host
        self._active.add(rid)

        # Simulate node execution with pauses
        await asyncio.sleep(0.05)

        # Open a gate and wait for resolution
        host.state.gates["gate-plan"] = StubGate(gate_id="gate-plan")
        self.gate_event.set()

        # Wait until gate is resolved (or timeout)
        for _ in range(50):
            gate = host.state.gates.get("gate-plan")
            if gate and gate.status != "pending":
                break
            await asyncio.sleep(0.05)

        # Finish up
        host.state.phase = "close"
        host.state.jira_issue_key = "INTEG-1"
        host.state.pr_url = "https://github.com/org/repo/pull/99"
        host.state.finished_at = 1.0
        self._active.discard(rid)
        return StubFlowResult(status="completed")

    async def run_revision(self, brief: Any, *, run_id: str | None = None, **kwargs) -> StubFlowResult:
        rid = run_id or "run-rev"
        host = StubHost(rid, script=[
            _envelope(rid, 1, "run/created", run_id=rid, work_kind="bug", summary="Revision", revision=True),
            _envelope(rid, 2, "node/started", node_id="development"),
            _envelope(rid, 3, "node/completed", node_id="development", summary={}),
            _envelope(rid, 4, "run/closed", outcome="succeeded", jira_issue_key="", pr_url=""),
        ])
        self._hosts[rid] = host
        self._active.add(rid)
        await asyncio.sleep(0.1)
        host.state.finished_at = 1.0
        self._active.discard(rid)
        return StubFlowResult(status="completed")

    async def resolve_gate(self, run_id: str, gate_id: str, *, resolution: str,
                           resolved_by: str, comment: str = "", **kwargs) -> None:
        self._resolve_calls.append({
            "run_id": run_id, "gate_id": gate_id,
            "resolution": resolution, "resolved_by": resolved_by,
        })
        host = self._hosts.get(run_id)
        if host:
            gate = host.state.gates.get(gate_id)
            if gate:
                gate.status = resolution

    async def cancel_run(self, run_id: str, requested_by: str) -> None:
        self._cancel_calls.append({"run_id": run_id, "requested_by": requested_by})


# ── Runtime fixture ───────────────────────────────────────────────────────

@dataclass
class StubRuntime:
    runner: ScriptedRunner
    flow: Any = None
    dispatcher: Any = None
    jira_toolkit: Any = None
    redis_url: str = ""
    reporter: str = "test@example.com"
    escalation_assignee: str = "oncall@example.com"


@pytest.fixture
def scripted_runner() -> ScriptedRunner:
    return ScriptedRunner()


@pytest.fixture
def stub_runtime(scripted_runner: ScriptedRunner) -> StubRuntime:
    return StubRuntime(runner=scripted_runner)


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_action(**kwargs) -> StubAction:
    a = StubAction()
    for k, v in kwargs.items():
        object.__setattr__(a, k, v)
    return a


def _envelope(channel_run_id: str, seq: int, action_type: str, **action_kwargs) -> StubEnvelope:
    action = _make_action(type=action_type, **action_kwargs)
    return StubEnvelope(
        channel=f"run://{channel_run_id}",
        server_seq=seq,
        action=action,
    )


def _make_action_script(run_id: str) -> List[StubEnvelope]:
    return [
        _envelope(run_id, 1, "run/created", run_id=run_id, work_kind="bug",
                  summary="Fix sync issue", revision=False),
        _envelope(run_id, 2, "node/started", node_id="research"),
        _envelope(run_id, 3, "node/completed", node_id="research", summary={}),
        _envelope(run_id, 4, "node/started", node_id="development"),
        _envelope(run_id, 5, "dispatch/tool_use", node_id="development", tool_name="Edit"),
        _envelope(run_id, 6, "node/completed", node_id="development", summary={}),
        _envelope(run_id, 7, "gate/opened", gate=StubGate()),
        _envelope(run_id, 8, "node/started", node_id="qa"),
        _envelope(run_id, 9, "node/completed", node_id="qa", summary={}),
        _envelope(run_id, 10, "jira/linked", issue_key="INTEG-1"),
        _envelope(run_id, 11, "pr/linked", pr_url="https://github.com/org/repo/pull/99", changeset="abc"),
        _envelope(run_id, 12, "run/closed", outcome="succeeded", jira_issue_key="INTEG-1", pr_url=""),
    ]
