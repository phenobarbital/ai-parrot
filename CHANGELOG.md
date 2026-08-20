# Changelog

All notable changes to AI-Parrot are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — FEAT-434: Claude Agent Tool Bridge

`ClaudeAgentClient` (`llm="claude-agent:*"` / `"claude-code:*"`) no longer
discards the agent's registered tools when delegating a turn to a local
Claude Code sub-agent — they are now bridged automatically as an
in-process `mcp__parrot__<tool>` SDK-MCP server, dispatched through
`ToolManager.execute_tool()` so guardrails, grants, HITL confirmation and
tool-result compression all apply unchanged. See
[`docs/tools.md`](docs/tools.md#claude-agent-tool-bridge-feat-434),
[`docs/agentd.md`](docs/agentd.md#claude-code-sub-agent-tool-bridge-feat-434)
and [`docs/hitl-confirmation.md`](docs/hitl-confirmation.md#bridged-tools-claude-code-sub-agents-feat-434).

### Behavior Change

- **`ToolManager.search_tools()` results are now relevance-ordered, not
  alphabetical — and the match set can differ too, not just the order.**
  A new lexical ranker, `ToolManager.rank_tools()`, is the source of
  truth; `search_tools()` is now a thin JSON-formatting wrapper over it.
  The return type, JSON shape, and no-match message are byte-identical.
  The legacy substring check required the *whole query string* to appear
  literally in a tool's name/description; the new scorer additionally
  awards partial credit per individual token, so a multi-word query like
  `"weather current"` can now match a tool whose text contains those
  words separately (not just contiguously) where it previously would
  not have. A blank/whitespace-only query still matches the full
  registry (preserved deliberately — `"" in name.lower()` was always
  `True` under the old substring check). This affects every existing
  caller, including LLM-visible calls (`search_tools` is itself a
  registered tool).

### Added

- `parrot.clients.claude_agent_bridge.ClaudeAgentToolBridge` — converts
  registered tools into `claude_agent_sdk.SdkMcpTool` objects, strips the
  self-granted `confirm` schema property on this path only, bounds/ranks
  the exposed set (`select()`), and maps every failure mode (tool error,
  timeout, HITL denial/timeout) to a recoverable MCP error result.
  `claude_agent_sdk` stays a strictly-lazy, optional import.
- `ToolManager.rank_tools(query, limit)` — lexical relevance ranking
  (token overlap over name + description), deterministic tie-break.
- `ClaudeAgentRunOptions.mcp_servers` / `.expose_parrot_tools` (default
  `True`) / `.max_exposed_tools` (default `15`) / `.tool_timeout`.
- agentd caller identity: `SO_PEERCRED` -> OS user, with an
  env-configured (`AGENTD_SERVICE_IDENTITY_*`) service-identity fallback
  whose confirmation window is pinned to `0`.
- agentd bridged-HITL wiring: `AgentDaemon._configure_hitl()` attaches a
  `ConfirmationGuard` (channel `"agentd"`, `window_seconds=0`) to the
  served agent's `ToolManager`; the `"hitl.respond"` RPC lets an attached
  `parrot attach` console answer a pending confirmation.

---

## [Unreleased] — FEAT-380: Tool-Result Compression Pipeline

A client-agnostic compression stage now runs inside
`ToolManager.execute_tool()` for every `AbstractTool`/`ToolkitTool` call —
see [`docs/tools/compression.md`](docs/tools/compression.md) for the full
feature documentation (config format, levels, kill switch, tee recovery
flow, savings report, optional Rust extension).

### Behavior Change

- **`AfterToolCallEvent.result_size_bytes` now reports the
  POST-compression size; the pre-compression size moved to a new field,
  `result_size_bytes_original`.** Anyone graphing `result_size_bytes` over
  time will see an unexplained step change at this release — that IS the
  change: the field's meaning flipped from "raw tool output size" to
  "size after the compression pipeline ran." Update any dashboard/alert
  that assumed the old (pre-compression) semantics to read
  `result_size_bytes_original` instead.
- **`GoogleGenAIClient.MAX_TOOL_RESULT_CHARS` is now a last line of
  defense, not the primary one.** Its positional (first-N) truncation
  behavior is unchanged, but it now runs on payloads that have typically
  already passed through the compression pipeline above, and a `warning`
  now logs the tool name and pre/post sizes whenever it actually fires
  (previously silent on two of its three truncation paths).

### Added

- `parrot.tools.compression` — new package: `FilterLevel`, the
  `ResultCompressor` protocol + codec registry (`register_codec`/
  `get_codec`), `CompressorRegistry` (multi-source TOML manifest loading:
  project → third-party packages → core defaults), `CompressionStage`
  (gates, effective-level resolution, codec dispatch, tee), the built-in
  `json_compact` (lossless, `MINIMAL`) and `columnar` (row-oriented
  splitting, `NORMAL`) codecs, `BudgetRouter` + `CircuitBreaker`
  (pre-compression latency budgeting, G7/G9), `CompressionTee` (working-
  memory escape hatch for lossy/error payloads), and `CompressionReport`
  (per-tool/per-session savings aggregation).
- New `AfterToolCallEvent` fields (all defaulted — the dataclass is
  frozen): `compression_codec`, `compression_level`,
  `result_size_bytes_original`, `compression_duration_ms`,
  `compression_teed`.
- `PARROT_COMPRESSION_DISABLED=1` — global kill switch; restores
  pre-feature behavior exactly.
- Optional Rust extension `parrot_codec`
  (`packages/ai-parrot/src/parrot/codec-rs/`, PyO3, built independently
  via `maturin develop`) accelerates the `columnar` codec's transform for
  already-serialized (`bytes`/`str`) input, with the GIL released for the
  duration. Purely optional — `pip install ai-parrot` is unaffected, and
  every code path has a pure-Python fallback.
- `clients/live.py`'s voice-session tool execution now routes through
  `AbstractTool.execute()` instead of the private `tool._execute()` —
  restoring permission checks, the credential broker, secret/PII
  redaction, and lifecycle events on that path (previously bypassed all
  four). `voice_text`/`display_data` are read from the ToolResult's own
  fields, uncompressed, exactly as before.

### Fixed

Found by an adversarial code review (Claude subagent + Codex, both CONFIRMed
after independent verification) before this feature's first release:

- **G3 violation**: a lossy compression whose tee call failed or was
  unavailable at RUNTIME (not just statically, e.g. a transient
  `WorkingMemoryToolkit` error) was still returned — with no way to
  recover the original. `CompressionStage.run()` now falls back to the
  uncompressed original whenever a lossy outcome's tee key comes back
  `None`, exactly as `CompressionTee.store()`'s own docstring always
  promised callers would happen.
- **`minimal_budget_ms` was dead code**: `CircuitBreaker._budget_for()`
  only branched INLINE vs. EXECUTOR, so MINIMAL-level calls (always
  routed INLINE) were judged against the coarser `inline_budget_ms`
  instead of the level-specific budget calibrated for them (TASK-1959).
  `record()`/`_budget_for()` now thread the effective `FilterLevel`
  through so MINIMAL calls are judged correctly.
- **`estimate_size()` wasn't actually cheap for `QueryResult`-shaped
  dicts**: a dict payload (e.g. `{"driver": ..., "rows": [...]}`, this
  feature's flagship use case) fell through to a full recursive
  `_rough_bytes()` walk of every row before routing — the exact
  "fully walk a large payload" cost the function's own docstring says it
  avoids. Dict payloads with a dominant list-valued field are now
  sampled the same cheap way as a bare list.
- **`ToolManager.execute_tool()`'s `meta = getattr(result, "metadata",
  {}) or {}`** silently swapped in a fresh dict whenever `result.metadata`
  was falsy — which is every time it starts as `{}` (Pydantic's
  `default_factory=dict` default, the common case) — breaking the
  aliasing the surrounding comment relied on. Compression fields now
  reliably land on the actual `ToolResult.metadata` object, not just on
  whatever `add_result_hook` happened to observe by reference.
- Circuit-breaker half-open probing had a race: `is_open()` didn't check
  for an in-flight probe, so two calls landing in the same post-cooldown
  window could both be treated as "the" probe. It now blocks any
  additional caller until the first probe resolves via `record()`.
- The error-path tee call in `execute_tool()` is now wrapped in its own
  try/except so a catastrophically broken tee can never mask the
  original `ValueError(result.error)`.
- `parrot_codec`'s `columnarize()` now wraps the transform in
  `catch_unwind` so an unexpected Rust panic surfaces as an ordinary
  `PyRuntimeError` (caught by `columnar.py`'s `except Exception:`)
  instead of PyO3's `PanicException`, which derives from `BaseException`
  and would otherwise slip past that guard.
- `parrot_codec`'s constant-column factoring now compares numbers the
  same way Python's `==` does (`1 == 1.0`); `serde_json::Value`'s derived
  `PartialEq` treated same-value int/float differently, a byte-for-byte
  parity break against the Python reference implementation.

### Known limitations (see `docs/tools/compression.md` for detail)

- The live voice route (`clients/live.py`) does not yet apply compression
  itself — only the permission/broker/redaction/event restoration above.
- The new `compression_*` fields are not yet populated on the literal
  `AfterToolCallEvent` instance a subscriber observes (the event fires
  before the compression stage runs); the real values are in
  `ToolResult.metadata` today.
- `CompressionReport` has no automatic `ToolManager` listener yet — feed
  it events manually.

---

## [Unreleased] — FEAT-319: EventBus Consolidation

### Changed

- **navigator-eventbus pinned to `>=0.1.0,<0.2`** (was a git commit hash).
  The published 0.1.0 release includes envelope `schema_version` support and
  tri-state `route_to_bus` on `HookManager`.

### Behavior Change

- **`HookManager.route_to_bus` auto-routing**: `navigator-eventbus>=0.1.0`
  changes `route_to_bus` to auto-enable when a bus is attached via
  `set_event_bus`. Any deployment that previously called `set_event_bus` and
  relied on the implicit `route_to_bus=False` default will now route hooks
  traffic to the bus. Pass `route_to_bus=False` explicitly to restore the old
  behavior. This is currently latent in ai-parrot (zero `route_to_bus` call
  sites).

### Added

- `test_no_internal_bus_copy` migration guard — asserts the deleted
  `parrot/core/events/bus/` directory stays deleted and no `parrot.*` module
  defines `BusCore`.

---

## [Unreleased] — FEAT-202: ai-parrot-integrations

### Breaking Changes

#### Dependencies removed from `ai-parrot` BASE install

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

#### OAuth2 import path changed

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

#### Zoom import path changed

```python
# OLD (raises ImportError with guidance)
from parrot.integrations.zoom.client import ZoomUsInterface

# NEW
from parrot_tools.zoom.client import ZoomUsInterface
```

### New Features

- **`ai-parrot-integrations`** satellite package with granular extras:
  `[slack|telegram|msteams|whatsapp|matrix|voice|messaging|all]`
- **`MessagingHook` Protocol** in `parrot.core.hooks.base` — pluggable interface
  for messaging channel hooks
- **`HookRegistry`** in `parrot.core.hooks.base` — allows satellite packages to
  self-register hook implementations
- **`ChannelRegistry`** in `parrot.human.channels` — allows satellite packages to
  register `HumanChannel` implementations for auto-discovery
- Matrix hook (`MatrixHook`) now in `parrot.integrations.matrix.hook` and
  auto-registers on import

### Non-Breaking Changes

- All `from parrot.integrations.X import Y` paths continue to work unchanged
  when `ai-parrot-integrations` is installed (PEP 420 namespace extension)
- `from parrot.voice import ...` continues to work via PEP 420
- `from parrot.human import TelegramHumanChannel` continues to work via PEP 420
- `BotManager` (`parrot.manager.manager`) is **unchanged** and remains in `ai-parrot`
- `IntegrationBotManager` lazy import from `BotManager` and `orchestrator.py`
  continues to work via PEP 420
- Zoom toolkit: `parrot_tools/zoomtoolkit.py` updated to import from new location

---

See [Migration Guide](docs/migration/feat-202-ai-parrot-integrations.md) for
detailed upgrade instructions.
