# Changelog

All notable changes to AI-Parrot are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.0.5] — 2026-09-20 — SDD tooling, CLI agent UI and client reliability

Twelve core-line distributions move to `1.0.5`. The sixteen satellites
(`ai-parrot-client-*`, `ai-parrot-openlit-bridge`) move to `0.2.5` and are
re-pinned to `ai-parrot>=1.0.5`.

Code changed in eight distributions: `ai-parrot` (185 files),
`ai-parrot-tools`, `ai-parrot-integrations`, `ai-parrot-client-google`,
`ai-parrot-server`, `ai-parrot-client-jev`, `parrot-formdesigner`,
`navrules`. The rest are version-only bumps.

### Added

- **FEAT-573: interactive `parrot agent <agent_id>` CLI.** The agent REPL
  becomes a real terminal application — usable composer, readable
  conversation rendering, discoverable commands and visible progress.
- **FEAT-563: scoped test selection.** The SDD cycle no longer runs all
  ~2,900 `test_*.py` modules; tasks select the tests that cover their scope,
  with guard-bypass checks closed by code review.
- **FEAT-564: video-reel Omni/Veo reliability.** Owner-checked job polling
  and artifact delivery in `GoogleGenAIClient.generate_video_reel`; the owned
  async Veo client is now closed on every exit path.
- **FEAT-565: autonomous planogram compliance.** `examples/planogram/
  planogram_check.py` runs the compliance algorithm end to end.
- **FEAT-570: local-MCP toolkit exposure.** Builtin-consumer audit, a
  cross-host command matrix and a no-secret integration test on top of the
  FEAT-485/556 local-MCP machinery.
- **FEAT-582: worktree-aware `/sdd-status`.** Task state is now read from the
  feature's worktree, not only from the per-spec index on `dev`; `/sdd-next`
  gains worktree progress annotations.
- **FEAT-577 / FEAT-576: grounded, scoped SDD specs.** Specs record which
  project and part of the codebase they concern, and spec authoring is
  grounded in a brainstorm/proposal.
- **FEAT-579: `invoke()` lifecycle telemetry** on the OpenAI-base clients,
  wiring `BeforeClientCallEvent` / `AfterClientCallEvent` /
  `ClientCallFailedEvent` through the invoke path.
- **FEAT-580 (15/16 tasks): LSP evidence for SDD seats.** Bounded LSP
  framing with a scripted fake server, Pyright process ownership, versioned
  diagnostics, hash-verified definition/reference tools, checkpoint
  diagnostics and a bounded CLI pilot runner. TASK-3514 remains in progress.

### Changed

- **FEAT-562 CI remediation closed out** — `test-core` workspace install and
  the drifted-test repairs are complete.
- **sdd-coder** requires strong-model seats for `unknown`-complexity tasks.
- **`parrot codex install`** no longer accepts `--toolkits` /
  `--all-toolkits`.
- **FEAT-571 memory-dynamics** landed as research spikes (attribution
  precision, brain-page state/lineage) rather than shipped behaviour, plus a
  real repair to `UnifiedMemoryManager` episodic recording.

### Fixed

- **Security (CWE-209):** video-reel error responses no longer expose stack
  traces.
- **sdd-coder:** pool-based retry crashed on the native seat; retry-label
  eligibility now fails closed (TASK-3554).
- **sdd-worker:** sandboxed Bash calls are bounded, `aiosqlite` threads no
  longer leak, and a worktree sandbox may administer sibling worktrees.
- **`/sdd-done`** refuses `--merge` and `--sync-down` from inside a worktree.
- **jev client:** session timeout is enforced and the answer kind
  cross-checked.
- **`GoogleGenAIClient`** API-key resolution.
- **CLI console** TTY detection.
- **Agent methods** are exposed correctly as MCP tools.
- **CI `test-core`:** optional `duckduckgo-search` and `arxiv` imports are
  guarded so core imports without those extras.
- **`wikitoolkit status`** hints when the `sqlite3` CLI is missing.

### Docs

- SDD specs and task graphs landed for in-flight features: FEAT-572
  (`/sdd-fix` ledger lane, 10/13), FEAT-574 (planogram pipeline),
  FEAT-578 (spec wiki ADR), FEAT-581 (agentic E2E testing).

---

## [1.0.4] — 2026-09-17

Twelve core-line distributions move to `1.0.4`. The sixteen satellites
(`ai-parrot-client-*`, `ai-parrot-openlit-bridge`) move to `0.2.4` and are
re-pinned to `ai-parrot>=1.0.4`.

### Fixed

- **`wikitoolkit` crashed at startup in every installed copy** (hotfix PR
  #1410). `parrot.knowledge.wiki.ledger.sdd_ingest` imported the repo-local
  `scripts.sdd.sdd_meta`, which no wheel ships. The parser now lives in
  `parrot.knowledge.wiki.ledger.sdd_meta` (`scripts/sdd/sdd_meta.py` is a
  re-export shim), and the CLI imports `SDDGraphIngest` lazily in the two
  ledger commands that use it. New guard test: no `packages/*/src` module may
  import `scripts.*`.
- **parrot-formdesigner:** same packaging bug — `tools/snippet_authoring`
  imported `scripts.check_snippet_conformance`. The gate moved to
  `parrot_formdesigner.services.snippets.conformance` (old path kept as shim).
- **`wikitoolkit ledger open`** on a read-only shared ledger now reports
  "NOT filed" instead of raising.
- **Crew execution history handler:** the authenticated user id was silently
  dropped (`await self.session()` raised under `@user_session()`), so a
  client-supplied `user_id` always won.
- **`parrot.tools` redirector** aliased every `parrot_tools.*` module onto
  `parrot.tools.*`, clobbering core `parrot.tools.abstract` once any
  redirected tool was imported.
- **NavigatorToolkit** could not be constructed (merge resurrected a second
  `super().__init__` without `dsn`).
- **CrewExecutionDocument** dropped FlowResult's `infographic` key.
- **Planogram endcap:** a failed illumination check crashed detection.
- **`parrot.interfaces.http`:** unused top-level `googleapiclient` imports
  broke core import without that optional dependency.
- **CI:** `test-core` installs the whole workspace; ~200 drifted tests
  repaired, optional-extra / live-service tests skip cleanly.

### Changed

- **BREAKING — FEAT-558: `QuerysourceToolkit` replaces `QSourceTool`.**
  `parrot_tools/qsource.py` is removed (hard cut). The new
  `parrot_tools.querysource` toolkit offers `list_slugs`, `describe_slug`,
  `execute_slug` (typed conditions), `run_multiquery` / `save_multiquery`,
  `list_components`, `validate_pipeline` and `get_dialect_reference`, with
  tenant guarding over `public.queries` and bounded JSON-safe results.
  The `ai-parrot-tools[db]` extra now requires `querysource>=4.5.11`.
- **sdd-codereview / sdd-worker** prompt updates.

### Docs

- SDD specs: FEAT-563 (scoped-test-selection), FEAT-564
  (video-reel Omni/Veo reliability).

---

## [1.0.3] — 2026-09-17

Twelve core-line distributions move to `1.0.3`. The sixteen satellites
(`ai-parrot-client-*`, `ai-parrot-openlit-bridge`) move to `0.2.3` and are
re-pinned to `ai-parrot>=1.0.3`.

### Added

- **FEAT-561: Task complexity measurement for sdd-coder.** Typed complexity
  evidence/policy/response contracts, Ruff+wiki+scope+dependency evidence
  collection, deterministic complexity evaluation, complexity-restricted
  dispatch and routing, MCP diagnostics surface, and measurable task contracts
  in both SDD authoring hosts.
- **FEAT-559: Execution pool suspensions for sdd-coder.** Private execution
  pool with atomic admission, durable suspension records with strict ledger
  replay, failure-classified dispatch gating, execution lifecycle (begin/end)
  with history-gated startup, execution attribution in telemetry and review
  history, and execution lifecycle MCP tools.
- **FEAT-560: Exclusive-task wave scheduling in dev-loop.** Shared
  exclusive-wave partition helpers, dispatch exclusive tasks alone in pool
  rounds, and parallel-width pool sizing from the task graph.
- **FEAT-526: Meta (Llama) LLM client.** `ai-parrot-client-meta` wired into
  the client satellite matrix with `search_tools` mapped to native
  `tool_search`.
- **FEAT-540: GraphIndex core-seams** — spec approved + 13 tasks committed
  (implementation pending).
- **Configurable infographic theme** on `CrewDefinition`/`AgentCrew`.

### Fixed

- **Security:** upgrade Vite 5→6, svelte-vite-plugin 4→5 (CVE-2026-53571);
  remove chromadb dependency (CVE-2026-45833/45831/45830).
- **FormDesigner:** upload gates rejected every file the presets allow;
  fixed-format text labeling; image-pair count gate; fourth gate exact-match
  defect.
- **Codex dispatch stdin isolation** (hotfix PR #1391): isolated Codex stdin
  and bounded subprocess diagnostics with offline regression suite.
- **CI:** declare `tqdm` as core dependency; install wiki stack in
  `test-wiki-extras`.
- **sdd-worker:** restore FEAT-543 delegated step; scope FEAT-549 absence
  tests; protect shared environments from worker mutations.
- **F4: Telegram/CLI token persistence.** `SessionVault` rejected `:` in key
  names, so `VaultTokenSync.store_tokens()` silently stored nothing (the error
  was swallowed). Vault keys may contain `:` now and the tokens are persisted.

### Changed

- **BREAKING — Vault crypto hardening (FEAT-099).** Requires
  `navigator-session>=1.0.0` and the offline vault migration
  (`navigator-vault migrate`; see navigator-session
  `docs/vault/migration-runbook.md`).
  - `parrot.security.credentials_utils` seals credentials with envelope v2
    bound to their document and field: `encrypt_credential(credential, context,
    keyring)` / `decrypt_credential(encrypted, context, keyring)` with
    `credential_context(user_id, name)` and `llm_key_context(user_id, provider)`.
    A credential copied to another user, name or provider no longer decrypts.
  - `parrot.security.vault_utils.get_vault_keyring()` replaces `load_vault_keys()`,
    which was removed.
  - `users_bots.mcp_config` / `tools_config` bind their context through AEAD
    instead of the in-plaintext `_ctx` envelope.
  - `user_credentials`, `user_llm_keys` and `users_bots` are registered as vault
    targets for rotation and migration.
  - `VaultTokenSync.read_tokens_result()` distinguishes missing from unreadable
    tokens; integrations report `status: needs_reconnect` when stored tokens
    cannot be used.
- Navigator stack deps pinned to Python 3.13+ builds.

---

## [1.0.2] — 2026-09-15

Twelve core-line distributions move to `1.0.2`. The sixteen satellites
(`ai-parrot-client-*`, `ai-parrot-openlit-bridge`) move to `0.2.2` and are
re-pinned to `ai-parrot>=1.0.2`.

### Added

- **FEAT-566: Shared SDD work ledger.** An append-only, atomic ledger log
  (`wikitoolkit ledger` CLI group + MCP tools) that ingests SDD spec/task
  graphs, reduces events with a replay cursor and atomic claim, and adds
  federation overlay namespace routing so ledgers from different repos don't
  collide. Wired into `/sdd-start`, `/sdd-next`, `/sdd-done`, and Claude/Codex/
  Antigravity review twins; a worktree structural-hook guard installs it
  post-merge. Retrofitted with async I/O and fsync durability.
- **FEAT-557: SQLite reliability for wikitoolkit.** A `SQLitePragmaPolicy`
  model and typed `WikiStoreBusy` error, a `_open`/`_read`/`_write` connection
  policy using `BEGIN IMMEDIATE`, non-fatal WAL checkpoints, and a busy
  timeout with explicit write transactions on `SourceCollectionManager`. All
  21 store call sites migrated off the old `_connect` path. `wikitoolkit
  status` gains a SQLite diagnostics block, and a multiprocess contention
  test covers the read path.
- **FEAT-551: MS Teams FormDesigner renderer.** New `TeamsFormRenderer` and
  `TeamsSubmitEnvelope`, a `_formdesigner` branch in
  `MSTeamsAgentWrapper._handle_card_submission`, bot-side pure submit
  helpers, and Teams upload-field posture (`Action.OpenUrl` +
  `RenderWarning`, since Teams cards can't accept file uploads directly).
  Registered via `setup_form_api` with tenant pass-through. Existing
  `AdaptiveCardRenderer` output is unchanged (verified via a byte-identical
  golden fixture); its hooks are now overridable for renderer subclasses.
- **A2UI / report charts.** Combined bar+line charts, a KPI card that states
  what its number means (including "no good direction" metrics), and a
  chart key rendered in words under the chart instead of only in color.

### Fixed

- **Printed/exported reports:** charts now size from a CSS box instead of
  the measuring moment, keep their proportion instead of being boxed,
  survive being printed, and no longer waste whole sheets or force
  horizontal scrolling on a phone-width table. The trend line, KPI values,
  and chart grid column count now match between the live app and the
  exported/print surface.
- **hotfix/WIKI-FTS-RESCAN:** external-content FTS5 indexing so re-ingesting
  a wiki source no longer rescans the entire index.
- **ci(release):** restored the eight client-satellite publish legs that had
  dropped out of `release.yml`.
- **stores/kb:** dropped an unused `duckdb` import and repaired the stale
  tests it was masking.

---

## [1.0.1] — 2026-09-13

Everything in this release is additive or opt-in. No public API was removed.
Twelve core-line distributions move to `1.0.1`. The sixteen satellites
(`ai-parrot-client-*`, `ai-parrot-openlit-bridge`) move to `0.2.1` and are
re-pinned to `ai-parrot>=1.0.1`.

### Added

- **FEAT-550: Token budgets for Bedrock and Mantle.** New `parrot.clients.budget`
  entry module: an atomic `QuestionBudget` ledger, `BudgetScope` / `BudgetRegistry`,
  and an `AbstractClient` budget gate. Also adds `BedrockBudgetAdapter` and
  `MantleBudgetAdapter` (opt-in), with per-attempt reservation, a no-retry
  transport and tools-disabled finalization. When the budget runs out, the caller
  gets a partial `AIMessage` instead of an exception.
  `InvokeResult.budget_report` is new. Calls without a budget are unaffected.
- **FEAT-542: LanceDB vector store** (`ai-parrot-embeddings[lancedb]`). Exact
  cosine search, model-free full-text search and native hybrid search. Mutations
  are process-safe. Includes a fully offline local-agent profile.
- **FEAT-539: Contracts card ontology.** Typed contract cards in a Postgres
  catalog, O365 SharePoint/OneDrive delta ingestion, and GraphIndex temporal
  publishing. Answers go through a citation and claim verification gate. Adds a
  ReAct `ContractsAgent`, renewal and obligation reports, and an operator CLI.
- **FEAT-538: Durable task memory for `WorkingMemoryToolkit`.** Opt-in. Task,
  plan and decision journals, versioned artifacts and evidence pins, bounded
  recall injected into Stage 2 rendering, and a PostgreSQL durable backend with
  retention.
- **FEAT-459: Custom code in form builder** (`parrot-formdesigner`). Snippet and
  manifest models; git and tenant-DB snippet sources with a tenant approval
  service; a tier router over subprocess (tiers 1–2) and gVisor (tiers 3–4)
  worker pools; a `HostBroker`; a Web Worker runtime with a TS bundler; and an
  LLM authoring surface. Existing `@register_form_event` handlers are unchanged.
- **FEAT-544: A2UI form output renderer.** `A2UIFormRenderer` is registered as
  the `a2ui` render format. The form `.../data` and `.../validate` endpoints are
  now dual-wire: they accept A2UI action envelopes as well as the existing format.
- **FEAT-535: Tenant visibility for UI surfaces.** New `SurfaceScope` /
  `SurfaceScopeResolver`, scope-aware listing, and a visibility `PATCH`. Existing
  rows read as `private`.
- **FEAT-536 / FEAT-537: VoiceBot avatars.** LiveAvatar dual output (Gemini/Nova
  through real tools) in the Voice UI. Multi-room HeyGen broadcast mode:
  `BroadcastSession`, a Redis-backed cross-worker registry, floor control, and
  the voice-broadcast HTTP/WebSocket API.
- **FEAT-543: Tool optimizations.** New toolkits `LocalGitToolkit`,
  `BoundedSourceToolkit` and `TargetedWriterToolkit` (hash-gated `writer_apply`
  with a journal and rollback). Adds opt-in PreToolUse read guards for Claude Code
  and Codex, and `ToolkitSection.llm_kwargs`.
- **FEAT-555: Dev-loop in Slack.** New `/devloop` Slack command, confirm and gate
  cards, a live status card, and a headless `parrot devloop run --headless` child
  mode. Installable via the `devloop` extra.
- **FEAT-549: `sdd-coder` orchestrator** behind the `parrot-sdd-coder` MCP server.
  It dispatches one task per sub-agent across a roster of different model seats.
  Adds `GeminiOpenAICompatClient` and the `google-compat` dev-loop backend.
- **FEAT-554: sdd-coder attempt telemetry.** An append-only telemetry sink, an
  observational token-budget mode, and an analysis script for tuning budgets.
- **FEAT-553: Shared coder conventions.** New `codebase-conventions.md`, injected
  into every dispatch prompt. A ruff `TID251` banned-import gate now runs on sdd-coder
  attempts.
- **FEAT-556: `parrot claude install` enables MCP servers automatically.** It
  seeds `.parrot/mcp-toolkits.yaml` (opt-in via `--toolkits` / `--all-toolkits`)
  and approves managed servers in `.claude/settings.local.json`. Codex and Google
  installers get the same behaviour.
- **FEAT-548: Observability.** Ships an AI-Parrot usage and cost Grafana dashboard.
  The `[observability]` env block now targets Prometheus instead of OpenLIT.
- **FEAT-494:** Fable models in the catalog, plus a `research_primary` model role.

### Changed

- **Dev-loop:** the default in-process turn budget rises from 24 to 40 (FEAT-553).
- **SDD tooling:** `/sdd-task` no longer creates worktrees. The implementing lane
  creates them through `python -m scripts.sdd.ensure_worktree` (FEAT-552).
  `/sdd-spec` gains an optional Codex design-research cross-check (FEAT-545,
  hardened in FEAT-546).

### Fixed

- `ClientCallFailedEvent` is now emitted on every client error path (FEAT-548).
- Voice: reply text is no longer duplicated, Gemini Live token usage is reported,
  and playback is gapless. A participant who leaves no longer strands their seat.
- `ui_surfaces` jsonb columns are no longer double-encoded. Hyphenated A2UI
  renderer ids now resolve to the right module.
- Wiki: `~` is escaped in ArangoDB document keys.
- The missing `ContractsToolkit` entry is now registered.
- The TASK-ID collision checker no longer crashes on hotfix ids.
- sdd-coder: native sub-worktrees are kept until they are merged, and a merge that
  did not land is never reported as done.
- `codex exec` no longer receives the unsupported `--ask-for-approval` flag.

---

## [1.0.0] — 2026-09-07 — First stable release

**First stable release.** `ai-parrot` and its eleven sibling distributions —
`ai-parrot-server`, `-tools`, `-loaders`, `-embeddings`, `-pipelines`,
`-visualizations`, `-integrations`, `-advisors`, `parrot-formdesigner`,
`navrules` and `parrot-codec` — all move to `1.0.0` together. The fifteen
`ai-parrot-client-<provider>` satellites and `ai-parrot-openlit-bridge` stay on
their own `0.2.0` line; they were first published two days ago and are
versioned independently of the core.

`0.29.0` was version-bumped in the tree (`c390e9e56c`) but never tagged or
published — PyPI goes `0.28.1` → `1.0.0`. Everything documented under the old
`[0.29.0]` heading (FEAT-520 … FEAT-526) therefore reaches users **for the
first time here**, and has been folded into this section rather than left as a
release nobody can install.

### Breaking Changes

#### FEAT-523: PEP 420 LLM clients — every provider ships from its own `ai-parrot-client-<provider>` satellite

Core `ai-parrot` no longer bundles any provider client. Each provider is a
separate distribution — a PEP 420 namespace package under
`parrot.clients.<provider>` that registers itself with `LLMFactory` through
the `parrot.clients` entry-point group. Hard cut: no deprecation shims.

Spec: `sdd/specs/pep-420-llm-clients.spec.md`.

**15 new distributions**: `ai-parrot-client-openai`, `-anthropic`,
`-google`, `-amazon`, `-meta`, `-gemma4`, `-hf`, `-groq`, `-grok`, `-zai`,
`-nvidia`, `-moonshot`, `-openrouter`, `-local`, `-vllm`.

- **Extras install satellites.** `ai-parrot[anthropic]`, `[openai]`,
  `[google]`, `[groq]`, `[bedrock-native]`, … each pull the matching
  satellite; `ai-parrot[llms]` pulls all 15. `openai` / `tiktoken` stay core
  dependencies because `OpenAIBaseClient` stays in core (subclassed by seven
  satellites).
- **`LLMFactory.create()` for a provider whose satellite is not installed
  raises `ImportError` naming the distribution to install.**
- **Module renames** (callers updated in-feature):
  `parrot.clients.gpt` → `parrot.clients.openai`;
  `.claude` / `.claude_agent` / `.claude_agent_bridge` / `.anthropic_backends`
  → `.anthropic`; `.bedrock` + `.nova` → `.amazon`; `.live` → `.google.live`;
  `.localllm` → `.local`; `gemma4`, `hf`, `groq`, `grok`, `zai`, `nvidia`,
  `moonshot`, `openrouter`, `vllm` become `clients/<provider>/` folder
  subpackages (`{__init__,client,models}.py`).
- **Provider enums left `parrot.models`.** Every `parrot.models.<provider>`
  enum now lives in `parrot.clients.<provider>.models`;
  `parrot/models/{openai,claude,groq,localllm,moonshot,nvidia,openrouter,zai,bedrock_models}.py`
  are deleted. `LiveVoiceResponse` moved to `parrot.models.voice`.
- Added `LLMFactory.list_providers()` / `list_models()` (entry-point-backed
  catalogue); the server LLM handler lists models through it.
- Release tooling now covers 28 distributions: `scripts/release.py`,
  `make bump-all` and `release.yml` discover the satellites;
  `make build-clients publish-clients` bootstraps a never-published
  satellite on PyPI with twine.

#### FEAT-524: Conversation History Ownership — memory-less clients

`ConversationHistory` had two owners: `AbstractClient` and `AbstractBot` both
read and both wrote it under the same key. Every stateful round persisted **two**
turns and sent the history to the provider **twice** — once as replayed messages
from the client, once as a text digest injected into the system prompt.
`AbstractBot` is now the sole owner. Hard cut: no deprecation shims.

Guide: `docs/memory/conversation-history-ownership.md`.
Spec: `sdd/specs/conversation-history-ownership.spec.md`.

**`AbstractClient` (base + all 19 concrete clients)**
- `conversation_memory` constructor kwarg removed (and its `InMemoryConversation()`
  default).
- `user_id` / `session_id` removed from `ask()` and `ask_stream()`. Pass
  `history: Sequence[HistoryMessage]` instead. Telemetry still resolves ids from
  the `parrot.observability.context` ContextVars that `BaseBot` binds.
- `stateless` removed from `ask()` / `ask_stream()` — a stateless call is one with
  no `history`.
- Removed: `start_conversation`, `get_conversation`, `clear_conversation`,
  `delete_conversation`, `list_user_conversations`, `_get_chatbot_key`,
  `_prepare_conversation_context`, `_update_conversation_memory`,
  `create_conversation_memory`.
- Added: `_format_history()` (the single per-provider override point),
  `_build_messages()`, `_existing_files()`.

**`parrot.memory`**
- `ConversationHistory.get_messages_for_api()` removed → new pure
  `parrot.memory.render_history()`, exported alongside `HistoryMessage`.
- `ConversationTurn.chatbot_id` added (last field; legacy records deserialize to
  `None`) plus the canonical `ConversationTurn.from_ai_message()` constructor.

**`AbstractBot`**
- `build_conversation_context()` removed, with the `conversation_context` kwarg on
  `create_system_prompt()` / `_build_prompt()` and the `## Conversation Context:`
  block. History never appears in a system prompt again.
- `save_conversation_turn()` lost its `chatbot_id` parameter and is now the single
  writer; it raises `ValueError` if `turn.chatbot_id != memory_key_id`.
- `_create_llm_client()` lost its `conversation_memory` parameter.
- New `memory_key_id` property: the explicit `chatbot_id` if configured, else
  `self.name` (never the random per-process `uuid4()` default).

**Storage key** — unified to `(chatbot, user, session)` on all three backends.
Legacy un-segmented Redis/File histories are **re-keyed lazily on first read**;
the legacy record is left in place for rollback. No offline migration job.

### Added

#### FEAT-534: `LyriaToolkit` — natural-language music generation

- `LyriaToolkit(AbstractToolkit)` in `parrot_tools.google.lyria` exposes Lyria
  to tool-calling agents for the first time: `generate_music`,
  `list_genres_and_moods`, and the standalone `parse_music_prompt` heuristic.
- Free-form text ("a soft ambient music with slow tempo") maps to structured
  Lyria controls — `bpm`, `genre`, `mood`, `density`, `brightness`,
  `temperature`, `negative_prompt`, `seed` — through documented ranges the LLM
  reads off the tool schema.
- Exact `n`-second output (default 10s, range 1–120s): the RealTime stream is
  collected as 48kHz 16-bit stereo PCM and framed into a valid WAV, so both
  streaming and the fixed-30s Vertex `lyria-002` batch path honour the
  requested duration.

#### FEAT-533: Bookstore conceptual relations — a book graph with communities

- The flat ficha catalog gains a relation graph: deterministic relations from
  existing `BookCard` fields (authorship, topic, language, era), classification
  relations from new LLM-filled card fields written at carding time, and
  LLM-judged conceptual relations with a persisted judgement log.
- Communities are derived through `graphindex` with LLM-generated labels and
  persisted alongside the catalog; `bookstore relate` and `export-wiki` (into a
  `wikitoolkit` plane, with namespace registration) are the CLI surface.
- Three new agent tools plus `related_books`; edge weights land in the
  graphindex payload. Docs: `docs/bookstore-graph.md`.

#### FEAT-532: Luau / Roblox support for wikitoolkit

- `.luau` / `.lua` are indexed by the offline build, with comments, functions,
  signatures, exported types and module-table exports in the outline.
- Static `require` resolution walks `sourcemap.json`, then
  `default.project.json`, then relative string imports; DataModel and external
  references are attached to offline scans without changing file identity.
- A federated **Roblox API plane** — one page per platform class and enum,
  generated from the official API dump and enriched with SHA-pinned
  creator-docs prose, with no LLM calls and no vendored dumps. Shared under
  `PARROT_HOME`, queried through namespace `roblox`, and published as immutable
  generations with an explicit refresh.

#### FEAT-531: wikitoolkit / bookstore CLIs auto-detect a coding-agent LLM

- When `PARROT_BOOKSTORE_LLM` / `WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL` /
  `WIKI_EXTRACT_LLM` are unset, both CLIs now detect an authenticated Claude
  Code or Codex session on the machine and default to it, instead of silently
  degrading to BM25 / deterministic carding.
- Detection is non-invasive: no subprocess spawn, no network call, no LLM
  request. Claude Code wins when both are present, on a cheap model (Haiku).
- The auto-selection is announced with an unmissable warning naming the
  provider, the model, and the env var that overrides it. Detection or
  construction failures degrade gracefully to the previous behaviour.

#### FEAT-530: Supervised Obscura headless browser

- `ObscuraProcessManager` supervises the pinned Linux Obscura `v0.2.2` binary;
  `PlaywrightDriver` gains an explicit connect-over-CDP mode selected through
  the existing `DriverFactory`, leaving `AbstractDriver`, the scraping plan and
  the browsing toolkit contracts untouched.
- Obscura's native MCP server is registered as a first-class agent/Codex
  browser capability, alongside — not replacing — Chrome DevTools MCP.
- New CLI commands start, stop and inspect the supervised process. The Selenium
  ChromeDriver backend is unchanged, and Obscura is not yet the default engine.

#### FEAT-529: A2UI `Graph` component under the new `viz-core` catalog

- The first graph/DAG/flow component in any Parrot A2UI catalog, shipped
  together with the **`viz-core` catalog shell** and its resolution contract.
- The wire carries **typed nodes and edges**, not a mermaid string: per-node
  state is bindable to the data model, and per-node clicks dispatch v1.0
  actions. Mermaid remains a *codec* (import text → typed shape, export back).
- Native rendering in all four lanes — ECharts, interactive HTML, SSR
  HTML/PDF, and the bundled Svelte canvas — over a shared `Graph` SVG contract
  and a deterministic layered layout. A `FlowDefinition` adapter renders
  `AgentsFlow` graphs directly.

#### FEAT-528: `PgRecipeStore` + parent-agnostic agent packages

- `PgRecipeStore` is a third `AbstractRecipeStore`: one relational row per
  recipe, so a recipe becomes editable, backed-up, queryable data living
  alongside the `navigator.ui_surfaces` it produces. `FileRecipeStore` and the
  Redis-backed `DBRecipeStore` are unchanged.
- The `flex_dashboard` agent package is now importable under **any** parent
  package name — a host whose repo root already owns an `agents/` package no
  longer gets `ModuleNotFoundError`.
- `load_transformer_module()` lets a host register a recipe's transformers
  without importing the agent class, its LLM or its toolkit.
  `parrot.handlers.models.recipes.PgRecipeStore` and
  `parrot.tools.infographic_recipes.load_transformer_module` are public
  contract paths.

#### FEAT-527: Infographic → A2UI migration (dual-emit)

- `InfographicToolkit.emit_a2ui` defaults to `True` and the HTML-lane
  `DeprecationWarning` is dropped: infographic turns now dual-emit an A2UI
  envelope alongside the legacy HTML document, ending the G7 policy
  contradiction.
- New `HtmlDocument` catalog component and `build_html_document()`;
  `render_template` / `render_data_template` emit it as a surface, rendered in
  a sandboxed iframe and degrading to a titled link elsewhere. A `tool_only`
  registration gate rejects tool-only components in LLM-origin envelopes.
- Chart-type parity: `ChartType` gains five types, donut/radar are no longer
  collapsed, and `KPICard` / `DataTable` props plus half-width `Row` lowering
  land in the adapter pass-through.
- The bundled Svelte UI opens the infographic canvas in a2ui mode from chat
  turns behind a `features.a2ui` flag, with a Rendered/HTML toggle.

#### Bookstore — indexed book library for Claude Code

New core package `parrot.knowledge.bookstore`: a *library* on top of PageIndex,
where each book carries a consultable catalog card ("ficha hemeroteca") so a
research agent decides which book to open before opening it.

- SQLite + FTS5 `library.db` (WAL, additive migrations, sanitized MATCH, LIKE
  fallback when FTS5 is absent) with multi-scope merge, project scope winning.
- LLM carding with a deterministic no-LLM fallback; `BookstoreToolkit` as the
  read-only agent surface, a `bookstore` console script (also
  `parrot bookstore`), and an MCP stdio server.
- Bulk `add-folder` ingest, plus EPUB, MOBI and DOCX readers shared with
  wikitoolkit ingestion. Ships with a Claude Code skill and a `/bookstore`
  command.

#### FEAT-525: Per-turn conversation compaction

Deterministic, budget-driven retention of conversation history — the
extension point FEAT-524 left open. Guide:
`docs/memory/per-turn-conversation-compaction.md`.

- `ConversationMemory.add_turn()` is now a concrete template method
  (Stage 0 normalize → Stage 0.5 token count → write-time oversize offload →
  one write via the abstract `_store_turn()`). Custom backends implement
  `_store_turn`, never `add_turn`.
- `parrot.memory.compaction.compact_history()` — pure three-tier pre-pass
  (verbatim / pruned / dropped) driven by a `ContextBudget` auto-resolved
  per model from `MODEL_WINDOWS`; kill switch `context_budget=False` or
  `PARROT_COMPACTION_DISABLED=1`. `PrunePolicy` registry with built-ins.
- Pruned tool output is offloaded to a memory-owned `OmissionStore`
  (InMemory / Redis / File) and recoverable through the
  `read_omitted_content` tool (ContextVar-scoped, fails closed; excluded
  from `search_tools`).
- `AbstractBot.render_context_history()` feeds every bot entry point;
  `save_conversation_turn(compaction=)`; `ConversationTurn` schema v2;
  `render_history()` also accepts `Sequence[TurnView]`.

#### FEAT-526: Meta (Muse) LLM client — `ai-parrot-client-meta`

- `MetaClient` in `parrot.clients.meta` (subclass of `OpenAIBaseClient`),
  `LLMFactory.create("meta:muse-spark-1.3")`, with a `MetaModel` catalogue
  of the seven live-verified model ids and capability sets.
- Chat Completions path (chat, tool calling, structured output, streaming,
  `invoke()`) plus a client-local Responses API path unlocking search
  grounding and `count_input_tokens()`. Live e2e suite mirrors the OpenAI
  one.

#### FEAT-522: Interactive HTML `Map` components + generated Tailwind CSS

- `Map` renders as a real interactive Leaflet map — top-level and
  Infographic-nested — inside `interactive-html` documents through a shared
  `build_map_document()`; `MarkerCluster` wraps a layer past 500 points
  (per-layer overridable).
- Genuinely offline: folium CDN resources are swapped for vendored
  data URIs (license manifest included), which also closes the CDN leak in
  the standalone `folium_map` renderer.
- `scripts/generate_a2ui_css.py` AST-scans every class `interactive_html.py`
  emits and generates Tailwind v4 CSS folded into
  `DesignSystem.stylesheet()`; a CI freshness gate (`--check`) keeps the
  generated CSS and vendored assets from drifting.

#### FEAT-521: Python REPL worker — idle detection and memory guardrails

- `ProcessObserver` samples every live worker (CPU time, RSS, state, thread
  count) and derives `settled` / `computing` / `stalled` verdicts; every
  timeout, bootstrap failure and namespace-loss error names the verdict and
  the last sample.
- Two-stage deadline: SIGINT first (the worker returns a bounded
  `interrupted` result and keeps its namespace), SIGKILL only after
  `interrupt_grace_ms`.
- `WorkerPool` enforces a host memory reserve with pressure eviction.
  `execution_mode="inprocess"` escape hatch and worker bootstrap
  diagnostics; `python_repl_execution_mode` exposed on `flex_dashboard` /
  `finance_reporter`.

#### FEAT-520: GraphIndex Postgres Backend — Bitemporal Plane + One-Pass Hybrid Retrieval

Third GraphIndex persistence backend (`PostgresPersistence`) at parity
with `SQLitePersistence`/`GraphIndexPersistence`, plus a fourth
`BaseWikiStore` implementation (`PostgresWikiStore`) — both over ONE
shared, engine-enforced bitemporal `graphindex.*` schema. asyncpg only;
zero SQLAlchemy; `PgVectorStore` is explicitly not reused.

- `PostgresPersistence` — full parity surface (`persist_graph`,
  `replace_document_slice`, `is_stale`, `load_graph`) plus the graph
  commit protocol (`apply_update`/`get_commit`/`list_commits`/
  `revert_commit`) on real transactions.
- Bitemporal writes: `node_versions.validity` is a `tstzrange` protected
  by a GiST `EXCLUDE` constraint — overlapping versions of one concept
  are rejected by the ENGINE, not ingest discipline. Corrections
  close-and-insert; content is never `UPDATE`d.
- Temporal read contract (Postgres-only in v1): `as_of(t)`, `history
  (concept_id)`, `diff(concept_id, t1, t2)`.
- `hybrid_retrieve` — graph expansion + pgvector KNN + `ts_rank_cd` FTS as
  CTEs of ONE SQL statement, RRF-fused (`Σ w/(60+rank)`) in SQL, with
  cross-encoder re-ranking through the existing `parrot.rerankers` seam.
- `PostgresWikiStore` — full `BaseWikiStore` surface over the same
  schema, including the schema-v2 symbol surface (`upsert_symbols`,
  `find_symbols`, trigram+FTS `search_symbols_fts`).
- In-schema pgvector embeddings (`graphindex.embeddings`) with a
  config-driven ANN index (`ivfflat` default — see the TASK-2770 spike
  artifact for the measured HNSW-vs-IVFFlat tradeoff).
- `build_graph_memory_toolkit(backend="postgres", ...)` factory path; four
  mono-purpose temporal/hybrid agent tools (`graph_as_of`,
  `graph_concept_history`, `graph_diff`, `graph_hybrid_retrieve`),
  registered only when the bound persistence exposes the temporal surface
  (duck-typed).
- Docs: [`docs/graphindex.md`](docs/graphindex.md) backend matrix,
  Temporal API, and Hybrid Retrieval sections.

### Fixed

#### Hotfix `chromemanager-async-migration`: async `ChromeManager` (requests → aiohttp)

`ChromeManager` (`parrot.mcp.chrome`, ai-parrot-server) probed and launched
Chrome with `requests`, `subprocess` and `time.sleep`, and was reached from the
async `add_chrome_devtools_mcp_server()` hook — so `WebAgent.configure()` could
block the event loop for 10+ seconds while Chrome came up.
Spec: `sdd/specs/chromemanager-async-migration.spec.md`.

- `ChromeManager.is_running()`, `start(headless=True, timeout=10.0)` and
  `stop()` are now coroutines (aiohttp probe of `/json/version`,
  `asyncio.create_subprocess_exec`, `asyncio.sleep`/`wait_for`). The
  `requests` import is gone. `is_chrome_running()` remains as a deprecated
  coroutine alias of `is_running()`; `is_port_open()` was removed.
- `create_chrome_devtools_mcp_server()` no longer launches Chrome as a side
  effect — it is a pure `MCPServerConfig` builder. Callers that built a
  config and called `add_mcp_server()` themselves must now call the new
  `ensure_chrome_running(browser_url, headless=False)` coroutine (or use the
  mixin hook).
- `MCPEnabledMixin.add_chrome_devtools_mcp_server()` gained
  `ensure_running: bool = True`: it awaits `ensure_chrome_running()` before
  connecting (skipped when `auto_connect=True`). `WebAgent` behaviour is
  unchanged. `MCPEnabledMixin.shutdown()` now awaits `ChromeManager.stop()`.
- The `WebAgent` unit tests no longer spawn a real Chrome when calling the
  factory with default arguments.

#### Other fixes

- **Security** — closed a path-injection on `PandasAgent.report_dir`
  (CodeQL alert #213).
- Google client: `invoke()` recovers a raw-string structured parse; no
  longer forces `thinking_budget=0` on `gemini-3.5-flash-lite`.
- OpenAI-family `ask()` no longer double-encodes the current turn;
  gemma4 / hf `ask_stream()` forward `history=`.
- dev-loop: dropped the unusable `model: gpt-5.5` from `sdd-secondopinion`;
  SDD command frontmatter uses the valid `haiku` alias.

---

## [0.28.0] — 2026-08-26

### Added

#### FEAT-463: Matrix Agents Swarm

Matrix-protocol agent swarm infrastructure — agents coordinate over
Matrix rooms via an Application Service, with dedicated channels, tunnels,
and swarm-policy dispatch.

- `ChannelManager` — room provisioning with optional Spaces.
- `TunnelRegistry` & `AgentTunnel` — bidirectional agent-to-agent
  communication via `m.parrot.task` / `m.parrot.result` events.
- Inbound task handler: `handle_task → m.parrot.result`.
- `AgentSwarmToolkit` — LLM-callable tools for swarm operations.
- Transport wiring, swarm policy dispatch, and concurrent sessions.
- Session trigger reply-to & tunnel cross-pollination.
- Matrix dev stack: `docker-compose`, bridges profile, bootstrap script.
- Documentation: `CLIENTS.md`, `BRIDGES.md`, swarm example & usage guide.

#### FEAT-462: Unified Telemetry Bus

Replaces the fragmented telemetry layer with a single OTEL + OpenLIT
pipeline — configure once, export to any combination of endpoints.

- `ObservabilityConfig` model extensions for multi-target OTLP.
- `make_span_exporters` multi-endpoint exporter factory.
- GenAI SemConv attribute additions (token-level, model metadata).
- `OpenLitUsageRecorder` — async usage recording via OpenLIT.
- `OpenLIT Bridge` optional-extra package (`parrot-openlit`).
- Setup telemetry refactor & bootstrap cleanup (delete legacy
  integration paths, consolidate `_do_bootstrap`).

#### FEAT-460: Raw Upload Field Types

File-upload support for FormBuilder — upload, validate, thumbnail,
and serve binary attachments declaratively.

- `FileEnvelope` model & `UPLOAD_FIELD_TYPES` constant.
- `FieldConstraints.max_inline_size_bytes` extension.
- `ThumbnailService` — on-demand thumbnail generation.
- `/file-upload` route handler and route registration.
- Validator dual-read coercer (base64 ↔ multipart).
- JSON Schema, HTML5, PDF, and adaptive-card renderer updates.
- `/thumbnail` serving route.
- Integration & regression test suite.

### Fixed

- **Scheduler input sanitization** — env and DB inputs now sanitized
  before they reach APScheduler, closing an injection vector.
- **NetworkNinja multi-photo import** — a multi-photo question now
  imports as `MULTI_UPLOAD` instead of `FILE` with a flag.
- **OTLP endpoint bug (FEAT-462)** — critical exporter target
  resolution fixed during code review.

### Changed

- Project-local RTK filters configuration (`.rtk.local.toml`).

---

## [0.27.1] — 2026-08-25

### Added

#### FEAT-457: FormBuilder FormSchema Persistency

Autonomous submission persistence pipeline for FormBuilder — forms declare
a `persistence` block and submissions route to the appropriate sink
automatically, no handler-side wiring.

- `parrot.forms.core.persistence` — `PersistenceConfig`, `SinkType`,
  `SinkCoordinate` (immutable after validation).
- `AbstractSubmissionSink` ABC with capability model and typed error taxonomy.
- Six built-in sinks: `PostgresTableSink` (provision + extend), `AsyncDBSink`
  (Mongo/Arango nested, BigQuery tabular), `CsvFileSink` (lock-free),
  `GoogleSheetSink` (with `[gsheet]` optional extra).
- `SubmissionMapper` — tabular flattening and document nesting.
- `SinkAliasRegistry` — tenant-scoped credential allowlist.
- `SinkFactory` + `SinkDispatchTable` — coordinate-driven dispatch.
- `AutonomousFormStorage` — pointer-indexed form definitions.
- Application wiring via alias registry app key and factory injection.
- End-to-end integration suite and reference documentation.

#### FEAT-456: FormBuilder Relational Field Types

Relational cardinality support for FormBuilder fields — define entity
references and relation specs declaratively in field extractors.

- `EntityRef`, `RelationSpec` models.
- `FormField.relation` aspect with combination validator.
- Extractor `relation:` block (YAML) + JSON Schema `x-relation` emission.
- `FormValidator` shape validation for relational submissions.
- Documentation and end-to-end integration tests.

#### FEAT-455: Web Automation Fixture-Site Tests

Test infrastructure for the web-automation toolkit: local fixture site,
`fake_broker` fixture, real-browser smoke tests, resume-without-duplicates
and submit-gate end-to-end coverage.

### Fixed

- **`wikitoolkit ingest-jira` fetched only the first page (FEAT-454
  follow-up).** Jira Cloud's cursor-based pagination now handled correctly;
  `--backfill`, `--concurrency`, and `--progress-every` flags added for
  large-corpus ingestion.
- **`setup_form_api` clobbered host-wired blob storage** — the API setup
  no longer overwrites a storage instance already attached by the host app.
- **`notification_succeeded` clobbered by NotificationMixin homologation** —
  restored after the `send_*` wrapper refactor.
- **`azure-identity==1.23.0` broke uv resolution** — pinned override added.
- **CodeQL pipeline unblocked** — last real alert closed.

### Changed

- CI release workflow: allow manual `workflow_dispatch` runs; drop retired
  `macos-13` build leg from `build-parrot-codec`.
- `release.py` now tracks `parrot-codec` as a managed distribution.
- MkDocs: 74 orphaned pages added to nav; new Knowledge Graph section
  (LLM Wiki, PageIndex, GraphIndex).

---

## [0.27.0] — 2026-08-24

A major feature release spanning 481 commits across 11 packages: the
integration satellite (`ai-parrot-integrations`), tool-result compression,
Claude Agent tool bridging, Jira ticket corpus federation, OpenAI-compatible
base clients, SaaS auth hardening, web automation infrastructure, and
comprehensive LLM Wiki documentation.

### Breaking Changes

#### FEAT-202: ai-parrot-integrations — dependencies removed from BASE install

The following SDKs are **no longer installed** when you run `pip install ai-parrot`.
Install the new satellite package with the appropriate extra instead:

| Removed dependency | Reason | Replacement |
|---|---|---|
| `pywa>=3.8.0` | WhatsApp SDK only needed for WA channel | `pip install ai-parrot-integrations[whatsapp]` |
| `aiogram>=3.12` | Telegram SDK only needed for Telegram channel | `pip install ai-parrot-integrations[telegram]` |
| `azure-teambots>=0.1.1` | MS Teams SDK only needed for Teams channel | `pip install ai-parrot-integrations[msteams]` |
| `mautrix>=0.20` | Matrix SDK only needed for Matrix channel | `pip install ai-parrot-integrations[matrix]` |
| `python-olm>=3.2.16` | Matrix E2E encryption only needed for Matrix | `pip install ai-parrot-integrations[matrix]` |
| `async-notify[default]` | Channel-specific; now in messaging extra | `pip install ai-parrot-integrations[messaging]` |

**If your code breaks** after upgrading `ai-parrot`, install the extras you need:

```bash
# Individual channels
pip install "ai-parrot-integrations[telegram]"
pip install "ai-parrot-integrations[slack]"
pip install "ai-parrot-integrations[msteams]"
pip install "ai-parrot-integrations[whatsapp]"
pip install "ai-parrot-integrations[matrix]"

# All channels
pip install "ai-parrot-integrations[all]"

# Backward-compat alias via ai-parrot meta-extra
pip install "ai-parrot[messaging]"  # maps to ai-parrot-integrations[messaging]
```

See [Migration Guide](docs/migration/feat-202-ai-parrot-integrations.md) for
detailed upgrade instructions.

#### OAuth2 import path changed (FEAT-202)

```python
# OLD (raises ImportError with guidance)
from parrot.integrations.oauth2.service import IntegrationsService

# NEW
from parrot.auth.oauth2.service import IntegrationsService
```

All sub-modules moved identically:

| Old path | New path |
|---|---|
| `parrot.integrations.oauth2.service` | `parrot.auth.oauth2.service` |
| `parrot.integrations.oauth2.registry` | `parrot.auth.oauth2.registry` |
| `parrot.integrations.oauth2.models` | `parrot.auth.oauth2.models` |
| `parrot.integrations.oauth2.persistence` | `parrot.auth.oauth2.persistence` |
| `parrot.integrations.oauth2.jira_provider` | `parrot.auth.oauth2.jira_provider` |
| `parrot.integrations.oauth2.o365_provider` | `parrot.auth.oauth2.o365_provider` |

#### Zoom import path changed (FEAT-202)

```python
# OLD (raises ImportError with guidance)
from parrot.integrations.zoom.client import ZoomUsInterface

# NEW
from parrot_tools.zoom.client import ZoomUsInterface
```

### Behavior Changes

- **`ToolManager.search_tools()` results are now relevance-ordered, not
  alphabetical — and the match set can differ.** (FEAT-434)
  A new lexical ranker, `ToolManager.rank_tools()`, is the source of truth;
  `search_tools()` is now a thin JSON-formatting wrapper over it. The new
  scorer awards partial credit per individual token, so multi-word queries
  can now match tools whose text contains those words separately (not just
  contiguously). A blank query still matches the full registry.
- **`AfterToolCallEvent.result_size_bytes` now reports the POST-compression
  size; the pre-compression size moved to
  `result_size_bytes_original`.** (FEAT-380)
  Update any dashboard/alert that assumed the old (pre-compression)
  semantics to read `result_size_bytes_original` instead.
- **`GoogleGenAIClient.MAX_TOOL_RESULT_CHARS` is now a last line of defense,
  not the primary one.** (FEAT-380) Payloads typically pass through the
  compression pipeline first.
- **`HookManager.route_to_bus` auto-routing** (FEAT-319):
  `navigator-eventbus>=0.1.0` changes `route_to_bus` to auto-enable when a
  bus is attached via `set_event_bus`. Pass `route_to_bus=False` explicitly to
  restore the old behavior.

### Added

#### FEAT-454: Jira Ticket Extractor → LLM Wiki (`issues` namespace)

Zero-LLM, byte-deterministic extraction of Jira tickets into a federated
`issues` wiki namespace. One markdown document per ticket, incremental via
watermark, off-repo storage. See
[`docs/guides/jira-ticket-extractor.md`](docs/guides/jira-ticket-extractor.md).

- `parrot/interfaces/jira/` — shared Jira read interface (4 auth modes,
  lazy `jira` import, `JiraIssue`/`JiraPerson` pydantic models).
- `parrot/knowledge/wiki/jira_render.py` — deterministic `JiraIssue` →
  markdown renderer with sync-marker preservation.
- `parrot/knowledge/wiki/jira_sync.py` — sweep engine with watermark,
  orphan detection, entity notes (people/projects/components/labels).
- `wikitoolkit ingest-jira` CLI command — build + optional `--enrich`.
- `ConceptType.ISSUE`, `.PERSON`, `.PROJECT` added to OKF ontology.
- `JiraToolkit` delegation refactor — all read methods now route through
  `JiraInterface`; zero public-surface change.
- Host `jira` extra: `pip install 'ai-parrot[jira]'`.

#### FEAT-434: Claude Agent Tool Bridge

`ClaudeAgentClient` now bridges the agent's registered tools to local
Claude Code sub-agents as an in-process `mcp__parrot__<tool>` SDK-MCP
server. See
[`docs/tools.md`](docs/tools.md#claude-agent-tool-bridge-feat-434).

- `parrot.clients.claude_agent_bridge.ClaudeAgentToolBridge`.
- `ToolManager.rank_tools(query, limit)` — lexical relevance ranking.
- `ClaudeAgentRunOptions.mcp_servers` / `.expose_parrot_tools` /
  `.max_exposed_tools` / `.tool_timeout`.
- agentd caller identity (`SO_PEERCRED` → OS user, service-identity fallback).
- agentd bridged-HITL wiring with `ConfirmationGuard`.

#### FEAT-380: Tool-Result Compression Pipeline

Client-agnostic compression stage inside `ToolManager.execute_tool()`. See
[`docs/tools/compression.md`](docs/tools/compression.md).

- `parrot.tools.compression` — `FilterLevel`, `ResultCompressor`, codec
  registry, `CompressionStage`, `BudgetRouter` + `CircuitBreaker`,
  `CompressionTee`, `CompressionReport`.
- Built-in codecs: `json_compact` (lossless) and `columnar` (row-oriented).
- `PARROT_COMPRESSION_DISABLED=1` — global kill switch.
- Optional Rust extension `parrot_codec` (PyO3, accelerates `columnar`).
- `clients/live.py` voice-session tool execution now routes through
  `AbstractTool.execute()` (restoring permission checks, credential broker,
  redaction, and lifecycle events).

#### FEAT-438: OpenAI-Compatible Base Clients

`OpenAIBaseClient` — shared skeleton for OpenAI-API-compatible providers
(OpenAI, DeepSeek, xAI, local servers). Single completion funnel for
`ask_stream`/`invoke`. `OpenAIClient` rebased onto it.

#### FEAT-446: SaaS Auth Hardening

Cross-tenant isolation fixes: WebSocket subprotocol JWT auth restored,
WhatsApp allowlist fail-closed financial control, negative-path integration
test suite.

#### FEAT-447: AgentsFlow Result Fidelity

Result preservation improvements in the `AgentsFlow` DAG executor.

#### FEAT-453: Web Automation Infrastructure

`BusinessAutomationToolkit` with `PlanDirectoryStore` wiring for browser-based
business process automation.

#### FEAT-452: Audio Notes Capture

`AudioNoteCaptureToolkit` extracted to `parrot_tools` — voice/text note
capture via `FirefliesWikiAgent`, structuring prompt, Obsidian persistence,
wiki ingestion.

#### FEAT-202: ai-parrot-integrations

- **`ai-parrot-integrations`** satellite package with granular extras:
  `[slack|telegram|msteams|whatsapp|matrix|voice|messaging|all]`.
- **`MessagingHook` Protocol** and **`HookRegistry`** — pluggable messaging
  channel hooks.
- **`ChannelRegistry`** — satellite packages self-register `HumanChannel`
  implementations.
- All `from parrot.integrations.X import Y` paths continue to work unchanged
  via PEP 420 namespace extension.

#### FEAT-319: EventBus Consolidation

- **navigator-eventbus pinned to `>=0.1.0,<0.2`** (was a git commit hash).
- `test_no_internal_bus_copy` migration guard.

#### Documentation

- `docs/guides/llm-wiki-guide.md` — comprehensive LLM Wiki guide covering
  build, query, remember, namespaces, backends (SQLite/ArangoDB), Claude/
  Codex/Gemini integration, git hooks, Obsidian vaults, and configuration.
- `docs/guides/jira-ticket-extractor.md` — Jira Ticket Extractor user guide.
- `docs/guides/jira-wiki-agent-integration.md` — integrating the `issues`
  namespace with existing agents.
- `docs/runbooks/jira-issues-namespace.md` — operator runbook for the
  `issues` namespace (credentials, cron, troubleshooting).
- AWS Bedrock / Amazon Nova sample agents and generation CLIs.

### Fixed

#### FEAT-380: Tool-Result Compression (adversarial review)

- G3 violation: lossy compression with a failed tee now falls back to the
  uncompressed original.
- `minimal_budget_ms` was dead code — MINIMAL-level calls now judged
  correctly.
- `estimate_size()` no longer does a full recursive walk for dict payloads.
- `ToolManager.execute_tool()` metadata aliasing bug fixed.
- Circuit-breaker half-open probing race condition.
- Error-path tee call now wrapped in try/except.
- `parrot_codec`: `catch_unwind` for Rust panics; consistent int/float
  comparison in constant-column factoring.

#### Other fixes

- `codex-agent`: do not require the SDK when backend is "cli".
- `claude-agent`: resume a conversation instead of re-creating its session.
- Bedrock: make the API key authoritative; wire the PageIndex plane.
- CLI: stop blaming optional extras for inner ImportErrors.
- Suppress SyntaxWarning for invalid escape sequences in docstrings.

### Known Limitations

- The live voice route (`clients/live.py`) does not yet apply compression
  itself — only the permission/broker/redaction/event restoration.
- The `compression_*` fields are not yet populated on the literal
  `AfterToolCallEvent` instance; the real values are in `ToolResult.metadata`.
- `CompressionReport` has no automatic `ToolManager` listener yet.
