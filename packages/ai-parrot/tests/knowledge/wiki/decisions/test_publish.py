"""FEAT-784 M8 — batch publication and ingest extensions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from parrot.knowledge.wiki.decisions.approvals import ApprovalEntry, ApprovalManifest
from parrot.knowledge.wiki.decisions.consequences import ConsequenceReport
from parrot.knowledge.wiki.decisions.ingest import discover_adr_sources, project_links
from parrot.knowledge.wiki.decisions.inventory import batch_marker_id, is_eligible
from parrot.knowledge.wiki.decisions.models import (
    ADR_REVISION_CONFLICT,
    APPROVAL_UNVERIFIED,
    BATCH_PARTIAL,
    DecisionConfig,
    DecisionError,
    DecisionRecord,
    DecisionRef,
)
from parrot.knowledge.wiki.decisions.publish import BatchPublisher, PublishResult, _marker_page
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.spec_entries import canonical_block_bytes, parse_spec_decisions

FENCE = "`" * 3
SPEC_PATH = "sdd/specs/demo.spec.md"
BATCH = "batch-1"


def _spec(supersedes: str = "") -> str:
    return f"""# Spec

## Decisions

{FENCE}yaml
schema_version: 1
document_id: demo
entries:
  - id: one
    statement: Clients never persist history.
    relation: forbids
    about: [clients]
    targets: [dir:src/clients]
{supersedes}  - id: two
    statement: Bots own history.
    relation: requires
    about: [memory]
    targets: [file:src/bots.py]
{FENCE}
"""


_SUPERSEDES = '    supersedes: [{decision_id: "adr:doc:old", revision: 1}]\n'


class _Adapter:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    async def verify(self, entry, *, spec_text):
        return self.ok, []


class _Service:
    def __init__(self, status: str = "pass") -> None:
        self.status = status
        self.calls: list[tuple[Path, str]] = []

    async def evaluate(self, spec_path, *, mode="preview"):
        self.calls.append((spec_path, mode))
        return ConsequenceReport(status=self.status, exit_code=0 if self.status == "pass" else 1)


def _setup(tmp_path: Path, text: str) -> ApprovalManifest:
    path = tmp_path / SPEC_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    block, _, diags = parse_spec_decisions(text, source_path=SPEC_PATH)
    assert block is not None, diags
    entry = ApprovalEntry(
        kind="spec", batch_id=BATCH, spec_path=SPEC_PATH, document_id="demo",
        entries=[DecisionRef(decision_id=f"adr:spec:demo#{e.id}", revision=1) for e in block.entries],
        block_sha256=hashlib.sha256(canonical_block_bytes(block)).hexdigest(),
        commit="abcdef0", actor="me <me@x>", recorded_at="2026-10-31",
    )
    return ApprovalManifest([entry], b"")


def _publisher(store, tmp_path, manifest, *, ok=True, status="pass") -> BatchPublisher:
    return BatchPublisher(store, tmp_path, DecisionConfig(), _Service(status), manifest, _Adapter(ok))


async def _marker_state(store) -> str | None:
    page = await store.get_page(batch_marker_id(BATCH))
    return None if page is None else json.loads(page["body"])["state"]


async def test_publish_all_or_nothing(adr_store, tmp_path, monkeypatch):
    manifest = _setup(tmp_path, _spec())
    original = DecisionRepository.save
    calls = {"n": 0}

    async def flaky(self, record, expected):
        calls["n"] += 1
        if calls["n"] == 2:
            raise DecisionError(ADR_REVISION_CONFLICT, "injected", decision_id=record.decision_id)
        return await original(self, record, expected)

    monkeypatch.setattr(DecisionRepository, "save", flaky)
    result = await _publisher(adr_store, tmp_path, manifest).publish(BATCH)
    assert result.status == "refused"
    assert await _marker_state(adr_store) == "pending"
    records = await DecisionRepository(adr_store).inventory()
    assert records and not any(is_eligible(r, approved_batches=frozenset()) for r in records)

    monkeypatch.setattr(DecisionRepository, "save", original)
    retry = await _publisher(adr_store, tmp_path, manifest).publish(BATCH)
    assert retry.status == "published"
    assert retry.written == 1 and retry.skipped == 1
    assert await _marker_state(adr_store) == "published"


async def test_publish_is_idempotent(adr_store, tmp_path, monkeypatch):
    manifest = _setup(tmp_path, _spec())
    first = await _publisher(adr_store, tmp_path, manifest).publish(BATCH)
    assert first.status == "published" and first.written == 2

    async def forbidden(*args, **kwargs):
        raise AssertionError("no writes expected")

    monkeypatch.setattr(type(adr_store), "compare_and_swap_page", forbidden)
    second = await _publisher(adr_store, tmp_path, manifest).publish(BATCH)
    assert isinstance(second, PublishResult)
    assert second.status == "already-published"
    assert second.written == 0 and second.skipped == 2


async def test_retirement_after_successor(adr_store, tmp_path, monkeypatch):
    repo = DecisionRepository(adr_store)
    old = DecisionRecord(
        schema_version=2, decision_id="adr:doc:old", decision="old", origin="documented", source_status="accepted"
    )
    await repo.save(old, None)
    manifest = _setup(tmp_path, _spec(_SUPERSEDES))

    order: list[str] = []
    original_cas = type(adr_store).compare_and_swap_page

    async def spy(self, page, expected):
        order.append(f"{page.concept_id}:{page.summary}" if page.concept_id.startswith("adr-batch:") else page.concept_id)
        return await original_cas(self, page, expected)

    monkeypatch.setattr(type(adr_store), "compare_and_swap_page", spy)
    result = await _publisher(adr_store, tmp_path, manifest).publish(BATCH)
    assert result.status == "published" and result.retired == 1
    assert order.index("adr:doc:old") > order.index(f"{batch_marker_id(BATCH)}:published")
    got, _ = await repo.get("adr:doc:old")
    assert got.lifecycle == "retired" and got.source_status == "superseded"


async def test_replay_uses_recorded_baseline(adr_store, tmp_path):
    manifest = _setup(tmp_path, _spec())
    publisher = _publisher(adr_store, tmp_path, manifest)
    result = await publisher.publish(BATCH)
    assert result.status == "published"
    assert publisher.service.calls == [(Path(SPEC_PATH), "replay")]


async def test_refuses_unverified_or_non_pass(adr_store, tmp_path):
    manifest = _setup(tmp_path, _spec())
    unverified = await _publisher(adr_store, tmp_path, manifest, ok=False).publish(BATCH)
    assert unverified.status == "refused" and unverified.diagnostics[0].code == APPROVAL_UNVERIFIED
    conflict = await _publisher(adr_store, tmp_path, manifest, status="conflict").publish(BATCH)
    assert conflict.status == "refused"
    unknown = await _publisher(adr_store, tmp_path, manifest).publish("nope")
    assert unknown.status == "refused"
    # edited after approval: digest mismatch
    (tmp_path / SPEC_PATH).write_text(_spec().replace("never persist", "rarely persist"), encoding="utf-8")
    edited = await _publisher(adr_store, tmp_path, manifest).publish(BATCH)
    assert edited.status == "refused"
    assert await adr_store.get_page(batch_marker_id(BATCH)) is None
    assert await DecisionRepository(adr_store).inventory() == []


async def test_refuses_marker_in_unknown_state(adr_store, tmp_path):
    manifest = _setup(tmp_path, _spec())
    await adr_store.compare_and_swap_page(_marker_page(BATCH, "weird", []), None)
    result = await _publisher(adr_store, tmp_path, manifest).publish(BATCH)
    assert result.status == "refused" and result.diagnostics[0].code == BATCH_PARTIAL


def test_seed_files_excluded_from_legacy_discovery(tmp_path, adr_config):
    d = tmp_path / "docs" / "decisions"
    d.mkdir(parents=True)
    (d / "plain.md").write_text("# ADR\n\nStatus: accepted\n", encoding="utf-8")
    (d / "seed.md").write_text("# Seed\n\n## Decision Metadata\n\nx\n", encoding="utf-8")
    (tmp_path / "sdd" / "specs").mkdir(parents=True)
    (tmp_path / "sdd" / "specs" / "a.spec.md").write_text("x", encoding="utf-8")
    assert discover_adr_sources(tmp_path, adr_config) == ["docs/decisions/plain.md"]
    batch = discover_adr_sources(
        tmp_path, adr_config, approved_specs=["sdd/specs/a.spec.md", "sdd/specs/missing.md", "../escape.md"]
    )
    assert batch == ["docs/decisions/seed.md", "sdd/specs/a.spec.md"]


async def test_project_links_about_and_normative_edges():
    class _Store:
        def __init__(self):
            self.edges = []

        async def add_edges(self, edges):
            self.edges.extend(edges)
            return len(edges)

    from parrot.knowledge.wiki.decisions.models import DecisionLink, DecisionTarget

    active = DecisionRecord(
        schema_version=2, decision_id="adr:spec:d#a", decision="a", origin="documented", source_status="accepted",
        about=["memory"], normative="forbids", targets=[DecisionTarget(target_id="dir:src", kind="dir")],
    )
    retired = active.model_copy(update={"decision_id": "adr:spec:d#b", "lifecycle": "retired"})
    legacy = DecisionRecord(
        decision_id="adr:doc:x", decision="x", origin="documented",
        links=[DecisionLink(target_id="file:a.py", relation="explains", provenance="extracted")],
    )
    store = _Store()
    count = await project_links(store, [active, retired, legacy])
    assert count == 3
    assert set(store.edges) == {
        ("adr:doc:x", "file:a.py", "explains", "extracted"),
        ("adr:spec:d#a", "concept:memory", "about", "asserted"),
        ("adr:spec:d#a", "dir:src", "forbids", "asserted"),
    }

