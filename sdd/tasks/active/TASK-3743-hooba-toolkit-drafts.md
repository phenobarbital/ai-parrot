# TASK-3743: HoobaToolkit draft tools: idempotent invoice / purchase-invoice drafts, multipart attach, BBVA import tool

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3742, TASK-3741
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6**, second half, design research S6 and S11. The three user-facing
capabilities: draft sales invoices, draft purchase invoices (gastos y compras), and the
BBVA statement import. Id resolution (contact, invoice serie, taxes, income taxes,
document types) happens before any POST; the Product line body (`oneOf`) is built
explicitly; the multipart document upload bypasses `HTTPService` (no file support) and
uses aiohttp with the session cookie. Every create is idempotent per `correlation_key`: a
`[parrot:<key>]` marker in `notes` lets a retry find a partially created draft and add only
the missing lines instead of creating a second header.

---

## Scope

- Add to `HoobaToolkit`: `hooba_create_invoice_draft`, `hooba_create_purchase_invoice_draft`, `hooba_attach_document`,
  `hooba_import_bbva_statement`, and private helpers `_resolve_tax`, `_resolve_income_tax`, `_resolve_serie`,
  `_resolve_contact`, `_find_by_key`, `_create_purchase_invoice(draft) -> DraftReceipt` (the importer's `DraftCreator`).
- `tests/hooba/test_toolkit_drafts.py` with a fake `_call`.

**NOT in scope**: `:issue` / `:confirm` or any other write outside `DRAFT_OPERATIONS` + the documents upload.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py` | MODIFY | draft tools, resolvers, attach, BBVA import tool |
| `packages/ai-parrot-tools/tests/hooba/test_toolkit_drafts.py` | CREATE | id resolution, state check, idempotency, multipart, import tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
import aiohttp                                                                # core dependency — multipart upload
from parrot_tools.hooba.importer import BbvaImporter                          # TASK-3741
from parrot_tools.hooba.bank import parse_bbva_statement, reconcile           # TASK-3739
from parrot_tools.hooba.rules import RuleEngine                               # TASK-3740
from parrot_tools.hooba.models import (DraftReceipt, ExpenseDraftBatch, HoobaLookupError, HoobaStateError,
                                       InvoiceDraft, PurchaseInvoiceDraft)    # TASK-3733
```

### Existing Signatures to Use
```python
# hooba/toolkit.py (TASK-3742): self._call(method, path, *, params=None, data=None) -> Any ; self._api.get_cookies();
#   self._api._ensure_session(force=...); self.settings.default_headers(); self._ok / self._err envelopes
# Hooba API (pinned spec 2026.6.17, spec §6 table):
#   POST /accounts/{accountId}/invoices  {invoiceSerieId, simplified, contactId, operationDate, reference, notes, ...} → Invoice{id, state}
#   POST /accounts/{accountId}/invoices/{invoiceId}/invoice-lines  Product: {type:"product", name, price, quantity, discount, taxId, incomeTaxId}
#   POST /accounts/{accountId}/purchase-invoices  {date, number, simplified, contactId, taxIncluded, subjectToIncomeTax, notes, ...}
#   POST /accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines  {name, price, quantity, taxId, incomeTaxId, accountingAccountId, notes}
#   POST /accounts/{accountId}/documents/{documentTypeId}/{entityRecordId}  multipart: file, data (JSON string)
#   GET /taxes → Tax{id, percentage, operationType, selectableForSimplifiedInvoice, ...}; GET /income-taxes; GET invoice-series; GET document-types
```

### Does NOT Exist
- ~~`HTTPService._request(files=...)`~~ — no multipart support; use `aiohttp.FormData` directly.
- ~~A Hooba idempotency header~~ — none documented; the `[parrot:<key>]` notes marker is FEAT-602's mechanism (S11).
- ~~Invoice-serie field names~~ like `isDefault` — not verified; read the `InvoiceSerie` schema from the pinned document and record the field you use in the Completion Note.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_toolkit_drafts.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/http.py#HTTPService._request"
  ]
}
```

---

## Implementation Notes

- Tax codes: `IVA21`→21, `IVA10`→10, `IVA4`→4 with `operationType` "sale" (invoices) / "purchase" (purchase invoices); `EXENTO` → `taxId=None`.
  Unresolvable → `HoobaLookupError` → error envelope (never guess an id).
- Create flow (both kinds): `draft = Model.model_validate(draft)`; `key = draft.correlation_key or uuid4().hex`;
  `existing = await self._find_by_key(kind, key)` (list drafts, notes contains `[parrot:{key}]`); if found, POST only the
  lines not yet present (compare by name+price) and return `reused=True`; else resolve ids, POST header with
  `notes=f"{draft.notes or ''} [parrot:{key}]".strip()`, POST each line, GET the entity, `state != "draft"` → `HoobaStateError`.
- `hooba_attach_document`: resolve `documentTypeId` from GET document-types by entity name; `aiohttp.FormData()` with
  `file` (open via `asyncio.to_thread`) and `data=json.dumps({})`; cookies from `self._api.get_cookies()`, headers
  `settings.default_headers()`; 401 → `await self._api._ensure_session(force=True)` and retry once.
- `hooba_import_bbva_statement(path, period, dry_run=True)`: parse → `BbvaImporter(RuleEngine.load(self._rules_path),
  self._find_contacts_raw, self._create_purchase_invoice)` → plan; `dry_run` → zero POSTs; else apply; return
  `ExpenseDraftBatch` (with `reconciled` from `reconcile(manifest, planned_rows)` and the manifest path).

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
1. Resolvers — *why*: no POST until every id is known (spec §7 "Line bodies are oneOf").
2. `_find_by_key` + the two create tools — *why*: S11 idempotency, AC-7 state check.
3. Attach via aiohttp multipart — *why*: S6.
4. BBVA import tool wiring the importer — *why*: capability 3.
5. Tests.

### `packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py` (MODIFY)
```python
# (a) imports — AFTER `from .web import HoobaWebAdapter` (occurrences: 1, verified after TASK-3742):
import json
import uuid

import aiohttp

from .bank import parse_bbva_statement, reconcile
from .importer import BbvaImporter
from .models import (DraftReceipt, ExpenseDraftBatch, HoobaLookupError, HoobaStateError, InvoiceDraft,
                     PurchaseInvoiceDraft)
from .rules import RuleEngine
# (move the stdlib/third-party lines into their proper import groups when applying — black/ruff order)

# (b) append these methods at the END of class HoobaToolkit:
    async def hooba_create_invoice_draft(self, draft: InvoiceDraft) -> dict:
        """Create a sales invoice in DRAFT state (never issued).

        Args:
            draft: Contact, serie, lines (name, price, quantity, tax code). Exactly one of contact_id / contact_query.

        Returns:
            ToolResult dict whose result is a DraftReceipt (``reused`` True when a partial draft was completed).
        """
        # FILL IN: see Implementation Notes — bounded by AC-7, S11
        raise NotImplementedError

    async def hooba_create_purchase_invoice_draft(self, draft: PurchaseInvoiceDraft) -> dict:
        """Declare an expense / purchase as a purchase-invoice DRAFT (never confirmed)."""
        # FILL IN: envelope around _create_purchase_invoice — bounded by AC-7
        raise NotImplementedError

    async def _create_purchase_invoice(self, draft: PurchaseInvoiceDraft) -> DraftReceipt:
        """Idempotent purchase-invoice draft creation; the BBVA importer's DraftCreator."""
        # FILL IN — bounded by AC-7, S11
        raise NotImplementedError

    async def hooba_attach_document(self, entity: Literal["invoice", "purchase_invoice"], entity_id: int,
                                    file_path: str) -> dict:
        """Attach a file (receipt, ticket PDF) to an invoice or purchase invoice."""
        # FILL IN: multipart via aiohttp — bounded by S6
        raise NotImplementedError

    async def hooba_import_bbva_statement(self, path: str, period: str, dry_run: bool = True) -> dict:
        """Turn a BBVA movements Excel into purchase-invoice drafts (dry run by default).

        Args:
            path: Local path of the BBVA .xlsx export.
            period: Accounting period label, e.g. "2026-09".
            dry_run: When True, plan only — nothing is sent to Hooba.
        """
        # FILL IN — bounded by AC-11
        raise NotImplementedError

    # FILL IN: _resolve_tax(code, operation_type), _resolve_income_tax(code), _resolve_serie(code, simplified),
    #          _resolve_contact(contact_id, contact_query), _find_by_key(kind, key), _find_contacts_raw(query)
    #          (returns list[ContactMatch] for the importer) — private (leading underscore) so they are not tools
```

### `packages/ai-parrot-tools/tests/hooba/test_toolkit_drafts.py` (CREATE)
```python
"""FEAT-602 TASK-3743 — draft tools (fake transport, no HTTP)."""
import pytest

from parrot_tools.hooba import HoobaToolkit
from parrot_tools.hooba.models import InvoiceDraft, InvoiceLineDraft, PurchaseInvoiceDraft, PurchaseInvoiceLineDraft


class FakeHooba:
    """Scripted responses for _call keyed by (method, path); records every call."""
    # FILL IN


async def test_create_invoice_draft_resolves_ids_and_posts_lines():
    # FILL IN: lookups before POST; header then one POST per line; Product body type="product"


async def test_create_draft_rejects_non_draft_state():
    # FILL IN: GET returns state "issued" → error envelope (HoobaStateError)


async def test_create_draft_reuses_existing_by_correlation_key():
    # FILL IN: existing draft with [parrot:k] and 1 of 2 lines → only the missing line posted, reused=True (S11)


async def test_create_purchase_invoice_draft_simplified():
    # FILL IN


async def test_unresolvable_tax_is_error_not_guess():
    # FILL IN


async def test_attach_document_multipart(aiohttp_server, tmp_path):
    # FILL IN: tiny aiohttp app asserting multipart fields file + data, cookie sid, x-hooba-language


async def test_import_bbva_dry_run_posts_nothing(tmp_path, monkeypatch):
    # FILL IN: synthetic fixture (tests/hooba/fixtures/make_bbva_fixture.py); FakeHooba saw zero POSTs
```

### FILL IN checklist
- [ ] four tools, `_create_purchase_invoice`, resolvers, `_find_by_key`, `_find_contacts_raw`
- [ ] every test body

---

## Acceptance Criteria

- [ ] AC-7 (spec): both create tools resolve ids, post header + lines, verify `state == 'draft'`, refuse any other state, and are idempotent per `correlation_key`.
- [ ] AC-11 (spec, tool half): `hooba_import_bbva_statement(dry_run=True)` makes zero POSTs; `dry_run=False` creates the drafts and reports `reconciled`.
- [ ] AC-14 (spec): multipart upload via aiohttp; no httpx/requests import.
- [ ] No request outside `DRAFT_OPERATIONS`, the documents upload, and GETs; `ruff check` and `black --check` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_toolkit_drafts.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_create_invoice_draft_resolves_ids_and_posts_lines` | AC-7 |
| `test_create_draft_rejects_non_draft_state` | AC-7 |
| `test_create_draft_reuses_existing_by_correlation_key` | S11 |
| `test_create_purchase_invoice_draft_simplified` | capability 2 |
| `test_unresolvable_tax_is_error_not_guess` | never guess ids |
| `test_attach_document_multipart` | S6 |
| `test_import_bbva_dry_run_posts_nothing` | AC-11 |

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
