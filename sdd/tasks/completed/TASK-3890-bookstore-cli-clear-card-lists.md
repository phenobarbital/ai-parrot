# TASK-3890: CLI flags to clear authors and topics

**Feature**: FEAT-615 — Bookstore re-index via staging tree + atomic PageIndex rename
**Spec**: `sdd/specs/bookstore-reindex-atomic-swap.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1–2h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement M5 clear flags, validate conflicts before opening the library, recognize clear-only updates, and pass [] only for explicitly cleared fields.

## Scope

Implement M5 clear flags, validate conflicts before opening the library, recognize clear-only updates, and pass [] only for explicitly cleared fields.

**NOT in scope**: Other feature modules, cross-process locking, global delete_tree cleanup changes, dependencies or shared test configuration changes.

**Parallelism**: Consumes existing Bookstore.update_card support for empty lists; owns cli.py and test_cli.py. No new symbol dependency or shared-resource mutation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | CLI flags to clear authors and topics |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | Focused regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against current dev source; recheck after dependencies land.

### Verified Imports

```python
import click  # existing dependency in packages/ai-parrot/pyproject.toml
from typing import Optional
from click.testing import CliRunner
from parrot.knowledge.bookstore import cli as bookstore_cli
from parrot.knowledge.bookstore.library import BookstoreError
```

Standard-library additions need no dependency. pytest is already declared in the workspace; existing module imports were reread.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:379`: `def update_cmd(book_id: str, title: Optional[str], authors: tuple[str, ...], topics: tuple[str, ...], summary: Optional[str]) -> None:`
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1356`: `def update_card(self, book_id: str, *, title: Optional[str]=None, authors: Optional[list[str]]=None, topics: Optional[list[str]]=None, summary: Optional[str]=None) -> BookCard:`
- `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py:344`: `def test_update_command_edits_title(tmp_path, monkeypatch):`
- `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py:351`: `def test_update_command_without_fields_fails(tmp_path, monkeypatch):`

### Does NOT Exist

--clear-authors and --clear-topics are new. No change to Bookstore.update_card is needed: it already accepts [].

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#update_cmd",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.update_card",
    "sym:packages/ai-parrot/tests/knowledge/bookstore/test_cli.py#test_update_command_edits_title",
    "sym:packages/ai-parrot/tests/knowledge/bookstore/test_cli.py#test_update_command_without_fields_fails"
  ]
}
```

## Implementation Notes

Follow existing CLI update tests and CliRunner; use isolated library directories and no LLM. Check authors/topics persisted values, manual card origin, clear-only operations, both conflicts and existing no-field behavior.

No Delegation Contract: test bodies and failure branches still require implementation judgment. Blueprint gaps are planning instructions; completed code must contain no placeholders.

## Implementation Blueprint

### Steps (in order)

1. Add boolean Click options and typed parameters — clear-only updates must reach update_card.
2. Reject --clear-authors plus --author and --clear-topics plus --topic before writes — conflicting intent must never modify a card.
3. Preserve None for unchanged fields and [] for clearing — update_card distinguishes those values.
4. Exercise persisted CLI results and no-field errors — parsing alone does not prove lists were cleared.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` (MODIFY)

- `@click.option("--summary", default=None, help="New summary.")` — packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:378, occurrences: 1 (verified with `grep -F -c`).
- `    if title is None and not authors and not topics and summary is None:` — packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:389, occurrences: 1 (verified with `grep -F -c`).

```python
# Insert options immediately after the existing --summary option.
@click.option("--clear-authors", is_flag=True, help="Remove all authors.")
@click.option("--clear-topics", is_flag=True, help="Remove all topics.")
def update_cmd(
    book_id: str,
    title: Optional[str],
    authors: tuple[str, ...],
    topics: tuple[str, ...],
    summary: Optional[str],
    clear_authors: bool,
    clear_topics: bool,
) -> None:
    """Edit ficha fields without re-indexing; clear flags remove list values."""
    from .library import BookstoreError
    # FILL IN: conflicts before opening the store — AC2.
    # FILL IN: existing no-op guard also checks not clear_authors/not clear_topics — AC1.
    # Retain existing store open / try / except / _echo_card wiring.
    # In store.update_card use:
    # authors=[] if clear_authors else (list(authors) or None),
    # topics=[] if clear_topics else (list(topics) or None),
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` (MODIFY)

- `def test_update_command_edits_title(tmp_path, monkeypatch):` — packages/ai-parrot/tests/knowledge/bookstore/test_cli.py:344, occurrences: 1 (verified with `grep -F -c`).

```python
# Append after existing update command tests. Reuse CliRunner and environment setup.
def test_cli_update_clear_authors_topics(tmp_path, monkeypatch) -> None:
    """Clear both persisted lists with one CLI update."""
    # FILL IN: populate nonempty lists, invoke clear flags, inspect persisted card — AC1.

def test_cli_update_clear_single_list_preserves_other(tmp_path, monkeypatch) -> None:
    """Clear-only calls work and preserve the unspecified list."""
    # FILL IN: cover each flag separately — AC1/AC3.

def test_cli_update_clear_flags_conflict(tmp_path, monkeypatch) -> None:
    """Matching replacement and clear options fail before any write."""
    # FILL IN: cover both conflicts, nonzero result and unchanged persisted lists — AC2.
```

**Why**: Preserve the verified surrounding code; implement only this file’s assigned behavior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` — complete its bounded blueprint and regression assertions; obey the acceptance criteria below.

## Acceptance Criteria

- [ ] AC1: bookstore update ID --clear-authors --clear-topics persists empty lists and manual origin. Either flag alone is a valid operation.
- [ ] AC2: Each clear flag conflicts with its matching repeated option and returns a clear ClickException without updating a card.
- [ ] AC3: Unspecified list fields remain unchanged; repeated author/topic replacement and existing no-field errors still work.
- [ ] Run black (120 columns) and ruff check on touched Python files; retain existing unrelated formatting. Store validation logs in artifacts/logs/.

## Validation Commands

Activate the project venv and export `PYTHONPATH=packages/ai-parrot/src` before running these commands.

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_cli.py -q`

## Test Specification

Follow existing CLI update tests and CliRunner; use isolated library directories and no LLM. Check authors/topics persisted values, manual card origin, clear-only operations, both conflicts and existing no-field behavior.

## Agent Instructions

1. Use `$sdd-start TASK-3890` to provision the feature worktree. Never implement on dev.
2. Read the spec and check dependencies are done in `sdd/tasks/index/bookstore-reindex-atomic-swap.json`.
3. Reverify contracts, set in-progress state and implement only declared files.
4. Complete all blueprint gaps, run file-scoped validations and commit scoped code.
5. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the implementation HEAD; it owns the completion note and active-to-completed move. Commit SDD state separately. Do not manually close the ledger issue; FEAT-615 closeout owns that evidence.

## Completion Note

Pending; populated by finalize_task after verified implementation.

## Completion Note

Merged by sdd-worker. Reviewed diff against task scope; files match the task list. Feature-scoped tests: 205 passed. Merge-tier validation was red for environmental reasons only (worktree cannot import main-checkout .so modules; test_integration_graph.py sqlite "unable to open database file" also fails on origin/dev). Evidence accepted by the user.
