---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-integrations, docs]
tags: [fireflies, mcp, wikitoolkit, telegram, insights, agent]
---

# Feature Specification: FirefliesInsightsAgent — transcripts → wiki inbox → insights → Telegram/Jira

**Feature ID**: FEAT-715
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

**Input**: `sdd/proposals/fireflies-insights-agent.brainstorm.md` (Recommended Option B; 18/18 open questions resolved)
**Base commit for all §6 anchors**: `3d4df63bf`

---

## 1. Motivation & Business Requirements

### Problem Statement

Fireflies.ai records and summarizes every meeting, but that knowledge dies in
Fireflies' own UI. Nothing in this repository today turns a meeting into
**acted-upon work**: the transcripts are not in the LLM-Wiki, nobody is told
what was decided, and the action items never become Jira tickets.

Three capabilities already exist in isolation and have never been joined:

1. **Fireflies over MCP** — `add_fireflies_mcp_server()` and
   `sync_fireflies_transcripts(..., include_summary=True)` can fetch both
   transcripts and Fireflies' own native summary (FEAT-441, merged).
2. **Autonomous wiki ingestion** — `InboxProcessor` (FEAT-626, merged) ingests
   every safe document dropped into the configured inbox directory. It is
   **CLI-only and one-shot**: `wikitoolkit inbox` processes whatever is there
   when it runs, then exits. Nothing watches the folder.
3. **Proactive Telegram + Jira from an agent** — `GitHubReviewer` is the mature
   in-repo pattern: a `TelegramAgentWrapper` injects its bot via
   `set_wrapper()`, the agent pushes to a configured channel, escapes HTML
   entities, chunks to Telegram's 4096-char limit, and wires `JiraToolkit` in
   `post_configure()`.

The existing `FirefliesObsidianAgent` joins only (1) and a *file sink*, targets
an Obsidian vault rather than the wiki inbox, and is a `BasicAgent` with no
skills, no working memory, no Telegram and no Jira.

**Who is affected**: the operator who runs these meetings and currently re-reads
transcripts by hand to extract decisions, risks and action items, and the team
that never sees them because they stay in Fireflies.

### Goals

- **G1** A registered `parrot.bots` agent that pulls Fireflies transcripts **with
  their native Fireflies summary** over MCP and drops each meeting into the wiki
  inbox directory.
- **G2** A **source-agnostic filesystem watcher** over that directory, so
  anything landing there — Fireflies, a scanned PDF, a manual drop — is ingested
  into the LLM-Wiki without a human running a command.
- **G3** Structured **insights** (decisions, risks/blockers, action items with
  owners) derived from transcript + summary, delivered **one message per meeting
  to one configured Telegram channel**.
- **G4** A confirmed insight becomes a **Jira ticket only after explicit human
  confirmation over Telegram**, rendered through a dedicated JiraToolkit
  template.
- **G5** The agent composes `SkillRegistryMixin` (file-based skills) and
  `WorkingMemoryToolkit`, so behaviour is extensible without code changes.
- **G6** **Ingestion and insights are independent paths.** A failed ingest must
  not suppress insights, and a failed insight run must not block ingestion.

### Non-Goals (explicitly out of scope)

- Re-implementing or extending FEAT-481's `FirefliesWikiAgent` (Obsidian vault +
  GraphIndex). That feature is deliberately untouched; the two agents are kept
  apart by their sink. See `proposals/fireflies-insights-agent.brainstorm.md`.
- A `wiki_inbox` MCP tool (ledger issue `f7477bd7bba4`) — not a prerequisite.
- A monolithic agent that owns the watcher internally (brainstorm Option A,
  rejected: it buries wiki infrastructure inside a bot).
- An `AgentsFlow` DAG decomposition (brainstorm Option C, rejected: the mixins
  this feature needs attach to a bot, not to a DAG node).
- Multi-channel or per-participant Telegram delivery; digests.
- Changing `InboxProcessor`'s per-document pipeline or its locking.

---

## 2. Architectural Design

### Overview

Two separable pieces, both delivered by this feature.

**`InboxWatcher`** (`parrot/knowledge/wiki/inbox/watcher.py`, new) — a
`watchdog`-based observer over the configured inbox directory. It debounces
filesystem events, holds **every** candidate behind a uniform size+mtime
stability window (default: two consecutive polls ~1.5 s apart with identical
size and mtime, ≈3 s total), and coalesces the burst into **one serialized**
`InboxProcessor.run()`. It is built on the **already-public, click-free**
`parrot.knowledge.wiki.runtime.build_ingest_runtime()` — that module exists so
"async servers can construct the charter triage and ingest services without
importing CLI code or starting a nested event loop", so **no CLI refactor is
needed**. It ships in two shapes from one implementation: a startable/stoppable
service object, and a `wikitoolkit inbox --watch` mode.

**`FirefliesInsightsAgent`** (`parrot/bots/fireflies_insights.py`, new) — a
`SkillRegistryMixin` + `Agent`. It pulls transcripts with the native summary
over MCP, consults `MeetingRegistry` (FEAT-472) so a handled meeting is never
re-fetched, and writes each meeting **atomically** (temp file + rename) into the
inbox directory. **Independently**, it derives structured insights from the
transcript + summary it already holds, pushes them to the configured Telegram
channel, and — on explicit human confirmation — creates a Jira ticket from a
dedicated template.

The two paths never await each other. The agent may optionally own the
watcher's lifecycle, but it does not contain it, and the watcher runs fine with
no agent at all.

`InboxConfig.stage_git` stays **configuration-driven**: the watcher neither
forces nor overrides it. The default `True` was chosen for occasional manual
runs, so operators running a long-lived watcher set it to `false` themselves —
this must be called out in `docs/wiki/inbox.md`.

Because `/agents/` is git-ignored wholesale, this feature also lands a narrow
`.gitignore` whitelist so the agent's `skills/` and `templates/` are actually
committable (see §6 Edit Sites and §7 Known Risks).

### Component Diagram

```
Fireflies (MCP)
     │  add_fireflies_mcp_server() → mcp_fireflies_<tool>
     ▼
┌──────────────────────── FirefliesInsightsAgent ────────────────────────┐
│  fetch (+include_summary) ── MeetingRegistry gate (suggest_from_date,  │
│                               lookup/classify → record_synced)         │
│         │                                                              │
│         ├─► atomic write (tmp + rename) ─────────────► <inbox dir>     │
│         │                             (fire-and-forget; never awaited) │
│         │                                                              │
│         └─► insights (AbstractClient.invoke(output_type=…))            │
│                 │  WorkingMemoryToolkit parks per-meeting artifacts    │
│                 ▼                                                      │
│             Telegram HTML (escaped, ≤4096 chunks) → public channel     │
│                 │                                                      │
│                 └─ human confirmation ─► JiraToolkit.jira_create_issue │
│                       (template) + best-effort wiki backlink           │
└────────────────────────────────────────────────────────────────────────┘

         <inbox dir>
              │  watchdog events → debounce → uniform stability window
              ▼
         InboxWatcher ──serialized──► InboxProcessor.run() ──► LLM-Wiki
              ▲                         (sole whole-run writer lock)
              └── also: `wikitoolkit inbox --watch`
```

### Integration Points

| Component | Direction | Contract |
|---|---|---|
| `parrot.mcp.integration.MCPEnabledMixin` | agent → MCP | `add_fireflies_mcp_server(api_key=None)`; tools registered as `mcp_fireflies_<name>` |
| `parrot.agents.meeting_registry.MeetingRegistry` | agent → state | `suggest_from_date`, `lookup`, `classify`, `record_synced`, `mark_analyzed`, `mark_wiki_ingested`; degrades to `available=False` |
| `parrot.knowledge.wiki.runtime.build_ingest_runtime` | watcher → wiki | builds `InboxRuntime`; consumed as-is, no promotion needed |
| `parrot.knowledge.wiki.inbox.InboxProcessor` | watcher → wiki | `run(dry_run, limit, force, archive) -> InboxRunReport`; owns the lock |
| `parrot.integrations.telegram` | agent → chat | `telegram_command` decorator; bot injected by `TelegramAgentWrapper.set_wrapper()` |
| `parrot_tools.jiratoolkit.JiraToolkit` | agent → Jira | `jira_create_issue(template=, template_params=)`; wired in `post_configure()` |
| `parrot.tools.working_memory.WorkingMemoryToolkit` | agent → memory | per-meeting intermediate artifacts |
| `parrot.skills.mixin.SkillRegistryMixin` | agent → skills | `skill_paths` → `agents/fireflies_insights/skills/` |
| `parrot.clients.base.AbstractClient.invoke` | agent → LLM | `invoke(prompt, output_type=…)` for validated insight models |

### Data Models

```python
# parrot/bots/fireflies_insights.py  (new)
class FirefliesMeeting(BaseModel):
    """ONE meeting's raw inputs, carried by both paths (S2).

    `sync_fireflies_transcripts` returns a REPORT dict, not these fields, so the
    agent owns its own fetch rather than reusing that method.
    """
    fireflies_id: str
    title: str
    meeting_date: str
    transcript: str
    summary: str = ""                     # Fireflies' own native summary
    participants: list[str] = Field(default_factory=list)
    fingerprint: str                      # meeting_registry.fingerprint(transcript)
    metadata: dict[str, Any] = Field(default_factory=dict)

class ActionItem(BaseModel):
    """One actionable commitment extracted from a meeting."""
    title: str
    owner: str | None = None
    due_date: str | None = None          # ISO-8601 date when the transcript names one
    evidence: str                         # verbatim transcript span supporting it

class MeetingInsights(BaseModel):
    """Structured insight set for ONE meeting; the LLM's `output_type`."""
    meeting_id: str
    meeting_title: str
    meeting_date: str
    decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)

class PendingApproval(BaseModel):
    """One outstanding Telegram confirmation (S8).

    `telegram_command` only attaches slash-command metadata and carries NO
    approval state, so this feature owns the protocol explicitly.
    """
    insight_id: str                       # opaque, stable; what the user confirms
    fireflies_id: str
    action_index: int
    chat_id: str                          # the only chat allowed to confirm
    user_id: str | None = None            # the only user allowed to confirm, when known
    expires_at: str                       # ISO-8601; a stale confirmation is refused
    created_ticket: str | None = None     # durable marker — set once, makes replay idempotent

class InsightRunReport(BaseModel):
    """Outcome of ONE agent run; never raises into the scheduler."""
    fetched: int = 0
    skipped: int = 0
    dropped_to_inbox: int = 0
    insights_sent: int = 0
    errors: list[str] = Field(default_factory=list)

# parrot/knowledge/wiki/inbox/watcher.py  (new)
class WatcherStats(BaseModel):
    """Counters for one watcher lifetime; surfaced by the CLI on shutdown."""
    events_seen: int = 0
    runs_started: int = 0
    documents_processed: int = 0
    lock_busy_retries: int = 0
```

### New Public Interfaces

```python
from parrot.knowledge.wiki.inbox import InboxWatcher          # new re-export
from parrot.bots.fireflies_insights import FirefliesInsightsAgent
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: InboxConfig stability window | yes | New Pydantic field on `InboxConfig` with validator bounds; name + default fixed in §3 | — |
| M2: InboxWatcher | no | — | The debounce/coalesce/lock-retry interplay is the one genuinely novel design in this feature |
| M3: `--watch` CLI mode | yes | One `click.option` + one branch; anchor verified in §6 | — |
| M4: Insight models | yes | Exact Pydantic models given in §2 Data Models | — |
| M5: Agent fetch + inbox drop | no | — | Atomic-write + `MeetingRegistry` gate ordering is a correctness decision |
| M6: Insights + Telegram | yes | Mirrors `GitHubReviewer._notify_telegram_alert` / chunking; anchors in §6 | — |
| M7: Jira confirmation + assets | no | — | Template parameter set is still being designed |
| M8: Docs | yes | Sections named in §3 | — |

### Module 1: InboxConfig stability window
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)
- **Responsibility**: Expose the watcher's quiescence window as configuration.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/wiki/project.py  (modifies project.py:286 class InboxConfig)
  class InboxConfig(BaseModel):          # verified: project.py:286
      max_candidates: int = Field(default=20, ge=1, le=100)      # verified: project.py:299
      lock_timeout: float = Field(default=30.0, ge=0.0)          # verified: project.py:300
      stability_window: float = Field(
          default=3.0, ge=0.0, le=300.0,
          description="Seconds a candidate's size and mtime must stay unchanged before ingestion.",
      )
      stability_poll_interval: float = Field(
          default=1.5, gt=0.0, le=60.0,
          description="Seconds between the size/mtime samples that prove stability.",
      )
      @model_validator(mode="after")
      def _validate_layout(self) -> "InboxConfig":   # verified: project.py:303 — EXTEND, do not replace
          """Also reject a poll interval larger than the window it must sample twice."""
  ```
- **Note (S4)**: the window is a *policy*, not a hard-coded sleep. M2 compares
  **nanosecond** `st_mtime_ns` plus `st_size`, and takes its clock and `stat`
  source by injection so the partial-write and slow-source tests run
  deterministically without real delays.

### Module 2: InboxWatcher
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` (CREATE)
- **Responsibility**: Observe the inbox directory; debounce, gate on stability,
  coalesce bursts into one serialized `InboxProcessor.run()`.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/wiki/inbox/watcher.py  (new)
  class InboxWatcher:
      """Source-agnostic folder watcher that serializes InboxProcessor runs."""

      def __init__(
          self,
          runtime: InboxRuntime,          # verified: inbox/processor.py:43
          *,
          stats: WatcherStats | None = None,
      ) -> None:
          """Bind an already-built runtime; validates inbox paths before observing."""

      async def start(self) -> None:
          """Begin observing. Idempotent; raises RuntimeError if already started."""

      async def stop(self, *, drain: bool = True) -> WatcherStats:
          """Stop observing; when drain, await the in-flight run before returning."""

      async def run_forever(self, *, stop_event: asyncio.Event | None = None) -> WatcherStats:
          """start() → wait for stop_event or cancellation → stop(). Used by the CLI."""

      async def _is_stable(self, path: Path) -> bool:
          """Two samples `stability_poll_interval` apart with identical size+mtime."""

      async def _drain_once(self) -> InboxRunReport:
          """One serialized InboxProcessor.run(); on InboxLockBusy back off and retry,
          never dropping the pending event."""

      async def _startup_scan(self) -> None:
          """Enqueue everything already present before observing (S3), so files
          that landed while the watcher was stopped are not lost forever."""
  ```
- **asyncio ownership contract (S1) — binding**: `start()` captures the running
  loop; watchdog callbacks run on observer threads and may ONLY call
  `loop.call_soon_threadsafe` to hand an event to **one** debounced worker task;
  `stop()` stops and joins the observer, then awaits that worker. **No watchdog
  callback may call `asyncio.run()` or touch `InboxProcessor` directly.**
- **Final-path revalidation (S3)**: a candidate's stability is re-checked on its
  FINAL path immediately before the run, so a rename landing mid-window cannot
  smuggle in a file that was never stable under its final name.

### Module 3: `wikitoolkit inbox --watch`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
- **Responsibility**: Run `InboxWatcher` as a standalone process.
- **Depends on**: Module 2.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/wiki/cli.py  (modifies cli.py:5946 `def inbox(`)
  @click.option("--watch", is_flag=True, help="Observe the inbox directory and ingest continuously.")
  def inbox(..., watch: bool) -> None:          # verified: cli.py:5946
      """Ingest every safe document from the configured inbox directory.

      With --watch, observe the directory until interrupted instead of exiting
      after one pass. --watch is incompatible with --limit and --dry-run.
      """
  ```

### Module 4: Insight models
- **Path**: `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (CREATE)
- **Responsibility**: The Pydantic contracts in §2 Data Models.
- **Depends on**: nothing.
- **Interface Skeleton**: exactly the `ActionItem` / `MeetingInsights` /
  `InsightRunReport` definitions in §2 Data Models.

### Module 5: Agent fetch + atomic inbox drop
- **Path**: `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY — same file as M4)
- **Responsibility**: MCP fetch with summary, `MeetingRegistry` gate, atomic write.
- **Depends on**: Module 4.
- **Interface Skeleton**:
  ```python
  # parrot/bots/fireflies_insights.py
  @register_agent(name="fireflies_insights")   # KEYWORD form — positional raises TypeError
  class FirefliesInsightsAgent(SkillRegistryMixin, Agent):   # Agent verified: bots/agent.py:1562
      """Fireflies meetings → wiki inbox + insights → Telegram → Jira."""

      skill_paths: List[Path] = [Path("agents/fireflies_insights/skills/")]   # mixin verified: skills/mixin.py:85

      def __init__(
          self,
          name: str = "FirefliesInsights",
          *,
          fireflies_token: Optional[str] = None,
          wiki_root: Optional[str | Path] = None,
          public_channel_id: Optional[ChatId] = None,
          jira_templates_dir: Optional[str | Path] = None,
          **kwargs: Any,
      ) -> None: ...

      async def configure(self, app=None) -> None:          # verified: bots/agent.py:179
          """Resolve the inbox dir and open MeetingRegistry."""

      async def post_configure(self) -> None:               # verified: bots/abstract.py:1767
          """Wire JiraToolkit + WorkingMemoryToolkit once self.app exists."""

      async def _ensure_fireflies_mcp(self) -> None:
          """Lazy MCP init; api_key → FIREFLIES_API_KEY → ValueError."""

      async def sync_meetings(self, limit: int = 10) -> InsightRunReport:
          """Fetch, gate on MeetingRegistry, drop atomically, then derive insights.
          Never raises into a scheduler — failures land in report.errors."""

      async def _fetch_meetings(self, limit: int) -> List[FirefliesMeeting]:
          """Own fetch over mcp_fireflies_* (S2). Does NOT call
          sync_fireflies_transcripts — that returns a report dict, not raw inputs."""

      def _drop_to_inbox(self, meeting: FirefliesMeeting) -> Path:
          """Write <inbox>/.<name>.tmp then os.replace() onto the final name.
          The DOT PREFIX is load-bearing: InboxProcessor.discover() skips
          dot-prefixed entries  # verified: inbox/processor.py:167"""
  ```
- **File-only skills (S6) — binding**: the agent sets
  `enable_skill_registry = False` and wires `SkillFileToolkit` directly from its
  `skill_paths`. Leaving the mixin's default `True` would build a **DB-backed**
  `SkillRegistry` persisted at `AGENTS_DIR/{agent_id}/skills`
  (verified: `skills/mixin.py:327-329`) — which both violates C3 and collides
  with the very directory this feature uses for file skills.
  **Do NOT modify `SkillRegistryMixin` itself**: it is shared by every agent,
  and this feature has no mandate to change their behaviour.

### Module 6: Insights + Telegram delivery
- **Path**: `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY)
- **Responsibility**: Derive `MeetingInsights`, render escaped HTML, chunk, send.
- **Depends on**: Modules 4, 5.
- **Interface Skeleton**:
  ```python
  # parrot/bots/fireflies_insights.py
      async def generate_insights(self, transcript: str, summary: str, meta: Dict[str, Any]) -> MeetingInsights:
          """AbstractClient.invoke(output_type=MeetingInsights)  # verified: clients/base.py:1916
          Validation failure is logged and reported, never sent to the channel."""

      def _format_insights_message(self, insights: MeetingInsights) -> str:
          """Telegram HTML; EVERY interpolation escaped.
          Mirrors GitHubReviewer._format_alert_message  # verified: bots/github_reviewer.py:1963"""

      def _chunk_message(self, text: str) -> List[str]:
          """Split under _TELEGRAM_MAX_MESSAGE=4096 reserving _TELEGRAM_PART_RESERVE=32
          # verified: bots/github_reviewer.py:2926, :2929"""

      def _get_telegram_bot(self):
          """getattr(self._wrapper, 'bot', None)  # verified: bots/github_reviewer.py:1958"""

      def set_wrapper(self, wrapper) -> None:
          """Called by TelegramAgentWrapper  # verified: integrations/telegram/wrapper.py:217"""

      async def notify_insights(self, insights: MeetingInsights) -> Dict[str, Any]:
          """Returns {'sent': 0, 'reason': 'no telegram wrapper'} instead of raising
          # pattern verified: bots/github_reviewer.py:1925"""

      @telegram_command("fireflies_sync", description="Fetch and report the latest meetings")
      async def cmd_sync(self, text: str) -> str:
          """On-demand run (C12)."""
  ```
- **Working-memory scope (S9) — binding**: ONE shared `WorkingMemoryToolkit` per
  run, with stable per-meeting keys `meeting:<fireflies_id>:transcript` and
  `meeting:<fireflies_id>:summary`. Entries are scoped and cleared between
  meetings so one meeting's artifacts can never leak into the next.

### Module 7: Jira confirmation + committable assets
- **Path**: `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY),
  `agents/fireflies_insights/templates/` (CREATE),
  `agents/fireflies_insights/skills/` (CREATE), `.gitignore` (MODIFY)
- **Responsibility**: Human-confirmed ticket creation from a template, the
  best-effort wiki backlink, and the ignore-rule change that makes the agent's
  assets trackable.
- **Depends on**: Module 6.
- **Interface Skeleton**:
  ```python
  # parrot/bots/fireflies_insights.py
      @telegram_command("fireflies_ticket", description="Create a Jira ticket from a reported insight")
      async def cmd_create_ticket(self, text: str) -> str:
          """Human confirmation gate (C8). Idempotent: a second confirmation for the
          same insight returns the existing key instead of opening a second ticket."""

      async def _create_ticket(self, insights: MeetingInsights, item: ActionItem) -> Dict[str, Any]:
          """JiraToolkit.jira_create_issue(template=…, template_params=…)
          # verified: parrot_tools/jiratoolkit.py:2608
          project/issuetype fall back to JIRA_DEFAULT_PROJECT / JIRA_DEFAULT_ISSUE_TYPE
          # verified: parrot_tools/jiratoolkit.py:945-946"""

      async def _wiki_backlink(self, fireflies_id: str) -> Optional[str]:
          """Best-effort (C8): resolve the page by EXTERNAL ID through the shared
          source manager (S7). MeetingRegistry.mark_wiki_ingested() returns an
          int row count, not a path  # verified: meeting_registry.py:560 — so it
          cannot be used for this. Returns None when ingestion has produced
          nothing yet; NEVER delays or blocks ticket creation."""

      async def _authorize(self, approval: PendingApproval, chat_id: str, user_id: str | None) -> bool:
          """Confirmation protocol (S8): the confirming chat must match, the user
          must match when known, and `expires_at` must not have passed."""
  ```
- **Approval protocol (S8) — binding**: every reported insight carries an opaque
  `insight_id`. A confirmation is accepted only from the originating chat,
  before `expires_at`. The `created_ticket` marker is written durably **before**
  the reply is sent, so a retried or replayed confirmation returns the existing
  key instead of opening a second ticket. A restart must not silently lose
  pending approvals — they expire explicitly rather than vanishing.
  ```gitignore
  # .gitignore  (modifies .gitignore:297 `/agents/`)
  /agents/*
  !/agents/fireflies_insights/
  /agents/fireflies_insights/*
  !/agents/fireflies_insights/skills/
  !/agents/fireflies_insights/skills/**
  !/agents/fireflies_insights/templates/
  !/agents/fireflies_insights/templates/**
  ```

### Module 8: Documentation
- **Path**: `docs/wiki/inbox.md` (MODIFY), `docs/agents/fireflies-insights.md` (CREATE)
- **Responsibility**: Document the watch mode, the `stage_git` caveat for a
  long-running watcher, and the agent's configuration.
- **Depends on**: Modules 3, 7.

---

## 4. Test Specification

### Unit Tests

| Module | Test file | Key cases |
|---|---|---|
| M1 | `packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py` | defaults; bounds rejected; poll interval > window rejected |
| M2 | `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py` (new) | burst coalesced into ONE run; unstable file deferred; **identical size with changed mtime still counts as unstable**; atomic rename; startup discovery; cancellation; `InboxLockBusy` retried not dropped; `stop(drain=True)` awaits in-flight; `stage_git=false` honoured (S10) |
| M3 | `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` | `--watch` starts the watcher; `--watch --limit` and `--watch --dry-run` rejected |
| M4 | `packages/ai-parrot/tests/bots/test_fireflies_insights.py` (new) | model validation |
| M5 | same | registry skip path; atomic write leaves no `.tmp`; registry unavailable → title fallback |
| M6 | same | HTML escaping of hostile titles; chunking at the 4096 boundary; no wrapper → structured reason, no raise |
| M7 | same | confirmation required; duplicate confirmation idempotent; backlink absent → ticket still created |

### Integration Tests

| Scenario | Test file |
|---|---|
| Drop a file → watcher ingests it end to end on SQLite | `packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher_integration.py` (new) |
| Agent run with a stubbed MCP: drop + insights + Telegram stub | `packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py` (new) |
| **Failure isolation (G6/S10)**: insight delivery survives an ingest failure, and ingestion survives an insight failure | `packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py` (new) |
| **Repeated Telegram confirmation** returns the existing ticket key; wrong chat and expired confirmations refused | `packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py` (new) |
| **Packaging (S5)**: import and one-shot `wikitoolkit inbox` succeed without the watcher extra | `packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py` |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/inbox/test_inbox_config.py
- packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py
- packages/ai-parrot/tests/knowledge/wiki/inbox/test_processor.py
- packages/ai-parrot/tests/knowledge/wiki/inbox/test_end_to_end.py
- packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher.py
- packages/ai-parrot/tests/knowledge/wiki/inbox/test_watcher_integration.py
- packages/ai-parrot/tests/bots/test_fireflies_insights.py
- packages/ai-parrot/tests/bots/test_fireflies_insights_integration.py
- packages/ai-parrot/tests/bots/test_fireflies_insights_assets.py
markers: none

### Test Data / Fixtures

```python
# Key fixtures needed
@pytest.fixture
def inbox_project(tmp_path): ...          # reuse tests/knowledge/wiki/inbox/conftest.py
@pytest.fixture
def fake_fireflies_mcp(): ...             # stub mcp_fireflies_* tools; NO network
@pytest.fixture
def telegram_bot_stub(): ...              # records send_message calls
```

> No `real_llm` tests. The insight call is exercised through a stubbed
> `AbstractClient.invoke`.

---

## 5. Acceptance Criteria

- [ ] **AC1** (G1) The agent fetches transcripts with `include_summary=True` and drops one document per meeting into the configured inbox directory.
- [ ] **AC2** (C11) Every dropped file is written to a temp name and `os.replace()`d; no `.tmp` artifact survives a successful run.
- [ ] **AC3** (G2, C6) A file appearing in the inbox directory is ingested without any command being run.
- [ ] **AC4** (C11) A burst of N files produces exactly **one** `InboxProcessor.run()`, not N.
- [ ] **AC5** (C11) A file still being written is deferred, never ingested partially; the uniform stability window applies to every candidate regardless of producer.
- [ ] **AC6** (C11) On `InboxLockBusy` the watcher backs off and retries; the pending event is never dropped.
- [ ] **AC7** (C13) An already-processed meeting is skipped via `MeetingRegistry` without re-fetching.
- [ ] **AC8** (C13) With the registry unavailable (`available=False`) the run still completes, falling back to title-based skip.
- [ ] **AC9** (G6) A failing ingest does not suppress insights, and a failing insight run does not block ingestion.
- [ ] **AC10** (G3, C7) One Telegram message per meeting to the configured channel; every interpolation HTML-escaped; no message exceeds 4096 chars.
- [ ] **AC11** (C7) With no Telegram wrapper attached the run returns a structured reason and does not raise.
- [ ] **AC12** (G4, C8) No Jira ticket is created without explicit human confirmation.
- [ ] **AC13** (C8) A confirmed insight is created through the Jira template; a duplicate confirmation returns the existing key rather than opening a second ticket.
- [ ] **AC14** (C8) When no wiki page exists yet the ticket is created **without** the backlink and the run succeeds.
- [ ] **AC15** (G5, C3) Skills in `agents/fireflies_insights/skills/` are discovered and listed by `list_skill_commands`.
- [ ] **AC16** (C14) `git check-ignore agents/fireflies_insights/skills/<f>` and `.../templates/<f>` report **not ignored**, while `agents/porygon/**` and a non-whitelisted file inside this agent's own directory remain ignored.
- [ ] **AC17** (C15) The watcher neither sets nor overrides `InboxConfig.stage_git`.
- [ ] **AC18** (C12) Both the scheduled run and the `@telegram_command` reach the same `sync_meetings()` entry point.
- [ ] **AC22** (S3) A file present before the watcher starts is ingested by the startup scan, not lost.
- [ ] **AC23** (S8) A confirmation from a different chat than the one that reported the insight is refused.
- [ ] **AC24** (S8) A confirmation after `expires_at` is refused with an explicit reason, not silently ignored.
- [ ] **AC25** (S6) With the agent configured, no DB-backed `SkillRegistry` is created under `AGENTS_DIR/fireflies_insights/skills`; only the file registry is active.
- [ ] **AC26** (S1) No watchdog callback calls `asyncio.run()` or `InboxProcessor` directly; `stop(drain=True)` joins the observer and awaits the worker.
- [ ] **AC27** (S4) The partial-write and slow-source tests run with an injected clock/stat source and no real sleeps.
- [ ] **AC28** (S9) Two meetings processed in one run never read each other's working-memory entries.
- [ ] **AC29** (S5) Importing `parrot.bots.fireflies_insights` or running `wikitoolkit inbox` **without** the watcher extra installed does not raise `ImportError`; `--watch` fails with an actionable message naming the required extra.
- [ ] **AC19** Every test in the §4 Validation Contract passes.
- [ ] **AC20** `ruff check` clean on all changed files; no banned import (`requests`, `httpx`, `langchain*`, `print`).
- [ ] **AC21** `docs/wiki/inbox.md` documents `--watch` and the `stage_git` caveat for a long-running watcher.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below was re-verified
> at `3d4df63bf`. The brainstorm's `github_reviewer.py` line numbers are **stale**
> — that file moved 163 lines in the `origin/dev` merge of 2026-10-22; the
> numbers here supersede them.

### Verified Imports

```python
from parrot.bots.agent import Agent                                  # bots/agent.py:1562
from parrot.skills.mixin import SkillRegistryMixin                   # skills/mixin.py:47
from parrot.skills.tools import SkillFileToolkit, create_skill_tools # skills/tools.py:381, :642
from parrot.tools.working_memory import WorkingMemoryToolkit         # working_memory/__init__.py:3 (def: tool.py:47)
from parrot.knowledge.wiki.inbox import (                            # inbox/__init__.py:3-4
    InboxProcessor, InboxRuntime, InboxRunReport, InboxDocResult,
)
from parrot.knowledge.wiki.inbox.processor import InboxLockBusy      # inbox/processor.py:64
from parrot.knowledge.wiki.runtime import build_ingest_runtime       # wiki/runtime.py:170
from parrot.knowledge.wiki.project import validate_inbox_paths       # wiki/project.py:315
from parrot.knowledge.wiki.charter import load_charter               # wiki/charter.py:404
from parrot.agents.meeting_registry import MeetingRegistry           # agents/meeting_registry.py:167
from parrot_tools.jiratoolkit import JiraToolkit                     # jiratoolkit.py:772
from parrot.integrations.telegram import telegram_command            # LAZY — see note
from parrot.registry import register_agent                           # ASSIGNMENT — see note
```

> **Two imports are lazy and will NOT appear in a naive grep of the package
> `__init__.py`.** Both were smoke-tested and resolve at runtime:
> - `telegram_command` is a PEP 562 lazy re-export declared in the `_LAZY_EXPORTS`
>   map of `parrot/integrations/telegram/__init__.py` (aiogram costs ~1.6 s to
>   import, so it is deferred). Defined at `integrations/telegram/decorators.py:5`.
> - `register_agent` is not a `def` — it is the assignment
>   `register_agent = agent_registry.register_bot_decorator`
>   (`parrot/registry/__init__.py:12`), exported via `__all__`.
>
> Do not "fix" either import; they work.

### Existing Class Signatures

```python
# parrot/mcp/integration.py:1356
class MCPEnabledMixin:
    async def add_fireflies_mcp_server(self, api_key: Optional[str] = None, **kwargs) -> List[str]: ...  # :1448
# registered via mcp/registry.py:178  method_name="add_fireflies_mcp_server"
# MCP tools are namespaced mcp_fireflies_<tool_name>   # agents/obsidian.py:1258

# parrot/bots/agent.py:40 / :1562
class BasicAgent(Chatbot, NotificationMixin): ...
class Agent(BasicAgent):
    async def configure(self, app=None) -> None: ...        # :179
    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]: ...   # :1024
# parrot/bots/abstract.py:1767
    async def post_configure(self) -> None: ...

# parrot/clients/base.py:1916
    async def invoke(self, prompt: str, *, output_type: Optional[type] = None,
                     structured_output: Optional[StructuredOutputConfig] = None,
                     model: Optional[str] = None, system_prompt: Optional[str] = None,
                     max_tokens: Optional[int] = None, ...) -> ...: ...

# parrot/knowledge/wiki/runtime.py — PUBLIC, click-free builders.
# __all__ = [WikiRuntimeError, persistence_for_project, build_triage_adapters,
#            build_novelty_scorer, build_ingest_runtime]          # runtime.py:26-31
def build_ingest_runtime(                                          # runtime.py:170
    root: Path, config: WikiProjectConfig, store: BaseWikiStore,
    sources: SourceCollectionManager, charter: "Charter", charter_path: Path, *,
    lightweight_model: str, model: str, novelty_scorer: Any,
    adapters: tuple[Any, Any, str, bool] | None = None, fetch_timeout: float = 30.0,
) -> "InboxRuntime": ...
def build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]: ...  # :90
async def build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any: ...  # :113
class WikiRuntimeError(RuntimeError): ...                          # :86
# cli.py:5290 `_build_ingest_runtime` is ONLY a click-flavoured wrapper around these.
# The watcher calls runtime.py directly. Do NOT refactor or export the CLI helper.

# parrot/knowledge/wiki/inbox/processor.py:43
class InboxRuntime(BaseModel):
    """model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)"""   # :46
    root: Path; config: WikiProjectConfig; wiki_config: WikiConfig; charter: Charter
    store: BaseWikiStore; sources: SourceCollectionManager; bookkeeper: WikiBookkeeper
    acquirer: DocumentAcquirer; router: IngestTriageRouter; orchestrator: WikiIngestOrchestrator
    light_adapter: SkipValidation[LLMCaller]; heavy_adapter: SkipValidation[LLMCaller]
    search: WikiCombinedSearch; models: dict[str, str]
class InboxLockBusy(RuntimeError): ...                              # :64
class InboxProcessor:                                               # :133
    def __init__(self, runtime: InboxRuntime, *, today: date | None = None) -> None: ...   # :136
    def discover(self, *, limit: int | None) -> list[DocumentRef]: ...                     # :153
    async def run(self, *, dry_run: bool = False, limit: int | None = None,
                  force: bool = False, archive: bool = True) -> InboxRunReport: ...        # :202
    async def process_one(self, ref: DocumentRef, *, dry_run: bool, force: bool,
                          archive: bool) -> InboxDocResult: ...                            # :275
# run() holds the SOLE whole-run writer lock — the processor, not the CLI, owns it. # :206

# parrot/knowledge/wiki/project.py:286
class InboxConfig(BaseModel):
    dir: str = "inbox"                              # :289
    archive_dir: str = f"{PARROT_DIR}/archive"      # :290
    rejected_subdir: str = "rejected"               # :293
    markdown_dir: str | None = None                 # :294
    date_format: str = "%Y-%m-%d"                   # :297
    stage_git: bool = True                          # :298 — stages archived+projected files in git
    max_candidates: int = 20                        # :299 ge=1 le=100
    lock_timeout: float = 30.0                      # :300 ge=0.0
    @model_validator(mode="after")
    def _validate_layout(self) -> "InboxConfig": ...  # :303
def validate_inbox_paths(root: Path, inbox: Path, archive: Path, markdown: Path) -> None: ...  # :315

# parrot/agents/meeting_registry.py:167
class MeetingRegistry:
    """Async facade over SourceCollectionManager. Constructor takes NO Obsidian toolkit.
    Degraded mode: on sqlite3.Error/OSError it logs ONE warning, sets available=False,
    and every verb returns a neutral value instead of raising."""
    def __init__(self, registry_dir: Path, *, manager: SourceCollectionManager | None = None) -> None: ...  # :184
    @property
    def available(self) -> bool: ...                                               # :228
    async def lookup(self, fireflies_id: str) -> MeetingRecord | None: ...         # :236
    async def classify(self, ...) -> Classified: ...                               # :253
    async def pending_analysis(self) -> list[MeetingRecord]: ...                   # :324
    async def suggest_from_date(self, *, overlap_days: int) -> str | None: ...     # :370
    async def record_synced(self, ...) -> ...: ...                                 # :430
    async def mark_analyzed(self, fireflies_id: str, fingerprint: str) -> None: ...     # :526
    async def mark_analysis_failed(self, fireflies_id: str, error: str) -> None: ...    # :545
    async def mark_wiki_ingested(self, *, at: str | None = None) -> int: ...       # :560
    async def forget(self, fireflies_id: str, *, reject: bool = False) -> bool: ...# :585
    # Vault-coupled verbs this feature does NOT use:
    #   unique_slug(..., vault_path=) :397 | backfill_from_vault :616
    #   merge_duplicates :738 | repair_path :851 | _vault_root(toolkit: ObsidianToolkit) :1066
def normalise_transcript(text: str) -> str: ...     # :69
def fingerprint(text: str) -> str: ...              # :91
class MeetingRecord(BaseModel): ...                 # :110

# parrot/agents/obsidian.py:163  — REFERENCE ONLY, not a base class
class FirefliesObsidianAgent(BasicAgent):
    async def _ensure_fireflies_mcp(self) -> None: ...                     # :320
    async def sync_fireflies_transcripts(self, limit: int = 10, skip_existing: bool = True,
        filters: Optional["FirefliesFilters"] = None, include_summary: bool = False,
        force_refetch: bool = False) -> Dict[str, Any]: ...                # :344
    async def _call_fireflies_tool(self, tool_name: str, args: Dict[str, Any]) -> Any: ...  # :1243
class FirefliesFilters(BaseModel): ...                                     # :62
# `limit` is a TOTAL across pages, not a page size; the tool caps one call at 50
# and paginates internally (skip=0,50,100,…).                              # :357

# parrot/bots/github_reviewer.py:495  — PATTERN SOURCE (line numbers re-verified at 3d4df63bf)
class GitHubReviewer(Agent):
    def set_wrapper(self, wrapper) -> None: ...                 # :882
    async def post_configure(self) -> None: ...                 # :888 — wires GitToolkit + JiraToolkit
    async def _notify_telegram_alert(self, payload: Dict[str, Any], ticket_key: str,
                                     result: PRReviewResult) -> Dict[str, Any]: ...  # :1925 — never raises
    def _get_telegram_bot(self): ...                            # :1958 — getattr(self._wrapper, "bot", None)
    def _format_alert_message(self, payload, ticket_key, result) -> str: ...  # :1963 — all interpolations escaped
    _TELEGRAM_MAX_MESSAGE = 4096                                # :2926
    _TELEGRAM_PART_RESERVE = 32                                 # :2929
# from parrot.integrations.telegram import telegram_command     # github_reviewer.py:77

# parrot/integrations/telegram/decorators.py:5
def telegram_command(command: str, description: str = "", parse_mode: str = "keyword") -> Callable: ...
# parse_mode: "keyword" | "positional" | "raw"
# TelegramAgentWrapper calls agent.set_wrapper(self)   # integrations/telegram/wrapper.py:217

# parrot/skills/mixin.py:47
class SkillRegistryMixin:
    enable_skill_registry: bool = True          # :77
    skill_paths: List[Path] = []                # :85
    inject_skills_into_prompt: bool = True      # :89
    tenant_based: bool = False                  # :110
    tenant_id: Optional[str] = None             # :112
# Usage: class MyAgent(SkillRegistryMixin, AbstractBot)
class SkillFileToolkit(AbstractToolkit): ...    # skills/tools.py:381
def create_skill_tools(registry: SkillRegistry, agent_id: str, include_write_tools: bool = True,
    file_registry: Optional["SkillFileRegistry"] = None, learned_dir: Optional[Path] = None, *,
    view_provider: Optional[Callable[[], Any]] = None,
    registry_provider: Optional[Callable[[], Optional[SkillRegistry]]] = None,
) -> List[AbstractTool]: ...                     # skills/tools.py:642
class SkillFileRegistry: ...                     # skills/file_registry.py:17
class SkillsDirectoryLoader: ...                 # skills/loader.py:26

# parrot/tools/working_memory/tool.py:47
class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit): ...

# parrot_tools/jiratoolkit.py:772
class JiraToolkit(AbstractToolkit):
    async def jira_create_issue(self, project: Optional[str] = None, summary: str = "",
        issuetype: Optional[str] = None, description: Optional[str] = None,
        assignee: Optional[str] = None, priority: Optional[str] = None,
        labels: Optional[List[str]] = None, components: Optional[List[str]] = None,
        due_date: Optional[str] = None, parent: Optional[str] = None,
        original_estimate: Optional[str] = None, fields: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None, template_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...                                  # :2608
    async def jira_create_issue_link(self, inward_issue: str, outward_issue: str,
        link_type: str = "Relates", comment: Optional[str] = None) -> Dict[str, Any]: ...  # :4375
# __init__ (:889, :964-971): templates_dir kwarg or JIRA_TEMPLATES_DIR env;
#   a non-directory is WARNED about and ignored, never raised; stays None when unset.
# Defaults (:945-946): default_project = JIRA_DEFAULT_PROJECT (fallback "NAV")
#                      default_issue_type = JIRA_DEFAULT_ISSUE_TYPE (fallback "Task")
```

### Integration Points

- `register_agent` **must be keyword-called**: `@register_agent(name="x")`.
  The positional form `@register_agent("x")` raises `TypeError`
  (documented at `bots/flows/result_agent.py:17`).
- `.gitignore` facts at `3d4df63bf`: `templates/` at **:274** (standalone line,
  `grep -cFx` = 1) and `/agents/` at **:297** (standalone line, `grep -cFx` = 1).
  `git check-ignore -v agents/fireflies_insights/templates/x.j2` answers
  `.gitignore:297:/agents/`. The in-file comment above :297 says this is
  deliberate: *"only NEW agent files are ignored again"*. Evidence: of the four
  agents with a `skills/` dir on disk, only `flex_dashboard` (12 files) and
  `odoo_agent` (4) are tracked; `porygon` and `security_advisor` have **0**.
- A plain negation does **not** work — git cannot re-include a path under an
  excluded *directory*. The rule must ignore the children instead. The M7 block
  was tested in a scratch repo with these verified outcomes:
  tracked → `agents/fireflies_insights/{skills,templates}/**`;
  ignored → `agents/porygon/**` (via `/agents/*`);
  ignored → `agents/fireflies_insights/secret_runtime.json` (via `/agents/fireflies_insights/*`).
  It is a narrow whitelist, not a blanket un-ignore. Precedent for this
  exception style already exists at `.gitignore:275-280`.

### Verified During Design Research (2026-10-22, `3d4df63bf`)

These five claims came from the `codex` cross-check and were each
independently re-verified before being folded in:

- **`watchdog>=4.0` is NOT a base dependency.** `packages/ai-parrot/pyproject.toml` has it only under the `filesystem-transport-full` optional extra; `[project.dependencies]` has no `watchdog` entry. A normal `pip install ai-parrot` lacks it.
- **`InboxProcessor.discover()` skips dot-prefixed entries** (`inbox/processor.py:167`, `if name.startswith("."):`). A dot-prefixed temp name is therefore safe from mid-write ingestion — this is load-bearing for AC2/AC5.
- **`sync_fireflies_transcripts()` returns a REPORT dict** (`report["synced"]`, `report["errors"]`, `report["from_date"]`), not the raw transcript and summary. The agent must own its own fetch to satisfy C5.
- **`MeetingRegistry.mark_wiki_ingested(...) -> int`** returns a stamped-row count (`meeting_registry.py:560`), not a document id or path. It cannot resolve the wiki backlink.
- **`SkillRegistryMixin` builds a DB-backed registry by default.** With `enable_skill_registry=True` (the default, `mixin.py:77`), `_configure_skill_registry` sets `persistence_path = agents_dir / agent_id / "skills"` (`mixin.py:327-329`) — the same directory this feature uses for FILE skills. Passing `skill_paths` does **not** disable it.

### Does NOT Exist (Anti-Hallucination)

- ~~`FirefliesWikiAgent`~~ — **not on `dev`**. It exists only on the unmerged branch `feat-fireflies-wiki-agent` (FEAT-481, 16 tasks stuck `in-progress`). Do not import it.
- ~~`parrot/agents/fireflies_wiki.py`~~ — no such file.
- ~~any inbox watcher / `InboxWatcher` / `--watch` flag~~ — does not exist today; this feature creates it. Verified absent: `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py`.
- ~~`parrot/bots/fireflies_insights.py`~~ — verified absent at `3d4df63bf`; this feature creates it.
- ~~`wiki_inbox` MCP tool~~ — no `wiki_inbox` symbol anywhere under `packages/ai-parrot/src/parrot/`, and no `knowledge/wiki/mcp/` package. Ledger issue `f7477bd7bba4` asks for it; **not** a prerequisite.
- ~~a need to promote `cli.py:_build_ingest_runtime` into a public seam~~ — the public seam **already exists** as `parrot.knowledge.wiki.runtime.build_ingest_runtime`.
- ~~`MeetingRegistry` requiring an `ObsidianToolkit`~~ — its constructor takes `registry_dir` + optional `SourceCollectionManager` only.
- ~~`GitHubReviewer.TELEGRAM_MAX`~~ — the constants are `_TELEGRAM_MAX_MESSAGE` (:2926) and `_TELEGRAM_PART_RESERVE` (:2929).
- ~~`FirefliesObsidianAgent` as a base class~~ — it is a `BasicAgent` with no skills, memory, Telegram or Jira. Reference only.
- ~~a Fireflies toolkit under `parrot_tools/`~~ — Fireflies is reached only over MCP.

### Edit Sites (Blueprint Anchors)

Verified against: `3d4df63bf`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `    lock_timeout: float = Field(default=30.0, ge=0.0, description="Seconds to wait for the inbox lock.")` | `project.py:300` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/watcher.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/__init__.py` | MODIFY | `__all__ = ["InboxProcessor", "InboxRuntime", "InboxRunReport", "InboxDocResult"]` | `inbox/__init__.py:6` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `def inbox(` | `cli.py:5946` | 1 |
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | CREATE | — | — | — |
| `.gitignore` | MODIFY | `/agents/` — **ambiguous as a substring (6 matches); unique as a whole line (`grep -cFx` = 1)**. Context: preceded by `# untrack); only NEW agent files are ignored again.` | `.gitignore:297` | 1 (exact-line) |
| `agents/fireflies_insights/templates/` | CREATE | — | — | — |
| `agents/fireflies_insights/skills/` | CREATE | — | — | — |
| `docs/wiki/inbox.md` | MODIFY | `(unverified — check before use)` | — | — |
| `docs/agents/fireflies-insights.md` | CREATE | — | — | — |

> `templates/` at `.gitignore:274` is **not** an edit site — M7 does not change
> it. It is recorded in Integration Points because it is the second rule that
> would otherwise swallow the agent's `templates/` directory.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `GitHubReviewer` is the reference for every Telegram and Jira concern:
  wrapper injection, escaping, chunking, `post_configure()` toolkit wiring, and
  returning a structured `{"sent": 0, "reason": …}` instead of raising.
- The watcher builds its `InboxRuntime` through `runtime.build_ingest_runtime`,
  never through `cli.py`.
- `watchdog` is thread-based; bridge its callbacks onto the event loop with
  `loop.call_soon_threadsafe` — never block the loop (codebase conventions).
- `aiohttp` only; Pydantic v2; `self.logger`, never `print`; Google-style
  docstrings; 120-column lines.

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| `InboxConfig.stage_git` defaults `True`; a long-running watcher keeps `git add`-ing into the wiki project's repo | Left to configuration by decision (C15). Must be documented prominently in `docs/wiki/inbox.md` (AC21). |
| `watchdog` emits several events per single file write | Debounce + the uniform stability window; AC4 asserts one run per burst. |
| A concurrent `wikitoolkit inbox` holds the lock | `InboxLockBusy` → back off and retry; never drop the event (AC6). |
| `MeetingRegistry` DB unavailable | Degrades to `available=False` by design; agent falls back to title-based skip (AC8). |
| Telegram 400 on malformed HTML entities | Escape every interpolation; AC10 includes a hostile-title case. |
| Wiki page absent at confirmation time | Backlink is best-effort; ticket is created anyway (AC14). |
| `/agents/` ignore rule change could accidentally un-ignore other agents | AC16 asserts `agents/porygon/**` and a non-whitelisted file in this agent's dir stay ignored. |
| `github_reviewer.py` anchors drift | Already drifted once (163 lines in the 2026-10-22 merge). `/sdd-task` must re-run `grep -c` per §6's rule. |
| `watchdog` missing on a normal install (S5) | Lazy import + actionable error naming the extra; AC29. Route (a) decided — §8 Q1. |
| The mixin's DB registry path collides with the file-skills path (S6) | `enable_skill_registry = False` + direct `SkillFileToolkit`; AC25. Do **not** modify the shared mixin. |
| A restart loses pending Telegram approvals (S8) | Approvals expire explicitly via `expires_at`; `created_ticket` is written durably before the reply; AC23/AC24. |
| Fireflies `limit` is a total across pages, not a page size | Documented in §6; do not treat `limit > 50` as an error. |

### External Dependencies

| Package | Purpose | Notes |
|---|---|---|
| `watchdog>=4.0` | Filesystem events | **Declared ONLY in the `filesystem-transport-full` extra — NOT in `[project.dependencies]`** (verified at `3d4df63bf`). A normal `pip install ai-parrot` does **not** have it. The brainstorm's C10 was wrong. **Decided (§8 Q1, route a): keep it in the extra, import lazily — no manifest change.** |
| `pydantic` v2 | Insight / watcher models | Repo standard |
| `click` | `--watch` flag | Already the wiki CLI's framework |

---

## 8. Open Questions

### Raised by the design-research cross-check

- [x] **Q1 (S5) — how do we ship `watchdog`?** — *Owner: Jesus Lara*: **route (a)**. `watchdog` stays in the existing `filesystem-transport-full` extra; `pyproject.toml` and `uv.lock` are NOT touched. `watcher.py` imports `watchdog` lazily inside `start()`, and `--watch` fails with an actionable message naming the extra (AC29). The base install and the one-shot `wikitoolkit inbox` work without it.

### Carried forward from the brainstorm

All questions from the brainstorm are resolved and carried forward.

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] What to do about the unmerged FEAT-481 agent — *Resolved in brainstorm*: build a new independent agent; leave FEAT-481 exactly as it is. (§1 Non-Goals)
- [x] How the inbox ingestion is triggered — *Resolved in brainstorm*: a real filesystem watcher, built inside this feature. (§3 M2)
- [x] Source of the insights — *Resolved in brainstorm*: transcript + native summary the agent already holds; independent of the ingestion path. (§2 Overview, G6, AC9)
- [x] Telegram cadence and destination — *Resolved in brainstorm*: one message per meeting, to a single configured channel. (§3 M6, AC10)
- [x] How Jira tickets are created — *Resolved in brainstorm*: only on explicit human confirmation over Telegram. (§3 M7, AC12)
- [x] Skill backend — *Resolved in brainstorm*: file-based (`skill_paths` + `SkillFileToolkit`); no DB skill registry. (§3 M5)
- [x] How the watcher runs in production — *Resolved in brainstorm*: both, from one implementation — a service object plus `wikitoolkit inbox --watch`. (§3 M2, M3)
- [x] What triggers an agent run — *Resolved in brainstorm*: scheduled **and** on-demand `@telegram_command`. (§3 M6, AC18)
- [x] Quiescence strategy — *Resolved in brainstorm*: uniform size+mtime window for every candidate; the agent still writes atomically as defence in depth, not as an exemption. (§3 M1, AC2, AC5)
- [x] Stability window value — *Resolved in brainstorm*: two polls ~1.5 s apart (≈3 s), configurable. (§3 M1)
- [x] Jira field mapping — *Resolved in brainstorm*: dedicated JiraToolkit template; `project`/`issuetype` fall back to the `JIRA_DEFAULT_*` env vars. (§3 M7)
- [x] Wiki backlink on the ticket — *Resolved in brainstorm*: best-effort; never delays or blocks ticket creation. (§3 M7, AC14)
- [x] Where the agent's skills live — *Resolved in brainstorm*: `agents/fireflies_insights/skills/` under `AGENTS_DIR`. (§3 M5, AC15)
- [x] Processed-meeting state — *Resolved in brainstorm*: reuse `MeetingRegistry` (FEAT-472). (§2 Integration Points, AC7, AC8)
- [x] `InboxConfig.stage_git` under a watcher — *Resolved in brainstorm*: left to configuration; the watcher never overrides it. (§2 Overview, AC17, AC21)
- [x] `/agents/` is git-ignored wholesale — *Resolved in brainstorm*: fix `.gitignore` with a narrow whitelist rather than `git add -f`. (§3 M7, §6 Integration Points, AC16)
- [x] The Jira template does not exist yet — *Resolved in brainstorm*: ship a base template in `agents/fireflies_insights/templates/`. Its exact parameter set is M7 design work.

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: completed · Transcript: `sdd/state/FEAT-715/design_research/`
> All 19 cited paths passed containment + existence checks. The five
> load-bearing factual claims were independently re-verified before any
> disposition was assigned — three of them corrected real errors in this spec.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define one asyncio owner for InboxWatcher (architecture) | CONFIRM | watchdog callbacks run on observer threads while `InboxProcessor.run()` is async and owns the lock; the ownership contract was under-specified. | §3 M2, §7 Patterns |
| S2 | Expose a structured Fireflies meeting payload (api) | CONFIRM | Verified: `sync_fireflies_transcripts` returns a report dict (`synced`/`errors`/`from_date`), not the raw transcript+summary — so C5 could not be met by calling it. | §2 Data Models, §3 M4/M5 |
| S3 | Specify the atomic-write and startup-scan contract (risk) | CONFIRM | Verified: `discover()` skips dot-prefixed names (processor.py:167), so a dot-prefixed temp is safe — but the startup scan and final-path revalidation were genuinely missing. | §3 M2/M5, AC5a, AC22 |
| S4 | Make quiescence an injectable timing policy (api) | CONFIRM | A hard-coded sleep makes the two-sample rule untestable; injecting clock/stat keeps AC5 deterministic without real delays. | §3 M1/M2, §4 |
| S5 | Resolve watchdog's optional-dependency packaging gap (risk) | ESCALATE | **Verified and it refutes the brainstorm's C10**: `watchdog>=4.0` is NOT in `[project.dependencies]`; it is only in the `filesystem-transport-full` extra. "No new dependency" was false. Which way to resolve it is a packaging-policy call for the owner. | §8 Q1, §7 External Dependencies |
| S6 | Add a genuine file-only mode to SkillRegistryMixin (architecture) | CONFIRM (adapted) | Verified: with `enable_skill_registry=True` (default) `_configure_skill_registry` builds a DB registry at `AGENTS_DIR/{agent_id}/skills` (mixin.py:327-329) — the same path chosen for file skills. Adopted in-scope (set the flag False, wire `SkillFileToolkit` directly); **rejected** the part that would modify the shared mixin, as that expands blast radius to every agent. | §3 M5, §7 Known Risks |
| S7 | Explicit ingestion-to-meeting correlation contract (architecture) | CONFIRM | Verified: `mark_wiki_ingested(...) -> int` returns a stamped-row count, not a path, so the backlink needs resolution by external id. | §3 M7 |
| S8 | Telegram confirmation as an idempotent authorization protocol (api) | CONFIRM | AC13 asserted idempotence without defining a mechanism; `telegram_command` only attaches metadata and carries no approval state. | §3 M7, AC13/AC23/AC24 |
| S9 | Per-meeting working-memory scope (api) | CONFIRM | Without stable keys and inter-meeting isolation one meeting's artifacts can leak into the next. | §3 M6 |
| S10 | Failure-isolation and long-running CLI acceptance tests (testing) | CONFIRM | Directly strengthens the G6 independence guarantee and the watcher contract. | §4, §5 |

Summary: **8** confirmed · **1** confirmed-adapted (S6) · **1** escalated (S5) · 0 rejected.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-715; the `sdd-coder` engine gives
  each task its own sub-worktree inside it.
- **Module dependency graph** (8 modules, 6 edges):
  - M2 → M1 — `InboxWatcher._is_stable` reads `InboxConfig.stability_window` / `stability_poll_interval`, added by M1.
  - M3 → M2 — the CLI flag constructs `InboxWatcher`.
  - M5 → M4 — `sync_meetings` returns `InsightRunReport`, defined by M4.
  - M6 → M4, M6 → M5 — `generate_insights` returns `MeetingInsights` (M4) and is called from the run M5 owns.
  - M7 → M6 — ticket creation consumes a `MeetingInsights` already reported.
  - M8 → M3, M8 → M7 — docs describe the shipped flag and the ignore-rule change.
  - M1 and M4 have no edge between them and are expected to run concurrently.
- **Shared files**: `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` is
  modified by **M4, M5, M6 and M7** — their tasks serialize on it.
  `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` is touched only by M3.
- **Exclusive resources**: **M7** edits `.gitignore`, repo-wide shared state
  outside any module's own files — its tasks are `parallel: false`.
- **Cross-feature dependencies**: none must merge first. `cli.py` is shared with
  other in-flight wiki work (FEAT-569, FEAT-626 follow-ups) — M3's single
  `click.option` keeps that contact surface minimal. FEAT-481 is deliberately
  untouched; verify before merging that neither branch started editing the
  other's files.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Jesus Lara | Initial draft from the accepted brainstorm (18/18 questions resolved); all §6 anchors re-verified at `3d4df63bf` |
| 0.2 | 2026-10-22 | Jesus Lara | Folded the `codex` design-research cross-check: 8 CONFIRM, 1 CONFIRM-adapted, 1 ESCALATE. Corrected the false "watchdog is already a dependency" claim (§8 Q1); added the asyncio-ownership contract, the startup scan, the structured Fireflies payload, the file-only skills requirement, the backlink-by-external-id contract and the approval protocol. AC22–AC29 added. |
