# TASK-5639: Compiled index — build, atomic publish, staleness

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5633, TASK-5637
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (index half), §2 "Plane and index" and design research S3: readers must see one
complete snapshot, so `procedures.json` is written to a temp file in the same directory and
published with `os.replace`. The hook (TASK-5637/5638) reads this file with the stdlib; a contract
test in this task ties the writer and that reader together.

---

## Scope

- Implement `compile_index`, `publish_index`, `read_index`, `is_stale` in `index.py`.
- Write `test_index_plane.py` with the index tests and `test_index_contract`.

**NOT in scope**: the wiki store and `ProcedurePlane` (TASK-5640); probes; the CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/index.py` | CREATE | Index document, publish, read, staleness |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py` | CREATE | Index and contract tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). Models come from TASK-5633 and `procedure_advice` from
> TASK-5637 — re-check both after they land.

### Verified Imports
```python
from parrot.knowledge.wiki.procedure.models import INDEX_FILE, INDEX_SCHEMA_VERSION, ProbeCost, ProcedureSpec   # TASK-5633
from parrot.sdd.scripts import procedure_advice                       # TASK-5637 — tests only
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/procedure/models.py  (TASK-5633)
INDEX_SCHEMA_VERSION = 1; INDEX_FILE = "procedures.json"
class ProcedureSpec(BaseModel):
    id: str; title: str; mode: ProcedureMode; command: str; use_instead: str; advice: str
    preconditions: list[ProbeCheck]; guards: list[GuardSpec]
class GuardSpec(BaseModel): kind; executable: str; argv_prefix: list[str]; path_globs: list[str]; scope: dict[str, ScopeArg]
class ProbeCheck(BaseModel): probe: str; expect: bool | str; args: dict[str, str]

# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py  (TASK-5637)
INDEX_SCHEMA_VERSION = 1; PLANE_DIR = Path(".parrot") / "procedure"; INDEX_FILE = "procedures.json"
def load_index(root: Path) -> dict[str, Any] | None: ...
```

### Does NOT Exist
- ~~`MANIFEST_DIR` import from `producers`~~ — TASK-5635 is not a dependency of this task. Define
  the literal `Path("sdd") / "procedures"` locally as `_MANIFEST_DIR` in `index.py`.
- ~~A lock file or a database for the index~~ — atomic rename only.
- ~~Writing the index from a hook~~ — nothing is written at hook time.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/index.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **Document** (spec §2 "Compiled index", `schema_version` 1):
  - `sources`: one `{"path": <POSIX path relative to root>, "sha1": <hex of the file bytes>}` per
    source file, sorted by path.
  - `guards`: one entry per `GuardSpec` of every spec, in spec order then guard order:
    `{"procedure": spec.id, "kind", "executable", "argv_prefix", "path_globs", "scope"}` where
    `scope` is `{key: {"argv": N}}` or `{key: {"flag": "..."}}` (only the set member).
  - `procedures`: `{spec.id: {"title", "mode", "command", "use_instead", "advice", "preconditions"}}`
    with each precondition as `{"probe", "expect", "args", "cost"}`; `cost` is
    `probe_costs.get(probe, "remote")` — an unknown probe is treated as remote so the hook never
    runs it.
  - `generation`: sha1 hex of the canonical JSON of the document **without** the `generation` key
    (`json.dumps(doc, sort_keys=True, separators=(",", ":"))`).
- **Publish**: `tempfile.NamedTemporaryFile` (or `mkstemp`) with `dir=plane_dir`, write, flush,
  `os.fsync`, then `os.replace(tmp, plane_dir / INDEX_FILE)`. Create `plane_dir` when missing.
  Remove the temp file if anything fails before the replace.
- **Stale** when: the document is `None`; a listed source file is missing; a listed source's sha1
  differs; or a `*.yaml` under `<root>/sdd/procedures/` is not listed.
- Fixtures are local to the test file (no `conftest.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Write `compile_index` — *why*: the document is a pure function of specs and source bytes.
2. Write `publish_index` / `read_index` — *why*: the atomic protocol is the point of the module.
3. Write `is_stale` — *why*: the CLI rebuilds on it and the docs explain it.
4. Write the tests, including the contract test against `procedure_advice.load_index`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/index.py` (CREATE)
```python
"""Compiled procedure index: one JSON file, published atomically (FEAT-891)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.procedure.models import INDEX_FILE, INDEX_SCHEMA_VERSION, ProbeCost, ProcedureSpec

_MANIFEST_DIR = Path("sdd") / "procedures"
_LOGGER = logging.getLogger(__name__)


def _sha1_file(path: Path) -> str:
    """sha1 hex digest of the file's bytes."""
    return hashlib.sha1(path.read_bytes()).hexdigest()  # noqa: S324 — content fingerprint, not security


def compile_index(specs: Sequence[ProcedureSpec], sources: Sequence[Path], *, root: Path,
                  probe_costs: Mapping[str, ProbeCost]) -> dict[str, Any]:
    """Return the index document; 'generation' is the sha1 of its canonical JSON."""
    document: dict[str, Any] = {"schema_version": INDEX_SCHEMA_VERSION}
    # FILL IN: sources, guards, procedures exactly as in the Implementation Notes "Document";
    # then document["generation"] = sha1 of the canonical JSON computed BEFORE adding the key.
    return document


def publish_index(plane_dir: Path, document: Mapping[str, Any]) -> Path:
    """Write procedures.json via a temp file in plane_dir + os.replace; return the path."""
    plane_dir.mkdir(parents=True, exist_ok=True)
    target = plane_dir / INDEX_FILE
    # FILL IN: per Implementation Notes "Publish". Log at debug level with the generation.
    return target


def read_index(plane_dir: Path) -> dict[str, Any] | None:
    """Return the document, or None when absent, unreadable or of another schema version."""
    # FILL IN


def is_stale(document: Mapping[str, Any] | None, *, root: Path) -> bool:
    """True when document is None, a listed source is missing or its sha1 differs, or a manifest
    under sdd/procedures is not listed."""
    # FILL IN: per Implementation Notes "Stale".
```
**Why this shape**: the four signatures are fixed by spec §3 M4. `sort_keys` + compact separators
make `generation` independent of dict ordering, so two builds of the same input publish the same
bytes.

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py` (CREATE)
```python
"""Tests for the compiled procedure index and the plane (FEAT-891)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from parrot.knowledge.wiki.procedure import index as index_mod
from parrot.knowledge.wiki.procedure.index import compile_index, is_stale, publish_index, read_index
from parrot.knowledge.wiki.procedure.models import INDEX_SCHEMA_VERSION, PLANE_DIR, ProcedureSpec
from parrot.sdd.scripts import procedure_advice

COSTS = {"task.status": "local", "pr.open": "remote"}


def _source(root: Path, name: str = "sdd-workflow.yaml", text: str = "graph: sdd\n") -> Path:
    """Write sdd/procedures/<name> under root and return its path."""
    # FILL IN


def _specs() -> list[ProcedureSpec]:
    """One mandatory node with an entry guard (scope task argv 0) and a `task.status` precondition, one plain node."""
    # FILL IN


def test_index_atomic_and_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish goes through a temp file + os.replace; generation is stable for equal input."""
    # FILL IN: record os.replace calls via monkeypatch.setattr(index_mod.os, "replace", wrapper); assert one
    # call whose source is in plane_dir and differs from the target; compile twice -> equal generation;
    # no temp file is left in plane_dir.


def test_is_stale_on_source_change(tmp_path: Path) -> None:
    """Editing a manifest, deleting it, or adding an unlisted one makes the index stale."""
    # FILL IN


def test_read_index_rejects_other_versions(tmp_path: Path) -> None:
    """A missing, unparsable or wrong-version file reads as None."""
    # FILL IN


def test_index_contract(tmp_path: Path) -> None:
    """The stdlib hook reader accepts exactly what publish_index writes."""
    assert procedure_advice.INDEX_SCHEMA_VERSION == INDEX_SCHEMA_VERSION
    assert procedure_advice.PLANE_DIR == PLANE_DIR and procedure_advice.INDEX_FILE == index_mod.INDEX_FILE
    # FILL IN: publish under tmp_path / PLANE_DIR; procedure_advice.load_index(tmp_path) == the document;
    # every guard has the keys procedure/kind/executable/argv_prefix/path_globs/scope and every
    # precondition has probe/expect/args/cost.
```

### FILL IN checklist
- [ ] `index.py::compile_index`, `publish_index`, `read_index`, `is_stale` — bounded by the Implementation Notes
- [ ] `test_index_plane.py` — two helpers and four test bodies

---

## Acceptance Criteria

- [ ] `procedures.json` is written with a temp file in the same directory and `os.replace`; no temp file remains.
- [ ] `generation` is identical for two compiles of the same specs and sources.
- [ ] `is_stale` is true for a changed, deleted or unlisted manifest and for a `None` document.
- [ ] `procedure_advice.load_index` returns the published document unchanged; both schema versions are equal.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5633 and TASK-5637 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`; never change a signature the blueprint fixes.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5639 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
