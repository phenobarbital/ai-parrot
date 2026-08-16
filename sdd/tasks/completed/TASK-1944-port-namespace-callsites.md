# TASK-1944: Port the 5 audited `.locals`/`.globals` call sites to the namespace API

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1943
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / AC13. With the namespace living in the worker,
`tool.locals`/`.globals` are no longer the source of truth. The 2026-07-27
audit (spec §6) found exactly **5 modules** with direct host access; each is
ported to the async namespace API from TASK-1943
(`get_var`/`set_var`/`list_vars`/`snapshot`). The compatibility dict-proxy
was **explicitly rejected** — every call site is ported for real.

---

## Scope

Port each audited call site (line numbers re-verified 2026-07-27):

1. **`parrot/bots/data.py`** — 14 direct reads of `pandas_tool.locals`
   (`:1800, :2329, :2626-2628, :2655, :2743-2748, :2810-2815`), including
   `execution_results` lookups. Replace with `await pandas_tool.get_var(...)`
   / `await pandas_tool.snapshot()` / `await pandas_tool.list_vars()` as
   each site requires. `:2329` returns the whole dict → `snapshot()`.
2. **`parrot/bots/agent.py:218-219`** — working memory stores a **live
   reference**: `wm._tool_locals[key] = tool.locals`. Impossible semantics
   across a process. Port to storing a **snapshot** (`await tool.snapshot()`)
   at capture time; audit readers of `wm._tool_locals` and adjust them to
   the snapshot semantics (values frozen at capture).
3. **`parrot/tools/agent.py:421-427`** — host→namespace **writes**:
   `python_repl.globals['previous_result'] = context` and
   `python_repl.globals[f'{safe_name}_result'] = ...` → `await
   python_repl.set_var(...)`. Note the guard `hasattr(python_repl, 'globals')`
   (`:419`) — replace with a capability check on the namespace API.
4. **`parrot/outputs/formats/base.py:137`** — `return tool.locals, None`
   after `execute_sync` → return `await tool.snapshot()` (adapt the
   surrounding sync/async seam as the file's own pattern dictates).
5. **`parrot/tools/pythonpandas.py`** — `df_locals` merge and `clone()`:
   `:122` (`self.df_locals = {}`), `:128-130` (merge into `locals_dict`
   kwarg), `:229-236` (`clone()` copies locals/globals + re-merges
   `df_locals`), `:292` (`self.locals.update(self.df_locals)`). Port the
   merge to worker seeding: DataFrames registered in `df_locals` are pushed
   through `set_var`/`inject_dataframe` when the worker starts (pickle path
   is fine until TASK-1945 lands Arrow). `clone()` seeds the clone's worker
   instead of copying host dicts.

- Add regression test `test_callsites_use_namespace_api` including a grep
  assertion: no direct `.locals`/`.globals` access on REPL tools from host
  modules outside `pythonrepl.py`/`repl_worker/`.
- Run/extend `test_e2e_pandas_agent` (PandasAgent over the namespace API).

**NOT in scope**: Arrow IPC transport (TASK-1945 — pickle seeding is
acceptable here); changes to the namespace API itself (TASK-1943); other
`.locals` uses that are NOT PythonREPLTool/PythonPandasTool instances.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | 14 reads → get_var/snapshot/list_vars |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | `:218-219` live ref → snapshot |
| `packages/ai-parrot/src/parrot/tools/agent.py` | MODIFY | `:421-427` writes → set_var |
| `packages/ai-parrot/src/parrot/outputs/formats/base.py` | MODIFY | `:137` → snapshot |
| `packages/ai-parrot/src/parrot/tools/pythonpandas.py` | MODIFY | df_locals merge + clone → worker seeding |
| `packages/ai-parrot/tests/repl_worker/test_callsites.py` | CREATE | `test_callsites_use_namespace_api` + grep guard |

---

## Codebase Contract (Anti-Hallucination)

> All call sites re-verified by grep on 2026-07-27 against `dev` HEAD.
> Short paths relative to `packages/ai-parrot/src/`.

### Verified Imports

```python
# The namespace API added by TASK-1943 (verify exact signatures there first):
# PythonREPLTool.get_var / set_var / list_vars / snapshot — all async
```

### Existing Signatures to Use (exact audited lines)

```python
# parrot/bots/data.py — pandas_tool.locals reads (verified):
#   :1800  pandas_tool.locals.get(inferred_var)
#   :2329  return pandas_tool.locals
#   :2626  if var in pandas_tool.locals
#   :2627  isinstance(pandas_tool.locals[var], pd.DataFrame)
#   :2628  not pandas_tool.locals[var].empty
#   :2655  list(pandas_tool.locals[var].columns) == ref_cols
#   :2743  if data_variable in pandas_tool.locals:
#   :2744  df = pandas_tool.locals.get(data_variable)
#   :2747  if df is None and 'execution_results' in pandas_tool.locals:
#   :2748  exec_results = pandas_tool.locals['execution_results']
#   :2810  if var_name in pandas_tool.locals:
#   :2811  df = pandas_tool.locals.get(var_name)
#   (+2 more in the :2743-2748 / :2810-2815 ranges)

# parrot/bots/agent.py:218-219 (verified):
#   if key not in wm._tool_locals:
#       wm._tool_locals[key] = tool.locals

# parrot/tools/agent.py:415-427 (verified):
#   python_repl = self.agent.tool_manager.get_tool('python_repl')
#   if python_repl and hasattr(python_repl, 'globals'):
#       python_repl.globals['previous_result'] = context
#       ...
#       python_repl.globals[f'{safe_name}_result'] = agent_result.result

# parrot/outputs/formats/base.py:137 (verified):
#   return tool.locals, None

# parrot/tools/pythonpandas.py (verified):
#   :122  self.df_locals = {}
#   :128  df_locals = kwargs.get('locals_dict', {})
#   :129  df_locals.update(self.df_locals)
#   :130  kwargs['locals_dict'] = df_locals
#   :229  clone.df_locals = {}
#   :235  clone.locals.update(clone.df_locals)
#   :236  clone.globals.update(clone.df_locals)
#   :292  self.locals.update(self.df_locals)
```

### Does NOT Exist

- ~~A dict-proxy that makes `tool.locals` transparently hit the worker~~ —
  rejected in the spec (Non-Goals). Every site is ported explicitly.
- ~~Sync variants of the namespace API~~ — the API is async (TASK-1943); if
  a call site is sync (`outputs/formats/base.py` seam), bridge it the way
  that file already bridges `execute_sync`, do not add blocking calls in
  async contexts.
- ~~Other host modules touching REPL `.locals`~~ — the audit found exactly
  these 5; if you find a new one, port it and note it in the Completion Note.

---

## Implementation Notes

### Key Constraints

- Snapshot semantics for `wm._tool_locals` (values frozen at capture) is a
  **deliberate behavior change** decided in the brainstorm — the live
  reference would have broken silently anyway. Mention it in the docstring.
- `data.py` hot paths that only need membership/columns should prefer
  `list_vars()` / targeted `get_var()` over full `snapshot()` (a snapshot
  serializes the whole namespace across the process boundary).
- Preserve each file's error handling style; these are consumer modules with
  their own conventions.
- Keep changes minimal per site: same logic, new access path.

### References in Codebase

- Spec §6 "Audited External Access" — canonical audit list.
- `parrot/tools/pythonrepl.py` namespace API (post-TASK-1943).

---

## Acceptance Criteria

- [ ] All 5 modules ported; behavior preserved (except the documented
      snapshot semantics in `bots/agent.py`).
- [ ] `test_callsites_use_namespace_api` passes, including the grep guard:
      no host `.locals`/`.globals` access on REPL tools outside
      `pythonrepl.py`/`repl_worker/` (AC13).
- [ ] `test_e2e_pandas_agent`: PandasAgent operates end-to-end over the
      namespace API.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/ -v`
- [ ] No linting errors: `ruff check` on the five modified files.

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_callsites.py
import pathlib
import re
import pytest

SRC = pathlib.Path("packages/ai-parrot/src/parrot")

def test_callsites_use_namespace_api():
    """Grep guard (AC13): no direct REPL .locals/.globals from host modules."""
    offenders = []
    pattern = re.compile(r"(pandas_tool|python_repl|tool)\.(locals|globals)\b")
    for py in SRC.rglob("*.py"):
        if "repl_worker" in py.parts or py.name == "pythonrepl.py":
            continue
        for i, line in enumerate(py.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{py}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)

async def test_e2e_pandas_agent():
    """PandasAgent (bots/data.py) end-to-end over the namespace API."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1943 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep every audited line before
   editing (line numbers drift)
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1944-port-namespace-callsites.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-28
**Notes**:
- **`bots/data.py`**: `_get_repl_locals()` and `_infer_data_variable_from_tools()`
  now `async def`, using `pandas_tool.snapshot()`/targeted `get_var()` calls
  instead of `.locals` membership checks (candidate values cached locally so
  the column-match tiebreaker doesn't re-fetch). `_inject_data_from_variable()`
  / `_inject_multi_data_from_variables()` (already async) ported to
  `get_var()` for the top-level lookup + `execution_results` fallback.
- **`bots/agent.py`**: `_wire_tool_namespaces_into_working_memory()` is now
  `async def` (uses `await tool.snapshot()`) and moved from `__init__` (sync,
  can't await) to a new `async def configure()` override — the framework's
  own async setup hook (`super().configure(app)` then the wiring call).
  Snapshot semantics (frozen at wiring time) replace the old live-reference
  semantics, per spec's explicit decision.
- **`tools/agent.py`**: `_inject_context_to_repl()` (already async) ported
  `python_repl.globals[...] = ...` writes to `await python_repl.set_var(...)`.
- **`outputs/formats/base.py`**: kept `tool.locals` — see Deviations below,
  this is the ONE documented, tested exception to AC13.
- **`tools/pythonpandas.py`**: `PythonPandasTool` now implements **worker
  seeding** — `_get_worker_handle()` override diffs `df_locals` against a
  `_seeded_df_names` tracking set and `set_var()`s anything new/changed into
  the worker (the worker's OWN `PythonREPLTool` instance has an empty
  namespace and knows nothing about `df_locals`). `_process_dataframes()`
  resets the tracking set whenever `df_locals` is rebuilt (so a name mapping
  to a NEW DataFrame object gets re-pushed, not skipped as "already seeded").
  `reset_environment()`/`clear_dataframes()` also reset it.
  `create_session_clone()` now sets the TASK-1943 worker-identity attributes
  (`_session_id`, `_worker_pool=None`, `_pending_worker_reset`,
  `_worker_config`, `_worker_repl_kwargs`, `_seeded_df_names`) that
  `object.__new__` bypasses, giving the clone its OWN worker (never the
  source's — required for G7 session isolation); also fixed `df_locals`
  being dropped entirely for a no-`dataset_manager` clone (contradicted the
  method's own docstring promise that eagerly-loaded DataFrames are copied).
- **Regression fix for the async conversions** (necessary, not scope creep):
  ~40 test failures surfaced from existing `MagicMock`-based mocks of
  `_get_repl_locals`/`_repl_locals_getter` across `test_infographic_toolkit.py`,
  `test_infographic_toolkit_enhance.py`, `test_infographic_build_block.py`,
  `test_infographic_e2e.py`, `test_dataset_manager.py` — fixed by switching
  those ROOT mock constructions to `AsyncMock` (mechanical, not a logic
  change). Verified via `git stash` diff against `dev`-equivalent state that
  every REMAINING failure (8 in the infographic/dataset-manager suite, plus
  `test_setup_mcp_servers`/`test_agent_real_integration`/`test_agent_module.py`
  errors) is 100% pre-existing (same failures with zero changes applied).
- `pytest packages/ai-parrot/tests/repl_worker/
  packages/ai-parrot/tests/test_pythonrepl_security.py
  packages/ai-parrot/tests/test_pythonrepl_executor.py -q` → 108 passed (incl.
  6 new in `test_callsites.py`); `ruff check` on all 8 modified source files
  matches pre-existing per-file error counts exactly (0 new anywhere).

**Deviations from spec**:
1. **`outputs/formats/base.py:153` (`execute_code()`'s `pandas_tool` branch)
   deliberately KEEPS `tool.locals`** — the one AC13 exception, explicitly
   documented in-code and in `test_callsites.py`'s `_KNOWN_EXCEPTIONS`. This
   branch calls `tool.execute_sync()` (TASK-1943's separate, pre-existing
   SYNCHRONOUS in-process escape hatch) immediately before the read; the
   worker is never started on this path, so `snapshot()`/`get_var()` (which
   always read the WORKER's namespace) would silently return an unrelated,
   empty namespace instead of `execute_sync()`'s own just-produced result.
   Correctly porting this would require ALSO routing `execute_sync()`
   through the worker — explicitly out of TASK-1943's scope. Verified this
   branch has ZERO real callers anywhere in `src/`/`tests/` today (grep
   confirmed) — a live risk, not a currently-exercised bug.
2. **Extended beyond the 5-file/6-file table**: `dataset_manager/tool.py`
   (`_repl_locals_getter` callback type + call site → async, since its ONLY
   caller — `store_dataframe` — is already async) and `infographic_toolkit.py`
   (`_get_repl_locals()` wrapper + `_resolve_blocks()` → async, since ALL
   their callers — `render`, `validate_blocks`, `build_block`-family methods
   — are already async) were both required for `bots/data.py`'s
   `_get_repl_locals()` async conversion to not silently break its real
   callers. `working_memory/tool.py` got a docstring-only fix (a stale
   example literally showed the old `pandas_tool.locals` live-reference
   pattern the grep guard would have flagged, and the doc already
   anticipated `configure()`-based wiring — a nice independent confirmation
   the `configure()` approach matches this codebase's own convention).
3. **The task's own audit undercounted `pythonpandas.py`'s `.locals` usage**:
   many more read/write sites exist beyond `:122,128-130,229-236,292`
   (`register_dataframes`, `sync_from_manager`, `_rebind_drifted_dataframes`,
   `execution_results` handling, etc., ~15+ more lines). None of these are
   caught by the AC13 grep pattern (`(pandas_tool|python_repl|tool)\.`) since
   they're all `self.locals`/`self.df_locals` — the tool's OWN internal
   state, not an EXTERNAL host module reading through a variable named
   `pandas_tool`/`tool`/`python_repl`. Left untouched (same "host bootstrap
   stays populated for backward compat" reasoning already established in
   TASK-1943): a full port of PythonPandasTool's entire internal namespace
   bookkeeping to the worker-only model is a substantially larger
   undertaking than this task's M-effort scope suggests, and is a strong
   candidate for its own dedicated follow-up task.
4. **`clear_dataframes()` cannot un-set an already-pushed worker variable** —
   the namespace API (TASK-1943, spec-frozen) has no `del_var`/`unset_var`.
   Documented in a docstring note; a full `reset_environment()` is the only
   current way to truly clear a live worker's namespace.
5. **Pre-existing worktree environment gap, resolved as a side effect**: two
   Cython extensions (`parrot/utils/types.pyx`,
   `parrot/utils/parsers/toml.pyx`) were missing their compiled `.so` in this
   fresh worktree checkout (gitignored build artifacts present in the main
   repo but not shared across worktrees) — this blocked importing
   `parrot.bots.data`/`parrot.bots.agent` entirely, and was silently masking
   my ability to test-verify this task's changes. Built both in-place
   (`cythonize` + `build_ext --inplace`, no source changes) purely to unblock
   verification; this is a local build artifact, not committed, and every
   test file that previously errored on `ModuleNotFoundError:
   parrot.utils.types`/`parrot.utils.parsers.toml` now imports and runs
   normally in this worktree.
