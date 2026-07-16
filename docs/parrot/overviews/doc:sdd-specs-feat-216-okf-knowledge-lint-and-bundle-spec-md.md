---
type: Wiki Overview
title: 'Feature Specification: OKF Knowledge Lint & Bundle Interchange'
id: doc:sdd-specs-feat-216-okf-knowledge-lint-and-bundle-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The OKF Knowledge Layer (FEAT-238) provides concept_id, typed relations,
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.concept_id
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.frontmatter
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.tools
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.store
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: OKF Knowledge Lint & Bundle Interchange

**Feature ID**: FEAT-216
**Date**: 2026-06-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next
**Related**: FEAT-238 (okf-knowledge-layer)

---

## 1. Motivation & Business Requirements

### Problem Statement

The OKF Knowledge Layer (FEAT-238) provides concept_id, typed relations,
frontmatter projection, and an in-memory KnowledgeGraph. Two gaps remain:

1. **Lint Operations (G3)** — KnowledgeGraph collects broken links in `_broken`
   (graph.py:99) but doesn't surface them as a structured report. There's no
   orphan detection (zero inbound edges), no missing concept page detection
   (referenced but non-existent concepts), and no stale-claims check.

2. **OKF Bundle Import/Export (G4)** — Sidecar projection generates internal
   `pageindex://` URIs. Google OKF v0.1 requires standard relative markdown
   paths in a directory hierarchy. There's no way to export an OKF-compliant
   bundle or import one from an external source.

### Goals

- Add `lint_knowledge_base()` returning a structured `LintReport` with orphans,
  broken links, missing concepts, stale claims
- Add `export_okf_bundle(tree_name, output_dir)` producing an OKF v0.1 compliant
  directory
- Add `import_okf_bundle(input_dir, tree_name)` consuming an OKF bundle into
  PageIndex
- Extend `OKFToolkit` with lint and bundle tools
- Map unknown OKF `type` values to a generic `OTHER` ConceptType on import
  (resolved design decision Q1)

### Non-Goals (explicitly out of scope)

- Not modifying the authoritative JSON model (frontmatter stays a projection)
- Not persisting the knowledge graph to ArangoDB (that's a future phase)
- Not implementing the LLM maintenance loop (ingest → query → lint write-back)
- Not building contradiction detection between concepts (stretch goal for future)

---

## 2. Architectural Design

### Overview

Two new modules in `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`:

**`lint.py`** — Knowledge base lint operations:
- `lint_knowledge_base(graph: KnowledgeGraph, tree: dict, content_store: NodeContentStore, stale_days: int = 90) -> LintReport`
- Checks: orphan concepts (zero inbound edges), broken links (from
  KnowledgeGraph._broken), missing concept pages (referenced in relates_to but
  no concept node), stale claims (timestamp older than threshold)

**`bundle.py`** — OKF v0.1 bundle import/export:
- `export_okf_bundle(tree: dict, tree_name: str, content_store: NodeContentStore, output_dir: Path) -> ExportReport`
  - Creates OKF directory hierarchy grouped by `type` (e.g. `concepts/`,
    `policies/`, `controls/`)
  - Rewrites `pageindex://` URIs to relative markdown paths
  - Strips AI-Parrot-specific fields (`node_id`, `resource`) from frontmatter
  - Generates `index.md` at root
- `import_okf_bundle(input_dir: Path, tree_name: str, store: JSONTreeStore, content_store: NodeContentStore) -> ImportReport`
  - Reads markdown files with YAML frontmatter
  - Maps `type` to `ConceptType` enum; unknown types → `ConceptType.OTHER`
    (new enum value)
  - Creates PageIndex nodes from content
  - Resolves markdown links into `relates_to` edges
  - Round-trip: export → import preserves concept_id, type, relates_to, body
    content

### Component Diagram

```
                   ┌───────────────────────────┐
                   │  OKFToolkit (existing)     │
                   │  + lint_knowledge_base()   │
                   │  + export_okf_bundle()     │
                   │  + import_okf_bundle()     │
                   └───────┬───────────────────-┘
           ┌───────────────┼───────────────────┐
           ▼               ▼                   ▼
     lint.py          bundle.py           graph.py (existing)
     ┌──────────┐     ┌──────────────┐    ┌──────────────────┐
     │LintReport│     │ExportReport  │    │KnowledgeGraph    │
     │  orphans │     │ImportReport  │    │  _broken         │
     │  broken  │     │  export()    │    │  neighbors()     │
     │  missing │     │  import()    │    │  trace()         │
     │  stale   │     └──────────────┘    └──────────────────┘
     └──────────┘
         ▲                    ▲
         │                    │
    KnowledgeGraph      frontmatter.py (existing)
    (reads _broken,     projection.py (existing)
     adjacency)         concept_id.py (existing)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `okf.graph.KnowledgeGraph` | reads | _broken, adjacency, concepts() for lint |
| `okf.frontmatter.ConceptFrontmatter` | reads/writes | Parse on import, project on export |
| `okf.frontmatter.parse_frontmatter()` | calls | Parse imported OKF files |
| `okf.frontmatter.project_frontmatter()` | calls | Re-project for export (with URI rewriting) |
| `okf.projection.project_sidecar()` | reference | Export follows same projection pattern |
| `okf.projection.generate_index_md()` | calls | Generate index.md for bundle |
| `okf.ontology.ConceptType` | extends | Add `OTHER` value for unknown import types |
| `okf.concept_id.derive_concept_id()` | calls | Generate concept_ids for imported nodes |
| `pageindex.store.JSONTreeStore` | reads/writes | Load/save trees during import |
| `pageindex.content_store.NodeContentStore` | reads/writes | Load/save sidecar bodies |
| `OKFToolkit` | extends | Add 3 new tools |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path

class LintFinding(BaseModel):
    """A single lint finding."""
    kind: str  # "orphan", "broken_link", "missing_concept", "stale"
    concept_id: str
    detail: str
    severity: str = "warning"  # "warning" | "error"

class LintReport(BaseModel):
    """Structured knowledge base lint report."""
    tree_name: str
    orphans: list[LintFinding] = Field(default_factory=list)
    broken_links: list[LintFinding] = Field(default_factory=list)
    missing_concepts: list[LintFinding] = Field(default_factory=list)
    stale_claims: list[LintFinding] = Field(default_factory=list)
    total_findings: int = 0
    total_concepts: int = 0

class ExportReport(BaseModel):
    """Result of OKF bundle export."""
    tree_name: str
    output_dir: str
    files_written: int = 0
    index_generated: bool = False
    uris_rewritten: int = 0

class ImportReport(BaseModel):
    """Result of OKF bundle import."""
    tree_name: str
    input_dir: str
    nodes_created: int = 0
    edges_created: int = 0
    types_mapped: dict[str, str] = Field(default_factory=dict)
    unknown_types: list[str] = Field(default_factory=list)
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py
def lint_knowledge_base(
    graph: KnowledgeGraph,
    tree: dict,
    content_store: NodeContentStore,
    stale_days: int = 90,
) -> LintReport:
    """Run lint checks on a knowledge base and return a structured report."""
    ...

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py
def export_okf_bundle(
    tree: dict,
    tree_name: str,
    content_store: NodeContentStore,
    output_dir: Path,
) -> ExportReport:
    """Export a PageIndex tree as an OKF v0.1 compliant directory bundle."""
    ...

def import_okf_bundle(
    input_dir: Path,
    tree_name: str,
    store: JSONTreeStore,
    content_store: NodeContentStore,
) -> ImportReport:
    """Import an OKF bundle directory into a PageIndex tree."""
    ...
```

---

## 3. Module Breakdown

### Module 1: ConceptType OTHER Extension
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py`
- **Responsibility**: Add `OTHER = "Other"` to ConceptType enum
- **Depends on**: none

### Module 2: Knowledge Lint Engine
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py` (new)
- **Responsibility**: `lint_knowledge_base()` function + LintReport/LintFinding models
- **Depends on**: Module 1, existing graph.py KnowledgeGraph

### Module 3: OKF Bundle Export
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` (new)
- **Responsibility**: `export_okf_bundle()` with URI rewriting and directory hierarchy
- **Depends on**: existing frontmatter.py, projection.py, concept_id.py

### Module 4: OKF Bundle Import
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` (extend)
- **Responsibility**: `import_okf_bundle()` with type mapping and edge resolution
- **Depends on**: Module 1 (OTHER type), Module 3 (shared bundle.py)

### Module 5: OKFToolkit Extensions
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py` (extend)
- **Responsibility**: 3 new tools: lint_knowledge_base, export_okf_bundle, import_okf_bundle
- **Depends on**: Module 2, Module 3, Module 4

### Module 6: Tests
- **Path**: `packages/ai-parrot/tests/knowledge/pageindex/test_okf_lint.py` (new) + `test_okf_bundle.py` (new)
- **Responsibility**: Unit and integration tests
- **Depends on**: Module 1-5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_lint_finds_orphans` | 2 | Concept with zero inbound edges detected |
| `test_lint_finds_broken_links` | 2 | Broken links from KnowledgeGraph._broken surfaced |
| `test_lint_finds_missing_concepts` | 2 | Concept referenced in relates_to but missing from graph |
| `test_lint_finds_stale_claims` | 2 | Concept with old timestamp flagged |
| `test_lint_empty_graph` | 2 | Empty graph returns zero findings |
| `test_export_creates_directory_hierarchy` | 3 | Export groups files by type subdirectory |
| `test_export_rewrites_uris` | 3 | `pageindex://` URIs rewritten to relative paths |
| `test_export_strips_internal_fields` | 3 | node_id, resource removed from frontmatter |
| `test_export_generates_index` | 3 | Root index.md generated |
| `test_import_reads_frontmatter` | 4 | YAML frontmatter parsed into PageIndex nodes |
| `test_import_maps_known_types` | 4 | Known ConceptType values mapped correctly |
| `test_import_maps_unknown_types_to_other` | 4 | Unknown type → ConceptType.OTHER |
| `test_import_resolves_markdown_links` | 4 | Markdown links become relates_to edges |
| `test_round_trip_fidelity` | 3+4 | Export → Import preserves concept_id, type, relates_to, body |
| `test_toolkit_lint` | 5 | Toolkit lint tool returns LintReport dict |
| `test_toolkit_export` | 5 | Toolkit export tool invokes export_okf_bundle |
| `test_toolkit_import` | 5 | Toolkit import tool invokes import_okf_bundle |

### Integration Tests

| Test | Description |
|---|---|
| `test_round_trip_fidelity` | Full export → import cycle preserves concept_id, type, relates_to, body content |
| `test_lint_after_import` | Import a bundle, run lint, verify zero findings on well-formed bundle |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_tree() -> dict:
    """A minimal PageIndex tree with OKF-enriched nodes."""
    return {
        "children": {
            "0001": {
                "node_id": "0001",
                "title": "Access Control Policy",
                "concept_id": "access-control-policy",
                "type": "Policy",
                "tags": ["access-control"],
                "timestamp": "2026-01-01T00:00:00Z",
                "relates_to": [
                    {"target": "audit-logging", "type": "references"}
                ],
            },
            "0002": {
                "node_id": "0002",
                "title": "Audit Logging",
                "concept_id": "audit-logging",
                "type": "Control",
                "tags": ["logging"],
                "timestamp": "2026-01-01T00:00:00Z",
                "relates_to": [],
            },
        }
    }

@pytest.fixture
def sample_okf_bundle(tmp_path) -> Path:
    """A minimal OKF v0.1 bundle directory on disk."""
    policies = tmp_path / "policies"
    policies.mkdir()
    (policies / "access-control-policy.md").write_text(
        "---\n"
        "type: Policy\n"
        "title: Access Control Policy\n"
        "id: access-control-policy\n"
        "tags: [access-control]\n"
        "timestamp: '2026-01-01T00:00:00Z'\n"
        "---\n\n"
        "# Access Control Policy\n\n"
        "See [Audit Logging](../controls/audit-logging.md).\n"
    )
    controls = tmp_path / "controls"
    controls.mkdir()
    (controls / "audit-logging.md").write_text(
        "---\n"
        "type: Control\n"
        "title: Audit Logging\n"
        "id: audit-logging\n"
        "tags: [logging]\n"
        "timestamp: '2026-01-01T00:00:00Z'\n"
        "---\n\n"
        "# Audit Logging\n\nAll access events are logged.\n"
    )
    return tmp_path
```

---

## 5. Acceptance Criteria

- [ ] `lint_knowledge_base()` detects: orphans (zero inbound), broken links, missing concepts, stale claims (> stale_days)
- [ ] `LintReport` is a structured Pydantic model with categorized findings
- [ ] `export_okf_bundle()` produces directory grouped by concept type
- [ ] Exported frontmatter contains only OKF v0.1 fields (type, title, description, tags, timestamp) — no node_id, no pageindex:// URIs
- [ ] Markdown links in exported bodies use relative paths within the bundle
- [ ] `import_okf_bundle()` creates valid PageIndex nodes from OKF markdown files
- [ ] Unknown `type` values mapped to `ConceptType.OTHER`
- [ ] Export → Import round-trip preserves concept_id, type, relates_to, body content
- [ ] `ConceptType.OTHER` added to enum without breaking existing code
- [ ] 3 new OKFToolkit tools auto-registered
- [ ] All existing OKF tests still pass
- [ ] All new tests pass: `pytest tests/knowledge/pageindex/test_okf_lint.py test_okf_bundle.py -v`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf.ontology import (
    ConceptType,        # line 21 of ontology.py
    RelationType,       # line 40 of ontology.py
    RelatesTo,          # line 56 of ontology.py
    SourceProvenance,   # line 71 of ontology.py
)
from parrot.knowledge.pageindex.okf.concept_id import (
    derive_concept_id,   # concept_id.py
    assign_concept_ids,  # concept_id.py
)
from parrot.knowledge.pageindex.okf.frontmatter import (
    ConceptFrontmatter,    # line 30 of frontmatter.py
    project_frontmatter,   # line 96 of frontmatter.py
    parse_frontmatter,     # line 149 of frontmatter.py
)
from parrot.knowledge.pageindex.okf.graph import (
    KnowledgeGraph,        # line 73 of graph.py
    build_graph,           # line 240 of graph.py
    parse_markdown_links,  # line 36 of graph.py
)
from parrot.knowledge.pageindex.okf.projection import (
    project_sidecar,       # line 84 of projection.py
    project_sidecars,      # line 131 of projection.py
    generate_index_md,     # line 192 of projection.py
    ProjectionReport,      # line 39 of projection.py
)
from parrot.knowledge.pageindex.okf.tools import OKFToolkit  # tools.py
from parrot.knowledge.pageindex.store import JSONTreeStore  # store.py
from parrot.knowledge.pageindex.content_store import NodeContentStore  # content_store.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py
class ConceptType(str, Enum):
    SECTION = "Section"      # line 27
    POLICY = "Policy"        # line 28
    CONTROL = "Control"      # line 29
    SAFEGUARD = "Safeguard"  # line 30
    EVIDENCE = "Evidence"    # line 31
    PLAYBOOK = "Playbook"    # line 32
    PROCEDURE = "Procedure"  # line 33
    STANDARD = "Standard"    # line 34
    FRAMEWORK = "Framework"  # line 35
    REGULATION = "Regulation"  # line 36
    GUIDELINE = "Guideline"  # line 37
    # NOTE: no OTHER value yet — Module 1 adds it

class RelationType(str, Enum):
    REFERENCES = "references"      # line 46
    MAPS_TO = "maps_to"            # line 47
    SATISFIES = "satisfies"        # line 48
    SATISFIED_BY = "satisfied_by"  # line 49
    SUPERSEDES = "supersedes"      # line 50
    SUPERSEDED_BY = "superseded_by"  # line 51
    IMPLEMENTS = "implements"      # line 52
    PART_OF = "part_of"            # line 53

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py
class KnowledgeGraph:
    def __init__(self, tree: dict[str, Any]) -> None:  # line 88
    # self._broken: list[dict] = []  # line 99
    def neighbors(self, concept_id: str, rel: Optional[str] = None) -> list[dict]:  # line 167
    def trace(self, concept_id: str, rel_chain: list[str]) -> list[list[str]]:  # line 187
    def broken_links(self) -> list[dict]:  # line 223
    def concepts(self) -> set[str]:  # line 231

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py
class ConceptFrontmatter(BaseModel):
    type: ConceptType       # line 49
    title: str              # line 50
    id: str                 # line 51
    node_id: str            # line 52
    resource: str           # line 53
    tags: list[str]         # line 54
    timestamp: str          # line 55
    summary: str            # line 56
    relates_to: list[RelatesTo]  # line 57
    source: Optional[SourceProvenance] = None  # line 58

def project_frontmatter(node: dict, tree_name: str) -> str:  # line 96
def parse_frontmatter(text: str) -> ConceptFrontmatter:  # line 149

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py
def project_sidecar(node: dict, tree_name: str, body: str) -> str:  # line 84
def project_sidecars(tree: dict, tree_name: str, content_store: NodeContentStore) -> ProjectionReport:  # line 131
def generate_index_md(tree: dict, tree_name: str) -> str:  # line 192
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `lint_knowledge_base()` | `KnowledgeGraph.broken_links()` | method call | `graph.py:223` |
| `lint_knowledge_base()` | `KnowledgeGraph.concepts()` | method call | `graph.py:231` |
| `lint_knowledge_base()` | `KnowledgeGraph.neighbors()` | method call | `graph.py:167` |
| `export_okf_bundle()` | `project_frontmatter()` | function call | `frontmatter.py:96` |
| `export_okf_bundle()` | `generate_index_md()` | function call | `projection.py:192` |
| `import_okf_bundle()` | `parse_frontmatter()` | function call | `frontmatter.py:149` |
| `import_okf_bundle()` | `derive_concept_id()` | function call | `concept_id.py` |
| `import_okf_bundle()` | `JSONTreeStore` | class instantiation | `store.py` |
| `OKFToolkit` (new tools) | `lint.lint_knowledge_base()` | function call | new `lint.py` |
| `OKFToolkit` (new tools) | `bundle.export_okf_bundle()` | function call | new `bundle.py` |
| `OKFToolkit` (new tools) | `bundle.import_okf_bundle()` | function call | new `bundle.py` |

### Does NOT Exist (Anti-Hallucination)

- ~~`okf.lint`~~ — module does not exist yet (this spec creates it)
- ~~`okf.bundle`~~ — module does not exist yet (this spec creates it)
- ~~`ConceptType.OTHER`~~ — enum value does not exist yet (Module 1 adds it)
- ~~`KnowledgeGraph.orphans()`~~ — no such method; lint.py will compute orphans by scanning adjacency
- ~~`KnowledgeGraph.missing_concepts()`~~ — no such method
- ~~`OKFToolkit.lint_knowledge_base()`~~ — does not exist yet
- ~~`OKFToolkit.export_okf_bundle()`~~ — does not exist yet
- ~~`OKFToolkit.import_okf_bundle()`~~ — does not exist yet

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- New Pydantic models for LintReport, ExportReport, ImportReport (consistent
  with ProjectionReport pattern)
- `lint.py` follows the pattern of pure functions consuming KnowledgeGraph
  (no side effects)
- `bundle.py` export follows `project_sidecars()` pattern: iterate tree nodes,
  write files
- Import follows `build_page_index()` pattern: read files → build tree dict →
  save via JSONTreeStore
- OKFToolkit tools follow existing async method pattern

### Known Risks / Gotchas

- `ConceptType.OTHER` must be additive — no existing code should break. Verify
  that no `match`/`if-elif` chains assume exhaustive enum coverage without a
  default.
- Import of large OKF bundles may be slow if many files — consider async file
  I/O
- URI rewriting on export must handle edge cases: absolute URLs (leave
  unchanged), anchor-only links (leave unchanged), external URLs (leave
  unchanged)
- Round-trip fidelity: AI-Parrot-specific fields (node_id, resource) are
  regenerated on import; they won't be identical to originals but will be
  functionally equivalent

### External Dependencies

No new external dependencies required. All functionality uses stdlib + existing
project deps (pydantic, pyyaml).

---

## 8. Open Questions

- [x] **Should OKF bundle import support arbitrary `type` values?** — *Resolved
  in proposal*: Map unknown types to `ConceptType.OTHER`.
- [x] **Should export produce a flat directory or nested by type?** —
  Recommendation: nested by type (e.g. `controls/`, `policies/`) matching OKF
  convention, with a flat fallback for bundles with only one type.: nested
- [x] **Should stale-claims detection use file mtime or frontmatter timestamp?**
  — Recommendation: frontmatter timestamp (more reliable, doesn't depend on
  filesystem): frontmatter timestamp

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks in one worktree)
- **Cross-feature dependencies**: Requires FEAT-238 (okf-knowledge-layer)
  merged (it is merged)
- Tasks are sequential: Module 1 → 2 → 3 → 4 → 5 → 6

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-16 | Jesus Lara | Initial draft from FEAT-215 proposal |
