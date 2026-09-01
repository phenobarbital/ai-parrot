# TASK-2656: Configurable ideation primary model (remove hardcoded claude-sonnet-4-6)

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2651, TASK-2652
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, primary-model half (goal G6). `IdeationNode` hardcodes
`model="claude-sonnet-4-6"` in its dispatch profile. This task makes the
primary research seat configurable, defaulting to `claude-opus-5`, sharing
the `DEV_FLOW_IDEATION_MODEL` seam that FEAT-482 also plans to introduce.

---

## Scope

- Add an optional `model: str | None = None` constructor parameter to
  `IdeationNode` (keyword-only, like its siblings); resolution order:
  explicit arg → `DEV_FLOW_IDEATION_MODEL` conf key → `"claude-opus-5"`.
- Replace the literal at `dev_flow/nodes/ideation.py:338` with the
  resolved value.
- Thread `model_plan.research_primary` → the `IdeationNode` factory in
  `dev_flow/factories.py:115-125`.
- **Coordination check**: FEAT-482 (in progress upstream) also touches
  `ideation.py` and plans the same conf key. BEFORE implementing, grep for
  `DEV_FLOW_IDEATION_MODEL` in `conf.py` and for a `model`/`coordinator`
  kwarg on `IdeationNode` — if FEAT-482 already landed either, REUSE its
  seam (adjust only defaults/threading) instead of adding a duplicate.
- Unit tests: default resolution, plan override, conf override.

**NOT in scope**: the research partner passthrough (TASK-2657), any other
node's model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py` | MODIFY | model param + literal removal |
| `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py` | MODIFY | thread research_primary |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEV_FLOW_IDEATION_MODEL` (if absent) |
| `packages/ai-parrot/tests/flows/dev_flow/test_ideation_model.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py (verified 2026-09-01)
class IdeationNode:  # :91
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 wiki_search: DevLoopWikiSearch | None = None,
                 ideation_max_rounds: int | None = None, name: str = "ideation"): ...  # :105-116
# Dispatch profile built at :322-339; model="claude-sonnet-4-6" literal at :338
# system_prompt_override=load_subagent_definition("sdd-ideation"), permission_mode="acceptEdits"

# dev_flow/factories.py:115-125 — the IdeationNode factory entry to extend
# conf.py:966 DEV_FLOW_GATE_TTL_QUESTIONS, :972 DEV_FLOW_IDEATION_MAX_ROUNDS — key-style precedent
```

### Does NOT Exist
- ~~`DEV_FLOW_IDEATION_MODEL` in conf.py~~ — absent as of 2026-09-01 (FEAT-482 may add it: GREP FIRST, reuse if present).
- ~~`IdeationNode(model=...)` / `IdeationNode(coordinator=...)`~~ — absent as of 2026-09-01 (same caveat).
- ~~Model params on other nodes~~ — out of scope; do not add.

---

## Implementation Notes

- Bedrock model-name nuance: the dispatch path creates the client via
  `LLMFactory.create(f"claude-agent:{profile.model}")`
  (`dev_loop/dispatchers/claude.py:230`) — `claude-opus-5` must be a model
  id the Claude CLI accepts (it is listed for the claude-code backend,
  `catalog.py:139`).
- Keep the change additive and minimal — FEAT-482 will edit the same file.

---

## Acceptance Criteria

- [ ] Literal `"claude-sonnet-4-6"` gone from `ideation.py` dispatch profile
- [ ] Default resolves to `claude-opus-5`; plan and conf overrides work
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_ideation_model.py -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_ideation_model.py
class TestIdeationModel:
    def test_default_is_opus_5(self): ...
    def test_plan_override(self): ...
    def test_conf_override(self, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — TASK-2651/2652 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** first — ESPECIALLY the FEAT-482 coordination greps
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`;
8. **Update index** → `"done"`; 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
