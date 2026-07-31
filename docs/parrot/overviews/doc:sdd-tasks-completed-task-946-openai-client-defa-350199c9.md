---
type: Wiki Overview
title: 'TASK-946: Bump OpenAIClient defaults to gpt-5-mini + refresh model sets'
id: doc:sdd-tasks-completed-task-946-openai-client-defaults-and-model-sets-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After TASK-944 (catalog + helpers) and TASK-945 (warning chokepoint),
relates_to:
- concept: mod:parrot.clients.gpt
  rel: mentions
---

# TASK-946: Bump OpenAIClient defaults to gpt-5-mini + refresh model sets

**Feature**: FEAT-138 — OpenAI Model Deprecation Refresh
**Spec**: `sdd/specs/openai-model-deprecation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-944, TASK-945
**Assigned-to**: unassigned

---

## Context

After TASK-944 (catalog + helpers) and TASK-945 (warning chokepoint),
`OpenAIClient` still defaults to `OpenAIModel.GPT4_TURBO` (shutoff
2026-10-23) and references several deprecated members in its
`STRUCTURED_OUTPUT_COMPATIBLE_MODELS` and `RESPONSES_ONLY_MODELS` sets.
This task bumps every default and refreshes the sets so the client emits
zero deprecation warnings on its own out-of-the-box configuration.

Implements Modules 3 and 4 of §3.

---

## Scope

- Class attribute defaults on `OpenAIClient`:
  - `model: str = OpenAIModel.GPT5_MINI.value`
  - `_default_model: str = "gpt-5-mini"`
  - `_fallback_model: str = "gpt-4.1-nano"` (KEEP — still in upstream catalog)
  - `_lightweight_model: str = "gpt-4.1"` (KEEP)
- Method-signature default replacements: every
  `model: Union[str, OpenAIModel] = OpenAIModel.GPT4_TURBO` → `OpenAIModel.GPT5_MINI`.
- Method at line 1410 (`model: str = "gpt-4-turbo"`) →
  `model: str = OpenAIModel.GPT5_MINI.value`.
- `RESPONSES_ONLY_MODELS` (line 56–67): keep only IDs still in upstream
  catalog. Drop `o3-mini`, `o3-deep-research`, `o4-mini`,
  `o4-mini-deep-research`, `gpt-5.4-pro` (verify), `gpt-5-pro`,
  `gpt-5.2-pro`, `gpt-5-mini`. Add `o3`, `o3-pro` (the only reasoning
  models in the new catalog).
- `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` (line 69–85): replace deprecated
  members (`GPT_O4`, `GPT_4O`, `GPT5_CHAT`, `GPT5_PRO`, `GPT5_2`, `GPT5_1`)
  and add new ones (`GPT5_5`, `GPT5_5_PRO`, `GPT5_3_CHAT`, `GPT5_2_CHAT`,
  `GPT4O_MINI`, `GPT4_1_NANO`).
- `DEFAULT_STRUCTURED_OUTPUT_MODEL = OpenAIModel.GPT5_MINI.value`.
- The search-preview branch (lines 729–730) and `_resolve_deep_research_model`
  (lines 256–264): per **spec §8 Q1 still open**, leave the existing code
  in place but add a `warnings.warn(..., DeprecationWarning)` immediately
  before each call. The branch will be deleted in a follow-up once Q1 is
  answered. **DO NOT delete the branch in this task.**

**NOT in scope**:
- Adding the `_normalize_model` helper or `_warned` cache (TASK-945).
- Touching `handlers/`, `loaders/` (TASK-947 / TASK-948).
- Writing tests (TASK-949).
- Resolving the search/deep-research code path (spec §8 Q1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | Update class attributes, method signatures, and the two model-set constants. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present at packages/ai-parrot/src/parrot/clients/gpt.py:38
# After TASK-945 it reads:
from ..models.openai import (
    OpenAIModel,
    is_deprecated,
    get_shutoff_date,
    resolve_alias,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/gpt.py — current state (pre-task)
# RESPONSES_ONLY_MODELS                            line 56
RESPONSES_ONLY_MODELS = {
    "o3", "o3-pro", "o3-mini", "o3-deep-research",
    "o4-mini", "o4-mini-deep-research",
    "gpt-5.4-pro", "gpt-5-pro", "gpt-5.2-pro", "gpt-5-mini",
}

# STRUCTURED_OUTPUT_COMPATIBLE_MODELS              line 69
STRUCTURED_OUTPUT_COMPATIBLE_MODELS = {
    OpenAIModel.GPT_4O_MINI.value,   # NOTE: enum was renamed to GPT4O_MINI in TASK-944
    OpenAIModel.GPT_O4.value,        # REMOVED in TASK-944
    OpenAIModel.GPT_4O.value,        # REMOVED in TASK-944
    OpenAIModel.GPT4_1.value,
    OpenAIModel.GPT_4_1_MINI.value,  # NOTE: was renamed to GPT4_1_MINI in TASK-944
    OpenAIModel.GPT_4_1_NANO.value,  # NOTE: was renamed to GPT4_1_NANO in TASK-944
    OpenAIModel.GPT5_4.value,
    OpenAIModel.GPT5_4_MINI.value,
    OpenAIModel.GPT5_4_NANO.value,
    OpenAIModel.GPT5_MINI.value,
    OpenAIModel.GPT5.value,
    OpenAIModel.GPT5_2.value,        # REMOVED in TASK-944
    OpenAIModel.GPT5_1.value,        # REMOVED in TASK-944
    OpenAIModel.GPT5_CHAT.value,     # REMOVED in TASK-944
    OpenAIModel.GPT5_PRO.value,      # REMOVED in TASK-944
}

DEFAULT_STRUCTURED_OUTPUT_MODEL = OpenAIModel.GPT_4O_MINI.value   # line 87
```

### Target Sets (after this task)

```python
RESPONSES_ONLY_MODELS = {
    "o3",
    "o3-pro",
    # Q1 open: search-preview / deep-research are KEPT in the deprecated
    # branches but NOT listed here because the upstream catalog no longer
    # exposes them as Responses-API targets.
}

STRUCTURED_OUTPUT_COMPATIBLE_MODELS = {
    OpenAIModel.GPT5_5.value,
    OpenAIModel.GPT5_5_PRO.value,
    OpenAIModel.GPT5_4.value,
    OpenAIModel.GPT5_4_PRO.value,
    OpenAIModel.GPT5_4_MINI.value,
    OpenAIModel.GPT5_4_NANO.value,
    OpenAIModel.GPT5_3_CHAT.value,
    OpenAIModel.GPT5_2_CHAT.value,
    OpenAIModel.GPT5.value,
    OpenAIModel.GPT5_MINI.value,
    OpenAIModel.GPT5_NANO.value,
    OpenAIModel.GPT4_1.value,
    OpenAIModel.GPT4_1_MINI.value,
    OpenAIModel.GPT4_1_NANO.value,
    OpenAIModel.GPT4O_MINI.value,
}

DEFAULT_STRUCTURED_OUTPUT_MODEL = OpenAIModel.GPT5_MINI.value
```

### Method-Default Map (verify line numbers — code may have shifted)

Run before editing:

```bash
grep -n "OpenAIModel\.GPT4_TURBO\|model: str = \"gpt-4-turbo\"" \
  packages/ai-parrot/src/parrot/clients/gpt.py
```

Each match must be replaced as follows:

| Pattern | Replacement |
|---|---|
| `OpenAIModel.GPT4_TURBO` (any context except `_is_responses_only` / `_resolve_deep_research_model`) | `OpenAIModel.GPT5_MINI` |
| `OpenAIModel.GPT4_TURBO.value` (line 94 attribute) | `OpenAIModel.GPT5_MINI.value` |
| `model: str = "gpt-4-turbo"` (line 1410) | `model: str = OpenAIModel.GPT5_MINI.value` |
| `_default_model: str = 'gpt-4o-mini'` (line 96) | `_default_model: str = "gpt-5-mini"` |

### Search & Deep-Research Branches (preserve, but warn)

```python
# Lines 256–264 (current):
@staticmethod
def _resolve_deep_research_model(model_str: str) -> str:
    """Resolve the deep research model based on the requested model."""
    normalized = (model_str or "").strip()
    if normalized in {
        OpenAIModel.O4_MINI.value,            # REMOVED in TASK-944 → use literal
        OpenAIModel.O4_MINI_DEEP_RESEARCH.value,  # REMOVED in TASK-944 → use literal
    }:
        return OpenAIModel.O4_MINI_DEEP_RESEARCH.value   # REMOVED → literal
    return OpenAIModel.O3_DEEP_RESEARCH.value             # REMOVED → literal
```

After this task, replace removed enum references with raw strings AND
add a `warnings.warn` at the top of the method:

```python
@staticmethod
def _resolve_deep_research_model(model_str: str) -> str:
    """Resolve the deep research model. NOTE: spec §8 Q1 open — these IDs
    are deprecated upstream (shutoff 2026-07-23). Branch retained until
    the question is resolved."""
    warnings.warn(
        "Deep-research models are deprecated (shutoff 2026-07-23). "
        "Pending decision in spec §8 Q1.",
        DeprecationWarning,
        stacklevel=2,
    )
    normalized = (model_str or "").strip()
    if normalized in {"o4-mini", "o4-mini-deep-research"}:
        return "o4-mini-deep-research"
    return "o3-deep-research"
```

Apply the same `warnings.warn` pattern to the search-preview branch
(lines 729–730 area) — replace `OpenAIModel.GPT_4O_MINI_SEARCH.value` /
`OpenAIModel.GPT_4O_SEARCH.value` with raw strings and emit a
DeprecationWarning at branch entry.

### Does NOT Exist

- ~~`OpenAIModel.GPT4_TURBO`~~ — removed by TASK-944. Do NOT reintroduce.
- ~~`OpenAIModel.GPT_4O_MINI`~~ — renamed to `GPT4O_MINI` in TASK-944.
- ~~`OpenAIModel.GPT_4_1_MINI`~~ — renamed to `GPT4_1_MINI`.
- ~~`OpenAIModel.GPT_4_1_NANO`~~ — renamed to `GPT4_1_NANO`.
- ~~`OpenAIModel.GPT_O4`~~, ~~`OpenAIModel.GPT_4O`~~, ~~`OpenAIModel.GPT5_2`~~, ~~`OpenAIModel.GPT5_1`~~, ~~`OpenAIModel.GPT5_CHAT`~~, ~~`OpenAIModel.GPT5_PRO`~~, ~~`OpenAIModel.O4_MINI`~~, ~~`OpenAIModel.O4_MINI_DEEP_RESEARCH`~~, ~~`OpenAIModel.O3_DEEP_RESEARCH`~~, ~~`OpenAIModel.GPT_4O_MINI_SEARCH`~~, ~~`OpenAIModel.GPT_4O_SEARCH`~~ — all removed by TASK-944. Use raw strings via the `DEPRECATIONS` dict if needed.

---

## Implementation Notes

### Pattern to Follow

```python
class OpenAIClient(AbstractClient):
    client_type: str = 'openai'
    model: str = OpenAIModel.GPT5_MINI.value          # was GPT4_TURBO
    client_name: str = 'openai'
    _default_model: str = "gpt-5-mini"                # was 'gpt-4o-mini'
    _fallback_model: str = "gpt-4.1-nano"             # keep
    _lightweight_model: str = "gpt-4.1"               # keep

    # ...

    async def ask(
        self,
        ...,
        model: Union[str, OpenAIModel] = OpenAIModel.GPT5_MINI,   # was GPT4_1
        ...,
    ):
        ...
```

### Key Constraints

- Run the `grep` from the call-site map FIRST, then edit. Line numbers
  in this task file are guideposts — TASK-945 inserts code that may have
  shifted them.
- Do NOT rename methods. Only edit defaults, set bodies, and the two
  internal branches that reference removed enum members.
- After editing, repo-grep for `GPT4_TURBO` and confirm zero hits in
  `parrot/clients/gpt.py`.
- After editing, repo-grep for `GPT_4O_MINI` (with the underscore-O) and
  confirm zero hits — TASK-944 dropped that name.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/gpt.py` — all edits land here.
- TASK-944 completion note will list the final enum member names; consult
  it if there is doubt about renames.

---

## Acceptance Criteria

- [ ] `OpenAIClient.model` default is `OpenAIModel.GPT5_MINI.value`.
- [ ] `OpenAIClient._default_model` is `"gpt-5-mini"`.
- [ ] `_fallback_model` and `_lightweight_model` are unchanged.
- [ ] Zero occurrences of `GPT4_TURBO` in `parrot/clients/gpt.py`:
      `grep -c "GPT4_TURBO" packages/ai-parrot/src/parrot/clients/gpt.py` → `0`.
- [ ] Zero occurrences of `"gpt-4-turbo"` (string literal) in
      `parrot/clients/gpt.py`.
- [ ] `RESPONSES_ONLY_MODELS == {"o3", "o3-pro"}`.
- [ ] `DEFAULT_STRUCTURED_OUTPUT_MODEL == "gpt-5-mini"`.
- [ ] `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` contains exactly the 15
      members listed in the contract.
- [ ] `_resolve_deep_research_model` and the search-preview branch emit
      a `DeprecationWarning` at entry; branch logic still functions.
- [ ] Module imports cleanly:
      `python -c "from parrot.clients.gpt import OpenAIClient, RESPONSES_ONLY_MODELS, STRUCTURED_OUTPUT_COMPATIBLE_MODELS, DEFAULT_STRUCTURED_OUTPUT_MODEL"`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/gpt.py`.

---

## Test Specification

Tests live in TASK-949. Smoke check:

```bash
source .venv/bin/activate
python -c "
from parrot.clients.gpt import (
    OpenAIClient, RESPONSES_ONLY_MODELS,
    STRUCTURED_OUTPUT_COMPATIBLE_MODELS, DEFAULT_STRUCTURED_OUTPUT_MODEL,
)
assert OpenAIClient.model == 'gpt-5-mini', OpenAIClient.model
assert OpenAIClient._default_model == 'gpt-5-mini'
assert RESPONSES_ONLY_MODELS == {'o3', 'o3-pro'}, RESPONSES_ONLY_MODELS
assert DEFAULT_STRUCTURED_OUTPUT_MODEL == 'gpt-5-mini'
assert 'gpt-5-mini' in STRUCTURED_OUTPUT_COMPATIBLE_MODELS
print('OK')
"
```

---

## Agent Instructions

1. Verify TASK-944 and TASK-945 are in `sdd/tasks/completed/`.
2. Re-grep call sites; line numbers will have shifted.
3. Update `.index.json` → `"in-progress"`.
4. Implement; run smoke check.
5. Move file to `sdd/tasks/completed/`, update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
