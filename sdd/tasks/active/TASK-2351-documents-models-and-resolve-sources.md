# TASK-2351: `wiki/documents.py` foundations — models + `resolve_sources()`

**Feature**: FEAT-451 — `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter
**Spec**: `sdd/specs/wikitoolkit-ingest-documents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec (§3). This is the foundation every other
task in FEAT-451 imports: the Pydantic models that describe a source document
and its metadata, plus `resolve_sources()` — the function that widens
`wikitoolkit ingest` from "a directory" to "a directory, a file, or a URL".

Nothing in this task changes existing behavior. It creates a new, standalone
module. `cli.py` is not touched here (that is TASK-2357).

---

## Scope

- CREATE `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` with:
  - `DocumentRef` — `uri: str`, `is_url: bool = False`, `suffix: str = ""`.
  - `DocumentMetadata` — all fields optional (see spec §2 Data Models):
    `title`, `author`, `created_at`, `modified_at`, `page_count`,
    `word_count`, `language`, `content_type`, `source_url`, `loader`,
    `extra: dict[str, Any]`.
  - `AcquiredDocument` — `ref`, `text`, `metadata`. Docstring MUST state that
    `text` has any leading YAML frontmatter already stripped.
  - `TriageProvenance` — `composite_score`, `decision`, `decision_source`,
    `charter_version`, all optional.
  - `DocumentAcquisitionError(Exception)` — raised when a document cannot be
    decoded or fetched; callers SKIP the document rather than triage garbage.
  - `resolve_sources(source: str, *, recursive: bool = True) -> list[DocumentRef]`.
- `resolve_sources` behavior:
  - `http://` or `https://` prefix → one `DocumentRef(is_url=True)`, `suffix`
    derived from the URL path (lowercased, may be `""`).
  - existing directory → recursive walk, **preserving the exact semantics of
    the current `_discover_documents`** (cli.py:2093-2114): `sorted()`,
    `p.is_file()`, and skip any path with a dot-prefixed part. When
    `recursive=False`, use `glob("*")` instead of `rglob("*")`.
  - existing file → exactly one ref, `is_url=False`.
  - anything else → `click.ClickException` with a message naming the bad path.
- Write unit tests in `tests/knowledge/wiki/test_documents.py`.

**NOT in scope**: `DocumentAcquirer` (TASK-2353), URL fetching (TASK-2354),
`render_frontmatter` / `split_frontmatter` (TASK-2352), any edit to `cli.py`,
`ingest.py`, `models.py`, or `sources.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` | CREATE | Models + `resolve_sources()` |
| `tests/knowledge/wiki/test_documents.py` | CREATE | Unit tests for this task |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `2026-08-23`. Re-verify before editing.

### Verified Imports

```python
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click                       # >=8.1.7, core dep
from pydantic import BaseModel, Field
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2093-2114
# THE EXACT WALK SEMANTICS resolve_sources() MUST PRESERVE for a directory:
def _discover_documents(folder: Path) -> list[Path]:
    return sorted(
        p
        for p in folder.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.parts)
    )
# Note the dot-part filter covers .git/, .parrot/, and dotfiles alike.
```

```python
# Sibling modules in this package use this logger convention:
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py — self.logger on classes
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py — module-level _cli_logger
logger = logging.getLogger("parrot.knowledge.wiki.documents")
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.documents`~~ — **you are creating it**. Verified
  absent from the `wiki/` package: arango_store, bookkeeper, charter,
  claude_code, cli, coding_agents, context, execution, export, file_store,
  ingest, languages, mcp_server, models, project, repo_scan, review, search,
  sources, store, toolkit, tools, triage, vault_scan.
- ~~`parrot.knowledge.wiki.models.DocumentRef` / `.DocumentMetadata`~~ —
  `models.py` holds `WikiPageCategory` (line 25), `WikiConfig` (52),
  `SourceManifestEntry` (159), `WikiSearchResult` (227), `WikiLintReport`
  (274) and nothing else. Put the new models in `documents.py`, not `models.py`.
- ~~a `parrot/` package at the repo root~~ — this is a uv workspace; core is at
  `packages/ai-parrot/src/parrot/`.
- ~~`requests` / `httpx`~~ — banned by CLAUDE.md. Not needed in this task at all.

---

## Implementation Notes

### Pattern to Follow

```python
class DocumentRef(BaseModel):
    """One resolved ingestion source: a local file or a remote URL.

    Attributes:
        uri: Absolute filesystem path, or an http(s) URL.
        is_url: True when ``uri`` is a remote URL.
        suffix: Lowercased extension including the dot, or "" when unknown.
    """

    uri: str
    is_url: bool = False
    suffix: str = ""
```

### Key Constraints

- Pydantic v2 models; Google-style docstrings; strict type hints throughout.
- `resolve_sources` is **synchronous** — it only touches the filesystem
  metadata layer (`is_dir`/`is_file`/`rglob`), never reads file contents.
- Raise `click.ClickException` (not bare `FileNotFoundError`) for a missing
  path, so the CLI keeps the clean error message Click gave before the
  argument type was widened.
- Normalize local paths with `Path(...).resolve()` so `uri` is absolute — the
  rest of the pipeline (and `SourceManifestEntry.source_uri`) assumes absolute.
- Lowercase every `suffix`; `get_loader_class` in a later task keys off it.
- Do NOT import `parrot_loaders` in this task. It is an optional satellite and
  is only reached (lazily) in TASK-2353.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2093-2114` — the walk to preserve.
- `packages/ai-parrot/src/parrot/knowledge/wiki/models.py:159` — Pydantic style in this package.
- `packages/ai-parrot/src/parrot/knowledge/wiki/review.py:135` — model-with-docstring-Attributes convention.

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.documents import DocumentRef, DocumentMetadata, AcquiredDocument, TriageProvenance, DocumentAcquisitionError, resolve_sources` works.
- [ ] `resolve_sources(<dir>)` returns refs equal (same order, same paths) to
      `_discover_documents(<dir>)` on the same tree.
- [ ] `resolve_sources(<file>)` returns exactly one ref with `is_url=False`.
- [ ] `resolve_sources("https://host/a.pdf")` returns one ref with
      `is_url=True` and `suffix == ".pdf"`.
- [ ] `resolve_sources("/no/such/path")` raises `click.ClickException`.
- [ ] `resolve_sources(<dir>, recursive=False)` does not descend.
- [ ] All fields of `DocumentMetadata` default to `None` (or `{}` for `extra`),
      so an empty instance is constructible: `DocumentMetadata()`.
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_documents.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/documents.py` clean.
- [ ] `mypy` clean on the new file.

---

## Test Specification

```python
# tests/knowledge/wiki/test_documents.py
import pytest
import click

from parrot.knowledge.wiki.documents import (
    AcquiredDocument,
    DocumentAcquisitionError,
    DocumentMetadata,
    DocumentRef,
    TriageProvenance,
    resolve_sources,
)


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / ".hidden.md").write_text("x")
    return tmp_path


class TestResolveSources:
    def test_directory_matches_legacy_walk(self, corpus):
        """Directory walk: sorted, files only, dot-parts skipped."""
        refs = resolve_sources(str(corpus))
        names = [r.uri for r in refs]
        assert all(".git" not in n and ".hidden" not in n for n in names)
        assert len(refs) == 2
        assert names == sorted(names)

    def test_directory_non_recursive(self, corpus):
        refs = resolve_sources(str(corpus), recursive=False)
        assert len(refs) == 1

    def test_single_file(self, corpus):
        refs = resolve_sources(str(corpus / "a.md"))
        assert len(refs) == 1 and refs[0].is_url is False
        assert refs[0].suffix == ".md"

    def test_url(self):
        refs = resolve_sources("https://example.test/doc.PDF")
        assert len(refs) == 1
        assert refs[0].is_url is True
        assert refs[0].suffix == ".pdf"

    def test_missing_path_raises_click_exception(self):
        with pytest.raises(click.ClickException):
            resolve_sources("/no/such/path/at/all")


class TestModels:
    def test_empty_metadata_constructible(self):
        md = DocumentMetadata()
        assert md.title is None and md.extra == {}

    def test_acquired_document_roundtrip(self):
        ref = DocumentRef(uri="/tmp/a.md", suffix=".md")
        doc = AcquiredDocument(ref=ref, text="body", metadata=DocumentMetadata())
        assert doc.text == "body"

    def test_triage_provenance_optional(self):
        assert TriageProvenance().composite_score is None

    def test_acquisition_error_is_exception(self):
        assert issubclass(DocumentAcquisitionError, Exception)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 Module 1).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-read `cli.py:2093-2114` and confirm
   the walk semantics before copying them. If they changed, update this
   contract first, then implement.
4. **Update status** in `sdd/tasks/index/wikitoolkit-ingest-documents.json` → `"in-progress"`.
5. **Implement** following the scope and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2351-documents-models-and-resolve-sources.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
