# TASK-4674: `optimization_models.py` and `background.py` accept brief task ids

**Feature**: FEAT-736 — The sdd_coder MCP surface accepts every id and tier its engine already accepts
**Spec**: `sdd/specs/sdd-coder-models-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4673
**Assigned-to**: unassigned

**Discovered-from**: `issue:0ea4f0acaefd`

---

## Context

`issue:0ea4f0acaefd` lists three source sites where `sdd_coder` hard-codes the
closed `^TASK-\d{1,5}$` shape. TASK-4673 widened the first
(`models.py`); this task does the other two:

- **`optimization_models.py:31`** — `_TASK_ID_PATTERN`, consumed twice: by
  `_check_optional_task_id` (L88, via `re.match`) and as a pydantic
  `Field(pattern=…)` on `TaskCompletionEvidence.task_id` (L209). The `Field`
  form is compiled by pydantic's **Rust** regex engine, not Python's `re`, so
  it needs its own proof.
- **`background.py:78`** — `_TASK_ID_RE`, the guard inside
  `BackgroundRunner.run_validation` (L565). FEAT-698 widened this module's
  `_FEATURE_ID_RE` to admit `BRIEF-*` (L80) but left the task-id regex closed;
  this task finishes that job.

Spec §3 Module 1, sites 2 and 3.

## Scope

- Widen `_TASK_ID_PATTERN` (`optimization_models.py:31`) and update
  `_check_optional_task_id`'s docstring (L85) and error text (L89).
- Widen `_TASK_ID_RE` (`background.py:78`), its cross-reference comment
  (L76-77) and the error text at L566.
- Add the tests listed in **Test Specification**, including the
  two-layer integration test that proves the schema and the runner guard now
  agree on `tier='task'`.

**NOT in scope**:
- `models.py` — TASK-4673 (this task depends on it).
- `test_scope/report.py` — TASK-4675.
- `complexity_collectors.py:177` (`re.search(r"(TASK-\d+)", line)`) — a
  best-effort telemetry scrape of a log line, not an input gate
  (spec §1 Non-Goals).
- The `tier='task'` obligations at `background.py:550-555` — they are correct
  already and must keep rejecting a missing `attempt_uid`/`base_ref`.
- Any shared regex module; each site keeps its own declaration.
- `packages/ai-parrot/build/...` — a stale build artifact tree.

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py` | MODIFY | 2 edit sites |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | 2 edit sites |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py` | MODIFY | 3 tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` | MODIFY | 2 tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_task_tier.py` | MODIFY | 1 integration test |

---

## Codebase Contract (Anti-Hallucination)

Verified at `dev @ b2ec65729`, 2026-10-24.

### Verified Imports

```python
# already imported in both source modules — add nothing
import re
from pydantic import Field

# test imports
from parrot.flows.dev_loop.sdd_coder.optimization_models import TaskCompletionEvidence
from parrot.flows.dev_loop.sdd_coder.models import CoderRunValidationArgs   # TASK-4673's widened model
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py
_TASK_ID_PATTERN = r"^TASK-\d{1,5}$"                               # L31  (1 occurrence)

def _check_optional_task_id(value: str | None) -> str | None:      # L84
    """Apply the closed `TASK-<1-5 digits>` shape only when a task_id is present."""   # L85
    if value is None:
        return value
    if not re.match(_TASK_ID_PATTERN, value):                      # L88
        raise ValueError(f"invalid task id {value!r}; expected TASK-<1-5 digits>")      # L89
    return value

class TaskCompletionEvidence(OptimizationModel):                   # L205
    feature_slug: str = Field(min_length=1)
    task_id: str = Field(pattern=_TASK_ID_PATTERN)                 # L209  ← Rust regex engine
    implementation_sha: str
    validation_refs: list[EvidenceRef]
    review_evidence: EvidenceRef
    fix_commits: list[str] = Field(default_factory=list)
    completion_facts: dict[str, object]

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
#: Same closed shape as `optimization_models._TASK_ID_PATTERN` (not imported --   # L76
#: that module's validators are private to its own field declarations).           # L77
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")                        # L78  (1 occurrence)
#: FEAT-695: canonical feature id shape for test-result records.
_FEATURE_ID_RE = re.compile(r"^(?:FEAT-\d+|BRIEF-[A-Za-z0-9][A-Za-z0-9._-]*)$")   # L80 — already brief-aware, DO NOT EDIT

# inside BackgroundRunner.run_validation — the surrounding guards, all correct already:
        if tier not in ("task", "merge", "feature"):               # L550
            raise ValueError(f"tier must be 'task', 'merge' or 'feature', got {tier!r}")
        if tier == "task":                                         # L552
            if len(task_ids) != 1:
                raise ValueError("tier='task' admits exactly one task id")
            if not base_ref or not attempt_uid:
                raise ValueError("tier='task' requires an explicit base_ref (fork SHA) and attempt_uid")
        ...
        for task_id in task_ids:                                   # L564
            if not _TASK_ID_RE.match(task_id):                     # L565
                raise ValueError(f"invalid task id {task_id!r}; expected TASK-<1-5 digits> (never a foreign id)")  # L566

# TASK-4673's result, which this task's integration test consumes:
class CoderRunValidationArgs(_Args):
    tier: Literal["task", "merge", "feature"]
    attempt_uid: Optional[str] = None
```

### Does NOT Exist

- `_check_task_id` in `optimization_models.py` — that module's helper is
  `_check_optional_task_id` (note the different name **and** the `None`
  passthrough).
- `_TASK_ID_RE` in `optimization_models.py` — it is a bare string
  `_TASK_ID_PATTERN`, not a compiled pattern, because `Field(pattern=…)`
  needs the string form.
- A shared regex module. Do not `from .models import _TASK_ID_RE` —
  `background.py:76-77` records that the duplication is deliberate.
- `BRIEF-*` is **not** a task id. `_FEATURE_ID_RE` already covers brief
  *feature* ids and must stay untouched; `["BRIEF-CS-228"]` passed as a
  `task_ids` entry must still be rejected.
- `packages/ai-parrot/build/lib.linux-x86_64-cpython-312/...` is not the source.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_task_tier.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py#_check_optional_task_id",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py#TaskCompletionEvidence",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#BackgroundRunner",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderRunValidationArgs"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Use the **exact same** widened shape TASK-4673 put in `models.py`, so the three
sites stay textually comparable:

```python
r"^(?:TASK-\d{1,5}|HOTFIX-[A-Za-z0-9][A-Za-z0-9._-]*-\d{1,5})$"
```

`optimization_models.py` keeps the bare-string form (`_TASK_ID_PATTERN`),
`background.py` keeps the compiled form (`_TASK_ID_RE`).

### Key Constraints

- **`Field(pattern=…)` is compiled by pydantic's Rust regex engine**, which
  rejects constructs Python's `re` accepts. The shape above uses no lookaround
  and no backreference, so it is portable — but AC 2 requires proving it by
  *instantiating `TaskCompletionEvidence`*, not by calling `re.match`.
- `background.py` uses `.match()` (prefix) while `models.py` uses
  `.fullmatch()`. The `$` anchor makes `.match()` total here — keep the anchor.
- Error texts are asserted by existing tests; run the regression suite and fix
  any assertion pinning the old string rather than weakening it.
- Do **not** touch `_FEATURE_ID_RE` (L80) — it is already correct.

### References in Codebase

- TASK-4673's `models.py` edit — the canonical wording of the widened regex
  and its `#:` comment.
- `scripts/sdd/brief_meta.py:181` — `brief_task_id()`.

---

## Implementation Blueprint

### Steps (in order)

1. Confirm TASK-4673 has landed (`grep HOTFIX packages/.../sdd_coder/models.py`)
   — the integration test in step 5 consumes its widened model and will fail
   confusingly otherwise.
2. Widen `optimization_models.py` (sites A and B).
3. Widen `background.py` (sites C and D).
4. Add the three `test_optimization_models.py` tests and the two
   `test_background_validation.py` tests.
5. Add the two-layer integration test to `test_background_task_tier.py`.
6. `ruff check` the four files, then run every Validation Command.

### `packages/.../sdd_coder/optimization_models.py` (MODIFY — site A)

```python
# occurrences: 1 (verified: grep -c '_TASK_ID_PATTERN = r"' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py)
# REPLACE the line `_TASK_ID_PATTERN = r"^TASK-\d{1,5}$"` (verified: optimization_models.py:31)
# Reserved `TASK-<NNN>` plus a brief's local `HOTFIX-<KEY>-<n>` (FEAT-698).
# Kept as a bare string, not a compiled pattern: `Field(pattern=...)` below
# needs the string form, and it is compiled by pydantic's Rust regex engine --
# so no lookaround or backreference may be introduced here.
_TASK_ID_PATTERN = r"^(?:TASK-\d{1,5}|HOTFIX-[A-Za-z0-9][A-Za-z0-9._-]*-\d{1,5})$"
```

**Why**: one constant covers both consumers (L88's validator and L209's
`Field`). The comment records the Rust-engine constraint so a later author does
not "improve" the pattern with a lookahead and break model construction at
import time.

### `packages/.../sdd_coder/optimization_models.py` (MODIFY — site B)

```python
# occurrences: 1 (verified: grep -c 'def _check_optional_task_id' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py)
# REPLACE the docstring and error text inside `def _check_optional_task_id` (verified: optimization_models.py:84-90)
def _check_optional_task_id(value: str | None) -> str | None:
    """Apply the `TASK-<1-5 digits>` / `HOTFIX-<KEY>-<1-5 digits>` shape only when a task_id is present."""
    if value is None:
        return value
    if not re.match(_TASK_ID_PATTERN, value):
        raise ValueError(f"invalid task id {value!r}; expected TASK-<1-5 digits> or HOTFIX-<KEY>-<1-5 digits>")
    return value
```

**Why**: same diagnostics argument as TASK-4673 — a message naming one legal
shape out of two misdirects whoever reads it.

### `packages/.../sdd_coder/background.py` (MODIFY — site C)

```python
# occurrences: 1 (verified: grep -c '_TASK_ID_RE = re.compile(' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py)
# REPLACE lines 76-78, i.e. the two `#:` comment lines above `_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")` and the line itself (verified: background.py:76-78)
#: Reserved `TASK-<NNN>` plus a brief's local `HOTFIX-<KEY>-<n>` (FEAT-698).
#: Same shape as `optimization_models._TASK_ID_PATTERN` and `models._TASK_ID_RE`
#: (not imported -- those modules' validators are private to their own field
#: declarations; keep the three in step by hand).
_TASK_ID_RE = re.compile(r"^(?:TASK-\d{1,5}|HOTFIX-[A-Za-z0-9][A-Za-z0-9._-]*-\d{1,5})$")
```

**Why**: this is the guard that `coder_run_validation` hits after the schema,
so leaving it closed would turn TASK-4673's fix into a rejection one layer
deeper. The comment keeps the existing "deliberately not imported" rationale
and extends it to name all three twins.

### `packages/.../sdd_coder/background.py` (MODIFY — site D)

```python
# occurrences: 1 (verified: grep -c "expected TASK-<1-5 digits> (never a foreign id)" packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py)
# REPLACE the raise at `raise ValueError(f"invalid task id {task_id!r}; expected TASK-<1-5 digits> (never a foreign id)")` (verified: background.py:566)
                raise ValueError(
                    f"invalid task id {task_id!r}; expected TASK-<1-5 digits>"
                    " or HOTFIX-<KEY>-<1-5 digits> (never a foreign id)"
                )
```

**Why**: "never a foreign id" is the point of the message and must survive —
`BRIEF-CS-228` is a *feature* id and is still foreign here, which is exactly
what `test_run_validation_rejects_foreign_task_id` pins.

### Test blocks

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py
# AFTER — append to the module.
BRIEF_TASK_ID = "HOTFIX-CS-228-3"


def test_optimization_field_pattern_accepts_brief_task_id():
    """Prove the widened pattern compiles under pydantic's Rust regex engine, not just `re`."""
    # FILL IN: build a minimal valid TaskCompletionEvidence with task_id=BRIEF_TASK_ID —
    # bounded by AC 2. Read the model's other required fields (feature_slug,
    # implementation_sha, validation_refs, review_evidence, completion_facts)
    # from optimization_models.py:205-213 and reuse whatever EvidenceRef factory
    # this test module already defines; do not invent one.
    ...
```

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_task_tier.py
# AFTER — append to the module.
def test_task_tier_schema_and_runner_guard_agree():
    """Schema admits tier='task'; the ENGINE, not the schema, rejects a missing attempt_uid."""
    # FILL IN: (1) CoderRunValidationArgs(..., tier="task", task_ids=[<one id>])
    #              parses with attempt_uid omitted — bounded by AC 4.
    #          (2) BackgroundRunner.run_validation with that same payload raises
    #              ValueError matching "requires an explicit base_ref" —
    #              bounded by AC 4 and the Non-Goal that the model must not
    #              duplicate the engine's rule.
    # Reuse this module's existing runner/tmp-worktree fixture; do not build a
    # new BackgroundRunner by hand.
    ...
```

**Why**: the integration test is the only place the two layers are checked
*together*, which is precisely the drift `issue:146f4be4ee6d` reported.

### FILL IN checklist

- [ ] `test_optimization_validator_accepts_brief_task_id` — the L88 path;
      bounded by AC 1.
- [ ] `test_optimization_field_pattern_accepts_brief_task_id` — the L209
      `Field` path, by model instantiation; bounded by AC 2.
- [ ] `test_optimization_field_pattern_still_rejects` — `"nope"`, `"HOTFIX-"`;
      bounded by AC 1.
- [ ] `test_run_validation_accepts_brief_task_id` — reaches the *next* guard,
      not the id error; bounded by AC 3.
- [ ] `test_run_validation_rejects_foreign_task_id` — `["BRIEF-CS-228"]` still
      raises, message contains `invalid task id`; bounded by AC 3.
- [ ] `test_task_tier_schema_and_runner_guard_agree` — bounded by AC 4.
- [ ] Any existing assertion pinning the old error strings — update, don't weaken.

---

## Acceptance Criteria

1. `_check_optional_task_id` accepts `HOTFIX-CS-228-3`, still returns `None`
   for `None`, and still rejects `"nope"` / `"HOTFIX-"`.
2. `TaskCompletionEvidence(task_id="HOTFIX-CS-228-3", …)` constructs — proving
   the pattern is valid for pydantic's `Field(pattern=…)` engine — and
   `task_id="nope"` still raises `ValidationError`.
3. `BackgroundRunner.run_validation` passes its id guard for
   `["HOTFIX-CS-228-1"]` and still raises `ValueError` containing
   `invalid task id` for `["BRIEF-CS-228"]`.
4. The two-layer test shows `CoderRunValidationArgs` admitting `tier="task"`
   while `run_validation` still rejects the same payload for a missing
   `base_ref`/`attempt_uid` — the obligation stayed in the engine.
5. `_FEATURE_ID_RE` (`background.py:80`) is byte-identical to before.
6. Every command in **Validation Commands** exits 0 with no test deleted or
   weakened.
7. `models.py`, `toolkit.py`, `engine.py`, `complexity_collectors.py` and
   anything under `build/` are unchanged by this task.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_task_tier.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py -q`

## Test Specification

| File | Test | Asserts |
|---|---|---|
| `test_optimization_models.py` | `test_optimization_validator_accepts_brief_task_id` | L88 validator accepts `HOTFIX-CS-228-3` |
| `test_optimization_models.py` | `test_optimization_field_pattern_accepts_brief_task_id` | `TaskCompletionEvidence` constructs (Rust engine proof) |
| `test_optimization_models.py` | `test_optimization_field_pattern_still_rejects` | `"nope"`, `"HOTFIX-"` raise |
| `test_background_validation.py` | `test_run_validation_accepts_brief_task_id` | id guard passes, next guard reached |
| `test_background_validation.py` | `test_run_validation_rejects_foreign_task_id` | `["BRIEF-CS-228"]` raises `invalid task id` |
| `test_background_task_tier.py` | `test_task_tier_schema_and_runner_guard_agree` | schema admits, engine enforces |

Run with `PYTHONPATH=packages/ai-parrot/src`. Reuse the existing fixtures in
each test module; add none.

## Agent Instructions

1. Verify TASK-4673 landed before writing the integration test.
2. Verify every contract line in the source; a moved anchor is re-located, a
   **missing** anchor is reported as drift, never invented.
3. Edit only the five files in the table. Never touch `_FEATURE_ID_RE`.
4. Use the identical widened shape TASK-4673 used — three textually comparable
   declarations, no shared module, no cross-module import.
5. `ruff check` the four changed source/test files, then run all four
   Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit as `feat(sdd-coder-models-fixes): TASK-4674 — optimization_models and background accept brief task ids`.

## Completion Note

**Verified**, 2026-10-24.

Four edit sites applied:
- `optimization_models._TASK_ID_PATTERN` widened (bare string kept, with a
  comment recording the Rust-regex-engine constraint), plus
  `_check_optional_task_id`'s docstring and error text.
- `background._TASK_ID_RE` widened; its comment now names all three twins and
  keeps the "deliberately not imported" rationale. The error at the guard
  names both shapes while preserving "(never a foreign id)".

**Naming correction to this task's Context/AC 3.** The task file said the
guard lives in `BackgroundRunner.run_validation`. The class is actually
`ValidationSupervisor` and the method is `start()` (`background.py`); the
engine's `run_validation` delegates to it. Same code, same line, wrong class
name in the task text — the implementation and tests target the real symbol.

Tests added (11 cases over 3 files):
- `test_optimization_models.py`: validator accept/reject and the
  `Field(pattern=...)` path proved by constructing `TaskCompletionEvidence`
  (AC 2) — this is the one that actually exercises pydantic's Rust engine.
- `test_background_validation.py`: `test_run_validation_accepts_brief_task_id`
  plus a 4-case parametrized rejection including `BRIEF-CS-228`.
- `test_background_task_tier.py`:
  `test_task_tier_schema_and_runner_guard_agree` — the schema parses
  `tier='task'` with and without `attempt_uid`, and the supervisor still
  raises `explicit base_ref` for the same payload, with no spawn (AC 4).

One self-inflicted red along the way: the first `TaskCompletionEvidence`
fixture used `implementation_sha="abc123"`, which that model rejects — it
needs a full 40-hex SHA. Fixed by reusing the module's `_FULL_SHA_A`; the
regex was never the failure.

Evidence:
- `pytest` over this task's four Validation Commands → **34 passed**
- Whole FEAT-736 validation contract (9 files) → **150 passed**
- `ruff check` on the four changed source/test files → clean

AC 5 confirmed: `_FEATURE_ID_RE` appears in the diff as context only.
AC 7 confirmed: `models.py`, `toolkit.py`, `engine.py`,
`complexity_collectors.py` and `build/` are untouched by this task.
