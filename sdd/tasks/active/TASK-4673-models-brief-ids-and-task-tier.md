# TASK-4673: `models.py` accepts brief task ids and `tier='task'`

**Feature**: FEAT-736 — The sdd_coder MCP surface accepts every id and tier its engine already accepts
**Spec**: `sdd/specs/sdd-coder-models-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:0ea4f0acaefd`
**Discovered-from**: `issue:146f4be4ee6d`

---

## Context

`sdd_coder/models.py` holds the argument models the MCP/tool surface validates
every `coder_*` call against (`toolkit.py:102` `_ARG_MODELS`). Two of its gates
are narrower than the engine they guard:

- `_TASK_ID_RE` (L111) only admits `^TASK-\d{1,5}$`, so a brief task id
  `HOTFIX-<KEY>-<n>` (`scripts/sdd/brief_meta.py:184`) is rejected before the
  engine sees it — `/sdd-brief --split` cannot use the MCP coder path
  (`issue:0ea4f0acaefd`).
- `CoderRunValidationArgs` (L815) declares `tier: Literal["merge", "feature"]`
  and has no `attempt_uid`, with `extra="forbid"` inherited from `_Args` — yet
  `toolkit.coder_run_validation` (L602) and `engine.run_validation`
  (`engine.py:1205`) both take `tier='task'` *and* `attempt_uid`. The schema
  gate rejects a call its own method signature advertises
  (`issue:146f4be4ee6d`).

This task fixes both in the one file. Spec §3 Modules 1 (site 1) and 2.

## Scope

- Widen `_TASK_ID_RE` to admit `HOTFIX-<KEY>-<n>` beside `TASK-<NNN>`, which
  fixes all four of its consumers at once: `CoderRunChunkArgs.task_ids` (L672),
  `CoderPrepareNativeArgs.task_id` (L682), `CoderRunValidationArgs.task_ids`
  (L826) and `NativeObservation.task_id` (L857).
- Update `_check_task_id`'s docstring (L628) and error text (L630) to name both
  accepted shapes.
- Add `_check_uuid_optional` beside `_check_uuid`.
- Widen `CoderRunValidationArgs.tier` and add `attempt_uid: Optional[str] = None`
  validated as a UUID **only when present**.
- Extend the four new/changed behaviours with tests in `test_models.py`.

**NOT in scope**:
- `optimization_models.py` and `background.py` task-id gates — TASK-4674.
- `test_scope/report.py` — TASK-4675.
- Enforcing the per-tier obligations (`tier='task'` ⇒ exactly one id +
  `attempt_uid` + `base_ref`). `background.py:550-555` already owns that rule;
  this model must NOT duplicate it (spec §1 Non-Goals).
- `toolkit.py` — it needs no edit; it already declares the wider signature.
- Any shared/common regex module (spec §1 Non-Goals; `issue:6da9094f951b`).
- `packages/ai-parrot/build/...` — a stale build artifact tree, never the source.

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | 4 edit sites |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py` | MODIFY | extend with 8 tests |

---

## Codebase Contract (Anti-Hallucination)

Verified at `dev @ b2ec65729`, 2026-10-24.

### Verified Imports

```python
# already imported at the top of models.py — add nothing
import re
from typing import List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

# already imported in tests/flows/dev_loop/sdd_coder/test_models.py
from parrot.flows.dev_loop.sdd_coder.models import (
    CoderRunChunkArgs, CoderPrepareNativeArgs, CoderRunValidationArgs, NativeObservation,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")                      # L111  (1 occurrence)

def _check_uuid(v: str) -> str: ...                              # L115  (1 occurrence)
#   raises ValueError("execution_id must be a valid UUID string, got …") via UUID(v)

def _check_task_id(v: str) -> str:                               # L627
    """Reject anything that does not match `^TASK-\\d{1,5}$`."""  # L628
    if not _TASK_ID_RE.fullmatch(v):                             # L629
        raise ValueError(f"invalid task id {v!r}; expected TASK-<1-5 digits>")   # L630
    return v

def _check_task_ids(vs: List[str]) -> List[str]: ...             # L634

class _Args(BaseModel):                                          # L618
    model_config = ConfigDict(extra="forbid")

class CoderRunValidationArgs(_Args):                              # L815  (1 occurrence)
    feature: str
    worktree: str
    execution_id: str = Field(..., min_length=1)
    task_ids: List[str] = Field(..., min_length=1)
    tier: Literal["merge", "feature"]                             # L822  ← widen
    timeout_seconds: int = Field(..., ge=1, le=7200)
    request_id: str = Field(..., min_length=1)
    _wt = field_validator("worktree")(_check_abs)
    _tids = field_validator("task_ids")(_check_task_ids)
    _exec = field_validator("execution_id")(_check_uuid)

# The naming precedent for the new optional wrapper (same module):
def _require_utc(value: datetime) -> datetime: ...
def _require_utc_optional(value: Optional[datetime]) -> Optional[datetime]: ...

# The id space being admitted — scripts/sdd/brief_meta.py
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")        # L28, + no `..`, no trailing `.`, no `.lock`
def brief_task_id(meta: BriefMeta, n: int) -> str:                # L181 → f"HOTFIX-{meta.key}-{n}"

# The layers that already accept what this task unblocks — DO NOT EDIT THEM
# packages/.../sdd_coder/toolkit.py:102   _ARG_MODELS["coder_run_validation"] = CoderRunValidationArgs
# packages/.../sdd_coder/toolkit.py:602   async def coder_run_validation(..., tier: Literal["task","merge","feature"], ..., attempt_uid: Optional[str] = None)
# packages/.../sdd_coder/engine.py:1205   async def run_validation(..., tier: Literal["task","merge","feature"], ..., attempt_uid=None, base_ref=None)

# tests/flows/dev_loop/sdd_coder/test_models.py already defines:
VALID_UUID  # module-level valid UUID string used by the existing arg-model tests
```

### Does NOT Exist

- `_check_uuid_optional` in `models.py` — **this task creates it**. Do not
  import it from anywhere; `_require_utc_optional` is only the naming
  precedent, not an implementation to reuse.
- `attempt_uid` on `CoderRunValidationArgs` — this task adds it.
- Any shared id-regex module under `parrot/flows/dev_loop/`. Do not
  `from ... import _TASK_ID_RE` — each module declares its own (deliberate;
  see `background.py:76-77`).
- `_SAFE_ID_RE` in `sdd_coder/` — it lives in `test_scope/report.py` and is
  TASK-4675's business.
- `_check_task_id` is **not** used by `optimization_models.py`; that module has
  its own `_check_optional_task_id` (TASK-4674).

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
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#_check_task_id",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#_check_uuid",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderRunValidationArgs",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderRunChunkArgs",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderPrepareNativeArgs",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativeObservation"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

```python
# Module-level regex constants in this file use a `#:` doc-comment and sit in
# the constants block near the top. Keep that style.
#: <what it admits and why>
_TASK_ID_RE = re.compile(r"...")
```

`_check_uuid_optional` mirrors `_require_utc_optional` in the same module: a
`None`-passthrough wrapper that delegates, nothing more.

### Key Constraints

- `_check_task_id` uses `.fullmatch()`. Keep it — the `^…$` anchors plus
  `fullmatch` are belt-and-braces and harmless.
- A brief key may itself end in digits (`CS-228` → `HOTFIX-CS-228-1`). The
  trailing `-\d{1,5}` anchor plus backtracking matches that; AC 3 pins it.
- The error text is asserted by existing tests. After editing, run the
  regression suites in **Validation Commands** and fix any assertion that
  pins the old string — do not weaken a test to make it pass.
- `attempt_uid` must stay `Optional[str] = None` with a *conditional* UUID
  check. A required field would break `tier='merge'`/`'feature'` callers.

### References in Codebase

- `scripts/sdd/brief_meta.py:181` — `brief_task_id()`, the id generator.
- `background.py:80` — `_FEATURE_ID_RE`, already widened to `BRIEF-*` by
  FEAT-698; this task is the task-id half of the same job.
- `background.py:550-555` — the engine's per-tier obligations, which this
  model must not duplicate.

---

## Implementation Blueprint

### Steps (in order)

1. Widen `_TASK_ID_RE` (site A) — one constant fixes all four consumers, so do
   it first and run the existing `test_models.py` to see which error-text
   assertions move.
2. Update `_check_task_id`'s docstring and error message (site B) — the message
   is user-facing diagnostics for a coder seat, so it must name both shapes or
   a brief author cannot tell why a good id was refused.
3. Add `_check_uuid_optional` (site C) *before* site D, because site D's
   validator references it.
4. Widen `CoderRunValidationArgs` (site D).
5. Extend `test_models.py` with the eight tests in **Test Specification**.
6. `ruff check` the two files, then run every command in **Validation Commands**.

### `packages/.../sdd_coder/models.py` (MODIFY — site A)

```python
# occurrences: 1 (verified: grep -c '_TASK_ID_RE = re.compile(' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py)
# REPLACE the line `_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")` (verified: models.py:111)
#: Reserved task ids (`TASK-<NNN>`) and a brief's local, unreserved task ids
#: (`HOTFIX-<KEY>-<n>`, `scripts/sdd/brief_meta.brief_task_id`). `<KEY>` uses
#: brief_meta's own `_SAFE_REF_RE` character class. Re-declared, not imported:
#: see `background.py:76-77` and `optimization_models._TASK_ID_PATTERN`.
_TASK_ID_RE = re.compile(r"^(?:TASK-\d{1,5}|HOTFIX-[A-Za-z0-9][A-Za-z0-9._-]*-\d{1,5})$")
```

**Why**: one constant feeds `_check_task_id`/`_check_task_ids`, which are wired
as field validators at L672, L682, L826 and L857 — widening here is the whole
of `issue:0ea4f0acaefd` for this file. The character class is copied from
`brief_meta._SAFE_REF_RE` so the gate admits exactly the keys that tool already
accepts, no more.

### `packages/.../sdd_coder/models.py` (MODIFY — site B)

```python
# occurrences: 1 (verified: grep -c 'def _check_task_id(v: str) -> str:' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py)
# REPLACE the body of `def _check_task_id(v: str) -> str:` (verified: models.py:627-632)
def _check_task_id(v: str) -> str:
    """Reject anything that is neither `TASK-<1-5 digits>` nor `HOTFIX-<KEY>-<1-5 digits>`.

    The second shape is a brief's local, unreserved task id (FEAT-698,
    `scripts/sdd/brief_meta.brief_task_id`); without it the MCP coder surface
    refuses every `/sdd-brief --split` task the engine would have accepted.
    """
    if not _TASK_ID_RE.fullmatch(v):
        raise ValueError(f"invalid task id {v!r}; expected TASK-<1-5 digits> or HOTFIX-<KEY>-<1-5 digits>")
    return v
```

**Why**: the message is the only feedback a coder seat gets for a rejected id;
naming one shape when two are legal sends a brief author hunting the wrong bug.

### `packages/.../sdd_coder/models.py` (MODIFY — site C)

```python
# occurrences: 1 (verified: grep -c 'def _check_uuid(v: str) -> str:' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py)
# AFTER — insert below the closing `return v` of `def _check_uuid(v: str) -> str:` (verified: models.py:115)
def _check_uuid_optional(v: Optional[str]) -> Optional[str]:
    """Apply `_check_uuid` only when a value is present (mirrors `_require_utc_optional`)."""
    if v is None:
        return None
    return _check_uuid(v)
```

**Why**: `attempt_uid` is meaningful only for `tier='task'`, so the schema may
not require it — but when a caller does send one, a malformed uid must fail at
the schema rather than reach the engine's attempt lookup as a cache miss.

### `packages/.../sdd_coder/models.py` (MODIFY — site D)

```python
# occurrences: 1 (verified: grep -c 'class CoderRunValidationArgs(_Args):' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py)
# REPLACE the class `class CoderRunValidationArgs(_Args):` (verified: models.py:815-827)
class CoderRunValidationArgs(_Args):
    """`coder_run_validation` arguments (FEAT-584 M8/R8): admits one protected, idempotent selection.

    `tier='task'` (FEAT-709) is admitted here but its *obligations* are not
    enforced here: exactly one `task_ids` entry, an `attempt_uid` this
    execution issued, and the engine-supplied fork SHA as `base_ref` are
    checked by `BackgroundRunner.run_validation` (`background.py`), which owns
    that rule. This model only stops the schema from refusing a request the
    toolkit's own signature advertises.
    """

    feature: str
    worktree: str
    execution_id: str = Field(..., min_length=1)
    task_ids: List[str] = Field(..., min_length=1)
    tier: Literal["task", "merge", "feature"]
    timeout_seconds: int = Field(..., ge=1, le=7200)
    request_id: str = Field(..., min_length=1)
    attempt_uid: Optional[str] = None
    _wt = field_validator("worktree")(_check_abs)
    _tids = field_validator("task_ids")(_check_task_ids)
    _exec = field_validator("execution_id")(_check_uuid)
    _attempt_uuid = field_validator("attempt_uid")(_check_uuid_optional)
```

**Why**: `toolkit.py:102` binds this model as the `_pre_execute` schema for
`coder_run_validation`, and `_Args` sets `extra="forbid"` — so an absent
`attempt_uid` field is an outright rejection, not a silently dropped key. The
docstring records *where* the per-tier rule lives so a later reader does not
"helpfully" duplicate it here.

### `packages/.../tests/flows/dev_loop/sdd_coder/test_models.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_chunk_args_accept_valid' packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py)
# AFTER — append the new tests at the end of the arg-model test block; reuse the
# module-level VALID_UUID already defined in this file.

BRIEF_TASK_ID = "HOTFIX-CS-228-1"   # brief key 'CS-228' ends in digits on purpose


def test_chunk_args_accept_brief_task_ids():
    """A brief's local task id is admitted beside TASK-<NNN> (issue:0ea4f0acaefd)."""
    args = CoderRunChunkArgs(
        feature="BRIEF-CS-228", worktree="/abs/path", task_ids=[BRIEF_TASK_ID], execution_id=VALID_UUID
    )
    assert args.task_ids == [BRIEF_TASK_ID]


# FILL IN: the remaining seven tests from the task's Test Specification table —
# bounded by AC 1..5. Each is 3-6 lines in the style above; use
# `pytest.raises(ValidationError)` for every rejection case and assert on the
# parsed field for every acceptance case. Do NOT assert on the exact ValueError
# text (AC 6 keeps the message free to improve).
```

**Why**: the acceptance cases are what the two ledger issues actually report;
the rejection cases are what stops the widened regex from becoming a hole.

### FILL IN checklist

- [ ] `test_prepare_native_accepts_brief_task_id` — bounded by AC 1.
- [ ] `test_brief_key_ending_in_digits` — the backtracking case, bounded by AC 3.
- [ ] `test_task_id_still_rejects_foreign_ids` — parametrized over
      `"nope"`, `"HOTFIX-1"`, `"HOTFIX--1"`, `"HOTFIX-CS-228-"`,
      `"HOTFIX-CS-228-123456"`, `"TASK-123456"`, `"hotfix-cs-228-1"`;
      bounded by AC 1.
- [ ] `test_run_validation_args_accept_task_tier` — bounded by AC 4.
- [ ] `test_run_validation_args_tier_task_without_attempt_uid_parses` —
      bounded by AC 4 **and** the Non-Goal: the model must NOT enforce the
      engine's obligation.
- [ ] `test_run_validation_args_reject_bad_attempt_uid` — bounded by AC 4.
- [ ] `test_run_validation_args_reject_unknown_tier` — bounded by AC 4.
- [ ] Any existing assertion in this file that pins the old
      `"expected TASK-<1-5 digits>"` text — update it to the new message
      (bounded by AC 6: the suites must pass, not be weakened).

---

## Acceptance Criteria

1. `CoderRunChunkArgs`, `CoderPrepareNativeArgs`, `CoderRunValidationArgs` and
   `NativeObservation` each accept a `HOTFIX-<KEY>-<n>` task id, and each still
   rejects `"nope"`, `"HOTFIX-1"`, `"HOTFIX-CS-228-"` and `"TASK-123456"`.
2. `_check_task_id`'s error message names both accepted shapes.
3. A brief key ending in digits (`HOTFIX-CS-228-1`) is accepted and the value
   round-trips verbatim.
4. `CoderRunValidationArgs(tier="task", attempt_uid=<uuid>)` parses; `tier="task"`
   with `attempt_uid` omitted still parses; `tier="whatever"` and
   `attempt_uid="not-a-uuid"` both raise `ValidationError`.
5. `_check_uuid_optional(None) is None`, and it delegates for a present value.
6. Every command in **Validation Commands** exits 0, including the two
   regression suites — no test was deleted or weakened to get there.
7. No symbol is imported across `sdd_coder` modules to share the regex, and
   `toolkit.py`, `engine.py`, `background.py` and `optimization_models.py` are
   unchanged by this task.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py -q`

## Test Specification

| Test | Asserts |
|---|---|
| `test_chunk_args_accept_brief_task_ids` | `task_ids == ["HOTFIX-CS-228-1"]` |
| `test_prepare_native_accepts_brief_task_id` | `CoderPrepareNativeArgs(task_id="HOTFIX-CS-228-12")` parses |
| `test_brief_key_ending_in_digits` | id round-trips verbatim (backtracking) |
| `test_task_id_still_rejects_foreign_ids` | 7 bad ids each raise `ValidationError` |
| `test_run_validation_args_accept_task_tier` | `tier="task"`, `attempt_uid == VALID_UUID` |
| `test_run_validation_args_tier_task_without_attempt_uid_parses` | model does not enforce the engine's rule |
| `test_run_validation_args_reject_bad_attempt_uid` | `ValidationError` |
| `test_run_validation_args_reject_unknown_tier` | `ValidationError` |

Run with `PYTHONPATH=packages/ai-parrot/src`. No new fixtures; `VALID_UUID` is
already defined in `test_models.py`.

## Agent Instructions

1. Verify every "Existing Signatures to Use" line in the source before editing.
   If a line number moved, re-locate the anchor; if an anchor is **gone**, stop
   and report the drift instead of inventing an attachment point.
2. Edit only the two files in the table. `toolkit.py` needs no change.
3. Do not add a shared regex module and do not import `_TASK_ID_RE` from
   another module (spec §1 Non-Goals).
4. Run `ruff check` on both files, then all three Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src`.
5. Commit as `feat(sdd-coder-models-fixes): TASK-4673 — models.py accepts brief task ids and tier='task'`.

## Completion Note

<!-- filled in on completion -->
