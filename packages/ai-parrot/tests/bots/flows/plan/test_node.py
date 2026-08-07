"""Tests for PlanToolNode — the payload-never-enters-context executor."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.flows.plan.facets import estimate_bytes, extract_facets, merge_facets
from parrot.bots.flows.plan.models import ArtifactRef, FacetSpec, ForEach, PlanNode
from parrot.bots.flows.plan.node import PlanToolNode, ToolExecutionError, make_tool_node_factory


# ── fakes mirroring the real contracts ───────────────────────────────────────

class _Entry:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Catalog:
    """Stands in for WorkingMemoryCatalog: a flat dict, overwrite-on-collision."""

    def __init__(self) -> None:
        self._store: Dict[str, _Entry] = {}

    def get(self, key: str) -> _Entry:
        if key not in self._store:
            raise KeyError(f"No entry {key!r}. Available: {sorted(self._store)}")
        return self._store[key]

    def __contains__(self, key: str) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)


class _WorkingMemory:
    def __init__(self) -> None:
        self._catalog = _Catalog()
        self.writes: List[str] = []

    async def store_result(self, key: str, data: Any, **_: Any) -> dict:
        self._catalog._store[key] = _Entry(data)
        self.writes.append(key)
        return {"status": "stored"}


class _ToolManager:
    """Records dispatches; returns a payload per tool name."""

    def __init__(self, payloads: Dict[str, Any]) -> None:
        self._payloads = payloads
        self.calls: List[tuple[str, Dict[str, Any]]] = []
        self.max_in_flight = 0
        self._in_flight = 0
        self.fail_times: Dict[str, int] = {}

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any],
        permission_context: Optional[Any] = None,
    ) -> Any:
        self.calls.append((tool_name, dict(parameters)))
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            await asyncio.sleep(0)
            remaining = self.fail_times.get(tool_name, 0)
            if remaining:
                self.fail_times[tool_name] = remaining - 1
                raise RuntimeError(f"transient failure in {tool_name}")
            payload = self._payloads[tool_name]
            return payload(parameters) if callable(payload) else payload
        finally:
            self._in_flight -= 1


class _Ctx:
    def __init__(self, results: Optional[Dict[str, Any]] = None) -> None:
        self.results = results or {}
        self.initial_task = ""


def _node(plan_node: PlanNode, manager: _ToolManager, wm: _WorkingMemory) -> PlanToolNode:
    return PlanToolNode(
        node_id=plan_node.id,
        plan_node=plan_node,
        tool_manager=manager,
        working_memory=wm,
    )


# ── the central invariant ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payload_goes_to_working_memory_not_into_the_result():
    big = {"findings": [{"id": f"f{i}", "severity": "high"} for i in range(5000)]}
    wm, manager = _WorkingMemory(), _ToolManager({"get_report": big})
    node = _node(
        PlanNode(id="fetch", tool="get_report", store_as="report",
                 facets=FacetSpec(counts={"n": "findings[]"})),
        manager, wm,
    )

    ref = await node.execute(_Ctx())

    assert isinstance(ref, ArtifactRef)
    assert ref.keys == ["report"]
    assert ref.facets["n"] == 5000
    assert wm._catalog.get("report").data is big

    # The published value must stay small: no payload anywhere inside it.
    published = ref.model_dump_json()
    assert "f4999" not in published
    assert len(published) < 1000
    assert ref.bytes_stored > 100_000


@pytest.mark.asyncio
async def test_dispatch_goes_through_the_tool_manager():
    # Not tool.execute(): the manager path is what runs result hooks,
    # dataframe extraction and permission propagation.
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"ok": True}})
    node = _node(PlanNode(id="n", tool="t", args={"a": 1}, store_as="k"), manager, wm)

    await node.execute(_Ctx())

    assert manager.calls == [("t", {"a": 1})]


# ── guards ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_false_skips_without_calling_the_tool():
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"x": 1}})
    ctx = _Ctx({"listing": ArtifactRef(node_id="listing", facets={"n": 0})})
    node = _node(
        PlanNode(id="n", tool="t", store_as="k", depends_on=["listing"],
                 when="ctx.artifacts.listing.n > 0"),
        manager, wm,
    )

    ref = await node.execute(ctx)

    assert ref.status == "skipped"
    assert manager.calls == []
    assert wm.writes == []


@pytest.mark.asyncio
async def test_guard_true_runs():
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"x": 1}})
    ctx = _Ctx({"listing": ArtifactRef(node_id="listing", facets={"n": 3})})
    node = _node(
        PlanNode(id="n", tool="t", store_as="k", depends_on=["listing"],
                 when="ctx.artifacts.listing.n > 0"),
        manager, wm,
    )

    assert (await node.execute(ctx)).status == "ok"
    assert len(manager.calls) == 1


@pytest.mark.asyncio
async def test_guard_can_branch_on_upstream_status():
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"x": 1}})
    ctx = _Ctx({"fetch": ArtifactRef(node_id="fetch", status="error")})
    node = _node(
        PlanNode(id="n", tool="t", store_as="k", depends_on=["fetch"],
                 when='ctx.status.fetch == "ok"'),
        manager, wm,
    )

    assert (await node.execute(ctx)).status == "skipped"


# ── fan-out ──────────────────────────────────────────────────────────────────

def _fanout_setup(payload_fn=None, **for_each_kw):
    wm = _WorkingMemory()
    wm._catalog._store["listing"] = _Entry({"keys": ["a.json", "b.json", "c.json"]})
    manager = _ToolManager(
        {"get": payload_fn or (lambda p: {"findings": [{"severity": "high"}],
                                          "src": p["key"]})}
    )
    node = _node(
        PlanNode(
            id="fetch", tool="get", args={"key": "{item}"},
            store_as="report_{index}", depends_on=["listing"],
            for_each=ForEach(source="{artifacts.listing}", select="keys[]",
                             **for_each_kw),
            facets=FacetSpec(group_counts={"by_sev": "findings[].severity"}),
        ),
        manager, wm,
    )
    ctx = _Ctx({"listing": ArtifactRef(node_id="listing", keys=["listing"])})
    return node, manager, wm, ctx


@pytest.mark.asyncio
async def test_for_each_expands_over_the_stored_body():
    node, manager, wm, ctx = _fanout_setup()

    ref = await node.execute(ctx)

    assert ref.item_count == 3
    assert sorted(ref.keys) == ["report_0", "report_1", "report_2"]
    assert sorted(c[1]["key"] for c in manager.calls) == ["a.json", "b.json", "c.json"]
    # Facets merge across items rather than reporting only the last one.
    assert ref.facets["by_sev"] == {"high": 3}


@pytest.mark.asyncio
async def test_for_each_respects_max_concurrency():
    node, manager, _, ctx = _fanout_setup(max_concurrency=1)
    await node.execute(ctx)
    assert manager.max_in_flight == 1

    node, manager, _, ctx = _fanout_setup(max_concurrency=8)
    await node.execute(ctx)
    assert manager.max_in_flight > 1


@pytest.mark.asyncio
async def test_for_each_over_empty_source_does_nothing_rather_than_fanning_out_on_none():
    wm = _WorkingMemory()
    wm._catalog._store["listing"] = _Entry({"other": 1})  # no 'keys' at all
    manager = _ToolManager({"get": {"x": 1}})
    node = _node(
        PlanNode(id="fetch", tool="get", args={"key": "{item}"},
                 store_as="r_{index}", depends_on=["listing"],
                 for_each=ForEach(source="{artifacts.listing}", select="keys[]")),
        manager, wm,
    )

    ref = await node.execute(_Ctx({"listing": ArtifactRef(node_id="listing",
                                                          keys=["listing"])}))

    assert ref.item_count == 0
    assert manager.calls == []


@pytest.mark.asyncio
async def test_exceeding_max_items_raises_instead_of_truncating_silently():
    node, _, _, ctx = _fanout_setup(max_items=2)
    with pytest.raises(ToolExecutionError, match="above max_items"):
        await node.execute(ctx)


@pytest.mark.asyncio
async def test_item_errors_are_collected_and_marked_partial():
    def payload(params):
        if params["key"] == "b.json":
            raise RuntimeError("boom")
        return {"findings": []}

    node, _, wm, ctx = _fanout_setup(payload)
    ref = await node.execute(ctx)

    assert ref.status == "partial"
    assert len(ref.keys) == 2
    assert any("boom" in e for e in ref.errors)


@pytest.mark.asyncio
async def test_on_item_error_fail_propagates():
    def payload(params):
        raise RuntimeError("boom")

    node, _, _, ctx = _fanout_setup(payload, on_item_error="fail")
    with pytest.raises(ToolExecutionError):
        await node.execute(ctx)


@pytest.mark.asyncio
async def test_skip_existing_makes_a_rerun_idempotent():
    node, manager, wm, ctx = _fanout_setup()
    await node.execute(ctx)
    first = len(manager.calls)

    node2, manager2, _, ctx2 = _fanout_setup()
    # Same working memory: simulate resuming after a crash with 2 of 3 done.
    object.__setattr__(node2, "working_memory", wm)
    wm._catalog._store.pop("report_2")
    await node2.execute(ctx2)

    assert first == 3
    assert len(manager2.calls) == 1  # only the missing item re-ran


# ── retries ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_recovers_from_a_transient_failure():
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"ok": True}})
    manager.fail_times["t"] = 2
    node = _node(
        PlanNode(id="n", tool="t", store_as="k",
                 retry={"max_attempts": 3, "backoff_seconds": 0.0}),
        manager, wm,
    )

    assert (await node.execute(_Ctx())).status == "ok"
    assert len(manager.calls) == 3


@pytest.mark.asyncio
async def test_retry_exhaustion_raises_with_the_last_error():
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"ok": True}})
    manager.fail_times["t"] = 5
    node = _node(
        PlanNode(id="n", tool="t", store_as="k", retry={"max_attempts": 2}),
        manager, wm,
    )

    with pytest.raises(ToolExecutionError, match="after 2 attempt"):
        await node.execute(_Ctx())


# ── argument resolution ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_artifact_placeholder_passes_the_body_by_value():
    body = {"deltas": [1, 2, 3]}
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"ok": True}})
    wm._catalog._store["deltas"] = _Entry(body)
    node = _node(
        PlanNode(id="n", tool="t", args={"payload": "{artifacts.diff}"},
                 store_as="k", depends_on=["diff"]),
        manager, wm,
    )

    await node.execute(_Ctx({"diff": ArtifactRef(node_id="diff", keys=["deltas"])}))

    assert manager.calls[0][1]["payload"] is body


@pytest.mark.asyncio
async def test_node_placeholder_passes_the_small_ref_not_the_body():
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"ok": True}})
    wm._catalog._store["deltas"] = _Entry({"huge": "x" * 10_000})
    node = _node(
        PlanNode(id="n", tool="t", args={"ref": "{nodes.diff.output}"},
                 store_as="k", depends_on=["diff"]),
        manager, wm,
    )

    await node.execute(
        _Ctx({"diff": ArtifactRef(node_id="diff", keys=["deltas"], facets={"n": 3})})
    )

    passed = manager.calls[0][1]["ref"]
    assert passed["facets"] == {"n": 3}
    assert "huge" not in str(passed)


@pytest.mark.asyncio
async def test_missing_artifact_is_a_clear_error():
    wm, manager = _WorkingMemory(), _ToolManager({"t": {}})
    node = _node(
        PlanNode(id="n", tool="t", args={"p": "{artifacts.absent}"},
                 store_as="k", depends_on=["absent"]),
        manager, wm,
    )

    with pytest.raises(ToolExecutionError, match="no working-memory artifact"):
        await node.execute(_Ctx())


@pytest.mark.asyncio
async def test_item_field_templating_in_key_and_args():
    wm = _WorkingMemory()
    wm._catalog._store["src"] = _Entry({"items": [{"id": "alpha"}, {"id": "beta"}]})
    manager = _ToolManager({"t": {"ok": True}})
    node = _node(
        PlanNode(id="n", tool="t", args={"which": "id-{item.id}"},
                 store_as="out_{item.id}", depends_on=["src"],
                 for_each=ForEach(source="{artifacts.src}", select="items[]")),
        manager, wm,
    )

    ref = await node.execute(_Ctx({"src": ArtifactRef(node_id="src", keys=["src"])}))

    assert sorted(ref.keys) == ["out_alpha", "out_beta"]
    assert sorted(c[1]["which"] for c in manager.calls) == ["id-alpha", "id-beta"]


# ── factory ──────────────────────────────────────────────────────────────────

def test_factory_injects_live_dependencies_through_the_closure():
    # This is the mechanism that lets the analyst agent read the same catalog
    # the executor wrote: neither object is serialisable into node config.
    wm, manager = _WorkingMemory(), _ToolManager({})
    factory = make_tool_node_factory(manager, wm)

    class _Def:
        id = "fetch"
        config = PlanNode(id="fetch", tool="t", store_as="k").model_dump(mode="json")

    node = factory(_Def(), {"listing"}, {"diff"})

    assert node.tool_manager is manager
    assert node.working_memory is wm
    assert node.dependencies == {"listing"}
    assert node.successors == {"diff"}
    assert node.plan_node.tool == "t"


# ── facets ───────────────────────────────────────────────────────────────────

def test_group_counts_are_capped():
    payload = {"f": [{"k": f"v{i}"} for i in range(100)]}
    spec = FacetSpec(group_counts={"by_k": "f[].k"}, max_group_keys=5)
    assert len(extract_facets(payload, spec)["by_k"]) == 5


def test_long_string_facets_are_clipped():
    payload = {"note": "x" * 5000}
    facets = extract_facets(payload, FacetSpec(paths={"note": "note"}))
    assert len(facets["note"]) < 300


def test_merge_sums_counts_and_merges_groups():
    spec = FacetSpec(counts={"n": "f[]"}, group_counts={"g": "f[].s"})
    merged = merge_facets(
        [{"n": 2, "g": {"high": 2}}, {"n": 3, "g": {"high": 1, "low": 3}}], spec
    )
    assert merged == {"n": 5, "g": {"low": 3, "high": 3}}


def test_estimate_bytes_never_raises_on_exotic_objects():
    class _Weird:
        def __repr__(self) -> str:
            return "weird"

    assert estimate_bytes(_Weird()) > 0
    assert estimate_bytes(None) == 0
    assert estimate_bytes(b"1234") == 4


# ── end-to-end over a scheduler stand-in ─────────────────────────────────────

async def _drive(plan, manager, wm):
    """Execute a plan the way AgentsFlow's scheduler does.

    Mirrors the real contract: fresh nodes, execute(ctx, deps), the return
    value stored into ctx.results, dependencies before dependents.
    """
    from parrot.bots.flows.plan.compile import to_flow_definition
    from parrot.bots.flows.plan.node import build_manifest, make_tool_node_factory

    fd = to_flow_definition(plan)
    factory = make_tool_node_factory(manager, wm)
    by_id = {n.id: n for n in fd.nodes if n.type == "tool"}

    ctx = _Ctx()
    refs = []
    for node_id in plan.topological_order():
        node_def = by_id[node_id]
        deps = {e.from_ for e in fd.edges if e.to == node_id}
        node = factory(node_def, deps, set())
        ref = await node.execute(ctx, {})
        ctx.results[node_id] = ref     # what mark_completed() stores
        refs.append(ref)
    return build_manifest(plan, refs), ctx


@pytest.mark.asyncio
async def test_end_to_end_plan_produces_a_bounded_manifest():
    from parrot.bots.flows.plan.models import ExecutionPlan

    reports = {
        "a.json": {"findings": [{"severity": "critical"}, {"severity": "low"}]},
        "b.json": {"findings": [{"severity": "critical"}]},
    }
    plan = ExecutionPlan(
        name="sweep",
        objective="Fetch reports and map criticals.",
        nodes=[
            PlanNode(id="listing", tool="list_reports", args={"prefix": "p/"},
                     store_as="listing",
                     facets=FacetSpec(counts={"n_reports": "keys[]"})),
            PlanNode(id="fetch", tool="get_report", args={"key": "{item}"},
                     store_as="report_{index}", depends_on=["listing"],
                     when="ctx.artifacts.listing.n_reports > 0",
                     for_each=ForEach(source="{artifacts.listing}", select="keys[]"),
                     facets=FacetSpec(group_counts={"by_sev": "findings[].severity"})),
            PlanNode(id="soc2", tool="map_soc2", args={"bodies": "{artifacts.fetch}"},
                     store_as="mapping", depends_on=["fetch"],
                     when="ctx.artifacts.fetch.by_sev.critical > 0",
                     facets=FacetSpec(counts={"n_controls": "controls[]"})),
        ],
    )
    wm = _WorkingMemory()
    manager = _ToolManager({
        "list_reports": {"keys": list(reports)},
        "get_report": lambda p: reports[p["key"]],
        "map_soc2": lambda p: {"controls": [{"id": "CC6.1"}, {"id": "CC7.2"}]},
    })

    manifest, ctx = await _drive(plan, manager, wm)

    assert manifest.nodes_ok == 3 and manifest.nodes_skipped == 0
    assert manifest.artifact("fetch").item_count == 2
    assert manifest.artifact("fetch").facets["by_sev"] == {"critical": 2, "low": 1}
    assert manifest.artifact("soc2").facets["n_controls"] == 2

    # Bodies live only in working memory.
    assert set(wm.writes) == {"listing", "report_0", "report_1", "mapping"}
    # And the whole manifest stays tiny regardless of payload size.
    assert len(manifest.model_dump_json()) < 2000
    assert all(isinstance(v, ArtifactRef) for v in ctx.results.values())


@pytest.mark.asyncio
async def test_end_to_end_guard_skips_downstream_without_failing_the_run():
    from parrot.bots.flows.plan.models import ExecutionPlan

    plan = ExecutionPlan(
        name="sweep",
        objective="Nothing to do when the listing is empty.",
        nodes=[
            PlanNode(id="listing", tool="list_reports", args={"prefix": "p/"},
                     store_as="listing",
                     facets=FacetSpec(counts={"n_reports": "keys[]"})),
            PlanNode(id="fetch", tool="get_report", args={"key": "{item}"},
                     store_as="report_{index}", depends_on=["listing"],
                     when="ctx.artifacts.listing.n_reports > 0",
                     for_each=ForEach(source="{artifacts.listing}", select="keys[]")),
        ],
    )
    wm = _WorkingMemory()
    manager = _ToolManager({"list_reports": {"keys": []}, "get_report": {}})

    manifest, _ = await _drive(plan, manager, wm)

    assert manifest.nodes_skipped == 1
    assert manifest.nodes_failed == 0
    assert [c[0] for c in manager.calls] == ["list_reports"]
