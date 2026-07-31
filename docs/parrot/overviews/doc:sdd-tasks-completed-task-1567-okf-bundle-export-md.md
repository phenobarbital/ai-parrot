---
type: Wiki Overview
title: 'TASK-1567: OKF Bundle Export'
id: doc:sdd-tasks-completed-task-1567-okf-bundle-export-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: PageIndex's OKF layer (FEAT-238) projects sidecars with `pageindex://` URIs
  and
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.bundle
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.frontmatter
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1567: OKF Bundle Export

**Feature**: FEAT-216 — OKF Knowledge Lint & Bundle Interchange
**Spec**: `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1565
**Assigned-to**: unassigned

---

## Context

PageIndex's OKF layer (FEAT-238) projects sidecars with `pageindex://` URIs and
AI-Parrot-specific fields. Google OKF v0.1 requires standard relative markdown
paths in a directory hierarchy. This task creates the export half of `bundle.py`,
producing an OKF-compliant directory bundle from a PageIndex tree.

Implements: Spec §3 Module 3.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` with:
  - `ExportReport` Pydantic model (tree_name, output_dir, files_written, index_generated, uris_rewritten)
  - `export_okf_bundle(tree, tree_name, content_store, output_dir) -> ExportReport`
- Export logic:
  - Create directory hierarchy grouped by ConceptType (e.g. `policies/`, `controls/`, `sections/`)
  - For each node: project frontmatter **without** `node_id` and `resource` fields
  - Rewrite `pageindex://` URIs in body text to relative markdown paths within the bundle
  - Leave external URLs, anchor-only links, and absolute URLs unchanged
  - Generate `index.md` at bundle root using `generate_index_md()`
  - Use `flatten_concept_id_for_filename()` for filenames
- Export new symbols from `okf/__init__.py`
- Create unit tests in `test_okf_bundle.py`

**NOT in scope**: import logic (TASK-1568), OKFToolkit integration (TASK-1569).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` | CREATE | Export function + ExportReport model |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Export bundle symbols |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py` | CREATE | Unit tests for export |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.okf.ontology import ConceptType  # verified: ontology.py:21
from parrot.knowledge.pageindex.okf.frontmatter import (
    ConceptFrontmatter,    # line 30 of frontmatter.py
    project_frontmatter,   # line 96 of frontmatter.py
)
from parrot.knowledge.pageindex.okf.projection import (
    flatten_concept_id_for_filename,  # projection.py
    generate_index_md,                # line 192 of projection.py
    ProjectionReport,                 # line 39 of projection.py (pattern reference)
)
from parrot.knowledge.pageindex.content_store import NodeContentStore  # content_store.py
from parrot.knowledge.pageindex.utils import structure_to_list  # utils.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py
class ConceptFrontmatter(BaseModel):
    type: ConceptType       # line 49
    title: str              # line 50
    id: str                 # line 51 — concept_id
    node_id: str            # line 52 — STRIP on export
    resource: str           # line 53 — STRIP on export (pageindex:// URI)
    tags: list[str]         # line 54
    timestamp: str          # line 55
    summary: str            # line 56
    relates_to: list[RelatesTo]  # line 57
    source: Optional[SourceProvenance] = None  # line 58

def project_frontmatter(node: dict, tree_name: str) -> str:  # line 96
    # Returns YAML frontmatter string (including --- delimiters)

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py
def flatten_concept_id_for_filename(concept_id: str) -> str:
    # Returns filename-safe version of concept_id

def generate_index_md(tree: dict, tree_name: str) -> str:  # line 192
    # Returns index.md content as string
```

### Does NOT Exist
- ~~`okf.bundle`~~ — does not exist yet; this task creates it
- ~~`export_okf_bundle()`~~ — does not exist yet
- ~~`ConceptFrontmatter.to_okf_dict()`~~ — no such method; manually strip fields
- ~~`project_frontmatter_okf()`~~ — no OKF-specific variant; use `project_frontmatter()` and post-process

---

## Implementation Notes

### Pattern to Follow
```python
# Follow project_sidecars() pattern from projection.py:131
def export_okf_bundle(
    tree: dict,
    tree_name: str,
    content_store: NodeContentStore,
    output_dir: Path,
) -> ExportReport:
    report = ExportReport(tree_name=tree_name, output_dir=str(output_dir))
    nodes = structure_to_list(tree.get("structure", []))
    for node in nodes:
        cid = node.get("concept_id")
        if not cid:
            continue
        # 1. Determine subdirectory from type
        concept_type = node.get("type", "Section").lower() + "s"  # "Policy" → "policys" → handle pluralization
        type_dir = output_dir / concept_type
        type_dir.mkdir(parents=True, exist_ok=True)
        # 2. Write frontmatter (stripped) + body
        ...
    return report
```

### Key Constraints
- URI rewriting: regex replace `pageindex://<tree>/<concept_id>` → relative path `../<type>/<filename>.md`
- Pluralization of directory names: `Policy` → `policies`, `Control` → `controls`, etc. Use a simple mapping dict.
- OKF v0.1 frontmatter fields: `type`, `title`, `id` (concept_id), `description` (from summary), `tags`, `timestamp`. Omit: `node_id`, `resource`, `source`, `relates_to` (convert to markdown links in body instead).
- Nested directory for types with more than one concept; flat for single-concept types.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py:131` — `project_sidecars()` iteration pattern
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py:96` — frontmatter projection

---

## Acceptance Criteria

- [ ] `export_okf_bundle()` produces directory hierarchy grouped by concept type
- [ ] Exported frontmatter contains only OKF fields: type, title, id, description, tags, timestamp
- [ ] No `node_id`, `resource`, or `pageindex://` URIs in exported files
- [ ] Markdown links in bodies rewritten from `pageindex://` to relative paths
- [ ] External URLs, anchor-only links left unchanged
- [ ] `index.md` generated at bundle root
- [ ] `ExportReport` returned with accurate counts
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py -v -k export`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py
import pytest
from pathlib import Path
from parrot.knowledge.pageindex.okf.bundle import export_okf_bundle, ExportReport


def test_export_creates_directory_hierarchy(sample_tree, mock_content_store, tmp_path):
    report = export_okf_bundle(sample_tree, "test", mock_content_store, tmp_path)
    assert (tmp_path / "policies").is_dir()
    assert (tmp_path / "controls").is_dir()
    assert report.files_written >= 2


def test_export_rewrites_uris(sample_tree, mock_content_store, tmp_path):
    export_okf_bundle(sample_tree, "test", mock_content_store, tmp_path)
    content = (tmp_path / "policies" / "access-control-policy.md").read_text()
    assert "pageindex://" not in content


def test_export_strips_internal_fields(sample_tree, mock_content_store, tmp_path):
    export_okf_bundle(sample_tree, "test", mock_content_store, tmp_path)
    content = (tmp_path / "policies" / "access-control-policy.md").read_text()
    assert "node_id:" not in content
    assert "resource:" not in content


def test_export_generates_index(sample_tree, mock_content_store, tmp_path):
    report = export_okf_bundle(sample_tree, "test", mock_content_store, tmp_path)
    assert (tmp_path / "index.md").is_file()
    assert report.index_generated is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
2. **Check dependencies** — TASK-1565 must be completed
3. **Read `projection.py`** for the `project_sidecars()` iteration pattern
4. **Read `frontmatter.py`** for `project_frontmatter()` output format
5. **Implement** `bundle.py` with `export_okf_bundle()` and `ExportReport`
6. **Run tests**: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py -v -k export`

---

## Completion Note

*(Agent fills this in when done)*
