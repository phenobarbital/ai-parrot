# TASK-3733: parrot_tools.hooba package skeleton + Pydantic models and exceptions

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5** and §2 Data Models. Every other Hooba module exchanges these models:
drafts (`InvoiceDraft`, `PurchaseInvoiceDraft` and their lines), `DraftReceipt`,
`ContactMatch`, the BBVA row/statement models, and the deductibility verdict with its
Hooba mapping. This task also creates the package itself and the test package.

`HoobaSettings` is listed in §2 but lives in `settings.py` per §3 Module 2 (TASK-3734);
it is NOT defined here. Design research added `correlation_key` (drafts and receipt,
S11), `reused` (receipt) and `evidence` (verdict, S12) — they are part of the contract.

---

## Scope

- Create `parrot_tools/hooba/__init__.py` exporting the models and exceptions (NOT `HoobaToolkit` — TASK-3742 adds it).
- Create `parrot_tools/hooba/models.py` with every §2 model except `HoobaSettings`, plus `HoobaStateError`, `HoobaLookupError`.
- Create `tests/hooba/__init__.py` (empty) and `tests/hooba/test_models.py`.

**NOT in scope**: settings, credentials, any I/O.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/hooba/__init__.py` | CREATE | package exports (models + exceptions) |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/models.py` | CREATE | §2 Data Models (minus HoobaSettings) + exceptions |
| `packages/ai-parrot-tools/tests/hooba/__init__.py` | CREATE | empty test package marker |
| `packages/ai-parrot-tools/tests/hooba/test_models.py` | CREATE | round-trip and validation tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from pydantic import BaseModel, Field     # pydantic v2 (workspace dependency)
import datetime as dt                     # stdlib — use dt.date to avoid the `date: date` field/type clash
from decimal import Decimal               # stdlib
```

### Existing Signatures to Use
```python
# No existing signatures are extended. Field names mirror Spec A's DeductibilityVerdict
# (sdd/specs/auto-finance-toolkit.spec.md:196-201): draft_id, txn_id, rule_id, deductible_pct,
# capped_amount, legal_basis, invoice_required, status — keep those names byte-identical.
```

### Does NOT Exist
- ~~`parrot_tools.hooba`~~ — the package does not exist yet; this task creates it.
- ~~`parrot_tools.finance.DeductibilityVerdict`~~ — Spec A was never implemented; do not import it.
- ~~`HoobaSettings` in models.py~~ — it lives in `settings.py` (TASK-3734).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- **Pydantic v2 gotcha**: a field named `date` annotated `date` (the type imported by name) fails at class creation.
  Import `datetime as dt` and annotate `dt.date` everywhere.
- Money is `Decimal`, never float. `model_dump(mode="json")` must round-trip (tests assert it).
- `DraftReceipt.state` is a free `str` — the toolkit (not the model) enforces `== "draft"`.

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
1. Create the package `__init__.py` — *why*: every later module imports from `parrot_tools.hooba`.
2. Write `models.py` from spec §2 — *why*: one shared contract; names are not renegotiable.
3. Create the empty `tests/hooba/__init__.py` — *why*: all later test modules live in that package.
4. Write round-trip tests.

### `packages/ai-parrot-tools/src/parrot_tools/hooba/__init__.py` (CREATE)
```python
"""Hooba (app.hooba.com) automation for AI-Parrot agents — FEAT-602.

Drafts only: nothing in this package issues invoices or confirms purchase invoices.
"""
from .models import (
    BankExpenseRow,
    BbvaStatement,
    ContactMatch,
    DeductibilityVerdict,
    DraftReceipt,
    ExpenseDraftBatch,
    HoobaLookupError,
    HoobaMapping,
    HoobaStateError,
    InvoiceDraft,
    InvoiceLineDraft,
    PurchaseInvoiceDraft,
    PurchaseInvoiceLineDraft,
)

__all__ = [
    "BankExpenseRow", "BbvaStatement", "ContactMatch", "DeductibilityVerdict", "DraftReceipt",
    "ExpenseDraftBatch", "HoobaLookupError", "HoobaMapping", "HoobaStateError", "InvoiceDraft",
    "InvoiceLineDraft", "PurchaseInvoiceDraft", "PurchaseInvoiceLineDraft",
]
```

### `packages/ai-parrot-tools/src/parrot_tools/hooba/models.py` (CREATE)
```python
"""Pydantic models shared by the Hooba toolkit modules (FEAT-602 spec §2)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class HoobaStateError(RuntimeError):
    """A created entity came back in a state other than ``draft``."""


class HoobaLookupError(LookupError):
    """An invoice serie, tax, income tax, contact or document type could not be resolved."""


class InvoiceLineDraft(BaseModel):
    """One product line of a sales-invoice draft."""

    name: str
    price: Decimal
    quantity: Decimal = Decimal("1")
    discount: Decimal = Decimal("0")
    tax_code: str = "IVA21"
    income_tax_code: Optional[str] = None
    notes: Optional[str] = None


class InvoiceDraft(BaseModel):
    """A sales invoice to create in ``draft`` state."""

    contact_id: Optional[int] = None
    contact_query: Optional[str] = None
    invoice_serie_code: Optional[str] = None
    operation_date: Optional[dt.date] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    simplified: bool = False
    correlation_key: Optional[str] = None
    lines: list[InvoiceLineDraft] = Field(min_length=1)

    # FILL IN: model_validator(mode="after") — exactly one of contact_id / contact_query; bounded by spec §2 comment


class PurchaseInvoiceLineDraft(BaseModel):
    """One line of a purchase-invoice (expense) draft."""

    name: str
    price: Decimal
    quantity: Decimal = Decimal("1")
    tax_code: str = "IVA21"
    income_tax_code: Optional[str] = None
    accounting_account_code: Optional[str] = None
    notes: Optional[str] = None


class PurchaseInvoiceDraft(BaseModel):
    """A purchase invoice (gasto / compra) to create in ``draft`` state."""

    date: dt.date
    number: Optional[str] = None
    simplified: bool = False
    contact_id: Optional[int] = None
    contact_query: Optional[str] = None
    tax_included: bool = True
    subject_to_income_tax: bool = False
    notes: Optional[str] = None
    correlation_key: Optional[str] = None
    lines: list[PurchaseInvoiceLineDraft] = Field(min_length=1)


class DraftReceipt(BaseModel):
    """What Hooba returned for a created (or reused) draft."""

    kind: Literal["invoice", "purchase_invoice"]
    id: int
    state: str
    number: Optional[str] = None
    url: Optional[str] = None
    line_ids: list[int] = Field(default_factory=list)
    correlation_key: str
    reused: bool = False


class ContactMatch(BaseModel):
    """A fuzzy match between a free-text name and a Hooba contact."""

    contact_id: int
    legal_name: str
    score: float


# FILL IN: BankExpenseRow, BbvaStatement, HoobaMapping, DeductibilityVerdict (with `evidence: dict`),
#          ExpenseDraftBatch — copy field-for-field from spec §2 Data Models, using dt.date and Decimal;
#          bounded by spec §2 (names are the contract; do not add or rename fields)
```
**Why this shape**: the draft and receipt models are written out because TASK-3743 and TASK-3741 bind to
them directly; the bank/verdict models are a verbatim copy from §2 (too long for one block, no decisions left).

### `packages/ai-parrot-tools/tests/hooba/__init__.py` (CREATE)
```python
```

### `packages/ai-parrot-tools/tests/hooba/test_models.py` (CREATE)
```python
"""FEAT-602 TASK-3733 — model contracts."""
import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from parrot_tools.hooba.models import (
    DeductibilityVerdict, DraftReceipt, HoobaMapping, InvoiceDraft, InvoiceLineDraft, PurchaseInvoiceDraft,
    PurchaseInvoiceLineDraft,
)


def test_models_roundtrip():
    # FILL IN: build one instance of every model; model_validate(model_dump(mode="json")) equals original


def test_invoice_draft_requires_exactly_one_contact_selector():
    # FILL IN: neither → ValidationError; both → ValidationError


def test_drafts_require_at_least_one_line():
    # FILL IN


def test_purchase_invoice_date_field_is_a_date():
    d = PurchaseInvoiceDraft(date=dt.date(2026, 9, 3), lines=[PurchaseInvoiceLineDraft(name="x", price=Decimal("1"))])
    assert d.date == dt.date(2026, 9, 3)
```

### FILL IN checklist
- [ ] `InvoiceDraft` validator — exactly one of `contact_id` / `contact_query`
- [ ] the five remaining models copied from spec §2
- [ ] every test body

---

## Acceptance Criteria

- [ ] Every model in spec §2 (except `HoobaSettings`) exists with the listed field names; `DraftReceipt.correlation_key`, `DraftReceipt.reused`, `DeductibilityVerdict.evidence` included.
- [ ] `from parrot_tools.hooba import InvoiceDraft, DraftReceipt, DeductibilityVerdict` works.
- [ ] `model_dump(mode='json')` round-trips for every model.
- [ ] `ruff check` and `black --check` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_models.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_models_roundtrip` | JSON round trip for every model |
| `test_invoice_draft_requires_exactly_one_contact_selector` | validator |
| `test_drafts_require_at_least_one_line` | `min_length=1` |
| `test_purchase_invoice_date_field_is_a_date` | the `dt.date` workaround |

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
