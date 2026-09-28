<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
Original request (verbatim): google-drive-interface -- use the FEAT-603 feat-FEAT-603-sharepoint-filemanager
as example for a Google Drive File Manager interface and integration with toolkit

The request is to give Google Drive the same treatment FEAT-603 gave SharePoint and
OneDrive: a parrot-native implementation of navigator's `FileManagerInterface`
(`GoogleDriveFileManager`, in `parrot/interfaces/file/gdrive.py`) that composes the
existing `GoogleClient` (`parrot/interfaces/google.py`) for service-account / OAuth-user
/ cached authentication and uses aiogoogle's Drive v3 discovery for transport, plus the
same registration seams — lazy shim exports, `FileManagerFactory._PARROT_NATIVE["gdrive"]`,
the `ManagerType` literal and `_DRIVE_RELATIVE_BACKENDS` in `parrot/tools/filemanager.py`
— so `FileManagerToolkit(manager_type="gdrive")` works out of the box, with an optional
net-new `GoogleDriveToolkit` under `parrot_tools.google`. Nothing Drive-related exists in
the repo today, and FEAT-603's `GraphDriveFileManager` is Microsoft-Graph-specific, so the
Drive manager is a **sibling** class that reuses only the backend-neutral `batch.py`
models and mirrors the Graph extension surface (`list_entries`, server-side `find_files`,
`upload_file_from_bytes`, `create_sharing_link`, `upload_files`/`download_files`,
`setup()`). The main design work is not the transport but (a) mapping the interface's
path model onto Drive's id-addressed, duplicate-name-tolerant store and (b) sequencing:
FEAT-603 is not merged into `dev` yet, and every edit site this feature touches only
exists on its branch. Recommendation: resolve the four open questions, then `/sdd-spec`,
scheduled after FEAT-603 lands.

---

### Constraints and goals
- **FEAT-603 is not on `dev`.** `git log` on `parrot/interfaces/file/` over 60 days is
  empty; `graph.py`, `batch.py`, `_PARROT_NATIVE` and the widened `ManagerType` exist only on
  `feat-FEAT-603-sharepoint-filemanager` (HEAD `e11822c64`, merge-base `8b5c42b3a` vs
  `origin/dev` `bdaf25b78`, 4 files uncommitted — review fixes in flight).
  *Implication*: FEAT-608 is sequenced **after** FEAT-603 merges; the spec's §6 anchors
  must be re-verified against `dev` at that point. *Evidence*: F015, F011

- **`GraphDriveFileManager` is not a reusable base.** Its request builders,
  `@odata.nextLink` pagination, `createLink` and Graph host allow-list are all
  Microsoft-specific. *Implication*: `GoogleDriveFileManager(FileManagerInterface)` is a
  sibling that re-implements the same extension surface; only `batch.py` is shared.
  *Evidence*: F007, F009

- **`DriveEntry` / `GraphFileManagerError` live in `graph.py`, which imports msgraph.**
  *Implication*: relocate `DriveEntry` to a backend-neutral module (with `graph.py`
  re-exporting it) or define a Drive-specific entry model; `gdrive.py` must never import
  `graph.py`. *Evidence*: F007, F009

- **`parrot.interfaces.google` is heavy at import time** (selenium, webdriver_manager,
  playwright, redis) and `GoogleClient.__init__` eagerly builds an `aioredis` client.
  *Implication*: `gdrive.py` is a lazy entry in both shims and constructs the client only
  in `connect()`; extend `test_no_cloud_sdk_leak_on_import` for `aiogoogle` / `selenium` /
  `redis`. *Evidence*: F002, F010

- **`execute_api_call` re-discovers the API on every call.** *Implication*: the manager
  holds one `Aiogoogle` session + discovered `drive` v3 API for its lifetime (a
  `DriveClient` wrapper in the `CalendarClient` mould), otherwise every listing page,
  upload chunk and batch item pays discovery. *Evidence*: F002

- **Three Google auth modes already have a branch table** in
  `GoogleBaseTool._get_client` (`service_account` → `initialize()`; `user` →
  `interactive_login()` + `initialize()`; `cached` → `initialize()` with fallback to
  interactive login). *Implication*: `connect()` reproduces it (one credential load per
  manager) and `adopt_client()` accepts an already-initialised `GoogleClient` from the tool
  base — the AC3 analogue. *Evidence*: F003

- **Path-addressed contract over an id-addressed store.** `FileManagerInterface` takes
  paths; Drive addresses items by id and allows same-name siblings. *Implication*: a
  segment-walk path resolver (`files.list` with `'<parent>' in parents and name = …`)
  with a per-manager cache, plus an explicit upload/rename conflict policy.
  *Evidence*: F004, F002 (Drive model is external API knowledge — see C12)

- **aiogoogle 5.19 media support** covers `upload_file` (path), `pipe_from` (async
  iterable), `download_file`, `pipe_to`, chunked through aiofiles, multipart
  metadata+media; the `resumable` branch of `_build_upload_media` is only partially
  wired. *Implication*: small uploads and streaming downloads are free; large-file
  resumable sessions need a spec-time spike and possibly a direct aiohttp path with
  FEAT-603's URL-validation discipline (AC21). *Evidence*: F013

- **Toolkit ops are already generic.** `_OP_TO_METHOD` carries `find`, `batch_upload`,
  `batch_download`; backends without `upload_files`/`download_files` get the single-op
  fallback; `_DRIVE_RELATIVE_BACKENDS` gates the `default_output_dir` join.
  *Implication*: no toolkit operation changes — only the six registration edit sites.
  *Evidence*: F011, F009

- **Nothing to refactor on the tool side.** No Drive tool/loader exists; the existing
  Google tools bypass `GoogleClient` (`googleapiclient.discovery.build`); only
  `GoogleCalendarToolkit` and `LyriaToolkit` are toolkits. *Implication*: no M7/M8
  analogue; a `GoogleDriveToolkit` is net-new. *Evidence*: F006, F014

- **Packaging.** `aiogoogle==5.17.0` is an exact pin inside the `agents` bundles while
  `5.19.0` is installed; no core extra covers Google Workspace. *Implication*: new
  `gdrive` extra (`aiogoogle>=5.17,<6`, `aiofiles`) folded into `all`, mirroring
  `msgraph`. *Evidence*: F012

- **TID251** forbids `httpx`/`requests`; aiogoogle's transport is aiohttp, so it is
  admissible. *Evidence*: F013, F016

### Recommended option / probable scope
### What's New

- **`packages/ai-parrot/src/parrot/interfaces/file/gdrive.py`** —
  `GoogleDriveFileManager(FileManagerInterface)` + `GoogleDriveFileManagerError`.
  Locator: root folder (id or path) and optional shared-drive id (U1); auth kwargs
  `credentials` / `auth_mode` / `scopes` / `user_creds_cache_file`; `manager_name =
  "gdrivefile"`; `prefix` semantics as S3/GCS; the nine interface methods, the four
  folder/rename hooks, and the FEAT-603 extension surface: `list_entries`, server-side
  `find_files` (`q=` on `name contains` / `mimeType`), `upload_file_from_bytes`,
  `create_sharing_link` (`permissions.create` + `webViewLink`, U3), `upload_files` /
  `download_files` returning `BatchItemResult`, `setup()` / `handle_file` with the 413
  guard. *Evidence*: F004, F007, F008, F009
- **`DriveClient` wrapper** — one `Aiogoogle` session + discovered `drive` v3 API per
  manager exposing `list` / `get` / `create` / `update` / `copy` / `delete` /
  `permissions.create` / `export` with media kwargs; promoted from
  `GoogleClient.get_drive_client()` as FEAT-453 did for Calendar (U5, default) or
  private to `gdrive.py`. *Evidence*: F002
- **`packages/ai-parrot-tools/src/parrot_tools/google/drive.py`** —
  `GoogleDriveToolkit(AbstractToolkit)` delegating to the manager (list / search /
  download / upload / share, optionally Workspace `export`), exported from
  `parrot_tools.google` (U4). *Evidence*: F014, F003
- **Tests** — `packages/ai-parrot/tests/interfaces/_gdrive_fakes.py` (fake `Aiogoogle`
  + drive resource with scripted pages, errors and media), `test_gdrive_filemanager.py`,
  `test_gdrive_filemanager_live.py` (`@pytest.mark.live`, env-gated),
  `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py`. *Evidence*: F014, F016
- **Docs** — `docs/interfaces/gdrive-filemanager.md`, `docs/integrations/google-oauth2.md`
  (scopes, SA vs OAuth, shared-drive permissions). *Evidence*: F014
- **Packaging** — `gdrive` extra in `packages/ai-parrot/pyproject.toml`, added to `all`.
  *Evidence*: F012

### What Changes

- **`parrot/interfaces/file/__init__.py`::`_LAZY_MANAGERS` / `__all__`** — add
  `GoogleDriveFileManager → parrot.interfaces.file.gdrive`. *Evidence*: F010
- **`parrot_tools/file/__init__.py`::`__getattr__` / `__all__`** — widen the lazy branch.
  *Evidence*: F010
- **`parrot/tools/filemanager.py`** — `ManagerType` gains `"gdrive"`;
  `FileManagerFactory._PARROT_NATIVE["gdrive"] = ("parrot.interfaces.file.gdrive",
  "GoogleDriveFileManager")`; both `_DRIVE_RELATIVE_BACKENDS` sets gain `"gdrive"`;
  docstrings list it. *Evidence*: F011
- **`parrot/interfaces/google.py`::`GoogleClient.get_drive_client`** — (U5, default yes)
  return a live `DriveClient` instead of the config dict; no callers exist. *Evidence*:
  F002, F006
- **`parrot/interfaces/file/graph.py`::`DriveEntry`** — (design choice) relocate to a
  backend-neutral module and re-export; behaviour unchanged. *Evidence*: F007
- **`parrot_tools/google/__init__.py`::`__all__`** — export `GoogleDriveToolkit`.
  *Evidence*: F014

### What's Untouched (Non-Goals)

- `navigator.utils.file` (`GCSFileManager`, `S3FileManager`, `FileServingExtension`) —
  upstream, unchanged.
- `GraphDriveFileManager` behaviour, `SharePointFileManager`, `OneDriveFileManager`, all
  FEAT-603 O365 tools and Delta tools.
- `GoogleClient` auth paths (`interactive_login`, Redis/file cache), `GoogleBaseTool`,
  the existing Search / Places / Routes / Calendar / Lyria tools.
- `FileManagerToolkit` operations and `_OP_TO_METHOD`.
- `parrot_loaders` — no Drive **loader** in v1 (a RAG loader over the manager is a
  natural follow-up).
- Google Cloud Storage — already covered by `GCSFileManager` (`manager_type="gcs"`).

### Patterns to Follow

- Thin concrete manager: `manager_name` + `client_class` + `__init__` + `_build_client` +
  `_resolve_drive_id`; AC2 analogue asserts no other overrides. *Evidence*: F008
- Lazy shim registration + `test_no_cloud_sdk_leak_on_import` extension (AC10 analogue
  for `aiogoogle` / `selenium` / `redis`). *Evidence*: F010
- `_PARROT_NATIVE` map + `ValueError` listing all keys (AC11 analogue: seven keys).
  *Evidence*: F011
- Batch engine contract (AC8): input-order `BatchItemResult`, never raise per item,
  bounded concurrency, retry 429/5xx honouring `Retry-After`, skip remainder on auth
  failure. *Evidence*: F009, F016
- Auth branch table copied from the tool base into `connect()`; `adopt_client()` for an
  already-authenticated client (AC3). *Evidence*: F003, F007
- Fake-client harness + env-gated live suite + signature-snapshot test (M0 / M10 / AC19).
  *Evidence*: F014, F016
- `manager_name` `"<backend>file"` and prefix normalisation as in GCS/S3. *Evidence*: F005

### Integration Risks

- **Sequencing on FEAT-603**: edit sites and shared models are not on `dev`; a worktree
  cut too early would conflict. Mitigation: gate `/sdd-task` on the FEAT-603 merge and
  re-verify §6 then. *Evidence*: F015
- **Path semantics over an id-addressed store with duplicate names**: ambiguous
  list/upload/rename. Mitigation: segment resolver with cache, deterministic first match,
  `conflict_behavior` replace | fail | rename (U2). *Evidence*: F004, F002
- **Heavy transitive imports** in `parrot.interfaces.google`. Mitigation: lazy shim entry
  + client built in `connect()` + leak test. *Evidence*: F002, F010
- **aiogoogle resumable uploads partially wired**: files above ~5 MB may fail or buffer.
  Mitigation: spec-time spike; fallback to a direct aiohttp resumable session with URL
  validation. *Evidence*: F013
- **Service-account ownership / storage-quota limits on My Drive**: uploads into a
  service account's own Drive may be rejected in real tenants. Mitigation: target shared
  drives, folders shared with the SA, or domain-wide delegation (`subject`) — U1.
  *Evidence*: — (external, C15)
- **aiogoogle exact pin drift** (`==5.17.0` vs installed `5.19.0`). Mitigation: the new
  extra uses `>=5.17,<6`; the `agents` bundles are left alone or relaxed in the same PR.
  *Evidence*: F012

---

Decisions already taken (resolved questions):
- [x] **U1 — Which Drive targets must v1 support?** — *Resolved* (2026-09-25):
  **My Drive + shared drives** — the principal's My Drive by default, plus an optional
  `shared_drive_id` (Drive `driveId` + `supportsAllDrives=True` /
  `includeItemsFromAllDrives=True` on every call). Domain-wide delegation (`subject=`)
  is **out of scope** for v1 (future constructor kwarg, no design impact).
  *Resolves claims*: C15 (mitigated: uploads can target a shared drive)

- [x] **U2 — How should paths map onto Drive's id-addressed model?** — *Resolved*
  (2026-09-25): **path-based, like S3/Graph** — a segment-walk resolver over `files.list`
  (`'<parent>' in parents and name = '<seg>' and trashed = false`) with a per-manager
  path→id cache, deterministic first match (newest `modifiedTime`, then `id`), and an
  upload `conflict_behavior` of `replace` (default) | `fail` | `rename`, mirroring
  FEAT-603. `FileManagerToolkit` semantics stay identical across backends.
  *Resolves claims*: C12

- [x] **U3 — What should `get_file_url()` return by default?** — *Resolved*
  (2026-09-25): **`webViewLink` with no permission change** — `get_file_url(path,
  expiry)` never widens access (`expiry` is accepted for signature parity and ignored
  with a debug log); explicit sharing goes through the extension
  `create_sharing_link(path, *, scope="user"|"domain"|"anyone", role="reader"|"writer",
  expiry, email_address=None)` which calls `permissions.create` and returns
  `webViewLink`. `expirationTime` is only applied for `user`/`group` permissions (Drive
  does not support it on `anyone`/`domain`).
  *Resolves claims*: — (policy decision)

- [x] **U4 — Which agent-facing surface is in scope?** — *Resolved* (2026-09-25):
  **`FileManagerToolkit` + `GoogleDriveToolkit`** — `manager_type="gdrive"` in
  `FileManagerToolkit` / `FileManagerTool` / `FileManagerFactory`, plus a net-new
  `GoogleDriveToolkit(AbstractToolkit)` under `parrot_tools.google` (list / search /
  download / upload / share) delegating to the manager, in the `GoogleCalendarToolkit`
  mould. Workspace `files.export` is **out of scope** for v1.
  *Resolves claims*: — (scope decision)

- [x] **U5 — Should `GoogleClient.get_drive_client()` be promoted to return a live
  `DriveClient`?** — *Resolved by default*: yes, promote — no callers exist (F006) and
  internal hard cuts need no shims. Override at spec time if disagreed.
  *Resolves claims*: C14

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/interfaces/google.py
packages/ai-parrot-tools/src/parrot_tools/google/base.py
.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py
.venv/lib/python3.12/site-packages/navigator/utils/file/gcs.py
packages/ai-parrot/src/parrot/interfaces/file/graph.py
packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py
packages/ai-parrot/src/parrot/interfaces/file/batch.py
packages/ai-parrot/src/parrot/interfaces/file/__init__.py
packages/ai-parrot-tools/src/parrot_tools/file/__init__.py
packages/ai-parrot/src/parrot/tools/filemanager.py
packages/ai-parrot/pyproject.toml
packages/ai-parrot/src/parrot/conf.py
.venv/lib/python3.12/site-packages/aiogoogle/resource.py
packages/ai-parrot-tools/src/parrot_tools/google/calendar.py
packages/ai-parrot-tools/src/parrot_tools/google/__init__.py
packages/ai-parrot/tests/interfaces/_graph_fakes.py
sdd/specs/sharepoint-filemanager.spec.md

### Questions still open in the exploration document
- [ ] **Resumable uploads above ~5 MB** — *Owner*: spec author
  *Blocks claims*: C8
  *Plausible answers*: a) aiogoogle's `MediaUpload(resumable=…)` branch works end to end
  → use it · b) it does not → direct aiohttp resumable session (`uploadType=resumable`,
  validated `Location` URL, no token in logs) as FEAT-603 did for Graph upload sessions.
  Decide with a spec-time spike, not a user question.

---

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
