# TASK-5137: conf: add DEFAULT_LLM, delete dead DEFAULT_LLM_MODEL_NAME

**Feature**: FEAT-796 — Per-Component LLM Defaults
**Spec**: `sdd/specs/per-component-llm-defaults.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (G4). `conf.py:248` defines `DEFAULT_LLM_MODEL_NAME` (env `LLM_MODEL_NAME`), which nothing in `packages/*/src` reads. Replace it with the opt-in, provider-qualified global `DEFAULT_LLM` that the resolver (TASK-5138) cascades to.

---

## Scope

- Replace `conf.py:248` with `DEFAULT_LLM: str | None = config.get("DEFAULT_LLM", fallback=None)` plus a comment explaining the `provider:model` format.
- Write tests asserting `DEFAULT_LLM` defaults to `None` and `DEFAULT_LLM_MODEL_NAME` no longer exists.

**NOT in scope**: `DEFAULT_LLM_MODEL` / `LLM_MODEL` at `conf.py:456` — live, must not change. The resolver itself (TASK-5138).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Replace dead knob with DEFAULT_LLM |
| `packages/ai-parrot/tests/unit/test_conf_default_llm.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, names and signatures. Verify anything not listed
> before using it. Anchors verified at dev `e179aba02f`.

### Verified Imports
```python
from navconfig import config  # verified: parrot/conf.py:6
```

### Existing Signatures to Use
```python
# parrot/conf.py
DEFAULT_LLM_MODEL_NAME = config.get("LLM_MODEL_NAME", fallback="gemini-2.5-pro")  # line 248 — zero readers
DEFAULT_LLM_MODEL = config.get("LLM_MODEL", fallback="gemini-flash-latest")  # line 456 — LIVE, do not touch
```

### Does NOT Exist
- ~~any reader of `DEFAULT_LLM_MODEL_NAME`~~ — none in `packages/*/src` (hard cut accepted, spec §8)
- ~~`conf.DEFAULT_LLM`~~ — created by this task

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_conf_default_llm.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `DEFAULT_LLM` must NOT fall back to `LLM_MODEL` — that would move crews/experts for deployments that set `LLM_MODEL` for chatbots (spec §7).
- Tests: navconfig reads env at import; assert on the module attribute, and for the default use `config.get('DEFAULT_LLM', fallback=None)` semantics, not a reload.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path the blueprint fixes.

### Steps (in order)
1. Replace the line at `conf.py:248` (keep the `# LLM Model` comment above it) — *why*: G4 + new global.
2. Write the test file — *why*: AC7 needs proof the dead knob is gone.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'DEFAULT_LLM_MODEL_NAME = config.get("LLM_MODEL_NAME", fallback="gemini-2.5-pro")' conf.py)
# REPLACE line 248 with:
# Opt-in global default for per-component LLM selection (FEAT-796), "provider:model".
# Unset -> each component keeps its builtin default. Independent of LLM_MODEL below.
DEFAULT_LLM: str | None = config.get("DEFAULT_LLM", fallback=None)
```
**Why**: the old name had no readers; the new knob is provider-qualified so the provider stops being hardcoded.

### `packages/ai-parrot/tests/unit/test_conf_default_llm.py` (CREATE)
```python
"""FEAT-796 TASK-5137 — DEFAULT_LLM replaces the dead DEFAULT_LLM_MODEL_NAME."""
from parrot import conf


def test_default_llm_model_name_removed() -> None:
    assert not hasattr(conf, "DEFAULT_LLM_MODEL_NAME")


def test_default_llm_attribute_exists() -> None:
    assert hasattr(conf, "DEFAULT_LLM")
    # FILL IN: when DEFAULT_LLM env is unset in the test env, assert conf.DEFAULT_LLM is None
```

### FILL IN checklist
- [ ] `test_default_llm_attribute_exists` — env-independent None assertion; bounded by AC1

---

## Acceptance Criteria

- [ ] `parrot.conf.DEFAULT_LLM` exists, default `None`
- [ ] `parrot.conf.DEFAULT_LLM_MODEL_NAME` no longer exists
- [ ] `DEFAULT_LLM_MODEL` unchanged
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_conf_default_llm.py -q`

---

## Test Specification

```python
# see blueprint
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug per-component-llm-defaults --feature-id FEAT-796`), never on `dev`.
2. Read the spec; confirm every `Depends-on` task is `done` in `sdd/tasks/index/per-component-llm-defaults.json`.
3. Verify the Codebase Contract (re-run the `grep -c` of every anchor) before writing code.
4. Mark the task `in-progress` in the index and commit only that file.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH` set to the changed packages' absolute `src` dirs; `ruff check` the touched files.
7. Commit only the listed files; close with `parrot sdd task close TASK-5137 per-component-llm-defaults verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
