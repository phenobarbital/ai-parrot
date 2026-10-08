"""Reporting label policy and compliance invariance for FEAT-645."""

import pytest

from parrot.models.detections import AisleConfig, PlanogramDescription
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, SlotsDefinition
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    FacingStatus,
    ObservationRef,
    PositionResult,
    RuleOutcome,
    ShelfScore,
)


def _definition() -> SlotsDefinition:
    """Build occupied and expected-empty facings with distinct labels."""
    return SlotsDefinition.model_validate(
        {
            "shelves": [
                {
                    "shelf_id": "ink_top",
                    "shelf_number": 1,
                    "level": "top",
                    "facings": [
                        {
                            "facing_id": "f1",
                            "shelf_id": "ink_top",
                            "slot": 1,
                            "product": "MODEL-CLOSEOUT",
                            "descriptors": {"display_name": "Closeout display one"},
                        },
                        {
                            "facing_id": "f2",
                            "shelf_id": "ink_top",
                            "slot": 2,
                            "product": "MODEL-CLOSEOUT",
                            "descriptors": {"display_name": "Closeout display two"},
                        },
                        {
                            "facing_id": "f3",
                            "shelf_id": "ink_top",
                            "slot": 3,
                            "product": "MODEL-THRESHOLD",
                            "descriptors": {"display_name": "Threshold display"},
                        },
                        {
                            "facing_id": "f4",
                            "shelf_id": "ink_top",
                            "slot": 4,
                            "product": "MODEL-LOW-DECIDING",
                            "descriptors": {"display_name": "Low deciding display"},
                        },
                        {
                            "facing_id": "f5",
                            "shelf_id": "ink_top",
                            "slot": 5,
                            "product": "MODEL-MISMATCH",
                            "descriptors": {"display_name": "Mismatch display"},
                        },
                        {
                            "facing_id": "f6",
                            "shelf_id": "ink_top",
                            "slot": 6,
                            "product": "MODEL-EMPTY",
                            "descriptors": {"display_name": "Empty display"},
                        },
                        {
                            "facing_id": "empty_slot",
                            "shelf_id": "ink_top",
                            "slot": 7,
                            "expected_occupancy": "empty",
                        },
                    ],
                }
            ]
        }
    )


def _description() -> PlanogramDescription:
    """Return the minimum real description accepted by the projection."""
    return PlanogramDescription(brand="Expected brand", category="Ink", aisle=AisleConfig(name="Aisle"), shelves=[])


def _position(
    facing_id: str,
    status: FacingStatus,
    identity: str | None = None,
    confidence: float = 0.95,
) -> PositionResult:
    """Return a position whose first observation is the deciding view."""
    return PositionResult(
        facing_id=facing_id,
        shelf_id="ink_top",
        status=status,
        identity=identity,
        observations=[ObservationRef(image_id="img0", shape_id=facing_id, source="cv", raw_confidence=confidence)],
    )


def _fixture() -> tuple[SlotsDefinition, list[ShelfScore], list[PositionResult], PlanogramDescription]:
    """Build a complete shelf covering every reporting presence outcome."""
    definition = _definition()
    low_deciding = _position("f4", FacingStatus.MISPLACED, "Observed after low view", confidence=0.5)
    low_deciding.observations.append(ObservationRef(image_id="img1", shape_id="f4", source="cv", raw_confidence=0.99))
    positions = [
        _position("f1", FacingStatus.MATCH, "Observed brand only"),
        _position("f2", FacingStatus.INFERRED_PRESENT, "Observed inferred brand"),
        _position("f3", FacingStatus.MISPLACED, "Observed threshold model", confidence=0.9),
        low_deciding,
        _position("f5", FacingStatus.MISMATCH, "Observed wrong model"),
        _position("f6", FacingStatus.EMPTY),
        _position("empty_slot", FacingStatus.UNEXPECTED_OCCUPIED, "Unexpected observed model"),
    ]
    scores = [
        ShelfScore(
            shelf_id="ink_top",
            shelf_level="top",
            expected_facings=6,
            facing_strict=0.25,
            facing_lenient=0.5,
            strict_score=0.25,
            lenient_score=0.5,
            coverage=1.0,
        )
    ]
    return definition, scores, positions, _description()


def _without_labels(result: dict[str, object]) -> dict[str, object]:
    """Remove the only policy-controlled fields from a serialized result."""
    return {
        key: value
        for key, value in result.items()
        if key not in {"expected_products", "found_products", "missing_products", "unexpected_products"}
    }


def test_project_compliance_product_labels() -> None:
    """Product mode lists expected models, preserves facings and excludes brand-only identity."""
    definition, scores, positions, description = _fixture()

    result = project_compliance(
        scores,
        positions,
        definition,
        description,
        policy=ReportingPolicy(product_label="product", misplaced_min_confidence=0.9),
    )[0]

    assert result.expected_products == [
        "MODEL-CLOSEOUT",
        "MODEL-CLOSEOUT",
        "MODEL-THRESHOLD",
        "MODEL-LOW-DECIDING",
        "MODEL-MISMATCH",
        "MODEL-EMPTY",
    ]
    assert result.found_products == ["MODEL-CLOSEOUT", "MODEL-CLOSEOUT", "MODEL-THRESHOLD"]
    assert result.missing_products == ["MODEL-EMPTY"]
    assert "Observed brand only" not in result.found_products


def test_project_compliance_default_unchanged() -> None:
    """Omitted and display-name policies produce identical legacy serialized results."""
    definition, scores, positions, description = _fixture()

    default = project_compliance(scores, positions, definition, description)[0]
    explicit = project_compliance(scores, positions, definition, description, policy=ReportingPolicy())[0]

    assert default.model_dump(mode="json") == explicit.model_dump(mode="json")
    assert default.expected_products == [
        "Closeout display one",
        "Closeout display two",
        "Threshold display",
        "Low deciding display",
        "Mismatch display",
        "Empty display",
    ]
    assert default.found_products == [
        "Observed brand only",
        "Observed inferred brand",
        "Observed threshold model",
        "Observed after low view",
        "Observed wrong model",
    ]
    assert default.missing_products == ["Empty display"]


def test_scores_identical_across_policies() -> None:
    """Only label lists differ; projection and finalization decisions remain equal."""
    definition, scores, positions, description = _fixture()
    legacy = project_compliance(scores, positions, definition, description)
    product = project_compliance(
        scores, positions, definition, description, policy=ReportingPolicy(product_label="product")
    )

    assert _without_labels(legacy[0].model_dump(mode="json")) == _without_labels(product[0].model_dump(mode="json"))
    assert legacy[0].compliance_score == pytest.approx(product[0].compliance_score)
    comparison = ComparisonResult(
        assessment_status=AssessmentStatus.COMPLETE,
        overall_compliance_score=0.5,
        strict_compliance_score=0.25,
    )
    legacy_final = finalize_comparison(comparison, legacy)
    product_final = finalize_comparison(comparison, product)
    assert legacy_final.overall_compliant is product_final.overall_compliant
    assert legacy_final.model_dump(exclude={"compliance_results"}) == product_final.model_dump(
        exclude={"compliance_results"}
    )


def test_illumination_and_unexpected_labels_unchanged() -> None:
    """Illumination details and observed unexpected products keep their established meaning."""
    definition, scores, positions, description = _fixture()
    scores[0].rule_results = [
        RuleOutcome(
            rule_id="illumination",
            assessed=True,
            passed=False,
            score=0.0,
            penalty=0.5,
            detail="Backlight is off",
        )
    ]

    legacy = project_compliance(scores, positions, definition, description)[0]
    product = project_compliance(
        scores, positions, definition, description, policy=ReportingPolicy(product_label="product")
    )[0]

    assert legacy.unexpected_products == product.unexpected_products == ["Unexpected observed model"]
    assert legacy.missing_products[-1] == product.missing_products[-1] == "Backlight is off"
