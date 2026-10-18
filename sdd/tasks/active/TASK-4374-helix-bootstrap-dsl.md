# TASK-4374: HelixDB plane bootstrap, DSL helpers and package exports

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4373
**Assigned-to**: unassigned

---

## Context

Completes spec §3 Module 1. Every plane backend (wiki, ledger, schema, GraphIndex, ontology,
PageIndex, BookStore) bootstraps its labels through `ensure_plane` and builds its queries
from the shared DSL helpers — the "design every other module depends on" (spec §3
delegation table: M1 not delegation-eligible). The spec §2 "Data-model mapping" is
normative here: one label per record kind, user keys as **unique equality indexes**,
find-or-add edges (HelixDB is a multigraph), BM25 on a top-level `search_text`, lazy
per-dimension vector indexes recorded in `Meta vector_dims:<label>`, CAS via
`BatchCondition`.

This task also creates `parrot/knowledge/helix/__init__.py` with **exports only** — no
registry registrations (those land in TASK-4386 for the traversal compiler and TASK-4392
for `register_all()`).

---

## Scope

- Create `parrot/knowledge/helix/bootstrap.py`: `LabelSpec`, `PlaneSchema`, `ensure_plane`,
  `ensure_vector_index`, `known_vector_dimensions`.
- Create `parrot/knowledge/helix/dsl.py` (pure builders, no I/O): `lookup_by_key`,
  `upsert_node_entries`, `find_or_add_edge_entries`, `text_search`, `vector_search`,
  `cas_page_entries`, plus the `MAX_SEARCH_LIMIT = 800` clamp.
- Create `parrot/knowledge/helix/__init__.py` exporting the spec §2 "New Public Interfaces"
  names of the helix package (settings, client, bootstrap, errors).
- Tests `test_bootstrap.py`, `test_dsl.py`.

**NOT in scope**: any plane backend (TASK-4376+); `helix/traversal.py` and the compiler
registration (TASK-4386); `register_all()` (TASK-4392); conftest changes (TASK-4373 owns
conftest; TASK-4396 extends it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/helix/bootstrap.py` | CREATE | LabelSpec, PlaneSchema, ensure_plane, ensure_vector_index, known_vector_dimensions |
| `packages/ai-parrot/src/parrot/knowledge/helix/dsl.py` | CREATE | pure DSL builders |
| `packages/ai-parrot/src/parrot/knowledge/helix/__init__.py` | CREATE | package exports only |
| `packages/ai-parrot/tests/knowledge/helix/test_bootstrap.py` | CREATE | idempotence, receipt polling, lazy vector dims |
| `packages/ai-parrot/tests/knowledge/helix/test_dsl.py` | CREATE | find-or-add dedupe, CAS conditions, clamps |

---

## Codebase Contract (Anti-Hallucination)

Verified on dev @ `1c239a5ca`. `helixdb` is not installed in the shared `.venv`; SDK names
below are the spec §6 wheel-verified list (helix-db 0.3.4) — re-check each against the wheel
before use (Agent Instructions step 6).

### Verified Imports
```python
from parrot.knowledge.helix.client import HelixClient, open_helix_client, _sdk   # TASK-4373
from parrot.knowledge.helix.settings import HelixSettings, HelixMode, resolve_helix_settings  # TASK-4372
from parrot.knowledge.helix.errors import HelixExtraMissing, HelixUnavailable, HelixWriteRejected  # TASK-4372
from pydantic import BaseModel, Field
# SDK (lazy, via _sdk() inside functions) — spec §6:
#   g, read_batch, write_batch, define_params, IndexSpec, Predicate, BatchCondition, VectorDistanceMetric, NodeRef
```

### Existing Signatures to Use
```python
# helixdb/dsl.py (spec §6, wheel line numbers)
read_batch() :3410 ; write_batch() :3414 ; g() :3054
IndexSpec :1284            # node_equality, node_unique_equality, node_range, node_text, node_vector
Predicate :770             # Predicate.eq(prop, value), …
BatchCondition :3175       # var_not_empty / var_empty / var_min_size
ReadBatch.var_as_if :3271 ; WriteBatch.var_as_if :3358
VectorDistanceMetric :592  # cosine / euclidean / manhattan
# Traversal ops: n, n_where, n_with_label, out, in_, both, out_e, in_e, add_n, add_e, set_property,
#   remove_property, drop, drop_edge, drop_edge_by_id, create_index_if_not_exists, drop_index,
#   get_index_operation, create_text_index_nodes, create_vector_index_nodes, text_search_nodes,
#   vector_search_nodes, where, limit, skip, order_by, dedup, count, value_map, project, …
# Limits: whole-index search cap 800; text/vector indexes on top-level properties only
```

### Does NOT Exist
- ~~`g().upsert(...)` / any HelixDB upsert op~~ — emulate with `var_as_if` + `add_n` / `set_property`.
- ~~unique edge index~~ — HelixDB never dedupes edges; use `find_or_add_edge_entries`.
- ~~`SearchConsistency` on 0.3.4~~ — not settable.
- ~~`parrot.knowledge.helix.register_all` / compiler registration~~ — later tasks (4386, 4392).
- ~~nested-property text/vector indexes~~ — top-level properties only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/helix/bootstrap.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/helix/dsl.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/helix/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/helix/test_bootstrap.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/helix/test_dsl.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- No `helixdb` import at module scope in any of the three modules; `import parrot.knowledge.helix`
  must succeed without the extra (AC3: the error appears only when a backend is *selected*).
- `ensure_plane` issues all index DDL for the plane in **one** write batch
  (`create_index_if_not_exists` per `LabelSpec.unique_key` [unique equality] + `equality`
  entries; `create_text_index_nodes` for `text_property`), then polls `get_index_operation`
  receipts until active or `settings.index_ready_timeout_s`; a blocked build raises
  `HelixUnavailable` naming the blocker code. It finally upserts `Meta(key="schema_version")`.
  Return `{"created": [...], "active": [...], "blocked": [...]}`. A second call creates nothing.
- `ensure_vector_index(client, label, prefix, dim)` returns `f"{prefix}_{dim}"`; first use creates
  a cosine vector index on that property and appends `dim` to Meta `vector_dims:<label>`
  (stored as a JSON list, sorted, deduped). `known_vector_dimensions` reads it back (`[]` if absent).
- `Meta` is itself a label (`unique_key="key"`), bootstrapped implicitly by `ensure_plane`
  even when the plane schema omits it.
- DSL builders: `text_search` / `vector_search` clamp `limit` to `MAX_SEARCH_LIMIT = 800` and
  log the clamp at debug; projections append `"$score"` / `"$distance"`.
- `upsert_node_entries` = conditional entries: `var_as_if(var_empty → add_n(label, props))`,
  `var_as_if(var_not_empty → set_property…)` — never two round-trips.
- `cas_page_entries(batch, page_props, expected_hash)`: `expected_hash is None` ⇒ insert only when
  no `Page` with that `concept_id` exists; otherwise update only when the stored `content_hash`
  equals `expected_hash`. The caller learns success from the `returning` map.
- One logical write = one batch (spec §7). Batches with > ~4 MiB of text must be split by callers;
  expose a `TEXT_BATCH_BUDGET_BYTES = 4 * 1024 * 1024` constant for them.

### Drift vs spec
- None in the repo (the package is new). The DSL method names are spec-§6 wheel facts, not
  re-verified here because the wheel is not installed in the shared venv.

---

## Implementation Blueprint

### Steps (in order)
1. Inspect the installed wheel's `helixdb/dsl.py` for the exact call shapes (see Agent Instructions) — *why*: the builders are only as right as the SDK names.
2. Write `dsl.py` — *why*: bootstrap and every backend consume it.
3. Write `bootstrap.py` — *why*: G6 idempotent bootstrap + lazy vectors (AC10).
4. Write `__init__.py` exports — *why*: spec §2 public interface.
5. Write and run the tests.

### `packages/ai-parrot/src/parrot/knowledge/helix/dsl.py` (CREATE)
```python
"""Pure HelixDB DSL builders shared by every FEAT-670 backend (no I/O)."""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from parrot.knowledge.helix.client import _sdk

logger = logging.getLogger(__name__)

MAX_SEARCH_LIMIT = 800
TEXT_BATCH_BUDGET_BYTES = 4 * 1024 * 1024


def clamp_limit(limit: int) -> int:
    """Clamp a search limit to HelixDB's whole-index cap (800), logging the clamp."""
    if limit > MAX_SEARCH_LIMIT:
        logger.debug("HelixDB search limit %s clamped to %s", limit, MAX_SEARCH_LIMIT)
        return MAX_SEARCH_LIMIT
    return max(1, limit)


def lookup_by_key(label: str, key: str, value: Any) -> Any:
    """``g().n_where(Predicate.eq(key, value))`` restricted to ``label``."""
    sdk = _sdk()
    # FILL IN: build the traversal restricting to `label` (n_with_label + where, or n_where on the unique
    #          index then label filter — whichever the wheel supports with an index hit) — bounded by spec §2 "all lookups use n_where(Predicate.eq(...))"
    raise NotImplementedError


def upsert_node_entries(batch: Any, var: str, label: str, key: str, props: Mapping[str, Any]) -> Any:
    """Conditional add-or-update of one node keyed by ``props[key]`` (HelixDB has no upsert op)."""
    # FILL IN: bind `var` = lookup_by_key(label, key, props[key]); var_as_if(BatchCondition.var_empty(var), add_n(label, props));
    #          var_as_if(BatchCondition.var_not_empty(var), set_property per non-key prop); return batch — bounded by spec §6 Does NOT Exist (no upsert)
    raise NotImplementedError


def find_or_add_edge_entries(
    batch: Any, var: str, src_var: str, dst_var: str, rel: str, props: Mapping[str, Any]
) -> Any:
    """Add ``(src)-[rel]->(dst)`` only when no such edge exists (HelixDB is a multigraph)."""
    # FILL IN: bind `var` = src out_e(rel) filtered on target == dst; var_as_if(var_empty → add_e(rel, src, dst, props));
    #          var_as_if(var_not_empty → set_property on the edge for props) — bounded by test_dsl_find_or_add_edge_dedupes
    raise NotImplementedError


def text_search(label: str, prop: str, query: str, limit: int, projection: Sequence[str]) -> Any:
    """BM25 ``text_search_nodes`` + ``value_map([*projection, "$score"])``; limit clamped to 800."""
    # FILL IN: g().text_search_nodes(label, prop, query, clamp_limit(limit)).value_map([...]) — bounded by AC11
    raise NotImplementedError


def vector_search(label: str, prop: str, vector: Sequence[float], limit: int, projection: Sequence[str]) -> Any:
    """``vector_search_nodes`` + ``value_map([*projection, "$distance"])``; limit clamped to 800."""
    # FILL IN: as text_search with vector_search_nodes; list(map(float, vector)) — bounded by AC10, AC18
    raise NotImplementedError


def cas_page_entries(batch: Any, page_props: Mapping[str, Any], expected_hash: str | None) -> Any:
    """Compare-and-swap a ``Page`` on ``content_hash`` via ``BatchCondition``.

    ``expected_hash is None`` ⇒ insert-only; otherwise update only when the stored hash matches.
    """
    # FILL IN: conditional entries per Implementation Notes; expose a returning var ("cas_applied") the caller reads
    #          — bounded by test_dsl_cas_entries_conditions and BaseWikiStore.compare_and_swap_page semantics (wiki/store.py)
    raise NotImplementedError
```
**Why this shape**: names and signatures are the spec §3 M1 skeleton verbatim; `clamp_limit`
and the byte budget make AC11 / the §7 text-admission risk a single shared rule.

### `packages/ai-parrot/src/parrot/knowledge/helix/bootstrap.py` (CREATE)
```python
"""Idempotent per-plane label/index bootstrap with receipt polling (FEAT-670 M1, G6)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from parrot.knowledge.helix.client import HelixClient, _sdk
from parrot.knowledge.helix.errors import HelixUnavailable

logger = logging.getLogger(__name__)

META_LABEL = "Meta"
VECTOR_DIMS_KEY = "vector_dims:{label}"


class LabelSpec(BaseModel):
    """Declarative per-label bootstrap: unique key, equality indexes, text property."""

    label: str
    unique_key: str
    equality: list[str] = Field(default_factory=list)
    text_property: str | None = None
    vector_property_prefix: str | None = None


class PlaneSchema(BaseModel):
    """All labels and edge labels one plane bootstraps."""

    plane: str
    schema_version: str
    labels: list[LabelSpec]
    edge_labels: list[str]


async def ensure_plane(client: HelixClient, schema: PlaneSchema) -> dict[str, Any]:
    """Create every index of ``schema`` in one write batch, poll receipts, upsert Meta(schema_version).

    Returns:
        ``{"created": [...], "active": [...], "blocked": [...]}``.

    Raises:
        HelixUnavailable: an index build is blocked or not active within ``index_ready_timeout_s``.
    """
    # FILL IN: labels = schema.labels + implicit LabelSpec(label=META_LABEL, unique_key="key") when absent;
    #          one write_batch with create_index_if_not_exists(IndexSpec.node_unique_equality(...)) per unique key,
    #          node_equality per `equality`, create_text_index_nodes per text_property; collect operation ids
    # FILL IN: poll get_index_operation per id with asyncio.sleep backoff until active / blocked / deadline
    #          (time.monotonic() + client.settings.index_ready_timeout_s); blocked → HelixUnavailable(blocker code)
    # FILL IN: upsert Meta(key="schema_version", value=schema.schema_version) via dsl.upsert_node_entries
    #          — bounded by test_ensure_plane_idempotent_and_polls_receipts
    raise NotImplementedError


async def known_vector_dimensions(client: HelixClient, label: str) -> list[int]:
    """Dimensions recorded in Meta ``vector_dims:<label>`` (``[]`` when none)."""
    # FILL IN: read Meta by key VECTOR_DIMS_KEY.format(label=label); json.loads(value) → sorted ints
    raise NotImplementedError


async def ensure_vector_index(client: HelixClient, label: str, prefix: str, dimension: int) -> str:
    """Return ``f"{prefix}_{dimension}"``, creating its cosine vector index on first use (lazy, Q1)."""
    prop = f"{prefix}_{dimension}"
    if dimension in await known_vector_dimensions(client, label):
        return prop
    # FILL IN: one write batch: create_vector_index_nodes(label, prop, dimension, VectorDistanceMetric cosine)
    #          + Meta vector_dims:<label> = json.dumps(sorted(set(dims) | {dimension})); poll the receipt
    #          — bounded by AC10 / test_ensure_vector_index_lazy_per_dimension
    raise NotImplementedError
```
**Why this shape**: `LabelSpec` / `PlaneSchema` are spec §2 Data Models verbatim (defaults
switched to `default_factory`); `ensure_plane` is lazy per store instance, never on import (spec §7).

### `packages/ai-parrot/src/parrot/knowledge/helix/__init__.py` (CREATE)
```python
"""HelixDB provider core (FEAT-670): settings, client, bootstrap, DSL, errors.

Importing this package never imports the ``helixdb`` SDK. Registry registrations are added by
later tasks (traversal compiler: TASK-4386; ``register_all()``: TASK-4392).
"""
from parrot.knowledge.helix.bootstrap import LabelSpec, PlaneSchema, ensure_plane, ensure_vector_index, known_vector_dimensions
from parrot.knowledge.helix.client import HelixClient, open_helix_client
from parrot.knowledge.helix.errors import HelixExtraMissing, HelixUnavailable, HelixWriteRejected
from parrot.knowledge.helix.settings import HelixMode, HelixSettings, resolve_helix_settings

__all__ = [
    "HelixClient", "HelixExtraMissing", "HelixMode", "HelixSettings", "HelixUnavailable", "HelixWriteRejected",
    "LabelSpec", "PlaneSchema", "ensure_plane", "ensure_vector_index", "known_vector_dimensions",
    "open_helix_client", "resolve_helix_settings",
]
```

### FILL IN checklist
- [ ] `dsl.py::lookup_by_key` — label restriction with index hit; spec §2
- [ ] `dsl.py::upsert_node_entries` — conditional entries; no upsert op
- [ ] `dsl.py::find_or_add_edge_entries` — dedupe; test_dsl_find_or_add_edge_dedupes
- [ ] `dsl.py::text_search` / `vector_search` — clamp + projection; AC10, AC11, AC18
- [ ] `dsl.py::cas_page_entries` — insert-only vs hash match; test_dsl_cas_entries_conditions
- [ ] `bootstrap.py::ensure_plane` — single DDL batch, receipt polling, Meta schema_version
- [ ] `bootstrap.py::known_vector_dimensions` / `ensure_vector_index` — Meta-recorded lazy dims; AC10

---

## Acceptance Criteria

- [ ] `import parrot.knowledge.helix` works without `helix-db` installed (AC3 precondition).
- [ ] `test_ensure_plane_idempotent_and_polls_receipts`: second call creates nothing; blocked build → `HelixUnavailable` with blocker code.
- [ ] `test_ensure_vector_index_lazy_per_dimension`: dims 3 then 5 → two properties, `Meta vector_dims:Page == [3, 5]` (AC10).
- [ ] `test_dsl_find_or_add_edge_dedupes`: same `(src, dst, rel)` twice → one edge.
- [ ] `test_dsl_cas_entries_conditions`: insert-only when expected is None; hash mismatch → no write.
- [ ] Search limit > 800 is clamped (AC11).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/helix/test_bootstrap.py -q`
- `pytest packages/ai-parrot/tests/knowledge/helix/test_dsl.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/helix/test_bootstrap.py
import pytest

from parrot.knowledge.helix import LabelSpec, PlaneSchema, ensure_plane, ensure_vector_index, open_helix_client
from parrot.knowledge.helix.bootstrap import known_vector_dimensions

SCHEMA = PlaneSchema(plane="t", schema_version="3",
                     labels=[LabelSpec(label="Page", unique_key="concept_id", text_property="search_text")],
                     edge_labels=["links_to"])


async def test_ensure_plane_idempotent_and_polls_receipts(helix_memory_settings):
    async with await open_helix_client(helix_memory_settings) as c:
        first = await ensure_plane(c, SCHEMA)
        assert first["created"] and not first["blocked"]
        second = await ensure_plane(c, SCHEMA)
        assert second["created"] == []


async def test_ensure_vector_index_lazy_per_dimension(helix_memory_settings):
    async with await open_helix_client(helix_memory_settings) as c:
        await ensure_plane(c, SCHEMA)
        assert await ensure_vector_index(c, "Page", "embedding", 3) == "embedding_3"
        assert await ensure_vector_index(c, "Page", "embedding", 5) == "embedding_5"
        assert await ensure_vector_index(c, "Page", "embedding", 3) == "embedding_3"
        assert await known_vector_dimensions(c, "Page") == [3, 5]

# blocked-build branch: monkeypatch the receipt reader to return a blocked status and assert
# HelixUnavailable(match=<blocker code>) — SDK-free, runs without the wheel.

# packages/ai-parrot/tests/knowledge/helix/test_dsl.py
from parrot.knowledge.helix.dsl import MAX_SEARCH_LIMIT, clamp_limit


def test_clamp_limit():
    assert clamp_limit(5000) == MAX_SEARCH_LIMIT == 800 and clamp_limit(10) == 10

# test_dsl_find_or_add_edge_dedupes (embedded): two batches each running find_or_add_edge_entries for the
#   same (src, dst, rel) → out_e(rel).count() == 1
# test_dsl_cas_entries_conditions (embedded): expected None on a new page → applied; again → not applied;
#   wrong hash → not applied and stored props unchanged; right hash → applied
```

---

## Agent Instructions

1. **Work in the feature worktree** `feat-FEAT-670-helixdb-provider`, never on `dev`.
2. Read spec §2 "Data-model mapping", §3 Module 1, §6 SDK surface, §7 Known Risks.
3. `TASK-4373` must be `done` in `sdd/tasks/index/helixdb-provider.json`.
4. Mark `in-progress`; commit only the index file.
5. This module is **not delegation-eligible** (spec §3): every later backend depends on these helpers — keep it with a thinking model.
6. Before filling any DSL FILL IN, read the real wheel: `uv run --no-sync --with helix-db==0.3.4 python -c "import helixdb.dsl as d, inspect; print(inspect.getsource(d.WriteBatch.var_as_if))"` (and the ops you use). Never `uv sync` in the worktree. Record verified call shapes in the Completion Note.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (embedded tests need the wheels; `uv run --no-sync --with helix-db==0.3.4 --with helix-db-embedded==0.3.3 pytest …`). If the embedded tier cannot run, close `partial` and say so.
8. Commit only the listed files: `feat(helixdb-provider): TASK-4374 — HelixDB bootstrap, DSL helpers and exports`.
9. `scripts/sdd/close_task.sh TASK-4374 helixdb-provider verified`, fill the Completion Note, commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
