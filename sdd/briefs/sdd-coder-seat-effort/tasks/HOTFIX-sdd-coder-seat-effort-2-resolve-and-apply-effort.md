# HOTFIX-sdd-coder-seat-effort-2: Resolve seat/strong-model effort and apply it to the dispatch profile

**Feature**: sdd-coder-seat-effort — Per-seat reasoning effort for the sdd-coder roster
**Spec**: `sdd/briefs/sdd-coder-seat-effort.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-sdd-coder-seat-effort-1
**Assigned-to**: unassigned

---

## Context

Task 1 added `RosterSeat.effort`, `StrongModelIdentity.effort` and
`CodexCodeDispatchProfile.reasoning_effort`. This task decides, per attempt, which effort applies
and writes it into the backend-specific profile field built by `build_dispatcher`. The mapping lives
in a new pure module so it is unit-testable with the real profile classes (the engine test fakes
always return `LLMCodeDispatchProfile`).

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/effort.py` with:
  - `EFFORT_FIELD_BY_BACKEND: Dict[str, str] = {"zai": "reasoning_effort", "moonshot": "reasoning_effort",
    "google-compat": "reasoning_effort", "google_coding": "effort", "codex": "reasoning_effort"}`.
  - `resolve_seat_effort(seat: RosterSeat, classification: Optional[str],
    strong_models: Sequence[StrongModelIdentity]) -> Optional[str]` — precedence:
    1. if `classification in ("complex", "unknown")` and a `StrongModelIdentity` with
       `(backend, model) == (seat.backend, seat.model or "")` has `effort`, return it;
    2. else `seat.effort`;
    3. else `None`.
  - `apply_effort_to_profile(profile: BaseModel, backend: str, effort: Optional[str], *,
    seat_label: str, logger: logging.Logger) -> BaseModel`:
    - `effort is None` → return `profile` unchanged (same object).
    - backend not in `EFFORT_FIELD_BY_BACKEND`, or the field is not in `type(profile).model_fields`
      → `logger.warning("seat %r: backend %r has no reasoning-effort setting; effort=%r ignored", ...)`,
      return unchanged.
    - accepted values come from the field annotation: unwrap `Optional[...]` and, when it is a
      `Literal`, use `typing.get_args`; a plain `str` annotation accepts any value. If `effort`
      is not accepted → `logger.warning(... "not supported by backend %r (accepted: %s); ignored" ...)`,
      return unchanged.
    - otherwise return `profile.model_copy(update={field: effort})`. (`model_copy` does not
      validate — that is why the explicit accepted-value check above is mandatory.)
  - Google-style docstrings, strict type hints.
- In `SddCoderEngine._run_attempt` (engine.py:3389), right after
  `profile = profile.model_copy(update={"subagent": "sdd-coder"})` (engine.py:3545) and before
  `_profile_with_runner_binaries`, add:
  ```python
  effort = resolve_seat_effort(
      seat, assessment.classification if assessment is not None else None,
      self.roster.complexity.strong_models,
  )
  profile = apply_effort_to_profile(profile, seat.backend or "", effort, seat_label=seat.label, logger=self.logger)
  ```
  When an effort is applied, log one INFO line (`seat`, `backend`, `effort`, `source` =
  `strong_model` | `seat`). Resolve the source inside `resolve_seat_effort`'s caller or return a
  `(effort, source)` tuple — implementer's choice, keep it in `effort.py`.
- `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` and
  `examples/sdd-coder-mcp.yaml`: add **commented** documentation next to the roster and
  `complexity.strong_models` blocks: the `effort:` key, the vocabulary, the precedence, the
  per-backend support (codex/zai/moonshot/google-compat/google_coding; nova, grok, claude-code
  and native seats ignored with a warning), and the one-time `policy_sha256` cache invalidation.
  Do not change any active seat value (shipped behaviour stays identical).

**NOT in scope**:
- Native seats (`coder_prepare_native`, `.claude/agents/sdd-worker.md`) — separate ledger issue.
- `agent_builder.build_dispatcher` / env-var defaults.
- The operator's git-ignored `.parrot/mcp-toolkits.yaml`.
- Retry-seat selection, eligibility or `strong_keys` logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/effort.py` | CREATE | `resolve_seat_effort`, `apply_effort_to_profile`, mapping table |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | call the helpers in `_run_attempt` |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` | MODIFY | commented `effort` docs |
| `examples/sdd-coder-mcp.yaml` | MODIFY | commented `effort` docs |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_effort.py` | CREATE | helper unit tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | engine wiring test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.models import RosterSeat, RosterConfig  # sdd_coder/models.py:155, :292
from parrot.flows.dev_loop.sdd_coder.complexity_models import StrongModelIdentity, ComplexityPolicy  # complexity_models.py:80, :96
from parrot.flows.dev_loop.models import (  # models/__init__.py
    CodexCodeDispatchProfile, ZaiCodeDispatchProfile, MoonshotCodeDispatchProfile,
    GoogleCompatCodeDispatchProfile, GoogleCodingDispatchProfile, NovaCodeDispatchProfile, LLMCodeDispatchProfile,
)
```
(Verify each profile name is exported from `parrot.flows.dev_loop.models` before use; import from
its `models/<backend>.py` module otherwise.)

### Existing Signatures to Use
```python
# sdd_coder/engine.py
self.logger = logging.getLogger(__name__)          # line 442
async def _run_attempt(...)                         # line 3389
assessment: Optional[ComplexityAssessment] = None   # line 3501, set at line 3514 inside the try
DevAgentSpec(agent=seat.backend, model=seat.model)  # line 3540
profile = profile.model_copy(update={"subagent": "sdd-coder"})  # line 3545
profile = self._profile_with_runner_binaries(profile, path)      # line 3546

# complexity_models.py:270 — ComplexityAssessment.classification: Literal["standard","complex","unknown"]
# RosterConfig.complexity: ComplexityPolicy  (sdd_coder/models.py:300); .strong_models: Tuple[StrongModelIdentity, ...]

# profile fields
ZaiCodeDispatchProfile.reasoning_effort: Literal["max","xhigh","high","medium","low","minimal","none"]  # models/zai.py:31
MoonshotCodeDispatchProfile.reasoning_effort: str                                                     # models/moonshot.py:34
GoogleCompatCodeDispatchProfile.reasoning_effort: Literal["none","low","medium","high"]               # models/google_compat.py:20
GoogleCodingDispatchProfile.effort: Optional[Literal["low","medium","high"]]                          # models/google_coding.py:26
CodexCodeDispatchProfile.reasoning_effort: Optional[Literal["minimal","low","medium","high","xhigh"]] # created by task 1

# tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py
def fake_builder_factory(behaviour_by_backend: dict, *, gate=None)  # line 75 — returns LLMCodeDispatchProfile
def _roster(*labels_backends) -> RosterConfig                        # line 92
# test_engine_forces_sdd_coder_subagent (line ~168) is the pattern: dispatcher.calls[*]["profile"]
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop.sdd_coder.effort`~~ — this task creates it
- ~~an effort field on `NovaCodeDispatchProfile`, `GrokCodeDispatchProfile`, `ClaudeCodeDispatchProfile`~~ — unsupported → warning
- ~~validation inside `BaseModel.model_copy(update=...)`~~ — Pydantic v2 skips it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/effort.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml", "action": "MODIFY"},
    {"path": "examples/sdd-coder-mcp.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_effort.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterSeat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_models.py#StrongModelIdentity"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No behaviour change when no seat/strong model sets `effort` (profile object returned unchanged).
- Never silently drop a configured value: every skip path logs a WARNING naming seat, backend, value.
- Warnings fire per attempt; that is acceptable (attempts are few). Do not add caching/dedup state.
- `effort.py` must not import `engine.py` (keep it a leaf module).

---

## Acceptance Criteria

- [ ] Complex task on a strong codex seat whose strong_model has `effort: high` and seat `effort: medium` → profile `reasoning_effort == "high"`.
- [ ] Standard task on the same seat → `"medium"` (strong-model effort ignored).
- [ ] No effort anywhere → profile returned unchanged (identity) and no warning.
- [ ] `google-compat` with `effort: max` → WARNING, `reasoning_effort` keeps its built value.
- [ ] `google_coding` with `effort: high` → `effort == "high"`.
- [ ] `nova` seat with `effort: high` → WARNING, profile unchanged.
- [ ] Engine: a roster seat with `effort` reaches the dispatched profile (fake builder returning a real `CodexCodeDispatchProfile`/`ZaiCodeDispatchProfile`); existing `test_engine_dispatch.py` tests stay green.
- [ ] Template and example still parse; `test_roster.py::test_shipped_template_has_two_retry_capable_strong_seats` green.
- [ ] `ruff check` clean on touched Python files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_effort.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_routing.py -q`

---

## Test Specification

- `test_effort.py`:
  - `test_resolve_strong_override_for_complex` / `..._for_unknown`
  - `test_resolve_seat_effort_for_standard`
  - `test_resolve_none_when_unset`
  - `test_apply_maps_each_backend` (parametrize codex/zai/moonshot/google-compat/google_coding with real profile classes)
  - `test_apply_rejects_unsupported_value_with_warning` (caplog; google-compat `max`, codex `none`)
  - `test_apply_unsupported_backend_warns` (nova)
  - `test_apply_none_returns_same_object`
- `test_engine_dispatch.py`: `test_engine_applies_seat_effort_to_profile` — local builder variant that
  returns a real backend profile; assert `dispatcher.calls[0]["profile"].reasoning_effort`.

---

## Agent Instructions

1. Work in `.claude/worktrees/fix-sdd-coder-seat-effort-sdd-coder-seat-effort` — never on `dev`.
2. Confirm HOTFIX-sdd-coder-seat-effort-1 is `done` in `sdd/briefs/sdd-coder-seat-effort.index.json`.
3. Read the brief; verify the Codebase Contract lines (engine.py lines drift often — re-grep).
4. Touch only the six listed files.
5. Run every Validation Command with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit code: `feat(sdd-coder): HOTFIX-sdd-coder-seat-effort-2 — resolve and apply per-seat effort`.
7. Update this Completion Note and the per-brief index status; commit the SDD state.

---

## Completion Note

<!-- Filled in by the implementer. -->
