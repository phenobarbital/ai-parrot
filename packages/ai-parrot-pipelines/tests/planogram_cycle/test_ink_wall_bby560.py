"""FEAT-646: definition-aware gap fill and multi-bay membership on the BBY560 ink wall."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.contracts import CreditPolicy, CycleContext, EvidenceWeights, FixtureMembership
from parrot_pipelines.planogram.stages import perceive as perceive_module
from parrot_pipelines.planogram.stages.perceive import perceive_image
from parrot_pipelines.planogram.types import InkWall

_IMAGE = (
    Path(__file__).resolve().parents[4]
    / "examples"
    / "planogram"
    / "images"
    / "epson_inkwall_config"
    / "2026-09-04-Kip-Kerrick-Best-Buy-560.jpeg"
)
EXPECTED_FACINGS = [17, 18, 18, 18, 18, 15]
EDGE_TAG = "price_tag:205-2416-313-2469"


class _InlineExecutor:
    """Run CPU helpers inline."""

    max_workers = 1

    async def run(self, fn, *args):
        """Return the direct result of a CPU helper."""
        return fn(*args)

    async def aclose(self) -> None:
        """Close the no-op executor."""
        return None


class _NoOcr:
    """Represent an unavailable OCR reader."""

    available = False


def _definition():
    """Build the six-shelf BBY560 definition with the expected facing counts."""
    shelves = []
    for shelf_number, facing_count in enumerate(EXPECTED_FACINGS, start=1):
        facings = [
            {
                "facing_id": f"shelf_{shelf_number}_facing_{slot}",
                "shelf_id": f"shelf_{shelf_number}",
                "slot": slot,
                "product": f"PRODUCT-{shelf_number}-{slot}",
                "brand": "Acme",
            }
            for slot in range(1, facing_count + 1)
        ]
        shelves.append(
            {
                "shelf_id": f"shelf_{shelf_number}",
                "shelf_number": shelf_number,
                "level": f"row{shelf_number}",
                "facings": facings,
            }
        )
    return load_slots_definition({"version": "1", "shelves": shelves})


def _ctx(definition, **profile_updates) -> CycleContext:
    """Build a deterministic CV-only cycle context."""
    layout = InkWall.default_layout_profile().model_copy(update=profile_updates)
    return CycleContext(
        vision=None,
        executor=_InlineExecutor(),
        ocr=_NoOcr(),
        definition=definition,
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
        layout=layout,
    )


def test_expected_facings_counts_shelves_with_facings():
    """Expected facings skip empty shelves and return no sentinel for empty definitions."""
    definition = SimpleNamespace(
        shelves=[
            SimpleNamespace(facings=["a", "b"]),
            SimpleNamespace(facings=[]),
            SimpleNamespace(facings=["c"]),
        ]
    )
    assert perceive_module._expected_facings(SimpleNamespace(definition=definition)) == [2, 1]
    assert perceive_module._expected_facings(SimpleNamespace(definition=None)) is None
    assert perceive_module._expected_facings(SimpleNamespace(definition=SimpleNamespace(shelves=[]))) is None
    assert perceive_module._expected_facings(SimpleNamespace(definition=SimpleNamespace(shelves=[SimpleNamespace(facings=[])]))) is None


@pytest.fixture
def bby560() -> Image.Image:
    """Load the optional BBY560 example image."""
    if not _IMAGE.exists():
        pytest.skip("BBY560 example image is not available (examples/ images are not tracked)")
    return Image.open(_IMAGE).convert("RGB")


async def test_ink_wall_bby560_full_height_slots(bby560):
    """Definition gap fill completes the final BBY560 row without changing preceding rows."""
    definition = _definition()
    filled = await perceive_image(bby560, "img0", _ctx(definition))
    unfilled = await perceive_image(bby560, "img0", _ctx(definition, definition_gap_fill=False))
    filled_rows = [[slot for slot in filled.slots if slot.row_index == index] for index in range(6)]
    unfilled_rows = [[slot for slot in unfilled.slots if slot.row_index == index] for index in range(6)]
    assert len(filled_rows[5]) >= 15
    assert [[slot.model_dump() for slot in row] for row in filled_rows[:5]] == [
        [slot.model_dump() for slot in row] for row in unfilled_rows[:5]
    ]


async def test_ink_wall_bby560_membership_edge_tag(bby560):
    """The edge tag is on-fixture and the completed final row has 15 registrable slots."""
    perception = await perceive_image(bby560, "img0", _ctx(_definition()))
    edge_tag = next(shape for shape in perception.shapes if shape.shape_id == f"img0:{EDGE_TAG}")
    assert edge_tag.membership == FixtureMembership.ON_FIXTURE
    assert "row_block" in edge_tag.membership_evidence
    final_row = [slot for slot in perception.slots if slot.row_index == 5]
    assert sum(slot.anchor_shape_id is not None and not slot.inferred for slot in final_row) == 15
