"""Plan and tee provenance across the post-dispatch boundary (TASK-2991).

Three required cases from the task's Test Specification:

- ``test_post_dispatch`` — plan and tee writes carry the actual producer
  call/attempt/step *after* the manager has reset its per-invocation
  context.
- ``test_plan_parallel`` — mapped calls keep plan attribution, unmapped
  calls stay task-level, and nothing creates a task or a step.
- ``test_no_unknown_retry`` — an unresolved outcome is never retried,
  while ordinary configured transient retries are untouched.

What these tests refuse to do is assert that a helper was *called*. The
bug being fixed is that provenance is silently **lost** at a boundary, so
every assertion here reads the value back out of a real
:class:`InMemoryArtifactStore` descriptor or a real
:class:`InvocationRecord`. A test that merely observed
``retained_producer`` being entered would still pass if the write landed
with ``producer_call_id=None``, which is exactly the failure.

The context reset is verified directly rather than assumed: the catalog
write is wrapped so it records what :data:`CURRENT_CALL` held at the
moment it ran. Every enabled plan write in these tests sees ``None``
there — the ambient value really is gone — and still lands attributed,
which is the whole point of the retention.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

import pytest
from parrot.bots.flows.plan.models import ArtifactRef, ExecutionPlan, FacetSpec, ForEach, PlanNode, RetryPolicy
from parrot.bots.flows.plan.node import (
    PlanToolNode,
    ToolExecutionError,
    UnknownToolOutcomeError,
    build_manifest,
    make_tool_node_factory,
)
from parrot.tools.compression.tee import CompressionTee
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.context import (
    CURRENT_CALL,
    RETAINED_PRODUCER,
    TurnTaskSession,
    turn_session,
)
from parrot.tools.working_memory.task_memory.models import Attribution, CallOutcome, TaskScope
from parrot.tools.working_memory.task_memory.observer import InvocationObserver, ObserverMode

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
TASK_ID = "t-1"


# ── local fixtures (no shared conftest dependency) ───────────────────────────


class TaskMemoryStub:
    """The composition surface :class:`WorkingMemoryToolkit` reads.

    Backed by a **real** artifact store, so what these tests exercise is
    the genuine enabled write path and its genuine descriptors.
    """

    def __init__(self) -> None:
        """Initialize with a real in-memory artifact store."""
        self.artifacts = InMemoryArtifactStore()
        self.scope = SCOPE
        self.task_id = TASK_ID
        self.config = TaskMemoryConfig()


class WriteProbe:
    """Records the ambient context each enabled catalog write ran under.

    Wraps ``aput_generic`` rather than replacing it: the real write still
    happens, and the probe only observes what :data:`CURRENT_CALL` and
    :data:`RETAINED_PRODUCER` held at that instant. That is what turns
    "provenance survived" into a falsifiable claim about *which*
    mechanism carried it.
    """

    def __init__(self, catalog: Any) -> None:
        """Wrap ``catalog.aput_generic`` in place.

        Args:
            catalog: The enabled working-memory catalog.
        """
        self.ambient_calls: List[Optional[str]] = []
        self.retained: List[Optional[str]] = []
        self._inner = catalog.aput_generic

        async def _probed(key: str, data: Any, **kwargs: Any) -> Any:
            self.ambient_calls.append(CURRENT_CALL.get())
            self.retained.append(RETAINED_PRODUCER.get())
            return await self._inner(key, data, **kwargs)

        catalog.aput_generic = _probed  # type: ignore[method-assign]


class ObservedManager:
    """A ``ToolManager`` stand-in wired exactly like ``_observed``.

    The ordering mirrors ``ToolManager._observed`` verbatim — begin,
    dispatch, cancelled/finish — because the boundary under test *is*
    that ordering. Anything looser would prove nothing about the real
    reset.
    """

    def __init__(
        self,
        handler: Callable[[str, Dict[str, Any]], Any],
        *,
        observer: Optional[InvocationObserver] = None,
    ) -> None:
        """Initialize the fake manager.

        Args:
            handler: Async callable invoked as the "tool body".
            observer: Optional invocation observer, as the real manager's
                opt-in observer would be.
        """
        self._handler = handler
        self._observer = observer
        self.calls: List[tuple[str, Dict[str, Any]]] = []

    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        permission_context: Optional[Any] = None,
    ) -> Any:
        """Dispatch one call, observed when an observer is installed.

        Args:
            tool_name: The tool to run.
            parameters: Resolved keyword arguments.
            permission_context: Ignored; present for signature parity.

        Returns:
            Whatever the handler returned.
        """
        self.calls.append((tool_name, dict(parameters)))
        if self._observer is None:
            return await self._handler(tool_name, parameters)

        observed = await self._observer.begin(tool_name)
        try:
            result = await self._handler(tool_name, parameters)
        except asyncio.CancelledError:
            await self._observer.cancelled(observed)
            raise
        except BaseException as exc:  # noqa: BLE001 — recorded, then re-raised
            await self._observer.finish(observed, exception=exc)
            raise
        await self._observer.finish(observed, value=result)
        return result


class Ctx:
    """Minimal ``FlowContext`` stand-in: the node only reads ``results``."""

    def __init__(self, results: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the context.

        Args:
            results: Previously published node results.
        """
        self.results = results or {}
        self.initial_task = ""


@pytest.fixture()
async def enabled():
    """Yield ``(toolkit, task-memory stub, write probe)`` with task memory on."""
    stub = TaskMemoryStub()
    toolkit = WorkingMemoryToolkit(task_memory=stub)
    probe = WriteProbe(toolkit._catalog)
    try:
        yield toolkit, stub, probe
    finally:
        await stub.artifacts.close()


@pytest.fixture(autouse=True)
def _no_context_leak():
    """Fail loudly if a test leaves dispatch context bound."""
    yield
    assert CURRENT_CALL.get() is None, "CURRENT_CALL leaked out of a test"
    assert RETAINED_PRODUCER.get() is None, "RETAINED_PRODUCER leaked out of a test"


def plan_node(**kwargs: Any) -> PlanNode:
    """Build a ``PlanNode`` with this module's defaults.

    Args:
        **kwargs: Overrides forwarded to :class:`PlanNode`.

    Returns:
        The node specification.
    """
    defaults: Dict[str, Any] = {"id": "fetch", "tool": "get_report", "store_as": "report"}
    defaults.update(kwargs)
    return PlanNode(**defaults)


def build_node(
    spec: PlanNode,
    manager: ObservedManager,
    working_memory: WorkingMemoryToolkit,
    *,
    plan_run_id: Optional[str] = "run_abc",
    step_mapping: Optional[Dict[str, str]] = None,
) -> PlanToolNode:
    """Build a ``PlanToolNode`` through the shared factory.

    Going through :func:`make_tool_node_factory` rather than the
    constructor is deliberate: the factory is where the executor threads
    run/step correlation in, so testing around it would skip the wiring.

    Args:
        spec: The plan node specification.
        manager: The dispatching manager.
        working_memory: The toolkit receiving payloads.
        plan_run_id: Plan-run correlation.
        step_mapping: Explicit ``{node_id: step_id}`` mapping.

    Returns:
        The constructed node.
    """
    factory = make_tool_node_factory(
        manager,
        working_memory,
        plan_run_id=plan_run_id,
        step_mapping=step_mapping,
    )

    class _Definition:
        id = spec.id
        config = spec.model_dump(mode="json")

    return factory(_Definition(), set(), set())


async def payload_handler(_tool: str, _args: Dict[str, Any]) -> Dict[str, Any]:
    """Return a small deterministic payload.

    Args:
        _tool: Unused tool name.
        _args: Unused arguments.

    Returns:
        The payload.
    """
    await asyncio.sleep(0)
    return {"findings": [{"id": "f1", "severity": "high"}]}


async def descriptor_for(stub: TaskMemoryStub, key: str) -> Any:
    """Return the artifact descriptor currently published under ``key``.

    Args:
        stub: The task-memory stub owning the store.
        key: The alias to resolve.

    Returns:
        The :class:`ArtifactDescriptor` behind the alias.
    """
    descriptor = await stub.artifacts.get_current(SCOPE, key, task_id=TASK_ID)
    assert descriptor is not None, f"no artifact published under {key!r}"
    return descriptor


async def descriptors(stub: TaskMemoryStub) -> Any:
    """Return every descriptor in the task's namespace.

    Args:
        stub: The task-memory stub owning the store.

    Returns:
        The page's descriptors.
    """
    page = await stub.artifacts.list(SCOPE, task_id=TASK_ID)
    return page.items


# ── required case 1 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_dispatch(enabled) -> None:
    """Plan and tee writes name the real producer after the context reset.

    Both writes happen past the dispatcher's boundary. The probe proves
    the boundary is real — ``CURRENT_CALL`` is ``None`` at write time —
    and the descriptors prove the provenance survived it anyway.
    """
    toolkit, stub, probe = enabled
    session = TurnTaskSession(SCOPE, task_id=TASK_ID)
    observer = InvocationObserver(session)
    manager = ObservedManager(payload_handler, observer=observer)

    with turn_session(SCOPE, session=session):
        node = build_node(
            plan_node(),
            manager,
            toolkit,
            step_mapping={"fetch": "step-7"},
        )
        ref = await node.execute(Ctx())

        # The tee writes at the same post-dispatch point the compression
        # stage does: after the observed call has already finished.
        assert CURRENT_CALL.get() is None
        aggregate = [r for r in session.records if r.context.plan_node_id == "fetch"][0]
        tee = CompressionTee(toolkit)
        with session.retained_producer(aggregate.call_id):
            tee_key = await tee.store("get_report", {"raw": "full payload"}, "lossy")

    assert isinstance(ref, ArtifactRef)

    # 1. The boundary is genuinely crossed: nothing ambient was available.
    assert probe.ambient_calls == [None, None], "the dispatcher's context was still bound"
    assert probe.retained == [aggregate.call_id, aggregate.call_id]

    # 2. The plan write carries call, attempt and step.
    stored = await descriptor_for(stub, "report")
    assert stored.producer_call_id == aggregate.call_id
    assert stored.attribution is Attribution.PLAN
    assert aggregate.context.plan_run_id == "run_abc"
    assert aggregate.context.plan_attempt == 1
    assert aggregate.context.mapped_step_id == "step-7"
    assert aggregate.context.attributed_step_id == "step-7"

    # 3. The artifact version is attached back to the producing receipt,
    #    and published as immutable evidence rather than a mutable alias.
    evidence = f"{stored.ref.artifact_id}@{stored.ref.version}"
    receipts = [str(r) for r in aggregate.artifact_receipts]
    assert evidence in receipts
    assert ref.versions == [evidence]
    assert ref.keys == ["report"], "the alias is still published, it is just not the evidence"
    assert ref.tracking_degraded is False

    # 4. The physical attempt is a CHILD of the plan node's aggregate, so
    #    the aggregate is not counted as a second execution of it.
    children = [r for r in session.records if r.parent_call_id == aggregate.call_id]
    assert len(children) == 1
    assert children[0].tool_name == "get_report"
    assert children[0].outcome is CallOutcome.SUCCESS

    # 5. The tee write, at the same boundary, is attributed too.
    assert tee_key is not None
    teed = await descriptor_for(stub, tee_key)
    assert teed.producer_call_id == aggregate.call_id
    assert teed.attribution is Attribution.PLAN
    assert f"{teed.ref.artifact_id}@{teed.ref.version}" in [
        str(r) for r in session.receipt(aggregate.call_id).artifact_receipts
    ]


# ── required case 2 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_parallel(enabled) -> None:
    """Mapped calls keep plan attribution; unmapped ones stay task-level.

    And neither creates anything: a plan run never invents a task or a
    step, not even the step whose id its own node id superficially
    resembles.
    """
    toolkit, stub, _probe = enabled
    session = TurnTaskSession(SCOPE, task_id=TASK_ID)
    manager = ObservedManager(payload_handler, observer=InvocationObserver(session))

    with turn_session(SCOPE, session=session):
        # A step is declared for the turn. An unmapped plan call must NOT
        # borrow it: plan provenance overrides the declaration and stays
        # task-level.
        session.declare("step-declared")

        mapped = build_node(
            plan_node(id="mapped", store_as="mapped_out"),
            manager,
            toolkit,
            step_mapping={"mapped": "step-7"},
        )
        unmapped = build_node(
            plan_node(id="unmapped", store_as="unmapped_out"),
            manager,
            toolkit,
            step_mapping={"other": "step-9"},
        )
        fan_out = build_node(
            plan_node(
                id="items",
                store_as="item_{index}",
                depends_on=["mapped"],
                for_each=ForEach(source="{artifacts.mapped}", select="findings[]"),
                facets=FacetSpec(),
            ),
            manager,
            toolkit,
            step_mapping={},
        )

        mapped_ref, unmapped_ref = await asyncio.gather(mapped.execute(Ctx()), unmapped.execute(Ctx()))
        fan_ref = await fan_out.execute(Ctx(results={"mapped": mapped_ref}))

    by_node = {r.context.plan_node_id: r for r in session.records if r.context.plan_node_id}

    # Mapped: plan attribution AND a resolved step.
    assert by_node["mapped"].context.attribution is Attribution.PLAN
    assert by_node["mapped"].context.attributed_step_id == "step-7"
    assert (await descriptor_for(stub, "mapped_out")).attribution is Attribution.PLAN

    # Unmapped: still plan provenance, but task-level — the declared step
    # is visible in the snapshot and deliberately not used.
    assert by_node["unmapped"].context.attribution is Attribution.PLAN
    assert by_node["unmapped"].context.attributed_step_id is None
    assert by_node["unmapped"].context.declared_step_ids == ("step-declared",)
    assert by_node["unmapped"].context.mapped_step_id is None
    unmapped_stored = await descriptor_for(stub, "unmapped_out")
    assert unmapped_stored.producer_call_id == by_node["unmapped"].call_id

    # No automatic task or step creation: the selected task is the one the
    # runtime already had, and the turn declared exactly what it declared.
    assert session.task_id == TASK_ID
    assert session.declared_step_ids == ("step-declared",)
    assert {d.task_id for d in await descriptors(stub)} == {TASK_ID}

    # Concurrency: every fan-out item is its own attempt with its own
    # index, and each artifact names its own item's attempt — not a
    # neighbour's, and not one shared receipt.
    assert fan_ref.item_count == 1
    items = [r for r in session.records if r.context.plan_node_id == "items"]
    assert [r.context.plan_item_index for r in items] == [0]
    item_stored = await descriptor_for(stub, "item_0")
    assert item_stored.producer_call_id == items[0].call_id
    assert fan_ref.versions == [f"{item_stored.ref.artifact_id}@{item_stored.ref.version}"]

    # The two concurrent nodes did not share a receipt.
    assert by_node["mapped"].call_id != by_node["unmapped"].call_id
    assert mapped_ref.versions != unmapped_ref.versions


@pytest.mark.asyncio
async def test_plan_parallel_fan_out_items_are_independent(enabled) -> None:
    """Each of several concurrent items keeps its own attempt and index."""
    toolkit, stub, _probe = enabled
    session = TurnTaskSession(SCOPE, task_id=TASK_ID)

    async def three_items(_tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0)
        return {"findings": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "echo": args}

    manager = ObservedManager(three_items, observer=InvocationObserver(session))

    with turn_session(SCOPE, session=session):
        source = build_node(plan_node(id="src", store_as="src_out"), manager, toolkit)
        source_ref = await source.execute(Ctx())
        fan_out = build_node(
            plan_node(
                id="items",
                store_as="item_{index}",
                depends_on=["src"],
                for_each=ForEach(source="{artifacts.src}", select="findings[]"),
            ),
            manager,
            toolkit,
        )
        ref = await fan_out.execute(Ctx(results={"src": source_ref}))

    items = sorted(
        (r for r in session.records if r.context.plan_node_id == "items"),
        key=lambda r: r.context.plan_item_index,
    )
    assert [r.context.plan_item_index for r in items] == [0, 1, 2]
    assert len({r.call_id for r in items}) == 3
    for index, record in enumerate(items):
        stored = await descriptor_for(stub, f"item_{index}")
        assert stored.producer_call_id == record.call_id
    assert len(ref.versions) == 3
    assert len(set(ref.versions)) == 3


# ── required case 3 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_unknown_retry(enabled) -> None:
    """Unresolved outcomes are not retried; ordinary transients still are."""
    toolkit, _stub, _probe = enabled

    # (a) Ordinary configured transient retries: untouched.
    attempts: List[int] = []

    async def flaky(_tool: str, _args: Dict[str, Any]) -> Dict[str, Any]:
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    session = TurnTaskSession(SCOPE, task_id=TASK_ID)
    manager = ObservedManager(flaky, observer=InvocationObserver(session))
    with turn_session(SCOPE, session=session):
        node = build_node(plan_node(retry=RetryPolicy(max_attempts=3)), manager, toolkit)
        ref = await node.execute(Ctx())

    assert attempts == [1, 2, 3]
    assert ref.status == "ok"
    plan_attempts = [r for r in session.records if r.context.plan_node_id == "fetch"]
    assert [r.context.plan_attempt for r in plan_attempts] == [1, 2, 3]
    assert [r.outcome for r in plan_attempts] == [
        CallOutcome.ERROR,
        CallOutcome.ERROR,
        CallOutcome.SUCCESS,
    ]
    # Each retry is a sibling attempt, never a child of the previous one.
    assert all(r.parent_call_id is None for r in plan_attempts)

    # (b) An unresolved outcome ends the loop at once. The tool timed out,
    #     so its external effect may already have happened; running it
    #     again is exactly what must not occur.
    started = 0

    async def hangs(_tool: str, _args: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal started
        started += 1
        await asyncio.sleep(5)
        return {"unreachable": True}

    session_b = TurnTaskSession(SCOPE, task_id=TASK_ID)
    manager_b = ObservedManager(hangs, observer=InvocationObserver(session_b))
    with turn_session(SCOPE, session=session_b):
        node_b = build_node(
            plan_node(store_as="never", timeout=0.05, retry=RetryPolicy(max_attempts=3)),
            manager_b,
            toolkit,
        )
        with pytest.raises(UnknownToolOutcomeError) as raised:
            await node_b.execute(Ctx())

    assert started == 1, "an unresolved outcome must not be retried"
    assert "not retried automatically" in str(raised.value)
    assert isinstance(raised.value, ToolExecutionError), "existing handling still catches it"
    physical = [r for r in session_b.records if r.context.plan_node_id is None]
    assert [r.outcome for r in physical] == [CallOutcome.CANCELLED]
    assert not physical[0].outcome.is_resolved

    # (c) With task memory absent there is no receipt to read, so the
    #     legacy retry behaviour is preserved exactly (AC13).
    legacy_started = 0

    async def legacy_hangs(_tool: str, _args: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal legacy_started
        legacy_started += 1
        await asyncio.sleep(5)
        return {"unreachable": True}

    node_c = build_node(
        plan_node(store_as="legacy", timeout=0.05, retry=RetryPolicy(max_attempts=3)),
        ObservedManager(legacy_hangs),
        WorkingMemoryToolkit(),
    )
    with pytest.raises(ToolExecutionError) as legacy_raised:
        await node_c.execute(Ctx())

    assert legacy_started == 3, "the disabled path keeps its configured retries"
    assert not isinstance(legacy_raised.value, UnknownToolOutcomeError)


# ── supporting failure cases ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_tee_is_degraded_not_evidence(enabled) -> None:
    """A tee that could not persist claims nothing and admits the gap."""
    toolkit, stub, _probe = enabled
    session = TurnTaskSession(SCOPE, task_id=TASK_ID)
    manager = ObservedManager(payload_handler, observer=InvocationObserver(session))

    with turn_session(SCOPE, session=session):
        node = build_node(plan_node(), manager, toolkit)
        await node.execute(Ctx())
        aggregate = [r for r in session.records if r.context.plan_node_id == "fetch"][0]
        before = len(session.receipt(aggregate.call_id).artifact_receipts)

        async def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("artifact store unavailable")

        toolkit._catalog.aput_generic = boom  # type: ignore[method-assign]
        tee = CompressionTee(toolkit)
        with session.retained_producer(aggregate.call_id):
            key = await tee.store("get_report", {"raw": "full"}, "error")

    # The contract that a broken tee never breaks a call is preserved…
    assert key is None
    # …and it produced no evidence at all…
    assert len(session.receipt(aggregate.call_id).artifact_receipts) == before
    assert not [d for d in await descriptors(stub) if "__tee__" in (d.alias or "")]
    # …while the gap is recorded rather than passed off as tracked work.
    assert session.receipt(aggregate.call_id).degraded is True


@pytest.mark.asyncio
async def test_degraded_dispatch_surfaces_in_the_manifest_ref(enabled) -> None:
    """A best-effort dispatch whose start was not persisted reads degraded."""
    toolkit, _stub, _probe = enabled
    session = TurnTaskSession(SCOPE, task_id=TASK_ID)

    async def refuse(_task_id: str, _events: Any) -> None:
        raise RuntimeError("journal unavailable")

    observer = InvocationObserver(session, append=refuse, mode=ObserverMode.BEST_EFFORT)
    manager = ObservedManager(payload_handler, observer=observer)

    with turn_session(SCOPE, session=session):
        node = build_node(plan_node(), manager, toolkit)
        ref = await node.execute(Ctx())

    assert ref.status == "ok"
    assert ref.tracking_degraded is True, "degraded tracking must not read as tracked"

    manifest = build_manifest(ExecutionPlan(name="p", objective="o", nodes=[plan_node()]), [ref], duration_seconds=0.0)
    assert manifest.is_tracking_degraded() is True


@pytest.mark.asyncio
async def test_manifest_cites_versions_not_aliases(enabled) -> None:
    """The manifest carries exact versions; the alias alone is not evidence."""
    toolkit, stub, _probe = enabled
    session = TurnTaskSession(SCOPE, task_id=TASK_ID)
    manager = ObservedManager(payload_handler, observer=InvocationObserver(session))

    with turn_session(SCOPE, session=session):
        node = build_node(plan_node(), manager, toolkit)
        first = await node.execute(Ctx())
        # Overwriting the alias moves it to a NEW version. The first
        # manifest must keep citing the version it actually proved.
        second = await node.execute(Ctx())

    stored = await descriptor_for(stub, "report")
    assert stored.ref.version == 2
    assert first.versions == [f"{stored.ref.artifact_id}@1"]
    assert second.versions == [f"{stored.ref.artifact_id}@2"]

    plan = ExecutionPlan(name="p", objective="o", nodes=[plan_node()])
    manifest = build_manifest(plan, [first, second], duration_seconds=0.0)
    assert manifest.evidence_refs() == [
        f"{stored.ref.artifact_id}@1",
        f"{stored.ref.artifact_id}@2",
    ]
    assert manifest.is_tracking_degraded() is False


@pytest.mark.asyncio
async def test_disabled_plan_path_is_unchanged() -> None:
    """With task memory absent, nothing is versioned and nothing degrades."""
    toolkit = WorkingMemoryToolkit()
    manager = ObservedManager(payload_handler)
    node = build_node(plan_node(), manager, toolkit, plan_run_id=None)

    ref = await node.execute(Ctx())

    assert ref.keys == ["report"]
    assert ref.versions == []
    assert ref.tracking_degraded is False
    assert toolkit._catalog.get("report").data == {"findings": [{"id": "f1", "severity": "high"}]}

    tee = CompressionTee(toolkit)
    key = await tee.store("get_report", {"raw": "full"}, "lossy")
    assert key is not None
    assert toolkit._catalog.get(key).data == {"raw": "full"}
