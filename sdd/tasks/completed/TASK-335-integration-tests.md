# TASK-335: Integration Tests for Prompt Layer System

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-329, TASK-330, TASK-331, TASK-332
**Assigned-to**: —

---

## Context

> Integration tests that verify the prompt layer system works correctly when wired into actual bot classes (AbstractBot, VoiceBot, PandasAgent) and BotManager. Includes comparison tests between legacy and layer-based outputs.
> Implements spec Section 10 (Integration Tests + Comparison Tests).

---

## Scope

- Create test files in `tests/bots/prompts/`:
  - `test_abstractbot_prompt_integration.py` — AbstractBot with/without PromptBuilder
  - `test_voicebot_prompt.py` — VoiceBot voice preset integration
  - `test_pandasagent_prompt.py` — PandasAgent with dataframe layer
  - `test_yaml_prompt_config.py` — BotManager YAML prompt config parsing
- Comparison tests:
  - For each migrated bot type, generate both legacy and layer-based outputs with identical inputs
  - Verify semantic equivalence: same sections present, same variable values, correct ordering
  - These tests ensure migration doesn't change bot behavior
- Test scenarios:
  - Bot with full context (all layers active)
  - Bot with minimal context (most layers conditional-off)
  - Bot with custom layers added at runtime
  - YAML-defined bot with prompt config

**NOT in scope**: Performance/load tests, production DB tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/bots/prompts/test_abstractbot_prompt_integration.py` | CREATE | AbstractBot integration tests |
| `tests/bots/prompts/test_voicebot_prompt.py` | CREATE | VoiceBot integration tests |
| `tests/bots/prompts/test_pandasagent_prompt.py` | CREATE | PandasAgent integration tests |
| `tests/bots/prompts/test_yaml_prompt_config.py` | CREATE | BotManager YAML config tests |
| `tests/bots/prompts/test_comparison.py` | CREATE | Legacy vs layer output comparison tests |

---

## Implementation Notes

- Use mocks for LLM clients and database connections — these are prompt assembly tests, not LLM tests.
- For comparison tests, create a bot using legacy path and another using layer path with same config, compare outputs structurally.
- Use `pytest.mark.asyncio` for async test functions.
- Mock `dynamic_values` module to return predictable values.

---

## Acceptance Criteria

- [ ] All integration tests pass: `pytest tests/bots/prompts/test_*integration* tests/bots/prompts/test_comparison* -v`
- [ ] AbstractBot legacy path produces identical output as before migration.
- [ ] AbstractBot layer path produces structurally equivalent output.
- [ ] VoiceBot prompt includes voice-specific behavior.
- [ ] PandasAgent prompt includes dataframe context when schemas present.
- [ ] BotManager correctly parses YAML prompt config.
- [ ] Comparison tests verify semantic equivalence between legacy and layer outputs.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Section 10.
2. **Read the implementations** of TASK-329 through TASK-332.
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
4. **Implement** the test suite following the scope above.
5. **Run tests**: `pytest tests/bots/prompts/ -v`
6. **Verify** all tests pass.
7. **Move this file** to `sdd/tasks/completed/TASK-335-integration-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
