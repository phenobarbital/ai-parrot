"""Unit tests for the shared generation budget primitive (FEAT-581, M6, TASK-3538).

Covers success, boundary/invalid input, exhaustion (no further reservation
or attempt after exhaustion) and concurrency for
``parrot.clients.google.budget.GenerationBudget`` /
``GenerationBudgetExceeded``. No credentials, network or provider SDK calls
are used — every scenario drives the primitive directly with synthetic
byte/token/call inputs.

``budget.py`` itself has no dependency on the ``google-genai`` SDK or on any
other ``parrot.*`` module (stdlib-only: ``asyncio``/``logging``/``time``).
It is loaded here by file path with ``importlib`` — the same
load-a-module-by-path technique the repo's own root ``conftest.py`` uses
for ``tests/mock_fspath_guard.py`` — instead of ``from parrot.clients.google
import budget``, because importing that dotted path would first execute the
*package's* ``__init__.py`` (``parrot/clients/google/__init__.py``), which
eagerly imports sibling modules (``live.py``) requiring the optional
``google-genai`` SDK. That SDK is on this repo's own
``OPTIONAL_SUBMODULES`` allowlist precisely because it is not installed in
every environment — a normal package import would make this test suite
skip instead of genuinely exercising the budget primitive under test.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib

import pytest

_BUDGET_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "src" / "parrot" / "clients" / "google" / "budget.py"
)


def _load_budget_module():
    """Load ``budget.py`` directly by path, bypassing the ``parrot.clients.google`` package."""
    spec = importlib.util.spec_from_file_location("_generation_budget_under_test", _BUDGET_MODULE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load the generation budget module from {_BUDGET_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_budget_module = _load_budget_module()
GenerationBudget = _budget_module.GenerationBudget
GenerationBudgetExceeded = _budget_module.GenerationBudgetExceeded


def _make_budget(
    *,
    max_calls: int = 4,
    max_output_tokens: int = 512,
    max_request_bytes: int = 16384,
    timeout_s: float = 60,
) -> GenerationBudget:
    return GenerationBudget(
        max_calls=max_calls,
        max_output_tokens=max_output_tokens,
        max_request_bytes=max_request_bytes,
        timeout_s=timeout_s,
    )


class TestConstruction:
    """Construction succeeds with the spec's live-budget ceilings and rejects invalid ones."""

    def test_construct_with_spec_defaults(self) -> None:
        budget = _make_budget()
        assert budget.max_calls == 4
        assert budget.max_output_tokens == 512
        assert budget.max_request_bytes == 16384
        assert budget.timeout_s == 60
        assert budget.calls_used == 0
        assert budget.bytes_used == 0
        assert budget.usage_tokens_used == 0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_calls": 0},
            {"max_calls": -1},
            {"max_output_tokens": 0},
            {"max_request_bytes": 0},
            {"timeout_s": 0},
            {"timeout_s": -5},
            {"timeout_s": float("inf")},
        ],
    )
    def test_construct_rejects_non_positive_or_infinite_ceilings(self, kwargs: dict) -> None:
        base = {
            "max_calls": 4,
            "max_output_tokens": 512,
            "max_request_bytes": 16384,
            "timeout_s": 60,
        }
        base.update(kwargs)
        with pytest.raises(ValueError):
            GenerationBudget(**base)


class TestReserveSuccess:
    """Successful reservations increment counters atomically."""

    @pytest.mark.asyncio
    async def test_single_reservation_increments_counters(self) -> None:
        budget = _make_budget(max_calls=4)
        await budget.reserve(request_bytes=1000, output_tokens=100)
        assert budget.calls_used == 1
        assert budget.bytes_used == 1000

    @pytest.mark.asyncio
    async def test_sequential_reservations_accumulate(self) -> None:
        budget = _make_budget(max_calls=4)
        await budget.reserve(request_bytes=1000, output_tokens=100)
        await budget.reserve(request_bytes=2000, output_tokens=200)
        assert budget.calls_used == 2
        assert budget.bytes_used == 3000

    @pytest.mark.asyncio
    async def test_reservation_at_exact_ceilings_succeeds(self) -> None:
        budget = _make_budget(max_request_bytes=16384, max_output_tokens=512)
        await budget.reserve(request_bytes=16384, output_tokens=512)
        assert budget.calls_used == 1
        assert budget.bytes_used == 16384


class TestReserveInvalidInput:
    """Negative inputs are rejected before any lock/counter interaction."""

    @pytest.mark.asyncio
    async def test_negative_request_bytes_raises_value_error(self) -> None:
        budget = _make_budget()
        with pytest.raises(ValueError):
            await budget.reserve(request_bytes=-1, output_tokens=10)
        assert budget.calls_used == 0

    @pytest.mark.asyncio
    async def test_negative_output_tokens_raises_value_error(self) -> None:
        budget = _make_budget()
        with pytest.raises(ValueError):
            await budget.reserve(request_bytes=10, output_tokens=-1)
        assert budget.calls_used == 0


class TestReserveExhaustion:
    """Each ceiling dimension is enforced, and exhaustion permanently blocks new attempts."""

    @pytest.mark.asyncio
    async def test_max_calls_exhaustion_raises_and_retains_counters(self) -> None:
        budget = _make_budget(max_calls=2)
        await budget.reserve(request_bytes=100, output_tokens=10)
        await budget.reserve(request_bytes=200, output_tokens=20)
        assert budget.calls_used == 2

        with pytest.raises(GenerationBudgetExceeded) as excinfo:
            await budget.reserve(request_bytes=1, output_tokens=1)
        assert excinfo.value.reason_code == "max_calls"

        # Exhaustion cannot reserve or issue another attempt: counters from
        # the prior successful reservations are retained, not reset, and a
        # second attempt at exhaustion still fails identically.
        assert budget.calls_used == 2
        assert budget.bytes_used == 300
        with pytest.raises(GenerationBudgetExceeded):
            await budget.reserve(request_bytes=1, output_tokens=1)
        assert budget.calls_used == 2

    @pytest.mark.asyncio
    async def test_request_bytes_ceiling_raises_without_consuming_a_call(self) -> None:
        budget = _make_budget(max_calls=4, max_request_bytes=100)
        with pytest.raises(GenerationBudgetExceeded) as excinfo:
            await budget.reserve(request_bytes=101, output_tokens=10)
        assert excinfo.value.reason_code == "request_bytes"
        # No attempt was issued: the call counter must not move.
        assert budget.calls_used == 0
        assert budget.bytes_used == 0

    @pytest.mark.asyncio
    async def test_output_tokens_ceiling_raises_without_consuming_a_call(self) -> None:
        budget = _make_budget(max_calls=4, max_output_tokens=50)
        with pytest.raises(GenerationBudgetExceeded) as excinfo:
            await budget.reserve(request_bytes=10, output_tokens=51)
        assert excinfo.value.reason_code == "output_tokens"
        assert budget.calls_used == 0

    @pytest.mark.asyncio
    async def test_deadline_exceeded_raises_and_blocks_further_reservation(self) -> None:
        budget = _make_budget(max_calls=4, timeout_s=0.05)
        await budget.reserve(request_bytes=10, output_tokens=1)
        await asyncio.sleep(0.1)

        with pytest.raises(GenerationBudgetExceeded) as excinfo:
            await budget.reserve(request_bytes=10, output_tokens=1)
        assert excinfo.value.reason_code == "deadline"
        # The earlier successful reservation's counters remain visible.
        assert budget.calls_used == 1

        # Exhaustion via deadline is permanent for this instance too.
        with pytest.raises(GenerationBudgetExceeded):
            await budget.reserve(request_bytes=10, output_tokens=1)

    @pytest.mark.asyncio
    async def test_generation_budget_exceeded_is_a_plain_exception_not_e2e_error(self) -> None:
        # Frozen contract: this type must not depend on ai-parrot-server's
        # E2EBudgetError, since ai-parrot-client-google does not depend on
        # ai-parrot-server (TASK-3519 research finding).
        budget = _make_budget(max_calls=1)
        await budget.reserve(request_bytes=1, output_tokens=1)
        with pytest.raises(Exception) as excinfo:
            await budget.reserve(request_bytes=1, output_tokens=1)
        assert type(excinfo.value) is GenerationBudgetExceeded
        assert isinstance(excinfo.value, Exception)


class TestReserveConcurrency:
    """One shared instance enforces its ceiling across concurrent callers atomically."""

    @pytest.mark.asyncio
    async def test_concurrent_reservations_never_exceed_max_calls(self) -> None:
        budget = _make_budget(max_calls=4)

        async def _attempt() -> bool:
            try:
                await budget.reserve(request_bytes=10, output_tokens=1)
                return True
            except GenerationBudgetExceeded:
                return False

        results = await asyncio.gather(*[_attempt() for _ in range(20)])

        assert sum(results) == 4
        assert budget.calls_used == 4
        assert budget.bytes_used == 40

    @pytest.mark.asyncio
    async def test_shared_instance_enforces_one_counter_across_simulated_scenarios(self) -> None:
        # "Support one shared run counter across scenarios/clients" — a
        # single GenerationBudget instance shared by several simulated
        # scenario/client callers must see one combined ceiling, not a
        # fresh allowance per caller.
        shared_budget = _make_budget(max_calls=3)

        async def _scenario(name: str) -> None:
            await shared_budget.reserve(request_bytes=50, output_tokens=5)

        await asyncio.gather(_scenario("scenario-a"), _scenario("scenario-b"), _scenario("scenario-c"))
        assert shared_budget.calls_used == 3

        with pytest.raises(GenerationBudgetExceeded):
            await _scenario("scenario-d-over-shared-limit")
        assert shared_budget.calls_used == 3


class TestRecordUsageTokens:
    """Actual provider-reported token usage is tracked separately from byte counts."""

    @pytest.mark.asyncio
    async def test_record_usage_tokens_accumulates(self) -> None:
        budget = _make_budget()
        await budget.record_usage_tokens(123)
        await budget.record_usage_tokens(45)
        assert budget.usage_tokens_used == 168
        # Never inferred from bytes_used, which tracks reserved request bytes only.
        assert budget.bytes_used == 0

    @pytest.mark.asyncio
    async def test_record_usage_tokens_rejects_negative(self) -> None:
        budget = _make_budget()
        with pytest.raises(ValueError):
            await budget.record_usage_tokens(-1)
        assert budget.usage_tokens_used == 0

    @pytest.mark.asyncio
    async def test_record_usage_tokens_independent_of_reserve_failures(self) -> None:
        budget = _make_budget(max_calls=1)
        await budget.reserve(request_bytes=10, output_tokens=1)
        await budget.record_usage_tokens(50)
        with pytest.raises(GenerationBudgetExceeded):
            await budget.reserve(request_bytes=10, output_tokens=1)
        # Usage-token bookkeeping is unaffected by a subsequent reservation failure.
        assert budget.usage_tokens_used == 50
