# TASK-5186: Claude installer portability and shared wiki root

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: pending
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
- Keep bare-wikitoolkit/parrot-* tie-breaking, remote entries, foreign entry ownership and Claude approvals/hooks intact.
- Load wiki config and remote settings from shared_root in the CLI BEFORE passing config to the library; route initial build checks/builds to the same root.
- Refuse implicit linked-worktree install/uninstall before writes; explicit --path proceeds; status remains read-only.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | Resolve portability before emission and use shared state without redirecting host assets. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | Caller-supplied worktree defaults must never overwrite primary wiki configuration. |
| `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py` | MODIFY | CLI-level assertions catch the config-argument and build-root bugs that library-only tests miss. |

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
from parrot.knowledge.wiki.claude_code.cli import claude
from parrot.knowledge.wiki.claude_code.installer import install_claude_integration, reconcile_toolkit_entries
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:139
def _current_portable_mode(root: Path) -> bool:

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:705
def reconcile_toolkit_entries(root: Path, *, portable: Optional[bool] = None) -> tuple[list[str], list[str]]:

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:1216
def install_claude_integration(
    root: Path,
    config: Optional[WikiProjectConfig] = None,
    git_hook: bool = True,
    gitignore: bool = True,
    bookstore: bool = True,
    approve_mcp: bool = True,
    compaction: bool = False,
    typesafe_api_key: Optional[str] = None,
    plugin_cli: bool = True,
    remote: Optional[WikiRemoteConfig] = None,
    portable: Optional[bool] = None,
) -> list[str]:

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:36
def _resolve_root(path: Optional[str]) -> Path:

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:140
def install(
    path_: Optional[str],
    git_hook: bool,
    gitignore: bool,
    build_now: bool,
    bookstore: bool,
    tool_guards: bool,
    approve_mcp: bool,
    compaction: bool,
    typesafe_api_key: Optional[str],
    plugin_cli: bool,
    use_remote: bool,
    remote_url: Optional[str],
    token_env: Optional[str],
    portable: Optional[bool],
    sandbox_mode: Optional[str],
    non_interactive: bool,
    no_welcome: bool,
) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:276
def status(path_: Optional[str], as_json: bool) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:255
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
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_current_portable_mode",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#reconcile_toolkit_entries",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#_resolve_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#install",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#status",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#uninstall",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#config_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#save_project_config"
  ]
}
```

## Implementation Notes

TASK-5185 creates resolve_portable_mode; its dependency TASK-5184 supplies install_root and worktree refusal. Owns claude_code installer.py/cli.py and test_claude_installer_portable.py; no host-file overlap.

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

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY)

Anchor `def _current_portable_mode(root: Path) -> bool:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:139`.

Anchor `    if portable is None:` — occurrences: 2; verified `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:736,1280`.

Disambiguating current context for each occurrence:

```python
        servers = data["mcpServers"] = {}

    if portable is None:
        portable = _current_portable_mode(root)  # reads .mcp.json before this function writes it

```

```python
        actions = [".parrot/wiki.json — config already present"]
    save_project_config(root, config)
    if portable is None:
        portable = _current_portable_mode(root)
    logger.debug("claude install: portable=%s", portable)
```

```python
from parrot.launcher import install_root
from parrot.mcp.portability import resolve_portable_mode

def _current_portable_mode(root: Path) -> bool | None:
    """Return managed form, or None when no managed form is available."""
    # FILL IN: retain host-specific inference; change only no-managed-config cases per spec M2.

# At the existing portable-is-None site in reconcile_toolkit_entries:
decision = resolve_portable_mode(portable, current=_current_portable_mode(root))
portable = decision.portable
# FILL IN: append decision.note once to the returned action log, after its list is initialized.
# At install_claude_integration, resolve the decision independently before emitting host assets.
# Pass the resulting bool to nested emitters/reconcilers so a fallback note is not duplicated.
state_root = install_root(root, explicit=root).shared_root
config = config or load_effective_config(state_root).config
existed = config_path(state_root).exists()
save_project_config(state_root, config)
# FILL IN: retain all asset paths at root; retain deliberate config overrides for library callers.
```

**Why**: Resolve portability before emission and use shared state without redirecting host assets.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` (MODIFY)

Anchor `def _resolve_root(path: Optional[str]) -> Path:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:36`.

Anchor `        config = load_effective_config(root).config` — occurrences: 1; verified `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:172`.

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

### `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py` (MODIFY)

Anchor `def test_default_install_unchanged(repo_root: Path) -> None:` — occurrences: 1; verified `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py:48`.

```python
# Preserve existing host emission, ownership and sticky transition tests.
# Pin managed_launcher_on_path=False in the existing default-emission test.
def test_host_cli_worktree_preserves_shared_config_and_build_root(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """The claude CLI preserves primary state while writing explicit worktree host assets."""
    # FILL IN: primary with non-default config + linked worktree without wiki.json; invoke CliRunner.
    # Capture wiki_build invocation; assert primary root and --no-build suppression.
    # FILL IN: implicit refusal, explicit override, uninstall/status and portable default/notes cases.
```

**Why**: CLI-level assertions catch the config-argument and build-root bugs that library-only tests miss.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC3–AC5: launcher-present fresh install is portable; launcher-absent fresh install emits exactly one baked note; sticky mode and both explicit migrations work.
- [ ] AC7: CLI refuses implicit linked worktree with exit 1 and both paths, accepts --path, resolves subdirs, and permits status.
- [ ] AC8: CLI and library retain non-default primary wiki config; explicit worktree install creates no local wiki.json; build and remote lookup use primary state.
- [ ] Existing foreign-entry and remote-mode tests still pass; tests isolate HOME/PATH and never launch a real provider build.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5186` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Pending. The finalizer records verified implementation evidence when this task is complete.
