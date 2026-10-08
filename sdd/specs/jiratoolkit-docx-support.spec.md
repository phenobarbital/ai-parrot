---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server, ai-parrot-integrations]
tags: [jira, attachments, file-upload, sandbox, toolkit]
---

# Feature Specification: Session file store and Jira attachments for binary documents

**Feature ID**: FEAT-639
**Date**: 2026-10-07
**Author**: Jesus
**Status**: approved
**Target version**: 1.2.0

---

## 1. Motivation & Business Requirements

### Problem Statement

Users report that **they cannot attach `.docx` files to a Jira ticket** through an
agent. The report arrived with no stack trace and no HTTP status, so the first
job was to establish whether Jira fails at all.

It does not. There are **two independent silent-drop paths** upstream of Jira:

1. **Non-tabular uploads are discarded.** `Agent.handle_files`
   (`packages/ai-parrot/src/parrot/bots/agent.py:365`) only understands `.xlsx`,
   `.xls` and `.csv`. Every other file is read into a `BytesIO`, matches no
   DataFrame branch, and **is dropped without ever being written to disk**
   (`agent.py:404-418`). The handler nevertheless answers
   `{"message": "Files uploaded successfully", "added_files": []}`
   (`handlers/agent.py:1289-1291`) — the user sees success.
2. **An upload that carries a prompt never reaches ingestion at all.**
   `_handle_attachments` is called only on the no-query branch:
   `if not query: return await self._handle_attachments(...)`
   (`handlers/agent.py:1821`). A multipart request with a file *and* a question
   — the natural way a user says *"attach this to NAV-123"* — bypasses
   `handle_files` entirely.

Either way no path exists on disk, and the only tool available,
`JiraToolkit.jira_add_attachment` (`parrot_tools/jiratoolkit.py:1748`), accepts
exactly one filesystem path (`attachment: str`). The model either hallucinates a
path (→ `FileNotFoundError` from `jira.JIRA.add_attachment`) or reports that it
cannot comply.

So "docx cannot be uploaded" is really **"binary uploads never become anything
the agent can reference"**. CSV and Excel work by accident, because they take the
DataFrame branch.

Three latent defects in the Jira layer compound it, and are fixed here because a
restored path alone would stay fragile:

- **Two divergent attachment paths.** `jira_add_attachment` (`:1748`) lets the
  exception escape; the upload loop inside `jira_add_comment` (`:2055-2079`)
  catches everything and returns `{"file": …, "error": …}`. Same operation,
  opposite failure contracts.
- **No pre-flight validation.** Size, emptiness and type are never checked. The
  library detects an empty attachment only *after* the round trip
  (`jira/client.py:1198-1202`), and the deployment's size limit surfaces as an
  opaque HTTP error — neither is actionable for a model deciding whether to retry.
- **A comment is committed before its attachments.** `jira_add_comment` creates
  the comment at `:2049-2052` and only then uploads, so an attachment failure
  leaves a published comment that promises a file nobody can see.

### Goals

- G1 — A file uploaded in a session (chat, web, Teams, Telegram) is **persisted**
  and addressable, whatever its type, and whether or not the request also
  carries a prompt.
- G2 — An agent can attach such a file to a Jira issue by **opaque handle**,
  never by filesystem path.
- G3 — One attachment path shared by `jira_add_attachment` and
  `jira_add_comment`, with one typed result envelope and one failure contract.
- G4 — Attachment failures are **pre-flighted and actionable** (`empty_file`,
  `too_large`, `unknown_handle`), not opaque `JIRAError`s.
- G5 — The upload endpoint stops reporting success for a file it discarded.
- G6 — An agent may only ever attach files inside its own session sandbox, and
  that boundary holds against traversal, absolute paths and symlinks.

### Non-Goals (explicitly out of scope)

- **Sending the real `Content-Type` to Jira.** `jira.JIRA.add_attachment`
  hard-codes `application/octet-stream` (`jira/client.py:1159-1161`); honouring
  the real MIME type would require a hand-rolled multipart POST. Decided on
  2026-10-07 to keep the library and accept the generic icon. MIME is recorded
  in the store's manifest as **advisory metadata only** — the spec contains no
  `aiohttp` multipart upload, no custom Jira endpoint call, and no acceptance
  criterion about the uploaded Content-Type.
- **TTL or automatic cleanup** of session files — persistence with manual
  cleanup is a deliberate decision (see §8 Q4 for the residual quota question).
- **The Jira tool fetching a URL itself.** Remote documents are imported into
  the session store by an explicit tool first; the Jira layer only ever resolves
  handles. This is the SSRF boundary.
- **A second general-purpose file abstraction.** A bespoke attachment store
  without `FileManagerToolkit` was rejected in the brainstorm (Option C) — see
  `sdd/proposals/jiratoolkit-docx-support.brainstorm.md`.
- **Rewriting `FileManagerToolkit`.** It is reused as the remote *transport*;
  `filemanager.py` is not modified by this feature.
- **The admin UI's own upload gate.** `DataManagementModal.svelte:112` rejects
  anything that is not `.xlsx`/`.xls` before a request is even made, and discards
  the server's response. Fixing it is deferred to a separate feature
  (`issue:04dcfd611ebc`, §8 Q5), so after this feature the docx path works through
  the API and the chat channels but **not** through the admin UI's data modal.

---

## 2. Architectural Design

### Overview

A thin **`SessionFileStore`** owns the sandbox, the handles and the manifest.
**`FileManagerToolkit` is reused as the remote transport** (S3/GCS/SharePoint/
OneDrive/Google Drive) and is not modified. The Jira layer consumes handles only.

Four decisions shape everything below, and all four came from verified evidence
rather than preference:

1. **The handle manifest lives on disk, beside the file.** The server runs under
   gunicorn with multiple workers: an in-memory `file_id`→path map would not
   survive a restart and would fail when the upload and the attachment land on
   different workers — which contradicts the "files persist" decision outright.
2. **The sandbox has its own canonicalizing resolver.**
   `FileManagerToolkit._resolve_output_path` (`filemanager.py:887`) returns any
   absolute path unchanged (`if Path(path).is_absolute(): return path`) and
   otherwise compares with a lexical `startswith`. It is not, and must not be
   used as, a security boundary. The store resolves with `Path.resolve()` +
   `is_relative_to(session_root)` and refuses symlinks.
3. **Session binding is request-scoped, never toolkit state.** Toolkits are
   long-lived, reusable instances; mutating a root per request would let
   concurrent sessions overwrite each other. The session id is read from the
   task-local `RequestContext` via `current_context()`
   (`utils/helpers.py:58`, bound by `AbstractBot.session()`), and an attachment
   call with no bound session is refused rather than defaulted.
4. **The store is written to before the request branches on `query`.** Otherwise
   the "file plus prompt" shape keeps losing the file (`handlers/agent.py:1821`).

Session roots are scoped by `session_id` alone, under `OUTPUT_DIR`.

### Component Diagram

```
 upload (multipart: file [+ query])
            │
            ▼
 AgentHandler._handle_upload_persistence        ← M4 (runs BEFORE the query branch)
            │
            ├──→ Agent.handle_files ──→ DataFrame registry      (tabular, unchanged)
            │
            └──→ SessionFileStore.put_bytes ──→ SessionFileRecord(file_id)   ← M1
                        │                              │
                        │                     <OUTPUT_DIR>/sessions/<session_id>/
                        │                        ├── <file_id>.bin
                        │                        └── <file_id>.json   (manifest sidecar)
                        ▼
      SessionFileToolkit  (sf_list_session_files,                     ← M2
                           sf_import_remote_file,  ──→ FileManagerToolkit (transport, unmodified)
                           sf_store_generated_file)
                        │  file_id
                        ▼
      JiraToolkit._attach_session_files  ──→ jira.JIRA.add_attachment  ← M3
                        │
                        ▼
              JiraAttachmentReport (one entry per input handle)

 Telegram / MS Teams wrappers ──→ SessionFileStore.put_bytes          ← M5
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `Agent.handle_files` (`bots/agent.py:365`) | modifies | Keeps the tabular branch; non-tabular files are persisted instead of dropped |
| `AgentHandler._handle_attachments` (`handlers/agent.py:1278`) | modifies | Honest response; persistence hoisted ahead of the `if not query` branch at `:1821` |
| `JiraToolkit.jira_add_attachment` (`jiratoolkit.py:1748`) | modifies | Hard cut: `attachment: str` → `file_ids: List[str]` |
| `JiraToolkit.jira_add_comment` (`jiratoolkit.py:2027`) | modifies | Hard cut: `attachments: List[str]` → `file_ids: List[str]`; **rebased onto FEAT-637's signature** |
| `FileManagerToolkit` (`tools/filemanager.py:724`) | uses | Remote transport only — **not modified** |
| `current_context()` (`utils/helpers.py:58`) | uses | Supplies `session_id`; `AbstractBot.session()` binds it |
| `OUTPUT_DIR` (`conf.py:56`) | uses | Parent of every session root |
| `AbstractToolkit` (`tools/toolkit.py:262`) | extends | `SessionFileToolkit` via `tool_prefix` |
| Telegram crew allowlist (`telegram/crew/payload.py:36`) | modifies | Add docx/pdf/office MIME types |
| MS Teams wrapper (`msteams/wrapper.py:831`) | extends | Non-audio attachments routed into the store |

### Data Models

```python
# packages/ai-parrot/src/parrot/interfaces/file/session.py  (new)

class SessionFileRecord(BaseModel):
    """Manifest entry for one stored session file. Serialized next to the blob."""
    file_id: str                 # opaque, URL-safe, >= 128 bits of entropy
    session_id: str
    filename: str                # sanitized original name, for display and Jira
    mime_type: str               # advisory only — never sent to Jira (see §1 Non-Goals)
    size: int
    origin: Literal["upload", "remote", "generated"]
    created_at: datetime


# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (new models)

AttachmentErrorCode = Literal[
    "unknown_handle",    # no manifest entry for this file_id in this session
    "no_session",        # no RequestContext bound — refused, never defaulted
    "outside_sandbox",   # resolved outside the session root (traversal/symlink)
    "missing_file",      # manifest entry exists, blob does not
    "empty_file",        # zero bytes — rejected before the round trip
    "too_large",         # exceeds the configured Jira attachment limit
    "forbidden",         # Jira 401/403
    "rejected",          # Jira 4xx other than 401/403/413
    "transport_error",   # network/timeout
]

class AttachmentResult(BaseModel):
    """Outcome for exactly ONE input handle. One entry per input, order preserved."""
    file_id: str
    ok: bool
    filename: Optional[str] = None
    attachment_id: Optional[str] = None
    size: Optional[int] = None
    error_code: Optional[AttachmentErrorCode] = None
    detail: Optional[str] = None   # bounded to 500 chars, newline-collapsed, never a raw body

class JiraAttachmentReport(BaseModel):
    """Shared envelope returned by BOTH attachment-bearing tools."""
    issue: str
    attachments: List[AttachmentResult]
    attached: int
    failed: int

class JiraCommentReport(BaseModel):
    """jira_add_comment result — comment and attachment outcomes are INDEPENDENT."""
    issue: str
    comment: Dict[str, Any]
    comment_ok: bool
    attachments: List[AttachmentResult]
    attached: int
    failed: int
```

`detail` is a **bounded, sanitized diagnostic**, never a verbatim response body:
a Jira error body can be a multi-kilobyte HTML page or carry operational detail,
and this string is fed directly into the model's context. The stable, matchable
signal is `error_code`; `detail` is for a human reading the transcript.

> This overrides the brainstorm's edge-case line *"Status and body surfaced
> verbatim"*. The override is deliberate and recorded in §9 (S10).

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/interfaces/file/session.py  (new)
class SessionFileStore:
    """Sandboxed, manifest-backed per-session file store."""
    def __init__(self, root: Optional[Path] = None) -> None: ...
    async def put_bytes(self, session_id: str, filename: str, data: bytes, *,
                        origin: str = "upload") -> SessionFileRecord: ...
    async def put_path(self, session_id: str, source: Path, *,
                       filename: Optional[str] = None,
                       origin: str = "generated") -> SessionFileRecord: ...
    async def resolve(self, session_id: str, file_id: str) -> tuple[SessionFileRecord, Path]: ...
    async def list_files(self, session_id: str) -> List[SessionFileRecord]: ...
    async def usage_bytes(self, session_id: str) -> int: ...

# packages/ai-parrot/src/parrot/tools/session_files.py  (new)
class SessionFileToolkit(AbstractToolkit):
    """Agent-facing view of the session store. tool_prefix = 'sf'."""
    async def list_session_files(self) -> Dict[str, Any]: ...
    async def import_remote_file(self, backend: str, remote_path: str,
                                 filename: Optional[str] = None) -> Dict[str, Any]: ...
    async def store_generated_file(self, filename: str, content: str) -> Dict[str, Any]: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: SessionFileStore | yes | Full signatures in §2; layout `<OUTPUT_DIR>/sessions/<session_id>/<file_id>.{bin,json}`; resolver = `Path.resolve()` + `is_relative_to` + `is_symlink()` refusal; `SessionFileError` subclasses map 1:1 to the `AttachmentErrorCode` values | — |
| M2: SessionFileToolkit | yes | `tool_prefix = "sf"`; session from `current_context()`; `import_remote_file` delegates to a `FileManagerToolkit` built per call with `manager_type=backend` | — |
| M3: Jira attachment pipeline | no | — | Must rebase onto FEAT-637's final `jira_add_comment` signature, which is not merged yet (§8 Q1) |
| M4: Ingestion + endpoint | no | — | The response shape is a hard cut; the consumer audit (§8 Q3) decides how far it reaches |
| M5: Channel wrappers | yes | Telegram: extend `allowed_mime_types` defaults; Teams: route non-audio attachments of `_find_audio_attachment`'s sibling path into `SessionFileStore.put_bytes` | — |

### Module 1: Session file store
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/session.py` *(new)*
- **Responsibility**: Owns the sandbox, the opaque handles and the on-disk
  manifest. Pure storage — knows nothing about requests, agents or Jira.
- **Depends on**: `parrot.conf.OUTPUT_DIR`; nothing else in this spec.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/session.py  (new)
  from parrot.conf import OUTPUT_DIR            # verified: parrot/conf.py:56

  class SessionFileError(Exception):
      """Base for every store refusal. Carries a stable `code`."""
      code: str

  class UnknownHandle(SessionFileError): ...        # code = "unknown_handle"
  class OutsideSandbox(SessionFileError): ...       # code = "outside_sandbox"
  class MissingBlob(SessionFileError): ...          # code = "missing_file"

  class SessionFileRecord(BaseModel):
      """Manifest entry for one stored file (fields in §2 Data Models)."""

  class SessionFileStore:
      """Per-session, sandboxed file store addressed by opaque handles.

      Layout: ``<root>/sessions/<session_id>/<file_id>.bin`` with a sibling
      ``<file_id>.json`` manifest, so a handle resolves after a restart and
      from any gunicorn worker sharing the directory.
      """
      def __init__(self, root: Optional[Path] = None) -> None:
          """Default root is ``OUTPUT_DIR / 'sessions'``."""

      def session_root(self, session_id: str) -> Path:
          """Return the canonical root for *session_id*, creating it on demand.

          Raises ValueError when *session_id* is empty or contains a path separator.
          """

      async def put_bytes(self, session_id: str, filename: str, data: bytes, *,
                          origin: str = "upload") -> SessionFileRecord:
          """Store *data* under a fresh handle; returns its manifest record.

          *filename* is sanitized (basename only, control chars stripped) before
          storage; the blob name is derived from the handle, never from the input.
          Writes blob then manifest, both via a temp file + atomic rename, so a
          partial write never yields a resolvable handle. Raises OSError on a
          full disk, after removing the partial file.
          """

      async def put_path(self, session_id: str, source: Path, *,
                         filename: Optional[str] = None,
                         origin: str = "generated") -> SessionFileRecord:
          """Copy *source* into the session root under a fresh handle."""

      async def resolve(self, session_id: str, file_id: str) -> tuple[SessionFileRecord, Path]:
          """Resolve a handle to its record and a verified-contained blob path.

          Canonicalizes with ``Path.resolve()`` and requires
          ``is_relative_to(session_root)``; refuses a symlinked blob.
          Raises UnknownHandle / OutsideSandbox / MissingBlob — never returns a
          path it has not proven to be inside the session root.
          """

      async def list_files(self, session_id: str) -> List[SessionFileRecord]:
          """Every record in the session, newest first."""

      async def usage_bytes(self, session_id: str) -> int:
          """Total bytes stored for the session.

          Reporting only: ``put_bytes``/``put_path`` log a WARNING once the total
          crosses ``SESSION_FILES_WARN_BYTES`` and then store the file anyway. No
          upload is ever rejected for an aggregate quota (§8 Q4).
          """
  ```

### Module 2: Session file toolkit
- **Path**: `packages/ai-parrot/src/parrot/tools/session_files.py` *(new)*
- **Responsibility**: The agent's only view of the store. Binds the session
  request-scoped, lists handles, and imports remote or generated content.
- **Depends on**: Module 1; `FileManagerToolkit` (unmodified); `current_context()`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/tools/session_files.py  (new)
  from parrot.tools.toolkit import AbstractToolkit        # verified: parrot/tools/toolkit.py:262
  from parrot.tools.filemanager import FileManagerToolkit  # verified: parrot/tools/filemanager.py:724
  from parrot.utils.helpers import current_context         # verified: parrot/utils/helpers.py:58
  from parrot.interfaces.file.session import SessionFileStore   # M1

  class SessionFileToolkit(AbstractToolkit):
      """Lists and stages the files of the CURRENT session, by handle."""
      tool_prefix: str = "sf"                 # verified: AbstractToolkit.tool_prefix at toolkit.py:276

      def __init__(self, store: Optional[SessionFileStore] = None) -> None: ...

      def _require_session(self) -> str:
          """Return the bound session id, or raise SessionFileError('no_session').

          Reads ``current_context()``; never falls back to a default session —
          an unbound call is refused so two concurrent sessions cannot collide.
          """

      async def list_session_files(self) -> Dict[str, Any]:
          """List the files available in this session.

          Returns {"files": [{"file_id", "filename", "mime_type", "size", "origin"}]}.
          Use a file_id with jira_add_attachment / jira_add_comment to attach it.
          """

      async def import_remote_file(self, backend: str, remote_path: str,
                                   filename: Optional[str] = None) -> Dict[str, Any]:
          """Import a file from remote storage into this session, returning its handle.

          *backend* is one of "s3", "gcs", "sharepoint", "onedrive", "gdrive"
          (verified: FileManagerToolkit manager_type, filemanager.py:746-753).
          Downloads via FileManagerToolkit into a private temp path, then hands
          it to the store. Returns {"file_id", "filename", "size"}.
          """

      async def store_generated_file(self, filename: str, content: str) -> Dict[str, Any]:
          """Store text the agent produced as a session file, returning its handle."""
  ```

### Module 3: Jira attachment pipeline (hard cut)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` *(modify)*
- **Responsibility**: One validated, handle-based attachment path behind both
  tools, with one typed envelope and independent comment/attachment statuses.
- **Depends on**: Module 1. FEAT-637 is **merged** (all 5 tasks `done`, 2026-10-07) —
  the gate in §8 Q1 is satisfied.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py

  class AddAttachmentInput(BaseModel):        # replaces jiratoolkit.py:361
      issue: str = Field(description="Issue key or id")
      file_ids: List[str] = Field(description="Session file handles from sf_list_session_files")

  class AddCommentInput(BaseModel):           # modifies jiratoolkit.py:455
      # `body`, `is_internal`, `template`, `template_params` as left by FEAT-637
      file_ids: Optional[List[str]] = Field(default=None, description="Session file handles")
      # REPLACES `attachments: Optional[List[str]]` (paths) — jiratoolkit.py:461

  class JiraToolkit(AbstractToolkit):         # verified: jiratoolkit.py:596
      async def _max_attachment_bytes(self) -> int:
          """Resolve this deployment's attachment size limit, cached per client.

          ``JIRA_MAX_ATTACHMENT_BYTES`` wins when set. Otherwise asks the live
          deployment via ``self.jira.attachment_meta()["uploadLimit"]``
          (verified: jira/client.py:1110) off the event loop — correct for Cloud
          and Server/DC alike, so the deployment never has to be known in
          advance. A failed or malformed probe logs a WARNING and falls back to
          10 MB. Never raises.
          """

      async def _attach_session_files(self, issue: str,
                                      file_ids: Sequence[str]) -> List[AttachmentResult]:
          """Resolve, pre-flight and upload each handle. Best-effort, never raises.

          Per handle, in order: resolve via SessionFileStore (unknown_handle /
          outside_sandbox / missing_file), then size checks (empty_file,
          too_large against ``await self._max_attachment_bytes()``), then upload off the
          event loop with ``asyncio.to_thread``. Jira failures map to forbidden /
          rejected / transport_error with a bounded, sanitized `detail`.
          Returns exactly one AttachmentResult per input, order preserved.
          """

      @requires_permission("jira.write")      # verified: jiratoolkit.py:1746
      @tool_schema(AddAttachmentInput)
      async def jira_add_attachment(self, issue: str,
                                    file_ids: List[str]) -> Dict[str, Any]:
          """Attach one or more session files to an issue. Requires jira.write.

          Returns a JiraAttachmentReport dict. Never raises for a per-file
          failure — read `attachments[].error_code`.
          """

      @requires_permission("jira.write")
      @tool_schema(AddCommentInput)
      async def jira_add_comment(self, issue: str, body: Optional[str] = None,
                                 is_internal: bool = False,
                                 file_ids: Optional[List[str]] = None,
                                 template: Optional[str] = None,
                                 template_params: Optional[Dict[str, Any]] = None
                                 ) -> Dict[str, Any]:
          # Signature confirmed against FEAT-637 as merged (jiratoolkit.py:2530-2538,
          # verified 1f74e23c7): `file_ids` REPLACES `attachments: Optional[List[str]]`;
          # `body`, `template` and `template_params` are FEAT-637's and are kept verbatim.
          """Comment on an issue, optionally attaching session files.

          Attachments are RESOLVED AND PRE-FLIGHTED BEFORE the comment is
          created, so a handle error never leaves a published comment promising
          a file. Upload still follows comment creation (Jira offers no
          rollback), so `comment_ok` and the per-file results are reported
          independently. Returns a JiraCommentReport dict.
          """
  ```

### Module 4: Ingestion and upload endpoint
- **Path**: `packages/ai-parrot/src/parrot/bots/agent.py`,
  `packages/ai-parrot-server/src/parrot/handlers/agent.py` *(modify)*
- **Responsibility**: Persist every upload, on both request shapes, and stop
  reporting success for a discarded file.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/bots/agent.py:365
  async def handle_files(self, attachments: Dict[str, Any]) -> Dict[str, Any]:
      """Register tabular uploads as DataFrames AND persist every upload.

      HARD CUT: previously returned List[str] of DataFrame names.
      Now returns {"dataframes": [...], "files": [SessionFileRecord-as-dict],
      "errors": [{"filename", "error"}]}.
      Tabular files are BOTH registered and stored, so they can be attached too.
      """

  # modifies packages/ai-parrot-server/src/parrot/handlers/agent.py
  async def _persist_attachments(self, bot: AbstractBot,
                                 attachments: Dict[str, Any]) -> Dict[str, Any]:
      """Persist uploads BEFORE the request branches on `query`.

      Called ahead of the `if not query:` branch at handlers/agent.py:1821, so a
      multipart request carrying a file AND a prompt no longer loses the file.
      """

  async def _handle_attachments(self, bot, agent,
                                attachments: Dict[str, Any]) -> web.Response:
      """Upload-only response. Reports what was stored and what was registered.

      HARD CUT on the response body: {"message", "added_files"} becomes
      {"files": [...], "dataframes": [...], "errors": [...], "agent"}.
      An upload that produced neither a stored file nor a DataFrame is a 4xx/5xx,
      never a success with an empty list.
      """
  ```

### Module 5: Channel wrappers
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/payload.py`,
  `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` *(modify)*
- **Responsibility**: Documents arriving over Telegram and MS Teams land in the
  session store like any web upload.
- **Depends on**: Module 1, Module 4.
- **Interface Skeleton**:
  ```python
  # modifies .../telegram/crew/payload.py:36 — extend the default allowlist with
  # docx/doc/xlsx/pptx/odt office MIME types (pdf is already present).

  # modifies .../msteams/wrapper.py (sibling of _find_audio_attachment:822)
  async def _handle_document_attachment(self, turn_context: TurnContext,
                                        attachment: Attachment) -> Optional[str]:
      """Download a non-audio Teams attachment into the session store.

      Reuses the existing CDN token path (_get_attachment_token, wrapper.py:914).
      Returns the file_id, or None when the download fails.
      """
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_put_bytes_creates_blob_and_manifest` | M1 | Both files written; record round-trips |
| `test_resolve_returns_contained_path` | M1 | Happy path returns record + path inside the root |
| `test_resolve_rejects_unknown_handle` | M1 | `UnknownHandle`, no filesystem access |
| `test_resolve_rejects_traversal_handle` | M1 | `../`-style handle → `OutsideSandbox` |
| `test_resolve_rejects_absolute_path_handle` | M1 | An absolute path as a handle is refused (the gap in `_resolve_output_path`) |
| `test_resolve_rejects_symlinked_blob` | M1 | Symlink pointing outside → `OutsideSandbox` |
| `test_handle_not_resolvable_across_sessions` | M1 | A valid handle of session A fails under session B |
| `test_store_survives_restart` | M1 | A fresh `SessionFileStore` over the same root resolves an existing handle |
| `test_duplicate_filenames_get_distinct_handles` | M1 | Same name twice → two handles, two blobs |
| `test_filename_is_sanitized` | M1 | `../../etc/passwd` as a filename stores a basename only |
| `test_partial_write_leaves_no_resolvable_handle` | M1 | Disk-full during write → handle not resolvable, no stray blob |
| `test_toolkit_refuses_without_session` | M2 | No `RequestContext` → `no_session`, never a default root |
| `test_toolkit_lists_only_current_session` | M2 | Two bound sessions see disjoint listings |
| `test_import_remote_file_returns_handle` | M2 | `FileManagerToolkit` download mocked; handle resolvable afterwards |
| `test_attach_reports_one_entry_per_handle` | M3 | N handles in → N results out, order preserved |
| `test_attach_rejects_empty_file_before_upload` | M3 | `empty_file`; the Jira client is never called |
| `test_attach_rejects_oversize_before_upload` | M3 | `too_large` against the configured limit; client never called |
| `test_attach_maps_jira_403_to_forbidden` | M3 | Error code mapping, `detail` bounded to 500 chars |
| `test_attach_detail_is_sanitized` | M3 | A 50 KB HTML error body is not echoed into the result |
| `test_mixed_handles_are_best_effort` | M3 | Good + bad handles: successes stand, failures named |
| `test_comment_preflights_handles_before_creating` | M3 | A bad handle means no comment is created |
| `test_comment_ok_with_failed_attachment` | M3 | Upload failure after creation → `comment_ok=True`, `failed=1` |
| `test_add_attachment_requires_write` | M3 | `jira.write` still enforced on the new signature |
| `test_handle_files_persists_docx` | M4 | A `.docx` upload produces a resolvable handle |
| `test_handle_files_persists_and_registers_csv` | M4 | A CSV is BOTH a DataFrame and a stored file |
| `test_upload_response_reports_stored_files` | M4 | No `{"message": "...successfully", "added_files": []}` |
| `test_upload_with_query_persists_file` | M4 | **Regression for `handlers/agent.py:1821`** — file + prompt keeps the file |
| `test_telegram_allowlist_accepts_docx` | M5 | docx MIME passes `validate_mime` |

### Integration Tests

| Test | Description |
|---|---|
| `test_upload_then_attach_by_handle` | Upload a docx → list handles → `jira_add_attachment` → Jira client called once with the stored path |
| `test_upload_with_prompt_then_attach` | The real user shape: multipart with file + "attach this to NAV-1", end to end |
| `test_remote_import_then_attach` | `sf_import_remote_file` → handle → attached |
| `test_concurrent_sessions_do_not_cross_resolve` | Two concurrent `AbstractBot.session()` blocks; neither resolves the other's handles |

### Test Data / Fixtures

```python
@pytest.fixture
def session_store(tmp_path) -> SessionFileStore:
    """Store rooted in tmp_path — never the real OUTPUT_DIR."""

@pytest.fixture
def bound_session(session_store):
    """Binds a RequestContext(session_id='s-test') for the duration of the test."""

@pytest.fixture
def docx_bytes() -> bytes:
    """Minimal valid .docx (a zip with [Content_Types].xml) — built in-test, no binary fixture."""
```

---

## 5. Acceptance Criteria

- [ ] AC1 — A `.docx` or `.pdf` uploaded in a session is persisted and resolvable
      by handle; `test_handle_files_persists_docx` passes.
- [ ] AC2 — A multipart request carrying **both** a file and a prompt persists the
      file; `test_upload_with_query_persists_file` passes (regression for
      `handlers/agent.py:1821`).
- [ ] AC3 — The upload endpoint never answers success for an upload that produced
      neither a stored file nor a DataFrame.
- [ ] AC4 — Both `jira_add_attachment` and `jira_add_comment` take `file_ids` and
      return exactly one `AttachmentResult` per input handle, order preserved.
- [ ] AC5 — No attachment tool accepts a filesystem path or a URL. Grep of the two
      tool schemas shows `file_ids` only.
- [ ] AC6 — A handle that resolves outside its session root is refused before any
      I/O: traversal, absolute-path and symlink cases all raise `OutsideSandbox`.
- [ ] AC7 — A handle from another session is not resolvable.
- [ ] AC8 — Empty and oversize files are rejected **before** the Jira round trip;
      the Jira client is provably not called.
- [ ] AC9 — The attachment size limit is **discovered** from
      `JIRA.attachment_meta()["uploadLimit"]` and overridable by
      `JIRA_MAX_ATTACHMENT_BYTES`; it is never a constant in code. Tested at the
      boundary and boundary+1, plus the probe-failure fallback path.
- [ ] AC10 — `detail` on a failed attachment is at most 500 characters and never a
      raw Jira response body; `error_code` is one of the declared literals.
- [ ] AC11 — A bad handle prevents comment creation; an upload failure *after*
      creation reports `comment_ok=True` with the failure listed.
- [ ] AC12 — Handles resolve from a freshly constructed store over the same root
      (restart/cross-worker proxy); `test_store_survives_restart` passes.
- [ ] AC13 — An attachment call with no bound `RequestContext` is refused with
      `no_session` rather than defaulting to any root.
- [ ] AC14 — docx passes the Telegram MIME allowlist; Teams document attachments
      produce a handle.
- [ ] AC15 — No `aiohttp` multipart upload to Jira and no custom Jira attachment
      endpoint exist in the diff (the Non-Goal is observable, per S12).
- [ ] AC16 — Crossing `SESSION_FILES_WARN_BYTES` logs a WARNING and still stores
      the file; no code path rejects an upload on an aggregate session quota.
- [ ] AC17 — Every in-repo caller of the changed signatures is updated in this
      feature (hard cut, no shim). The upload response has **no** in-repo consumer
      (audited §8 Q3), so nothing reads it; the admin UI is out of scope (§8 Q5).
      Measured surface for the Jira cut (2026-10-08, `1f74e23c7`): **no production
      caller passes `attachments=`** — the only occurrences are the docstring example
      (`jiratoolkit.py:2550`) and four call sites in
      `tests/test_jira_comment_attachments.py`; `jira_add_attachment` is referenced
      only in `tests/test_jiratoolkit_permissions.py:165-167,236`.
- [ ] AC18 — `ruff check` clean on every changed file; no banned import introduced.

---

## 6. Codebase Contract

> Verified against base commit `e4d2a224e` on `dev`, 2026-10-07; the
> `jiratoolkit.py` rows were re-verified against `1f74e23c7` on 2026-10-08,
> after FEAT-637 merged (rev 0.3).

### Verified Imports

```python
from parrot.conf import OUTPUT_DIR                        # verified: parrot/conf.py:56
from parrot.utils.helpers import RequestContext, current_context
#                                                          # verified: parrot/utils/helpers.py:7, :58
#   (_current_ctx ContextVar at :53; imported by bots/abstract.py:67)
from parrot.tools.filemanager import FileManagerToolkit    # verified: parrot/tools/filemanager.py:724
from parrot.tools.toolkit import AbstractToolkit           # verified: parrot/tools/toolkit.py:262
from parrot_tools.jiratoolkit import JiraToolkit           # verified: parrot_tools/jiratoolkit.py:596
# inside jiratoolkit.py (:52-57), already present:
from parrot.tools.manager import ToolManager               # verified: jiratoolkit.py:52
from .toolkit import AbstractToolkit                       # verified: jiratoolkit.py:55
from .decorators import tool_schema, requires_permission   # verified: jiratoolkit.py:56
from .jira_config import JiraToolkitConfig                 # verified: jiratoolkit.py:57
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class AddAttachmentInput(BaseModel):                           # line 361
    issue: str = Field(description="Issue key or id")          # line 364
    attachment: str = Field(description="Path to attachment file on disk")   # line 365

class AddCommentInput(BaseModel):                              # line 455
    issue: str                                                 # line 458
    body: str                                                  # line 459
    is_internal: bool = Field(default=False, ...)              # line 460
    attachments: Optional[List[str]] = Field(default=None, ...) # line 461

class JiraToolkit(AbstractToolkit):                            # line 596
    def _set_jira_client(self)                                 # line 908
    def _init_jira_client(self) -> JIRA                        # line 915
    #   options = {"server":…, "verify": False,
    #              "headers": {"Accept-Encoding": "gzip, deflate"}}   # lines 916-921
    def _issue_to_dict(self, issue_obj: Any) -> Dict[str, Any] # line 1157
    @staticmethod _project_of(issue)                           # line 1605
    async def jira_add_attachment(self, issue: str, attachment: str) -> Dict[str, Any]  # line 1748
    #   body: self.jira.add_attachment(issue=issue, attachment=attachment)  # line 1755
    async def jira_add_comment(self, issue, body, is_internal=False,
                               attachments=None) -> Dict[str, Any]          # line 2027
    #   comment created BEFORE uploads:  self.jira.add_comment(...)         # line 2049-2052
    #   per-file loop with os.path.isfile + to_thread + except -> {"error"}  # lines 2055-2079

# packages/ai-parrot/src/parrot/bots/agent.py
async def handle_files(self, attachments: Dict[str, Any]) -> List[str]:     # line 365
    #   ONLY .xlsx/.xls/.csv produce a DataFrame                            # lines 404-410
    #   anything else -> df is None -> bytes dropped, nothing stored        # lines 411-418

# packages/ai-parrot-server/src/parrot/handlers/agent.py
async def _handle_attachments(self, bot, agent, attachments) -> web.Response:   # line 1278
    added_files = await bot.handle_files(attachments)                       # line 1287
    return self.json_response({"message": "Files uploaded successfully",
                               "added_files": added_files, ...})            # lines 1289-1291
#   call site — ONLY on the no-query branch:
    if not query:
        return await self._handle_attachments(bot, agent, attachments)      # line 1821
#   enclosing scope:  async with agent.session(request=…, user_id=…, session_id=…) as bot:  # line 1811

# packages/ai-parrot/src/parrot/tools/filemanager.py
class FileManagerToolkit(AbstractToolkit):                                  # line 724
    tool_prefix: Optional[str] = "fs"                                       # line 762
    manager_type: "fs"|"temp"|"s3"|"gcs"|"sharepoint"|"onedrive"|"gdrive"   # lines 746-753
    max_file_size: int = 100 * 1024 * 1024                                  # line 768
    def _check_file_size(self, size: int) -> None                           # line 854
    _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint","onedrive","gdrive"}) # line 866
    def _storage_path(self, path) -> str                                    # line 870
    def _resolve_output_path(self, path=None) -> str                        # line 887
    #   if Path(path).is_absolute() or path.startswith(self.default_output_dir):
    #       return path            # <-- NOT a security boundary            # lines 897-899
    async def list_files(...)   # 905      async def upload_file(...)       # 944
    async def download_file(...) # 993     async def get_file_metadata(...) # 1144
    async def create_file(...)  # 1173     async def find_files(...)        # 1222
    async def batch_upload(self, items: List[Dict[str, str]])               # line 1258
    async def batch_download(self, items: List[Dict[str, str]])             # line 1348

# packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext:                                                       # line 7
    def __init__(self, request=None, app=None, llm=None,
                 user_id=None, session_id=None, **kwargs)                   # line 17
_current_ctx: ContextVar[Optional[RequestContext]]                          # line 53
def current_context() -> Optional[RequestContext]                           # line 58

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    exclude_tools: tuple[str, ...] = ()                                     # line 262
    tool_prefix: str | None = None                                          # line 276
    def get_tools(...)                                                      # line 522
    def _generate_tools(self) -> None                                       # line 575

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/payload.py
self.allowed_mime_types = allowed_mime_types or [                           # line 36
    "text/csv","application/json","text/plain","image/png","image/jpeg",
    "application/pdf","application/vnd.apache.parquet"]                     # lines 37-44

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
def _find_audio_attachment(self, activity) -> Optional[Attachment]          # line 822
async def _handle_voice_attachment(self, turn_context, attachment) -> None  # line 841
async def _get_attachment_token(self, turn_context) -> Optional[str]        # line 914
```

External library behavior (installed, verified — `jira==3.10.5`):

```python
# .venv/lib/python3.12/site-packages/jira/client.py
def add_attachment(self, issue, attachment: str | BufferedReader,
                   filename: str | None = None) -> Attachment:              # line 1119
    if isinstance(attachment, str):
        attachment_io = open(attachment, "rb")   # FileNotFoundError here    # line 1141
    encoded_data = MultipartEncoder(
        fields={"file": (fname, attachment_io, "application/octet-stream")}) # line 1160
    #                                            ^ Content-Type HARD-CODED
    request_headers = {..., "X-Atlassian-Token": "no-check"}                 # lines 1162-1167
    url = self._get_url(f"issue/{issue}/attachments")                        # line 1179
    if jira_attachment.size == 0:
        raise JIRAError("Added empty attachment?!: ...")                     # lines 1198-1202

def attachment_meta(self) -> dict[str, int]:                                 # line 1110
    """GET attachment/meta -> {"enabled": bool, "uploadLimit": int}."""      # line 1116
self.deploymentType = None                                                   # line 658
    self.deploymentType = si.get("deploymentType")                           # line 667
@property
def _is_cloud(self) -> bool: return self.deploymentType in ("Cloud",)        # lines 702-704
```

Admin UI (TypeScript/Svelte — **not modified by this feature**, see §8 Q5):

```ts
// packages/ai-parrot-server/ui/src/lib/api/agent.ts
const BASE_PATH = "/api/v1/agents/chat";                                     // line 11
export const uploadAgentData = async (                                       // line 153
  agentName: string, formData: FormData, client?: AxiosInstance): Promise<any> => {
  const response = await http.put(`${BASE_PATH}/${agentName}`, formData, {   // line 159
    headers: { "Content-Type": "multipart/form-data" } });
  return response.data;                                                      // caller discards it
};

// packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte
message: "Only Excel files (.xlsx, .xls) are allowed.",                      // line 112
await uploadAgentData(agentId, formData);                                    // line 122
uploadStatus = { type: "success", message: "Uploaded" };                     // line 123 — hardcoded
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SessionFileStore` | `OUTPUT_DIR` | module attribute | `parrot/conf.py:56` |
| `SessionFileToolkit._require_session` | `current_context()` | function call | `parrot/utils/helpers.py:58` |
| `SessionFileToolkit.import_remote_file` | `FileManagerToolkit.download_file()` | method call | `parrot/tools/filemanager.py:993` |
| `JiraToolkit._attach_session_files` | `SessionFileStore.resolve()` | method call | M1 (new) |
| `JiraToolkit._attach_session_files` | `self.jira.add_attachment()` | method call | `jiratoolkit.py:1755` / `jira/client.py:1119` |
| `_persist_attachments` | `SessionFileStore.put_bytes()` | method call | M1 (new) |
| `_persist_attachments` | the `if not query:` branch | hoisted above it | `handlers/agent.py:1821` |
| `_handle_document_attachment` | `_get_attachment_token()` | method call | `msteams/wrapper.py:914` |

### Does NOT Exist (Anti-Hallucination)

- ~~`packages/ai-parrot/src/parrot/interfaces/jira.py`~~ — Jira is a **package**:
  `parrot/interfaces/jira/{__init__,client,errors,models,parse}.py`
- ~~`JiraInterface.add_attachment` / `get_attachment` / any attachment method~~ —
  `JiraInterface` (`interfaces/jira/client.py:101`) has **no** attachment support;
  every attachment call goes through the raw `jira.JIRA` client on `JiraToolkit`
- ~~A session file store, a `file_id` namespace, or any handle→path resolver~~ —
  introduced by this feature; nothing of the sort exists today
- ~~`FileManagerToolkit._resolve_output_path` as a sandbox check~~ — it exists
  (`filemanager.py:887`) but **returns absolute paths unchanged**; it is NOT a
  containment check and must not be used as one
- ~~A "remote source → local session store" operation on `FileManagerToolkit`~~ —
  `download_file` (`:993`) targets the backend fixed at construction; the import
  operation is new (M2)
- ~~`async def fs_upload_file(...)`~~ — no `fs_`-prefixed methods in source; names
  are generated from `upload_file` via `tool_prefix = "fs"` (`filemanager.py:762`)
- ~~Any MIME detection in the Jira attachment path~~ — no `mimetypes` call in
  `jiratoolkit.py`; the only MIME shown is read back from Jira's response (`:2073`)
- ~~A size, emptiness or type check before upload~~ — `jira_add_comment` checks
  only `os.path.isfile` (`:2057`); `jira_add_attachment` checks nothing
- ~~A Jira attachment-size constant or config key anywhere in the repo~~ — none;
  M3 introduces it (as discovery + override, not a constant)
- ~~Any consumer of the `added_files` upload response~~ — audited across `.py`,
  `.ts`, `.svelte` and `.js`: one producer (`handlers/agent.py:1287-1289`), **zero
  consumers**. The admin UI calls the endpoint but discards the body
- ~~Any docx/PDF branch in `Agent.handle_files`~~ — only `.xlsx`, `.xls`, `.csv`
  (`agent.py:404-410`)
- ~~`.docx` in the Telegram crew MIME allowlist~~ — the default list
  (`telegram/crew/payload.py:36-44`) has csv, json, txt, png, jpeg, pdf, parquet only
- ~~A non-audio attachment handler in the MS Teams wrapper~~ — only
  `_find_audio_attachment` (`:822`) / `_handle_voice_attachment` (`:841`)

### Edit Sites (Blueprint Anchors)

> **`/sdd-task` MUST re-run each `grep -c`.** The `jiratoolkit.py` rows below were
> refreshed on 2026-10-08 against `1f74e23c7`, after FEAT-637 merged — all four
> anchors drifted (361→389, 455→507, 1748→2169, 2027→2530) but remain unique.
> `dev` keeps moving, so re-verify again at implementation time.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/session.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/session_files.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 input schema) | `class AddAttachmentInput(BaseModel):` | `jiratoolkit.py:389` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 comment schema) | `class AddCommentInput(BaseModel):` | `jiratoolkit.py:507` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 attachment tool) | `    async def jira_add_attachment(self, issue: str, attachment: str) -> Dict[str, Any]:` | `jiratoolkit.py:2169` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY (M3 comment tool) | `    async def jira_add_comment(` | `jiratoolkit.py:2530` | 1 |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY (M4 ingestion) | `    async def handle_files(self, attachments: Dict[str, Any]) -> List[str]:` | `bots/agent.py:365` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY (M4 response) | `    async def _handle_attachments(` | `handlers/agent.py:1278` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY (M4 hoist persistence above this branch) | `                if not query:\n                    return await self._handle_attachments(bot, agent, attachments)` | `handlers/agent.py:1820-1821` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/payload.py` | MODIFY (M5 allowlist) | `        self.allowed_mime_types = allowed_mime_types or [` | `telegram/crew/payload.py:36` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY (M5 document path, insert after) | `    def _find_audio_attachment(self, activity: Activity) -> Optional[Attachment]:` | `msteams/wrapper.py:822` | 1 |
| `packages/ai-parrot/tests/test_jira_comment_attachments.py` | MODIFY (M3 rewrite to handles) | `async def test_add_comment_with_valid_attachments(toolkit, tmp_path):` | `tests/test_jira_comment_attachments.py:51` | 1 |
| `packages/ai-parrot/tests/test_jiratoolkit_permissions.py` | MODIFY (M3 new signature) | `    def test_jira_add_attachment_requires_write(self, toolkit):` | `tests/test_jiratoolkit_permissions.py:165` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first: every store operation is `async def`; blocking filesystem and
  `jira` client calls go through `asyncio.to_thread`.
- `aiohttp` only — `requests`/`httpx` are banned (`ruff` TID251 enforces it).
  This feature adds **no** direct HTTP call of its own to Jira (see §1 Non-Goals).
- Pydantic v2 for `SessionFileRecord`, `AttachmentResult` and both report models.
- `self.logger` for all logging; an `outside_sandbox` refusal logs at WARNING as
  a security event, with the session id and the offending handle, never a path.
- Blob and manifest are written via temp file + atomic rename, so a crash mid-write
  never leaves a resolvable handle pointing at a truncated file.
- Tools carry Google-style docstrings — they are the LLM-facing description, and
  `sf_list_session_files` is how the model discovers handles at all.

### Known Risks / Gotchas

- **Multi-worker and restart.** The server runs under gunicorn; upload and
  attachment can land on different workers. The on-disk manifest is what makes a
  handle resolvable across both. If `OUTPUT_DIR` is ever worker-local or on
  ephemeral storage, handles break — deployment must put it on shared, persistent
  storage. Covered by `test_store_survives_restart`.
- **`_resolve_output_path` is not a boundary.** The single most likely
  implementation mistake is reusing it (`filemanager.py:887`) for containment. It
  returns absolute paths unchanged. Four tests exist specifically to catch this.
- **Concurrency.** Toolkits are reusable instances. Never store the session id,
  the root or a handle map on the toolkit — resolve per call from
  `current_context()`. `test_concurrent_sessions_do_not_cross_resolve` guards it.
- **Partial commit on comments.** Jira has no attachment rollback. Handles are
  pre-flighted before the comment is created, which removes the common case, but
  a genuine upload failure after creation still leaves a comment. That is why
  `comment_ok` and the attachment results are separate fields rather than one
  boolean.
- **Error text reaching the model.** `detail` is bounded to 500 characters and
  newline-collapsed. A raw Jira error body can be a large HTML page and may carry
  operational detail; `error_code` is the stable thing to branch on.
- **Disk growth.** Files persist until deleted by hand, by decision. `usage_bytes`
  measures a session and crossing `SESSION_FILES_WARN_BYTES` logs a WARNING; the
  cleanup procedure is documented in `docs/`. Nothing rejects an upload on an
  aggregate quota (§8 Q4) — so an unattended deployment *can* fill its disk, and
  the runbook is the only mitigation. Stated here so the trade-off is explicit.
- **The admin UI stays blocked.** After this feature a docx can be uploaded over
  the API and the chat channels, but the admin UI's data modal still refuses it in
  the browser (§8 Q5, `issue:04dcfd611ebc`). Anyone verifying the fix through that
  modal will conclude it did not work.
- **Session id trust.** Scoping by `session_id` alone means isolation is only as
  good as session-id entropy and reuse policy. Accepted; recorded here so a later
  multi-tenant review can find it.
- **FEAT-637 collides on both edited Jira methods.** Its spec redefines
  `jira_add_comment` while *keeping* `attachments: List[str]`. It merges first
  (§8 Q1); this feature then replaces that parameter with `file_ids`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `jira` | `==3.10.5` (`packages/ai-parrot/pyproject.toml:388`), `>=3.10` (`packages/ai-parrot-tools/pyproject.toml:54`) | Existing Jira client — unchanged, still the upload path |
| — | — | **No new runtime dependency.** `mimetypes` (stdlib) records advisory MIME; `python-magic` is explicitly not adopted |

New configuration (no new package):

| Key | Default | Reason |
|---|---|---|
| `JIRA_MAX_ATTACHMENT_BYTES` | unset → **discovered from Jira** | Overrides the discovered limit when set. Unset, the limit comes from `JIRA.attachment_meta()["uploadLimit"]` (`jira/client.py:1110`), cached per client; a failed probe falls back to 10 MB and logs at WARNING. This is why the Cloud-vs-DC question is moot (§8 Q2) |
| `SESSION_FILES_DIR` | `OUTPUT_DIR / "sessions"` | Root of every session sandbox; must be shared, persistent storage |
| `SESSION_FILES_WARN_BYTES` | `500 * 1024 * 1024` | Per-session total above which a WARNING is logged. **Reporting only — never rejects an upload** (§8 Q4) |

---

## 8. Open Questions

- [x] Is this a feature or a hotfix, and on which base branch? — *Resolved in brainstorm*: `feature`, base `dev`.
- [x] Which origins must be supported? — *Resolved in brainstorm*: server path, chat upload, remote URL, agent-generated.
- [x] Does the chat-upload → handle bridge belong to this feature? — *Resolved in brainstorm*: yes, it is the core.
- [x] Security posture for paths and URLs? — *Resolved in brainstorm*: strict session sandbox; URLs imported by an explicit tool first, never fetched by the Jira tool.
- [x] How does the tool contract evolve? — *Resolved in brainstorm*: hard cut, one shared helper, all callers updated in-feature.
- [x] Failure semantics and pre-flight validation? — *Resolved in brainstorm*: best-effort with a per-file report; pre-validate size, type and emptiness.
- [x] What reference does the Jira tool accept? — *Resolved in brainstorm*: an opaque session `file_id`, never a path.
- [x] Lifecycle of session files? — *Resolved in brainstorm*: persistent, manual cleanup.
- [x] Real `Content-Type` per file? — *Resolved 2026-10-07*: no. Keep `jira.JIRA.add_attachment` and accept `application/octet-stream`; MIME stays advisory manifest metadata (§1 Non-Goals, §9 S12).
- [x] Scoping of the session root? — *Resolved 2026-10-07*: `session_id` alone (residual risk in §7).
- [x] Where does the store live? — *Resolved 2026-10-07*: hybrid — a thin `SessionFileStore` owns the sandbox and handles; `FileManagerToolkit` is reused as remote transport and is not modified. This refines the brainstorm's "reuse FileManagerToolkit" after S2/S3/S4 showed it cannot be the store on its own.
- [x] Sequencing against FEAT-603 / FEAT-608 on `filemanager.py`? — *Resolved by research*: no conflict; FEAT-603 is 21/21 done (2026-09-25), FEAT-608 is 14/14 done (2026-10-05, PR #1596). This feature does not modify `filemanager.py` anyway.
- [x] **Q1** — Sequencing against FEAT-637 — *Resolved 2026-10-08, and now **satisfied***: FEAT-637 merged on 2026-10-07 (TASK-4113..4117 all `done`, `completed_at` 22:59). The §6 `jiratoolkit.py` anchors were re-verified against `1f74e23c7` on 2026-10-08 — all four drifted and were corrected in rev 0.3. M3 is unblocked.
  *(History: the gate was set while FEAT-637 was still unstarted; M1/M2/M4/M5 were decomposed first as TASK-4128..4136, M3 in a second pass.)*
- [x] **Q2** — Attachment size limit — *Resolved 2026-10-08*: **discover it from Jira, with a configuration override**. `jira.JIRA.attachment_meta()` (`jira/client.py:1110`) returns `{"enabled", "uploadLimit"}` for the live deployment, so neither Cloud-vs-DC nor the exact limit has to be known in advance. `JIRA_MAX_ATTACHMENT_BYTES` overrides it when set; a conservative fallback applies when the probe fails. The deployment question is therefore moot and is NOT reopened.
- [x] **Q3** — Consumers of the upload response — *Resolved 2026-10-08 by audit*: **zero**. `added_files` is read by no `.py`, `.ts`, `.svelte` or `.js` file in the repo — it has one producer (`handlers/agent.py:1287-1289`) and no consumer. The admin UI *does* call the endpoint (`uploadAgentData` → PUT `/api/v1/agents/chat/{agent}`, `ui/src/lib/api/agent.ts:153`) but discards the body (`DataManagementModal.svelte:122`), so the hard cut breaks nothing. Scope decision: **backend only in this feature**; the UI's own gate is deferred — see Q5.
- [x] **Q4** — Aggregate session quota — *Resolved 2026-10-08*: **report only**. `SessionFileStore.usage_bytes()` plus a WARNING once a configured threshold is crossed, and a documented cleanup procedure. No upload is ever rejected for an aggregate quota — that would add a failure mode the end user cannot clear, and it would contradict the locked "persistent, manual cleanup" decision.
- [ ] **Q5** *(new, deferred — tracked as `issue:04dcfd611ebc`)* — The admin UI blocks `.docx`/`.pdf` **client-side** at the file picker (`DataManagementModal.svelte:112`: *"Only Excel files (.xlsx, .xls) are allowed."*) and shows a hardcoded "Uploaded" instead of the server's answer. Until that is fixed, the admin UI remains a fourth silent gate on this very use case. Out of scope here by decision; a separate feature owns it. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted brainstorm.
> Model: `gpt-5.6-luna` (codex-cli 0.160.0, `reasoning_effort=high`) · Status: completed
> · Transcript: `sdd/state/FEAT-639/design_research/`
> All 13 cited paths passed repository containment and `test -e`. Claims S1, S3 and
> S5 were spot-checked against the source and confirmed verbatim before adoption.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make file resolution request-scoped, not mutable toolkit state (architecture) | CONFIRM | Verified: `RequestContext` + `_current_ctx` ContextVar exist (`utils/helpers.py:53`, bound by `AbstractBot.session()`). Toolkits are reusable, so per-request mutation would race. | §2 Overview (3), §3 M2, §7 |
| S2 | Persist the handle manifest; define worker-storage requirements (risk) | CONFIRM | Gunicorn multi-worker: an in-memory map survives neither restart nor a cross-worker request, contradicting "files persist". | §2 Overview (1), §3 M1, §7 |
| S3 | Do not reuse the current path resolver as the security boundary (risk) | CONFIRM | Verified: `_resolve_output_path` (`filemanager.py:887`) returns any absolute path unchanged — lexical, no canonicalization, no symlink handling. | §2 Overview (2), §3 M1, §6 |
| S4 | Add explicit staging APIs for remote and generated files (architecture) | CONFIRM | `FileManagerToolkit` binds one backend at construction; no "remote source → session handle" operation exists. | §3 M2 |
| S5 | Persist attachments before the query-handling branch (architecture) | CONFIRM | Verified: `handlers/agent.py:1821` — `if not query:`. A file-plus-prompt request never reaches ingestion. Second silent-drop path, previously unknown. | §1, §3 M4, §5 AC2 |
| S6 | Define the Jira size limit as deployment configuration (api) | CONFIRM | No size constant exists in the repo; Cloud and DC differ and the deployment is unresolved, so a hard-coded 10 MB would be a guess. | §7 config, §5 AC9, §8 Q2 |
| S7 | Freeze one typed result envelope and attachment cardinality (api) | CONFIRM | The two tools return different shapes today; "same shape" was underspecified for the singular tool. | §2 Data Models, §5 AC4 |
| S8 | Specify partial-commit semantics for comments (risk) | CONFIRM | Verified: the comment is created at `jiratoolkit.py:2049-2052` before any upload. Pre-flight removes the common case but not atomicity. | §3 M3, §5 AC11, §7 |
| S9 | Expand tests beyond path-based Jira mocks (testing) | CONFIRM | All six existing tests use local paths; none would fail under the new contract. | §4 |
| S10 | Bound and sanitize Jira error details returned to the model (risk) | CONFIRM | Overrides the brainstorm's "body surfaced verbatim": the string enters the model's context and can be a large HTML page. | §2 Data Models, §5 AC10, §7 |
| S11 | Add aggregate session quotas and an operator cleanup contract (risk) | ESCALATE | The runbook half is folded into §7 regardless; whether a quota *rejects* uploads conflicts with the locked manual-cleanup decision and is the user's call. | §7 + §8 Q4 |
| S12 | Resolve the MIME decision; remove contradictory acceptance criteria (alternative) | CONFIRM | Correct — the brief still carried multipart/`aiohttp`/real-MIME language after the constraint was reversed. The spec now states exactly one behavior and makes it observable. | §1 Non-Goals, §5 AC15 |

Summary: **11** confirmed · **0** rejected · **1** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for this spec; the `sdd-coder` engine gives
  each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (imports `SessionFileStore`, `SessionFileRecord`)
  - M3 → M1 (calls `SessionFileStore.resolve()`)
  - M4 → M1 (calls `SessionFileStore.put_bytes()`)
  - M5 → M1, M4 (routes channel uploads through the same ingestion)
  - M2, M3 and M4 have no edges between them and are expected to run concurrently
    once M1 lands.
- **Shared files**: none. Each module owns its files exclusively —
  M1 and M2 create new modules, M3 owns `jiratoolkit.py` + its two test modules,
  M4 owns `bots/agent.py` + `handlers/agent.py`, M5 owns the two integration files.
  `filemanager.py` is used but **not modified** by any module, which is what keeps
  the graph free of serialization.
- **Exclusive resources**: none — no module mutates shared state outside its own
  files (no lockfile, migration or extension rebuild).
- **Cross-feature dependencies**:
  - **FEAT-637 `jiratoolkit-template-support` MUST be merged before this feature
    starts at all** (§8 Q1) — the block is on the whole feature, not only on M3.
    It redefines `jira_add_comment` in the same file while keeping
    `attachments: List[str]`; M3 then replaces that parameter with `file_ids`.
    At decision time FEAT-637 had 5 tasks (`TASK-4113..4117`) all `pending` and no
    worktree, so **`/sdd-task` for FEAT-639 must not run until FEAT-637 is merged**,
    and every `jiratoolkit.py` anchor in §6 is re-verified at that point.
    (M1, M2, M4 and M5 touch no file FEAT-637 touches and could technically have
    proceeded in parallel; serializing them is a deliberate conflict-avoidance
    choice, recorded so the cost is visible.)
  - FEAT-603 and FEAT-608 are both complete and merged — no constraint.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-07 | Jesus | Initial draft from the accepted brainstorm, with codex design research folded in (11 confirmed, 1 escalated) |
| 0.2 | 2026-10-08 | Jesus | §8 Q1–Q4 resolved and routed into the body: FEAT-637 blocks the whole feature; size limit discovered via `attachment_meta()` with config override; upload response has zero consumers (audited) and the admin UI gate is deferred to `issue:04dcfd611ebc` as new Q5; session quota is reporting-only |
| 0.3 | 2026-10-08 | Jesus | FEAT-637 merged — §8 Q1 satisfied; the four `jiratoolkit.py` Edit Sites anchors re-verified and corrected against `1f74e23c7` (361→389, 455→507, 1748→2169, 2027→2530); M3's skeleton rebased onto FEAT-637's actual `jira_add_comment` signature; AC17's caller surface measured |
