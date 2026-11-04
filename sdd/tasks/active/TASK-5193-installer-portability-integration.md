# TASK-5193: Cross-host portability and shared-state regression gate

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5190, TASK-5191, TASK-5192
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Implement spec cross-host parity and fresh-repository integration tests after the public APIs land.
- Keep implementation files read-only; report actual failures rather than weakening assertions.
- Own the existing parity and project-root tests and extend SDD toolkit tests with real chained host/SDD installs.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py` | MODIFY | Keep the ambiguous-bare-command regression while extending the truth table. |
| `packages/ai-parrot/tests/knowledge/wiki/test_project_roots.py` | MODIFY | Validate state preservation through the actual wiki discovery API. |
| `packages/ai-parrot/tests/sdd/test_installer_toolkits.py` | MODIFY | The integration boundary catches forwarding and output-log defects missed by spies. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
from pathlib import Path
import pytest
from click.testing import CliRunner
from parrot.cli import cli
from parrot.knowledge.wiki.project import find_project_root, load_effective_config
from parrot.sdd.installer import install_sdd_integration
from parrot.self_.doctor import run_doctor
```

### Existing Signatures to Use

```python
# packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py:35
def _install_claude(root: Path, portable: bool | None) -> None:

# packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py:39
def _install_codex(root: Path, portable: bool | None) -> None:

# packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py:118
def test_no_config_is_baked(root: Path) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1049
def find_project_root(start: Path | None = None) -> Path | None:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1274
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig:

# packages/ai-parrot/src/parrot/sdd/installer.py:1064
def install_sdd_integration(
    root: Path,
    hosts: Sequence[str] = ("claude",),
    *,
    keep_edits: bool = False,
    dry_run: bool = False,
    portable: bool = False,
    base_branch: str | None = None,
    push_base: bool = False,
    hotfix_base: str | None = None,
    dangerous_guard: bool = True,
    sdd_coder: bool = True,
) -> list[str]:

# packages/ai-parrot/src/parrot/self_/doctor.py:664
def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]:
```

### Does NOT Exist

- No production source changes belong to this regression task; fix discovered implementation defects in their owning task.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_project_roots.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_installer_toolkits.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#_install_claude",
    "sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#_install_codex",
    "sym:packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py#test_no_config_is_baked",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_project_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor"
  ]
}
```

## Implementation Notes

TASK-5190 owns test_installer_toolkits.py before this task and supplies SDD tri-state wiring; TASK-5191 supplies toolkit CLI flags/root; TASK-5192 supplies doctor form/provenance checks.

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

### `packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py` (MODIFY)

Anchor `def test_no_config_is_baked(root: Path) -> None:` — occurrences: 1; verified `packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py:118`.

```python
# Replace test_no_config_is_baked with no-config=None assertions for all three hosts.
def test_no_config_follows_launcher_rule(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Host defaults differ from inference: fresh None follows launcher availability."""
    # FILL IN: all hosts, launcher on/off, exactly one fallback note, explicit forms and sticky transitions.
```

**Why**: Keep the ambiguous-bare-command regression while extending the truth table.

### `packages/ai-parrot/tests/knowledge/wiki/test_project_roots.py` (MODIFY)

Anchor `def test_project_below_temp_root_still_resolves` — occurrences: 1; verified `packages/ai-parrot/tests/knowledge/wiki/test_project_roots.py:51`.

```python
def test_host_install_keeps_wiki_config_on_primary_checkout(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit worktree installation never redirects wiki discovery away from primary state."""
    # FILL IN: parameterize hosts with non-default primary config and isolated HOME; assert config preserved.
    # Existing wiki-plane walk semantics remain unchanged, including explicit ordinary subdirectories.
```

**Why**: Validate state preservation through the actual wiki discovery API.

### `packages/ai-parrot/tests/sdd/test_installer_toolkits.py` (MODIFY)

Anchor `def test_cli_flag_and_dry_run` — occurrences: 1; verified `packages/ai-parrot/tests/sdd/test_installer_toolkits.py:121`.

```python
def test_fresh_repo_end_to_end_portable(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Host then SDD install with fake managed launcher emits portable host configs and hooks."""
    # FILL IN: actual installs; inspect .mcp.json, settings and agent hooks; doctor reports portable.
def test_fresh_repo_end_to_end_baked_with_note(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the launcher each installer explains fallback once and doctor remains informational."""
    # FILL IN: count exact host-note prefix, retain distinct guard note; assert no external calls.
```

**Why**: The integration boundary catches forwarding and output-log defects missed by spies.

### FILL IN checklist

- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_project_roots.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/sdd/test_installer_toolkits.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC3/AC4: fake managed launcher vs absent launcher drives fresh CLI/library outputs, one host fallback note per installer, and correct informational doctor forms.
- [ ] AC5: tri-state inference distinguishes no managed entries, baked and portable across all hosts without breaking bare-wikitoolkit tie cases.
- [ ] AC8: host installs into explicit worktree preserve primary wiki settings and subsequent wiki discovery; no local wiki plane is created.
- [ ] All spec-listed test files are exercised by the cached feature contract; these task commands target only the owned regression files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_project_roots.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer_toolkits.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5193` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Pending. The finalizer records verified implementation evidence when this task is complete.

## Orchestrator Note (FEAT-804, post TASK-5186..5188 merge)

Transitional red to FIX in this task: `test_portable_mode_parity.py::test_no_config_is_baked` asserts `_current_portable_mode(root) is False`; since TASK-5186/5187/5188 the function is tri-state and returns `None` when no managed entry exists. Update the assertion to `is None` for claude and codex (and add the google equivalent if absent).
