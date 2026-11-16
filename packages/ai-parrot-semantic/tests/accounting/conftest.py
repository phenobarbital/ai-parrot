"""Shared FEAT-713 accounting fixtures. Written once (TASK-5525); later tasks must not edit this file."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Awaitable, Callable

import pyarrow as pa
import pytest

from parrot.auth.permission import PermissionContext, UserSession
from parrot.semantic.accounting.models import ChartAccount, ChartSnapshot

#: Account ids of the fixture chart, grouped by role.
PRODUCT_SALES_ACCOUNTS = tuple(f"40{n}0" for n in range(10))  # 4000..4090, credit
RETURNS_ACCOUNT = "4900"  # contra-revenue, debit
COGS_ACCOUNTS = tuple(f"50{n}0" for n in range(10))  # 5000..5090, debit
OTHER_COST_ACCOUNT = "5900"  # debit, excluded from cogs by the model
OPEX_ACCOUNTS = tuple(f"6{n:02d}0" for n in range(15))  # 6000..6140, debit
D_AND_A_ACCOUNTS = ("6810", "6820")  # debit, d&a from 2025-01-01
SUSPENSE_ACCOUNT = "9999"  # debit, excluded

TROC_PNL_YAML = """\
model: troc_pnl
version: "2026.10"
tenant: troc
chart_of_accounts:
  source: { dataframe: journal }
  account_key: account_id
  posting_date: posting_date
  amount_convention: debit_positive
  amount: amount
  nature: { from_column: nature }
  dimensions: [entity, product_line, cost_center]

sets:
  product_sales:      { select: { prefix: "40" } }
  returns:            { accounts: ["4900"] }
  cost_of_sales:      { select: { prefix: "5" }, except: ["5900"] }
  other_cost:         { accounts: ["5900"] }
  operating_expenses: { select: { range: ["6000", "6799"] } }
  d_and_a:            { accounts: ["6810", "6820"], valid_from: "2025-01-01" }
  d_and_a_legacy:     { accounts: ["6810", "6820"], valid_to: "2025-01-01" }

excluded:
  - { accounts: ["9999"], reason: "suspense, cleared monthly" }

metrics:
  revenue:          { expr: "sum(product_sales) - sum(returns)", description: "Net revenue", unit: "currency" }
  cogs:             { expr: "sum(cost_of_sales)", description: "Cost of goods sold", unit: "currency" }
  gross_margin:     { expr: "revenue - cogs", description: "Revenue minus cogs", unit: "currency" }
  opex:             { expr: "sum(operating_expenses)", description: "Operating expenses", unit: "currency" }
  ebitda:
    expr: "gross_margin - sum(other_cost) - opex"
    description: "Earnings before interest, taxes, depreciation and amortisation"
    unit: "currency"
  gross_margin_pct: { expr: "gross_margin / revenue", description: "Gross margin ratio", unit: "ratio" }

assertions:
  - { expr: "gross_margin == revenue - cogs" }
"""

_ENTITIES = ("TROC", "TROC-EU", "TROC-US")
_PRODUCT_LINES = ("pokemon", "magic", "yugioh", "accessories")
_COST_CENTERS = ("CC100", "CC200", "CC300", "CC400")
_EMPTY_MONTH = (2025, 8)
_JOURNAL_ROWS = 10_000


def _chart_accounts() -> tuple[ChartAccount, ...]:
    """Build the 40 fixture accounts, sorted by account id."""
    accounts: list[ChartAccount] = []
    accounts += [ChartAccount(account_id=a, nature="credit", tags=("revenue",)) for a in PRODUCT_SALES_ACCOUNTS]
    accounts.append(ChartAccount(account_id=RETURNS_ACCOUNT, nature="debit", tags=("revenue", "returns")))
    accounts += [ChartAccount(account_id=a, nature="debit", tags=("cogs",)) for a in COGS_ACCOUNTS]
    accounts.append(ChartAccount(account_id=OTHER_COST_ACCOUNT, nature="debit", tags=("other_cost",)))
    accounts += [ChartAccount(account_id=a, nature="debit", tags=("opex",)) for a in OPEX_ACCOUNTS]
    accounts += [ChartAccount(account_id=a, nature="debit", tags=("d_and_a",)) for a in D_AND_A_ACCOUNTS]
    accounts.append(ChartAccount(account_id=SUSPENSE_ACCOUNT, nature="debit", tags=("suspense",)))
    return tuple(sorted(accounts, key=lambda account: account.account_id))


@pytest.fixture
def chart_snapshot() -> ChartSnapshot:
    """40 accounts: 4xxx credit (revenue, 4900 returns), 5xxx debit (cogs, 5900 excluded-from-cogs),
    6xxx debit (opex), 6810/6820 d&a valid_from 2025-01-01, 9999 suspense (excluded).

    4900 (returns) is a contra-revenue account and carries the debit nature; every other 4xxx is credit.
    """
    accounts = _chart_accounts()
    assert len(accounts) == 40
    return ChartSnapshot(accounts=accounts, taken_at=date(2026, 10, 1), source="manifest:fixture")


@pytest.fixture
def troc_pnl_yaml(tmp_path: Path) -> Path:
    """<tmp>/troc/troc_pnl.yaml — amount_convention: debit_positive, nature from_column, source dataframe: journal."""
    path = tmp_path / "troc" / "troc_pnl.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TROC_PNL_YAML, encoding="utf-8")
    return path


def _posting_months() -> list[tuple[int, int]]:
    """Calendar months 2025-01..2026-09 with postings (the empty month left out)."""
    months = [(year, month) for year in (2025, 2026) for month in range(1, 13) if (year, month) <= (2026, 9)]
    return [ym for ym in months if ym != _EMPTY_MONTH]


@pytest.fixture
def journal_frame() -> pa.Table:
    """10k postings 2025-01..2026-09, Decimal(18,2) amounts, dimensions entity/product_line/cost_center,
    both natures, reversals, one empty month.

    Deterministic (seeded). Under ``debit_positive`` credit-nature accounts post negative amounts; every tenth
    original posting is followed by its reversal (same account, date and dimensions, negated amount). August 2025
    has no postings.
    """
    rng = random.Random(713)
    natures = {account.account_id: account.nature for account in _chart_accounts()}
    account_ids = sorted(natures)
    months = _posting_months()
    columns: dict[str, list] = {
        "account_id": [],
        "posting_date": [],
        "amount": [],
        "entity": [],
        "product_line": [],
        "cost_center": [],
    }

    def _append(account_id: str, posted: date, amount: Decimal, entity: str, line: str, center: str) -> None:
        columns["account_id"].append(account_id)
        columns["posting_date"].append(posted)
        columns["amount"].append(amount)
        columns["entity"].append(entity)
        columns["product_line"].append(line)
        columns["cost_center"].append(center)

    originals = 0
    while len(columns["account_id"]) < _JOURNAL_ROWS:
        account_id = rng.choice(account_ids)
        year, month = rng.choice(months)
        posted = date(year, month, rng.randint(1, 28))
        magnitude = Decimal(rng.randint(100, 5_000_000)).scaleb(-2)
        amount = magnitude if natures[account_id] == "debit" else -magnitude
        entity = rng.choice(_ENTITIES)
        line = rng.choice(_PRODUCT_LINES)
        center = rng.choice(_COST_CENTERS)
        _append(account_id, posted, amount, entity, line, center)
        originals += 1
        if originals % 10 == 0 and len(columns["account_id"]) < _JOURNAL_ROWS:
            _append(account_id, posted, -amount, entity, line, center)

    schema = pa.schema(
        [
            ("account_id", pa.string()),
            ("posting_date", pa.date32()),
            ("amount", pa.decimal128(18, 2)),
            ("entity", pa.string()),
            ("product_line", pa.string()),
            ("cost_center", pa.string()),
        ]
    )
    return pa.table(columns, schema=schema)


@pytest.fixture
def journal_duckdb_file(tmp_path: Path, journal_frame: pa.Table) -> Path:
    """The same journal written to a DuckDB file table `journal`, for the executor-path test."""
    duckdb = pytest.importorskip("duckdb")
    path = tmp_path / "journal.duckdb"
    connection = duckdb.connect(str(path))
    try:
        connection.register("journal_frame", journal_frame)
        connection.execute("CREATE TABLE journal AS SELECT * FROM journal_frame")
        connection.unregister("journal_frame")
    finally:
        connection.close()
    return path


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
