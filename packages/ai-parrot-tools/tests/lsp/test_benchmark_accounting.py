"""Unit tests for the FEAT-580 M5 pilot manifest and cache-aware accounting.

All tests are pure in-memory Pydantic validation and arithmetic: no
process is started, no server is probed, and no live price is read
anywhere in this module (TASK-3509).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

#: tests/lsp -> tests -> ai-parrot-tools -> packages -> repo root
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.sdd_lsp.accounting import (  # noqa: E402
    attempt_cost_usd,
    category_costs_usd,
    find_duplicate_usage_keys,
    usage_cost_usd,
    validate_model_usage,
)
from benchmarks.sdd_lsp.models import (  # noqa: E402
    ARM_NAMES,
    REPETITIONS,
    TASK_COUNT,
    AttemptRecord,
    CachePriceRow,
    ModelUsage,
    PilotManifest,
    PriceBook,
    SeatSpec,
)

MODEL = "gpt-5-codex"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _valid_seats() -> dict[str, SeatSpec]:
    return {arm: SeatSpec(arm=arm, argv=["echo", arm], timeout_s=30.0) for arm in ARM_NAMES}


def _valid_manifest(**overrides: object) -> PilotManifest:
    fields: dict[str, object] = dict(
        pinned_commit="abc123def",
        task_ids=tuple(f"task-{i}" for i in range(TASK_COUNT)),
        repetitions=REPETITIONS,
        arms=ARM_NAMES,
        seats=_valid_seats(),
        model=MODEL,
        environment_id="pinned-env-1",
        price_provenance="vendor console, read 2026-09-19",
        cache_semantics="provider-reported ephemeral cache classes (5m/1h)",
        spending_ceiling_usd=50.0,
        per_attempt_cost_reservation_usd=2.0,
    )
    fields.update(overrides)
    return PilotManifest(**fields)


def _price_book() -> PriceBook:
    return PriceBook(
        rows={
            MODEL: CachePriceRow(
                input_usd_per_1k=1.0,
                cache_read_usd_per_1k=0.1,
                cache_write_usd_per_1k={"5m": 1.25, "1h": 2.0},
                output_usd_per_1k=3.0,
                reasoning_usd_per_1k=3.0,
                effective_date="2026-09-01",
                provenance="vendor console",
            )
        }
    )


# --------------------------------------------------------------------------- #
# Manifest dimensions and explicit spending budget
# --------------------------------------------------------------------------- #
def test_manifest_dimensions_and_explicit_budget():
    """A well-formed manifest is exactly 12 tasks x 3 reps x 5 arms = 180."""
    manifest = _valid_manifest()
    assert manifest.total_attempts == 180
    assert set(manifest.arms) == set(ARM_NAMES)
    assert len(manifest.task_ids) == TASK_COUNT

    with pytest.raises(ValidationError):
        _valid_manifest(task_ids=tuple(f"task-{i}" for i in range(TASK_COUNT - 1)))

    with pytest.raises(ValidationError):
        _valid_manifest(task_ids=("dup-task",) * TASK_COUNT)

    with pytest.raises(ValidationError):
        _valid_manifest(repetitions=2)

    with pytest.raises(ValidationError):
        _valid_manifest(arms=("current", "wiki_ast"))

    with pytest.raises(ValidationError):
        seats = _valid_seats()
        del seats["lsp_combined"]
        _valid_manifest(seats=seats)

    with pytest.raises(ValidationError):
        seats = _valid_seats()
        seats["current"] = SeatSpec(arm="wiki_ast", argv=["echo"], timeout_s=5.0)
        _valid_manifest(seats=seats)

    with pytest.raises(ValidationError):
        _valid_manifest(spending_ceiling_usd=1.0, per_attempt_cost_reservation_usd=5.0)

    with pytest.raises(ValidationError):
        _valid_manifest(spending_ceiling_usd=-1.0)

    with pytest.raises(ValidationError):
        _valid_manifest(per_attempt_cost_reservation_usd=0.0)

    with pytest.raises(ValidationError):
        SeatSpec(arm="current", argv=["ok", ""], timeout_s=5.0)


# --------------------------------------------------------------------------- #
# Disjoint cache/read/write/output/reasoning billing
# --------------------------------------------------------------------------- #
def test_cache_categories_are_disjoint():
    """Every billing category is priced exactly once and never merged."""
    prices = _price_book()
    usage = ModelUsage(
        attempt_id="a1",
        seat_id="s1",
        request_id="r1",
        model=MODEL,
        input_tokens=1000,
        cache_read_tokens=2000,
        cache_write_tokens={"5m": 4000, "1h": 500},
        output_tokens=300,
        reasoning_tokens=200,
        # Deliberately understated relative to the categories above: a
        # provider "total" is a check value, never billed on its own.
        provider_total_input_tokens=1,
        provider_total_output_tokens=1,
        source="provider_usage",
    )

    categories = category_costs_usd(usage, prices)
    assert categories == {
        "input": pytest.approx(1.0),
        "cache_read": pytest.approx(0.2),
        "cache_write:5m": pytest.approx(5.0),
        "cache_write:1h": pytest.approx(1.0),
        "output": pytest.approx(0.9),
        "reasoning": pytest.approx(0.6),
    }

    total = usage_cost_usd(usage, prices)
    assert total == pytest.approx(sum(v for v in categories.values()))

    # The misleading provider totals do not silently pass: they are flagged
    # as inconsistent, but they never change the disjoint category math.
    issues = validate_model_usage([usage])
    assert any(issue.code == "inconsistent_usage" for issue in issues)

    # An unrecognized cache-write class prices as unknown, not as 0, and
    # does not corrupt the categories that remain known.
    usage_unknown_class = usage.model_copy(update={"cache_write_tokens": {"unmapped-class": 100}})
    partial = category_costs_usd(usage_unknown_class, prices)
    assert partial["input"] == pytest.approx(1.0)
    assert partial["cache_write:unmapped-class"] is None
    assert usage_cost_usd(usage_unknown_class, prices) is None


# --------------------------------------------------------------------------- #
# Unknown usage never becomes zero
# --------------------------------------------------------------------------- #
def test_unknown_usage_never_becomes_zero():
    """Missing usage/prices stay unknown; genuine zeros stay distinct."""
    prices = PriceBook(
        rows={
            MODEL: CachePriceRow(
                input_usd_per_1k=1.0,
                output_usd_per_1k=2.0,
                effective_date="2026-09-01",
                provenance="vendor console",
            )
        }
    )

    silent = ModelUsage(attempt_id="a1", seat_id="s1", request_id="r1", model=MODEL, source="provider_usage")
    assert usage_cost_usd(silent, prices) is None
    issues = validate_model_usage([silent])
    assert any(issue.code == "unknown_usage" for issue in issues)

    # A genuinely reported zero is a real value, distinct from "unknown".
    zero_output = ModelUsage(
        attempt_id="a1",
        seat_id="s1",
        request_id="r2",
        model=MODEL,
        input_tokens=100,
        output_tokens=0,
        source="provider_usage",
    )
    assert usage_cost_usd(zero_output, prices) == pytest.approx(0.1)

    # Reported tokens against an unpriced model still cannot become a cost.
    unpriced = ModelUsage(
        attempt_id="a1",
        seat_id="s1",
        request_id="r3",
        model="unlisted-model",
        input_tokens=500,
        source="provider_usage",
    )
    assert usage_cost_usd(unpriced, prices) is None

    # Unknown propagates to the whole attempt: never a silent partial sum.
    attempt_with_unknown = AttemptRecord(
        attempt_id="a1",
        task_id="t1",
        arm="current",
        repetition=1,
        seat_id="s1",
        accepted=True,
        usage=[zero_output, silent],
    )
    assert attempt_cost_usd(attempt_with_unknown, prices) is None

    # No usage at all is a real, known zero -- different from "unknown".
    empty_attempt = AttemptRecord(
        attempt_id="a2", task_id="t1", arm="current", repetition=1, seat_id="s1", accepted=True
    )
    assert attempt_cost_usd(empty_attempt, prices) == 0.0


# --------------------------------------------------------------------------- #
# Actual-billed-cost precedence and duplicate/retry identifiers
# --------------------------------------------------------------------------- #
def test_actual_cost_precedence_and_duplicate_requests():
    """Actual billed cost wins; duplicate/retry identifiers are detected."""
    prices = PriceBook(
        rows={
            MODEL: CachePriceRow(
                input_usd_per_1k=1.0,
                output_usd_per_1k=2.0,
                effective_date="2026-09-01",
                provenance="vendor console",
            )
        }
    )

    priced_by_provider = ModelUsage(
        attempt_id="a1",
        seat_id="s1",
        request_id="r1",
        model=MODEL,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        actual_cost_usd=0.005,
        source="provider_usage",
    )
    # Category math on these token counts would be far larger; the actual
    # billed figure must win regardless.
    assert usage_cost_usd(priced_by_provider, prices) == pytest.approx(0.005)
    naive_category_total = sum(category_costs_usd(priced_by_provider, prices).values())
    assert naive_category_total != pytest.approx(0.005)

    # A failed request's retry is still real spend and must be charged.
    original = ModelUsage(
        attempt_id="a1",
        seat_id="s1",
        request_id="r2",
        model=MODEL,
        input_tokens=100,
        output_tokens=100,
        failed=True,
        source="provider_usage",
    )
    retry = ModelUsage(
        attempt_id="a1",
        seat_id="s1",
        request_id="r3",
        model=MODEL,
        input_tokens=100,
        output_tokens=100,
        is_retry=True,
        retry_of_request_id="r2",
        source="provider_usage",
    )
    attempt = AttemptRecord(
        attempt_id="a1",
        task_id="t1",
        arm="current",
        repetition=1,
        seat_id="s1",
        accepted=True,
        usage=[original, retry],
        retries=1,
    )
    expected = usage_cost_usd(original, prices) + usage_cost_usd(retry, prices)
    assert attempt_cost_usd(attempt, prices) == pytest.approx(expected)

    # A retry flag with nothing to link to is an invalid record.
    with pytest.raises(ValidationError):
        ModelUsage(
            attempt_id="a1",
            seat_id="s1",
            request_id="r4",
            model=MODEL,
            is_retry=True,
            source="provider_usage",
        )

    # A duplicate (attempt_id, seat_id, request_id) is a defect, not a
    # legitimate double charge or a silently ignored extra record.
    duplicate = ModelUsage(
        attempt_id="a1",
        seat_id="s1",
        request_id="r2",
        model=MODEL,
        input_tokens=50,
        output_tokens=50,
        source="provider_usage",
    )
    duplicate_keys = find_duplicate_usage_keys([original, duplicate])
    assert duplicate_keys == [("a1", "s1", "r2")]

    issues = validate_model_usage([original, duplicate], expected_request_ids={"r2", "r99"})
    codes = {(issue.code, issue.request_id) for issue in issues}
    assert ("duplicate_request_id", "r2") in codes
    assert ("missing_request_id", "r99") in codes
