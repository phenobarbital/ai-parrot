# TASK-5641: Probe registry and the `next` resolver

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5633, TASK-5638
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, goal G4 and design research S8: the position in the workflow is **derived**, not
recorded. A node is done when all its `done_when` checks hold; the valid next steps are the nodes
that are not done and whose `requires_procedures` are all done. No LLM call, no history.

---

## Scope

- Implement `ProbeRunner` and `resolve` in `resolver.py` (no import of `parrot.sdd`).
- Implement `PROBE_COSTS`, `SddProbeRunner` and `scope_for` in `procedure_probes.py` (no `main()`),
  reusing `LOCAL_PROBES`, `apply_check`, `feature_index`, `current_branch` and `checkout_root`
  from `procedure_advice`, and adding the two remote probes.
- Write `test_resolver.py`.

**NOT in scope**: the CLI verbs (TASK-5643, TASK-5644), the MCP tool (TASK-5649), rendering.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/resolver.py` | CREATE | `ProbeRunner`, `resolve` |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py` | CREATE | `PROBE_COSTS`, `SddProbeRunner`, `scope_for` |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_resolver.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). Models come from TASK-5633; the `procedure_advice` names from
> TASK-5637 / TASK-5638 — re-read that module after they land and correct this section if needed.

### Verified Imports
```python
from parrot.knowledge.wiki.procedure.models import (       # TASK-5633
    ProbeCheck, ProbeCost, ProbeResult, ProcedureSpec, ResolvedProcedure, Resolution,
)
from parrot.sdd.scripts.procedure_advice import (           # TASK-5637 / TASK-5638
    LOCAL_PROBES, apply_check, checkout_root, current_branch, feature_index,
)
from parrot.sdd.config import SddConfigError, load_sdd_config   # sdd/config.py:21, :278
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/procedure/models.py  (TASK-5633)
class ProbeResult(BaseModel): check: ProbeCheck; value: bool | None; cost: ProbeCost; detail: str = ""
class ResolvedProcedure(BaseModel): spec: ProcedureSpec; done: bool | None; ready: bool; preconditions: list[ProbeResult]
class Resolution(BaseModel): scope: dict[str, str]; stale: bool; next: list[ResolvedProcedure]; mandatory: list[ProcedureSpec]

# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py  (TASK-5638)
LOCAL_PROBES: dict[str, Probe]                      # Probe = Callable[[Path, Mapping[str, str], Mapping[str, str]], bool | None]
def apply_check(check: Mapping[str, Any], checkout: Path, scope: Mapping[str, str], *, probes=None) -> bool | None
def feature_index(checkout: Path, scope: Mapping[str, str]) -> dict[str, Any] | None
def current_branch(checkout: Path) -> str | None

# packages/ai-parrot/src/parrot/sdd/config.py
def load_sdd_config(root: Path | None = None) -> SddConfig      # :278; raises SddConfigError on an invalid file
class SddConfig(BaseModel): hotfix_base: str = "main"            # :32
```

### Does NOT Exist
- ~~An import of `parrot.sdd` in `resolver.py`~~ — forbidden; the resolver only knows the
  `ProbeRunner` protocol.
- ~~A `main()` in `procedure_probes.py`~~ — it must not have one.
- ~~A log of completed steps~~ — position is derived from `done_when` only.
- ~~`requests` / `httpx`~~ — the remote probes shell out to `git` and `gh` with a timeout.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/resolver.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_resolver.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#load_sdd_config"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **Resolver rules**:
  - A check's value is `None` when the runner does not know the probe (`cost` is `None`), or the
    probe is `remote` and `allow_remote` is false; otherwise `runner.run(check, scope)`.
  - `done(spec)`: `False` when `done_when` is empty; `True` when every check is `True`; `False`
    when any is `False`; else `None`. Compute it once per node (memoize).
  - `ready(spec)`: every id in `requires_procedures` is a known node whose `done` is `True`.
  - `next`: nodes with `mode != "constraint"`, `done is not True` and `ready`, each with its
    precondition results, ordered by (mandatory first, id).
  - `mandatory`: nodes with `mode == "mandatory"` and `done is not True`, ordered by id.
- **`SddProbeRunner.run`** builds `{"probe", "expect", "args": {**check.args, "hotfix_base": <value>}}`
  and calls `apply_check(..., probes=<local + remote>)`. `hotfix_base` comes from
  `load_sdd_config(checkout).hotfix_base`, read once, `"main"` on `SddConfigError`.
- **Remote probes** (`subprocess.run(..., capture_output=True, text=True, timeout=timeout)`; any
  `OSError`, `subprocess.SubprocessError` or unexpected output returns `None`):
  - `branch.pushed`: `git -C <checkout> rev-list --count @{u}..HEAD` — exit 0 and output `0` is
    `True`; exit 0 and another number is `False`; a non-zero exit (no upstream) is `False`.
  - `pr.open`: `gh pr list --head <branch> --json number --limit 1` — exit 0 and a non-empty JSON
    list is `True`; exit 0 and `[]` is `False`; anything else `None`. Unknown branch: `None`.
- **`scope_for`**: explicit arguments first. `feature` may be a slug or a `FEAT-<N>` id; normalize
  it to the index header's `feature` slug through `feature_index`. Without `feature`, derive it
  from the branch (`feat-<FEAT-ID>-<slug>`) or, when only `task` is given, from the index listing
  that task. `branch` is `current_branch(checkout)`. Keys with no value are omitted.
- Fixtures are local to the test file (no `conftest.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Write `resolver.py` — *why*: it is pure and testable with a fake runner.
2. Write `procedure_probes.py` — *why*: the real runner is thin once `apply_check` exists.
3. Write the tests (fake runner for the resolver; `tmp_path` repo and a patched
   `subprocess.run` for the runner).

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/resolver.py` (CREATE)
```python
"""Deterministic `next` resolution over a procedure graph (FEAT-891). No LLM, no history."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from parrot.knowledge.wiki.procedure.models import (
    ProbeCheck,
    ProbeCost,
    ProbeResult,
    ProcedureSpec,
    ResolvedProcedure,
    Resolution,
)


class ProbeRunner(Protocol):
    """Evaluates named probes for a scope."""

    def cost(self, probe: str) -> ProbeCost | None:
        """Cost class of a registered probe, or None when the probe is unknown."""
        ...

    def run(self, check: ProbeCheck, scope: Mapping[str, str]) -> bool | None:
        """Whether the check holds: True, False, or None when it cannot be decided."""
        ...


def resolve(specs: Sequence[ProcedureSpec], scope: Mapping[str, str], runner: ProbeRunner, *,
            allow_remote: bool = True, stale: bool = False) -> Resolution:
    """Evaluate done_when lazily, keep nodes that are not done and whose requires_procedures are
    all done, order them by (mode mandatory first, id), and attach their precondition results.
    A probe of cost 'remote' is reported as unknown when allow_remote is False."""
    by_id = {spec.id: spec for spec in specs}
    done_cache: dict[str, bool | None] = {}

    def result(check: ProbeCheck) -> ProbeResult:
        # FILL IN: per Implementation Notes "Resolver rules" (first bullet); cost defaults to "remote"
        # in the ProbeResult when the runner does not know the probe; detail says why a value is None.
        ...

    def done(spec: ProcedureSpec) -> bool | None:
        # FILL IN: memoized in done_cache.
        ...

    # FILL IN: build `next` and `mandatory` per the rules; return Resolution(scope=dict(scope), stale=stale, ...).
```
**Why this shape**: the protocol keeps `parrot.knowledge` free of `parrot.sdd`. Replace the `...`
placeholders with real bodies — they are blueprint gaps, not stubs to keep.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py` (CREATE)
```python
"""Probe registry and scope resolution for the procedure graph (FEAT-891). No main()."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.procedure.models import ProbeCheck, ProbeCost
from parrot.sdd.config import SddConfigError, load_sdd_config
from parrot.sdd.scripts.procedure_advice import LOCAL_PROBES, apply_check, current_branch, feature_index

REMOTE_PROBES = ("branch.pushed", "pr.open")
PROBE_COSTS: dict[str, ProbeCost] = {**dict.fromkeys(LOCAL_PROBES, "local"), **dict.fromkeys(REMOTE_PROBES, "remote")}
_FEATURE_BRANCH = re.compile(r"^feat-(FEAT-\d+)-(.+)$")
_LOGGER = logging.getLogger(__name__)


class SddProbeRunner:
    """ProbeRunner over a checkout: LOCAL_PROBES from procedure_advice plus the remote probes."""

    def __init__(self, checkout: Path, *, timeout: int = 5) -> None:
        self.checkout = Path(checkout)
        self.timeout = timeout
        self._probes: dict[str, Any] = {
            **LOCAL_PROBES,
            "branch.pushed": self._branch_pushed,
            "pr.open": self._pr_open,
        }
        self._hotfix_base: str | None = None

    def cost(self, probe: str) -> ProbeCost | None:
        """Cost class of a registered probe, or None."""
        return PROBE_COSTS.get(probe)

    def run(self, check: ProbeCheck, scope: Mapping[str, str]) -> bool | None:
        """Apply one check with the shared semantics of procedure_advice.apply_check."""
        # FILL IN: per Implementation Notes "SddProbeRunner.run".

    def _branch_pushed(self, checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
        # FILL IN: per Implementation Notes "Remote probes".
        ...

    def _pr_open(self, checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
        # FILL IN
        ...


def scope_for(checkout: Path, *, feature: str | None = None, task: str | None = None) -> dict[str, str]:
    """Fill 'feature', 'task' and 'branch': explicit arguments first, then the current branch
    name ('feat-<FEAT-ID>-<slug>'), matching per-spec index headers by feature or feature_id."""
    # FILL IN: per Implementation Notes "scope_for".
```

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_resolver.py` (CREATE)
```python
"""Tests for the procedure resolver and the SDD probe runner (FEAT-891)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.procedure.models import ProbeCheck, ProcedureSpec
from parrot.knowledge.wiki.procedure.resolver import resolve
from parrot.sdd.scripts import procedure_probes
from parrot.sdd.scripts.procedure_probes import PROBE_COSTS, SddProbeRunner, scope_for


class FakeRunner:
    """Answers checks from a {probe: value} table; `remote` lists the remote probe names."""

    def __init__(self, values: dict[str, bool | None], remote: tuple[str, ...] = ()) -> None:
        self.values, self.remote = values, remote

    def cost(self, probe: str):
        return None if probe not in self.values else ("remote" if probe in self.remote else "local")

    def run(self, check: ProbeCheck, scope):
        return self.values[check.probe]


def _graph() -> list[ProcedureSpec]:
    """spec -> task -> start(task) -> task-close(mandatory) ; done requires task. As in spec §3 M9."""
    # FILL IN


def test_resolver_next_without_history() -> None:
    """`spec` done, `task` not -> `task` is next; mandatory nodes are listed."""
    # FILL IN


def test_resolver_remote_unknown_when_disallowed() -> None:
    """allow_remote=False reports a remote probe as unknown and never calls the runner for it."""
    # FILL IN


def test_resolver_is_deterministic() -> None:
    """Two runs over the same state return equal Resolution objects, ordered mandatory first then id."""
    # FILL IN


def test_probe_costs_cover_the_table() -> None:
    """PROBE_COSTS has exactly the nine probes of spec §2 with their cost classes."""
    assert PROBE_COSTS == {
        "spec.exists": "local", "index.exists": "local", "task.status": "local", "task.depends_done": "local",
        "feature.tasks_done": "local", "flow.base_allowed": "local", "env.not_worker_sandbox": "local",
        "branch.pushed": "remote", "pr.open": "remote",
    }


def test_scope_for_from_branch_and_arguments(tmp_path: Path) -> None:
    """The feature comes from an explicit slug or FEAT id, else from a feat-<FEAT-ID>-<slug> branch."""
    # FILL IN: tmp repo with .git/HEAD on feat-FEAT-1-demo and sdd/tasks/index/demo.json (feature_id FEAT-1).


def test_runner_remote_probe_failure_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A timeout or a missing binary in a remote probe yields None, never an exception."""
    # FILL IN: monkeypatch procedure_probes.subprocess.run to raise subprocess.TimeoutExpired / FileNotFoundError.
```

### FILL IN checklist
- [ ] `resolver.py::resolve` — the three inner pieces; bounded by "Resolver rules"
- [ ] `procedure_probes.py::SddProbeRunner.run`, the two remote probes, `scope_for`
- [ ] `test_resolver.py` — `_graph` and six test bodies

---

## Acceptance Criteria

- [ ] `resolve` gives the same answer on two runs with unchanged state and makes no LLM call.
- [ ] A node with empty `done_when` is never done; an unknown or disallowed-remote probe is reported as unknown.
- [ ] `resolver.py` imports nothing from `parrot.sdd`; `procedure_probes.py` has no `main()`.
- [ ] `PROBE_COSTS` lists exactly the nine probes of spec §2.
- [ ] A failing remote probe returns `None`.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_resolver.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5633 and TASK-5638 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN` and replace every `...` placeholder.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5641 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
