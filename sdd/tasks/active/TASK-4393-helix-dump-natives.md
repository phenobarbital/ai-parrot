# TASK-4393: HelixDB natives for the bulk-transfer surface — `HelixWikiStore.dump_*`, `HelixSchemaStore.dump_columns`, `HelixPersistence.export_commits` / `import_commits`

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 12 — "SQLite and HelixDB implement the bulk-read surface natively"; AC27; §4 `test_dump_bulk_surface_parity`)
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-4391, TASK-4377, TASK-4382, TASK-4384
**Assigned-to**: unassigned

---

## Context

TASK-4391 added the bulk-transfer surface with base defaults and SQLite natives and fixed the
**row contracts** every backend must return. `wikitoolkit migrate` (TASK-4394) can only copy a
plane *to and from* HelixDB losslessly if the HelixDB classes implement the same surface
natively instead of inheriting the `NotImplementedError` defaults:

- `HelixWikiStore` (TASK-4376/4377): `dump_attrs`, `dump_meta`, `dump_symbols`, `dump_embeddings`;
- `HelixSchemaStore` (TASK-4382): `dump_columns`;
- `HelixPersistence` (TASK-4383/4384): `export_commits` / `import_commits` — the HelixDB half of
  the `GraphHistoryTransfer` capability (`"history"` is declared on the registry row by TASK-4392).

This task also extends `tests/knowledge/wiki/test_dump_surface.py` with the `helix-memory`
backend so the same assertions prove SQLite ↔ HelixDB parity.

---

## Scope

- Add the four `dump_*` natives to `HelixWikiStore` in `wiki/helix_store.py`.
- Add `dump_columns` to `HelixSchemaStore` in `wiki/schema/helix_store.py`.
- Add `export_commits` / `import_commits` to `HelixPersistence` in `graphindex/persist_helix.py`.
- Extend `test_dump_surface.py`: `"helix-memory"` in `BACKENDS`, a helix branch in the `wiki_store`
  fixture, cross-backend parity of rows, `dump_columns` parity, and SQLite → HelixDB → SQLite
  commit-history round trip.

**NOT in scope**: base defaults / SQLite natives (TASK-4391); `GraphHistoryTransfer` Protocol and
the migration engine (TASK-4394); the registry `"history"` capability (TASK-4392); any change to
the existing write methods of the three Helix classes; Arango / Postgres natives.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` | MODIFY | `dump_attrs` / `dump_meta` / `dump_symbols` / `dump_embeddings` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py` | MODIFY | `dump_columns` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` | MODIFY | `export_commits` / `import_commits` |
| `packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py` | MODIFY | `helix-memory` backend + parity tests |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca`. **None of the four target files exists on `dev` yet** —
they are created by TASK-4376 / TASK-4382 / TASK-4383 / TASK-4391. Every name below marked
"(task)" is taken from those task files and MUST be re-verified in the worktree.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore           # store.py:697, :1092
from parrot.knowledge.wiki.symbols import SymbolRecord                           # symbols.py:58
from parrot.knowledge.wiki.schema.models import ColumnRecord                     # schema/models.py:34
from parrot.knowledge.wiki.schema.store import SchemaStore                       # schema/store.py:48
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence         # persist_sqlite.py:139
# (task) TASK-4372/4373/4374:
from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.helix.bootstrap import known_vector_dimensions             # (client, label) -> list[int]
from parrot.knowledge.helix.client import _sdk                                   # lazy helixdb accessor
# (task) TASK-4376/4377 — wiki/helix_store.py:
from parrot.knowledge.wiki.helix_store import HelixWikiStore                     # _c() -> HelixClient; module helper _symbol_from_props(props)
# (task) TASK-4382 — wiki/schema/helix_store.py:
from parrot.knowledge.wiki.schema.helix_store import HelixSchemaStore
# (task) TASK-4383/4384 — graphindex/persist_helix.py:
from parrot.knowledge.graphindex.persist_helix import HelixPersistence          # _client(ctx), _tenant_locks, _SEQ_KEY = "gi_commit_seq"
```

### Existing Signatures to Use
```python
# TASK-4391 row contracts (the parity oracle — SQLite natives in wiki/store.py / schema/store.py / persist_sqlite.py):
#   dump_attrs()      -> [{"concept_id", "key", "value"}] ordered by (concept_id, key)
#   dump_meta()       -> dict[str, str] key-ordered
#   dump_symbols()    -> list[SymbolRecord] ordered by concept_id
#   dump_embeddings() -> [{"concept_id", "vector": list[float], "model"}] ordered by concept_id
#   dump_columns()    -> list[ColumnRecord] ordered by (table_id, ordinal)
#   export_commits(ctx, *, after_seq=0, limit=500) -> commits with seq > after_seq ascending; row = commit fields + seq
#       + payload (decoded dict) + items [{item_type, item_key, prior(JSON text | None)}]; [] for an unused tenant
#   import_commits(ctx, commits, *, replace=False) -> int; replace ⇒ wipe first; else append-only, ValueError on an
#       existing commit_id or seq ≤ current max

# (task) TASK-4376 data model — wiki/helix_store.py
#   Page: unique concept_id; `stub` flag (edge-only targets, excluded from every dump); vector props embedding_<d> + embedding_model
#   PageAttr: unique attr_key = f"{concept_id}\x1f{key}"; props concept_id, key, value
#   Symbol: unique concept_id; SQLite symbols columns + source_id + search_text (TASK-4377 _symbol_props/_symbol_from_props)
#   Meta: unique key, prop value; internal keys "schema_version" (also in SQLite) and "vector_dims:<label>" (Helix-only)
#   class HelixWikiStore(BaseWikiStore): async def _c(self) -> HelixClient   (lazy initialize)
#   async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]   (TASK-4377 — last public method)
# (task) TASK-4382 — wiki/schema/helix_store.py: class HelixSchemaStore(HelixWikiStore) with Column nodes keyed
#   (table_id, name), COLUMN_OF edges; `async def find_columns(` same signature as schema/store.py:135
# (task) TASK-4384 — graphindex/persist_helix.py: GCommit(commit_id, seq, op, agent_id, run_id, asserted_by, reason,
#   committed_at, payload JSON text, reverted_at); GCommitItem(item_id, commit_id, item_type, item_key, prior JSON text, seq);
#   Meta gi_commit_seq; `async def get_commit(self, ctx: TenantContext, commit_id: str) -> Optional[dict[str, Any]]:`
```

### Blueprint anchors (expected counts once the dependency tasks land — re-run `grep -c -F` first)
| File | Anchor | Expected |
|---|---|---|
| `wiki/helix_store.py` | `    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]:` | 1 |
| `wiki/schema/helix_store.py` | `    async def find_columns(` | 1 |
| `graphindex/persist_helix.py` | `    async def get_commit(self, ctx: TenantContext, commit_id: str) -> Optional[dict[str, Any]]:` | 1 |
| `tests/knowledge/wiki/test_dump_surface.py` | `BACKENDS = ["sqlite"]  # TASK-4393 appends "helix-memory"` | 1 |
| `tests/knowledge/wiki/test_dump_surface.py` | `    raise AssertionError(request.param)` | 1 |

If a count differs, quote 2-3 lines of context to make the anchor unique before editing.

### Does NOT Exist
- ~~Any of the four target files on `dev`~~ — created by TASK-4376 / 4382 / 4383 / 4391.
- ~~A HelixDB "dump" op~~ — bulk reads are ordinary read batches (`n_with_label` + `value_map`), ordered in Python.
- ~~`GraphHistoryTransfer`~~ — TASK-4394.
- ~~`SymbolRecord.source_id`~~ — not a field (`symbols.py:58-100`); `dump_symbols` cannot carry it (TASK-4391 limit, flagged for TASK-4394).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py#ColumnRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py#SchemaStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py#SQLitePersistence"
  ]
}
```

---

## Implementation Notes

### Decisions (bounded by the TASK-4391 row contracts)
- **Stub pages are invisible**: `dump_attrs` / `dump_embeddings` skip concept ids whose `Page.stub` is true (SQLite has no row for them).
- **`dump_meta` excludes Helix-internal keys** starting with `vector_dims:` — the target backend re-derives its own index bookkeeping (SQLite has no such keys; a copy into HelixDB re-creates them through `upsert_embedding`). `schema_version` and every user key are included.
- **`dump_embeddings`**: for each `d in known_vector_dimensions(client, "Page")` read pages with a non-null `embedding_<d>`; one row per page. If a page carries more than one dimension (re-embedded with a different model) emit the highest `d` and `self.logger.warning` once with the count — SQLite keeps exactly one vector per page.
- **`export_commits` / `import_commits`** mirror TASK-4391 exactly; `prior` stays JSON text (TASK-4384 stores the canonical SQLite row shape, so priors are portable). `import_commits` runs under `self._tenant_locks[ctx.tenant_id]`, writes `GCommit` / `GCommitItem` nodes verbatim (`item_id = f"{commit_id}|{item_type}|{item_key}"`, item `seq` = commit `seq`) and sets `Meta gi_commit_seq = max(current, max imported seq)` in the same batch, so the next `apply_update` continues the sequence. It never touches `GNode` / edges. Split into several write batches only when the text budget (`dsl.TEXT_BATCH_BUDGET_BYTES`) requires it; the `replace=True` wipe is the first batch.
- Read-only stores may dump (no `_assert_writable()` in dump paths); `import_commits` has no read-only mode (persistence is never read-only).

### Key Constraints
- No top-level `helixdb` import; DSL through `parrot.knowledge.helix.dsl` / `_sdk()`.
- Do not change any existing method of the three classes; append only.
- Order in Python after the read (key-ordered output is the resume contract of TASK-4394).

---

## Implementation Blueprint

### Steps (in order)
1. Re-run the anchor greps; read the TASK-4376/4377/4382/4384 implementations for the exact label/property names.
2. Add the wiki natives, then `dump_columns`, then export/import — *why*: each is independent; parity tests drive them.
3. Extend `test_dump_surface.py`; run it (both backends) plus the Helix suites listed in Validation Commands.
4. `ruff check --fix` on the four files.

### `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` (MODIFY)
```python
# occurrences: expected 1 (verify: grep -c -F '    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]:' packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py)
# BEFORE — insert immediately above that line (inside class HelixWikiStore)
    # -- bulk-transfer surface (FEAT-670 M12; TASK-4391 row contracts) -----
    async def dump_attrs(self) -> list[dict[str, Any]]:
        """Every PageAttr of a non-stub page as ``{"concept_id", "key", "value"}`` ordered by (concept_id, key)."""
        client = await self._c()
        # FILL IN: read all PageAttr value_map(["concept_id", "key", "value"]) + the non-stub Page ids; filter; sort
        raise NotImplementedError

    async def dump_meta(self) -> dict[str, str]:
        """Every Meta key/value except Helix-internal ``vector_dims:*``, key-ordered."""
        client = await self._c()
        # FILL IN: read all Meta value_map(["key", "value"]); drop keys starting with "vector_dims:"; dict(sorted(...))
        raise NotImplementedError

    async def dump_symbols(self) -> list[SymbolRecord]:
        """Every Symbol node decoded with ``_symbol_from_props``, ordered by concept id."""
        client = await self._c()
        # FILL IN: read all Symbol props; sort by concept_id; [_symbol_from_props(p) for p in rows]
        raise NotImplementedError

    async def dump_embeddings(self) -> list[dict[str, Any]]:
        """``{"concept_id", "vector", "model"}`` per embedded non-stub page, ordered by concept id."""
        client = await self._c()
        # FILL IN: per known_vector_dimensions(client, "Page") read (concept_id, embedding_<d>, embedding_model, stub);
        #   highest d wins per page (+ one warning); sort — bounded by "Decisions"
        raise NotImplementedError

```

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py` (MODIFY)
```python
# occurrences: expected 1 (verify: grep -c -F '    async def find_columns(' packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py)
# BEFORE — insert immediately above that line (inside class HelixSchemaStore)
    async def dump_columns(self) -> list[ColumnRecord]:
        """Every Column node as a ``ColumnRecord`` ordered by (table_id, ordinal)."""
        client = await self._c()
        # FILL IN: read all Column props; map with the module's existing props→ColumnRecord helper (TASK-4382);
        #   sort by (table_id, ordinal) — bounded by SchemaStore.dump_columns parity
        raise NotImplementedError

```

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` (MODIFY)
```python
# occurrences: expected 1 (verify: grep -c -F '    async def get_commit(self, ctx: TenantContext, commit_id: str) -> Optional[dict[str, Any]]:' packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py)
# BEFORE — insert immediately above that line (inside class HelixPersistence)
    # -- GraphHistoryTransfer (capability "history", FEAT-670 M12) --------
    async def export_commits(
        self, ctx: TenantContext, *, after_seq: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Raw commits with ``seq > after_seq`` ascending (≤ ``limit``) incl. decoded payload and JSON-text priors."""
        client = await self._client(ctx)
        # FILL IN: GCommit where seq > after_seq, order_by seq asc, limit; items per commit (GCommitItem by commit_id,
        #   keys item_type/item_key/prior); payload = orjson.loads(payload) — bounded by TASK-4391 row contract
        raise NotImplementedError

    async def import_commits(
        self, ctx: TenantContext, commits: list[dict[str, Any]], *, replace: bool = False
    ) -> int:
        """Insert raw commit rows preserving commit_id / seq / reverted_at / items; advance ``gi_commit_seq``.

        Raises:
            ValueError: ``replace=False`` and an incoming commit id exists or an incoming ``seq`` ≤ the current max.
        """
        client = await self._client(ctx)
        async with self._tenant_locks[ctx.tenant_id]:
            # FILL IN: replace ⇒ drop every GCommit/GCommitItem first; else append-only checks; add nodes verbatim;
            #   set Meta gi_commit_seq = max(current, max seq) in the same batch — bounded by "Decisions"
            raise NotImplementedError

```

### `packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py` (MODIFY)
```python
# occurrences: 1 (verify: grep -c -F 'BACKENDS = ["sqlite"]  # TASK-4393 appends "helix-memory"' …/test_dump_surface.py)
# REPLACE that line with:
BACKENDS = ["sqlite", "helix-memory"]

# occurrences: 1 (verify: grep -c -F '    raise AssertionError(request.param)' …/test_dump_surface.py)
# BEFORE — insert above that line, inside the wiki_store fixture:
    if request.param == "helix-memory":
        pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")
        from parrot.knowledge.helix.settings import HelixMode, HelixSettings
        from parrot.knowledge.wiki.helix_store import HelixWikiStore

        store = HelixWikiStore(HelixSettings(mode=HelixMode.MEMORY, database=f"wiki_{uuid.uuid4().hex}"), wiki_name="t")
        await store.initialize()
        yield store
        await store.close()
        return
```
Add `import uuid` to the test imports, and append the tests in Test Specification.

### FILL IN checklist
- [ ] `HelixWikiStore.dump_attrs` / `dump_meta` / `dump_symbols` / `dump_embeddings` — "Decisions"
- [ ] `HelixSchemaStore.dump_columns` — ordering
- [ ] `HelixPersistence.export_commits` / `import_commits` — TASK-4391 row contract, seq counter
- [ ] new test bodies

---

## Acceptance Criteria

- [ ] **AC-1** (spec `test_dump_bulk_surface_parity`) on the same seeded plane, `dump_attrs` / `dump_meta` (minus nothing — Helix-internal keys already excluded) / `dump_symbols` / `dump_embeddings` return **equal** rows on `sqlite` and `helix-memory`.
- [ ] **AC-2** `HelixSchemaStore.dump_columns()` equals `SchemaStore.dump_columns()` for the same `upsert_columns` input.
- [ ] **AC-3** SQLite `export_commits` → Helix `import_commits` → Helix `export_commits` → fresh SQLite `import_commits` yields identical `get_commit` results (ids, `seq`, items, priors, `reverted_at`) at each hop; a non-reverted commit copied into HelixDB reverts there; the next Helix `apply_update` gets `seq = max + 1`.
- [ ] **AC-4** Helix `import_commits(replace=False)` refuses an existing `commit_id` / non-increasing `seq` with `ValueError`; `replace=True` wipes.
- [ ] **AC-5** (spec AC27) the Helix classes no longer raise `NotImplementedError` from any bulk method; pre-existing Helix suites still pass.
- [ ] **AC-6** `ruff check` clean on the three source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_helix_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_helix_schema_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_commit_protocol_helix.py -q`

---

## Test Specification

```python
# appended to packages/ai-parrot/tests/knowledge/wiki/test_dump_surface.py
@pytest.mark.asyncio
async def test_dump_parity_sqlite_vs_helix(tmp_path) -> None:
    """Seed both backends with _seed(); every dump_* is equal (AC-1)."""
    pytest.importorskip("helixdb_uniffi")
    # FILL IN: build SQLiteWikiStore + HelixWikiStore(memory), await _seed on both, compare the four dumps


@pytest.mark.asyncio
async def test_dump_columns_parity(tmp_path) -> None: ...                 # AC-2 — SchemaStore vs HelixSchemaStore(memory)


@pytest.mark.asyncio
async def test_commit_history_round_trip_sqlite_helix_sqlite(tmp_path) -> None: ...   # AC-3


@pytest.mark.asyncio
async def test_helix_import_commits_refusals() -> None: ...                # AC-4
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`).
2. Read spec §3 M12 / AC27 and the TASK-4391 "Row contracts".
3. TASK-4391, TASK-4377, TASK-4382 and TASK-4384 must be `done` in `sdd/tasks/index/helixdb-provider.json`.
4. Re-run every anchor grep; update this contract first if a dependency task named things differently.
5. Status `in-progress` → commit the index only.
6. Implement; append only — no edits to existing methods.
7. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; a skip because `helixdb_uniffi` is absent is not a pass (close as `done-with-issues` stating it if the wheel cannot be installed).
8. Commit only the four listed files; `scripts/sdd/close_task.sh TASK-4393 helixdb-provider verified`.
9. Fill in the Completion Note; commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
