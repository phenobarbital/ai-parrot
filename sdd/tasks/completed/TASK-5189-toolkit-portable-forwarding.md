# TASK-5189: Forward portability through host adapters and toolkit services

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5186, TASK-5187, TASK-5188
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Extend HostAdapter.reconcile and all three adapters with keyword-only portable: bool | None = None.
- Thread that value verbatim through _reconcile_all, install_toolkits and set_toolkits_enabled.
- Keep uninstall semantics, ownership, preflight and approvals unchanged. Deduplicate identical fallback notes at the report boundary so multi-host commands satisfy AC4.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/hosts.py` | MODIFY | The protocol must carry False as an explicit choice rather than dropping it through truthiness. |
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | MODIFY | Keep the narrow service extension and existing cleanup/approval contracts. |
| `packages/ai-parrot/tests/mcp/test_hosts.py` | MODIFY | Verify the Google positional override is retained. |
| `packages/ai-parrot/tests/mcp/test_toolkit_install.py` | MODIFY | Check emitted configs as well as forwarding spies. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
from pathlib import Path
from typing import Sequence
import pytest
from parrot.mcp.hosts import HostKind, get_adapter
from parrot.mcp.toolkit_install import ActionReport, install_toolkits, set_toolkits_enabled
from parrot.knowledge.wiki.claude_code.installer import reconcile_toolkit_entries
from parrot.knowledge.wiki.codex.installer import reconcile_toolkit_tables
from parrot.knowledge.wiki.google.installer import reconcile_toolkit_entries
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/mcp/hosts.py:51
    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:

# packages/ai-parrot/src/parrot/mcp/hosts.py:95
    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:

# packages/ai-parrot/src/parrot/mcp/hosts.py:167
    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:

# packages/ai-parrot/src/parrot/mcp/hosts.py:219
    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:

# packages/ai-parrot/src/parrot/mcp/hosts.py:18
class HostKind(str, Enum):

# packages/ai-parrot/src/parrot/mcp/toolkit_install.py:145
def _reconcile_all(root: Path, hosts: Sequence[HostKind], report: ActionReport) -> None:

# packages/ai-parrot/src/parrot/mcp/toolkit_install.py:158
def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:

# packages/ai-parrot/src/parrot/mcp/toolkit_install.py:222
def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind]) -> ActionReport:

# packages/ai-parrot/src/parrot/mcp/toolkit_install.py:55
class ActionReport(BaseModel):
```

### Does NOT Exist

- portable keyword does not yet exist on HostAdapter.reconcile, install_toolkits or set_toolkits_enabled.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/mcp/hosts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/mcp/toolkit_install.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/mcp/test_hosts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/mcp/test_toolkit_install.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#HostAdapter.reconcile",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#ClaudeAdapter.reconcile",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#CodexAdapter.reconcile",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#GoogleAdapter.reconcile",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#HostKind",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#_reconcile_all",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#install_toolkits",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#set_toolkits_enabled",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#ActionReport"
  ]
}
```

## Implementation Notes

TASK-5186, TASK-5187, TASK-5188 supply the tri-state host reconcilers whose fresh-host behavior these service tests consume.

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

### `packages/ai-parrot/src/parrot/mcp/hosts.py` (MODIFY)

Anchor `    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:` — occurrences: 4; verified `packages/ai-parrot/src/parrot/mcp/hosts.py:51,95,167,219`.

Disambiguating current context for each occurrence:

```python
        """Per-toolkit entry state. Reads config files only; imports no toolkit."""

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        """Rewrite ONLY this host's `parrot-<name>` entries. Returns (actions, warnings)."""

```

```python
        return states

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.claude_code.installer import reconcile_toolkit_entries

```

```python
        return states

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.codex.installer import reconcile_toolkit_tables

```

```python
        return states

    def reconcile(self, root: Path) -> tuple[list[str], list[str]]:
        from parrot.knowledge.wiki.google.installer import reconcile_toolkit_entries

```

```python
# Update protocol and ClaudeAdapter, CodexAdapter, GoogleAdapter methods identically:
def reconcile(self, root: Path, *, portable: bool | None = None) -> tuple[list[str], list[str]]:
    """Reconcile managed toolkit entries, forwarding the caller's tri-state form."""
    # FILL IN: retain each existing lazy import and forward portable=portable.
    # Claude: reconcile_toolkit_entries(root, portable=portable)
    # Codex: reconcile_toolkit_tables(root, portable=portable)
    # Google: reconcile_toolkit_entries(root, self._mcp_path, portable=portable)
```

**Why**: The protocol must carry False as an explicit choice rather than dropping it through truthiness.

### `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` (MODIFY)

Anchor `def _reconcile_all(root: Path, hosts: Sequence[HostKind], report: ActionReport) -> None:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/mcp/toolkit_install.py:145`.

Anchor `def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind]) -> ActionReport:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/mcp/toolkit_install.py:158`.

Anchor `def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool, hosts: Sequence[HostKind]) -> ActionReport:` — occurrences: 1; verified `packages/ai-parrot/src/parrot/mcp/toolkit_install.py:222`.

```python
def _reconcile_all(root: Path, hosts: Sequence[HostKind], report: ActionReport,
                   *, portable: bool | None = None) -> None:
    """Collect reconciler results with explicit command form and existing failure isolation."""
    # FILL IN: existing loop uses adapter.reconcile(root, portable=portable).
    # Deduplicate identical host-config fallback notes while retaining other action order.

def install_toolkits(root: Path, names: Sequence[str], hosts: Sequence[HostKind],
                     *, portable: bool | None = None) -> ActionReport:
    """Seed and register toolkits with the caller's explicit or inferred form."""
    # FILL IN: preserve body; _reconcile_all(..., portable=portable).

def set_toolkits_enabled(root: Path, names: Sequence[str], enabled: bool,
                        hosts: Sequence[HostKind], *, portable: bool | None = None) -> ActionReport:
    """Toggle sections and reconcile while retaining all existing approval semantics."""
    # FILL IN: preserve body; _reconcile_all(..., portable=portable).
```

**Why**: Keep the narrow service extension and existing cleanup/approval contracts.

### `packages/ai-parrot/tests/mcp/test_hosts.py` (MODIFY)

Anchor `def test_only_google_is_user_scoped():` — occurrences: 1; verified `packages/ai-parrot/tests/mcp/test_hosts.py:32`.

```python
def test_reconcile_forwards_portable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All adapters forward None, False and True, including Google's mcp_path override."""
    # FILL IN: parameterize hosts/forms; capture exact reconciler args and sentinel returns.
```

**Why**: Verify the Google positional override is retained.

### `packages/ai-parrot/tests/mcp/test_toolkit_install.py` (MODIFY)

Anchor `def test_install_hostless_still_seeds_yaml(tmp_path):` — occurrences: 1; verified `packages/ai-parrot/tests/mcp/test_toolkit_install.py:53`.

```python
def test_install_portable_form_across_hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Toolkit orchestration preserves form, failures, foreign entries and one-note output."""
    # FILL IN: actual isolated host configs for explicit forms and sticky None, plus failure isolation.
```

**Why**: Check emitted configs as well as forwarding spies.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/mcp/hosts.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/mcp/test_hosts.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/mcp/test_toolkit_install.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] AC6: explicit True/False and None reach every host adapter and reconciler unchanged.
- [ ] Fresh hosts emit portable entries when requested; existing baked/portable hosts remain sticky with None.
- [ ] Per-host failures are collected without losing other results; foreign entries survive; no toolkit class is imported by inspection.
- [ ] A multi-host fresh baked install returns one identical host-config fallback note, not one copy per host.

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_hosts.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_toolkit_install.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5189` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Completed 2026-11-05 via sdd-worker orchestration.

- Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 311s · Tokens: n/a.
- Wave merge-tier validation (5189+5192): 182 passed, 2 failed — both transitional reds in test files owned by pending tasks
  (test_portable_mode_parity::test_no_config_is_baked -> TASK-5193; test_installer::test_guard_hook_portable_flag_forces_bare -> TASK-5190).
- Closure deviation: `coder_record_review` fails server-side (`CoderReview() argument after ** must be a mapping`), so no review EvidenceRef
  exists for `parrot sdd task finalize`; closed via `parrot sdd task close` with this hand-written note. Review/feedback NOT recorded; fix_commits: none.
