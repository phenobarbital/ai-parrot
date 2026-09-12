"""FEAT-550 M1 — policy validation and record semantics (spec §4 'Policy validation')."""

from __future__ import annotations

import asyncio
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


from parrot.clients.budget import QuestionBudget  # noqa: E402


def _est(n: int) -> TokenEstimate:
    return TokenEstimate(input_tokens=n, method="test", quality="estimated", request_fingerprint=f"fp{n}")


def _usage(i: int, o: int) -> BudgetUsage:
    return BudgetUsage(input_tokens=i, output_tokens=o, provider="fake", model="m", route="r")


async def _ledger(b: int = 10_000, reserve: float | int = 0.15, mode: str = "estimated") -> QuestionBudget:
    return QuestionBudget(
        TokenBudgetPolicy(token_budget=b, final_answer_reserve=reserve, budget_mode=mode),
        "op-1",
    )


class TestReservationArithmetic:
    async def test_default_reserve_example(self) -> None:
        """Spec §2.3 example: 2000+500, 3000+700 -> A_work=2300, A_final=3800; 3200 input denied for work."""
        q = await _ledger()
        r1 = await q.reserve(
            _est(2000),
            max_output_tokens=4096,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r1.reservation_id, _usage(2000, 500))
        r2 = await q.reserve(
            _est(3000),
            max_output_tokens=4096,
            min_output_tokens=1,
            call_id="c",
            round_number=2,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r2.reservation_id, _usage(3000, 700))

        rep = await q.report()
        assert rep.remaining_work_tokens == 2300
        assert rep.remaining_total_tokens == 3800

        with pytest.raises(BudgetExhausted):
            await q.reserve(
                _est(3200),
                max_output_tokens=4096,
                min_output_tokens=1,
                call_id="c",
                round_number=3,
                attempt_number=1,
                phase="work",
            )

    async def test_final_phase_requires_claim_and_uses_a_final(self) -> None:
        q = await _ledger()
        r1 = await q.reserve(
            _est(2000),
            max_output_tokens=4096,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r1.reservation_id, _usage(2000, 500))
        r2 = await q.reserve(
            _est(3000),
            max_output_tokens=4096,
            min_output_tokens=1,
            call_id="c",
            round_number=2,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r2.reservation_id, _usage(3000, 700))

        # Denial transitions active -> draining
        with pytest.raises(BudgetExhausted):
            await q.reserve(
                _est(3200),
                max_output_tokens=4096,
                min_output_tokens=1,
                call_id="c",
                round_number=3,
                attempt_number=1,
                phase="work",
            )
        assert q.state == "draining"

        claimed = await q.claim_finalization("c")
        assert claimed is True
        assert q.state == "draining"

        r3 = await q.reserve(
            _est(3200),
            max_output_tokens=4096,
            min_output_tokens=1,
            call_id="c",
            round_number=3,
            attempt_number=1,
            phase="final",
        )
        assert r3.output_cap == 600
        assert q.state == "finalizing"

        with pytest.raises(BudgetExhausted):
            await q.reserve(
                _est(4000),
                max_output_tokens=4096,
                min_output_tokens=1,
                call_id="c",
                round_number=4,
                attempt_number=1,
                phase="final",
            )

    async def test_zero_reserve_refuses_claim_even_with_room_left(self) -> None:
        """Spec §2.1 "Zero disables finalization" — a zero `final_answer_reserve`
        must refuse `claim_finalization()` outright, even when the ordinary
        round that triggered draining left plenty of headroom for a closing
        attempt (code-reviewer finding, FEAT-550 wrap-up: relying only on the
        remaining balance also happening to be zero does not hold in general —
        an underspending ordinary round can leave room even with reserve=0)."""
        q = await _ledger(b=1000, reserve=0)
        r1 = await q.reserve(
            _est(50),
            max_output_tokens=100,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r1.reservation_id, _usage(50, 10))  # consumes only 60/1000

        # A next ordinary round whose ESTIMATE alone exceeds what remains
        # (available_work == available_total for reserve=0) denies and
        # transitions to draining, even though 940 tokens are still unspent.
        with pytest.raises(BudgetExhausted):
            await q.reserve(
                _est(950),
                max_output_tokens=100,
                min_output_tokens=1,
                call_id="c",
                round_number=2,
                attempt_number=1,
                phase="work",
            )
        assert q.state == "draining"

        # There is plenty of room (940 tokens) for a tiny closing attempt —
        # but reserve=0 must refuse the claim regardless.
        assert await q.claim_finalization("c") is False


class TestExactlyOnce:
    async def test_duplicate_settle_inert_and_contradiction_typed(self) -> None:
        q = await _ledger()
        r = await q.reserve(
            _est(1000),
            max_output_tokens=1000,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r.reservation_id, _usage(1000, 200))
        # identical duplicate settlement is inert
        await q.settle(r.reservation_id, _usage(1000, 200))
        # contradictory settlement raises
        with pytest.raises(BudgetAccountingError):
            await q.settle(r.reservation_id, _usage(1000, 300))

    async def test_uncertain_then_late_settle_once(self) -> None:
        q = await _ledger()
        r = await q.reserve(
            _est(1000),
            max_output_tokens=500,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        await q.mark_uncertain(r.reservation_id, "network timeout")
        rep = await q.report()
        assert rep.uncertain_tokens == r.total

        await q.settle(r.reservation_id, _usage(1000, 300))
        rep = await q.report()
        assert rep.uncertain_tokens == 0
        assert rep.total_tokens == 1300

        with pytest.raises(BudgetAccountingError):
            await q.settle(r.reservation_id, _usage(1000, 999))

    async def test_release_only_from_reserved(self) -> None:
        q = await _ledger()
        r = await q.reserve(
            _est(1000),
            max_output_tokens=500,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r.reservation_id, _usage(1000, 200))
        with pytest.raises(BudgetAccountingError):
            await q.release_unspent(r.reservation_id)

    async def test_estimated_overrun_recorded_unclamped(self) -> None:
        q = await _ledger(b=1_000, reserve=0)
        r = await q.reserve(
            _est(500),
            max_output_tokens=700,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r.reservation_id, _usage(500, 700))
        rep = await q.report()
        assert rep.overrun_tokens == 200

    async def test_zero_budget_admits_nothing(self) -> None:
        q = await _ledger(b=0, reserve=0)
        with pytest.raises(BudgetExhausted):
            await q.reserve(
                _est(1),
                max_output_tokens=1,
                min_output_tokens=1,
                call_id="c",
                round_number=1,
                attempt_number=1,
                phase="work",
            )

    async def test_strict_mode_violation_denies_all_further_admission(self) -> None:
        q = await _ledger(b=10_000, reserve=0, mode="strict")
        r = await q.reserve(
            _est(1000),
            max_output_tokens=500,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        with pytest.raises(BudgetAccountingError):
            await q.settle(r.reservation_id, _usage(1000, 600))
        with pytest.raises(BudgetExhausted):
            await q.reserve(
                _est(1),
                max_output_tokens=1,
                min_output_tokens=1,
                call_id="c",
                round_number=2,
                attempt_number=1,
                phase="work",
            )


class TestConcurrency:
    async def test_competing_reservations_cannot_oversubscribe(self) -> None:
        """Barrier-controlled: two coroutines race for the last allowance; exactly one wins."""
        q = await _ledger(b=1000, reserve=0)
        gate = asyncio.Event()

        async def contender(idx: int):
            await gate.wait()
            try:
                return await q.reserve(
                    _est(600),
                    max_output_tokens=300,
                    min_output_tokens=100,
                    call_id=f"c{idx}",
                    round_number=1,
                    attempt_number=1,
                    phase="work",
                )
            except BudgetExhausted:
                return None

        tasks = [asyncio.create_task(contender(i)) for i in range(2)]
        gate.set()
        results = await asyncio.gather(*tasks)
        assert sum(r is not None for r in results) == 1

    async def test_claim_finalization_single_owner(self) -> None:
        """Two claims racing after drain: exactly one succeeds (spec §2.3 'Only the answer owner can claim').

        Uses a nonzero reserve — reserve=0 now always refuses the claim
        outright (spec §2.1 "Zero disables finalization"; see
        test_zero_reserve_refuses_claim_even_with_room_left), which is
        orthogonal to what THIS test exercises (the race itself)."""
        q = await _ledger(b=1000, reserve=100)
        r = await q.reserve(
            _est(600),
            max_output_tokens=300,
            min_output_tokens=1,
            call_id="c",
            round_number=1,
            attempt_number=1,
            phase="work",
        )
        await q.settle(r.reservation_id, _usage(600, 300))
        with pytest.raises(BudgetExhausted):
            await q.reserve(
                _est(600),
                max_output_tokens=300,
                min_output_tokens=100,
                call_id="c",
                round_number=2,
                attempt_number=1,
                phase="work",
            )
        assert q.state == "draining"

        gate = asyncio.Event()

        async def claimant(idx: int) -> bool:
            await gate.wait()
            return await q.claim_finalization(f"owner{idx}")

        tasks = [asyncio.create_task(claimant(i)) for i in range(2)]
        gate.set()
        results = await asyncio.gather(*tasks)
        assert sum(results) == 1


class TestEnforcementFlag:
    def test_defaults_to_enforce(self):
        assert TokenBudgetPolicy(token_budget=1000).enforcement == "enforce"

    def test_observe_is_accepted(self):
        assert TokenBudgetPolicy(token_budget=1000, enforcement="observe").enforcement == "observe"

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=1000, enforcement="advisory")


class TestReportEstimateFields:
    def test_defaults_when_absent(self):
        # Build a BudgetReport with exactly the kwargs _report_locked
        # passes today (parrot/clients/budget.py:340-358) and assert the three
        # new fields default — bounded by AC: "a report built without the new
        # fields still validates"
        report = BudgetReport(
            operation_id="op_1",
            policy=TokenBudgetPolicy(token_budget=1000),
            state="active",
            revision=1,
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            uncertain_tokens=0,
            in_flight_tokens=0,
            remaining_work_tokens=850,
            remaining_total_tokens=850,
            counting_methods=("method1", "method2"),
            overrun_tokens=0,
            accounting_complete=True,
            budget_exhausted=False,
            finalization_attempted=False,
            finalized=False,
            answer_complete=False,
        )
        assert report.settled_estimate_input_tokens == 0
        assert report.released_estimate_tokens == 0


def _estimate(n: int = 5000, method: str = "tiktoken:o200k_base") -> TokenEstimate:
    return TokenEstimate(input_tokens=n, method=method, quality="estimated", request_fingerprint="fp")


@pytest.fixture
def observing_ledger() -> QuestionBudget:
    """A ledger whose ceiling is absurdly below demand, in observe mode."""
    return QuestionBudget(TokenBudgetPolicy(token_budget=1, enforcement="observe"), "op-observe")


class TestObservationalReserve:
    async def test_never_denies_and_preserves_cap(self, observing_ledger):
        for round_no in range(1, 11):
            res = await observing_ledger.reserve(
                _estimate(), max_output_tokens=8192, min_output_tokens=1,
                call_id="c1", round_number=round_no, attempt_number=1, phase="work",
            )
            assert res.output_cap == 8192

    async def test_does_not_consult_available(self, observing_ledger, monkeypatch):
        # Monkeypatch QuestionBudget._available to raise, then assert a
        # reserve() still succeeds — bounded by AC "never calls _available()"
        def raise_on_available(self, phase):
            raise RuntimeError("_available should not be called in observe mode")

        monkeypatch.setattr(QuestionBudget, "_available", raise_on_available)
        # Should not raise
        await observing_ledger.reserve(
            _estimate(), max_output_tokens=8192, min_output_tokens=1,
            call_id="c1", round_number=1, attempt_number=1, phase="work",
        )

    async def test_state_stays_active_past_the_ceiling(self, observing_ledger):
        # Reserve + settle usage far above token_budget, then assert
        # state == "active"
        for i in range(10):
            res = await observing_ledger.reserve(
                _estimate(10000), max_output_tokens=8192, min_output_tokens=1,
                call_id="c1", round_number=i + 1, attempt_number=1, phase="work",
            )
            await observing_ledger.settle(res.reservation_id, _usage(10000, 8000))

        rep = await observing_ledger.report()
        assert rep.state == "active"


class TestSettledEstimateReporting:
    async def test_released_excluded_from_calibration(self):
        # One settled reservation (estimate=100, usage=100) and one
        # released (estimate=1000); assert settled_estimate_input_tokens == 100,
        # released_estimate_tokens == 1000, input_tokens == 100 — the exact
        # scenario spec §10 R5 describes
        q = QuestionBudget(TokenBudgetPolicy(token_budget=100000, enforcement="enforce"), "op-test")
        r1 = await q.reserve(
            _est(100), max_output_tokens=100, min_output_tokens=1,
            call_id="c", round_number=1, attempt_number=1, phase="work",
        )
        await q.settle(r1.reservation_id, _usage(100, 50))

        r2 = await q.reserve(
            _est(1000), max_output_tokens=100, min_output_tokens=1,
            call_id="c", round_number=2, attempt_number=1, phase="work",
        )
        await q.release_unspent(r2.reservation_id)

        rep = await q.report()
        assert rep.settled_estimate_input_tokens == 100
        assert rep.released_estimate_tokens == 1000
        assert rep.input_tokens == 100

    async def test_uncertain_counted_in_neither(self):
        # Mark_uncertain a reservation; assert it appears in neither
        # estimate total — bounded by AC "an uncertain one appears in neither"
        q = QuestionBudget(TokenBudgetPolicy(token_budget=100000, enforcement="enforce"), "op-test")
        r1 = await q.reserve(
            _est(100), max_output_tokens=100, min_output_tokens=1,
            call_id="c", round_number=1, attempt_number=1, phase="work",
        )
        await q.mark_uncertain(r1.reservation_id, "timeout")

        rep = await q.report()
        assert rep.settled_estimate_input_tokens == 0
        assert rep.released_estimate_tokens == 0
        assert rep.uncertain_tokens == 100
