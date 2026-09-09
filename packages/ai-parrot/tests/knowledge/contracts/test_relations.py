"""Explicit bounded relation judgement tests (TASK-3040)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from parrot.knowledge.contracts.library import ContractLibrary
from parrot.knowledge.contracts.models import (
    ContractCard,
    Obligation,
    Party,
    TermSpec,
)
from parrot.knowledge.contracts.relations import (
    DEFAULT_MAX_CANDIDATES,
    RELATION_SYSTEM_PROMPT,
    ContractRelationStage,
    RelationBatchDraft,
    RelationJudgementDraft,
    candidate_contracts,
    canonical_pair,
)

from .test_catalog_contract import InMemoryContractCatalog
from .test_ingestion import FakeIndexer, MSA_MARKDOWN, write

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def card(contract_id: str, **overrides) -> ContractCard:
    """A synthetic card with one obligation."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} agreement",
        "contract_type": "msa",
        "status": "active",
        "source_uri": f"sharepoint://legal/{contract_id}.pdf",
        "source_sha256": f"sha-{contract_id}",
        "source_format": "pdf",
        "parties": [Party(party_id="party-acme", name="ACME Inc.", role="customer")],
        "term": TermSpec(effective_date=date(2026, 1, 1)),
        "obligations": [
            Obligation(
                obligation_id=f"{contract_id}-ob-001",
                contract_id=contract_id,
                kind="compliance",
                text="Vendor shall maintain SOC 2.",
                node_id="0005",
            )
        ],
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


class FakeAdapter:
    """Counts judgement calls and replays scripted batches."""

    model = "test-model"

    def __init__(self, batches: Optional[dict[str, RelationBatchDraft]] = None) -> None:
        self.batches = batches or {}
        self.calls: list[str] = []
        self.system_prompts: list[Optional[str]] = []
        self.fail = False

    async def ask_structured(self, prompt, output_type, temperature=0.0, system_prompt=None):
        self.calls.append(prompt)
        self.system_prompts.append(system_prompt)
        if self.fail:
            raise RuntimeError("model unavailable")
        source = prompt.split("- id: ")[1].split("\n")[0].strip()
        return self.batches.get(source, RelationBatchDraft())


@pytest.fixture()
async def stage() -> ContractRelationStage:
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    await catalog.upsert(card("acme-msa"))
    await catalog.upsert(card("acme-sow", contract_type="sow", parent_contract_id="acme-msa"))
    return ContractRelationStage(
        catalog=catalog, adapter=FakeAdapter(), now=lambda: FROZEN_NOW
    )


# --------------------------------------------------------------------------
# Candidate selection
# --------------------------------------------------------------------------


def test_candidates_cover_counterparty_family_and_obligation_kinds():
    source = card("acme-msa")
    same_party = card("acme-nda", contract_type="nda")
    family = card("acme-sow", contract_type="sow", parent_contract_id="acme-msa")
    same_kind = card(
        "zeta-dpa",
        contract_type="dpa",
        parties=[Party(party_id="party-zeta", name="Zeta LLC", role="vendor")],
    )
    unrelated = card(
        "omega-sla",
        contract_type="sla",
        parties=[Party(party_id="party-omega", name="Omega SA", role="vendor")],
        obligations=[],
    )

    pairs = candidate_contracts(source, [same_party, family, same_kind, unrelated])
    assert [pair.target_contract_id for pair in pairs] == [
        "acme-nda",
        "acme-sow",
        "zeta-dpa",
    ]
    assert pairs[0].reason == "shared counterparty"
    assert pairs[2].reason == "overlapping obligation kinds"
    assert "omega-sla" not in {pair.target_contract_id for pair in pairs}


def test_candidate_order_is_stable_and_bounded():
    source = card("acme-msa")
    others = [card(f"acme-{index:02d}") for index in range(20)]
    first = candidate_contracts(source, others, max_candidates=3)
    assert len(first) == 3
    assert first == candidate_contracts(source, list(reversed(others)), max_candidates=3)
    assert DEFAULT_MAX_CANDIDATES == 8


def test_a_contract_is_never_its_own_candidate():
    source = card("acme-msa")
    assert candidate_contracts(source, [source]) == []


def test_symmetric_pairs_are_canonicalised():
    assert canonical_pair("zeta", "acme") == ("acme", "zeta")
    assert canonical_pair("acme", "zeta") == canonical_pair("zeta", "acme")


# --------------------------------------------------------------------------
# 1. Bounded calls, membership, endpoint rejection
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_structured_call_per_source_contract(stage):
    report = await stage.relate()
    assert report.calls == 2, "one call per source contract, not per pair"
    assert set(stage.adapter.system_prompts) == {RELATION_SYSTEM_PROMPT}


@pytest.mark.asyncio
async def test_none_outcomes_are_logged_not_discarded(stage):
    report = await stage.relate(["acme-msa"])

    assert report.none_outcomes == 1
    assert report.judged == ["acme-msa->acme-sow=none"]
    history = await stage.catalog.judgements_for("acme-msa")
    assert [judgement.outcome for judgement in history] == ["none"]
    assert history[0].model == "test-model"
    assert history[0].source_sha256 == "sha-acme-msa"
    assert history[0].target_sha256 == "sha-acme-sow"
    assert await stage.catalog.active_relations("acme-msa") == []


@pytest.mark.asyncio
async def test_a_conflicts_verdict_writes_one_canonical_edge(stage):
    stage.adapter.batches["acme-sow"] = RelationBatchDraft(
        judgements=[
            RelationJudgementDraft(
                target_contract_id="acme-msa",
                outcome="conflicts_with",
                confidence=0.8,
                rationale="notice periods disagree",
            )
        ]
    )
    report = await stage.relate(["acme-sow"])

    assert len(report.relations) == 1
    relation = report.relations[0]
    assert (relation.source_contract_id, relation.target_contract_id) == (
        "acme-msa",
        "acme-sow",
    ), "the symmetric pair is canonicalised"
    # Traversable from either endpoint.
    assert len(await stage.related("acme-sow")) == 1
    assert len(await stage.related("acme-msa")) == 1


@pytest.mark.asyncio
async def test_endpoints_outside_the_candidate_set_are_rejected(stage):
    stage.adapter.batches["acme-msa"] = RelationBatchDraft(
        judgements=[
            RelationJudgementDraft(target_contract_id="acme-msa", outcome="conflicts_with"),
            RelationJudgementDraft(target_contract_id="other-tenant-contract", outcome="conflicts_with"),
            RelationJudgementDraft(target_contract_id="does-not-exist", outcome="conflicts_with"),
        ]
    )
    report = await stage.relate(["acme-msa"])

    assert report.relations == []
    assert any("self-judgement" in reason for reason in report.rejected)
    assert sum("was not a candidate" in reason for reason in report.rejected) == 2
    assert await stage.catalog.active_relations("acme-msa") == []


@pytest.mark.asyncio
async def test_unknown_source_contracts_are_reported(stage):
    report = await stage.relate(["ghost"])
    assert report.rejected == ["ghost"]
    assert report.calls == 0


@pytest.mark.asyncio
async def test_references_obligation_must_be_cross_contract(stage):
    stage.adapter.batches["acme-sow"] = RelationBatchDraft(
        judgements=[
            RelationJudgementDraft(
                target_contract_id="acme-msa",
                outcome="references_obligation",
                source_obligation_id="acme-sow-ob-001",
                target_obligation_id="acme-msa-ob-001",
                confidence=0.9,
            )
        ]
    )
    report = await stage.relate(["acme-sow"])
    relation = report.relations[0]
    assert relation.kind == "references_obligation"
    assert relation.source_contract_id == "acme-sow"
    assert relation.target_contract_id == "acme-msa"
    assert relation.source_obligation_id == "acme-sow-ob-001"


@pytest.mark.asyncio
async def test_references_obligation_with_bad_obligations_degrades_to_none(stage):
    stage.adapter.batches["acme-sow"] = RelationBatchDraft(
        judgements=[
            RelationJudgementDraft(
                target_contract_id="acme-msa",
                outcome="references_obligation",
                source_obligation_id="acme-msa-ob-001",  # belongs to the target
                target_obligation_id="acme-msa-ob-001",
            )
        ]
    )
    report = await stage.relate(["acme-sow"])

    assert report.relations == []
    assert any("references_obligation needs two obligations" in item for item in report.rejected)
    assert (await stage.catalog.judgements_for("acme-sow"))[0].outcome == "none"


@pytest.mark.asyncio
async def test_an_unknown_outcome_is_recorded_as_none(stage):
    stage.adapter.batches["acme-msa"] = RelationBatchDraft(
        judgements=[
            RelationJudgementDraft(target_contract_id="acme-sow", outcome="supersedes")
        ]
    )
    report = await stage.relate(["acme-msa"])
    assert report.none_outcomes == 1
    assert report.relations == []


@pytest.mark.asyncio
async def test_a_failed_batch_is_reported_without_aborting(stage):
    stage.adapter.fail = True
    report = await stage.relate()
    assert report.calls == 2
    assert len(report.errors) == 2
    assert report.relations == []


@pytest.mark.asyncio
async def test_without_an_adapter_nothing_is_judged():
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    await catalog.upsert(card("acme-msa"))
    stage = ContractRelationStage(catalog=catalog, adapter=None)
    report = await stage.relate()
    assert report.calls == 0
    assert "no LLM adapter" in report.errors[0]


# --------------------------------------------------------------------------
# 2. Replay, force and invalidation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_without_force_reuses_the_stored_outcome(stage):
    await stage.relate(["acme-msa"])
    assert stage.adapter.calls and len(stage.adapter.calls) == 1

    replay = await stage.relate(["acme-msa"])
    assert replay.calls == 0, "an active judgement is not re-asked"
    assert replay.skipped == ["acme-msa->acme-sow"]
    assert len(await stage.catalog.judgements_for("acme-msa")) == 1


@pytest.mark.asyncio
async def test_force_appends_history_and_replaces_the_active_result(stage):
    await stage.relate(["acme-msa"])
    stage.adapter.batches["acme-msa"] = RelationBatchDraft(
        judgements=[
            RelationJudgementDraft(
                target_contract_id="acme-sow", outcome="conflicts_with", confidence=0.7
            )
        ]
    )
    forced = await stage.relate(["acme-msa"], force=True)

    assert forced.calls == 1
    history = await stage.catalog.judgements_for("acme-msa")
    assert [judgement.outcome for judgement in history] == ["none", "conflicts_with"]
    assert len(await stage.catalog.active_relations("acme-msa")) == 1


@pytest.mark.asyncio
async def test_a_changed_source_hash_invalidates_stale_edges(stage):
    stage.adapter.batches["acme-sow"] = RelationBatchDraft(
        judgements=[
            RelationJudgementDraft(target_contract_id="acme-msa", outcome="conflicts_with")
        ]
    )
    await stage.relate(["acme-sow"])
    assert len(await stage.catalog.active_relations("acme-sow")) == 1

    stored = await stage.catalog.get("acme-sow")
    await stage.catalog.upsert(
        stored.model_copy(update={"source_sha256": "sha-refreshed"}), expected_revision=1
    )
    report = await stage.relate(["acme-sow"])

    assert report.invalidated >= 1
    history = await stage.catalog.judgements_for("acme-sow")
    assert history[0].active is False, "the old judgement is invalidated, not deleted"


@pytest.mark.asyncio
async def test_a_none_verdict_removes_a_previously_active_relation(stage):
    stage.adapter.batches["acme-sow"] = RelationBatchDraft(
        judgements=[
            RelationJudgementDraft(target_contract_id="acme-msa", outcome="conflicts_with")
        ]
    )
    await stage.relate(["acme-sow"])
    assert len(await stage.catalog.active_relations("acme-sow")) == 1

    stage.adapter.batches["acme-sow"] = RelationBatchDraft(
        judgements=[RelationJudgementDraft(target_contract_id="acme-msa", outcome="none")]
    )
    await stage.relate(["acme-sow"], force=True)
    assert await stage.catalog.active_relations("acme-sow") == []


# --------------------------------------------------------------------------
# 3. Wiring: explicit ingest / relate only
# --------------------------------------------------------------------------


@pytest.fixture()
def library(tmp_path):
    """A library whose relation stage can be observed."""
    indexers: dict[Path, FakeIndexer] = {}
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    return ContractLibrary(
        catalog=catalog,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
        adapter=None,
        indexer_factory=lambda directory, adapter: indexers.setdefault(
            Path(directory), FakeIndexer(directory, adapter)
        ),
        now=lambda: FROZEN_NOW,
        today=lambda: date(2026, 9, 9),
    )


@pytest.mark.asyncio
async def test_library_exposes_relate_contracts(library, tmp_path):
    await library.add_contract(write(tmp_path, "acme-msa.md"))
    report = await library.relate_contracts()
    assert "no LLM adapter" in report.errors[0], "no adapter configured in this fixture"


@pytest.mark.asyncio
async def test_ingestion_does_not_judge_relations_by_default(library, tmp_path, monkeypatch):
    calls: list[Any] = []

    async def spy(self, contract_ids=None, *, force=False):
        calls.append(contract_ids)
        return await ContractRelationStage.relate(self, contract_ids, force=force)

    monkeypatch.setattr(ContractRelationStage, "relate", spy)
    assert library.relate_on_ingest is False

    await library.add_contract(write(tmp_path, "acme-msa.md"))
    assert calls == [], "judgement is explicit; ingestion does not trigger it"


@pytest.mark.asyncio
async def test_relate_on_ingest_wires_the_stage_at_ingest_time(library, tmp_path):
    """With the flag on, ingestion drives the judgement stage explicitly."""
    judge = FakeAdapter()
    stage = ContractRelationStage(
        catalog=library.catalog, adapter=judge, now=lambda: FROZEN_NOW
    )
    seen: list[Any] = []
    original = stage.relate

    async def spy(contract_ids=None, *, force=False):
        seen.append(list(contract_ids) if contract_ids else None)
        return await original(contract_ids, force=force)

    stage.relate = spy  # type: ignore[method-assign]
    library._relation_stage = stage
    library.relate_on_ingest = True

    await library.add_contract(write(tmp_path, "acme-msa.md"))
    await library.add_contract(
        write(tmp_path, "acme-sow.md", MSA_MARKDOWN + "\n\nStatement of work.\n")
    )

    assert seen == [["acme-msa"], ["acme-sow"]]


@pytest.mark.asyncio
async def test_ingest_time_judgement_spends_calls_only_when_candidates_exist(tmp_path):
    """Cards with no shared counterparty/family/kind cost nothing."""
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    judge = FakeAdapter()
    stage = ContractRelationStage(catalog=catalog, adapter=judge, now=lambda: FROZEN_NOW)

    await catalog.upsert(card("acme-msa"))
    assert (await stage.relate(["acme-msa"])).calls == 0, "no candidates, no call"

    await catalog.upsert(card("acme-nda", contract_type="nda"))
    assert (await stage.relate(["acme-msa"])).calls == 1
    assert len(judge.calls) == 1


@pytest.mark.asyncio
async def test_deterministic_reads_never_invoke_the_judge(stage):
    await stage.relate(["acme-sow"])
    calls_before = len(stage.adapter.calls)

    await stage.related("acme-sow")
    await stage.catalog.active_relations("acme-msa")
    await stage.catalog.judgements_for("acme-msa")

    assert len(stage.adapter.calls) == calls_before, "retrieval is LLM-free"
