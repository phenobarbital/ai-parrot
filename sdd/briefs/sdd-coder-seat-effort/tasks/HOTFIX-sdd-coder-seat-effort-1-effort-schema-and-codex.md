# HOTFIX-sdd-coder-seat-effort-1: Effort fields on RosterSeat / StrongModelIdentity + codex reasoning_effort

**Feature**: sdd-coder-seat-effort — Per-seat reasoning effort for the sdd-coder roster
**Spec**: `sdd/briefs/sdd-coder-seat-effort.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Operators want to set reasoning effort per sdd-coder seat in `.parrot/mcp-toolkits.yaml`
(`sdd-coder.kwargs.roster[]` and `complexity.strong_models[]`). This task adds the schema and the
codex command flag; task 2 resolves and applies the value at dispatch time. Today an `effort:` key
is silently ignored on a roster seat and crashes start-up on a strong model (`extra="forbid"`).

---

## Scope

- Define a shared alias in `sdd_coder/models.py`:
  `SeatEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]`.
- Add `effort: Optional[SeatEffort] = None` to `RosterSeat` (models.py:155). Extend the existing
  `_backend_required_for_mcp` model validator (or add a second `mode="after"` validator) so that
  `kind == "native"` with `effort` set logs a `logging.getLogger(__name__).warning(...)` saying the
  effort is not applied to native seats yet. It must NOT raise.
- Add `effort: Optional[SeatEffort] = None` to `StrongModelIdentity` (complexity_models.py:80),
  importing `SeatEffort` from `sdd_coder.models` **only if this creates no import cycle**; otherwise
  declare the identical `Literal` locally in `complexity_models.py` (check:
  `python -c "import parrot.flows.dev_loop.sdd_coder"`). Update the class docstring `Attributes:`.
- Add to `CodexCodeDispatchProfile` (models/codex.py:10):
  `reasoning_effort: Optional[Literal["minimal", "low", "medium", "high", "xhigh"]] = None`
  with a `description` stating it is emitted as `-c model_reasoning_effort=<x>` and that `None`
  keeps the operator's `~/.codex/config.toml` value.
- In `CodexCodeDispatcher._build_command` (dispatchers/codex.py:432), when
  `getattr(profile, "reasoning_effort", None)` is set, append `"-c", f"model_reasoning_effort={value}"`
  right after the existing `approval_policy` `-c` pair (line 463-464). When `None`, the command is
  byte-identical to today. Do not touch the review command builder (`codex.py:~526`).
- Tests (see Test Specification).

**NOT in scope**:
- Resolving/applying the effort in the engine (task 2).
- Native seats (`coder_prepare_native`, `sdd-worker.md`).
- `agent_builder.build_dispatcher` env defaults — unchanged.
- Templates / examples (task 2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `SeatEffort` alias; `RosterSeat.effort`; native-seat warning |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_models.py` | MODIFY | `StrongModelIdentity.effort` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py` | MODIFY | `CodexCodeDispatchProfile.reasoning_effort` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | MODIFY | emit `-c model_reasoning_effort=<x>` in `_build_command` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py` | MODIFY | schema tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py` | MODIFY | command tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # sdd_coder/models.py:11
from typing import Any, Dict, List, Literal, Optional, Tuple  # sdd_coder/models.py:8
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher  # test_codex_command_variants.py:10
from parrot.flows.dev_loop.models import CodexCodeDispatchProfile  # models/__init__.py:69
```

### Existing Signatures to Use
```python
# sdd_coder/models.py:155
class RosterSeat(BaseModel):
    label: str = Field(..., min_length=1, max_length=32)
    kind: SeatKind = "mcp"            # SeatKind = Literal["mcp", "native"] (line 30)
    backend: Optional[DevAgentBackend] = None
    model: str = ""
    fallback_model: str = ""
    @model_validator(mode="after")
    def _backend_required_for_mcp(self) -> "RosterSeat": ...   # line 168-181

# sdd_coder/complexity_models.py:80
class StrongModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_model: str
    backend: str
    model: str

# models/codex.py:10 — CodexCodeDispatchProfile(BaseModel): subagent, model, sandbox,
#   approval_policy, timeout_seconds, ignore_user_config, ignore_rules (line 31)

# dispatchers/codex.py:432
def _build_command(self, *, profile, cwd, schema_path, output_path, prompt) -> List[str]:
    # line 463-464: "-c", f"approval_policy={profile.approval_policy}",
    # line 470: if profile.ignore_user_config: ...
```

### Does NOT Exist
- ~~`RosterSeat.effort`~~, ~~`StrongModelIdentity.effort`~~, ~~`SeatEffort`~~ — this task creates them
- ~~`CodexCodeDispatchProfile.reasoning_effort`~~ — this task creates it
- ~~a `--effort` / `--reasoning-effort` flag on `codex exec`~~ — use `-c model_reasoning_effort=<x>`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterSeat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_models.py#StrongModelIdentity",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py#CodexCodeDispatchProfile",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher._build_command"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Default `None` everywhere: an existing roster/profile must validate and behave exactly as before.
- `ComplexityPolicy._validate_strong_models` (dedup on `(backend, model)`) stays unchanged — effort
  is not part of the identity key.
- Adding a field to `StrongModelIdentity` changes `policy_sha256` (`complexity_collectors.py:94`);
  that one-time cache invalidation is expected — mention it in the field docstring.
- Logging: module logger, never `print`.

---

## Acceptance Criteria

- [ ] `RosterSeat(label="a", backend="codex", model="m", effort="high").effort == "high"`; default is `None`.
- [ ] `RosterSeat(..., effort="ultra")` raises `ValidationError`.
- [ ] A native seat with `effort` validates and emits one WARNING (caplog); no warning without effort.
- [ ] `StrongModelIdentity(canonical_model="x", backend="codex", model="m", effort="high")` validates; unknown keys still raise.
- [ ] Codex `_build_command` with `reasoning_effort="high"` contains `-c model_reasoning_effort=high`; with `None` the command equals today's (existing tests unchanged and green).
- [ ] `ruff check` clean on all touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q`

---

## Test Specification

- `test_models.py`: `test_roster_seat_effort_default_none`, `test_roster_seat_effort_accepts_vocabulary`
  (parametrize all 7 values), `test_roster_seat_effort_rejects_unknown`,
  `test_native_seat_effort_warns` (caplog), `test_strong_model_identity_effort`.
- `test_codex_command_variants.py`: `test_dev_dispatch_emits_model_reasoning_effort` (asserts the
  `-c` pair is present and follows `approval_policy`), `test_dev_dispatch_without_effort_has_no_override`.

---

## Agent Instructions

1. Work in `.claude/worktrees/fix-sdd-coder-seat-effort-sdd-coder-seat-effort` — never on `dev`.
2. Read the brief `sdd/briefs/sdd-coder-seat-effort.brief.md`.
3. Verify the Codebase Contract lines before editing; if drifted, re-grep and fix the contract first.
4. Touch only the six listed files.
5. Run every Validation Command with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit code: `feat(sdd-coder): HOTFIX-sdd-coder-seat-effort-1 — effort fields + codex reasoning_effort`.
7. Update this Completion Note and the per-brief index status; commit the SDD state.

---

## Completion Note

<!-- Filled in by the implementer. -->
