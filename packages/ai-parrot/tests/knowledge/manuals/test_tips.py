"""relink_tips matrix (FEAT-601 AC6)."""

from __future__ import annotations

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.models import Step, StepIdentity, content_hash
from parrot.knowledge.manuals.tips import add_tip, relink_tips, retire_tip

from .._support.graph import FakeGraphStore


def _step(manual_id: str, suffix: str, *, source_identity: str | None, text: str, order: int) -> Step:
    """Build one Step with substantiated evidence and a hash derived from ``text``."""
    full_id = f"{manual_id}:{suffix}"
    return Step(
        identity=StepIdentity(step_id=full_id, source_identity=source_identity, content_hash=content_hash(text)),
        order=order,
        text=Extracted(value=text, evidence=Evidence(node_id="n1", quote=text, page=1)),
    )


class _FlakyGraphStore(FakeGraphStore):
    """A graph double whose ``create_edges`` fails for one tip a fixed number of times."""

    def __init__(self, *, fail_tip_id: str, fail_times: int) -> None:
        super().__init__()
        self.fail_tip_id = fail_tip_id
        self.fail_times = fail_times
        self.fail_count = 0

    async def create_edges(self, ctx, edge_collection, edges):
        for edge in edges:
            if edge.get("source_id") == f"tech_tip/{self.fail_tip_id}" and self.fail_count < self.fail_times:
                self.fail_count += 1
                raise RuntimeError("simulated graph write failure")
        return await super().create_edges(ctx, edge_collection, edges)


@pytest.mark.asyncio
async def test_relink_tips_matrix() -> None:
    """Renumbered→source_identity, reworded-same-hash→content_hash, deleted→orphaned, changed torque→candidate."""
    store = FakeGraphStore()
    manual_id = "manual-x"

    previous = [
        _step(manual_id, "s1", source_identity="A1", text="Remove the cover plate", order=1),
        _step(manual_id, "s2", source_identity="A2", text="Torque bolt to 20 Nm", order=2),
        _step(manual_id, "s3", source_identity="A3", text="Torque the wheel nut to 100 Nm exactly", order=3),
        _step(manual_id, "s4", source_identity="A4", text="A step nobody will ever mention again", order=4),
        _step(manual_id, "s5", source_identity=None, text="Remove access screw", order=5),
    ]
    current = [
        _step(manual_id, "c1", source_identity="A1", text="Remove the cover plate", order=3),  # renumbered
        _step(manual_id, "c2", source_identity="B2", text="  Torque  BOLT to 20 nm  ", order=1),  # reworded, same hash
        _step(
            manual_id, "c3", source_identity="B3", text="Torque the wheel nut to 110 Nm exactly", order=2
        ),  # changed torque
        _step(
            manual_id, "c5a", source_identity="B5a", text="Remove access screw", order=6
        ),  # duplicate hash, higher order
        _step(
            manual_id, "c5b", source_identity="B5b", text="Remove access screw", order=4
        ),  # duplicate hash, lower order (wins)
        _step(manual_id, "c_new", source_identity="B_new", text="A brand new unrelated step", order=5),  # insert
    ]

    tips = {}
    for suffix, previous_step in zip(("s1", "s2", "s3", "s4", "s5"), previous, strict=True):
        tips[suffix] = await add_tip(
            store,
            None,
            step_id=previous_step.identity.step_id,
            text=f"tip for {suffix}",
            author_employee_id="tech-1",
            source_revision="rev-a",
        )

    report = await relink_tips(store, None, manual_id=manual_id, previous_steps=previous, current_steps=current)
    assert not report.failed

    by_tip_id = {outcome.tip_id: outcome for outcome in (report.relinked + report.orphaned + report.candidates)}

    outcome_s1 = by_tip_id[tips["s1"].tip_id]
    assert outcome_s1.method == "source_identity"
    assert outcome_s1.new_step_id == f"{manual_id}:c1"

    outcome_s2 = by_tip_id[tips["s2"].tip_id]
    assert outcome_s2.method == "content_hash"
    assert outcome_s2.new_step_id == f"{manual_id}:c2"

    outcome_s3 = by_tip_id[tips["s3"].tip_id]
    assert outcome_s3.method == "candidate"
    assert outcome_s3.new_step_id is None
    assert outcome_s3.candidates and outcome_s3.candidates[0][0] == f"{manual_id}:c3"

    outcome_s4 = by_tip_id[tips["s4"].tip_id]
    assert outcome_s4.method == "orphaned"
    assert outcome_s4.new_step_id is None

    outcome_s5 = by_tip_id[tips["s5"].tip_id]
    assert outcome_s5.method == "content_hash"
    assert outcome_s5.new_step_id == f"{manual_id}:c5b"  # lowest order wins the duplicate-hash tie

    doc_s1 = await store.get_document(None, "tech_tip", tips["s1"].tip_id)
    assert doc_s1["attached_step_id"] == f"{manual_id}:c1"
    assert doc_s1["orphaned"] is False
    assert doc_s1["history"][-1]["action"] == "relinked"

    doc_s3 = await store.get_document(None, "tech_tip", tips["s3"].tip_id)
    assert doc_s3["orphaned"] is True
    assert doc_s3["attached_step_id"] == previous[2].identity.step_id
    assert doc_s3["history"][-1]["action"] == "candidate"

    doc_s4 = await store.get_document(None, "tech_tip", tips["s4"].tip_id)
    assert doc_s4["orphaned"] is True
    assert doc_s4["attached_step_id"] == previous[3].identity.step_id
    assert doc_s4["history"][-1]["action"] == "orphaned"

    assert store.edge_pairs("tech_tip_on") >= {
        (f"tech_tip/{tips['s1'].tip_id}", f"step/{manual_id}:c1"),
        (f"tech_tip/{tips['s2'].tip_id}", f"step/{manual_id}:c2"),
        (f"tech_tip/{tips['s5'].tip_id}", f"step/{manual_id}:c5b"),
    }


@pytest.mark.asyncio
async def test_relink_is_idempotent() -> None:
    """Second run: only 'unchanged' outcomes, no new edges, history not re-appended."""
    store = FakeGraphStore()
    manual_id = "manual-y"
    previous = [
        _step(manual_id, "s1", source_identity="A1", text="Check oil level", order=1),
        _step(manual_id, "s2", source_identity=None, text="Replace filter", order=2),
    ]
    current = [
        _step(manual_id, "c1", source_identity="A1", text="Check oil level", order=1),
        _step(manual_id, "c2", source_identity="X2", text="Replace filter", order=2),
    ]
    tip1 = await add_tip(
        store,
        None,
        step_id=previous[0].identity.step_id,
        text="tip1",
        author_employee_id="tech-1",
        source_revision="rev-a",
    )
    tip2 = await add_tip(
        store,
        None,
        step_id=previous[1].identity.step_id,
        text="tip2",
        author_employee_id="tech-1",
        source_revision="rev-a",
    )

    first = await relink_tips(store, None, manual_id=manual_id, previous_steps=previous, current_steps=current)
    assert {outcome.method for outcome in first.relinked} == {"source_identity", "content_hash"}
    assert not first.candidates and not first.orphaned and not first.failed

    edges_after_first = list(store.edges.get("tech_tip_on", []))
    history_after_first = {
        tip1.tip_id: list((await store.get_document(None, "tech_tip", tip1.tip_id))["history"]),
        tip2.tip_id: list((await store.get_document(None, "tech_tip", tip2.tip_id))["history"]),
    }

    second = await relink_tips(store, None, manual_id=manual_id, previous_steps=previous, current_steps=current)
    assert {outcome.method for outcome in second.relinked} == {"unchanged"}
    assert not second.candidates and not second.orphaned and not second.failed
    assert store.edges.get("tech_tip_on", []) == edges_after_first

    for tip_id, history in history_after_first.items():
        doc = await store.get_document(None, "tech_tip", tip_id)
        assert doc["history"] == history


@pytest.mark.asyncio
async def test_relink_collects_failures() -> None:
    """A store that raises on one tip twice ⇒ tip_id in report.failed, others still processed."""
    manual_id = "manual-z"
    previous = [
        _step(manual_id, "s1", source_identity="A1", text="Step one text", order=1),
        _step(manual_id, "s2", source_identity="A2", text="Step two text", order=2),
    ]
    current = [
        _step(manual_id, "c1", source_identity="A1", text="Step one text", order=1),
        _step(manual_id, "c2", source_identity="A2", text="Step two text", order=2),
    ]
    setup_store = FakeGraphStore()
    tip_a = await add_tip(
        setup_store,
        None,
        step_id=previous[0].identity.step_id,
        text="tip-a",
        author_employee_id="tech-1",
        source_revision="rev-a",
    )
    tip_b = await add_tip(
        setup_store,
        None,
        step_id=previous[1].identity.step_id,
        text="tip-b",
        author_employee_id="tech-1",
        source_revision="rev-a",
    )

    flaky = _FlakyGraphStore(fail_tip_id=tip_a.tip_id, fail_times=2)
    flaky.nodes = setup_store.nodes
    flaky.edges = setup_store.edges

    report = await relink_tips(flaky, None, manual_id=manual_id, previous_steps=previous, current_steps=current)

    assert report.failed == [tip_a.tip_id]
    assert flaky.fail_count == 2

    relinked_ids = {outcome.tip_id for outcome in report.relinked}
    assert tip_b.tip_id in relinked_ids
    assert tip_a.tip_id not in relinked_ids

    # The failed tip must never end up disconnected: its original edge survives.
    assert (f"tech_tip/{tip_a.tip_id}", f"step/{previous[0].identity.step_id}") in flaky.edge_pairs("tech_tip_on")
    doc_a = await flaky.get_document(None, "tech_tip", tip_a.tip_id)
    assert doc_a["attached_step_id"] == previous[0].identity.step_id


@pytest.mark.asyncio
async def test_relink_never_crosses_manuals() -> None:
    """A step of another manual with the same hash is never a target."""
    store = FakeGraphStore()
    text = "Shared text that happens to match another manual"
    previous = [_step("manual-a", "s1", source_identity=None, text=text, order=1)]
    current = [_step("manual-b", "s1", source_identity=None, text=text, order=1)]  # same hash, wrong manual

    tip = await add_tip(
        store,
        None,
        step_id=previous[0].identity.step_id,
        text="cross-manual tip",
        author_employee_id="tech-1",
        source_revision="rev-a",
    )

    report = await relink_tips(store, None, manual_id="manual-a", previous_steps=previous, current_steps=current)

    assert not report.relinked
    assert not report.candidates
    assert len(report.orphaned) == 1
    assert report.orphaned[0].tip_id == tip.tip_id


@pytest.mark.asyncio
async def test_add_and_retire_tip() -> None:
    """add_tip writes tech_tip + tech_tip_on with origin=technician; retire flips active and appends history."""
    store = FakeGraphStore()
    tip = await add_tip(
        store,
        None,
        step_id="manual-x:s1",
        text="Grease the bearing first",
        author_employee_id="tech-7",
        source_revision="rev-a",
    )

    doc = await store.get_document(None, "tech_tip", tip.tip_id)
    assert doc["origin"] == "technician"
    assert doc["author_employee_id"] == "tech-7"
    assert doc["active"] is True
    assert doc["attached_step_id"] == "manual-x:s1"

    edges = store.edges["tech_tip_on"]
    assert len(edges) == 1
    assert edges[0]["kind"] == "tech_tip_on"
    assert edges[0]["origin"] == "technician"
    assert edges[0]["linked_by"] == "technician"
    assert edges[0]["_from"] == f"tech_tip/{tip.tip_id}"
    assert edges[0]["_to"] == "step/manual-x:s1"

    await retire_tip(store, None, tip_id=tip.tip_id, by="curator-9")

    retired = await store.get_document(None, "tech_tip", tip.tip_id)
    assert retired["active"] is False
    assert retired["history"][-1]["action"] == "retired"
    assert retired["history"][-1]["by"] == "curator-9"

    with pytest.raises(ValueError):
        await retire_tip(store, None, tip_id="missing-tip", by="curator-9")
