"""FEAT-624 — fact_tag_present kind and informative result fields."""

from __future__ import annotations

import pytest

from parrot.models.compliance import ShelfAssessment
from parrot_pipelines.planogram.comparison.definition import (
    RuleBinding,
    SlotsDefinitionError,
    load_slots_definition,
    validate_bindings,
)
from parrot_pipelines.planogram.contracts import RuleOutcome, ShelfScore


@pytest.fixture
def definition():
    """One shelf with two described facings and one zone on a second, zone-only shelf."""
    return load_slots_definition(
        {
            "shelves": [
                {
                    "shelf_id": "s1",
                    "shelf_number": 1,
                    "facings": [
                        {
                            "facing_id": "s1:1",
                            "shelf_id": "s1",
                            "slot": 1,
                            "product": "A",
                            "descriptors": {"display_name": "A"},
                        },
                        {
                            "facing_id": "s1:2",
                            "shelf_id": "s1",
                            "slot": 2,
                            "product": "B",
                            "descriptors": {"display_name": "B"},
                        },
                    ],
                },
                {"shelf_id": "s2", "shelf_number": 2, "facings": []},
            ],
            "zones": [{"zone_id": "z1", "kind": "header", "shelf_id": "s2"}],
        }
    )


def _binding(target: str, mandatory: bool = False) -> dict:
    return {
        "rule_id": f"fact_tag_present:{target}",
        "kind": "fact_tag_present",
        "target_id": target,
        "params": {"price_required": True},
        "mandatory": mandatory,
    }


def _zone_rule() -> dict:
    return {"rule_id": "zone_present:z1", "kind": "zone_present", "target_id": "z1", "mandatory": True}


def test_fact_tag_kind_is_accepted(definition):
    bindings = validate_bindings(definition, {"rule_bindings": [_binding("s1:1"), _zone_rule()]})
    assert [binding.kind for binding in bindings] == ["fact_tag_present", "zone_present"]


@pytest.mark.parametrize("target", ["z1", "s1"])
def test_fact_tag_binding_must_target_a_facing(definition, target):
    with pytest.raises(SlotsDefinitionError, match="must target a facing"):
        validate_bindings(definition, {"rule_bindings": [_binding(target), _zone_rule()]})


def test_fact_tag_binding_cannot_be_mandatory(definition):
    with pytest.raises(SlotsDefinitionError, match="informative and cannot be mandatory"):
        validate_bindings(definition, {"rule_bindings": [_binding("s1:1", mandatory=True), _zone_rule()]})


def test_fact_tag_binding_does_not_satisfy_zone_only_shelf(definition):
    with pytest.raises(SlotsDefinitionError, match="s2: zone-only shelf has no mandatory bound rule"):
        validate_bindings(definition, {"rule_bindings": [_binding("s1:1")]})


def test_shelf_score_has_info_results():
    score = ShelfScore(shelf_id="s1", shelf_level="s1", info_results=[RuleOutcome(rule_id="r")])
    assert score.info_results[0].rule_id == "r" and score.rule_results == []


@pytest.mark.skipif(
    "info_results" not in ShelfAssessment.model_fields,
    reason="core ai-parrot resolves to the main checkout inside a worktree; runs after merge",
)
def test_shelf_assessment_has_info_results():
    assert ShelfAssessment(info_results=[{"rule_id": "r"}]).info_results == [{"rule_id": "r"}]
