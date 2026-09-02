# TASK-2717: catalog.py — Add Fable models and research_primary role

**Feature**: FEAT-494 — select-model-dev-flow-ideation-model
**Spec**: `sdd/specs/select-model-dev-flow-ideation-model.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The `claude-code` backend in `catalog.py` does not list Fable models
(`"claude-fable-5-1"`, `"claude-fable-5"`) in its `models` tuple, and its
`roles` tuple does not include `"research_primary"`. As a consequence:

- The `dl-claude-models` datalist in `dev.html` (built from
  `modelOptions("claude-code", "")`) does not surface Fable as an option.
- `catalog_payload()["roles"]` has no `"research_primary"` key, so any surface
  querying that role gets nothing.

This task implements spec §3 Module 1.

---

## Scope

- Append `"claude-fable-5-1"` and `"claude-fable-5"` to the `claude-code`
  `BackendInfo.models` tuple (after `"claude-haiku-4-5"`).
- Append `"research_primary"` to the `claude-code` `BackendInfo.roles` tuple.
- Add `"research_primary": [b.id for b in backends_for_role("research_primary")]`
  to the `"roles"` dict inside `catalog_payload()`.

**NOT in scope**:
- Changes to `server_dev.py` (TASK-2718).
- Test files (TASK-2719).
- Any change to the Bedrock `nova` backend entry (line 342 contains the
  unrelated `"global.anthropic.claude-fable-5"` cross-region id — do NOT touch).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py` | MODIFY | Add Fable to claude-code models; add research_primary to roles; update catalog_payload |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# No new imports needed — all changes are within catalog.py itself
from parrot.flows.dev_loop.catalog import BackendInfo, BACKENDS, backends_for_role, catalog_payload
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:544-558
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:214-227
class BackendInfo(NamedTuple):
    id: str
    label: str
    transport: str
    model_env: Optional[str]
    default_model: str
    models: Tuple[str, ...]   # line 224 — append Fable ids here
    requires: str
    roles: Tuple[str, ...]    # line 226 — append "research_primary" here
    notes: str = ""

# claude-code BackendInfo entry — lines 232-246 (CURRENT state, before this task)
BackendInfo(
    id="claude-code",
    label="Claude Code",
    transport="cli",
    model_env=None,
    default_model="claude-sonnet-4-6",
    models=(
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        # ← insert "claude-fable-5-1", "claude-fable-5" here
    ),
    requires="`claude` CLI on $PATH, authenticated",
    roles=("development", "judge", "primary_review", "planner"),
    # ← insert "research_primary" here
    notes="Write-enabled reviewer; also drives planner/synthesis/QA.",
)

# catalog_payload() — lines 507-541
# Current "roles" dict keys: development, judge, primary_review, adversarial, research_partner
# ← add "research_primary" key

# backends_for_role() — line 420-433
def backends_for_role(role: str) -> List[BackendInfo]:
    return [b for b in _BY_ID.values() if role in b.roles]  # line 433
```

### Does NOT Exist

- ~~`RESEARCH_PRIMARY_BACKENDS`~~ — no such module-level constant; use `backends_for_role("research_primary")`.
- ~~`BackendInfo.research_primary_models`~~ — no such attribute; the field is `models`.
- ~~`"claude-fable-5-1"` or `"claude-fable-5"` in claude-code's models~~ — NOT present yet (only `"global.anthropic.claude-fable-5"` exists in the `nova` backend at line 342 — a separate, unrelated entry).

---

## Implementation Notes

### Pattern to Follow

The `models` tuple is append-only — add Fable ids AFTER `"claude-haiku-4-5"`,
preserving the existing order:

```python
models=(
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-fable-5-1",   # new
    "claude-fable-5",     # new
),
```

The `catalog_payload()` roles dict addition follows the established pattern:

```python
"roles": {
    "development": [b.id for b in backends_for_role("development")],
    "judge": [b.id for b in backends_for_role("judge")],
    "primary_review": [b.id for b in backends_for_role("primary_review")],
    "adversarial": [resolved_adversarial_backend],
    "research_partner": [b.id for b in backends_for_role("research_partner")],
    "research_primary": [b.id for b in backends_for_role("research_primary")],  # new
},
```

### Key Constraints

- Do NOT reorder or remove any existing entry in the `models` or `roles` tuples.
- The `_BY_ID` dict is built at import time from `BACKENDS` — modifying the
  `claude-code` entry in `BACKENDS` automatically updates `_BY_ID`. No extra
  dict manipulation needed.
- Do NOT touch the `nova` backend or any other backend entry.
- Both Fable ids must be added: `"claude-fable-5-1"` AND `"claude-fable-5"`.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:232-246` — claude-code entry
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:507-541` — `catalog_payload()`
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:420-433` — `backends_for_role()`

---

## Acceptance Criteria

- [ ] `"claude-fable-5-1"` is in the `claude-code` `models` tuple.
- [ ] `"claude-fable-5"` is in the `claude-code` `models` tuple.
- [ ] `"research_primary"` is in the `claude-code` `roles` tuple.
- [ ] `catalog_payload()["roles"]["research_primary"]` is a non-empty list.
- [ ] `"claude-code"` is in `catalog_payload()["roles"]["research_primary"]`.
- [ ] Existing models (`"claude-opus-5"`, `"claude-sonnet-5"`, `"claude-sonnet-4-6"`, `"claude-haiku-4-5"`) are still present (no regression).
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_catalog.py -v` passes.

---

## Test Specification

No new test file — tests are in TASK-2719. Run existing catalog tests after implementation:

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/flows/dev_loop/test_catalog.py -v
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/select-model-dev-flow-ideation-model.spec.md` for full context.
2. **Verify the Codebase Contract** — read `catalog.py` around lines 232-246 and 507-541
   to confirm line numbers match before editing.
3. Make the three targeted edits to `catalog.py`:
   a. Append `"claude-fable-5-1"` and `"claude-fable-5"` to the `claude-code` `models` tuple.
   b. Append `"research_primary"` to the `claude-code` `roles` tuple.
   c. Add `"research_primary": [b.id for b in backends_for_role("research_primary")]` to
      the `"roles"` dict in `catalog_payload()`.
4. Run `pytest packages/ai-parrot/tests/flows/dev_loop/test_catalog.py -v` and confirm pass.
5. Commit with message: `feat(FEAT-494): add Fable models and research_primary role to catalog`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
