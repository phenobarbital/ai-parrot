---
id: FEAT-608
title: Google Drive FileManager — FileManagerInterface over Drive v3, registered as manager_type "gdrive" and exposed through FileManagerToolkit + a Google Drive toolkit
slug: google-drive-interface
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-25
  summary_oneline: Google Drive FileManager (FileManagerInterface over Drive v3) modeled on FEAT-603 SharePoint/OneDrive managers, wired into FileManagerToolkit
overall_confidence: medium
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-tools]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [filemanager, google-drive, google-workspace, aiogoogle, storage, toolkit]
research_state: sdd/state/FEAT-608/
created: 2026-09-25
updated: 2026-09-25
---

# FEAT-608 — Google Drive FileManager (`GoogleDriveFileManager`)

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-608/`](../state/FEAT-608/)
> **ID note**: `FEAT-608` is **provisional** (next free id in `sdd/tasks/.id_ledger.json`
> at research time). `/sdd-spec` reserves the definitive id through `reserve_ids.py`;
> rename `sdd/state/FEAT-608/` then if the ledger hands out a different number.

---

## 0. Origin

The original request, preserved verbatim. The full source is at
`sdd/state/FEAT-608/source.md`.

> google-drive-interface -- use the FEAT-603 feat-FEAT-603-sharepoint-filemanager
> as example for a Google Drive File Manager interface and integration with toolkit

**Initial signals** (extracted, not interpreted):
- Verbs: "use … as example" → additive, pattern-following feature (enrichment)
- Named entities: "Google Drive", "File Manager interface", "toolkit", "FEAT-603",
  worktree `feat-FEAT-603-sharepoint-filemanager`
- Components / labels: none (inline source)
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

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

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted
> at `sdd/state/FEAT-608/findings/`. Each cites the finding ID(s) that justify
> its inclusion. Paths under `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/`
> are FEAT-603 code that is **not on `dev` yet** (F015); their `dev` location after
> the merge is the same path minus the worktree prefix.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/interfaces/google.py` | `GoogleClient` | 226-290, 650-772, 827-836, 1051-1075 | existing Google auth + aiogoogle transport (SA / user creds, Redis+file session cache, `execute_api_call`, `interactive_login`); `get_drive_client()` returns only a config dict | F001, F002 |
| 2 | `packages/ai-parrot/src/parrot/interfaces/google.py` | `CalendarClient` | 160-224 | precedent for promoting a `get_*_client()` dict into a live wrapper (FEAT-453) | F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/google/base.py` | `GoogleBaseTool._get_client` | 82-135 | auth-mode branch table (`service_account` / `user` / `cached`) to reproduce in the manager's `connect()` | F003 |
| 4 | `.venv/…/navigator/utils/file/abstract.py` | `FileManagerInterface` | 36-296 | the contract: 9 abstract coroutines, 4 optional folder/rename hooks, `find_files` default | F004 |
| 5 | `.venv/…/navigator/utils/file/gcs.py` | `GCSFileManager` | 45-149, 507-543 | upstream Google-credential manager; fixes `manager_name` `"<x>file"`, `prefix`, `setup()`/`handle_file` conventions | F005 |
| 6 | `…/feat-FEAT-603-…/packages/ai-parrot/src/parrot/interfaces/file/graph.py` | `GraphDriveFileManager` | 93-155, 213-361, 517-1006 | reference surface to mirror (lifecycle, extensions, 413 serving guard); Graph-specific → Drive is a sibling | F007 |
| 7 | `…/feat-FEAT-603-…/packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py` | `SharePointFileManager` | 12-57 | thin concrete-manager pattern (`manager_name`, `client_class`, `__init__`, `_build_client`, `_resolve_drive_id`) | F008 |
| 8 | `…/feat-FEAT-603-…/packages/ai-parrot/src/parrot/interfaces/file/batch.py` | `BatchItemResult`, `BatchSummary` | 1-71 | backend-neutral batch models to reuse unchanged | F009 |
| 9 | `…/feat-FEAT-603-…/packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | `_LAZY_MANAGERS` | 37-43 | registration edit site #1 (lazy re-export) | F010 |
| 10 | `…/feat-FEAT-603-…/packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` | `__getattr__` | 21-27 | registration edit site #2 (parity shim) | F010 |
| 11 | `…/feat-FEAT-603-…/packages/ai-parrot/src/parrot/tools/filemanager.py` | `ManagerType`, `FileManagerFactory._PARROT_NATIVE`, `_DRIVE_RELATIVE_BACKENDS` (×2), `_OP_TO_METHOD` | 27-52, 259, 704-718, 862-881 | registration edit sites #3-#6; `find`/`batch_*` ops already generic | F011 |
| 12 | `packages/ai-parrot/pyproject.toml` | `[project.optional-dependencies]` | 396-425, 599-604, 882 | `aiogoogle==5.17.0` pinned inside `agents` bundles; `google` extra is GenAI-oriented; `msgraph` extra (worktree) is the precedent | F012 |
| 13 | `packages/ai-parrot/src/parrot/conf.py` | `GOOGLE_CREDENTIALS_FILE` | 430-435 | default credential file fallback | F012 |
| 14 | `.venv/…/aiogoogle/resource.py` | `Method.__call__` (`upload_file` / `pipe_from` / `download_file` / `pipe_to`) | 394-397, 563-663 | media transport for `files.create` / `files.update` / `files.get(alt=media)`; resumable branch partially wired | F013 |
| 15 | `packages/ai-parrot-tools/src/parrot_tools/google/calendar.py` | `GoogleCalendarToolkit` | 74 | toolkit precedent for a `GoogleDriveToolkit` | F014 |
| 16 | `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py` | `__all__` | 1-24 | export list to extend | F014 |
| 17 | `…/feat-FEAT-603-…/packages/ai-parrot/tests/interfaces/_graph_fakes.py` | `FakeGraphClient` | — | fake-client harness pattern → `_gdrive_fakes.py` | F014, F016 |
| 18 | `sdd/specs/sharepoint-filemanager.spec.md` | §3 modules, §5 AC1-AC24 | 374-389, 941-964 | spec shape and AC template to mirror | F016 |

### 2.2 Constraints Discovered

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

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `e11822c64` | 2026-09-25 | worktree `feat-FEAT-603-…` | fix(sharepoint-filemanager): FEAT-603 — narrow size-guard exception handling in graph.py | `interfaces/file/graph.py` |
| `8511be814` | 2026-09-25 | worktree `feat-FEAT-603-…` | sdd: complete TASK-3768 for sharepoint-filemanager | SDD state |
| `e74891c78` | ≤90 days | dev | style: apply black formatting (post sdd-worker) | `interfaces/google.py` |
| `a6aa9e4fd` | ≤90 days | dev | fix(lyria-toolkit): address code-review findings (FEAT-534) | `parrot_tools/google/lyria.py` |
| `0cd06246a` | ≤90 days | dev | feat(web-automation-infra): TASK-2393 — Google Calendar event tools + live calendar client | `interfaces/google.py`, `parrot_tools/google/calendar.py` |

`parrot/interfaces/file/` has **no commits on `dev` in 60 days** — everything
file-manager-related is on the FEAT-603 branch. `GoogleClient`'s auth code was not
touched by the recent commits. *Evidence*: F015

---

## 3. Probable Scope  *(mode = enrichment)*

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

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | No Google Drive manager, tool, loader or integration exists anywhere in the repo | F001, F006 | high | wiki query + repo-wide grep both return only the scope table in `google.py` |
| C2 | `GoogleClient` already provides SA and OAuth-user auth over aiogoogle with Redis/file session caching, but no Drive wrapper | F002 | high | page content read: `initialize` / `execute_api_call` / `interactive_login`; `get_drive_client` returns a dict |
| C3 | `GoogleBaseTool._get_client` is the auth-mode branch table to reproduce | F003 | high | direct read of the branch code |
| C4 | The contract is navigator's `FileManagerInterface` (9 abstract + 4 hooks + `find_files` default) | F004 | high | direct read of `abstract.py` (navigator-api 4.0.0) |
| C5 | `GraphDriveFileManager` cannot be the Drive base; Drive is a sibling reusing only `batch.py` | F007, F009 | high | graph.py surface is msgraph-specific; batch.py docstring is explicit |
| C6 | Registration = two shim entries + four edit sites in `filemanager.py` via `_PARROT_NATIVE` | F010, F011 | high | line-level grep of the worktree file |
| C7 | FEAT-603 is not merged into `dev`; its worktree is ahead and dirty | F015 | high | empty dev log, merge-base ≠ origin/dev, 4 modified files |
| C8 | aiogoogle 5.19 supports chunked media upload/download via kwargs; resumable is partial | F013 | medium | kwargs and streaming helpers confirmed; resumable branch not read end-to-end |
| C9 | Importing `parrot.interfaces.google` loads selenium/playwright/redis; manager must be lazy | F002 | high | import block visible in the page content |
| C10 | Toolkit `find`/batch ops are generic and need no change | F011, F009 | high | `_OP_TO_METHOD` already lists them; AC12 documents the fallback |
| C11 | No core extra covers Google Workspace; aiogoogle pin `==5.17.0` vs installed `5.19.0` | F012 | high | grep of both pyproject files + `importlib.metadata` |
| C12 | Drive is id-addressed with duplicate sibling names, so a resolver + conflict policy are required | F002, F004 | medium | interface is path-based (F004); Drive model is external API knowledge |
| C13 | FEAT-603's harness / live-suite / docs / AC structure transfers minus client-port and tool-refactor modules | F014, F016 | high | module table and AC list read; files listed in the worktree |
| C14 | `get_drive_client()` has no callers and can be promoted like `get_calendar_client()` | F002, F006 | high | `CalendarClient` precedent in the same file; no Drive consumers |
| C15 | Service accounts may be unable to own/upload files in their own My Drive under current quota rules | — | low | external platform behaviour; nothing in the repo confirms it |

Distribution: **12** high, **2** medium, **1** low.

> Overall confidence is **medium**, not high: scope depends on U1/U2 (constructor and
> path semantics) and the code this feature edits is on an unmerged branch (C7).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Should `GoogleClient.get_drive_client()` be promoted to return a live `DriveClient`
  (hard cut of the config-dict return, as FEAT-453 did for Calendar)?** — *Resolved by
  default*: yes, promote — no callers exist (F006) and internal hard cuts need no shims.
  Override at spec time if disagreed.
  *Resolves claims*: C14

### Unresolved (defer to spec / implementation)

- [ ] **U1 — Which Drive targets must v1 support?** — *Owner*: Jesus
  *Blocks claims*: C15
  *Plausible answers*: a) My Drive of the principal only (simplest; SA uploads may hit
  quota limits) · b) My Drive + shared drives via an optional `shared_drive_id`
  (**recommended**) · c) all three incl. domain-wide delegation (`subject=`)

- [ ] **U2 — How should paths map onto Drive's id-addressed model with duplicate names
  allowed?** — *Owner*: Jesus
  *Blocks claims*: C12
  *Plausible answers*: a) path-based like S3/Graph: segment resolver + cache, first match,
  upload `conflict_behavior` replace | fail | rename (**recommended**) · b) id-based only:
  keys are Drive file ids, root is a folder id · c) hybrid: paths by default, `id:<fileId>`
  accepted anywhere a path is

- [ ] **U3 — What should `get_file_url()` return by default on Drive?** — *Owner*: Jesus
  *Plausible answers*: a) `webViewLink` without touching permissions (only existing
  viewers can open it) · b) create a `domain` reader permission then `webViewLink`
  (organization-wide, mirrors FEAT-603's default) · c) create an `anyone` reader
  permission (public link — riskiest)

- [ ] **U4 — Which agent-facing surface is in scope?** — *Owner*: Jesus
  *Plausible answers*: a) only `FileManagerToolkit(manager_type="gdrive")` /
  `FileManagerTool` · b) also a `GoogleDriveToolkit` under `parrot_tools.google`
  (list/search/download/upload/share) like `GoogleCalendarToolkit` (**recommended**) ·
  c) b) plus Workspace export (Docs/Sheets/Slides → PDF/DOCX/XLSX via `files.export`)

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-608`** (after U1–U4 are answered and **after FEAT-603 merges to
`dev`**) — *Rationale*: localization is high-confidence and the architecture is fixed by
the FEAT-603 precedent (sibling manager + the same six registration seams); the unknowns
are parameter choices, not architectural forks. The spec should carry the FEAT-603 AC
list adapted to Drive (interface parity, subclass minimality, one credential load, lazy
shim / no SDK leak, factory keys, batch semantics, pagination to exhaustion via
`nextPageToken`, no-httpx lint, live gate) and add Drive-specific ACs for the path
resolver, conflict policy, sharing-link policy and resumable uploads.

### Alternatives

- **`/sdd-brainstorm FEAT-608`** — only if U2 lands on the id-based or hybrid model,
  which changes the toolkit's path handling and deserves an options analysis.
- **`/sdd-task FEAT-608`** — not applicable: multi-module feature (manager, wrapper,
  registration, toolkit, tests, docs, packaging).
- **Manual review** — not needed; research completed within budget.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-608/state.json` |
| Source (raw) | `sdd/state/FEAT-608/source.md` |
| Research plan | `sdd/state/FEAT-608/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-608/findings/F001-*.md` … `F016-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-608/synthesis.json` |
| Synthesis reasoning | `sdd/state/FEAT-608/synthesis.thinking.log` |

**Budget consumed**:
- Files read: 12 / 40
- Grep calls: 16 / 25
- Git calls: 4 / 10
- Wall time: ~240s / 300s
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive request: "interface",
"integration with toolkit"; no negation).

**Gates**: this run executed unattended — the plan gate was auto-approved (recorded as
`approved_by_user: false`); the review gate and Q&A are folded into §5 for the user to
answer.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude Fable 5.1) |
