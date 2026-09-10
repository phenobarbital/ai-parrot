"""Token, latency and cost accounting for the FEAT-543 benchmarks.

Two rules drive the design:

* **Unknown is never zero.** A provider that reports no usage yields
  ``tokens=None``, which propagates to ``cost_usd=None``. Coercing a missing
  measurement to 0 would silently flatter the optimized side.
* **Every number carries its provenance.** Provider-reported counts are
  labelled ``provider_usage``; anything the harness estimates is labelled
  ``estimate:<method>`` so a reader can tell measurement from arithmetic.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "PRICES_PATH",
    "CostModel",
    "PriceRow",
    "Stage",
    "UsageRecord",
    "cost_usd",
    "estimate_tokens",
    "percentile",
)

PRICES_PATH = Path(__file__).with_name("prices.yaml")

#: Accounting stages. Keeping planning/review/repair separate from the raw
#: model calls is what prevents "savings" that merely moved work elsewhere.
Stage = Literal[
    "tool_schema_overhead",
    "planning_packet",
    "primary_input",
    "primary_output",
    "delegate_input",
    "delegate_output",
    "review",
    "repair",
]

#: Stages attributable to the delegate rather than the primary model.
DELEGATE_STAGES = frozenset({"delegate_input", "delegate_output", "repair"})

#: A crude but honest character-based estimator, always labelled as such.
ESTIMATE_METHOD = "estimate:chars_div_4"


def estimate_tokens(text: str) -> int:
    """Estimate a token count from raw text.

    Args:
        text: The text to estimate.

    Returns:
        An approximate token count (``len // 4``). Always report this with
        the :data:`ESTIMATE_METHOD` source label — it is not a measurement.
    """
    return len(text) // 4


class UsageRecord(BaseModel):
    """One accounted quantity in a benchmark run.

    Attributes:
        stage: Which part of the workflow this belongs to.
        tokens: The token count, or None when genuinely unknown.
        source: ``provider_usage`` or ``estimate:<method>``.
        elapsed_ms: Wall-clock time attributable to this stage.
    """

    model_config = ConfigDict(extra="forbid")

    stage: Stage
    tokens: Optional[int] = None
    source: str
    elapsed_ms: int = 0


class PriceRow(BaseModel):
    """A per-model price, with the provenance that makes it auditable.

    Attributes:
        input_usd_per_1k: USD per 1,000 input tokens.
        output_usd_per_1k: USD per 1,000 output tokens.
        provenance: Where the figure came from (URL, contract, console).
        as_of: The date the price was read.
    """

    model_config = ConfigDict(extra="forbid")

    input_usd_per_1k: float = Field(..., ge=0)
    output_usd_per_1k: float = Field(..., ge=0)
    provenance: str = Field(..., min_length=1)
    as_of: str = Field(..., min_length=1)


class CostModel(BaseModel):
    """The configured price table.

    Ships empty on purpose: an invented price is worse than no price, so
    cost is reported as ``unknown`` until an operator fills this in.
    """

    model_config = ConfigDict(extra="forbid")

    rows: dict[str, PriceRow] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "CostModel":
        """Load the price table, tolerating an absent or empty file.

        Args:
            path: The YAML file; defaults to the shipped ``prices.yaml``.

        Returns:
            The parsed cost model, possibly with no rows.
        """
        target = path or PRICES_PATH
        if not target.is_file():
            return cls()
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        rows = data.get("models") or {}
        return cls(rows={name: PriceRow.model_validate(row) for name, row in rows.items()})


def cost_usd(records: list[UsageRecord], model: str, prices: CostModel) -> Optional[float]:
    """Compute the USD cost of a set of usage records.

    Args:
        records: The accounted usage.
        model: The model identity to price.
        prices: The configured price table.

    Returns:
        The cost, or None when the price is unknown or any input token count
        is unknown. Never returns 0 to stand in for "we do not know".
    """
    row = prices.rows.get(model)
    if row is None:
        return None
    if any(record.tokens is None for record in records):
        return None
    total = 0.0
    for record in records:
        rate = row.output_usd_per_1k if record.stage.endswith("_output") else row.input_usd_per_1k
        total += (record.tokens or 0) / 1000.0 * rate
    return round(total, 6)


def percentile(values: list[float], fraction: float) -> Optional[float]:
    """Return a percentile using nearest-rank, safe for tiny samples.

    Args:
        values: The observations.
        fraction: The percentile as a fraction (e.g. 0.95).

    Returns:
        The percentile value, or None for an empty sample.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * len(ordered) + 0.5)) - 1))
    return ordered[index]


def median(values: list[float]) -> Optional[float]:
    """Return the median, or None for an empty sample.

    Args:
        values: The observations.

    Returns:
        The median, or None.
    """
    return statistics.median(values) if values else None


def totals_by_kind(records: list[UsageRecord]) -> dict[str, Any]:
    """Split token totals into primary, delegate and overall.

    Fewer primary tokens is not fewer total tokens — reporting both is the
    entire point of this function.

    Args:
        records: The accounted usage.

    Returns:
        A mapping with ``primary_tokens``, ``delegate_tokens`` and
        ``total_tokens``; a member is None when any contributing record's
        count is unknown.
    """

    def _sum(subset: list[UsageRecord]) -> Optional[int]:
        if not subset:
            return 0
        if any(record.tokens is None for record in subset):
            return None
        return sum(record.tokens or 0 for record in subset)

    delegate = [record for record in records if record.stage in DELEGATE_STAGES]
    primary = [record for record in records if record.stage not in DELEGATE_STAGES]
    primary_total = _sum(primary)
    delegate_total = _sum(delegate)
    overall = None if primary_total is None or delegate_total is None else primary_total + delegate_total
    return {"primary_tokens": primary_total, "delegate_tokens": delegate_total, "total_tokens": overall}
