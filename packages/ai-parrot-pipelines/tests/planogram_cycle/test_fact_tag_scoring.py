"""FEAT-624 — fact_tag_present outcomes are informative only."""

from __future__ import annotations

import pytest

from parrot.models.compliance import ShelfAssessment
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    EvidenceWeights,
    Identification,
    ObservationSource,
    RuleOutcome,
)


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


FAILED = RuleOutcome(rule_id="fact_tag_present:s1_f1", assessed=True, passed=False, score=0.0, detail="fact tag not observed")
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
