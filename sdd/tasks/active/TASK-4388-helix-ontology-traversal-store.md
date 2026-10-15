# TASK-4388: HelixOntologyGraphStore — typed traversals, execute_pattern / execute_query

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4387, TASK-4386
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (G4, G10, AC7, AC25). TASK-4387 created `HelixOntologyGraphStore` with the
`GraphDocumentStore` half and `NotImplementedError("TASK-4388")` stubs for the six `OntologyTraversalStore`
methods. This task implements them on HelixDB:

- `is_reachable` — the **management-chain authorization primitive** (`AuthorizationChecker._check_management_chain`,
  authorization.py:216-257 calls it with `edge_collection="reports_to"`, `max_depth=10`).
- `get_document_by_id` — used by the same-department authorization rule and the entity resolver.
- `find_by_field`, `search_by_name` — entity resolution.
- `execute_pattern` — serves `query_templates["helix"]` (explicit or materialised by TASK-4385's validator), else
  compiles `traversal_spec` lazily with the `"helix"` compiler; otherwise `TraversalPatternUnavailable`.
  **Never** falls back to `query_template` (that is AQL).
- `execute_query` — `dialect != "helix"` → `QueryDialectMismatch`; helix text goes through the same read-only
  op-tree parser. No `"helix"` query validator is registered, so LLM-dynamic generation stays fail-closed
  (`OntologyIntentResolver` degrades to `vector_only`).

**Security relevance**: authorization decisions and tenant-authored templates flow through these methods —
adversarial `/sdd-codereview` is mandatory.

---

## Scope

- Replace the six stubs in `ontology/helix_graph_store.py` with real implementations.
- Tests `tests/knowledge/ontology/test_typed_traversals_helix.py`: typed ops on InMemory, fixture patterns via
  `execute_pattern`, dialect errors, authorization checker on the real Helix store, intent fail-closed.

**NOT in scope**: registering the backend (TASK-4392); a helix query validator (never in FEAT-670);
live AQL-vs-Helix parity (TASK-4397); editing `authorization.py`, `entity_resolver.py`, `mixin.py`, `intent.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/helix_graph_store.py` | MODIFY | implement the six OntologyTraversalStore methods |
| `packages/ai-parrot/tests/knowledge/ontology/test_typed_traversals_helix.py` | CREATE | typed-traversal + pattern + authorization tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.exceptions import TraversalPatternUnavailable, QueryDialectMismatch, QueryValidationError  # verified: exceptions.py:46,42,27
from parrot.knowledge.ontology.contracts import DynamicQuery                     # verified: contracts.py:17 (dialect, text, bind_vars, collection_binds)
from parrot.knowledge.ontology.validators import validate_query                  # verified: validators.py:120 — no "helix" validator registered (only "aql" :144)
from parrot.knowledge.ontology.authorization import AuthorizationChecker         # verified: authorization.py:72 (__init__(graph_store, reports_to_collection="reports_to") :82)
from parrot.knowledge.ontology.intent import OntologyIntentResolver              # verified: intent.py:50 (__init__(ontology, llm_client=None, dialect="aql") :83-86)
# created by earlier FEAT-670 tasks — verify on pickup:
from parrot.knowledge.ontology.traversal_spec import TraversalSpecUnsupported, compile_traversal_spec   # TASK-4385
from parrot.knowledge.helix.traversal import parse_helix_op_tree, build_helix_traversal                # TASK-4386
from parrot.knowledge.ontology.helix_graph_store import HelixOntologyGraphStore, ontology_database_name # TASK-4387
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py — OntologyTraversalStore :106
async def is_reachable(self, ctx, start_id: str, target_id: str, *, edge_collection: str, max_depth: int, direction: str = "outbound") -> bool  # :112
async def get_document_by_id(self, ctx, doc_id: str) -> dict | None                                             # :125
async def find_by_field(self, ctx, collection: str, field: str, value: Any, *, filters: Mapping | None = None, limit: int = 2) -> list[dict]  # :129
async def search_by_name(self, ctx, collection: str, needle: str, *, field: str = "name", filters: Mapping | None = None, limit: int = 10) -> list[dict]  # :142
async def execute_pattern(self, ctx, pattern: TraversalPattern, params: Mapping, collection_binds: Mapping[str, str] | None = None) -> list[dict]  # :155
async def execute_query(self, ctx, query: DynamicQuery) -> list[dict]                                           # :165

# Reference semantics — packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py (ArangoOntologyGraphStore)
#   is_reachable :342 — direction.upper() ∉ {OUTBOUND, INBOUND, ANY} → ValueError; max_depth < 1 → ValueError;
#     `FOR v IN 1..depth DIR @asker_id @@edge_collection FILTER v._id == @target_id`
#   get_document_by_id :383 — DOCUMENT(@target_id), None when absent
#   find_by_field :396 — equality on field + equality filters (_filter_clause :332), LIMIT
#   search_by_name :429 — LIKE(LOWER(e.f), '%'+needle.lower()+'%') + filters, SORT LENGTH(e.f) ASC, LIMIT
#   execute_pattern :465 — `templates.get(self.dialect) or query_template`; TraversalPatternUnavailable when none
#   execute_query :494 — query.dialect != self.dialect → QueryDialectMismatch
# packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:216 _check_management_chain → is_reachable(ctx, user_id,
#   target_id, edge_collection=self._reports_to, max_depth=10); exceptions are caught and logged → deny (:247-257)
# packages/ai-parrot/src/parrot/knowledge/ontology/intent.py:235-239 dynamic query: validate_query(self._dialect, …);
#   QueryValidationError → return None (vector_only)
# packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py:530-543 — pattern intents call execute_pattern; dynamic call execute_query
```

### Does NOT Exist
- ~~`register_query_validator("helix", …)`~~ — must not be added (AC7).
- ~~`ArangoOntologyGraphStore.execute_traversal`~~ — removed by FEAT-540.
- ~~a HelixDB "shortest path with predicate" helper in `helix/dsl.py`~~ — not in TASK-4374's skeleton; use the BFS below.
- ~~`TraversalPattern.query_templates["helix"]` on bundled defaults~~ — bundled patterns are AQL-only (spec Non-Goal);
  on HelixDB they raise `TraversalPatternUnavailable`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/helix_graph_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/test_typed_traversals_helix.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#OntologyTraversalStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#DynamicQuery",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py#TraversalPatternUnavailable",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py#QueryDialectMismatch",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/validators.py#validate_query",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py#AuthorizationChecker",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/intent.py#OntologyIntentResolver",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#ArangoOntologyGraphStore.is_reachable"
  ]
}
```

---

## Implementation Notes

### Decisions
- **`is_reachable`** — iterative bounded BFS, one read per depth level: frontier = `{start_id}`; for depth
  1..`max_depth` read the neighbours' `_id` over label `edge_collection` (`out` / `in_` / `both` by direction),
  return `True` as soon as `target_id` appears; keep a `visited` set; stop when the frontier is empty.
  Validate exactly like Arango (direction → `ValueError`, `max_depth < 1` → `ValueError`) and additionally cap
  `max_depth` at 10 (authorization uses 10) and the frontier at 800 ids per level — on overflow log a warning and
  return `False` (**fail closed = deny**). Missing start vertex → `False`. Same semantics as AQL `1..N`: depth-0
  (start == target) is `False` unless a cycle reaches it.
- **`get_document_by_id`** — `n_where(_id == doc_id)` (database is per tenant, so no label needed); strip the
  internal `search_text` property from every returned document (all read methods).
- **`find_by_field` / `search_by_name`** — `_IDENT`-check `collection`, `field` and every filter key; limits clamped to
  1..800. `search_by_name`: `text_search` on `search_text` (TASK-4374 `helix_dsl.text_search`) for candidate
  recall, then Python-side `needle.lower() in str(doc.get(field, "")).lower()` + filter equality, sort by
  `len(doc[field])` ascending, truncate to `limit` (parity with graph_store.py:429). If text search returns
  nothing for a non-tokenisable needle, fall back to a label scan bounded at 800 — FILL IN after checking
  tokenizer behaviour in the wheel.
- **`execute_pattern`** — order: `pattern.query_templates.get("helix")` → else if `pattern.traversal_spec`:
  `compile_traversal_spec(spec, "helix").text` (lazy; `TraversalSpecUnsupported` → `TraversalPatternUnavailable`)
  → else `TraversalPatternUnavailable`. Then `parse_helix_op_tree(text)` (pydantic error →
  `TraversalPatternUnavailable` with the reason; never execute an unparsable template), check every
  `define_params` name is in `params` (`ValueError` otherwise), `build_helix_traversal(tree, params,
  collection_binds or {})`, execute through `HelixClient.read`, strip `search_text`.
- **`execute_query`** — `query.dialect != "helix"` → `QueryDialectMismatch` (message mirrors graph_store.py:508);
  else the same parse → build → read path with `query.bind_vars` / `query.collection_binds`. It does **not**
  call `validate_query` (that is the intent resolver's job and has no helix validator — fail closed upstream).

### Drift vs spec
- Spec §2 skeleton names `QueryRequest` for execution; the op-tree is executed via TASK-4386's
  `build_helix_traversal` + `HelixClient.read` instead (no raw SDK JSON pass-through — read-only by construction).
- `intent.py:265` returns `query_template` (AQL) as `ResolvedIntent.query` even for dialect `"helix"`; harmless
  because pattern intents execute through `execute_pattern(pattern, …)` (mixin.py:530), which never reads
  `query_template` here. Record in the Completion Note; do not edit intent.py.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read TASK-4387's `helix_graph_store.py`, TASK-4386's `helix/traversal.py` public functions.
2. Implement `is_reachable` and `get_document_by_id` first (authorization), then finders, then pattern/query.
3. Write tests; run the TASK-4385/4386 suites too.

### `packages/ai-parrot/src/parrot/knowledge/ontology/helix_graph_store.py` (MODIFY)
```python
# occurrences: 6 of `raise NotImplementedError("TASK-4388")` (one per stub; written by TASK-4387) — replace each
#   method body; anchor on each `async def <name>(` line, which is unique (verify grep -c -F 'async def is_reachable(' → 1).
# add imports (anchor: the `from parrot.knowledge.ontology.schema import TenantContext, TraversalPattern` line, 1 occurrence):
from parrot.knowledge.helix.traversal import build_helix_traversal, parse_helix_op_tree
from parrot.knowledge.ontology.exceptions import QueryDialectMismatch, TraversalPatternUnavailable
from parrot.knowledge.ontology.traversal_spec import TraversalSpecUnsupported, compile_traversal_spec

_MAX_DEPTH = 10
_MAX_FRONTIER = 800
_DIRECTIONS = {"outbound": "out", "inbound": "in_", "any": "both"}

    async def is_reachable(
        self, ctx: TenantContext, start_id: str, target_id: str, *,
        edge_collection: str, max_depth: int, direction: str = "outbound",
    ) -> bool:
        """Bounded BFS; fails closed (False) on frontier overflow."""
        step = _DIRECTIONS.get(direction.lower())
        if step is None:
            raise ValueError(f"Unsupported traversal direction {direction!r}")
        depth = int(max_depth)
        if depth < 1:
            raise ValueError("max_depth must be >= 1")
        label = _label(edge_collection)
        frontier, visited = {start_id}, {start_id}
        for _ in range(min(depth, _MAX_DEPTH)):
            # FILL IN: one HelixClient.read: n_where(_id in frontier) → <step>(label) → value_map(["_id"]);
            #   next = ids - visited; return True if target_id in ids; overflow (> _MAX_FRONTIER) → warn + return False
            ...
        return False

    async def execute_pattern(
        self, ctx: TenantContext, pattern: TraversalPattern, params: Mapping[str, Any],
        collection_binds: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        text = (pattern.query_templates or {}).get(self.dialect)
        if not text and pattern.traversal_spec is not None:
            try:
                text = compile_traversal_spec(pattern.traversal_spec, self.dialect).text
            except TraversalSpecUnsupported as exc:
                raise TraversalPatternUnavailable(f"Pattern has no {self.dialect!r} template: {exc}") from exc
        if not text:
            raise TraversalPatternUnavailable(f"Pattern has no {self.dialect!r} query template")
        return await self._run_op_tree(ctx, text, params, collection_binds or {})

    async def execute_query(self, ctx: TenantContext, query: DynamicQuery) -> list[dict[str, Any]]:
        if query.dialect != self.dialect:
            raise QueryDialectMismatch(f"Store dialect is {self.dialect!r}, query dialect is {query.dialect!r}")
        return await self._run_op_tree(ctx, query.text, query.bind_vars, query.collection_binds)

    async def _run_op_tree(self, ctx, text: str, params: Mapping[str, Any], binds: Mapping[str, str]) -> list[dict[str, Any]]:
        try:
            tree = parse_helix_op_tree(text)
        except ValueError as exc:   # pydantic.ValidationError subclasses ValueError
            raise TraversalPatternUnavailable(f"helix template rejected: {exc}") from exc
        missing = [p for p in tree.define_params if p not in params]
        if missing:
            raise ValueError(f"missing traversal params: {missing}")
        traversal = build_helix_traversal(tree, params, binds)
        # FILL IN: execute via (await self._client(ctx)).read(<read batch wrapping traversal>, query_name="ont.pattern");
        #   normalise rows to list[dict]; strip "search_text" — bounded by TASK-4386's build_helix_traversal return type
        raise NotImplementedError

    # FILL IN: get_document_by_id, find_by_field, search_by_name per "Decisions" (strip search_text, _IDENT checks, limit clamp)
```
**Why**: `execute_pattern` deliberately has no `query_template` fallback (AQL must never be sent to HelixDB);
both pattern and dynamic paths share one parser-gated executor so a tenant overlay cannot reach a write op;
`is_reachable` denies rather than guesses when bounds are exceeded.

### FILL IN checklist
- [ ] `is_reachable` per-level read + overflow deny
- [ ] `_run_op_tree` execution + row normalisation
- [ ] `get_document_by_id`, `find_by_field`, `search_by_name` (+ text-search fallback decision)

---

## Acceptance Criteria

- [ ] AC7: typed ops behave on InMemory; a pattern with `query_templates["helix"]` (explicit) and a
      `traversal_spec`-only pattern both run via `execute_pattern`; an AQL-only pattern raises
      `TraversalPatternUnavailable`; `execute_query(DynamicQuery(dialect="aql", …))` raises `QueryDialectMismatch`;
      `await validate_query("helix", "...")` raises `QueryValidationError` (no validator registered).
- [ ] AC25 (part): fixture patterns (`find_team`, `authoritative_doc_for_topic`) executed on InMemory return the expected ids.
- [ ] A hand-written helix template containing a write op (`{"op": "drop"}`) raises `TraversalPatternUnavailable`
      and the database is unchanged.
- [ ] `AuthorizationChecker(store)` management-chain rule: allow for a 3-hop subordinate, deny for a non-subordinate,
      deny (no exception escapes) when the frontier cap is exceeded.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/test_typed_traversals_helix.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/test_helix_graph_store.py -q`
- `pytest packages/ai-parrot/tests/knowledge/helix/test_traversal_helix.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/ontology/test_typed_traversals_helix.py
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

pytest.importorskip("helixdb")

import parrot.knowledge.helix  # noqa: F401  (registers the "helix" compiler)
from parrot.knowledge.helix.settings import HelixMode, HelixSettings
from parrot.knowledge.ontology.contracts import DynamicQuery
from parrot.knowledge.ontology.exceptions import QueryDialectMismatch, QueryValidationError, TraversalPatternUnavailable
from parrot.knowledge.ontology.helix_graph_store import HelixOntologyGraphStore, ontology_database_name
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext, TraversalPattern
from parrot.knowledge.ontology.validators import validate_query

FIXTURE = Path(__file__).parent / "fixtures" / "portable.ontology.yaml"
PATTERNS = yaml.safe_load(FIXTURE.read_text())["traversal_patterns"]


def _ctx(tenant: str = "t1") -> TenantContext:
    onto = MergedOntology(name="t", version="1", entities={}, relations={}, traversal_patterns={}, layers=[],
                          merge_timestamp=datetime.now(timezone.utc))
    return TenantContext(tenant_id=tenant, arango_db="ignored", pgvector_schema=tenant, ontology=onto)


@pytest.fixture
async def store():
    s = HelixOntologyGraphStore(lambda ctx: HelixSettings(mode=HelixMode.MEMORY, database=ontology_database_name(ctx.tenant_id)))
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_execute_pattern_helix_dialect(store) -> None:
    ctx = _ctx()
    aql_only = TraversalPattern(description="d", query_template="FOR v IN c RETURN v")
    with pytest.raises(TraversalPatternUnavailable):
        await store.execute_pattern(ctx, aql_only, {})
    with pytest.raises(QueryDialectMismatch):
        await store.execute_query(ctx, DynamicQuery(dialect="aql", text="FOR v IN c RETURN v"))
    with pytest.raises(QueryValidationError):
        await validate_query("helix", "{}")
    hostile = TraversalPattern(description="d", query_templates={"helix": '{"version":1,"steps":[{"op":"drop"}]}'})
    with pytest.raises(TraversalPatternUnavailable):
        await store.execute_pattern(ctx, hostile, {})


@pytest.mark.asyncio
async def test_traversal_spec_compile_helix_executes(store) -> None:
    # FILL IN: seed employees e1..e3 + member_of_team edges (e1,e2,e3 → team t) via upsert_nodes/create_edges;
    #   find_team with {"user_id": "employees/e1"} and binds {"@member_of_team": "member_of_team"} → {e2, e3} ids
    ...


@pytest.mark.asyncio
async def test_is_reachable_and_authorization(store) -> None:
    # FILL IN: reports_to chain a→b→c→d; is_reachable(a, d, max_depth=10) True, (d, a) False, bad direction ValueError;
    #   AuthorizationChecker(store) management-chain rule allows a over d and denies d over a
    ...


@pytest.mark.asyncio
async def test_find_and_search_by_name(store) -> None:
    # FILL IN: find_by_field equality + filters + limit; search_by_name case-insensitive contains, shortest first
    ...
```

---

## Agent Instructions

1. **Work in the feature worktree** `feat-FEAT-670-helixdb-provider`
   (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`), never on `dev`.
2. Read spec §3 Module 8, §4 rows `test_helix_ontology_store_contracts` / `test_execute_pattern_helix_dialect` /
   `test_traversal_spec_compile_helix`, AC7 and AC25.
3. Check `Depends-on` (TASK-4387, TASK-4386) are `done` in `sdd/tasks/index/helixdb-provider.json`.
4. Re-verify the contract: `grep -n 'NotImplementedError("TASK-4388")' .../ontology/helix_graph_store.py` (expect 6),
   `grep -n '^def ' .../helix/traversal.py`, and authorization.py's call at :240-246.
5. Mark `in-progress` in the per-spec index; commit only that file.
6. Implement from the blueprint; complete every `# FILL IN:`; no `query_template` fallback; no helix validator.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; `ruff check --fix` the touched files.
8. **Security review is mandatory**: run `/sdd-codereview TASK-4388` (adversarial, codex second opinion) before
   closing. Focus: authorization reachability correctness and fail-closed bounds, template execution read-only
   guarantee, no AQL leaking to HelixDB, param/bind completeness, internal `search_text` never returned.
   Triage every finding CONFIRM / REJECT / ESCALATE in the Completion Note.
9. Commit only the listed files: `feat(helixdb-provider): TASK-4388 — HelixOntologyGraphStore typed traversals`.
10. `scripts/sdd/close_task.sh TASK-4388 helixdb-provider verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
