# TASK-3472: Unattended `/sdd-spec` callers pass `--no-interview`

**Feature**: FEAT-577 — `/sdd-spec` Intake Mode — Interview-Driven Spec Creation
**Spec**: `sdd/specs/sdd-feature-specification.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3471
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6** and the matching guard in **Module 7** (G11).
`sdd-research` invokes `/sdd-spec <slug> --type … --base-branch …` with no `--`
notes and no exploration doc. That matches the intake auto-trigger exactly, so
an unattended dev-loop run would try to interview a human who isn't there.
Every unattended invocation gets an explicit `--no-interview`. Both agents are
dual-sourced: `.claude/agents/<name>.md` and
`packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/<name>.md` must
stay byte-identical (`packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py`).

---

## Scope

- Append ` --no-interview` to both `/sdd-spec` lines in `sdd-research.md`
  (both copies). Keep the trailing `# kind == …` comments aligned.
- Change `sdd-planner.md` line 46 (both copies) so the invocation reads ``/sdd-spec <slug> --no-interview``.
- Add `test_unattended_callers_pass_no_interview` to `tests/sdd_scripts/test_command_contracts.py`.

**NOT in scope**: `sdd-autopilot.md` / `sdd-ideation.md`. They only mention `/sdd-spec` in prose and never invoke it (spec §6).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-research.md` | MODIFY | `--no-interview` on lines 75–76 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | MODIFY | identical edit |
| `.claude/agents/sdd-planner.md` | MODIFY | `--no-interview` on line 46 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-planner.md` | MODIFY | identical edit |
| `tests/sdd_scripts/test_command_contracts.py` | MODIFY | add the guard test |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (each occurs exactly once per file; both copies identical)
- `sdd-research.md:75` `   /sdd-spec <slug> --type hotfix --base-branch main       # kind == "bug"`
- `sdd-research.md:76` `   /sdd-spec <slug> --type feature --base-branch dev        # kind == "enhancement" | "new_feature"`
- `sdd-planner.md:46` ``   ``"brainstorm"`` or ``"proposal"``, run ``/sdd-spec`` to scaffold and``
- `tests/sdd_scripts/test_command_contracts.py`: `_REPO_ROOT` (module level), `_read(rel: str) -> str` (skips when missing, ~`:35-39`), existing tests `test_no_command_hand_rolls_a_worktree` `:43`, `test_every_creator_calls_ensure_worktree` `:51`, `test_no_legacy_naming_template_remains` `:58`.

### Does NOT Exist
- ~~A `--no-interview` flag before TASK-3471~~ — this task depends on it.
- ~~`/sdd-spec` invocations in `sdd-autopilot.md` / `sdd-ideation.md`~~ — prose only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/agents/sdd-research.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-planner.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-planner.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_command_contracts.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit `.claude/agents/sdd-research.md` lines 75–76, then copy the whole file
   over the `_subagent_data` twin. *Why*: the byte-parity test compares full
   bodies.
2. Same for `sdd-planner.md` line 46.
3. Add the guard test. *Why*: a future prompt edit must not silently drop the flag (spec §7 Known Risks).

### `.claude/agents/sdd-research.md` (MODIFY) — and its `_subagent_data` twin
```text
# occurrences: 1 (verified: grep -cF '/sdd-spec <slug> --type hotfix --base-branch main' .claude/agents/sdd-research.md) — line 75
# REPLACE lines 75-76 with:
   /sdd-spec <slug> --type hotfix --base-branch main --no-interview       # kind == "bug"
   /sdd-spec <slug> --type feature --base-branch dev --no-interview        # kind == "enhancement" | "new_feature"
```

### `.claude/agents/sdd-planner.md` (MODIFY) — and its `_subagent_data` twin
```text
# occurrences: 1 (verified: grep -cF 'run ``/sdd-spec`` to scaffold and' .claude/agents/sdd-planner.md) — line 46
# REPLACE the substring  run ``/sdd-spec`` to scaffold and
#                  with  run ``/sdd-spec <slug> --no-interview`` to scaffold and
# FILL IN: re-wrap the paragraph only if the line exceeds its neighbours' width — bounded by byte parity (edit the twin identically)
```

### `tests/sdd_scripts/test_command_contracts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def test_no_legacy_naming_template_remains' tests/sdd_scripts/test_command_contracts.py)
# BEFORE — insert above `def test_no_legacy_naming_template_remains() -> None:` (verified: :58)

#: Agent prompts that run /sdd-spec unattended — they must never enter intake mode (FEAT-577).
_UNATTENDED_SPEC_CALLERS = (
    ".claude/agents/sdd-research.md",
    ".claude/agents/sdd-planner.md",
    "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md",
    "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-planner.md",
)


@pytest.mark.parametrize("rel", _UNATTENDED_SPEC_CALLERS)
def test_unattended_callers_pass_no_interview(rel: str) -> None:
    """Every /sdd-spec invocation in an unattended agent carries --no-interview (FEAT-577)."""
    # FILL IN: collect lines containing "/sdd-spec " followed by "<slug>" (the invocation shape); assert the
    # list is non-empty and every such line contains "--no-interview" — bounded by spec G11 (prose mentions
    # like "``/sdd-spec``" without "<slug>" are not invocations)
```

### FILL IN checklist
- [ ] planner paragraph wrap (only if needed)
- [ ] `test_unattended_callers_pass_no_interview` body

---

## Acceptance Criteria

- [ ] Every unattended `/sdd-spec` invocation carries `--no-interview` (4 files)
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` passes
- [ ] `tests/sdd_scripts/test_command_contracts.py` passes

---

## Validation Commands

- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`

---

## Test Specification

See the blueprint test block.

---

## Agent Instructions

1. Confirm TASK-3471 is done (`--no-interview` is documented in `/sdd-spec`).
2. Implement; run the Validation Commands. In a worktree, prefix with `PYTHONPATH=packages/ai-parrot/src`, because the parity test reads the `_subagent_data` copy via `importlib.resources`.
3. Move this file to `sdd/tasks/completed/` and set the index status to `done`.

---

## Completion Note

Added `--no-interview` to every `/sdd-spec` invocation line in
`.claude/agents/sdd-research.md` / `_subagent_data/sdd-research.md` (both
copies, both flow-type lines) and `.claude/agents/sdd-planner.md` /
`_subagent_data/sdd-planner.md`. Added
`test_unattended_callers_pass_no_interview` to
`tests/sdd_scripts/test_command_contracts.py`. Merged cleanly (outcome:
merged, no lint changes needed).

Merge-tier `select_tests` escalated the full `packages/ai-parrot/tests/flows/dev_loop`
suite (core escalation triggered by the `.claude/agents/*` targets): 2243
passed, 16 failed. Verified all 16 are pre-existing/environmental, not
caused by this task — FEAT-577 touches zero files under
`packages/*/src/parrot/`: (a) `test_no_credentials_skips_without_constructing_client`
fails identically on `dev` HEAD directly (missing `NovaClient` attribute on
`parrot.flows.dev_loop.dispatchers.nova`, unrelated to intake/no-interview);
(b) the remaining dev_loop failures are a worktree-environment artifact
(`ModuleNotFoundError: No module named 'parrot.utils.types'` — a compiled
extension module absent from this worktree, a documented pre-existing
worktree limitation). `tests/sdd_scripts/*` (65 tests) all passed.

Seat: mistral (nova) · Backend: nova · Model: mistral.devstral-2-123b · Attempts: 1 · Duration: 185.9s · Tokens: 471503/7360
