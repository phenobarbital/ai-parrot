# TASK-576: Extended Router — Database Selection + Role Inference

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-569
**Assigned-to**: unassigned

---

## Context

Implements spec Module 9. Extends the existing `SchemaQueryRouter` with two new capabilities: (a) database selection — detecting which toolkit to route to based on query mentions, and (b) role inference — mapping `QueryIntent` to a suggested `UserRole` when no explicit role is provided. This enables the three-tier role resolution: explicit > inferred > default.

---

## Scope

- Extend `SchemaQueryRouter` in `router.py` (modify existing file):
  - Add `registered_databases: Dict[str, str]` — maps database identifiers to toolkit names
  - Add `register_database(identifier, toolkit_name)` method
  - Add role inference via `INTENT_ROLE_MAPPING` dict:
    - `OPTIMIZE_QUERY` → `DATABASE_ADMIN`
    - `SHOW_DATA` → `BUSINESS_USER`
    - `GENERATE_QUERY` → `DATA_ANALYST`
    - `ANALYZE_DATA` → `DATA_SCIENTIST`
    - `EXPLORE_SCHEMA` → `DEVELOPER`
    - `VALIDATE_QUERY` → `QUERY_DEVELOPER`
    - `EXPLAIN_METADATA` → `DEVELOPER`
    - `CREATE_EXAMPLES` → `DEVELOPER`
  - Extend `route()` to:
    - Accept optional `database: Optional[str]` parameter
    - Set `target_database` in `RouteDecision` (explicit > detected from query > None)
    - Set `role_source` field: `"explicit"`, `"inferred"`, or `"default"`
    - When no `user_role` provided, infer from `QueryIntent` via mapping
- Extend `RouteDecision` dataclass in `models.py`:
  - Add `target_database: Optional[str] = None`
  - Add `role_source: str = "default"`
- Write unit tests for role inference, database detection, and priority ordering

**NOT in scope**: Agent integration, toolkit registration logic (that's in DatabaseAgent).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/router.py` | MODIFY | Add database selection + role inference |
| `parrot/bots/database/models.py` | MODIFY | Add fields to RouteDecision |
| `tests/unit/test_extended_router.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.models import (
    UserRole,           # models.py:15
    QueryIntent,        # models.py:72
    RouteDecision,      # models.py:241
    OutputComponent,    # models.py:24
    get_default_components,    # models.py:412
    INTENT_COMPONENT_MAPPING,  # models.py:459
)
from parrot.bots.database.router import SchemaQueryRouter  # router.py:15
```

### Existing Signatures to Use
```python
# parrot/bots/database/router.py:15
class SchemaQueryRouter:
    def __init__(self, primary_schema, allowed_schemas):  # line 18
    async def route(self, query, user_role, output_components=None, intent_override=None) -> RouteDecision:  # line 93
    def _detect_intent(self, query) -> QueryIntent:  # line 140
    def _is_raw_sql(self, query) -> bool:  # line 134

# parrot/bots/database/models.py:241
@dataclass
class RouteDecision:
    intent: QueryIntent
    components: OutputComponent
    user_role: UserRole
    primary_schema: str
    allowed_schemas: List[str]
    needs_metadata_discovery: bool = True
    needs_query_generation: bool = True
    needs_execution: bool = True
    needs_plan_analysis: bool = False
    data_limit: Optional[int] = 1000
    include_full_data: bool = False
    convert_to_dataframe: bool = False
    execution_options: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.8
```

### Does NOT Exist
- ~~`SchemaQueryRouter.select_database()`~~ — no such method
- ~~`SchemaQueryRouter.infer_role()`~~ — no such method
- ~~`INTENT_ROLE_MAPPING`~~ — does not exist yet (this task creates it)
- ~~`RouteDecision.target_database`~~ — field does not exist yet
- ~~`RouteDecision.role_source`~~ — field does not exist yet

---

## Implementation Notes

### Key Constraints
- `route()` signature must remain backward-compatible: new params are optional
- Database detection from query: simple keyword matching (e.g., "bigquery", "postgres", "influx" in query text)
- Role inference is a suggestion — explicit `user_role` always wins
- `INTENT_ROLE_MAPPING` is a reasonable default; it can be overridden at agent level

### References in Codebase
- `parrot/bots/database/router.py` — existing router to extend
- `parrot/bots/database/models.py:197` — `ROLE_COMPONENT_DEFAULTS` for reference on role patterns

---

## Acceptance Criteria

- [ ] `route()` accepts optional `database` and `user_role` (now truly optional) params
- [ ] `RouteDecision` includes `target_database` and `role_source` fields
- [ ] Role inference: "optimize this query" with no explicit role → `DATABASE_ADMIN`
- [ ] Role inference: "show me sales data" with no explicit role → `BUSINESS_USER`
- [ ] Explicit role beats inferred: `route(query, user_role=DEVELOPER)` → role_source="explicit"
- [ ] Database detection: query mentioning "bigquery" sets `target_database`
- [ ] Backward compatible: existing calls without new params still work
- [ ] All tests pass: `pytest tests/unit/test_extended_router.py -v`

---

## Test Specification

```python
import pytest
from parrot.bots.database.router import SchemaQueryRouter
from parrot.bots.database.models import UserRole, QueryIntent


class TestRoleInference:
    @pytest.fixture
    def router(self):
        r = SchemaQueryRouter(primary_schema="public", allowed_schemas=["public"])
        r.register_database("sales_pg", "PostgresToolkit")
        r.register_database("analytics_bq", "BigQueryToolkit")
        return r

    async def test_optimize_infers_dba(self, router):
        decision = await router.route("optimize this slow query SELECT * FROM orders")
        assert decision.user_role == UserRole.DATABASE_ADMIN
        assert decision.role_source == "inferred"

    async def test_show_data_infers_business(self, router):
        decision = await router.route("show me all sales for Q1")
        assert decision.user_role == UserRole.BUSINESS_USER
        assert decision.role_source == "inferred"

    async def test_explicit_role_wins(self, router):
        decision = await router.route(
            "show me data", user_role=UserRole.DEVELOPER
        )
        assert decision.user_role == UserRole.DEVELOPER
        assert decision.role_source == "explicit"

    async def test_database_detection(self, router):
        decision = await router.route("what tables are in bigquery analytics?")
        assert decision.target_database is not None

    async def test_backward_compatible(self, router):
        """Old-style call still works."""
        decision = await router.route(
            "show me data", user_role=UserRole.DATA_ANALYST
        )
        assert decision.intent is not None
        assert decision.components is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sqlagent-repair.spec.md` (Module 9)
2. **Check dependencies** — TASK-569 must be completed (for model awareness), but this task modifies `router.py` and `models.py` directly
3. **Read existing `router.py`** carefully — extend, don't rewrite
4. **Read existing `models.py`** ��� add fields to `RouteDecision` without breaking existing fields
5. **Implement**, test, move to completed, update index

---

## Completion Note

*(Agent fills this in when done)*
