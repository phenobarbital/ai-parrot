# TASK-4135: MS Teams — route non-audio attachments into the session store

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4129
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The Teams wrapper handles **audio only**: `_find_audio_attachment`
(`msteams/wrapper.py:822`) matches `AUDIO_CONTENT_TYPES` (`:108`) and
`_handle_voice_attachment` (`:841`) hands the URL to the transcriber. A `.docx` posted
in a Teams chat is ignored entirely.

This task adds the document sibling: find non-audio attachments, download them from
the Teams CDN using the existing bot-token path, and store them with
`SessionFileStore.put_bytes` so they become attachable handles like any web upload.

---

## Scope

- Add `_find_document_attachments(activity)` returning every non-audio attachment that
  carries a `content_url`.
- Add `_handle_document_attachment(turn_context, attachment)` that downloads via
  `aiohttp` with the token from `_get_attachment_token` and stores the bytes with
  `origin="upload"`, returning the `file_id` or `None` on failure.
- Wire both into the existing message path so documents are stored before the message
  is processed.
- Write tests with the HTTP download mocked.

**NOT in scope**: Telegram (TASK-4134) · changing voice handling · adaptive-card
attachments (`content_url` is absent for those — skip them) · the Jira side.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | Document discovery, download and store |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_document_attachments.py` | CREATE | Discovery + mocked-download tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                                           # verified: msteams/wrapper.py:16 (already imported)
from parrot.interfaces.file.session import SessionFileStore   # TASK-4128
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(...):
    AUDIO_CONTENT_TYPES = {...}                                              # line 108
    def _find_audio_attachment(self, activity: Activity) -> Optional[Attachment]:  # line 822
        if not activity.attachments:          # line 831
            return None
        for attachment in activity.attachments:                               # line 834
            content_type = (attachment.content_type or "").lower()            # line 835
            if any(ct in content_type for ct in self.AUDIO_CONTENT_TYPES):    # line 836
                return attachment
    async def _handle_voice_attachment(self, turn_context, attachment) -> None:   # line 841
        token = await self._get_attachment_token(turn_context)                # line 871
        ... url=attachment.content_url, auth_token=token                      # lines 874-876
    async def _get_attachment_token(self, turn_context) -> Optional[str]:     # line 914
        """Token for downloading attachments from the MS Teams CDN; may return None."""
```

### Does NOT Exist
- ~~a non-audio attachment handler in this wrapper~~ — only the audio pair above
- ~~a raw download helper on the wrapper~~ — `_handle_voice_attachment` delegates the
  fetch to `self._voice_transcriber.transcribe_url(...)` (`:874`); there is no reusable
  byte-downloading method. Write the `aiohttp` GET here
- ~~`requests` / `httpx`~~ — banned repo-wide (ruff TID251); `aiohttp` is already imported at `:16`
- ~~`attachment.content_bytes`~~ — Bot Framework attachments carry `content_url`, not bytes

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_document_attachments.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._find_audio_attachment",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/session.py#SessionFileStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Attachments without a `content_url` (adaptive cards) are skipped, not errored.
- A failed download logs a WARNING and returns `None`; the user's message still runs.
- The session id must come from the same `RequestContext` the bot binds — if the Teams
  path has no bound session at that point, store under the Teams conversation id and
  record that choice in the Completion Note.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_find_document_attachments` mirroring `_find_audio_attachment` — *why*: the
   audio matcher is the established shape in this file; diverging invites drift.
2. Add `_handle_document_attachment` with an `aiohttp` GET + bearer token — *why*: the
   Teams CDN needs the bot token, which `_get_attachment_token` already produces.
3. Wire both into the message path next to the voice branch — *why*: a document and a
   prompt usually arrive in the same activity.

### `.../msteams/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def _find_audio_attachment(self, activity: Activity) -> Optional\[Attachment\]:' packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py)
# BEFORE — insert above `def _find_audio_attachment(` (verified: msteams/wrapper.py:822)
    def _find_document_attachments(self, activity: Activity) -> list[Attachment]:
        """Return every non-audio attachment that carries a downloadable URL.

        Adaptive cards have no content_url and are skipped.
        """
        if not activity.attachments:
            return []
        found = []
        for attachment in activity.attachments:
            content_type = (attachment.content_type or "").lower()
            if any(ct in content_type for ct in self.AUDIO_CONTENT_TYPES):
                continue
            if not getattr(attachment, "content_url", None):
                continue
            found.append(attachment)
        return found

    async def _handle_document_attachment(
        self, turn_context: TurnContext, attachment: Attachment
    ) -> Optional[str]:
        """Download a non-audio Teams attachment into the session store.

        Reuses the existing CDN token path. Returns the file_id, or None when the
        download fails — a failure must never stop the user's message.
        """
        token = await self._get_attachment_token(turn_context)
        # FILL IN: aiohttp GET attachment.content_url with
        # headers={"Authorization": f"Bearer {token}"} when token is not None;
        # non-200 -> log WARNING and return None; read the bytes and
        # await store.put_bytes(session_id, attachment.name or "attachment",
        # data, origin="upload"); return record.file_id
        # bounded by AC14 and "a failed download never raises"
        raise NotImplementedError
```
**Why**: `_find_document_attachments` returns a *list* where the audio sibling returns
one item — a Teams message can carry several files and losing the extras would
reproduce the bug this feature fixes. Skipping URL-less attachments is what keeps
adaptive cards out of the store.

### FILL IN checklist
- [ ] `_handle_document_attachment` download + store; bounded by "never raises"
- [ ] wiring into the message path; bounded by "documents stored before processing"
- [ ] session-id source decision; record it in the Completion Note

---

## Acceptance Criteria

- [ ] A `.docx` Teams attachment produces a handle resolvable by `SessionFileStore` (spec AC14)
- [ ] An adaptive-card attachment (no `content_url`) is skipped, not errored
- [ ] Several document attachments in one activity all get handles
- [ ] A non-200 download logs a WARNING, returns `None`, and does not raise
- [ ] Audio attachments still take the voice path unchanged
- [ ] No `requests`/`httpx` import appears in the diff
- [ ] `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_document_attachments.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_voice_integration.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/msteams/test_document_attachments.py
import pytest

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TestFindDocumentAttachments:
    def test_skips_audio(self):
        # FILL IN: activity with one audio + one docx -> only the docx is returned

    def test_skips_attachment_without_content_url(self):
        """Adaptive cards carry no content_url."""
        # FILL IN

    def test_returns_all_documents(self):
        # FILL IN


class TestHandleDocumentAttachment:
    async def test_downloads_and_stores(self, tmp_path):
        """Spec AC14 — a mocked 200 becomes a resolvable handle."""
        # FILL IN: mock the aiohttp GET, assert store.resolve accepts the file_id

    async def test_failed_download_returns_none(self, tmp_path):
        """A non-200 logs and returns None without raising."""
        # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-docx-support --feature-id FEAT-639`)
2. Read the spec sections named in Context before writing code.
3. **Verify the Codebase Contract** — confirm every import and signature still exists;
   if anything moved, fix the contract in this file FIRST, then implement.
4. Check every `Depends-on` task is `done` in `sdd/tasks/index/jiratoolkit-docx-support.json`,
   then set this task `in-progress` and commit only that index file.
5. Implement from the blueprint; complete every `# FILL IN:`; never change a fixed signature.
6. Run the Validation Commands.
7. Commit only the files this task lists (never `git add .` / `-A`).
8. `scripts/sdd/close_task.sh TASK-4135 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any

## Completion Note

Merged by sdd-coder engine; targeted tests pass (upload handler 4, msteams 6). Teams files keyed by conversation id.
