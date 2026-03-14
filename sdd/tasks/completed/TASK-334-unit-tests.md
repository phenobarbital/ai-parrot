# TASK-334: Unit Tests for Prompt Layer System

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-325, TASK-326, TASK-327, TASK-328
**Assigned-to**: —

---

## Context

> Comprehensive unit test suite for the core prompt layer modules: layers.py, builder.py, presets.py, and domain_layers.py. Validates all rendering, composition, mutation, and preset behaviors.
> Implements spec Section 10 (Unit Tests).

---

## Scope

- Create/expand test files in `tests/bots/prompts/`:
  - `test_layers.py` — PromptLayer rendering, conditions, partial_render, priority ordering
  - `test_builder.py` — PromptBuilder factory methods, mutation API, two-phase rendering, single-phase fallback, clone
  - `test_presets.py` — preset registration, retrieval, independence
  - `test_domain_layers.py` — domain layer rendering, conditions, priority ordering, lookup
- Test edge cases:
  - Empty context values
  - Missing required vars (safe_substitute handles gracefully)
  - Layer with condition that raises (should it propagate?)
  - Builder with no layers
  - Builder with all layers having conditions that return False
  - `partial_render` with overlapping var names across phases

**NOT in scope**: Integration tests with AbstractBot/VoiceBot/PandasAgent (that's TASK-335).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/bots/prompts/test_layers.py` | CREATE | Unit tests for PromptLayer and built-in layers |
| `tests/bots/prompts/test_builder.py` | CREATE | Unit tests for PromptBuilder |
| `tests/bots/prompts/test_presets.py` | CREATE | Unit tests for presets registry |
| `tests/bots/prompts/test_domain_layers.py` | CREATE | Unit tests for domain-specific layers |
| `tests/bots/prompts/__init__.py` | CREATE | Empty init for test package |
| `tests/bots/prompts/conftest.py` | CREATE | Shared fixtures (sample contexts, custom layers) |

---

## Implementation Notes

- Use pytest with standard assertions (no unittest.TestCase).
- Create shared fixtures in `conftest.py` for common context dicts (full context, minimal context, empty context).
- Test the spec's example scenarios from Section 10.
- Verify XML tag structure in rendered output (presence of tags, correct nesting).
- Test that `build()` produces layers in priority order.

---

## Acceptance Criteria

- [ ] All unit tests pass: `pytest tests/bots/prompts/ -v`
- [ ] Coverage for: render, partial_render, conditions, priorities, mutations, cloning, presets, domain layers.
- [ ] Edge cases covered: empty contexts, all-false conditions, no layers.
- [ ] Test file structure is clean and well-organized with descriptive test names.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Section 10.
2. **Read the implementation** of TASK-325 through TASK-328 (layers.py, builder.py, presets.py, domain_layers.py).
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
4. **Implement** the test suite following the scope above.
5. **Run tests**: `pytest tests/bots/prompts/ -v`
6. **Verify** all tests pass.
7. **Move this file** to `sdd/tasks/completed/TASK-334-unit-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
