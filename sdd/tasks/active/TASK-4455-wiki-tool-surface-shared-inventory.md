# TASK-4455: Shared wiki MCP tool inventory + current store kwargs in the surface tests

**Feature**: FEAT-700 — Hermetic, current expectations for the package-tree wiki tests
**Spec**: `sdd/specs/fixgroup-09687c688868.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: issue:66599d4e8c84

---

## Context

Ledger fix lane (`/sdd-fix`, fixgroup:09687c688868). Four tests hardcode the
8-tool local stdio surface of FEAT-450 days; the real surface is the 13-tool
`LOCAL_NO_LEDGER` already frozen in `test_tool_surface_golden.py:15`. One
more test pins `kwargs == {}` for the sqlite store, but
`create_wiki_mcp_server` now passes `sqlite_policy=` (`mcp_server.py:194`).
Implements spec §3 M1 (clusters A + B).

---

## Scope

- Create `_tool_surface.py` holding `LOCAL_NO_LEDGER`, `LEDGER`, `BULK`
  (moved verbatim from the golden test).
- Point the golden test and the three stale files at it.
- Update the sqlite-kwargs assertion.

**NOT in scope**: any file under `packages/ai-parrot/src/`; installer or
CLI tests (TASK-4456 / TASK-4457); the root twin `tests/knowledge/wiki/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/_tool_surface.py` | CREATE | frozen inventories, no `parrot` imports |
| `packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py` | MODIFY | import the inventories instead of defining them |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` | MODIFY | `names == set(LOCAL_NO_LEDGER)`; kwargs keys == `{"sqlite_policy"}` |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` | MODIFY | `BASE_TOOLS = set(LOCAL_NO_LEDGER)` |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py` | MODIFY | `BASE_TOOLS = set(LOCAL_NO_LEDGER)` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from tests.knowledge.wiki.test_mcp_server import _seed_wiki, _subprocess_env  # verified: test_mcp_server_vault.py:15 (same import style for the new module)
from parrot.knowledge.wiki.mcp_server import build_wiki_tools, create_wiki_mcp_server  # verified: test_tool_surface_golden.py:9
```

### Existing Signatures to Use
```python
# test_tool_surface_golden.py:15-33 — the three inventories to MOVE verbatim:
LOCAL_NO_LEDGER = sorted([... 13 names ...]); LEDGER = sorted([... 7 ...]); BULK = sorted([... 4 ...])
# mcp_server.py:190-195
store = create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend, sqlite_policy=sqlite_policy_from_config(config))
```

### Does NOT Exist
- ~~`tests/knowledge/wiki/test_mcp_server_namespaces.py`~~ (root twin) — only
  the package tree has it.
- ~~a `BASE_TOOLS` export in `parrot.knowledge.wiki.mcp_server`~~ — the
  inventory lives in tests only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/wiki/_tool_surface.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#create_wiki_mcp_server"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_tool_surface.py` must not import `parrot` (the golden test's
  `importorskip` must stay the only gate on `parrot.mcp.transports`).
- Keep the golden test's two test functions unchanged in behaviour.
- Before running: `ls -d /tmp/.git /tmp/.parrot` must print nothing (spec §7).

---

## Implementation Blueprint

### Steps (in order)
1. Create `_tool_surface.py` with the three lists — *why*: one owner for
   the inventory.
2. Replace the three definitions in the golden test with an import.
3. Replace the literal sets in the three stale files; fix the kwargs assert.
4. Run validation; `ruff check --fix` the five files.

### `packages/ai-parrot/tests/knowledge/wiki/_tool_surface.py` (CREATE)
```python
"""Frozen wiki MCP tool inventories shared by the surface tests (FEAT-700).

Owned here so that adding a tool updates ONE place; every test asserting
the local stdio surface imports ``LOCAL_NO_LEDGER`` from this module.
"""

from __future__ import annotations

LOCAL_NO_LEDGER: list[str] = sorted(
    [
        "wiki_query", "wiki_page", "wiki_related", "wiki_remember", "wiki_note", "wiki_status",
        "wiki_symbol_lookup", "wiki_code_outline", "wiki_blast_radius",
        "wiki_decision_why", "wiki_decisions_for_symbol", "wiki_lint", "wiki_standup",
    ]
)
LEDGER: list[str] = sorted(
    ["ledger_open", "ledger_ready", "ledger_claim", "ledger_close", "ledger_context", "ledger_list", "ledger_show"]
)
BULK: list[str] = sorted(["wiki_page_hashes", "wiki_ingest_batch", "wiki_sync_push", "wiki_sync_pull"])
```

### `packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^LOCAL_NO_LEDGER = sorted(' <path>)
# REPLACE — the three module-level definitions (lines 15-33) with:
from tests.knowledge.wiki._tool_surface import BULK, LEDGER, LOCAL_NO_LEDGER  # noqa: E402 — after importorskip
```

### `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert names == {' <path>)
# REPLACE — the `assert names == { ... }` literal (lines 89-98) with:
            assert names == set(LOCAL_NO_LEDGER) | set(LEDGER)  # _seed_wiki creates .git → ledger overlay mounted (spec rev 0.2)
# occurrences: 1 (verified: grep -c 'assert captured\["kwargs"\] == {}' <path>)
# REPLACE line 182 with:
        assert set(captured["kwargs"]) == {"sqlite_policy"}
# plus the import near the other `from tests...`/`from parrot...` imports:
from tests.knowledge.wiki._tool_surface import LOCAL_NO_LEDGER
```

### `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` / `test_mcp_server_vault.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -c '^BASE_TOOLS = {' <path>)
# REPLACE the whole `BASE_TOOLS = { ... }` literal with:
BASE_TOOLS = set(LOCAL_NO_LEDGER)
# and add the import next to the existing `from tests.knowledge.wiki...` / `from parrot...` imports.
```

---

## Acceptance Criteria

- [ ] AC1: `test_initialize_and_list_tools`, `test_no_namespaces_keeps_a_plain_store`,
      `test_namespace_is_injected`, `test_no_vault_keeps_base_tool_set`,
      `test_sqlite_backend_unaffected_by_arango_branch` pass.
- [ ] AC2: among the four surface test modules, the inventory literal lives only in `_tool_surface.py` (spec rev 0.2 scope).
- [ ] AC3: `test_tool_surface_golden.py` still passes (2 tests).
- [ ] No linting errors on the five files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py -q -p no:cacheprovider -o addopts=""`

---

## Test Specification

See blueprint; no new tests beyond the moved inventory.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-09687c688868 --feature-id FEAT-700`)
2. **Read the spec** for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/fixgroup-09687c688868.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the five listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4455 fixgroup-09687c688868 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*
