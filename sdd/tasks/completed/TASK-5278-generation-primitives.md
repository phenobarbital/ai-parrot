# TASK-5278: Generation models, body references and identity helpers

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the data half of spec §3 **Module 2** (`knowledge/pageindex/generation.py`):
`GenerationInfo`, `BodyRef`, `PublishReport`, `StaleGenerationError` and the helpers that give
every node a stable identity (`concept_id`) and every body a content address. TASK-5282 adds
`WriteTransaction` to the same module.

---

## Scope

- Create `generation.py` with the three Pydantic models, `StaleGenerationError`,
  `flatten_concept_id`, `body_sha16`, `generation_of`, `next_generation` and `ensure_concept_ids`.
- `flatten_concept_id` delegates to the existing `flatten_concept_id_for_filename` — *because* OKF
  sidecars already use that flattening and blob keys must agree with it.
- `ensure_concept_ids` assigns a `concept_id` to every node that lacks one using
  `derive_concept_id(title, parent_path)`, exactly as `tree_ops._assign_okf_concept_ids` does, but
  without the silent ImportError no-op (publication cannot proceed without identities).
- Create `test_generation.py` with the model/helper tests.

**NOT in scope**: `WriteTransaction` and package exports (TASK-5282), `TreeLockTimeout`
(defined in `locks.py`, TASK-5276).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py` | CREATE | Models and helpers |
| `packages/ai-parrot/tests/knowledge/pageindex/test_generation.py` | CREATE | Unit tests for models and helpers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename      # verified: knowledge/okf/utils.py:18 (in __all__ :49)
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id     # verified: knowledge/pageindex/okf/concept_id.py:72
from parrot.knowledge.pageindex.utils import structure_to_list              # verified: imported at knowledge/pageindex/okf/projection.py:30
```

### Existing Signatures to Use
```python
# knowledge/okf/utils.py
_MAX_FLAT_ID_LENGTH = 60                                         # line 15
def flatten_concept_id_for_filename(concept_id: str) -> str      # line 18: "/" → "--"; >60 chars → truncated + "-<sha1[:8]>"

# knowledge/pageindex/okf/concept_id.py
def derive_concept_id(title: str, parent_path: str = "") -> str  # line 72 (deterministic slug, scoped by parent path)

# knowledge/pageindex/tree_ops.py — the walk to mirror (do not import the private helper)
def _assign_okf_concept_ids(target) -> None                      # lines 56-86: depth-first; parent_path is the parent's concept_id
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.generation`~~ — created by this task
- ~~`GenerationInfo`, `BodyRef`, `PublishReport`, `StaleGenerationError`, `body_ref`~~ — introduced here
- ~~a uuid-based concept_id~~ — concept ids are deterministic slugs; two same-titled siblings may share one (harmless for blobs: the content hash differs or the blob is identical)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_generation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Blob key format is fixed by the spec: `"<flat_concept_id>.<sha16>"`, flat id matching
  `^[A-Za-z0-9_-]{1,64}$`, sha16 = first 16 hex chars of SHA-256 over the UTF-8 markdown.
  TASK-5279 validates the same format independently in the content store; a test there asserts both agree.
- `published_at` is ISO-8601 UTC with a trailing `Z` (`datetime.now(timezone.utc)`).
- Pydantic v2 (`BaseModel`, `model_validate`, `model_dump`).

---

## Implementation Blueprint

### Steps (in order)
1. Create the module from the block — *why*: TASK-5279/5282 import these exact names.
2. Fill `BodyRef.parse`, `next_generation`, `ensure_concept_ids`.
3. Write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py` (CREATE)
```python
"""Generation publication primitives for PageIndex trees (FEAT-831)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

from parrot.knowledge.okf.utils import flatten_concept_id_for_filename  # verified: okf/utils.py:18
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id  # verified: pageindex/okf/concept_id.py:72

_FLAT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA16_RE = re.compile(r"^[0-9a-f]{16}$")


class GenerationInfo(BaseModel):
    """Stored under ``tree["generation"]``; absent on a tree never written by FEAT-831 code."""

    id: int
    published_at: str
    parent: Optional[int] = None


class BodyRef(BaseModel):
    """Address of an immutable body blob: ``<flat_concept_id>.<sha16>``."""

    flat_concept_id: str
    sha16: str

    @property
    def key(self) -> str:
        return f"{self.flat_concept_id}.{self.sha16}"

    @classmethod
    def parse(cls, value: str) -> "BodyRef":
        """Parse ``value``; raises ``ValueError`` when either part has the wrong shape."""
        # FILL IN: rpartition on "." and validate both parts with _FLAT_RE/_SHA16_RE — bounded by AC-1
        raise NotImplementedError


class PublishReport(BaseModel):
    """Returned by ``WriteTransaction.publish()`` and by ``rename_tree``."""

    tree_name: str
    generation: int
    bodies_written: int = 0
    bodies_swept: int = 0
    okf_projected: bool = False


class StaleGenerationError(RuntimeError):
    """The base generation of a candidate is no longer the live one; nothing was written."""


def flatten_concept_id(concept_id: str) -> str:
    """Flatten ``concept_id`` exactly like OKF sidecar filenames."""
    return flatten_concept_id_for_filename(concept_id)


def body_sha16(markdown: str) -> str:
    """First 16 hex chars of SHA-256 over the UTF-8 ``markdown``."""
    return hashlib.sha256((markdown or "").encode("utf-8")).hexdigest()[:16]


def generation_of(tree: dict[str, Any]) -> Optional[GenerationInfo]:
    """Return the tree's ``GenerationInfo`` or ``None`` for a legacy tree."""
    raw = tree.get("generation")
    return GenerationInfo.model_validate(raw) if isinstance(raw, dict) else None


def next_generation(base: Optional[GenerationInfo]) -> GenerationInfo:
    """``id = base.id + 1`` (1 for a legacy or new tree), ``parent = base.id``, ``published_at`` = now (UTC)."""
    # FILL IN — bounded by AC-2
    raise NotImplementedError


def ensure_concept_ids(tree: dict[str, Any]) -> int:
    """Assign ``concept_id`` to every node lacking one (depth-first, parent path = parent's concept_id).

    Returns the number of ids assigned. Existing ids are never changed.
    """
    # FILL IN: mirror tree_ops._assign_okf_concept_ids (:56-86) without the ImportError guard — bounded by AC-3
    raise NotImplementedError
```
**Why this shape**: spec §2 Data Models fixes the three models and the key format; helpers
are the only place that knows the format, so the content store, the transaction and rename
all share one definition.

### FILL IN checklist
- [ ] `BodyRef.parse`; bounded by AC-1
- [ ] `next_generation`; bounded by AC-2
- [ ] `ensure_concept_ids`; bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: `BodyRef.parse(ref.key) == ref`; `parse("bad")`, `parse("a.XYZ")` and a flat id with `/` raise `ValueError`.
- [ ] AC-2: `next_generation(None)` → id 1, parent `None`; `next_generation(GenerationInfo(id=4, ...))` → id 5, parent 4; `published_at` parses as UTC.
- [ ] AC-3: `ensure_concept_ids` fills missing ids in a nested tree, keeps existing ones, and returns the count.
- [ ] AC-4: `flatten_concept_id("a/b") == "a--b"`; `body_sha16` is deterministic and 16 hex chars.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_generation.py
import pytest

from parrot.knowledge.pageindex.generation import (
    BodyRef, GenerationInfo, body_sha16, ensure_concept_ids, flatten_concept_id, next_generation,
)


def test_body_ref_roundtrip():
    ref = BodyRef(flat_concept_id="intro", sha16=body_sha16("hello"))
    assert BodyRef.parse(ref.key) == ref


@pytest.mark.parametrize("value", ["bad", "a.XYZ", "a/b.0123456789abcdef"])
def test_body_ref_rejects(value):
    with pytest.raises(ValueError):
        BodyRef.parse(value)


def test_next_generation():
    assert next_generation(None).id == 1
    nxt = next_generation(GenerationInfo(id=4, published_at="2026-01-01T00:00:00Z"))
    assert (nxt.id, nxt.parent) == (5, 4)


def test_ensure_concept_ids_preserves_existing():
    tree = {"structure": [{"title": "A", "concept_id": "keep", "nodes": [{"title": "B"}]}]}
    assert ensure_concept_ids(tree) == 1
    assert tree["structure"][0]["concept_id"] == "keep"
    assert tree["structure"][0]["nodes"][0]["concept_id"]


def test_flatten_matches_okf():
    assert flatten_concept_id("a/b") == "a--b"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-generation-publication --feature-id FEAT-831`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-generation-publication.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
7. **Verify** — run the Validation Commands and `ruff check` on the files you touched.
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `parrot sdd task close TASK-5278 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
