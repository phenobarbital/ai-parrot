# TASK-4182: Knowledge upload — models, policy and staging

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4179
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (part A). The new subpackage `parrot.integrations.knowledge_upload`
needs its data models (spec §2 Data Models), the username-or-group authorization
policy (G3, AC3) and the staging helpers that guarantee the original file is
deleted (G4, AC5). The service (TASK-4183), the targets (TASK-4184/4185) and the
three platform adapters all build on these three files.

`resolve_profile` calls `UserInfoService.get_profile_by_email`, which TASK-4179
adds to `parrot/auth/userinfo.py` — hence the dependency.

---

## Scope

- Create `knowledge_upload/models.py` with every model from spec §2 Data Models,
  field-for-field (enums, configs, `UploaderIdentity`, `UploadRequest`,
  `UploadStatus`, `UploadOutcome`).
- Create `knowledge_upload/policy.py` with `UploadPolicy` and `resolve_profile`.
- Create `knowledge_upload/staging.py` with `safe_filename`, `staged_file`,
  `sweep_staging`.
- Create `knowledge_upload/__init__.py` exporting the **models only** (pydantic/stdlib) — never `policy`/`service`: the Telegram/Teams/Slack `models.py` import this package (TASK-4186), so it must not pull asyncdb/`parrot.auth`. Import `UploadPolicy` from `.policy`
  only (no service — that lands in TASK-4183).
- Write unit tests for policy and staging.

**NOT in scope**: `KnowledgeUploadService`, `IngestTarget`, `build_targets`
(TASK-4183); any target (TASK-4184/4185); config fields on the integration
dataclasses (TASK-4186); platform adapters.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/__init__.py` | CREATE | Package exports (models only — lightweight) |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/models.py` | CREATE | Pydantic v2 models from spec §2 |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/policy.py` | CREATE | `UploadPolicy`, `resolve_profile` |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/staging.py` | CREATE | `safe_filename`, `staged_file`, `sweep_staging` |
| `packages/ai-parrot-integrations/tests/knowledge_upload/__init__.py` | CREATE | Test package marker (other test dirs have one) |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_policy.py` | CREATE | Policy + resolve_profile tests |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_staging.py` | CREATE | Staging tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.userinfo import UserInfoService, EmployeeProfile  # verified: packages/ai-parrot/src/parrot/auth/userinfo.py:77 (UserInfoService), EmployeeProfile defined above it
from pydantic import BaseModel, Field                               # used throughout core (userinfo.py:20)
```
`parrot.integrations` is a namespace spread over core
(`packages/ai-parrot/src/parrot/integrations/__init__.py`) and this satellite;
new subpackages under `packages/ai-parrot-integrations/src/parrot/integrations/`
import fine (verified: `parrot.integrations.core` resolves to the satellite).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/userinfo.py
class EmployeeProfile(BaseModel):
    user_id: int | str                 # :64
    username: str | None = None        # :65
    email: str | None = None           # :67
    groups: list[str] = []             # :71
class UserInfoService:                                                  # :77
    def __init__(self, dsn: str | None = None, cache_ttl: int = 600, cache_max_size: int = 500) -> None  # :88
    async def get_profile(self, user_id: Any) -> EmployeeProfile | None  # :148 — never raises for a missing row
    # ADDED BY TASK-4179 (dependency, not yet in the tree when this task was written):
    async def get_profile_by_email(self, email: str) -> EmployeeProfile | None
```

### Does NOT Exist
- ~~`parrot.integrations.knowledge_upload`~~ — this task creates it.
- ~~`UserInfoService.get_profile_by_username`~~ — never added; identities are nav user id or email only.
- ~~`EmployeeProfile.roles`~~ — the field is `groups`.
- ~~`TelegramUserSession.groups`~~ — no session stores groups; always go through `UserInfoService`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/policy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/staging.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_policy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_staging.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#EmployeeProfile",
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#UserInfoService",
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#UserInfoService.get_profile"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2 only; models are copied from spec §2 — do not rename fields (the
  adapters and targets of later tasks rely on them).
- Policy is **deny by default**: both lists empty ⇒ nobody allowed (AC3).
- Matching is case-insensitive for usernames and groups (spec §2 Identity).
- `staged_file` must delete the file on normal exit, on exception and on
  `asyncio.CancelledError` (AC5) — use `try/finally`, never `except Exception`.
- Blocking filesystem calls go through `asyncio.to_thread` (spec §7 Patterns).
- Staging directory mode is `0o700`; set it with `chmod` after `mkdir` because
  `mkdir(mode=)` is masked by the umask.

### References in Codebase
- `packages/ai-parrot/tests/auth/test_userinfo_service.py` — fake-connection style if you need it (here a `MagicMock`/`AsyncMock` `UserInfoService` is enough).

---

## Implementation Blueprint

### Steps (in order)
1. Write `models.py` from spec §2 — *why*: every later task imports these names.
2. Write `policy.py` — *why*: AC3 authorization lives in one place, tested once.
3. Write `staging.py` — *why*: AC5 deletion guarantee lives in one context manager.
4. Write `__init__.py` exports (models only) — *why*: integration configs import the package root at module load (TASK-4186); keeping it pydantic-only avoids pulling asyncdb into every wrapper import.
5. Write the tests and run the Validation Commands.

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/models.py` (CREATE)
```python
"""Data models for chat-driven knowledge uploads (FEAT-647)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class UploadTargetKind(str, Enum):
    """Where an uploaded document is ingested."""

    BOOKSTORE = "bookstore"
    WIKI = "wiki"


class BookstoreTargetConfig(BaseModel):
    """Bookstore target settings; ``library_dir`` may contain env vars."""

    library_dir: str
    llm: str = "google:gemini-3.1-flash-lite"


class WikiTargetConfig(BaseModel):
    """LLM-wiki target settings; ``wiki_root`` holds ``.parrot/wiki.json``."""

    wiki_root: str
    charter_path: str | None = None
    llm: str = "google:gemini-3.1-flash-lite"


class KnowledgeUploadConfig(BaseModel):
    """Per-bot ``knowledge_upload`` block (one global allow-list per bot)."""

    enabled: bool = False
    allowed_usernames: list[str] = []
    allowed_groups: list[str] = []
    max_size_mb: int = Field(10, gt=0)
    allowed_extensions: list[str] = [".pdf", ".docx", ".md", ".markdown"]
    max_concurrent_jobs: int = Field(2, gt=0)
    slack_pending_window_s: int = Field(300, gt=0)
    bookstore: BookstoreTargetConfig | None = None
    wiki: WikiTargetConfig | None = None


class UploaderIdentity(BaseModel):
    """Who is uploading, as seen by the platform adapter."""

    platform: Literal["telegram", "msteams", "slack"]
    platform_user_id: str
    nav_user_id: str | None = None
    email: str | None = None


class UploadRequest(BaseModel):
    """One upload, bytes held in memory (≤ max_size_mb)."""

    target: UploadTargetKind
    identity: UploaderIdentity
    filename: str
    data: bytes
    force: bool = False
    title: str | None = None
    authors: list[str] = []
    topics: list[str] = []


class UploadStatus(str, Enum):
    """Outcome status of an upload request or job."""

    ACCEPTED = "accepted"
    DENIED = "denied"
    INVALID = "invalid"
    ADDED = "added"
    UPDATED = "updated"
    SKIPPED = "skipped"
    REJECTED_BY_TRIAGE = "rejected_by_triage"
    FAILED = "failed"


class UploadOutcome(BaseModel):
    """Result reported to the user (``message``) and to the audit log."""

    job_id: str
    status: UploadStatus
    target: UploadTargetKind
    filename: str
    message: str
    detail: dict[str, Any] = {}
```
**Why this shape**: verbatim spec §2; `str` enums so values serialize cleanly into
audit `extra=` fields. Do not add fields here — later tasks are written against
exactly these names.

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/policy.py` (CREATE)
```python
"""Authorization policy: username OR group allow-list, deny by default."""
from __future__ import annotations

import logging
from collections.abc import Iterable

from parrot.auth.userinfo import EmployeeProfile, UserInfoService

from .models import UploaderIdentity

logger = logging.getLogger(__name__)


class UploadPolicy:
    """Username-or-group allow-list; deny by default."""

    def __init__(self, allowed_usernames: Iterable[str], allowed_groups: Iterable[str]) -> None:
        self._usernames = {u.strip().casefold() for u in allowed_usernames if u and u.strip()}
        self._groups = {g.strip().casefold() for g in allowed_groups if g and g.strip()}

    def is_allowed(self, profile: EmployeeProfile | None) -> bool:
        """True iff profile is not None and (username ∈ allowed_usernames or groups ∩ allowed_groups),
        case-insensitive; False when both lists are empty."""
        # FILL IN: implement exactly the docstring rule — bounded by AC3 (OR, never AND; empty lists deny)
        raise NotImplementedError


async def resolve_profile(identity: UploaderIdentity, userinfo: UserInfoService) -> EmployeeProfile | None:
    """nav_user_id → get_profile; else email → get_profile_by_email (TASK-4179).

    Returns None when neither identifier is present or no row matches; a lookup
    error is logged and treated as None (deny), never raised to the chat.
    """
    # FILL IN: try identity.nav_user_id via userinfo.get_profile first; when it yields None and
    # identity.email is set, fall back to userinfo.get_profile_by_email — bounded by spec §2 Identity
    # (Telegram nav_user_id first, nav_email fallback; Teams/Slack email only)
    raise NotImplementedError
```
**Why**: the spec makes the profile the only identity source; `resolve_profile`
swallowing DB errors into `None` keeps "unknown identity ⇒ deny" (AC3) true even
when the auth DB is down.

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/staging.py` (CREATE)
```python
"""Private staging of uploaded bytes with guaranteed deletion (AC5)."""
from __future__ import annotations

import asyncio
import logging
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_filename(name: str) -> str:
    """Basename only, NFC, no separators/control chars; raises ValueError when empty."""
    # FILL IN: NFC-normalize, take the last component after splitting on both "/" and "\\",
    # drop control chars (unicodedata.category startswith "C"), strip spaces/dots at both ends,
    # keep the extension; raise ValueError if nothing usable remains — bounded by spec §2 Staging
    raise NotImplementedError


def _prepare_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)


@asynccontextmanager
async def staged_file(directory: Path, filename: str, data: bytes) -> AsyncIterator[Path]:
    """Create `directory` 0o700, write data to directory/safe_filename(filename), yield the path,
    unlink it in `finally` (also on CancelledError)."""
    path = directory / safe_filename(filename)
    await asyncio.to_thread(_prepare_dir, directory)
    try:
        await asyncio.to_thread(path.write_bytes, data)
        yield path
    finally:
        # FILL IN: unlink with missing_ok=True via asyncio.to_thread; if the await itself is
        # cancelled, still remove the file synchronously (path.unlink) — bounded by AC5
        raise NotImplementedError


def sweep_staging(directory: Path) -> int:
    """Delete leftover files from a crashed run; returns count."""
    # FILL IN: return 0 when the directory does not exist; unlink regular files only (never recurse
    # or follow symlinked dirs); log the count at INFO when > 0 — bounded by spec §2 Staging
    raise NotImplementedError
```
**Why this shape**: the context manager is the single place AC5 is enforced; the
service writes nothing to disk outside it. `safe_filename` keeps the extension
because both planes pick the loader by suffix.

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/__init__.py` (CREATE)
```python
"""Chat-driven document upload into the Bookstore / LLM wiki (FEAT-647)."""
from .models import (
    BookstoreTargetConfig,
    KnowledgeUploadConfig,
    UploaderIdentity,
    UploadOutcome,
    UploadRequest,
    UploadStatus,
    UploadTargetKind,
    WikiTargetConfig,
)

__all__ = [
    "BookstoreTargetConfig",
    "KnowledgeUploadConfig",
    "UploadOutcome",
    "UploadRequest",
    "UploadStatus",
    "UploadTargetKind",
    "UploaderIdentity",
    "WikiTargetConfig",
]
```
**Why**: TASK-4183 extends `__all__` with the service; keep the package import
light (no `parrot.knowledge` imports) so disabled bots pay nothing (spec §7).

### `packages/ai-parrot-integrations/tests/knowledge_upload/__init__.py` (CREATE)
```python
```
**Why**: sibling test dirs (`tests/telegram/`, `tests/msteams/`) are packages.

### FILL IN checklist
- [ ] `policy.py::UploadPolicy.is_allowed` — OR rule, case-insensitive, deny when both empty; bounded by AC3
- [ ] `policy.py::resolve_profile` — nav id first, email fallback, errors → None; bounded by spec §2 Identity
- [ ] `staging.py::safe_filename` — traversal-proof basename; bounded by spec §2 Staging
- [ ] `staging.py::staged_file` finally — unlink even on cancel; bounded by AC5
- [ ] `staging.py::sweep_staging` — files only, count returned
- [ ] test bodies in `test_policy.py` / `test_staging.py`

---

## Acceptance Criteria

- [ ] All models match spec §2 Data Models field-for-field.
- [ ] `UploadPolicy` allows by username only, by group only, case-insensitive; denies with empty lists and with `None` profile (AC3).
- [ ] `resolve_profile` uses nav user id first, email second; returns `None` on lookup errors.
- [ ] `safe_filename("../../etc/passwd")` → `"passwd"`; Windows separators handled; empty result raises `ValueError`.
- [ ] `staged_file` leaves no file after normal exit, exception and cancellation; directory mode is `0o700` (AC5).
- [ ] `sweep_staging` removes leftovers and returns the count; missing dir → 0.
- [ ] `ruff check` clean on all touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_policy.py -q`
- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_staging.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/knowledge_upload/test_policy.py
from unittest.mock import AsyncMock

import pytest

from parrot.auth.userinfo import EmployeeProfile
from parrot.integrations.knowledge_upload import UploaderIdentity
from parrot.integrations.knowledge_upload.policy import UploadPolicy
from parrot.integrations.knowledge_upload.policy import resolve_profile


def _profile(username="someone", groups=()):
    return EmployeeProfile(user_id=1, username=username, groups=list(groups))


class TestUploadPolicy:
    def test_allowed_by_username_case_insensitive(self):
        assert UploadPolicy(["JLara"], []).is_allowed(_profile("jlara"))

    def test_allowed_by_group(self):
        assert UploadPolicy([], ["curators"]).is_allowed(_profile(groups=["Curators"]))

    def test_deny_by_default(self):
        assert not UploadPolicy([], []).is_allowed(_profile("jlara", ["curators"]))

    def test_none_profile_denied(self):
        assert not UploadPolicy(["jlara"], ["curators"]).is_allowed(None)


async def test_resolve_profile_email_fallback():
    userinfo = AsyncMock()
    userinfo.get_profile.return_value = None
    userinfo.get_profile_by_email.return_value = _profile("jlara")
    ident = UploaderIdentity(platform="telegram", platform_user_id="9", nav_user_id="42", email="j@x.com")
    assert (await resolve_profile(ident, userinfo)).username == "jlara"


async def test_resolve_profile_error_is_none():
    userinfo = AsyncMock()
    userinfo.get_profile_by_email.side_effect = RuntimeError("db down")
    ident = UploaderIdentity(platform="slack", platform_user_id="U1", email="j@x.com")
    assert await resolve_profile(ident, userinfo) is None


# packages/ai-parrot-integrations/tests/knowledge_upload/test_staging.py
import asyncio
import stat

import pytest

from parrot.integrations.knowledge_upload.staging import safe_filename, staged_file, sweep_staging


def test_safe_filename_traversal():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\docs\\manual.pdf") == "manual.pdf"
    with pytest.raises(ValueError):
        safe_filename("../")


async def test_staged_file_deleted_on_success_error_cancel(tmp_path):
    async with staged_file(tmp_path / "up", "a.md", b"# hi") as p:
        assert p.read_bytes() == b"# hi"
        assert stat.S_IMODE((tmp_path / "up").stat().st_mode) == 0o700
    assert not p.exists()
    # FILL IN: exception path and CancelledError path (task cancelled while inside the block)


def test_sweep_staging(tmp_path):
    (tmp_path / "x.pdf").write_bytes(b"x")
    assert sweep_staging(tmp_path) == 1
    assert sweep_staging(tmp_path / "missing") == 0
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4182 teams-telegram-uploader-bookstore verified`
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
