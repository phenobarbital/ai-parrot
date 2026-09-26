# TASK-3739: BBVA statement parser (off-loop), synthetic fixture generator and import manifest

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3733
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8**, U3, design research S10. A BBVA `.xlsx` export has preamble rows
(holder, account, period) before the movements table. This task locates the header row by
tokens, maps columns, parses Spanish amounts/dates, keeps debits only, digests the file,
cross-checks the row count with `ExcelLoader` (same discipline as FEAT-453's
`ingest._load_expense_rows`), and runs all workbook work in `asyncio.to_thread`. It also
provides the permission-hardened per-statement manifest used for resume/reconcile, and a
generator for a **synthetic** BBVA workbook (no real data — AC-17).

The real layout is still an open question (spec §8 Q2); `HEADER_TOKENS` is data so a
layout correction is a one-line change.

---

## Scope

- `hooba/bank/__init__.py`, `hooba/bank/bbva.py` (`HEADER_TOKENS`, `parse_bbva_statement`, `_parse_bbva_sync`, `parse_es_amount`, `parse_es_date`).
- `hooba/bank/manifest.py` (`ImportManifest`, `manifest_path_for`, `load_manifest`, `write_manifest`, `reconcile`).
- `tests/hooba/fixtures/__init__.py`, `tests/hooba/fixtures/make_bbva_fixture.py` (`build_bbva_workbook(path) -> Path`).
- `tests/hooba/test_bbva.py`.

**NOT in scope**: rule evaluation (TASK-3740), draft creation (TASK-3741).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/__init__.py` | CREATE | exports |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/bbva.py` | CREATE | header detection, Spanish parsing, debit rows, digest, row-count cross-check |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/manifest.py` | CREATE | ImportManifest + atomic 0o600 writes + reconcile |
| `packages/ai-parrot-tools/tests/hooba/fixtures/__init__.py` | CREATE | empty |
| `packages/ai-parrot-tools/tests/hooba/fixtures/make_bbva_fixture.py` | CREATE | synthetic workbook builder (openpyxl) |
| `packages/ai-parrot-tools/tests/hooba/test_bbva.py` | CREATE | parser + manifest tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot_tools.business_automation.ingest import checkpoint_dir_for, compute_statement_digest   # verified: ingest.py:86, 99
from parrot_loaders.excel import ExcelLoader                                   # verified: ingest.py:65
from parrot_tools.hooba.models import BankExpenseRow, BbvaStatement            # created by TASK-3733
import pandas as pd                                                            # business_automation extra
import openpyxl                                                                # excel extra (fixture builder + sheet scan)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py
def checkpoint_dir_for(operation: str) -> Path                                # lines 86-96 — $PARROT_STATE_DIR/business_automation/checkpoints/<op>/, 0o700
def compute_statement_digest(xlsx_path: Union[str, Path]) -> str              # lines 99-108 — sha256(bytes)[:16]
async def _load_expense_rows(xlsx_path, client_column, amount_column)         # lines 111-151 — PATTERN to mirror:
#   loader = ExcelLoader(Path(xlsx_path), output_mode="row"); documents = await loader.load(Path(xlsx_path), split_documents=False)
#   pass a concrete Path, not str (AbstractLoader.from_path quirk, comment lines 128-133)

# packages/ai-parrot-loaders/src/parrot_loaders/excel.py
class ExcelLoader(AbstractLoader):                                            # line 21
    def __init__(self, source=None, *, ..., sheets=None, header=0, ..., output_mode="sheet", ...)   # lines 38-60
```

### Does NOT Exist
- ~~`parrot_tools.finance.parse_bank_excel`~~ — Spec A, never implemented.
- ~~`ExcelStructureAnalyzer` in parrot_loaders~~ — it lives in core `parrot/tools/dataset_manager/excel_analyzer.py:133`; not used here.
- ~~`ingest.reconcile` for this manifest~~ — bound to `ImportPlanBundle`; this task defines its own `reconcile`.
- ~~A real BBVA export in the repo~~ — fixtures are synthetic only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/bank/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/bank/bbva.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/bank/manifest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/fixtures/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/fixtures/make_bbva_fixture.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_bbva.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py#compute_statement_digest",
    "sym:packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py#checkpoint_dir_for",
    "sym:packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py#_load_expense_rows"
  ]
}
```

---

## Implementation Notes

- Header detection: scan the first 40 rows; a row is the header when ≥ 3 cells match `HEADER_TOKENS`
  case- and accent-insensitively (`unicodedata.normalize("NFKD")` + drop combining marks). `fecha` and `importe` are mandatory.
- The ExcelLoader cross-check compares against the number of rows AFTER the header row within the detected table; if
  ExcelLoader's row mode cannot model the preamble (it reads with `header=0`), compare against a pandas read with
  `header=<detected row>` instead and record the choice in the Completion Note — the invariant is "two independent
  readers agree on the table's row count", never skip it.
- Amounts: numeric cells as-is; strings like `"-1.234,56"` / `"1.234,56 €"` → `Decimal`. Dates: `datetime` cells or `dd/mm/yyyy`.
- `row_id = f"{digest}:{row_index}"`, `row_index` 0-based within the table. Credits (≥ 0) and blanks → `skipped`.
- Manifest: `checkpoint_dir_for("hooba_bbva_import") / f"{digest}.manifest.json"`; write to a tmp file in the same dir,
  `os.chmod(tmp, 0o600)`, `os.replace`. The fixture: 6 preamble rows; header
  `Fecha | F.Valor | Concepto | Movimiento | Importe | Divisa | Disponible | Observaciones`; 7 rows: debits RETA, MOVISTAR,
  REPSOL, RESTAURANTE, TRASPASO and 2 credits. Invented names/amounts only.

### Key Constraints (all FEAT-602 tasks)
- async-first: no blocking I/O inside `async def` — wrap pandas/openpyxl/filesystem work in `asyncio.to_thread` (spec §7, S10).
- aiohttp only in new code: `httpx` and `requests` are banned by ruff TID251; the only httpx surface is inside the exempt `HTTPService` / `openapitoolkit.py`.
- Pydantic v2 models for every structured value; `self.logger` (or a module `logger = logging.getLogger(__name__)`), never `print`.
- Never log cookie values, passwords, IBANs or full bank rows at INFO or above.
- Google-style docstrings and strict type hints on every function and class; `black` line length 120; `ruff check` clean.
- Drafts only: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, a DELETE, or any write outside `DRAFT_OPERATIONS` (spec G3, AC-5).
- Worktree testing: the shared `.venv` is editable-installed against the MAIN checkout. Run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-loaders/src pytest ...` so the worktree's code is imported. Never `uv sync` in a worktree.
- Fixtures are synthetic: never commit real Hooba selectors, credentials, bank exports or personal data (AC-17).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above. Business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Fixture builder first — *why*: every parser test and TASK-3741/3744 reuse it.
2. `bbva.py` with a pure sync core and an async wrapper — *why*: S10.
3. `manifest.py` — *why*: resume-without-duplicates needs a durable, private record.
4. Tests.

### `packages/ai-parrot-tools/tests/hooba/fixtures/__init__.py` (CREATE)
```python
```

### `packages/ai-parrot-tools/tests/hooba/fixtures/make_bbva_fixture.py` (CREATE)
```python
"""Build a SYNTHETIC BBVA-like movements workbook (no real data)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import openpyxl

HEADER = ["Fecha", "F.Valor", "Concepto", "Movimiento", "Importe", "Divisa", "Disponible", "Observaciones"]


def build_bbva_workbook(path: Path, *, extra_rows: int = 0) -> Path:
    """Write the fixture to ``path`` and return it. ``extra_rows`` appends synthetic debits (load tests)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Movimientos"
    # FILL IN: 6 preamble rows (e.g. "Titular: ACME TEST", "Cuenta: ES00 0000 ...0000", "Periodo: 01/09/2026 - 30/09/2026", blanks),
    #          HEADER, 5 debits (CUOTA RETA -294,00; MOVISTAR -45,50 string "-45,50"; REPSOL -60,00; RESTAURANTE -18,90;
    #          TRASPASO A CUENTA PROPIA -500,00), 2 credits; then extra_rows debits — invented values only (AC-17)
    wb.save(path)
    return path
```

### `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/bbva.py` (CREATE)
```python
"""BBVA movements export → :class:`BbvaStatement` (FEAT-602 M8)."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Union

from parrot_loaders.excel import ExcelLoader
from parrot_tools.business_automation.ingest import compute_statement_digest

from ..models import BankExpenseRow, BbvaStatement

logger = logging.getLogger(__name__)

HEADER_TOKENS = {"fecha", "f.valor", "fecha valor", "concepto", "movimiento", "importe", "divisa", "disponible",
                 "observaciones"}


def parse_es_amount(value: Any) -> Optional[Decimal]:
    """``-1.234,56`` / ``1.234,56 €`` / numeric → Decimal; blank → None."""
    # FILL IN — bounded by AC-10
    raise NotImplementedError


def parse_es_date(value: Any) -> Optional[dt.date]:
    """datetime/date cell or ``dd/mm/yyyy`` → date; blank → None."""
    # FILL IN — bounded by AC-10
    raise NotImplementedError


def _parse_bbva_sync(path: Path, sheet: Optional[str]) -> BbvaStatement:
    """Pure synchronous parse (runs in a worker thread)."""
    # FILL IN: see Implementation Notes (header scan, column map, debit rows, row_id, skipped, row_count)
    raise NotImplementedError


async def parse_bbva_statement(path: Union[str, Path], *, sheet: Optional[str] = None) -> BbvaStatement:
    """Parse a BBVA export off the event loop and cross-check its row count with ExcelLoader."""
    path = Path(path)
    statement = await asyncio.to_thread(_parse_bbva_sync, path, sheet)
    # FILL IN: independent row-count cross-check (ExcelLoader row mode, pattern ingest.py:134-143; see Notes);
    #          mismatch → ValueError naming both counts — bounded by AC-10
    return statement
```

### `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/manifest.py` (CREATE)
```python
"""Per-statement import manifest for resume and reconciliation (FEAT-602 M8)."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from parrot_tools.business_automation.ingest import checkpoint_dir_for

_OPERATION = "hooba_bbva_import"


class ImportManifest(BaseModel):
    """Progress of one statement import; ``completed`` maps row_id → purchase_invoice_id."""

    statement_digest: str
    period: str
    started_at: dt.datetime
    row_count: int
    completed: Dict[str, int] = Field(default_factory=dict)
    skipped: Dict[str, str] = Field(default_factory=dict)


def manifest_path_for(digest: str) -> Path:
    """``$PARROT_STATE_DIR/business_automation/checkpoints/hooba_bbva_import/<digest>.manifest.json``."""
    return checkpoint_dir_for(_OPERATION) / f"{digest}.manifest.json"


def load_manifest(digest: str) -> Optional[ImportManifest]:
    """Load a prior manifest or return None. Sync — call via asyncio.to_thread."""
    # FILL IN
    raise NotImplementedError


def write_manifest(manifest: ImportManifest) -> Path:
    """Atomic write, file mode 0o600. Sync — call via asyncio.to_thread."""
    # FILL IN: tmp in same dir, chmod 0o600, os.replace — bounded by AC-11
    raise NotImplementedError


def reconcile(manifest: ImportManifest, planned_rows: int) -> Dict[str, Any]:
    """``{rows_in, drafts_out, skipped, delta, reconciled}`` — reconciled iff delta == 0."""
    # FILL IN: rows_in = planned_rows; drafts_out = len(completed); skipped = len(skipped);
    #          delta = rows_in - drafts_out - skipped
    raise NotImplementedError
```

### `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/__init__.py` (CREATE)
```python
"""Bank statement parsing for the Hooba toolkit."""
from .bbva import HEADER_TOKENS, parse_bbva_statement, parse_es_amount, parse_es_date
from .manifest import ImportManifest, load_manifest, manifest_path_for, reconcile, write_manifest

__all__ = ["HEADER_TOKENS", "ImportManifest", "load_manifest", "manifest_path_for", "parse_bbva_statement",
           "parse_es_amount", "parse_es_date", "reconcile", "write_manifest"]
```

### `packages/ai-parrot-tools/tests/hooba/test_bbva.py` (CREATE)
```python
"""FEAT-602 TASK-3739 — BBVA parser and manifest."""
import stat
from decimal import Decimal
from unittest.mock import patch

import pytest

from parrot_tools.hooba.bank import (
    ImportManifest, parse_bbva_statement, parse_es_amount, parse_es_date, reconcile, write_manifest,
)
from .fixtures.make_bbva_fixture import build_bbva_workbook


async def test_parse_bbva_fixture(tmp_path):
    # FILL IN: header row 6; 5 debits; 2 skipped; digest stable across two parses


def test_parse_bbva_spanish_amounts_and_dates():
    # FILL IN: "-1.234,56" → Decimal("-1234.56"); "03/09/2026" → date(2026, 9, 3)


async def test_parse_bbva_header_not_found(tmp_path):
    # FILL IN


async def test_parse_bbva_runs_off_event_loop(tmp_path):
    # FILL IN: patch asyncio.to_thread in the bbva module and assert it received _parse_bbva_sync (S10)


def test_manifest_permissions_and_reconcile(tmp_path, monkeypatch):
    # FILL IN: monkeypatch PARROT_STATE_DIR=tmp_path; file mode 0o600, dir 0o700; delta math
```

### FILL IN checklist
- [ ] fixture rows; `parse_es_amount`, `parse_es_date`, `_parse_bbva_sync`, row-count cross-check
- [ ] `load_manifest`, `write_manifest`, `reconcile`
- [ ] every test body

---

## Acceptance Criteria

- [ ] AC-10 (spec): header detected after the preamble, Spanish amounts/dates parsed, debits only, row counts cross-checked by two independent readers, stable digest.
- [ ] Workbook parsing runs in `asyncio.to_thread` (S10); the manifest is written atomically with mode 0o600 in a 0o700 dir.
- [ ] AC-17 (spec): the fixture is synthetic.
- [ ] `ruff check` and `black --check` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_bbva.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_parse_bbva_fixture` | header, debits, skipped, digest |
| `test_parse_bbva_spanish_amounts_and_dates` | locale parsing |
| `test_parse_bbva_header_not_found` | `ValueError` |
| `test_parse_bbva_runs_off_event_loop` | S10 |
| `test_manifest_permissions_and_reconcile` | 0o600/0o700, delta |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 module, §6, §7).
2. **Check dependencies** — verify every `Depends-on` task is done in `sdd/tasks/index/hooba-toolkit.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every anchor in the blueprint still has the stated occurrence count (`grep -c`)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/hooba-toolkit.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria and run every Validation Command.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note


- Task: TASK-3739
- Feature: hooba-toolkit
- Implementation SHA: c925ad9da3ac989650dcb04e454686aae13f5abd
- Closed at (UTC): 2026-09-25T18:16:21+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| merge_tier_engine_outcome | failed (workspace-wide import-impact sweep; 105 pre-existing unrelated failures across other distributions, same as chunk0/chunk1) |
| orchestrator_targeted_verification | packages/ai-parrot-tools/tests/hooba/ full directory (30 tests across all TASK-3733/3734/3735/3737/3738/3739 test files): 30/30 passed. ruff clean on all 6 new bank/fixture files. |
| seat_summary | Seat: haiku(native)->sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: ~359.8s · Tokens: ~117458 total (in/out breakdown n/a) |
| verification_method | Ran pytest directly (PYTHONPATH override) with the two compiled Cython extensions temporarily copied in from the main checkout since worktrees have no compiled .so; removed afterward (never committed). Note: the parrot-sdd-coder MCP server's execution state was lost mid-wave (server restart); this validation log was recovered from durable disk storage by content hash, independent of the lost execution_id. |
