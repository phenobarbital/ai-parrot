# TASK-5262: Snapshot file format, `build_snapshot` and `pg_trgm`-compatible similarity

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5258
**Assigned-to**: unassigned

---

## Context

Spec Module 8 (part 1) and spec §2 "Snapshot". A local, read-only SQLite file per
`(ontology_id, version)` holds only the rows visible at that version, that version's closure,
embeddings as float32 BLOBs and an FTS5 trigram index over labels. This task defines the file
format, writes it atomically from a `VersionContent`, and provides `trigram_similarity` matching
PostgreSQL `pg_trgm` so the snapshot ranks like the server. The read-side store is TASK-5263
(same file, later).

---

## Scope

- `vocabulary/snapshot.py` (new) with `SNAPSHOT_FORMAT_VERSION = 1`, `snapshot_path`,
  `build_snapshot`, `trigram_similarity` (spec lines 872–877) and the private `_SNAPSHOT_DDL`.
- SQLite schema (no version columns — a snapshot is one version):
  `meta(key PRIMARY KEY, value)` with `format_version`, `ontology_id`, `version`, `checksum`,
  `base_iri`, `built_at`; `concept(iri PK, kind, pref_label, definition, deprecated INT, replaced_by, extra JSON, embedding BLOB)`;
  `label(iri, lang, kind, text)`; `relation(subject_iri, predicate, object_iri, inferred INT)`;
  `statement(subject_iri, predicate, object JSON, object_hash)`;
  `closure(family, ancestor_iri, descendant_iri, depth)`; indexes mirroring spec §2;
  `CREATE VIRTUAL TABLE label_fts USING fts5(text, iri UNINDEXED, lang UNINDEXED, kind UNINDEXED, tokenize='trigram')`.
- `build_snapshot(content, dest_root)` writes to `<path>.tmp` then `os.replace` → final path; refuses
  to overwrite a final file whose `meta.checksum` differs (raise `ValueError`), returns early if equal.
  Uses `aiosqlite`; NumPy converts embeddings to float32 bytes.
- `trigram_similarity(a, b)` — pg_trgm semantics: lower-case; split into words on non-alphanumerics;
  each word padded as `"  " + w + " "`; trigrams = all 3-char windows; set similarity
  `|A∩B| / |A∪B|`; `0.0` when either set is empty.
- `test_snapshot_build.py`.

**NOT in scope**: `SnapshotOntologyStore`, `SnapshotSource`, `HttpSnapshotSource`, `_create_snapshot` (TASK-5263).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/snapshot.py` | CREATE | format + build + similarity |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_build.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiosqlite                          # core dependency (installed 0.22.1): packages/ai-parrot/pyproject.toml:205
import numpy as np                        # installed 2.5.4; declared by TASK-5252's extra — import inside functions
from parrot.knowledge.ontology.vocabulary.contracts import VersionContent        # TASK-5253
# tests:
from parrot.knowledge.ontology.vocabulary.turtle import parse_turtle, content_checksum   # TASK-5258
from parrot.knowledge.ontology.vocabulary.closure import build_closure, materialise_inverses  # TASK-5257
```

### Existing Signatures to Use
```python
# TASK-5253
class VersionContent(BaseModel): ontology_id; version; checksum; content: OntologyContent;
                                 closure: list[ClosureRow]; embeddings: dict[str, list[float]] = {}
```

### Does NOT Exist
- ~~`sqlite-vec`~~ — explicitly not introduced (draft §4.3); vectors are NumPy brute force.
- ~~a Python `pg_trgm` package~~ — implement the algorithm; do not add a dependency.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/snapshot.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_build.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `_SNAPSHOT_DDL` and `snapshot_path` — *why*: fixed layout `{root}/{ontology_id}/v{version}.sqlite`.
2. `build_snapshot` with the atomic temp-then-rename write — *why*: a reader must never see a half file.
3. `trigram_similarity`; record reference values (see FILL IN) — *why*: spec §7 "Trigram parity".
4. Tests.

### `.../vocabulary/snapshot.py` (CREATE)
```python
"""Read-only SQLite snapshots of one ontology version (FEAT-824)."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from parrot.knowledge.ontology.vocabulary.contracts import VersionContent

logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.snapshot")

SNAPSHOT_FORMAT_VERSION = 1
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_SNAPSHOT_DDL = """
-- FILL IN: tables, indexes and the label_fts FTS5 trigram table per TASK-5262 Scope.
"""


def snapshot_path(root: Path, ontology_id: str, version: int) -> Path:
    """{root}/{ontology_id}/v{version}.sqlite"""
    return Path(root).expanduser() / ontology_id / f"v{version}.sqlite"


async def build_snapshot(content: VersionContent, dest_root: Path) -> Path:
    """Write the snapshot atomically (temporary file, then rename) and return its path."""
    import aiosqlite
    import numpy as np

    final = snapshot_path(dest_root, content.ontology_id, content.version)
    # FILL IN: existing-file checksum check; mkdir; write <final>.tmp with executescript(_SNAPSHOT_DDL),
    #          executemany inserts (embeddings as np.asarray(v, dtype=np.float32).tobytes()), label_fts rows,
    #          meta rows; commit; close; os.replace(tmp, final); logger.info.
    raise NotImplementedError


def trigram_similarity(a: str, b: str) -> float:
    """pg_trgm-compatible similarity: lower-cased, word-padded trigram sets, |A∩B| / |A∪B|."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _trigrams(text: str) -> set[str]:
    """Trigrams of every word padded as '  word ' (pg_trgm convention)."""
    out: set[str] = set()
    for word in _WORD.findall(text.lower()):
        padded = f"  {word} "
        out.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return out
```

### `.../vocabulary/test_snapshot_build.py` (CREATE) — required cases
```python
def test_snapshot_path_layout(tmp_path): ...
async def test_build_snapshot_contents(tmp_path, golden_v1, golden_base_iri): ...
    # VersionContent from parse_turtle + build_closure(+inverses); built file has meta.version/checksum,
    # one concept row per concept, closure rows, label_fts searchable with MATCH
async def test_build_is_atomic_and_idempotent(tmp_path, ...): ...   # no *.tmp left; second build returns same path
async def test_build_refuses_conflicting_checksum(tmp_path, ...): ...
REFERENCE = [  # FILL IN: ≥ 6 (a, b, value) triples recorded from `SELECT similarity(a, b)` on a live
               #          PostgreSQL with pg_trgm (include accents and multi-word strings); paste the values.
]
def test_trigram_similarity_reference_values(): ...   # abs(trigram_similarity(a,b) - v) <= 0.02 for each
```

### FILL IN checklist
- [ ] `_SNAPSHOT_DDL`, `build_snapshot` body.
- [ ] `REFERENCE` values recorded from a live `pg_trgm` (state the PostgreSQL version in the note).
- [ ] test bodies.

---

## Acceptance Criteria

- [ ] A snapshot holds only the given version's rows and closure, with its version and checksum in `meta`.
- [ ] Writes are atomic; a conflicting existing snapshot is never overwritten.
- [ ] `trigram_similarity` matches recorded `pg_trgm` values within 0.02.
- [ ] `ruff check` passes; no `sqlite-vec`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_build.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5258 is `done` (and rdflib is installed for the tests).
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the listed files; close with `parrot sdd task close TASK-5262 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
