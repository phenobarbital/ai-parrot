# Changelog

All notable changes to AI-Parrot are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Breaking Changes

#### FEAT-524: Conversation History Ownership — memory-less clients (0.29.0)

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
