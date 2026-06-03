# TASK-1424: Dataset loaders (`parrot/eval/datasets.py`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 8 (brainstorm §10)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1415
**Assigned-to**: unassigned

---

## Context

Loads benchmark files into `EvalDataset`. Implements spec §3 Module 8. A distinct `DatasetLoader` —
**NOT** `AbstractLoader` (which produces `List[Document]` and does not fit eval tasks, spec §1
Non-Goals).

---

## Scope

- Create `parrot/eval/datasets.py` with:
  - `DatasetLoader(ABC)` — `async load(source: str) -> EvalDataset`.
  - `JSONLDatasetLoader` — one JSON object per line → `EvalTask`; dataset `name` from filename or a
    header line.
  - `YAMLDatasetLoader` — a YAML doc with `name` + `tasks: [...]`.
- `HFDatasetLoader` is OPTIONAL/reserved — add a stub that raises `NotImplementedError` with a clear
  message (full HF ingest is out of scope, spec §7 deps table).
- Export from `parrot/eval/__init__.py`.

**NOT in scope**: SWE-bench/τ-bench HF ingestion, the actual benchmark files (TASK-1428).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/datasets.py` | CREATE | Loaders |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export loaders |
| `packages/ai-parrot/tests/eval/test_datasets.py` | CREATE | Unit tests + tmp fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import json
from abc import ABC, abstractmethod
import yaml                                  # PyYAML — already a repo dependency
from parrot.eval.models import EvalDataset, EvalTask   # TASK-1415
```

### Does NOT Exist
- ~~Reuse of `parrot.loaders.AbstractLoader`~~ — wrong contract (`List[Document]`); build `DatasetLoader`.
- ~~`BaseLoader`~~ — the real loader base is `AbstractLoader` (and it is not used here anyway).

---

## Implementation Notes

### Key Constraints
- Async `load`; read files with `asyncio.to_thread` (or aiofiles if already a dep) — no blocking I/O
  on the event loop.
- Validate each record into `EvalTask` (Pydantic) so malformed rows fail loudly.

---

## Acceptance Criteria

- [ ] `from parrot.eval import JSONLDatasetLoader, YAMLDatasetLoader` resolves.
- [ ] JSONL and YAML round-trip into an `EvalDataset` with the expected task count.
- [ ] Malformed records raise a validation error (not a silent skip).
- [ ] `HFDatasetLoader().load(...)` raises `NotImplementedError`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_datasets.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/datasets.py`

---

## Test Specification

```python
import pytest
from parrot.eval import JSONLDatasetLoader

async def test_jsonl_roundtrip(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('{"task_id": "t1", "inputs": {"q": "hi"}}\n')
    ds = await JSONLDatasetLoader().load(str(p))
    assert len(ds.tasks) == 1 and ds.tasks[0].task_id == "t1"
```

---

## Agent Instructions

Standard SDD flow: verify the contract, set index `in-progress`, implement, run tests + ruff, move to
`completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
