"""Regression tests: illumination evidence, fact-tag corroboration and row registration on the cycle (FEAT-612)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from parrot.models.detections import AisleConfig, DetectionBox, PlanogramDescription, ShelfConfig
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import plan as plan_module
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FacingStatus,
    FixtureMembership,
    Identification,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves


class _RaisingVision:
    """Any attribute access or call proves compare() tried to use the vision adapter (AC8)."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"compare() must not touch vision ({name})")


def definition(shelves: Dict[str, List[str]], zones: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Raw definition: ``{"top": ["P-100", "P-200"], ...}`` in top-to-bottom order; generic labels only."""
    rows = []
    for number, (level, products) in enumerate(shelves.items()):
        facings = [
            {
                "facing_id": f"{level}:{slot}",
                "shelf_id": level,
                "slot": slot,
                "product": product,
                "brand": "Acme",
                "descriptors": {"display_name": product, "identifiers": [product]},
            }
            for slot, product in enumerate(products, start=1)
        ]
        rows.append({"shelf_id": level, "shelf_number": number, "level": level, "facings": facings})
    return {"shelves": rows, "zones": list(zones)}


def handler(raw_definition: Dict[str, Any], threshold: Optional[float] = None) -> ProductOnShelves:
    """ProductOnShelves over a MagicMock pipeline with a minimal migrated configuration."""
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.regression")
    pipeline.reference_images = {}
    config = MagicMock()
    config.planogram_config = {"brand": "Acme"}
    config.slots_definition = raw_definition
    if threshold is None:
        config.get_planogram_description.side_effect = ValueError("no legacy shelves")
    else:
        config.get_planogram_description.return_value = PlanogramDescription(
            brand="Acme",
            category="generic",
            aisle=AisleConfig(name="aisle"),
            shelves=[
                ShelfConfig(level=shelf["level"], products=[], compliance_threshold=threshold)
                for shelf in raw_definition["shelves"]
            ],
        )
    return ProductOnShelves(pipeline=pipeline, config=config)


def ctx(raw_definition: Dict[str, Any], bindings: Sequence[Dict[str, Any]] = ()) -> CycleContext:
    """Deterministic context: default credits/weights, POS default layout, vision that raises."""
    return CycleContext(
        definition=load_slots_definition(raw_definition),
        bindings=[RuleBinding(**binding) for binding in bindings],
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
        layout=ProductOnShelves.default_layout_profile(),
        vision=_RaisingVision(),
    )


def observe(
    rows: List[List[Optional[str]]],
    image_id: str = "img0",
    membership: FixtureMembership = FixtureMembership.ON_FIXTURE,
    extra_shapes: Sequence[Shape] = (),
) -> tuple[PerceptionResult, IdentificationResult]:
    """One product shape + slot per cell; ``None`` = observed empty; row 0 is the top row."""
    shapes: List[Shape] = []
    slots: List[Slot] = []
    idents: List[Identification] = []
    for r, row in enumerate(rows):
        for s, label in enumerate(row, start=1):
            shape_id = f"{image_id}:p{r}_{s}"
            slot_id = f"{image_id}:r{r}:s{s}"
            box = DetectionBox(
                x1=20 + 150 * (s - 1), y1=100 + 200 * r, x2=150 + 150 * (s - 1), y2=250 + 200 * r, confidence=0.9
            )
            shapes.append(
                Shape(
                    shape_id=shape_id,
                    image_id=image_id,
                    kind=ShapeKind.PRODUCT,
                    box=box,
                    row_index=r,
                    slot_index=s,
                    membership=membership,
                )
            )
            slots.append(
                Slot(slot_id=slot_id, image_id=image_id, row_index=r, slot_index=s, box=box, anchor_shape_id=shape_id)
            )
            idents.append(
                Identification(
                    shape_id=slot_id,
                    image_id=image_id,
                    product=label,
                    brand="Acme" if label else None,
                    occupancy="occupied" if label else "empty",
                    raw_confidence=0.9,
                    evidence=[f"reads {label}"] if label else ["empty slot"],
                )
            )
    perception = PerceptionResult(
        image_id=image_id,
        image_size=(1000, 1000),
        shapes=[*shapes, *extra_shapes],
        slots=slots,
        zones=[shape for shape in extra_shapes if shape.kind == ShapeKind.ZONE],
        row_count=len(rows),
    )
    return perception, IdentificationResult(image_id=image_id, identifications=idents)


def zone_shape(image_id: str = "img0", ocr_text: Optional[str] = None) -> Shape:
    """A header zone above the product rows."""
    return Shape(
        shape_id=f"{image_id}:zone",
        image_id=image_id,
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=10, y1=5, x2=600, y2=80, confidence=0.9),
        ocr_text=ocr_text,
        membership=FixtureMembership.ON_FIXTURE,
    )


async def _compare(h: ProductOnShelves, c: CycleContext, *images: Any) -> ComparisonResult:
    """Run compare() over ``(perception, identification)`` pairs."""
    return await h.compare([p for p, _ in images], [i for _, i in images], c)


def with_observations(ident: IdentificationResult, observations: Sequence[RuleObservation]) -> IdentificationResult:
    """Attach rule observations to an identification result."""
    return ident.model_copy(update={"rule_observations": list(observations)})


def illumination(value: Optional[str], image_id: str = "img0", assessed: bool = True) -> RuleObservation:
    """An illumination observation of the header zone."""
    return RuleObservation(
        image_id=image_id,
        target_id=f"{image_id}:zone",
        kind="illumination",
        value=value,
        assessed=assessed,
        source=ObservationSource.LLM,
    )


HEADER_ZONE = {"zone_id": "zone_backlit", "kind": "backlit", "shelf_id": "header", "required": True}


LEGACY_KEYS = (
    "step3_compliance_results",
    "compliance_results",
    "overall_compliance_score",
    "overall_compliant",
    "identified_products",
    "shelf_regions",
    "rendered_image",
    "overlay_path",
)
PRESENT = {FacingStatus.MATCH, FacingStatus.INFERRED_PRESENT, FacingStatus.VARIANT_UNRESOLVED}
ZONE_BINDING = {"rule_id": "zone", "kind": "zone_present", "target_id": "zone_backlit"}


def _status(result: ComparisonResult) -> Dict[str, FacingStatus]:
    """Facing id to status."""
    return {position.facing_id: position.status for position in result.position_results}


def tag_shape(text: str, x1: int = 30, x2: int = 120, image_id: str = "img0", row: int = 0) -> Shape:
    """A fact tag just under the product row ``row``."""
    y1 = 255 + 200 * row
    return Shape(
        shape_id=f"{image_id}:tag:{text}",
        image_id=image_id,
        kind=ShapeKind.FACT_TAG,
        box=DetectionBox(x1=x1, y1=y1, x2=x2, y2=y1 + 20, confidence=0.9),
        ocr_text=text,
        membership=FixtureMembership.ON_FIXTURE,
    )


def _header_ctx(required: str = "on") -> tuple[Dict[str, Any], CycleContext]:
    """Zone-only header definition with one illumination rule."""
    raw = definition({"header": []}, zones=[HEADER_ZONE])
    bindings = [
        ZONE_BINDING,
        {"rule_id": "ill", "kind": "illumination", "target_id": "zone_backlit", "params": {"required": required}},
    ]
    return raw, ctx(raw, bindings)


def _outcome(result: ComparisonResult, rule_id: str = "ill") -> Any:
    """The rule outcome of the first shelf."""
    return {o.rule_id: o for o in result.shelf_scores[0].rule_results}[rule_id]


@pytest.mark.parametrize("value,passed", [("on", True), ("off", False)])
async def test_illumination_rule_follows_observation(value: str, passed: bool) -> None:
    raw, c = _header_ctx()
    perception, ident = observe([], extra_shapes=[zone_shape()])
    result = await _compare(handler(raw), c, (perception, with_observations(ident, [illumination(value)])))
    outcome = _outcome(result)
    assert outcome.assessed is True
    assert outcome.passed is passed
    assert (result.compliance_results[0].compliance_status.value == "compliant") is passed


async def test_illumination_without_observation_is_unassessed() -> None:
    raw, c = _header_ctx()
    result = await _compare(handler(raw), c, observe([], extra_shapes=[zone_shape()]))
    assert _outcome(result).assessed is False
    assert result.compliance_results[0].assessment.assessment_status == "inconclusive"
    assert result.compliance_results[0].compliance_status.value != "compliant"
    assert result.overall_compliant is False


async def test_unknown_illumination_observation_is_unassessed_not_failed() -> None:
    raw, c = _header_ctx()
    perception, ident = observe([], extra_shapes=[zone_shape()])
    ident = with_observations(ident, [illumination(None, assessed=False)])
    result = await _compare(handler(raw), c, (perception, ident))
    assert _outcome(result).assessed is False
    assert _outcome(result).passed is None
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE


async def test_conflicting_illumination_across_photos_is_unassessed() -> None:
    raw, c = _header_ctx()
    images = []
    for image_id, value in (("img0", "on"), ("img1", "off")):
        perception, ident = observe([], image_id=image_id, extra_shapes=[zone_shape(image_id)])
        images.append((perception, with_observations(ident, [illumination(value, image_id)])))
    result = await _compare(handler(raw), c, *images)
    outcome = _outcome(result)
    assert outcome.assessed is False
    assert "conflict" in (outcome.detail or "")
    assert result.compliance_results[0].compliance_status.value != "compliant"


async def test_fact_tag_never_makes_an_unseen_product_present() -> None:
    raw = definition({"top": ["P-100", "P-200"]})
    perception, ident = observe([["P-100"]], extra_shapes=[tag_shape("P-200", x1=170, x2=260)])
    result = await _compare(handler(raw), ctx(raw), (perception, ident))
    positions = {p.facing_id: p for p in result.position_results}
    assert positions["top:2"].status not in PRESENT
    assert positions["top:2"].lenient_credit == 0.0
    assert result.compliance_results[0].compliance_status.value != "compliant"


async def test_fact_tag_corroborates_an_observed_facing() -> None:
    raw = definition({"top": ["P-100", "P-200"]})
    without = await _compare(handler(raw), ctx(raw), observe([["unreadable", "P-200"]]))
    tagged = observe([["unreadable", "P-200"]], extra_shapes=[tag_shape("P-100")])
    with_tag = await _compare(handler(raw), ctx(raw), tagged)
    assert _status(without)["top:1"] != FacingStatus.MATCH
    position = {p.facing_id: p for p in with_tag.position_results}["top:1"]
    assert position.status == FacingStatus.MATCH
    assert 0.0 < position.lenient_credit and position.strict_credit <= position.lenient_credit
    assert {s.value for s in (_status(with_tag)["top:2"],)} == {"match"}


async def test_fact_tag_for_unknown_product_changes_nothing() -> None:
    raw = definition({"top": ["P-100", "P-200"], "bottom": ["P-300"]})
    rows = [["unreadable", "P-200"]]
    baseline = await _compare(handler(raw), ctx(raw), observe(rows))
    tagged = await _compare(handler(raw), ctx(raw), observe(rows, extra_shapes=[tag_shape("UNKNOWN-LABEL")]))
    assert [p.model_dump() for p in tagged.position_results] == [p.model_dump() for p in baseline.position_results]


async def test_fact_tag_naming_another_shelf_product_never_credits_this_facing() -> None:
    raw = definition({"top": ["P-100", "P-200"], "bottom": ["P-300"]})
    rows = [["unreadable", "P-200"]]
    tagged = await _compare(handler(raw), ctx(raw), observe(rows, extra_shapes=[tag_shape("P-300")]))
    positions = {p.facing_id: p for p in tagged.position_results}
    assert positions["top:1"].status not in (FacingStatus.MATCH, FacingStatus.INFERRED_PRESENT)
    assert positions["top:1"].lenient_credit == 0.0
    assert positions["bottom:1"].status not in PRESENT  # the other shelf's facing is never made present by a tag
    assert tagged.compliance_results[0].compliance_status.value != "compliant"


async def test_observed_rows_register_to_definition_shelves_in_order() -> None:
    raw = definition({"top": ["P-100", "P-200"], "bottom": ["P-300"]})
    result = await _compare(handler(raw), ctx(raw), observe([["P-100", "P-200"], ["P-300"]]))
    shelf_of = {p.facing_id: p.shelf_id for p in result.position_results}
    assert shelf_of == {"top:1": "top", "top:2": "top", "bottom:1": "bottom"}
    assert set(_status(result).values()) == {FacingStatus.MATCH}


async def test_more_observed_rows_than_shelves_never_register() -> None:
    raw = definition({"top": ["P-100"]})
    result = await _compare(handler(raw), ctx(raw), observe([["P-100"], ["P-100"]]))
    assert _status(result) == {"top:1": FacingStatus.NOT_VISIBLE}
    assert result.compliance_results[0].compliance_status.value != "compliant"


async def test_off_fixture_shapes_never_register() -> None:
    raw = definition({"top": ["P-100", "P-200"]})
    observed = observe([["P-100", "P-200"]], membership=FixtureMembership.OFF_FIXTURE)
    result = await _compare(handler(raw), ctx(raw), observed)
    assert result.detected_products == 0
    assert all(status not in PRESENT for status in _status(result).values())
    assert result.overall_compliant is False


class _InlineExecutor:
    """CpuExecutor stand-in that runs CPU helpers inline (the real one is covered by test_cpu_executor.py)."""

    def __init__(self, max_workers: int = 2) -> None:
        self.max_workers = max_workers

    async def run(self, fn: Any, *args: Any) -> Any:
        return fn(*args)

    async def aclose(self) -> None:
        return None


async def test_run_round_trip_returns_legacy_keys_measured(
    monkeypatch: pytest.MonkeyPatch, fake_vision_client: Any, synthetic_shelf_image: Any
) -> None:
    monkeypatch.setattr(plan_module, "CpuExecutor", _InlineExecutor)
    raw = definition({"top": ["P-100", "P-200"]})
    perception, ident = observe([["P-100", "P-200"]])

    async def _perceive(self: Any, image: Any, image_id: str, c: Any) -> PerceptionResult:
        return perception.model_copy(update={"image_id": image_id})

    async def _identify(self: Any, image: Any, p: PerceptionResult, c: Any) -> IdentificationResult:
        return ident

    monkeypatch.setattr(ProductOnShelves, "perceive", _perceive)
    monkeypatch.setattr(ProductOnShelves, "identify", _identify)
    config = PlanogramConfig(
        config_name="pos-regression",
        planogram_type="product_on_shelves",
        planogram_config={"brand": "Acme", "category": "generic", "aisle": {"name": "a"}, "shelves": []},
        slots_definition=raw,
    )
    result = await PlanogramCompliance(planogram_config=config, llm=fake_vision_client).run(synthetic_shelf_image)
    assert set(LEGACY_KEYS) <= set(result)
    assert result["compliance_results"] is result["step3_compliance_results"]
    assert result["assessment_status"] == AssessmentStatus.COMPLETE.value
    assert "legacy" not in str(result["assessment_status"]) and "legacy" not in str(result["detection_source"])
    assert result["overall_compliant"] is True
    assert fake_vision_client.calls_to("ask") == []
