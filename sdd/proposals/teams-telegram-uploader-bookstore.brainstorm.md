---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-integrations, ai-parrot]
tags: [knowledge-upload, bookstore, llm-wiki, ingest-triage, telegram, msteams]
---

# Brainstorm: Chat-driven document upload into Bookstore / LLM Wiki

**Date**: 2026-10-09
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The Odoo agents in `navigator-agent-server` (OdooSupport, OdooSOP, OdooQA,
OdooHelpdesk) answer from two knowledge planes: the shared `odoo-sop` LLM wiki
and the Odoo Bookstore (PageIndex trees + catalog cards). Today, new knowledge
can only enter those planes **offline**: an operator runs `bookstore add` /
`bookstore add-folder` or `wikitoolkit ingest` on the server
(`agents/odoo_library/README.md`). Subject-matter experts who talk to the
agents through Telegram, MS Teams or Slack cannot contribute a new SOP, manual
or book without shell access.

We want a chat-native path: an **authorized** user attaches a PDF, DOCX or
Markdown file to an explicit command on Telegram, Teams or Slack, and the
document is ingested into the Bookstore or the LLM wiki. The original file is
transient: it is deleted after ingestion; only the derived knowledge persists.

## Constraints & Requirements

- **Explicit destination**: the user picks the target by command — one command
  for the Bookstore (`/ingest_book`), one for the wiki (`/ingest_wiki`). No
  LLM-side classification.
- **Formats**: `.pdf`, `.docx`, `.md`/`.markdown` (v1). `.doc` is unsupported
  by the bookstore and is rejected.
- **Authorization against the navigator-auth identity**: allow-list of
  usernames and groups compared against the session of the user invoking the
  agent. Groups come from `auth.vw_users` (`UserInfoService.get_profile`).
  - Rule: allowed if the username **or** any of the user's groups is in the
    allow-list (OR, never AND).
  - Telegram: **all four** Odoo bots switch to forced login
    (`force_authentication: true`) for security, regardless of which one is
    used as the "curator"; so `TelegramUserSession.nav_user_id` is always
    present.
  - Teams / Slack: no navigator-auth login exists; map the platform user to a
    navigator user **by email** (Teams member email/UPN, Slack `users.info`
    email) and look it up in `auth.vw_users`. Unknown → deny.
  - Default is deny: empty allow-lists mean nobody may upload.
- **No persistence of the original**: the uploaded file lives only in a
  per-job temp directory and is removed in a `finally`, success or failure. It
  must NOT go through `SessionFileStore` (Teams default path) nor the leaking
  Telegram temp path (`handle_document` never deletes).
- **Ingest parity with the CLI**: Bookstore = `Bookstore.add_book` (same as
  `bookstore add`); wiki = the FEAT-402 supervised path — the document first
  goes through the charter-driven `IngestTriageRouter` (the triage filter),
  then the full ingest pipeline (LLM split into linked pages). Requires LLM +
  PageIndexToolkit + a charter for the target wiki.
- **Size limits on all three platforms**: a configurable `max_size_mb` per
  platform, **default 10 MB** on Telegram, Teams and Slack,
  checked before download whenever the platform exposes the size
  (Telegram is additionally capped at 20 MB by the Bot API).
- **Audit = logs only**: a structured log record per upload attempt; no DB
  table.
- **Long-running**: PDF ingest makes many LLM calls (minutes). Teams turns
  time out (~15 s). The command acknowledges immediately and runs ingestion as
  an in-process asyncio task, notifying the user on completion/failure
  (proactive message on Teams/Slack). Ingestions into the same target are
  serialized by a lock.
- **Duplicates**: same sha256 → "already present", skipped; `--force`
  re-ingests. A new version of the same document replaces the old one
  (bookstore `"updated"`, wiki `replace_source_slice`) and must invalidate the
  in-memory PageIndex tree cache of the serving process.
- **Platforms in v1**: Telegram, MS Teams **and** Slack.
- **Generic code in ai-parrot** (`ai-parrot-integrations` + core knowledge);
  `navigator-agent-server` only contributes configuration
  (`env/integrations_bots.yaml`).
- Async-only, aiohttp only, Pydantic v2 config, no secrets in config.

---

## Options Explored

### Option A: Platform-agnostic `KnowledgeUploadService` + thin per-platform command adapters

A single service in `ai-parrot-integrations` (e.g.
`parrot/integrations/core/knowledge_upload/`) owns the whole pipeline:
authorize → validate (extension, size) → stage into a private temp dir →
dispatch to an ingest *target* (`BookstoreTarget`, `WikiTarget`) → delete →
report. Each wrapper (Telegram, Teams, Slack) only does three platform things:
(1) register the `/ingest_book` / `/ingest_wiki` commands on its own router,
(2) resolve an `UploaderIdentity` (nav user id / email → `EmployeeProfile`),
(3) download the attached file bytes and send the final notification. Config
is one Pydantic block (`knowledge_upload:`) shared by all three integration
configs.

Targets are built from config: Bookstore target uses `Bookstore` +
`LibraryLocation`; Wiki target builds an `LLMWikiToolkit` **with** a
`PageIndexToolkit` and LLM client so `ingest_source` works (the agents' own
read-only wiki toolkit is untouched).

✅ **Pros:**
- One authorization, deletion and dedup implementation for 3 platforms; the
  security-critical parts are tested once.
- Reusable by any parrot agent, not only Odoo; matches the "generic in
  ai-parrot" decision.
- In-process execution lets the service invalidate the PageIndex tree cache
  and checkpoint the wiki WAL after a write.
- Explicit commands keep the LLM out of the trust decision.

❌ **Cons:**
- Touches three large wrappers (Telegram `wrapper.py` is >3.5k lines).
- Command handlers today receive no identity (Telegram `@telegram_command`,
  Teams `AgentCommandHandler`) — the upload commands must be registered at
  the wrapper level, not via the agent decorator.
- Long LLM work runs inside the web worker process (shared with chat traffic).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` (existing) | Telegram document download (`bot.get_file`/`download_file`) | already used by `handle_document` |
| `botbuilder-core` (existing) | Teams attachment download, `TeamsInfo.get_member` (email/UPN), proactive messages | already used by msteams wrapper |
| `slack-sdk` / aiohttp (existing) | `files.info`, `users.info` (needs `users:read.email` scope) | `download_slack_file` exists but is unused |
| `parrot_loaders` (existing) | DOCX → markdown, PDF loaders | used by bookstore and `DocumentAcquirer` |
| stdlib `tempfile`, `hashlib` | private staging dir + sha256 | `TemporaryDirectory` cleanup in `finally` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:977` — `Bookstore.add_book`
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:243` — `LLMWikiToolkit.ingest_source`
- `packages/ai-parrot/src/parrot/auth/userinfo.py:148` — `UserInfoService.get_profile` (groups)
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3146` — `handle_document` download logic
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:844` — `_handle_document_attachment` (token + download)
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/files.py:68` — `download_slack_file`
- `MSTeamsCommandRouter.register` / `SlackCommandRouter.register` — command registration

---

### Option B: Agent-side ingest tools guarded by permissions

Add write tools (`ingest_book`, `ingest_wiki_document`) to a toolkit given to
the agent. The integrations pass the uploaded file path to the agent (today
Telegram already appends `[Attached document saved at: …]` to the caption) and
the LLM calls the tool. Authorization is a tool guard over
`PermissionContext` populated with the user's groups.

✅ **Pros:**
- Smallest wrapper changes; works wherever the agent already receives files.
- Natural-language UX ("add this manual to the library").

❌ **Cons:**
- Contradicts the explicit-command decision: the LLM decides when/where to
  ingest, a prompt-injection target for a write path.
- File handling stays on today's paths, which **persist** (Teams
  `SessionFileStore`) or **leak** (Telegram temp files) — the opposite of the
  "delete the original" requirement; Slack does not even download files.
- `PermissionContext.roles` is empty on every integration today
  (`_build_permission_context` sets `roles=frozenset()`).
- Minutes-long tool call blocks the agent turn (Teams timeout).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| parrot `AbstractToolkit` | tool surface | existing |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:29` — `BookstoreToolkit` (read-only today)
- `packages/ai-parrot/src/parrot/auth/permission.py:81` — `PermissionContext`

---

### Option C: Authenticated HTTP ingestion endpoint + integrations as clients

Add an aiohttp handler in `ai-parrot-server` (`POST /api/v1/knowledge/upload`,
multipart, navigator-auth protected) that performs authorization and ingest
and returns a job id; job status via `GET`. The chat integrations just forward
the downloaded bytes with the resolved user identity (service token +
impersonated user), and poll / receive a callback for completion.

✅ **Pros:**
- One ingest surface also usable from the admin UI, scripts, or other bots.
- navigator-auth enforcement is native on HTTP handlers.
- Natural place for a job registry.

❌ **Cons:**
- Integrations would need a trusted service-to-service credential and an
  "on behalf of" user field — a new trust boundary to secure.
- Bytes cross the network twice; more moving parts for the same process.
- Still needs all the per-platform download/identity work of Option A.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` multipart | upload handler | existing stack |
| `navigator-auth` | handler auth | already set up in navigator-agent-server `app.py` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/agent.py:1289` — existing multipart upload → `handle_files`
- `packages/ai-parrot-server/src/parrot/handlers/scope.py:110` — reads `userinfo["groups"]`

---

### Option D (unconventional): CLI subprocess worker

Keep the chat side of Option A but run ingestion as a subprocess of the
existing CLIs (`bookstore add <tmp> …`, `wikitoolkit ingest <tmp> --auto …`),
the same way `ensure_odoo_wiki()` already shells out to `wikitoolkit build`.
The temp file is deleted when the subprocess exits.

✅ **Pros:**
- Literal CLI parity; LLM-heavy work isolated from the serving process (a
  crash or memory spike does not take the bot down).
- No in-process wiring of PageIndex/LLM for the wiki target.

❌ **Cons:**
- The serving process keeps stale PageIndex trees (`PageIndexToolkit._trees`
  cache) after an `"updated"` book — needs an extra invalidation channel.
- Error reporting through exit codes/stdout parsing; harder to test.
- `wikitoolkit ingest` is charter-driven and needs extra flags/env for models.

📊 **Effort:** Medium

🔗 **Existing Code to Reuse:**
- navigator-agent-server `agents/odoo_common.py:240` — `ensure_odoo_wiki` subprocess pattern
- `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:102` — `bookstore add`

---

## Recommendation

**Option A** is recommended because it is the only option that satisfies all
the user decisions at once: explicit commands, one hardened implementation of
authorization + guaranteed deletion for three platforms, generic code in
ai-parrot, and in-process cache invalidation so a new or updated book is
visible to the running agents immediately. Option B puts a write path behind
the LLM and inherits today's leaking/persisting file paths; Option C adds a
service-to-service trust boundary for no functional gain in v1; Option D's
isolation is attractive but its stale-cache problem undermines the core
promise ("upload and it's available").

What we trade off: higher effort and LLM-heavy work inside the bot process.
Mitigations: a per-target lock and a small concurrency cap; Option D's
subprocess runner can be added later as an alternative *executor* behind the
same `IngestTarget` interface without touching the chat side.

---

## Feature Description

### User-Facing Behavior

- **Telegram**: send a document with caption `/ingest_book` or `/ingest_wiki`
  (optional args: `--force`, `--title "…"`, `--topic x`), or reply to an
  already-sent document with the command. Commands appear in the bot menu only
  if `knowledge_upload.enabled`.
- **MS Teams**: message with an attachment and text `/ingest_book` /
  `/ingest_wiki` (routed by `MSTeamsCommandRouter`).
- **Slack**: slash commands cannot carry files, so the flow is: share the file
  in the DM/channel with the message text `/ingest_book …` (message event with
  `files`), or run the slash command and upload the file within a short
  pending window (e.g. 5 min) — the next file from that user is consumed.
- Responses:
  1. Not authorized → "You are not allowed to upload knowledge." (no detail
     about lists), audit-logged.
  2. Accepted → "Received *manual.pdf* → Bookstore. Processing…"
  3. Done → "Added *Title* to the Bookstore (42 sections)" / "Wiki: 7 pages
     created, 2 updated" / "Already present (same content) — use --force".
  4. Failed → short error + job id; the temp file is deleted anyway.

### Internal Behavior

1. Wrapper detects an ingest command with an attachment and **short-circuits**
   the default document handling (no `SessionFileStore`, no leaking temp
   file, no agent invocation).
2. Wrapper resolves `UploaderIdentity`:
   - Telegram: `TelegramUserSession.nav_user_id` (forced login).
   - Teams: member email/UPN → navigator user.
   - Slack: `users.info` email → navigator user.
   Then `UserInfoService` → `EmployeeProfile(username, groups)`.
3. `KnowledgeUploadService.authorize(identity, target)`: allowed if
   `username ∈ allowed_usernames` OR `groups ∩ allowed_groups ≠ ∅`
   (one global list per bot for both targets — no per-target lists). Deny by
   default.
4. Validate extension (`.pdf .docx .md .markdown`) and size
   (`max_size_mb`), then download into a private `TemporaryDirectory`
   (0700) — bytes never touch a persistent store.
5. Acknowledge; spawn an asyncio task registered in a small job registry
   (in-memory, for status + cancellation on shutdown); acquire the per-target
   lock.
6. Ingest:
   - Bookstore: `Bookstore.add_book(tmp_path, title=…, topics=…, force=…)`,
     then rewrite the card's `source_path` to a logical
     `upload://<platform>/<username>/<filename>` (the temp path would be a
     dangling reference) and invalidate the cached PageIndex tree.
   - Wiki: FEAT-402 triage first — `IngestTriageRouter.triage(path, content)`
     with the wiki's charter returns a `ManifestDocEntry` whose
     `proposed_action` is `admit` / `archive` / `discard`. `admit` → run
     `WikiIngestOrchestrator.ingest(..., triage=entry, charter_version=…)`
     (decision recorded with `decision_source="auto"`, as `--auto` does);
     `discard` → nothing is ingested and the user gets the triage briefing as
     the reason; gray-zone / `archive` → also rejected with the briefing as
     explanation (no chat confirmation, `--force` does not bypass triage — it
     only bypasses the duplicate check). Triage and ingest use the same LLM as
     the bookstore (`google:gemini-3.1-flash-lite`). Dedicated ingest
     toolkit wired with PageIndex + LLM, same logical source naming so a
     re-upload replaces the same source slice; checkpoint WAL.
7. `finally`: delete the temp dir; emit a structured audit log record (who,
   platform, target, filename, sha256, size, triage action, outcome,
   duration). Logs only — no DB table.
8. Notify the user (proactive message on Teams/Slack, reply on Telegram).

### Edge Cases & Error Handling

- Command without attachment → usage help. Attachment of wrong type or too
  large → rejected before download where the platform gives metadata.
- Size: each platform has its own `max_size_mb` (default 10 MB); oversize files are rejected
  before download when the platform reports the size (Telegram
  `document.file_size`, Teams attachment metadata when present, Slack
  `files.info` `size`), and the download is aborted past the limit otherwise.
  Telegram Bot API cannot download >20 MB regardless of config.
- No charter for the target wiki → the wiki command is disabled at startup
  with a logged reason (triage cannot run without one).
- Email lookup ambiguity / missing email (guest users, Slack without
  `users:read.email`) → deny with "identity could not be verified".
- No LLM configured: Bookstore PDF ingest raises `BookstoreError`; wiki ingest
  needs an LLM — the service checks at startup and hides/disables commands
  whose target cannot work.
- Process restart mid-ingest: job lost, temp dir is gone with it (`/tmp` +
  startup sweep of a known prefix); the user must re-upload. Acceptable
  because originals are intentionally not persisted.
- Concurrent uploads to the same target → serialized; to different targets →
  parallel up to a cap.
- `reingest_source` on a wiki source whose original was deleted cannot work —
  re-ingestion is by re-uploading.
- Prompt injection inside the document only affects the *content* of the
  ingested pages, not authorization (the LLM is not in the trust path).

---

## Capabilities

### New Capabilities
- `knowledge-upload-service`: platform-agnostic authorize/stage/ingest/delete/report pipeline with Bookstore and Wiki targets.
- `knowledge-upload-auth`: navigator-auth identity resolution (nav user id or email) + username/group allow-list policy.
- `telegram-knowledge-upload`: `/ingest_book`, `/ingest_wiki` with document caption/reply.
- `msteams-knowledge-upload`: Teams commands + attachment download + proactive completion message.
- `slack-knowledge-upload`: Slack message/slash-command flow, file download, `users.info` email mapping.

### Modified Capabilities
- Bookstore: allow a logical `source_path` override for uploads; PageIndex tree cache invalidation hook.
- Telegram/Teams/Slack integration configs: new `knowledge_upload` block.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `ai-parrot-integrations/.../telegram/wrapper.py`, `models.py` | modifies | command registration, document short-circuit, config block |
| `ai-parrot-integrations/.../msteams/wrapper.py`, `models.py`, `commands/` | modifies | router command, attachment download bypassing `SessionFileStore`, email lookup |
| `ai-parrot-integrations/.../slack/wrapper.py`, `models.py`, `files.py` | modifies | first real use of `download_slack_file`; `users.info` email |
| `ai-parrot-integrations/.../core/` (new `knowledge_upload/`) | extends | service, targets, policy, job registry |
| `ai-parrot/.../knowledge/bookstore/library.py` | modifies | source_path override (overlaps FEAT-539, see Parallelism) |
| `ai-parrot/.../knowledge/pageindex/toolkit.py` | modifies | tree cache invalidation |
| `ai-parrot/.../auth/userinfo.py` | extends | lookup by email / username |
| navigator-agent-server `env/integrations_bots.yaml` | config | `knowledge_upload` block; `force_authentication: true` + login enabled on **all four** Odoo bots |
| navigator-agent-server `agents/odoo_wiki/.parrot/charter.yaml` | new config | editorial charter for `odoo-sop` (does not exist yet); written by the user, NOT a deliverable of this feature; required by the triage filter |
| `ai-parrot/.../knowledge/wiki/triage.py`, `ingest.py` | depends on | FEAT-402 triage router + orchestrator `triage=` path, reused as-is |
| Slack app manifest | deployment | `users:read.email`, `files:read` scopes |

No breaking changes: the feature is opt-in (`knowledge_upload.enabled: false`
by default).

---

## Code Context

### User-Provided Code
None (the request was prose only).

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:178
class Bookstore:
    def __init__(self, locations, adapter=None, lightweight_model=None): ...   # :192
    async def add_book(                                                         # :977
        self,
        file_path: str | Path,
        scope: str = "project",
        title: Optional[str] = None,
        authors: Optional[list[str]] = None,
        topics: Optional[list[str]] = None,
        force: bool = False,
        *,
        relate: bool = False,
    ) -> tuple[BookCard, str]: ...   # status in {"added", "updated", "skipped"}; dedup sha256 then path
# library.py:57 _FORMAT_BY_SUFFIX: .pdf .md/.markdown .txt .epub .mobi .docx (no .doc)
# library.py:1047 PDF ingest without LLM raises BookstoreError
# library.py:1135-1137 card stores source_path, source_sha256, source_format (original not copied)

# packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:31
class LibraryLocation:  # (scope, root); db_path=root/library.db (:43), trees_dir=root/trees (:48)
def resolve_locations(cwd=None, include_global=True, require_exists=False): ...  # :78

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:42
class LLMWikiToolkit(AbstractToolkit):
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any, okf_toolkit: Any,
                 config: WikiConfig, agent_id: str = "agent",
                 store: Optional[BaseWikiStore] = None, **kwargs: Any) -> None: ...   # :76
    async def ingest_source(self, wiki_name: str, source_path: str,
                            source_type: Optional[str] = None) -> dict[str, Any]: ...  # :243
# ingest requires pageindex_toolkit + LLM (ingest.py:797-820); re-ingest replaces via
# store.replace_source_slice (ingest.py:433); sources manifest records path/sha1/mtime only (sources.py:231)

# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py:198 (WikiIngestOrchestrator)
async def ingest(self, source_path: str, wiki_config: WikiConfig, *,
                 triage: Optional[ManifestDocEntry] = None,
                 charter_version: Optional[str] = None,
                 acquired: AcquiredDocument | None = None) -> IngestReport: ...
# triage=None is the legacy path; FEAT-402 passes the triage entry

# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:243
class IngestTriageRouter:
    def __init__(self, charter: Charter, adapter: PageIndexLLMAdapter,
                 sources: SourceCollectionManager, novelty_scorer: NoveltyScorer, *,
                 heavy_adapter: PageIndexLLMAdapter | None = None,
                 max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES,
                 allowed_suffixes: frozenset[str] | None = None) -> None: ...   # :262
    async def triage(self, path: Path, content: str, *,
                     skip_duplicate_check: bool = False) -> ManifestDocEntry: ...  # :295
# triage.py:67 class NoveltyScorer

# packages/ai-parrot/src/parrot/knowledge/wiki/review.py:135
class ManifestDocEntry(BaseModel):
    proposed_action: Literal["admit", "archive", "discard"]   # :164
    decision: ...          # None until review / auto
    decision_source: ...   # "heuristic" | "model" | "human" | "auto"

# packages/ai-parrot/src/parrot/knowledge/wiki/charter.py
class Charter(BaseModel): ...                     # :311
def load_charter(path: Path) -> Charter: ...       # :404
# Thresholds.route(composite) -> Literal["admit", "gray", "reject"]   # :110
# cli.py:4564 _resolve_charter_path: --charter, else <root>/.parrot/charter.yaml
# cli.py:5087-5090 `wikitoolkit ingest --auto`: "Thresholds decide; flags a stratified audit sample."

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
self._trees: dict[str, dict[str, Any]] = {}          # :162 in-memory tree cache
def _load_tree(self, tree_name: str) -> dict[str, Any]: ...   # :179 — no invalidation API

# packages/ai-parrot/src/parrot/auth/userinfo.py
class EmployeeProfile:  # user_id, username, display_name, email, ..., groups: list[str] (:71), programs
class UserInfoService:                                        # :77
    async def get_profile(self, user_id: Any) -> EmployeeProfile | None: ...   # :148, by user_id only

# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext: ...

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/
# auth.py:44 class TelegramUserSession — nav_user_id (:52), nav_email, telegram_username; no groups
# wrapper.py:3146 async def handle_document(self, message: Message) -> None   (temp file never deleted)
# wrapper.py:1442 async def _invoke_agent(...)
# wrapper.py:759  def _register_agent_commands(self) -> None
# wrapper.py:1044 def _is_authorized(self, chat_id: int) -> bool   (fails open when allowed_chat_ids None)
# wrapper.py:1258 def _build_permission_context(...)               (roles=frozenset())
# decorators.py:5 def telegram_command(command: str, description: str = "", parse_mode: str = "keyword") -> Callable
#   — decorated agent methods receive parsed args only, no user/session

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/
# wrapper.py:304 def _is_authorized(self, conversation_id: str, user_id: str) -> bool
# wrapper.py:827 def _find_document_attachments(self, activity: Activity) -> list[Attachment]
# wrapper.py:844 async def _handle_document_attachment(self, turn_context, attachment) -> Optional[str]
#   — stores into SessionFileStore().put_bytes(...) (persistent), file_id discarded
# commands/__init__.py:30 class MSTeamsCommandRouter: register(command, handler) :56,
#   try_dispatch :74, try_dispatch_plain :111, registered_commands :153; handler = async (turn_context) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/slack/
# commands/__init__.py:27 class SlackCommandRouter: register(command, handler) :50; handler = async (payload: dict) -> dict|None
# files.py:48 def extract_files_from_event(event) -> List[Dict[str, Any]]
# files.py:68 async def download_slack_file(file_info, bot_token, download_dir: Optional[str] = None)  — never called today
```

#### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError   # library.py:178, :111
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                   # toolkit.py:42
from parrot.auth.userinfo import UserInfoService, EmployeeProfile          # userinfo.py:77
from parrot.integrations.msteams.commands import MSTeamsCommandRouter      # commands/__init__.py:30
from parrot.integrations.slack.commands import SlackCommandRouter          # commands/__init__.py:27
from parrot.integrations.slack.files import download_slack_file, extract_files_from_event
```

#### Key Attributes & Constants
- `TelegramAgentConfig.max_document_size_mb` → `int`, default 20 (telegram/models.py:128)
- `TelegramAgentConfig.force_authentication`, `enable_login`, `auth_method(s)`, `allowed_chat_ids` (telegram/models.py)
- `MSTeams config allowed_conversation_ids / allowed_user_ids` (msteams/models.py:45-46)
- `SlackAgentConfig.allowed_channel_ids / allowed_user_ids` (slack/models.py:59-60)
- navigator-agent-server: `ODOO_WIKI_NAME="odoo-sop"`, `ODOO_WIKI_ROOT`, `ODOO_WIKI_STORAGE` (agents/odoo_common.py:213-215); `odoo_library_dir()` (:312), `odoo_bookstore_toolkit()` (:317, read-only, default LLM `google:gemini-3.1-flash-lite` :309); bots configured in `env/integrations_bots.yaml` (Telegram only, `enable_login: false`).

### Does NOT Exist (Anti-Hallucination)
- ~~Any upload-to-knowledge-base feature in Telegram/Teams/Slack integrations~~
- ~~A shared cross-platform command registry~~; ~~a Teams/Slack command decorator~~; ~~command handlers receiving user identity~~
- ~~Groups/roles in `TelegramUserSession` or any integration session~~
- ~~`UserInfoService` lookup by email or username~~ (only `get_profile(user_id)`)
- ~~Bookstore write tool / HTTP endpoint~~ (`BookstoreToolkit` is read-only)
- ~~A `wikitoolkit bookstore` subcommand~~ (CLI is `bookstore` / `parrot bookstore`)
- ~~PDF/TXT bookstore ingest without an LLM~~; ~~wiki ingest with `pageindex_toolkit=None`~~
- ~~`.doc` support~~
- ~~PageIndex tree cache invalidation API~~
- ~~TTL/cleanup on `SessionFileStore`~~; ~~cleanup of Telegram document temp files~~
- ~~Slack file download in the wrapper~~ (`download_slack_file` unused); ~~use of `SlackAgentConfig.commands` / `enable_attachments`~~
- ~~Teams config for the Odoo agents~~
- ~~An editorial charter for the `odoo-sop` wiki~~ (`agents/odoo_wiki/.parrot/` has none)
- ~~Background ingestion jobs~~

---

## Parallelism Assessment

- **Internal parallelism**: high after a shared foundation. Task 1
  (service + policy + targets + config model + `UserInfoService` email lookup
  + PageIndex cache invalidation) is a prerequisite; then Telegram, Teams and
  Slack adapters touch disjoint wrapper files and can run in parallel.
- **Cross-feature independence**: FEAT-539 (`contracts-card-ontology`, still
  open) touches `knowledge/bookstore/library.py`; the `source_path` override
  must be coordinated (keep it a small, additive keyword argument). No other
  open spec touches the three wrappers.
- **Recommended isolation**: `mixed`
- **Rationale**: foundation sequential; the three platform adapters are
  independent and benefit from sub-worktrees.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: feature → dev
- [x] How is the destination chosen? — *Owner: Jesus Lara*: explicit commands (`/ingest_book`, `/ingest_wiki`)
- [x] Identity source — *Owner: Jesus Lara*: navigator-auth session; Telegram bots with forced login; Teams/Slack mapped by email to `auth.vw_users`
- [x] Ingest depth — *Owner: Jesus Lara*: same as CLI; wiki uses full `ingest_source` (LLM)
- [x] Execution model — *Owner: Jesus Lara*: in-process asyncio task + completion notification, per-target lock
- [x] Platforms in v1 — *Owner: Jesus Lara*: Telegram, Teams and Slack
- [x] Code location — *Owner: Jesus Lara*: generic in ai-parrot; navigator-agent-server only config
- [x] Duplicates — *Owner: Jesus Lara*: skip same sha256, `--force` to re-ingest, new version replaces
- [x] Username/group rule — *Owner: Jesus Lara*: OR — a matching username or a matching group is enough
- [x] Forced login scope — *Owner: Jesus Lara*: forced login on all four Odoo bots for security, even if only one acts as "curator"
- [x] Wiki filtering — *Owner: Jesus Lara*: apply the FEAT-402 charter-driven triage filter before ingesting
- [x] Audit trail — *Owner: Jesus Lara*: logs only
- [x] Size limits — *Owner: Jesus Lara*: configurable size limit on all three platforms
- [x] Triage gray zone / `archive` — *Owner: Jesus Lara*: rejected with the triage briefing as explanation; `--force` does not bypass triage
- [x] `odoo-sop` charter authorship — *Owner: Jesus Lara*: the user writes `agents/odoo_wiki/.parrot/charter.yaml`; not a deliverable of this feature (wiki command stays disabled until it exists)
- [x] Allow-list scope — *Owner: Jesus Lara*: one global list (usernames + groups) per bot, shared by both targets
- [x] Wiki/triage LLM — *Owner: Jesus Lara*: reuse the bookstore's `google:gemini-3.1-flash-lite`
- [x] Size limit — *Owner: Jesus Lara*: 10 MB default on all three platforms (configurable)
