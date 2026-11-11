# TASK-5526: Request, plan and result contracts

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5525
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models (second half) and "Numeric and period contracts (revision 0.3)". Appends to
`parrot/semantic/accounting/models.py` the request side (`Period`, `MetricRequest`, `AssertionRequest`, the
kind-discriminated `AccountingRequest`), the portable IR (`PlanSet`, `PlanExpr`, `MetricPlan` — the FEAT-742
contract), and the outputs (`Lineage`, `CompiledMetricQuery`, `RuntimeResult`, `AssertionResult`, `MetricResult`).
The compiler, evaluator, runtimes and audit all consume these.

---

## Scope

- Append the models above to `models.py`, field-for-field as spec §2.
- `MetricRequest._cumulative_fits_grain`: allowed matrix **mtd: day/month; qtd: day/month/quarter;
  ytd: day/month/quarter/year**; `week` or `None` grain with any cumulative mode raises; non-cumulative `week` is valid.
- `Period`: `from_ <= to`. `AssertionRequest`: `period.cumulative` must be `None`.
- `MetricPlan.plan_hash` and `CompiledMetricQuery.cache_key` properties.
- Extend `tests/accounting/test_models.py` with `test_request_cumulative_fits_grain`,
  `test_accounting_request_discriminates`, `test_plan_round_trips_json`.

**NOT in scope**: building plans (TASK-5530), rendering (TASK-5531), evaluating (TASK-5532).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py` | MODIFY | append request/plan/result models |
| `packages/ai-parrot-semantic/tests/accounting/test_models.py` | MODIFY | three more tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, TypeAdapter, model_validator   # Pydantic v2
from typing import Annotated, Literal
# in-module (TASK-5525): AmountConvention, Nature, AccountingGrain, Cumulative, ResolvedSet
```

### Existing Signatures to Use
```python
# packages/ai-parrot-semantic/src/parrot/semantic/cache.py:12  _model_digest_of(cache_key)
#   cache_key must be canonical JSON: a list whose FIRST element is the model digest (or a dict with "model_digest").
#   CompiledMetricQuery.cache_key = json.dumps([model_hash, canonical request, dialect], separators=(",", ":"))
```
- Models created by TASK-5525 in the same file: `ResolvedSet`, the literals.

### Does NOT Exist
- ~~`canonical_request()`~~ yet — TASK-5530 creates it in `compiler.py`. `cache_key` here uses
  `self.request.model_dump(mode="json", by_alias=True)` with `sort_keys=True`; TASK-5530's `canonical_request`
  must produce the identical string (it reuses the same expression).
- ~~sqlglot objects inside `MetricPlan`~~ — forbidden (AC17); the plan is plain data.
- ~~`CompiledQuery`~~ for accounting — use `CompiledMetricQuery`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot-semantic/src/parrot/semantic/cache.py#_model_digest_of"]
}
```

---

## Implementation Notes

### Key Constraints
- `Period.from_` uses `Field(alias="from")`; set `ConfigDict(populate_by_name=True, frozen=True)` on `Period`.
- `PlanExpr` is recursive (`args: tuple["PlanExpr", ...]`); call `PlanExpr.model_rebuild()` after the class.
- `CompiledMetricQuery.assertions` is recursive; call `model_rebuild()` too.
- `MetricPlan` fields `result_scale`, `rounding`, `arithmetic_version` are hashed (they are ordinary fields).
- `plan_hash` = sha256 hex of `json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`.

---

## Implementation Blueprint

### Steps (in order)
1. Append the request models and the `AccountingRequest` union — *why*: the plan and audit replay key on `kind`.
2. Append plan models and `model_rebuild()` calls.
3. Append outputs.
4. Add the three tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py` (MODIFY)
```python
# AFTER — append at end of file, below `class AccountingModel` (created by TASK-5525)
# occurrences: 1 (verify: grep -c '^class AccountingModel(BaseModel, frozen=True):' models.py)
# Also add to the module imports: `from typing import Annotated` and `from datetime import datetime`.

_CUMULATIVE_GRAINS: dict[str, frozenset[str]] = {
    "mtd": frozenset({"day", "month"}),
    "qtd": frozenset({"day", "month", "quarter"}),
    "ytd": frozenset({"day", "month", "quarter", "year"}),
}


class Period(BaseModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True)

    from_: date = Field(alias="from")
    to: date  # inclusive
    cumulative: Cumulative | None = None

    # FILL IN: validator — from_ <= to.


class MetricRequest(BaseModel, frozen=True):
    kind: Literal["metric"] = "metric"
    metric: str
    grain: AccountingGrain | None = None
    dimensions: tuple[str, ...] = ()
    filters: dict[str, str | int | tuple[str | int, ...]] = {}
    period: Period

    @model_validator(mode="after")
    def _cumulative_fits_grain(self) -> "MetricRequest":
        # FILL IN: when period.cumulative is set, grain must be in _CUMULATIVE_GRAINS[cumulative]
        #   (week and None always rejected) — spec "Numeric and period contracts", AC8.
        return self


class AssertionRequest(BaseModel, frozen=True):
    kind: Literal["assertion"] = "assertion"
    assertion_index: int = Field(ge=0)
    period: Period

    # FILL IN: validator — period.cumulative must be None.


AccountingRequest = Annotated[MetricRequest | AssertionRequest, Field(discriminator="kind")]


class Lineage(BaseModel, frozen=True):
    metric: str | None
    assertion_index: int | None = None
    formula: str
    sets: tuple[ResolvedSet, ...]
    assertions: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class PlanSet(BaseModel, frozen=True):
    alias: str
    accounts: tuple[str, ...]


class PlanExpr(BaseModel, frozen=True):
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


class CompiledMetricQuery(BaseModel, frozen=True):
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
    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    target: Literal["database", "duckdb"]
    duration_ms: int


class AssertionResult(BaseModel, frozen=True):
    expr: str
    status: Literal["passed", "failed", "skipped"]
    lhs: Decimal | None
    rhs: Decimal | None
    tolerance: Decimal
    period: Period


class MetricResult(BaseModel, frozen=True):
    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    row_count: int
    compiled: CompiledMetricQuery
    assertion_results: tuple[AssertionResult, ...]
    chart_drift: bool
    audit_id: str
    duration_ms: int
```

### `packages/ai-parrot-semantic/tests/accounting/test_models.py` (MODIFY — append)
```python
from pydantic import TypeAdapter

from parrot.semantic.accounting.models import AccountingRequest, AssertionRequest, MetricPlan, MetricRequest


def test_request_cumulative_fits_grain() -> None:
    # FILL IN: every allowed (cumulative, grain) of the matrix passes; every cumulative with week or None fails;
    #   non-cumulative week passes — AC8.


def test_accounting_request_discriminates() -> None:
    # FILL IN: TypeAdapter(AccountingRequest).validate_json(...) yields MetricRequest / AssertionRequest by kind;
    #   AssertionRequest with cumulative period or negative index fails.


def test_plan_round_trips_json() -> None:
    # FILL IN: build a small MetricPlan by hand; model_validate_json(plan.model_dump_json()) == plan;
    #   plan_hash stable; changing a formula changes plan_hash.
```

### FILL IN checklist
- [ ] `Period`, `MetricRequest`, `AssertionRequest` validators — AC8.
- [ ] Three tests.

---

## Acceptance Criteria

- [ ] Every model of spec §2 Data Models (except `AccountingAuditEntry`) exists in `models.py`.
- [ ] The cumulative/grain matrix is enforced exactly (AC8).
- [ ] `MetricPlan` round-trips through JSON; `plan_hash` covers formulas and numeric fields (AC17).
- [ ] `CompiledMetricQuery.cache_key` decodes to a JSON list whose first element is `model_hash`.
- [ ] `ruff check` passes on both files.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_models.py -q`

---

## Test Specification

Blueprint tests plus the four from TASK-5525 must all pass.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5526 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
