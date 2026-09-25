"""FEAT-601 M5 — carding passes (AC3)."""

from __future__ import annotations

from parrot.knowledge.bookstore.models import TocEntry
from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals import carding as cd


def test_select_procedure_nodes_density() -> None:
    toc = [TocEntry(node_id="0001", title="Introduction", depth=1), TocEntry(node_id="0002", title="Notes", depth=1)]
    bodies = {
        "0001": "This manual describes the unit.",
        "0002": "1. Insert the shaft.\n2. Tighten the bolt.\n3. Align.",
    }
    assert cd.select_procedure_nodes(toc, bodies)[0] == "0002"


def test_validate_steps_drops_unsupported() -> None:
    body = {"0002": "1. Insert the shaft into the housing."}
    good = cd.StepDraft(
        order=1,
        text=Extracted[str](
            value="Insert the shaft",
            evidence=Evidence(node_id="0002", quote="Insert the shaft into the housing."),
            confidence=0.9,
        ),
    )
    bad = cd.StepDraft(
        order=2,
        text=Extracted[str](
            value="Grease it",
            evidence=Evidence(node_id="0002", quote="Grease the bearing."),
            confidence=0.9,
        ),
    )
    kept, notes = cd.validate_steps([good, bad], body, node_id="0002")
    assert [s.order for s in kept] == [1] and notes


async def test_draft_manual_bounded_calls_and_fallback(fake_adapter) -> None:
    toc = [
        TocEntry(node_id="0001", title="Safety", depth=1),
        TocEntry(node_id="0002", title="Assembly", depth=1),
        TocEntry(node_id="0003", title="Notes", depth=1),
    ]
    bodies = {
        "0001": "Warning: wear safety glasses at all times.",
        "0002": "1. Insert the shaft into the housing.\n2. Tighten the bolt.",
        "0003": "1. Check the connection.\n2. Align the bracket.",
    }

    def loader(node_id: str) -> str | None:
        return bodies.get(node_id)

    # No adapter -> deterministic fallback, no procedures invented.
    fallback = await cd.draft_manual(None, filename="model-x.pdf", toc=toc, toc_digest="digest", loader=loader)
    assert fallback.origin == "fallback"
    assert fallback.procedures == []
    assert fallback.llm_calls == 0

    header_draft = cd.ManualHeaderDraft(
        equipment_models=[
            Extracted[str](
                value="Model X",
                evidence=Evidence(node_id="0001", quote="Warning: wear safety glasses at all times."),
                confidence=0.9,
            )
        ]
    )
    fake_adapter.script(cd.ManualHeaderDraft, header_draft)

    good_procedure = cd.ProcedureDraft(
        title=Extracted[str](
            value="Assembly",
            evidence=Evidence(node_id="0002", quote="Insert the shaft into the housing."),
            confidence=0.9,
        ),
        kind="assembly",
        node_id="0002",
        steps=[
            cd.StepDraft(
                order=1,
                text=Extracted[str](
                    value="Insert the shaft",
                    evidence=Evidence(node_id="0002", quote="Insert the shaft into the housing."),
                    confidence=0.9,
                ),
            )
        ],
    )
    fake_adapter.script(cd.ProcedureStepsDraft, cd.ProcedureStepsDraft(procedures=[good_procedure]), key="0002")
    fake_adapter.fail_keys.add("0003")

    draft = await cd.draft_manual(
        fake_adapter,
        filename="model-x.pdf",
        toc=toc,
        toc_digest="digest",
        loader=loader,
        max_procedure_sections=5,
    )

    assert draft.origin == "llm"
    # 1 header call + one call per selected procedure section (0002, 0003).
    assert draft.llm_calls == 1 + 2
    assert draft.procedure_nodes == ["0002"]
    assert [procedure.node_id for procedure in draft.procedures] == ["0002"]
    assert any("0003" in warning for warning in draft.warnings)
