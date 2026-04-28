# TASK-855: AbstractLoader contract changes — language, title, validate_metadata

**Feature**: FEAT-125 — AI-Parrot Loaders Metadata Standardization
**Spec**: `sdd/specs/ai-parrot-loaders-metadata-standarization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-125. It extends `AbstractLoader` with the
new `language` attribute, enriches `create_metadata` to build a canonical
closed-shape `document_meta`, adds `_derive_title` and `_validate_metadata`
helpers, and wires the validator into `create_document` and `_load_tasks`.

Every other task in this feature depends on these contract changes.
Implements **Module 1** of the spec.

---

## Scope

- Add `language: str = "en"` keyword argument to `AbstractLoader.__init__`; store as `self.language`.
- Extend `create_metadata` signature with `language: Optional[str] = None` and `title: Optional[str] = None`.
- Inside `create_metadata`, build `document_meta` as a **closed-shape** dict with exactly `{source_type, category, type, language, title}`:
  - `language` defaults to `self.language` when the kwarg is `None`.
  - `title` defaults to `self._derive_title(path)` when `None`.
  - If caller passes legacy `doc_metadata` dict, fold canonical keys into `document_meta` and hoist non-canonical keys to top-level `**kwargs`.
- Implement `_derive_title(self, path) -> str`:
  - `Path` → `path.stem` (normalized: replace underscores/hyphens with spaces, title-case).
  - `http(s)://...` URL → last non-empty path segment, decoded.
  - Fallback → `str(path)`.
- Implement `_validate_metadata(self, metadata: dict) -> dict`:
  - Check for all canonical top-level keys (`url`, `source`, `filename`, `type`, `source_type`, `created_at`, `category`, `document_meta`).
  - Check `document_meta` has exactly the 5 canonical keys.
  - On any miss: `self.logger.warning(...)` + auto-fill defaults.
  - **Never raise.**
  - Return the (possibly patched) metadata dict.
- Wire `_validate_metadata` into `create_document` (after building/receiving metadata, before constructing `Document`).
- Wire `_validate_metadata` into `_load_tasks` (once per returned `Document`, after the gather loop). Do NOT place it in `chunk_documents`.

**NOT in scope**: Refactoring any concrete loader. Changing `Document` model. Adding Pydantic schema for `document_meta`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/loaders/abstract.py` | MODIFY | All changes: `__init__`, `create_metadata`, `_derive_title`, `_validate_metadata`, `create_document`, `_load_tasks` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader  # abstract.py:36
from parrot.stores.models import Document            # stores/models.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/loaders/abstract.py

class AbstractLoader(ABC):                                          # line 36
    extensions: List[str] = ['.*']                                  # line 41
    skip_directories: List[str] = []                                # line 42

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        **kwargs
    ):                                                              # line 44
        # Sets (among others):
        self._source_type = source_type                             # line 74
        self.category: str = kwargs.get('category', 'document')     # line 76
        self.doctype: str = kwargs.get('doctype', 'text')           # line 77

    def create_metadata(
        self,
        path: Union[str, PurePath],
        doctype: str = 'document',
        source_type: str = 'source',
        doc_metadata: Optional[dict] = None,
        **kwargs
    ):                                                              # line 717
        # Current body builds:
        # {url, source, filename, type, source_type, created_at,
        #  category, document_meta: {**doc_metadata}, **kwargs}

    def create_document(
        self,
        content: Any,
        path: Union[str, PurePath],
        metadata: Optional[dict] = None,
        **kwargs
    ) -> Document:                                                  # line 750
        # If metadata is None, calls create_metadata with path/doctype/source_type
        # Then wraps in Document(page_content=content, metadata=_meta)

    async def _load_tasks(self, tasks: list) -> list:               # line 567
        # Gathers results; for each res:
        #   if list → results.extend(res)
        #   else → results.append(res)
        # Returns results (list of Document)
```

```python
# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):                                          # line 21
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### Does NOT Exist
- ~~`AbstractLoader.language`~~ — does **not** exist today; this task adds it.
- ~~`AbstractLoader._derive_title`~~ — does not exist; new in this task.
- ~~`AbstractLoader._validate_metadata`~~ — does not exist; new in this task.
- ~~`AbstractLoader.set_language()` / global `LOADER_DEFAULT_LANGUAGE`~~ — not real.
- ~~`Document.document_meta` accessor~~ — `Document` has no typed accessor for `document_meta`.
- ~~`AbstractLoader.title`~~ — no instance attribute for title exists.

---

## Implementation Notes

### Pattern to Follow
```python
# Extend __init__ signature — add language before **kwargs:
def __init__(
    self,
    source=None,
    *,
    tokenizer=None,
    text_splitter=None,
    source_type: str = 'file',
    language: str = 'en',       # NEW
    **kwargs
):
    ...
    self.language: str = language  # NEW — after existing attribute assignments

# Extend create_metadata — add language/title after doc_metadata:
def create_metadata(
    self,
    path,
    doctype='document',
    source_type='source',
    doc_metadata=None,
    *,
    language=None,   # NEW
    title=None,      # NEW
    **kwargs
):
    ...
```

### Key Constraints
- `_derive_title` is sync (no I/O). For URL parsing use `urllib.parse.urlparse`.
- `_validate_metadata` is sync. Uses `self.logger.warning(...)`, never `print`.
- The `document_meta` sub-dict must contain **exactly** 5 keys: `source_type`, `category`, `type`, `language`, `title`. No extras.
- Legacy `doc_metadata` dict: any key matching the 5 canonical names is folded in; all other keys are hoisted to top-level metadata.
- `create_document` signature must NOT change (additive only).
- `_load_tasks` validator call: iterate over `results` after gather, call `_validate_metadata` on each `Document.metadata`.

### References in Codebase
- `packages/ai-parrot/src/parrot/loaders/abstract.py` — sole file to modify

---

## Acceptance Criteria

- [ ] `AbstractLoader.__init__` accepts `language: str = "en"` and stores on `self.language`
- [ ] `create_metadata` accepts `language` and `title` kwargs
- [ ] `document_meta` keys are exactly `{source_type, category, type, language, title}`
- [ ] `_derive_title` returns `path.stem` (normalized) for Path, trailing segment for URL, fallback for others
- [ ] `_validate_metadata` logs warning on missing canonical fields, auto-fills defaults, never raises
- [ ] `_validate_metadata` wired into `create_document`
- [ ] `_validate_metadata` wired into `_load_tasks` (once per Document, not in chunk_documents)
- [ ] Legacy `doc_metadata` callers still produce valid canonical `document_meta`
- [ ] Existing tests still pass: `pytest packages/ai-parrot/tests/ -v -k loader`
- [ ] No breaking changes to `create_metadata` or `create_document` public signatures

---

## Test Specification

```python
# packages/ai-parrot/tests/test_abstractloader_metadata.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from parrot.loaders.abstract import AbstractLoader


CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}
CANONICAL_TOP_LEVEL_KEYS = {
    "url", "source", "filename", "type",
    "source_type", "created_at", "category", "document_meta",
}


class ConcreteLoader(AbstractLoader):
    """Minimal concrete subclass for testing."""
    async def _load(self, source, **kwargs):
        return []


class TestCreateMetadataCanonicalShape:
    def test_returns_canonical_top_level_keys(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(Path("/tmp/test.pdf"), doctype="pdf", source_type="file")
        assert CANONICAL_TOP_LEVEL_KEYS.issubset(set(meta.keys()))

    def test_document_meta_closed_shape(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(Path("/tmp/test.pdf"))
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_language_defaults_from_self(self):
        loader = ConcreteLoader(language="fr")
        meta = loader.create_metadata(Path("/tmp/test.pdf"))
        assert meta["document_meta"]["language"] == "fr"

    def test_language_kwarg_overrides_self(self):
        loader = ConcreteLoader(language="fr")
        meta = loader.create_metadata(Path("/tmp/test.pdf"), language="es")
        assert meta["document_meta"]["language"] == "es"

    def test_title_auto_derived_from_path(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(Path("/tmp/my_report.pdf"))
        assert meta["document_meta"]["title"] != ""

    def test_extras_become_top_level(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(Path("/tmp/t.pdf"), origin="test", vtt_path="/tmp/x.vtt")
        assert "origin" in meta
        assert "vtt_path" in meta
        assert "origin" not in meta["document_meta"]

    def test_legacy_doc_metadata_canonical_fields_folded(self):
        loader = ConcreteLoader()
        meta = loader.create_metadata(
            Path("/tmp/t.pdf"),
            doc_metadata={"language": "de", "table": "plans"}
        )
        assert meta["document_meta"]["language"] == "de"
        assert "table" in meta  # hoisted to top level
        assert "table" not in meta["document_meta"]


class TestValidateMetadata:
    def test_warns_on_missing_field(self, caplog):
        loader = ConcreteLoader()
        incomplete = {"url": "x", "source": "x"}
        result = loader._validate_metadata(incomplete)
        assert "document_meta" in result
        assert any("warning" in r.levelname.lower() or "missing" in r.message.lower()
                    for r in caplog.records)

    def test_does_not_raise_on_empty(self):
        loader = ConcreteLoader()
        result = loader._validate_metadata({})
        assert isinstance(result, dict)


class TestDeriveTitle:
    def test_path_stem(self):
        loader = ConcreteLoader()
        assert loader._derive_title(Path("/tmp/my_report.pdf")) != ""

    def test_url_segment(self):
        loader = ConcreteLoader()
        title = loader._derive_title("https://example.com/docs/guide")
        assert title != ""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-855-abstractloader-contract-changes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker-feat-125
**Date**: 2026-04-27
**Notes**: Implemented all changes to `abstract.py`:
- Added `language: str = "en"` kwarg to `__init__` → `self.language`
- Extended `create_metadata` with `language` / `title` kwargs; builds closed-shape `document_meta` with exactly 5 canonical keys
- Added `_derive_title`: handles `Path` (→ `path.stem` title-cased), HTTP URLs (→ last segment), string file paths (→ stem), fallback string
- Added `_validate_metadata`: warns + auto-fills all missing canonical fields, never raises; also hoists non-canonical keys from `document_meta` to top level
- Wired `_validate_metadata` into `create_document` and `_load_tasks`
- Created 25-test suite in `packages/ai-parrot/tests/test_abstractloader_metadata.py` — all pass
- Added navigator/parrot stubs to conftest.py to fix pre-existing FEAT-124 import breakage

**Deviations from spec**: conftest.py modified (not in task file list) to fix pre-existing test infrastructure breakage from FEAT-124 that prevented any tests from collecting.
