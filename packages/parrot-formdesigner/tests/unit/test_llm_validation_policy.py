"""Unit tests for the LLM-validation enforcement policy (FEAT-728, TASK-4623)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core import implausible_fields as exported_implausible_fields
from parrot_formdesigner.core.llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    implausible_fields,
)


def _report(status: str = "ok", threshold: float = 0.7, **items: PlausibilityVerdict) -> PlausibilityReport:
    """Build a report carrying the supplied verdicts."""
    return PlausibilityReport(status=status, threshold=threshold, items=dict(items))


def _verdict(plausible: bool = True, confidence: float = 1.0) -> PlausibilityVerdict:
    """Build one plausibility verdict."""
    return PlausibilityVerdict(plausible=plausible, confidence=confidence, reason="")


class TestPolicyField:
    """Tests for the form-level implausibility policy."""

    def test_on_implausible_defaults_to_annotate(self) -> None:
        """Existing payloads retain annotate behavior when the key is absent."""
        assert LLMValidationConfig().on_implausible == "annotate"
        assert LLMValidationConfig.model_validate({"enabled": True}).on_implausible == "annotate"

    def test_on_implausible_rejects_unknown_value(self) -> None:
        """Only the three documented policy values are accepted."""
        with pytest.raises(ValidationError):
            LLMValidationConfig(on_implausible="hold")


class TestImplausibleFields:
    """Tests for the report-only enforcement classifier."""

    def test_flags_not_plausible(self) -> None:
        """A negative plausibility verdict trips regardless of confidence."""
        assert implausible_fields(_report(answer=_verdict(plausible=False, confidence=1.0))) == ["answer"]

    def test_flags_below_threshold(self) -> None:
        """Confidence below the report threshold trips the classifier."""
        assert implausible_fields(_report(threshold=0.7, answer=_verdict(confidence=0.69))) == ["answer"]

    def test_threshold_boundary_is_strict(self) -> None:
        """Confidence equal to the threshold does not trip the classifier."""
        assert implausible_fields(_report(threshold=0.7, answer=_verdict(confidence=0.7))) == []

    def test_returns_sorted_ids(self) -> None:
        """Flagged field ids are returned in stable sorted order."""
        report = _report(zebra=_verdict(plausible=False), alpha=_verdict(confidence=0.5))
        assert implausible_fields(report) == ["alpha", "zebra"]

    @pytest.mark.parametrize("status", ["skipped", "blocked"])
    def test_empty_for_non_ok_status(self, status: str) -> None:
        """Skipped and blocked reports do not flag answers."""
        report = _report(status=status, answer=_verdict(plausible=False))
        assert implausible_fields(report) == []

    def test_empty_report_is_empty(self) -> None:
        """An OK report without verdicts flags nothing."""
        assert implausible_fields(_report()) == []

    def test_core_reexport_matches_classifier(self) -> None:
        """The public core namespace exposes the classifier."""
        assert exported_implausible_fields is implausible_fields
