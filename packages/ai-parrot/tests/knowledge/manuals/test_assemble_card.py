"""FEAT-601 M5 — deterministic assembly + serial qualifiers (AC4, AC20)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals import carding as cd
from parrot.knowledge.manuals.models import MediaRef
from parrot.knowledge.pageindex.pdf_to_markdown import PageImage


def _extracted(value: str | int, *, node_id: str = "node-1") -> Extracted[str | int]:
    """Create one independently evidenced draft value."""
    return Extracted(value=value, evidence=Evidence(node_id=node_id, quote=str(value)), confidence=0.9)


def _source(**updates: object) -> cd.SourceInfo:
    """Create a minimal source context for deterministic assembly tests."""
    return cd.SourceInfo(
        source_sha256="a" * 64,
        source_format="pdf",
        revision="A",
        **updates,
    )


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("from S/N 2024-0001", "2024-0001", None),
        ("serial numbers A100 to A250", "A100", "A250"),
        ("número de serie desde 2024-0100", "2024-0100", None),
    ],
)
def test_parse_serial_qualifier(text: str, start: str, end: str | None) -> None:
    """Recognized serial qualifiers retain their bounds and vendor shape."""
    serial_range = cd.parse_serial_qualifier(text)
    assert serial_range is not None
    assert serial_range.start == start
    assert serial_range.end == end
    assert serial_range.format


def test_parse_serial_qualifier_unparseable() -> None:
    """Non-serial prose remains available for the verification queue."""
    assert cd.parse_serial_qualifier("for early units only") is None


def test_assemble_card_resolves_parts_and_precedes() -> None:
    """Assembly resolves parts, preserves cross references, durations, and figure links."""
    image = PageImage(
        path=Path("figure.png"),
        page=4,
        index=0,
        bbox=(0.0, 0.0, 1.0, 1.0),
        width=1,
        height=1,
        sha256="b" * 64,
    )
    candidate = cd.FigureCandidate(image=image, label="1")
    media_id = hashlib.sha256(f"{image.sha256}:{image.page}:{image.index}".encode()).hexdigest()[:16]
    draft = cd.CardingDraft(
        header=cd.ManualHeaderDraft(parts=[_extracted("P-7 Hex bolt M8")]),
        procedures=[
            cd.ProcedureDraft(
                title=_extracted("Assemble"),
                kind="assembly",
                node_id="node-1",
                steps=[
                    cd.StepDraft(text=_extracted("Install the P-7 hex bolt M8."), order=1, part_mentions=["P-7"]),
                    cd.StepDraft(text=_extracted("Tighten the bolt."), order=2, duration_minutes=_extracted(3)),
                    cd.StepDraft(
                        text=_extracted("Inspect Figure 1 before step 2."),
                        order=3,
                        duration_minutes=_extracted(2),
                        figure_refs=["Figure 1"],
                        cross_refs=["before step 2"],
                    ),
                ],
            )
        ],
    )
    card = cd.assemble_card(
        draft,
        manual_id="manual-1",
        source=_source(figure_candidates=[candidate]),
        figures=[MediaRef(media_id=media_id, kind="figure", storage_key="figures/1.png")],
        page_map={"node-1": 4},
        now=datetime(2026, 1, 1),
    )
    procedure = card.procedures[0]
    assert procedure.steps[0].parts[0].resolved is True
    assert procedure.steps[2].cross_refs == ["before step 2"]
    assert procedure.estimated_minutes == 5
    assert procedure.steps[2].media[0].media_id == media_id
    assert procedure.steps[2].media[0].role == "primary"


def test_assemble_card_carries_identity_forward() -> None:
    """Source identity precedes exact hash during refresh identity carry-forward."""
    first = cd.CardingDraft(
        procedures=[
            cd.ProcedureDraft(
                title=_extracted("Assembly"),
                kind="assembly",
                node_id="node-1",
                steps=[
                    cd.StepDraft(text=_extracted("Fit the bracket."), order=1, source_identity="1"),
                    cd.StepDraft(text=_extracted("Tighten the fastener."), order=2),
                ],
            )
        ]
    )
    first_card = cd.assemble_card(
        first,
        manual_id="manual-1",
        source=_source(),
        figures=[],
        page_map={"node-1": 1},
        now=datetime(2026, 1, 1),
    )
    refreshed = cd.CardingDraft(
        procedures=[
            cd.ProcedureDraft(
                title=_extracted("Assembly"),
                kind="assembly",
                node_id="node-2",
                steps=[
                    cd.StepDraft(text=_extracted("Fit the revised bracket."), order=7, source_identity="1"),
                    cd.StepDraft(text=_extracted("Tighten the fastener."), order=8),
                ],
            )
        ]
    )
    refreshed_card = cd.assemble_card(
        refreshed,
        manual_id="manual-1",
        source=_source(previous_card=first_card, revision="B"),
        figures=[],
        page_map={"node-2": 2},
        now=datetime(2026, 1, 2),
    )
    assert refreshed_card.procedures[0].steps[0].identity.step_id == first_card.procedures[0].steps[0].identity.step_id
    assert refreshed_card.procedures[0].steps[1].identity.step_id == first_card.procedures[0].steps[1].identity.step_id
