---
type: feature
base_branch: dev
---

# Brainstorm: `PostgresResultStorage` read paths are silently broken

**Date**: 2026-08-09
**Author**: Jesus Lara (found by Claude during the SaaS tenancy work)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

`PostgresResultStorage`
(`packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`)
is the Postgres backend for crew and flow execution results. **Its read methods
cannot work**, and they fail silently rather than raising.

This was found while building the SaaS secret store against the same driver: the
first parameterised query written the same way raised immediately, which
prompted checking the existing call sites.

## The defect

`asyncdb`'s `pg` driver defines:

```python
fetchrow(self)              # no arguments
fetch(self, number=1)       # a cursor-style row count, NOT a query
fetch_one(self, sentence: str, *args, **kwargs)
fetch_all(self, sentence: str, *args, **kwargs)
execute(self, sentence: Any, *args, **kwargs)
```

The storage calls:

- `get()` (~line 356): `await conn.fetchrow("SELECT * FROM ... WHERE id = $1", record_id)`
  → `TypeError: pg.fetchrow() takes 1 positional argument but 2 were given`
- `list()` (~line 322): `await conn.fetch(sql, *params, limit, offset)`
  → `TypeError` for the same reason; `sql` is bound to `number`.

Both sit inside a broad `except Exception` that logs a warning and returns a
default. So:

- `get(collection, record_id)` always returns `None`
- `list(...)` always returns `[]`

…and the only trace is a `warning`-level log line. Any dashboard or API reading
crew/flow execution history through this backend has been showing "no results"
rather than an error.

`save()` is **correct** — it uses `execute(sql, *params)`, which does accept
positional parameters. So writes work and reads do not, which is exactly the
shape of bug that survives a long time: the data is there, it just cannot be
read back through this class.

`fetch()` at ~line 187 inside `fetch(collection, execution_id)` uses
`conn.execute(...)` and is fine.

## Blast radius

- Affects only the `postgres` result-storage backend. `CREW_RESULT_STORAGE`
  defaults to `documentdb`, so a deployment on defaults never sees it — which
  is likely why it has gone unnoticed.
- The SaaS plane writes flow audit rows through `_save_result` (the working
  path) and does not read them back through this class, so the Community
  Manager work is unaffected. It is recorded here rather than fixed there
  because it is out of that feature's scope.

## Constraints & Requirements

- The fix must not change the public `ResultStorage` interface.
- It needs a regression test against a real Postgres — a mock would have
  reproduced the original mistake, since the bug is precisely a wrong
  assumption about the driver's signature.

## Options Explored

### Option A: Switch the two call sites to `fetch_one` / `fetch_all` — RECOMMENDED

✅ **Pros:** two-line fix; matches what the driver actually offers.
❌ **Cons:** none of substance.
📊 **Effort:** Low.

### Option B: Fix, and narrow the exception handling

As Option A, plus stop swallowing `TypeError`/`AttributeError` — a programming
error should surface, and only operational errors (connection loss) should be
degraded to a warning.

✅ **Pros:** prevents the next silent breakage of the same kind.
❌ **Cons:** changes failure behaviour, so it needs a deliberate decision about
whether result-storage reads may raise into callers.
📊 **Effort:** Low-Medium.

### Option C: Audit every `asyncdb` call site in the repo

The same confusion is easy to repeat; a grep for `\.fetch\(` and `\.fetchrow\(`
with more than one argument would find any siblings.

📊 **Effort:** Low, and probably worth doing once alongside Option A.

## Open Questions

- [ ] Are there other `conn.fetch(...)`/`conn.fetchrow(...)` call sites with
      arguments elsewhere in the repo? (Option C.)
- [ ] Should the broad `except Exception` in this class be narrowed generally?
      It is what turned a `TypeError` into an empty list.
- [ ] Is anything in production reading crew history through the Postgres
      backend and quietly seeing nothing?

## Recommendation

Option A immediately, with Option C as a one-off sweep. Option B is worth
considering but is a behavioural change and should be decided on its own merits.
