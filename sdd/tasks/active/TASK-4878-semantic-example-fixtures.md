# TASK-4878: Committed model and policy fixtures for the semantic examples

**Feature**: FEAT-769 — Example agents for the governed Semantic Layer
**Spec**: `sdd/specs/semantic-layer-example.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4877
**Assigned-to**: unassigned

---

## Context

Implements the fixture half of spec §3 Module 2 and spec §4 "Test Data / Fixtures".
Every new example (TASK-4880, TASK-4881, TASK-4882, TASK-4883) loads these files, so they
must be correct and loadable before any of them starts.

Two decisions made after the spec was approved shape this fixture:

- **Q1 answered (b)** — TASK-4883 ships the `governed: false` compile leg, so this task
  also commits an **ungoverned copy** of the same graph in a **separate directory**. A
  second copy in the *same* directory is impossible: `SemanticModelLoader._models_from_documents`
  (`loader.py:163-166`) keys models by name into one dict, so a duplicate `orders` would
  silently overwrite the governed one.
- **Q3 answered (second connection, isolation demo)** — `customers` is pinned to its own
  named connection, `semantic_dim`, while `orders` stays on `semantic_example`. This
  demonstrates the real behaviour of `ConnectionResolver` (`execution.py:26-49`): the
  connection is resolved **per root model** from `PARROT_SEMANTIC_CONN_<NAME>_<KEY>`.
  It is **not** a cross-connection refusal — no such check exists in the library (the
  connection is read only from the root model's policy at `toolkit.py:315,485` and
  `engines/__init__.py:23`, and is never compared against a joined model's).

Spec §2 (S2) applies throughout: `loader.py:111-115` raises `missing_policy` for **every**
model name in a document, so each of the two models in each directory needs its own
`<model>.policy.yaml` — four policy files in total.

---

## Scope

- Create `examples/agents/semantic/models/` with the governed fixture: `orders.yml`,
  `orders.policy.yaml`, `customers.policy.yaml`.
- Give `orders.policy.yaml` the `masks:` and `saved_queries:` blocks TASK-4882 needs.
- Give `customers.policy.yaml` the second connection, `semantic_dim` (Q3).
- Create `examples/agents/semantic/models_ungoverned/` with the same two models and two
  `governed: false` policies, for TASK-4883's compile leg.
- Write `packages/ai-parrot-semantic/tests/test_example_fixtures.py` pinning that **both**
  directories load through the real `SemanticModelLoader` with no `missing_policy`, that
  the two connections are distinct, and that the mask and saved query validate.

**NOT in scope**: `_common.py` (TASK-4879); any example module; the DuckDB warehouse
builder (TASK-4879 owns it); any change under `packages/ai-parrot-semantic/src/**`;
editing `packages/ai-parrot-semantic/tests/fixtures/models/*` — the test fixtures stay
exactly as they are and this fixture is a separate, committed copy.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/semantic/models/orders.yml` | CREATE | Governed graph: `customers` + `orders` |
| `examples/agents/semantic/models/orders.policy.yaml` | CREATE | `governed: true`, `connection: semantic_example`, roles, RLS, `masks:`, `saved_queries:` |
| `examples/agents/semantic/models/customers.policy.yaml` | CREATE | `governed: true`, `connection: semantic_dim` (Q3) |
| `examples/agents/semantic/models_ungoverned/orders.yml` | CREATE | Same graph, separate directory |
| `examples/agents/semantic/models_ungoverned/orders.policy.yaml` | CREATE | `governed: false` |
| `examples/agents/semantic/models_ungoverned/customers.policy.yaml` | CREATE | `governed: false` |
| `packages/ai-parrot-semantic/tests/test_example_fixtures.py` | CREATE | Pin test: both directories load; AC11 |

> The pin test is an addition to the spec's §4 table. Spec AC11 ("the committed fixture
> loads through `SemanticModelLoader` … no `missing_policy`") is otherwise verified by no
> runnable test, and this task would have no validation command of its own.

---

## Codebase Contract (Anti-Hallucination)

> Verified at `e00c8de82` (2026-10-29).

### Verified Imports

```python
from parrot.semantic.loader import SemanticModelLoader          # verified: loader.py:70
from parrot.semantic.errors import SemanticPolicyError          # verified: errors.py:27
```

### Existing Signatures to Use

```python
# packages/ai-parrot-semantic/src/parrot/semantic/loader.py:70
class SemanticModelLoader:
    def __init__(self, models_dir: Path, driver: str = ...) -> None: ...
    def load(self) -> dict[str, LoadedModel]: ...
# loader.py:111-115 — per-model policy requirement
policy_path = self.models_dir / f"{name}.policy.yaml"
if not policy_path.is_file():
    raise SemanticPolicyError("missing_policy", "Each semantic model requires a policy side-file", details={"model": name})
# loader.py:116 — a model's policy is validated against the columns of its model AND its related models
columns = {graph_model.table: set(graph_model.columns) for graph_model in graph_models.values()}

# packages/ai-parrot-semantic/src/parrot/semantic/policy.py
class RoleGrant(BaseModel):    # :26   model_config = {"extra": "forbid"}  :29
    metrics: list[str] | Literal["*"]; dimensions: list[str] | Literal["*"]; usage: list[str] | Literal["*"]
class MaskRule(BaseModel):     # :36   model_config = {"extra": "forbid"}  :39
    strategy: Literal["null", "hash", "partial"]   # :41  MANDATORY, no default
    projection_roles: list[str] = []               # :42  roles EXEMPT from the mask
    usage_roles: list[str] = []                    # :43  roles allowed to USE the column outside projection
class SavedQuery(BaseModel):   # :46   model_config = {"extra": "forbid"}  :49
    name: str; query: SemanticQuery; verified_by: str; verified_at: date; description: str = ""
class ModelPolicy(BaseModel):  # :58   model_config = {"extra": "forbid"}  :61
    governed: bool = True; connection: str = ""; limits: Limits; roles: dict[str, RoleGrant]
    masks: dict[str, MaskRule]; rls: list[RlsRule]; saved_queries: list[SavedQuery]; allowed_functions: list[str]
# policy.py:105-110 — mask_for() returns None when the roles intersect projection_roles
def mask_for(self, roles: frozenset[str], column: str) -> MaskRule | None:
    rule = self.masks.get(column)
    if rule is None or roles.intersection(rule.projection_roles):
        return None
    return rule
# policy.py:147-148 — only a GOVERNED policy requires a connection
if policy.governed and not policy.connection:
    raise SemanticPolicyError("invalid_policy", "Governed policies require a connection")
# policy.py:203-212 — mask keys are table.column and the column must be a member or a known physical column
# policy.py:161-175 — a saved query's `model` is force-set from the policy FILENAME; never write it yourself
# policy.py:218-224 — saved queries are validated with query.validate_against(member_kinds, time_dimensions)

# packages/ai-parrot-semantic/src/parrot/semantic/execution.py:26
class ConnectionResolver:
    PREFIX = "PARROT_SEMANTIC_CONN_"                                    # :20
    def resolve(self, connection: str, driver: str) -> dict[str, Any]:  # :26
    # prefix = PREFIX + re.sub(r"[^A-Za-z0-9]", "_", connection).upper() + "_"   # :39
```

The shape to mirror — `packages/ai-parrot-semantic/tests/fixtures/models/orders.yml`
(22 lines) and `orders.policy.yaml` (8 lines), both read at `e00c8de82`:

```yaml
# packages/ai-parrot-semantic/tests/fixtures/models/orders.yml  (VERBATIM, 22 lines)
models:
  - name: customers
    table: dim.customers
    columns: {id: INTEGER, tenant_id: VARCHAR, email: VARCHAR, salary: DECIMAL}
    primary_key: [id]
    dimensions:
      - {name: email, kind: categorical, column: email}
    metrics:
      - {name: customer_count, agg: count}
    relationships:
      - {from_model: customers, to_model: orders, cardinality: one_to_many, from_columns: [id], to_columns: [customer_id]}
  - name: orders
    table: sales.orders
    columns: {id: INTEGER, customer_id: INTEGER, region: VARCHAR, tenant_id: VARCHAR, order_date: TIMESTAMP, amount: DECIMAL}
    primary_key: [id]
    dimensions:
      - {name: region, kind: categorical, column: region}
      - {name: order_date, kind: time, column: order_date, grain: month}
    metrics:
      - {name: revenue, agg: sum, column: amount}
      - {name: order_count, agg: count}
    relationships: []

# packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml  (VERBATIM, 8 lines)
governed: true
connection: semantic_test
limits: {default: 1000, max: 10000}
roles:
  analyst: {metrics: [revenue, order_count], dimensions: [region, order_date], usage: [sales.orders.region]}
  admin: {metrics: "*", dimensions: "*", usage: "*"}
rls:
  - {driver: duckdb, table: sales.orders, predicate_template: "region IN (:subject.programs)", subject_attribute: programs}
```

### Does NOT Exist

- ~~`qualified_members:`, `joined_members:`, a `models:` key inside `RoleGrant`~~ — verified
  absent from `policy.py`. `RoleGrant` is `extra="forbid"`: a guessed key is a hard
  `invalid_policy` error, not a warning.
- ~~a cross-connection check~~ — no code path compares a root model's `connection` to a
  joined model's, no error code names one, and no test asserts one. Do not write a fixture
  that claims to demonstrate a connection *refusal*.
- ~~`model:` inside a `saved_queries[].query`~~ — `_expand_saved_queries` (`policy.py:161-175`)
  overwrites it from the policy filename. Writing it is misleading and has no effect.
- ~~a `connection:` on a `governed: false` policy~~ — not required (`policy.py:147`) and not
  used; the ungoverned fixture must not carry one.
- ~~`customers.policy.yaml` under `packages/ai-parrot-semantic/tests/fixtures/models/`~~ —
  only `orders.yml` and `orders.policy.yaml` exist there; `tests/_models.py:16-23` writes
  the second at runtime. Do not "fix" the test fixtures.
- ~~`strategy` defaulting~~ — `MaskRule.strategy` has **no** default; omitting it is a
  validation error.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/semantic/models/orders.yml",
      "action": "CREATE"
    },
    {
      "path": "examples/agents/semantic/models/orders.policy.yaml",
      "action": "CREATE"
    },
    {
      "path": "examples/agents/semantic/models/customers.policy.yaml",
      "action": "CREATE"
    },
    {
      "path": "examples/agents/semantic/models_ungoverned/orders.yml",
      "action": "CREATE"
    },
    {
      "path": "examples/agents/semantic/models_ungoverned/orders.policy.yaml",
      "action": "CREATE"
    },
    {
      "path": "examples/agents/semantic/models_ungoverned/customers.policy.yaml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_fixtures.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/loader.py#SemanticModelLoader",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/policy.py#ModelPolicy",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/policy.py#MaskRule",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/policy.py#SavedQuery",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/policy.py#RoleGrant"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- The governed `orders.yml` is the test fixture's 22 lines **verbatim** — same two models,
  same columns, same relationship, same grain. Only the policies differ. Keeping the graph
  identical is what lets a reader compare the examples against the library's own tests.
- `masks` keys are physical `table.column`, not member names (`policy.py:203-208` does a
  `rpartition(".")`: `sales.orders.region` → table `sales.orders`, member `region`).
- **`projection_roles` lists the roles that are EXEMPT** from the mask (`policy.py:109`).
  The analyst must therefore be **absent** from `projection_roles` to see a masked value.
- A mask replaces the ordinary `usage:` grant for its column (`policy.py:101-103`): if
  `sales.orders.region` is masked, only `usage_roles` grants usage on it. Keep `analyst`
  in `usage_roles` so the existing RLS predicate and the analyst's `usage:` grant stay
  coherent.
- Do not add a file named `test_*.py` under `examples/` (AC10) — the pin test lives in
  `packages/ai-parrot-semantic/tests/`.

---

## Implementation Blueprint

### Steps (in order)
1. Copy the test fixture's `orders.yml` verbatim into `examples/agents/semantic/models/orders.yml` — *why*: the graph must match the library's own fixture so readers can diff the two.
2. Write `orders.policy.yaml` from the test fixture's policy, changing `connection` to `semantic_example` and adding `masks:` and `saved_queries:` — *why*: TASK-4882 demonstrates exactly these two keys, which no YAML outside unit tests carries (G4).
3. Write `customers.policy.yaml` with `connection: semantic_dim` — *why*: Q3's per-model connection isolation; `loader.py:111-115` requires this file to exist regardless.
4. Copy the same `orders.yml` into `models_ungoverned/` and add two `governed: false` policies — *why*: TASK-4883's compile leg needs a root model whose `check_query_rights` short-circuits (`catalog.py:64-65`), and a separate directory is the only way to avoid the name collision in step 1's dict.
5. Write the pin test and run it — *why*: AC11 is otherwise unverified, and a `missing_policy` here would block four downstream tasks.

### `examples/agents/semantic/models/orders.yml` (CREATE)
```yaml
# Governed example graph for the ai-parrot semantic layer.
# Mirrors packages/ai-parrot-semantic/tests/fixtures/models/orders.yml verbatim so the
# examples and the library's own tests describe the same warehouse.
models:
  - name: customers
    table: dim.customers
    columns: {id: INTEGER, tenant_id: VARCHAR, email: VARCHAR, salary: DECIMAL}
    primary_key: [id]
    dimensions:
      - {name: email, kind: categorical, column: email}
    metrics:
      - {name: customer_count, agg: count}
    relationships:
      - {from_model: customers, to_model: orders, cardinality: one_to_many, from_columns: [id], to_columns: [customer_id]}
  - name: orders
    table: sales.orders
    columns: {id: INTEGER, customer_id: INTEGER, region: VARCHAR, tenant_id: VARCHAR, order_date: TIMESTAMP, amount: DECIMAL}
    primary_key: [id]
    dimensions:
      - {name: region, kind: categorical, column: region}
      - {name: order_date, kind: time, column: order_date, grain: month}
    metrics:
      - {name: revenue, agg: sum, column: amount}
      - {name: order_count, agg: count}
    relationships: []
```
**Why this shape**: identical to the library's fixture. `order_date` carries
`grain: month`, which is what TASK-4883's time-grain leg queries; the `one_to_many`
relationship is what makes the cross-model join *compile* while governance still denies it.
Do not add models, columns or relationships — four downstream tasks assume exactly this graph.

### `examples/agents/semantic/models/orders.policy.yaml` (CREATE)
```yaml
# Policy for the `orders` model. One policy side-file per model (loader.py:111-115).
governed: true
connection: semantic_example
limits: {default: 1000, max: 10000}
roles:
  analyst: {metrics: [revenue, order_count], dimensions: [region, order_date], usage: [sales.orders.region]}
  admin: {metrics: "*", dimensions: "*", usage: "*"}
rls:
  - {driver: duckdb, table: sales.orders, predicate_template: "region IN (:subject.programs)", subject_attribute: programs}
masks:
  # `analyst` is deliberately NOT in projection_roles, so an analyst sees the masked value
  # while `admin` is exempt (policy.py:105-110). Both may still USE the column in filters
  # and RLS, because a mask replaces the ordinary `usage:` grant for its column.
  sales.orders.region:
    strategy: "null"
    projection_roles: [admin]
    usage_roles: [analyst, admin]
saved_queries:
  - name: monthly_revenue
    description: Revenue by calendar month. Reviewed for the analyst role.
    verified_by: data-governance
    verified_at: 2026-10-29
    query:
      metrics: [revenue]
      time_dimensions: [{name: order_date, grain: month}]
```
**Why this shape**: the `masks:` and `saved_queries:` blocks exist for TASK-4882 (G4) and
are the only two policy keys the repository demonstrates nowhere outside unit tests.
`strategy: "null"` is chosen so the masked projection is exactly assertable (spec §3 M5
requires the **exact** masked output); `hash` and `partial` are the other two legal values.
The saved query omits `model:` on purpose — `policy.py:161-175` injects it from this
filename. `grain` is mandatory on a `TimeDimension` (`models.py:32`).

### `examples/agents/semantic/models/customers.policy.yaml` (CREATE)
```yaml
# Policy for the `customers` model — REQUIRED by loader.py:111-115, which raises
# `missing_policy` for every model name in a document.
#
# Q3: `customers` resolves its own named connection. The semantic layer reads the
# connection from the ROOT model's policy only (toolkit.py:315,485), so a query rooted at
# `customers` reaches PARROT_SEMANTIC_CONN_SEMANTIC_DIM_DATABASE while a query rooted at
# `orders` reaches PARROT_SEMANTIC_CONN_SEMANTIC_EXAMPLE_DATABASE. This demonstrates
# per-model connection isolation; it is NOT a cross-connection refusal (no such check exists).
governed: true
connection: semantic_dim
limits: {default: 1000, max: 10000}
roles:
  analyst: {metrics: [customer_count], dimensions: [email], usage: [dim.customers.email]}
  admin: {metrics: "*", dimensions: "*", usage: "*"}
```
**Why this shape**: minimal but genuinely governed, so TASK-4883's second-connection leg
runs a real governed query against a second warehouse. It grants the analyst only what that
leg projects. Note this does **not** let a query rooted at `orders` reach `customers.email`
— `check_query_rights` resolves the allowed set from the root model alone (`catalog.py:66`).

### `examples/agents/semantic/models_ungoverned/orders.yml` (CREATE)
```yaml
# The SAME graph as ../models/orders.yml, in its own directory.
# A second copy cannot live beside the first: SemanticModelLoader._models_from_documents
# (loader.py:163-166) keys models by name into one dict, so a duplicate `orders` would
# silently overwrite the governed one.
# FILL IN: copy ../models/orders.yml verbatim (identical 22-line body) — bounded by AC12:
#          the two graphs must be identical, so the only difference on display is governance.
```
**Why this shape**: TASK-4883's leg (c) compiles the cross-model join that governance
denies. The lesson only lands if the graph is provably the same and *only* the policy
differs. Copy the file; do not re-type or re-shape it.

### `examples/agents/semantic/models_ungoverned/orders.policy.yaml` (CREATE)
```yaml
# Ungoverned twin of ../models/orders.policy.yaml.
# `governed: false` short-circuits RoleCatalog.check_query_rights (catalog.py:64-65), which
# is why the cross-model join compiles here and is denied next door. This is the COMPILER
# surface, not a way to bypass governance.
# No `connection:` — only a governed policy requires one (policy.py:147-148), and this
# model is compiled, never executed.
governed: false
roles:
  admin: {metrics: "*", dimensions: "*", usage: "*"}
```
**Why this shape**: the smallest policy that loads. It carries no RLS, no masks and no
saved queries, so nothing here can be mistaken for a governed capability.

### `examples/agents/semantic/models_ungoverned/customers.policy.yaml` (CREATE)
```yaml
# Required side-file for the second model in this directory (loader.py:111-115).
governed: false
roles:
  admin: {metrics: "*", dimensions: "*", usage: "*"}
```
**Why**: without it the whole directory fails to load with `missing_policy` — the exact
trap S2 identified.

### `packages/ai-parrot-semantic/tests/test_example_fixtures.py` (CREATE)
```python
"""Regression contract: the committed example model/policy fixtures load (FEAT-769 AC11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.semantic.loader import SemanticModelLoader  # verified: loader.py:70

_MODELS = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "models"
_UNGOVERNED = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "models_ungoverned"


def test_governed_fixture_loads_with_one_policy_per_model() -> None:
    """Both models load; neither raises `missing_policy` (spec AC11)."""
    loaded = SemanticModelLoader(_MODELS, driver="duckdb").load()
    assert set(loaded) == {"orders", "customers"}
    # FILL IN: assert orders is governed and customers is governed — bounded by AC11


def test_the_two_models_use_distinct_named_connections() -> None:
    """Q3: the connection is a per-model property, resolved from the ROOT model's policy."""
    loaded = SemanticModelLoader(_MODELS, driver="duckdb").load()
    assert loaded["orders"].policy.connection == "semantic_example"
    assert loaded["customers"].policy.connection == "semantic_dim"


def test_mask_and_saved_query_validate_through_the_real_loader() -> None:
    """The `masks:`/`saved_queries:` TASK-4882 demonstrates are accepted by load_policy."""
    policy = SemanticModelLoader(_MODELS, driver="duckdb").load()["orders"].policy
    mask = policy.masks["sales.orders.region"]
    assert mask.strategy == "null"
    # An analyst is NOT exempt, so a mask applies to it (policy.py:105-110).
    assert policy.mask_for(frozenset({"analyst"}), "sales.orders.region") is mask
    assert policy.mask_for(frozenset({"admin"}), "sales.orders.region") is None
    # FILL IN: assert the saved query's name and that its `model` was injected as "orders"
    #          — bounded by policy.py:161-175


def test_ungoverned_fixture_loads_and_is_not_governed() -> None:
    """TASK-4883's compile surface: same graph, `governed: false` on both models."""
    loaded = SemanticModelLoader(_UNGOVERNED, driver="duckdb").load()
    assert set(loaded) == {"orders", "customers"}
    assert not any(model.policy.governed for model in loaded.values())


def test_the_two_graphs_are_identical() -> None:
    """Only governance differs between the two directories (spec AC12)."""
    assert (_MODELS / "orders.yml").read_text(encoding="utf-8").splitlines()[2:] == (
        _UNGOVERNED / "orders.yml"
    ).read_text(encoding="utf-8").splitlines()[2:]
    # FILL IN: adjust the leading-comment offset if the two headers differ in length
    #          — bounded by: the `models:` body must compare equal, the comments need not
```
**Why this shape**: `parents[3]` is the repo root from
`packages/ai-parrot-semantic/tests/` — the same depth `test_example_agent.py:21` uses.
No `pytest.importorskip("duckdb")` is needed here because nothing opens a warehouse; the
loader is pure YAML + Pydantic. Every assertion is a denial-or-equality that fails loudly
rather than logging (spec AC7).

### FILL IN checklist
- [ ] `models_ungoverned/orders.yml` — copy the governed `orders.yml` body verbatim; bounded by AC12 (the graphs must be identical).
- [ ] `test_example_fixtures.py::test_governed_fixture_loads_with_one_policy_per_model` — assert both policies are `governed`; bounded by AC11.
- [ ] `test_example_fixtures.py::test_mask_and_saved_query_validate_through_the_real_loader` — assert the saved query's name and injected `model`; bounded by `policy.py:161-175`.
- [ ] `test_example_fixtures.py::test_the_two_graphs_are_identical` — set the comment-header offset so the `models:` bodies compare equal; bounded by AC12.

---

## Acceptance Criteria

- [ ] Both fixture directories load through `SemanticModelLoader` with no `missing_policy`
      (spec AC11).
- [ ] `examples/agents/semantic/models/orders.yml` and
      `examples/agents/semantic/models_ungoverned/orders.yml` declare an identical graph.
- [ ] `orders` resolves `connection: semantic_example`; `customers` resolves
      `connection: semantic_dim` (Q3).
- [ ] `orders.policy.yaml` carries a `masks:` entry keyed `sales.orders.region` whose
      `projection_roles` excludes `analyst`, and a `saved_queries:` entry whose `query`
      omits `model:`.
- [ ] Both `models_ungoverned/` policies are `governed: false` and carry no `connection:`.
- [ ] No fixture claims or demonstrates a cross-connection refusal (no such check exists).
- [ ] `ruff check packages/ai-parrot-semantic/tests/test_example_fixtures.py` is clean (spec AC9).
- [ ] No file named `test_*.py` was added under `examples/` (spec AC10).

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_example_fixtures.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_loader.py -q`

---

## Test Specification

See the `test_example_fixtures.py` block above — it IS the test specification for this
task. Five tests: governed load, distinct connections, mask/saved-query validation,
ungoverned load, graph equality. `test_loader.py` is run as a regression check that the
new fixture directories did not disturb the loader's own contract.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer-example --feature-id FEAT-769`)
2. **Read the spec** at the path listed above for full context — especially §2 (S2, one
   policy per model) and §4 "Test Data / Fixtures"
3. **Check dependencies** — TASK-4877 must be `"done"` in
   `sdd/tasks/index/semantic-layer-example.json`; this task writes into the directory it creates
4. **Verify the Codebase Contract** — re-read `policy.py:26-70` and `loader.py:111-117`
   before writing any YAML. `RoleGrant`, `MaskRule`, `SavedQuery` and `ModelPolicy` are all
   `extra="forbid"`: a guessed key is a hard validation error
5. **Update status** in `sdd/tasks/index/semantic-layer-example.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Steps in order; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4878 semantic-layer-example verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
