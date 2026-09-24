"""Pydantic contracts for the FEAT-580 LSP pilot benchmark (spec §2 Evaluation).

Every model here is a data contract only: constructing or validating one
never starts a process, calls a provider SDK, or reads a live price. Two
rules from the spec drive every field:

* **Unknown is never zero.** A provider that does not report a quantity
  yields ``None``, which must propagate to an unknown cost rather than a
  silently flattering 0.
* **Every number carries provenance.** ``ModelUsage.source`` and
  ``CachePriceRow.provenance``/``effective_date`` make every accounted
  figure auditable back to where it came from.

The existing two-rate ``benchmarks.tool_optimizations.accounting`` models
(``UsageRecord``, ``PriceRow``, ``CostModel``) cannot represent cache
categories or actual billed cost, so this module defines a distinct,
cache-aware schema rather than silently reusing them (spec §6 Codebase
Contract).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = (
    "ARM_NAMES",
    "REPETITIONS",
    "TASK_COUNT",
    "ArmName",
    "AttemptRecord",
    "CachePriceRow",
    "GateDecision",
    "GateResult",
    "ModelUsage",
    "PilotManifest",
    "PilotReport",
    "PriceBook",
    "SeatSpec",
)

#: The five fixed evaluation arms (spec §2 Evaluation contract). This is
#: the canonical set membership; a manifest's ``counterbalanced_order``
#: may reorder presentation without changing this fixed set.
ARM_NAMES: tuple[str, ...] = (
    "current",
    "wiki_ast",
    "lsp_navigation",
    "lsp_diagnostics",
    "lsp_combined",
)

ArmName = Literal["current", "wiki_ast", "lsp_navigation", "lsp_diagnostics", "lsp_combined"]

#: Fixed matrix dimensions: 12 tasks x 3 repetitions x 5 arms = 180 planned
#: task attempts, before any explicitly recorded retry (spec §2).
TASK_COUNT = 12
REPETITIONS = 3

GateDecision = Literal["go", "no_go", "inconclusive"]


class SeatSpec(BaseModel):
    """One operator-configured CLI seat used to run a single arm.

    Attributes:
        arm: The arm this seat serves.
        argv: The literal argv used to launch the seat. Never shell
            interpolated; each token must be non-empty.
        timeout_s: The per-attempt timeout, in seconds, for this seat.
    """

    model_config = ConfigDict(extra="forbid")

    arm: ArmName
    argv: list[str] = Field(..., min_length=1)
    timeout_s: float = Field(..., gt=0)

    @model_validator(mode="after")
    def _validate_argv(self) -> "SeatSpec":
        if any(not token for token in self.argv):
            raise ValueError("seat argv entries must be non-empty")
        return self


class PilotManifest(BaseModel):
    """The pinned, auditable configuration of one pilot run (spec §3 M5).

    Validating a manifest never starts a process, spends money, or reads a
    live price — it only proves the run is well-formed before a runner may
    launch a single attempt.

    Attributes:
        pinned_commit: The exact repository commit the pilot measures.
        task_ids: The fixed set of task identifiers; exactly
            :data:`TASK_COUNT`, all unique.
        repetitions: Paired repetitions per task/arm; must equal
            :data:`REPETITIONS`.
        arms: The exact fixed five-arm set from :data:`ARM_NAMES`.
        seats: One :class:`SeatSpec` per arm, keyed by arm name.
        model: The pinned model identity under test.
        model_version: The pinned model version, when the provider exposes
            one distinct from ``model``.
        environment_id: The pinned, immutable dependency environment
            identity backing every attempt.
        price_provenance: Where the pilot's prices come from (console,
            contract, published rate card).
        cache_semantics: A human-readable description of how this run's
            provider(s) report cache read/write classes.
        counterbalanced_order: The recorded arm/task presentation order
            used to counterbalance sequencing effects.
        spending_ceiling_usd: The explicit total spending ceiling for the
            whole run.
        per_attempt_cost_reservation_usd: A positive per-attempt cost
            reservation the runner must consume before launching an
            attempt, so a single in-flight request cannot silently
            overspend past the ceiling.
    """

    model_config = ConfigDict(extra="forbid")

    pinned_commit: str = Field(..., min_length=1)
    task_ids: tuple[str, ...] = Field(...)
    repetitions: int = Field(default=REPETITIONS)
    arms: tuple[ArmName, ...] = Field(default=ARM_NAMES)
    seats: dict[ArmName, SeatSpec]
    model: str = Field(..., min_length=1)
    model_version: Optional[str] = None
    environment_id: str = Field(..., min_length=1)
    price_provenance: str = Field(..., min_length=1)
    cache_semantics: str = Field(..., min_length=1)
    counterbalanced_order: tuple[str, ...] = Field(default_factory=tuple)
    spending_ceiling_usd: float = Field(..., gt=0)
    per_attempt_cost_reservation_usd: float = Field(..., gt=0)

    @model_validator(mode="after")
    def _validate_matrix(self) -> "PilotManifest":
        if len(self.task_ids) != TASK_COUNT:
            raise ValueError(f"exactly {TASK_COUNT} task ids are required, got {len(self.task_ids)}")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task_ids must be unique")
        if self.repetitions != REPETITIONS:
            raise ValueError(f"exactly {REPETITIONS} repetitions are required, got {self.repetitions}")
        if set(self.arms) != set(ARM_NAMES) or len(self.arms) != len(ARM_NAMES):
            raise ValueError(f"exactly the five fixed arms are required: {sorted(ARM_NAMES)}")
        missing_seats = set(ARM_NAMES) - set(self.seats)
        if missing_seats:
            raise ValueError(f"missing seat argv for arms: {sorted(missing_seats)}")
        for arm, seat in self.seats.items():
            if seat.arm != arm:
                raise ValueError(f"seat keyed under {arm!r} declares arm {seat.arm!r}")
        if self.per_attempt_cost_reservation_usd > self.spending_ceiling_usd:
            raise ValueError(
                "per_attempt_cost_reservation_usd "
                f"({self.per_attempt_cost_reservation_usd}) exceeds the total "
                f"spending_ceiling_usd ({self.spending_ceiling_usd})"
            )
        return self

    @property
    def total_attempts(self) -> int:
        """Return the fixed planned attempt count, before recorded retries."""
        return len(self.task_ids) * self.repetitions * len(self.arms)


class ModelUsage(BaseModel):
    """One normalized provider usage record for a single model request.

    Uniqueness is on ``(attempt_id, seat_id, request_id)``. Every count may
    be ``None`` when the provider did not report it — never coerced to
    zero. ``actual_cost_usd``, when present, takes precedence over any
    category-based recomputation (spec §2 Evaluation contract).

    Attributes:
        attempt_id: The attempt this request belongs to.
        seat_id: The CLI seat that issued the request.
        request_id: The provider/seat request identifier.
        model: The model identity actually used to serve this request.
        model_version: The provider-reported model version, if distinct.
        input_tokens: Uncached input tokens, or ``None`` if unreported.
        cache_read_tokens: Tokens served from cache, or ``None``.
        cache_write_tokens: Cache-write tokens keyed by the provider's
            reported cache class (e.g. ``"5m"``, ``"1h"``); a class may map
            to ``None`` when the provider reports the class but not a
            count for it.
        output_tokens: Output tokens, or ``None`` if unreported.
        reasoning_tokens: Reasoning tokens billed as a separate,
            non-overlapping category, or ``None`` if not applicable/unreported.
        provider_total_input_tokens: The provider's own reported input
            total. A check value only — never an extra billable category.
        provider_total_output_tokens: The provider's own reported output
            total. A check value only — never an extra billable category.
        actual_cost_usd: The provider's actual billed cost for this
            request, when available. Takes precedence over category math.
        is_retry: Whether this request is an explicitly recorded retry.
        retry_of_request_id: The original request id this retries, required
            when ``is_retry`` is true.
        failed: Whether this request failed (its cost, if any, is still
            charged — a failure does not erase spend).
        source: Provenance label, e.g. ``"provider_usage"`` or
            ``"estimate:<method>"``.
    """

    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(..., min_length=1)
    seat_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    model_version: Optional[str] = None
    input_tokens: Optional[int] = Field(default=None, ge=0)
    cache_read_tokens: Optional[int] = Field(default=None, ge=0)
    cache_write_tokens: dict[str, Optional[int]] = Field(default_factory=dict)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    reasoning_tokens: Optional[int] = Field(default=None, ge=0)
    provider_total_input_tokens: Optional[int] = Field(default=None, ge=0)
    provider_total_output_tokens: Optional[int] = Field(default=None, ge=0)
    actual_cost_usd: Optional[float] = Field(default=None, ge=0)
    is_retry: bool = False
    retry_of_request_id: Optional[str] = None
    failed: bool = False
    source: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_usage(self) -> "ModelUsage":
        for cache_class, tokens in self.cache_write_tokens.items():
            if not cache_class:
                raise ValueError("cache_write_tokens keys must be non-empty class labels")
            if tokens is not None and tokens < 0:
                raise ValueError(f"cache_write_tokens[{cache_class!r}] must be >= 0")
        if self.is_retry and not self.retry_of_request_id:
            raise ValueError("is_retry requires retry_of_request_id")
        return self


class CachePriceRow(BaseModel):
    """A per-model, cache-aware price row with full provenance.

    Categories mirror :class:`ModelUsage`'s disjoint billing categories.
    Any absent rate means "unknown", never a stand-in zero.

    Attributes:
        currency: The billing currency for every rate in this row.
        input_usd_per_1k: Rate for uncached input tokens.
        cache_read_usd_per_1k: Rate for cache-read tokens, or ``None`` if
            this model/provider's cache-read price is unknown.
        cache_write_usd_per_1k: Rates per reported cache-write class.
        output_usd_per_1k: Rate for output tokens.
        reasoning_usd_per_1k: Rate for separately billed reasoning tokens,
            or ``None`` if unknown/not applicable.
        effective_date: The date this price row was read/became effective.
        provenance: Where the figure came from (console, contract, URL).
    """

    model_config = ConfigDict(extra="forbid")

    currency: str = Field(default="USD", min_length=1)
    input_usd_per_1k: float = Field(..., ge=0)
    cache_read_usd_per_1k: Optional[float] = Field(default=None, ge=0)
    cache_write_usd_per_1k: dict[str, float] = Field(default_factory=dict)
    output_usd_per_1k: float = Field(..., ge=0)
    reasoning_usd_per_1k: Optional[float] = Field(default=None, ge=0)
    effective_date: str = Field(..., min_length=1)
    provenance: str = Field(..., min_length=1)


class PriceBook(BaseModel):
    """The configured cache-aware price table.

    Ships empty on purpose, same discipline as the FEAT-543
    ``benchmarks.tool_optimizations.accounting.CostModel``: an invented
    price is worse than reporting cost as unknown.

    Attributes:
        rows: Price rows keyed by model identity.
    """

    model_config = ConfigDict(extra="forbid")

    rows: dict[str, CachePriceRow] = Field(default_factory=dict)


class AttemptRecord(BaseModel):
    """One executed (or attempted) task/arm/repetition combination.

    Joins acceptance/review results, raw trace references, normalized
    usage, tool/LSP counters, cold/warm metrics and failure reasons by
    attempt ID (spec §2/§3 M5).

    Attributes:
        attempt_id: The unique identifier for this attempt.
        task_id: The fixed task identifier this attempt targets.
        arm: The arm this attempt was run under.
        repetition: The 1-based repetition index (1..:data:`REPETITIONS`).
        seat_id: The CLI seat that executed this attempt.
        accepted: Whether the attempt's output passed acceptance checks.
        failure_reason: A short explicit reason when the attempt did not
            complete or was not accepted.
        usage: Every :class:`ModelUsage` record produced during this
            attempt, including failed and retried requests.
        raw_trace_refs: Pointers to the raw seat log(s) backing this
            attempt's normalized usage.
        tool_calls: Count of tool invocations made during the attempt.
        lsp_operations: Count of LSP tool invocations made during the
            attempt (0 for arms that do not expose LSP tools).
        cold_start: Whether this attempt paid a cold LSP/session startup
            cost, recorded separately from warm subsequent calls.
        elapsed_ms: Wall-clock duration of the attempt, if recorded.
        correction_cycles: Reviewer/self-correction cycles observed.
        retries: Count of explicitly recorded retries for this attempt.
    """

    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(..., min_length=1)
    task_id: str = Field(..., min_length=1)
    arm: ArmName
    repetition: int = Field(..., ge=1, le=REPETITIONS)
    seat_id: str = Field(..., min_length=1)
    accepted: bool
    failure_reason: Optional[str] = None
    usage: list[ModelUsage] = Field(default_factory=list)
    raw_trace_refs: list[str] = Field(default_factory=list)
    tool_calls: int = Field(default=0, ge=0)
    lsp_operations: int = Field(default=0, ge=0)
    cold_start: bool = False
    elapsed_ms: Optional[int] = Field(default=None, ge=0)
    correction_cycles: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_usage_scope(self) -> "AttemptRecord":
        for record in self.usage:
            if record.attempt_id != self.attempt_id:
                raise ValueError(
                    f"usage record attempt_id {record.attempt_id!r} does not match attempt {self.attempt_id!r}"
                )
        return self


class PilotReport(BaseModel):
    """A deterministic pilot summary artifact (spec §2 Evaluation contract).

    ``synthetic`` must stay ``True`` for any offline/fixture-produced
    report; only a report built from a complete, audited live run can
    satisfy the adoption gate (spec §5 Acceptance Criteria).

    Attributes:
        manifest: The manifest this report was produced from.
        attempts: Every attempted (successful or not) :class:`AttemptRecord`.
        coverage_manifest: A mapping describing expected-vs-observed trace
            coverage, so missing traces are never silently dropped.
        generated_at: When this report was produced (UTC).
        synthetic: Whether this report was produced offline/from fixtures
            rather than a live, audited run.
    """

    model_config = ConfigDict(extra="forbid")

    manifest: PilotManifest
    attempts: list[AttemptRecord] = Field(default_factory=list)
    coverage_manifest: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    synthetic: bool = True


class GateResult(BaseModel):
    """The FEAT-580 adoption-gate disposition contract.

    This model carries only the decision and its supporting evidence; the
    decision procedure itself (``evaluate_gate``) is implemented by the
    report module, not this one.

    Attributes:
        decision: ``"go"``, ``"no_go"``, or ``"inconclusive"``.
        cost_reduction_pct: Observed model-cost reduction of the combined
            LSP arm against ``wiki_ast``, when computable.
        acceptance_regressed: Whether an acceptance-rate regression was
            observed, when computable.
        correctness_regressed: Whether a correctness regression was
            observed, when computable.
        median_wall_time_regression_pct: Observed median wall-time
            regression, when computable.
        reasons: Human-readable reasons supporting the decision, including
            why a metric is inconclusive.
        per_task_regressions: Task-level regressions to report alongside
            aggregates, per spec §2's "report task-level regressions" rule.
    """

    model_config = ConfigDict(extra="forbid")

    decision: GateDecision
    cost_reduction_pct: Optional[float] = None
    acceptance_regressed: Optional[bool] = None
    correctness_regressed: Optional[bool] = None
    median_wall_time_regression_pct: Optional[float] = None
    reasons: list[str] = Field(default_factory=list)
    per_task_regressions: list[str] = Field(default_factory=list)
