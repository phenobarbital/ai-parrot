# TASK-4482: Core fix: request-scoped RLS in AuthorizingDataSource + cloned sources in _clone_agent_dm (M12)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:90cf04ce8edd`

---

## Context

Spec §3 Module 12 + §8 Q6 + AC20 — vulnerability `issue:90cf04ce8edd` (major). `AuthorizingDataSource._apply_rls` rewrites the WRAPPED source in place (`self._inner.sql = rewritten_sql`, authorizing.py:191; `_permanent_filter`/`required_filter` mutations for Table/QuerySlug/Mongo), so predicates accumulate across fetches and leak to every holder of the inner object; `_clone_agent_dm` then shares `entry.source` across user managers (datasets.py:70) — one subject's RLS can reach another subject's queries.

---

## Scope

- Make `_apply_rls` return a per-call `copy.copy` of the inner source with RLS applied (fresh `dict` for `_permanent_filter`; mongo filter on the copy only); `fetch()` delegates to that copy; never mutate `self._inner`.
- Add `_clone_source(source)` in `handlers/datasets.py` and use it in `_clone_agent_dm` (`source=_clone_source(entry.source),`).
- Rewrite `test_rls_injected_before_fetch` (it asserts the buggy mutation) and add `test_rls_not_persisted_across_fetches`, `test_rls_two_subjects_isolated`.
- Append `test_e2e_dataset_manager_rls_two_users` to `test_datasetmanager_authz_integration.py`; create `test_datasets_clone.py` (`test_clone_agent_dm_copies_source`).

**NOT in scope**: redesigning the Mongo filter (out of scope, spec §6); any public signature change (AC17); the semantic satellite.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py` | MODIFY | request-scoped RLS copy |
| `packages/ai-parrot-server/src/parrot/handlers/datasets.py` | MODIFY | _clone_source + use in _clone_agent_dm |
| `packages/ai-parrot/tests/auth/test_authorizing_data_source.py` | MODIFY | fix buggy assertion + 2 tests |
| `packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py` | MODIFY | two-user e2e |
| `packages/ai-parrot-server/tests/handlers/test_datasets_clone.py` | CREATE | clone isolation test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
import copy                                                                  # stdlib — add next to `import logging` (authorizing.py:27)
from parrot.tools.dataset_manager.sources.base import DataSource            # verified: sources/authorizing.py:32 (import site)
from parrot.tools.dataset_manager.sources.sql import SQLQuerySource          # verified: sources/sql.py:26; `self.sql = sql` at :53
from parrot.tools.dataset_manager.sources.rls import inject_rls_sql, inject_rls_table_source, inject_rls_query_slug   # verified: rls.py:72,132,172 (table/slug mutate source._permanent_filter in place)
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager       # verified: handlers/datasets.py:32
from parrot.auth.rls_registry import RlsPredicate                           # verified: rls_registry.py:70
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py
class AuthorizingDataSource(DataSource):   # line 41
    def __init__(self, inner, guard, pctx_provider) -> None   # line 58; self._inner = inner (:65)
    async def fetch(self, **params) -> pd.DataFrame           # line 74; `            self._apply_rls(predicates, resources)` (:148); `return await self._inner.fetch(**params)` (:151)
    def _apply_rls(self, predicates, resources) -> None       # line 153; `            self._inner.sql = rewritten_sql` (:191);
        # inject_rls_table_source(self._inner, ...) (:199); inject_rls_query_slug(self._inner, ...) (:207); self._inner.required_filter = ... (:228, :232)
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py:196 / query_slug.py:98 — self._permanent_filter: Dict[str, Any]
# packages/ai-parrot-server/src/parrot/handlers/datasets.py
def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None   # line 47; `                source=entry.source,` (:70)
# packages/ai-parrot/tests/auth/test_authorizing_data_source.py:189 — async def test_rls_injected_before_fetch(...) asserts "_rls" in inner.sql (:210)
```

### Does NOT Exist
- ~~`DataSource.copy()` / `.clone()` / `model_copy()`~~ — plain classes; use `copy.copy` + explicit `dict()` of `_permanent_filter`.
- ~~`MongoSource.required_filter` as a constructor dict~~ — `__init__` takes `required_filter: bool` (mongo.py:77,84); the attribute assigned at authorizing.py:228/232 is dynamic — keep that semantics on the COPY only.
- ~~`packages/ai-parrot-server/tests/handlers/test_datasets_clone.py`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/datasets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_authorizing_data_source.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_datasets_clone.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py#AuthorizingDataSource",
    "sym:packages/ai-parrot-server/src/parrot/handlers/datasets.py#_clone_agent_dm"
  ]
}
```

---

## Implementation Notes

- Spec §6 Edit Sites lists the fetch anchor at `authorizing.py:149`; it is at **:148** on dev @ 754878f67 (count still 1).
- `copy.copy` shares connection pools/credentials by design — only `sql`, `_permanent_filter` and the mongo filter must be per call.
- Local venv may fail to collect `packages/ai-parrot/tests` (navigator-session pin); if so, run with `PYTHONPATH=packages/ai-parrot/src` and report the collection error rather than skipping tests silently.
- `/sdd-done` closes `issue:90cf04ce8edd` through the `Discovered-from` line — do not run `ledger close` yourself.

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Add `import copy`; change `_apply_rls` to build and return `scoped` — *why*: never mutate the shared inner source.
2. Change fetch Step 5/6 to fetch from the returned target — *why*: the RLS-applied copy is what runs.
3. Add `_clone_source` + use it — *why*: user managers never share a source object.
4. Fix the existing test and add the new ones — *why*: AC20.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'import logging' authorizing.py) — AFTER `import logging` (authorizing.py:27):
import copy

# occurrences: 1 (verified: grep -c -F '            self._apply_rls(predicates, resources)' authorizing.py) — at authorizing.py:147-151
# REPLACE Step 5/6 with:
        # Step 5: inject RLS into a request-scoped copy (never mutate self._inner — issue:90cf04ce8edd)
        target = self._apply_rls(predicates, resources) if predicates else self._inner

        # Step 6: delegate to the (possibly scoped) inner source
        return await target.fetch(**params)

# _apply_rls (authorizing.py:153): return type `-> None` becomes `-> DataSource`; first statement:
        scoped = copy.copy(self._inner)
        if hasattr(scoped, "_permanent_filter"):
            scoped._permanent_filter = dict(self._inner._permanent_filter)
# then replace EVERY `self._inner` inside _apply_rls's branches with `scoped`
# (occurrences: 1 for '            self._inner.sql = rewritten_sql' at :191 -> '            scoped.sql = rewritten_sql'),
# and `return scoped` at the end of every branch (including the unknown-type branch).
```
**Why**: spec §3 M12 skeleton. FILL IN: the `isinstance` checks may stay on `self._inner` (type is identical); the Mongo branch must read `existing` from `scoped` and assign on `scoped`; update the docstring (no longer 'in place').

### `packages/ai-parrot-server/src/parrot/handlers/datasets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None:' datasets.py)
# BEFORE — insert above that line (datasets.py:47):
def _clone_source(source: "DataSource | None") -> "DataSource | None":
    """Shallow-copy a DataSource for a per-user manager (issue:90cf04ce8edd).

    Connection objects stay shared; mutable filter state (`_permanent_filter`) gets a fresh dict so no
    two user managers share RLS state. ``None`` stays ``None``.
    """
    if source is None:
        return None
    clone = copy.copy(source)
    if hasattr(clone, "_permanent_filter"):
        clone._permanent_filter = dict(source._permanent_filter)
    return clone

# occurrences: 1 (verified: grep -c -F '                source=entry.source,' datasets.py) — at datasets.py:70 REPLACE with:
                source=_clone_source(entry.source),
```
**Why**: spec §3 M12. FILL IN: add `import copy` to datasets.py's stdlib imports (lines 12-15) and a `TYPE_CHECKING` import of `DataSource` from `..tools.dataset_manager.sources.base` (match the file's relative style, datasets.py:32). If `entry.source` is itself an `AuthorizingDataSource`, `copy.copy` copies the wrapper but SHARES its `_inner` — that is now safe because `_apply_rls` no longer mutates `_inner`; state this in a one-line comment.

### FILL IN checklist
- [ ] Branch rewrites inside `_apply_rls` on `scoped` — bounded by AC20.
- [ ] datasets.py imports.
- [ ] Test bodies (see Test Specification).

---

## Acceptance Criteria

- [ ] After N fetches `inner.sql` and `_permanent_filter` equal their constructor values; each fetch target carries exactly one RLS rewrite (AC20).
- [ ] `_clone_agent_dm` yields pairwise-distinct source objects whose `_permanent_filter` dicts are not shared (AC20).
- [ ] Both existing auth test files pass (spec Validation Contract) — no public signature changed (AC17).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot/tests/auth/test_authorizing_data_source.py -q`
- `pytest packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_datasets_clone.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/auth/test_authorizing_data_source.py — replace test_rls_injected_before_fetch's tail:
class _RecordingSQL(SQLQuerySource):
    seen: list[str] = []
    async def fetch(self, **params):
        type(self).seen.append(self.sql)
        return pd.DataFrame({"id": [1]})

#   inner = _RecordingSQL(sql="SELECT * FROM sales.orders", driver="pg"); await source.fetch()
#   assert "_rls" in _RecordingSQL.seen[-1] and inner.sql == "SELECT * FROM sales.orders"

async def test_rls_not_persisted_across_fetches(...):
    # FILL IN: two fetches -> each seen SQL has exactly one RLS wrapper; inner.sql unchanged
    ...

async def test_rls_two_subjects_isolated(...):
    # FILL IN: pctx A/B with different predicates through ONE AuthorizingDataSource; neither sees the other's
    #          literals; TableSource/QuerySlugSource inner _permanent_filter untouched
    ...

# packages/ai-parrot-server/tests/handlers/test_datasets_clone.py
def test_clone_agent_dm_copies_source():
    # FILL IN: fake agent with _dataset_manager holding a TableSource(permanent_filter={...}) and a None-source entry;
    #          two clones -> sources distinct from each other and from the agent's; filters not shared; None kept
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4482 — Core fix: request-scoped RLS in AuthorizingDataSource + cloned sources in _clone_agent_dm (M12)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4482 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
