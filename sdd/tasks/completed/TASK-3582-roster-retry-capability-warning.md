# TASK-3582: Report a roster that cannot retry a complex task, at execution start

**Feature**: FEAT-588 — Make the sdd-coder retry ladder reachable for complex/unknown tasks
**Spec**: `sdd/specs/fixgroup-47eb801095a6.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3580
**Assigned-to**: unassigned

**Discovered-from**: `issue:569e81756247` (ledger, severity major)

---

## Context

Implements spec §3 **Module 3** and goal **G3**.

A roster whose `complexity.strong_models` resolves to fewer than two
retry-capable seats can never retry a complex/unknown task — that is the whole
defect of this feature. Today an operator discovers it only when a task fails
and blocks, with a diagnostic that reads like transient capacity. The condition
is fully known at `coder_begin_execution`, so report it there.

Per spec §8 **Q2 (resolved: yes)**, the warning also fires when `strong_models`
is **empty** — the most extreme case of the same condition, where every
complex/unknown task blocks at admission rather than on retry.

The warning is advisory. It must never block or fail an execution.

---

## Scope

- Add a `roster_warnings: List[str]` field to `ExecutionPoolView`.
- Have `ExecutionPool` compute the warnings and populate them in `view()`:
  - `strong_models` empty → every complex/unknown task will block at admission;
  - fewer than two **retry-capable** strong seats → a complex/unknown task that
    fails attempt 1 has no MCP seat to retry on. "Retry-capable" means eligible
    under `eligible_seats()` for a restricted classification; a `kind: native`
    strong seat counts only for the *native handoff* path (TASK-3580), never for
    an MCP retry, so a roster whose only second strong seat is native must still
    be reported.
- Store what the pool needs to compute this — `ExecutionPool.__init__` already
  receives `roster: RosterConfig` (which carries `complexity`) but currently
  keeps only `roster_fingerprint(roster)` (`pool.py:106`).
- Tests in `test_execution_pool_integration.py`.

**NOT in scope**:
- `engine.py` — TASK-3580 owns it this feature; the warning is computed in the
  pool and surfaces through the `view()` that `begin_execution` already returns.
- Blocking, failing or degrading an execution on the warning.
- Changing `eligible_seats()` or the strong-model allowlist semantics (spec NG3).
- Surfacing the warning in `sdd-worker`'s prompt.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `ExecutionPoolView.roster_warnings` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py` | MODIFY | Compute warnings; populate in `view()` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py` | MODIFY | Tests for both warning cases and the clean case |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `b366bd774` on 2026-09-21.

### Existing Signatures to Use

```python
# models.py:444 — NOTE `extra="forbid"`: an ad-hoc dict key raises. Add a real field.
class ExecutionPoolView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_id: str = Field(..., min_length=1)
    feature_id: str = Field(..., min_length=1)
    worktree_path: str = Field(..., min_length=1)
    status: ExecutionStatus
    generation: int = Field(..., ge=0)
    seats: List[PoolSeatView] = Field(default_factory=list)
    fallback_required: bool = False
    fallback_reason: str = ""
    persisted: bool = True
    persistence_degraded: bool = False   # :463

# models.py:207
class RosterConfig(BaseModel):
    seats: List[RosterSeat] = Field(..., min_length=1)      # :210
    complexity: ComplexityPolicy = Field(default_factory=ComplexityPolicy)  # :215

# complexity_models.py:122
strong_models: Tuple[StrongModelIdentity, ...] = ()

# pool.py — __init__ RECEIVES `roster: RosterConfig` but stores only the fingerprint:
#   pool.py:106   self._roster_fingerprint = roster_fingerprint(roster)
# There is no `self._roster` today (verified: grep -n 'self\._roster' pool.py
# returns only the three `_roster_fingerprint` lines: :106, :160, :194).

# pool.py:167
def view(self) -> ExecutionPoolView:
    """Return a read-only snapshot of the current pool state."""
    return ExecutionPoolView(
        execution_id=self._execution_id,
        ...
        persistence_degraded=self._persistence_degraded,   # :179
    )

# roster.py:241 — the definition of "eligible for a restricted classification"
def eligible_seats(
    assessment: ComplexityAssessment, seats: List[RosterSeat], policy: ComplexityPolicy
) -> List[RosterSeat]: ...
# roster.py:277 -- backend is "native" for kind="native" seats:
#   backend = "native" if seat.kind == "native" else (seat.backend or "")
```

### Does NOT Exist
- ~~`ExecutionPoolView.warnings`~~ / ~~`.notices`~~ — no such field; `grep -n 'warnings\|notices' models.py` returns nothing. You are adding `roster_warnings`.
- ~~`ExecutionPool.roster`~~ / ~~`self._roster`~~ — not stored today. Add what you need in `__init__`.
- ~~`RosterConfig.strong_models`~~ — it is nested: `roster.complexity.strong_models`.
- ~~a `warn`/`warning` channel on `CoderFailure`~~ — `CoderFailure` is an exception; this warning must never raise.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#ExecutionPoolView",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py#ExecutionPool.view",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#eligible_seats"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Advisory only.** Never raise, never set `fallback_required`, never change
  `status`. A warning is a string in a list; nothing branches on it.
- `ExecutionPoolView` is `extra="forbid"` — adding a key at construction time
  without declaring the field raises a `ValidationError`. Declare the field.
- Compute in the pool, not in `begin_execution`: that method has several
  `return ...view()` paths (idempotent resume at `engine.py:~600`, plus fresh
  construction), and patching each with a `model_copy` would drift.
- Default `[]`, so every existing construction site and test stays valid.

### References in Codebase
- `pool.py:167` `view()` — the construction site to extend.
- `roster.py:241` `eligible_seats` — reuse it rather than re-deriving
  "is this seat strong?"; it already handles the `kind="native"` → `backend="native"`
  mapping that a hand-rolled check gets wrong.

---

## Implementation Blueprint

### Steps (in order)
1. Declare `roster_warnings` on `ExecutionPoolView` — *why*: `extra="forbid"`
   means an undeclared key is a hard error, not a silent extra.
2. Keep the policy (or the roster) on `ExecutionPool` in `__init__` — *why*: the
   constructor already receives it and throws it away after fingerprinting.
3. Compute the warnings and pass them in `view()` — *why*: every caller of
   `begin_execution` and `coder_status` then gets them for free, with no change
   to any return path.
4. Test both cases plus a clean roster — *why*: a warning that also fires on a
   healthy two-MCP-strong-seat roster would be noise operators learn to ignore.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '    persistence_degraded: bool = False' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py)
# AFTER — insert below `    persistence_degraded: bool = False` (verified: models.py:463)
    roster_warnings: List[str] = Field(default_factory=list)
    """FEAT-588: advisory notes about a roster that cannot retry a complex/unknown
    task -- an empty `complexity.strong_models`, or fewer than two retry-capable
    strong seats. Never blocks the execution; nothing branches on it."""
```
**Why**: a defaulted list keeps every existing construction site and fixture
valid, and the field is declared so `extra="forbid"` accepts it.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py` (MODIFY — keep the policy)
```python
# occurrences: 1 (verified: grep -c -F '        self._roster_fingerprint = roster_fingerprint(roster)' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py)
# AFTER — insert below `        self._roster_fingerprint = roster_fingerprint(roster)` (verified: pool.py:106)
        self._complexity = roster.complexity
```
**Why**: `__init__` already receives the whole `RosterConfig` and currently
discards everything but the fingerprint. Keeping only the policy makes the
dependency explicit and avoids implying the pool may read the rest of the
roster.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py` (MODIFY — compute + populate)
```python
# occurrences: 1 (verified: grep -c -F '            persistence_degraded=self._persistence_degraded,' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py)
# AFTER — insert below `            persistence_degraded=self._persistence_degraded,` (verified: pool.py:179)
            roster_warnings=self._roster_warnings(),
```
plus a new private helper on the same class:
```python
    def _roster_warnings(self) -> List[str]:
        """Advisory notes about a roster that cannot retry a complex task (FEAT-588).

        Returns:
            Zero or more human-readable warnings; never raises.
        """
        # FILL IN: (a) empty `self._complexity.strong_models` -> warn that every
        # complex/unknown task blocks at admission (spec Q2); (b) fewer than two
        # RETRY-capable strong seats among `self._seats` -> warn that a failed
        # attempt 1 has no MCP seat to retry on. Use `eligible_seats()` with a
        # restricted classification rather than re-deriving strength by hand, and
        # remember a `kind="native"` strong seat is NOT retry-capable for an MCP
        # retry -- bounded by AC-1/AC-2/AC-3.
        raise NotImplementedError
```
**Why**: computing inside `view()` means `begin_execution`'s several return
paths — including the idempotent-resume one — all carry the warning with no
further edits. It is pure and cheap, so recomputing per snapshot is fine.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py` (MODIFY)
```python
# AFTER — add module-level tests following this file's existing fixture style
def test_empty_strong_models_is_reported_at_execution_start():
    """FEAT-588 AC-2 / spec Q2: an empty allowlist blocks every complex task."""
    # FILL IN: build a pool whose roster has complexity.strong_models == ()
    # and assert view().roster_warnings names the condition — bounded by AC-2.
    raise NotImplementedError


def test_single_retry_capable_strong_seat_is_reported():
    """FEAT-588 AC-1: the shipped roster shape — 1 MCP strong + 1 native strong."""
    # FILL IN: assert the warning fires, and that it fires BECAUSE the native
    # strong seat is not retry-capable for an MCP retry — bounded by AC-1.
    raise NotImplementedError


def test_two_mcp_strong_seats_produce_no_warning():
    """FEAT-588 AC-3: a healthy roster must stay silent."""
    # FILL IN: two MCP strong seats -> view().roster_warnings == [] — bounded by AC-3.
    raise NotImplementedError
```
**Why**: the third test is the one that keeps the feature useful — a warning
that also fires on a healthy roster trains operators to ignore it.

### FILL IN checklist
- [ ] `_roster_warnings()` body (both conditions, via `eligible_seats`)
- [ ] three test bodies

---

## Acceptance Criteria

- [ ] AC-1 — a roster with one MCP strong seat + one native strong seat yields a warning naming the missing MCP retry capacity.
- [ ] AC-2 — an empty `complexity.strong_models` yields a warning (spec Q2).
- [ ] AC-3 — a roster with two MCP strong seats yields `roster_warnings == []`.
- [ ] AC-4 — the warning never blocks: `status`, `fallback_required` and `fallback_reason` are unchanged by it, and no exception is raised.
- [ ] AC-5 — `ExecutionPoolView` still validates with `extra="forbid"`; existing construction sites are unaffected by the new default.
- [ ] `ruff check` and `black --check` clean on all three files.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_compact_views.py -q`

---

## Output

### Completion Note
(Agent fills this in when done)

## Completion Note

- Task: TASK-3582
- Feature: fixgroup-47eb801095a6
- Implementation SHA: b7001a7c554f9f855d23ecb399aebe8533f356fa
- Closed at (UTC): 2026-09-21T22:08:43+00:00
- Fix commits: b7001a7c554f9f855d23ecb399aebe8533f356fa

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| ac_verification | AC-1..AC-5 covered by test_single_retry_capable_strong_seat_is_reported/test_empty_strong_models_is_reported_at_execution_start/test_two_mcp_strong_seats_produce_no_warning; extra=forbid still validates; ruff shows only 42 pre-existing unrelated ASYNC221 findings (residual, deferred to /sdd-done) |
| merge_tier_validation | coder_run_validation (tier=merge, TASK-3582+TASK-3583) timed_out after 180s -- same deterministic pre-existing hang in packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py already confirmed unrelated and filed as issue:1dbb2aac09ba |
| model_feedback_id | coder-feedback:267735c7de8d454b7fb85b2c |
| review_feedback_id | coder-review:c2a0f689f44047e5d2989d63 |
| review_fix_commit | b7001a7c554f9f855d23ecb399aebe8533f356fa -- fixed invalid Pydantic literal backend="claude" in test_two_mcp_strong_seats_produce_no_warning |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 167.62s · Tokens: n/a |
| task_scoped_tests | pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py test_compact_views.py test_roster.py test_complexity_routing.py -> 138 passed after review fix (was 1 failed due to invalid backend literal) |
