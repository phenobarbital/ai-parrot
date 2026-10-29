# TASK-4879: Shared scaffolding `_common.py` for the semantic examples

**Feature**: FEAT-769 — Example agents for the governed Semantic Layer
**Spec**: `sdd/specs/semantic-layer-example.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4878
**Assigned-to**: unassigned

---

## Context

Implements the code half of spec §3 Module 2. One PBAC evaluator, one guard builder, one
identity factory, one warehouse builder and one `connection_env` shared by all four new
examples (TASK-4880, TASK-4881, TASK-4882, TASK-4883), so none of them re-invents the
fail-closed wiring that review `issue:f0da823294fb` already had to correct once.

**This module does not absorb the relocated example.** Spec §2 ("Why `_common.py` does not
absorb the moved example") keeps `agent_semantic_example.py`'s private copies: its pin test
asserts on that file's **source text** (`test_example_agent.py:77-83`). The duplication is
deliberate. Do not import `_common` from the moved example and do not delete its helpers.

Q3 (answered after the spec was approved) adds a **second named connection**, so this
module binds two connection environment variables and builds two warehouses. The second
connection demonstrates that `ConnectionResolver` (`execution.py:26-49`) resolves per
**root model** — it is not a cross-connection refusal, which the library does not implement.

---

## Scope

- Create `examples/agents/semantic/_common.py` with `MODELS_DIR`, `MODELS_UNGOVERNED_DIR`,
  `CONNECTION_ENV`, `CONNECTION_ENV_DIM`, `ExamplePolicyEvaluator`, `build_guard`,
  `build_warehouse`, `build_dim_warehouse`, `connection_env`, `example_identity` and
  `build_toolkit`.
- Write `packages/ai-parrot-semantic/tests/test_example_common.py` pinning that the guard is
  a real `DataPlanePolicyGuard` around the example evaluator, that `connection_env` restores
  **both** variables on exit, and that `build_toolkit` produces a working governed toolkit.

**NOT in scope**: any example agent module (TASK-4880..4883); the YAML fixtures
(TASK-4878); editing the relocated `agent_semantic_example.py` in any way; the README or
docs (TASK-4884); any change under `packages/ai-parrot-semantic/src/**`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/semantic/_common.py` | CREATE | Shared evaluator, guard, warehouses, identity, toolkit builder |
| `packages/ai-parrot-semantic/tests/test_example_common.py` | CREATE | Pin test for the scaffolding |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `e00c8de82` (2026-10-29).

### Verified Imports

```python
from parrot.auth import DataPlanePolicyGuard, PermissionContext, RlsRegistry, UserSession
# verified by import: DataPlanePolicyGuard -> parrot.auth.dataplane_guard,
#   PermissionContext/UserSession -> parrot.auth.permission, RlsRegistry -> parrot.auth.rls_registry
#   (parrot/auth/__init__.py re-exports these lazily — a plain grep of __init__.py does NOT show them)
from parrot.semantic.context import SemanticRequestIdentity   # verified: context.py:18
from parrot.semantic.toolkit import SemanticLayerToolkit      # verified: toolkit.py:38
```

> `parrot.semantic.__init__` exports only `__version__, SemanticQuery, SemanticQueryResult,
> SemanticLayerToolkit` — everything else MUST come from its submodule.

### Existing Signatures to Use

```python
# packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:38
class SemanticLayerToolkit(AbstractToolkit):
    tool_prefix = "sl"                              # :41
    exclude_tools = ("reload",)                     # :42
    def __init__(self, **kwargs: Any) -> None: ...  # :44  KWARGS ONLY
    # pops: models_dir, dialect, dataplane_guard, rls_registry, database_toolkit, signer,
    #       audit_storage, static_subject, result_ttl_s=900, result_store_max=256,
    #       allowed_functions=(), audit_required=None, allow_raw_sql=False,
    #       dataset_manager_factory
    # raises: static_subject_forbidden :67 · invalid_allow_raw_sql :70 ·
    #         invalid_sink_factory :72 · guard_required :79

# packages/ai-parrot-semantic/src/parrot/semantic/context.py:18
class SemanticRequestIdentity(BaseModel, frozen=True):
    # fields: ctx, channel, agent_id, session_id

# The exact construction the relocated example already uses — examples/semantic/agent_semantic_example.py:299-325
rls_registry = RlsRegistry()
toolkit = SemanticLayerToolkit(
    models_dir=models_dir,
    dialect="duckdb",
    dataplane_guard=build_guard(evaluator or ExamplePolicyEvaluator(), rls_registry),
    rls_registry=rls_registry,
)
context = PermissionContext(
    session=UserSession(user_id, "example-tenant", frozenset({"analyst"}), {"programs": [program]})
)
SemanticRequestIdentity(ctx=context, channel="agent", agent_id="semantic-example", session_id=session_id)

def build_guard(evaluator: ExamplePolicyEvaluator, rls_registry: RlsRegistry) -> DataPlanePolicyGuard:
    return DataPlanePolicyGuard(evaluator=evaluator, rls_registry=rls_registry)

# The evaluator protocol the guard calls — examples/semantic/agent_semantic_example.py:139-180
class ExamplePolicyEvaluator:
    def check_access(self, eval_ctx, resource_type: str, resource: str, action: str, env) -> SimpleNamespace
        # allowed only for resource_type == "driver", resource == "duckdb", action == "driver:connect"
    def filter_resources(self, eval_ctx, resource_type: str, resources: list[str], action: str, env) -> SimpleNamespace
        # resource_type == "table", action == "table:read"; table ids are "duckdb:<schema>.<table>"
    # the subject's roles are read from  getattr(eval_ctx, "store", {}).get("userinfo", {}).get("roles", [])

# packages/ai-parrot-semantic/src/parrot/semantic/execution.py:20,26,39
class ConnectionResolver:
    PREFIX = "PARROT_SEMANTIC_CONN_"
    # env var name = PREFIX + re.sub(r"[^A-Za-z0-9]", "_", connection).upper() + "_" + KEY.upper()
    # so connection "semantic_example" + key "database" -> PARROT_SEMANTIC_CONN_SEMANTIC_EXAMPLE_DATABASE
    #    connection "semantic_dim"     + key "database" -> PARROT_SEMANTIC_CONN_SEMANTIC_DIM_DATABASE
```

The warehouse the fixture graph expects (from `packages/ai-parrot-semantic/tests/_models.py:32-55`,
which seeds exactly these two tables):

```sql
CREATE SCHEMA sales; CREATE SCHEMA dim;
CREATE TABLE sales.orders (id INTEGER, customer_id INTEGER, tenant_id VARCHAR, region VARCHAR, order_date TIMESTAMP, amount DECIMAL);
CREATE TABLE dim.customers (id INTEGER, tenant_id VARCHAR, email VARCHAR, salary DECIMAL);
INSERT INTO sales.orders VALUES (1, 10, 'tenant-a', 'eu', '2026-01-01', 12.50), (2, 20, 'tenant-b', 'us', '2026-01-02', 25.00);
INSERT INTO dim.customers VALUES (10, 'tenant-a', 'a@example.test', 100.00), (20, 'tenant-b', 'b@example.test', 200.00);
```

### Does NOT Exist

- ~~`SemanticLayerToolkit(models_dir, dialect)`~~ positionally — `__init__` is `**kwargs` only
  (`toolkit.py:44`); a positional argument is a `TypeError`.
- ~~`parrot.semantic.SemanticRequestIdentity`~~ — not exported from the package root.
- ~~a `Chatbot`/`Agent` kwarg named `semantic_toolkit`~~ — tools go in `tools=[...]`.
- ~~an `unregister`/`remove` API on `RlsRegistry`~~ — `reload()` cannot drop a rule. Use a
  fresh toolkit instance for a changed policy snapshot.
- ~~a cross-connection check~~ — nothing in the library compares a root model's connection
  to a joined model's. `connection_env` binds two variables so two **root** models resolve
  to two files; it demonstrates nothing about refusals.
- ~~`os.environ` mutation outside `connection_env`~~ —
  `test_build_toolkits_does_not_mutate_environment` (`test_example_agent.py:85`) pins the
  equivalent behaviour for the moved example; this module must hold the same bar.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/semantic/_common.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_common.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/context.py#SemanticRequestIdentity",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/execution.py#ConnectionResolver"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`examples/agents/finance/hooba_agent.py` is the house style for this directory: a `Usage::`
docstring, a module-level `LOGGER = logging.getLogger(__name__)`, `build_*` factories, and
no `print` except a final result summary. `_common.py` is a helper module, so it has no
`argparse` and no `main()`.

### Key Constraints

- Full type hints and Google-style docstrings on every function and class (`ruff` runs over
  `examples/` at line-length 120 with only `F401,F841,E402` waived — `TID251`, `B`, `ASYNC`,
  `PIE`, `C4`, `LOG` all apply).
- `import duckdb` **inside** the warehouse builders, not at module scope, so importing
  `_common` never requires duckdb (the pin tests `importorskip` it).
- `connection_env` must restore **both** variables, including the case where one was unset
  before (pop it) and the other was set (restore the old value).
- Never mutate `os.environ` outside `connection_env`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module constants and `ExamplePolicyEvaluator` — *why*: every other function takes the evaluator or the dirs, so they come first.
2. Add `build_guard` returning a real `DataPlanePolicyGuard` — *why*: AC "no gate is forced open"; a stub evaluator was a `issue:f0da823294fb` regression class.
3. Add `build_warehouse` and `build_dim_warehouse` — *why*: TASK-4883's second-connection leg needs a second file holding only `dim.customers`.
4. Add `connection_env` binding both variables with full restore — *why*: spec AC3 requires the environment to be restored on exit.
5. Add `example_identity` and `build_toolkit` — *why*: these are the two call sites all four examples share.
6. Write the pin test and run it — *why*: this module is the single point of failure for four downstream tasks.

### `examples/agents/semantic/_common.py` (CREATE)
```python
"""Shared scaffolding for the governed semantic-layer examples (FEAT-769).

These helpers are used by the four example agents in this directory. The relocated
``agent_semantic_example.py`` deliberately keeps its own private copies — see the spec
section "Why ``_common.py`` does not absorb the moved example".
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from parrot.auth import DataPlanePolicyGuard, PermissionContext, RlsRegistry, UserSession
from parrot.semantic.context import SemanticRequestIdentity
from parrot.semantic.toolkit import SemanticLayerToolkit

LOGGER = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent / "models"
MODELS_UNGOVERNED_DIR = Path(__file__).parent / "models_ungoverned"

#: Connection of the `orders` model (models/orders.policy.yaml).
CONNECTION_ENV = "PARROT_SEMANTIC_CONN_SEMANTIC_EXAMPLE_DATABASE"
#: Connection of the `customers` model (models/customers.policy.yaml) — a SECOND warehouse.
CONNECTION_ENV_DIM = "PARROT_SEMANTIC_CONN_SEMANTIC_DIM_DATABASE"

_ALLOWED_DRIVER = "duckdb"
_ALLOWED_TABLES = ("duckdb:sales.orders", "duckdb:dim.customers")
_ALLOWED_ROLE = "analyst"
_WAREHOUSE_NAME = "semantic-example.duckdb"
_DIM_WAREHOUSE_NAME = "semantic-dim.duckdb"


class ExamplePolicyEvaluator:
    """Explicit allow-list PBAC evaluator plugged into the real DataPlanePolicyGuard.

    No gate is bypassed: only an ``analyst`` subject may connect to DuckDB and read the
    two fixture tables. ``revoke()`` withdraws the grant so later decisions fail closed.
    Production hosts use the navigator-auth ``PolicyEvaluator`` instead.
    """

    def __init__(self, *, allowed_role: str = _ALLOWED_ROLE) -> None:
        """Start with the fixture grant enabled for ``allowed_role``."""
        self.allowed_role = allowed_role
        self.revoked = False

    def revoke(self) -> None:
        """Withdraw the fixture grant for every subsequent decision."""
        self.revoked = True

    def _permits(self, eval_ctx: Any) -> bool:
        """Return whether the evaluated subject still holds the fixture grant."""
        userinfo = getattr(eval_ctx, "store", {}).get("userinfo", {})
        return not self.revoked and self.allowed_role in userinfo.get("roles", [])

    def check_access(self, eval_ctx: Any, resource_type: str, resource: str, action: str, env: Any) -> SimpleNamespace:
        """Allow only ``driver:connect`` on the DuckDB driver for the allowed role."""
        del env
        allowed = (
            self._permits(eval_ctx)
            and resource_type == "driver"
            and resource == _ALLOWED_DRIVER
            and action == "driver:connect"
        )
        return SimpleNamespace(allowed=allowed)

    def filter_resources(
        self, eval_ctx: Any, resource_type: str, resources: list[str], action: str, env: Any
    ) -> SimpleNamespace:
        """Return only the fixture tables for the allowed role performing ``table:read``."""
        del env
        if not self._permits(eval_ctx) or resource_type != "table" or action != "table:read":
            return SimpleNamespace(allowed=[])
        return SimpleNamespace(allowed=[resource for resource in resources if resource in _ALLOWED_TABLES])


def build_guard(evaluator: ExamplePolicyEvaluator, rls_registry: RlsRegistry) -> DataPlanePolicyGuard:
    """Build the core data-plane guard around the example evaluator."""
    return DataPlanePolicyGuard(evaluator=evaluator, rls_registry=rls_registry)


def build_warehouse(directory: Path) -> Path:
    """Create the deterministic DuckDB warehouse for the `orders` connection.

    Seeds ``sales.orders`` and ``dim.customers`` so a governed query and the ungoverned
    join compile and run against the same physical shape the library's own tests use.

    Args:
        directory: Directory the warehouse file is created in; created if absent.

    Returns:
        The path of the created warehouse file.
    """
    import duckdb

    directory.mkdir(parents=True, exist_ok=True)
    warehouse = directory / _WAREHOUSE_NAME
    connection = duckdb.connect(str(warehouse))
    try:
        # FILL IN: run the CREATE SCHEMA / CREATE TABLE / INSERT statements for
        #          sales.orders and dim.customers — bounded by the exact DDL and rows
        #          quoted in this task's Codebase Contract (tests/_models.py:32-55).
        pass
    finally:
        connection.close()
    return warehouse


def build_dim_warehouse(directory: Path) -> Path:
    """Create the SECOND warehouse, holding only ``dim.customers``.

    The `customers` model declares ``connection: semantic_dim``, so a query rooted at it
    resolves :data:`CONNECTION_ENV_DIM` and reads this file instead of the `orders` one.
    This is per-model connection isolation, not a cross-connection refusal.

    Args:
        directory: Directory the warehouse file is created in; created if absent.

    Returns:
        The path of the created warehouse file.
    """
    import duckdb

    directory.mkdir(parents=True, exist_ok=True)
    warehouse = directory / _DIM_WAREHOUSE_NAME
    connection = duckdb.connect(str(warehouse))
    try:
        # FILL IN: create schema dim and table dim.customers with the SAME columns and rows
        #          as build_warehouse — bounded by: a reader must be able to tell the two
        #          files apart only by which connection reached them.
        pass
    finally:
        connection.close()
    return warehouse


@contextmanager
def connection_env(warehouse: Path, dim_warehouse: Path | None = None) -> Iterator[None]:
    """Bind the example connection variables for the enclosed block only.

    Both variables are restored exactly as they were on exit — popped when they were
    unset, reset to their previous value when they were set — so the example never leaks
    process-wide configuration.

    Args:
        warehouse: Warehouse backing the ``semantic_example`` connection.
        dim_warehouse: Optional warehouse backing the ``semantic_dim`` connection.
    """
    bindings = {CONNECTION_ENV: str(warehouse)}
    if dim_warehouse is not None:
        bindings[CONNECTION_ENV_DIM] = str(dim_warehouse)
    previous = {name: os.environ.get(name) for name in bindings}
    os.environ.update(bindings)
    try:
        yield
    finally:
        # FILL IN: restore every name in `previous` — pop when the old value is None,
        #          assign otherwise — bounded by AC3 (the environment is restored on exit).
        pass


def example_identity(
    user_id: str,
    session_id: str,
    program: str,
    *,
    roles: frozenset[str] = frozenset({_ALLOWED_ROLE}),
) -> SemanticRequestIdentity:
    """Build the trusted fixture identity bound around every governed call.

    Args:
        user_id: Subject identifier.
        session_id: Session identifier; part of the result owner tuple.
        program: Value of the ``programs`` subject attribute the RLS rule filters on.
        roles: Subject roles; ``analyst`` by default.

    Returns:
        A frozen :class:`SemanticRequestIdentity`.
    """
    context = PermissionContext(session=UserSession(user_id, "example-tenant", roles, {"programs": [program]}))
    return SemanticRequestIdentity(
        ctx=context, channel="agent", agent_id="semantic-examples", session_id=session_id
    )


def build_toolkit(
    warehouse: Path,
    *,
    evaluator: ExamplePolicyEvaluator | None = None,
    models_dir: Path | None = None,
    **extra: Any,
) -> SemanticLayerToolkit:
    """Build a governed SemanticLayerToolkit over the committed fixture models.

    Args:
        warehouse: Warehouse the toolkit's connection resolves to; bound by the caller
            through :func:`connection_env`.
        evaluator: Example evaluator; a fresh permissive one when omitted.
        models_dir: Model directory; :data:`MODELS_DIR` when omitted.
        **extra: Extra kwargs forwarded verbatim to :class:`SemanticLayerToolkit`.

    Returns:
        A toolkit wired to a real guard — never a bypassed one.
    """
    del warehouse  # the connection is resolved from the environment, not passed in
    rls_registry = RlsRegistry()
    return SemanticLayerToolkit(
        models_dir=models_dir or MODELS_DIR,
        dialect="duckdb",
        dataplane_guard=build_guard(evaluator or ExamplePolicyEvaluator(), rls_registry),
        rls_registry=rls_registry,
        **extra,
    )
```
**Why this shape**: the evaluator, guard and `connection_env` are copied in spirit from
`agent_semantic_example.py:139-283`, which review `issue:f0da823294fb` already hardened —
reusing its proven shape is what keeps four new examples from re-introducing a placeholder
guard or an environment leak. `_ALLOWED_TABLES` widens the moved example's single table to
both fixture tables because the `customers` model is now independently queryable (Q3).
`connection_env` keeps the spec's single-argument call working and adds the second
warehouse as an optional argument. `build_toolkit` takes `warehouse` for call-site symmetry
but deliberately discards it: the connection comes from the environment
(`ConnectionResolver`), never from a constructor argument — stating that in code is part of
the lesson.

### `packages/ai-parrot-semantic/tests/test_example_common.py` (CREATE)
```python
"""Regression contract: shared scaffolding for the semantic examples (FEAT-769 M2)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("duckdb")

_COMMON_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "_common.py"


@pytest.fixture(scope="module")
def common() -> ModuleType:
    """Load the shared module by absolute path, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_examples_common", _COMMON_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_guard_is_a_real_dataplane_guard(common: ModuleType) -> None:
    """The example evaluator is plugged into the core guard; no gate is forced open."""
    from parrot.auth import DataPlanePolicyGuard, RlsRegistry

    guard = common.build_guard(common.ExamplePolicyEvaluator(), RlsRegistry())
    assert isinstance(guard, DataPlanePolicyGuard)


def test_evaluator_denies_once_revoked(common: ModuleType) -> None:
    """`revoke()` fails closed for every subsequent decision."""
    # FILL IN: build an eval_ctx whose store["userinfo"]["roles"] contains "analyst",
    #          assert check_access allows driver:connect, revoke, assert it no longer does
    #          — bounded by AC7 (a denial that silently succeeds must fail the test).


def test_connection_env_restores_both_variables(common: ModuleType, tmp_path: Path) -> None:
    """Spec AC3: nothing leaks process-wide, for a previously-set and an unset variable."""
    before = dict(os.environ)
    with common.connection_env(tmp_path / "a.duckdb", tmp_path / "b.duckdb"):
        assert os.environ[common.CONNECTION_ENV] == str(tmp_path / "a.duckdb")
        assert os.environ[common.CONNECTION_ENV_DIM] == str(tmp_path / "b.duckdb")
    assert dict(os.environ) == before


def test_connection_env_restores_a_preexisting_value(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A variable that was already set is restored to its old value, not popped."""
    monkeypatch.setenv(common.CONNECTION_ENV, "/previous.duckdb")
    with common.connection_env(tmp_path / "a.duckdb"):
        assert os.environ[common.CONNECTION_ENV] == str(tmp_path / "a.duckdb")
    assert os.environ[common.CONNECTION_ENV] == "/previous.duckdb"


def test_warehouses_are_seeded_and_distinct(common: ModuleType, tmp_path: Path) -> None:
    """Two files: the orders warehouse holds both tables, the dim one holds dim.customers."""
    # FILL IN: build both warehouses, open each with duckdb and assert the table sets
    #          — bounded by the DDL quoted in the Codebase Contract.


def test_build_toolkit_exposes_the_sl_tools(common: ModuleType, tmp_path: Path) -> None:
    """The toolkit loads the committed fixture and exposes the prefixed tools."""
    warehouse = common.build_warehouse(tmp_path)
    with common.connection_env(warehouse):
        toolkit = common.build_toolkit(warehouse)
    names = {tool.name for tool in toolkit.get_tools()}
    assert any(name.startswith("sl_") for name in names)
    # FILL IN: assert `sl_reload` is absent — SemanticLayerToolkit.exclude_tools = ("reload",)
    #          (toolkit.py:42) — bounded by: the example must not advertise a tool the
    #          library hides.
```
**Why this shape**: `parents[3]` is the repo root from `packages/ai-parrot-semantic/tests/`,
and the `importlib.util.spec_from_file_location` fixture is the precedent set by
`test_example_agent.py:26-37` — including popping `sys.modules[spec.name]` in a `finally`.
The environment tests are two, not one, because popping an unset variable and restoring a
set one are different branches and `issue:f0da823294fb` found an env leak in exactly this
area.

### FILL IN checklist
- [ ] `_common.py::build_warehouse` — the DDL and INSERTs; bounded by the contract's quoted SQL.
- [ ] `_common.py::build_dim_warehouse` — `dim.customers` only, same columns and rows; bounded by the contract's quoted SQL.
- [ ] `_common.py::connection_env` — restore loop over `previous`; bounded by AC3.
- [ ] `test_example_common.py::test_evaluator_denies_once_revoked` — the eval_ctx shape and the revoke assertion; bounded by AC7.
- [ ] `test_example_common.py::test_warehouses_are_seeded_and_distinct` — the table-set assertions; bounded by the contract's SQL.
- [ ] `test_example_common.py::test_build_toolkit_exposes_the_sl_tools` — assert `sl_reload` is absent; bounded by `toolkit.py:42`.

---

## Acceptance Criteria

- [ ] `_common.py` exposes `MODELS_DIR`, `MODELS_UNGOVERNED_DIR`, `CONNECTION_ENV`,
      `CONNECTION_ENV_DIM`, `ExamplePolicyEvaluator`, `build_guard`, `build_warehouse`,
      `build_dim_warehouse`, `connection_env`, `example_identity`, `build_toolkit`.
- [ ] The guard is a real `DataPlanePolicyGuard` around `ExamplePolicyEvaluator`; no gate is
      forced open and no evaluator is stubbed.
- [ ] `connection_env` restores both variables on exit, for the set and the unset case
      (spec AC3).
- [ ] Nothing is written outside the directory passed to the warehouse builders (spec AC3).
- [ ] The relocated `agent_semantic_example.py` is untouched and does not import `_common`.
- [ ] `ruff check examples/agents/semantic packages/ai-parrot-semantic/tests/test_example_common.py`
      is clean (spec AC9).
- [ ] No LLM provider is initialized anywhere in this module or its test (spec AC6).

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_example_common.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q`

---

## Test Specification

See the `test_example_common.py` block above — it IS the test specification.
`test_example_agent.py` is re-run as a regression check that the relocated example was not
disturbed (spec §2 keeps its helpers private, so any coupling introduced here shows up there).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer-example --feature-id FEAT-769`)
2. **Read the spec** at the path listed above — especially §2 "Why `_common.py` does not
   absorb the moved example"
3. **Check dependencies** — TASK-4878 must be `"done"`; `build_toolkit` loads the fixture it commits
4. **Verify the Codebase Contract** — confirm `from parrot.auth import DataPlanePolicyGuard,
   PermissionContext, RlsRegistry, UserSession` resolves by **importing it**, not by grepping
   `parrot/auth/__init__.py`: these names are lazily re-exported and a grep shows nothing
5. **Update status** in `sdd/tasks/index/semantic-layer-example.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Steps in order; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4879 semantic-layer-example verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
