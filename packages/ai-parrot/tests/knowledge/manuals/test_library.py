"""ManualLibrary pipeline with fake indexer/adapter/file manager (FEAT-601 M8)."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals import carding as cd
from parrot.knowledge.manuals.library import ImageOnlyManual, ManualLibrary

from .._support.catalog import InMemoryManualCatalog  # TASK-3702
from .._support.pdfs import STEPS_REV_A

pytestmark = pytest.mark.asyncio


def _build_captioned_manual_pdf(path: Path, *, steps: tuple[str, ...] = STEPS_REV_A) -> Path:
    """Same 6-page layout as ``_support.pdfs.build_manual_pdf`` with figures large enough to
    clear ``extract_page_images``'s default ``min_area_ratio=0.05``.

    The shared ``manual_pdf`` fixture's 120x80 figure is only ~1.9% of a default page's area
    (a limitation already documented by TASK-3706's ``test_figures.py::_build_captioned_manual`),
    so it never survives real figure extraction. This 240x240 variant (~11.5%) is used here to
    exercise the pairing/upload stages of the ingest pipeline end-to-end.
    """
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        cover = document.new_page()
        cover.insert_text((72, 72), "MODEL X ASSEMBLY MANUAL")
        parts = document.new_page()
        parts.insert_text((72, 72), "PARTS TABLE\nBase plate\nCover\nDrive belt\nTensioner bolt")
        procedure = document.new_page()
        procedure.insert_text((72, 72), "ASSEMBLY PROCEDURE\n" + "\n".join(steps))
        pixmap_one = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 240, 240), 0)
        pixmap_one.clear_with(180)
        pixmap_two = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 240, 240), 0)
        pixmap_two.clear_with(120)  # distinct fill so the two figures hash differently
        figure_one = document.new_page()
        rect_one = pymupdf.Rect(72, 100, 312, 340)
        figure_one.insert_image(rect_one, stream=pixmap_one.tobytes("png"))
        figure_one.insert_text((72, rect_one.y1 + 16), "Fig. 1 Drive belt routing")
        figure_two = document.new_page()
        rect_two = pymupdf.Rect(72, 100, 312, 340)
        figure_two.insert_image(rect_two, stream=pixmap_two.tobytes("png"))
        figure_two.insert_text((72, rect_two.y1 + 16), "Fig. 2 Cover installation")
        warning = document.new_page()
        warning.draw_rect(pymupdf.Rect(60, 60, 400, 140), color=(0.8, 0.2, 0.1), fill=(1, 0.9, 0.8))
        warning.insert_text((72, 90), "WARNING: Disconnect power before assembly.")
        document.save(str(path))
    finally:
        document.close()
    return path


def _header_draft() -> cd.ManualHeaderDraft:
    """A header draft whose quotes are verbatim on the cover/parts/warning pages."""
    return cd.ManualHeaderDraft(
        equipment_models=[
            Extracted[str](
                value="Model X",
                evidence=Evidence(node_id="0000", quote="MODEL X ASSEMBLY MANUAL"),
                confidence=0.95,
            )
        ],
        parts=[
            Extracted[str](value="Base plate", evidence=Evidence(node_id="0001", quote="Base plate"), confidence=0.9),
        ],
        hazards=[
            Extracted[str](
                value="Disconnect power before assembly",
                evidence=Evidence(node_id="0005", quote="WARNING: Disconnect power before assembly."),
                confidence=0.9,
            )
        ],
    )


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


def _build_library(
    *, tmp_path: Path, adapter, file_manager, indexer_factory
) -> tuple[ManualLibrary, InMemoryManualCatalog]:
    """Build a ManualLibrary wired to an in-memory catalog and fake collaborators."""
    catalog = InMemoryManualCatalog()
    library = ManualLibrary(
        catalog=catalog,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
        adapter=adapter,
        file_manager=file_manager,
        vision_client=None,
        indexer_factory=indexer_factory,
    )
    return library, catalog


async def test_add_manual_pipeline_fake_indexer(
    fake_adapter, fake_file_manager, tmp_path, fake_indexer_factory
) -> None:
    """Card with 1 procedure / 5 ordered steps, 2 paired figures uploaded (storage keys, no URLs), queue entries listed."""
    pytest.importorskip("pymupdf")
    manual_pdf = _build_captioned_manual_pdf(tmp_path / "manuals" / "model-x-rev-a.pdf")
    fake_adapter.script(cd.ManualHeaderDraft, _header_draft())
    fake_adapter.script(cd.ProcedureStepsDraft, _procedure_draft(STEPS_REV_A, {2: "Fig. 1", 4: "Fig. 2"}), key="0002")
    library, catalog = _build_library(
        tmp_path=tmp_path, adapter=fake_adapter, file_manager=fake_file_manager, indexer_factory=fake_indexer_factory
    )

    result = await library.add_manual(manual_pdf, equipment=["Model X"], revision="Rev A")

    assert result.status == "created"
    assert result.card is not None
    assert len(result.card.procedures) == 1
    steps = result.card.procedures[0].steps
    assert [step.order for step in steps] == [1, 2, 3, 4, 5]
    assert len(result.card.figures) == 2
    for figure in result.card.figures:
        assert figure.storage_key is not None
        assert not figure.storage_key.lower().startswith(("http://", "https://", "file://"))
    assert result.figures_paired == 2
    assert result.figures_unpaired == 0
    assert result.hazards == 1
    assert len(fake_file_manager.objects) == 2
    stored = await catalog.get(result.card.manual_id)
    assert stored is not None and stored.manual_id == result.card.manual_id


async def test_add_manual_refuses_image_only(
    image_only_pdf, fake_adapter, fake_file_manager, tmp_path, fake_indexer_factory
) -> None:
    """status='refused' with an OCR-not-supported warning; no catalog write."""
    library, catalog = _build_library(
        tmp_path=tmp_path, adapter=fake_adapter, file_manager=fake_file_manager, indexer_factory=fake_indexer_factory
    )

    with pytest.raises(ImageOnlyManual):
        await library._to_markdown(image_only_pdf, "pdf", images_dir=tmp_path / "images")

    result = await library.add_manual(image_only_pdf, equipment=["Model X"], revision="Rev A")

    assert result.status == "refused"
    assert result.card is None
    assert any("extractable text" in warning for warning in result.warnings)
    assert await catalog.list_cards() == []


async def test_add_manual_unchanged_on_same_sha(
    manual_pdf, fake_adapter, fake_file_manager, tmp_path, fake_indexer_factory
) -> None:
    """Second add ⇒ 'unchanged'; force=True re-cards."""
    fake_adapter.script(cd.ManualHeaderDraft, _header_draft())
    fake_adapter.script(cd.ProcedureStepsDraft, _procedure_draft(STEPS_REV_A, {2: "Fig. 1", 4: "Fig. 2"}), key="0002")
    library, catalog = _build_library(
        tmp_path=tmp_path, adapter=fake_adapter, file_manager=fake_file_manager, indexer_factory=fake_indexer_factory
    )

    first = await library.add_manual(manual_pdf, equipment=["Model X"], revision="Rev A")
    assert first.status == "created"

    second = await library.add_manual(manual_pdf, equipment=["Model X"], revision="Rev A")
    assert second.status == "unchanged"
    assert second.card.manual_id == first.card.manual_id

    third = await library.add_manual(manual_pdf, equipment=["Model X"], revision="Rev A", force=True)
    assert third.status == "updated"
    assert third.card.manual_id == first.card.manual_id
    assert len(await catalog.list_cards()) == 1


async def test_refresh_appends_version_and_relinks(
    manual_pdf, manual_pdf_rev_b, fake_adapter, fake_file_manager, tmp_path, fake_indexer_factory
) -> None:
    """rev B ⇒ versions[] appended with valid_from/valid_to; carried-forward step ids; relink counts populated."""
    fake_adapter.script(cd.ManualHeaderDraft, _header_draft())
    fake_adapter.script(cd.ProcedureStepsDraft, _procedure_draft(STEPS_REV_A, {2: "Fig. 1", 4: "Fig. 2"}), key="0002")
    library, catalog = _build_library(
        tmp_path=tmp_path, adapter=fake_adapter, file_manager=fake_file_manager, indexer_factory=fake_indexer_factory
    )

    created = await library.add_manual(manual_pdf, equipment=["Model X"], revision="Rev A")
    assert created.status == "created"
    manual_id = created.card.manual_id
    original_step_ids = [step.identity.step_id for step in created.card.procedures[0].steps]

    rev_b_steps = (
        STEPS_REV_A[0],
        STEPS_REV_A[1],
        "3. Route the drive belt around the pulley. See Fig. 1.",
        "4. Tighten the tensioner bolt to 12 Nm using a torque wrench.",
    )
    fake_adapter.script(cd.ProcedureStepsDraft, _procedure_draft(rev_b_steps, {2: "Fig. 1"}), key="0002")

    refreshed = await library.refresh(manual_id, manual_pdf_rev_b, revision="Rev B")

    assert refreshed.status == "updated"
    assert refreshed.card is not None
    assert refreshed.card.manual_id == manual_id
    assert len(refreshed.card.versions) == 2
    assert refreshed.card.versions[-1].valid_from is not None
    new_steps = refreshed.card.procedures[0].steps
    assert len(new_steps) == 4
    # Steps 1 and 2 are verbatim-unchanged between revisions -> carried-forward identity (R1).
    assert new_steps[0].identity.step_id == original_step_ids[0]
    assert new_steps[1].identity.step_id == original_step_ids[1]
    # Step 3 was reworded -> a fresh identity, never a stale carry-forward.
    assert new_steps[2].identity.step_id not in original_step_ids


async def test_verify_procedure_freezes_version(
    manual_pdf, fake_adapter, fake_file_manager, tmp_path, fake_indexer_factory
) -> None:
    """verification == 'verified', verified_by stamped."""
    fake_adapter.script(cd.ManualHeaderDraft, _header_draft())
    fake_adapter.script(cd.ProcedureStepsDraft, _procedure_draft(STEPS_REV_A, {2: "Fig. 1", 4: "Fig. 2"}), key="0002")
    library, catalog = _build_library(
        tmp_path=tmp_path, adapter=fake_adapter, file_manager=fake_file_manager, indexer_factory=fake_indexer_factory
    )

    created = await library.add_manual(manual_pdf, equipment=["Model X"], revision="Rev A")
    procedure = created.card.procedures[0]

    updated = await library.verify_procedure(created.card.manual_id, procedure.procedure_id, user="qa@example.com")

    assert updated.verification == "verified"
    assert updated.procedures[0].verification == "verified"
    provenance = updated.field_provenance[f"procedures.{procedure.slug}.verification"]
    assert provenance.verified_by == "qa@example.com"
    assert provenance.verification == "verified"
