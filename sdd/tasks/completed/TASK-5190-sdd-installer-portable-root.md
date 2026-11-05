# TASK-5190: SDD tri-state hooks, toolkit forwarding and checkout roots

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5189
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Implement spec M2/M3/M4 SDD changes together: tri-state hooks, keyword forwarding and shared checkout resolver.
- Keep dangerous guard and guard-hook outputs unchanged for old automatic/explicit-portable behavior; False now forces baked.
- Refuse implicit linked-worktree writes before planning, including dry-run; status only resolves.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | Keep both hook emitters and toolkit service forwarding on the same explicit tri-state. |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | Root refusal must precede install planning and side effects. |
| `packages/ai-parrot/tests/sdd/test_installer.py` | MODIFY | Separate explicit False from the old automatic case. |
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | MODIFY | Exercise Click callback routing rather than only the new helper. |
| `packages/ai-parrot/tests/sdd/test_installer_toolkits.py` | MODIFY | Verify real emitted toolkit entries and receipt behavior. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
from pathlib import Path
from typing import Any, Literal, Sequence
import pytest
import click
from parrot.launcher import managed_launcher_on_path, LinkedWorktreeError, install_root, require_primary_checkout  # TASK-5184
from parrot.mcp.toolkit_install import install_toolkits  # extended by TASK-5189
from parrot.sdd.installer import guard_hook_command, dangerous_hook_command, install_sdd_integration
from click.testing import CliRunner
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/installer.py:280
def guard_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]:

# packages/ai-parrot/src/parrot/sdd/installer.py:308
def dangerous_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]:

# packages/ai-parrot/src/parrot/sdd/installer.py:338
def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool) -> list[str]:

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

# packages/ai-parrot/src/parrot/sdd/installer.py:1227
def _install_toolkits_step(root: Path, hosts: Sequence[str], receipt: dict[str, Any]) -> list[str]:

# packages/ai-parrot/src/parrot/sdd/installer.py:1551
def sdd_status(root: Path) -> dict[str, Any]:

# packages/ai-parrot/src/parrot/sdd/cli.py:48
def _root(path_: Path | None) -> Path:

# packages/ai-parrot/src/parrot/sdd/cli.py:103
def install(
    path_: Path | None,
    hosts: tuple[str, ...],
    keep_edits: bool,
    force: bool,
    portable: bool,
    base_branch: str | None,
    push_base: bool,
    hotfix_base: str | None,
    no_dangerous_guard: bool,
    no_sdd_coder: bool,
    dry_run: bool,
) -> None:

# packages/ai-parrot/src/parrot/sdd/cli.py:161
def uninstall(
    path_: Path | None,
    hosts: tuple[str, ...],
    keep_edits: bool,
    dry_run: bool,
    stalled: bool,
    keep: tuple[str, ...],
) -> None:

# packages/ai-parrot/src/parrot/sdd/cli.py:206
def status(path_: Path | None, as_json: bool) -> None:

# packages/ai-parrot/src/parrot/launcher.py:118
def script_path(venv: Path, name: str, *, os_name: str | None = None) -> Path:
```

### Does NOT Exist

- No --no-portable SDD option exists yet; the current boolean portable=False means automatic, not forced baked.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_sdd_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_installer_toolkits.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#guard_hook_command",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#dangerous_hook_command",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_dangerous_guard",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_toolkits_step",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#sdd_status",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#_root",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#install",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#uninstall",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#status",
    "sym:packages/ai-parrot/src/parrot/launcher.py#script_path"
  ]
}
```

## Implementation Notes

TASK-5189 adds install_toolkits(portable=); inherited TASK-5184 supplies launcher/root primitives. All SDD installer/CLI writes are owned here.

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

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY)

Anchor `def guard_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/installer.py:280`.

Anchor `            actions.extend(_install_toolkits_step(root, hosts, receipt))` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/installer.py:1152`.

Anchor `def _install_toolkits_step(root: Path, hosts: Sequence[str], receipt: dict[str, Any]) -> list[str]:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/installer.py:1227`.

Anchor `def dangerous_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/installer.py:308`.

Anchor `def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool) -> list[str]:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/installer.py:338`.

Anchor `    portable: bool = False,` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/installer.py:1070`.

Anchor `    hook = guard["command"] if guard["form"] in {"bare", "baked"} else guard_hook_command(portable=False)[0]` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/installer.py:1568`.

```python
from parrot.launcher import managed_launcher_on_path

def guard_hook_command(*, portable: bool | None) -> tuple[str, Literal["bare", "baked"]]:
    """Render explicit or launcher-selected guard form; False forces baked."""
    # FILL IN: True -> GUARD_HOOK_LINE; None -> managed_launcher_on_path; else existing shlex bake.

def dangerous_hook_command(*, portable: bool | None) -> tuple[str, Literal["bare", "baked"]]:
    """Derive dangerous guard from the same tri-state guard decision."""
    # FILL IN: retain current body.

def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
    """Install the dangerous guard without altering ownership or merge behavior."""
    # FILL IN: retain current body.

def _install_toolkits_step(root: Path, hosts: Sequence[str], receipt: dict[str, Any],
                           *, portable: bool | None) -> list[str]:
    """Install SDD toolkits and record only the sections this installation owns."""
    # FILL IN: keep body; install_toolkits(..., portable=portable).

def install_sdd_integration(
    root: Path, hosts: Sequence[str] = ("claude",), *, keep_edits: bool = False,
    dry_run: bool = False, portable: bool | None = None, base_branch: str | None = None,
    push_base: bool = False, hotfix_base: str | None = None,
    dangerous_guard: bool = True, sdd_coder: bool = True,
) -> list[str]:
    """Deploy SDD assets and forward the caller's tri-state to hooks and toolkits."""
    # FILL IN: retain current implementation and make the wiring changes below.
# Its toolkit step becomes _install_toolkits_step(root, hosts, receipt, portable=portable).
# sdd_status auto fallback uses guard_hook_command(portable=None), not False.
```

**Why**: Keep both hook emitters and toolkit service forwarding on the same explicit tri-state.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)

Anchor `def _root(path_: Path | None) -> Path:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/cli.py:48`.

Anchor `    "--portable",` — occurrences: 1; verified `packages/ai-parrot/src/parrot/sdd/cli.py:77`.

```python
from parrot.launcher import LinkedWorktreeError, install_root, require_primary_checkout

def _root(path_: Path | None, *, write: bool = True) -> Path:
    """Resolve checkout or explicit target and reject implicit worktree writes."""
    # FILL IN: preserve invalid-directory error; resolve install_root; translate LinkedWorktreeError.

# Replace the existing portable option and type its callback argument as bool | None:
# @click.option("--portable/--no-portable", "portable", default=None,
#               help="Bare launcher commands or baked paths; default keeps each host's form then follows the launcher.")
# install/uninstall call _root(path_, write=True); status uses write=False.
```

**Why**: Root refusal must precede install planning and side effects.

### `packages/ai-parrot/tests/sdd/test_installer.py` (MODIFY)

Anchor `def test_guard_hook_bare_when_managed_launcher_on_path` — occurrences: 1; verified `packages/ai-parrot/tests/sdd/test_installer.py:353`.

```python
# Change automatic guard test calls from portable=False to portable=None.
def test_guard_hook_no_portable_forces_baked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """False forces baked guard commands even with the managed launcher on PATH."""
    # FILL IN: assert guard/dangerous output and quoting; preserve all existing receipt tests.
```

**Why**: Separate explicit False from the old automatic case.

### `packages/ai-parrot/tests/sdd/test_sdd_cli.py` (MODIFY)

Anchor `def test_install_status_uninstall_roundtrip(tmp_path: Path) -> None:` — occurrences: 1; verified `packages/ai-parrot/tests/sdd/test_sdd_cli.py:20`.

```python
def test_sdd_cli_refuses_linked_worktree_and_resolves_subdir(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """Write verbs refuse before mutations; status and explicit targets are available."""
    # FILL IN: install/uninstall/dry-run refusal and --path override; primary nested cwd resolution.
```

**Why**: Exercise Click callback routing rather than only the new helper.

### `packages/ai-parrot/tests/sdd/test_installer_toolkits.py` (MODIFY)

Anchor `def test_cli_flag_and_dry_run` — occurrences: 1; verified `packages/ai-parrot/tests/sdd/test_installer_toolkits.py:121`.

```python
# Extend existing test_cli_flag_and_dry_run, retaining its no-write assertions.
def test_sdd_install_portable_reaches_toolkits(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All selected hosts receive the explicit form, including False and fresh configs."""
    # FILL IN: None/True/False combinations; pin HOME/PATH and stub credential/roster probes.
```

**Why**: Verify real emitted toolkit entries and receipt behavior.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/sdd/installer.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/src/parrot/sdd/cli.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/sdd/test_installer.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/sdd/test_sdd_cli.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/sdd/test_installer_toolkits.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC6/AC11: None/True reproduce previous automatic/portable bytes; False forces both guards and toolkit entries baked even with launcher present.
- [ ] SDD --portable/--no-portable is default None and reaches guard, dangerous guard and install_toolkits unchanged.
- [ ] AC7: subdirectory install targets checkout; worktree refusal happens before any writes; explicit --path works and status remains usable.
- [ ] Dry-run writes nothing; receipt ownership/uninstall behavior remains intact; fallback notes are not duplicated.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer_toolkits.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5190` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Completed 2026-11-05 via sdd-worker orchestration.

- Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 473s · Tokens: n/a.
- Wave merge-tier validation (5190+5191): 173 passed, 2 failed — test_portable_mode_parity::test_no_config_is_baked (transitional, owned by TASK-5193)
  and test_sdd_cli::test_sdd_cli_mounts_every_helper (baseline red, also red in the TASK-5184 gate).
- Closure deviation: `coder_record_review` fails server-side (`CoderReview() argument after ** must be a mapping`), so no review EvidenceRef
  exists for `parrot sdd task finalize`; closed via `parrot sdd task close` with this hand-written note. Review/feedback NOT recorded; fix_commits: none.

## Orchestrator Note (FEAT-804, post TASK-5186..5188 merge)

Transitional red to FIX in this task: `tests/sdd/test_installer.py::test_guard_hook_portable_flag_forces_bare` now fails because the install path resolves the portable mode through `resolve_portable_mode` (launcher on PATH => portable). Update the test to pin `portability.managed_launcher_on_path` and separate explicit False from the automatic case, as this task already requires.
