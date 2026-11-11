# TASK-5476: PageIndex generic write-policy hook (`write_tools`, `_authorize_write`, `read_only`)

**Feature**: FEAT-876 — Bookstore notebooks over a shared PageIndex
**Spec**: `sdd/specs/bookstore-notebooks-shared-pageindex.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 2** (§3) and goal G3, decision `pageindex-write-policy-hook-is-generic`.
`PageIndexToolkit` gains a policy-free hook that the Bookstore facade (TASK-5478) uses for the library
policy. Dependency direction: `knowledge/pageindex/*` must never import `knowledge/bookstore/*`.
Design-research S3: the hook sits at the common mutation boundary `_mutate` **and** at the top of the
direct-lock paths, so a denied write never takes a lock or bumps a generation.

---

## Scope

- Add `class PageIndexWriteDenied(PermissionError)` at module level in `pageindex/toolkit.py`; export it from
  `parrot.knowledge.pageindex` (`__init__.py` and `__all__`).
- Add class attribute `write_tools: frozenset[str]` (prefixed names; exact set in the blueprint).
- Add keyword-only `read_only: bool = False` to `__init__` (stored as `self._read_only`).
- Add `def _authorize_write(self, tree_name: str, op: str) -> None` — default: raise `PageIndexWriteDenied`
  when `read_only`, else no-op.
- Call the hook **first** (before validation that takes locks, before `tree_lock`) in: `create_tree`,
  `delete_tree`, `rename_tree` (once for `src`, once for `dst`, `op="rename_tree"`), `vacuum_tree`,
  `index_segments`, `optimize` (only when `apply=True`, `op="optimize"`), `tag_node`, `insert_markdown`,
  `insert_ebook`, `insert_content`, `import_file`, `import_pdf`, `import_folder`, `delete_node`, `add_node`,
  `update_node_content`, `update_node`; and inside `_mutate` as a backstop (`op="_mutate"`).
- `get_tools()` drops every tool whose name is in `write_tools` when `read_only`.
- New test file `test_write_policy.py`.

**NOT in scope**: any Bookstore policy (TASK-5478); changes to `mcp/toolkit_server.py` or templates
(Non-Goal: byte-identical).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | Exception, `write_tools`, `read_only`, `_authorize_write`, hook calls, `get_tools` filter |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | MODIFY | Export `PageIndexWriteDenied` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_write_policy.py` | CREATE | Hook, read-only and coverage contract tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` at task-writing time (2026-11-11). Use these exact names.
> If you need anything not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.pageindex import PageIndexToolkit            # verified: pageindex/__init__.py:21, __all__ :51
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit    # verified: toolkit.py:220
from parrot.knowledge.pageindex.locks import tree_lock             # verified: bookstore/library.py:33 imports it
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
logger = logging.getLogger("parrot.knowledge.pageindex.toolkit")      # line 92
class PageIndexToolkit(AbstractToolkit):                                # line 220 — name="pageindex", tool_prefix="pageindex"
    llm_dependent_tools: frozenset[str] = frozenset({...5 names})      # line 265
    def __init__(self, adapter=None, storage_dir=None, ..., optimizer_settings=None, *,
                 llm_client=None, max_result_chars=None, **kwargs)      # line 275; keyword-only block at :302-305
    async def _mutate(self, tree_name, apply, *, attempts=3) -> T       # line 459
    def get_tools(self, permission_context=None, resolver=None) -> list # line 713 (super() + OKF tools)
    async def list_trees(self) -> list[str]                             # line 741 (read)
    async def create_tree(self, tree_name, doc_name=None)               # line 745
    async def delete_tree(self, tree_name)                              # line 781 (async with tree_lock(...) first statement)
    async def rename_tree(self, src, dst, *, overwrite=False)           # line 800 (validate names :822-823, lock :832)
    async def get_generation(...)                                       # line 896 — READ, not a write tool
    async def index_segments(self, tree_name, node_id=None)             # line 1456
    async def optimize(self, tree_name, node_id=None, apply=False, ...) # line 1541
    async def vacuum_tree(self, tree_name, max_age_s=None)              # line 1717
    async def tag_node(self, tree_name, node_id, categories=None, metadata=None)   # line 1958
    async def insert_markdown(self, tree_name, markdown, ...)           # line 2014
    async def insert_ebook(self, tree_name, sections, ...)              # line 2093
    async def insert_content(self, tree_name, content, ...)             # line 2169
    async def import_file(self, tree_name, file_path, ...)              # line 2193
    async def import_pdf(self, tree_name, pdf_path, ...)                # line 2212
    async def import_folder(self, tree_name, folder_path, ...)          # line 2552
    async def delete_node(self, tree_name, node_id)                     # line 2643
    async def add_node(self, tree_name, title, body="", ...)            # line 2674
    async def update_node_content(self, tree_name, node_id, body)       # line 2737
    async def update_node(self, tree_name, node_id, title=None, ...)    # line 2770
# tools/toolkit.py: AbstractToolkit.exclude_tools compares UNPREFIXED method names (:262, :598)
```

### Does NOT Exist
- ~~`PageIndexToolkit.write_tools` / `_authorize_write` / `read_only` / `PageIndexWriteDenied`~~ — added here.
- ~~`PageIndexToolkit.apply_plan` as a public tool~~ — verify with grep before adding it to `write_tools`; the AST scan
  at task-writing time found exactly the 16 mutating coroutines listed in Scope (+ `insert_content`/`import_file`,
  which delegate).
- ~~any import of `parrot.knowledge.bookstore` from `knowledge/pageindex/`~~ — forbidden.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_write_policy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._mutate",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.get_tools"
  ]
}
```

---

## Implementation Notes

- Put the hook call as the **first statement** after the docstring in each tool — before `_validate_name`,
  before `tree_lock`, before reading the tree — so a denied call has no side effect (AC + test
  `test_authorize_write_called_before_lock`).
- `rename_tree`: call `_authorize_write(src, "rename_tree")` then `_authorize_write(dst, "rename_tree")` (S4).
- `optimize`: hook only when `apply` is true; a dry run is a read.
- `_mutate` backstop: call `self._authorize_write(tree_name, "_mutate")` at the top. The public tools already
  authorized with their own op name; the backstop protects internal callers. Bookstore's own ingest goes
  through the plain `PageIndexToolkit` built by `Bookstore._toolkit` (default no-op hook) and is unaffected.
- `read_only` hiding filters by **prefixed** tool name in `get_tools()` — do not use `exclude_tools` (unprefixed,
  class-level).

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the exception and `write_tools` near `llm_dependent_tools` — *why*: class-level, like the sibling set.
2. Add `read_only` to `__init__` and `_authorize_write` — *why*: default policy lives here, subclasses/facades override.
3. Insert the hook call at the top of every write tool and in `_mutate` — *why*: S3 single boundary + direct-lock paths.
4. Filter `get_tools()` — *why*: a read-only server must not advertise writes.
5. Export the exception; write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^class PageIndexToolkit(AbstractToolkit):' toolkit.py) — INSERT ABOVE the class (line 220)
class PageIndexWriteDenied(PermissionError):
    """A write tool was refused for ``tree_name`` by the active write policy."""
```
```python
# occurrences: 1 (verified: grep -c '    llm_dependent_tools: frozenset\[str\] = frozenset(' toolkit.py) — INSERT ABOVE line 265
    #: Prefixed names of every tool that mutates a tree. ``read_only`` hides them; ``_authorize_write`` guards them.
    write_tools: frozenset[str] = frozenset(
        {
            "pageindex_create_tree", "pageindex_delete_tree", "pageindex_rename_tree", "pageindex_vacuum_tree",
            "pageindex_optimize", "pageindex_index_segments", "pageindex_insert_markdown", "pageindex_insert_ebook",
            "pageindex_insert_content", "pageindex_import_file", "pageindex_import_pdf", "pageindex_import_folder",
            "pageindex_tag_node", "pageindex_add_node", "pageindex_update_node", "pageindex_update_node_content",
            "pageindex_delete_node",
        }
    )
```
```python
# __init__ keyword-only block (verified: toolkit.py:302-305) — add after `max_result_chars: Optional[int] = None,`
        read_only: bool = False,
# and after `super().__init__(**kwargs)` (toolkit.py:307):
        self._read_only = read_only

    def _authorize_write(self, tree_name: str, op: str) -> None:
        """Write-policy hook, called before any tree lock is taken.

        Args:
            tree_name: Target tree (each endpoint for ``rename_tree``).
            op: Unprefixed tool name, or ``"_mutate"`` for the internal backstop.

        Raises:
            PageIndexWriteDenied: When the toolkit is ``read_only``.
        """
        if self._read_only:
            raise PageIndexWriteDenied(f"PageIndex toolkit is read-only: {op} on {tree_name!r} refused")
```
**Why**: the facade overrides `_authorize_write`-equivalent logic itself (it is not a subclass), but plain
servers get `read_only` for free. Place `_authorize_write` as a method of the class (not inside `__init__`).

```python
# Pattern for EVERY write tool (example: delete_tree, verified: toolkit.py:781, 1 occurrence)
    async def delete_tree(self, tree_name: str) -> dict[str, Any]:
        """Delete a tree JSON and every sidecar markdown file for it."""
        self._authorize_write(tree_name, "delete_tree")
        async with tree_lock(self._storage_dir, tree_name, timeout=self._lock_timeout_s):
            ...
# FILL IN: apply the same one-line call in the other 16 tools listed in Scope — bounded by AC-2
```
```python
# get_tools (verified: toolkit.py:713, 1 occurrence) — replace the final return
        tools = base_tools + okf_tools
        if self._read_only:
            tools = [tool for tool in tools if getattr(tool, "name", None) not in self.write_tools]
        return tools
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` (MODIFY)
```python
# FILL IN: add PageIndexWriteDenied to the existing `from .toolkit import ...` line and to __all__ (verified: __init__.py:21, :51)
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_write_policy.py` (CREATE)
```python
"""FEAT-876 M2 — PageIndexToolkit write-policy hook."""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from parrot.knowledge.pageindex import PageIndexToolkit, PageIndexWriteDenied


@pytest.fixture
def toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(storage_dir=tmp_path)


@pytest.fixture
def ro_toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(storage_dir=tmp_path, read_only=True)


def test_write_tools_matches_every_mutating_tool() -> None:
    """Every public coroutine that locks or mutates is in write_tools; no read tool is."""
    # FILL IN: AST-scan PageIndexToolkit for public async defs whose source contains
    #   `tree_lock(` or `_mutate(`; assert f"pageindex_{name}" in write_tools — bounded by AC-2
    #   (get_generation is a read: assert it is NOT in write_tools)


def test_read_only_hides_and_refuses(ro_toolkit: PageIndexToolkit) -> None:
    names = {tool.name for tool in ro_toolkit.get_tools()}
    assert not names & PageIndexToolkit.write_tools
    # FILL IN: `await ro_toolkit.create_tree("t")` raises PageIndexWriteDenied (make the test async)


async def test_authorize_write_called_before_lock(toolkit, monkeypatch) -> None:
    # FILL IN: create a tree; monkeypatch toolkit._authorize_write to raise; monkeypatch
    #   parrot.knowledge.pageindex.toolkit.tree_lock to fail the test if entered; call add_node / delete_tree /
    #   rename_tree / optimize(apply=True); assert PageIndexWriteDenied and tree unchanged — bounded by AC-3
    ...


async def test_rename_authorizes_both_endpoints(toolkit, monkeypatch) -> None:
    # FILL IN: record (tree_name, op) calls; rename a→b; assert both a and b were authorized
    ...


async def test_optimize_dry_run_is_not_a_write(ro_toolkit) -> None:
    # FILL IN: optimize(apply=False) on a read-only toolkit does not raise PageIndexWriteDenied
    ...
```
**Why**: the AST contract test is the S3 guard that keeps `write_tools` honest as tools are added.

### FILL IN checklist
- [ ] Hook call in all 17 write tools + `_mutate` backstop — bounded by Scope list and AC-2
- [ ] `__init__.py` export — bounded by AC-4
- [ ] Test bodies — bounded by spec §4 M2 rows

---

## Acceptance Criteria

- [ ] `PageIndexToolkit(read_only=True).get_tools()` contains none of `write_tools`; a direct write call raises `PageIndexWriteDenied`.
- [ ] `write_tools` covers every public coroutine that takes `tree_lock` or calls `_mutate` (AST contract test).
- [ ] A raising `_authorize_write` leaves the tree untouched and never enters `tree_lock`.
- [ ] `from parrot.knowledge.pageindex import PageIndexWriteDenied` works; no `knowledge/bookstore` import in `knowledge/pageindex/`.
- [ ] Existing PageIndex tests still pass (`test_toolkit.py`, `test_toolkit_no_llm.py`).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_write_policy.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`

---

## Test Specification

```python
# see the CREATE block above — packages/ai-parrot/tests/knowledge/pageindex/test_write_policy.py
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
9. **Close** with `parrot sdd task close TASK-5476 bookstore-notebooks-shared-pageindex verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(filled by sdd-worker)*

**Completed by**: sdd-worker
**Date**: 2026-11-11
**Notes**: Delivered in a prior interrupted run (commits 96fd40c24c + 8bfe1d6311, merged fa15cc83d4). Closed in this run; test_write_policy.py present.

**Deviations from spec**: none
