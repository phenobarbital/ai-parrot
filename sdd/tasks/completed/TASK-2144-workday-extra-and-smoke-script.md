# TASK-2144: `workday` pyproject extra + manual smoke script

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2136, TASK-2137, TASK-2138, TASK-2139, TASK-2140, TASK-2141
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of the spec, and closes the feature.

Two loose ends:

1. **Undeclared dependencies.** `ai-parrot-tools` declares only
   `ai-parrot`, `PyGithub` and `ddgs`. The Workday interface actually needs
   `zeep` (SOAP), `pandas` (the `fetch()` DataFrame surface) and — after
   TASK-2138 — `aiohttp`. All three arrive transitively via `ai-parrot`,
   which works but is implicit. Every other tool in this package declares
   its own extra (`jira`, `slack`, `aws`, `excel`, …); Workday should too.

2. **No live-tenant verification.** CI is entirely mock-based — there is no
   Workday tenant available to it. The `aiohttp` rewrite in TASK-2138 in
   particular was never exercised against the real API (flowtask's `httpx`
   original was). A maintainer-run smoke script closes that gap on demand
   without ever touching CI.

---

## Scope

- Add a `workday` extra to `packages/ai-parrot-tools/pyproject.toml` under
  `[project.optional-dependencies]`, following the existing extras style:
  ```toml
  workday = ["zeep[async]>=4.3.3", "pandas>=2.0", "aiohttp>=3.9"]
  ```
  (Match the `zeep[async]==4.3.3` pin already used in
  `packages/ai-parrot/pyproject.toml:280` — align rather than conflict.)
- Create a manual smoke script under `examples/` that exercises the ported
  surface against a real implementation tenant:
  - `WorkdayConfig(env="sandbox")` resolution
  - SOAP endpoint host rewrite actually pointing at the sandbox host
  - a read via `WorkdayService.fetch(...)`
  - a `WorkdayRestClient.find_worker(...)` + `get_time_clock_events(...)` round trip
  - optionally a write + read-back verification of a clock event
- The script MUST:
  - require explicit opt-in (env var or CLI flag) before doing anything
  - never be collected by pytest (do not name it `test_*.py`, do not place
    it under `tests/`)
  - print what it is about to do and refuse to run write operations unless
    separately confirmed
  - carry a header comment stating it is maintainer-run-only and never CI
- Document the extra and the smoke script briefly (README or module docstring).

**NOT in scope**:
- Wiring the smoke script into CI in any form.
- Adding a `workday` extra to `packages/ai-parrot/pyproject.toml` (the core
  package already pins `zeep`).
- Any further interface change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | Add the `workday` extra under `[project.optional-dependencies]` |
| `examples/workday_homologation_smoke.py` | CREATE | Maintainer-run smoke script (never CI) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.interfaces.workday.config import WorkdayConfig    # verified: config.py:112
from parrot_tools.interfaces.workday.service import WorkdayService  # verified: service.py:118
from parrot_tools.interfaces.workday.rest import WorkdayRestClient  # CREATED BY TASK-2138
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/service.py
class WorkdayService(SOAPClient):                                              # line 118
    async def fetch(self, operation_type: str, **params: Any) -> pd.DataFrame: # line 280
    async def fetch_models(self, operation_type: str, **params: Any) -> list:  # line 305
    async def put_time_clock_events(...)                                       # line 378
    async def start(self, **_kwargs: Any) -> None:                             # line 465
    async def close(self) -> None:                                             # line 469
```

### Existing pyproject structure (verified)

```toml
# packages/ai-parrot-tools/pyproject.toml
[project]
dependencies = [
    "ai-parrot>=0.25.31",
    "PyGithub>=2.1",
    "ddgs>=9.5.2",
]

[project.optional-dependencies]
# Existing extras follow this exact style — match it:
jira = ["jira>=3.10"]
slack = ["slack-sdk>=3.0"]
aws = ["boto3>=1.28"]
analysis = ["pandas>=2.0", "numpy>=1.26", "autoviz>=0.1"]
excel = ["openpyxl>=3.1", "odfpy>=1.4"]
```

```toml
# packages/ai-parrot/pyproject.toml:280 — the existing zeep pin to align with
"zeep[async]==4.3.3",
```

### Does NOT Exist

- ~~a `workday` extra in `packages/ai-parrot-tools/pyproject.toml`~~ — this task creates it
- ~~`zeep` / `pandas` / `aiohttp` as *direct* dependencies of `ai-parrot-tools`~~ — currently transitive only
- ~~`httpx` as a declared dependency~~ — present only transitively via `httpx-sse`; do not add it
- ~~an existing Workday smoke/example script~~ — `packages/ai-parrot/examples/workday_checkin.py` and `examples/tool/workday.py` exist but are toolkit examples, not a homologation smoke test. Do not overwrite either.
- ~~a CI job that runs against a live Workday tenant~~ — none exists and none may be added

---

## Implementation Notes

### Key Constraints
- **The smoke script must never run in CI.** Not named `test_*`, not under `tests/`, gated behind explicit opt-in, and write operations gated a second time.
- Use explicit `start()`/`close()` on `WorkdayService` — ai-parrot's `SOAPClient` has **no** `__aenter__`/`__aexit__`.
- `WorkdayRestClient` needs its `close()` called; do not leak an aiohttp session.
- Never hardcode credentials in the script — read from `parrot.conf` / env.
- Align the `zeep` spec with the core pin rather than introducing a conflicting range.
- Google-style docstrings; module logger or explicit prints are acceptable in an example script, but no secrets in output.

### References in Codebase
- `packages/ai-parrot/examples/workday_checkin.py` — existing Workday example for tone/shape
- `packages/ai-parrot-tools/pyproject.toml` `[project.optional-dependencies]` — extras style to match

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-tools/pyproject.toml` declares a `workday` extra with `zeep`, `pandas` and `aiohttp`
- [ ] The `zeep` spec is compatible with the `zeep[async]==4.3.3` pin in `packages/ai-parrot/pyproject.toml:280`
- [ ] `uv pip install -e 'packages/ai-parrot-tools[workday]'` resolves cleanly
- [ ] `examples/workday_homologation_smoke.py` exists and exercises config env resolution, the endpoint rewrite, a SOAP read, and a REST round trip
- [ ] The script requires explicit opt-in and gates write operations separately
- [ ] The script is NOT collected by pytest (`pytest --collect-only` does not pick it up)
- [ ] The script uses explicit `start()`/`close()`, never `async with WorkdayService(...)`
- [ ] No credentials hardcoded in the script
- [ ] The extra and the script are documented
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check examples/workday_homologation_smoke.py`

---

## Test Specification

```python
# No new automated tests — this task is packaging + a manual script.
# Verification is by the acceptance criteria above, plus:

# 1. The extra resolves:
#    uv pip install -e 'packages/ai-parrot-tools[workday]'
#
# 2. Pytest does not collect the smoke script:
#    pytest --collect-only 2>&1 | grep -c workday_homologation_smoke   # expect 0
#
# 3. The script refuses to run without opt-in:
#    python examples/workday_homologation_smoke.py                     # expect a clear refusal
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2136 through TASK-2141 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2144-workday-extra-and-smoke-script.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**: Added `workday = ["zeep[async]>=4.3.3", "pandas>=2.0", "aiohttp>=3.9"]`
to `packages/ai-parrot-tools/pyproject.toml` `[project.optional-dependencies]`,
matching the existing extras style; the `zeep[async]>=4.3.3` floor aligns
with (rather than conflicts with) the core package's
`zeep[async]==4.3.3` pin. Added a `workday` row to the README's extras
table. Did NOT add `workday` to the `all` meta-extra (not requested by
scope) and did NOT touch `packages/ai-parrot/pyproject.toml` (out of scope
— it already pins `zeep`).

Created `examples/workday_homologation_smoke.py`: a maintainer-run-only
script (module docstring states this explicitly) exercising
`WorkdayConfig(env="sandbox")` resolution, the SOAP endpoint host rewrite
(inspects the bound service's `_binding_options["address"]`), a
`WorkdayService.fetch("get_workers", ...)` read, and a
`WorkdayRestClient.find_worker(...)` + `get_time_clock_events(...)` round
trip, with an optional `Put_Time_Clock_Events` write + REST read-back
verification gated behind a SEPARATE `--write` CLI flag plus an
interactive `input("...type 'yes'...")` confirmation on top of the
script's own `--confirm` opt-in gate (three layers total for the write
path: `--confirm`, `--write`, interactive `yes`). Uses explicit
`start()`/`close()` throughout (`WorkdayService` has no
`__aenter__`/`__aexit__`) and always calls `WorkdayRestClient.close()` in a
`finally` block. No credentials appear anywhere in the script — it only
reads `WorkdayConfig(env="sandbox")`, which resolves from `parrot.conf`/env
exactly like every other sandbox caller.

Verified: `pytest --collect-only` picks up 0 tests from the file (not
named `test_*`, not under `tests/`); running with no flags prints a clear
refusal and exits 1; `--help` works without a live tenant; `ruff check`
clean; `uv pip install --dry-run -e 'packages/ai-parrot-tools[workday]'`
resolves 215 packages with no conflicts (only unrelated
worktree-vs-main-repo path/version noise for `aioboto3`/`boto3`,
pre-existing and unrelated to this change). Full `tests/workday/` suite
(160 tests, unchanged from TASK-2143) still passes. Force-added the new
example file with `git add -f` — the repo's `.gitignore` has a blanket
`examples/**/*.py` rule (documented in `CLAUDE.md`'s "Heads-up" note for a
different path, `sdd/templates/`, but the same mechanism applies here).

**Deviations from spec**: none. This is the final task of FEAT-415 —
all nine tasks (TASK-2136 through TASK-2144) are now complete.
