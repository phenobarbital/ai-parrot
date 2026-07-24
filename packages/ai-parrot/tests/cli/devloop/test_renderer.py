"""Unit tests for the devloop run renderer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from parrot.cli.devloop.renderer import RunView


# ── Stub models ─────────────────────────────────────────────────────────────

@dataclass
class StubGate:
    gate_id: str = "gate-1"
    kind: str = "plan_approval"
    status: str = "pending"
    title: str = "Approve the plan"
    node_id: str = "research"


@dataclass
class StubState:
    run_id: str = "run-abc123"
    phase: str = "research"
    summary: str = "Test run"
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


@dataclass
class StubEnvelope:
    channel: str = "run://run-abc123"
    server_seq: int = 0
    action: Any = field(default_factory=StubAction)
    origin: Any = None


@dataclass
class StubHost:
    state: StubState = field(default_factory=StubState)
    _envelopes: List[StubEnvelope] = field(default_factory=list)

    def replay_since(self, last_seq: int) -> List[StubEnvelope]:
        return [e for e in self._envelopes if e.server_seq > last_seq]

    def snapshot(self):
        return None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_action(type_: str, **kwargs) -> StubAction:
    a = StubAction(type=type_)
    for k, v in kwargs.items():
        setattr(a, k, v)
    return a


def _make_view(envelopes: List[StubEnvelope]) -> RunView:
    host = StubHost(_envelopes=envelopes)
    console = Console(record=True, force_terminal=True, width=120)
    return RunView(host, console, run_id="run-test")


# ── Tests ───────────────────────────────────────────────────────────────────

def test_renderer_maps_node_started():
    env = StubEnvelope(server_seq=1, action=_make_action("node/started", node_id="research"))
    view = _make_view([env])
    view.poll_once()
    assert view._last_seq == 1
    assert len(view._renderables) >= 1


def test_renderer_maps_node_completed():
    env = StubEnvelope(server_seq=1, action=_make_action("node/completed", node_id="research", summary={}))
    view = _make_view([env])
    view.poll_once()
    assert any("completed" in str(r) for r in view._renderables)


def test_renderer_maps_node_failed():
    env = StubEnvelope(server_seq=1, action=_make_action("node/failed", node_id="qa", error="assertion failed"))
    view = _make_view([env])
    view.poll_once()
    assert any("FAILED" in str(r) for r in view._renderables)


def test_renderer_maps_run_created():
    env = StubEnvelope(server_seq=1, action=_make_action("run/created", run_id="run-x", work_kind="bug", summary="Fix", revision=False))
    view = _make_view([env])
    view.poll_once()
    assert any("Run created" in str(r) for r in view._renderables)


def test_renderer_maps_run_closed():
    env = StubEnvelope(server_seq=1, action=_make_action("run/closed", outcome="succeeded", jira_issue_key="", pr_url=""))
    view = _make_view([env])
    view.poll_once()
    assert any("succeeded" in str(r) for r in view._renderables)


def test_renderer_maps_gate_opened():
    gate = StubGate(gate_id="g1", kind="plan_approval", title="Approve plan")
    env = StubEnvelope(server_seq=1, action=_make_action("gate/opened", gate=gate))
    view = _make_view([env])
    view.poll_once()
    # Panel's str() includes content; check for gate_id or "Approval"
    from rich.panel import Panel
    assert any(isinstance(r, Panel) for r in view._renderables)


def test_renderer_maps_gate_resolved():
    env = StubEnvelope(server_seq=1, action=_make_action("gate/resolved", gate_id="g1", resolution="approved", resolved_by="user", comment="lgtm"))
    view = _make_view([env])
    view.poll_once()
    assert any("approved" in str(r) for r in view._renderables)


def test_renderer_maps_jira_linked():
    env = StubEnvelope(server_seq=1, action=_make_action("jira/linked", issue_key="OPS-123"))
    view = _make_view([env])
    view.poll_once()
    assert any("OPS-123" in str(r) for r in view._renderables)


def test_renderer_maps_pr_linked():
    env = StubEnvelope(server_seq=1, action=_make_action("pr/linked", pr_url="https://github.com/org/repo/pull/42", changeset="abc"))
    view = _make_view([env])
    view.poll_once()
    assert any("pull/42" in str(r) for r in view._renderables)


def test_renderer_maps_dispatch_tool_use():
    env = StubEnvelope(server_seq=1, action=_make_action("dispatch/tool_use", node_id="development", tool_name="Edit"))
    view = _make_view([env])
    view.poll_once()
    assert any("Edit" in str(r) for r in view._renderables)


def test_renderer_unknown_action_tolerated():
    env = StubEnvelope(server_seq=1, action=_make_action("future/unknown_action"))
    view = _make_view([env])
    view.poll_once()
    assert view._last_seq == 1
    assert len(view._renderables) >= 1


def test_renderer_replay_cursor_never_rerender():
    envs = [
        StubEnvelope(server_seq=1, action=_make_action("node/started", node_id="research")),
        StubEnvelope(server_seq=2, action=_make_action("node/completed", node_id="research", summary={})),
    ]
    view = _make_view(envs)
    view.poll_once()
    count_after_first = len(view._renderables)
    # Second poll with same envelopes — nothing new
    view.poll_once()
    assert len(view._renderables) == count_after_first


def test_renderer_pending_gates():
    host = StubHost(state=StubState(
        gates={"g1": StubGate(status="pending"), "g2": StubGate(status="approved")}
    ))
    view = RunView(host, Console(record=True, force_terminal=True, width=120))
    pending = view.pending_gates()
    assert "g1" in pending
    assert "g2" not in pending


def test_renderer_pause_resume():
    view = _make_view([])
    view.pause()
    assert view._paused is True
    view.resume()
    assert view._paused is False
