"""FEAT-590 M5: DelegateToolNode gate, on_reject, traces."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest
from pydantic import BaseModel

from parrot.bots.flows.plan.delegate import DelegateBackendError, ToolCallProposal
from parrot.bots.flows.plan.delegate.node import (
    DelegateRejectedError,
    DelegateToolNode,
    make_delegate_node_factory,
)
from parrot.bots.flows.plan.delegate.protocol import DelegateTrace
from parrot.bots.flows.plan.models import ArtifactRef, DelegatePlanNode, ForEach
from ._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager
from .test_node import _Ctx, _Entry, _WorkingMemory


class _Url(BaseModel):
    url: str


def _proposal(name, args=None, confidence=0.9, backend="fake") -> ToolCallProposal:
    return ToolCallProposal(name=name, arguments=args or {}, confidence=confidence, backend=backend, latency_ms=1.0)


class _TraceSink:
    """Captures every :class:`DelegateTrace` recorded through it."""

    def __init__(self) -> None:
        self.records: List[DelegateTrace] = []

    async def record(self, trace: DelegateTrace) -> None:
        """Append the trace."""
        self.records.append(trace)


class _FailingSink:
    """A sink that always raises — proves a failure never fails the node."""

    async def record(self, trace: DelegateTrace) -> None:
        """Raise unconditionally."""
        raise RuntimeError("sink down")


def _make_tool(**kwargs: Any) -> FakeTool:
    return FakeTool("fetch_url", _Url, **kwargs)


@pytest.mark.asyncio
async def test_delegate_accept_dispatches_proposed_tool() -> None:
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})
    delegate = FakeDelegate([_proposal("fetch_url", {"url": "http://x"}, confidence=0.9)])
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"]),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate,),
    )

    ref = await node.execute(_Ctx())

    assert ref.status == "ok"
    assert manager.calls == [("fetch_url", {"url": "http://x"})]


@pytest.mark.parametrize(
    "verdict",
    [
        "declined",
        "unknown_tool",
        "invalid_args",
        "side_effect_denied",
        "low_confidence",
        "unscored",
        "guard_false",
        "input_too_long",
        "backend_error",
    ],
)
@pytest.mark.asyncio
async def test_delegate_gate_verdicts(verdict: str) -> None:
    trace_sink = _TraceSink()
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})

    plan_kwargs: Dict[str, Any] = dict(id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"])
    script: List[Any] = [_proposal("fetch_url", {"url": "http://x"}, confidence=0.9)]

    if verdict == "declined":
        script = [_proposal(None)]
    elif verdict == "unknown_tool":
        script = [_proposal("other_tool", {"url": "http://x"})]
    elif verdict == "invalid_args":
        script = [_proposal("fetch_url", {})]
    elif verdict == "side_effect_denied":
        tool.delegate_safe = False
    elif verdict == "low_confidence":
        plan_kwargs["min_confidence"] = 0.8
        script = [_proposal("fetch_url", {"url": "http://x"}, confidence=0.5)]
    elif verdict == "unscored":
        plan_kwargs["min_confidence"] = 0.8
        script = [_proposal("fetch_url", {"url": "http://x"}, confidence=None)]
    elif verdict == "guard_false":
        plan_kwargs["accept_when"] = "ctx.proposal.confidence > 0.99"
    elif verdict == "backend_error":
        script = [DelegateBackendError("boom")]

    max_input_chars = 5 if verdict == "input_too_long" else 1000
    delegate = FakeDelegate(script, max_input_chars=max_input_chars)
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(**plan_kwargs),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate,),
        trace_sink=trace_sink,
    )

    with pytest.raises(DelegateRejectedError):
        await node.execute(_Ctx())

    assert manager.calls == []
    assert trace_sink.records[-1].verdict == verdict


@pytest.mark.asyncio
async def test_rejected_proposal_never_dispatches() -> None:
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})
    delegate = FakeDelegate([_proposal(None)])
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"]),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate,),
    )

    with pytest.raises(DelegateRejectedError):
        await node.execute(_Ctx())

    assert manager.calls == []


@pytest.mark.asyncio
async def test_extra_arg_keys_rejected() -> None:
    trace_sink = _TraceSink()
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})
    delegate = FakeDelegate([_proposal("fetch_url", {"url": "http://x", "extra": "y"}, confidence=0.9)])
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"]),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate,),
        trace_sink=trace_sink,
    )

    with pytest.raises(DelegateRejectedError):
        await node.execute(_Ctx())

    assert manager.calls == []
    assert trace_sink.records[-1].verdict == "invalid_args"


@pytest.mark.asyncio
async def test_side_effect_rechecked_at_dispatch() -> None:
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})
    delegate = FakeDelegate([_proposal("fetch_url", {"url": "http://x"}, confidence=0.9)])
    trace_sink = _TraceSink()
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"]),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate,),
        trace_sink=trace_sink,
    )
    # Flipped AFTER construction/validation, BEFORE dispatch: the re-check must
    # read the live object, not a snapshot taken earlier.
    tool.delegate_safe = False

    with pytest.raises(DelegateRejectedError):
        await node.execute(_Ctx())

    assert manager.calls == []
    assert trace_sink.records[-1].verdict == "side_effect_denied"


@pytest.mark.asyncio
async def test_confidence_gate_unscored() -> None:
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})

    # min_confidence unset -> gate skipped entirely, even for confidence=None.
    delegate = FakeDelegate([_proposal("fetch_url", {"url": "http://x"}, confidence=None)])
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"]),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate,),
    )
    ref = await node.execute(_Ctx())
    assert ref.status == "ok"

    # min_confidence set + confidence=None -> rejected 'unscored', never coerced.
    trace_sink = _TraceSink()
    delegate2 = FakeDelegate([_proposal("fetch_url", {"url": "http://x"}, confidence=None)])
    node2 = DelegateToolNode(
        node_id="n2",
        plan_node=DelegatePlanNode(
            id="n2", store_as="k2", instruction="Fetch it", tools=["fetch_url"], min_confidence=0.5
        ),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate2,),
        trace_sink=trace_sink,
    )
    with pytest.raises(DelegateRejectedError):
        await node2.execute(_Ctx())
    assert trace_sink.records[-1].verdict == "unscored"


@pytest.mark.asyncio
async def test_on_reject_retry_backend_uses_next_delegate() -> None:
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})

    primary = FakeDelegate([_proposal(None, backend="primary")], backend_name="primary")
    too_small = FakeDelegate(
        [_proposal("fetch_url", {"url": "http://x"}, backend="too_small")], backend_name="too_small", max_tools=0
    )
    secondary = FakeDelegate(
        [_proposal("fetch_url", {"url": "http://x"}, confidence=0.9, backend="secondary")], backend_name="secondary"
    )
    trace_sink = _TraceSink()
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(
            id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"], on_reject="retry_backend"
        ),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(primary, too_small, secondary),
        trace_sink=trace_sink,
    )

    ref = await node.execute(_Ctx())

    assert ref.status == "ok"
    assert manager.calls == [("fetch_url", {"url": "http://x"})]
    assert too_small.seen == []  # skipped: max_tools < len(tools)
    assert [record.proposal.backend for record in trace_sink.records] == ["primary", "secondary"]
    assert [record.verdict for record in trace_sink.records] == ["declined", "accepted"]


@pytest.mark.asyncio
async def test_on_reject_escalate_recorded_even_with_skip() -> None:
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})
    wm = _WorkingMemory()
    wm._catalog._store["listing"] = _Entry({"keys": ["a", "b"]})

    def script(instruction: str) -> ToolCallProposal:
        if instruction == "a":
            return _proposal(None)
        return _proposal("fetch_url", {"url": instruction}, confidence=0.9)

    delegate = FakeDelegate([script, script])
    plan_node = DelegatePlanNode(
        id="fetch",
        store_as="report_{index}",
        instruction="{item}",
        tools=["fetch_url"],
        depends_on=["listing"],
        on_reject="escalate",
        for_each=ForEach(source="{artifacts.listing}", select="keys[]", on_item_error="skip"),
    )
    node = DelegateToolNode(
        node_id="fetch", plan_node=plan_node, tool_manager=manager, working_memory=wm, delegates=(delegate,)
    )
    ctx = _Ctx({"listing": ArtifactRef(node_id="listing", keys=["listing"])})

    ref = await node.execute(ctx)

    # on_item_error="skip" would normally drop the failure entirely; an
    # escalation must be recorded regardless.
    assert ref.escalated == 1
    assert any(e.startswith("escalate:") for e in ref.errors)
    assert ref.status == "partial"
    assert len(ref.keys) == 1
    assert manager.calls == [("fetch_url", {"url": "b"})]


@pytest.mark.asyncio
async def test_single_node_escalate_returns_error_ref() -> None:
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})
    delegate = FakeDelegate([_proposal(None)])
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(
            id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"], on_reject="escalate"
        ),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate,),
    )

    ref = await node.execute(_Ctx())

    assert ref.status == "error"
    assert ref.escalated == 1
    assert any("escalate:" in e for e in ref.errors)
    assert manager.calls == []


@pytest.mark.asyncio
async def test_trace_per_proposal() -> None:
    tool = _make_tool(delegate_safe=True)
    manager = FakeToolManager([tool], {"fetch_url": {"ok": True}})

    # A failing sink must never fail the node.
    delegate = FakeDelegate([_proposal("fetch_url", {"url": "http://x"}, confidence=0.9)])
    node = DelegateToolNode(
        node_id="n",
        plan_node=DelegatePlanNode(id="n", store_as="k", instruction="Fetch it", tools=["fetch_url"]),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate,),
        trace_sink=_FailingSink(),
    )
    ref = await node.execute(_Ctx())
    assert ref.status == "ok"

    # A real sink records exactly one trace for a single (non-retry) proposal.
    trace_sink = _TraceSink()
    delegate2 = FakeDelegate([_proposal("fetch_url", {"url": "http://x"}, confidence=0.9)])
    node2 = DelegateToolNode(
        node_id="n2",
        plan_node=DelegatePlanNode(id="n2", store_as="k2", instruction="Fetch it", tools=["fetch_url"]),
        tool_manager=manager,
        working_memory=_WorkingMemory(),
        delegates=(delegate2,),
        trace_sink=trace_sink,
    )
    await node2.execute(_Ctx())

    assert len(trace_sink.records) == 1
    assert trace_sink.records[0].verdict == "accepted"
    assert trace_sink.records[0].final_call == {"name": "fetch_url", "arguments": {"url": "http://x"}}


def test_factory_binds_chain_and_host_flag() -> None:
    manager = FakeToolManager([], {})
    wm = _WorkingMemory()
    delegate = FakeDelegate([])
    trace_sink = _TraceSink()
    factory = make_delegate_node_factory(
        manager,
        wm,
        (delegate,),
        trace_sink=trace_sink,
        allow_delegate_side_effects=True,
    )

    class _Def:
        id = "n"
        config = DelegatePlanNode(id="n", store_as="k", instruction="hi", tools=["fetch_url"]).model_dump(
            mode="json"
        )

    node = factory(_Def(), {"listing"}, {"next"})

    assert node.tool_manager is manager
    assert node.working_memory is wm
    assert node.delegates == (delegate,)
    assert node.trace_sink is trace_sink
    assert node.allow_delegate_side_effects is True
    assert node.dependencies == {"listing"}
    assert node.successors == {"next"}
