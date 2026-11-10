# TASK-5483: CLI: `add --import`, `notebook draft`, `relate --from-notes`, `list --notes`, `remove --with-notes`, `doctor --notes`

**Feature**: FEAT-876 — Bookstore notebooks over a shared PageIndex
**Spec**: `sdd/specs/bookstore-notebooks-shared-pageindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5479, TASK-5480, TASK-5481, TASK-5482
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 8** (§3). Wires the library features of TASK-5477..5482 into the `bookstore` click
group. Messages and JSON shapes follow the existing commands (`--json` emits the result dict / model dumps).

---

## Scope

- `add`: `--import` (FILE is a tree JSON path **or** an uncatalogued tree name in the library),
  `--as [book|notes]` (default `book`), `--for <book_id>` (notes of that book). With `--import`, call
  `store.import_tree(...)`; FILE no longer uses `click.Path(exists=True)` — validate existence manually only when
  `--import` is not set (same error text click produced).
- New group `notebook` with `draft`: `--library` | `--book <id>` (exactly one), `--global`, `--no-llm`, `--json`.
- `relate --from-notes`: run `notebooks.apply_relation_sheets(store)` and print the edge count (can be combined with
  book ids / `--all`; runs before the normal stages).
- `list --notes`: list `kind="notes"` rows of every scope (`tree_name`, `scope`, `notes_for`).
- `remove --with-notes`: pass `with_notes=True`.
- `doctor --notes`: pass `notes=True`; human output prints a short notes section; `--json` includes `report["notes"]`.
- Tests in `test_cli.py` (click `CliRunner`, like the existing ones).

**NOT in scope**: any library logic (all in earlier tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | New options and the `notebook` group |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | CLI wiring tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` at task-writing time (2026-11-11). Use these exact names.
> If you need anything not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# cli.py imports heavy modules lazily inside commands (see `from .library import BookstoreError` in add) — keep that
from .library import BookstoreError                         # library.py:197
from .notebooks import apply_relation_sheets, draft_book_notebook, draft_library_notebook   # TASK-5480/5481
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py
def _open_bookstore(require_exists=..., use_llm=..., ...)   # line 34 — returns a Bookstore (read its exact signature before use)
_INVOCATION_CWD                                               # relative FILE anchoring (add, line ~131)
def bookstore() -> None                                       # line 99 (click group)
@bookstore.command("add")   def add(file, global_scope, title, authors, topics, force, no_llm, relate, llm)   # 103/117
@bookstore.command("list")  def list_cmd(as_json, by_community)                                            # 248
@bookstore.command("relate") def relate(book_ids, relate_all, no_llm, communities_only, force, resolution, llm)   # 450
@bookstore.command("doctor") def doctor_cmd(global_scope, repair, relate, no_llm, llm, as_json)            # 710
@bookstore.command("remove") def remove(book_id, yes)                                                      # 778
# Library API (earlier tasks):
#   Bookstore.import_tree(source, scope, *, as_kind, notes_for, title, force) -> (BookCard, status)   TASK-5482
#   Bookstore.remove_book(book_id, *, with_notes=False)                                               TASK-5477
#   Bookstore.doctor(scope=None, *, repair, relate, use_llm, notes=False)                             TASK-5479
#   CatalogStore.list_cards(kind="notes") via store._catalog(scope) for each store.locations          TASK-5475
#   notebooks.draft_library_notebook(store, scope, *, use_llm) / draft_book_notebook(store, book_id)  TASK-5481
#   notebooks.apply_relation_sheets(store, scope=None) -> int                                         TASK-5480
```

### Does NOT Exist
- ~~`bookstore notebook list`/`show`~~ — not in scope; only `notebook draft`.
- ~~`bookstore import`~~ as a separate command — it is `add --import`.

---

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
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#add",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#list_cmd",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#relate",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#doctor_cmd",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#remove",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#_open_bookstore"
  ]
}
```

---

## Implementation Notes

- Keep existing output strings unchanged for the no-new-flag paths (AC: `bookstore list` output unchanged).
- `--as notes` without `--import` → `click.UsageError`. `--library` and `--book` together or neither → `UsageError`.
- `notebook draft --library` defaults to the project scope; `--global` targets the global library.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. `add` options + import branch — *why*: G8 surface.
2. `notebook` group + `draft` — *why*: G6 surface.
3. `relate --from-notes`, `list --notes`, `remove --with-notes`, `doctor --notes` — *why*: G7/G2/G4 surfaces.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` (MODIFY)
```python
# add (verified: cli.py:103, 1 occurrence) — replace the argument decorator and add three options
@bookstore.command("add")
@click.argument("file")
# ...existing options unchanged...
@click.option("--import", "import_tree", is_flag=True, help="FILE is a PageIndex tree JSON (or an in-library tree name) to adopt without re-ingesting.")
@click.option("--as", "as_kind", type=click.Choice(["book", "notes"]), default="book", show_default=True, help="Catalog the imported tree as a book or a notebook.")
@click.option("--for", "notes_for", default=None, help="With --as notes: the book these notes belong to.")
# FILL IN: add the three parameters to def add(...); when not import_tree, keep today's flow but first check
#   Path(file).is_file() and raise click.BadParameter("Path '<file>' does not exist.") like click did;
#   when import_tree: card, status = asyncio.run(store.import_tree(...)); echo "<status>: <book_id> (<scope>)"
```
```python
# AFTER the remove command (verified: cli.py:778) — new group
@bookstore.group("notebook")
def notebook() -> None:
    """Notebooks: per-book notes and the library's sector index."""


@notebook.command("draft")
@click.option("--library", "library", is_flag=True, help="Draft sectors into the library notebook.")
@click.option("--book", "book_id", default=None, help="Draft a reading-guide skeleton for one book.")
@click.option("--global", "global_scope", is_flag=True, help="Target the global library (with --library).")
@click.option("--no-llm", is_flag=True, help="Communities map 1:1 to sectors; no model calls.")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def notebook_draft(library: bool, book_id: Optional[str], global_scope: bool, no_llm: bool, as_json: bool) -> None:
    """Propose notebook structure (drafts never overwrite your own notes)."""
    # FILL IN: validate exactly one of --library/--book; open the bookstore (use_llm=not no_llm);
    #   run the matching draft coroutine; echo counts (or json.dumps) — bounded by AC-2
```
```python
# relate (cli.py:450): add @click.option("--from-notes", is_flag=True, help="Turn notebook relation sheets into manual edges.")
# list (cli.py:248):   add @click.option("--notes", "show_notes", is_flag=True, help="List notebooks instead of books.")
# remove (cli.py:778): add @click.option("--with-notes", is_flag=True, help="Also delete the book's notebook.")
# doctor (cli.py:710): add @click.option("--notes", "check_notes", is_flag=True, help="Also check notebooks and anchors.")
# FILL IN: thread each flag to the library call — bounded by AC-3..AC-6
```

### FILL IN checklist
- [ ] `add` import branch + manual existence check — bounded by AC-1
- [ ] `notebook draft` — bounded by AC-2
- [ ] `relate --from-notes` — bounded by AC-3
- [ ] `list --notes` — bounded by AC-4
- [ ] `remove --with-notes`, `doctor --notes` — bounded by AC-5, AC-6
- [ ] Tests

---

## Acceptance Criteria

- [ ] AC-1: `bookstore add --import <tree.json>` imports and prints the status; `bookstore add <missing>` still fails with a "does not exist" message; plain `add` behaviour unchanged.
- [ ] AC-2: `bookstore notebook draft --library --no-llm --json` prints `{created, updated, skipped_human}`; `--library --book x` is a usage error.
- [ ] AC-3: `bookstore relate --from-notes` writes manual edges and prints their count.
- [ ] AC-4: `bookstore list --notes` lists notebooks; `bookstore list` output is unchanged.
- [ ] AC-5: `bookstore remove <id> --with-notes --yes` removes the notebook too.
- [ ] AC-6: `bookstore doctor --notes --json` includes `notes`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_cli.py -q`

---

## Test Specification

```python
def test_cli_add_import_and_notebook_draft(tmp_path, monkeypatch): ...
def test_cli_list_notes_and_remove_with_notes(tmp_path, monkeypatch): ...
def test_cli_relate_from_notes(tmp_path, monkeypatch): ...
def test_cli_doctor_notes_json(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug bookstore-notebooks-shared-pageindex --feature-id FEAT-876`).
   Run tests with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
2. **Read the spec** at the path above (§2 Overview, the module section named in Context, §6, §7).
3. **Check dependencies** — every `Depends-on` task must be `done` in
   `sdd/tasks/index/bookstore-notebooks-shared-pageindex.json`.
4. **Verify the Codebase Contract** before writing code; if an entry is stale, fix the contract here first.
   Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `in-progress` (set `started_at`) and commit only that file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Validate**: `ruff check --fix <files>` and the Validation Commands below.
8. **Commit the code** — stage only the files listed in this task.
9. **Close** with `parrot sdd task close TASK-5483 bookstore-notebooks-shared-pageindex verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
