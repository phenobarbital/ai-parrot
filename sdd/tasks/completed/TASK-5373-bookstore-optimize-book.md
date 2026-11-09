# TASK-5373: Bookstore.optimize_book and `bookstore optimize` command

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5371
**Assigned-to**: unassigned

---

## Context

Spec Module 5, Bookstore half (G12, AC-13). New books are already optimized at import (TASK-5370); existing books opt in.

## Scope

- `Bookstore.optimize_book(book_id, *, apply=False, llm_passes=None)` before `refresh_card`; when applied, re-derive
  `toc`, `toc_digest`, `chapter_count`, `page_count` and upsert the card (same fields `refresh_card` recomputes).
- `bookstore optimize BOOK_ID [--global] [--apply] [--no-llm] [--llm SPEC] [--json]` before `remove`.
- Test (bookstore half of `test_optimize_book_and_cli`).

**NOT in scope**: `parrot pageindex optimize` (TASK-5374); `add_book` (no change).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | optimize_book |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | bookstore optimize |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py` | CREATE | test_optimize_book_and_cli (bookstore half) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError, _NullAdapter  # library.py:179,112,150
from parrot.knowledge.bookstore.carding import derive_toc  # carding.py:124
```

### Existing Signatures to Use
```python
# library.py:216 has_llm (property: adapter is not None); :234 _toolkit(self, scope) -> PageIndexToolkit
# library.py:1460 async def refresh_card(self, book_id: str) -> BookCard  — resolve_book :1462, derive_toc :1464, upsert :~1500
# carding.py:124 derive_toc(tree, max_depth=2) -> tuple[list[TocEntry], str]
# cli.py: click group `bookstore` :98; `add` :102-155 shows the --no-llm/--llm/--global option pattern; `remove` :569
```

### Does NOT Exist
- ~~`Bookstore.optimize_book`~~, ~~`bookstore optimize`~~ — new here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.refresh_card",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#derive_toc"
  ]
}
```

---

## Implementation Notes

- Copy `refresh_card`'s card-update path for the four fields rather than calling `refresh_card` (it also re-drafts the
  card with an LLM). Read :1460-1510 first.
- Without `--apply` neither card nor tree changes (AC-13). `llm_passes` default = `self.has_llm`.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)
```python
# BEFORE `    async def refresh_card(self, book_id: str) -> BookCard:` (library.py:1460; occurrences: 1)
    async def optimize_book(self, book_id: str, *, apply: bool = False,
                            llm_passes: Optional[bool] = None) -> dict[str, Any]:
        """Optimize a book's PageIndex tree; when applied, rebuild the card TOC fields."""
        card, loc = self.resolve_book(book_id)
        toolkit = self._toolkit(loc.scope)
        report = await toolkit.optimize(card.tree_name, apply=apply,
                                        llm_passes=self.has_llm if llm_passes is None else llm_passes)
        if apply and not report.get("errors"):
            tree = await toolkit.get_tree(card.tree_name)
            toc_entries, toc_digest = derive_toc(tree)
            # FILL IN: chapter_count/page_count exactly as refresh_card derives them; upsert the card
        return report
```

### `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` (MODIFY)
```python
# BEFORE `@bookstore.command("remove")` (cli.py:569; occurrences: 1)
@bookstore.command("optimize")
@click.argument("book_id")
@click.option("--global", "global_scope", is_flag=True)
@click.option("--apply", is_flag=True)
@click.option("--no-llm", is_flag=True)
@click.option("--llm", default=None)
@click.option("--json", "as_json", is_flag=True)
def optimize_cmd(book_id: str, global_scope: bool, apply: bool, no_llm: bool, llm: Optional[str], as_json: bool) -> None:
    """Dry-run report by default; ``--apply`` publishes a generation and rebuilds the card TOC."""
    # FILL IN: build the Bookstore exactly as `add` does (scope/llm handling); asyncio.run(optimize_book(...)); print
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py` (CREATE)
```python
def test_optimize_book_and_cli(): ...   # FILL IN: bookstore half (pattern of tests/knowledge/bookstore/test_library.py)
```

---

## Acceptance Criteria

- [ ] AC-13: `--apply` republishes and rewrites the four card fields; without it nothing changes.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_cli.py -q`

---

## Test Specification

Spec §4 row `test_optimize_book_and_cli` (bookstore half).

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5373 — Bookstore.optimize_book and `bookstore optimize` command`.

---

## Completion Note

**Completed**: 2026-11-09 | **Implementation commit**: 527f93363c

Delivered via sdd-coder pool (merged). Scope: bookstore optimize_book.
Validation: merge-tier wave (5372+5373) — 212 passed, exit 0.
Deviations: none noted.

