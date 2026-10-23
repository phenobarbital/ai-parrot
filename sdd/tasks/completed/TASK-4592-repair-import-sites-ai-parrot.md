# TASK-4592: Repair the ai-parrot import sites

**Feature**: FEAT-720 — One Importable Identity per Package Test Tree
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4591
**Assigned-to**: unassigned
**Discovered-from**: `issue:45cf6a054e06`

---

## Context

Implements spec **Module 3** for `packages/ai-parrot` — the largest share of the
fallout, 24 of the 34 class-(i) sites plus 6 class-(v) files.

TASK-4591 removed the `tests` package. Every `from tests.<x> import …` in this
distribution now resolves against nothing. This task restores each one, changing
**only how the symbol is reached** — never what the test asserts.

`packages/ai-parrot` is also the distribution TASK-4590 was asked to explain:
round 2 saw its `--collect-only` exit 4 and could not say whether the change
caused it. Read §5 of the spike evidence before assuming a failure here is yours
to fix.

---

## Scope

- Repair every class-(i) `from tests.<x> import …` site in `packages/ai-parrot/tests`
  (24 files, enumerated below).
- Repair every class-(v) dotted string target `"tests.…"` in
  `packages/ai-parrot/tests` (6 files).
- Repair any class-(ii)/(iii) site in this distribution that TASK-4590's §3
  table attributes to `packages/ai-parrot`.
- Add a nested `__init__.py` where class (ii) requires one.

**NOT in scope**: any other distribution (TASK-4593/4594); deleting or restoring
a top-level `__init__.py` (TASK-4591); the regression test (TASK-4595); fixing a
failure TASK-4590 §5 attributes to a **pre-existing** cause; changing any
assertion, fixture behaviour, parameter or skip.


> **Amendment A (spec rev 0.2)** — measured in the (a′) state (TASK-4591 applied, importlib mode), standalone
> per-root `--collect-only`: `ai-parrot` fails to collect exactly these 5 files — `from ..tools._host_probe import host_plugins` (2) and `from ...bots.flows.plan._delegate_fakes import …` (3) — because `..`/`...` now climb past the first-level package. They are listed below as class (x). Repair by importing the helper through a conftest-provided fixture or a file-location load inside the nearest `conftest.py`; **never** by putting the tests directory on `sys.path` (it would re-shadow `tools`, `mcp`, …).
> Class (ii)/(iii)/(vi) work formerly attributed to TASK-4590 §3 is **moot** unless named in the table below:
> TASK-4591 now removes/adds the nested `__init__.py` files that caused it. Repairs may change only an import
> statement, a `conftest.py`, or a dotted string target. Never restore or add an `__init__.py`.
> Class (xi) `sys.modules` pollution seen only in many-trees-one-session runs is NOT this task's.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/flows/test_storage_parity.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/eval/test_benchmarks_e2e.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/handlers/test_checkpoint_handlers.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/integration/rag/test_store_router_integration.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/integration/test_jira_wiki_e2e.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/interfaces/jira/conftest.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema_import_clean.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/conftest.py` | MODIFY | class (i) import (2 sites) |
| `packages/ai-parrot/tests/knowledge/wiki/test_llmcaller_consumers.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_source_manager_event_loop.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/knowledge/wiki/test_vault_scan.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/loaders/obsidian/conftest.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/outputs/a2ui/runtime/test_dispatch.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/tools/test_obsidian_okf_tools.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/tools/test_obsidian_toolkit.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/unit/clients/test_factory_discovery.py` | MODIFY | class (i) import |
| `packages/ai-parrot/tests/interfaces/test_apply_tooling_server_managed.py` | MODIFY | class (x): relative import reached through the removed `tests` root |
| `packages/ai-parrot/tests/interfaces/test_resolve_spec_class_resolver.py` | MODIFY | class (x): relative import reached through the removed `tests` root |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_allowlist_repair.py` | MODIFY | class (x): relative import reached through the removed `tests` root |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_integration.py` | MODIFY | class (x): relative import reached through the removed `tests` root |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_wiring.py` | MODIFY | class (x): relative import reached through the removed `tests` root |

Class-(v) files (6, located by the command in the contract below) and any
class-(ii)/(iii) file named by TASK-4590 §3 are added to this table by the
implementing agent **before** editing, so the Complexity Contract stays accurate.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

The sites being repaired, sampled verbatim on `dev c2fd0ae28`:

```python
# packages/ai-parrot/tests/interfaces/jira/conftest.py:3
from tests.fixtures.jira_payloads import raw_issue_payload, remote_links_payload

# packages/ai-parrot/tests/knowledge/wiki/conftest.py:32  (inside a function)
    from tests.fixtures.jira_payloads import raw_issue_payload
# packages/ai-parrot/tests/knowledge/wiki/conftest.py:39  (inside a function)
    from tests.fixtures.jira_payloads import remote_links_payload
```

The shared fixture module they reach for:
`packages/ai-parrot/tests/fixtures/jira_payloads.py`.

### Verified facts (measured on `dev c2fd0ae28`)

| Fact | Value | Command |
|---|---|---|
| class-(i) sites in `packages/ai-parrot` | **24 files** | `grep -rln -E '^\s*(from\|import)\s+tests[.\s]' packages/ai-parrot/tests` |
| class-(v) files in `packages/ai-parrot` | **6 files** | `grep -rln "['\"]tests\." packages/ai-parrot/tests` |
| nested `__init__.py` under this tree | survives TASK-4591 | `find packages/ai-parrot/tests -name '__init__.py'` |

### Does NOT Exist
- ~~a `tests` package after TASK-4591~~ — that is the point of this task. Do not
  restore `packages/ai-parrot/tests/__init__.py` to make an import resolve.
- ~~a `conftest.py` at `packages/ai-parrot/tests/fixtures/`~~ — verify before
  assuming one; `fixtures/` is a plain module directory.
- ~~a shared `tests.fixtures` package importable from another distribution~~ —
  each distribution has its own `tests/fixtures`; never cross-import one.
- ~~a single mechanical rewrite that fits all 24 sites~~ — a `conftest.py` at a
  different depth needs a different number of leading dots. Verify per file.

### Repo-specific gotcha

There are **two** wiki test trees in this repo: `packages/ai-parrot/tests/knowledge/wiki`
(this task's, 11 of the 24 sites) and a root-level `tests/knowledge/wiki`. They
are not the same files. Edit only the `packages/` one here; the root tree is
outside every `packages/*/tests` glob this feature touches.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/bots/flows/test_storage_parity.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/eval/test_benchmarks_e2e.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/handlers/test_checkpoint_handlers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/integration/rag/test_store_router_integration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/integration/test_jira_wiki_e2e.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/jira/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/graphindex/test_pg_schema_import_clean.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_llmcaller_consumers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_source_manager_event_loop.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_vault_scan.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/loaders/obsidian/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/runtime/test_dispatch.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_obsidian_okf_tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_obsidian_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/clients/test_factory_discovery.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_apply_tooling_server_managed.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_resolve_spec_class_resolver.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_delegate_allowlist_repair.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_delegate_integration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_delegate_wiring.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints — the hard one
A repair may change **only** an import statement, a `conftest.py`, or a dotted
string target. It may **not** change an assertion, a fixture's behaviour, a
test's parameters, or add a skip/xfail. A site that appears to need more than an
import change is a **finding for the Completion Note**, not a licence to edit the
test (AC5, AC6).

### Other constraints
- Prefer a relative import (`from ..fixtures.jira_payloads import …`) — the
  nested `__init__.py` files survive TASK-4591, so relative imports resolve.
- Where the importing file is a `conftest.py` at the tree root, a relative import
  has no parent package: inject the path in that `conftest.py` instead (class iii).
- Count the dots per file. Depth differs: `tests/interfaces/jira/conftest.py` and
  `tests/knowledge/wiki/conftest.py` both reach `tests/fixtures/`, but
  `tests/tools/test_obsidian_toolkit.py` sits one level shallower.
- `packages/ai-parrot/tests/knowledge/wiki/conftest.py` has **two** sites (lines
  32 and 39), both inside function bodies — keep them function-local.
- Run each repaired file's own test file after editing it; do not wait for the
  whole distribution.
- `PYTHONPATH=packages/ai-parrot/src` when running tests in the worktree.

### References in Codebase
- `sdd/state/FEAT-720/spike-collect.md` §3 — the authoritative per-site list
- `packages/ai-parrot/tests/fixtures/jira_payloads.py` — the most-reached module

---

## Implementation Blueprint

### Steps (in order)
1. Read TASK-4590's §3 table and reconcile it against the 24 files listed above —
   *why*: the table is today's evidence and this list is three weeks old; the
   table wins, and a file in one but not the other must be explained.
2. Add any class-(ii)/(iii)/(v) file it names for this distribution to the Files
   table and the Complexity Contract — *why*: those two must match exactly, and
   the validator checks it.
3. Repair the class-(i) sites, one file at a time, running that file's tests
   after each — *why*: 24 edits landed in a batch make a single bad dot count
   impossible to localise.
4. Repair the 6 class-(v) dotted string targets — *why*: they are resolved at
   runtime, so collection succeeds and the failure only appears in the assertion.
5. Re-run the per-distribution collect and compare the item count to TASK-4590's
   baseline — *why*: AC2 requires an unchanged count, and a drop means a file
   stopped collecting rather than being repaired.

### `packages/ai-parrot/tests/interfaces/jira/conftest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from tests.fixtures.jira_payloads import raw_issue_payload, remote_links_payload' packages/ai-parrot/tests/interfaces/jira/conftest.py)
# REPLACE — the line `from tests.fixtures.jira_payloads import raw_issue_payload, remote_links_payload` (verified: packages/ai-parrot/tests/interfaces/jira/conftest.py:3)
# FILL IN: the replacement import — bounded by AC5 (import-only change) and by
#          this file's depth under packages/ai-parrot/tests (count the dots;
#          tests/interfaces/jira/ → tests/fixtures/ is three levels up)
```
**Why**: this is the simplest of the 24 and the pattern for the rest — a
module-level, single-line import of a sibling fixture module. It is left as a
`FILL IN` rather than written out because the correct number of leading dots is a
per-file fact, and a wrong dot count fails at collection in a way that looks like
a missing module.

### `packages/ai-parrot/tests/knowledge/wiki/conftest.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -c 'from tests.fixtures.jira_payloads import raw_issue_payload' … and '… remote_links_payload' …)
# REPLACE — two function-local imports (verified: packages/ai-parrot/tests/knowledge/wiki/conftest.py:32 and :39)
# FILL IN: both replacements — bounded by AC5, and by keeping them function-local:
#          do NOT hoist them to module scope. They are deferred on purpose; this
#          file is one of two wiki conftests in the repo and hoisting changes
#          import-time behaviour for every test under it.
```
**Why**: the two imports are inside function bodies, which is a deliberate
deferral. A repair that hoists them to module level would be a behaviour change,
not an import change, and would breach AC5.

### FILL IN checklist
- [ ] `interfaces/jira/conftest.py:3` — replacement import; bounded by AC5 + file depth
- [ ] `knowledge/wiki/conftest.py:32,39` — both replacements, kept function-local; bounded by AC5
- [ ] the remaining 22 class-(i) files — same rule, one per file; bounded by AC5
- [ ] the 6 class-(v) dotted targets — bounded by AC5
- [ ] any class-(ii)/(iii) site TASK-4590 §3 attributes to this distribution

---

## Acceptance Criteria

- [ ] No `from tests.<x>` or `import tests.<x>` remains under
      `packages/ai-parrot/tests`:
      `grep -rn -E '^\s*(from|import)\s+tests[.\s]' packages/ai-parrot/tests` → empty.
- [ ] No unresolved `"tests.…"` dotted string target remains in this distribution.
- [ ] `pytest packages/ai-parrot/tests --collect-only -q -p no:randomly` exits 0
      with the **same item count** as TASK-4590's baseline (AC2). A changed count
      is a defect.
- [ ] Every edit is an import statement, a `conftest.py`, or a dotted string
      target — reviewable as such in the diff (AC5).
- [ ] No test is skipped, xfailed or deleted (AC6).
- [ ] No `packages/*/tests/__init__.py` is restored (AC4).
- [ ] `ruff check` clean on every changed file (AC9).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_factory_discovery.py -q`
- `pytest packages/ai-parrot/tests/tools/test_obsidian_toolkit.py -q`
- `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`

---

## Test Specification

No new test code. Each repaired file's existing tests are the specification: they
must pass exactly as they did before TASK-4591, with the same item count.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** §2 breakage classes and **TASK-4590's `sdd/state/FEAT-720/spike-collect.md` §3**
3. **Check dependencies** — TASK-4591 must be `"done"` in the per-spec index
4. **Verify the Codebase Contract** — re-run the two `grep` counts; if a file has
   appeared or vanished, update this task's tables FIRST
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file
6. **Implement** one file at a time, running that file's tests after each
7. **Verify** every acceptance criterion, especially the unchanged item count
8. **Commit the code** — stage only this task's files, never `git add .` / `-A`
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4592 tests-test-wheel-layout-tech-debt-2 verified`
10. **Fill in the Completion Note** — list any site that needed more than an
    import change, as a finding rather than an edit

---

## Completion Note

**Completed by**: sdd-worker (seat gpt-5.6-sol attempt 2; attempt 1 gpt-5.6-terra delivered nothing)
**Date**: 2026-10-23
**Notes**: 29 files committed by the engine + 2 class-(v) files (`integration/test_structured_artifact_envelope_e2e.py`,
`tools/working_memory/task_memory/test_postgres_artifacts.py`) that the task's table omitted but its Scope covers; the engine flagged them
`fidelity_violation` (left uncommitted), the worker reviewed and committed them, then merged the branch by hand.
Evidence: `packages/ai-parrot/tests` standalone collect = **25,328 items, 0 errors** (baseline 25,328 — AC2 holds for this distribution);
the 4 task validation commands: 56 passed. Every edit is an import statement or dotted target.

**Deviations from spec**: two files outside the task's table (see above), in scope per the Scope text.
