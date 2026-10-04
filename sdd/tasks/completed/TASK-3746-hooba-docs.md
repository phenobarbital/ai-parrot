# TASK-3746: docs/hooba-toolkit.md + business-automation runbook §8 (env, spec pin, private catalog, dry-run import)

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3743
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11** (docs half), AC-16. Operators need one page: what the toolkit does
(drafts only), how to configure it (`HOOBA_*`), how the spec pin is refreshed, how the
private Playwright catalog is seeded and located, how a BBVA import is run safely
(dry run first), and what is deliberately impossible (issue/confirm).

---

## Scope

- `docs/hooba-toolkit.md`: overview, env table, tool list with OperationKind, spec pin + prune CLI, private catalog and
  `seed_catalog`, BBVA dry-run walkthrough, rule table caveats (review_required, gestoría sign-off), troubleshooting
  (401 / session recovery, `HoobaLookupError`), security notes.
- `docs/business-automation-runbook.md`: new `## 8. Hooba toolkit` section at the end linking the page.

**NOT in scope**: code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/hooba-toolkit.md` | CREATE | operator + developer guide |
| `docs/business-automation-runbook.md` | MODIFY | append §8 Hooba toolkit |
| `packages/ai-parrot-tools/tests/hooba/test_docs.py` | CREATE | the page names every tool HoobaToolkit exposes |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# none — documentation only
```

### Existing Signatures to Use
```python
# docs/business-automation-runbook.md — 235 lines; last section is line 225:
#   "## 7. Scheduled canary (`SmokeCheck`, Decision D4)"   (occurrences: 1)
```

### Does NOT Exist
- ~~Documenting `:issue` / `:confirm` usage~~ — not possible in v1; say so explicitly.
- ~~Real credentials, account ids, selectors or bank data in examples~~ — use placeholders (`23549` is the spec's example id; prefer `<your-account-id>`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/hooba-toolkit.md",
      "action": "CREATE"
    },
    {
      "path": "docs/business-automation-runbook.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_docs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Take the tool list from `HoobaToolkit.operation_kinds()` as implemented (run it in a REPL), not from memory.
- State the spec pin version (`2026.6.17`) and the regenerate command; state that `uv lock` is run in the main checkout.

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
1. Write the page — *why*: AC-16.
2. Append runbook §8 — *why*: operators already read the business-automation runbook.

### `docs/hooba-toolkit.md` (CREATE)
```markdown
# HoobaToolkit

Drafts-only automation of Hooba (app.hooba.com) for AI-Parrot agents (FEAT-602).

## What it does / what it never does
<!-- FILL IN: three capabilities; never issues, confirms, cancels, sends or deletes -->

## Configuration
<!-- FILL IN: table of HOOBA_* variables (required/optional, default, purpose); credentials via CredentialBroker -->

## Tools
<!-- FILL IN: composite tools + generated tools summary, each with its OperationKind -->

## The pinned API document
<!-- FILL IN: version 2026.6.17, sha pin, `python -m parrot_tools.hooba.spec.prune ...` -->

## Browser fallback (private catalog)
<!-- FILL IN: HOOBA_CATALOG_DIR, seed_catalog(), session recovery, navigation-only -->

## Importing a BBVA statement
<!-- FILL IN: dry run → review → apply; manifest location; resume; reconcile -->

## Deductibility rules (autonomo_es_v1)
<!-- FILL IN: every verdict review_required; legal_basis; gestoría sign-off pending -->

## Troubleshooting
<!-- FILL IN -->
```

### `docs/business-automation-runbook.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## 7. Scheduled canary' docs/business-automation-runbook.md) — line 225 -->
<!-- APPEND at end of file (after the §7 section, which is the last one): -->

## 8. Hooba toolkit

<!-- FILL IN: 5–10 lines: what it is, drafts only, link to docs/hooba-toolkit.md, HOOBA_CATALOG_DIR is private -->
```

### `packages/ai-parrot-tools/tests/hooba/test_docs.py` (CREATE)
```python
"""FEAT-602 TASK-3746 — the operator page stays in sync with the toolkit."""
from pathlib import Path

DOC = Path(__file__).resolve().parents[4] / "docs" / "hooba-toolkit.md"
COMPOSITE = ("hooba_whoami", "hooba_find_contact", "hooba_list_drafts", "hooba_download_invoice_pdf",
             "hooba_recover_web_session", "hooba_run_web_action", "hooba_create_invoice_draft",
             "hooba_create_purchase_invoice_draft", "hooba_attach_document", "hooba_import_bbva_statement")


def test_docs_name_every_composite_tool():
    text = DOC.read_text(encoding="utf-8")
    missing = [name for name in COMPOSITE if name not in text]
    assert not missing, missing


def test_docs_state_drafts_only_and_spec_pin():
    # FILL IN: "2026.6.17" in text; the never-issue/confirm statement present
```

### FILL IN checklist
- [ ] every section of the page
- [ ] runbook §8
- [ ] `test_docs_state_drafts_only_and_spec_pin`

---

## Acceptance Criteria

- [ ] AC-16 (spec, docs half): the page documents env vars, the spec pin, the private catalog contract, the seed helper and the dry-run import; the runbook links it.
- [ ] No real credentials, selectors or personal data in the docs.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_docs.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_docs_name_every_composite_tool` | every composite tool name in `HoobaToolkit.operation_kinds()` (`hooba_whoami` … `hooba_import_bbva_statement`) appears in `docs/hooba-toolkit.md` |
| `test_docs_state_drafts_only_and_spec_pin` | the page contains `2026.6.17` and states that issue/confirm are impossible |

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

**Completed by**: sdd-worker (seat=glm, backend=nova, model=zai.glm-4.7-flash,
attempt_uid=0b85a1fd220f48af999a85dd9c03e088, execution_id=85c083ec-56b6-42fe-8884-e686fbcf7a61)
**Date**: 2026-09-26
**Notes**: `docs/hooba-toolkit.md` + business-automation runbook §8 (env, spec pin, private
catalog, dry-run import). Attempt 1 on `zai.glm-5` timed out
(`APITimeoutError: Request timed out`, an infra/provider issue unrelated to the task) and
retried automatically on `zai.glm-4.7-flash`, which completed cleanly (0 lint residuals).
Full hooba suite green post-merge.

**Deviations from spec**: none.

**Deviations from spec**: none | describe if any
