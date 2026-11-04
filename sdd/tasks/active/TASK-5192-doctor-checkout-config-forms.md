# TASK-5192: Doctor checkout provenance and informational host forms

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5186, TASK-5187, TASK-5188
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Implement M5 and the M4 doctor CLI wiring together; use actual pins, not find_project_root discovery.
- Add a non-runtime repo: checkout check and informational per-present-file host forms without changing existing health/collision checks.
- Keep runtime-only free of repository checks and preserve never-raise diagnostics behavior.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/doctor.py` | MODIFY | Separate informational deployment form from broken-command and checkout failures. |
| `packages/ai-parrot/src/parrot/self_/cli.py` | MODIFY | Automatic discovery must not masquerade as an explicit pin. |
| `packages/ai-parrot/tests/self_/test_doctor.py` | MODIFY | Per-file checks prevent one Google config from masking the other. |
| `packages/ai-parrot/tests/self_/test_doctor_sdd.py` | MODIFY | Catch the original CLI provenance defect, not merely helper behavior. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
from pathlib import Path
import os
import sys
import pytest
from parrot.launcher import InstallRoot, explicit_project_pin, install_root  # TASK-5184
from parrot.self_.doctor import DoctorCheck, DoctorScope, run_doctor
from parrot.knowledge.wiki.google.installer import toolkit_config_paths
from click.testing import CliRunner
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/self_/doctor.py:40
class DoctorCheck(BaseModel):

# packages/ai-parrot/src/parrot/self_/doctor.py:590
def _check_host_configs(root: Path) -> list[DoctorCheck]:

# packages/ai-parrot/src/parrot/self_/doctor.py:664
def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]:

# packages/ai-parrot/src/parrot/self_/doctor.py:50
def failed(checks: list[DoctorCheck]) -> list[DoctorCheck]:

# packages/ai-parrot/src/parrot/self_/cli.py:61
def doctor(sdd_scope: bool, runtime_only: bool) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:206
def toolkit_config_paths(root: Path, mcp_path: Optional[Path] = None) -> tuple[Path, ...]:

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:75
def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool:
```

### Does NOT Exist

- run_doctor has no install_root keyword yet; _check_checkout/_check_host_config_forms are new.
- No portable_required SDD config key is authorized; form is informational.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/self_/doctor.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/self_/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/self_/test_doctor.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/self_/test_doctor_sdd.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#DoctorCheck",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#_check_host_configs",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#failed",
    "sym:packages/ai-parrot/src/parrot/self_/cli.py#doctor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#toolkit_config_paths",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_current_portable_mode"
  ]
}
```

## Implementation Notes

TASK-5186, TASK-5187, TASK-5188 define tri-state host inference; inherited TASK-5184 provides InstallRoot and explicit_project_pin. Owns doctor.py and self_/cli.py only.

Use the approved stdlib-only launcher/decision structures from the spec. Keep public signatures
and existing ownership checks; use black (120 columns) and ruff for Python edits. New test functions
must have type hints and explanatory docstrings, matching production conventions. Keep HOME/PATH,
Google user-global config, credential probes and Git fixtures isolated under tmp_path. Never run
installers against the developer checkout/home as a test. Store test logs in artifacts/logs/.

## Implementation Blueprint

The blocks below are scoped edit plans, not wholesale replacements of existing files. CREATE
blocks are whole-file starting points; fill their bounded bodies before committing. Preserve
surrounding implementation and imports. No FILL IN or unfinished body may remain in implemented code.

### Steps (in order)

1. Revalidate listed anchors and prerequisite signatures — because dependencies or FEAT-802 may move adjacent code.
2. Apply the declared per-file edits in the order below — because caller and callee contracts must remain coherent.
3. Implement every bounded test case in Acceptance Criteria — because wiring-only spies do not verify emitted artifacts.
4. Run the Validation Commands and scoped lint — because the final state must preserve existing regression coverage.

### `packages/ai-parrot/src/parrot/self_/doctor.py` (MODIFY)

Anchor `def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/self_/doctor.py:664`.

Anchor `def _check_host_configs(root: Path) -> list[DoctorCheck]:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/self_/doctor.py:590`.

```python
from parrot.launcher import InstallRoot

def _check_checkout(resolved: InstallRoot) -> DoctorCheck:
    """Describe primary/explicit linked roots; fail only implicit linked checkouts."""
    # FILL IN: exact spec M5 name, details, fix and ok semantics.

def _check_host_config_forms(root: Path) -> list[DoctorCheck]:
    """Emit one informational form check for each existing host config file."""
    # FILL IN: same labels/paths as _check_host_configs; map tri-state to spec details.
    # Inspect each Google file independently; do not duplicate plugin-first inference for both labels.
    # Keep malformed-config handling tolerant and leave existing parse/collision failures intact.

def run_doctor(root: Path, *, scope: DoctorScope = "full",
               install_root: InstallRoot | None = None) -> list[DoctorCheck]:
    """Run current checks, adding checkout provenance outside runtime-only scope."""
    # FILL IN: existing runtime checks first; after runtime-only return, append checkout if supplied.
    # _check_host_configs appends _check_host_config_forms; failed() remains unchanged.
```

**Why**: Separate informational deployment form from broken-command and checkout failures.

### `packages/ai-parrot/src/parrot/self_/cli.py` (MODIFY)

Anchor `    root = find_project_root(sys.argv[1:], os.environ, Path.cwd()) or Path.cwd()` — occurrences: 1; verified `packages/ai-parrot/src/parrot/self_/cli.py:72`.

```python
from parrot.launcher import explicit_project_pin, install_root

# Replace root discovery inside doctor only:
pin = explicit_project_pin(sys.argv[1:], os.environ, Path.cwd())
resolved = install_root(Path.cwd(), explicit=pin)
checks = run_doctor(resolved.root, scope=scope, install_root=resolved)
# FILL IN: preserve CLI scopes, formatting and failed(checks) exit handling.
```

**Why**: Automatic discovery must not masquerade as an explicit pin.

### `packages/ai-parrot/tests/self_/test_doctor.py` (MODIFY)

Anchor `def test_doctor_flags_broken_host_config` — occurrences: 1; verified `packages/ai-parrot/tests/self_/test_doctor.py:23`.

```python
def test_doctor_host_config_form(isolated_home: Path, tmp_path: Path) -> None:
    """Each present config gets its own informational form without altering failure status."""
    # FILL IN: absent/no-managed/baked/portable, mixed Google forms, malformed config and collision cases.
```

**Why**: Per-file checks prevent one Google config from masking the other.

### `packages/ai-parrot/tests/self_/test_doctor_sdd.py` (MODIFY)

Anchor `def test_ready_repo_has_no_sdd_failures` — occurrences: 1; verified `packages/ai-parrot/tests/self_/test_doctor_sdd.py:66`.

```python
def test_doctor_cli_pin_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only actual argv/env pins allow a linked checkout check to pass."""
    # FILL IN: clear argv/env pins, invoke real CLI in worktree cwd; isolate unrelated runtime checks.
    # Assert unpinned fails, valid pins pass and runtime-only omits checkout checks.
```

**Why**: Catch the original CLI provenance defect, not merely helper behavior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/self_/doctor.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/src/parrot/self_/cli.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/self_/test_doctor.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/self_/test_doctor_sdd.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC9: unpinned linked-worktree CLI invocation fails repo: checkout; genuine valid pins pass with truthful linked detail; runtime-only omits it.
- [ ] AC10: every present host config gets exactly one informational form check; baked form alone never changes exit status.
- [ ] Google user-global and repo-local files are described individually, even when their forms differ; malformed configs retain existing failing parse checks.
- [ ] Existing runtime, component and SDD readiness checks retain their semantics.

## Validation Commands

- `pytest packages/ai-parrot/tests/self_/test_doctor.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5192` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Pending. The finalizer records verified implementation evidence when this task is complete.

## Orchestrator Note (FEAT-804, post TASK-5186..5188 merge)

Transitional red to FIX in this task: `tests/self_/test_doctor_sdd.py::ready_repo` monkeypatches `shutil.which` with a lambda that does not accept `path=`; `parrot.launcher.managed_launcher_on_path` now calls `shutil.which("parrot", path=...)`, so `test_sdd_tool_checks_follow_the_installed_assets[*]` fail with TypeError. Make the fixture lambda accept `path=None` (and honour it). Do not weaken the production call.
