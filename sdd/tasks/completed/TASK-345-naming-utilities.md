# TASK-345: Create Name Slugification & Deduplication Utilities

**Feature**: API Bot Creation — Normalization & Provisioning
**Feature ID**: FEAT-049
**Spec**: `sdd/specs/new-api-bot-creation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Foundation task for FEAT-049. Creates the reusable naming utility module that TASK-347 will import into the handler.
> Implements spec Section 3 — Module 1.

---

## Scope

- Create `parrot/utils/naming.py` with two functions:

### `slugify_name(name: str) -> str`
- Strip leading/trailing whitespace.
- Lowercase the string.
- Replace any non-alphanumeric character (except hyphens) with a hyphen using `re.sub(r'[^a-z0-9-]+', '-', ...)`.
- Collapse consecutive hyphens: `re.sub(r'-{2,}', '-', ...)`.
- Strip leading/trailing hyphens.
- Raise `ValueError("Name produces an empty slug after normalization")` if result is empty.
- Return the slug.

### `deduplicate_name(slug: str, exists_fn: Callable[[str], Awaitable[Optional[str]]]) -> str`
- `exists_fn` is an async callable that returns a source string (e.g., `"database"`) if the name exists, or `None` if free.
- Call `await exists_fn(slug)`. If `None`, return slug.
- Otherwise iterate `f"{slug}-{i}"` for `i` in `range(2, 100)`.
- Return the first candidate where `exists_fn` returns `None`.
- Raise `ValueError(f"Cannot deduplicate '{slug}': all suffixes up to -99 are taken")` if exhausted.

**NOT in scope**: Handler integration (TASK-347), registry cleanup (TASK-346), vector store provisioning (TASK-348).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/utils/naming.py` | CREATE | `slugify_name()` and `deduplicate_name()` functions |
| `tests/test_naming.py` | CREATE | Unit tests (10 test cases from spec Section 3 — Module 3) |

---

## Implementation Notes

- Use only `re` from stdlib — no external `python-slugify` dependency.
- `deduplicate_name` is async because `exists_fn` (the handler's `_check_duplicate`) is async.
- Type hints: `from typing import Callable, Awaitable, Optional`.

---

## Tests to Write

| Test | Input | Expected |
|---|---|---|
| `test_slugify_name_basic` | `"My Cool Bot"` | `"my-cool-bot"` |
| `test_slugify_name_special_chars` | `"Bot @#$ Test!"` | `"bot-test"` |
| `test_slugify_name_consecutive_hyphens` | `"Bot - - Test"` | `"bot-test"` |
| `test_slugify_name_trim` | `"  My Bot  "` | `"my-bot"` |
| `test_slugify_name_empty_raises` | `"@#$"` | `ValueError` |
| `test_slugify_name_already_slug` | `"my-bot"` | `"my-bot"` |
| `test_slugify_name_underscores` | `"my_bot_name"` | `"my-bot-name"` |
| `test_deduplicate_no_conflict` | slug free | unchanged slug |
| `test_deduplicate_one_conflict` | slug taken | `"slug-2"` |
| `test_deduplicate_multiple` | slug, slug-2, slug-3 taken | `"slug-4"` |
| `test_deduplicate_exhaustion` | all 1-99 taken | `ValueError` |

---

## Acceptance Criteria

- [x] `parrot/utils/naming.py` exists with both functions.
- [x] All 11 unit tests pass with `pytest tests/test_naming.py`.
- [x] `slugify_name` is idempotent: `slugify_name("my-bot") == "my-bot"`.
- [x] No external dependencies added.
