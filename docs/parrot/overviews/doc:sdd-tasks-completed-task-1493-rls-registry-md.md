---
type: Wiki Overview
title: 'TASK-1493: RLS Registry'
id: doc:sdd-tasks-completed-task-1493-rls-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: template with subject attributes, producing bound parameters (not interpolated).
relates_to:
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.auth.rls_registry
  rel: mentions
---

# TASK-1493: RLS Registry

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 4. navigator-auth has no obligation/advice channel, so RLS
> predicates cannot travel inside the policy grant. Instead, a parrot-side
> in-memory registry maps `(driver, table)` to predicate templates with
> subject-attribute placeholders. This is a leaf module — no dependencies
> on other FEAT-228 tasks.

---

## Scope

- Define the `RlsRule` and `RlsPredicate` Pydantic models.
- Implement `RlsRegistry` with:
  - `register(rule: RlsRule)` — add a predicate template.
  - `lookup(driver: str, tables: set[str]) -> list[RlsRule]` — find matching rules.
  - `render(rule: RlsRule, ctx: PermissionContext) -> RlsPredicate` — render
    template with subject attributes, producing bound parameters (not interpolated).
- Superuser / fully-granted subjects → empty predicate list.
- Write unit tests.

**NOT in scope**: SQL/AST injection of predicates (TASK-1494), guard evaluation
(TASK-1495), `AuthorizingDataSource` (TASK-1496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/rls_registry.py` | CREATE | `RlsRegistry`, `RlsRule`, `RlsPredicate` |
| `tests/auth/test_rls_registry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.permission import PermissionContext, UserSession
# verified: packages/ai-parrot/src/parrot/auth/__init__.py exports both

# PermissionContext fields:
# session: UserSession, request_id, channel, trace_context, extra

# to_eval_context bridge:
from parrot.auth.permission import to_eval_context
# verified: parrot/auth/permission.py:166 (module-level function)
# Returns EvalContext(username, user_id, tenant_id, groups, roles, programs)
```

### Existing Signatures to Use
```python
# parrot/auth/permission.py:80
@dataclass
class PermissionContext:
    session: UserSession                              # line ~80
    request_id: Optional[str] = None
    channel: Optional[str] = None
    trace_context: "Optional[TraceContext]" = None
    extra: dict[str, Any] = field(default_factory=dict)

# UserSession (same file) — has: username, groups, roles, programs
```

### Does NOT Exist
- ~~`parrot.auth.rls_registry`~~ — does not exist yet (this task creates it)
- ~~`RlsRule`~~ — does not exist yet (this task creates it)
- ~~`RlsPredicate`~~ — does not exist yet (this task creates it)
- ~~`RlsRegistry`~~ — does not exist yet (this task creates it)
- ~~`PermissionContext.groups`~~ — groups live on `PermissionContext.session.groups`, NOT directly on `PermissionContext`
- ~~`PermissionContext.programs`~~ — programs live on `PermissionContext.session.programs`

---

## Implementation Notes

### Pattern to Follow
```python
from pydantic import BaseModel, Field
from parrot.auth.permission import PermissionContext

class RlsRule(BaseModel):
    """Registry entry: template predicate keyed by (driver, table)."""
    driver: str
    table: str
    predicate_template: str    # e.g. "region IN (:subject.programs)"
    subject_attribute: str     # e.g. "programs" or "groups"
    description: str = ""

class RlsPredicate(BaseModel):
    """A rendered RLS predicate ready for injection."""
    table: str
    sql_predicate: str         # e.g. "region IN (:p0, :p1)"
    bound_params: dict[str, list[str]] = Field(default_factory=dict)

class RlsRegistry:
    """In-memory registry: (driver, table) -> predicate template."""

    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], RlsRule] = {}

    def register(self, rule: RlsRule) -> None: ...

    def lookup(self, driver: str, tables: set[str]) -> list[RlsRule]: ...

    def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate:
        """Render template with subject attributes as bound parameters."""
        # Extract attribute values from ctx.session (e.g. ctx.session.programs)
        # Generate parameter placeholders (:p0, :p1, ...)
        # Return RlsPredicate with bound_params dict
        ...
```

### Key Constraints
- **Never interpolate** subject values into SQL strings. Always produce
  `bound_params` for parameterized binding.
- Subject attributes are read from `ctx.session.groups`, `ctx.session.programs`,
  etc. — NOT from `ctx.groups` (which doesn't exist).
- The `predicate_template` uses a simple placeholder convention:
  `:subject.<attr>` where `<attr>` matches a `UserSession` field name.
- Empty attribute list (e.g. `programs=[]`) → the predicate becomes a tautology
  that matches nothing (`1=0` or empty IN), effectively denying all rows.
- Registry is in-memory; loaded from config at startup (config loading is NOT
  part of this task).

### References in Codebase
- `parrot/auth/permission.py` — `PermissionContext`, `UserSession`
- `parrot/auth/dataset_guard.py` — structural pattern for auth modules

---

## Acceptance Criteria

- [ ] `RlsRegistry.register()` stores a rule keyed by `(driver, table)`
- [ ] `RlsRegistry.lookup("pg", {"pg:sales.orders"})` returns matching rules
- [ ] `RlsRegistry.lookup("pg", {"pg:unknown.table"})` returns empty list
- [ ] `RlsRegistry.render()` produces `RlsPredicate` with bound parameters
- [ ] Rendered predicate never contains raw subject values in `sql_predicate`
- [ ] Empty subject attribute (e.g. `programs=[]`) produces a deny-all predicate
- [ ] All tests pass: `pytest tests/auth/test_rls_registry.py -v`
- [ ] No linting errors: `ruff check parrot/auth/rls_registry.py`
- [ ] Imports work: `from parrot.auth.rls_registry import RlsRegistry, RlsRule, RlsPredicate`

---

## Test Specification

```python
# tests/auth/test_rls_registry.py
import pytest
from parrot.auth.rls_registry import RlsRegistry, RlsRule, RlsPredicate
from parrot.auth.permission import PermissionContext, UserSession


@pytest.fixture
def registry():
    reg = RlsRegistry()
    reg.register(RlsRule(
        driver="pg",
        table="sales.orders",
        predicate_template="region IN (:subject.programs)",
        subject_attribute="programs",
        description="Regional managers see only their region",
    ))
    return reg


@pytest.fixture
def regional_pctx():
    return PermissionContext(
        session=UserSession(
            username="regional_mgr",
            groups=["RegionalManager"],
            programs=["northeast", "southeast"],
        )
    )


class TestRlsRegistry:
    def test_lookup_match(self, registry):
        rules = registry.lookup("pg", {"pg:sales.orders"})
        assert len(rules) == 1
        assert rules[0].table == "sales.orders"

    def test_lookup_no_match(self, registry):
        rules = registry.lookup("pg", {"pg:hr.employees"})
        assert len(rules) == 0

    def test_render_produces_bound_params(self, registry, regional_pctx):
        rules = registry.lookup("pg", {"pg:sales.orders"})
        pred = registry.render(rules[0], regional_pctx)
        assert isinstance(pred, RlsPredicate)
        assert "northeast" not in pred.sql_predicate  # not interpolated
        assert len(pred.bound_params) > 0

    def test_render_empty_programs_deny_all(self, registry):
        ctx = PermissionContext(
            session=UserSession(username="nobody", groups=[], programs=[])
        )
        rules = registry.lookup("pg", {"pg:sales.orders"})
        pred = registry.render(rules[0], ctx)
        assert pred.sql_predicate in ("1=0", "FALSE")  # deny-all tautology
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` §5.5 for RLS design
2. **Check dependencies** — none; start immediately
3. **Verify the Codebase Contract** — confirm `PermissionContext` and `UserSession` fields
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1493-rls-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-08
**Notes**: Implemented RlsRule, RlsPredicate, RlsRegistry. Codebase Contract deviation: UserSession uses `user_id`/`tenant_id`/`metadata` instead of `username`/`groups`/`programs` — adapted to read groups/programs from `session.metadata`. All 8 tests pass.

**Deviations from spec**: UserSession schema in this codebase uses `metadata` dict for groups/programs, not top-level fields. Adapted accordingly without changing the public RLS API.
