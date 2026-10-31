# TASK-5000: Subsystem taxonomy loader (M3a)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4997
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (taxonomy half) and design-research S7: the `about` axis of a decision must come from a
curated vocabulary (`sdd/taxonomy/subsystems.yaml`), not the free-form SDD `tags` (`DocTaxonomy` accepts any
tag and only warns on unknown projects, sdd_meta.py:201/220). The taxonomy validates `about` ids, maps a spec's
frontmatter `projects`/`tags` to subsystem ids, offers suggestions (never auto-corrects), projects
`concept:<id>` pages for ABOUT edges, and contributes a digest to the snapshot manifest.

The actual `subsystems.yaml` content is TASK-5012; this task ships only the loader.

---

## Scope

- Create `taxonomy.py` with `Subsystem` and `Taxonomy` (`load`, `ids`, `closest`, `map_projects`,
  `project_pages`, `digest`).
- `Taxonomy.load` raises `DecisionError(TAXONOMY_INVALID)` on unknown parent, project not in
  `KNOWN_PROJECTS`, duplicate id, parent cycle, malformed YAML/fields.
- Tests `test_taxonomy.py`.

**NOT in scope**: the YAML file itself (TASK-5012); validating spec `about` lists (TASK-5005 calls `ids()`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/taxonomy.py` | CREATE | loader + mapping |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_taxonomy.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import difflib, hashlib, json
from pathlib import Path
import yaml                                                          # usage verified: okf/frontmatter.py:25
from pydantic import Field, ValidationError
from parrot.knowledge.wiki.decisions.models import _Strict, DecisionError, TAXONOMY_INVALID  # models.py:47,57 (+TASK-4997)
from parrot.knowledge.wiki.ledger.sdd_meta import KNOWN_PROJECTS     # verified: ledger/sdd_meta.py:45
from parrot.knowledge.wiki.store import WikiPageRecord               # verified: store.py (fields lines 471-483)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
KNOWN_PROJECTS: frozenset[str]   # line 45 — every packages/<dist> name plus areas (sdd-tooling, dev-loop, admin-ui, docs, ci)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py — class WikiPageRecord(BaseModel)
    concept_id: str = Field(..., min_length=1)   # line 471
    node_id: Optional[str] = None; title: str = ""; category: str = "concept"; summary: str = ""; body: str = ""
    source_id: Optional[str] = None; token_count: int = 0; origin: str = "ingest"; asserted_by: Optional[str] = None
    content_hash: Optional[str] = None           # line 482
    attrs: dict[str, str] = {}                   # line 483
```

### Does NOT Exist
- ~~`parrot.knowledge.ontology.concept_catalog` as the taxonomy~~ — FEAT-159 per-tenant Postgres ontology; not reused.
- ~~`DocTaxonomy.subsystems`~~ — `DocTaxonomy` has no subsystem axis; do not extend it.
- ~~`sdd/taxonomy/subsystems.yaml`~~ — created by TASK-5012; tests write their own temp file.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/taxonomy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_taxonomy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#KNOWN_PROJECTS",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord"
  ]
}
```

---

## Implementation Notes

- File format (decided here, consumed by TASK-5012):
  ```yaml
  schema_version: 1
  subsystems:
    - id: memory
      title: Conversation memory
      description: ...
      parent: null
      projects: [ai-parrot]
  mapping:            # optional: frontmatter tag -> subsystem id (versioned with the file)
    memory: memory
  ```
  `map_projects(projects, tags)`: subsystems whose `projects` intersect the spec's `projects`, plus
  `mapping[tag]` for each known tag; returns a sorted, de-duplicated list. Unknown tags are reported via
  `unmapped_tags()` / a second return path the caller (TASK-5005) records in `CoverageSummary.unmapped_tags`.
  Because the spec fixes `map_projects(...) -> list[str]`, expose unmapped tags as a separate method
  `unmapped(tags) -> list[str]`.
- `digest()`: sha256 of canonical JSON of the validated content (sorted keys) — deterministic for TASK-5003's manifest.
- `project_pages()`: `WikiPageRecord(concept_id=f"concept:{id}", node_id=same, title, category="concept",
  summary=description, body=description, origin="authored", content_hash=sha1(body))`.

---

## Implementation Blueprint

### Steps (in order)
1. Define `Subsystem` and the private file model — *why*: strict validation of the curated file.
2. Implement `Taxonomy.load` with all integrity checks — *why*: a broken taxonomy must refuse, not degrade (spec §3 M3).
3. Implement query methods and `digest` — *why*: TASK-5003/P09 consume them.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/taxonomy.py` (CREATE)
```python
"""Curated subsystem taxonomy for the decision ``about`` axis (FEAT-784 Module 3)."""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from parrot.knowledge.wiki.decisions.models import TAXONOMY_INVALID, DecisionError, _Strict
from parrot.knowledge.wiki.ledger.sdd_meta import KNOWN_PROJECTS
from parrot.knowledge.wiki.store import WikiPageRecord

logger = logging.getLogger(__name__)


class Subsystem(_Strict):
    """One curated subsystem id."""

    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(..., min_length=1)
    description: str = ""
    parent: str | None = None
    projects: list[str]


class _TaxonomyFile(_Strict):
    schema_version: Literal[1]
    subsystems: list[Subsystem]
    mapping: dict[str, str] = Field(default_factory=dict)


class Taxonomy:
    """Validated, immutable subsystem vocabulary."""

    def __init__(self, data: _TaxonomyFile) -> None:
        self._data = data
        self._by_id = {s.id: s for s in data.subsystems}

    @classmethod
    def load(cls, path: Path) -> "Taxonomy":
        """Raise DecisionError(TAXONOMY_INVALID) on unknown parent/project or duplicate id."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            data = _TaxonomyFile.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise DecisionError(TAXONOMY_INVALID, f"{path}: {exc}") from exc
        # FILL IN: duplicate ids; parent not in ids; parent cycle; project not in KNOWN_PROJECTS;
        #          mapping value not in ids — each raises DecisionError(TAXONOMY_INVALID, <specific message>)
        #          — bounded by spec §3 M3 ("unknown parent/project or duplicate id")
        return cls(data)

    def ids(self) -> frozenset[str]:
        """Every subsystem id."""
        return frozenset(self._by_id)

    def closest(self, raw: str, limit: int = 3) -> list[str]:
        """Suggestions only; never auto-corrects."""
        return difflib.get_close_matches(raw, sorted(self._by_id), n=limit, cutoff=0.5)

    def map_projects(self, projects: list[str], tags: list[str]) -> list[str]:
        """Versioned mapping projects/tags → subsystem ids; unknown tags are reported, not mapped."""
        # FILL IN: union of subsystems whose projects ∩ projects, and mapping[tag] for known tags; sorted unique
        return []

    def unmapped(self, tags: list[str]) -> list[str]:
        """Tags with no mapping entry (reported in CoverageSummary.unmapped_tags), sorted."""
        return sorted({t for t in tags if t not in self._data.mapping})

    def project_pages(self) -> list[WikiPageRecord]:
        """``concept:<id>`` pages for ABOUT edges."""
        # FILL IN: one WikiPageRecord per subsystem (see Implementation Notes for field values), sorted by id
        return []

    def digest(self) -> str:
        """sha256 over the canonical JSON of the validated file."""
        canonical = json.dumps(self._data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```
**Why this shape**: method names and the `load` classmethod are fixed by the spec §3 M3 skeleton; `unmapped`
is additive (the fixed `map_projects` return type cannot carry unmapped tags). Suggestions never mutate input
(spec "Suggestions only; never auto-corrects").

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_taxonomy.py` (CREATE)
```python
"""FEAT-784 M3 — subsystem taxonomy."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionError
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy

VALID = """schema_version: 1
subsystems:
  - {id: memory, title: Memory, projects: [ai-parrot]}
  - {id: clients, title: Clients, projects: [ai-parrot]}
  - {id: server, title: Server, projects: [ai-parrot-server]}
  - {id: memory-compaction, title: Compaction, parent: memory, projects: [ai-parrot]}
mapping: {memory: memory, mcp: server}
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "subsystems.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_taxonomy_load_and_ids(tmp_path):
    assert Taxonomy.load(_write(tmp_path, VALID)).ids() >= {"memory", "clients"}


@pytest.mark.parametrize("bad", [
    # FILL IN: unknown parent; unknown project "no-such-pkg"; duplicate id; parent cycle; mapping to unknown id;
    #          malformed yaml; extra field
])
def test_taxonomy_rejects(tmp_path, bad):
    with pytest.raises(DecisionError) as exc:
        Taxonomy.load(_write(tmp_path, bad))
    assert exc.value.code == "TAXONOMY_INVALID"


def test_closest_suggests_without_correcting(tmp_path):
    # FILL IN: closest("memroy") == ["memory", ...]; ids() unchanged


def test_map_projects_and_unmapped(tmp_path):
    # FILL IN: map_projects(["ai-parrot-server"], ["mcp", "weird"]) == ["server"]; unmapped(["mcp","weird"]) == ["weird"]


def test_digest_stable_and_sensitive(tmp_path):
    # FILL IN: same content → same digest; changed title → different digest


def test_project_pages(tmp_path):
    # FILL IN: concept ids "concept:<id>", category "concept"
```

### FILL IN checklist
- [ ] `Taxonomy.load` integrity checks — spec §3 M3
- [ ] `map_projects`, `project_pages`
- [ ] test bodies / bad cases

---

## Acceptance Criteria

- [ ] Unknown parent / unknown project / duplicate id / cycle ⇒ `TAXONOMY_INVALID`.
- [ ] `closest()` only suggests; `map_projects` is deterministic; `digest()` changes with content.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_taxonomy.py -q`

---

## Test Specification

See the blueprint test block (spec §4 `test_taxonomy_load_and_suggest`).

---

## Agent Instructions

1. Worktree `feat-FEAT-784-sdd-decision-audit`; TASK-4997 `done`.
2. Implement; complete FILL INs; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the two files; `scripts/sdd/close_task.sh TASK-5000 sdd-decision-audit verified`.

---

## Completion Note

*(filled in by the implementing agent)*
