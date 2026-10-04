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
AI-Parrot has a uniform storage contract — `FileManagerInterface` from
`navigator.utils.file` (navigator-api 4.0.0), implemented by
`LocalFileManager`, `TempFileManager`, `S3FileManager` and `GCSFileManager` —
that agents, `FileManagerToolkit`, report persistence and artifact storage all
program against. Microsoft SharePoint document libraries and OneDrive drives
are **not** behind that contract. Instead the repo carries two parallel,
non-conforming surfaces:

- `parrot/interfaces/sharepoint.py::SharepointClient` and
  `parrot/interfaces/onedrive.py::OneDriveClient` — Graph-SDK clients with
  flowtask-style, stateful method sets (`upload_files`, `file_search`,
  `download_found_files`, `file_lookup`) that configure the target via
  instance attributes (`client.directory`, `client.site`) rather than
  path arguments, and that share almost no method names with each other.
- `parrot_tools/o365/{sharepoint,onedrive}.py` tools that re-implement
  listing/searching/downloading **directly on the raw Graph client** because
  the clients above do not expose those operations in a reusable shape.

Consequences:

1. Nothing that speaks `FileManagerInterface` (the `file_manager` tool,
   `FileManagerToolkit`, `ReportPersistenceMixin`, artifact stores) can target
   SharePoint or OneDrive. Every consumer needs bespoke O365 code.
2. Bytes-in-memory uploads (agent-generated reports, charts, exports) have no
   path to SharePoint at all — `SharepointClient.upload_files` only takes
   local filenames.
3. The flowtask sibling of `SharepointClient` (which the user pointed at as
   the reference) has drifted ahead: it gained `drive: {type, user}` OneDrive
   targeting (`_ensure_drive_config`, `_resolve_user_drive`) that ai-parrot's
   copy lacks, while ai-parrot's `O365Client` gained `set_auth_mode`,
   `is_app_only`, `get_user_context` and an async `close()` that flowtask
   lacks. The two are diverging in both directions.
4. Batch upload/download, sharing-link generation and server-side search
   exist as fragments across the clients and tools but never as a single,
   documented, testable API.

**Who is affected**: agent authors (want `FileManagerToolkit(manager_type=
"sharepoint")`), pipeline/flowtask users (need a stable, mockable client),
and the O365 toolkit maintainers (currently duplicating drive-item logic in
every tool).

**Why now**: FEAT-539 just landed delta enumeration for both drives with a
robust retry/validation helper (`parrot_tools/o365/delta.py`), so the Graph
plumbing is mature; the missing piece is the uniform manager façade.

### Constraints and goals
- **Contract fidelity**: implement every abstract method of
  `FileManagerInterface` (`list_files`, `get_file_url`, `upload_file`,
  `download_file`, `copy_file`, `delete_file`, `exists`, `get_file_metadata`,
  `create_file`) with the exact signatures at
  `navigator/utils/file/abstract.py:53-155`, plus the optional folder/rename
  hooks (`create_folder`, `remove_folder`, `rename_folder`, `rename_file`,
  lines 170-212), the inherited `create_from_bytes`/`create_from_text`
  helpers and a server-side `find_files` override.
- **Home & reuse (decided)**: new modules under
  `packages/ai-parrot/src/parrot/interfaces/file/` that **compose** the
  existing `SharepointClient` / `OneDriveClient` (auth, site/drive
  resolution, upload sessions). No second Graph auth stack.
- **Shape (decided)**: two public classes, `SharePointFileManager` and
  `OneDriveFileManager`, over one shared abstract `GraphDriveFileManager`
  that owns drive-item operations. Paths are **drive-relative**, exactly
  like S3 `prefix + key`.
- **Auth (decided)**: app-only client credentials, delegated/OBO, and
  username/password (ROPC) — i.e. every mode `O365Client._create_credential`
  already supports. Credentials arrive as a `credentials` dict or fall back
  to the `SHAREPOINT_*` / `O365_*` values in `parrot/conf.py:598-617`.
- **OneDrive scope (decided)**: any user's drive via `users/{upn|id}/drive`
  under app-only auth, or `me/drive` under delegated auth. Port flowtask's
  `_resolve_user_drive` into `OneDriveClient`; do **not** port the
  `drive.type=onedrive` shim into `SharepointClient` (the class split makes
  it redundant).
- **URLs (decided)**: `get_file_url` returns a Graph `createLink` sharing
  link (organization scope by default, `expirationDateTime` derived from
  `expiry` when the tenant allows it).
- **Batch (decided)**: `upload_files` / `download_files` return per-item
  results and never raise mid-batch; a bounded semaphore (default 5) drives
  concurrency; Graph 429/503 `Retry-After` is honoured.
- **Registration (decided, all four)**: `parrot.interfaces.file` lazy
  re-exports; `FileManagerFactory` + `FileManagerTool`/`FileManagerToolkit`
  `manager_type` literals `sharepoint` / `onedrive`; refactor
  `SharePointToolkit`/`OneDriveToolkit` tools onto the managers; mirror
  S3's `setup(app, route)` HTTP file-serving extension.
- **Verification (decided)**: mocked unit tests in CI + an opt-in
  `@pytest.mark.live` suite gated on `SHAREPOINT_*`/`O365_*` env vars, run
  manually before `/sdd-done`.
- **Conflict semantics (assumed, user did not object)**: uploads default to
  `@microsoft.graph.conflictBehavior=replace` (S3 overwrite parity);
  `delete_file` is a Graph DELETE (recycle bin), not permanent deletion.
- **Conventions**: aiohttp only for raw HTTP (upload-session chunk PUTs
  already use `aiohttp.ClientSession` at `sharepoint.py:417`); the
  `import httpx` at `sharepoint.py:11` / `onedrive.py:10` is unused legacy
  and must not spread into new modules (ruff TID251 bans it). msgraph-sdk
  itself depends on httpx transitively via kiota — that is an accepted,
  pre-existing dependency (`ai-parrot[agents]` extra,
  `packages/ai-parrot/pyproject.toml:440-442`).
- **No blocking I/O** in async paths; Pydantic v2 models for batch results;
  Google docstrings; `self.logger`.
- **Backwards compatibility**: `SharepointClient`/`OneDriveClient` public
  methods stay (flowtask and the delta tools call them); additions only.

---

### Recommended option / probable scope
**Option B** is recommended because:

- It is the only option in which "two classes on a shared base" is a real
  design rather than a naming convention: Graph treats a SharePoint library
  and a OneDrive as the same `drive` resource, so a base that owns all
  drive-item operations and delegates *only* drive resolution to subclasses
  mirrors the API's own shape. Option A's base would be hollow because the
  two existing clients share almost no methods.
- It resolves the stateful-protocol problem (instance-attribute
  `directory`/`filename`) that makes Option A unsafe for the decided
  per-item concurrent batch semantics.
- It pays for the O365 toolkit refactor the user put in scope: the four
  List/Search/Download/Upload tools per drive already contain the drive-item
  code Option B centralises, so the refactor is a net deletion.
- The trade-off is more new code than a thin adapter and a temporary
  coexistence of two request styles (`SharepointClient.upload_files` stays
  for flowtask parity). That is acceptable: the clients' public surface is
  untouched, additions are confined to `OneDriveClient._resolve_user_drive`,
  and the base is the reusable asset every later Graph feature (group
  drives, shared-with-me) will build on.
- Option C's URL grammar is elegant but fights the decided ergonomics and
  the split configuration defaults; Option D was ruled out by the home
  decision.

---

### Recommended Option B
Introduce `parrot/interfaces/file/graph.py::GraphDriveFileManager(FileManagerInterface)`
— an abstract base whose only backend-specific hook is
`async _resolve_drive_id() -> str` (plus a `client` factory). The base
implements **all** `FileManagerInterface` methods once, directly against
`client.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(
"root:/<path>:")` builders (the same pattern `ListSharePointFilesTool` already
uses at `parrot_tools/o365/sharepoint.py:100-125`), reusing the clients only
for what they are good at:

- `O365Client` — credential/auth-mode handling (`_create_credential`,
  `set_auth_mode`, `is_app_only`, `acquire_token_on_behalf_of`, `user_auth`).
- `SharepointClient` — `verify_sharepoint_access`, `_resolve_site`
  (sub-site detection), `_resolve_drive(library)`, `_ensure_folder`,
  `_create_upload_session` + `_upload_large_file` (chunked, aiohttp).
- `OneDriveClient` — `_resolve_drive` (`me`) plus the newly ported
  `_resolve_user_drive(user)`; `_upload_large_file_content` for bytes.

`SharePointFileManager(site, library="Documents", prefix="", credentials=None,
auth_mode="direct", ...)` and `OneDriveFileManager(user="me", prefix="",
credentials=None, auth_mode=..., ...)` become ~60-line subclasses: constructor
+ `_resolve_drive_id` + `manager_name`. Extensions beyond the interface, on
the base: `upload_files`, `download_files` (batch, per-item results),
`upload_file_from_bytes` (S3 parity), `find_files` (Graph `search(q)` with
local pattern fallback, lifted from `SharepointClient.file_search`'s
`_pattern_is_api_safe` logic), `get_file_url(..., scope=, link_type=)`,
`create_folder`/`remove_folder`/`rename_*`, and `setup(app, route)` via
`navigator.utils.file.web.FileServingExtension`.

✅ **Pros:**
- One implementation of every drive-item operation; SharePoint vs OneDrive
  differ **only** in how the drive id is found — which is exactly how Graph
  models them (`/drives/{id}/...` is identical for both).
- Stateless, path-argument API — safe for concurrent batches, satisfies
  `BinaryIO` destinations, testable with a fake request-builder tree.
- The O365 toolkit tools (`List*`, `Search*`, `Download*`, `Upload*` for both
  drives) collapse to thin calls on the managers, deleting their duplicated
  Graph walks; `Delta*` tools keep their own `DriveDeltaHelper` path.
- Ports flowtask's `_resolve_user_drive` **once** into `OneDriveClient`,
  closing the drift the user flagged.

❌ **Cons:**
- More new code than A (the base is the bulk of the feature).
- Two Graph request styles coexist for a while (the clients' own
  `upload_files`/`file_search` remain for flowtask compatibility).
- `copy_file` on Graph is asynchronous (HTTP 202 + monitor URL) — the base
  must poll with aiohttp; not a one-liner.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `msgraph-sdk` 1.63.0 | drive-item request builders, `createLink`, `createUploadSession`, `copy`, `search` | already a dependency; `CreateLinkPostRequestBody` verified importable |
| `microsoft-kiota-http` 1.13.0 | ships `RetryHandler` middleware (429/503 with `Retry-After`) in the default Graph pipeline | verified `kiota_http.middleware.retry_handler.RetryHandler` |
| `aiohttp` 3.14.3 | resumable-upload chunk PUTs, `copy` monitor polling, `@microsoft.graph.downloadUrl` streaming | codebase standard |
| `aiofiles` | chunked local reads/writes | already imported by both clients |
| `navigator-api` 4.0.0 | `FileManagerInterface`, `FileMetadata`, `FileServingExtension` | pinned `>=3.2.2` in `ai-parrot/pyproject.toml:124` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/interfaces/o365.py:115-978` `O365Client` — all auth modes, `graph_client` property, `get_user_context`.
- `packages/ai-parrot/src/parrot/interfaces/sharepoint.py:96-357` site/drive/folder resolution; `:390-470` upload session + chunked upload; `:867-873` `_pattern_is_api_safe`.
- `packages/ai-parrot/src/parrot/interfaces/onedrive.py:88-165` drive/folder resolution; `:677-735` `_upload_large_file_content` (bytes → session).
- `/home/jesuslara/proyectos/flowtask/flowtask/interfaces/Sharepoint.py:145-188` `_resolve_user_drive` — to port into `OneDriveClient`.
- `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py:72-185` listing walk (`root:/{path}:` + `.children.get()`), to be moved into the base.
- `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py:487-539` `_status_code_of` / `_retry_after_seconds` — reuse for batch throttling.
- `.venv/.../navigator/utils/file/s3.py:571` `upload_file_from_bytes`, `:613` `setup`, `:635` `handle_file` — API shape to mirror.
- `.venv/.../navigator/utils/file/web.py:28` `FileServingExtension(manager, route, manager_name)`.

---

### Verified code anchors (paths only — open them yourself)
/home/jesuslara/proyectos/flowtask/flowtask/interfaces/Sharepoint.py
.venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py
.venv/lib/python3.12/site-packages/navigator/utils/file/s3.py
.venv/lib/python3.12/site-packages/navigator/utils/file/web.py
.venv/lib/python3.12/site-packages/navigator/utils/file/factory.py
packages/ai-parrot/src/parrot/interfaces/file/__init__.py
packages/ai-parrot/src/parrot/tools/filemanager.py
packages/ai-parrot/src/parrot/interfaces/o365.py
packages/ai-parrot/src/parrot/interfaces/sharepoint.py
packages/ai-parrot/src/parrot/interfaces/onedrive.py
packages/ai-parrot-tools/src/parrot_tools/o365/base.py
packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py
packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py
packages/ai-parrot-tools/src/parrot_tools/o365/delta.py
packages/ai-parrot/pyproject.toml
packages/ai-parrot-tools/pyproject.toml
packages/ai-parrot/tests/interfaces/test_file_shim.py
packages/ai-parrot-tools/tests/test_o365_delta_tools.py
tests/tools/test_filemanager_toolkit.py
tests/tools/test_office365_toolkit.py
packages/ai-parrot-tools/tests/unit/test_o365_permission_context_bridge.py
packages/ai-parrot-tools/tests/contracts/test_ingest_delta.py

### Questions still open in the exploration document
- [ ] Upload conflict default: `replace` (S3 parity) vs `fail`/`rename`, and should it be a constructor kwarg (`conflict_behavior=`)? — *Owner: Jesus* (assumed `replace`, kwarg exposed).
- [ ] Sharing-link defaults: `type="view"` vs `"edit"`, and should `expiry=0` mean "no expiration"? — *Owner: Jesus* (assumed `view`, `expiry<=0` → no expiration).
- [ ] Batch concurrency default (5) and per-item retry budget (3) — confirm against the tenant's throttling profile. — *Owner: Jesus*.
- [ ] Should `manager_name` values be `"sharepointfile"` / `"onedrivefile"` (S3 convention `"s3file"`) or `"sharepoint"` / `"onedrive"`? — *Owner: Jesus*.
- [ ] Should `FileManagerToolArgs.operation` gain `find`/`batch_upload`/`batch_download` so agents can reach the extension methods, or is v1 limited to the nine interface ops? — *Owner: Jesus* (assumed: nine ops only; batch/find via direct manager use).
- [ ] Add a dedicated `ai-parrot[msgraph]` extra (msgraph-sdk + azure-identity + kiota auth) so `FileManagerFactory.create("sharepoint")` has a documented install path outside `[agents]`? — *Owner: Jesus*.
- [ ] Live-gate tenant: which site/library and which user's OneDrive are safe to write to, and under which env var names (`SHAREPOINT_*` exist in conf; a `PARROT_LIVE_SHAREPOINT_SITE`-style test knob does not)? — *Owner: Jesus*.
- [ ] After this feature, should flowtask's `SharepointClient` drop its `drive.type=onedrive` shim in favour of `OneDriveFileManager` (separate repo follow-up)? — *Owner: Jesus*.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
