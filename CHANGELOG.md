# Changelog

All notable changes to AI-Parrot are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.29.0] — 2026-09-05 — PEP 420 LLM-client satellites, memory-less clients

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

### Added

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
