---
type: feature
base_branch: dev
---

# Feature Specification: select-model-dev-flow-ideation-model

**Feature ID**: FEAT-494
**Date**: 2026-09-02
**Author**: jesuslarag@gmail.com
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-486 / TASK-2656 made the dev-flow ideation seat model configurable
end-to-end (env key `DEV_FLOW_IDEATION_MODEL`, POST field `research_primary`,
flow wiring in `IdeationNode`). However, the UI surface for selecting a model
was never completed as a full operator-facing knob:

1. `"claude-fable-5-1"` / `"claude-fable-5"` are absent from the `claude-code`
   backend's curated `models` tuple in `catalog.py` (only a Bedrock cross-region
   id `"global.anthropic.claude-fable-5"` appears in the `nova` backend — a
   different, unrelated entry). Operators using the direct Anthropic API
   (`claude-code` backend) cannot discover Fable as a selectable option in the UI.

2. `_model_plan_payload` in `server_dev.py` (lines 374–391) serialises
   `research_primary` as a plain string (the current value) but does not include
   a `research_primary_models` list alongside it — unlike `pool_backends` and
   `review_primary_backends` which ARE exposed. The `/api/config` payload
   therefore has no named curated model list for the ideation seat.

3. `catalog_payload()` in `catalog.py` exposes roles `development`, `judge`,
   `primary_review`, `adversarial`, `research_partner` — but no
   `research_primary` role. Any UI or CLI surface that builds its picker from
   role lists sees the seat as invisible.

The result: an operator who wants Fable for ideation must set an env var before
startup (a deployment-level change) or craft a raw POST — both are
friction-heavy for a knob the system already fully supports end-to-end.
This is a presentation bug, not a design gap.

### Goals

- Add `"claude-fable-5-1"` and `"claude-fable-5"` to the `claude-code`
  backend's curated model list so they appear in the existing `dl-claude-models`
  datalist on the UI's research-primary seat automatically.
- Expose a `research_primary_models` key in the `/api/config` `defaults.model_plan`
  payload for any future UI / CLI surface.
- Add a `research_primary` role to `catalog_payload()` → `"roles"` so any
  surface querying `backends_for_role("research_primary")` gets a result.
- Cover the new keys with targeted tests in the existing test files.

### Non-Goals (explicitly out of scope)

- `model_plan.py` `DEFAULT_RESEARCH_PRIMARY` remains `"claude-opus-5"` — this
  is an exposure fix, not a default change. (Resolved in brainstorm.)
- `IdeationNode` dispatch logic is not touched — it already accepts any
  non-empty string as the model id.
- The Bedrock cross-region id `"global.anthropic.claude-fable-5"` in the `nova`
  backend (catalog.py line 342) is unrelated and left as-is.
- Research-partner seat logic (`resolve_research_partner_backend`) is
  unaffected.
- `server.py` (ops console) is not touched — FEAT-486 did not wire a
  `research_primary` seat there.
- `dev.html` requires no structural changes: the `dl-claude-models` datalist
  already reads from `modelOptions("claude-code", "")` which is derived from
  the catalog payload; adding Fable to the catalog entry is sufficient for the
  datalist to surface it automatically.

---

## 2. Architectural Design

### Overview

Three additive changes, each in one file, zero structural impact:

1. **`catalog.py` (`claude-code` backend)** — append `"claude-fable-5-1"` and
   `"claude-fable-5"` to the `models` tuple of the `claude-code`
   `BackendInfo`; add `"research_primary"` to its `roles` tuple; update
   `catalog_payload()` to emit `"research_primary"` in the `"roles"` dict
   (resolved via `backends_for_role("research_primary")`).

2. **`server_dev.py` — `_model_plan_payload`** — extend the returned dict with
   `"research_primary_models"`, derived from `llm_catalog.get_backend("claude-code").models`
   so the entry stays in one place and picks up future additions automatically.

3. **Tests** — extend `test_server_dev_model_plan.py` (FEAT-486 / TASK-2658's
   test file) and `test_catalog.py` with targeted assertions.

### Component Diagram

```
catalog.py (claude-code BackendInfo)
  └── models += ("claude-fable-5-1", "claude-fable-5")
  └── roles  += ("research_primary",)
  └── catalog_payload() roles["research_primary"] = backends_for_role("research_primary")

                        ↓ consumed by
server_dev.py _model_plan_payload()
  └── adds research_primary_models → /api/config defaults.model_plan

                        ↓ consumed by
dev.html modelOptions("claude-code", "")  ← already reads from catalog, no code change needed
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `catalog.py::BackendInfo` (claude-code entry, line 232–246) | modify | append Fable ids to `models`; add `research_primary` to `roles` |
| `catalog.py::catalog_payload()` (line 507) | modify | add `roles["research_primary"]` |
| `server_dev.py::_model_plan_payload()` (line 353) | modify | add `research_primary_models` key |
| `dev.html::dl-claude-models` datalist (line 1426) | no change | reads `modelOptions("claude-code", "")` from catalog automatically |
| `test_server_dev_model_plan.py` (FEAT-486 TASK-2658) | extend | new assertions |
| `test_catalog.py` | extend | new assertions |

---

## 3. Module Breakdown

### Module 1: catalog.py — Add Fable models and research_primary role
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py`
- **Responsibility**:
  1. Append `"claude-fable-5-1"` and `"claude-fable-5"` to the `claude-code`
     `BackendInfo.models` tuple (currently ends at `"claude-haiku-4-5"`,
     line ~243).
  2. Append `"research_primary"` to the `claude-code` `BackendInfo.roles`
     tuple (currently `("development", "judge", "primary_review", "planner")`,
     line ~245).
  3. In `catalog_payload()` (line 507), add
     `"research_primary": [b.id for b in backends_for_role("research_primary")]`
     to the returned `"roles"` dict.
- **Depends on**: nothing (no new imports)

### Module 2: server_dev.py — Add research_primary_models to _model_plan_payload
- **Path**: `examples/dev_loop/server_dev.py`
- **Responsibility**:
  - In `_model_plan_payload()` (line 353), add:
    ```python
    "research_primary_models": list(llm_catalog.get_backend("claude-code").models),
    ```
    This key is derived from the catalog entry so it stays in sync with
    Module 1 automatically without duplicating the list.
- **Depends on**: Module 1 (the catalog entry must exist before the helper
  is called; at import time `llm_catalog` is already a module-level import
  in `server_dev.py`).

### Module 3: Tests
- **Path**: `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py`
  and `packages/ai-parrot/tests/flows/dev_loop/test_catalog.py`
- **Responsibility**:
  - `test_server_dev_model_plan.py` — in `TestConfigPayload`:
    - Assert `"research_primary_models"` is present in `defaults.model_plan`
      from `/api/config`.
    - Assert `"claude-fable-5-1"` and `"claude-fable-5"` are both in that list.
    - Assert `"claude-opus-5"` is still present (no regression).
  - `test_catalog.py`:
    - Assert `"research_primary"` is in `catalog_payload()["roles"]`.
    - Assert `"claude-code"` is in `catalog_payload()["roles"]["research_primary"]`.
    - Assert `"claude-fable-5-1"` and `"claude-fable-5"` are in the `claude-code`
      backend's `models` list returned by `catalog_payload()["backends"]`.
- **Depends on**: Modules 1 and 2.

---

## 4. Test Specification

### Unit Tests

| Test | File | Description |
|---|---|---|
| `test_research_primary_models_in_config_payload` | `test_server_dev_model_plan.py` | `/api/config` `defaults.model_plan` includes `research_primary_models` key |
| `test_fable_in_research_primary_models` | `test_server_dev_model_plan.py` | `research_primary_models` contains `"claude-fable-5-1"` and `"claude-fable-5"` |
| `test_opus_still_in_research_primary_models` | `test_server_dev_model_plan.py` | Existing `"claude-opus-5"` is not dropped (regression guard) |
| `test_research_primary_role_in_catalog_payload` | `test_catalog.py` | `catalog_payload()["roles"]["research_primary"]` is non-empty |
| `test_claude_code_is_research_primary_backend` | `test_catalog.py` | `"claude-code"` in `catalog_payload()["roles"]["research_primary"]` |
| `test_fable_in_claude_code_models` | `test_catalog.py` | `"claude-fable-5-1"` and `"claude-fable-5"` in claude-code backend models |

### Integration Tests

None needed — the changes are additive (new keys in existing dicts, new entries
in existing tuples). The existing `TestConfigPayload` suite already covers
`/api/config` round-trip correctness; the new tests extend it.

### Test Data / Fixtures

No new fixtures. The existing `make_client` fixture from
`test_server_dev_model_plan.py` provides a fully wired test server; new tests
reuse it.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `"claude-fable-5-1"` and `"claude-fable-5"` are present in the
      `claude-code` backend's `models` tuple in `catalog.py`.
- [ ] `"research_primary"` is in the `claude-code` backend's `roles` tuple
      in `catalog.py`.
- [ ] `catalog_payload()["roles"]["research_primary"]` contains `"claude-code"`.
- [ ] `_model_plan_payload()` returns a `"research_primary_models"` key whose
      value is a list that includes `"claude-fable-5-1"` and `"claude-fable-5"`.
- [ ] The `/api/config` `defaults.model_plan.research_primary_models` field
      is present and includes Fable models (verified by new test).
- [ ] The existing `"claude-opus-5"` entry in the `claude-code` models list
      is NOT removed (no regression).
- [ ] `DEFAULT_RESEARCH_PRIMARY` in `model_plan.py` remains `"claude-opus-5"`
      (confirmed: the default does not change).
- [ ] All existing `TestConfigPayload`, `TestConsoleDefaultPlan`, and
      `TestPlanParsing` tests still pass.
- [ ] All new tests in Module 3 pass.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow/ -v` passes with no
      failures.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_catalog.py -v`
      passes with no failures.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every reference below is verified against the codebase as of 2026-09-02.

### Verified Imports

```python
# server_dev.py already imports llm_catalog at module level
from parrot.flows.dev_loop import catalog as llm_catalog  # verified: examples/dev_loop/server_dev.py (top of file)

# catalog.py
from parrot.flows.dev_loop.catalog import (
    BackendInfo,
    BACKENDS,
    catalog_payload,
    backends_for_role,
    get_backend,
)  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:544-558
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:214-227
class BackendInfo(NamedTuple):
    id: str                      # line 215
    label: str                   # line 220
    transport: str               # line 221
    model_env: Optional[str]     # line 222
    default_model: str           # line 223
    models: Tuple[str, ...]      # line 224
    requires: str                # line 225
    roles: Tuple[str, ...]       # line 226
    notes: str = ""              # line 227

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:232-246
# claude-code BackendInfo entry (current state — BEFORE this feature):
BackendInfo(
    id="claude-code",
    label="Claude Code",
    transport="cli",
    model_env=None,
    default_model="claude-sonnet-4-6",
    models=(
        "claude-opus-5",        # line 239
        "claude-sonnet-5",      # line 240
        "claude-sonnet-4-6",    # line 241
        "claude-haiku-4-5",     # line 242
        # ← "claude-fable-5-1" and "claude-fable-5" go here
    ),
    requires="`claude` CLI on $PATH, authenticated",
    roles=("development", "judge", "primary_review", "planner"),  # line 245
    # ← "research_primary" goes here
    notes="Write-enabled reviewer; also drives planner/synthesis/QA.",
)

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:507-541
def catalog_payload(config_getter: Optional[ConfigGetter] = None) -> Dict[str, Any]:
    # Returns dict with keys: "backends", "roles", "adversarial_backend",
    # "adversarial_model", "research_partner_backend", "default_judge_panel"
    # "roles" dict currently has: development, judge, primary_review, adversarial, research_partner
    # ← "research_primary" key missing (this feature adds it)

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:420-433
def backends_for_role(role: str) -> List[BackendInfo]:
    """Return every backend that may fill ``role``."""
    return [b for b in _BY_ID.values() if role in b.roles]  # line 433

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:409-417
def get_backend(backend_id: str) -> Optional[BackendInfo]:
    """Return the BackendInfo for ``backend_id``, or None."""
    return _BY_ID.get(backend_id)  # line 417

# examples/dev_loop/server_dev.py:353-391
def _model_plan_payload(plan: DevFlowModelPlan, *, review_pair_active: bool = True) -> dict[str, Any]:
    return {
        "review_pair_active": review_pair_active,               # line 375
        "research_primary": plan.research_primary,              # line 376
        "research_partner": plan.research_partner.model_dump(mode="json"),  # line 377
        "dev_agents": [...],                                    # line 378
        "review": {...},                                        # lines 379-385
        "pool_backends": list(supported_dev_pool_backends()),   # line 386
        "review_primary_backends": list(llm_catalog.PRIMARY_REVIEW_BACKENDS),  # line 387
        "partner_backends": [...],                              # lines 389-390
        # ← "research_primary_models" missing (this feature adds it)
    }
```

### Integration Points

| New Change | Connects To | Via | Verified At |
|---|---|---|---|
| Fable models in claude-code entry | `modelOptions("claude-code", "")` in dev.html | `catalog_payload()` → `backends` → `claude-code.models` | `catalog.py:460`, `dev.html:1370-1380` |
| `research_primary` role | `backends_for_role("research_primary")` | `b.id in b.roles` check | `catalog.py:433` |
| `research_primary_models` in `_model_plan_payload` | `/api/config` → `defaults.model_plan` | `_model_plan_payload()` return dict | `server_dev.py:374` |

### Does NOT Exist (Anti-Hallucination)

- ~~`catalog_payload()["roles"]["research_primary"]`~~ — does NOT exist yet; this feature adds it.
- ~~`_model_plan_payload()` returning `"research_primary_models"`~~ — does NOT exist yet.
- ~~`"claude-fable-5-1"` or `"claude-fable-5"` in `claude-code` backend `models`~~ — NOT present yet (only `"global.anthropic.claude-fable-5"` exists, in the `nova` Bedrock backend at line 342 — a different entry).
- ~~`llm_catalog.RESEARCH_PRIMARY_BACKENDS`~~ — does not exist; use `backends_for_role("research_primary")` instead.
- ~~`BackendInfo.research_primary_models`~~ — no such attribute; `BackendInfo.models` is the field.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- The `models` tuple on `BackendInfo` is **append-only** — never reorder or
  remove existing entries (other tests and deployments may depend on ordering).
  Add Fable ids at the end of the tuple, after `"claude-haiku-4-5"`.
- `catalog_payload()["roles"]` additions follow the existing pattern:
  `"<role>": [b.id for b in backends_for_role("<role>")]`.
- `_model_plan_payload()` additions follow the existing `llm_catalog.*`
  pattern already used by `pool_backends` and `partner_backends` in that
  function — derive from the catalog, not from a hardcoded list.

### Known Risks / Gotchas

- **Both Fable ids must be added**: `"claude-fable-5-1"` and `"claude-fable-5"`.
  The user confirmed both are valid API model ids; including both costs nothing
  and covers whichever id the installed Claude CLI version accepts.
- **Bedrock entry is unrelated**: `"global.anthropic.claude-fable-5"` in the
  `nova` backend (line 342) is the cross-region Bedrock id — a different
  deployment path. Do not confuse with or modify it.
- **`get_backend("claude-code")` returns `Optional[BackendInfo]`**: guard
  against `None` in `_model_plan_payload()` (e.g., `b = llm_catalog.get_backend("claude-code"); list(b.models) if b else []`), although in practice the `claude-code` entry is always present.
- **`_BY_ID` dict**: the module-level `_BY_ID` is built from `BACKENDS` at
  import time (plus the `RESEARCH_PARTNER_BACKENDS` update at line 404). Since
  `BackendInfo` is immutable (NamedTuple), any change to the `claude-code`
  entry in `BACKENDS` is automatically reflected in `_BY_ID` at next import.

### External Dependencies

No new dependencies. All changes are within existing files using existing imports.

---

## 8. Open Questions

- [x] What is the exact Claude CLI model id string for Fable? — *Resolved in brainstorm*: `"claude-fable-5-1"` and `"claude-fable-5"` (both confirmed by the user; include both).
- [x] Should Fable be the new default for the ideation seat, or remain a selectable alternative? — *Resolved in brainstorm*: keep `"claude-opus-5"` as default; Fable is an opt-in selectable alternative.

---

## Worktree Strategy

- **Isolation unit**: per-spec (all tasks run sequentially in one worktree).
- **Rationale**: the three modules touch separate files with no concurrent
  edit conflicts — sequential execution in a single worktree is sufficient
  and simpler.
- **Cross-feature dependencies**: none. This feature is purely additive on top
  of FEAT-486 / FEAT-482 work that is already merged to `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-02 | jesuslarag@gmail.com | Initial draft from proposal |
