---
type: feature
base_branch: dev
projects: [ai-parrot-integrations, ai-parrot]
tags: [knowledge-upload, bookstore, llm-wiki, ingest-triage, telegram, msteams]
---

# Feature Specification: Chat-driven document upload into Bookstore / LLM Wiki

**Feature ID**: FEAT-647
**Date**: 2026-10-09
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: next minor of `ai-parrot` / `ai-parrot-integrations`

Source brainstorm: `sdd/proposals/teams-telegram-uploader-bookstore.brainstorm.md`
(Recommended Option A — platform-agnostic `KnowledgeUploadService` + thin
per-platform command adapters).

---

## 1. Motivation & Business Requirements

### Problem Statement

The Odoo agents in `navigator-agent-server` (OdooSupport, OdooSOP, OdooQA,
OdooHelpdesk) answer from two knowledge planes: the shared `odoo-sop` LLM wiki
and the Odoo Bookstore (PageIndex trees + catalog cards). Today new knowledge
can only enter those planes **offline**: an operator runs `bookstore add` /
`bookstore add-folder` or `wikitoolkit ingest` on the server
(`agents/odoo_library/README.md`). Subject-matter experts who talk to the
agents through Telegram, MS Teams or Slack cannot contribute a new SOP, manual
or book without shell access.

We want a chat-native path: an **authorized** user attaches a PDF, DOCX or
Markdown file to an explicit command on Telegram, Teams or Slack, and the
document is ingested into the Bookstore or the LLM wiki. The original file is
transient: it is deleted after ingestion; only the derived knowledge persists.

### Goals
- G1. Two explicit commands on Telegram, MS Teams and Slack: `ingest_book`
  (→ Bookstore) and `ingest_wiki` (→ LLM wiki). The user picks the target; the
  LLM never decides.
- G2. Formats `.pdf`, `.docx`, `.md`, `.markdown`; anything else is rejected.
- G3. Authorization against the **navigator-auth** identity: allowed if the
  user's username **or** any of the user's groups is in **one global
  allow-list per bot** (shared by both targets). Deny by default (empty lists
  ⇒ nobody may upload).
- G4. The original file is never persisted: it is held in memory, written to a
  private staging path only for the duration of the ingest, and deleted in a
  `finally` (success, failure or cancellation).
- G5. Ingest parity with the CLI: Bookstore = `Bookstore.add_book` (as
  `bookstore add`); wiki = FEAT-402 supervised path — charter-driven triage
  (`IngestTriageRouter`) then `WikiIngestOrchestrator.ingest`.
- G6. Long-running ingests never block the chat turn: immediate
  acknowledgement, in-process asyncio job, completion/failure notification.
- G7. Duplicates: identical content (sha256) is skipped unless `--force`; a new
  version under the same file name replaces the previous one.
- G8. Size limit on all three platforms: `max_size_mb`, **default 10 MB**.
- G9. Audit by structured log records only.
- G10. Generic code in ai-parrot; `navigator-agent-server` contributes only
  configuration.

### Non-Goals (explicitly out of scope)
- Writing the `odoo-sop` editorial charter
  (`agents/odoo_wiki/.parrot/charter.yaml`) — the user writes it; until it
  exists, `ingest_wiki` is disabled.
- Changing the agents' read toolkits (`BookstoreToolkit`, `LLMWikiToolkit`
  wiring in `navigator-agent-server`), or giving the LLM any write tool —
  agent-side ingest tools were rejected in the brainstorm (Option B).
- An HTTP upload endpoint (brainstorm Option C) and out-of-process CLI workers
  (Option D).
- Fixing the pre-existing leaks of the *default* document paths (Telegram
  `handle_document` temp files, Teams `SessionFileStore` uploads) — upload
  commands bypass them; the defaults are left as they are.
- Persistent job queue / surviving restarts, `.doc`, `.epub`, `.txt` uploads,
  group chats on Telegram (documents are private-chat only today), a DB audit
  table, chat-side confirmation of triage gray-zone documents.
- Editing `navigator-agent-server` from this repo (its config change is
  documented in §7 as a deployment step).

---

## 2. Architectural Design

### Overview

A new subpackage `parrot.integrations.knowledge_upload` (in
`ai-parrot-integrations`) owns the whole pipeline. Wrappers only do platform
work: register the two commands, resolve who the user is, download the bytes
(bounded by `max_size_mb`) and deliver the final notification.

**User-facing behavior**
- **Telegram** (private chats): send a document with caption
  `/ingest_book [--force] [--title "…"] [--author "…"] [--topic x]` or
  `/ingest_wiki [--force]`, or reply to an already-sent document with the
  command. Commands are added to the bot menu only when
  `knowledge_upload.enabled` and the target is available.
- **MS Teams**: a message with a file attachment whose text is `/ingest_book …`
  or `/ingest_wiki …` (routed by `MSTeamsCommandRouter`, which already runs
  before the default attachment handling).
- **Slack**: slash commands cannot carry files, so two entry points:
  (a) share the file with message text `ingest_book …` / `ingest_wiki …`
  (no leading slash) — consumed by a message interceptor; (b) run the slash
  command `/ingest_book` / `/ingest_wiki`, which arms a pending window
  (`slack_pending_window_s`, default 300 s) during which the next file shared
  by that user in that channel is consumed.
- Replies: unauthorized → "You are not allowed to upload knowledge." (no list
  details); accepted → "Received *x.pdf* → Bookstore. Processing…"; done →
  "Added *Title* to the Bookstore" / "Wiki: N pages created, M updated" /
  "Already present (same content) — use --force"; triage rejection → the
  triage briefing as explanation; failure → short error + job id.

**Identity** (G3)
- Telegram: all four Odoo bots run with `enable_login: true` +
  `force_authentication: true` (security decision, independent of which bot is
  the curator). The upload handler additionally requires
  `session.authenticated` and `session.nav_user_id` itself (defense in depth),
  then `UserInfoService.get_profile(nav_user_id)`; fallback to
  `get_profile_by_email(session.nav_email)`.
- Teams: member email/UPN via `TeamsInfo.get_member` →
  `UserInfoService.get_profile_by_email` (new).
- Slack: `users.info` → `user.profile.email` →
  `UserInfoService.get_profile_by_email` (new).
- Profile not found / no email ⇒ deny ("identity could not be verified").
- Policy: case-insensitive match of `profile.username` against
  `allowed_usernames`, or non-empty intersection of `profile.groups` with
  `allowed_groups`.

**Staging and identity of the ingested source** (G4, G7). Both planes derive
source identity from the file path (`Bookstore.add_book` resolves the path and
stores it as `source_path`; `WikiIngestOrchestrator.ingest` keys the source
manifest on the resolved path — a logical `upload://…` URI is rejected by
`SourceCollectionManager.add_source`). The brainstorm's `upload://` rewrite is
therefore replaced by a **stable staging path per target**:
- Bookstore: `<library_dir>/.uploads/<safe_filename>`
- Wiki: `<wiki_root>/.parrot/uploads/<safe_filename>` (`.parrot` is in
  `VAULT_EXCLUDE_DIRS`, so `wikitoolkit build --vault` never scans it)

`safe_filename` = basename of the platform-provided name, NFC-normalized,
path separators and control chars stripped, extension preserved. The same
file name re-uploaded maps to the same path ⇒ Bookstore status `"updated"`
(same `book_id`) and wiki `replace_source_slice` (pages replaced, not
duplicated). The staging directory is created `0o700`; the file exists only
between "write" and the `finally` that unlinks it; a startup sweep removes any
leftover file from a crashed run. Bytes are held in memory until the target
lock is acquired (≤ `max_size_mb`).

**Execution** (G6). `KnowledgeUploadService.submit()` validates synchronously
(policy, extension, size) and returns an acknowledgement; the ingest runs in an
asyncio task tracked by the service (bounded by a semaphore,
`max_concurrent_jobs`, default 2). Stage → ingest → delete all happen inside a
**process-wide per-target lock** keyed by the resolved target root (several bot
wrappers in one process share it, preventing staging-name collisions and
concurrent SQLite writers). The wrapper-supplied `notify` coroutine delivers
the outcome. `shutdown()` cancels running jobs; cancellation still deletes the
staged file.

**Bookstore target**. `Bookstore([LibraryLocation(scope="project",
root=library_dir)], adapter=…, lightweight_model=…)` built with
`resolve_adapter(llm)` (default `google:gemini-3.1-flash-lite`, same as the
agents). No adapter ⇒ target unavailable (PDF ingest requires an LLM).
`add_book(staged_path, title=…, authors=…, topics=…, force=…)` →
`"added" | "updated" | "skipped"`.

**Wiki target** (FEAT-402 triage, decisions resolved in brainstorm).
`build_ingest_runtime(...)` (new public builder extracted from the CLI) gives
the charter, triage router, orchestrator, acquirer and store; both triage
models are `google:gemini-3.1-flash-lite`. Flow: `acquirer.acquire(ref)` →
`router.triage(staged_path, acquired.text)` → **only `proposed_action ==
"admit"` is ingested** (`decision="admit"`, `decision_source="auto"`,
`charter_version=charter.version`, `acquired=acquired`); `archive`, gray-zone
and `discard` are **rejected with the triage briefing as explanation**;
`--force` never bypasses triage (it only bypasses the duplicate check). After
a write the SQLite WAL is checkpointed. No charter ⇒ target unavailable.

**Freshness for the serving agents**. Each Odoo agent owns its own
`Bookstore` → `PageIndexToolkit` whose `_trees` cache never reloads. A new
book is visible immediately (catalog reads are per call), but an `"updated"`
book would stay stale. `PageIndexToolkit._load_tree` gains an on-disk
signature check (mtime_ns + size of the tree JSON): when it changed, the
cached tree, its search engine and its content-store cache are evicted and the
tree reloaded. Wiki reads go through the SQLite plane and need nothing.

### Component Diagram
```
Telegram / Teams / Slack wrapper
  │  command + attachment          (platform adapter: M8 / M9 / M10)
  ├─ resolve identity ──→ UserInfoService.get_profile / get_profile_by_email (M2)
  ├─ download bytes (≤ max_size_mb)
  └─ KnowledgeUploadService.submit(request, notify)          (M1)
        ├─ UploadPolicy.authorize(profile)                    (M1)
        ├─ validate extension/size  → ack
        └─ asyncio job ─ per-target lock ─ stage ─┬─ BookstoreTarget (M4) → Bookstore.add_book
                                                  └─ WikiTarget (M5) → build_ingest_runtime (M3)
                                                        → triage → (admit) orchestrator.ingest
              finally: unlink staged file · audit log · notify(outcome)
PageIndexToolkit._load_tree freshness (M6) ← serving agents see updated books
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `Bookstore.add_book` | uses | via stable staging path; status drives the reply |
| `bookstore._llm.resolve_adapter` | uses | builds the Bookstore LLM adapter |
| `WikiIngestOrchestrator.ingest`, `IngestTriageRouter.triage`, `DocumentAcquirer.acquire` | uses | FEAT-402 path, auto decision for `admit` only |
| `wiki/cli.py` `_build_ingest_runtime` + helpers | modifies | logic extracted to public `wiki/runtime.py`; CLI wrappers keep raising `click.ClickException` |
| `PageIndexToolkit._load_tree` | modifies | on-disk freshness check |
| `UserInfoService` | extends | `get_profile_by_email` |
| `TelegramAgentConfig` / `MSTeamsAgentConfig` / `SlackAgentConfig` | extends | `knowledge_upload` field parsed in `from_dict` |
| `TelegramAgentWrapper._register_handlers` | modifies | ingest handlers registered before the default document handler |
| `MSTeamsCommandRouter.register` | uses | `ingest_book` / `ingest_wiki` handlers |
| `SlackCommandRouter.register`, `SlackAgentWrapper.add_message_interceptor` | uses | slash commands + file-message interceptor |
| Slack assistant-mode DM path | modifies | interceptors must also run before `_assistant_handler.handle_user_message` |
| navigator-agent-server `env/integrations_bots.yaml` | config (out of repo) | `knowledge_upload` block, `enable_login`/`force_authentication: true` on all four bots |

### Data Models
```python
# parrot/integrations/knowledge_upload/models.py
class UploadTargetKind(str, Enum):
    BOOKSTORE = "bookstore"
    WIKI = "wiki"

class BookstoreTargetConfig(BaseModel):
    library_dir: str                      # env vars expanded (os.path.expandvars)
    llm: str = "google:gemini-3.1-flash-lite"

class WikiTargetConfig(BaseModel):
    wiki_root: str                        # project root holding .parrot/wiki.json
    charter_path: str | None = None       # default <wiki_root>/.parrot/charter.yaml
    llm: str = "google:gemini-3.1-flash-lite"   # used for both triage stages + ingest

class KnowledgeUploadConfig(BaseModel):
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
    platform: Literal["telegram", "msteams", "slack"]
    platform_user_id: str
    nav_user_id: str | None = None
    email: str | None = None

class UploadRequest(BaseModel):
    target: UploadTargetKind
    identity: UploaderIdentity
    filename: str
    data: bytes
    force: bool = False
    title: str | None = None
    authors: list[str] = []
    topics: list[str] = []

class UploadStatus(str, Enum):
    ACCEPTED = "accepted"; DENIED = "denied"; INVALID = "invalid"
    ADDED = "added"; UPDATED = "updated"; SKIPPED = "skipped"
    REJECTED_BY_TRIAGE = "rejected_by_triage"; FAILED = "failed"

class UploadOutcome(BaseModel):
    job_id: str
    status: UploadStatus
    target: UploadTargetKind
    filename: str
    message: str                 # user-facing text
    detail: dict[str, Any] = {}  # e.g. book_id, pages_created, briefing
```

### New Public Interfaces
See §3 Interface Skeletons; the entry points are
`KnowledgeUploadService.from_config()`, `.submit()`, `.available_targets()`,
`.shutdown()`, `UserInfoService.get_profile_by_email()` and
`parrot.knowledge.wiki.runtime.build_ingest_runtime()`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: knowledge-upload core | no | — | job lifecycle, lock registry and cleanup ordering are security-relevant design |
| M2: userinfo email lookup | yes | `get_profile_by_email(email) -> EmployeeProfile \| None`, same SELECT as `get_profile` with `WHERE lower(email) = lower($1)`, cache key `email:<lower>` | — |
| M3: wiki runtime extraction | yes | move bodies verbatim; `WikiRuntimeError` replaces `click.ClickException`; CLI wrappers convert | — |
| M4: bookstore target | yes | contract fixed in skeleton | — |
| M5: wiki target | no | — | triage → decision mapping and runtime caching need judgment |
| M6: pageindex freshness | yes | signature = `(st_mtime_ns, st_size)` of `JSONTreeStore._path_for(name)`; skip when `_batch_depth.get(name)` | — |
| M7: config fields | yes | `knowledge_upload: KnowledgeUploadConfig` dataclass field, `from_dict` → `KnowledgeUploadConfig.model_validate(data.get("knowledge_upload") or {})` | — |
| M8: Telegram adapter | no | — | aiogram handler ordering + reply-to flow |
| M9: Teams adapter | no | — | attachment download variants + proactive delivery |
| M10: Slack adapter | no | — | pending window + interceptor placement |
| M11: docs | yes | `docs/integrations/knowledge-upload.md` | — |

### Module 1: Knowledge upload core
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/`
  (`__init__.py`, `models.py`, `policy.py`, `staging.py`, `service.py`, `targets/__init__.py`, `targets/base.py`)
- **Responsibility**: config/data models, authorization policy, staging +
  guaranteed deletion, job runner with semaphore and process-wide per-target
  locks, audit logging, lazy target construction.
- **Depends on**: M2 (profile lookup); targets M4/M5 are imported lazily by name.
- **Interface Skeleton**:
  ```python
  # knowledge_upload/policy.py (new)
  class UploadPolicy:
      """Username-or-group allow-list; deny by default."""
      def __init__(self, allowed_usernames: Iterable[str], allowed_groups: Iterable[str]) -> None: ...
      def is_allowed(self, profile: EmployeeProfile | None) -> bool:
          """True iff profile is not None and (username ∈ allowed_usernames or groups ∩ allowed_groups),
          case-insensitive; False when both lists are empty."""
  async def resolve_profile(identity: UploaderIdentity, userinfo: UserInfoService) -> EmployeeProfile | None:
      """nav_user_id → get_profile (verified: parrot/auth/userinfo.py:148); else email → get_profile_by_email (M2)."""

  # knowledge_upload/staging.py (new)
  def safe_filename(name: str) -> str:
      """Basename only, NFC, no separators/control chars; raises ValueError when empty."""
  @asynccontextmanager
  async def staged_file(directory: Path, filename: str, data: bytes) -> AsyncIterator[Path]:
      """Create `directory` 0o700, write data to directory/safe_filename(filename), yield the path,
      unlink it in `finally` (also on CancelledError)."""
  def sweep_staging(directory: Path) -> int:
      """Delete leftover files from a crashed run; returns count."""

  # knowledge_upload/targets/base.py (new)
  class IngestTarget(ABC):
      kind: UploadTargetKind
      @property
      @abstractmethod
      def lock_key(self) -> Path: """Resolved root used for the process-wide lock."""
      @property
      @abstractmethod
      def staging_dir(self) -> Path: ...
      @abstractmethod
      async def available(self) -> tuple[bool, str]: """(usable, reason) — checked once at startup."""
      @abstractmethod
      async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome: ...

  # knowledge_upload/service.py (new)
  Notify = Callable[[UploadOutcome], Awaitable[None]]
  class KnowledgeUploadService:
      def __init__(self, config: KnowledgeUploadConfig, targets: dict[UploadTargetKind, IngestTarget],
                   userinfo: UserInfoService | None = None) -> None: ...
      @classmethod
      async def from_config(cls, config: KnowledgeUploadConfig) -> "KnowledgeUploadService":
          """Build configured targets lazily, run available() + sweep_staging(); unavailable targets are
          dropped with a logged reason."""
      def available_targets(self) -> set[UploadTargetKind]: ...
      def max_bytes(self, platform_cap_mb: int | None = None) -> int:
          """min(config.max_size_mb, platform_cap_mb) in bytes."""
      async def authorize(self, identity: UploaderIdentity) -> EmployeeProfile | None:
          """Profile when allowed, None when denied (denial is audit-logged)."""
      async def submit(self, request: UploadRequest, notify: Notify) -> UploadOutcome:
          """Validate (target available, extension, size, authorization) and return ACCEPTED immediately
          after scheduling the job; DENIED / INVALID outcomes are returned without scheduling. The job:
          semaphore → per-target lock → staged_file → target.ingest → audit log → notify(outcome).
          Exceptions become FAILED outcomes; notify errors are logged, never raised."""
      async def shutdown(self) -> None: """Cancel running jobs and await them."""
  ```

### Module 2: UserInfoService email lookup
- **Path**: `packages/ai-parrot/src/parrot/auth/userinfo.py` (modifies)
- **Responsibility**: resolve a navigator user from an email (Teams/Slack).
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  class UserInfoService:  # verified: parrot/auth/userinfo.py:77
      async def get_profile(self, user_id: Any) -> EmployeeProfile | None:  # verified: userinfo.py:148
      async def get_profile_by_email(self, email: str) -> EmployeeProfile | None:  # new
          """Case-insensitive lookup in auth.vw_users; None when no row or when more than one row matches
          (ambiguous identities are never authorized). Cached like get_profile."""
  ```

### Module 3: Public wiki ingest runtime
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` (new);
  `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (modifies)
- **Responsibility**: expose the supervised-ingest service stack without
  `click`; the CLI keeps its behavior and messages.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # wiki/runtime.py (new)
  class WikiRuntimeError(RuntimeError): """LLM client / runtime construction failed."""
  def build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:
      """Body moved from cli._build_triage_adapters (verified: wiki/cli.py:4611)."""
  def build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:
      """Body moved from cli._build_novelty_scorer (verified: wiki/cli.py:4671)."""
  def build_ingest_runtime(root: Path, config: WikiProjectConfig, store: BaseWikiStore,
                           sources: SourceCollectionManager, charter: Charter, charter_path: Path, *,
                           lightweight_model: str, model: str, fetch_timeout: float = 30.0) -> InboxRuntime:
      """Body moved from cli._build_ingest_runtime (verified: wiki/cli.py:4729) minus model-id resolution;
      raises WikiRuntimeError instead of click.ClickException."""
  # wiki/cli.py: _build_ingest_runtime keeps its signature, calls _resolve_ingest_model_ids then
  # runtime.build_ingest_runtime, converting WikiRuntimeError → click.ClickException (same message).
  # _build_triage_adapters / _build_novelty_scorer become aliases of the public functions.
  ```

### Module 4: Bookstore target
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/bookstore.py` (new)
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  class BookstoreTarget(IngestTarget):
      kind = UploadTargetKind.BOOKSTORE
      def __init__(self, config: BookstoreTargetConfig) -> None:
          """library_dir = Path(os.path.expandvars(config.library_dir)).expanduser().resolve();
          staging_dir = library_dir/'.uploads'."""
      async def available(self) -> tuple[bool, str]:
          """resolve_adapter(config.llm) (verified: bookstore/_llm.py:43) must return an adapter."""
      async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
          """Bookstore.add_book(staged_path, scope='project', title=, authors=, topics=, force=)
          (verified: bookstore/library.py:977); 'added'|'updated' → ADDED|UPDATED, 'skipped' → SKIPPED;
          BookstoreError → FAILED."""
  ```

### Module 5: Wiki target
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/wiki.py` (new)
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  class WikiTarget(IngestTarget):
      kind = UploadTargetKind.WIKI
      def __init__(self, config: WikiTargetConfig) -> None:
          """wiki_root resolved; staging_dir = wiki_root/'.parrot'/'uploads';
          charter_path = config.charter_path or wiki_root/'.parrot'/'charter.yaml'."""
      async def available(self) -> tuple[bool, str]:
          """Charter file exists and loads (load_charter, verified: wiki/charter.py:404); project config
          loads (load_effective_config, verified: wiki/project.py:1111); the runtime builds."""
      async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
          """acquire → router.triage(staged_path, text) (verified: wiki/triage.py:295) → admit only:
          entry.model_copy(update={'decision': 'admit', 'decision_source': 'auto'}) →
          orchestrator.ingest(str(staged_path), wiki_config, triage=entry,
          charter_version=charter.version, acquired=acquired) (verified: wiki/ingest.py:198);
          other actions → REJECTED_BY_TRIAGE with the briefing; IngestReport.status != 'ok' → FAILED;
          SQLite store → checkpoint()."""
  ```

### Module 6: PageIndex tree freshness
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (modifies)
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  class PageIndexToolkit(AbstractToolkit):  # verified: pageindex/toolkit.py:54
      def _tree_signature(self, tree_name: str) -> tuple[int, int] | None:  # new
          """(st_mtime_ns, st_size) of self._store._path_for(tree_name) (verified: pageindex/store.py:40);
          None when the file is missing."""
      def _load_tree(self, tree_name: str) -> dict[str, Any]:  # modifies, verified: toolkit.py:179
          """Cached tree when its signature is unchanged or the tree is inside an open batch
          (self._batch_depth); otherwise pop _trees/_search, evict the content-store cache
          (_content_store._cache_evict_tree, verified: pageindex/content_store.py:105) and reload."""
  ```

### Module 7: Integration config fields
- **Path**: `telegram/models.py`, `msteams/models.py`, `slack/models.py` (modify)
- **Depends on**: M1 (`KnowledgeUploadConfig`)
- **Interface Skeleton**:
  ```python
  # each @dataclass config gains:
  knowledge_upload: KnowledgeUploadConfig = field(default_factory=KnowledgeUploadConfig)
  # and each from_dict passes:
  knowledge_upload=KnowledgeUploadConfig.model_validate(data.get("knowledge_upload") or {}),
  ```
  Telegram keeps `max_document_size_mb` for the default path; the upload path
  uses `service.max_bytes(platform_cap_mb=20)`.

### Module 8: Telegram adapter
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/knowledge_upload.py` (new);
  `telegram/wrapper.py` (modifies)
- **Depends on**: M1, M7
- **Interface Skeleton**:
  ```python
  class TelegramKnowledgeUpload:
      """Registers /ingest_book and /ingest_wiki on the wrapper's router."""
      def __init__(self, wrapper: "TelegramAgentWrapper", service: KnowledgeUploadService) -> None: ...
      def register(self, router: Router) -> list[tuple[str, str]]:
          """Register Command('ingest_book'|'ingest_wiki') handlers (private chats) for DOCUMENT messages
          (caption) and TEXT replies to a document; returns menu entries for _add_platform_commands.
          Must be called BEFORE the default handle_document registration (verified: wrapper.py:333)."""
      async def handle(self, message: Message, target: UploadTargetKind) -> None:
          """_is_authorized(chat_id) (verified: wrapper.py:1044) → session = _get_user_session (verified:
          wrapper.py:1080) must be authenticated with nav_user_id → size check vs document.file_size →
          bot.get_file + bot.download_file into BytesIO → service.submit(request, notify=message.answer-based)."""
  def parse_ingest_args(text: str) -> dict[str, Any]:
      """shlex-based: --force, --title, --author (repeatable), --topic (repeatable)."""
  ```
  Wrapper: build the service (`await KnowledgeUploadService.from_config(...)`)
  lazily on first use or in the wrapper's async start hook when
  `config.knowledge_upload.enabled`; call `shutdown()` on stop.

### Module 9: MS Teams adapter
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/knowledge_upload.py` (new);
  `msteams/wrapper.py` (modifies)
- **Depends on**: M1, M7
- **Interface Skeleton**:
  ```python
  def register_knowledge_upload_commands(router: MSTeamsCommandRouter, wrapper: "MSTeamsAgentWrapper",
                                         service: KnowledgeUploadService) -> None:
      """router.register('ingest_book'|'ingest_wiki', handler) (verified: msteams/commands/__init__.py:56).
      Called next to agent_cmd_handler.register (verified: msteams/wrapper.py:182)."""
  async def _handle(turn_context: TurnContext, target: UploadTargetKind, ...) -> None:
      """Pick the first non-card attachment; prefer content['downloadUrl'] (file.download.info), else
      content_url + wrapper._get_attachment_token (verified: msteams/wrapper.py:964); enforce max_bytes while
      reading; email via TeamsInfo.get_member (unverified — check before use); conversation reference via
      TurnContext.get_conversation_reference (verified usage: msteams/commands/jira_commands.py:146);
      notify through wrapper.adapter.continue_conversation(ref, callback, config.client_id)
      (pattern verified: msteams/oauth_callback.py:127)."""
  ```

### Module 10: Slack adapter
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/slack/knowledge_upload.py` (new);
  `slack/wrapper.py` (modifies)
- **Depends on**: M1, M7
- **Interface Skeleton**:
  ```python
  class SlackKnowledgeUpload:
      def __init__(self, wrapper: "SlackAgentWrapper", service: KnowledgeUploadService) -> None: ...
      def register(self) -> None:
          """command_router.register('ingest_book'|'ingest_wiki', self.on_command)
          (verified: slack/commands/__init__.py:50) and wrapper.add_message_interceptor(self.intercept)
          (verified: slack/wrapper.py:586)."""
      async def on_command(self, payload: dict[str, Any]) -> dict[str, Any]:
          """Arm pending[(channel_id, user_id)] for slack_pending_window_s; ephemeral 'Now share the file'."""
      async def intercept(self, event: dict[str, Any]) -> bool:
          """Consume a message with files when its text starts with ingest_book/ingest_wiki or a pending
          window is armed for (channel, user); False otherwise."""
      async def _download(self, file_info: dict[str, Any], max_bytes: int) -> bytes:
          """aiohttp GET url_private_download with Bearer bot_token, streamed with a hard byte cap.
          Does NOT use files.download_slack_file (unsanitized dest name, MIME filter)."""
      async def _email(self, user_id: str) -> str | None:
          """users.info → user.profile.email (scope users:read.email)."""
  ```
  Wrapper change: run `_run_interceptors(event)` also before the assistant-mode
  DM dispatch (verified anchor: `slack/wrapper.py:288`), after authorization.
  Notification via `post_message(channel, text, thread_ts=…)` (verified:
  `slack/wrapper.py:645`).

### Module 11: Documentation
- **Path**: `docs/integrations/knowledge-upload.md` (new)
- **Responsibility**: configuration block, commands per platform, Slack app
  scopes (`files:read`, `users:read`, `users:read.email`, slash commands),
  Telegram login requirement, charter prerequisite, navigator-agent-server
  example.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_policy_username_or_group` | M1 | allowed by username only, by group only; case-insensitive |
| `test_policy_deny_by_default` | M1 | empty lists / `None` profile → denied |
| `test_safe_filename` | M1 | strips `../`, separators, control chars; keeps extension; empty → ValueError |
| `test_staged_file_deleted_on_success_error_cancel` | M1 | file gone after normal exit, exception and `CancelledError`; dir mode 0o700 |
| `test_sweep_staging` | M1 | leftovers removed |
| `test_submit_rejects_extension_and_size` | M1 | `.doc`, `.exe`, > max_bytes → INVALID, no job scheduled |
| `test_submit_denied_not_scheduled` | M1 | DENIED returned, audit log record emitted |
| `test_job_notifies_and_serializes_per_target` | M1 | two jobs same target never overlap (fake target with event); different targets overlap |
| `test_job_failure_becomes_failed_outcome` | M1 | target raises → FAILED notify, file deleted |
| `test_shutdown_cancels_jobs` | M1 | running job cancelled, staged file deleted |
| `test_get_profile_by_email` | M2 | match, case-insensitive, ambiguous → None (mock AsyncDB) |
| `test_build_ingest_runtime_public` | M3 | builds with fake adapters; error → WikiRuntimeError |
| `test_cli_ingest_runtime_wrapper` | M3 | CLI wrapper still raises `click.ClickException` with the same message |
| `test_bookstore_target_status_mapping` | M4 | added/updated/skipped/BookstoreError (Bookstore mocked) |
| `test_bookstore_target_same_name_updates` | M4 | same staged name, new bytes → `"updated"`, same book_id (real Bookstore, md file, no LLM) |
| `test_wiki_target_admit_only` | M5 | admit → orchestrator.ingest called with triage entry `decision_source="auto"`; archive/discard → REJECTED_BY_TRIAGE with briefing, ingest not called |
| `test_wiki_target_unavailable_without_charter` | M5 | missing charter → `available()` False |
| `test_load_tree_reloads_on_change` | M6 | rewrite tree file → next `_load_tree` returns new tree, `_search` evicted |
| `test_load_tree_batch_not_reloaded` | M6 | inside batch the in-memory tree is kept |
| `test_config_from_dict_knowledge_upload` | M7 | each of the 3 configs parses the block; absent → disabled defaults |
| `test_telegram_ingest_caption_and_reply` | M8 | caption command and reply-to-document both submit; default handle_document not invoked |
| `test_telegram_requires_nav_session` | M8 | unauthenticated / no nav_user_id → denied message |
| `test_parse_ingest_args` | M8 | quoting, repeatable flags |
| `test_teams_ingest_command_download_variants` | M9 | downloadUrl vs content_url+token; oversize aborted |
| `test_teams_no_attachment_usage` | M9 | command without attachment → usage help |
| `test_slack_intercept_text_prefix` | M10 | `ingest_book` message with file consumed |
| `test_slack_pending_window` | M10 | slash command then file within window consumed; after window not consumed |
| `test_slack_assistant_dm_runs_interceptors` | M10 | assistant-mode DM with file is intercepted |

### Integration Tests
| Test | Description |
|---|---|
| `test_upload_markdown_into_temp_bookstore` | real `Bookstore` on `tmp_path`, `.md` upload through the service → card present, staging dir empty |
| `test_upload_into_temp_wiki_with_fake_llm` | temp wiki project + charter + fake adapters returning admit → pages created; discard path creates none; staging empty |

### Test Data / Fixtures
```python
@pytest.fixture
def upload_config(tmp_path):
    return KnowledgeUploadConfig(
        enabled=True, allowed_usernames=["jlara"], allowed_groups=["curators"],
        bookstore=BookstoreTargetConfig(library_dir=str(tmp_path / "library")),
        wiki=WikiTargetConfig(wiki_root=str(tmp_path / "wiki")),
    )

@pytest.fixture
def curator_profile():
    return EmployeeProfile(user_id=1, username="other", groups=["curators"])
```
Tests live in `packages/ai-parrot-integrations/tests/knowledge_upload/` and
`packages/ai-parrot/tests/` (M2, M3, M6). No real LLM, Telegram, Teams or
Slack calls.

---

## 5. Acceptance Criteria

- [ ] AC1 — `ingest_book` / `ingest_wiki` work on Telegram (caption + reply), MS Teams (message with attachment) and Slack (text prefix + slash-command pending window).
- [ ] AC2 — Only `.pdf`, `.docx`, `.md`, `.markdown` are accepted; others get INVALID before any download when the platform reports the name.
- [ ] AC3 — Authorization: allowed iff username ∈ `allowed_usernames` OR groups ∩ `allowed_groups` ≠ ∅ (one global list per bot, both targets); empty lists deny everyone; identity from navigator-auth (Telegram `nav_user_id`; Teams/Slack email → `auth.vw_users`); unknown/ambiguous identity denies.
- [ ] AC4 — Telegram upload handlers refuse unauthenticated sessions even if `force_authentication` is false; the documented deployment sets `enable_login: true` and `force_authentication: true` on all four Odoo bots.
- [ ] AC5 — The original file never reaches `SessionFileStore`, the Telegram `tg_doc_` temp path, or the agent; after every job (success, failure, cancellation) the staging directory contains no file.
- [ ] AC6 — Bookstore ingest = `Bookstore.add_book`; same content → SKIPPED unless `--force`; same file name with new content → UPDATED with the same `book_id`.
- [ ] AC7 — Wiki ingest runs FEAT-402 triage first; only `admit` is ingested (`decision_source="auto"`); `archive`/gray/`discard` are rejected with the triage briefing; `--force` does not bypass triage.
- [ ] AC8 — Triage and ingest use `google:gemini-3.1-flash-lite` by default (same LLM as the Bookstore).
- [ ] AC9 — Without a charter the wiki target is unavailable: `ingest_wiki` is not registered/advertised and a reason is logged.
- [ ] AC10 — `max_size_mb` defaults to 10 on all three platforms and is enforced before download when the size is known and during download otherwise (Telegram additionally capped at 20).
- [ ] AC11 — The command acknowledges immediately; ingestion runs as a background job; the user is notified on completion/failure (Telegram reply, Teams proactive message, Slack `chat.postMessage`).
- [ ] AC12 — Jobs on the same target are serialized process-wide (several bot wrappers in one process); at most `max_concurrent_jobs` run at once.
- [ ] AC13 — Every attempt emits one structured audit log record (platform, username, target, filename, sha256, size, status, triage action, duration); no DB table.
- [ ] AC14 — An updated book is visible to already-running agents on their next read (PageIndex freshness check).
- [ ] AC15 — `wikitoolkit ingest` CLI behavior and error messages are unchanged after the runtime extraction.
- [ ] AC16 — Feature is opt-in: with no `knowledge_upload` block nothing is registered and existing behavior is unchanged.
- [ ] AC17 — All unit/integration tests in §4 pass; `ruff check` clean on touched files.
- [ ] AC18 — `docs/integrations/knowledge-upload.md` documents config, commands, Slack scopes, login requirement and the charter prerequisite.

---

## 6. Codebase Contract

> Verified against base commit `088d42869` (dev, 2026-10-09).

### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError      # library.py:178, :111
from parrot.knowledge.bookstore.config import LibraryLocation                  # config.py:31
from parrot.knowledge.bookstore._llm import resolve_adapter                    # _llm.py:43 (used by navigator-agent-server odoo_common.py)
from parrot.knowledge.wiki.charter import Charter, load_charter                # charter.py:311, :404
from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer     # triage.py:243, :67
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator                # ingest.py (ctor :164)
from parrot.knowledge.wiki.review import ManifestDocEntry                      # review.py:135
from parrot.knowledge.wiki.documents import DocumentAcquirer, DocumentRef, AcquiredDocument  # documents.py:481, :69, :119
from parrot.knowledge.wiki.inbox.processor import InboxRuntime                 # processor.py:43 (TYPE_CHECKING import at cli.py:52)
from parrot.knowledge.wiki.project import WikiProjectConfig, load_effective_config  # project.py:531, :1111
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                # toolkit.py:54
from parrot.knowledge.pageindex.store import JSONTreeStore                     # store.py:23
from parrot.auth.userinfo import UserInfoService, EmployeeProfile              # userinfo.py:77
from parrot.integrations.msteams.commands import MSTeamsCommandRouter          # msteams/commands/__init__.py:30
from parrot.integrations.slack.commands import SlackCommandRouter              # slack/commands/__init__.py:27
from botbuilder.core import TurnContext                                         # used in msteams/commands/jira_commands.py
```

### Existing Class Signatures
```python
# knowledge/bookstore/library.py
class Bookstore:                                                       # :178
    def __init__(self, locations, adapter=None, lightweight_model=None)  # :192
    self._toolkits: dict[str, PageIndexToolkit]                        # :211 (one per scope, lazy via _toolkit :233)
    async def add_book(self, file_path: str | Path, scope: str = "project", title: Optional[str] = None,
                       authors: Optional[list[str]] = None, topics: Optional[list[str]] = None,
                       force: bool = False, *, relate: bool = False) -> tuple[BookCard, str]:  # :977
    # path = Path(file_path).expanduser().resolve()  :1015 ; read_bytes + sha256 + catalog.find_by_sha :1024-1033
    # identical bytes, not force → (existing card, "skipped"); same path new bytes → "updated" (same book_id)
    # PDF without LLM → BookstoreError :1047 ; source_path=str(path) :1135, source_sha256 :1136
    # all reads of the file complete before add_book returns
# _FORMAT_BY_SUFFIX :57 → .pdf .md/.markdown .txt .epub .mobi .docx

# knowledge/bookstore/_llm.py
def resolve_adapter(llm_spec: Optional[str] = None, lightweight_model: Optional[str] = None
                    ) -> tuple[Optional[Any], Optional[str], Optional[Any]]:   # :43 → (adapter, light, client) | (None, None, None)

# knowledge/wiki/ingest.py
class WikiIngestOrchestrator:
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any, source_manager: SourceCollectionManager,
                 bookkeeper: WikiBookkeeper, store: Optional[BaseWikiStore] = None, sync_graph: bool = False) -> None:  # :164
    async def ingest(self, source_path: str, wiki_config: WikiConfig, *, triage: Optional[ManifestDocEntry] = None,
                     charter_version: Optional[str] = None, acquired: AcquiredDocument | None = None) -> IngestReport:  # :198
# IngestReport (:120): source_id, source_uri, pages_created, pages_updated, graph_nodes_created, duration_ms,
#   status: str = "ok", error: Optional[str]
# identity = str(Path(source_path).resolve()) for non-http (:294-299); add_source stats the file (:334)
# "discard" decisions record status="rejected", no pages (_record_discard :307-308)

# knowledge/wiki/triage.py
class IngestTriageRouter:                                              # :243
    def __init__(self, charter: Charter, adapter: PageIndexLLMAdapter, sources: SourceCollectionManager,
                 novelty_scorer: NoveltyScorer, *, heavy_adapter: PageIndexLLMAdapter | None = None,
                 max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES, allowed_suffixes: frozenset[str] | None = None) -> None:  # :262
    async def triage(self, path: Path, content: str, *, skip_duplicate_check: bool = False) -> ManifestDocEntry:  # :295

# knowledge/wiki/review.py
class ManifestDocEntry(BaseModel):                                     # :135
    proposed_action: Literal["admit", "archive", "discard"]           # :164
    decision_source: Literal["heuristic", "model", "human", "auto"]   # :167
    # decision: None until review/auto

# knowledge/wiki/documents.py
class DocumentRef: uri: str; is_url: bool = False; suffix: str = ""   # :69
class AcquiredDocument: ref; text: str; metadata; ebook_sections       # :119
class DocumentAcquirer:
    def __init__(self, *, fetch_timeout=30.0, max_bytes=100*1024*1024, cache_dir=None)  # :481
    async def acquire(self, ref: DocumentRef) -> AcquiredDocument       # :500

# knowledge/wiki/cli.py
def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:   # :4611
def _resolve_ingest_model_ids(lightweight_model_opt: str | None, model_opt: str | None) -> tuple[str, str]:  # :4645 (click.echo; stays in CLI)
def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:  # :4671
def _build_ingest_runtime(root, config, store, sources, charter, charter_path, *, lightweight_model_opt,
                          model_opt, fetch_timeout: float = 30.0) -> "InboxRuntime":  # :4729 (raises click.ClickException)
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore:   # :469
def _open_sources(root: Path, config: WikiProjectConfig, store: Optional[BaseWikiStore] = None) -> SourceCollectionManager:  # :526
def _checkpoint_if_sqlite(store: BaseWikiStore, label: str) -> None:       # :504 (SQLiteWikiStore.checkpoint())
def _resolve_charter_path(root: Path, charter_opt: str | None) -> Path:    # :4564 (default <root>/.parrot/charter.yaml)
# --auto (:5370-5372): entry.decision = entry.proposed_action; entry.decision_source = "auto"; then
#   orch.ingest(entry.source_uri, wiki_config, triage=entry, charter_version=charter.version, acquired=...)
# knowledge/wiki/vault_scan.py:58 VAULT_EXCLUDE_DIRS includes ".parrot"

# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                               # :54
    self._store = JSONTreeStore(storage_dir)                           # :114
    self._content_store = NodeContentStore(storage_dir, cache_size=content_cache_size)  # :115
    self._trees: dict[str, dict[str, Any]] = {}                        # :162
    self._search: dict[str, HybridPageIndexSearch] = {}                # :163
    self._batch_depth: dict[str, int] = {}                             # :164
    def _load_tree(self, tree_name: str) -> dict[str, Any]:            # :179
    async def delete_tree(self, tree_name: str) -> dict[str, Any]      # :398 (pops _trees/_search)
# knowledge/pageindex/store.py: class JSONTreeStore :23; def _path_for(self, tree_name: str) -> Path :40
# knowledge/pageindex/content_store.py: def _cache_evict_tree(self, tree_name: str) -> None :105

# auth/userinfo.py
class EmployeeProfile: user_id; username: str | None; email: str | None; groups: list[str] = []  # :64-71
class UserInfoService:                                                 # :77
    def __init__(self, dsn: str | None = None, cache_ttl: int = 600, cache_max_size: int = 500) -> None  # :88
    async def get_profile(self, user_id: Any) -> EmployeeProfile | None   # :148 (SELECT … FROM auth.vw_users WHERE user_id = $1)

# integrations/telegram/
@dataclass class TelegramAgentConfig                                   # models.py:39
    enable_login: bool = True (:83); force_authentication: bool = False (:85); max_document_size_mb: int = 20 (:128)
    @classmethod from_dict(cls, name, data) (:231)
class TelegramUserSession: nav_user_id (:52), nav_email, authenticated     # auth.py:44
# wrapper.py: _register_handlers :231; default DOCUMENT handler registered :333-338;
#   _add_platform_commands(entries) :368; _is_authorized(chat_id) :1044; _get_user_session(message) :1080;
#   _check_authentication(message) :1568; handle_document :3146 (writes tg_doc_ temp, never deleted)

# integrations/msteams/
@dataclass class MSTeamsAgentConfig: allowed_user_ids (:46); from_dict (:130); client_id   # models.py:15
class MSTeamsCommandRouter: register(command, handler) :56 (handler = async (turn_context) -> None); try_dispatch :74
# wrapper.py: router built :180-182; on_message_activity :547 — command dispatch :570 runs BEFORE the
#   SessionFileStore attachment loop :608-610; _handle_document_attachment :844; _get_attachment_token :964;
#   self.adapter (passed to MSTeamsOAuthNotifier :191)
# oauth_callback.py:127 await self._adapter.continue_conversation(conv_ref, _callback, self._app_id)

# integrations/slack/
@dataclass class SlackAgentConfig: bot_token (:54); allowed_user_ids (:60); from_dict (:108)   # models.py:29
class SlackCommandRouter: register(command, handler) :50 (handler = async (payload: dict) -> dict|None); dispatch :68
# wrapper.py: MessageInterceptor = Callable[[Dict[str, Any]], Awaitable[bool]] :27; router :125;
#   assistant-mode DM dispatch :288 (bypasses interceptors); auth + interceptors :305-322;
#   _handle_command :340; add_message_interceptor :586; _run_interceptors :595; _slack_api(method, payload) :609;
#   post_message(channel, text, blocks=None, thread_ts=None) -> Optional[str] :645
# files.py: download_slack_file(file_info, bot_token, download_dir=None, allowed_types=None) :68 — NOT reused
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `BookstoreTarget` | `Bookstore.add_book()` | method call | `bookstore/library.py:977` |
| `WikiTarget` | `build_ingest_runtime()` → `IngestTriageRouter.triage()` / `WikiIngestOrchestrator.ingest()` | method call | `wiki/triage.py:295`, `wiki/ingest.py:198` |
| `resolve_profile` | `UserInfoService.get_profile()` / `get_profile_by_email()` | method call | `auth/userinfo.py:148` |
| `TelegramKnowledgeUpload` | `router.message.register(..., Command(...))` | aiogram handler | `telegram/wrapper.py:333` |
| Teams handler | `MSTeamsCommandRouter.register()` | router | `msteams/commands/__init__.py:56` |
| Slack handler | `SlackCommandRouter.register()`, `add_message_interceptor()` | router / interceptor | `slack/commands/__init__.py:50`, `slack/wrapper.py:586` |

### Does NOT Exist (Anti-Hallucination)
- ~~Any upload-to-knowledge feature in Telegram/Teams/Slack~~; ~~a shared cross-platform command registry~~; ~~command handlers that receive user identity~~
- ~~Groups/roles in `TelegramUserSession`~~ or any integration session
- ~~`UserInfoService.get_profile_by_email` / lookup by username~~ (M2 adds the email one)
- ~~Bookstore write tool or HTTP endpoint~~ (`BookstoreToolkit` is read-only)
- ~~A logical-source / `source_uri` override on `Bookstore.add_book` or `WikiIngestOrchestrator.ingest`~~ — identity is the resolved path
- ~~A public, click-free ingest runtime builder~~ (M3 adds `wiki/runtime.py`); ~~`wiki/supervised*.py`, `ingest_one`, `triage_and_ingest`~~
- ~~A public evict/reload API on `PageIndexToolkit`~~ (only `delete_tree`/`rename_tree` pop the cache)
- ~~`wikitoolkit bookstore` subcommand~~ (CLI is `bookstore` / `parrot bookstore`)
- ~~PDF/TXT Bookstore ingest without an LLM~~; ~~wiki ingest with `pageindex_toolkit=None`~~; ~~`.doc` support~~
- ~~Slack file download in the wrapper~~ (`download_slack_file` is never called); ~~`SlackAgentConfig.commands` / Telegram `enable_attachments` being used~~
- ~~TTL/cleanup on `SessionFileStore`~~; ~~cleanup of Telegram `tg_doc_` temp files~~
- ~~`TeamsInfo` usage anywhere in `parrot.integrations`~~ (library API, unverified here)
- ~~An editorial charter for `odoo-sop`~~; ~~Teams/Slack config for the Odoo agents~~
- ~~Background ingestion jobs~~ anywhere in the codebase

### Edit Sites (Blueprint Anchors)

Verified against: `088d42869`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/models.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/policy.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/staging.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/service.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/base.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/bookstore.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/wiki.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/userinfo.py` | MODIFY | `    async def get_profile(self, user_id: Any) -> EmployeeProfile \| None:` | `userinfo.py:148` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:` | `cli.py:4611` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:` | `cli.py:4671` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `def _build_ingest_runtime(` | `cli.py:4729` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    def _load_tree(self, tree_name: str) -> dict[str, Any]:` | `toolkit.py:179` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `    max_document_size_mb: int = 20` | `models.py:128` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `            max_document_size_mb=int(data.get('max_document_size_mb', 20)),` | `models.py:296` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/knowledge_upload.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `        # Document messages (private only for now)` | `wrapper.py:333` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `    allowed_user_ids: Optional[List[str]] = None` | `models.py:46` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `            allowed_user_ids=data.get("allowed_user_ids"),` | `models.py:155` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/knowledge_upload.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `        agent_cmd_handler.register(self._command_router)` | `wrapper.py:182` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` | MODIFY | `    allowed_user_ids: Optional[List[str]] = None` | `models.py:60` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` | MODIFY | `            allowed_user_ids=data.get("allowed_user_ids"),` | `models.py:126` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/knowledge_upload.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | `        self._command_router = SlackCommandRouter()` | `wrapper.py:125` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | `            if event_type == "message" and event.get("channel_type") == "im":` | `wrapper.py:288` | 1 |
| `docs/integrations/knowledge-upload.md` | CREATE | — | — | — |

Tests (CREATE): `packages/ai-parrot-integrations/tests/knowledge_upload/` (M1, M4, M5, M7–M10),
`packages/ai-parrot/tests/` files for M2, M3, M6.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; aiohttp for every HTTP download; never `requests`/`httpx`.
- Pydantic v2 for the new models; the existing integration configs stay
  `@dataclass` and only gain one field + `from_dict` parsing.
- `self.logger` / `logging.getLogger(__name__)`; audit records use one logger
  name `parrot.integrations.knowledge_upload.audit` with `extra=` fields.
- Blocking filesystem work (`write_bytes`, `unlink`, `chmod`) through
  `asyncio.to_thread`.
- Lazy imports of `parrot.knowledge.*` inside targets so importing the
  integrations does not pull the knowledge stack when the feature is disabled.
- Error messages to users never echo allow-lists, paths or stack traces.

### Known Risks / Gotchas
- **Path-derived identity** (both planes): stable staging names make
  re-uploads replace; two different documents uploaded under the same file
  name replace each other — documented behavior, the user decided "new version
  replaces".
- **Stale `source_path`**: cards and the wiki manifest point at a staging path
  whose file is deleted; `bookstore card --refresh` and `wikitoolkit
  reingest` on those sources cannot re-read them — re-upload instead.
- **Telegram Bot API**: bots cannot download files > 20 MB; effective cap is
  `min(max_size_mb, 20)`.
- **Teams attachments**: personal-chat files arrive as
  `application/vnd.microsoft.teams.file.download.info` with a pre-authenticated
  `content["downloadUrl"]`; channel files may need the bot token. Verify both
  against a real tenant; size may be unknown before download → streamed cap.
- **Teams identity**: `TeamsInfo.get_member` needs the bot to be in the
  conversation's roster; guest users may lack an email → deny.
- **Slack**: `users:read.email` scope required; file text cannot start with
  `/` (the client treats it as a slash command) — hence the bare
  `ingest_book` prefix; the assistant-mode DM path currently skips
  interceptors — M10 must run them there too without changing dev-loop
  interceptor semantics (first `True` wins).
- **Process restart** mid-job: the job is lost; the startup sweep deletes the
  staged file; the user re-uploads (originals are intentionally not kept).
- **LLM-heavy work in the serving process**: bounded by
  `max_concurrent_jobs` and the per-target lock.
- **Prompt injection inside documents** affects only ingested content, never
  authorization (the LLM is not in the trust path).
- **FEAT-539** (`contracts-card-ontology`, open) touches
  `bookstore/library.py`; this spec does **not** modify that file anymore
  (the `upload://` rewrite was dropped), so there is no conflict.
- **`wiki/cli.py`** is large and actively edited: M3 keeps the CLI functions'
  names and signatures (wrappers), minimizing merge risk.

### Deployment (navigator-agent-server, out of repo)
```yaml
# env/integrations_bots.yaml — each of OdooSupport, OdooSOP, OdooQA, OdooHelpdesk
enable_login: true
force_authentication: true
knowledge_upload:            # on the curator bot(s)
  enabled: true
  allowed_usernames: [jlara]
  allowed_groups: [odoo_curators]
  max_size_mb: 10
  bookstore: {library_dir: "${ODOO_LIBRARY_DIR}"}
  wiki: {wiki_root: "/app/agents/odoo_wiki"}
```
Plus the user-authored `agents/odoo_wiki/.parrot/charter.yaml`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiogram` | existing | Telegram `get_file` / `download_file` |
| `botbuilder-core` | existing | `TurnContext`, `TeamsInfo`, `continue_conversation` |
| `aiohttp` | existing | Teams/Slack downloads |
| `ai-parrot-loaders` | existing (optional) | DOCX/PDF text for the wiki acquirer and Bookstore DOCX |

No new dependencies.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-647-teams-telegram-uploader-bookstore`;
  each task gets its own sub-worktree from the `sdd-coder` engine.
- **Module dependency graph**:
  - M1 → M2 (`resolve_profile` calls `get_profile_by_email`)
  - M4 → M1 (`IngestTarget`, models)
  - M5 → M1, M3 (`build_ingest_runtime`)
  - M7 → M1 (`KnowledgeUploadConfig`)
  - M8, M9, M10 → M1, M7
  - M11 → M8–M10 (documents final command syntax)
  - M2, M3, M6 have no inbound dependency and can start immediately, in parallel.
- **Shared files**: none across modules — M7 touches the three `models.py`
  files, M8/M9/M10 touch the three `wrapper.py` files.
- **Exclusive resources**: none (no lockfile, migration or extension rebuild).
- **Cross-feature dependencies**: none blocking (FEAT-539 no longer overlaps).

---

## 8. Open Questions

- [x] Flow type / base branch — *Resolved in brainstorm*: feature → dev
- [x] How is the destination chosen? — *Resolved in brainstorm*: explicit commands (`/ingest_book`, `/ingest_wiki`)
- [x] Identity source — *Resolved in brainstorm*: navigator-auth session; Telegram bots with forced login; Teams/Slack mapped by email to `auth.vw_users`
- [x] Ingest depth — *Resolved in brainstorm*: same as CLI; wiki uses full `ingest_source` (LLM) — realized as the FEAT-402 orchestrator path
- [x] Execution model — *Resolved in brainstorm*: in-process asyncio task + completion notification, per-target lock
- [x] Platforms in v1 — *Resolved in brainstorm*: Telegram, Teams and Slack
- [x] Code location — *Resolved in brainstorm*: generic in ai-parrot; navigator-agent-server only config
- [x] Duplicates — *Resolved in brainstorm*: skip same sha256, `--force` to re-ingest, new version replaces
- [x] Username/group rule — *Resolved in brainstorm*: OR — a matching username or a matching group is enough
- [x] Forced login scope — *Resolved in brainstorm*: forced login on all four Odoo bots for security, even if only one acts as "curator"
- [x] Wiki filtering — *Resolved in brainstorm*: apply the FEAT-402 charter-driven triage filter before ingesting
- [x] Audit trail — *Resolved in brainstorm*: logs only
- [x] Size limits — *Resolved in brainstorm*: configurable size limit on all three platforms; 10 MB default
- [x] Triage gray zone / `archive` — *Resolved in brainstorm*: rejected with the triage briefing as explanation; `--force` does not bypass triage
- [x] `odoo-sop` charter authorship — *Resolved in brainstorm*: the user writes it; not a deliverable of this feature
- [x] Allow-list scope — *Resolved in brainstorm*: one global list (usernames + groups) per bot, shared by both targets
- [x] Wiki/triage LLM — *Resolved in brainstorm*: reuse the bookstore's `google:gemini-3.1-flash-lite`
- [ ] Teams: confirm on a real tenant which attachment shape (`downloadUrl` vs `content_url`+token) personal and channel uploads use — *Owner: implementer (M9)*
- [ ] Slack: `users.info` via the existing `_slack_api` (JSON POST) or a form-encoded/GET call — verify during M10 — *Owner: implementer (M10)*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (brainstorm status is `exploration`, not `accepted`) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-09 | Jesus Lara (with Claude) | Initial draft from brainstorm; `upload://` rewrite replaced by stable staging paths after verifying path-derived identity |
