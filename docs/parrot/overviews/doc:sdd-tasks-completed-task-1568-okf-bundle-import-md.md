---
type: Wiki Overview
title: 'TASK-1568: OKF Bundle Import'
id: doc:sdd-tasks-completed-task-1568-okf-bundle-import-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Completes the OKF interchange by implementing the import path: read an OKF
  bundle'
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
- concept: mod:parrot.knowledge.pageindex.store
  rel: mentions
---

# TASK-1568: OKF Bundle Import

**Feature**: FEAT-216 — OKF Knowledge Lint & Bundle Interchange
**Spec**: `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1565, TASK-1567
**Assigned-to**: unassigned

---

## Context

Completes the OKF interchange by implementing the import path: read an OKF bundle
directory, create PageIndex nodes, map types to ConceptType enum (unknown → OTHER),
and resolve markdown links into `relates_to` edges. Combined with export (TASK-1567),
this enables round-trip fidelity: export → import preserves concept_id, type,
relates_to, and body content.

Implements: Spec §3 Module 4.

---

## Scope

- Extend `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` with:
  - `ImportReport` Pydantic model (tree_name, input_dir, nodes_created, edges_created, types_mapped, unknown_types)
  - `import_okf_bundle(input_dir, tree_name, store, content_store) -> ImportReport`
- Import logic:
  - Walk `input_dir` recursively for `.md` files
  - Parse YAML frontmatter using `parse_frontmatter()` with fallback for non-ConceptFrontmatter formats
  - Map `type` field to `ConceptType` enum; unknown values → `ConceptType.OTHER`
  - Generate `concept_id` from frontmatter `id` field (or derive from title)
  - Create PageIndex tree nodes from parsed content
  - Parse markdown links from body text using `parse_markdown_links()` → build `relates_to` edges
  - Save tree via `JSONTreeStore` and bodies via `NodeContentStore`
- Add round-trip fidelity test: export → import preserves key fields
- Export new symbols from `okf/__init__.py`

**NOT in scope**: OKFToolkit integration (TASK-1569), lint operations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` | MODIFY | Add import_okf_bundle() + ImportReport |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Export import symbols |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py` | MODIFY | Add import + round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.okf.ontology import ConceptType, RelationType, RelatesTo  # ontology.py
from parrot.knowledge.pageindex.okf.frontmatter import parse_frontmatter  # line 149 of frontmatter.py
from parrot.knowledge.pageindex.okf.graph import parse_markdown_links  # line 36 of graph.py
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id  # concept_id.py
from parrot.knowledge.pageindex.store import JSONTreeStore  # store.py
from parrot.knowledge.pageindex.content_store import NodeContentStore  # content_store.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py
def parse_frontmatter(text: str) -> ConceptFrontmatter:  # line 149
    # Parses YAML frontmatter from text, returns ConceptFrontmatter
    # Raises ValueError if frontmatter is invalid

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py
def parse_markdown_links(body: str) -> list[str]:  # line 36
    # Extracts markdown hyperlink targets, skipping code fences
    # Returns deduplicated list of relative path targets

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/concept_id.py
def derive_concept_id(source_uri: str, suffix: str = "") -> str:
    # Returns 16-char hex prefix of SHA-1(source_uri + suffix)

# packages/ai-parrot/src/parrot/knowledge/pageindex/store.py
class JSONTreeStore:
    def save(self, name: str, tree: dict) -> None:  # atomic write via tempfile
    def load(self, name: str) -> dict:
    def exists(self, name: str) -> bool:
```

### Does NOT Exist
- ~~`import_okf_bundle()`~~ — does not exist yet; this task creates it
- ~~`ImportReport`~~ — does not exist yet
- ~~`parse_frontmatter_loose()`~~ — no such function; use `parse_frontmatter()` with try/except for unknown types
- ~~`ConceptType.from_string()`~~ — no such classmethod; use `ConceptType(value)` with ValueError catch → `ConceptType.OTHER`

---

## Implementation Notes

### Pattern to Follow
```python
def import_okf_bundle(
    input_dir: Path,
    tree_name: str,
    store: JSONTreeStore,
    content_store: NodeContentStore,
) -> ImportReport:
    report = ImportReport(tree_name=tree_name, input_dir=str(input_dir))
    structure = []
    # Walk directory for .md files
    for md_file in sorted(input_dir.rglob("*.md")):
        if md_file.name == "index.md":
            continue  # skip index files
        text = md_file.read_text(encoding="utf-8")
        # Parse frontmatter (handle unknown types gracefully)
        try:
            fm = parse_frontmatter(text)
            concept_type = fm.type
        except (ValueError, ValidationError):
            # Unknown type → parse manually, map to OTHER
            ...
        # Build node dict, save body
        ...
    # Save tree
    tree = {"structure": structure, "doc_name": tree_name}
    store.save(tree_name, tree)
    return report
```

### Key Constraints
- Type mapping: `ConceptType(type_value)` → catch `ValueError` → `ConceptType.OTHER`. Record mapping in `types_mapped`.
- `parse_frontmatter()` expects `ConceptFrontmatter` format. For OKF bundles with simpler frontmatter (just `type`, `title`, `id`, `tags`, `timestamp`), parse the YAML manually first, then construct the node dict.
- Markdown link resolution: `parse_markdown_links(body)` returns relative paths like `../controls/audit-logging.md`. Strip path components to extract concept_id (filename minus `.md`).
- `concept_id`: prefer frontmatter `id` field if present; otherwise derive from title.
- `node_id`: auto-assign sequential IDs (`"0001"`, `"0002"`, ...).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` — add import to this file (created by TASK-1567)
- `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py` — `build_page_index()` pattern for tree construction
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py:149` — `parse_frontmatter()`

---

## Acceptance Criteria

- [ ] `import_okf_bundle()` reads OKF bundle directory and creates PageIndex tree
- [ ] Known ConceptType values mapped correctly
- [ ] Unknown type values → `ConceptType.OTHER` with entry in `unknown_types` list
- [ ] Markdown links in body text resolved into `relates_to` edges
- [ ] `concept_id` preserved from frontmatter `id` field
- [ ] Tree saved via `JSONTreeStore`, bodies saved via `NodeContentStore`
- [ ] `index.md` files in bundle skipped during import
- [ ] Round-trip test passes: export → import preserves concept_id, type, relates_to, body
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py (extend)

def test_import_reads_frontmatter(sample_okf_bundle, mock_store, mock_content_store):
    report = import_okf_bundle(sample_okf_bundle, "test", mock_store, mock_content_store)
    assert report.nodes_created >= 2


def test_import_maps_known_types(sample_okf_bundle, mock_store, mock_content_store):
    report = import_okf_bundle(sample_okf_bundle, "test", mock_store, mock_content_store)
    assert "Policy" in report.types_mapped.values() or report.types_mapped.get("Policy") == "Policy"


def test_import_maps_unknown_types_to_other(tmp_path, mock_store, mock_content_store):
    (tmp_path / "custom.md").write_text(
        "---\ntype: CustomThing\ntitle: Test\nid: test-id\n---\nBody.\n"
    )
    report = import_okf_bundle(tmp_path, "test", mock_store, mock_content_store)
    assert "CustomThing" in report.unknown_types


def test_import_resolves_markdown_links(sample_okf_bundle, mock_store, mock_content_store):
    report = import_okf_bundle(sample_okf_bundle, "test", mock_store, mock_content_store)
    assert report.edges_created >= 1


def test_round_trip_fidelity(sample_tree, mock_content_store, mock_store, tmp_path):
    """Export → Import preserves concept_id, type, relates_to, body."""
    export_okf_bundle(sample_tree, "test", mock_content_store, tmp_path)
    report = import_okf_bundle(tmp_path, "reimported", mock_store, mock_content_store)
    assert report.nodes_created >= 2
    # Verify concept_ids match
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
2. **Check dependencies** — TASK-1565 and TASK-1567 must be completed
3. **Read the export function** in `bundle.py` (from TASK-1567) to understand the export format
4. **Read `parse_frontmatter()`** and `parse_markdown_links()` for parsing behavior
5. **Implement** `import_okf_bundle()` and `ImportReport` in `bundle.py`
6. **Run tests**: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py -v`

---

## Completion Note

*(Agent fills this in when done)*
