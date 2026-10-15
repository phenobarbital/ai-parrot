"""FEAT-683: appearance rule evaluation and scoring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.comparison.rules import evaluate_rules
from parrot_pipelines.planogram.comparison.scoring import score_shelves
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    FixtureMembership,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    RuleOutcome,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.layout import ZoneSelector


def _box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    """Build a confident fixture-relative box."""
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _binding(**params: object) -> RuleBinding:
    """Bind appearance evidence to the base zone."""
    return RuleBinding(rule_id="appearance:zone-base-1", kind="appearance", target_id="zone-base-1", params=params)


def _definition():
    """Build one zone-only shelf with the appearance target."""
    return load_slots_definition(
        {
            "shelves": [{"shelf_id": "s1", "shelf_number": 1, "level": "base", "facings": []}],
            "zones": [{"zone_id": "zone-base-1", "kind": "graphic", "shelf_id": "s1"}],
        }
    )


def _perception(image_id: str, fragments: list[tuple[str, tuple[int, int, int, int]]]) -> PerceptionResult:
    """Build one image's observed zone fragments."""
    return PerceptionResult(
        image_id=image_id,
        image_size=(200, 200),
        zones=[
            Shape(
                shape_id=shape_id,
                image_id=image_id,
                kind=ShapeKind.ZONE,
                box=_box(*box),
                membership=FixtureMembership.ON_FIXTURE,
                membership_evidence=["zone_selector:zone-base-1"],
            )
            for shape_id, box in fragments
        ],
    )


def _evaluate(
    binding: RuleBinding,
    images: list[tuple[str, list[tuple[str, tuple[int, int, int, int], dict[str, str]]]]],
    selectors: list[ZoneSelector] | None = None,
) -> RuleOutcome:
    """Evaluate appearance observations against the synthetic base-zone definition."""
    perceptions = [_perception(image_id, [(shape_id, box) for shape_id, box, _ in fragments]) for image_id, fragments in images]
    identifications = [
        IdentificationResult(
            image_id=image_id,
            identifications=[],
            rule_observations=[
                RuleObservation(
                    image_id=image_id,
                    target_id=shape_id,
                    kind="appearance",
                    value=value,
                    assessed=True,
                    source=ObservationSource.LLM,
                )
                for shape_id, _box_value, value in fragments
            ],
        )
        for image_id, fragments in images
    ]
    context = CycleContext(
        definition=_definition(),
        bindings=[binding],
        layout=SimpleNamespace(zone_selectors=selectors or []),
    )
    return evaluate_rules(perceptions, identifications, [], context)[
        binding.rule_id
    ]


def test_appearance_all_match_passes() -> None:
    """Every determined configured attribute may pass together."""
    outcome = _evaluate(
        _binding(background_color=["white"], border_color=["blue"], finish=["matte"], base_surface_color=["blue"]),
        [("img0", [("zone0", (0, 0, 100, 100), {"background_color": "white", "border_color": "blue", "finish": "matte", "base_surface_color": "blue"})])],
    )
    assert (outcome.assessed, outcome.passed, outcome.score, outcome.detail) == (True, True, 1.0, None)


def test_appearance_mismatch_fails_with_detail() -> None:
    """A determined attribute outside its accepted values fails the rule."""
    outcome = _evaluate(
        _binding(border_color=["blue"]), [("img0", [("zone0", (0, 0, 100, 100), {"border_color": "grey"})])]
    )
    assert outcome.passed is False
    assert "border_color: grey (expected blue)" in outcome.detail


def test_appearance_unknown_is_unassessed_not_failed() -> None:
    """Undetermined attributes earn no score without failing assessed attributes."""
    outcome = _evaluate(
        _binding(background_color=["white"], finish=["matte"]),
        [("img0", [("zone0", (0, 0, 100, 100), {"background_color": "white", "finish": "unknown"})])],
    )
    assert (outcome.assessed, outcome.passed, outcome.score) == (True, True, pytest.approx(0.5))
    assert "finish: not assessed" in outcome.detail


def test_appearance_nothing_known_unassessed() -> None:
    """No determinate observation leaves the entire rule unassessed."""
    outcome = _evaluate(
        _binding(background_color=["white"], base_surface_color=["blue"]),
        [("img0", [("zone0", (0, 0, 100, 100), {"background_color": "unknown", "base_surface_color": "not_visible"})])],
    )
    assert (outcome.assessed, outcome.passed, outcome.detail) == (False, None, "appearance not observed")


def test_appearance_majority_by_area() -> None:
    """The largest matched fragment decides an image's attribute state."""
    outcome = _evaluate(
        _binding(background_color=["white"]),
        [
            (
                "img0",
                [
                    ("small", (0, 0, 10, 10), {"background_color": "grey"}),
                    ("large", (0, 0, 100, 100), {"background_color": "white"}),
                ],
            )
        ],
        [ZoneSelector(zone_id="zone-base-1", band=(0.0, 1.0))],
    )
    assert outcome.passed is True


def test_appearance_conflict_across_images() -> None:
    """Different image winners leave the attribute unassessed."""
    outcome = _evaluate(
        _binding(background_color=["white"]),
        [
            ("img0", [("zone0", (0, 0, 100, 100), {"background_color": "white"})]),
            ("img1", [("zone1", (0, 0, 100, 100), {"background_color": "blue"})]),
        ],
    )
    assert (outcome.assessed, outcome.passed, outcome.detail) == (False, None, "appearance not observed")


def test_scalar_param_is_one_item_list() -> None:
    """A scalar configured value has the same semantics as a one-item list."""
    outcome = _evaluate(
        _binding(background_color="white"), [("img0", [("zone0", (0, 0, 100, 100), {"background_color": "white"})])]
    )
    assert (outcome.assessed, outcome.passed, outcome.score) == (True, True, 1.0)


def test_appearance_counts_in_visual_term() -> None:
    """A failed mandatory appearance outcome lowers visual score and remains deciding evidence."""
    definition = _definition()
    binding = _binding(background_color=["white"])
    description = PlanogramConfig(
        planogram_config={
            "brand": "Acme",
            "category": "Test",
            "aisle": {"name": "Test"},
            "shelves": [{"level": "base", "height_ratio": 1.0, "products": []}],
        }
    ).get_planogram_description()
    outcome = RuleOutcome(rule_id=binding.rule_id, assessed=True, passed=False, score=0.0)
    shelf = score_shelves([], definition, [binding], {binding.rule_id: outcome}, description, CreditPolicy.default())[0]
    assert shelf.lenient_score == 0.0
    assert shelf.rule_results == [outcome]
