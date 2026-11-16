# TASK-5678: Core AgentMemoryToolkit and lazy CLI operations

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5671, TASK-5675, TASK-5674, TASK-5668
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes create_memory_manager from TASK-5671; Consumes import_feedback from TASK-5675; Consumes trusted evidence admission from TASK-5674; Consumes authorized forget/suppression service from TASK-5668

## Context

Implement the bounded M6 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Rework (host-delegated decision, 2026-11-16) — issue:76c09075409e

The delivery attached the memory command group with a module-level import in `knowledge/wiki/cli.py`
(`from parrot.memory.dynamics.cli import register_memory_commands` + `register_memory_commands(wiki)`), so every
`wikitoolkit` command imported `parrot.memory` and navconfig logging at startup. The spec requires the group to be
attached **lazily**. Measured: with that one import stubbed out, nothing else at `wikitoolkit` startup imports
`parrot.memory`, so the requirement is achievable.

Required: importing `parrot.knowledge.wiki.cli` and running any non-memory `wikitoolkit` command must NOT import
`parrot.memory`; `wiki.commands["memory"]` must still exist (so `wikitoolkit --help` lists it) and `wikitoolkit memory ...`
must behave exactly as before, importing the memory package only when that command is used. Add a regression test that
runs a wikitoolkit command in a **fresh subprocess** and asserts `parrot.memory` is not in `sys.modules`.

## Release Preconditions

No additional owner decision is required beyond completed dependency contracts. Do not bypass a blocked dependency.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Core toolkit as explicitly authorized by user (`packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py`).
- Lazy registration of status/recall/cite/review/forget/sync/import/export (`packages/ai-parrot/src/parrot/memory/dynamics/cli.py`).
- Attach the lazy memory command group (`packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`).
- Explicit YAML, lazy resources, CLI scope and stdout purity (`packages/ai-parrot/tests/memory/agent_memory/test_operations.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

The original delivery (toolkit, dynamics CLI, operations tests) is merged and unchanged by this rework; only these two files change:

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Attach the memory command group lazily (no import of parrot.memory at startup) |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_lazy_memory.py` | CREATE | Fresh-subprocess regression: wikitoolkit commands do not import parrot.memory |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .factory import create_memory_manager
from .models import AgentMemoryConfig
from parrot.tools.toolkit import AbstractToolkit
from typing import Any
import click
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1504`: `def wiki(ctx: click.Context, verbose: bool) -> None:` (`@click.group(name="wiki")` at :1495).
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:140`: `from parrot.memory.dynamics.cli import register_memory_commands` (exactly 1 occurrence; remove it) and `:1516`: `register_memory_commands(wiki)` (exactly 1 occurrence; replace it).
- `packages/ai-parrot/src/parrot/memory/dynamics/cli.py`: `def register_memory_commands(group: click.Group) -> None:` returns early if `"memory" in group.commands`, otherwise builds the `memory` click group and ends with `group.add_command(memory)`; it imports `parrot.memory.agent_memory.toolkit` at module level (fine once only imported lazily).
- `packages/ai-parrot/tests/memory/agent_memory/test_operations.py:158`: `assert "memory" in wiki.commands` — must keep passing.
- click is 8.5.x here: `click.Group.make_context(info_name, args, parent=None, **extra)` is what a parent group calls on a subcommand before `invoke`.
- `packages/ai-parrot/src/parrot/tools/toolkit.py`: 225:class AbstractToolkit(ServerManagedToolkit, ABC):  # noqa: B024 -- deliberately has no required abstract methods; see below.
- `packages/ai-parrot/src/parrot/mcp/toolkit_config.py`: 21:class ToolkitSection(BaseModel):
- `packages/ai-parrot/src/parrot/tools/toolkit.py:426` — `AbstractToolkit._open`: `async def _open(self) -> None:`
- `packages/ai-parrot/src/parrot/tools/toolkit.py:442` — `AbstractToolkit._close`: `async def _close(self) -> None:`
- `packages/ai-parrot/src/parrot/tools/toolkit.py:455` — `AbstractToolkit._ensure_open`: `async def _ensure_open(self) -> None:`

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/test_cli_lazy_memory.py` is a new test (absent before this rework).
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_cli_lazy_memory.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#wiki"
  ]
}
```

## Implementation Notes

Use async I/O, strict hints, Pydantic v2 and Google docstrings; log through self.logger or
the module logger. Format Python with black (120) and run scoped ruff. Keep test logs under
artifacts/logs. All DB/process fixtures are isolated; no shared DDL or dependency mutation is
authorized. User explicitly confirmed that the new AgentMemoryToolkit remains in core at
parrot.memory.agent_memory; do not move it into parrot_tools.

## Implementation Blueprint

### Steps (in order)

1. Verify release preconditions and dependency contracts — unresolved evidence must not become invented implementation policy.
2. Recheck the exact anchors and imports below after dependencies land — overlapping writers deliberately run in sequence.
3. Apply each per-file block and complete its bounded FILL IN items — preserve public contracts outside this task's scope.
4. Implement the behavioral cases below with real temporary stores where persistence matters — mocks alone cannot prove durability.
5. Run the narrow validation commands and scoped style checks — do not mark missing backend evidence as a passing persistence test.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

Remove the module-level `from parrot.memory.dynamics.cli import register_memory_commands` (line 140) and the eager
`register_memory_commands(wiki)` call (line 1516). Attach a lightweight placeholder named `memory` instead:

```python
class _LazyMemoryGroup(click.Group):
    """`memory` command that imports parrot.memory only when it is actually used."""

    def __init__(self) -> None:
        super().__init__(name="memory", help="Operate on one explicitly configured agent-memory store.")
        self._resolved: click.Group | None = None

    def _real(self) -> click.Group:
        """Import the real group once (build it on a scratch group; take its `memory` command)."""
        ...  # import register_memory_commands HERE, call it on a scratch click.Group, return holder.commands["memory"]

    def make_context(self, info_name, args, parent=None, **extra):
        """Delegate parsing and invocation to the real group."""
        return self._real().make_context(info_name, args, parent=parent, **extra)

wiki.add_command(_LazyMemoryGroup())
```

- `wiki.commands["memory"]` exists at import time; its help line is static (no import needed to render `wikitoolkit --help`).
- `wikitoolkit memory <sub> ...` (options such as `--storage-path`, sub-commands, `--help`) behaves exactly as with the eager
  registration — the real group handles it. Do not change `dynamics/cli.py` behavior.
- No other import of `parrot.memory`, `parrot.clients` or the toolkit may be introduced at module level in `wiki/cli.py`.

### `packages/ai-parrot/tests/knowledge/wiki/test_cli_lazy_memory.py` (CREATE)

Fresh-subprocess regression (use `subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=...)`,
inherit the environment; the child prints one JSON line):
1. child imports `parrot.knowledge.wiki.cli`, invokes a real wikitoolkit command through `click.testing.CliRunner` (for example
   `wiki status --help`), and prints `{"exit_code": ..., "memory_loaded": <any module == "parrot.memory" or startswith "parrot.memory.">}` —
   assert `exit_code == 0` and `memory_loaded is False`;
2. child invokes `wiki memory --help` and prints the same plus whether the output contains `--storage-path` — assert exit 0, the
   option listed, and `memory_loaded is True` (the group still resolves on demand);
3. in-process: `"memory" in wiki.commands`.

### FILL IN checklist

- [ ] `wiki/cli.py`: no module-level import of `parrot.memory`; lazy `memory` group attached; behavior of `wikitoolkit memory ...` unchanged.
- [ ] `test_cli_lazy_memory.py`: fresh-subprocess assertions as described above.
- [ ] No placeholders; existing `test_operations.py` and `tests/knowledge/wiki/test_cli.py` keep passing.

## Acceptance Criteria

- [ ] Rework (issue:76c09075409e): `parrot.memory` is NOT imported when `parrot.knowledge.wiki.cli` is imported or a non-memory wikitoolkit command runs (fresh-subprocess test).
- [ ] `wiki.commands["memory"]` still exists and `wikitoolkit memory ...` (options, sub-commands, `--help`) behaves as before.
- [ ] The previously delivered behavior still holds: `tests/memory/agent_memory/test_operations.py` and `tests/knowledge/wiki/test_cli.py` pass.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_operations.py packages/ai-parrot/tests/knowledge/wiki/test_cli_lazy_memory.py packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`

## Test Specification

- `explicit_yaml_lazy_construct_close_reopen`: AC17: explicit YAML class_path/kwargs constructs the toolkit synchronously and acquires stores only in _open; close/reopen and partial failure work.
- `cli_scope_and_evidence_validation`: AC05/AC17: all operations use runtime/trusted scope and evidence references, not supplied grades; profile operations are not exposed to coder tooling by default.
- `wikitoolkit_commands_do_not_import_parrot_memory`, `memory_group_resolves_lazily`: see the regression test above.
- `jsonrpc_stdout_and_no_optimizer`: AC17/AC18: stdout stays JSON-RPC clean, no implicit registry, no fitting command/dependency, and shared SDD root is resolved independently of worker CWD.

Use deterministic clocks, runtime-derived identities and isolated temporary stores. Preserve
CancelledError. Use subprocesses for crash/multiprocess checks, never shared production data.

## Agent Instructions

1. Use the FEAT-892 worktree provisioned by sdd-start; never implement on dev.
2. Check every Depends-on task is done and each Release Preconditions item is met; blocked is not runnable.
3. Read the full spec and reverify this task's Codebase Contract; refresh stale evidence before editing.
4. Implement only declared files plus normal SDD state; preserve concurrent/unrelated changes.
5. Run validation, commit scoped implementation, and finalize with `parrot sdd task finalize`
   using real TaskCompletionEvidence and the exact implementation HEAD. Let finalization own
   the completion note and active-to-completed move; do not fabricate completion evidence.

## Completion Note

- Task: TASK-5678
- Feature: agent-memory-mixin
- Implementation SHA: 3d4ef24e71027298d47a084c1e39132a7e3e2516
- Closed at (UTC): 2026-11-16T02:11:30+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 (rework of the original sol delivery) · Duration: 545s · Tokens: n/a |
