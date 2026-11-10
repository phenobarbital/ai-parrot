# TASK-5472: Bookstore API and CLI `--pdf-backend` wiring

**Feature**: FEAT-875 — Optional PyMuPDF Layout for Bookstore PDF Ingestion
**Spec**: `sdd/specs/bookstore-pymupdf-layout.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5471
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. This forwards the explicit PDF extractor choice from the user to
`PageIndexToolkit.import_pdf(pdf_backend=...)`, which TASK-5471 created. There are three forwarding
paths, and **all three** must carry it:

1. `bookstore add` CLI → `store.add_book` (`cli.py:143`)
2. `bookstore add-folder` CLI → its **own independent** `store.add_book` loop (`cli.py:225`). It does **not** call `store.add_folder`.
3. `Bookstore.add_folder` → `self.add_book` loop (`library.py:1856`)

## Scope

- `Bookstore.add_book(..., *, relate=False, pdf_backend="legacy")`. Reject unknown names with
  `BookstoreError` before ingestion. Forward to `toolkit.import_pdf` **only** for PDFs, since non-PDF
  formats ignore any valid backend. Keep SHA dedupe, staging, `force`, rollback, and the
  `PDFStructureError → BookstoreError` conversion exactly as they are.
- `Bookstore.add_folder(..., *, relate=False, pdf_backend="legacy")` forwards per file.
- CLI: a `--pdf-backend` option with `click.Choice(["legacy", "pymupdf-layout"])`, default `legacy`, on both
  `add` and `add-folder`. The callbacks gain a trailing `pdf_backend` parameter.
  `--dry-run` must return **before** any extraction or child spawn (it already returns before
  `_open_bookstore`, so keep the new code below that return). The help text must say that switching
  extractors on an unchanged book requires `--force`.
- Create `tests/knowledge/bookstore/test_pdf_backend.py`: CLI forwarding for both commands, manager
  `add_folder` forwarding, unknown-name rejection, non-PDF passthrough, SHA-skip without `--force`, and
  no worker on dry-run. Mock `store.add_book` and the toolkit throughout, with no real extraction.

**NOT in scope**: the PageIndex routing (TASK-5471), native integration tests (TASK-5473), any new MCP write tool, and catalog schema fields.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `add_book` / `add_folder` keyword + forwarding |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `--pdf-backend` on `add` and `add-folder` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_pdf_backend.py` | CREATE | Forwarding/validation tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.pageindex.layout import PDFStructureError       # verified: library.py:32
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit        # verified: library.py:35
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError   # verified: cli.py:198 (local import)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1426
async def add_book(self, file_path: str | Path, scope: str = "project", title: Optional[str] = None,
                   authors: Optional[list[str]] = None, topics: Optional[list[str]] = None,
                   force: bool = False, *, relate: bool = False) -> tuple[BookCard, str]: ...
#   library.py:1502-1512 — `if fmt == "pdf":` then `result = await toolkit.import_pdf(tree_name=staging,
#       pdf_path=str(path), with_summaries=..., with_doc_description=..., structure_mode=...)`
#       `except PDFStructureError as exc: raise BookstoreError(f"Cannot index {path.name}: {exc}") from exc`
# library.py:1814
async def add_folder(self, folder: str | Path, scope: str = "project", recursive: bool = False,
                     force: bool = False, *, relate: bool = False) -> dict[str, Any]: ...
#   library.py:1856 — `card, status = await self.add_book(path, scope=scope, force=force, relate=relate)`

# packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py
# :103 @bookstore.command("add") ... :117 def add(file, global_scope, title, authors, topics, force, no_llm, relate, llm)
# :143 store.add_book(file, scope=scope, title=..., authors=..., topics=..., force=force, relate=relate)
# :159 @bookstore.command("add-folder") ... :176 def add_folder(folder, recursive, global_scope, force, no_llm, relate, llm, dry_run)
# :204 `if dry_run:` (returns before _open_bookstore)
# :225 card, status = await store.add_book(path, scope=scope, force=force, relate=relate)
# PageIndexToolkit.import_pdf(..., *, pdf_backend: str = "legacy")  — created by TASK-5471
```

### Does NOT Exist

- No `pdf_backend` parameter or `--pdf-backend` option in Bookstore today.
- The `add-folder` CLI does **not** call `Bookstore.add_folder`. It has its own loop, and both must be wired.
- No catalog field records the backend, and none is added (spec §2: logs only).

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/bookstore/test_pdf_backend.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_folder",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#add",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#add_folder",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_pdf"
  ]
}
```

## Implementation Notes

### Key Constraints

- Validate the name **before** the SHA lookup, so an unknown name fails before ingestion. A valid name
  must not bypass the SHA skip, so the preflight must not force regeneration (spec §3 M4).
- Do not run a dependency preflight that spawns the child on dry-run, or on an unchanged-source skip.

## Implementation Blueprint

### Steps (in order)

1. `library.py`: add a module-level `_PDF_BACKENDS` constant plus the keyword on both methods, and forward it.
2. `cli.py`: add the option and parameter to both commands, and forward it in both `store.add_book` calls.
3. Write the tests.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)

```python
# add_book signature — occurrences of anchor 1 (verified: grep -c 'async def add_book(' library.py)
# REPLACE `        relate: bool = False,\n    ) -> tuple[BookCard, str]:` (verified: library.py:1435-1436)
        relate: bool = False,
        pdf_backend: str = "legacy",
    ) -> tuple[BookCard, str]:
# + docstring Args line:
#   pdf_backend: PDF text extractor, "legacy" (default) or "pymupdf-layout". Ignored for non-PDF
#       files. Switching extractors on an unchanged file requires ``force=True`` (sha256 dedupe).
```

```python
# FILL IN: early in add_book's body, before the sha256/catalog lookup:
#   if pdf_backend not in _PDF_BACKENDS: raise BookstoreError(f"Unknown pdf_backend {pdf_backend!r}; ...")
#   — bounded by "unknown names fail before ingestion"
```

```python
# occurrences: 1 (verified: grep -c 'structure_mode="auto" if self.has_llm else "layout",' library.py)
# AFTER — insert below `                            structure_mode="auto" if self.has_llm else "layout",` (verified: library.py:1509)
                            pdf_backend=pdf_backend,
```

```python
# add_folder — REPLACE `        relate: bool = False,\n    ) -> dict[str, Any]:` (verified: library.py:1821-1822)
        relate: bool = False,
        pdf_backend: str = "legacy",
    ) -> dict[str, Any]:
# occurrences: 1 (verified: grep -c 'await self.add_book(path, scope=scope, force=force, relate=relate)' library.py)
# REPLACE library.py:1856
                card, status = await self.add_book(
                    path, scope=scope, force=force, relate=relate, pdf_backend=pdf_backend
                )
```

**Why:** forwarding only inside the `fmt == "pdf"` branch makes non-PDF files ignore the option for free.
FILL IN: a matching `pdf_backend` Args line in `add_folder`'s docstring. Note that
`relate: bool = False,` occurs more than once in the file. Disambiguate each REPLACE by the following
`) -> tuple[BookCard, str]:` or `) -> dict[str, Any]:` line.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` (MODIFY)

```python
# `add` — AFTER the `--llm` option block of @bookstore.command("add") (verified: cli.py:111-115),
#   before `def add(` (cli.py:117). occurrences of `def add(`: 1
@click.option(
    "--pdf-backend",
    type=click.Choice(["legacy", "pymupdf-layout"]),
    default="legacy",
    show_default=True,
    help="PDF text extractor. Switching extractors on an unchanged book requires --force.",
)
# signature: append `    pdf_backend: str = "legacy",` after `    llm: Optional[str],` (cli.py:126)
# store.add_book call at cli.py:143 — add `pdf_backend=pdf_backend,` after `relate=relate,` (cli.py:150)
```

```python
# `add-folder` — same option, inserted after `@click.option("--dry-run", ...)` (verified: cli.py:175)
# signature: append `    pdf_backend: str = "legacy",` after `    dry_run: bool,` (cli.py:184)
# occurrences of `store.add_book(`: 2 (verified: grep -c 'store.add_book(' cli.py) — the add-folder one is
#   the single-line call inside `async def _run()` (cli.py:225); REPLACE it with:
                card, status = await store.add_book(
                    path, scope=scope, force=force, relate=relate, pdf_backend=pdf_backend
                )
```

**Why:** `store.add_book(` occurs twice, so target the `_run()` loop one by its single-line
form. Do not touch the multi-line call at `:143` with this edit. The option sits below the
`dry_run` early return in flow terms, so dry-run never spawns a worker.

### `packages/ai-parrot/tests/knowledge/bookstore/test_pdf_backend.py` (CREATE)

```python
"""Bookstore --pdf-backend forwarding tests (FEAT-875)."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from parrot.knowledge.bookstore import cli as bookstore_cli


def test_cli_pdf_backend_forwarding(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Both add commands pass the choice; dry-run does not initialize extraction."""
    # FILL IN: fake _open_bookstore returning a stub whose async add_book records kwargs;
    #          invoke `add` and `add-folder` with --pdf-backend pymupdf-layout; assert recorded value;
    #          invoke `add-folder --dry-run` and assert add_book / _open_bookstore never called
    ...


# FILL IN: test_cli_rejects_unknown_backend (Click exit code 2)
# FILL IN: test_manager_add_folder_forwards_backend (patch Bookstore.add_book)
# FILL IN: test_add_book_rejects_unknown_backend_before_ingest (BookstoreError, toolkit untouched)
# FILL IN: test_non_pdf_ignores_backend (md file: import_pdf never called)
# FILL IN: test_unchanged_source_skips_without_force (status "skipped", import_pdf not called)
```

**Why:** these are the CLI/force/dry-run rows of spec §4 Unit Tests. Reuse fixtures from the existing
`tests/knowledge/bookstore/conftest.py` rather than inventing new library setup.

### FILL IN checklist

- [ ] Early `BookstoreError` validation in `add_book`
- [ ] `add_folder` docstring
- [ ] Six tests

## Acceptance Criteria

- [ ] `add`, the CLI `add-folder`, and the manager `add_folder` all forward `pdf_backend`. The default is `legacy`.
- [ ] Unknown names fail before ingestion (Click choice on the CLI, `BookstoreError` in Python).
- [ ] `--dry-run` spawns no worker. Unchanged sources are still skipped without `--force`.
- [ ] Existing `test_cli.py` and `test_library.py` pass unchanged.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_pdf_backend.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`

## Test Specification

See the blueprint. Everything is mocked: no PDF extraction, no Layout package, no LLM.

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**: `parrot sdd worktree ensure --slug bookstore-pymupdf-layout --feature-id FEAT-875`
2. **Read the spec** at the path listed above.
3. **Check dependencies**: TASK-5471 must be `"done"`.
4. **Verify the Codebase Contract**. Re-check every line number, because TASK-5471 does not touch these files but others may.
5. **Update status** to `"in-progress"` and commit only the index file.
6. **Implement** from the blueprint, completing every `FILL IN`.
7. **Verify**: run the Validation Commands.
8. **Commit** only the files this task lists.
9. **Close** with `parrot sdd task close TASK-5472 bookstore-pymupdf-layout verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
