# TASK-5350: Align `GoogleCodingDispatchProfile` mode/effort literals with agy

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. `agy --help` (1.4.12 and 1.5.3, re-checked 2026-11-08) accepts
`--mode (accept-edits, auto, plan)` and `--effort (low|medium|high|xhigh|max)`, and
`parrot.flows.dev_loop.sdd_coder.models.SeatEffort` already carries `"xhigh"`/`"max"`. The dev-loop profile
rejects `mode="auto"` and `effort="xhigh"`/`"max"`.

**Spec drift (corrected here):** spec §3 M4/§6 place the class at line 44 with fields `binary_path`,
`mode: Optional[...] = None`, `effort: ... = "high"`, `skip_permissions`. The real class is at line 15:
`mode: Literal["accept-edits", "plan"] = "accept-edits"` and `effort: Optional[Literal["low", "medium", "high"]] = None`.
The spec's intent is "the default stays" — so widen the literals and **keep the current defaults**
(`mode="accept-edits"`, `effort=None`). Changing them would change every dispatcher command line
(`_build_command` emits `--mode` whenever `mode` is set), which the spec does not ask for.

---

## Scope

- Widen `mode` to `Literal["accept-edits", "auto", "plan"]` and `effort` to
  `Optional[Literal["low", "medium", "high", "xhigh", "max"]]`, defaults unchanged.
- Test that the profile accepts the new values, rejects an unknown one, and that `_build_command` passes them
  through as `--mode auto` / `--effort xhigh`.

**NOT in scope**: making `"auto"` a default anywhere (account-gated, spec §1); the launcher (TASK-5351…5354).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py` | MODIFY | widened `mode`/`effort` literals |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | MODIFY | profile + command-line tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09).

### Verified Imports
```python
from parrot.flows.dev_loop import GoogleCodingDispatchProfile, GoogleCodingDispatcher  # test file lines 14-22
from parrot.flows.dev_loop.sdd_coder.models import SeatEffort  # models.py:31 — Literal["none","minimal","low","medium","high","xhigh","max"]
from pydantic import ValidationError                            # pydantic v2, already a dependency
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py
class GoogleCodingDispatchProfile(BaseModel):                                   # line 15
    subagent: Literal["sdd-worker", ..., "sdd-coder"] = "sdd-worker"            # line 21
    model: str = "auto"                                                         # line 24
    agent: Optional[str] = None                                                 # line 25
    effort: Optional[Literal["low", "medium", "high"]] = None                   # line 26
    mode: Literal["accept-edits", "plan"] = "accept-edits"                      # line 27
    dangerously_skip_permissions: bool = True                                   # line 28
    sandbox: bool = True                                                        # line 29
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)                  # line 30

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py
class GoogleCodingDispatcher:
    def _build_command(self, *, profile: GoogleCodingDispatchProfile, schema_path: str, prompt: str) -> List[str]:  # line 294
        # line 315: if profile.mode: cmd.extend(["--mode", profile.mode])
        # line 321: if profile.effort: cmd.extend(["--effort", profile.effort])

# packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py
def dispatcher(monkeypatch):  # line 82 fixture — a GoogleCodingDispatcher with faked redis
```

### Does NOT Exist
- ~~`GoogleCodingDispatchProfile.binary_path` / `.skip_permissions`~~ — the spec §6 listing is stale; the fields are `dangerously_skip_permissions`, `sandbox`, …
- ~~A profile default of `mode=None`~~ — the current default is `"accept-edits"`; keep it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py#GoogleCodingDispatchProfile",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher._build_command"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Replace the two field lines — *why*: the only model change the spec asks for.
2. Add the tests at the end of the test file — *why*: AC "accepts mode=auto and effort xhigh/max".

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/google_coding.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    effort: Optional\[Literal\["low", "medium", "high"\]\] = None' google_coding.py) — line 26
# occurrences: 1 (verified: grep -c '    mode: Literal\["accept-edits", "plan"\] = "accept-edits"' google_coding.py) — line 27
# REPLACE lines 26-27 with:
    effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = None
    mode: Literal["accept-edits", "auto", "plan"] = "accept-edits"
```
**Why**: same values as `agy --help` and `SeatEffort` (minus `none`/`minimal`, which agy rejects); defaults
unchanged so no existing dispatch changes. `"auto"` is an opt-in: agy only warns on accounts without it.

### `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` (MODIFY)
```python
# AFTER — append at end of file
@pytest.mark.parametrize("mode", ["accept-edits", "auto", "plan"])
@pytest.mark.parametrize("effort", [None, "low", "medium", "high", "xhigh", "max"])
def test_google_coding_profile_auto_and_xhigh(mode: str, effort: str | None) -> None:
    profile = GoogleCodingDispatchProfile(mode=mode, effort=effort)
    assert (profile.mode, profile.effort) == (mode, effort)


def test_google_coding_profile_defaults_unchanged() -> None:
    profile = GoogleCodingDispatchProfile()
    assert profile.mode == "accept-edits" and profile.effort is None


# FILL IN tests:
#  - unknown values (mode="yolo", effort="ultra", effort="minimal") raise pydantic.ValidationError
#  - dispatcher._build_command(profile=GoogleCodingDispatchProfile(mode="auto", effort="xhigh"), schema_path="s.json",
#    prompt="p") contains the adjacent pairs ["--mode", "auto"] and ["--effort", "xhigh"]
```

### FILL IN checklist
- [ ] validation-error and `_build_command` pass-through tests

---

## Acceptance Criteria

- [ ] `GoogleCodingDispatchProfile` accepts `mode="auto"` and `effort` `"xhigh"`/`"max"`; unknown values are rejected.
- [ ] Defaults stay `mode="accept-edits"`, `effort=None`; all existing dispatcher tests pass.
- [ ] `ruff check` is clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5350 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
