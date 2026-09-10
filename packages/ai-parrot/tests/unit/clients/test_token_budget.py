"""FEAT-550 M1 — policy validation and record semantics (spec §4 'Policy validation')."""
from __future__ import annotations

import math
from decimal import Decimal
import pytest
from pydantic import ValidationError

from parrot.core.exceptions import (
    BudgetError,
    BudgetExhausted,
    BudgetUnsupported,
    BudgetScopeConflict,
    BudgetStateMissing,
    BudgetResumeConflict,
    BudgetSnapshotInvalid,
    BudgetAccountingError,
    BudgetRegistryFull,
)
from parrot.models.responses import InvokeResult
from parrot.models.basic import CompletionUsage
from parrot.models.token_budget import (
    TokenBudgetPolicy,
    TokenEstimate,
    BudgetUsage,
    BudgetReservation,
    BudgetReport,
    BudgetSnapshot,
)


class TestTokenBudgetPolicy:
    def test_valid_policy_defaults(self) -> None:
        policy = TokenBudgetPolicy(token_budget=10000)
        assert policy.token_budget == 10000
        assert policy.budget_mode == "estimated"
        assert policy.final_answer_reserve == 0.15
        assert policy.final_reserve_tokens == 1500

    def test_valid_policy_absolute_reserve(self) -> None:
        policy = TokenBudgetPolicy(token_budget=10000, final_answer_reserve=1000)
        assert policy.final_answer_reserve == 1000
        assert policy.final_reserve_tokens == 1000

    def test_valid_policy_zero_reserve(self) -> None:
        policy = TokenBudgetPolicy(token_budget=10000, final_answer_reserve=0)
        assert policy.final_reserve_tokens == 0

        policy_float = TokenBudgetPolicy(token_budget=10000, final_answer_reserve=0.0)
        assert policy_float.final_reserve_tokens == 0

    def test_policy_rounding_floor(self) -> None:
        # 15% of 10005 is 1500.75 -> floor is 1500
        policy = TokenBudgetPolicy(token_budget=10005, final_answer_reserve=0.15)
        assert policy.final_reserve_tokens == 1500

        # 15% of 10007 is 1501.05 -> floor is 1501
        policy2 = TokenBudgetPolicy(token_budget=10007, final_answer_reserve=0.15)
        assert policy2.final_reserve_tokens == 1501

    def test_reject_invalid_types_strict(self) -> None:
        # strict=True should reject string token_budget
        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget="10000")  # type: ignore

        # strict=True should reject bool token_budget
        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=True)  # type: ignore

        # reject bool final_answer_reserve
        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=10000, final_answer_reserve=True)

    def test_reject_negative_values(self) -> None:
        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=-100)

        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=10000, final_answer_reserve=-5)

        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=10000, final_answer_reserve=-0.1)

    def test_reject_out_of_range_reserve(self) -> None:
        # float reserve > 1.0
        with pytest.raises(ValidationError, match="fractional final_answer_reserve must be finite and within"):
            TokenBudgetPolicy(token_budget=10000, final_answer_reserve=1.1)

        # int reserve > token_budget
        with pytest.raises(ValidationError, match="absolute final_answer_reserve must be within"):
            TokenBudgetPolicy(token_budget=10000, final_answer_reserve=10001)

    def test_reject_non_finite_float_reserve(self) -> None:
        with pytest.raises(ValidationError, match="fractional final_answer_reserve must be finite and within"):
            TokenBudgetPolicy(token_budget=10000, final_answer_reserve=float("nan"))

        with pytest.raises(ValidationError, match="fractional final_answer_reserve must be finite and within"):
            TokenBudgetPolicy(token_budget=10000, final_answer_reserve=float("inf"))

    def test_immutability(self) -> None:
        policy = TokenBudgetPolicy(token_budget=10000)
        with pytest.raises(ValidationError if hasattr(ValidationError, "FrozenError") else Exception):
            policy.token_budget = 5000  # type: ignore


class TestOtherRecords:
    def test_token_estimate(self) -> None:
        est = TokenEstimate(
            input_tokens=100,
            method="cl100k_base",
            quality="exact",
            request_fingerprint="fp123",
        )
        assert est.input_tokens == 100
        assert est.quality == "exact"
        with pytest.raises(Exception):
            est.input_tokens = 200  # type: ignore

    def test_budget_usage(self) -> None:
        usage = BudgetUsage(
            input_tokens=150,
            output_tokens=50,
            details={"cache_read": 50},
            provider="bedrock",
            model="anthropic.claude-3",
            route="direct",
        )
        assert usage.total_tokens == 200
        with pytest.raises(Exception):
            usage.input_tokens = 200  # type: ignore

    def test_budget_reservation(self) -> None:
        res = BudgetReservation(
            reservation_id="res_1",
            operation_id="op_1",
            call_id="call_1",
            round_number=0,
            attempt_number=1,
            phase="work",
            input_allowance=500,
            output_cap=200,
            request_fingerprint="fp123",
        )
        assert res.total == 700
        with pytest.raises(Exception):
            res.input_allowance = 600  # type: ignore


class TestBudgetErrors:
    def test_error_hierarchy_and_attributes(self) -> None:
        report_dict = {"operation_id": "op_123", "state": "active"}
        err = BudgetExhausted("Out of tokens", operation_id="op_123", report=report_dict)
        assert isinstance(err, BudgetError)
        assert err.code == "budget_exhausted"
        assert err.operation_id == "op_123"
        assert err.report == report_dict

        # Verify other error codes
        assert BudgetUnsupported("msg").code == "budget_unsupported"
        assert BudgetScopeConflict("msg").code == "budget_scope_conflict"
        assert BudgetStateMissing("msg").code == "budget_state_missing"
        assert BudgetResumeConflict("msg").code == "budget_resume_conflict"
        assert BudgetSnapshotInvalid("msg").code == "budget_snapshot_invalid"
        assert BudgetAccountingError("msg").code == "budget_accounting_error"
        assert BudgetRegistryFull("msg").code == "budget_registry_full"


class TestInvokeResultBudgetReport:
    def test_invoke_result_has_budget_report(self) -> None:
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        res = InvokeResult(
            output="hello",
            model="test-model",
            usage=usage,
            budget_report={"operation_id": "op_123", "budget_exhausted": False},
        )
        assert res.budget_report == {"operation_id": "op_123", "budget_exhausted": False}

        # Default should be None
        res_default = InvokeResult(
            output="hello",
            model="test-model",
            usage=usage,
        )
        assert res_default.budget_report is None
