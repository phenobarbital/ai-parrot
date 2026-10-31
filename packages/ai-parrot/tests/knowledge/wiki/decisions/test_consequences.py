"""FEAT-784 M6 — ConsequenceService.evaluate() and governing()."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.knowledge.wiki.decisions.consequences import ConsequenceService, audit_configured
from parrot.knowledge.wiki.decisions.models import (
    AUDIT_NOT_CONFIGURED,
    SPEC_INVALID_ID,
    WAIVER_INVALID,
    DecisionConfig,
    DecisionRecord,
    DecisionTarget,
)
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.store import WikiPageRecord
from parrot.knowledge.wiki.structural.service import BlastRadiusOutput, ImpactedSymbol, SymbolHit

_TAXONOMY = """\
schema_version: 1
subsystems:
  - {id: core, title: Core, projects: [ai-parrot]}
  - {id: http, title: HTTP, projects: []}
mapping:
  networking: http
"""


def _hit(symbol_id: str) -> SymbolHit:
    rel, _, qual = symbol_id.removeprefix("sym:").partition("#")
    return SymbolHit(symbol_id=symbol_id, rel_path=rel, qualname=qual, kind="function", start_line=1, end_line=2)


class _StubStructural:
    """read_repair=False structural stub with a controllable blast radius."""

    _read_repair = False

    def __init__(self) -> None:
        self.impacted: list[ImpactedSymbol] = []
        self.truncated = False

    async def lookup(self, query, *, limit=20, **_):
        return SimpleNamespace(hits=[], total=0)

    async def blast_radius(self, symbol, *, relations=None, depth=2, include_inferred=True, include_tests=True):
        assert relations == ["calls", "extends", "implements", "uses"] and depth == 2 and include_tests
        return BlastRadiusOutput(root=_hit(symbol), impacted=list(self.impacted), truncated=self.truncated)


class _Adapter:
    """Verifies only the listed approval batch ids."""

    def __init__(self, allowed: set[str] | None = None) -> None:
        self.allowed = allowed or set()

    async def verify(self, entry, *, spec_text):
        return entry.batch_id in self.allowed, []


def _record(decision_id: str, **updates: object) -> DecisionRecord:
    values: dict[str, object] = {
        "decision_id": decision_id,
        "decision": decision_id,
        "origin": "documented",
        "source_status": "accepted",
    }
    values.update(updates)
    return DecisionRecord.model_validate(values)


def _v2(decision_id: str, normative: str, targets: list[str], about: list[str], **updates: object) -> DecisionRecord:
    kinds = {"sym:": "symbol", "file:": "file", "dir:": "dir"}
    typed = [DecisionTarget(target_id=t, kind=next(k for p, k in kinds.items() if t.startswith(p))) for t in targets]
    return _record(decision_id, schema_version=2, normative=normative, targets=typed, about=about, **updates)


def _spec(entries: str, *, waivers: str = "", extra: str = "") -> str:
    text = (
        "---\nprojects: [ai-parrot]\ntags: [networking, misc]\n---\n"
        "# Spec\n\n**Status**: draft\n\n"
        "## Decisions\n\n```yaml\nschema_version: 1\ndocument_id: feat-x\nentries:\n"
        f"{entries}```\n"
    )
    if waivers:
        text += f"\n## Decision Waivers\n\n```yaml\n{waivers}```\n"
    return text + extra


_ENTRY_A = """\
  - id: use-aiohttp
    statement: Require aiohttp for HTTP.
    relation: requires
    about: [http]
    targets: ["sym:pkg/a.py#f"]
"""


def _entry_contradicting(target: str) -> str:
    return (
        _ENTRY_A
        + "    contradicts: [{decision_id: '"
        + target
        + "', revision: 1}]\n"
    )


@pytest.fixture
async def plane(adr_store, tmp_path):
    """decision_plane: legacy schema-1 ADRs, a rejected one, a chain and >50 filler records."""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "sdd").mkdir()
    taxonomy = root / "sdd" / "subsystems.yaml"
    taxonomy.write_text(_TAXONOMY, encoding="utf-8")
    await adr_store.upsert_pages(
        [
            WikiPageRecord(concept_id="file:pkg/a.py", content_hash="h1"),
            WikiPageRecord(concept_id="sym:pkg/a.py#f", content_hash="h2"),
            WikiPageRecord(concept_id="dir:pkg", content_hash="h3"),
        ]
    )
    repo = DecisionRepository(adr_store)
    await repo.save(_record("adr:doc:legacy-accepted", review_status="accepted"), None)
    await repo.save(_record("adr:doc:legacy-unreviewed"), None)
    await repo.save(_record("adr:doc:rejected", review_status="rejected"), None)
    await repo.save(_v2("adr:doc:chain-a1", "constrains", ["file:pkg/z.py"], ["core"]), None)
    await repo.save(
        _v2(
            "adr:doc:chain-a2",
            "constrains",
            ["file:pkg/z.py"],
            ["core"],
            supersedes_refs=[{"decision_id": "adr:doc:chain-a1", "revision": 1}],
        ),
        None,
    )
    for index in range(60):
        await repo.save(_record(f"adr:doc:filler-{index:02d}"), None)
    structural = _StubStructural()
    approvals = root / "sdd" / "approvals.jsonl"
    service = ConsequenceService(
        adr_store,
        root,
        DecisionConfig(),
        structural,
        taxonomy_path=taxonomy,
        approvals_path=approvals,
        adapter=_Adapter({"waiver-1"}),
    )
    return SimpleNamespace(root=root, store=adr_store, repo=repo, structural=structural, service=service,
                           approvals=approvals)


def _write(root: Path, text: str, name: str = "spec.md") -> Path:
    (root / name).write_text(text, encoding="utf-8")
    return Path(name)


async def test_unconfigured_repo_is_skipped(tmp_path, adr_store):
    (tmp_path / "spec.md").write_text("# Spec\n\nNo decisions here.\n", encoding="utf-8")
    assert not audit_configured(tmp_path / "t.yaml", tmp_path / "a.jsonl")
    service = ConsequenceService(
        adr_store, tmp_path, DecisionConfig(), _StubStructural(),
        taxonomy_path=tmp_path / "t.yaml", approvals_path=tmp_path / "a.jsonl", adapter=_Adapter(),
    )
    report = await service.evaluate(Path("spec.md"))
    assert report.status == "skipped" and report.exit_code == 0
    dossier = await service.governing(Path("spec.md"))
    assert dossier.empty_plane and dossier.entries == []


async def test_block_in_unconfigured_repo_is_invalid(tmp_path, adr_store):
    (tmp_path / "spec.md").write_text(_spec(_ENTRY_A), encoding="utf-8")
    service = ConsequenceService(
        adr_store, tmp_path, DecisionConfig(), _StubStructural(),
        taxonomy_path=tmp_path / "t.yaml", approvals_path=tmp_path / "a.jsonl", adapter=_Adapter(),
    )
    report = await service.evaluate(Path("spec.md"))
    assert report.status == "invalid" and report.exit_code == 2
    assert AUDIT_NOT_CONFIGURED in {d.code for d in report.diagnostics}


async def test_clean_spec_passes(plane):
    report = await plane.service.evaluate(_write(plane.root, _spec(_ENTRY_A)))
    assert report.status == "pass", report.diagnostics
    assert report.coverage.subsystems == ["core", "http"]
    assert report.coverage.unmapped_tags == ["misc"]
    assert report.coverage.targets_resolved == report.coverage.targets_total == 1
    assert report.snapshot is not None


async def test_explicit_conflict_blocks_beyond_limit(plane):
    # filler-55 sorts far past the 50th eligible record.
    report = await plane.service.evaluate(_write(plane.root, _spec(_entry_contradicting("adr:doc:filler-55"))))
    assert report.status == "conflict" and report.exit_code == 1
    [finding] = [f for f in report.findings if f.kind == "contradiction"]
    assert finding.blocking and finding.waived_by is None
    assert {p.decision_id for p in finding.participants} == {"adr:doc:filler-55", "adr:spec:feat-x#use-aiohttp"}


async def test_reverse_contradiction_blocks(plane):
    await plane.repo.save(
        _record("adr:doc:reverse", schema_version=2, contradicts=[{"decision_id": "adr:spec:feat-x#use-aiohttp",
                                                                    "revision": 1}]),
        None,
    )
    report = await plane.service.evaluate(_write(plane.root, _spec(_ENTRY_A)))
    assert report.status == "conflict"


async def test_prospective_supersession_resolves_contradiction(plane):
    entry = _entry_contradicting("adr:doc:filler-03") + "    supersedes: [{decision_id: 'adr:doc:filler-03', revision: 1}]\n"
    report = await plane.service.evaluate(_write(plane.root, _spec(entry)))
    assert not any(f.kind == "contradiction" for f in report.findings)


async def test_polarity_overlap_is_advisory(plane):
    await plane.repo.save(_v2("adr:doc:no-httpx", "forbids", ["file:pkg/a.py"], ["core"]), None)
    report = await plane.service.evaluate(_write(plane.root, _spec(_ENTRY_A)))
    conflicts = [f for f in report.findings if f.kind == "potential-conflict"]
    assert len(conflicts) == 1 and not conflicts[0].blocking
    assert conflicts[0].scope == ["file:pkg/a.py"]
    assert report.status == "pass"


async def test_ancestor_scope_collected(plane):
    await plane.repo.save(_v2("adr:doc:dir-rule", "constrains", ["dir:pkg"], ["core"]), None)
    await plane.repo.save(_v2("adr:doc:other-rule", "forbids", ["file:other/b.py"], []), None)
    plane.structural.impacted = [
        ImpactedSymbol(symbol=_hit("sym:other/b.py#g"), via="calls", distance=1, provenance="extracted"),
        ImpactedSymbol(symbol=_hit("sym:other/c.py#h"), via="calls", distance=2, provenance="inferred"),
    ]
    spec_path = _write(plane.root, _spec(_ENTRY_A))
    dossier = await plane.service.governing(spec_path)
    ids = [entry.decision_id for entry in dossier.entries]
    assert "adr:doc:dir-rule" in ids and "adr:doc:other-rule" not in ids
    report = await plane.service.evaluate(spec_path)
    [blast] = [f for f in report.findings if f.kind == "blast-radius"]
    assert "sym:other/b.py#g" in blast.message and "inferred: sym:other/c.py#h" in blast.message
    assert not any("adr:doc:other-rule" in {p.decision_id for p in f.participants} for f in report.findings)


async def test_status_precedence(plane):
    plane.structural.truncated = True
    entry = _entry_contradicting("adr:doc:filler-10").replace("about: [http]", "about: [htp]")
    report = await plane.service.evaluate(_write(plane.root, _spec(entry)))
    assert report.status == "invalid" and report.exit_code == 2
    assert SPEC_INVALID_ID in {d.code for d in report.diagnostics}
    assert "http" in next(d.message for d in report.diagnostics if d.code == SPEC_INVALID_ID)
    assert report.coverage.impact_complete is False
    assert any(f.kind == "contradiction" and f.blocking for f in report.findings)


async def test_unresolved_target_is_invalid(plane):
    report = await plane.service.evaluate(_write(plane.root, _spec(_ENTRY_A.replace("#f", "#missing"))))
    assert report.status == "invalid"


async def test_digests_exclude_generated_sections(plane):
    text = _spec(_ENTRY_A)
    first = await plane.service.evaluate(_write(plane.root, text))
    edited = text.replace("**Status**: draft", "**Status**: approved") + "\n## Consequences\n\nGenerated.\n"
    second = await plane.service.evaluate(_write(plane.root, edited))
    assert first.input_digest == second.input_digest
    assert first.evaluation_digest == second.evaluation_digest


async def test_waiver_binding(plane):
    entry = _entry_contradicting("adr:doc:filler-20")
    base = await plane.service.evaluate(_write(plane.root, _spec(entry)))
    [finding] = [f for f in base.findings if f.kind == "contradiction"]
    plane.approvals.write_text(
        json.dumps(
            {
                "kind": "waiver",
                "batch_id": "waiver-1",
                "spec_path": "spec.md",
                "document_id": "feat-x",
                "entries": [],
                "block_sha256": "a" * 64,
                "commit": "a" * 40,
                "actor": "Ada <ada@example.com>",
                "recorded_at": "2026-10-31T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    participants = "".join(
        f"    - {{decision_id: '{p.decision_id}', revision: {p.revision}}}\n" for p in finding.participants
    )

    def waiver(actor: str, parts: str) -> str:
        return (
            f"- finding_fingerprint: '{finding.fingerprint}'\n  participants:\n{parts}"
            f"  actor: '{actor}'\n  reason: accepted risk\n  approval_ref: waiver-1\n"
        )

    ok = await plane.service.evaluate(_write(plane.root, _spec(entry, waivers=waiver("Ada <ada@example.com>",
                                                                                   participants))))
    assert ok.status == "pass", ok.diagnostics
    assert next(f for f in ok.findings if f.kind == "contradiction").waived_by == "waiver-1"

    forged = await plane.service.evaluate(_write(plane.root, _spec(entry, waivers=waiver("Mallory <m@x>",
                                                                                       participants))))
    assert forged.status == "conflict"
    assert WAIVER_INVALID in {d.code for d in forged.diagnostics}

    changed = participants.replace("filler-20", "filler-21")
    moved = await plane.service.evaluate(_write(plane.root, _spec(entry, waivers=waiver("Ada <ada@example.com>",
                                                                                      changed))))
    assert moved.status == "conflict"
    assert WAIVER_INVALID in {d.code for d in moved.diagnostics}


async def test_truncated_impact_is_incomplete(plane):
    plane.structural.truncated = True
    report = await plane.service.evaluate(_write(plane.root, _spec(_ENTRY_A)))
    assert report.status == "incomplete" and report.exit_code == 3
    assert report.coverage.impact_complete is False


async def test_read_repair_structural_is_incomplete(plane):
    plane.structural._read_repair = True
    report = await plane.service.evaluate(_write(plane.root, _spec(_ENTRY_A)))
    assert report.status == "incomplete"


async def test_supersession_fault_is_invalid(plane):
    await plane.repo.save(
        _v2("adr:doc:bad", "constrains", ["file:pkg/q.py"], ["core"],
            supersedes_refs=[{"decision_id": "adr:doc:legacy-accepted", "revision": 9}]),
        None,
    )
    report = await plane.service.evaluate(_write(plane.root, _spec(_ENTRY_A)))
    assert report.status == "invalid"


async def test_evaluate_never_constructs_llm(plane, monkeypatch):
    from parrot.clients.factory import LLMFactory

    def _boom(*args, **kwargs):
        raise AssertionError("LLMFactory.create must never be called")

    monkeypatch.setattr(LLMFactory, "create", staticmethod(_boom))
    spec_path = _write(plane.root, _spec(_entry_contradicting("adr:doc:filler-01")))
    report = await plane.service.evaluate(spec_path)
    assert report.status == "conflict"
    dossier = await plane.service.governing(spec_path)
    assert dossier.entries and not dossier.empty_plane
