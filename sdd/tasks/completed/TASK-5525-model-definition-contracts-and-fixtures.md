# TASK-5525: Model-definition contracts and shared accounting test fixtures

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5524
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models and §3 Module 2 (second half). This task writes the first half of
`parrot/semantic/accounting/models.py` — everything that describes a model and its resolved form — plus
`tests/accounting/conftest.py`, which the spec requires to hold **every** shared accounting fixture so no later
task edits it. TASK-5526 appends the request / plan / result contracts to the same `models.py`.

---

## Scope

- Create `models.py` with: `AmountConvention`, `Nature`, `AccountingGrain`, `Cumulative`, `JournalSource`,
  `NatureSpec`, `ChartOfAccounts`, `Selector`, `AccountSet`, `MetricDef`, `Assertion`, `Exclusion`,
  `AccountingModelSpec`, `ChartAccount`, `ChartSnapshot` (with `snapshot_hash`), `ResolvedSet`, `AccountingModel`,
  exactly as spec §2, with the validators of spec §3 M2.
- Create `tests/accounting/conftest.py` with the six fixtures of spec §4 "Test Data / Fixtures".
- Create `tests/accounting/test_models.py` with `test_amount_convention_required`, `test_journal_source_rules`,
  `test_reserved_metric_name_rejected`, `test_natures_sorted_unique`.

**NOT in scope**: `Period`, `MetricRequest`, `AssertionRequest`, `Lineage`, plan and result models (TASK-5526);
`test_request_cumulative_fits_grain` (TASK-5526); selector resolution and validation (TASK-5528).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py` | CREATE | model-definition contracts |
| `packages/ai-parrot-semantic/tests/accounting/conftest.py` | CREATE | all shared accounting fixtures |
| `packages/ai-parrot-semantic/tests/accounting/test_models.py` | CREATE | contract validator tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, model_validator   # Pydantic v2
import pyarrow as pa                                                   # core dependency pyarrow>=25.0
from parrot.auth.permission import PermissionContext, UserSession     # packages/ai-parrot/src/parrot/auth/permission.py:81, :21
from parrot.semantic.accounting.errors import Problem                  # created by TASK-5524 (not needed in models.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession:            # line 21 — positional/keyword: user_id, tenant_id, roles: frozenset[str], metadata
class PermissionContext:      # line 81 (dataclass) — PermissionContext(session=UserSession(...)); properties user_id :132, tenant_id :137, roles :142
# usage precedent: packages/ai-parrot-semantic/tests/test_results.py:18
#   PermissionContext(session=UserSession(user_id, tenant_id, frozenset({"analyst"}), {"region": "EU"}))
```
- `pytest.ini:3` sets `asyncio_mode = auto`.

### Does NOT Exist
- ~~`Grain` / `Metric` as accounting names~~ — `parrot.semantic.models.Grain` (`SL/models.py:12`) and
  `parrot.semantic.model.Metric` exist; use `AccountingGrain` and `MetricDef`.
- ~~`CompiledQuery` for this feature~~ — taken by `SL/models.py:192`; the accounting one is `CompiledMetricQuery`
  (TASK-5526).
- ~~a `parrot.semantic.accounting.loader.canonical_json`~~ yet — TASK-5529 creates it; `snapshot_hash` here uses its
  own sorted-JSON + sha256 so this module stays self-contained.
- ~~fixtures in `packages/ai-parrot-semantic/tests/conftest.py`~~ — none; do not add any there.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#UserSession"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `models.py` imports only the standard library and `pydantic` (compile-path isolation, AC1).
- All models are frozen; collections are tuples so models are hashable and JSON round-trippable.
- `AccountSet.except_` uses `Field(alias="except")`; give the model `ConfigDict(populate_by_name=True)`.
- Validators raise `ValueError` (Pydantic converts them); the loader (TASK-5529) turns schema errors into
  `ModelValidationError`.
- `conftest.py` is exclusive: it is loaded by every accounting test. Write all six fixtures now.

---

## Implementation Blueprint

### Steps (in order)
1. Write the literals and the spec models in order — *why*: later models reference earlier ones.
2. Add validators (FILL INs) — *why*: spec §3 M2 lists them; tests pin each one.
3. Write `conftest.py` — *why*: TASK-5528..5540 consume these fixtures and must not edit the file.
4. Write `test_models.py`.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py` (CREATE)
```python
"""Accounting contracts (FEAT-713 spec §2). Standard library and pydantic only."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AmountConvention = Literal["debit_positive", "credit_positive", "debit_credit_columns", "natural_balance"]
Nature = Literal["debit", "credit"]
AccountingGrain = Literal["day", "week", "month", "quarter", "year"]
Cumulative = Literal["mtd", "qtd", "ytd"]
RESERVED_METRIC_NAMES = frozenset({"__validate__"})


class JournalSource(BaseModel, frozen=True):
    """Where postings live: a database table XOR a named frame."""

    table: str | None = None
    dataframe: str | None = None
    connection: str | None = None
    driver: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "JournalSource":
        # FILL IN: exactly one of table/dataframe; table requires connection AND driver — test_journal_source_rules.
        return self


class NatureSpec(BaseModel, frozen=True):
    from_column: str | None = None
    accounts: dict[str, Nature] | None = None

    # FILL IN: validator — exactly one of from_column / accounts.


class ChartOfAccounts(BaseModel, frozen=True):
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

    # FILL IN: validator — debit_credit_columns needs debit+credit and no amount; others need amount;
    #   nature required unless natural_balance — test_amount_convention_required, spec §2 sign table.


class Selector(BaseModel, frozen=True):
    prefix: str | None = None
    range: tuple[str, str] | None = None
    tag: str | None = None


class AccountSet(BaseModel, frozen=True):
    model_config = ConfigDict(populate_by_name=True, frozen=True)

    accounts: tuple[str, ...] = ()
    select: Selector | None = None
    except_: tuple[str, ...] = Field(default=(), alias="except")
    valid_from: date | None = None
    valid_to: date | None = None
    allow_overlap: tuple[str, ...] = ()

    # FILL IN: validator — accounts or select present; valid_from < valid_to when both set.


class MetricDef(BaseModel, frozen=True):
    expr: str
    description: str = ""
    dimensions: tuple[str, ...] | None = None
    unit: str | None = None


class Assertion(BaseModel, frozen=True):
    expr: str
    tolerance: Decimal = Decimal("0")
    on_failure: Literal["flag", "block"] = "flag"


class Exclusion(BaseModel, frozen=True):
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

    # FILL IN: validator — reject metric names in RESERVED_METRIC_NAMES (spec §3 M2) — test_reserved_metric_name_rejected.


class ChartAccount(BaseModel, frozen=True):
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

    # FILL IN: validator — natures sorted by account id and unique (spec §3 M2) — test_natures_sorted_unique.
```
**Why**: the field lists are fixed by spec §2 and consumed by every later task; only the validators are open.

### `packages/ai-parrot-semantic/tests/accounting/conftest.py` (CREATE)
```python
"""Shared FEAT-713 accounting fixtures. Written once (TASK-5525); later tasks must not edit this file."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Awaitable, Callable

import pyarrow as pa
import pytest

from parrot.auth.permission import PermissionContext, UserSession
from parrot.semantic.accounting.models import ChartAccount, ChartSnapshot


@pytest.fixture
def chart_snapshot() -> ChartSnapshot:
    """40 accounts: 4xxx credit (revenue, 4900 returns), 5xxx debit (cogs, 5900 excluded-from-cogs),
    6xxx debit (opex), 6810/6820 d&a valid_from 2025-01-01, 9999 suspense (excluded)."""
    # FILL IN: exactly 40 ChartAccount rows matching the docstring; taken_at=date(2026, 10, 1),
    #   source="manifest:fixture" — bounded by spec §4 fixtures.


@pytest.fixture
def troc_pnl_yaml(tmp_path: Path) -> Path:
    """<tmp>/troc/troc_pnl.yaml — amount_convention: debit_positive, nature from_column, source dataframe: journal."""
    # FILL IN: write a model (tenant troc, model troc_pnl) whose sets cover every chart_snapshot account in every
    #   interval except 9999 (listed under excluded); metrics revenue, cogs, gross_margin, opex, ebitda,
    #   gross_margin_pct (a ratio); one assertion `gross_margin == revenue - cogs`; dimensions entity,
    #   product_line, cost_center. It must load with ZERO problems under load_model (TASK-5529) — bounded by AC4.
    #   Return the file path.


@pytest.fixture
def journal_frame() -> pa.Table:
    """10k postings 2025-01..2026-09, Decimal(18,2) amounts, dimensions entity/product_line/cost_center,
    both natures, reversals, one empty month."""
    # FILL IN: deterministic (seeded) rows; columns account_id (str), posting_date (date32), amount
    #   (decimal128(18, 2)), entity, product_line, cost_center; one calendar month with no rows.


@pytest.fixture
def journal_duckdb_file(tmp_path: Path, journal_frame: pa.Table) -> Path:
    """The same journal written to a DuckDB file table `journal`, for the executor-path test."""
    duckdb = pytest.importorskip("duckdb")
    # FILL IN: create <tmp>/journal.duckdb, CREATE TABLE journal AS SELECT * FROM the registered frame; return path.


@pytest.fixture
def recording_storage() -> tuple[Callable[[str], Awaitable[None]], list[str]]:
    """An async audit sink that records every payload."""
    payloads: list[str] = []

    async def storage(payload: str) -> None:
        payloads.append(payload)

    return storage, payloads


@pytest.fixture
def permission_context() -> PermissionContext:
    """A PermissionContext for user 'u1', tenant 'troc', role 'finance'."""
    return PermissionContext(session=UserSession("u1", "troc", frozenset({"finance"}), {}))
```

### `packages/ai-parrot-semantic/tests/accounting/test_models.py` (CREATE)
```python
"""FEAT-713 M2 — model-definition contract validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.semantic.accounting.models import AccountingModelSpec, ChartOfAccounts, JournalSource


def test_amount_convention_required() -> None:
    # FILL IN: missing amount_convention ⇒ ValidationError; each of the four conventions enforces its columns
    #   and nature rule (spec §2 sign table).


def test_journal_source_rules() -> None:
    # FILL IN: table XOR dataframe; table without connection or driver ⇒ ValidationError.


def test_reserved_metric_name_rejected() -> None:
    # FILL IN: a metric named "__validate__" ⇒ ValidationError.


def test_natures_sorted_unique() -> None:
    # FILL IN: AccountingModel with unsorted or duplicate natures ⇒ ValidationError; JSON round-trip keeps tuples.
```

### FILL IN checklist
- [ ] Validators on `JournalSource`, `NatureSpec`, `ChartOfAccounts`, `AccountSet`, `AccountingModelSpec`,
  `AccountingModel` — bounded by spec §3 M2.
- [ ] `chart_snapshot`, `troc_pnl_yaml`, `journal_frame`, `journal_duckdb_file` fixture bodies — bounded by spec §4.
- [ ] Four tests in `test_models.py`.

---

## Acceptance Criteria

- [ ] All models of the Scope list exist with spec §2 field names and types; all frozen.
- [ ] Validators reject every invalid combination named in spec §3 M2 (AC3 half).
- [ ] `conftest.py` holds all six fixtures of spec §4; `chart_snapshot` has 40 accounts.
- [ ] `models.py` imports only stdlib + pydantic.
- [ ] `ruff check` passes on the three files.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_models.py -q`

---

## Test Specification

The four tests in the blueprint. `troc_pnl_yaml` loading cleanly is proven later by TASK-5529.

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
9. **Close the task** with `parrot sdd task close TASK-5525 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native opus coder (attempt 9420810507b64a3989d5ee7718f18a99), commit 4092546c70
**Date**: 2026-11-12
**Notes**: models.py contracts, conftest fixtures, test_models.py. Tests green. AC4 (troc_pnl_yaml loads with zero problems) is verifiable only in TASK-5529. Residual lint: B905 zip() without strict= at models.py:209 (style, left to /sdd-done).

**Deviations from spec**: fixture account 4900 (returns) is debit-natured (contra-revenue) so revenue = sales - returns works under debit_positive; spec docstring says "4xxx credit". Fixture also adds set `d_and_a_legacy` (valid_to 2025-01-01) to cover two membership intervals. Later tasks must use set names: product_sales, returns, cost_of_sales, other_cost, operating_expenses, d_and_a, d_and_a_legacy.
