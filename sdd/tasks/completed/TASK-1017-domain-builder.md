# TASK-1017: Domain Builder

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1013
**Assigned-to**: unassigned

---

## Context

Agents must manually construct Odoo domain triplets, which is error-prone. This
task adds a `build_domain` method that takes structured `{field, operator, value}`
dicts, validates operators, and produces the correct Odoo domain array.

Implements spec §3 Module 4: Domain Builder.

---

## Scope

- Add `build_domain` method to `OdooToolkit` (synchronous — no Odoo call)
- Define `SAFE_DOMAIN_OPERATORS` constant (frozenset)
- Validate each condition's operator against the whitelist
- Handle logical operators: `"and"` (default, uses `&` prefix) and `"or"` (uses `|` prefix)
- Decorate with `@tool_schema(BuildDomainInput)`
- Return `DomainBuildResult` envelope

**NOT in scope**: Domain parsing from string input, nested boolean combinations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `build_domain`, `SAFE_DOMAIN_OPERATORS` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import BuildDomainInput        # TASK-1013
from .models.envelopes import DomainBuildResult    # TASK-1013
from parrot.tools.decorators import tool_schema    # decorators.py:37
```

### Does NOT Exist
- ~~`OdooToolkit.build_domain()`~~ — must be created
- ~~`parrot_tools.odoo.domain_utils`~~ — no such module

---

## Implementation Notes

### Operator Whitelist (from spec §7)
```python
SAFE_DOMAIN_OPERATORS = frozenset({
    "=", "!=", ">", ">=", "<", "<=",
    "in", "not in",
    "like", "not like", "ilike", "not ilike",
    "=like", "=ilike",
    "child_of", "parent_of",
})
```

### Domain Construction Logic
For `"and"` with N conditions: `['&'] * (N-1) + [(field, op, val), ...]`
For `"or"` with N conditions: `['|'] * (N-1) + [(field, op, val), ...]`

Example: `build_domain([{field: "name", operator: "ilike", value: "test"}, {field: "active", operator: "=", value: True}], "and")`
→ `DomainBuildResult(domain=['&', ('name', 'ilike', 'test'), ('active', '=', True)], warnings=[], valid=True)`

### Key Constraints
- This method is synchronous (not async) — no Odoo call needed
- Reject operators not in whitelist → set `valid=False` and add warning
- Empty conditions → return `domain=[]`, `valid=True`
- Single condition → no prefix operator needed

---

## Acceptance Criteria

- [ ] AND with 2 conditions produces correct `&` prefix
- [ ] OR with 3 conditions produces correct `|` prefixes
- [ ] Unsafe operator (e.g., `"LIKE; DROP TABLE"`) → `valid=False` with warning
- [ ] Empty conditions → `domain=[]`
- [ ] Returns `DomainBuildResult` envelope

---

## Test Specification

```python
def test_build_domain_and():
    result = tk.build_domain(
        conditions=[
            {"field": "name", "operator": "ilike", "value": "test"},
            {"field": "active", "operator": "=", "value": True},
        ],
        logical_operator="and",
    )
    assert result.valid is True
    assert "&" in result.domain

def test_build_domain_or():
    result = tk.build_domain(
        conditions=[
            {"field": "email", "operator": "ilike", "value": "@acme"},
            {"field": "phone", "operator": "!=", "value": False},
        ],
        logical_operator="or",
    )
    assert result.valid is True
    assert "|" in result.domain

def test_build_domain_invalid_operator():
    result = tk.build_domain(
        conditions=[{"field": "name", "operator": "EVIL", "value": "x"}],
    )
    assert result.valid is False
    assert len(result.warnings) > 0
```

---

## Completion Note

*(Agent fills this in when done)*
