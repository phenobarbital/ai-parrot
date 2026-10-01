"""Tests for the FEAT-574 cycle contracts."""

import pytest
from parrot.models.compliance import ComplianceResult, ComplianceStatus, ShelfAssessment
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FacingStatus,
    Identification,
    IdentificationResult,
    IdentificationResponse,
    IdentifyStrategy,
    ObservationRef,
    ObservationSource,
    OcrReading,
    PerceptionResult,
    ReferenceImage,
    RuleObservation,
    RuleOutcome,
)


def test_credit_policy_defaults_and_validation() -> None:
    """Spec §2 credit table; strict > lenient is rejected."""
    policy = CreditPolicy.default()

    assert policy.strict[FacingStatus.MATCH] == 1.0
    assert policy.lenient[FacingStatus.MATCH] == 1.0

    assert policy.strict[FacingStatus.MISPLACED] == 0.0
    assert policy.lenient[FacingStatus.MISPLACED] == 0.5

    for status in (FacingStatus.VARIANT_UNRESOLVED, FacingStatus.INFERRED_PRESENT):
        assert policy.strict[status] == 0.0
        assert policy.lenient[status] == 1.0

    for status in (
        FacingStatus.MISMATCH,
        FacingStatus.EMPTY,
        FacingStatus.OCCUPIED_UNASSIGNED,
        FacingStatus.CONFLICT,
        FacingStatus.NOT_ASSESSED,
        FacingStatus.NOT_VISIBLE,
        FacingStatus.UNEXPECTED_OCCUPIED,
    ):
        assert policy.strict[status] == 0.0
        assert policy.lenient[status] == 0.0

    strict = dict(policy.strict)
    lenient = dict(policy.lenient)

    # strict > lenient for one status is rejected
    bad_strict_gt_lenient = dict(strict)
    bad_strict_gt_lenient[FacingStatus.MATCH] = 1.0
    bad_lenient = dict(lenient)
    bad_lenient[FacingStatus.MATCH] = 0.0
    with pytest.raises(ValueError):
        CreditPolicy(strict=bad_strict_gt_lenient, lenient=bad_lenient)

    # credit > 1 is rejected
    bad_strict_over_one = dict(strict)
    bad_strict_over_one[FacingStatus.MATCH] = 1.5
    with pytest.raises(ValueError):
        CreditPolicy(strict=bad_strict_over_one, lenient=lenient)

    # missing status is rejected
    missing_strict = dict(strict)
    del missing_strict[FacingStatus.MATCH]
    with pytest.raises(ValueError):
        CreditPolicy(strict=missing_strict, lenient=lenient)


def test_is_resolved_includes_occupied_expected_positions() -> None:
    policy = CreditPolicy.default()
    resolved = {
        FacingStatus.MATCH,
        FacingStatus.MISPLACED,
        FacingStatus.VARIANT_UNRESOLVED,
        FacingStatus.MISMATCH,
        FacingStatus.EMPTY,
        FacingStatus.INFERRED_PRESENT,
        FacingStatus.EXPECTED_EMPTY,
        FacingStatus.UNEXPECTED_OCCUPIED,
    }
    for status in FacingStatus:
        assert policy.is_resolved(status) == (status in resolved)


def test_compliance_result_assessment_is_optional() -> None:
    """Legacy construction without `assessment` still validates; with it, round-trips."""
    legacy = ComplianceResult(
        shelf_level="top",
        expected_products=["a"],
        found_products=["a"],
        missing_products=[],
        unexpected_products=[],
        compliance_status=ComplianceStatus.COMPLIANT,
        compliance_score=1.0,
    )
    assert legacy.assessment is None

    with_assessment = ComplianceResult(
        shelf_level="top",
        expected_products=["a"],
        found_products=["a"],
        missing_products=[],
        unexpected_products=[],
        compliance_status=ComplianceStatus.COMPLIANT,
        compliance_score=1.0,
        assessment=ShelfAssessment(
            assessment_status="complete",
            coverage=1.0,
            strict_score=1.0,
            lenient_score=1.0,
            expected_facings=1,
            resolved_facings=1,
        ),
    )
    assert with_assessment.assessment is not None
    assert with_assessment.assessment.assessment_status == "complete"
    dumped = with_assessment.model_dump()
    restored = ComplianceResult(**dumped)
    assert restored.assessment.coverage == 1.0


def test_safe_defaults_never_read_as_pass() -> None:
    result = ComparisonResult()
    assert result.overall_compliant is False
    assert result.assessment_status is AssessmentStatus.INCONCLUSIVE
    assert result.coverage is None
    assert result.definition_coverage is None
    assert result.evidence_quality is None
    assert result.strict_compliance_score is None


def test_enum_values_are_public_strings() -> None:
    assert ObservationSource.LLM_ADDED.value == "llm_added"
    assert ObservationSource.CV.value == "cv"
    assert ObservationSource.LLM.value == "llm"
    assert ObservationSource.LEGACY_LLM.value == "legacy_llm"
    assert AssessmentStatus.LEGACY_UNMEASURED.value == "legacy_unmeasured"
    assert AssessmentStatus.COMPLETE.value == "complete"
    assert AssessmentStatus.INCONCLUSIVE.value == "inconclusive"
    assert FacingStatus.MATCH.value == "match"
    assert FacingStatus.NOT_VISIBLE.value == "not_visible"


def test_identification_defaults_and_bounds() -> None:
    ident = Identification(shape_id="img0:r0:s1")
    assert ident.occupancy == "unknown"
    assert ident.source is ObservationSource.CV
    assert ident.raw_confidence == 0.0

    with pytest.raises(ValueError):
        Identification(shape_id="img0:r0:s1", raw_confidence=1.5)
    with pytest.raises(ValueError):
        Identification(shape_id="img0:r0:s1", raw_confidence=-0.1)

    response = IdentificationResponse()
    assert response.existing_identifications == []
    assert response.added_shapes == []


def test_cycle_context_builds_with_defaults() -> None:
    ctx = CycleContext()
    assert isinstance(ctx.credit_policy, CreditPolicy)
    assert ctx.credit_policy.strict[FacingStatus.MATCH] == 1.0
    assert ctx.credit_policy.lenient[FacingStatus.MATCH] == 1.0
    assert EvidenceWeights().weight_for(ObservationSource.LLM_ADDED) == 0.5

    # PerceptionResult sanity: contracts.py should be importable end-to-end
    perception = PerceptionResult()
    assert perception.shapes == []


def test_slots_identify_strategy_value() -> None:
    """Slots is an opt-in identify strategy."""
    assert IdentifyStrategy.SLOTS.value == "slots"
    assert IdentifyStrategy("full_image") is IdentifyStrategy.FULL_IMAGE
    assert IdentifyStrategy("strips") is IdentifyStrategy.STRIPS


def test_expected_empty_credits_and_resolution() -> None:
    """Expected-empty credits are resolved without changing prior credits."""
    policy = CreditPolicy.default()
    assert policy.strict[FacingStatus.EXPECTED_EMPTY] == 1.0
    assert policy.lenient[FacingStatus.EXPECTED_EMPTY] == 1.0
    assert policy.strict[FacingStatus.UNEXPECTED_OCCUPIED] == 0.0
    assert policy.lenient[FacingStatus.UNEXPECTED_OCCUPIED] == 0.0
    assert policy.is_resolved(FacingStatus.EXPECTED_EMPTY)
    assert policy.is_resolved(FacingStatus.UNEXPECTED_OCCUPIED)
    assert policy.strict[FacingStatus.MATCH] == 1.0
    assert policy.lenient[FacingStatus.MATCH] == 1.0
    assert policy.strict[FacingStatus.MISPLACED] == 0.0
    assert policy.lenient[FacingStatus.MISPLACED] == 0.5
    assert policy.strict[FacingStatus.INFERRED_PRESENT] == 0.0
    assert policy.lenient[FacingStatus.INFERRED_PRESENT] == 1.0


def test_ocr_reading_bounds() -> None:
    """OCR readings constrain confidence to the normalized range."""
    assert OcrReading().text == "" and OcrReading().confidence == 0.0
    with pytest.raises(ValueError):
        OcrReading(confidence=1.5)
    with pytest.raises(ValueError):
        OcrReading(confidence=-0.1)


def test_reference_image_is_bytes_and_label() -> None:
    """Reference images retain their opaque prompt label and encoded bytes."""
    ref = ReferenceImage(label="ref-0001", image=b"\x89PNG", catalog_key="refs")
    assert ref.brand is None and ref.image == b"\x89PNG"


def test_rule_observation_is_neutral() -> None:
    """Rule observations capture visible evidence rather than verdicts."""
    obs = RuleObservation(
        image_id="img0",
        target_id="img0:zone-region:z1",
        kind="zone_present",
        source=ObservationSource.LLM,
    )
    assert obs.assessed is False and obs.value is None and obs.evidence == []
    assert "passed" not in RuleObservation.model_fields
    with pytest.raises(ValueError):
        RuleObservation(
            image_id="img0",
            target_id="img0:zone-region:z1",
            kind="text_requirements",
            source=ObservationSource.LLM,
        )


def test_new_fields_default_empty() -> None:
    """New cycle fields are optional additive per-run state."""
    assert PerceptionResult().ocr_readings == {}
    assert Identification(shape_id="img0:r0:s1").reference_id is None
    assert IdentificationResult().rule_observations == []
    assert RuleOutcome(rule_id="r").observations == []
    ctx = CycleContext()
    assert ctx.layout is None and ctx.reference_bank == [] and ctx.images == {}
    outcome = RuleOutcome(
        rule_id="r",
        observations=[ObservationRef(image_id="img0", shape_id="z", source=ObservationSource.CV)],
    )
    assert RuleOutcome.model_validate(outcome.model_dump()) == outcome


def test_historical_values_still_parse() -> None:
    """Historical enum values remain deserializable."""
    assert ObservationSource("legacy_llm") is ObservationSource.LEGACY_LLM
    assert AssessmentStatus("legacy_unmeasured") is AssessmentStatus.LEGACY_UNMEASURED
    assert EvidenceWeights().legacy_llm == 0.5
