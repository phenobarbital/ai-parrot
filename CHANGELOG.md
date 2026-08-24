# Changelog

All notable changes to AI-Parrot are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed

- **`wikitoolkit ingest-jira` fetched only the first page (FEAT-454
  follow-up).** Jira Cloud retired the offset-based `/search` endpoint:
  pycontribs now redirects `search_issues(startAt=0)` to the cursor-based
  `enhanced_search_issues` and raises for any `startAt > 0`, and that
  response carries no `total`. `JiraInterface.search_issues` read the
  missing `total` as "scope exhausted" and stopped after exactly one page
  (100 issues), which also produced spurious `unresolved_link_keys`
  warnings for in-scope tickets it had never fetched. It now paginates by
  `nextPageToken` on Cloud and keeps the `startAt` loop for Server/DC,
  where a missing `total` pages on until a short page instead of
  truncating. Operators who ran a truncated sweep must backfill with
  `ingest-jira --force` — the truncated run stored an `"ok"` watermark.

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
