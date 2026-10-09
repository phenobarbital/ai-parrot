# TASK-4184: Knowledge upload — Bookstore target

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4183
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. `/ingest_book` must ingest exactly like `bookstore add`
(G5, AC6): `Bookstore.add_book` on a stable staging path
`<library_dir>/.uploads/<safe_filename>` so the same file name re-uploaded maps
to the same path → status `"updated"` with the same `book_id`; identical bytes
→ `"skipped"` unless `--force` (G7).

---

## Scope

- Implement `BookstoreTarget(IngestTarget)` in `targets/bookstore.py` per the
  spec §3 M4 skeleton.
- Build the `Bookstore` once in `available()` (needs an LLM adapter from
  `resolve_adapter(config.llm)`), cache it on `self._bookstore`, reuse it in
  `ingest()`.
- Map `add_book` statuses to `UploadStatus` and user messages.
- Unit tests (mocked `Bookstore`) + one integration test with a real
  `Bookstore` on `tmp_path` ingesting `.md` without an LLM.

**NOT in scope**: changes to `bookstore/library.py` (none — spec §7 "FEAT-539"
note); PageIndex cache freshness (TASK-4181); the service (TASK-4183).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/bookstore.py` | CREATE | `BookstoreTarget` |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_bookstore_target.py` | CREATE | unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError   # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:178, :111
from parrot.knowledge.bookstore.config import LibraryLocation              # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:31
from parrot.knowledge.bookstore._llm import resolve_adapter                # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:43
# Created by TASK-4182 / TASK-4183 (dependencies):
from ..models import BookstoreTargetConfig, UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind
from .base import IngestTarget
```
Import the three `parrot.knowledge.bookstore` names **inside** methods (lazy,
spec §7).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
class BookstoreError(RuntimeError): ...                                    # :111
class Bookstore:                                                           # :178
    def __init__(self, locations: list[LibraryLocation], adapter: Optional[Any] = None,
                 lightweight_model: Optional[str] = None) -> None          # :194-199; raises BookstoreError when no locations
    @property
    def has_llm(self) -> bool                                              # :215
    async def add_book(self, file_path: str | Path, scope: str = "project", title: Optional[str] = None,
                       authors: Optional[list[str]] = None, topics: Optional[list[str]] = None,
                       force: bool = False, *, relate: bool = False) -> tuple[BookCard, str]   # :977
    # :1015 path resolved; :1024-1033 sha256 dedup → (card, "skipped") when same bytes and not force;
    #   catalog.find_by_path(str(path)) match → status "updated", slug = existing.book_id
    # :1047 PDF without LLM → BookstoreError; md (:1060) and docx (:1076) need no LLM
    # :1126, :1129 `authors if authors is not None else draft.authors` — an EMPTY list overrides the draft!
    # :1105 `if title or authors or topics: card_origin = "manual"`
# packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
class BookCard(BaseModel):                                                 # :152
    book_id: str          # :159
    title: str            # :160
    page_count: Optional[int]  # :173
# packages/ai-parrot/src/parrot/knowledge/bookstore/config.py
class LibraryLocation:  # :31 — LibraryLocation(scope="project", root=<Path>); db_path=root/library.db, trees_dir=root/trees
# packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py
def resolve_adapter(llm_spec: Optional[str] = None, lightweight_model: Optional[str] = None
                    ) -> tuple[Optional[Any], Optional[str], Optional[Any]]   # :43 → (adapter, light, client) or (None, None, None)
```
Usage precedent: navigator-agent-server `agents/odoo_common.py:317-338`
(`resolve_adapter(spec)` → `Bookstore([LibraryLocation(scope="project", root=...)], adapter=adapter, lightweight_model=light)`).

### Does NOT Exist
- ~~A `source_path` / logical-name parameter on `Bookstore.add_book`~~ — identity is the resolved staging path.
- ~~`Bookstore.add_bytes` / in-memory ingest~~ — a real file path is required.
- ~~`BookstoreToolkit` write tools~~ — read-only; do not use it here.
- ~~`upload://` URIs~~ — dropped by the spec.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/bookstore.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_bookstore_target.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.add_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#LibraryLocation",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py#resolve_adapter",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCard"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pass `authors=request.authors or None` and `topics=request.topics or None`,
  `title=request.title or None` — because `add_book` treats an empty list as an
  explicit override (library.py:1126, :1129) and would wipe the drafted authors
  and mark the card `manual`.
- `resolve_adapter` constructs an LLM client (sync) — call it via
  `asyncio.to_thread` in `available()`.
- `available()` returns `(False, reason)` when the adapter is `None` (spec §2:
  PDF ingest requires an LLM ⇒ target unavailable) or `library_dir` cannot be
  created.
- Status mapping: `"added"` → ADDED, `"updated"` → UPDATED, `"skipped"` → SKIPPED
  ("Already present (same content) — use --force"); `BookstoreError` → FAILED
  with `str(exc)` (it is a user-meaningful message, never a path-free traceback
  — strip the absolute path if present).
- `detail`: `{"book_id": card.book_id, "title": card.title}`.

**Integration-test decision**: `available()` requires an adapter, so the
integration test does **not** call it. It constructs `BookstoreTarget(config)`
and injects `target._bookstore = Bookstore([LibraryLocation(scope="project",
root=target.library_dir)], adapter=None)` — a real no-LLM Bookstore, which
supports `.md` (library.py:1060). `_bookstore` is therefore a documented private
attribute set by `available()`; `ingest()` raises `RuntimeError` if it is
`None` (the service only calls `ingest` on available targets).

---

## Implementation Blueprint

### Steps (in order)
1. Write `targets/bookstore.py` — *why*: spec §3 M4.
2. Write the tests (unit with `AsyncMock` bookstore; integration with real md ingest) — *why*: AC6.
3. Run the Validation Commands.

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/bookstore.py` (CREATE)
```python
"""Bookstore ingest target (``/ingest_book``)."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from ..models import BookstoreTargetConfig, UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind
from .base import IngestTarget


class BookstoreTarget(IngestTarget):
    """Ingest uploads with ``Bookstore.add_book`` (same as ``bookstore add``)."""

    kind = UploadTargetKind.BOOKSTORE

    def __init__(self, config: BookstoreTargetConfig) -> None:
        """library_dir = Path(os.path.expandvars(config.library_dir)).expanduser().resolve();
        staging_dir = library_dir/'.uploads'."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.library_dir = Path(os.path.expandvars(config.library_dir)).expanduser().resolve()
        self._bookstore: Any | None = None

    @property
    def lock_key(self) -> Path:
        return self.library_dir

    @property
    def staging_dir(self) -> Path:
        return self.library_dir / ".uploads"

    async def available(self) -> tuple[bool, str]:
        """resolve_adapter(config.llm) must return an adapter."""
        from parrot.knowledge.bookstore._llm import resolve_adapter
        from parrot.knowledge.bookstore.config import LibraryLocation
        from parrot.knowledge.bookstore.library import Bookstore

        # FILL IN: adapter, light, _client = await asyncio.to_thread(resolve_adapter, self.config.llm);
        # adapter None → (False, "no LLM for <llm>"); mkdir library_dir; build and cache self._bookstore
        # with one project LibraryLocation; any exception → (False, short reason) — bounded by AC9 / spec §2
        raise NotImplementedError

    async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
        """Bookstore.add_book(staged_path, scope='project', title=, authors=, topics=, force=);
        'added'|'updated' → ADDED|UPDATED, 'skipped' → SKIPPED; BookstoreError → FAILED."""
        from parrot.knowledge.bookstore.library import BookstoreError

        if self._bookstore is None:
            raise RuntimeError("BookstoreTarget used before available()")
        try:
            card, status = await self._bookstore.add_book(
                staged_path,
                scope="project",
                title=request.title or None,
                authors=request.authors or None,
                topics=request.topics or None,
                force=request.force,
            )
        except BookstoreError as exc:
            # FILL IN: FAILED outcome; message without absolute paths — bounded by spec §7
            raise NotImplementedError from exc
        # FILL IN: map status → UploadStatus + message ("Added *Title* to the Bookstore", "Updated …",
        # "Already present (same content) — use --force"); detail={"book_id", "title"} — bounded by AC6
        raise NotImplementedError
```
**Why this shape**: the Bookstore is built once (catalog/toolkits are cached per
scope inside it); `asyncio` import is used by `available()`. Never pass the
original platform file name to `add_book` — only the staged path, whose name is
the stable identity (spec §2 Staging).

### FILL IN checklist
- [ ] `bookstore.py::available` — adapter required, cache `_bookstore`; bounded by AC9
- [ ] `bookstore.py::ingest` — status mapping and FAILED path; bounded by AC6, spec §7
- [ ] test bodies in `test_bookstore_target.py`

---

## Acceptance Criteria

- [ ] `available()` is `(False, reason)` when `resolve_adapter` yields no adapter (AC9).
- [ ] `add_book` is called with the staged path, `scope="project"`, `force=request.force`, and `None` (not `[]`) for absent authors/topics/title.
- [ ] Status mapping: added→ADDED, updated→UPDATED, skipped→SKIPPED, `BookstoreError`→FAILED (AC6).
- [ ] Integration: real Bookstore, `.md` staged as `<library>/.uploads/doc.md` → ADDED; same bytes again → SKIPPED; same name with new bytes → UPDATED with the same `book_id`.
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_bookstore_target.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/knowledge_upload/test_bookstore_target.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.knowledge_upload import (
    BookstoreTargetConfig, UploaderIdentity, UploadRequest, UploadStatus, UploadTargetKind,
)
from parrot.integrations.knowledge_upload.targets.bookstore import BookstoreTarget


def _req(**kw):
    return UploadRequest(target=UploadTargetKind.BOOKSTORE, filename="doc.md", data=b"# T\n\nbody",
                         identity=UploaderIdentity(platform="telegram", platform_user_id="1"), **kw)


async def test_available_without_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr("parrot.knowledge.bookstore._llm.resolve_adapter", lambda *a, **k: (None, None, None))
    ok, reason = await BookstoreTarget(BookstoreTargetConfig(library_dir=str(tmp_path))).available()
    assert not ok and reason


@pytest.mark.parametrize("status,expected", [("added", UploadStatus.ADDED), ("updated", UploadStatus.UPDATED),
                                             ("skipped", UploadStatus.SKIPPED)])
async def test_status_mapping(tmp_path, status, expected):
    target = BookstoreTarget(BookstoreTargetConfig(library_dir=str(tmp_path)))
    card = MagicMock(book_id="b1", title="T")
    target._bookstore = MagicMock(add_book=AsyncMock(return_value=(card, status)))
    out = await target.ingest(tmp_path / "doc.md", _req(), "job1")
    assert out.status == expected
    kwargs = target._bookstore.add_book.call_args.kwargs
    assert kwargs["authors"] is None and kwargs["topics"] is None


async def test_same_name_updates_real_bookstore(tmp_path):
    from parrot.knowledge.bookstore.config import LibraryLocation
    from parrot.knowledge.bookstore.library import Bookstore

    target = BookstoreTarget(BookstoreTargetConfig(library_dir=str(tmp_path / "lib")))
    target._bookstore = Bookstore([LibraryLocation(scope="project", root=target.library_dir)], adapter=None)
    staged = target.staging_dir / "doc.md"
    staged.parent.mkdir(parents=True)
    # FILL IN: write v1 → ADDED; same bytes → SKIPPED; v2 bytes same name → UPDATED, same book_id
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/teams-telegram-uploader-bookstore.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4184 teams-telegram-uploader-bookstore verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
