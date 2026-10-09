# TASK-4183: Knowledge upload — IngestTarget base and KnowledgeUploadService

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4182
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (part B). The service is the platform-agnostic core of the
feature: validation, authorization, background job, process-wide per-target lock,
staging with guaranteed deletion, audit log, notification (G3, G4, G6, G9;
AC2, AC3, AC5, AC10–AC13). The targets (TASK-4184 bookstore, TASK-4185 wiki)
implement the `IngestTarget` ABC defined here; the platform adapters call
`submit()`.

---

## Scope

- Create `targets/base.py` with the `IngestTarget` ABC (spec §3 skeleton).
- Create `targets/__init__.py` with `build_targets(config)` that lazily imports
  `.bookstore` / `.wiki` **inside the function** (those modules land in
  TASK-4184 / TASK-4185).
- Create `service.py` with `KnowledgeUploadService` and a module-level
  process-wide lock registry `_TARGET_LOCKS: dict[Path, asyncio.Lock]`.
- Do NOT touch `knowledge_upload/__init__.py` (models-only by design, see TASK-4182); consumers import
  `parrot.integrations.knowledge_upload.service` / `.targets.base` directly.
- Unit tests with fake `IngestTarget` subclasses only.

**NOT in scope**: `BookstoreTarget` / `WikiTarget` bodies; platform adapters;
config fields on integration dataclasses (TASK-4186).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/__init__.py` | CREATE | `build_targets` with lazy imports |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/base.py` | CREATE | `IngestTarget` ABC |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/service.py` | CREATE | `KnowledgeUploadService`, `_TARGET_LOCKS`, audit logger |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_service.py` | CREATE | service tests with fake targets |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.userinfo import UserInfoService, EmployeeProfile   # verified: packages/ai-parrot/src/parrot/auth/userinfo.py:77
# Created by TASK-4182 (dependency):
from .models import (KnowledgeUploadConfig, UploadOutcome, UploadRequest, UploadStatus,
                     UploadTargetKind, UploaderIdentity)
from .policy import UploadPolicy, resolve_profile
from .staging import staged_file, sweep_staging
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/userinfo.py
class UserInfoService:                                          # :77
    def __init__(self, dsn: str | None = None, cache_ttl: int = 600, cache_max_size: int = 500) -> None  # :88 — DSN resolved lazily, construction does no I/O

# From TASK-4182 (dependency — exact names fixed by spec §2/§3):
class UploadPolicy:
    def __init__(self, allowed_usernames: Iterable[str], allowed_groups: Iterable[str]) -> None
    def is_allowed(self, profile: EmployeeProfile | None) -> bool
async def resolve_profile(identity: UploaderIdentity, userinfo: UserInfoService) -> EmployeeProfile | None
@asynccontextmanager
async def staged_file(directory: Path, filename: str, data: bytes) -> AsyncIterator[Path]
def sweep_staging(directory: Path) -> int
```

### Does NOT Exist
- ~~`parrot.integrations.knowledge_upload.targets.bookstore` / `.wiki`~~ — created by TASK-4184 / TASK-4185; import them **only inside** `build_targets`.
- ~~An existing job queue / background-job helper in ai-parrot~~ — the service owns its own `set[asyncio.Task]`.
- ~~A DB audit table~~ — audit is log-only (G9).
- ~~`EmployeeProfile.roles`~~ — use `groups`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/base.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/service.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_service.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#UserInfoService",
    "sym:packages/ai-parrot/src/parrot/auth/userinfo.py#EmployeeProfile"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `submit()` returns **immediately**: DENIED / INVALID without scheduling,
  ACCEPTED after `asyncio.create_task(...)` (AC11).
- Order inside the job (spec §2 Execution): semaphore → per-target lock →
  `staged_file` → `target.ingest` → audit log → `notify(outcome)`. Stage **inside**
  the lock — two jobs for the same target must never share the staging path (AC12).
- `_TARGET_LOCKS` is module-level, keyed by `target.lock_key` (resolved `Path`),
  so several wrappers (four Odoo bots) in one process share it (AC12).
- Any exception from `target.ingest` → FAILED outcome (message never contains a
  traceback or path); `notify` errors are logged, never raised (spec §3 M1).
- `asyncio.CancelledError` must propagate after cleanup (do not swallow it in the
  job), so `shutdown()` can await cancelled tasks.
- Audit: exactly one record per attempt (denied/invalid/finished) on logger
  `parrot.integrations.knowledge_upload.audit`, fields via `extra=`: platform,
  username (from profile, else platform_user_id), target, filename, sha256, size,
  status, triage action (`outcome.detail.get("triage_action")`), duration (AC13).
- User messages never echo allow-lists, paths or stack traces (spec §7).
- `job_id`: `uuid.uuid4().hex[:12]`.
- Extension check against `config.allowed_extensions` is case-insensitive on the
  suffix of `safe`-normalized name (AC2).

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:122` — `_background_tasks` set + `add_done_callback(discard)` pattern (lines 290-292).

---

## Implementation Blueprint

### Steps (in order)
1. Write `targets/base.py` — *why*: service and targets compile against the ABC.
2. Write `targets/__init__.py` with lazy imports — *why*: target modules do not exist yet and must not be imported when the feature is disabled.
3. Write `service.py` (two blocks below) — *why*: single owner of the job lifecycle.
4. Leave `knowledge_upload/__init__.py` untouched — *why*: it must stay models-only so integration configs can import it cheaply.
5. Write `test_service.py` with fake targets; run the Validation Commands.

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/base.py` (CREATE)
```python
"""Ingest target contract for knowledge uploads."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import UploadOutcome, UploadRequest, UploadTargetKind


class IngestTarget(ABC):
    """A knowledge plane an uploaded document can be ingested into."""

    kind: UploadTargetKind

    @property
    @abstractmethod
    def lock_key(self) -> Path:
        """Resolved root used for the process-wide lock."""

    @property
    @abstractmethod
    def staging_dir(self) -> Path:
        """Directory where the upload is staged for the duration of one ingest."""

    @abstractmethod
    async def available(self) -> tuple[bool, str]:
        """(usable, reason) — checked once at startup."""

    @abstractmethod
    async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
        """Ingest the staged file and return the user-facing outcome."""
```

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/__init__.py` (CREATE)
```python
"""Target factory for knowledge uploads (lazy: no knowledge imports when disabled)."""
from __future__ import annotations

from ..models import KnowledgeUploadConfig, UploadTargetKind
from .base import IngestTarget


def build_targets(config: KnowledgeUploadConfig) -> dict[UploadTargetKind, IngestTarget]:
    """Instantiate the configured targets; availability is checked by the service."""
    targets: dict[UploadTargetKind, IngestTarget] = {}
    if config.bookstore is not None:
        from .bookstore import BookstoreTarget  # lazy — TASK-4184

        targets[UploadTargetKind.BOOKSTORE] = BookstoreTarget(config.bookstore)
    if config.wiki is not None:
        from .wiki import WikiTarget  # lazy — TASK-4185

        targets[UploadTargetKind.WIKI] = WikiTarget(config.wiki)
    return targets


__all__ = ["IngestTarget", "build_targets"]
```
**Why**: spec §7 "lazy imports of `parrot.knowledge.*`"; the two target modules
are written in parallel by other tasks.

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/service.py` (CREATE) — block 1/2
```python
"""Platform-agnostic knowledge upload service (FEAT-647)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from parrot.auth.userinfo import EmployeeProfile, UserInfoService

from .models import KnowledgeUploadConfig, UploaderIdentity, UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind
from .policy import UploadPolicy, resolve_profile
from .staging import safe_filename, staged_file, sweep_staging
from .targets.base import IngestTarget

Notify = Callable[[UploadOutcome], Awaitable[None]]

audit_logger = logging.getLogger("parrot.integrations.knowledge_upload.audit")

# Process-wide: every service instance (one per bot wrapper) shares these locks (AC12).
_TARGET_LOCKS: dict[Path, asyncio.Lock] = {}


def _target_lock(key: Path) -> asyncio.Lock:
    lock = _TARGET_LOCKS.get(key)
    if lock is None:
        lock = _TARGET_LOCKS[key] = asyncio.Lock()
    return lock


class KnowledgeUploadService:
    """Authorize, validate, stage, ingest, delete, audit and notify."""

    def __init__(
        self,
        config: KnowledgeUploadConfig,
        targets: dict[UploadTargetKind, IngestTarget],
        userinfo: UserInfoService | None = None,
    ) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._targets = dict(targets)
        self._userinfo = userinfo or UserInfoService()
        self._policy = UploadPolicy(config.allowed_usernames, config.allowed_groups)
        self._semaphore = asyncio.Semaphore(config.max_concurrent_jobs)
        self._jobs: set[asyncio.Task] = set()

    @classmethod
    async def from_config(cls, config: KnowledgeUploadConfig) -> "KnowledgeUploadService":
        """Build configured targets lazily, run available() + sweep_staging(); unavailable targets are
        dropped with a logged reason."""
        from .targets import build_targets

        # FILL IN: for each built target await available(); drop (log WARNING with reason) when False;
        # sweep_staging(target.staging_dir) via asyncio.to_thread for kept ones — bounded by AC9
        raise NotImplementedError

    def available_targets(self) -> set[UploadTargetKind]:
        """Targets that passed ``available()`` (adapters advertise only these)."""
        return set(self._targets)

    def max_bytes(self, platform_cap_mb: int | None = None) -> int:
        """min(config.max_size_mb, platform_cap_mb) in bytes."""
        mb = self.config.max_size_mb if platform_cap_mb is None else min(self.config.max_size_mb, platform_cap_mb)
        return mb * 1024 * 1024

    async def authorize(self, identity: UploaderIdentity) -> EmployeeProfile | None:
        """Profile when allowed, None when denied (denial is audit-logged)."""
        profile = await resolve_profile(identity, self._userinfo)
        if self._policy.is_allowed(profile):
            return profile
        # FILL IN: audit-log the denial (status=denied, no filename/sha) — bounded by AC13
        return None
```

### `service.py` (CREATE) — block 2/2 (continue the class)
```python
    async def submit(self, request: UploadRequest, notify: Notify) -> UploadOutcome:
        """Validate (target available, extension, size, authorization) and return ACCEPTED immediately
        after scheduling the job; DENIED / INVALID outcomes are returned without scheduling."""
        job_id = uuid.uuid4().hex[:12]
        # FILL IN: order = target available → extension (safe_filename suffix, case-insensitive) →
        # size (len(request.data) > max_bytes()) → authorize(request.identity); INVALID/DENIED outcomes
        # with short user messages and one audit record each — bounded by AC2, AC3, AC10
        task = asyncio.create_task(self._run_job(job_id, request, profile, notify))
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)
        return UploadOutcome(
            job_id=job_id,
            status=UploadStatus.ACCEPTED,
            target=request.target,
            filename=request.filename,
            message=f"Received {request.filename} → {request.target.value}. Processing…",
        )

    async def _run_job(
        self, job_id: str, request: UploadRequest, profile: EmployeeProfile, notify: Notify
    ) -> None:
        target = self._targets[request.target]
        started = time.monotonic()
        sha256 = hashlib.sha256(request.data).hexdigest()
        outcome: UploadOutcome | None = None
        try:
            async with self._semaphore, _target_lock(target.lock_key):
                async with staged_file(target.staging_dir, request.filename, request.data) as staged:
                    outcome = await target.ingest(staged, request, job_id)
        except asyncio.CancelledError:
            # FILL IN: build a FAILED outcome ("cancelled"), audit it, re-raise — bounded by spec §2 Execution
            raise
        except Exception:  # noqa: BLE001 - any target failure becomes a FAILED outcome
            self.logger.exception("knowledge upload job %s failed", job_id)
            # FILL IN: FAILED outcome with a short message incl. job_id, never a traceback/path — bounded by spec §7
        # FILL IN: one audit record (sha256, size=len(request.data), duration, triage_action) then
        # `await notify(outcome)` wrapped so notify errors are logged only — bounded by AC11, AC13

    async def shutdown(self) -> None:
        """Cancel running jobs and await them."""
        for task in list(self._jobs):
            task.cancel()
        await asyncio.gather(*self._jobs, return_exceptions=True)
```
**Why this shape**: the lock is taken before staging so the stable staging path
(spec §2) is never shared by two concurrent jobs; `staged_file` sits inside the
`try`, so cancellation/failure still unlinks (AC5). `profile` is passed into the
job only for the audit record — authorization already happened in `submit`.

### FILL IN checklist
- [ ] `service.py::from_config` — availability + sweep; bounded by AC9
- [ ] `service.py::authorize` — denial audit record; bounded by AC13
- [ ] `service.py::submit` — validation order + INVALID/DENIED outcomes; bounded by AC2, AC3, AC10
- [ ] `service.py::_run_job` — cancel/failed outcomes, audit record, safe notify; bounded by AC5, AC11, AC13
- [ ] test bodies in `test_service.py`

---

## Acceptance Criteria

- [ ] `submit()` returns INVALID for disallowed extensions and oversize data, DENIED for unauthorized users — neither schedules a job (AC2, AC3, AC10).
- [ ] ACCEPTED is returned before the target finishes; `notify` receives the final outcome (AC11).
- [ ] Two jobs on the same `lock_key` never overlap, even across two service instances; different keys may overlap (AC12).
- [ ] Target exception → FAILED outcome, staged file deleted, notify still called.
- [ ] `shutdown()` cancels running jobs; staged files are deleted (AC5).
- [ ] Exactly one audit record per attempt on logger `parrot.integrations.knowledge_upload.audit` (AC13).
- [ ] `from_config` drops unavailable targets with a logged reason (AC9).
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_service.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/knowledge_upload/test_service.py
import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.auth.userinfo import EmployeeProfile
from parrot.integrations.knowledge_upload import (
    IngestTarget, KnowledgeUploadConfig, KnowledgeUploadService, UploaderIdentity,
    UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind,
)


class FakeTarget(IngestTarget):
    kind = UploadTargetKind.BOOKSTORE

    def __init__(self, root: Path, gate: asyncio.Event | None = None, fail: bool = False):
        self._root, self.gate, self.fail = root, gate, fail
        self.active = 0
        self.max_active = 0
        self.seen_paths: list[Path] = []

    @property
    def lock_key(self) -> Path:
        return self._root

    @property
    def staging_dir(self) -> Path:
        return self._root / ".uploads"

    async def available(self):
        return True, ""

    async def ingest(self, staged_path, request, job_id):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.seen_paths.append(staged_path)
        try:
            if self.gate:
                await self.gate.wait()
            if self.fail:
                raise RuntimeError("boom")
            return UploadOutcome(job_id=job_id, status=UploadStatus.ADDED, target=self.kind,
                                 filename=request.filename, message="ok")
        finally:
            self.active -= 1


@pytest.fixture
def userinfo():
    ui = AsyncMock()
    ui.get_profile.return_value = EmployeeProfile(user_id=1, username="jlara", groups=["curators"])
    return ui


def _request(data=b"# doc", name="a.md"):
    return UploadRequest(target=UploadTargetKind.BOOKSTORE, filename=name, data=data,
                         identity=UploaderIdentity(platform="telegram", platform_user_id="9", nav_user_id="1"))


async def test_submit_rejects_extension_and_size(tmp_path, userinfo):
    cfg = KnowledgeUploadConfig(enabled=True, allowed_usernames=["jlara"], max_size_mb=1)
    svc = KnowledgeUploadService(cfg, {UploadTargetKind.BOOKSTORE: FakeTarget(tmp_path)}, userinfo)
    assert (await svc.submit(_request(name="a.doc"), AsyncMock())).status == UploadStatus.INVALID
    assert (await svc.submit(_request(data=b"x" * (2 * 1024 * 1024)), AsyncMock())).status == UploadStatus.INVALID


async def test_job_notifies_and_deletes(tmp_path, userinfo):
    # FILL IN: ACCEPTED, await notify called with ADDED, staged path no longer exists
    ...


async def test_job_serializes_per_target_across_services(tmp_path, userinfo):
    # FILL IN: two services, same tmp_path target root, gate event; assert max_active == 1 across both
    ...


async def test_job_failure_becomes_failed_outcome(tmp_path, userinfo):
    ...


async def test_shutdown_cancels_jobs(tmp_path, userinfo):
    ...


async def test_denied_is_audited(tmp_path, userinfo, caplog):
    # FILL IN: allow-list without jlara/curators → DENIED, one record on the audit logger
    ...
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4183 teams-telegram-uploader-bookstore verified`
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
