# TASK-4883: Time grains, the governed-join denial and connection isolation (`governed_joins_agent.py`)

**Feature**: FEAT-769 — Example agents for the governed Semantic Layer
**Spec**: `sdd/specs/semantic-layer-example.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4879
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6 and goal **G5**. This is **not** a "joins work" example. Design
research S1, verified empirically, established that the governed path **cannot authorize a
cross-model join**: `RoleCatalog.check_query_rights` (`catalog.py:50-73`) resolves the
allowed member set from the **root model only**, so a qualified member such as
`customers.email` is never granted to a query rooted at `orders` — *even when the root
policy grants `metrics: "*"` and `dimensions: "*"`*. Meanwhile `engines/native.py` compiles
that join correctly. The compiler and the governance gate disagree by design.

The denial is therefore **the lesson**. It is the concrete demonstration of the
"fails loudly on out-of-scope questions instead of inventing a figure" property FEAT-704
claims. Adding qualified-member authorization to the library is an explicit non-goal
(spec §1, §8 Q1).

Two post-approval decisions extend this module:

- **Q1 answered (b)** — leg (c) ships: the same join compiling under an explicitly
  `governed: false` model, clearly labelled as the **compiler surface**, not a governance
  bypass. It reads `examples/agents/semantic/models_ungoverned/`, committed by TASK-4878.
- **Q3 answered (second connection, isolation demo)** — leg (d) ships: a governed query
  rooted at `customers`, which declares `connection: semantic_dim` and therefore reaches a
  **second DuckDB file**. This demonstrates that the connection is resolved per **root
  model** (`toolkit.py:315,485`, `execution.py:26-49`). It is **not** a cross-connection
  refusal — the library implements no such check, and nothing in this example may suggest
  it does.

---

## Scope

- Create `examples/agents/semantic/governed_joins_agent.py` with four legs:
  - `run_time_grain` — a governed `time_dimensions` query with an explicit grain (works).
  - `show_governed_join_denial` — a governed cross-model query, **asserted to raise**
    `member_not_granted`; raises `RuntimeError` if it unexpectedly succeeds.
  - `compile_ungoverned_join` — the same join compiling under `governed: false`.
  - `run_on_second_connection` — a governed query rooted at `customers`, reaching the
    second warehouse.
- Create `packages/ai-parrot-semantic/tests/test_example_governed_joins.py` pinning all four.

**NOT in scope**: adding qualified-member authorization to the library (spec §1 non-goal);
writing the fixtures (TASK-4878); the shared scaffolding (TASK-4879); the other three
examples; the README or docs (TASK-4884); any change under
`packages/ai-parrot-semantic/src/**`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/semantic/governed_joins_agent.py` | CREATE | Grains, the denial, the ungoverned compile, connection isolation |
| `packages/ai-parrot-semantic/tests/test_example_governed_joins.py` | CREATE | Pin test (spec §4) |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `e00c8de82` (2026-10-29).

### Verified Imports

```python
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context  # verified: context.py:18,86
from parrot.semantic.errors import SemanticAccessError                              # verified: errors.py:31
from parrot.semantic.models import SemanticQuery, SemanticQueryResult, TimeDimension  # verified: models.py:102,217,32
from parrot.semantic.toolkit import SemanticLayerToolkit                            # verified: toolkit.py:38
```

### Existing Signatures to Use

```python
# packages/ai-parrot-semantic/src/parrot/semantic/catalog.py:50-73  — THE denial this example teaches
def check_query_rights(self, query: SemanticQuery, roles: frozenset[str]) -> None:
    loaded = self.models.get(query.model)
    if loaded is None:
        raise SemanticAccessError("model_not_found", ..., details={"model": query.model})
    if not loaded.policy.governed:          # :64-65  governed:false SHORT-CIRCUITS the gate
        return
    allowed = loaded.policy.allowed_members(roles, loaded.members)   # :66  ROOT MODEL ONLY
    for name in self._referenced_members(query, loaded):
        if name not in allowed:
            raise SemanticAccessError(
                "member_not_granted", "Query references a member that is not granted",
                details={"member": name, "suggestions": self._suggest(name, sorted(allowed))},
            )

# The empirically verified outcome (spec §2 Overview):
#   orders.members = [revenue, order_count, region, order_date]        # no customers.*
#   SemanticQuery(model="orders", dimensions=["customers.email"])
#     -> SemanticAccessError("member_not_granted")
#        details={'member': 'customers.email', 'suggestions': ['order_date','order_count','revenue']}

# packages/ai-parrot-semantic/src/parrot/semantic/models.py:32-43
class TimeDimension(BaseModel):
    name: str; grain: ...; date_range: ...     # grain is MANDATORY

# packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py
async def compile_query(self, query: SemanticQuery) -> dict: ...   # :195  returns PRE-RLS SQL
async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult: ...  # :200

# packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:315,485 — the connection comes from the ROOT model
await self._executor.run_with_columns(governed, connection=loaded.policy.connection)

# packages/ai-parrot-semantic/src/parrot/semantic/execution.py:20,26,39
class ConnectionResolver:
    PREFIX = "PARROT_SEMANTIC_CONN_"
    # env name = PREFIX + connection.upper() (non-alphanumerics -> "_") + "_" + KEY.upper()
```

The fixtures this example reads, committed by TASK-4878:

- `examples/agents/semantic/models/` — `orders` (`connection: semantic_example`, governed)
  and `customers` (`connection: semantic_dim`, governed).
- `examples/agents/semantic/models_ungoverned/` — the **same graph**, both policies
  `governed: false`, no `connection:`.

Helpers from `_common.py` (TASK-4879): `MODELS_DIR`, `MODELS_UNGOVERNED_DIR`,
`CONNECTION_ENV`, `CONNECTION_ENV_DIM`, `build_warehouse`, `build_dim_warehouse`,
`connection_env`, `build_toolkit` (accepts `models_dir=`), `example_identity`.

### Does NOT Exist

- ~~qualified-member authorization~~ — there is no policy key, no `RoleGrant` field and no
  catalog path that grants `customers.email` to a query rooted at `orders`. Do **not**
  invent `qualified_members:`, `joined_members:` or a `models:` list in `RoleGrant`;
  `RoleGrant` is `extra="forbid"` (`policy.py:29`). Verified absent from `policy.py`.
- ~~a cross-connection refusal~~ — nothing compares a root model's `connection` to a joined
  model's; there is no error code for it and no test. Leg (d) demonstrates **isolation**
  (two roots, two files), never a refusal. A cross-model query fails earlier, with
  `member_not_granted`.
- ~~`governed: false` as a way to "unlock" a governed query~~ — it is a different model in a
  different directory, and the example must label it as the compiler surface. Presenting it
  as a bypass violates spec AC12.
- ~~`compile_query` returning "the SQL as executed"~~ — it is **pre-RLS** (closed
  `issue:22fbd14d96a9`). Governed SQL lives only in the audit record.
- ~~`reload()` to drop an RLS rule~~ — it cannot (closed `issue:e3ff9bfb4a83`). Use a fresh
  toolkit instance for a changed policy snapshot. No example may present it otherwise.
- ~~`TimeDimension(name="order_date")`~~ without a grain — `grain` is mandatory
  (`models.py:32-43`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/semantic/governed_joins_agent.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_governed_joins.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/catalog.py#RoleCatalog",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#TimeDimension",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#SemanticQuery",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/execution.py#ConnectionResolver"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **The denial is asserted, never logged** (S8, spec AC7). `show_governed_join_denial`
  returns the caught error and raises `RuntimeError` when the query unexpectedly succeeds —
  the `test_example_agent.py:199-215` pattern.
- Every docstring and printed label must be unambiguous about which surface is which:
  grains and the second connection are **governed**; the join compile is the **compiler**.
  Spec AC12 forbids presenting a cross-model join as a working governed query.
- Leg (d) binds **both** connection variables through
  `_common.connection_env(warehouse, dim_warehouse)` and builds both warehouses.
- No LLM provider anywhere (spec AC6); this example builds no `Agent`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module docstring in `Usage::` form, stating up front that the denial is the lesson — *why*: a reader who skims must not mistake this for a joins tutorial.
2. Add `run_time_grain` — *why*: it establishes that governed queries over a grained time dimension do work, so the following denial is clearly about joins, not about grains.
3. Add `show_governed_join_denial` returning the error and raising on success — *why*: AC7 and AC12.
4. Add `compile_ungoverned_join(directory)` over `MODELS_UNGOVERNED_DIR` — *why*: Q1(b); it proves the compiler and the gate disagree rather than asserting it in prose.
5. Add `run_on_second_connection` rooted at `customers` — *why*: Q3; the connection is a per-root-model property.
6. Add `smoke()` running all four and the pin test — *why*: spec AC3.

### `examples/agents/semantic/governed_joins_agent.py` (CREATE)
```python
"""Time grains, the governed cross-model denial, and connection isolation (FEAT-769 M6).

This is NOT a joins demo. The governed path cannot authorize a cross-model join: the
allowed member set is resolved from the ROOT model alone (``catalog.py:66``), so a
qualified member is never granted — even under ``metrics: "*"``. The compiler, meanwhile,
compiles that join correctly. The denial is the lesson: it is what "fails loudly on
out-of-scope questions instead of inventing a figure" looks like in practice.

Usage::

    python examples/agents/semantic/governed_joins_agent.py --smoke    # all four legs, no LLM
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import _common  # noqa: E402  (examples/ is not a package)

from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.models import SemanticQuery, SemanticQueryResult, TimeDimension
from parrot.semantic.toolkit import SemanticLayerToolkit

LOGGER = logging.getLogger(__name__)

#: The qualified member the governed path refuses to authorize from an `orders` root.
UNGRANTABLE_MEMBER = "customers.email"


async def run_time_grain(
    toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity
) -> SemanticQueryResult:
    """Run a governed query over a time dimension with an explicit grain.

    Grains work on a single model; `grain` is mandatory on a ``TimeDimension``
    (``models.py:32-43``).

    Args:
        toolkit: The governed toolkit over the committed fixture.
        identity: The trusted fixture identity.

    Returns:
        The governed result, one row per month.
    """
    query = SemanticQuery(
        model="orders",
        metrics=["revenue"],
        time_dimensions=[TimeDimension(name="order_date", grain="month")],
    )
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await toolkit.query_metrics(query)


async def show_governed_join_denial(
    toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity
) -> SemanticAccessError:
    """Return the ``member_not_granted`` error a governed cross-model query raises.

    ``RoleCatalog.check_query_rights`` resolves the allowed set from the ROOT model only
    (``catalog.py:66``), so ``customers.email`` is never granted to a query rooted at
    ``orders``. This is the governance surface refusing a question it cannot answer
    truthfully — not a bug, and not something a policy key can unlock.

    Args:
        toolkit: The governed toolkit.
        identity: The trusted fixture identity.

    Returns:
        The ``SemanticAccessError`` that was raised, for the caller to report.

    Raises:
        RuntimeError: If the query unexpectedly SUCCEEDS. A denial that silently passes is
            a failure of this example, not a pass.
    """
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=[UNGRANTABLE_MEMBER])
    async with bind_semantic_context(identity.ctx, identity=identity):
        try:
            await toolkit.query_metrics(query)
        except SemanticAccessError as error:
            LOGGER.info("governed cross-model query denied as expected: %s", error)
            return error
    raise RuntimeError(f"governed cross-model query on {UNGRANTABLE_MEMBER} unexpectedly succeeded")


async def compile_ungoverned_join(directory: Path) -> str:
    """Compile the same join under an explicitly ``governed: false`` model.

    This is the COMPILER surface, not a governance bypass: a different model, in a
    different directory, whose policy declares ``governed: false`` — which short-circuits
    ``check_query_rights`` (``catalog.py:64-65``). The SQL below is also PRE-RLS
    (``toolkit.py:195``); governed SQL exists only in the audit record.

    Args:
        directory: Scratch directory for the compile-only toolkit.

    Returns:
        The compiled SQL containing the join.
    """
    # FILL IN: build a toolkit over _common.MODELS_UNGOVERNED_DIR (pass models_dir= to
    #          _common.build_toolkit), bind a context, call compile_query with the same
    #          SemanticQuery that was denied above, and return the compiled SQL
    #          — bounded by: no query_metrics here; this leg compiles and never executes,
    #          which is why the ungoverned policies carry no connection.
    raise NotImplementedError


async def run_on_second_connection(
    toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity
) -> SemanticQueryResult:
    """Run a governed query rooted at ``customers``, which uses a SECOND warehouse.

    ``customers`` declares ``connection: semantic_dim`` while ``orders`` declares
    ``semantic_example``; the connection is read from the ROOT model's policy
    (``toolkit.py:315,485``) and resolved from the environment
    (``execution.py:26-49``). This demonstrates per-model connection isolation. It is NOT
    a cross-connection refusal — no such check exists in the library.

    Args:
        toolkit: The governed toolkit.
        identity: The trusted fixture identity.

    Returns:
        The governed result, read from the dim warehouse.
    """
    query = SemanticQuery(model="customers", metrics=["customer_count"], dimensions=["email"])
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await toolkit.query_metrics(query)


async def smoke() -> dict[str, Any]:
    """Run all four legs deterministically, with no LLM and no network.

    Returns:
        A JSON-safe summary labelling which surface produced each outcome.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        warehouse = _common.build_warehouse(root)
        dim_warehouse = _common.build_dim_warehouse(root)
        identity = _common.example_identity("analyst-1", "session-1", "eu")
        with _common.connection_env(warehouse, dim_warehouse):
            toolkit = _common.build_toolkit(warehouse)
            # FILL IN: run all four legs and return a summary whose keys name the SURFACE,
            #          not just the outcome (e.g. "governed_time_grain",
            #          "governed_join_denied", "compiler_only_join_sql",
            #          "governed_second_connection") — bounded by AC12: nothing in this
            #          summary may read as a cross-model join succeeding under governance.
            raise NotImplementedError


async def main() -> None:
    """Run the four legs and print a labelled summary."""
    parser = argparse.ArgumentParser(description="Grains, the governed-join denial, and connection isolation")
    parser.add_argument("--smoke", action="store_true", help="Run all four legs (default)")
    parser.parse_args()
    print(json.dumps(await smoke(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```
**Why this shape**: `show_governed_join_denial` **returns** the error rather than
re-raising, so the caller can report it as a successful demonstration, while the
`RuntimeError` on the success path makes a vanished denial loud (AC7). The four functions
are named after their surfaces so the summary cannot be misread. `compile_ungoverned_join`
takes a directory and never executes, which is precisely why TASK-4878's ungoverned
policies carry no `connection:`.

### `packages/ai-parrot-semantic/tests/test_example_governed_joins.py` (CREATE)
```python
"""Regression contract: grains, the governed-join denial, connection isolation (FEAT-769 M6)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from parrot.semantic.errors import SemanticAccessError

pytest.importorskip("duckdb")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "governed_joins_agent.py"


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example by absolute path, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_governed_joins_example", _EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture
def governed(example: ModuleType, tmp_path: Path):
    """A governed toolkit with BOTH connections bound, plus the fixture identity."""
    warehouse = example._common.build_warehouse(tmp_path)
    dim_warehouse = example._common.build_dim_warehouse(tmp_path)
    identity = example._common.example_identity("analyst-1", "session-1", "eu")
    with example._common.connection_env(warehouse, dim_warehouse):
        yield example._common.build_toolkit(warehouse), identity


@pytest.mark.asyncio
async def test_governed_time_grain_succeeds(example: ModuleType, governed) -> None:
    """Grains work on a single model."""
    toolkit, identity = governed
    result = await example.run_time_grain(toolkit, identity)
    # FILL IN: assert the result carries the revenue metric and a month-grained
    #          order_date column — bounded by models.py:32-43 (grain is mandatory).


@pytest.mark.asyncio
async def test_governed_cross_model_query_is_denied(example: ModuleType, governed) -> None:
    """Spec AC12: the governed cross-model query raises member_not_granted."""
    toolkit, identity = governed
    error = await example.show_governed_join_denial(toolkit, identity)
    assert isinstance(error, SemanticAccessError)
    # FILL IN: assert the error code is "member_not_granted" and its details name
    #          example.UNGRANTABLE_MEMBER — bounded by catalog.py:68-73, which puts the
    #          member and the suggestions in `details`.


@pytest.mark.asyncio
async def test_a_silently_succeeding_denial_fails_the_example(example: ModuleType, governed) -> None:
    """Spec AC7: if the denial stops happening, the example must raise."""
    toolkit, identity = governed
    # FILL IN: monkeypatch toolkit.query_metrics so the cross-model call returns instead of
    #          raising, then assert pytest.raises(RuntimeError) around
    #          show_governed_join_denial — bounded by the test_example_agent.py:199-215 pattern.


@pytest.mark.asyncio
async def test_ungoverned_model_compiles_the_join(example: ModuleType, tmp_path: Path) -> None:
    """Q1(b): the compiler surface produces the join the gate refuses to authorize."""
    sql = await example.compile_ungoverned_join(tmp_path)
    assert "JOIN" in sql.upper()
    # FILL IN: assert the compiled SQL references the customers table — bounded by:
    #          this is the COMPILER surface; do not assert anything about RLS, which is
    #          not applied to compile_query output (pre-RLS, toolkit.py:195).


@pytest.mark.asyncio
async def test_second_connection_reads_the_dim_warehouse(example: ModuleType, governed) -> None:
    """Q3: the connection is resolved from the ROOT model's policy, per model."""
    toolkit, identity = governed
    result = await example.run_on_second_connection(toolkit, identity)
    # FILL IN: assert rows came back and that the email values are the dim warehouse's
    #          fixture values — bounded by: this proves which FILE was read, which is the
    #          whole point of the leg.


@pytest.mark.asyncio
async def test_second_connection_is_not_a_refusal(example: ModuleType, governed) -> None:
    """The second connection demonstrates isolation, never a cross-connection refusal."""
    toolkit, identity = governed
    result = await example.run_on_second_connection(toolkit, identity)
    assert result.row_count > 0, "the second connection must SUCCEED; it is not a denial demo"


@pytest.mark.asyncio
async def test_smoke_labels_every_surface(example: ModuleType) -> None:
    """Spec AC3/AC12: offline, and no key presents a governed cross-model success."""
    summary = await example.smoke()
    # FILL IN: assert the summary's keys name the four surfaces and that the denial is
    #          reported as a denial — bounded by AC12.
```
**Why this shape**: `test_second_connection_is_not_a_refusal` exists specifically to stop a
future editor from rewriting leg (d) into the cross-connection refusal that Q3 originally
asked for and the library does not implement. `test_a_silently_succeeding_denial_fails_the_example`
is the AC7 guard for this module's denial, the same shape TASK-4881 uses for its deny.

### FILL IN checklist
- [ ] `governed_joins_agent.py::compile_ungoverned_join` — build the ungoverned toolkit and compile; bounded by: compile only, never execute.
- [ ] `governed_joins_agent.py::smoke` — the four legs and the surface-labelled summary; bounded by AC12.
- [ ] `test_example_governed_joins.py::test_governed_time_grain_succeeds` — metric/grain assertions; bounded by `models.py:32-43`.
- [ ] `test_example_governed_joins.py::test_governed_cross_model_query_is_denied` — code and `details` assertions; bounded by `catalog.py:68-73`.
- [ ] `test_example_governed_joins.py::test_a_silently_succeeding_denial_fails_the_example` — the broken-denial monkeypatch; bounded by AC7.
- [ ] `test_example_governed_joins.py::test_ungoverned_model_compiles_the_join` — the customers-table assertion; bounded by: compiler surface only.
- [ ] `test_example_governed_joins.py::test_second_connection_reads_the_dim_warehouse` — the fixture-value assertion; bounded by: it proves which file was read.
- [ ] `test_example_governed_joins.py::test_smoke_labels_every_surface` — the key assertions; bounded by AC12.

---

## Acceptance Criteria

- [ ] The governed time-grain query succeeds.
- [ ] The governed cross-model query is **asserted** to raise `member_not_granted`, and the
      example raises `RuntimeError` if it succeeds (spec AC7, AC12).
- [ ] The ungoverned model compiles the join, labelled as the compiler surface — no example
      presents a cross-model join as a working governed query (spec AC12).
- [ ] The `customers`-rooted query reads the second warehouse through
      `CONNECTION_ENV_DIM`, and is presented as connection **isolation**, never as a
      cross-connection refusal.
- [ ] No example presents `reload()` as a way to drop an RLS rule (spec AC12).
- [ ] `--smoke` runs offline with no LLM call, no network, no write outside a temporary
      directory, and both connection variables restored on exit (spec AC3).
- [ ] No LLM provider is initialized (spec AC6).
- [ ] `ruff check examples/agents/semantic packages/ai-parrot-semantic/tests/test_example_governed_joins.py`
      is clean (spec AC9).
- [ ] No file named `test_*.py` was added under `examples/` (spec AC10).

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_example_governed_joins.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_catalog.py -q`

---

## Test Specification

See the `test_example_governed_joins.py` block above — it IS the test specification. Seven
tests: grain success, the denial, the broken-denial guard, the ungoverned compile, the
second connection, the not-a-refusal guard, and the labelled smoke summary.
`test_catalog.py` is re-run as a regression check on the gate this example depends on.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer-example --feature-id FEAT-769`)
2. **Read the spec** at the path listed above — especially §2 Overview, which explains why
   this module is a denial demonstration and not a joins demo
3. **Check dependencies** — TASK-4879 must be `"done"`
4. **Verify the Codebase Contract** — re-read `catalog.py:50-73` before writing the denial
   leg, and confirm for yourself that `allowed` comes from the root model only
5. **Update status** in `sdd/tasks/index/semantic-layer-example.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Steps in order; complete every `# FILL IN:` marker. If you
   find yourself wanting a policy key that would grant a qualified member, stop: that is an
   explicit non-goal, and no such key exists
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4883 semantic-layer-example verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
