# TASK-4882: Masking and saved-queries example (`masked_policy_agent.py`)

**Feature**: FEAT-769 — Example agents for the governed Semantic Layer
**Spec**: `sdd/specs/semantic-layer-example.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4879
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5 and closes goal **G4**. `masks:` and `saved_queries:` are
fully supported in `policy.py` (`MaskRule` at `:36`, `SavedQuery` at `:46`) but appear in
no YAML outside unit tests, so an adopter has no worked example of either. This task makes
both executable against the committed fixture TASK-4878 wrote.

The two behaviours are easy to get backwards, which is why the example asserts the exact
output rather than printing it:

- **`projection_roles` lists the roles that are EXEMPT from the mask** (`policy.py:105-110`:
  `mask_for` returns `None` when the roles intersect `projection_roles`). The fixture
  therefore exempts `admin` and masks `analyst`.
- **A saved query is exclusive with explicit members** (`models.py:121-123`): a
  `SemanticQuery` carrying `saved_query=` must carry no metrics, dimensions,
  time_dimensions, filters or order_by at all.

---

## Scope

- Create `examples/agents/semantic/masked_policy_agent.py` with `run_masked_query`,
  `run_saved_query` and a `--smoke` path running both.
- Demonstrate the contrast: the same projection returns a masked value for `analyst` and a
  raw value for `admin`.
- Create `packages/ai-parrot-semantic/tests/test_example_masked_policy.py` asserting the
  **exact** masked output and the saved-query expansion.

**NOT in scope**: writing the `masks:`/`saved_queries:` YAML (TASK-4878 owns the fixture —
read it, do not change it); the shared scaffolding (TASK-4879); the LLM path (TASK-4880);
MCP-local (TASK-4881); grains or joins (TASK-4883); the README or docs (TASK-4884); any
change under `packages/ai-parrot-semantic/src/**`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/semantic/masked_policy_agent.py` | CREATE | Masking + saved-queries example |
| `packages/ai-parrot-semantic/tests/test_example_masked_policy.py` | CREATE | Pin test (spec §4) |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `e00c8de82` (2026-10-29).

### Verified Imports

```python
from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context  # verified: context.py:18,86
from parrot.semantic.models import SemanticQuery, SemanticQueryResult               # verified: models.py:102,217
from parrot.semantic.toolkit import SemanticLayerToolkit                            # verified: toolkit.py:38
```

### Existing Signatures to Use

```python
# packages/ai-parrot-semantic/src/parrot/semantic/policy.py:36-43
class MaskRule(BaseModel):                         # model_config = {"extra": "forbid"}  :39
    strategy: Literal["null", "hash", "partial"]   # :41  MANDATORY — no default
    projection_roles: list[str] = []               # :42  roles EXEMPT from the mask
    usage_roles: list[str] = []                    # :43  roles allowed to USE the column outside projection

# packages/ai-parrot-semantic/src/parrot/semantic/policy.py:46-52
class SavedQuery(BaseModel):                       # model_config = {"extra": "forbid"}  :49
    name: str; query: SemanticQuery; verified_by: str; verified_at: date; description: str = ""

# packages/ai-parrot-semantic/src/parrot/semantic/policy.py:105-110  — THE easily-inverted rule
def mask_for(self, roles: frozenset[str], column: str) -> MaskRule | None:
    rule = self.masks.get(column)
    if rule is None or roles.intersection(rule.projection_roles):
        return None          # <- listed roles are EXEMPT
    return rule

# packages/ai-parrot-semantic/src/parrot/semantic/policy.py:95-103
def usage_allowed(self, roles: frozenset[str], column: str) -> bool:
    mask = self.masks.get(column)
    if mask is not None:
        return bool(roles.intersection(mask.usage_roles))   # a mask REPLACES the ordinary usage grant
    return any(grant.usage == "*" or column in grant.usage for role, grant in self.roles.items() if role in roles)

# packages/ai-parrot-semantic/src/parrot/semantic/models.py:118-127
@model_validator(mode="after")
def validate_structure(self) -> "SemanticQuery":
    explicit_fields = self.metrics or self.dimensions or self.time_dimensions or self.filters or self.order_by
    if self.saved_query is not None:
        if explicit_fields:
            raise ValueError("saved_query is exclusive with explicit members, filters, and ordering")

# packages/ai-parrot-semantic/src/parrot/semantic/models.py:217-227
class SemanticQueryResult(BaseModel):
    columns: list[str]; rows: list[dict[str, Any]]; row_count: int; truncated: bool
    duration_ms: int; compiled_sql: str; audit_id: str; result_id: str | None = None

# packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py
async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult: ...   # :200
async def list_saved_queries(self, model: str) -> list[dict]: ...                 # :183

# packages/ai-parrot-semantic/src/parrot/semantic/catalog.py:75
def expand_saved_query(self, query: SemanticQuery) -> SemanticQuery: ...
    # replaces `saved_query` with the stored query (SAME model); unknown name -> SemanticValidationError
```

The fixture this example reads, committed by TASK-4878 at
`examples/agents/semantic/models/orders.policy.yaml`:

```yaml
masks:
  sales.orders.region:
    strategy: "null"
    projection_roles: [admin]       # admin is EXEMPT; analyst is masked
    usage_roles: [analyst, admin]
saved_queries:
  - name: monthly_revenue
    query:
      metrics: [revenue]
      time_dimensions: [{name: order_date, grain: month}]
```

Helpers from `examples/agents/semantic/_common.py` (TASK-4879): `build_warehouse`,
`connection_env`, `build_toolkit`, `example_identity` (its `roles=` keyword selects
`analyst` or `admin`).

### Does NOT Exist

- ~~`projection_roles` meaning "roles that get masked"~~ — it is the **exemption** list
  (`policy.py:109`). Inverting it is the most likely bug in this task.
- ~~a `SemanticQuery(saved_query="monthly_revenue", metrics=["revenue"])`~~ — the two are
  mutually exclusive (`models.py:121-123`); this raises a `ValueError` at construction.
- ~~`model:` inside the fixture's `saved_queries[].query`~~ — injected from the policy
  filename (`policy.py:161-175`). The saved query is always rooted at `orders`.
- ~~`MaskRule(strategy=...)` with any value outside `"null" | "hash" | "partial"`~~ —
  `Literal`-typed; anything else is a validation error.
- ~~a mask key that is a member name~~ — mask keys are physical `table.column`
  (`policy.py:203-208`), e.g. `sales.orders.region`.
- ~~`SemanticQueryResult.data`~~ — the field is `rows` (`models.py:221`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/semantic/masked_policy_agent.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_masked_policy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/policy.py#MaskRule",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/policy.py#SavedQuery",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#SemanticQuery",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#SemanticQueryResult",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- The fixture is read-only for this task. If the mask or saved query does not behave as
  described, report the drift — do not edit `models/orders.policy.yaml` (TASK-4878 owns it).
- The masked value must be asserted **exactly** (spec §3 M5). `strategy: "null"` was chosen
  by TASK-4878 precisely so the expected output is unambiguous.
- Do not label `compile_query` output "the SQL as executed" — it is **pre-RLS** SQL (spec
  §7, closed `issue:22fbd14d96a9`). Governed SQL lives only in the audit record.
- Do not copy the moved example's broad `usage:` list as "required": usage rights restrict
  only masked / `sensitive: true` members (closed `issue:9a4e4c35b032`).
- No LLM provider anywhere (spec AC6); this example builds no `Agent`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module docstring in `Usage::` form — *why*: house style for this directory (`hooba_agent.py:3-6`).
2. Add `run_masked_query(toolkit, identity)` projecting the masked column — *why*: it is the behaviour G4 names and the one `policy.py:105-110` makes easy to invert.
3. Add `run_saved_query(toolkit, identity)` executing `SemanticQuery(model=..., saved_query=...)` with no explicit members — *why*: `models.py:121-123` rejects the mixed form outright.
4. Add `smoke()` running both plus the admin contrast — *why*: the contrast is what proves `projection_roles` is an exemption list, not a mask list.
5. Write the pin test asserting the exact masked projection and the expansion — *why*: spec §3 M5 requires the **exact** masked output.

### `examples/agents/semantic/masked_policy_agent.py` (CREATE)
```python
"""Column masking and saved queries on a governed model (FEAT-769 M5).

Two policy features that `policy.py` supports but no YAML outside the unit tests
demonstrates: a `masks:` rule that redacts a projected column for roles that are not
exempt, and a reviewed `saved_queries:` entry executed by name.

Usage::

    python examples/agents/semantic/masked_policy_agent.py --smoke     # no LLM, no network
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
from parrot.semantic.models import SemanticQuery, SemanticQueryResult
from parrot.semantic.toolkit import SemanticLayerToolkit

LOGGER = logging.getLogger(__name__)

#: The physical column masked by models/orders.policy.yaml.
MASKED_COLUMN = "sales.orders.region"
#: The reviewed query that policy file publishes by name.
SAVED_QUERY_NAME = "monthly_revenue"


async def run_masked_query(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> SemanticQueryResult:
    """Project the masked column and return the governed result.

    The policy exempts `admin` from the mask through ``projection_roles`` and therefore
    masks every other role, `analyst` included (``policy.py:105-110``).

    Args:
        toolkit: The governed toolkit.
        identity: The trusted identity whose roles decide whether the mask applies.

    Returns:
        The governed query result; `region` is redacted unless the identity is exempt.
    """
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await toolkit.query_metrics(query)


async def run_saved_query(toolkit: SemanticLayerToolkit, identity: SemanticRequestIdentity) -> SemanticQueryResult:
    """Execute the reviewed saved query by name.

    ``saved_query`` is exclusive with explicit members, filters and ordering
    (``models.py:121-123``), so the query below carries nothing but the model and the name.

    Args:
        toolkit: The governed toolkit.
        identity: The trusted identity.

    Returns:
        The governed result of the expanded saved query.
    """
    query = SemanticQuery(model="orders", saved_query=SAVED_QUERY_NAME)
    async with bind_semantic_context(identity.ctx, identity=identity):
        return await toolkit.query_metrics(query)


async def smoke() -> dict[str, Any]:
    """Run the masked projection for both roles and the saved query, with no LLM.

    Returns:
        A JSON-safe summary showing the masked and unmasked projections side by side.
    """
    with tempfile.TemporaryDirectory() as directory:
        warehouse = _common.build_warehouse(Path(directory))
        with _common.connection_env(warehouse):
            toolkit = _common.build_toolkit(warehouse)
            analyst = _common.example_identity("analyst-1", "session-1", "eu")
            # FILL IN: build an `admin` identity with
            #          _common.example_identity(..., roles=frozenset({"admin"})), run
            #          run_masked_query for both and run_saved_query once, and return a
            #          summary contrasting the analyst's redacted `region` with the
            #          admin's raw value — bounded by: `projection_roles` is an EXEMPTION
            #          list, so the admin is the one who sees the real value.
            raise NotImplementedError


async def main() -> None:
    """Run the deterministic masking and saved-query demonstration."""
    parser = argparse.ArgumentParser(description="Masking and saved queries on a governed model")
    parser.add_argument("--smoke", action="store_true", help="Run the deterministic demo (default)")
    parser.parse_args()
    print(json.dumps(await smoke(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```
**Why this shape**: `run_masked_query` and `run_saved_query` take an identity rather than a
role string so the same function demonstrates both sides of the exemption — running it
twice with different roles is what makes the `projection_roles` semantics visible. The
saved-query call carries only `model` and `saved_query` because any explicit member turns
it into a construction-time `ValueError`.

### `packages/ai-parrot-semantic/tests/test_example_masked_policy.py` (CREATE)
```python
"""Regression contract: the masking / saved-queries example (FEAT-769 M5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from parrot.semantic.models import SemanticQuery

pytest.importorskip("duckdb")

_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "agents" / "semantic" / "masked_policy_agent.py"


@pytest.fixture(scope="module")
def example() -> ModuleType:
    """Load the example by absolute path, after the duckdb skip check."""
    spec = importlib.util.spec_from_file_location("semantic_masked_policy_example", _EXAMPLE_PATH)
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
    """A governed toolkit with the example connection bound."""
    warehouse = example._common.build_warehouse(tmp_path)
    with example._common.connection_env(warehouse):
        yield example._common.build_toolkit(warehouse)


@pytest.mark.asyncio
async def test_analyst_sees_the_exact_masked_projection(example: ModuleType, governed) -> None:
    """Spec §3 M5: the masked output is asserted exactly, not merely logged."""
    identity = example._common.example_identity("analyst-1", "session-1", "eu")
    result = await example.run_masked_query(governed, identity)
    assert "region" in result.columns
    # FILL IN: assert EVERY row's `region` is the exact redacted value produced by
    #          strategy "null" — bounded by: this must be an equality assertion on the
    #          value, not a truthiness check, so a mask that stops applying fails the test.


@pytest.mark.asyncio
async def test_admin_is_exempt_and_sees_the_raw_value(example: ModuleType, governed) -> None:
    """`projection_roles` is an EXEMPTION list (policy.py:105-110)."""
    identity = example._common.example_identity("admin-1", "session-2", "eu", roles=frozenset({"admin"}))
    result = await example.run_masked_query(governed, identity)
    # FILL IN: assert at least one row's `region` is a real region value from the fixture
    #          ('eu' or 'us') — bounded by: if this ever equals the masked value, the
    #          exemption has inverted and the test must fail.


@pytest.mark.asyncio
async def test_saved_query_expands_and_runs(example: ModuleType, governed) -> None:
    """The reviewed query executes by name and returns the monthly revenue shape."""
    identity = example._common.example_identity("analyst-1", "session-1", "eu")
    result = await example.run_saved_query(governed, identity)
    # FILL IN: assert the result carries the revenue metric and a month-grained
    #          order_date column — bounded by the fixture's saved query definition.


def test_saved_query_is_exclusive_with_explicit_members() -> None:
    """models.py:121-123 — the mixed form is rejected at construction."""
    with pytest.raises(ValueError, match="exclusive"):
        SemanticQuery(model="orders", saved_query="monthly_revenue", metrics=["revenue"])


@pytest.mark.asyncio
async def test_smoke_contrasts_both_roles_without_a_provider(example: ModuleType) -> None:
    """Spec AC3/AC6: offline, deterministic, no LLM."""
    summary = await example.smoke()
    # FILL IN: assert the summary shows the analyst's redacted value and the admin's raw
    #          value as different — bounded by AC6 (no provider initialized).
```
**Why this shape**: the analyst and admin tests are a matched pair; together they fail if
`projection_roles` is read backwards, which a single test could not catch.
`test_saved_query_is_exclusive_with_explicit_members` needs no fixture at all — it pins a
constructor rule an adopter will hit on their first attempt.

### FILL IN checklist
- [ ] `masked_policy_agent.py::smoke` — the admin identity and the contrasting summary; bounded by: `projection_roles` is an exemption list.
- [ ] `test_example_masked_policy.py::test_analyst_sees_the_exact_masked_projection` — the exact-value assertion; bounded by spec §3 M5.
- [ ] `test_example_masked_policy.py::test_admin_is_exempt_and_sees_the_raw_value` — the raw-value assertion; bounded by `policy.py:105-110`.
- [ ] `test_example_masked_policy.py::test_saved_query_expands_and_runs` — the metric/grain assertions; bounded by the fixture's saved query.
- [ ] `test_example_masked_policy.py::test_smoke_contrasts_both_roles_without_a_provider` — the difference assertion; bounded by AC6.

---

## Acceptance Criteria

- [ ] The pin test asserts the **exact** masked projection for `analyst` and the raw value
      for the exempt `admin` (spec §3 M5).
- [ ] The saved query runs by name with no explicit members, and the mixed form is pinned
      as a `ValueError`.
- [ ] `--smoke` runs offline with no LLM call, no network, no write outside a temporary
      directory, and `CONNECTION_ENV` restored on exit (spec AC3).
- [ ] No LLM provider is initialized (spec AC6).
- [ ] `examples/agents/semantic/models/orders.policy.yaml` is **not** modified by this task.
- [ ] `ruff check examples/agents/semantic packages/ai-parrot-semantic/tests/test_example_masked_policy.py`
      is clean (spec AC9).
- [ ] No file named `test_*.py` was added under `examples/` (spec AC10).

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_example_masked_policy.py -q`

---

## Test Specification

See the `test_example_masked_policy.py` block above — it IS the test specification. Five
tests: the exact masked projection, the exempt role's raw value, the saved-query
expansion, the exclusivity rule, and the offline smoke contrast.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer-example --feature-id FEAT-769`)
2. **Read the spec** at the path listed above, and read
   `examples/agents/semantic/models/orders.policy.yaml` before writing any assertion
3. **Check dependencies** — TASK-4879 must be `"done"`
4. **Verify the Codebase Contract** — re-read `policy.py:95-110` before deciding which role
   is masked. `projection_roles` is an EXEMPTION list; getting this backwards is the
   expected failure mode of this task
5. **Update status** in `sdd/tasks/index/semantic-layer-example.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — follow the Steps in order; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4882 semantic-layer-example verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
