# TASK-5188: Google installer portability and shared wiki root

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5185
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Apply spec M2 and M4 to this host in one task to avoid overlapping installer writers.
- Preserve plugin-first/user-global inference order, foreign entries and existing multi-repo-safe global toolkit emission; isolate both Google files in tests.
- Load wiki config and remote settings from shared_root in the CLI BEFORE passing config to the library; route initial build checks/builds to the same root.
- Refuse implicit linked-worktree install/uninstall before writes; explicit --path proceeds; status remains read-only.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | Resolve portability before emission and use shared state without redirecting host assets. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` | MODIFY | Caller-supplied worktree defaults must never overwrite primary wiki configuration. |
| `packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py` | MODIFY | CLI-level assertions catch the config-argument and build-root bugs that library-only tests miss. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
from pathlib import Path
from typing import Optional
import click
import pytest
from click.testing import CliRunner
from parrot.launcher import LinkedWorktreeError, install_root, require_primary_checkout  # TASK-5184
from parrot.mcp.portability import resolve_portable_mode  # TASK-5185
from parrot.knowledge.wiki.project import load_effective_config, config_path, save_project_config
from parrot.knowledge.wiki.google.cli import google
from parrot.knowledge.wiki.google.installer import install_google_integration, reconcile_toolkit_entries
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:75
def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool:

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:219
def reconcile_toolkit_entries(
    root: Path, mcp_path: Optional[Path] = None, *, portable: Optional[bool] = None
) -> tuple[list[str], list[str]]:

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:380
def install_google_integration(
    root: Path,
    config: Optional[WikiProjectConfig] = None,
    gitignore: bool = True,
    bookstore: bool = True,
    mcp_config_path: Optional[Path] = None,
    portable: Optional[bool] = None,
) -> list[str]:

# packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py:25
def _resolve_root(path: Optional[str]) -> Path:

# packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py:69
def install(
    path_: Optional[str],
    gitignore: bool,
    build_now: bool,
    bookstore: bool,
    portable: Optional[bool],
) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py:119
def status(path_: Optional[str], as_json: bool) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py:105
def uninstall(path_: Optional[str]) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1274
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1021
def config_path(root: Path) -> Path:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1105
def save_project_config(root: Path, config: WikiProjectConfig) -> Path:
```

### Does NOT Exist

- No prefer-worktree option exists on knowledge.wiki.project.find_project_root; leave that resolver unchanged.
- The host root helper has no write parameter before this task; new launcher/decision symbols come from dependencies.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_current_portable_mode",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#reconcile_toolkit_entries",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#install_google_integration",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#_resolve_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#install",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#status",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#uninstall",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#config_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#save_project_config"
  ]
}
```

## Implementation Notes

TASK-5185 creates resolve_portable_mode; its dependency TASK-5184 supplies install_root and worktree refusal. Owns google installer.py/cli.py and test_google_portable.py; no host-file overlap.

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

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` (MODIFY)

Anchor `def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:75`.

Anchor `    if portable is None:` — occurrences: 2; verified `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:245,404`.

Disambiguating current context for each occurrence:

```python
    cfg = load_toolkits_config(root)
    enabled_toolkits = {name: section for name, section in cfg.toolkits.items() if section.enabled}
    if portable is None:
        portable = _current_portable_mode(root, mcp_path)
    desired_local = assets.toolkit_mcp_entries(root, enabled_toolkits, portable=portable)
```

```python
    existed = config_path(root).exists()
    save_project_config(root, config)
    if portable is None:
        portable = _current_portable_mode(root, mcp_config_path)

```

```python
from parrot.launcher import install_root
from parrot.mcp.portability import resolve_portable_mode

def _current_portable_mode(root: Path, mcp_path: Optional[Path] = None) -> bool | None:
    """Return managed form, or None when no managed form is available."""
    # FILL IN: retain host-specific inference; change only no-managed-config cases per spec M2.

# At the existing portable-is-None site in reconcile_toolkit_entries:
decision = resolve_portable_mode(portable, current=_current_portable_mode(root, mcp_path))
portable = decision.portable
# FILL IN: append decision.note once to the returned action log, after its list is initialized.
# At install_google_integration, resolve the decision independently before emitting host assets.
# Pass the resulting bool to nested emitters/reconcilers so a fallback note is not duplicated.
state_root = install_root(root, explicit=root).shared_root
config = config or load_effective_config(state_root).config
existed = config_path(state_root).exists()
save_project_config(state_root, config)
# FILL IN: retain all asset paths at root; retain deliberate config overrides for library callers.
```

**Why**: Resolve portability before emission and use shared state without redirecting host assets.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` (MODIFY)

Anchor `def _resolve_root(path: Optional[str]) -> Path:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py:25`.

Anchor `        config = load_effective_config(root).config` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py:79`.

```python
from parrot.launcher import LinkedWorktreeError, install_root, require_primary_checkout

def _resolve_root(path: Optional[str], *, write: bool = True) -> Path:
    """Resolve the install target, rejecting implicit worktree writes before side effects."""
    # FILL IN: validate an explicit directory before resolution; preserve existing invalid-path error.
    try:
        resolved = install_root(Path.cwd(), explicit=Path(path) if path else None)
        if write:
            require_primary_checkout(resolved)
    except LinkedWorktreeError as exc:
        raise click.ClickException(str(exc)) from exc
    return resolved.root

# install/uninstall use write=True; status uses write=False.
# In install, after root = _resolve_root(path_):
state_root = install_root(root, explicit=root).shared_root
config = load_effective_config(state_root).config
# FILL IN: pass this shared config to installer; remote lookup uses it where supported.
# Replace both build check and build invocation roots:
# config.is_built(state_root)
# context.invoke(wiki_build, path_=str(state_root), quiet=True)
# Keep --no-build suppression and host asset/status paths at root.
```

**Why**: Caller-supplied worktree defaults must never overwrite primary wiki configuration.

### `packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py` (MODIFY)

Anchor `def test_default_emission_unchanged(` — occurrences: 1; verified `packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py:78`.

```python
# Preserve existing host emission, ownership and sticky transition tests.
# Pin managed_launcher_on_path=False in the existing default-emission test.
def test_host_cli_worktree_preserves_shared_config_and_build_root(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """The google CLI preserves primary state while writing explicit worktree host assets."""
    # FILL IN: primary with non-default config + linked worktree without wiki.json; invoke CliRunner.
    # Capture wiki_build invocation; assert primary root and --no-build suppression.
    # FILL IN: implicit refusal, explicit override, uninstall/status and portable default/notes cases.
```

**Why**: CLI-level assertions catch the config-argument and build-root bugs that library-only tests miss.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC3–AC5: launcher-present fresh install is portable; launcher-absent fresh install emits exactly one baked note; sticky mode and both explicit migrations work.
- [ ] AC7: CLI refuses implicit linked worktree with exit 1 and both paths, accepts --path, resolves subdirs, and permits status.
- [ ] AC8: CLI and library retain non-default primary wiki config; explicit worktree install creates no local wiki.json; build and remote lookup use primary state.
- [ ] Existing foreign-entry and remote-mode tests still pass; tests isolate HOME/PATH and never launch a real provider build.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5188` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Completed 2026-11-05 via sdd-worker orchestration.

- Seat: opus · Backend: native · Attempts: 1 · Tokens: n/a. Delivered ca462eec3d; the coder's own run: test_google_portable.py 17 passed, hosts/toolkit_install 15 passed.
- Wave merge-tier validation (5186+5187+5188): 175 passed, 5 failed. All 5 are transitional reds in test files owned by pending tasks
  (test_portable_mode_parity::test_no_config_is_baked -> TASK-5193; test_installer::test_guard_hook_portable_flag_forces_bare -> TASK-5190;
  test_doctor_sdd::ready_repo `shutil.which` lambda x3 -> TASK-5192); each owner task file carries an Orchestrator Note.
- Closure deviation: `coder_record_review` fails server-side (`CoderReview() argument after ** must be a mapping`), so no review EvidenceRef
  exists for `parrot sdd task finalize`; closed via `parrot sdd task close` with this hand-written note. Review/feedback NOT recorded; fix_commits: none.
