---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [knowledge-upload, integrations, authorization, dos, ledger-fix]
---

# Feature Specification: Authorize knowledge uploads before downloading the file

**Feature ID**: FEAT-673
**Date**: 2026-10-15
**Author**: Claude (agent:sdd-fix)
**Status**: approved
**Target version**: 0.30.x

---

## 1. Motivation & Business Requirements

> Ledger-driven fix (`/sdd-fix`, fixgroup:78be66fdfe17). Resolves
> `issue:3cf4d0630516` (major, vulnerability, discovered from FEAT-647).

### Problem Statement

`KnowledgeUploadService.authorize()` (allow-list check) runs only inside
`submit()` (`service.py:122`), which needs an `UploadRequest` carrying the
file bytes. All three platform adapters therefore download the file into
memory (10–20 MB) **before** the uploader is authorized:

- Telegram `TelegramKnowledgeUpload.handle` — `bot.download_file` at
  `telegram/knowledge_upload.py:146-147`.
- MS Teams `TeamsKnowledgeUpload.handle` — `self.download(...)` at
  `msteams/commands/knowledge_upload.py:152`.
- Slack `SlackKnowledgeUpload._process` — `self._download(...)` at
  `slack/knowledge_upload.py:173`.

Any user who can reach the bot (but is not on the upload allow-list) can
make it fetch and buffer files repeatedly before denial: a memory/bandwidth
DoS.

### Goals
- New `KnowledgeUploadService.pre_authorize(identity, target, filename,
  declared_size=None) -> UploadOutcome | None`: runs every check that needs
  no bytes — target availability, filename/extension, declared size,
  allow-list authorization — and returns the rejection outcome (audited,
  same messages/statuses as `submit()`), or `None` when the download may
  proceed.
- Each adapter calls `pre_authorize` **before** its download and replies
  with the rejection message (no fetch) when it is not `None`.
- `submit()` keeps all its checks (authoritative, on the real bytes) and
  shares the validation helper with `pre_authorize`.

### Non-Goals (explicitly out of scope)
- Teams download timeout / host allow-list and the startup staging sweep
  (`issue:1ac5c0eb31e5`, minor — separate issue).
- Caching the resolved profile between `pre_authorize` and `submit`: the
  second lookup happens only for already-authorized users after a
  successful download, so it does not reopen the DoS.
- Changing allow-list semantics (`UploadPolicy`) or messages.

---

## 2. Architectural Design

### Overview

Split `submit()`'s byte-independent checks into a shared helper and expose
them (plus `authorize`) as `pre_authorize`. Adapters reorder their flow to
build the `UploaderIdentity` first, pre-authorize, then download.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `KnowledgeUploadService.submit` (`service.py:108`) | modified | uses the shared `_validate` helper; behavior unchanged |
| `KnowledgeUploadService._invalid_outcome` (`service.py:181`) | modified | takes identity/target/filename/size instead of a request |
| `TelegramKnowledgeUpload.handle` (`telegram/knowledge_upload.py:121`) | modified | identity + `pre_authorize` before `get_file`/`download_file` |
| `TeamsKnowledgeUpload.handle` (`msteams/commands/knowledge_upload.py:124`) | modified | `pre_authorize` after `resolve_email`, before `download` |
| `SlackKnowledgeUpload._process` (`slack/knowledge_upload.py:154`) | modified | resolve email + `pre_authorize` before `_download` |

### New Public Interfaces

```python
async def pre_authorize(
    self,
    identity: UploaderIdentity,
    target: UploadTargetKind,
    filename: str,
    declared_size: int | None = None,
) -> UploadOutcome | None:
    """Reject an upload before any bytes are fetched; ``None`` means proceed."""
```

---

## 3. Module Breakdown

### Module 1: Service pre-authorization + adapter reordering
- **Paths**: `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/service.py`,
  `.../telegram/knowledge_upload.py`, `.../msteams/commands/knowledge_upload.py`,
  `.../slack/knowledge_upload.py`, and their tests under
  `packages/ai-parrot-integrations/tests/knowledge_upload/`.
- **Responsibility**: no adapter fetches bytes for an unauthorized uploader.
- **Depends on**: nothing new.

---

## 4. Test Specification

| Test | File | Description |
|---|---|---|
| `test_pre_authorize_denies_unlisted_user` | test_service.py | not on allow-list → `DENIED` outcome, audited, no job |
| `test_pre_authorize_rejects_invalid_before_lookup` | test_service.py | bad extension / declared oversize / unavailable target → `INVALID`, userinfo never called |
| `test_pre_authorize_allows` | test_service.py | allowed user, valid file → `None` |
| `test_denied_user_never_downloads` | test_telegram_upload.py | `pre_authorize` denies → `get_file` not called, denial message sent |
| `test_denied_user_never_downloads` | test_msteams_upload.py | `pre_authorize` denies → `download` not called |
| `test_denied_user_never_downloads` | test_slack_upload.py | `pre_authorize` denies → `_download` not called, denial posted |

Existing adapter fakes gain a `pre_authorize` returning `None`.

---

## 5. Acceptance Criteria

- [ ] AC1: `pre_authorize` returns `DENIED` (audited) for an unlisted user
      and `INVALID` for bad target/extension/declared size, without
      requiring file bytes; `None` when allowed.
- [ ] AC2: Telegram, Teams and Slack adapters call `pre_authorize` before
      any download call and send its message instead of downloading when
      it rejects.
- [ ] AC3: `submit()` behavior and messages are unchanged (existing
      `test_service.py` passes).
- [ ] AC4: the whole `packages/ai-parrot-integrations/tests/knowledge_upload/`
      suite passes; ruff clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.integrations.knowledge_upload.models import (  # verified: models.py:47,56,69,82,11
    UploaderIdentity, UploadRequest, UploadStatus, UploadOutcome, UploadTargetKind,
)
from parrot.integrations.knowledge_upload.service import KnowledgeUploadService  # verified: service.py:43
```

### Existing Signatures
```python
# service.py
class KnowledgeUploadService:
    async def authorize(self, identity: UploaderIdentity) -> EmployeeProfile | None:  # line 90 (audits DENIED)
    async def submit(self, request: UploadRequest, notify: Notify) -> UploadOutcome:  # line 108
    def max_bytes(self, platform_cap_mb: int | None = None) -> int:  # line 85
    def _invalid_outcome(self, job_id: str, request: UploadRequest, message: str) -> UploadOutcome:  # line 181
```

### Does NOT Exist (Anti-Hallucination)
- ~~`KnowledgeUploadService.pre_authorize`~~ — created by this feature.
- ~~`UploadRequest` without `data`~~ — `data: bytes` is required; do not
  build a request before download.

---

## 7. Implementation Notes & Constraints

- Cheap checks (target, extension, declared size) run before the identity
  lookup so malformed requests cost no userinfo call.
- Telegram passes `platform_cap_mb` already folded into its own size check;
  `pre_authorize` uses the service-wide `max_bytes()`, same as `submit()`.
- Teams has no reliable declared size → `declared_size=None`.
- Slack: identity resolution (`users.info`) moves before the download.

---

## 8. Open Questions

None.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-15 | Claude (agent:sdd-fix) | Initial spec from fixgroup:78be66fdfe17 / issue:3cf4d0630516 |
