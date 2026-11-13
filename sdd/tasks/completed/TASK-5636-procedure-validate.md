# TASK-5636: Deterministic graph validation

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5633
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (the pure part) and goal G5: preconditions are named probes validated
deterministically. `validate_graph` is reused by `parrot sdd procedure check`, by `build` (errors
abort) and by the lint rule (TASK-5642).

---

## Scope

- Implement `GraphFinding` and `validate_graph` in `validate.py`, pure (no I/O, no store, no
  `parrot.sdd` import).
- Implement the nine finding codes of the table below, with the exact code strings and severities.
- Write `test_validate.py` with one case per code.

**NOT in scope**: the lint rule and `packs/__init__.py` (TASK-5642); computing `known_commands`
(the CLI does it, TASK-5643); probe implementations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/validate.py` | CREATE | `GraphFinding`, `validate_graph` |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). The models come from TASK-5633 — re-check after it lands.

### Verified Imports
```python
from pydantic import BaseModel
from parrot.knowledge.wiki.procedure.models import ProbeCost, ProcedureSpec   # TASK-5633
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/procedure/models.py  (TASK-5633)
class ProcedureSpec(BaseModel):
    id: str; mode: ProcedureMode; source: ProcedureSource; command: str
    preconditions: list[ProbeCheck]; done_when: list[ProbeCheck]
    requires_procedures: list[str]; guards: list[GuardSpec]; use_instead: str
    executor: ExecutorRef | None; confirm: bool; advice: str
    def edges(self) -> list[tuple[str, str, str]]: ...     # (src, dst, rel)
class ProbeCheck(BaseModel): probe: str; expect: bool | str; args: dict[str, str]
class GuardSpec(BaseModel): kind: GuardKind   # "entry" | "bypass"
```

### Does NOT Exist
- ~~A probe registry in this package~~ — probe names and costs are passed in as `known_probes`;
  the registry (`PROBE_COSTS`) is created by TASK-5641 in `parrot/sdd/scripts/procedure_probes.py`.
- ~~`parrot.knowledge.lint` usage here~~ — the lint `Finding` model is used only by TASK-5642.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/validate.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- Finding codes (exact strings):

  | Code | Severity | Condition |
  |---|---|---|
  | `broken-edge` | error | an edge target that is not a node id; relations `applies_to` and `learned_from` are exempt |
  | `requires-cycle` | error | a cycle in `requires_procedures`; one finding per cycle, subjects = its sorted member ids |
  | `unknown-probe` | error | a `ProbeCheck.probe` (in `preconditions` or `done_when`) not in `known_probes` |
  | `remote-probe-in-guard` | warning | a node with at least one guard whose `preconditions` are non-empty and all of cost `remote` |
  | `mandatory-without-enforcement` | error | `mode == "mandatory"` with no guard and `executor is None` |
  | `bypass-without-alternative` | error | a `bypass` guard on a node with empty `use_instead` |
  | `learned-mandatory` | error | `source == "learned"` with `mode == "mandatory"` or `confirm is True` |
  | `uncovered-command` | warning | a name in `known_commands` that no node's `command` mentions as a whole token |
  | `advice-too-long` | error | `advice` longer than 300 characters |

- "Whole token" for `uncovered-command`: the name is not preceded or followed by a letter, digit,
  `_` or `-` (`sdd-task` does not match inside `sdd-tasks`, and is not matched by `sdd task`).
- A cycle made only of `next` edges is legal and produces no finding.
- Fixtures are local to the test file (no `conftest.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Write `GraphFinding` and the per-code checks as small private functions — *why*: one function
   per code keeps each rule testable and the table auditable.
2. Sort the result by `(code, subjects)` — *why*: the output must be identical between runs.
3. Write one test per code plus the `next`-cycle case.

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/validate.py` (CREATE)
```python
"""Deterministic checks over a procedure graph (FEAT-891). Pure: no I/O."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.procedure.models import ProbeCost, ProcedureSpec

ADVICE_MAX_CHARS = 300
_EDGE_EXEMPT = frozenset({"applies_to", "learned_from"})


class GraphFinding(BaseModel):
    """One problem found in a procedure graph."""

    code: str
    severity: Literal["error", "warning"]
    subjects: list[str] = Field(default_factory=list)
    message: str


def _mentions(command: str, name: str) -> bool:
    """True when ``name`` appears in ``command`` as a whole token."""
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", command) is not None


def _requires_cycles(specs: Sequence[ProcedureSpec]) -> list[list[str]]:
    """Return each cycle of the requires_procedures graph once, as its sorted member ids."""
    # FILL IN: depth-first search over {spec.id: spec.requires_procedures} restricted to known ids;
    # deduplicate cycles by their sorted member tuple.


def validate_graph(
    specs: Sequence[ProcedureSpec],
    *,
    known_probes: Mapping[str, ProbeCost],
    known_commands: Sequence[str] = (),
) -> list[GraphFinding]:
    """Return every finding, sorted by (code, subjects)."""
    findings: list[GraphFinding] = []
    ids = {spec.id for spec in specs}
    for spec in specs:
        for _src, dst, rel in spec.edges():
            if rel not in _EDGE_EXEMPT and dst not in ids:
                findings.append(GraphFinding(code="broken-edge", severity="error", subjects=[spec.id, dst],
                                             message=f"{spec.id} has a '{rel}' edge to unknown node {dst}"))
        # FILL IN: unknown-probe, remote-probe-in-guard, mandatory-without-enforcement,
        # bypass-without-alternative, learned-mandatory, advice-too-long — one GraphFinding each,
        # subjects starting with spec.id, conditions exactly as in the Implementation Notes table.
    # FILL IN: requires-cycle (from _requires_cycles) and uncovered-command (from known_commands and
    # _mentions over every spec.command; subjects = [name]).
    return sorted(findings, key=lambda f: (f.code, f.subjects))
```
**Why this shape**: the signature and the code table are fixed by spec §3 M3. `known_probes` maps a
probe name to its cost so `remote-probe-in-guard` needs no second argument.

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py` (CREATE)
```python
"""Tests for the procedure graph validator (FEAT-891)."""

import pytest

from parrot.knowledge.wiki.procedure.models import ProcedureSpec
from parrot.knowledge.wiki.procedure.validate import validate_graph

PROBES = {"spec.exists": "local", "pr.open": "remote"}


def _spec(node_id: str, **overrides) -> ProcedureSpec:
    return ProcedureSpec(**{"id": node_id, "title": node_id, "kind": "command", **overrides})


def _codes(specs, **kwargs) -> list[str]:
    return [f.code for f in validate_graph(specs, known_probes=PROBES, **kwargs)]


@pytest.mark.parametrize(
    ("specs", "kwargs", "code"),
    [
        # FILL IN: one row per code of the Implementation Notes table, each a minimal graph that
        # triggers exactly that code (9 rows).
    ],
)
def test_validate_codes(specs, kwargs, code) -> None:
    """Each finding code fires on its minimal graph."""
    assert code in _codes(specs, **kwargs)


def test_clean_graph_and_next_cycle() -> None:
    """A valid graph with a `next` cycle produces no finding."""
    # FILL IN: a -> next b, b -> next a, b requires a; assert validate_graph(...) == []


def test_findings_sorted_and_stable() -> None:
    """Two runs return the same list, sorted by (code, subjects)."""
    # FILL IN
```

### FILL IN checklist
- [ ] `validate.py::_requires_cycles` — one finding per cycle, no duplicates
- [ ] `validate.py::validate_graph` — the remaining eight codes, conditions from the table
- [ ] `test_validate.py` — nine parametrized rows and two test bodies

---

## Acceptance Criteria

- [ ] All nine codes exist with the exact strings and severities of the table.
- [ ] `applies_to` and `learned_from` targets never produce `broken-edge`.
- [ ] A `next` cycle produces no finding; a `requires_procedures` cycle produces one `requires-cycle`.
- [ ] `validate.py` performs no I/O and imports nothing from `parrot.sdd`.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5633 is `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`; never change a signature the blueprint fixes.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5636 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-5636
- Feature: procedural-graph-plane
- Implementation SHA: 8f749cc587fa1021c0bb68f0c0e6a511a5d16920
- Closed at (UTC): 2026-11-13T22:07:15+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 276.0s · Tokens: n/a |
