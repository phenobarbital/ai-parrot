"""End-to-end legibility integration tests (FEAT-496 TASK-2734).

Every prior FEAT-496 task tests its own layer in isolation. This module
tests the SEAM between them — the class of defect the feature exists to
fix: `payload["tools"]` written by the dispatcher, `payload["tool_name"]`
read by the reducer, `keys[0]=value` rendered by the console. Each piece
was internally consistent; the defect lived in the mismatch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from parrot.flows.dev_loop.agent_pool import DevAgentPool
from parrot.flows.dev_loop.dispatchers._shared import (
    _DISPATCH_LABELS_CTX,
    bind_labels,
    normalize_payload,
)
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher
from parrot.flows.dev_loop.dispatchers.gemini import GeminiCodeDispatcher
from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    ResearchOutput,
)
from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    RunCreated,
    session_channel,
)
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer
from parrot.flows.dev_loop.task_scheduler import TaskRef

KINDS = [
    "dispatch.queued",
    "dispatch.started",
    "dispatch.message",
    "dispatch.tool_use",
    "dispatch.tool_result",
    "dispatch.output_invalid",
    "dispatch.failed",
    "dispatch.completed",
]

ALL_DISPATCHER_CLASSES = [
    ClaudeCodeDispatcher,
    CodexCodeDispatcher,
    GeminiCodeDispatcher,
    GoogleCodingDispatcher,
    LLMCodeDispatcher,
]


def _dispatcher(cls):
    kwargs = {"max_concurrent": 1, "redis_url": "redis://localhost:6379/0", "stream_ttl_seconds": 300}
    return cls(**kwargs)


async def _fake_redis():
    r = AsyncMock()
    r.xadd = AsyncMock(return_value=b"1-0")
    return r


# ---------------------------------------------------------------------------
# Claude message-sequence classes (mirrors test_claude_dispatcher_events.py)
# ---------------------------------------------------------------------------


class ToolUseBlock:
    def __init__(self, name, id_, input_):
        self.name, self.id, self.input = name, id_, input_


class ToolResultBlock:
    def __init__(self, tool_use_id, content="ok", is_error=False):
        self.tool_use_id, self.content, self.is_error = tool_use_id, content, is_error


class TextBlock:
    def __init__(self, text):
        self.text = text


class AssistantMessage:
    def __init__(self, content):
        self.content = content


class UserMessage:
    def __init__(self, content):
        self.content = content


class SystemMessage:
    subtype = "init"
    model = "claude-opus-5"
    cwd = "/wt/feat-496"
    session_id = "s1"
    tools = ["Read", "Bash"]
    mcp_servers = []
    content = None


class ResultMessage:
    subtype = "success"
    num_turns = 12
    duration_ms = 63000
    total_cost_usd = 0.42
    content = None


class TestClaudeStreamLegibility:
    """FEAT-496 AC1/AC2 — the exact reported bug, over a realistic sequence."""

    async def test_no_payload_is_uninformative(self, monkeypatch):
        d = _dispatcher(ClaudeCodeDispatcher)
        captured = []

        async def fake_publish(self, stream_key, *, kind, run_id, node_id, payload):
            captured.append((kind, normalize_payload(kind, payload)))

        monkeypatch.setattr(ClaudeCodeDispatcher, "_publish_event", fake_publish)

        for msg in [
            SystemMessage(),
            AssistantMessage([TextBlock("working")]),
            AssistantMessage([ToolUseBlock("Bash", "toolu_x", {"command": "pytest"})]),
            UserMessage([ToolResultBlock("toolu_x")]),
            ResultMessage(),
        ]:
            await d._publish_message_event("k", msg, "run-1", "development.w1")

        for _kind, payload in captured:
            assert payload["summary"], f"no summary: {payload}"
            assert set(payload) - {"message_class"}, f"uninformative payload: {payload}"
            for key, value in payload.items():
                if key == "tool_use_id":
                    continue
                assert not (isinstance(value, str) and value.startswith("toolu_")), (
                    f"an opaque tool id leaked into display field {key!r}: {value!r}"
                )


# ---------------------------------------------------------------------------
# Pool wave -> task identity, no cross-talk
# ---------------------------------------------------------------------------


class _LabelledRecordingDispatcher:
    """Mimics a real dispatcher's internal label-bind + normalize_payload
    pipeline (ContextVar bind, publish through normalize_payload, reset),
    without any Redis/session-state I/O — the seam under test is
    "does DispatchLabels actually reach a published payload", not the
    transport."""

    def __init__(self):
        self.published = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd,
                       session_host=None, labels=None):
        token = bind_labels(labels)
        try:
            payload = normalize_payload("dispatch.tool_use", {"tool_name": "Read"})
            self.published.append((node_id, payload))
        finally:
            _DISPATCH_LABELS_CTX.reset(token)
        return DevelopmentOutput(files_changed=[], commit_shas=[], summary=brief.task_id)


def _research():
    return ResearchOutput(
        jira_issue_key="OPS-1", spec_path="sdd/specs/x.spec.md", feat_id="FEAT-496",
        branch_name="feat-496-fix", worktree_path="/tmp/wt",
    )


class TestPoolTaskIdentity:
    """FEAT-496 AC5 — every seat's published events carry ITS OWN task_id."""

    async def test_two_seats_two_tasks_no_crosstalk(self):
        d1, d2 = _LabelledRecordingDispatcher(), _LabelledRecordingDispatcher()
        config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code") for _ in (d1, d2)])
        dispatchers = [d1, d2]

        def _builder(spec):
            idx = len(_builder.built)
            disp = dispatchers[idx]
            _builder.built.append(disp)
            return disp, object()

        _builder.built = []
        pool = DevAgentPool.build(config, _builder, pool_max=2)

        tasks = [
            TaskRef(id="TASK-1", status="pending", depends_on=[]),
            TaskRef(id="TASK-2", status="pending", depends_on=[]),
        ]
        await pool.run_wave(
            tasks, research=_research(), run_id="r1", cwd_for=lambda w: f"/tmp/wt/{w}"
        )

        by_seat = {}
        for disp in (d1, d2):
            for node_id, payload in disp.published:
                by_seat.setdefault(node_id, set()).add(payload.get("task_id"))

        assert len(by_seat) == 2
        assert all(len(v) == 1 for v in by_seat.values()), by_seat
        # No seat's task_id ever appears under a different seat.
        seat_task_ids = {seat: next(iter(ids)) for seat, ids in by_seat.items()}
        assert len(set(seat_task_ids.values())) == 2


# ---------------------------------------------------------------------------
# Multiplexer passthrough — guards the agy wire-format regression (root
# cause 7) and any future payload-stripping regression.
# ---------------------------------------------------------------------------


class TestMultiplexerPassthrough:
    def test_enriched_payload_survives(self):
        import time

        from parrot.flows.dev_loop.models import DispatchEvent

        payload = normalize_payload(
            "dispatch.tool_use",
            {"tool_name": "Read", "task_id": "TASK-1857", "seat": "development.w1"},
        )
        event = DispatchEvent(kind="dispatch.tool_use", ts=time.time(), run_id="r1",
                              node_id="development.w1", payload=payload)
        fields = {"event": event.model_dump_json()}

        mux = FlowStreamMultiplexer(object(), run_id="r1")
        env = mux._fields_to_envelope("flow:r1:dispatch:development.w1", fields, ts=1.0)

        assert env["event_kind"] == "dispatch.tool_use"
        assert env["event_kind"] != "flow.unknown"
        assert env["payload"]["summary"]
        assert env["payload"]["task_id"] == "TASK-1857"
        assert env["payload"]["tool_name"] == "Read"

    def test_agy_flat_fields_no_longer_reach_flow_unknown(self):
        """Root cause 7 regression guard — see TASK-2727."""
        import time

        from parrot.flows.dev_loop.models import DispatchEvent

        payload = normalize_payload("dispatch.tool_use", {"agy_event": {}, "tool_name": "read_file"})
        event = DispatchEvent(kind="dispatch.tool_use", ts=time.time(), run_id="r1",
                              node_id="development", payload=payload)
        fields = {"event": event.model_dump_json()}

        mux = FlowStreamMultiplexer(object(), run_id="r1")
        env = mux._fields_to_envelope("flow:r1:dispatch:development", fields, ts=1.0)
        assert env["event_kind"] == "dispatch.tool_use"


# ---------------------------------------------------------------------------
# Cross-backend contract — every dispatcher, every kind, same guarantees.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("dispatcher_cls", ALL_DISPATCHER_CLASSES, ids=lambda c: c.__name__)
async def test_normalized_contract_holds(dispatcher_cls, kind, monkeypatch):
    """FEAT-496 AC2/AC7/AC9 — every backend, every kind: a summary, never a
    bare class name, never dropped keys."""
    d = _dispatcher(dispatcher_cls)
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")
    fake_redis.expire = AsyncMock(return_value=True)

    # Each dispatcher names its lazy-redis getter differently.
    for attr in ("_ensure_redis", "_get_redis"):
        if hasattr(d, attr):
            async def _get(_fr=fake_redis):
                return _fr
            monkeypatch.setattr(d, attr, _get)

    await d._publish_event(
        "flow:r1:dispatch:development", kind=kind, run_id="r1", node_id="development",
        payload={"some_backend_key": "value"},
    )

    assert fake_redis.xadd.await_args is not None
    args = fake_redis.xadd.await_args
    fields = args.args[1] if len(args.args) > 1 else args.kwargs.get("fields") or args.args[-1]
    assert "event" in fields
    import json as _json
    decoded = _json.loads(fields["event"])
    payload = decoded["payload"]
    assert payload["summary"]
    assert len(payload["summary"]) <= 160
    # The backend's own key must survive normalization untouched.
    assert payload["some_backend_key"] == "value"


# ---------------------------------------------------------------------------
# Backward compatibility — a pre-FEAT-496 persisted ActionEnvelope.
# ---------------------------------------------------------------------------


def test_pre_feat496_envelope_still_validates():
    envelope = ActionEnvelope(
        channel=session_channel("run-1"), server_seq=1, action=RunCreated(run_id="run-1"),
    )
    dumped = envelope.model_dump()
    restored = ActionEnvelope.model_validate(dumped)
    assert restored.action.type == "run/created"
