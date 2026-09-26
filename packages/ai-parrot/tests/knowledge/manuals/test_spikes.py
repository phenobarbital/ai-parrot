"""Spike harness over fakes (FEAT-601 M0)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals import carding as cd
from parrot.knowledge.manuals import spikes
from parrot.knowledge.manuals.graph_loader import ManualGraphLoader
from parrot.knowledge.manuals.library import ManualLibrary
from parrot.knowledge.manuals.models import MediaView, ProcedureAnswer, ProcedureCitation

from .._support.adapter import FakeIndexer
from .._support.catalog import InMemoryManualCatalog
from .._support.pdfs import STEPS_REV_A


def _procedure_draft(steps: tuple[str, ...], figure_step_refs: Mapping[int, str]) -> cd.ProcedureStepsDraft:
    """A procedure draft whose step quotes are verbatim on the assembly-procedure page (node 0002)."""
    step_drafts = [
        cd.StepDraft(
            order=index + 1,
            text=Extracted[str](value=line, evidence=Evidence(node_id="0002", quote=line), confidence=0.9),
            figure_refs=[figure_step_refs[index]] if index in figure_step_refs else [],
        )
        for index, line in enumerate(steps)
    ]
    return cd.ProcedureStepsDraft(
        procedures=[
            cd.ProcedureDraft(
                title=Extracted[str](
                    value="Assembly Procedure",
                    evidence=Evidence(node_id="0002", quote="ASSEMBLY PROCEDURE"),
                    confidence=0.9,
                ),
                kind="assembly",
                node_id="0002",
                steps=step_drafts,
            )
        ]
    )


def test_evaluate_thresholds_pass_and_fail() -> None:
    """Exactly-at-threshold passes; missing_required=1 fails; missing measurement fails with a note."""
    at_threshold = spikes._evaluate(
        "figures",
        {"steps_in_order_ratio": 0.90, "missing_required": 0.0, "primary_figure_accuracy": 0.80},
        [],
    )
    assert at_threshold.passed
    assert at_threshold.notes == []

    missing_required = spikes._evaluate(
        "figures",
        {"steps_in_order_ratio": 1.0, "missing_required": 1.0, "primary_figure_accuracy": 1.0},
        [],
    )
    assert not missing_required.passed

    missing_measurement = spikes._evaluate("video", {}, [])
    assert not missing_measurement.passed
    assert any("coverage" in note for note in missing_measurement.notes)


def test_write_report_under_root(tmp_path: Path) -> None:
    """spike-<name>-*.json written with sorted keys and round-trips to SpikeReport."""
    report = spikes.SpikeReport(
        name="figures",
        measurements={"steps_in_order_ratio": 1.0, "missing_required": 0.0, "primary_figure_accuracy": 1.0},
        thresholds=spikes.THRESHOLDS["figures"],
        passed=True,
    )

    path = spikes.write_report(report, root=tmp_path)

    assert path.parent == tmp_path
    assert path.name.startswith("spike-figures-")
    assert path.name.endswith(".json")
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert list(payload.keys()) == sorted(payload.keys())
    assert spikes.SpikeReport.model_validate(payload) == report


def test_corpus_dir_from_env_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Unset or nonexistent MANUALS_SPIKE_CORPUS ⇒ FileNotFoundError."""
    monkeypatch.delenv(spikes.SPIKE_CORPUS_ENV, raising=False)
    with pytest.raises(FileNotFoundError):
        spikes.corpus_dir_from_env()

    monkeypatch.setenv(spikes.SPIKE_CORPUS_ENV, str(tmp_path / "does-not-exist"))
    with pytest.raises(FileNotFoundError):
        spikes.corpus_dir_from_env()

    monkeypatch.setenv(spikes.SPIKE_CORPUS_ENV, str(tmp_path))
    assert spikes.corpus_dir_from_env() == tmp_path


@pytest.mark.asyncio
async def test_spike_media_records_per_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake senders: two succeed, one raises ⇒ passed=False, note names the failing channel."""
    calls: list[tuple[str, list[str]]] = []

    async def _ok(channel: str, parsed) -> None:
        calls.append((channel, list(parsed.image_urls)))

    async def _boom(channel: str, parsed) -> None:
        raise RuntimeError("channel unavailable")

    spikes.CHANNEL_SENDERS.clear()
    spikes.register_channel_sender("msteams", _ok)
    spikes.register_channel_sender("whatsapp", _ok)
    spikes.register_channel_sender("telegram", _boom)
    try:
        answer = ProcedureAnswer(
            answer_kind="lookup",
            answer="See the referenced figure.",
            citations=[ProcedureCitation(manual_id="m1", node_id="n1", quote="q")],
            media=[MediaView(media_id="https://cdn.example/figure.png", kind="figure", role="primary")],
        )

        report = await spikes.spike_media(answer, channels=("msteams", "whatsapp", "telegram"))
    finally:
        spikes.CHANNEL_SENDERS.clear()

    assert report.name == "media"
    assert not report.passed
    assert report.measurements["channels_delivered"] == 2.0
    assert any("telegram" in note for note in report.notes)
    assert {channel for channel, _urls in calls} == {"msteams", "whatsapp"}
    assert all(urls == ["https://cdn.example/figure.png"] for _channel, urls in calls)


@pytest.mark.asyncio
async def test_spike_tips_expected_outcomes(
    manual_pdf: Path,
    manual_pdf_rev_b: Path,
    fake_graph_store,
    fake_adapter,
    fake_file_manager,
    tmp_path: Path,
) -> None:
    """In-process spike 4: 3/3 expected relink outcomes ⇒ passed."""

    def _indexer_factory(storage_dir: Path, adapter) -> FakeIndexer:
        return FakeIndexer(storage_dir, adapter)

    catalog = InMemoryManualCatalog()
    library = ManualLibrary(
        catalog=catalog,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
        adapter=fake_adapter,
        file_manager=fake_file_manager,
        vision_client=None,
        indexer_factory=_indexer_factory,
    )

    fake_adapter.script(cd.ProcedureStepsDraft, _procedure_draft(STEPS_REV_A, {2: "Fig. 1", 4: "Fig. 2"}), key="0002")
    created = await library.add_manual(manual_pdf, equipment=["Model X"], revision="Rev A")
    assert created.status == "created"

    # Publish rev A once so the graph records it as the manual's last-seen revision — the
    # relink step inside publish() only fires on a later publish whose catalog revision differs.
    seed_loader = ManualGraphLoader(catalog=catalog, graph_store=fake_graph_store)
    seed_report = await seed_loader.publish_all()
    assert seed_report.published

    rev_b_steps = (
        STEPS_REV_A[0],
        STEPS_REV_A[1],
        "3. Route the drive belt around the pulley. See Fig. 1.",
        "4. Tighten the tensioner bolt to 12 Nm using a torque wrench.",
    )
    fake_adapter.script(cd.ProcedureStepsDraft, _procedure_draft(rev_b_steps, {2: "Fig. 1"}), key="0002")
    refreshed = await library.refresh(created.card.manual_id, manual_pdf_rev_b, revision="Rev B")
    assert refreshed.status == "updated"

    report = await spikes.spike_tips(fake_graph_store, catalog, revisions=(manual_pdf, manual_pdf_rev_b))

    assert report.name == "tips"
    assert report.measurements["expected_outcomes_matched"] == 3.0
    assert report.passed
    assert report.notes == []
