# TASK-3741: BbvaImporter: plan (dry run) and apply (awaited, resumable, idempotent) BBVA rows → purchase-invoice drafts

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3739, TASK-3740
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10**, U3, design research S9 and S11. Turns a parsed statement into one
`simplified` purchase-invoice draft per debit row. Contacts are only linked when a
Hooba contact matches with score ≥ 0.85; otherwise `contact_id=None` and the note says so.
`apply` awaits each draft creation and records a row as complete in the manifest only
after its `DraftReceipt` is returned (never fire-and-forget: this path does not use
`BusinessAutomationToolkit.run_operation`). Each draft carries `correlation_key=row_id`
so a crash between the header and line POSTs is healed by the toolkit's reuse scan.

The importer is transport-agnostic: `find_contact` and `create_draft` are injected
callables (the toolkit wires them in TASK-3743), so these tests need no HTTP.

---

## Scope

- `hooba/importer.py`: `ContactFinder`, `DraftCreator`, `PlannedDraft`, `BbvaImporter` (`plan`, `apply`).
- `tests/hooba/test_importer.py` using the synthetic fixture and fake callables.

**NOT in scope**: the agent-facing tool (TASK-3743), HTTP.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/hooba/importer.py` | CREATE | BbvaImporter + PlannedDraft |
| `packages/ai-parrot-tools/tests/hooba/test_importer.py` | CREATE | dry-run, idempotency, resume tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot_tools.hooba.models import (BankExpenseRow, BbvaStatement, ContactMatch, DeductibilityVerdict,
                                       DraftReceipt, PurchaseInvoiceDraft, PurchaseInvoiceLineDraft)   # TASK-3733
from parrot_tools.hooba.bank import ImportManifest, load_manifest, write_manifest   # TASK-3739
from parrot_tools.hooba.rules import RuleEngine                                  # TASK-3740
```

### Existing Signatures to Use
```python
# TASK-3739: load_manifest(digest) -> Optional[ImportManifest]; write_manifest(m) -> Path  (both SYNC — call via asyncio.to_thread)
#            ImportManifest(statement_digest, period, started_at, row_count, completed: Dict[str, int], skipped: Dict[str, str])
# TASK-3740: RuleEngine.assess(row, *, period) -> Optional[DeductibilityVerdict]   (None ⇒ rule.skip)
#            DeductibilityVerdict.hooba: HoobaMapping(category, tax_code, subject_to_income_tax, income_tax_code, simplified, ...)
# tests: tests/hooba/fixtures/make_bbva_fixture.py::build_bbva_workbook(path) -> Path   (TASK-3739)
```

### Does NOT Exist
- ~~`BusinessAutomationToolkit.run_operation` / `ingest.build_import_plan`~~ in this path — they are fire-and-forget and browser-bound (S9 was rejected precisely because FEAT-602 does not use them).
- ~~Contact creation~~ — never; unmatched merchants stay `contact_id=None` (U3, spec non-goals).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/importer.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_importer.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `plan`: load (or create) the manifest via `asyncio.to_thread`; rows already in `manifest.completed` are skipped silently;
  `verdict is None` → `skipped[row_id] = "rule.skip"`; best contact = first of `await find_contact(row.concept)` with
  `score >= 0.85` (the finder returns candidates sorted desc).
- Draft: `date=row.booking_date`, `simplified=verdict.hooba.simplified`, `contact_id`, `tax_included=True`,
  `subject_to_income_tax=verdict.hooba.subject_to_income_tax`, `correlation_key=row.row_id`,
  `notes=f"BBVA {row.row_id} · {row.concept} · {verdict.legal_basis} · review_required={verdict.review_required}"`
  plus `" · contact: none (no match ≥ 0.85)"` when unmatched, one line `name=row.concept`, `price=abs(row.amount)`,
  `tax_code=verdict.hooba.tax_code`, `income_tax_code=verdict.hooba.income_tax_code`,
  `accounting_account_code=verdict.hooba.accounting_account_code`.
- `apply`: sequential; `receipt = await create_draft(p.draft)`; then `manifest.completed[row_id] = receipt.id` and
  `await asyncio.to_thread(write_manifest, manifest)`; an exception propagates (progress already persisted).

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
1. Write the importer with injected callables — *why*: testable without HTTP; the toolkit owns transport.
2. Tests: dry-run plan, second plan after apply skips completed rows, failure mid-apply then resume.

### `packages/ai-parrot-tools/src/parrot_tools/hooba/importer.py` (CREATE)
```python
"""BBVA statement → purchase-invoice drafts (FEAT-602 M10). Transport-agnostic."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel

from .bank import ImportManifest, load_manifest, write_manifest
from .models import (
    BankExpenseRow, BbvaStatement, ContactMatch, DeductibilityVerdict, DraftReceipt, PurchaseInvoiceDraft,
    PurchaseInvoiceLineDraft,
)
from .rules import RuleEngine

logger = logging.getLogger(__name__)

ContactFinder = Callable[[str], Awaitable[list[ContactMatch]]]
DraftCreator = Callable[[PurchaseInvoiceDraft], Awaitable[DraftReceipt]]
CONTACT_THRESHOLD = 0.85


class PlannedDraft(BaseModel):
    """One bank row, its verdict, and the draft it will become."""

    row: BankExpenseRow
    verdict: DeductibilityVerdict
    draft: PurchaseInvoiceDraft
    contact: Optional[ContactMatch] = None


class BbvaImporter:
    """Plan and apply BBVA rows as Hooba purchase-invoice drafts."""

    def __init__(self, engine: RuleEngine, find_contact: ContactFinder, create_draft: DraftCreator) -> None:
        self._engine = engine
        self._find_contact = find_contact
        self._create_draft = create_draft

    async def plan(self, statement: BbvaStatement, *, period: str
                   ) -> tuple[list[PlannedDraft], ImportManifest, list[dict]]:
        """Build drafts for rows not yet completed; returns (planned, manifest, skipped)."""
        manifest = await asyncio.to_thread(load_manifest, statement.digest)
        if manifest is None:
            manifest = ImportManifest(statement_digest=statement.digest, period=period,
                                      started_at=dt.datetime.now(dt.timezone.utc), row_count=statement.row_count)
        # FILL IN: per Implementation Notes — build PlannedDraft list and skipped [{row_id, reason}];
        #          record skips in manifest.skipped — bounded by AC-11, U3
        raise NotImplementedError

    async def apply(self, planned: list[PlannedDraft], manifest: ImportManifest) -> list[DraftReceipt]:
        """Create drafts sequentially; persist progress after each receipt (never before)."""
        # FILL IN: per Implementation Notes — bounded by AC-11, S9
        raise NotImplementedError
```

### `packages/ai-parrot-tools/tests/hooba/test_importer.py` (CREATE)
```python
"""FEAT-602 TASK-3741 — BBVA importer."""
import itertools

import pytest

from parrot_tools.hooba.bank import load_manifest, parse_bbva_statement
from parrot_tools.hooba.importer import BbvaImporter
from parrot_tools.hooba.models import ContactMatch, DraftReceipt
from parrot_tools.hooba.rules import RuleEngine
from .fixtures.make_bbva_fixture import build_bbva_workbook


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_STATE_DIR", str(tmp_path / "state"))


async def test_importer_plan_dry_run_idempotent(tmp_path):
    # FILL IN: plan twice without apply → same planned rows; TRASPASO skipped; MOVISTAR linked only if score ≥ 0.85


async def test_importer_contact_threshold(tmp_path):
    # FILL IN: finder returns 0.84 → contact_id None + note; 0.85 → linked


async def test_importer_apply_resumes_after_failure(tmp_path):
    # FILL IN: creator raises on the 3rd call → manifest has 2 completed; re-plan + apply creates only the rest


async def test_drafts_carry_row_id_as_correlation_key(tmp_path):
    # FILL IN (S11)
```

### FILL IN checklist
- [ ] `plan`, `apply`
- [ ] every test body

---

## Acceptance Criteria

- [ ] AC-11 (spec, importer half): one simplified purchase-invoice draft per debit row; `contact_id` only when a match scores ≥ 0.85; a row is marked complete only after its receipt; resume creates no duplicates.
- [ ] Every planned draft has `correlation_key == row.row_id`.
- [ ] `ruff check` and `black --check` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_importer.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_importer_plan_dry_run_idempotent` | plan purity, skips |
| `test_importer_contact_threshold` | U3 |
| `test_importer_apply_resumes_after_failure` | resume without duplicates |
| `test_drafts_carry_row_id_as_correlation_key` | S11 |

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

**Completed by**: sdd-worker (native sonnet coder, attempt_uid=45ccc09735e8450fa0383c396af02d61,
assessment_id=90d834040003211c939f44d1184fe4fc6d56d25bfb43adc0fc4e54dc622f4e17,
execution_id=85c083ec-56b6-42fe-8884-e686fbcf7a61)
**Date**: 2026-09-26
**Notes**: `BbvaImporter.plan`/`apply` implemented exactly per the Codebase Contract
(`ImportManifest`/`load_manifest`/`write_manifest`, `RuleEngine.assess`, all model fields,
`parse_bbva_statement`). Delivered `hooba/importer.py` + `tests/hooba/test_importer.py`
only — no unlisted files (explicitly checked against a prior confirmed defect on this same
backend/model, TASK-3421 `unlisted-file-added`, via `git status --porcelain
--untracked-files=all` before/after commit).

**Dispatch history / merge anomaly**: TASK-3741 first went to two MCP codex seats
(`gpt-5.6-terra` then `gpt-5.6-luna`), both of which failed immediately with a provider
auth error (`401 Unauthorized: Incorrect API key provided`) — an infra/provider outage,
not a task issue; the whole codex backend was down. Replanning routed it to a native
`sonnet` seat, which delivered correctly (`commit 402e16639` on branch
`...--TASK-3741-a1-85c083ec...`, validated: 4/4 new tests passed, `ruff check` clean).
However, `coder_merge` repeatedly (2x) resolved to attempt 2 (the empty, failed codex
`gpt-5.6-luna` branch, diagnostics=`empty_delivery`) instead of the native attempt's real
branch — the engine's "latest attempt" resolution did not pick up the native delivery.
`coder_record_native_observation` was attempted to reconcile this but was rejected with
`invalid tool arguments` (schema not discoverable from the tool description alone; did not
guess further to avoid corrupting engine state). Given verified evidence (file-fidelity
clean diff of exactly the 2 declared files against current HEAD, the native coder's own
contract-verified report, and a direct re-run: 46/46 hooba tests passing, ruff clean after
merge), merged the real branch manually
(`git merge --no-ff feat-FEAT-602-hooba-toolkit--TASK-3741-a1-...`), ran
`ruff check --fix` + `black` (engine's normal auto-format step, committed separately as
`style(hooba-toolkit): TASK-3741 — lint/format autofix`), and closed state via
`scripts/sdd/close_task.sh`.

**Deviations from spec**: none in the delivered code. Process deviation only: merge and
state-closure were done manually instead of via `coder_merge`/`finalize_task`, for the
reasons above (codex provider outage + engine attempt-tracking anomaly + a documented,
pre-existing sandbox limitation blocking `finalize_task.py` inside a worktree — see
TASK-3740's Completion Note for the latter).

Review recorded via `coder_record_review` (feedback_id=coder-review:9ea69330752edd9e890ab1ad),
zero corrections needed.
