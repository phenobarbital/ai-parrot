"""Cache-aware usage accounting for the FEAT-580 LSP pilot benchmark.

Three rules drive this module, sharpening the FEAT-543 discipline in
``benchmarks.tool_optimizations.accounting`` for cache-aware provider
billing (spec §2 Evaluation contract):

* **Unknown is never zero.** A missing token count, a missing price row,
  or a record with nothing reported at all yields ``None`` cost — never a
  silent 0 that could flatter one arm over another.
* **Categories are disjoint.** Uncached input, cache read, cache write (by
  reported class), output and separately billed reasoning are each priced
  once. Provider-reported "total" input/output figures are consistency
  checks only, never an extra billable category — so provider totals are
  never double-counted against the categories above.
* **Actual billed cost wins.** When a provider reports the real charge for
  a request, that figure is used as-is instead of a category
  recomputation that could diverge from what was actually billed.

This is a deliberately distinct schema from the two-rate
``benchmarks.tool_optimizations.accounting`` (``UsageRecord``/``PriceRow``/
``CostModel``): that model has no cache categories and cannot express
actual billed cost, so it is not reused unchanged here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from benchmarks.sdd_lsp.models import AttemptRecord, ModelUsage, PriceBook

__all__ = (
    "UsageIssue",
    "UsageIssueCode",
    "attempt_cost_usd",
    "category_costs_usd",
    "find_duplicate_usage_keys",
    "find_missing_request_ids",
    "usage_cost_usd",
    "validate_model_usage",
)

UsageIssueCode = Literal[
    "duplicate_request_id",
    "missing_request_id",
    "unknown_usage",
    "inconsistent_usage",
]


class UsageIssue(BaseModel):
    """One detected accounting problem, always attributable to a request.

    Attributes:
        code: The kind of problem detected.
        attempt_id: The attempt the issue was found in, or ``"<unknown>"``
            when the issue spans attempts (e.g. a globally missing id).
        seat_id: The seat the issue was found on, when known.
        request_id: The request the issue concerns, when known.
        detail: A short, human-readable explanation.
    """

    model_config = ConfigDict(extra="forbid")

    code: UsageIssueCode
    attempt_id: str
    seat_id: Optional[str] = None
    request_id: Optional[str] = None
    detail: str


def find_duplicate_usage_keys(records: list[ModelUsage]) -> list[tuple[str, str, str]]:
    """Return the ``(attempt_id, seat_id, request_id)`` keys seen more than once.

    Args:
        records: The normalized usage records to inspect.

    Returns:
        Each duplicated identity key, reported once regardless of how many
        extra copies exist.
    """
    seen: dict[tuple[str, str, str], int] = {}
    for record in records:
        key = (record.attempt_id, record.seat_id, record.request_id)
        seen[key] = seen.get(key, 0) + 1
    return [key for key, count in seen.items() if count > 1]


def find_missing_request_ids(records: list[ModelUsage], expected_request_ids: set[str]) -> set[str]:
    """Return expected request ids that have no matching usage record.

    Args:
        records: The normalized usage records actually collected.
        expected_request_ids: The request ids the trace/manifest expected
            to observe.

    Returns:
        The subset of ``expected_request_ids`` never observed in ``records``.
    """
    observed = {record.request_id for record in records}
    return expected_request_ids - observed


def _components_exceed_total(total: Optional[int], *parts: Optional[int]) -> bool:
    """Return whether known components already exceed a reported total.

    Args:
        total: The provider-reported total, or ``None`` if unreported.
        parts: The known disjoint components contributing to that total.

    Returns:
        ``True`` only when a total was reported and the sum of the parts
        that are actually known already exceeds it. A missing total or an
        entirely unknown set of parts is never flagged.
    """
    if total is None:
        return False
    known = [part for part in parts if part is not None]
    if not known:
        return False
    return sum(known) > total


def validate_model_usage(
    records: list[ModelUsage], expected_request_ids: Optional[set[str]] = None
) -> list[UsageIssue]:
    """Detect duplicate/missing identifiers and unknown or inconsistent usage.

    Args:
        records: The normalized usage records for one or more attempts.
        expected_request_ids: When provided, request ids the trace/manifest
            expected to observe; any absent id is reported as
            ``missing_request_id``.

    Returns:
        Every detected issue. An empty list means the usage is internally
        consistent — it does not by itself mean every record's cost is
        known.
    """
    issues: list[UsageIssue] = []

    for attempt_id, seat_id, request_id in find_duplicate_usage_keys(records):
        issues.append(
            UsageIssue(
                code="duplicate_request_id",
                attempt_id=attempt_id,
                seat_id=seat_id,
                request_id=request_id,
                detail="request_id repeated for the same attempt/seat",
            )
        )

    if expected_request_ids:
        for missing in sorted(find_missing_request_ids(records, expected_request_ids)):
            issues.append(
                UsageIssue(
                    code="missing_request_id",
                    attempt_id="<unknown>",
                    request_id=missing,
                    detail="expected request_id has no usage record",
                )
            )

    for record in records:
        reported_categories = _reported_categories(record)
        if not record.failed and record.actual_cost_usd is None and not reported_categories:
            issues.append(
                UsageIssue(
                    code="unknown_usage",
                    attempt_id=record.attempt_id,
                    seat_id=record.seat_id,
                    request_id=record.request_id,
                    detail="no token counts and no actual cost reported",
                )
            )
        if _components_exceed_total(record.provider_total_input_tokens, record.input_tokens, record.cache_read_tokens):
            issues.append(
                UsageIssue(
                    code="inconsistent_usage",
                    attempt_id=record.attempt_id,
                    seat_id=record.seat_id,
                    request_id=record.request_id,
                    detail="provider_total_input_tokens is smaller than uncached input plus cache read",
                )
            )
        if _components_exceed_total(record.provider_total_output_tokens, record.output_tokens):
            issues.append(
                UsageIssue(
                    code="inconsistent_usage",
                    attempt_id=record.attempt_id,
                    seat_id=record.seat_id,
                    request_id=record.request_id,
                    detail="provider_total_output_tokens is smaller than reported output tokens",
                )
            )

    return issues


def _reported_categories(usage: ModelUsage) -> dict[str, Optional[int]]:
    """Return every disjoint billing category the record actually reports.

    A category is "reported" when its token count is not ``None`` (an
    explicit ``0`` is a real report, distinct from an absent one).

    Args:
        usage: The normalized usage record.

    Returns:
        A mapping from category name to its (possibly ``0``) token count,
        containing only categories the record actually reported.
    """
    categories: dict[str, Optional[int]] = {}
    if usage.input_tokens is not None:
        categories["input"] = usage.input_tokens
    if usage.cache_read_tokens is not None:
        categories["cache_read"] = usage.cache_read_tokens
    for cache_class, tokens in usage.cache_write_tokens.items():
        if tokens is not None:
            categories[f"cache_write:{cache_class}"] = tokens
    if usage.output_tokens is not None:
        categories["output"] = usage.output_tokens
    if usage.reasoning_tokens is not None:
        categories["reasoning"] = usage.reasoning_tokens
    return categories


def category_costs_usd(usage: ModelUsage, prices: PriceBook) -> dict[str, Optional[float]]:
    """Price every disjoint billing category a usage record reports.

    Provider-reported "total" input/output figures are never priced here —
    they are consistency checks only (see :func:`validate_model_usage`),
    never an extra billable category, so they can never be double-counted
    against the categories below.

    Args:
        usage: The normalized usage record.
        prices: The configured cache-aware price table.

    Returns:
        A mapping from category name (``"input"``, ``"cache_read"``,
        ``"cache_write:<class>"``, ``"output"``, ``"reasoning"``) to its USD
        cost, for every category the record reported. A reported category
        priced against a missing model row or a missing rate is ``None``
        rather than ``0``.
    """
    row = prices.rows.get(usage.model)

    def _price(tokens: int, rate: Optional[float]) -> Optional[float]:
        if row is None or rate is None:
            return None
        return float(Decimal(tokens) / Decimal(1000) * Decimal(str(rate)))

    reported = _reported_categories(usage)
    costs: dict[str, Optional[float]] = {}
    for category, tokens in reported.items():
        if category == "input":
            rate = row.input_usd_per_1k if row else None
        elif category == "cache_read":
            rate = row.cache_read_usd_per_1k if row else None
        elif category == "output":
            rate = row.output_usd_per_1k if row else None
        elif category == "reasoning":
            rate = row.reasoning_usd_per_1k if row else None
        elif category.startswith("cache_write:"):
            cache_class = category.split(":", 1)[1]
            rate = row.cache_write_usd_per_1k.get(cache_class) if row else None
        else:  # pragma: no cover - defensive, _reported_categories is exhaustive
            rate = None
        costs[category] = _price(tokens, rate)
    return costs


def usage_cost_usd(usage: ModelUsage, prices: PriceBook) -> Optional[float]:
    """Compute one usage record's USD cost, actual-billed-cost first.

    Args:
        usage: The normalized usage record.
        prices: The configured cache-aware price table.

    Returns:
        ``usage.actual_cost_usd`` when the provider reported it (the
        precedence rule); otherwise the sum of every disjoint category the
        record reports. Returns ``None`` — never ``0`` — when the record
        reports no category at all, or when any reported category cannot
        be priced.
    """
    if usage.actual_cost_usd is not None:
        return usage.actual_cost_usd

    categories = category_costs_usd(usage, prices)
    if not categories:
        return None
    if any(cost is None for cost in categories.values()):
        return None
    total = sum(Decimal(str(cost)) for cost in categories.values())
    return float(total)


def attempt_cost_usd(attempt: AttemptRecord, prices: PriceBook) -> Optional[float]:
    """Sum one attempt's total USD cost, charging failed attempts and retries.

    Every usage record attached to the attempt is charged — including
    failed and explicitly retried requests — because a retry or a failure
    is still real spend, not a reason to discount it.

    Args:
        attempt: The attempt whose usage should be totaled.
        prices: The configured cache-aware price table.

    Returns:
        The summed cost, or ``None`` if any contributing usage record's
        cost is unknown. An attempt with no usage records costs ``0.0``.
    """
    if not attempt.usage:
        return 0.0
    costs = [usage_cost_usd(record, prices) for record in attempt.usage]
    if any(cost is None for cost in costs):
        return None
    return float(sum(Decimal(str(cost)) for cost in costs))
