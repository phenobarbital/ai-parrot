---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, dev-loop]
tags: [sdd-coder, mcp, validation, brief, hotfix, task-id, feat-709, feat-698]
---

# Feature Specification: The sdd_coder MCP surface accepts every id and tier its engine already accepts

**Feature ID**: FEAT-736
**Date**: 2026-10-24
**Author**: Jesus Lara (via `/sdd-fix`, from `fixgroup:5a49675ceac2`)
**Status**: approved
**Target version**: 1.3.x

> **Slug note.** The file is `sdd-coder-models-fixes` because `/sdd-fix`
> requires the planner's `suggested_slug` verbatim. The planner derived it
> from the group's shared file (`sdd_coder/models.py`); the feature is a
> little wider than that one file, as §1 shows.

---

## 1. Motivation & Business Requirements

### Problem Statement

Two `major` ledger issues say the same thing about the `sdd_coder`
orchestration kernel: **its argument models are narrower than its own
engine.** A caller that goes through the MCP / tool surface is rejected for
a request the engine underneath would have accepted and executed.

**`issue:0ea4f0acaefd` — brief task ids (`feature_gap`, from FEAT-698).**
FEAT-698 gave briefs their own id space: a brief's per-brief index is keyed
`BRIEF-<KEY>` and its tasks carry *local, unreserved* ids
`HOTFIX-<KEY>-<n>` (`scripts/sdd/brief_meta.py:184`, `brief_task_id`).
FEAT-698 widened `background.py`'s `_FEATURE_ID_RE` to admit `BRIEF-*`
(`background.py:80`) but left every **task**-id regex at the closed
`^TASK-\d{1,5}$` shape. So any `coder_*` call carrying a brief task id
fails validation before it reaches the engine, and `/sdd-brief --split`
cannot use the MCP coder path at all — briefs are stuck on the
single-agent / manual lane.

**`issue:146f4be4ee6d` — `tier='task'` (`bug`, from FEAT-709).**
FEAT-709 added a per-task validation tier. `engine.run_validation()`
(`engine.py:1205-1217`) takes `tier: Literal["task", "merge", "feature"]`
plus `attempt_uid`, `BackgroundRunner`'s own guard admits `'task'`
(`background.py:550-555`), and `toolkit.coder_run_validation()`
(`toolkit.py:602-612`) declares the three-value tier and the
`attempt_uid` parameter. But `CoderRunValidationArgs` — the model the
toolkit's `_pre_execute` schema check applies to that very tool
(`toolkit.py:102`) — still has `tier: Literal["merge", "feature"]`, no
`attempt_uid` field, and `extra="forbid"` from `_Args`. The schema gate
therefore rejects a call the method signature advertises. It was reported
by the TASK-4532 coder, which could not fix it: `models.py` was outside
its task's file list.

Both are the same failure mode — a validation layer that drifted behind the
layer it guards — so they share one spec, and the planner grouped them on
their shared file.

### Goals

1. Every task-id validator in the `sdd_coder` package accepts a brief task
   id `HOTFIX-<KEY>-<n>` in addition to `TASK-<NNN>`, and keeps rejecting
   anything that is neither.
2. `CoderRunValidationArgs` accepts exactly what
   `toolkit.coder_run_validation` / `engine.run_validation` accept:
   `tier='task'` and an optional `attempt_uid`.
3. `test_scope/report.py`'s `_safe_id` path gate accepts brief ids
   (`BRIEF-<KEY>` features, `HOTFIX-<KEY>-<n>` tasks) so brief validation
   junit reports stop collapsing into one shared `_invalid/` directory —
   while still refusing anything unsafe as a path component.
4. Each widened site has a test that drives it with a brief id / the
   `'task'` tier, and a test that still rejects a bad id.

### Non-Goals (explicitly out of scope)

- **No new shared regex module.** `background.py:76-78` deliberately
  re-declares the shape rather than importing it ("that module's
  validators are private to its own field declarations"). That choice
  stands; each site is widened in place and keeps a comment naming its
  twins. De-duplicating the `sdd_coder` constants is already its own open
  ledger issue (`issue:6da9094f951b`) and is not touched here.
- **No change to engine semantics.** `tier='task'` keeps requiring exactly
  one id, a `base_ref` and an `attempt_uid`; this feature only stops the
  *schema* from refusing the request first.
- **No FEAT/TASK id allocation for briefs.** Brief task ids stay local and
  unreserved — this feature accepts them, it does not register them.
- **`complexity_collectors.py:177`** (`re.search(r"(TASK-\d+)", line)`) is
  a best-effort scrape of a log line for telemetry, not an input gate. Out
  of scope.
- **No `parrot/flows/dev_loop/sdd_coder` API renames**, and nothing under
  `packages/ai-parrot/build/` (a stale build artifact tree).

---

## 2. Architectural Design

### Overview

One canonical widened shape, declared independently at each gate:

```
TASK-<1..5 digits>                     the reserved id space (unchanged)
HOTFIX-<KEY>-<1..5 digits>             a brief's local task id (new)
```

`<KEY>` is a brief key as `scripts/sdd/brief_meta.py` already validates it
(`_SAFE_REF_RE = ^[A-Za-z0-9][A-Za-z0-9._-]*$`, plus: no `..`, no trailing
`.`, no `.lock` suffix). The regex at each gate admits that character set:

```python
_TASK_ID_RE = re.compile(r"^(?:TASK-\d{1,5}|HOTFIX-[A-Za-z0-9][A-Za-z0-9._-]*-\d{1,5})$")
```

A brief key may itself end in digits (`CS-228` → `HOTFIX-CS-228-1`); the
trailing `-\d{1,5}` anchor plus backtracking matches that correctly, and a
test pins it.

**One deliberate divergence.** `test_scope/report.py::_safe_id` does not
validate an id, it decides whether a value is safe as a *filesystem path
component*. `[A-Za-z0-9._-]*` admits `..`, so the generic shape must not be
pasted there. That site gets a dot-free key class instead:

```python
_SAFE_ID_RE = re.compile(
    r"^(?:FEAT-\d+|TASK-\d+|BRIEF-[A-Za-z0-9][A-Za-z0-9_-]*|HOTFIX-[A-Za-z0-9][A-Za-z0-9_-]*-\d+|_rerun)$"
)
```

A brief key containing a `.` therefore keeps falling back to `_invalid`
(safe, and no worse than today) while every ordinary key gets its own
directory. This is the only site where the two shapes differ, and the
difference is commented there.

### Component Diagram

```
MCP / tool call
      │
      ▼
SDDCoderToolkit._pre_execute ──► _ARG_MODELS["coder_run_validation"]
      │                             = CoderRunValidationArgs   ← M2 (tier='task', attempt_uid)
      │                          _check_task_id / _check_task_ids ← M1 (models.py)
      ▼
SDDCoderToolkit.coder_run_validation   (already correct)
      │
      ▼
SDDCoderEngine.run_validation          (already correct)
      │
      ▼
BackgroundRunner.run_validation ──► _TASK_ID_RE  ← M1 (background.py)
      │
      ▼
select_tests / ValidationSupervisor ──► report.junit_path_for ──► _safe_id ← M3
                                              │
                                              ▼
                                   <root>/<feature>/<task>/<suite>-<n>.xml
                                   (today: _invalid/_invalid/… for every brief task)

optimization_models.{_TASK_ID_PATTERN, task_id Field} ← M1  (done-optimization contracts)
```

### Integration Points

| Caller | Today | After |
|---|---|---|
| `/sdd-brief --split` → `coder_run_chunk` / `coder_prepare_native` | `ValueError: invalid task id 'HOTFIX-…'` | admitted |
| FEAT-709 per-task validation over MCP | `extra="forbid"` / tier rejection | admitted |
| brief junit report paths | all under `_invalid/_invalid/` | one directory per brief feature + task |

### Data Models

No new models. One field added, one field widened:

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class CoderRunValidationArgs(_Args):
    tier: Literal["task", "merge", "feature"]        # was ["merge", "feature"]
    attempt_uid: Optional[str] = None                # new; required by the engine only for tier='task'
    _attempt_uuid = field_validator("attempt_uid")(_check_uuid_optional)
```

`attempt_uid` is validated as a UUID **only when present** — the engine,
not the schema, owns the "`tier='task'` requires it" rule (§1, Non-Goals).
`_check_uuid_optional` is a new one-line private helper beside
`_check_uuid`, mirroring the existing `_require_utc` / `_require_utc_optional`
pair in the same module.

### New Public Interfaces

None. Every change is a private module-level constant, a private validator,
or a field on an existing argument model.

---

## 3. Module Breakdown

### Module 1: Widen the task-id gates (`issue:0ea4f0acaefd`)

Three real source sites (the `build/` copy is a stale artifact and is left
alone):

1. **`sdd_coder/models.py:111`** — `_TASK_ID_RE`. Feeds `_check_task_id`
   (line 627) and `_check_task_ids` (634), wired as field validators at
   lines 672 (`CoderRunChunkArgs.task_ids`), 682
   (`CoderPrepareNativeArgs.task_id`), 826
   (`CoderRunValidationArgs.task_ids`) and 857
   (`NativeObservation.task_id`). Widening the constant fixes all four.
   The error message in `_check_task_id` (line 630) and the docstring
   (628) must name both accepted shapes.
2. **`sdd_coder/optimization_models.py:31`** — `_TASK_ID_PATTERN`, used by
   the validator at line 88 and as a pydantic `Field(pattern=…)` at line
   209. A `Field(pattern=…)` is applied by `rust-regex`, which does not
   support backtracking the same way; the pattern above uses no
   backreferences or lookarounds, so it is portable — but the test suite
   must assert the `Field`-level case too (M1's test for line 209), not
   only the validator.
3. **`sdd_coder/background.py:78`** — `_TASK_ID_RE`, used in
   `run_validation`'s guard at line 565. Update the cross-reference
   comment at 76-77 and the error text at 566.

Each of the three keeps its own declaration and a comment naming the other
two.

### Module 2: `CoderRunValidationArgs` admits `tier='task'` (`issue:146f4be4ee6d`)

In `sdd_coder/models.py`:

- Add `_check_uuid_optional(v: Optional[str]) -> Optional[str]` beside
  `_check_uuid` (line 115): returns `None` unchanged, otherwise delegates
  to `_check_uuid`.
- `CoderRunValidationArgs` (line 815): widen `tier` to
  `Literal["task", "merge", "feature"]`, add
  `attempt_uid: Optional[str] = None` with the optional-UUID validator, and
  extend the class docstring to say that the per-tier obligations
  (`tier='task'` ⇒ exactly one id + `attempt_uid` + engine-supplied
  `base_ref`) are enforced by the engine, not by this model.

### Module 3: Brief-aware junit report paths

In `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py`:

- Widen `_SAFE_ID_RE` (line 80) to the dot-free class in §2, admitting
  `BRIEF-<KEY>` feature ids and `HOTFIX-<KEY>-<n>` task ids alongside
  `FEAT-<NNN>`, `TASK-<NNN>` and the existing `_rerun` sentinel.
- Add a comment stating *why* this site's key class excludes `.` and `..`
  (it is a path component, not an id) and pointing at `sdd_coder`'s wider
  twins.
- `_safe_id` (line 85) and `junit_path_for` (line 88) keep their current
  behaviour and signatures; only the admitted set changes. Note
  `_SAFE_ID_RE.match` is a prefix match, not `fullmatch` — keep the
  trailing `$` in the pattern (it is already there) so this stays a full
  match.

### Module 4: Record the decision

Append one `wikitoolkit remember` entry (category `decision`) recording
that `sdd_coder` task-id gates admit brief ids, that the four declarations
stay deliberately separate per `background.py:76-77`, and that
`report.py`'s gate is intentionally stricter because it builds a path.

---

## 4. Test Specification

All tests run with `PYTHONPATH=packages/ai-parrot/src`.

### Unit Tests

**`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py`** (extend)

| Test | Asserts |
|---|---|
| `test_chunk_args_accept_brief_task_ids` | `CoderRunChunkArgs(feature="BRIEF-CS-228", worktree="/abs", task_ids=["HOTFIX-CS-228-1"], execution_id=VALID_UUID).task_ids == ["HOTFIX-CS-228-1"]` |
| `test_prepare_native_accepts_brief_task_id` | `CoderPrepareNativeArgs(..., task_id="HOTFIX-CS-228-12")` parses |
| `test_brief_key_ending_in_digits` | `HOTFIX-CS-228-1` parses and `task_id` round-trips verbatim (the backtracking case) |
| `test_task_id_still_rejects_foreign_ids` | each of `"nope"`, `"HOTFIX-1"`, `"HOTFIX--1"`, `"HOTFIX-CS-228-"`, `"HOTFIX-CS-228-123456"`, `"TASK-123456"`, `"hotfix-cs-228-1"` raises `ValidationError` |
| `test_run_validation_args_accept_task_tier` | `CoderRunValidationArgs(..., tier="task", attempt_uid=VALID_UUID)` parses; `.attempt_uid == VALID_UUID` |
| `test_run_validation_args_tier_task_without_attempt_uid_parses` | the model does **not** enforce the engine's obligation: `attempt_uid` omitted still parses (and the engine's own test covers the rejection) |
| `test_run_validation_args_reject_bad_attempt_uid` | `attempt_uid="not-a-uuid"` raises `ValidationError` |
| `test_run_validation_args_reject_unknown_tier` | `tier="whatever"` raises `ValidationError` |

**`.../sdd_coder/test_optimization_models.py`** (extend)

| Test | Asserts |
|---|---|
| `test_optimization_validator_accepts_brief_task_id` | the line-88 validator path accepts `HOTFIX-CS-228-3` |
| `test_optimization_field_pattern_accepts_brief_task_id` | the line-209 `Field(pattern=…)` model parses `HOTFIX-CS-228-3` — proves the pattern is valid under pydantic's regex engine |
| `test_optimization_field_pattern_still_rejects` | `"nope"` / `"HOTFIX-"` raise `ValidationError` |

**`.../sdd_coder/test_background_validation.py`** (extend)

| Test | Asserts |
|---|---|
| `test_run_validation_accepts_brief_task_id` | `BackgroundRunner.run_validation` passes its id guard for `["HOTFIX-CS-228-1"]` (reaching the next guard, not the id error) |
| `test_run_validation_rejects_foreign_task_id` | `["BRIEF-CS-228"]` still raises `ValueError` matching `invalid task id` |

**`packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py`** (extend)

| Test | Asserts |
|---|---|
| `test_junit_path_for_brief_ids` | `junit_path_for("BRIEF-CS-228", "HOTFIX-CS-228-1", "one", 1)` contains `BRIEF-CS-228/HOTFIX-CS-228-1` and no `_invalid` |
| `test_junit_path_for_brief_tasks_do_not_collide` | two different brief task ids produce two different parent directories |
| `test_junit_path_for_rejects_traversal` | `"../etc"`, `"a/b"`, `"HOTFIX-a..b-1"` and `"BRIEF-a..b"` all still map to `_invalid` |
| `test_junit_path_for_keeps_rerun_sentinel` | `_rerun` is still admitted |

### Integration Tests

**`.../sdd_coder/test_background_task_tier.py`** (extend) — one test that
drives the `tier='task'` path through `CoderRunValidationArgs` first
(schema) and then the runner guard, proving the two layers now agree:
schema-valid input with a missing `attempt_uid` is rejected by the
*engine* with its own message, not by the schema.

### Validation Contract

```bash
# Module 1 + 2
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py -q
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_models.py -q
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_task_tier.py -q
# Module 3
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py -q
# Regression: the contract suites that pin these models' shapes
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py -q
# Lint
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py
```

### Test Data / Fixtures

No new fixtures. `test_models.py` already defines `VALID_UUID`; brief ids
are literals. `report.py` tests use the existing `tmp_path` /
`REPORT_ROOT_ENV` override pattern already in `test_report.py:219`.

---

## 5. Acceptance Criteria

1. `CoderRunChunkArgs`, `CoderPrepareNativeArgs`,
   `CoderRunValidationArgs` and `NativeObservation` all accept
   `HOTFIX-<KEY>-<n>` task ids and still reject a non-matching id.
2. `optimization_models`' validator **and** its `Field(pattern=…)` both
   accept a brief task id; the pattern is accepted by pydantic's regex
   engine (proved by a model instantiation, not by `re` alone).
3. `BackgroundRunner.run_validation` admits a brief task id and still
   rejects a foreign id with `invalid task id` in the message.
4. `CoderRunValidationArgs(tier="task", attempt_uid=<uuid>)` parses; an
   unknown tier and a non-UUID `attempt_uid` still raise.
5. `report.junit_path_for` gives a brief feature/task its own directory
   pair, two brief tasks never share a directory, and `..`, `/` and a
   dotted key still map to `_invalid`.
6. Every command in §4's Validation Contract exits 0.
7. No site re-uses the dotted key class for a path component, and no new
   shared-regex module was introduced.
8. Both ledger issues are closed by `/sdd-done` via tasks carrying
   `**Discovered-from**: issue:0ea4f0acaefd` / `issue:146f4be4ee6d`.

---

## 6. Codebase Contract

### Verified Imports

```python
# all verified present on dev @ 77ff25da8, 2026-10-24
from parrot.flows.dev_loop.sdd_coder.models import (
    CoderRunChunkArgs, CoderPrepareNativeArgs, CoderRunValidationArgs, NativeObservation,
)
from parrot.flows.dev_loop.test_scope import report          # report.junit_path_for, report.report_root
from scripts.sdd.brief_meta import brief_task_id, BRIEF_ID_PREFIX   # id shapes this feature admits
```

### Existing Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")                        # L111
def _check_uuid(v: str) -> str: ...                                # L115
def _check_task_id(v: str) -> str: ...                             # L627
def _check_task_ids(vs: List[str]) -> List[str]: ...               # L634
class CoderRunValidationArgs(_Args):                               # L815
    feature: str
    worktree: str
    execution_id: str = Field(..., min_length=1)
    task_ids: List[str] = Field(..., min_length=1)
    tier: Literal["merge", "feature"]                              # L822  ← widen
    timeout_seconds: int = Field(..., ge=1, le=7200)
    request_id: str = Field(..., min_length=1)
    _wt = field_validator("worktree")(_check_abs)
    _tids = field_validator("task_ids")(_check_task_ids)
    _exec = field_validator("execution_id")(_check_uuid)

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py
_TASK_ID_PATTERN = r"^TASK-\d{1,5}$"                               # L31
# used: re.match(_TASK_ID_PATTERN, value)  L88 ; task_id: str = Field(pattern=_TASK_ID_PATTERN)  L209

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
_TASK_ID_RE = re.compile(r"^TASK-\d{1,5}$")                        # L78
_FEATURE_ID_RE = re.compile(r"^(?:FEAT-\d+|BRIEF-[A-Za-z0-9][A-Za-z0-9._-]*)$")   # L80 (already brief-aware)
# used: if not _TASK_ID_RE.match(task_id): raise ValueError(...)   L565-566

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
async def run_validation(self, feature: str, worktree: str, execution_id: str,
                         task_ids: List[str], tier: Literal["task", "merge", "feature"],
                         timeout_seconds: int, request_id: str, *,
                         attempt_uid: Optional[str] = None,
                         base_ref: Optional[str] = None) -> BackgroundRegistration: ...   # L1205

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py
_ARG_MODELS = {... "coder_run_validation": CoderRunValidationArgs}                   # L102
async def coder_run_validation(self, feature: str, worktree: str, execution_id: str,
                               task_ids: List[str], tier: Literal["task", "merge", "feature"],
                               timeout_seconds: int, request_id: str,
                               attempt_uid: Optional[str] = None) -> CoderResult: ... # L602

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py
_SAFE_ID_RE = re.compile(r"^(?:FEAT-\d+|TASK-\d+|_rerun)$")        # L80  ← widen
def _safe_id(value: str) -> bool: ...                              # L85
def junit_path_for(feature_id: str, task_id: str, suite: str, ordinal: int) -> Path: ...  # L88

# scripts/sdd/brief_meta.py — the id space being admitted
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")         # L28 (+ no `..`, no trailing `.`, no `.lock`)
BRIEF_ID_PREFIX = "BRIEF-"                                         # L25
def brief_task_id(meta: BriefMeta, n: int) -> str: ...             # L181 → f"HOTFIX-{meta.key}-{n}"
```

### Integration Points

- `toolkit.py:102` `_ARG_MODELS` binds `CoderRunValidationArgs` to the
  `coder_run_validation` tool — the model is the schema gate, so M2 is what
  unblocks the MCP call. `toolkit.py` itself needs **no** edit.
- `background.py:550-555` already enforces the `tier='task'` obligations;
  M2 must not duplicate them in the model.

### Does NOT Exist (Anti-Hallucination)

- There is **no** shared `sdd_coder` id-regex module, and this feature does
  not add one. Do not import `_TASK_ID_RE` across modules.
- There is **no** `_check_uuid_optional` in `models.py` yet — M2 adds it.
  (`_require_utc_optional` does exist, at `models.py` beside `_require_utc`;
  it is the naming precedent, not the implementation.)
- There is **no** `_SAFE_ID_RE` in `sdd_coder/` — the one named in the
  ledger body lives in `test_scope/report.py:80`. (The `_SAFE_ID_RE` copies
  under `packages/ai-parrot-server/src/parrot/e2e/` are a different feature
  and must not be touched.)
- `attempt_uid` does **not** exist on `CoderRunValidationArgs` today.
- `packages/ai-parrot/build/lib.linux-x86_64-cpython-312/...` is a stale
  build tree. Never edit it; it is not the source.

### Edit Sites (Blueprint Anchors)

| File | Anchor | Change |
|---|---|---|
| `…/sdd_coder/models.py` | `_TASK_ID_RE = re.compile(` (L111) | widen |
| `…/sdd_coder/models.py` | `def _check_uuid(v: str) -> str:` (L115) | add `_check_uuid_optional` after it |
| `…/sdd_coder/models.py` | `def _check_task_id(v: str) -> str:` (L627) | docstring + error text |
| `…/sdd_coder/models.py` | `class CoderRunValidationArgs(_Args):` (L815) | tier + `attempt_uid` + validator |
| `…/sdd_coder/optimization_models.py` | `_TASK_ID_PATTERN = r"` (L31) | widen |
| `…/sdd_coder/background.py` | `_TASK_ID_RE = re.compile(` (L78) | widen + comment L76-77 |
| `…/sdd_coder/background.py` | `raise ValueError(f"invalid task id {task_id!r}` (L566) | error text |
| `…/test_scope/report.py` | `_SAFE_ID_RE = re.compile(` (L80) | widen (dot-free class) + comment |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Keep `re.compile(...)` at module level, one per module, with the
  existing `#:` comment style.
- Google-style docstrings, strict type hints, 120 columns, `black`
  formatting (`.claude/rules/codebase-conventions.md`).
- `_check_uuid_optional` mirrors `_require_utc_optional`: a two-line
  `None`-passthrough wrapper, nothing more.
- Error messages name **both** accepted shapes, e.g.
  `expected TASK-<1-5 digits> or HOTFIX-<KEY>-<1-5 digits>`.

### Known Risks / Gotchas

1. **`Field(pattern=…)` uses pydantic's Rust regex engine**, not Python's
   `re`. The chosen pattern is plain (no lookaround, no backreference) so
   it compiles there — but `optimization_models.py:209` must be proved by
   instantiating the model in a test, not by `re.match` alone. This is AC 2.
2. **`_SAFE_ID_RE.match` is a prefix match.** The pattern's trailing `$`
   is what makes it total; do not drop it while editing.
3. **Path safety.** Never paste the dotted `[A-Za-z0-9._-]` class into
   `report.py` — `..` would become a usable path component. The two shapes
   differ on purpose (§2).
4. **Error-message assertions.** Existing tests may match on
   `"expected TASK-<1-5 digits>"`. Changing the text can turn a passing
   test red; run the regression suites in §4 and update any assertion that
   pins the old string.
5. **Worktree test imports.** The shared `.venv` is editable-installed
   against the main checkout — always prefix with
   `PYTHONPATH=packages/ai-parrot/src` inside the worktree
   (`.claude/rules/worktree-management.md`).
6. **Do not touch** `packages/ai-parrot/build/…` or
   `packages/ai-parrot-server/src/parrot/e2e/`.

### External Dependencies

None. `pydantic` v2 and the stdlib `re` are already in use at every site.

---

## 8. Open Questions

None blocking. Both issues name their fix sites, and every site was
verified in the source at `dev @ 77ff25da8` while writing §6.

One decision taken rather than asked: `report.py`'s key class excludes `.`
while `sdd_coder`'s admits it. Rationale is in §2 and commented at the edit
site; the alternative (one identical regex everywhere) would make `..` a
legal path component, which is strictly worse.

---

## 9. Provenance

| Source | Detail |
|---|---|
| `/sdd-fix` group | `fixgroup:5a49675ceac2`, lane `sdd`, `max_severity: major`, `suggested_slug: sdd-coder-models-fixes` |
| `issue:0ea4f0acaefd` | `feature_gap`/`major`, discovered from `spec:FEAT-698`, opened 2026-10-17 by `agent:mcp` |
| `issue:146f4be4ee6d` | `bug`/`major`, discovered from `spec:FEAT-709`, opened 2026-10-20 by `agent:mcp` |
| Parent specs | FEAT-698 (closed 2026-10-17), FEAT-709 (closed 2026-10-20) — neither open, so this is a new spec, not a reused parent |
| Planner | `wikitoolkit ledger plan-fix --json`, `planner_version: 1`, 2026-10-24 |
