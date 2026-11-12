"""Accounting contracts (FEAT-713 spec §2). Standard library and pydantic only."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AmountConvention = Literal["debit_positive", "credit_positive", "debit_credit_columns", "natural_balance"]
Nature = Literal["debit", "credit"]
AccountingGrain = Literal["day", "week", "month", "quarter", "year"]
Cumulative = Literal["mtd", "qtd", "ytd"]
RESERVED_METRIC_NAMES = frozenset({"__validate__"})


class JournalSource(BaseModel, frozen=True):
    """Where postings live: a database table XOR a named frame.

    Attributes:
        table: ``schema.table`` of the journal; mutually exclusive with ``dataframe``.
        dataframe: Name of a frame resolved by the frame provider.
        connection: ConnectionResolver name; required with ``table``.
        driver: DatabaseQueryToolkit driver name; required with ``table``.
    """

    table: str | None = None
    dataframe: str | None = None
    connection: str | None = None
    driver: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "JournalSource":
        """Require exactly one of table/dataframe; a table needs connection and driver."""
        if (self.table is None) == (self.dataframe is None):
            raise ValueError("journal source needs exactly one of 'table' or 'dataframe'")
        if self.table is not None and (not self.connection or not self.driver):
            raise ValueError("journal source 'table' requires both 'connection' and 'driver'")
        return self


class NatureSpec(BaseModel, frozen=True):
    """How account natures are resolved: an account-master column XOR an explicit mapping."""

    from_column: str | None = None
    accounts: dict[str, Nature] | None = None

    @model_validator(mode="after")
    def _one_origin(self) -> "NatureSpec":
        """Require exactly one of from_column / accounts."""
        if (self.from_column is None) == (self.accounts is None):
            raise ValueError("nature needs exactly one of 'from_column' or 'accounts'")
        return self


class ChartOfAccounts(BaseModel, frozen=True):
    """Journal layout: source, key columns, sign convention and dimensions."""

    source: JournalSource
    account_key: str
    posting_date: str
    amount_convention: AmountConvention
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    nature: NatureSpec | None = None
    dimensions: tuple[str, ...] = ()
    allow_float: bool = False

    @model_validator(mode="after")
    def _convention_columns(self) -> "ChartOfAccounts":
        """Enforce the columns and nature rule each amount convention needs (spec §2 sign table)."""
        if self.amount_convention == "debit_credit_columns":
            if not self.debit or not self.credit:
                raise ValueError("amount_convention 'debit_credit_columns' requires both 'debit' and 'credit'")
            if self.amount is not None:
                raise ValueError("amount_convention 'debit_credit_columns' does not take 'amount'")
        elif not self.amount:
            raise ValueError(f"amount_convention {self.amount_convention!r} requires 'amount'")
        if self.amount_convention != "natural_balance" and self.nature is None:
            raise ValueError(f"amount_convention {self.amount_convention!r} requires 'nature'")
        return self


class Selector(BaseModel, frozen=True):
    """Account selector resolved against the chart snapshot."""

    prefix: str | None = None
    range: tuple[str, str] | None = None
    tag: str | None = None


class AccountSet(BaseModel, frozen=True):
    """A named, optionally effective-dated, set of accounts as written in the model."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    accounts: tuple[str, ...] = ()
    select: Selector | None = None
    except_: tuple[str, ...] = Field(default=(), alias="except")
    valid_from: date | None = None
    valid_to: date | None = None
    allow_overlap: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _members_and_interval(self) -> "AccountSet":
        """Require accounts or select; valid_from must precede valid_to when both are set."""
        if not self.accounts and self.select is None:
            raise ValueError("account set needs 'accounts' or 'select'")
        if self.valid_from is not None and self.valid_to is not None and not self.valid_from < self.valid_to:
            raise ValueError("account set 'valid_from' must be earlier than 'valid_to'")
        return self


class MetricDef(BaseModel, frozen=True):
    """A metric expression over account sets and other metrics."""

    expr: str
    description: str = ""
    dimensions: tuple[str, ...] | None = None
    unit: str | None = None


class Assertion(BaseModel, frozen=True):
    """An ``<expr> == <expr>`` invariant checked with an exact tolerance."""

    expr: str
    tolerance: Decimal = Decimal("0")
    on_failure: Literal["flag", "block"] = "flag"


class Exclusion(BaseModel, frozen=True):
    """Accounts deliberately left out of every set, with the reason."""

    accounts: tuple[str, ...]
    reason: str


class AccountingModelSpec(BaseModel, frozen=True):
    """The model YAML as written."""

    model: str
    version: str
    tenant: str
    chart_of_accounts: ChartOfAccounts
    sets: dict[str, AccountSet]
    metrics: dict[str, MetricDef]
    assertions: tuple[Assertion, ...] = ()
    excluded: tuple[Exclusion, ...] = ()

    @model_validator(mode="after")
    def _no_reserved_metric(self) -> "AccountingModelSpec":
        """Reject metric names reserved by the toolkit (spec §3 M2)."""
        reserved = sorted(name for name in self.metrics if name in RESERVED_METRIC_NAMES)
        if reserved:
            raise ValueError(f"reserved metric name(s): {', '.join(reserved)}")
        return self


class ChartAccount(BaseModel, frozen=True):
    """One account of the account master."""

    account_id: str
    nature: Nature | None
    parent_id: str | None = None
    tags: tuple[str, ...] = ()


class ChartSnapshot(BaseModel, frozen=True):
    """Immutable account master."""

    accounts: tuple[ChartAccount, ...]
    taken_at: date
    source: str

    @property
    def snapshot_hash(self) -> str:
        """sha256 hex of the accounts sorted by account_id, as compact sorted-key JSON."""
        rows = sorted((a.model_dump(mode="json") for a in self.accounts), key=lambda r: r["account_id"])
        return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ResolvedSet(BaseModel, frozen=True):
    """An account set with its selectors resolved to an explicit, sorted account list."""

    name: str
    accounts: tuple[str, ...]
    valid_from: date | None
    valid_to: date | None


class AccountingModel(BaseModel, frozen=True):
    """Resolved, validated, hashable model."""

    spec: AccountingModelSpec
    snapshot_hash: str
    natures: tuple[tuple[str, Nature], ...]
    intervals: tuple[tuple[date | None, date | None], ...]
    sets: dict[str, ResolvedSet]
    model_hash: str

    @model_validator(mode="after")
    def _natures_sorted_unique(self) -> "AccountingModel":
        """Require natures strictly increasing by account id (sorted and unique, spec §3 M2)."""
        ids = [account_id for account_id, _ in self.natures]
        for previous, current in zip(ids, ids[1:]):
            if previous == current:
                raise ValueError(f"duplicate nature for account {current!r}")
            if previous > current:
                raise ValueError("natures must be sorted by account id")
        return self


# --- Requests (spec §2, "Numeric and period contracts", revision 0.3) -------------------------------------------

_CUMULATIVE_GRAINS: dict[str, frozenset[str]] = {
    "mtd": frozenset({"day", "month"}),
    "qtd": frozenset({"day", "month", "quarter"}),
    "ytd": frozenset({"day", "month", "quarter", "year"}),
}


class Period(BaseModel):
    """An inclusive ``[from, to]`` date window, optionally cumulative (period-to-date)."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    from_: date = Field(alias="from")
    to: date  # inclusive
    cumulative: Cumulative | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        """Require ``from <= to``."""
        if self.from_ > self.to:
            raise ValueError("period 'from' must not be later than 'to'")
        return self


class MetricRequest(BaseModel, frozen=True):
    """A request to compute one metric over a period."""

    kind: Literal["metric"] = "metric"
    metric: str
    grain: AccountingGrain | None = None
    dimensions: tuple[str, ...] = ()
    filters: dict[str, str | int | tuple[str | int, ...]] = {}
    period: Period

    @model_validator(mode="after")
    def _cumulative_fits_grain(self) -> "MetricRequest":
        """Enforce the cumulative/grain matrix (AC8); week or no grain never fits a cumulative mode."""
        cumulative = self.period.cumulative
        if cumulative is not None and (self.grain is None or self.grain not in _CUMULATIVE_GRAINS[cumulative]):
            allowed = ", ".join(sorted(_CUMULATIVE_GRAINS[cumulative]))
            raise ValueError(f"cumulative {cumulative!r} requires grain in {{{allowed}}}, got {self.grain!r}")
        return self


class AssertionRequest(BaseModel, frozen=True):
    """A request to evaluate one model assertion over a period."""

    kind: Literal["assertion"] = "assertion"
    assertion_index: int = Field(ge=0)
    period: Period

    @model_validator(mode="after")
    def _not_cumulative(self) -> "AssertionRequest":
        """Assertions are evaluated over plain periods only."""
        if self.period.cumulative is not None:
            raise ValueError("assertion requests do not accept a cumulative period")
        return self


AccountingRequest = Annotated[MetricRequest | AssertionRequest, Field(discriminator="kind")]


# --- Portable plan IR (FEAT-742 contract) ------------------------------------------------------------------------


class Lineage(BaseModel, frozen=True):
    """How a result was derived: formula, resolved sets and checked assertions."""

    metric: str | None
    assertion_index: int | None = None
    formula: str
    sets: tuple[ResolvedSet, ...]
    assertions: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class PlanSet(BaseModel, frozen=True):
    """An aliased account set referenced by plan expressions."""

    alias: str
    accounts: tuple[str, ...]


class PlanExpr(BaseModel, frozen=True):
    """A node of a plan arithmetic expression."""

    op: Literal["set", "num", "neg", "add", "sub", "mul", "div"]
    alias: str | None = None
    value: str | None = None
    args: tuple["PlanExpr", ...] = ()


PlanExpr.model_rebuild()


class MetricPlan(BaseModel, frozen=True):
    """Portable IR — plain data, no sqlglot (FEAT-742 contract)."""

    schema_version: Literal[1] = 1
    table: str
    account_key: str
    posting_date: str
    amount_convention: AmountConvention
    amount: str | None
    debit: str | None
    credit: str | None
    natures: tuple[tuple[str, Nature], ...]
    result_scale: Literal[6] = 6
    rounding: Literal["half_even"] = "half_even"
    arithmetic_version: Literal[1] = 1
    cast_decimal: bool
    sets: tuple[PlanSet, ...]
    columns: tuple[tuple[str, PlanExpr], ...]
    grain: AccountingGrain | None
    dimensions: tuple[str, ...]
    filters: tuple[tuple[str, tuple[str | int, ...]], ...]
    scan_from: date
    output_from: date
    to_exclusive: date
    cumulative: Cumulative | None

    @property
    def plan_hash(self) -> str:
        """sha256 hex of the plan's canonical JSON."""
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


# --- Outputs -----------------------------------------------------------------------------------------------------


class CompiledMetricQuery(BaseModel, frozen=True):
    """A rendered metric (or assertion) query with its plan, request and lineage."""

    sql: str
    dialect: str
    sql_hash: str
    model_hash: str
    plan_hash: str
    plan: MetricPlan
    request: AccountingRequest
    lineage: Lineage
    assertions: tuple["CompiledMetricQuery", ...] = ()

    @property
    def cache_key(self) -> str:
        """Canonical JSON list ``[model_hash, canonical request, dialect]`` — CompileCache shape."""
        request = json.dumps(self.request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
        return json.dumps([self.model_hash, request, self.dialect], separators=(",", ":"))


CompiledMetricQuery.model_rebuild()


class RuntimeResult(BaseModel, frozen=True):
    """Raw rows returned by a runtime target."""

    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    target: Literal["database", "duckdb"]
    duration_ms: int


class AssertionResult(BaseModel, frozen=True):
    """Outcome of one assertion check."""

    expr: str
    status: Literal["passed", "failed", "skipped"]
    lhs: Decimal | None
    rhs: Decimal | None
    tolerance: Decimal
    period: Period


class MetricResult(BaseModel, frozen=True):
    """Final metric result returned to callers."""

    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    row_count: int
    compiled: CompiledMetricQuery
    assertion_results: tuple[AssertionResult, ...]
    chart_drift: bool
    audit_id: str
    duration_ms: int
