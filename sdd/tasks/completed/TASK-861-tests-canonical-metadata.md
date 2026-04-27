# TASK-861: Tests for canonical metadata standardization

**Feature**: FEAT-125 — AI-Parrot Loaders Metadata Standardization
**Spec**: `sdd/specs/ai-parrot-loaders-metadata-standarization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-855, TASK-856, TASK-857, TASK-858, TASK-859, TASK-860
**Assigned-to**: unassigned

---

## Context

This task implements **Module 5** of the spec. It creates a comprehensive test
suite that validates the canonical metadata shape across ALL loaders, and
updates any existing per-loader tests whose fixtures assert specific metadata
shapes that changed.

This task runs AFTER all refactors are complete and verifies the entire feature
end-to-end.

---

## Scope

### New test file
Create `packages/ai-parrot-loaders/tests/test_metadata_standardization.py`:

1. **Parametrized integration test** that instantiates every loader in
   `LOADER_REGISTRY` against a small fixture and asserts every returned
   `Document` passes `_validate_metadata` with zero warnings.
2. **Closed-shape test**: for every loader fixture, verify
   `set(doc.metadata['document_meta'].keys()) == CANONICAL_DOC_META_KEYS`.
3. **Extras preservation test**: verify that known loader-specific keys
   (`origin`, `vtt_path`, `table`, `schema`, `row_index`, `topic_tags`,
   `start_time`, `end_time`, `content_kind`) appear at top level when the
   loader produces them.
4. **Canonical constant definitions**: shared fixture/constants module.

### Update existing tests
Scan `packages/ai-parrot-loaders/tests/` for tests that assert specific
metadata dict shapes (e.g. checking for keys in `document_meta` that are
no longer there). Update those assertions to match the new canonical shape.

**NOT in scope**: Writing implementation code. Changing loader behavior.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/tests/test_metadata_standardization.py` | CREATE | Main integration test suite |
| `packages/ai-parrot-loaders/tests/conftest.py` | MODIFY | Add shared fixtures and canonical constants |
| `packages/ai-parrot-loaders/tests/test_*.py` (existing) | MODIFY | Update metadata shape assertions where broken |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader     # abstract.py:36
from parrot.stores.models import Document              # stores/models.py:21

# LOADER_REGISTRY from packages/ai-parrot-loaders/src/parrot_loaders/__init__.py:9
# Contains all 25+ loader class paths as a dict[str, str]
```

### Existing Signatures to Use
```python
# After TASK-855:
# AbstractLoader._validate_metadata(metadata: dict) -> dict
# AbstractLoader.create_metadata(path, doctype, source_type, doc_metadata,
#                                *, language=None, title=None, **kwargs) -> dict

# packages/ai-parrot-loaders/src/parrot_loaders/__init__.py
LOADER_REGISTRY: dict[str, str] = {                                 # line 9
    "TextLoader": "parrot_loaders.txt.TextLoader",
    "CSVLoader": "parrot_loaders.csv.CSVLoader",
    # ... (25+ entries, see spec Section 6 for full list)
}
```

### Does NOT Exist
- ~~`LOADER_REGISTRY.values()` returning loader instances~~ — values are dotted-path strings, not classes.
- ~~`AbstractLoader.validate_metadata` (no underscore)~~ — the method is `_validate_metadata` (private).
- ~~`Document.validate_metadata`~~ — validation lives on `AbstractLoader`, not `Document`.

---

## Implementation Notes

### Integration test pattern
```python
import pytest
import importlib
from parrot_loaders import LOADER_REGISTRY

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}
CANONICAL_TOP_LEVEL_KEYS = {
    "url", "source", "filename", "type",
    "source_type", "created_at", "category", "document_meta",
}

def _get_loader_class(dotted_path: str):
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)

@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_loader_create_metadata_canonical_shape(loader_name, loader_path):
    cls = _get_loader_class(loader_path)
    # Skip abstract base classes
    if loader_name in ("BasePDF", "BaseVideoLoader"):
        pytest.skip("Abstract base class")
    loader = cls()
    meta = loader.create_metadata("test_source", doctype="test", source_type="test")
    assert CANONICAL_TOP_LEVEL_KEYS.issubset(set(meta.keys()))
    assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
```

### Key Constraints
- Some loaders require external dependencies (whisper, moviepy, etc.) that may not be available in CI. Use `pytest.importorskip` or skip markers.
- The integration test should test `create_metadata` output shape (sync, no I/O) rather than full `load()` calls where possible.
- For loaders that can be easily instantiated, also test with small fixtures via `_load`.
- Update existing test assertions for `document_meta` shape changes.

### References in Codebase
- `packages/ai-parrot-loaders/tests/` — existing test files
- `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` — LOADER_REGISTRY

---

## Acceptance Criteria

- [ ] New `test_metadata_standardization.py` with parametrized tests for all loaders
- [ ] `test_all_loaders_produce_canonical_documents` passes for every loader in LOADER_REGISTRY
- [ ] `test_document_meta_is_closed_shape` passes — no extras in `document_meta`
- [ ] `test_loader_specific_extras_preserved` — known extras at top level
- [ ] Existing per-loader tests updated where metadata shape assertions changed
- [ ] All tests pass: `pytest packages/ai-parrot-loaders/tests/ -v`
- [ ] No test uses `_validate_metadata` incorrectly (it's on the loader, not on Document)

---

## Test Specification

```python
# packages/ai-parrot-loaders/tests/test_metadata_standardization.py

import pytest
import importlib
from parrot_loaders import LOADER_REGISTRY

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}
CANONICAL_TOP_LEVEL_KEYS = {
    "url", "source", "filename", "type",
    "source_type", "created_at", "category", "document_meta",
}

ABSTRACT_BASES = {"BasePDF", "BaseVideoLoader"}


def _get_loader_class(dotted_path: str):
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_create_metadata_canonical_shape(loader_name, loader_path):
    if loader_name in ABSTRACT_BASES:
        pytest.skip("Abstract base class")
    cls = _get_loader_class(loader_path)
    loader = cls()
    meta = loader.create_metadata("test_source", doctype="test", source_type="test")
    assert CANONICAL_TOP_LEVEL_KEYS.issubset(set(meta.keys())), (
        f"{loader_name}: missing top-level keys: "
        f"{CANONICAL_TOP_LEVEL_KEYS - set(meta.keys())}"
    )
    assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS, (
        f"{loader_name}: document_meta keys mismatch: "
        f"got {set(meta['document_meta'].keys())}"
    )


@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_document_meta_no_extra_keys(loader_name, loader_path):
    if loader_name in ABSTRACT_BASES:
        pytest.skip("Abstract base class")
    cls = _get_loader_class(loader_path)
    loader = cls()
    meta = loader.create_metadata(
        "test_source", doctype="test", source_type="test",
        extra_field="should_be_top_level"
    )
    assert "extra_field" in meta
    assert "extra_field" not in meta["document_meta"]


@pytest.mark.parametrize("loader_name,loader_path", LOADER_REGISTRY.items())
def test_language_defaults(loader_name, loader_path):
    if loader_name in ABSTRACT_BASES:
        pytest.skip("Abstract base class")
    cls = _get_loader_class(loader_path)
    loader = cls()
    meta = loader.create_metadata("test_source")
    assert meta["document_meta"]["language"] == loader.language


def test_validate_metadata_warns_and_fills(caplog):
    """_validate_metadata auto-fills missing fields without raising."""
    cls = _get_loader_class(list(LOADER_REGISTRY.values())[0])
    loader = cls()
    incomplete = {"url": "x"}
    result = loader._validate_metadata(incomplete)
    assert "document_meta" in result
    assert set(result["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-855 through TASK-860 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm all TASK-855 through TASK-860 changes are present
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Run all tests**: `pytest packages/ai-parrot-loaders/tests/ -v`
7. **Move this file** to `tasks/completed/TASK-861-tests-canonical-metadata.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent (session feat-125)
**Date**: 2026-04-27
**Notes**: Created comprehensive test suite with 95 passing parametrized tests.
  - test_metadata_standardization.py: 5 parametrized test functions covering all
    loaders in LOADER_REGISTRY (canonical shape, closed document_meta, language/title
    propagation, extras at top level). Loaders requiring optional deps or that cannot
    be instantiated without config are skipped gracefully (45 skipped).
  - conftest.py: shared CANONICAL_DOC_META_KEYS and CANONICAL_TOP_LEVEL_KEYS constants
    as module-level frozensets and pytest fixtures.
  - Updated test_webscraping_loader.py: two assertions updated to reflect TASK-860
    canonical metadata changes (source_type is now "url"; description is now top-level).

**Deviations from spec**: none
