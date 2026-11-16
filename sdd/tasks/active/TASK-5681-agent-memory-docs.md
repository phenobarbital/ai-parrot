# TASK-5681: Documentation — agent-memory, user-memory and memory-dynamics

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5653, TASK-5654, TASK-5655, TASK-5656, TASK-5657, TASK-5658, TASK-5659, TASK-5660, TASK-5661, TASK-5662, TASK-5663, TASK-5664, TASK-5665, TASK-5666, TASK-5667, TASK-5668, TASK-5669, TASK-5670, TASK-5671, TASK-5672, TASK-5673, TASK-5674, TASK-5675, TASK-5676, TASK-5677, TASK-5678, TASK-5679, TASK-5680
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes documented public symbols, configuration or migration behavior from A0/X1 from TASK-5653; Consumes documented public symbols, configuration or migration behavior from A0 from TASK-5654; Consumes documented public symbols, configuration or migration behavior from M1 from TASK-5655; Consumes documented public symbols, configuration or migration behavior from M1/M3 from TASK-5656; Consumes documented public symbols, configuration or migration behavior from M1 from TASK-5657; Consumes documented public symbols, configuration or migration behavior from A1/M3 from TASK-5658; Consumes documented public symbols, configuration or migration behavior from M1 from TASK-5659; Consumes documented public symbols, configuration or migration behavior from M2 from TASK-5660; Consumes documented public symbols, configuration or migration behavior from M2 from TASK-5661; Consumes documented public symbols, configuration or migration behavior from M2 from TASK-5662; Consumes documented public symbols, configuration or migration behavior from M2 from TASK-5663; Consumes documented public symbols, configuration or migration behavior from M2 from TASK-5664; Consumes documented public symbols, configuration or migration behavior from M2 from TASK-5665; Consumes documented public symbols, configuration or migration behavior from U1 from TASK-5666; Consumes documented public symbols, configuration or migration behavior from U1 from TASK-5667; Consumes documented public symbols, configuration or migration behavior from U1 from TASK-5668; Consumes documented public symbols, configuration or migration behavior from A1/M3 from TASK-5669; Consumes documented public symbols, configuration or migration behavior from A1 from TASK-5670; Consumes documented public symbols, configuration or migration behavior from M6/A1 from TASK-5671; Consumes documented public symbols, configuration or migration behavior from A1 from TASK-5672; Consumes documented public symbols, configuration or migration behavior from A1 from TASK-5673; Consumes documented public symbols, configuration or migration behavior from M3 from TASK-5674; Consumes documented public symbols, configuration or migration behavior from M5 from TASK-5675; Consumes documented public symbols, configuration or migration behavior from M5 from TASK-5676; Consumes documented public symbols, configuration or migration behavior from M5 from TASK-5677; Consumes documented public symbols, configuration or migration behavior from M6 from TASK-5678; Consumes documented public symbols, configuration or migration behavior from M6 from TASK-5679; Consumes documented public symbols, configuration or migration behavior from X1 from TASK-5680

## Context

Implement the bounded X1/docs slice of FEAT-892 revision 0.2. The owner's accepted
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

- Architecture, flags, lifecycle, scope and hard-cut migration (`wiki/memory/agent-memory.md`).
- Independent knowledge, provenance, correction and suppression (`wiki/memory/user-memory.md`).
- Accepted gates, evidence, backends, CLI/MCP/export and measured limits (`wiki/memory/memory-dynamics.md`).
- Run required techwiki check through registered pytest runner (`packages/ai-parrot/tests/memory/agent_memory/test_documentation.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/memory/agent-memory.md` | CREATE | Architecture, flags, lifecycle, scope and hard-cut migration |
| `wiki/memory/user-memory.md` | CREATE | Independent knowledge, provenance, correction and suppression |
| `wiki/memory/memory-dynamics.md` | CREATE | Accepted gates, evidence, backends, CLI/MCP/export and measured limits |
| `packages/ai-parrot/tests/memory/agent_memory/test_documentation.py` | CREATE | Run required techwiki check through registered pytest runner |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from pathlib import Path
import json
import subprocess
```

### Existing Signatures and Anchors

- This task creates new files and consumes only the explicitly declared prerequisite contracts.

### Does NOT Exist

- `wiki/memory/agent-memory.md` is a new delivery path, absent on the verified base.
- `wiki/memory/user-memory.md` is a new delivery path, absent on the verified base.
- `wiki/memory/memory-dynamics.md` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/agent_memory/test_documentation.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/memory/agent-memory.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/memory/user-memory.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/memory/memory-dynamics.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_documentation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
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

### `wiki/memory/agent-memory.md` (CREATE)

```markdown
---
title: Agent Memory
summary: Architecture, flags, lifecycle, scope and hard-cut migration
---

# Agent Memory

## Purpose

<!-- FILL IN: explain delivered behavior and ownership — AC19. -->

## Public API

<!-- FILL IN: ref: links to implemented symbols — AC19. -->

## Configuration & Parameters

<!-- FILL IN: verified fields/defaults and limits — AC04/AC13. -->

## Usage Examples

<!-- FILL IN: executable examples against delivered public API — AC17/AC19. -->

## Gotchas

<!-- FILL IN: gate, scope, migration and durability limitations — AC08/AC12. -->

## Related

<!-- FILL IN: sibling wiki pages and FEAT-571/FEAT-889 ownership — AC01/AC15. -->
```

**Why:** Examples and API links must describe the delivered gated behavior, including the core toolkit exception and explicitly deferred brain/fitting work.

### `wiki/memory/user-memory.md` (CREATE)

```markdown
---
title: User Memory
summary: Independent knowledge, provenance, correction and suppression
---

# User Memory

## Purpose

<!-- FILL IN: explain delivered behavior and ownership — AC19. -->

## Public API

<!-- FILL IN: ref: links to implemented symbols — AC19. -->

## Configuration & Parameters

<!-- FILL IN: verified fields/defaults and limits — AC04/AC13. -->

## Usage Examples

<!-- FILL IN: executable examples against delivered public API — AC17/AC19. -->

## Gotchas

<!-- FILL IN: gate, scope, migration and durability limitations — AC08/AC12. -->

## Related

<!-- FILL IN: sibling wiki pages and FEAT-571/FEAT-889 ownership — AC01/AC15. -->
```

**Why:** Examples and API links must describe the delivered gated behavior, including the core toolkit exception and explicitly deferred brain/fitting work.

### `wiki/memory/memory-dynamics.md` (CREATE)

```markdown
---
title: Memory Dynamics
summary: Accepted gates, evidence, backends, CLI/MCP/export and measured limits
---

# Memory Dynamics

## Purpose

<!-- FILL IN: explain delivered behavior and ownership — AC19. -->

## Public API

<!-- FILL IN: ref: links to implemented symbols — AC19. -->

## Configuration & Parameters

<!-- FILL IN: verified fields/defaults and limits — AC04/AC13. -->

## Usage Examples

<!-- FILL IN: executable examples against delivered public API — AC17/AC19. -->

## Gotchas

<!-- FILL IN: gate, scope, migration and durability limitations — AC08/AC12. -->

## Related

<!-- FILL IN: sibling wiki pages and FEAT-571/FEAT-889 ownership — AC01/AC15. -->
```

**Why:** Examples and API links must describe the delivered gated behavior, including the core toolkit exception and explicitly deferred brain/fitting work.

### `packages/ai-parrot/tests/memory/agent_memory/test_documentation.py` (CREATE)

```python
"""Check required feature documentation through the registered pytest runner."""
import json
from pathlib import Path
import subprocess

def test_required_techwiki_command_and_pages() -> None:
    """Run the required CLI and reject advisory missing/empty-page results."""
    root = Path(__file__).resolve().parents[5]
    result = subprocess.run(
        ["parrot", "sdd", "techwiki", "check", "--spec",
         "sdd/specs/agent-memory-mixin.spec.md", "--root", ".", "--json"],
        cwd=root, capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    # FILL IN: verify the current CLI JSON envelope before selecting the decision — AC19.
    # Require status ok and no missing/empty/reason_codes; the checker is advisory by design.
    # Verify every ref: link resolves using the existing techwiki API helpers — AC19.
    # The CLI checks module-name syntax, not actual symbol existence; do not conflate the two.
    raise NotImplementedError
```

**Why:** Examples and API links must describe the delivered gated behavior, including the core toolkit exception and explicitly deferred brain/fitting work.

### FILL IN checklist

- [ ] `wiki/memory/agent-memory.md` — Architecture, flags, lifecycle, scope and hard-cut migration; bounded by the acceptance criteria below.
- [ ] `wiki/memory/user-memory.md` — Independent knowledge, provenance, correction and suppression; bounded by the acceptance criteria below.
- [ ] `wiki/memory/memory-dynamics.md` — Accepted gates, evidence, backends, CLI/MCP/export and measured limits; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_documentation.py` — Run required techwiki check through registered pytest runner; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC19: exactly the three required pages follow sdd/templates/techwiki-page.md and link actual public API symbols with ref: links.
- [ ] AC08/AC15: explain flags, precedence, rejected legacy names, manager brain-constructor break, public brain_service staging and FEAT-889 ownership.
- [ ] AC10/AC13/AC18: distinguish accepted policy from measured gates, state the supported ceiling and provisional thresholds, and explicitly defer fitting.
- [ ] AC19: parrot sdd techwiki check --spec sdd/specs/agent-memory-mixin.spec.md --root . completes; missing pages/API references are addressed, not hidden by an informational exit code.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_documentation.py -q`

## Test Specification

- `required_techwiki_command_and_pages`: AC19: exactly the three required pages follow sdd/templates/techwiki-page.md and link actual public API symbols with ref: links.

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

## Required Documentation Check

Run `parrot sdd techwiki check --spec sdd/specs/agent-memory-mixin.spec.md --root .`.
The repository currently registers no techwiki test runner. The declared pytest test must
invoke this exact CLI with subprocess.run and inspect its JSON/report for missing pages/API
symbols as well as exit status. Do not add an unrelated runner extension or weaken graph lint.
