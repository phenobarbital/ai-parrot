"""FEAT-624 — fact_tag_present outcomes are informative only."""

from __future__ import annotations

import pytest

from parrot.models.compliance import ShelfAssessment
from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.comparison.rules import _rule_fact_tag
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FixtureMembership,
    Identification,
    IdentificationResult,
    ObservationSource,
    OcrReading,
    PerceptionResult,
    RuleOutcome,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.stages.compare import compare_observations


def _setup():
    """One shelf, two facings, both matched in one image."""
    definition = load_slots_definition(
        {
            "shelves": [
                {
                    "shelf_id": "s1",
                    "shelf_number": 1,
                    "level": "top",
                    "facings": [
                        {
                            "facing_id": f"s1_f{i}",
                            "shelf_id": "s1",
                            "slot": i,
                            "product": f"P{i}",
                            "brand": "Acme",
                            "descriptors": {"display_name": f"Product {i}"},
                        }
                        for i in (1, 2)
                    ],
                }
            ]
        }
    )
    description = PlanogramConfig(
        planogram_config={
            "brand": "Acme",
            "category": "T",
            "aisle": {"name": "T"},
            "shelves": [{"level": "top", "height_ratio": 0.3, "products": []}],
        }
    ).get_planogram_description()
    idents = [
        Identification(
            shape_id=f"img0:s1_f{i}",
            image_id="img0",
            product=f"P{i}",
            occupancy="occupied",
            evidence=["sku"],
            source=ObservationSource.CV,
            raw_confidence=0.9,
        )
        for i in (1, 2)
    ]
    registration = ImageRegistration(
        image_id="img0",
        row_to_shelf={0: "s1"},
        assignments={f"img0:s1_f{i}": f"s1_f{i}" for i in (1, 2)},
    )
    return definition, description, [registration], idents


def _run(bindings, outcomes):
    """Run merge, scoring, summarization, projection, and finalization."""
    definition, description, registrations, idents = _setup()
    policy = CreditPolicy.default()
    positions = merge_positions(definition, registrations, idents, policy)
    shelves = score_shelves(positions, definition, bindings, outcomes, description, policy)
    comparison = summarize(shelves, positions, definition, EvidenceWeights())
    results = project_compliance(shelves, positions, definition, description)
    final = finalize_comparison(
        comparison.model_copy(update={"position_results": positions, "shelf_scores": shelves}), results
    )
    return shelves, final


FAILED = RuleOutcome(
    rule_id="fact_tag_present:s1_f1", assessed=True, passed=False, score=0.0, detail="fact tag not observed"
)
BINDING = RuleBinding(rule_id="fact_tag_present:s1_f1", kind="fact_tag_present", target_id="s1_f1", mandatory=False)


def test_failed_fact_tag_changes_no_score_or_status():
    base_shelves, base = _run([], {})
    shelves, final = _run([BINDING], {BINDING.rule_id: FAILED})
    for field in ("strict_score", "lenient_score", "coverage"):
        assert getattr(shelves[0], field) == getattr(base_shelves[0], field)
    assert final.overall_compliance_score == base.overall_compliance_score
    assert final.coverage == base.coverage
    assert final.overall_compliant == base.overall_compliant
    assert [result.compliance_status for result in final.compliance_results] == [
        result.compliance_status for result in base.compliance_results
    ]


def test_fact_tag_outcome_is_in_info_results_only():
    shelves, _ = _run([BINDING], {BINDING.rule_id: FAILED})
    assert [o.rule_id for o in shelves[0].info_results] == [BINDING.rule_id]
    assert all(o.rule_id != BINDING.rule_id for o in shelves[0].rule_results)


def test_missing_outcome_is_a_not_evaluated_placeholder():
    shelves, _ = _run([BINDING], {})
    assert shelves[0].info_results[0].detail == "not evaluated"


@pytest.mark.skipif(
    "info_results" not in ShelfAssessment.model_fields,
    reason="core ai-parrot resolves to the main checkout inside a worktree; runs after merge",
)
def test_projection_carries_info_results():
    _, final = _run([BINDING], {BINDING.rule_id: FAILED})
    assessment = final.compliance_results[0].assessment
    assert assessment.info_results[0]["rule_id"] == BINDING.rule_id


# --- End-to-end: compare_observations over a two-shelf fixture (FEAT-674, resolves FEAT-624 §4) ---

SHELVES = (("s1", "top"), ("s2", "bottom"))
ROW_HEIGHT = 250


def _box(x1, y1, x2, y2):
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9)


def _slot_box(row: int, index: int) -> DetectionBox:
    """Box of slot ``index`` (1-based) in shelf row ``row`` (0-based): 100 px wide, 200 px tall."""
    top = 100 + row * ROW_HEIGHT
    return _box((index - 1) * 100, top, index * 100, top + 200)


def _tag(shape_id: str, row: int, index: int, membership: FixtureMembership) -> Shape:
    """A FACT_TAG shape just below the slot at ``(row, index)``."""
    slot = _slot_box(row, index)
    return Shape(
        shape_id=shape_id,
        image_id="img0",
        kind=ShapeKind.FACT_TAG,
        box=_box(slot.x1 + 20, slot.y2 - 10, slot.x2 - 20, slot.y2 + 20),
        membership=membership,
    )


@pytest.fixture
def tagged_fixture():
    """Two shelves x two facings, every slot read correctly; three tags with different memberships.

    - under s1_f1: ON_FIXTURE tag with OCR ``$129.99``
    - under s1_f2: no tag
    - under s2_f1: UNCERTAIN-membership tag (counts, FEAT-624 spec section 2)
    - under s2_f2: OFF_FIXTURE tag (ignored)
    """
    definition = load_slots_definition(
        {
            "version": "1",
            "shelves": [
                {
                    "shelf_id": shelf_id,
                    "shelf_number": number,
                    "level": level,
                    "facings": [
                        {
                            "facing_id": f"{shelf_id}_f{i}",
                            "shelf_id": shelf_id,
                            "slot": i,
                            "product": f"{shelf_id.upper()}-{i}",
                            "brand": "Acme",
                            "descriptors": {"display_name": f"Product {shelf_id} {i}"},
                        }
                        for i in (1, 2)
                    ],
                }
                for number, (shelf_id, level) in enumerate(SHELVES, start=1)
            ],
        }
    )
    description = PlanogramConfig(
        planogram_config={
            "brand": "Acme",
            "category": "T",
            "aisle": {"name": "T"},
            "shelves": [{"level": level, "height_ratio": 0.3, "products": []} for _, level in SHELVES],
        }
    ).get_planogram_description()
    shapes, slots, idents = [], [], []
    for row, (shelf_id, _) in enumerate(SHELVES):
        for i in (1, 2):
            product_id = f"product_{shelf_id}_{i}"
            slot_id = f"img0:r{row}:s{i}"
            shapes.append(
                Shape(
                    shape_id=product_id,
                    image_id="img0",
                    kind=ShapeKind.PRODUCT,
                    box=_slot_box(row, i),
                    membership=FixtureMembership.ON_FIXTURE,
                )
            )
            slots.append(
                Slot(
                    slot_id=slot_id,
                    image_id="img0",
                    row_index=row,
                    slot_index=i,
                    box=_slot_box(row, i),
                    anchor_shape_id=product_id,
                )
            )
            idents.append(
                Identification(
                    shape_id=slot_id,
                    image_id="img0",
                    product=f"{shelf_id.upper()}-{i}",
                    brand="Acme",
                    occupancy="occupied",
                    evidence=["sku"],
                    source=ObservationSource.CV,
                    raw_confidence=0.9,
                )
            )
    shapes += [
        _tag("tag_s1_f1", 0, 1, FixtureMembership.ON_FIXTURE),
        _tag("tag_s2_f1", 1, 1, FixtureMembership.UNCERTAIN),
        _tag("tag_s2_f2", 1, 2, FixtureMembership.OFF_FIXTURE),
    ]
    perception = PerceptionResult(
        image_id="img0",
        image_size=(200, 600),
        shapes=shapes,
        slots=slots,
        ocr_readings={"tag_s1_f1": OcrReading(text="$129.99")},
        row_count=2,
    )
    identification = IdentificationResult(image_id="img0", identifications=idents)
    return definition, description, perception, identification


def _fact_tag_binding(facing_id: str, price_required: bool = False) -> RuleBinding:
    return RuleBinding(
        rule_id=f"fact_tag_present:{facing_id}",
        kind="fact_tag_present",
        target_id=facing_id,
        params={"price_required": price_required},
        mandatory=False,
    )


def _compare(fixture, bindings):
    definition, description, perception, identification = fixture
    ctx = CycleContext(
        definition=definition,
        bindings=list(bindings),
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )
    return compare_observations([perception], [identification], ctx, description)


def test_compare_observations_reports_fact_tags(tagged_fixture):
    bindings = [
        _fact_tag_binding("s1_f1", price_required=True),
        _fact_tag_binding("s1_f2"),
        _fact_tag_binding("s2_f1"),
        _fact_tag_binding("s2_f2"),
    ]
    base = _compare(tagged_fixture, [])
    final = _compare(tagged_fixture, bindings)

    # Registration really ran: every facing is matched, so the fixture is fully compliant.
    assert base.errors == [] and final.errors == []
    assert base.overall_compliant is True

    # Informative outcomes, per shelf, in info_results only.
    outcomes = {o.rule_id: o for shelf in final.shelf_scores for o in shelf.info_results}
    by_shelf = {shelf.shelf_id: [o.rule_id for o in shelf.info_results] for shelf in final.shelf_scores}
    assert by_shelf == {
        "s1": ["fact_tag_present:s1_f1", "fact_tag_present:s1_f2"],
        "s2": ["fact_tag_present:s2_f1", "fact_tag_present:s2_f2"],
    }
    assert all(not shelf.rule_results for shelf in final.shelf_scores)
    assert (outcomes["fact_tag_present:s1_f1"].assessed, outcomes["fact_tag_present:s1_f1"].passed) == (True, True)
    assert [ref.shape_id for ref in outcomes["fact_tag_present:s1_f1"].observations] == ["tag_s1_f1"]
    assert (outcomes["fact_tag_present:s1_f2"].passed, outcomes["fact_tag_present:s1_f2"].detail) == (
        False,
        "fact tag not observed",
    )
    assert outcomes["fact_tag_present:s2_f1"].passed is True
    assert (outcomes["fact_tag_present:s2_f2"].passed, outcomes["fact_tag_present:s2_f2"].detail) == (
        False,
        "fact tag not observed",
    )
    assert all(outcome.penalty == 0.0 for outcome in outcomes.values())

    # The compliance result is unchanged by the informative bindings.
    assert final.overall_compliance_score == base.overall_compliance_score
    assert final.overall_compliant == base.overall_compliant
    assert final.coverage == base.coverage
    for field in ("strict_score", "lenient_score", "coverage"):
        assert [getattr(s, field) for s in final.shelf_scores] == [getattr(s, field) for s in base.shelf_scores]
    assert [r.compliance_status for r in final.compliance_results] == [
        r.compliance_status for r in base.compliance_results
    ]


@pytest.mark.parametrize(
    ("membership", "passed"),
    [
        (FixtureMembership.ON_FIXTURE, True),
        (FixtureMembership.UNCERTAIN, True),
        (FixtureMembership.OFF_FIXTURE, False),
    ],
)
def test_uncertain_membership_tag_counts(membership, passed):
    slot = Slot(slot_id="img0:s1", image_id="img0", row_index=0, slot_index=1, box=_slot_box(0, 1))
    perception = PerceptionResult(
        image_id="img0", image_size=(200, 400), shapes=[_tag("img0:t1", 0, 1, membership)], slots=[slot]
    )
    outcome = _rule_fact_tag(
        _fact_tag_binding("f1"),
        [perception],
        [IdentificationResult(image_id="img0", identifications=[])],
        [ImageRegistration(image_id="img0", assignments={"img0:s1": "f1"})],
    )
    assert (outcome.assessed, outcome.passed) == (True, passed)
