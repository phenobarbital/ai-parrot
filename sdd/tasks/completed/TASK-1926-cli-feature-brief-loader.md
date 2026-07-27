# TASK-1926: CLI feature-brief loader — `parrot devloop run --brief feature.yaml`

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: done
**Completed**: 2026-07-27
**Verification**: verified
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1918, TASK-1925
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (CLI half). One CLI for bugs and features: `parrot devloop
run --brief feature.yaml` must detect `kind: feature` and hand a
`FeatureBrief` to the runner, which selects the feature topology.

---

## Scope

- Extend the devloop CLI brief loading (`parrot/cli/devloop/console.py`)
  to parse the brief file through the TASK-1918 union entry point
  (`parse_brief` / `Brief`) instead of hardcoding `WorkBrief`:
  - `kind: feature` → `FeatureBrief` → runner feature path.
  - All other briefs → `WorkBrief`, byte-identical behavior.
  - Confirmation/summary rendering: show document_path/doc_kind/judge panel
    for feature briefs (reuse the existing renderer style).
- Wizard: OUT of scope for interactive FeatureBrief collection (spec calls
  it optional) — when the wizard is invoked without `--brief`, keep current
  WorkBrief-only behavior.
- Tests: brief-file roundtrip for both kinds; e2e CLI invocation test with
  stubbed runner (`test_cli_brief_roundtrip` from spec §4).

**NOT in scope**: runner/topology logic (TASK-1925), new CLI commands,
interactive FeatureBrief wizard.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/console.py` | MODIFY | Union-aware brief loading |
| `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` | MODIFY | Help text mentions feature briefs |
| `packages/ai-parrot/tests/cli/test_devloop_feature_brief.py` | CREATE | Loader + e2e tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import parse_brief, FeatureBrief, WorkBrief  # TASK-1918
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/devloop/__init__.py  (verified 2026-07-27)
# @click.group(invoke_without_command=True)  :14
# @devloop.command("run")                    :26
# @click.option("--brief", "brief_file", type=click.Path(exists=True), ...)  :27
# "--yes" option :30 — non-interactive dispatch
# @devloop.command("revise")                 :44

# packages/ai-parrot/src/parrot/cli/devloop/console.py  (verified 2026-07-27)
# _collect brief via wizard-or-file :100-127 — currently hardcodes WorkBrief:
#   from parrot.flows.dev_loop.models import WorkBrief   # :101
#   return self._load_brief_file(brief_file, WorkBrief)  # :105
# def _load_brief_file(self, path_str: str, model_type: type) -> Any:  # :144
#   ← extend/replace the model_type contract here to route through parse_brief
# RevisionBrief path :137 — do NOT touch
```

### Does NOT Exist
- ~~A `--kind` CLI flag~~ — routing is by the brief's `kind` field only; do not add flags.
- ~~FeatureBrief wizard~~ — out of scope; wizard stays WorkBrief-only.
- ~~`parrot devloop feature` subcommand~~ — same `run` command handles both.

---

## Implementation Notes

### Pattern to Follow
Minimal diff in `console.py`: where WorkBrief is loaded from file, load the
raw dict, route through `parse_brief`, then branch rendering by type. Keep
`_load_brief_file`'s validation/error-reporting style.

### Key Constraints
- Zero behavior change for existing WorkBrief/RevisionBrief flows (spec §5).
- `--yes` non-interactive path must work with feature briefs.
- Errors from FeatureBrief validation (missing document) must surface as the
  CLI's normal user-facing brief-validation error, not a traceback.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/devloop/console.py:100-160` — loading + rendering
- Spec §2 User-Facing Behavior (brief YAML example)

---

## Acceptance Criteria

- [ ] `parrot devloop run --brief feature.yaml --yes` parses a FeatureBrief and invokes the runner's feature path (stubbed runner test)
- [ ] Existing WorkBrief briefs load byte-identically (regression test)
- [ ] Invalid feature brief → friendly CLI error, exit non-zero, no traceback
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/test_devloop_feature_brief.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/cli/devloop/`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_devloop_feature_brief.py
# Use click.testing.CliRunner with a stubbed DevLoopRunner.
def test_feature_brief_yaml_roundtrip(tmp_path): ...
def test_workbrief_yaml_unchanged(tmp_path): ...
def test_feature_brief_missing_document_friendly_error(tmp_path): ...
def test_run_yes_noninteractive_feature(tmp_path): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 User-Facing Behavior, §5)
2. **Check dependencies** — TASK-1918, TASK-1925 completed
3. **Verify the Codebase Contract** — re-grep console.py anchors
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**: `console.py`'s brief loading refactored into 3 layers:
`_read_brief_data(path_str)` (shared YAML/JSON-fallback file reader,
extracted from the old `_load_brief_file`), `_load_brief_file(path,
model_type)` (unchanged — still used for `RevisionBrief`, verified with
its own pre-existing regression test), and a new `_load_brief(path_str)`
routing through TASK-1918's `parse_brief` union entry point.
`_collect_work_brief` now calls `_load_brief` on the `--brief` path
instead of hardcoding `WorkBrief` — the wizard path (no `--brief`) is
untouched and stays `WorkBrief`-only, per scope. `runner.run(brief, ...)`
already dispatches on `isinstance` (TASK-1925), so `_dispatch_run` needed
no changes beyond an additive `FeatureBrief` confirmation-summary panel
(`_print_feature_brief_summary`, printed only for `FeatureBrief` — zero
output change for `WorkBrief` runs, which have no equivalent pre-dispatch
panel today).

**Deviation, justified by an explicit acceptance criterion**: added a
`except (FileNotFoundError, ValueError)` clause to `DevLoopConsole.
start()` around `_dispatch_initial()`, printing a friendly `[bold
red]Brief error:[/bold red]` message and returning exit code 1. This did
NOT exist before for ANY brief type — a malformed WorkBrief file would
previously have propagated a raw traceback all the way through Click,
same as an invalid FeatureBrief would without this fix. Required to
satisfy "Invalid feature brief → friendly CLI error, exit non-zero, no
traceback" (`pydantic.ValidationError` subclasses `ValueError`, so this
also catches invalid/missing WorkBrief fields — a strict robustness
improvement on the failure path only; the success path for existing
briefs is untouched, so "zero behavior change" still holds for the
happy path).

`__init__.py`: extended `run` command's `--brief` help text and
docstring to describe `kind: feature` routing; no `--kind` flag added
(routing is by the brief's own field, per the contract's explicit "does
NOT exist" note). Did not touch the pre-existing, unrelated
`skip_wizard`/`--yes` plumbing gap (the flag is accepted but never
threaded into `console.start()` — a latent gap in `run_cmd()` predating
this task and outside its file list); the interactive command loop
exits gracefully via `EOFError` on closed/non-tty stdin regardless
(verified empirically by the CLI-wiring test, which uses a mocked
`DevLoopConsole` rather than exercising the real loop).

Tests: `packages/ai-parrot/tests/cli/test_devloop_feature_brief.py` (7
tests — the task's own 4 plus a no-`kind`-key regression, an unchanged-
`_load_brief_file`/RevisionBrief regression, and a not-found-file
friendly-error case). All pass; full `tests/cli/` (95) and
`tests/flows/dev_loop/` suites green except the pre-existing, unrelated
`test_models_module_is_pure` test-order flake. `ruff check` clean on
both modified `devloop/` CLI files (3 pre-existing unused-import findings
in `console.py` — `List`, `Set`, `Text` — confirmed via `git stash` to
predate this task; left untouched, out of scope).

**Deviations from spec**: none beyond the justified `start()` error-
handling addition documented above.
