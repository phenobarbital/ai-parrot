# TASK-3829: Federated symbol queries: fan-out, qualified ids, `--ns`, no foreign read-repair

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3822, TASK-3826, TASK-3828
**Assigned-to**: unassigned

---

## Context

Spec §8 Q4 ("preferably yes") / §3 Module 5 / G8. `FederatedWikiStore`'s symbol methods are
local-only by v1 design (`federation.py:1397`), and the CLI hands the structural tools the bare
local plane (`_structural_tool`, `cli.py:2237`). So from a repo that federates
`navigator-svelte`, `symbols lookup requireDashboardContainer` returns nothing.

**Safety finding (2026-09-28), fixed here.** `StructuralService._ensure_fresh`
(`structural/service.py:431`) compares the **local** disk hash of each hit's `rel_path` with
the store's `page_hashes`. When the service reads a *foreign* plane, the file is not on local
disk and the hashes disagree. The service then tries to re-ingest or remove that source on the
foreign store (`service.py:474`, `:486`). The existing explicit-namespace path already builds
such a service (`structural/tools.py:257`). Every service over a foreign plane must skip
read-repair.

---

## Scope

- **Provenance (runtime only).**
  - `SymbolRecord` gains `namespace: str | None = Field(default=None, exclude=True)`. Backends
    persist explicit columns (e.g. `store.py:1747-1790`), so the field never reaches storage;
    `exclude=True` also keeps it out of `model_dump`.
  - `SymbolHit` gains `namespace: str | None = None`.
  - `_record_to_hit` sets `namespace` and qualifies `symbol_id` with `qualify_id(namespace, …)`
    when it is set.
- **Fan-out.**
  - `FederatedWikiStore.find_symbols` / `search_symbols_fts` call `self._fan_out(<name>, …)`
    (`federation.py:775`; it already works for any list-returning method) and tag every record
    of a non-`None` namespace group with `model_copy(update={"namespace": ns})`.
  - The merge puts the local group first, then the other groups by descending namespace
    weight, keeping each group's own order, capped at `limit`.
  - Skipped namespaces are already recorded by `_fan_out` in `last_skipped`.
  - `symbols_for` stays local.
- **Qualified targets (outline/blast).** In `StructuralService.outline` and `blast_radius`, if
  the target or seed is namespace-qualified (`split_namespaced_id`, `context.py:55`) and the
  store is a `FederatedWikiStore`, re-dispatch to
  `StructuralService(<scoped>, root, config, read_repair=False)` with the unqualified id, and
  return its result. `<scoped>` is:
  - `self._store.scoped(ns)` normally;
  - `self._store` itself when `ns == self._store.local_name` (an already-scoped store raises
    `KeyError` for its own name).
- **No foreign read-repair.**
  - `StructuralService.__init__` gains a keyword-only `read_repair: bool = True`. When it is
    False, `_ensure_fresh` returns `[]` immediately.
  - In `lookup`, only hits whose `namespace` is `None` are passed to `_ensure_fresh`.
  - `structural/tools.py`'s `service_factory` builds the foreign service with
    `read_repair=False` (`tools.py:257`).
- **CLI.**
  - `_structural_tool(name, path_, ns_opt=None)` wraps the store with the existing
    `_federate(root, config, _require_built(root, config), ns_opt)` (`cli.py:187`).
  - `symbols lookup|outline|blast` gain the existing `@ns_option` (`cli.py:135`) and pass
    `ns_opt` through.
  - The `--rel` help text (`cli.py:2338`) lists `uses` in the default set, which TASK-3826
    added.
- Write tests, including the end-to-end lookup across a namespace.

**NOT in scope**: cross-namespace symbol *edges* (spec Non-Goals); the legacy-FTS re-probe
(TASK-3827).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py` | MODIFY | `SymbolRecord.namespace` (runtime-only) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | fan-out for `find_symbols`/`search_symbols_fts` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` | MODIFY | `SymbolHit.namespace`, qualified ids, re-dispatch, `read_repair` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` | MODIFY | `read_repair=False` for foreign services |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `--ns` on `symbols *`, `_federate` in `_structural_tool`, `--rel` help |
| `tests/knowledge/wiki/test_federated_symbols.py` | CREATE | unit + end-to-end tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.context import qualify_id, split_namespaced_id     # context.py:83, :55
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle  # federation.py:622, :96
from parrot.knowledge.wiki.structural.service import StructuralService, SymbolHit  # service.py:116, :47
```

### Existing Signatures to Use
```python
# symbols.py:56  class SymbolRecord(BaseModel): ... depth: int = 1   (last field, symbols.py:102)
# federation.py:96   class NamespaceHandle: name, store, config, origin, storage_dir, read_only; weight (property)
# federation.py:622  class FederatedWikiStore(BaseWikiStore)
#   local_name, namespaces: dict[str, NamespaceHandle], _local, _local_prefix (property, :708)
#   def scoped(self, selector: str | None) -> BaseWikiStore:          # :712; single name -> FederatedWikiStore(local=handle.store, qualify_local=True, ...) :731-748; KeyError on unknown
#   async def _fan_out(self, call: str, *args, **kwargs) -> list[tuple[str | None, float, list]]   # :775
#   async def find_symbols(self, name=None, qualname_prefix=None, kind=None, language=None, path_prefix=None, limit=50) -> list[Any]:  # :1408
#   async def search_symbols_fts(self, query: str, limit: int = 20) -> list[Any]:                    # :1427
# structural/service.py
#   class SymbolHit(BaseModel): symbol_id, rel_path, qualname, kind, signature, doc, start_line, end_line, exported, score, stale   # :47-60
#   def _record_to_hit(record: SymbolRecord, *, score: float = 0.0, stale: bool = False) -> SymbolHit:   # :99
#   class StructuralService:
#       def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None:          # :126
#       async def lookup(...)            # :142-172 (calls self._ensure_fresh(rel_paths) at :166)
#       async def outline(self, target, *, depth=2, include_source=False) -> CodeOutlineOutput:           # :224
#       async def blast_radius(self, symbol, *, relations=None, depth=2, include_inferred=True, include_tests=True)  # :293
#       async def _ensure_fresh(self, rel_paths: list[str]) -> list[str]:                                  # :431
# structural/tools.py:243-257
#   local_service = StructuralService(store, root, config)
#   def service_factory(namespace): scoped = _scoped_store(store, namespace); ...; return StructuralService(scoped, root, config)   # :257
# cli.py
#   ns_option = click.option("--ns", "ns_opt", default=None, help=...)                                       # :135
#   def _federate(root: Path, config: WikiProjectConfig, local: BaseWikiStore, ns_opt: str | None) -> BaseWikiStore:  # :187
#   def _structural_tool(name: str, path_: str | None) -> Any:                                               # :2237
#   @symbols.command("lookup") :2288 / ("outline") :2312 / ("blast") :2331 ; --rel help at :2338
```

### Does NOT Exist
- ~~`SymbolRecord.namespace` / `SymbolHit.namespace`~~: created here.
- ~~`StructuralService(read_repair=…)`~~: created here.
- ~~A public `FederatedWikiStore.route()`~~: `_route` is private, and this task does not use it.
- ~~Cross-namespace `calls`/`uses` edges~~: never. Resolution is per plane at build time.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/federation.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_federated_symbols.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore.find_symbols",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore.search_symbols_fts",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore.scoped",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#_record_to_hit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_structural_tool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_federate"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never write to a foreign plane.** This is the load-bearing invariant: mutation-check it.
- Dedup in `StructuralService._search` keys on `sym_concept_id(rel_path, qualname)`
  (`service.py:189`). With namespaces, two planes can share a `rel_path`+`qualname`, so the key
  must become the *qualified* id.
- A single-namespace scoped store (`qualify_local=True`) reports its namespace through
  `_local_prefix`. Its "local" group is therefore tagged too, and ids come out qualified. That
  is intended.
- Complexity budget: keep `outline`/`blast_radius` changes to a guard clause plus one helper
  (`_redispatch_for(target) -> StructuralService | None`).

---

## Implementation Blueprint

### Steps (in order)
1. `SymbolRecord.namespace`. 2. Fan-out in `FederatedWikiStore`. 3. The service: `read_repair`,
`SymbolHit.namespace`, qualified ids, dedup key, re-dispatch. 4. `tools.py`: foreign services
get `read_repair=False`. 5. The CLI. 6. Tests, then mutation-check the no-foreign-write
invariant.

### `packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    depth: int = 1' symbols.py)
# AFTER — insert below `    depth: int = 1` (SymbolRecord's last field, verified: symbols.py:102)
    #: FEAT-609 M5: runtime-only provenance set by FederatedWikiStore for rows read
    #: from a foreign namespace. Never persisted (backends write explicit columns)
    #: and excluded from model_dump.
    namespace: str | None = Field(default=None, exclude=True)
```
Add `namespace` to the class docstring's Attributes.

### `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -c '    async def find_symbols(' / '    async def search_symbols_fts(self, query: str, limit: int = 20) -> list\[Any\]:' federation.py)
# REPLACE the bodies of find_symbols (federation.py:1408-1425) and search_symbols_fts (:1427-1429);
# also update the section comment at :1397 ("local plane only in v1") to say symbols now fan out.

    async def find_symbols(self, name=None, qualname_prefix=None, kind=None, language=None, path_prefix=None, limit=50) -> list[Any]:
        """Local plane + every namespace; foreign rows carry ``namespace`` (FEAT-609 M5)."""
        groups = await self._fan_out(
            "find_symbols",
            name=name, qualname_prefix=qualname_prefix, kind=kind,
            language=language, path_prefix=path_prefix, limit=limit,
        )
        return self._merge_symbol_groups(groups, limit)

    async def search_symbols_fts(self, query: str, limit: int = 20) -> list[Any]:
        """BM25 per plane, merged local-first then by namespace weight (FEAT-609 M5)."""
        groups = await self._fan_out("search_symbols_fts", query, limit)
        return self._merge_symbol_groups(groups, limit)

    def _merge_symbol_groups(self, groups: list[tuple[str | None, float, list[Any]]], limit: int) -> list[Any]:
        """Tag foreign records with their namespace; local group first, then by weight."""
        # FILL IN: order = [g for g in groups if g[0] == self._local_prefix] first, then the
        # rest sorted by weight desc (stable); for each group with a non-None namespace,
        # record.model_copy(update={"namespace": ns}); concatenate; cap at limit —
        # bounded by §Scope "Fan-out"
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` (MODIFY)
```python
# SymbolHit (service.py:47-60): add as the last field
    namespace: str | None = None

# _record_to_hit (service.py:99-113): qualify when the record came from a namespace
    symbol_id = sym_concept_id(record.rel_path, record.qualname)
    if record.namespace:
        symbol_id = qualify_id(record.namespace, symbol_id)
    # ...and pass namespace=record.namespace into SymbolHit(...)

# __init__ (service.py:126): keyword-only flag
    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig, *, read_repair: bool = True) -> None:
        ...
        self._read_repair = read_repair

# _ensure_fresh (service.py:431): first statement after the docstring
        if not self._read_repair:
            return []

# lookup (service.py:165): only local hits are read-repaired
        rel_paths = sorted({hit.rel_path for hit in hits if hit.namespace is None})

# _search._add (service.py:187-192): dedup on the QUALIFIED id
        def _add(record: SymbolRecord, score: float) -> None:
            hit = _record_to_hit(record, score=score)
            if hit.symbol_id in seen:
                return
            seen.add(hit.symbol_id)
            hits.append(hit)
```
```python
# New helper + guard clauses in outline() and blast_radius()
    def _redispatch_for(self, target: str) -> tuple["StructuralService", str] | None:
        """A read-only service over the namespace ``target`` names, plus the unqualified id.

        ``None`` when ``target`` is unqualified or the store is not federated.
        """
        namespace, local_id = split_namespaced_id(target)
        if namespace is None or not isinstance(self._store, FederatedWikiStore):
            return None
        # FILL IN: scoped = self._store.scoped(namespace), or self._store when namespace ==
        # self._store.local_name (KeyError otherwise -> return None and let the caller answer
        # "not found") — bounded by §Scope "Qualified targets"
        return StructuralService(scoped, self._root, self._config, read_repair=False), local_id

# first lines of outline():
        redispatch = self._redispatch_for(target)
        if redispatch is not None:
            service, local_target = redispatch
            return await service.outline(local_target, depth=depth, include_source=include_source)
# first lines of blast_radius(): same pattern with `symbol`, forwarding every kwarg.
```
A module-level `from parrot.knowledge.wiki.federation import FederatedWikiStore` in
`service.py` is cycle-safe. Verified: `federation.py` imports `store`, `context` and `project`,
and never `structural` (`federation.py:33-60`). Also import
`qualify_id, split_namespaced_id` from `parrot.knowledge.wiki.context`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        return StructuralService(scoped, root, config)' structural/tools.py)
# REPLACE that line (verified: tools.py:257) with:
        return StructuralService(scoped, root, config, read_repair=False)
```
Update the comment above it (`tools.py:250-256`): read-repair is now explicitly off rather than
"naturally never finds a file".

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# _structural_tool (cli.py:2237): signature + store
def _structural_tool(name: str, path_: str | None, ns_opt: str | None = None) -> Any:
    ...
    store = _federate(root, config, _require_built(root, config), ns_opt)

# each of symbols_lookup / symbols_outline / symbols_blast (cli.py:2288 / :2312 / :2331):
#   add `@ns_option` under `@path_option`, add `ns_opt: str | None` to the signature,
#   and call `_structural_tool("<tool>", path_, ns_opt)`.
# --rel help (cli.py:2338): "default: calls, extends, implements, uses."
```

### `tests/knowledge/wiki/test_federated_symbols.py` (CREATE)
```python
"""FEAT-609 M5: symbol queries read federated namespaces; foreign planes are never written."""

from __future__ import annotations

import pytest


@pytest.fixture
async def federation(tmp_path):
    # FILL IN: two REAL SQLiteWikiStore planes (local A, namespace "ns" B), each with one
    # upserted SymbolRecord (A: "localFn" in a.py; B: "remoteFn" in src/lib/x.ts), wrapped
    # in FederatedWikiStore with a NamespaceHandle — follow tests/knowledge/wiki/test_federation.py
    ...


async def test_federated_find_symbols_fans_out(federation) -> None:
    # FILL IN: find_symbols(name="remoteFn") returns B's record with namespace == "ns";
    # a query matching both returns the local one first
    ...


async def test_federated_symbols_skip_unopenable(federation) -> None:
    # FILL IN: a handle whose store raises -> query still answers; last_skipped names it
    ...


async def test_lookup_hit_is_qualified(federation, tmp_path) -> None:
    # FILL IN: StructuralService(federation, tmp_path, config).lookup("remoteFn") ->
    # hit.symbol_id == "ns::sym:src/lib/x.ts#remoteFn", hit.namespace == "ns"
    ...


async def test_outline_redispatches_qualified_target(federation, tmp_path) -> None:
    # FILL IN: outline("ns::src/lib/x.ts") returns B's symbols
    ...


async def test_foreign_plane_never_written(federation, tmp_path) -> None:
    # FILL IN: B opened read_only=True; lookup/outline/blast over "ns" ids must not raise
    # PermissionError and B's page/symbol counts are unchanged afterwards.
    # Mutation proof: set read_repair=True in _redispatch_for / tools.py and this goes RED.
    ...


def test_cli_symbols_ns_option(tmp_path) -> None:
    # FILL IN: CliRunner `symbols lookup remoteFn --ns ns` over a tmp repo whose wiki.json
    # declares the namespace (as tests/knowledge/wiki/test_cli.py does for --ns on query)
    ...
```

### FILL IN checklist
- [ ] `_merge_symbol_groups` ordering and tagging. Bound: §Scope "Fan-out".
- [ ] `_redispatch_for` scoped-store resolution, including the `local_name` case.
- [ ] Every test. Bound: real sqlite planes, and `test_foreign_plane_never_written` is
  mutation-checked.

---

## Acceptance Criteria

- [ ] From a repo that federates another, `wikitoolkit symbols lookup <foreign name>` returns
      the hit qualified with the namespace, both by default and with `--ns <name>` (spec AC).
- [ ] `outline`/`blast` accept a qualified target and answer from that namespace.
- [ ] No write ever reaches a foreign plane (mutation-checked).
- [ ] Local-only behaviour is unchanged: the existing `tests/knowledge/wiki/structural/*` and
      `test_cli_symbols.py` pass.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_federated_symbols.py -q`
- `pytest tests/knowledge/wiki/structural/test_service.py -q`
- `pytest tests/knowledge/wiki/structural/test_tools.py -q`
- `pytest tests/knowledge/wiki/test_cli_symbols.py -q`
- `pytest tests/knowledge/wiki/test_federation.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Confirm TASK-3822, TASK-3826 and TASK-3828 are `done`. Re-locate the anchors by text, since
   earlier tasks shifted the line numbers.
3. Implement, validate, mutation-check the no-foreign-write invariant, and stage only the
   listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3829 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
