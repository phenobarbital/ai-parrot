"""FEAT-784 M5 — inventory snapshot and eligibility."""

from __future__ import annotations

import json

import pytest

from parrot.knowledge.wiki.decisions.approvals import ApprovalManifest
from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, batch_marker_id, is_eligible
from parrot.knowledge.wiki.decisions.models import (
    ADR_INVENTORY_LIMIT,
    SNAPSHOT_UNSTABLE,
    SUPERSESSION_INVALID,
    DecisionError,
    DecisionRef,
    DecisionRecord,
    DecisionTarget,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy
from parrot.knowledge.wiki.store import WikiPageRecord


class _OkAdapter:
    """Approval adapter used where no approved spec records are required."""

    async def verify(self, entry, *, spec_text):
        """Accept every entry in this isolated unit test."""
        return True, []


def _record(decision_id: str, **updates: object) -> DecisionRecord:
    """Build an accepted documented decision with optional schema-2 fields."""
    values: dict[str, object] = {
        "decision_id": decision_id,
        "decision": decision_id,
        "origin": "documented",
        "source_status": "accepted",
    }
    values.update(updates)
    return DecisionRecord.model_validate(values)


def _taxonomy(tmp_path) -> Taxonomy:
    """Create the smallest valid taxonomy used by snapshots."""
    path = tmp_path / "subsystems.yaml"
    path.write_text("schema_version: 1\nsubsystems: [{id: core, title: Core, projects: [ai-parrot]}]\n")
    return Taxonomy.load(path)


async def _snapshot(adr_store, tmp_path, repo: DecisionRepository | None = None) -> InventorySnapshot:
    """Read a snapshot with no approval entries."""
    return await InventorySnapshot.take(
        repo or DecisionRepository(adr_store),
        _taxonomy(tmp_path),
        ApprovalManifest.load(tmp_path / "approvals.jsonl"),
        _OkAdapter(),
        "structural-1",
        store=adr_store,
        root=tmp_path,
        config_digest="config-1",
    )


def test_eligibility_predicate() -> None:
    """AC6: legacy acceptance and approved schema-2 batch semantics are exact."""
    legacy = _record("adr:doc:legacy")
    assert is_eligible(legacy, approved_batches=frozenset())
    assert not is_eligible(legacy.model_copy(update={"review_status": "rejected"}), approved_batches=frozenset())
    assert not is_eligible(legacy.model_copy(update={"lifecycle": "retired"}), approved_batches=frozenset())
    spec = _record("adr:spec:feat#one", schema_version=2, batch_id="batch-1")
    assert not is_eligible(spec, approved_batches=frozenset())
    assert is_eligible(spec, approved_batches=frozenset({"batch-1"}))


async def test_snapshot_collects_full_inventory(adr_store, tmp_path) -> None:
    """AC5: the snapshot retains all eligible records rather than a dossier budget."""
    repo = DecisionRepository(adr_store)
    for index in range(60):
        await repo.save(_record(f"adr:doc:{index}"), None)
    snapshot = await _snapshot(adr_store, tmp_path, repo)
    assert len(snapshot.eligible) == 60


@pytest.mark.parametrize("case", ["cycle", "changed_revision", "competing", "partial_targets"])
async def test_supersession_graph_validation(adr_store, tmp_path, case: str) -> None:
    """AC8: invalid supersession is diagnosed and never hides a predecessor."""
    repo = DecisionRepository(adr_store)
    target = DecisionTarget(target_id="file:pkg/a.py", kind="file")
    first = _record("adr:doc:first", schema_version=2, targets=[target])
    second = _record(
        "adr:doc:second",
        schema_version=2,
        targets=[] if case == "partial_targets" else [target],
        supersedes_refs=[{"decision_id": "adr:doc:first", "revision": 2 if case == "changed_revision" else 1}],
    )
    await repo.save(first, None)
    await repo.save(second, None)
    if case == "cycle":
        first = first.model_copy(
            update={"supersedes_refs": [DecisionRef(decision_id="adr:doc:second", revision=1)]}
        )
        await repo.save(first, (await repo.get(first.decision_id))[1])
    if case == "competing":
        third = _record(
            "adr:doc:third", schema_version=2, targets=[target], supersedes_refs=[{"decision_id": "adr:doc:first", "revision": 1}]
        )
        await repo.save(third, None)
    snapshot = await _snapshot(adr_store, tmp_path, repo)
    assert SUPERSESSION_INVALID in {diagnostic.code for diagnostic in snapshot.diagnostics}
    assert "adr:doc:first" in {record.decision_id for record in snapshot.eligible}


async def test_snapshot_unstable_is_incomplete(adr_store, tmp_path, monkeypatch) -> None:
    """A changed phase-two page hash has a concrete, failing observable effect."""
    repo = DecisionRepository(adr_store)
    await repo.save(_record("adr:doc:one"), None)

    async def changed_hashes(ids: list[str]) -> dict[str, str | None]:
        return {concept_id: "changed" for concept_id in ids}

    monkeypatch.setattr(adr_store, "page_hashes", changed_hashes)
    with pytest.raises(DecisionError) as exc:
        await _snapshot(adr_store, tmp_path, repo)
    assert exc.value.code == SNAPSHOT_UNSTABLE


async def test_inventory_overflow_raises(adr_store, tmp_path) -> None:
    """The repository's bounded inventory error propagates unchanged."""
    writer = DecisionRepository(adr_store)
    await writer.save(_record("adr:doc:one"), None)
    await writer.save(_record("adr:doc:two"), None)
    with pytest.raises(DecisionError) as exc:
        await _snapshot(adr_store, tmp_path, DecisionRepository(adr_store, max_records=1))
    assert exc.value.code == ADR_INVENTORY_LIMIT


async def test_unpublished_batch_is_invisible(adr_store, tmp_path) -> None:
    """A verified batch remains invisible until its marker becomes published."""
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("spec", encoding="utf-8")
    manifest_path = tmp_path / "approvals.jsonl"
    manifest_path.write_text(
        json.dumps(
            {
                "kind": "spec", "batch_id": "batch-1", "spec_path": "spec.md", "document_id": "feat",
                "entries": [], "block_sha256": "a" * 64, "commit": "a" * 40,
                "actor": "Ada <ada@example.com>", "recorded_at": "2026-10-31T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    await DecisionRepository(adr_store).save(
        _record("adr:spec:feat#one", schema_version=2, batch_id="batch-1"), None
    )
    approvals = ApprovalManifest.load(manifest_path)
    before = await InventorySnapshot.take(
        DecisionRepository(adr_store), _taxonomy(tmp_path), approvals, _OkAdapter(), "structural-1",
        store=adr_store, root=tmp_path, config_digest="config-1",
    )
    assert before.eligible == []
    await adr_store.upsert_pages(
        [WikiPageRecord(concept_id=batch_marker_id("batch-1"), category="adr_batch", body='{"state":"published"}')]
    )
    after = await InventorySnapshot.take(
        DecisionRepository(adr_store), _taxonomy(tmp_path), approvals, _OkAdapter(), "structural-1",
        store=adr_store, root=tmp_path, config_digest="config-1",
    )
    assert [record.decision_id for record in after.eligible] == ["adr:spec:feat#one"]
