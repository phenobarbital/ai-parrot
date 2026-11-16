# TASK-5678: Core AgentMemoryToolkit and lazy CLI operations

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
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

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py` | CREATE | Core toolkit as explicitly authorized by user |
| `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` | CREATE | Lazy registration of status/recall/cite/review/forget/sync/import/export |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Attach the lazy memory command group |
| `packages/ai-parrot/tests/memory/agent_memory/test_operations.py` | CREATE | Explicit YAML, lazy resources, CLI scope and stdout purity |

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

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1503`: `def wiki(ctx: click.Context, verbose: bool) -> None:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/tools/toolkit.py`: 225:class AbstractToolkit(ServerManagedToolkit, ABC):  # noqa: B024 -- deliberately has no required abstract methods; see below.
- `packages/ai-parrot/src/parrot/mcp/toolkit_config.py`: 21:class ToolkitSection(BaseModel):
- `packages/ai-parrot/src/parrot/tools/toolkit.py:426` — `AbstractToolkit._open`: `async def _open(self) -> None:`
- `packages/ai-parrot/src/parrot/tools/toolkit.py:442` — `AbstractToolkit._close`: `async def _close(self) -> None:`
- `packages/ai-parrot/src/parrot/tools/toolkit.py:455` — `AbstractToolkit._ensure_open`: `async def _ensure_open(self) -> None:`

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/agent_memory/test_operations.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_operations.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#ToolkitSection",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._close",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._ensure_open",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._open"
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

### `packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py` (CREATE)

```python
"""Explicitly configured core memory toolkit with lazy resource ownership."""
from typing import Any
from parrot.tools.toolkit import AbstractToolkit
from .factory import create_memory_manager
from .models import AgentMemoryConfig

class AgentMemoryToolkit(AbstractToolkit):
    """Expose scoped memory operations over the same stores as agents."""
    def __init__(self, config: dict[str, Any], namespace: dict[str, Any], **kwargs: Any) -> None:
        """Validate trusted serializable configuration without opening resources."""
        super().__init__(**kwargs)
        # FILL IN: validate config/namespace, no model-chosen principal — AC05/AC17.

    async def _open(self) -> None:
        """Construct configured stores; unwind partially acquired resources on failure."""
        # FILL IN: create_memory_manager with explicit ownership — AC07/AC17.
        raise NotImplementedError

    async def _close(self) -> None:
        """Drain/close owned resources and reset inherited opened state."""
        # FILL IN: idempotent cleanup then await super()._close() — AC07/AC17.
        raise NotImplementedError

    async def memory_status(self) -> dict[str, Any]:
        """Report enabled capabilities, durable pending reviews and degraded state."""
        # FILL IN: scoped store status without exposing secrets — AC17.
        raise NotImplementedError

    # FILL IN: typed/docstringed recall/cite/review/forget/sync/import operations — AC17.
    # Accept evidence references, never model grades; user profile operations disabled by default.
```

**Why:** The MCP constructor receives serialized kwargs before any async lifecycle; lazy acquisition and inherited close-state reset make reopen reliable.

### `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` (CREATE)

```python
"""Lazy memory CLI registration; resource acquisition belongs to command execution."""
import click

def register_memory_commands(group: click.Group) -> None:
    """Attach status/recall/cite/review/forget/sync/import-feedback/export-reviews commands."""
    # FILL IN: explicit configuration, async operation bridge, structured status — AC17.
    # No fitting command/optimizer import; retain existing configured memory target semantics.
    raise NotImplementedError
```

**Why:** The MCP constructor receives serialized kwargs before any async lifecycle; lazy acquisition and inherited close-state reset make reopen reliable.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'def wiki(ctx: click.Context, verbose: bool) -> None:' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1503: def wiki(ctx: click.Context, verbose: bool) -> None:
# Attach the lazy memory command group.
# FILL IN: AC17: explicit YAML class_path/kwargs constructs the toolkit synchronously and acquires stores only in _open; close/reopen and partial failure work.
# FILL IN: AC05/AC17: all operations use runtime/trusted scope and evidence references, not supplied grades; profile operations are not exposed to coder tooling by default.
# FILL IN: AC17/AC18: stdout stays JSON-RPC clean, no implicit registry, no fitting command/dependency, and shared SDD root is resolved independently of worker CWD.
```

**Why:** The MCP constructor receives serialized kwargs before any async lifecycle; lazy acquisition and inherited close-state reset make reopen reliable.

### `packages/ai-parrot/tests/memory/agent_memory/test_operations.py` (CREATE)

```python
"""Behavioral acceptance tests for Core AgentMemoryToolkit and lazy CLI operations."""
import pytest

def test_explicit_yaml_lazy_construct_close_reopen() -> None:
    """Verify explicit yaml lazy construct close reopen."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_cli_scope_and_evidence_validation() -> None:
    """Verify cli scope and evidence validation."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_jsonrpc_stdout_and_no_optimizer() -> None:
    """Verify jsonrpc stdout and no optimizer."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** The MCP constructor receives serialized kwargs before any async lifecycle; lazy acquisition and inherited close-state reset make reopen reliable.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/agent_memory/toolkit.py` — Core toolkit as explicitly authorized by user; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/cli.py` — Lazy registration of status/recall/cite/review/forget/sync/import/export; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — Attach the lazy memory command group; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_operations.py` — Explicit YAML, lazy resources, CLI scope and stdout purity; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC17: explicit YAML class_path/kwargs constructs the toolkit synchronously and acquires stores only in _open; close/reopen and partial failure work.
- [ ] AC05/AC17: all operations use runtime/trusted scope and evidence references, not supplied grades; profile operations are not exposed to coder tooling by default.
- [ ] AC17/AC18: stdout stays JSON-RPC clean, no implicit registry, no fitting command/dependency, and shared SDD root is resolved independently of worker CWD.
- [ ] User instruction: AgentMemoryToolkit remains core at parrot.memory.agent_memory; this explicit exception overrides the general concrete-toolkit location convention for this feature.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_operations.py -q`

## Test Specification

- `explicit_yaml_lazy_construct_close_reopen`: AC17: explicit YAML class_path/kwargs constructs the toolkit synchronously and acquires stores only in _open; close/reopen and partial failure work.
- `cli_scope_and_evidence_validation`: AC05/AC17: all operations use runtime/trusted scope and evidence references, not supplied grades; profile operations are not exposed to coder tooling by default.
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
