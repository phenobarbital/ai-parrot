"""Unit tests for FEAT-304 claims domain models (TASK-019)."""

import pytest
from pydantic import ValidationError

from parrot_formdesigner.services import (
    ClaimCategory,
    ClaimEventConfig,
    ClaimExceptionConfig,
    ClaimExceptionThresholdType,
    ClaimScope,
    ClaimTypeConfig,
    PayPeriodConfig,
)


def test_claim_type_config_defaults() -> None:
    cfg = ClaimTypeConfig(category=ClaimCategory.TIME, scope=ClaimScope.PROGRAM)
    assert cfg.auto_approve is False
    assert cfg.requires_receipt is False
    assert cfg.event_config is ClaimEventConfig.ALLOW
    assert cfg.budget_code is None


def test_claim_category_enum_values() -> None:
    assert {c.value for c in ClaimCategory} == {"time", "amount", "distance"}


def test_claim_scope_enum_values() -> None:
    assert {s.value for s in ClaimScope} == {"global", "client", "program"}


def test_exception_threshold_type_has_five_members() -> None:
    # Five confirmed Vision IQ thresholds (extensible enum).
    assert {t.value for t in ClaimExceptionThresholdType} == {
        "distance",
        "min_per_claim",
        "daily_minutes",
        "time_amount",
        "dollar_amount",
    }


def test_pay_period_config_accrue_default() -> None:
    assert PayPeriodConfig().accrue_to_next is True


def test_exception_config_blocks_auto_approve() -> None:
    cfg = ClaimExceptionConfig(
        threshold_type=ClaimExceptionThresholdType.DISTANCE,
        threshold_value=100.0,
        prompt="too far",
    )
    assert cfg.blocks_auto_approve is True


def test_models_forbid_extra_keys() -> None:
    with pytest.raises(ValidationError):
        ClaimTypeConfig(
            category=ClaimCategory.TIME,
            scope=ClaimScope.GLOBAL,
            bogus="x",  # type: ignore[call-arg]
        )
