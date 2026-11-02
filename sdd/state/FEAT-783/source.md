---
kind: file
jira_key: null
fetched_at: 2026-10-30T22:29:05Z
summary_oneline: "Unified usage & cost metrics per SDD spec: one correlation key and one ledger-owned usage plane across the dev-loop, Claude Code and Codex seats"
source_commit: 282d95d0c6
source_path: sdd/proposals/unified-usage.proposal.md
---

# Brainstorm: Unified Usage & Cost Metrics per Spec (SDD seats)

Oct 30, 2026 · @Jesus Lara

## Problem statement

Token usage and cost for one SDD spec are split across three seats that report to three different places, so nobody can answer "what did FEAT-123 cost?" with correct numbers.

- **Seat dev-loop** (`sdd-worker` orchestrating `sdd-coder` runs on parrot backends): the only seat whose usage lands in SDD state, via `coder_begin_execution` / `coder_end_execution` with an `execution_id`.
- **Seat Claude Code native** (the `sdd-*` slash commands, `sdd-worker` itself, `Task` sub-agents including `prepare_native` coders): usage leaves through the Claude Code OpenTelemetry plugin straight to Grafana, keyed by `session.id`, with no link to a spec or task.
- **Seat Codex** (interactive or as a coder backend): usage leaves through its own plugin to Grafana, again with no spec key.

The gap is not a missing exporter. It is a missing **correlation key** shared by the three seats, and a missing **single store** that owns the per-spec numbers. Grafana today shows totals per session and per tool; it cannot join those to `sdd/state/<FEAT-ID>/`.

Goal: one usage plane, written by all three seats, keyed by `(feat_id, task_id, attempt_uid, execution_id, seat, model)`, from which both `wikitoolkit usage report --feat FEAT-123` and the Grafana dashboards read.

## Current state

The pieces that can carry a per-spec usage record already exist; what is missing is the record itself and its writers.

**Exists (from the current codebase and prior brainstorms):**

- `flows/dev_loop/sdd_coder/engine.py` + `toolkit.py` (`SddCoderToolkit`): `coder_plan`, `coder_run_chunk`, `coder_prepare_native`, `coder_begin_execution`, `coder_end_execution`, `coder_record_feedback`, `coder_record_review`, `coder_status`. Executions carry `task_id`, `attempt_uid`, `backend`, `model`, `execution_id`.
- `knowledge/wiki/ledger/`: `LedgerLog` (append-only `events.jsonl`), `LedgerService.from_root / export_snapshot / compact / audit`, `LedgerEventKind` (today: work and insight events), `find_shared_root` resolving the main worktree via the git common dir. Hardened for concurrent worktree writers (WAL, `busy_timeout`, `BEGIN IMMEDIATE`).
- `knowledge/wiki/ledger/coder_feedback.py`, `coder_reviews.py`, `coder_suspensions.py`: per-execution planes keyed by `(task_id, attempt_uid, backend, model, execution_id)` — the same key a usage record needs.
- `AbstractClient` already extracts provider usage per completion (`input_tokens`, `usageMetadata`, …) for every parrot LLM client.
- `sdd/state/<FEAT-ID>/state.json` checkpoints: the authoritative `feat_id → current task` mapping on the `dev` branch.
- Claude Code OTel export and the Codex plugin, both already shipping to Grafana.

**Does NOT exist (to be confirmed by `/sdd-proposal`, not assumed):**

- A `usage.*` event kind in `LedgerEventKind`, or any ledger plane that stores tokens or cost.
- Any call from `coder_end_execution` (or from `AbstractClient`) that persists usage to SDD state. The `report_usage` callback in the per-turn compaction design is a calibration hook, not a usage store, and its implementation status must be checked.
- Any Claude Code hook (`UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `SessionEnd`) in the SDD plugin that records `session_id` / `agent_id` against a `feat_id`.
- A price table (model × token type → USD) owned by ai-parrot; each seat currently computes or omits USD on its own.
- A `wikitoolkit usage …` CLI group or MCP target.
- A Grafana datasource reading from SDD state or the ledger; the dashboards read the OTel pipeline only.

## Seats and their telemetry surfaces

Each seat exposes provider-reported tokens somewhere; only the dev-loop seat exposes them inside the SDD process. Facts below for Claude Code were verified against the official docs on 2026-10-30 (sources at the end); Codex rows are unverified and belong to the research directives.

| Seat | Where usage is reported | Keys available | Attribution to spec | Verified |
| --- | --- | --- | --- | --- |
| dev-loop (`sdd-coder` on parrot backends) | `AbstractClient` per completion; `coder_end_execution` boundary | `task_id`, `attempt_uid`, `execution_id`, `backend`, `model` | Direct — the engine owns the key | yes (codebase) |
| Claude Code native, main loop | OTel event `claude_code.api_request` | `session.id`, `prompt.id`, `model`, `request_id`, `query_source=main`, `input/output/cache_read/cache_creation_tokens`, `cost_usd` | Needs `session.id → feat_id` from a hook | yes |
| Claude Code native, `Task` sub-agents | Same event with `query_source=subagent`, `agent.name` (sub-agent type), `agent_id`, `parent_agent_id` (v2.1.310+) | as above + `agent_id` | Needs `agent_id → execution_id` from `SubagentStop` | partly — parent `session.id` on sub-agent events implied, not stated |
| Claude Code metrics (`claude_code.token.usage`, `claude_code.cost.usage`) | OTel metrics, today's Grafana source | `session.id`, `agent.name`, `query_source`; no `agent_id`, no `prompt.id` | Per session only; cannot reach task level | yes |
| Claude Code hooks | stdin JSON on every hook | `session_id`, `prompt_id` (= OTel `prompt.id`), `cwd`, `transcript_path`; in sub-agents `agent_id`, `agent_type`; `SubagentStop` adds `agent_transcript_path`, `last_assistant_message` | The bridge: hooks see the SDD side, OTel sees the usage side | yes |
| Claude Code raw bodies (`OTEL_LOG_RAW_API_BODIES=file:<dir>`) | `<dir>/index.jsonl` + response files with real `usage` | `session_id`, `query_source`, `model`, `request_id`, `message_id` | Local alternative to a collector; stores full prompts | yes (v2.1.274+) |
| Claude Code transcripts (`~/.claude/projects/*/<session>.jsonl`) | internal format, changes between versions | — | Not a stable source; do not parse | yes (docs say internal) |
| Agent SDK (if `sdd-coder` native were driven from Python) | `AssistantMessage.usage`, result `total_cost_usd`, `model_usage` (includes sub-agents) | `session_id`, `message_id` | Direct, but `total_cost_usd` is a client estimate | yes |
| Codex as coder backend | `codex exec --json` event stream (`turn.completed` usage?) | process-local | Direct if the engine parses the stream | **no** |
| Codex interactive | Codex OTel export → Grafana plugin | unknown | Unknown whether it honours `OTEL_RESOURCE_ATTRIBUTES` or exposes a session id to a wrapper | **no** |

Two constraints shape the design:

- Custom OTel attributes are set once per process via `OTEL_RESOURCE_ATTRIBUTES` (no spaces, cannot override `session.id`/`user.id`). They can tag a session with `sdd.feat=FEAT-123` when `claude` is launched inside the feature worktree, but cannot change per task inside a session.
- Token counts in OTel events are provider-reported; `cost_usd` is not labelled as billing data and the SDK documents its cost as an estimate. Tokens are the ground truth; USD must be derived centrally (see cost model).

## Proposed design: a usage plane in the ledger

The ledger becomes the single owner of per-spec usage: every seat appends `usage.*` events to the shared-root `events.jsonl`, `ledger.db` indexes them, and both the CLI report and Grafana read from that index. No seat computes USD; the plane does.

**Event kinds (extend `LedgerEventKind`):**

| Kind | Written by | Payload (beyond the common envelope) |
| --- | --- | --- |
| `usage.recorded` | all three seats | `seat`, `provider`, `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `request_id`, `source_ref` (OTel `request_id`, Codex event id, or parrot response id) |
| `usage.session.bound` | Claude Code / Codex hooks or wrappers | `seat`, `session_id`, `feat_id`, `task_id?`, `worktree`, `otel_resource` |
| `usage.agent.bound` | `SubagentStop` hook | `session_id`, `agent_id`, `agent_type`, `execution_id`, `task_id`, `attempt_uid` |
| `usage.priced` | the plane, on report or compaction | `price_table_version`, `usd`, `policy` (`billed` / `subscription` / `estimate`) |

**Correlation key** on every `usage.recorded`: `feat_id`, `task_id`, `attempt_uid`, `execution_id`, `seat`, `model`. The dev-loop seat fills it directly. The other two seats write partial keys (`session_id`, `agent_id`) and the plane resolves them through the `*.bound` events at index time — a deterministic join, never a time-window heuristic.

**Envelope**: reuse the existing `LedgerEvent` (`ts`, `actor`, `worktree`, `kind`, `payload`) so `LedgerService.export_snapshot / compact / audit` cover usage for free. Idempotency: `usage.recorded` is keyed by `(seat, source_ref)` so an OTel replay or a hook retry does not double count — the same rule `coder_feedback.py` applies ("retries of the recording call are not recurrences").

**Readers:**

- `wikitoolkit usage report --feat FEAT-123 [--by task|seat|model]` and an MCP target so `sdd-worker` can read spend mid-run (budget gates become possible later).
- Grafana: one datasource on a Postgres mirror of `ledger.db` usage tables (or the SQLite file via a sidecar). The OTel pipeline stays as-is for session-level dashboards; per-spec panels query the plane.

Why the ledger and not a new store: it already solves the hard part (shared root across worktrees, append-only log, SQLite concurrency), and the beads-style work ledger already keys its planes by `(task_id, attempt_uid, execution_id)`. Usage is one more plane on the same spine.

## Correlation protocol per seat

&#91;embedded content: usage flow · 3 seats, 4 ingestors, 1 plane, 3 readers\]

The Claude Code seat is the only one that needs two ingestors: hooks supply the SDD side of the key, the collector supplies the usage side, and the plane joins them. The existing Grafana pipeline is untouched.

| Seat | Writes `usage.recorded` from | Writes the binding from | Join rule in the plane |
| --- | --- | --- | --- |
| dev-loop | `coder_end_execution`: totals accumulated from `AbstractClient` across the execution's completions | none needed — the engine writes the full key | direct |
| Claude Code native, main loop | collector pipeline B: `api_request` with `query_source=main` | `UserPromptSubmit` or `SessionStart` hook: `session_id` + `feat_id` resolved from `cwd` (worktree) or the `/sdd-start FEAT-…` prompt; `task_id` from `state.json` at that moment | `session.id` → `usage.session.bound`; task attributed to the task current at the event's `ts`, orchestration overhead to `task_id=null` |
| Claude Code native, `sdd-coder` sub-agent | collector pipeline B: `api_request` with `query_source=subagent`, `agent_id` | `SubagentStop` hook with `agent_type=sdd-coder`: parses `execution_id`, `task_id`, `attempt_uid` from the coder's structured final block in `last_assistant_message`; writes `usage.agent.bound` | `(session.id, agent_id)` → `usage.agent.bound` → full key; sub-agents of other types bind to the session's task |
| Codex as coder backend | engine parses `codex exec --json` usage events inside `coder_run_chunk` | none needed | direct |
| Codex interactive (if in scope) | Codex OTel export routed through the same collector, or a wrapper that tails its stream | wrapper launched per worktree records `session → feat_id` | as Claude Code main loop |

Fallbacks, in order: a missing `usage.agent.bound` falls back to `prompt.id` ↔ hook `prompt_id`; a missing `usage.session.bound` falls back to the `sdd.feat` resource attribute set by the launcher; anything still unresolved is kept as `feat_id=null` and surfaces in `wikitoolkit usage audit`, never dropped.

## Cost model

Tokens are the only numbers the three seats agree on, so the plane stores tokens as facts and derives USD as a view. This is what makes the per-spec number "correct": a single formula, applied once, versioned.

- **Facts**: the four token counters per request, as reported by the provider (Anthropic `usage`, GenAI `usageMetadata`, Codex event, OTel `api_request`). Never a client-side cost figure.
- **Price table**: `usage/prices.yaml` in the shared root (`model`, `provider`, `input`, `output`, `cache_read`, `cache_creation` in USD per 1M tokens, `valid_from`). Versioned by content hash; `usage.priced` records the version used, so a price change re-prices old specs explicitly rather than silently.
- **Policy per seat**: `billed` (API key — real marginal cost), `subscription` (Claude Code or Codex on a plan — marginal cost zero, list price shown as `equivalent_usd`), `estimate` (tokens known, price unknown). Reports show both columns; the headline is the policy's own number. Without this, a Max-plan `sdd-worker` run inflates a spec's cost with money that was never spent.
- **Cross-check**: the plane keeps each seat's self-reported cost (`cost_usd`, `total_cost_usd`) as `source_cost_usd` for reconciliation only. A drift above 5% between `source_cost_usd` and the plane's `usd` for the same `request_id` is an audit finding, not a value.
- **Attempts vs tasks**: cost is attributed to `attempt_uid`; a task's cost is the sum over attempts including abandoned ones, because the retry is part of what the spec cost. A spec's cost = sum over its tasks + the orchestration overhead (`sdd-worker`'s own `query_source=main` requests, attributed to `task_id=null`).

## Options considered

Recommended: **Option C** — a ledger usage plane fed by the dev-loop engine, Claude Code hooks plus an OTel collector fan-out, and a Codex wrapper. It is the only option that gives task-level attribution for all three seats without parsing internal formats.

| Option | How attribution reaches the spec | Pros | Cons |
| --- | --- | --- | --- |
| A. Grafana-only: tag every seat with `OTEL_RESOURCE_ATTRIBUTES=sdd.feat=…` and build the per-spec panels in Grafana | One attribute per process, set by a per-worktree launcher | Smallest change; nothing new in ai-parrot | Session-level only (no task/attempt); Codex may not honour the attribute; USD stays each seat's estimate; dev-loop seat still outside Grafana |
| B. Transcript scraping: parse Claude Code `*.jsonl` and Codex session rollouts after the fact | File paths from hooks (`transcript_path`, `agent_transcript_path`) | No collector, no network | Formats documented as internal and version-dependent; async writes lag the turn; breaks silently on upgrades |
| C. Ledger usage plane with three ingestors (recommended) | `usage.recorded` + `usage.*.bound` events; join at index time | Task/attempt granularity; one price table; reuses ledger infra; Grafana reads the same numbers as the CLI | Needs an OTel collector sink (or raw-bodies index) and hooks in the SDD plugin; Codex ingestor is a spike |
| D. Drive the native seat through the Agent SDK instead of Claude Code's `Task` | `model_usage` and `session_id` on each result, written by the engine | Direct, no hooks | Changes how `sdd-worker` runs today; `total_cost_usd` is still an estimate; does not cover interactive Claude Code or Codex |

Option A is kept as a complement inside C: the launcher still sets `sdd.feat` so the existing Grafana session panels gain a feature label at zero cost, and the plane uses it as a fallback when a `usage.session.bound` event is missing.

## Impact & integration

Additive everywhere; no breaking API change. Lane split suggested for `/sdd-task`: Lane 0 models + event kinds, Lane 1 dev-loop ingestor, Lane 2 Claude Code hooks + collector sink, Lane 3 Codex ingestor (after its spike), Lane 4 CLI/MCP/Grafana readers.

| Affected component | Impact | Notes |
| --- | --- | --- |
| `knowledge/wiki/ledger/events.py` | extends | `usage.recorded`, `usage.session.bound`, `usage.agent.bound`, `usage.priced` + payload models |
| `knowledge/wiki/ledger/usage.py` (new) | new | `UsageStore.from_root`, `record`, `bind_session`, `bind_agent`, `resolve`, `report`; index tables in `ledger.db` |
| `knowledge/wiki/ledger/service.py` | extends | usage covered by `export_snapshot`, `compact` (roll per-request rows into per-attempt totals after N days), `audit` (unresolved bindings, cost drift) |
| `usage/prices.yaml` + `knowledge/wiki/ledger/pricing.py` (new) | new | price table loader, content-hash versioning, per-seat policy |
| `flows/dev_loop/sdd_coder/engine.py` | extends | collect `AbstractClient` usage per completion inside an execution; emit `usage.recorded` at `coder_end_execution`; Codex backend parses the JSON event stream |
| `flows/dev_loop/sdd_coder/toolkit.py` | extends | `coder_usage_status(execution_id)`; `coder_end_execution` returns the totals |
| `clients/abstract.py` (`AbstractClient`) | minimal | expose the last response's normalised `Usage` (already extracted) through one accessor; no new call path |
| `.claude/hooks/` (SDD plugin) + `flows/dev_loop/_subagent_data/*` | new | `UserPromptSubmit`/`SessionStart` → `usage.session.bound`; `SubagentStop` (agent\_type `sdd-coder`) → `usage.agent.bound`; hooks shell out to `wikitoolkit usage bind …` |
| `.claude/agents/sdd-coder.md`, `sdd-worker.md` | modifies | native coder's final structured block carries `execution_id`, `task_id`, `attempt_uid` so `last_assistant_message` is parseable; keep both copies in sync |
| `otel/collector.yaml` (new, ops) | new | fan-out: pipeline A → Grafana (unchanged); pipeline B logs-only → file or OTLP sink consumed by `wikitoolkit usage ingest-otel` |
| `knowledge/wiki/cli.py`, `mcp/local_cli.py` | extends | `usage` group: `report`, `bind`, `ingest-otel`, `ingest-codex`, `price`, `audit`; MCP target for `sdd-worker` |
| Grafana | ops | one datasource on the usage tables (Postgres mirror or SQLite sidecar); per-spec panels |
| `sdd/state/<FEAT-ID>/state.json` | reads only | the plane reads `current_task` / `attempt` to fill keys; nothing written there |

## Research directives for `/sdd-proposal`

`/sdd-proposal` must verify three surfaces against real code and real runs before it writes anything: the native agents inside ai-parrot, the Claude Code client, and the Codex client. Every "exists" claim below is a hypothesis to confirm with a file path, a line, or a captured event — not a given.

**1. Native agents (ai-parrot codebase)**

- `AbstractClient` and each concrete client (`anthropic`, `google_genai`, `openai`, `groq`, `huggingface`): where provider usage is parsed today, which fields are normalised, whether cache tokens are kept, and whether a structured `Usage` object already exists or usage is logged and dropped.
- `flows/dev_loop/sdd_coder/engine.py`: the lifecycle between `coder_begin_execution` and `coder_end_execution`; how many completions one execution makes; where the engine holds the client instance so usage can be accumulated per `execution_id`; what `coder_prepare_native` returns and whether it already carries `execution_id` to the native coder.
- `knowledge/wiki/ledger/`: the exact `LedgerEvent` envelope, `LedgerEventKind` enum, how `coder_feedback.py` dedups retries, how `ledger.db` indexes a plane (schema, migration pattern), and the `compact` contract — to design `usage` tables that roll up per-request rows.
- `memory/compaction` / `ConversationMemory.report_usage`: implemented or still design? If implemented, decide whether the usage plane subscribes to the same callback instead of adding a second extraction path.
- `sdd/state/<FEAT-ID>/state.json`: the fields that identify the current task and attempt, and how `sdd-worker` increments `attempt_uid`, so hooks can resolve `cwd → feat_id → task_id` without the LLM.
- Codex as a coder backend: how the engine spawns it today (`codex exec`, flags, stdout handling) and whether `--json` is already parsed.

**2. Claude Code client**

- Pin the installed version. `agent_id` / `parent_agent_id` on events need ≥ 2.1.310; cost-counter attribution redaction was fixed in 2.1.273; raw-bodies `index.jsonl` needs ≥ 2.1.274.
- Capture one `sdd-worker` run with `CLAUDE_CODE_ENABLE_TELEMETRY=1` and an OTLP file exporter: confirm that sub-agent `claude_code.api_request` events carry the parent `session.id`, that `agent.name` is populated for `sdd-coder`, and what `query_source=auxiliary` covers (title generation, compaction) so overhead is attributed and not lost.
- Hooks: capture the stdin JSON of `UserPromptSubmit`, `SessionStart`, `SubagentStart`, `SubagentStop`, `Stop`, `SessionEnd` from the SDD plugin; confirm `prompt_id`, `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message`, and the `SessionEnd` reason field name. Confirm whether any env var exposes the session id to a Bash tool call (none documented; `CLAUDE_ENV_FILE` from `SessionStart` is the documented way to export one).
- Decide collector vs raw bodies: measure the size of `OTEL_LOG_RAW_API_BODIES` output for one spec and check it never leaves the shared root; compare with an OTel Collector `filelog`/`otlp` sink. Confirm the Grafana plugin keeps working with the collector in front of it.
- `skill.name` / `plugin.name` attributes: confirm when they are populated, because `sdd-*` commands and the SDD plugin could give attribution for free on the orchestration side.

**3. Codex client**

- Pin the installed Codex CLI version and read its telemetry docs: does it export OTel (`[otel]` config), which events carry token usage, does it honour `OTEL_RESOURCE_ATTRIBUTES`, and is there a hook or `notify` mechanism that exposes a session id.
- `codex exec --json`: capture the event stream for one task and confirm the usage event name and fields (`input_tokens`, `cached_input_tokens`, `output_tokens`, model).
- Interactive sessions: locate the session rollout files, confirm whether they are documented as stable; if not, rule them out as Option B was ruled out for Claude Code.
- Plan policy: confirm whether the Codex seat runs on an API key or a subscription, since it sets the `usage.priced` policy for that seat.

**4. Cross-seat reconciliation run**

- One controlled spec with one task executed three times — once per seat — producing the same diff. Record all three usage paths and reconcile tokens against the provider dashboards. The proposal reports the deltas; `/sdd-spec` fixes the tolerance.

## Spikes (gates before `/sdd-spec`)

- **S1 — Sub-agent attribution in Claude Code OTel.** Run one `sdd-worker` task with the native coder under an OTLP file exporter. Pass: every sub-agent `api_request` carries the parent `session.id`, an `agent_id`, and `agent.name=sdd-coder`; `SubagentStop` input gives an `agent_id` equal to the one on the events. Fail → attribution falls back to `prompt.id` joins and the spec must say so.
- **S2 — Hook-to-ledger binding under worktree concurrency.** Two feature worktrees, two `sdd-worker` sessions in parallel, hooks writing `usage.session.bound` / `usage.agent.bound` via `wikitoolkit usage bind`. Pass: zero lost or cross-bound events; each `usage.recorded` resolves to exactly one `(feat_id, task_id, attempt_uid)`; hook latency added per sub-agent stop < 150 ms.
- **S3 — Codex usage source.** Capture `codex exec --json` for one task and, separately, Codex's OTel output if available. Pass: provider-reported token fields found for every turn, with a stable key to dedup; decide ingestor (`ingest-codex` from the stream vs the collector) and whether the interactive seat is in v1 scope.
- **S4 — Token reconciliation.** The cross-seat run from the research directives. Pass: plane totals within 1% of the provider dashboards for the API-key seats, and the Claude Code `cost_usd` drift from the plane's `usd` measured and documented. This fixes the price table and the per-seat policy before the spec.
- **S5 — Collector fan-out vs raw bodies (non-blocking).** Size and privacy comparison for one spec; informs the ops lane only.

## Open questions

- [ ] Is the interactive Codex seat in v1, or only Codex as a coder backend driven by the engine?
- [ ] Where does `prices.yaml` live for a developer with several packages sharing one managed venv (installer thread): per shared root, or one global file under `~/.parrot/`?
- [ ] Should `sdd-worker` read the plane mid-run to enforce a per-spec token budget, or is reporting enough for v1?
- [ ] Grafana reader: Postgres mirror of the usage tables (one more sync job) or a SQLite datasource sidecar on the shared root?
- [ ] Does the Agent SDK path (Option D) deserve a thin adapter so a future headless `sdd-worker` writes usage directly, or is that deferred until the SDK drives any part of the flow?
- [ ] Retention: how long per-request `usage.recorded` rows stay before `compact` rolls them into per-attempt totals (proposal: 30 days, matching Claude Code's own transcript retention).

## Sources

Claude Code facts verified on 2026-10-30 against: [Monitoring (OpenTelemetry)](https://code.claude.com/docs/en/monitoring-usage), [Hooks reference](https://code.claude.com/docs/en/hooks), [Agent SDK hooks](https://code.claude.com/docs/en/agent-sdk/hooks), [Agent SDK cost tracking](https://code.claude.com/docs/en/agent-sdk/cost-tracking), [Agent SDK subagents](https://code.claude.com/docs/en/agent-sdk/subagents), [Sessions](https://code.claude.com/docs/en/sessions), [Environment variables](https://code.claude.com/docs/en/env-vars), [Status line](https://code.claude.com/docs/en/statusline). ai-parrot facts from the codebase as summarised in `claude/agent-memory-dynamics.brainstorm.md` and `claude/sdd-work-ledger.brainstorm.md`; Codex facts are unverified and belong to the research directives.

