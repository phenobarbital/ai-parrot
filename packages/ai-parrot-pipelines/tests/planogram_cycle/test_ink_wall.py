"""InkWall: identity rules and synthetic end-to-end (FEAT-574, Module 16)."""

from __future__ import annotations

import inspect
import json
import re
from importlib import import_module

import cv2
import numpy as np
import pytest
from PIL import Image

from parrot.models.detections import DetectionBox
from parrot_pipelines import PIPELINE_REGISTRY
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import plan as plan_module
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FacingStatus,
    FixtureMembership,
    Identification,
    IdentificationResponse,
    IdentificationResult,
    PerceptionResult,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import InkWall
from parrot_pipelines.planogram.types.ink_wall import resolve_identity

W, H = 2000, 1400
TAG_TOPS = (380, 760, 1100)
PITCH = 220
GAP = (1, 3)  # row 1, column index 3 (slot 4) has no tag
UNDESCRIBED = {(1, 8), (2, 8), (3, 7), (3, 8)}  # (shelf, slot)


class _InlineExecutor:
    """Runs CPU helpers inline (spawned workers cannot import worktree-only Cython extensions)."""

    def __init__(self, max_workers: int = 2) -> None:
        self.max_workers = max_workers

    async def run(self, fn, *args):
        return fn(*args)

    async def aclose(self) -> None:
        return None


class _NoOcr:
    """OcrReader stand-in: the planogram extra is 'absent' (no ONNX model is loaded in tests)."""

    available = False


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(plan_module, "CpuExecutor", _InlineExecutor)
    monkeypatch.setattr(plan_module, "OcrReader", _NoOcr)


def _ctx(definition=None) -> CycleContext:
    return CycleContext(
        vision=None,
        executor=_InlineExecutor(),
        ocr=_NoOcr(),
        definition=definition,
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


@pytest.fixture
def synthetic_ink_wall() -> Image.Image:
    """Dark wall, 3 rows x 8 bright landscape labels, one gap, room for an untagged bottom row."""
    img = np.full((H, W, 3), 40, np.uint8)
    for row, top in enumerate(TAG_TOPS):
        for col in range(8):
            if (row, col) == GAP:
                continue
            x = 150 + col * PITCH
            cv2.rectangle(img, (x, top), (x + 110, top + 40), (245, 245, 245), -1)
            cv2.line(img, (x + 8, top + 20), (x + 102, top + 20), (20, 20, 20), 3)
    return Image.fromarray(img[:, :, ::-1].copy())


def _definition_dict(price: float | None = None) -> dict:
    shelves = []
    for shelf in (1, 2, 3):
        facings = []
        for slot in range(1, 9):
            described = (shelf, slot) not in UNDESCRIBED
            descriptors = (
                {"display_name": f"Acme ink {shelf}-{slot}", "family": f"F{shelf}", "identifiers": [f"A{shelf}{slot}"]}
                if described
                else {}
            )
            if price is not None and (shelf, slot) == (1, 1):
                descriptors["price"] = price
            facings.append(
                {
                    "facing_id": f"s{shelf}_f{slot}",
                    "shelf_id": f"shelf_{shelf}",
                    "slot": slot,
                    "product": f"ACME-{shelf}-{slot}",
                    "brand": "Acme",
                    "descriptors": descriptors,
                }
            )
        shelves.append(
            {"shelf_id": f"shelf_{shelf}", "shelf_number": shelf, "level": f"row{shelf}", "facings": facings}
        )
    return {"version": "1", "shelves": shelves}


@pytest.fixture
def synthetic_slots_definition() -> dict:
    """3 shelves x 8 facings, stable ids, 20 described / 4 undescribed."""
    return _definition_dict()


def _answer_strip(prompt, image, kwargs):
    """Fake LLM: read the AREAS ids and report the identifier printed at that (row, slot)."""
    areas = json.loads(prompt.split("AREAS: ", 1)[1])
    entries = []
    for area in areas:
        match = re.search(r":r(\d+):s(\d+)$", area["id"])
        row, slot = int(match.group(1)), int(match.group(2))
        if row >= 3:
            continue  # untagged bottom row: nothing legible
        code = f"A{row + 1}{slot}"
        entries.append(
            Identification(
                shape_id=area["id"],
                product=code,
                brand="Acme",
                text=code,
                occupancy="occupied",
                raw_confidence=0.8,
                evidence=[f"label reads {code}"],
            )
        )
    return IdentificationResponse(existing_identifications=entries)


# --------------------------------------------------------------------------- wiring


def test_ink_wall_is_registered_everywhere():
    assert PlanogramCompliance._PLANOGRAM_TYPES["ink_wall"] is InkWall
    for name in ("InkWall", "ProductCounter", "EndcapNoShelvesPromotional", "EndcapBacklitMultitier"):
        module_path, cls = PIPELINE_REGISTRY[name].rsplit(".", 1)
        assert getattr(import_module(module_path), cls).__name__ == name
    import parrot_pipelines.planogram as pkg

    assert pkg.InkWall is InkWall
    assert not any(InkWall._implements(InkWall.__new__(InkWall), n) for n in InkWall._LEGACY_CONTRACT)


def test_ink_wall_requires_slots_definition(fake_vision_client):
    with pytest.raises(ValueError):
        PlanogramCompliance(
            planogram_config=PlanogramConfig(planogram_type="ink_wall", planogram_config={}), llm=fake_vision_client
        )


# --------------------------------------------------------------------------- identity


def _ident(**kwargs) -> Identification:
    return Identification(shape_id="s", image_id="img0", **kwargs)


def test_resolve_identity_by_identifier():
    definition = load_slots_definition(_definition_dict())
    assert resolve_identity(_ident(brand="Acme", text="A23"), definition) == ("ACME-2-3", ["ACME-2-3"])
    assert resolve_identity(_ident(brand="Acme", evidence=["tag | A11"]), definition) == ("ACME-1-1", ["ACME-1-1"])


def test_resolve_identity_signature_without_xl_is_candidate_only():
    """family+colors match exactly one facing but `xl` was not read => (None, [that id])."""
    data = _definition_dict()
    data["shelves"][0]["facings"][0]["descriptors"].update({"family": "UNIQUE", "colors": ["cyan"], "xl": True})
    definition = load_slots_definition(data)
    read = {"family": "unique", "colors": ["Cyan"]}
    assert resolve_identity(_ident(brand="Acme", descriptors=read), definition) == (None, ["ACME-1-1"])
    with_xl = {**read, "xl": True}
    assert resolve_identity(_ident(brand="Acme", descriptors=with_xl), definition) == ("ACME-1-1", ["ACME-1-1"])
    several = resolve_identity(_ident(brand="Acme", descriptors={"family": "F2", "xl": False}), definition)
    assert several[0] is None and len(several[1]) == 7


def test_resolve_identity_alias_fuzzy():
    data = _definition_dict()
    data["shelves"][2]["facings"][0]["descriptors"]["aliases"] = ["EcoTank Black Bottle"]
    definition = load_slots_definition(data)
    assert resolve_identity(_ident(brand="Acme", text="ecotank black bottle 502"), definition)[0] == "ACME-3-1"
    assert resolve_identity(_ident(brand="Acme", text="completely different"), definition) == (None, [])


def test_resolve_identity_unknown_brand_is_unresolved():
    definition = load_slots_definition(_definition_dict())
    assert resolve_identity(_ident(brand="Other", text="A11"), definition) == (None, [])


def test_resolve_identity_never_reads_expected_facing():
    """The signature has no facing / slot argument: the same reading resolves the same way everywhere."""
    assert list(inspect.signature(resolve_identity).parameters) == ["identification", "definition"]
    definition = load_slots_definition(_definition_dict())
    first = resolve_identity(_ident(brand="Acme", text="A32"), definition)
    again = resolve_identity(_ident(brand="Acme", text="A32").model_copy(update={"shape_id": "other"}), definition)
    assert first == again == ("ACME-3-2", ["ACME-3-2"])


# --------------------------------------------------------------------------- perceive / compare


async def test_ink_wall_perceive_synthetic(synthetic_ink_wall, synthetic_slots_definition, fake_vision_client):
    config = PlanogramConfig(
        planogram_type="ink_wall", planogram_config={"brand": "Acme"}, slots_definition=synthetic_slots_definition
    )
    pipe = PlanogramCompliance(planogram_config=config, llm=fake_vision_client)
    perception = await pipe._type_handler.perceive(synthetic_ink_wall, "img0", _ctx())
    assert perception.detection_source == "cv" and perception.ocr_available is False
    assert perception.row_count == 3
    assert len([s for s in perception.shapes if s.kind == ShapeKind.PRICE_TAG]) == 23
    assert all(s.membership == FixtureMembership.ON_FIXTURE for s in perception.shapes)
    rows = {}
    for slot in perception.slots:
        rows.setdefault(slot.row_index, []).append(slot)
    assert [len(rows[r]) for r in sorted(rows)] == [8, 8, 8, 8]  # gap filled + untagged bottom row
    assert [s.inferred for s in rows[1]].count(True) == 1
    assert all(s.inferred for s in rows[3])
    tag_ids = {s.shape_id for s in perception.shapes}
    assert all(s.anchor_shape_id in tag_ids for s in perception.slots if not s.inferred)


async def test_ink_wall_end_to_end_synthetic(
    synthetic_ink_wall, synthetic_slots_definition, fake_vision_client, offline
):
    """Fake LLM answers every strip with the printed identifiers => all described facings `match`."""
    fake_vision_client.queue("ask_to_image", *([_answer_strip] * 4))
    config = PlanogramConfig(
        planogram_type="ink_wall", planogram_config={"brand": "Acme"}, slots_definition=synthetic_slots_definition
    )
    pipe = PlanogramCompliance(planogram_config=config, llm=fake_vision_client)
    result = await pipe.run(synthetic_ink_wall)
    assert {"compliance_results", "overall_compliance_score", "overall_compliant", "rendered_image"} <= set(result)
    assert result["compliance_results"] is result["step3_compliance_results"]
    assert result["detection_source"] == "cv"
    assert len(result["compliance_results"]) == 3
    assert result["definition_coverage"] == pytest.approx(20 / 24)
    assert result["assessment_status"] == "inconclusive"  # 4 undescribed facings stay unresolved
    assert result["overall_compliant"] is False
    statuses = {p.facing_id: p.status for p in result["position_results"]}
    described = [f"s{s}_f{i}" for s in (1, 2, 3) for i in range(1, 9) if (s, i) not in UNDESCRIBED]
    assert all(statuses[f] == FacingStatus.MATCH for f in described)
    assert all(statuses[f"s{s}_f{i}"] != FacingStatus.MATCH for s, i in UNDESCRIBED)
    assert len(fake_vision_client.calls_to("ask_to_image")) == 4  # 3 tag rows + the untagged bottom row


async def test_ink_wall_price_note_does_not_change_credits(fake_vision_client):
    definition_dict = _definition_dict(price=12.99)
    definition = load_slots_definition(definition_dict)
    config = PlanogramConfig(
        planogram_type="ink_wall", planogram_config={"brand": "Acme"}, slots_definition=definition_dict
    )
    pipe = PlanogramCompliance(planogram_config=config, llm=fake_vision_client)
    handler = pipe._type_handler
    shapes, slots, idents = [], [], []
    for shelf in (1, 2, 3):
        for slot in range(1, 9):
            tag_id = f"img0:tag:{shelf}{slot}"
            box = DetectionBox(x1=slot * 100, y1=shelf * 200, x2=slot * 100 + 60, y2=shelf * 200 + 20, confidence=0.9)
            shapes.append(
                Shape(
                    shape_id=tag_id,
                    image_id="img0",
                    kind=ShapeKind.PRICE_TAG,
                    box=box,
                    row_index=shelf - 1,
                    slot_index=slot,
                    ocr_text="$9.99" if (shelf, slot) == (1, 1) else "$12.99",
                    membership=FixtureMembership.ON_FIXTURE,
                )
            )
            slot_id = f"img0:r{shelf - 1}:s{slot}"
            slots.append(
                Slot(
                    slot_id=slot_id,
                    image_id="img0",
                    row_index=shelf - 1,
                    slot_index=slot,
                    box=box,
                    anchor_shape_id=tag_id,
                )
            )
            idents.append(
                Identification(
                    shape_id=slot_id, image_id="img0", brand="Acme", text=f"A{shelf}{slot}", evidence=["read"]
                )
            )
    perception = PerceptionResult(image_id="img0", image_size=(1000, 800), shapes=shapes, slots=slots, row_count=3)
    out = await handler.compare(
        [perception], [IdentificationResult(image_id="img0", identifications=idents)], _ctx(definition)
    )
    first = next(p for p in out.position_results if p.facing_id == "s1_f1")
    assert first.status == FacingStatus.MATCH
    assert (first.strict_credit, first.lenient_credit) == (1.0, 1.0)
    assert any(n.startswith("price_mismatch: expected 12.99, tag reads 9.99") for n in first.notes)
    others = [p for p in out.position_results if p.facing_id != "s1_f1"]
    assert not any(n.startswith("price_mismatch") for p in others for n in p.notes)


async def test_ink_wall_fallback_perception_still_compares(fake_vision_client, synthetic_slots_definition):
    """A fallback perception (slots == []) is compared by treating every on-fixture shape as its own slot."""
    definition = load_slots_definition(synthetic_slots_definition)
    config = PlanogramConfig(
        planogram_type="ink_wall", planogram_config={"brand": "Acme"}, slots_definition=synthetic_slots_definition
    )
    handler = PlanogramCompliance(planogram_config=config, llm=fake_vision_client)._type_handler
    shapes, idents = [], []
    for slot in range(1, 9):
        shape_id = f"img0:llm:{slot}"
        shapes.append(
            Shape(
                shape_id=shape_id,
                image_id="img0",
                kind=ShapeKind.PRODUCT,
                box=DetectionBox(x1=slot * 100, y1=100, x2=slot * 100 + 80, y2=300, confidence=0.8),
                membership=FixtureMembership.ON_FIXTURE,
            )
        )
        idents.append(
            Identification(shape_id=shape_id, image_id="img0", brand="Acme", text=f"A1{slot}", evidence=["r"])
        )
    perception = PerceptionResult(image_id="img0", image_size=(1000, 400), shapes=shapes, detection_source="llm")
    out = await handler.compare(
        [perception], [IdentificationResult(image_id="img0", identifications=idents)], _ctx(definition)
    )
    matched = [p for p in out.position_results if p.status == FacingStatus.MATCH]
    assert {p.facing_id for p in matched} == {f"s1_f{i}" for i in range(1, 8)}  # s1_f8 is undescribed
