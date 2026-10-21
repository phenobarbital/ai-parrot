---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-integrations, docs]
tags: [fireflies, mcp, wikitoolkit, telegram, insights, agent]
---

# Brainstorm: FirefliesInsightsAgent — transcripts → wiki inbox → insights → Telegram/Jira

**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: accepted
**Recommended Option**: Option B
**Open questions**: 18 of 18 resolved 2026-10-22 — none open (see Open Questions)

---

## Problem Statement

Fireflies.ai records and summarizes every meeting, but that knowledge dies in
Fireflies' own UI. Nothing in this repository today turns a meeting into
**acted-upon work**: the transcripts are not in the LLM-Wiki, nobody is told
what was decided, and the action items never become Jira tickets.

Three capabilities already exist in isolation and have never been joined:

1. **Fireflies over MCP** — `add_fireflies_mcp_server()` and
   `sync_fireflies_transcripts(..., include_summary=True)` can fetch both
   transcripts and Fireflies' own native summary (FEAT-441, merged).
2. **Autonomous wiki ingestion** — `InboxProcessor` (FEAT-626, merged) ingests
   every safe document dropped into the configured inbox directory, classifying
   it against the editorial charter and linking it into the knowledge graph.
   It is **CLI-only and one-shot**: `wikitoolkit inbox` processes whatever is
   there when it runs, then exits. Nothing watches the folder.
3. **Proactive Telegram + Jira from an agent** — `GitHubReviewer` (`bots/github_reviewer.py`)
   is the mature in-repo pattern: a `TelegramAgentWrapper` injects its bot via
   `set_wrapper()`, the agent pushes messages to a configured channel, escapes
   HTML entities, chunks to Telegram's 4096-char limit, and wires `JiraToolkit`
   in `post_configure()`.

The existing `FirefliesObsidianAgent` (`agents/obsidian.py`) joins only (1) and
a *file sink*, and it targets an Obsidian vault, not the wiki inbox. It is a
`BasicAgent`, so it has no skills, no working memory, no Telegram and no Jira.

**Who is affected**: the operator who runs these meetings and currently
re-reads transcripts by hand to extract decisions, risks and action items, and
the team that never sees them because they stay in Fireflies.

### Prior art in this repo — and why this is not a duplicate

`FEAT-481 fireflies-wiki-knowledgebase-agent` exists with 16 tasks stuck at
`in-progress` on the unmerged branch `feat-fireflies-wiki-agent` (66 commits
ahead of `dev`). It builds a `FirefliesWikiAgent` that compiles meetings into a
**contract-governed Obsidian vault plus a derived GraphIndex**, per
`sdd/references/obsidian-wiki-operating-contract.md`. It has no Telegram, no
Jira, no working memory and no skills, and it does not use the FEAT-626 inbox.

**Decision (user, 2026-10-22)**: this feature is a **new, independent agent**.
FEAT-481 is left exactly as it is. The two agents are kept apart by their sink:
FEAT-481 writes an Obsidian vault, this one writes the wiki inbox directory.

---

## Constraints & Requirements

- **C1** The agent lives in `parrot.bots` (core `ai-parrot`), following the
  `GitHubReviewer` precedent of a core bot that imports
  `parrot.integrations.telegram` and `parrot_tools.jiratoolkit`.
- **C2** It must be an `Agent` (not `BasicAgent`) composed with
  `SkillRegistryMixin`, so skills can be defined for it.
- **C3** Skills are **file-based**: `skill_paths` + `SkillFileToolkit`, versioned
  on disk, rooted at `agents/fireflies_insights/skills/` under `AGENTS_DIR` —
  the convention already used by `agents/porygon/`, `agents/flex_dashboard/`,
  `agents/odoo_agent/` and `agents/security_advisor/`. **Not** `.agent/skills/`,
  which is the SDD tooling's own tree. No DB skill registry in this feature.
  Because `/agents/` is git-ignored wholesale, this feature must also land the
  `.gitignore` whitelist that makes the directory committable — see C14.
- **C4** `WorkingMemoryToolkit` must be wired so intermediate per-meeting
  artifacts survive within a run and are addressable by the LLM.
- **C5** Insights are generated from the **transcript + summary the agent holds
  in memory**, never by waiting on or polling the wiki ingestion. The two paths
  are independent; a failed ingest must not suppress insights, and vice versa.
- **C6** A **real filesystem watcher** ingests what lands in the inbox folder,
  regardless of who put it there. It is built **inside this feature**, and ships
  in two shapes from one implementation: a startable/stoppable service object,
  and a `wikitoolkit inbox --watch` mode that runs it standalone.
- **C7** Telegram delivery is **per meeting, to one configured channel**,
  mirroring `GitHubReviewer.public_channel_id`. HTML entity escaping and the
  4096-char chunking rule are non-negotiable — Telegram answers 400 otherwise.
- **C8** Jira tickets are created **only after explicit human confirmation over
  Telegram**. The agent never opens a ticket on its own initiative. A confirmed
  insight is rendered through a **dedicated JiraToolkit template** (FEAT-637
  template support), not by assembling fields ad hoc, and the ticket gets a
  **best-effort backlink** to the meeting's wiki page when ingestion has already
  produced one — omitted silently when it has not. A **base template ships with
  the agent** at `agents/fireflies_insights/templates/`, committed to the repo,
  and is reachable by `JiraToolkit(templates_dir=…)` / `JIRA_TEMPLATES_DIR`.
- **C9** Async-first, `aiohttp` only, Pydantic v2 models, `self.logger`, no
  `print`, no LangChain — `.claude/rules/codebase-conventions.md` applies.
- **C10** No new third-party dependency: `watchdog>=4.0` is already declared in
  `packages/ai-parrot/pyproject.toml`.
- **C11** The inbox holds the sole whole-run writer lock (`InboxLockBusy`). The
  watcher must serialize runs and must never ingest a half-written file. Safety
  is **uniform**: every candidate passes the same size+mtime stability window
  regardless of its producer, so there is one code path to test. The agent still
  writes atomically (temp + rename) — belt and braces, not an exemption. Default
  window: **two consecutive polls ~1.5 s apart with identical size and mtime
  (≈3 s total)**, exposed as a new `InboxConfig` field so slow sources can raise
  it.
- **C12** The agent runs on a **schedule and on demand**: a periodic sync like
  `FirefliesObsidianAgent` (designed for ~8 h), plus a `@telegram_command` that
  forces a run — the `GitHubReviewer` pattern.
- **C13** Processed-meeting state reuses **`MeetingRegistry`** (FEAT-472,
  merged); the agent does not invent its own dedup store.
- **C14** The agent's committable assets are made trackable by **editing
  `.gitignore`**, not by `git add -f`. The existing blanket `/agents/` rule
  becomes `/agents/*` (git refuses to re-include anything under an excluded
  *directory*, so the rule must ignore the children instead), followed by a
  narrow whitelist for this agent's `skills/` and `templates/` only. Every other
  agent, and every non-whitelisted file inside this agent's own directory, stays
  ignored. The exact rule block is in Code Context and was verified empirically.
- **C15** `InboxConfig.stage_git` stays **configuration-driven**: the watcher
  neither forces nor overrides it. Operators who do not want a long-running
  watcher staging files into their wiki repo set it to `false` themselves.

---

## Options Explored

### Option A: One monolithic agent with an embedded watcher loop

A single `FirefliesInsightsAgent` owns everything: the Fireflies MCP fetch, the
drop into the inbox directory, an in-agent `watchdog` observer thread bridged to
asyncio, the insight generation, the Telegram push and the Jira confirmation
flow. Everything is one class in `parrot/bots/`.

✅ **Pros:**
- Single deployable unit: start the agent, the whole pipeline is live.
- No new module boundaries to design; fastest path to a working demo.
- The agent directly observes every ingest result, so its reports are complete.

❌ **Cons:**
- Puts wiki infrastructure (a folder watcher over `InboxProcessor`) *inside a
  bot*, so nothing else in the repo can reuse it — a second producer of inbox
  documents would have to re-implement it or import a bot.
- The agent class is already large (MCP + insights + Telegram + Jira + skills +
  working memory); adding the watcher makes it the next `github_reviewer.py`
  (212 KB) and hard to test in pieces.
- Ingestion dies when the agent dies, even though ingestion has nothing to do
  with Fireflies.
- Violates the repo's own layering: `parrot/knowledge/wiki/` owns the wiki.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `watchdog>=4.0` | Filesystem events | Already a declared `ai-parrot` dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py` — Telegram + Jira wiring pattern
- `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` — `InboxProcessor`

---

### Option B: Agent + a first-class `InboxWatcher` service in the wiki package

Two clearly separated pieces, both delivered by this feature:

1. **`InboxWatcher`** — a new service in `parrot/knowledge/wiki/inbox/watcher.py`.
   A `watchdog` observer over the configured inbox directory, debounced and
   quiescence-gated (a file is only a candidate once its size and mtime have
   been stable for N seconds), that coalesces bursts into a **single serialized
   `InboxProcessor.run()`**, built on the **already-public, click-free**
   `parrot.knowledge.wiki.runtime.build_ingest_runtime()` rather than
   re-assembling the 14 bound services of `InboxRuntime` by hand. That module
   exists precisely so "async servers can construct the charter triage and
   ingest services without importing CLI code or starting a nested event loop",
   so **no CLI refactor is needed**. The watcher is source-agnostic: Fireflies,
   a scanned PDF or a manual drop are all the same. It ships in two shapes from
   one implementation — a startable/stoppable service object, and a
   `wikitoolkit inbox --watch` CLI mode.

2. **`FirefliesInsightsAgent`** — a `SkillRegistryMixin` + `Agent` in
   `parrot/bots/fireflies_insights.py`. It pulls transcripts *with* the native
   Fireflies summary over MCP, writes each meeting as one document into the
   inbox directory (atomically: temp file + rename, so the watcher never sees a
   partial write), and **independently** runs its insight method over the
   transcript + summary it already holds. Insights go to the configured Telegram
   channel; a Telegram confirmation turns a selected insight into a Jira ticket
   via `JiraToolkit`.

The agent may optionally own the watcher's lifecycle as a managed background
task, but it does not contain it — and the watcher runs perfectly well without
any agent.

✅ **Pros:**
- Respects the repo's layering: the wiki owns wiki ingestion; the bot owns the
  meeting workflow. Each is independently testable.
- Any future producer (audio notes, email, Drive) gets folder ingestion free.
- Satisfies C5 structurally: the insight path never touches the watcher, so
  neither can block or break the other.
- Atomic writes + quiescence gate + serialized runs directly answer C11.
- Closes a real gap already filed in the work ledger (`f7477bd7bba4` asks for
  the inbox to be reachable beyond the CLI).
- The reusable seam it needs (`runtime.build_ingest_runtime`) **already exists
  and is public**, so the wiki-side cost is one new module plus a CLI flag.

❌ **Cons:**
- Two modules in two packages' trees instead of one class — more surface to
  spec, and the feature spans `bots/` and `knowledge/wiki/`.
- The watcher's quiescence heuristic is genuinely tricky: too short and it
  ingests a partial file, too long and ingestion feels laggy. Needs its own
  acceptance criteria.
- The `--watch` flag still touches `knowledge/wiki/cli.py`, the one file this
  feature shares with other in-flight wiki work.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `watchdog>=4.0` | Filesystem events, cross-platform | Already declared in `packages/ai-parrot/pyproject.toml` |
| `pydantic` v2 | Insight / watcher-report models | Repo standard |
| `click` | `--watch` flag on the existing `wiki inbox` command | Already the wiki CLI's framework |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` — `InboxProcessor.run()`, `InboxLockBusy`
- `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` — `build_ingest_runtime()`, `build_novelty_scorer()`, `build_triage_adapters()` (public, click-free)
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — the `inbox` command, extended with `--watch`
- `packages/ai-parrot/src/parrot/agents/meeting_registry.py` — `MeetingRegistry` id-keyed dedup, watermark and fingerprints
- `packages/ai-parrot/src/parrot/agents/obsidian.py` — Fireflies MCP fetch, `include_summary`, response parsing
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py` — `set_wrapper()`, `_get_telegram_bot()`, HTML escaping, 4096-char chunking, `@telegram_command`, `post_configure()` toolkit wiring
- `packages/ai-parrot/src/parrot/skills/mixin.py` — `SkillRegistryMixin`
- `packages/ai-parrot/src/parrot/tools/working_memory/` — `WorkingMemoryToolkit`
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` — `JiraToolkit`

---

### Option C: An `AgentsFlow` DAG of small single-purpose agents (unconventional)

Rather than one agent, model the pipeline as an explicit DAG on the existing
`AgentsFlow` executor (`bots/flows/flow/flow.py`): a `fetch` node (Fireflies
MCP), a `drop` node (write to inbox), an `insight` node (LLM over transcript +
summary), a `notify` node (Telegram) and an `InteractiveDecisionNode` for the
human Jira confirmation — which is exactly what that node type exists for. The
watcher stays a plain service outside the DAG.

✅ **Pros:**
- The human-in-the-loop Jira gate becomes a *declared* node rather than
  hand-rolled Telegram callback state — `InteractiveDecisionNode` already models
  "pause, ask a human, resume".
- Per-node retry, skip-propagation and `on_node_event` telemetry come free.
- Each node is small and independently testable; the pipeline is readable as a
  graph instead of as a 2000-line method chain.

❌ **Cons:**
- The user asked for an **agent in `parrot.bots`**; a flow is a different
  artifact, and `SkillRegistryMixin` / `WorkingMemoryToolkit` attach to a bot,
  not to a DAG node. Satisfying C1–C4 would mean a bot *plus* a flow anyway.
- Significantly more machinery for a mostly linear pipeline.
- `FlowContext` persistence across a human confirmation that may arrive hours
  later is a real design problem, not a free win.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `watchdog>=4.0` | Filesystem events | Already declared |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` — `AgentsFlow`
- `packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py` — `InteractiveDecisionNode`

---

## Recommendation

**Option B** is recommended.

It is the only option that satisfies every stated constraint without bending
one of them. Option A satisfies C6 by putting wiki infrastructure inside a bot,
which trades a permanent layering violation for a few days of saved design —
and the cost lands on the next producer that wants folder ingestion, not on
this feature. Option C buys a genuinely better human-in-the-loop model
(`InteractiveDecisionNode` is a real fit for C8), but it does not satisfy C1–C4
on its own: we would still need the bot, so C's machinery is additive rather
than substitutive.

**What Option B trades away, honestly:**

- **Scope.** Two modules across `bots/` and `knowledge/wiki/` instead of one
  class. The spec is bigger and the worktree touches two subsystems. Accepted
  because the split falls on an existing, well-defined seam.
- **The best answer for C8.** Hand-rolled Telegram confirmation state is
  weaker than `InteractiveDecisionNode`. Accepted for now because the
  confirmation is a single yes/no on a short-lived insight batch, and
  `GitHubReviewer` already demonstrates this pattern working in production over
  the same transport. If the confirmation flow grows (multi-step triage,
  assignment, re-prompting), revisit Option C.
- **Watcher timing risk.** The quiescence heuristic is the one genuinely novel
  piece of logic and needs its own tests and acceptance criteria rather than
  being treated as plumbing.

---

## Feature Description

### User-Facing Behavior

- The operator configures the agent with a Fireflies API key, a wiki project
  root (whose configured inbox directory is the drop target), a Telegram
  channel id, a Jira project, and a skills directory.
- On a scheduled run — or on demand via a `@telegram_command` — the agent pulls
  the latest meetings from Fireflies, **including each meeting's native
  Fireflies summary**, and skips meetings it has already processed.
- For each new meeting the operator receives **one Telegram message** in the
  configured channel: the meeting title and date, then the insights — decisions
  taken, risks and blockers raised, and action items with their owner where the
  transcript names one.
- Each message offers an explicit way to escalate: replying/confirming turns a
  chosen insight into a Jira ticket, rendered through a dedicated JiraToolkit
  template so every meeting ticket looks the same. **Nothing reaches Jira
  without that confirmation.** The agent answers with the created ticket key and
  URL, and — when the wiki has already ingested that meeting — a link to its
  wiki page.
- Meanwhile and independently, the meeting document appears in the LLM-Wiki,
  classified and linked by the existing inbox pipeline, and becomes queryable
  via `wikitoolkit query`. The operator does nothing to make this happen —
  the watcher sees the file land and ingests it.
- Dropping any other supported document into the same folder by hand ingests it
  too; the watcher is not Fireflies-specific.
- Skills placed in `agents/fireflies_insights/skills/` show up to the agent via
  `list_skill_commands` and can be invoked with their `/trigger`, so the
  operator can teach it house-specific insight formats without a code change.

### Internal Behavior

**Ingestion path (agent → folder → watcher → wiki), fire-and-forget:**

1. The agent lazily initializes the Fireflies MCP server, resolving the API key
   from an explicit argument, then `FIREFLIES_API_KEY` via navconfig.
2. It fetches transcripts with the summary included, and consults
   **`MeetingRegistry`** (FEAT-472) so an already-handled meeting is never
   re-fetched: `suggest_from_date()` supplies the watermark, `lookup()` /
   `classify()` the id-keyed gate, and `record_synced()` / `mark_analyzed()` /
   `mark_wiki_ingested()` record the outcome.
3. Each meeting is rendered to a single document and written **atomically** into
   the inbox directory — write to a temp name, then rename — so the watcher can
   never observe a partially written file.
4. The `InboxWatcher`, running independently, debounces the filesystem events,
   holds **every** candidate behind the same size+mtime stability window
   regardless of producer, and coalesces the burst into one serialized
   `InboxProcessor.run()`, which holds the whole-run writer lock. Its per-run
   `InboxRunReport` is logged, not awaited by the agent.

**Insight path (agent-local), independent of the above:**

5. From the transcript + Fireflies summary it already holds, the agent produces
   a structured insight set via the LLM, using `output_type` so the result is a
   validated Pydantic model rather than parsed prose.
6. Intermediate per-meeting artifacts are parked in `WorkingMemoryToolkit` so
   the LLM can address them by key across the turn without re-sending the whole
   transcript.
7. The insight set is rendered to Telegram HTML — every interpolation escaped —
   and chunked under the 4096-char limit before being pushed to the configured
   channel through the bot the `TelegramAgentWrapper` injected via `set_wrapper()`.
8. A human confirmation over Telegram triggers `JiraToolkit.jira_create_issue()`
   with the meeting template and its params; project and issue type still fall
   back to `JIRA_DEFAULT_PROJECT` / `JIRA_DEFAULT_ISSUE_TYPE`. The agent then
   looks for the meeting's wiki page and, if ingestion has already produced one,
   adds the backlink; otherwise it skips it silently. It replies with the key.

### Edge Cases & Error Handling

| Condition | Required behavior |
|---|---|
| No Fireflies API key | Fail fast at configure time with the actionable message naming `FIREFLIES_API_KEY`; do not start a watcher for a pipeline that cannot produce. |
| Fireflies MCP unreachable / rate-limited | Log and end the run cleanly. Already-dropped files still ingest. No partial Telegram message. |
| Meeting already processed | Skipped without re-fetch; counted in the run report. |
| Inbox directory missing or outside the project root | Refuse to start the watcher — `validate_inbox_paths` already enforces containment. |
| A file is still being written | Quiescence gate defers it to a later run. Never ingested partially. |
| Burst of N files at once | Coalesced into one `InboxProcessor.run()`, never N concurrent runs. |
| A concurrent `wikitoolkit inbox` holds the lock | `InboxLockBusy`: the watcher backs off and retries; it does not drop the event. |
| One document fails to ingest | Already isolated per-document by `InboxProcessor`; the run continues and the failure is reported. |
| Watcher crashes | Insight + Telegram path is unaffected (C5). Files remain in the folder and are picked up on restart. |
| Insight LLM returns malformed output | Validation failure is logged; the meeting is reported as "insights unavailable" rather than sending garbage to the channel. |
| Telegram 400 (bad entities) / 429 | Escaping and chunking prevent the former; the latter is retried with backoff, and a failure names the `chat_id` it could not reach. |
| No Telegram wrapper attached | Return a structured "no telegram wrapper" result, exactly as `_notify_telegram_alert` does — never raise into the run. |
| Jira unavailable at confirmation time | Report the failure in-channel with the insight preserved, so the human can retry; never silently drop a confirmed escalation. |
| Duplicate confirmation for one insight | Idempotent: return the existing ticket key rather than opening a second ticket. |
| Wiki page not yet ingested at confirmation time | Ticket is created **without** the backlink, silently. The backlink is best-effort by design (C8) and never delays or blocks the ticket. |
| `MeetingRegistry` DB unavailable | It degrades itself to `available = False` after one WARNING and returns neutral values instead of raising; the agent falls back to its own title-based skip for that run, exactly as FEAT-472 specifies. |
| `InboxConfig.stage_git` is `True` (the default) | Every archived and projected file is `git add`-ed. Under a long-running watcher this silently grows the index of whatever repo the wiki project lives in — see Open Questions. |

---

## Capabilities

### New Capabilities
- `fireflies-insights-agent`: a `parrot.bots` agent that pulls Fireflies
  transcripts + native summaries over MCP, drops them into the wiki inbox,
  derives structured insights, pushes them to Telegram, and escalates to Jira
  on human confirmation.
- `wiki-inbox-watcher`: a source-agnostic filesystem watcher over the wiki inbox
  directory that coalesces events into serialized `InboxProcessor` runs, usable
  as a service object and as `wikitoolkit inbox --watch`.

### Modified Capabilities
- `wikitoolkit-new-ingestion` (FEAT-626): gains the `--watch` mode and a
  stability-window setting on `InboxConfig`; the one-shot path is unchanged, and
  the runtime builder it needs is already public (no seam work).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/` | extends | New `fireflies_insights.py`; new class only, no change to existing bots |
| `parrot/knowledge/wiki/inbox/` | extends | New `watcher.py`; `processor.py` untouched |
| `parrot/knowledge/wiki/cli.py` | modifies | `--watch` flag on the existing `inbox` command — nothing else |
| `parrot/knowledge/wiki/runtime.py` | depends on | `build_ingest_runtime()` consumed as-is; already public and click-free, no promotion needed |
| `parrot/agents/meeting_registry.py` | depends on | `MeetingRegistry` consumed as-is for processed-meeting state (C13) |
| `parrot/integrations/telegram` | depends on | Consumes `telegram_command` and the wrapper-injected bot; no change to the integration |
| `parrot_tools/jiratoolkit.py` | depends on | Consumed as-is for ticket creation |
| `parrot/tools/working_memory/` | depends on | `WorkingMemoryToolkit` wired into the agent |
| `parrot/skills/` | depends on | `SkillRegistryMixin` + `skill_paths` + `SkillFileToolkit` |
| `parrot/mcp/integration.py` | depends on | `add_fireflies_mcp_server()` consumed as-is |
| `packages/ai-parrot/pyproject.toml` | none | `watchdog>=4.0` already declared — no new dependency |
| `.gitignore` | modifies | `/agents/` → `/agents/*` plus a narrow whitelist for this agent's `skills/` and `templates/` (C14). Verified not to un-ignore any other agent. |
| `parrot/knowledge/wiki/project.py` | modifies | `InboxConfig` gains the stability-window field (C11); `stage_git` untouched (C15) |
| `agents/fireflies_insights/templates/` | creates | Base Jira template for a confirmed insight, committed to the repo |
| `agents/fireflies_insights/skills/` | creates | File-based skills for the agent, committed to the repo |
| `docs/wiki/inbox.md` | modifies | Document the watch mode alongside the one-shot run |
| FEAT-481 `feat-fireflies-wiki-agent` | **no change** | Left untouched by explicit decision; different sink (Obsidian vault vs. wiki inbox) |

---

## Code Context

### User-Provided Code

None — the request was stated in prose. The references below were read from the
working tree at `dev` (`cdba878f2`) and independently re-verified by an
`sdd-contract-probe` run against the same HEAD. 36 of 38 checks came back clean;
the two reported "missing" (`telegram_command`, `register_agent`) were confirmed
**false negatives** of the probe's grep and were re-verified by importing them —
see the note under Verified Imports. One claim the probe did not cover was wrong
in the first draft and has been corrected: the Telegram chunking constant is
`_TELEGRAM_MAX_MESSAGE`, not `TELEGRAM_MAX`.

### Verified Codebase References

#### Classes & Signatures

```python
# packages/ai-parrot/src/parrot/mcp/integration.py:1356
class MCPEnabledMixin:
    # packages/ai-parrot/src/parrot/mcp/integration.py:1448
    async def add_fireflies_mcp_server(self, api_key: Optional[str] = None, **kwargs) -> List[str]:
        """API key precedence: explicit arg → FIREFLIES_API_KEY via navconfig → ValueError."""

# packages/ai-parrot/src/parrot/bots/agent.py:1562
class Agent(BasicAgent):
    # packages/ai-parrot/src/parrot/bots/agent.py:1024
    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]: ...

# packages/ai-parrot/src/parrot/agents/obsidian.py:163
class FirefliesObsidianAgent(BasicAgent):
    ANALYSIS_HEADING: str = "## Analysis"              # obsidian.py:186
    FIREFLIES_SUMMARY_HEADING: str = "## Fireflies Summary"  # obsidian.py:193

    # obsidian.py:320
    async def _ensure_fireflies_mcp(self) -> None: ...

    # obsidian.py:344
    async def sync_fireflies_transcripts(
        self,
        limit: int = 10,
        skip_existing: bool = True,
        filters: Optional["FirefliesFilters"] = None,
        include_summary: bool = False,
        force_refetch: bool = False,
    ) -> Dict[str, Any]: ...

    # obsidian.py:1243 — MCP tools are registered as mcp_fireflies_<tool_name>
    async def _call_fireflies_tool(self, tool_name: str, args: Dict[str, Any]) -> Any: ...

# packages/ai-parrot/src/parrot/agents/obsidian.py:62
class FirefliesFilters(BaseModel): ...

# packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py:43
class InboxRuntime(BaseModel):
    """Frozen (model_config frozen=True) bindings for ONE run."""
    root: Path
    config: WikiProjectConfig
    wiki_config: WikiConfig
    charter: Charter
    store: BaseWikiStore
    sources: SourceCollectionManager
    bookkeeper: WikiBookkeeper
    acquirer: DocumentAcquirer
    router: IngestTriageRouter
    orchestrator: WikiIngestOrchestrator
    light_adapter: SkipValidation[LLMCaller]
    heavy_adapter: SkipValidation[LLMCaller]
    search: WikiCombinedSearch
    models: dict[str, str]

# packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py:64
class InboxLockBusy(RuntimeError): ...

# packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py:133
class InboxProcessor:
    def __init__(self, runtime: InboxRuntime, *, today: date | None = None) -> None: ...  # :136
    def discover(self, *, limit: int | None) -> list[DocumentRef]: ...                     # :153
    async def run(                                                                          # :202
        self, *, dry_run: bool = False, limit: int | None = None,
        force: bool = False, archive: bool = True,
    ) -> InboxRunReport: ...
    async def process_one(                                                                  # :275
        self, ref: DocumentRef, *, dry_run: bool, force: bool, archive: bool
    ) -> InboxDocResult: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5290
def _build_ingest_runtime(
    root: Path, config: WikiProjectConfig, store: BaseWikiStore,
    sources: SourceCollectionManager, charter: "Charter", charter_path: Path, *,
    lightweight_model_opt: str | None, model_opt: str | None,
    fetch_timeout: float = 30.0,
) -> "InboxRuntime": ...
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:5946 — the one-shot `wiki inbox` command

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:315
def validate_inbox_paths(root: Path, inbox: Path, archive: Path, markdown: Path) -> None: ...
# packages/ai-parrot/src/parrot/knowledge/wiki/charter.py:404
def load_charter(path: Path) -> Charter: ...

# .gitignore — VERIFIED STATE AT dev (cdba878f2)
#   :274  templates/                       <- would catch any agent templates/ dir
#   :297  /agents/                         <- ignores the WHOLE agents tree
# `git check-ignore -v agents/fireflies_insights/templates/x.j2` answers
# ".gitignore:297:/agents/", so BOTH the skills/ and templates/ dirs of a NEW
# agent are untracked today. The in-file comment above :297 confirms this is
# deliberate: "only NEW agent files are ignored again". Evidence: of the four
# agents with a skills/ dir on disk, only flex_dashboard (12 files) and
# odoo_agent (4) are tracked; porygon and security_advisor have 0 tracked files.
#
# A plain negation does NOT work — git cannot re-include a path under an
# excluded DIRECTORY. The rule must ignore the children instead. This exact
# block was tested in a scratch repo and produces the intended result:
#
#   /agents/*
#   !/agents/fireflies_insights/
#   /agents/fireflies_insights/*
#   !/agents/fireflies_insights/skills/
#   !/agents/fireflies_insights/skills/**
#   !/agents/fireflies_insights/templates/
#   !/agents/fireflies_insights/templates/**
#
# Verified outcomes of that block:
#   tracked  -> agents/fireflies_insights/skills/**, agents/fireflies_insights/templates/**
#   ignored  -> agents/porygon/**            (matched by /agents/*)
#   ignored  -> agents/fireflies_insights/secret_runtime.json
#                                            (matched by /agents/fireflies_insights/*)
# i.e. it is a narrow whitelist, not a blanket un-ignore.
# Precedent for this style of exception already exists at .gitignore:275-280
# (three packages/* templates/ directories).

# packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py — PUBLIC, click-free builders.
# Docstring: "kept separate from command-line concerns so async servers can construct
# the charter triage and ingest services without importing CLI code or starting a
# nested event loop."  __all__ = [WikiRuntimeError, persistence_for_project,
# build_triage_adapters, build_novelty_scorer, build_ingest_runtime]  # runtime.py:26-31
def build_ingest_runtime(                                     # runtime.py:170
    root: Path, config: WikiProjectConfig, store: BaseWikiStore,
    sources: SourceCollectionManager, charter: "Charter", charter_path: Path, *,
    lightweight_model: str, model: str, novelty_scorer: Any,
    adapters: tuple[Any, Any, str, bool] | None = None, fetch_timeout: float = 30.0,
) -> "InboxRuntime": ...
def build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]: ...  # runtime.py:90
async def build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any: ...  # runtime.py:113
class WikiRuntimeError(RuntimeError): ...                     # runtime.py:86
# NOTE: cli.py:5290 `_build_ingest_runtime` is only a click-flavoured wrapper that
# resolves model ids, calls the three builders above and re-raises as ClickException.
# The watcher calls runtime.py directly. Do NOT refactor or export the CLI helper.

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:286
class InboxConfig(BaseModel):
    dir: str = "inbox"                                        # :289
    archive_dir: str = f"{PARROT_DIR}/archive"                # :290
    rejected_subdir: str = "rejected"                         # :293 single segment, no separators or '..'
    markdown_dir: str | None = None                           # :294 defaults to <storage_dir>/inbox
    date_format: str = "%Y-%m-%d"                             # :297
    stage_git: bool = True                                    # :298 — stages archived+projected files in git
    max_candidates: int = 20                                  # :299 ge=1, le=100
    lock_timeout: float = 30.0                                # :300 ge=0.0

# packages/ai-parrot/src/parrot/agents/meeting_registry.py:167
class MeetingRegistry:
    """Meeting-shaped async facade over SourceCollectionManager.
    Constructor takes NO Obsidian toolkit — it is backed by registry_dir/wiki.db
    and registry_dir/sources, the same path the wiki toolkit opens.
    Degraded mode: on sqlite3.Error/OSError it logs ONE warning, sets
    available=False, and every verb returns a neutral value instead of raising."""
    def __init__(self, registry_dir: Path, *, manager: SourceCollectionManager | None = None) -> None: ...  # :184
    @property
    def available(self) -> bool: ...                          # :228
    async def lookup(self, fireflies_id: str) -> MeetingRecord | None: ...        # :236
    async def classify(self, ...) -> Classified: ...                              # :253
    async def pending_analysis(self) -> list[MeetingRecord]: ...                  # :324
    async def suggest_from_date(self, *, overlap_days: int) -> str | None: ...    # :370
    async def record_synced(self, ...) -> ...: ...                                # :430
    async def mark_analyzed(self, fireflies_id: str, fingerprint: str) -> None: ...   # :526
    async def mark_analysis_failed(self, fireflies_id: str, error: str) -> None: ...  # :545
    async def mark_wiki_ingested(self, *, at: str | None = None) -> int: ...      # :560
    async def forget(self, fireflies_id: str, *, reject: bool = False) -> bool: ...   # :585
    # Vault-coupled verbs this feature does NOT use:
    #   unique_slug(..., vault_path=)  :397 | backfill_from_vault  :616
    #   merge_duplicates :738 | repair_path :851 | _vault_root(toolkit: ObsidianToolkit) :1066
def normalise_transcript(text: str) -> str: ...               # meeting_registry.py:69
def fingerprint(text: str) -> str: ...                        # meeting_registry.py:91
class MeetingRecord(BaseModel): ...                           # meeting_registry.py:110

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2608
    async def jira_create_issue(
        self, project: Optional[str] = None, summary: str = "",
        issuetype: Optional[str] = None, description: Optional[str] = None,
        assignee: Optional[str] = None, priority: Optional[str] = None,
        labels: Optional[List[str]] = None, components: Optional[List[str]] = None,
        due_date: Optional[str] = None, parent: Optional[str] = None,
        original_estimate: Optional[str] = None, fields: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None, template_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...
    async def jira_create_issue_link(                         # jiratoolkit.py:4375
        self, inward_issue: str, outward_issue: str,
        link_type: str = "Relates", comment: Optional[str] = None,
    ) -> Dict[str, Any]: ...
    # Defaults resolved in __init__ (jiratoolkit.py:945-946):
    #   self.default_project    = JIRA_DEFAULT_PROJECT    (fallback "NAV")
    #   self.default_issue_type = JIRA_DEFAULT_ISSUE_TYPE (fallback "Task")
    # Template dir resolution (jiratoolkit.py:889, 964-971):
    #   templates_dir: Optional[Union[str, Path]] = None   <- __init__ kwarg
    #   _tpl_dir = templates_dir or _cfg("JIRA_TEMPLATES_DIR")
    #   a non-directory is WARNED about and ignored, not raised
    #   self.templates_dir stays None when neither is set, and
    #   jira_list_templates reports {"has_templates_dir": bool}  (:3255)

# packages/ai-parrot/src/parrot/bots/github_reviewer.py:491
class GitHubReviewer(Agent):
    def set_wrapper(self, wrapper) -> None: ...                 # :875 — TelegramAgentWrapper injects its bot
    def _get_telegram_bot(self): ...                            # :1951 — returns getattr(self._wrapper, "bot", None) or None
    async def _notify_telegram_alert(                           # :1918
        self, payload: Dict[str, Any], ticket_key: str, result: PRReviewResult
    ) -> Dict[str, Any]: ...                                    # returns {"sent": 0, "reason": ...} — never raises
    def _format_alert_message(                                  # :1956 — all interpolations HTML-escaped
        self, payload: Dict[str, Any], ticket_key: str, result: PRReviewResult
    ) -> str: ...
    async def post_configure(self) -> None: ...                 # :881 — wires GitToolkit + JiraToolkit once self.app exists
    _TELEGRAM_MAX_MESSAGE = 4096                                # :2857 — sendMessage hard limit
    _TELEGRAM_PART_RESERVE = 32                                 # :2860 — head-room for the "(part n/m)" marker

# packages/ai-parrot/src/parrot/skills/mixin.py:47
class SkillRegistryMixin:
    enable_skill_registry: bool = True          # :77
    skill_paths: List[Path] = []                # :85  — opt-in; recommended [Path(".agent/skills/")]
    inject_skills_into_prompt: bool = True      # :89
    tenant_based: bool = False                  # :110
    tenant_id: Optional[str] = None             # :112
    # Usage: class MyAgent(SkillRegistryMixin, AbstractBot)

# packages/ai-parrot/src/parrot/skills/tools.py:381
class SkillFileToolkit(AbstractToolkit): ...
# packages/ai-parrot/src/parrot/skills/tools.py:642
def create_skill_tools(
    registry: SkillRegistry,
    agent_id: str,
    include_write_tools: bool = True,
    file_registry: Optional["SkillFileRegistry"] = None,
    learned_dir: Optional[Path] = None,
    *,
    view_provider: Optional[Callable[[], Any]] = None,
    registry_provider: Optional[Callable[[], Optional[SkillRegistry]]] = None,
) -> List[AbstractTool]: ...
# packages/ai-parrot/src/parrot/skills/file_registry.py:17
class SkillFileRegistry: ...
# packages/ai-parrot/src/parrot/skills/loader.py:26
class SkillsDirectoryLoader: ...

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py:47
class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit): ...

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:772
class JiraToolkit(AbstractToolkit): ...
```

#### Verified Imports

```python
from parrot.knowledge.wiki.inbox import InboxProcessor, InboxRuntime, InboxRunReport, InboxDocResult  # inbox/__init__.py:3-4
from parrot.knowledge.wiki.inbox.processor import InboxLockBusy                                       # processor.py:64
from parrot.knowledge.wiki.project import validate_inbox_paths                                        # project.py:315
from parrot.knowledge.wiki.charter import load_charter                                                # charter.py:404
from parrot.integrations.telegram import telegram_command                                             # LAZY (PEP 562) — see note below
from parrot.tools.working_memory import WorkingMemoryToolkit                                          # working_memory/__init__.py:3
from parrot.skills.mixin import SkillRegistryMixin                                                    # skills/mixin.py:47
from parrot.skills.tools import SkillFileToolkit, create_skill_tools                                  # skills/tools.py:381,642
from parrot_tools.jiratoolkit import JiraToolkit                                                      # jiratoolkit.py:772
from parrot.registry import register_agent                                                            # registry/__init__.py:12
```

> **Two of these imports are lazy and will not show up in a naive grep of the
> package `__init__.py`.** Both were smoke-tested at `dev` (`cdba878f2`) and
> resolve at runtime:
> - `telegram_command` is a PEP 562 lazy re-export declared in the
>   `_LAZY_EXPORTS` map of `parrot/integrations/telegram/__init__.py` (aiogram is
>   ~1.6 s to import, so it is deferred). The function itself is defined at
>   `packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py:5`.
> - `register_agent` is not a `def` at all — it is an assignment,
>   `register_agent = agent_registry.register_bot_decorator`
>   (`packages/ai-parrot/src/parrot/registry/__init__.py:12`), exported via `__all__`.
>
> Do not "fix" either import; they work.

#### Key Attributes & Constants

- MCP tools are namespaced `mcp_fireflies_<tool_name>` (e.g. `mcp_fireflies_get_transcripts`) — `obsidian.py:1258`
- `sync_fireflies_transcripts(limit=…)` is a **total across pages**, not a page size; the underlying tool caps a single call at 50 and paginates internally — `obsidian.py:357`
- `InboxRuntime.model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)` — `processor.py:46`
- `InboxProcessor.run()` holds the sole whole-run writer lock; the processor, not the CLI, owns it — `processor.py:206`, `cli.py:5959`
- `InboxDocResult.status` values observed in `run()`: `"skipped"`, `"failed"` (plus the discovery and `process_one` statuses) — `processor.py:214-221`
- `watchdog>=4.0` declared at `packages/ai-parrot/pyproject.toml:794` (repo-root `pyproject.toml:116` has `watchdog>=6.0.0`)
- `@register_agent` **must be called with a keyword**: `@register_agent(name="x")`. The positional form `@register_agent("x")` raises `TypeError` — documented at `bots/flows/result_agent.py:15-19`

### Does NOT Exist (Anti-Hallucination)

- ~~`FirefliesWikiAgent`~~ — **not on `dev`**. It exists only on the unmerged branch `feat-fireflies-wiki-agent` (FEAT-481). Do not import it.
- ~~`parrot/agents/fireflies_wiki.py`~~ — no such file in the working tree.
- ~~any inbox watcher / `InboxWatcher` / `--watch` flag~~ — does not exist; `wikitoolkit inbox` is strictly one-shot. This feature creates it.
- ~~`wiki_inbox` MCP tool~~ — does not exist: no `wiki_inbox` symbol anywhere under `packages/ai-parrot/src/parrot/`, and there is no `knowledge/wiki/mcp/` package. Ledger issue `f7477bd7bba4` asks for it; it is **not** a prerequisite of this feature.
- ~~`FirefliesObsidianAgent` as a base class for this agent~~ — it is a `BasicAgent` with no skills, no working memory, no Telegram and no Jira. It is a **reference**, not a parent.
- ~~a Fireflies toolkit under `parrot_tools/`~~ — Fireflies is reached only over MCP (`sdd/state/FEAT-263/findings/F010-workiq-fireflies.md`).
- ~~a need to promote `cli.py:_build_ingest_runtime` into a public seam~~ — the public seam **already exists** as `parrot.knowledge.wiki.runtime.build_ingest_runtime`. An earlier draft of this brainstorm said otherwise; it was wrong.
- ~~`MeetingRegistry` requiring an `ObsidianToolkit`~~ — its constructor takes `registry_dir` and an optional `SourceCollectionManager` only. Only `unique_slug`, `backfill_from_vault`, `merge_duplicates`, `repair_path` and `_vault_root` touch a vault, and none of them is used here.

---

## Parallelism Assessment

- **Internal parallelism**: good, and better than the first draft assumed now
  that the wiki-side seam turned out to be public already. Three natural lanes
  with almost no file overlap — (L1) `knowledge/wiki/inbox/watcher.py` + the
  `--watch` CLI flag (no CLI refactor);
  (L2) the agent's Fireflies-fetch and atomic inbox-drop half; (L3) the
  insight → Telegram → Jira half plus the skills/working-memory wiring. L1 is
  fully independent of L2/L3. L2 and L3 share the agent module, so they
  serialize on that one file.
- **Cross-feature independence**: the only shared file with anything in flight
  is `knowledge/wiki/cli.py`, which FEAT-626 follow-ups and the wiki features
  also touch. `bots/fireflies_insights.py` and `inbox/watcher.py` are new files
  and collide with nothing. **FEAT-481 is deliberately untouched** — verify
  before merging that neither branch has started editing the other's files.
- **Recommended isolation**: `per-spec`.
- **Rationale**: the lanes are clean but the feature is small enough that the
  coordination cost of multiple worktrees outweighs the gain, and L2/L3 both
  land in one new module anyway. One worktree, tasks ordered L1 → L2 → L3, with
  L1 mergeable on its own if the agent half slips.

---

## Open Questions

All questions raised during discovery are resolved. The three added at the
bottom were **discovered while resolving the others** and are deliberately left
open for `/sdd-spec` to settle with real numbers.

- [x] Flow type and base branch — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev`.
- [x] What to do about the unmerged FEAT-481 agent — *Owner: Jesus Lara*: build a new independent agent; leave FEAT-481 exactly as it is.
- [x] How the inbox ingestion is triggered — *Owner: Jesus Lara*: a real filesystem watcher, built inside this feature.
- [x] Source of the insights — *Owner: Jesus Lara*: the transcript + native summary the agent already holds; independent of the wiki ingestion path.
- [x] Telegram cadence and destination — *Owner: Jesus Lara*: one message per meeting, to a single configured channel (the `public_channel_id` pattern).
- [x] How Jira tickets are created — *Owner: Jesus Lara*: only on explicit human confirmation over Telegram.
- [x] Skill backend — *Owner: Jesus Lara*: file-based (`skill_paths` + `SkillFileToolkit`); no DB skill registry in this feature.
- [x] How is the watcher run in production — *Owner: Jesus Lara*: **both**, from one implementation — a startable/stoppable service object the agent may manage, plus a `wikitoolkit inbox --watch` mode that runs it standalone.
- [x] What triggers an agent run — *Owner: Jesus Lara*: **both** — a periodic scheduled sync plus an on-demand `@telegram_command`, mirroring `GitHubReviewer`.
- [x] Quiescence strategy — *Owner: Jesus Lara*: a **uniform** size+mtime stability window for every candidate regardless of producer, so there is one code path to test. The agent still writes atomically (temp + rename) as defence in depth, not as an exemption from the window. No sidecar marker file.
- [x] Jira field mapping — *Owner: Jesus Lara*: a **dedicated JiraToolkit template** (FEAT-637 template support) rather than ad-hoc field assembly; `project` / `issuetype` still fall back to `JIRA_DEFAULT_PROJECT` / `JIRA_DEFAULT_ISSUE_TYPE`.
- [x] Wiki backlink on the ticket — *Owner: Jesus Lara*: **best-effort** — added when the meeting's wiki page already exists at confirmation time, silently omitted when it does not. It never delays or blocks ticket creation (C5/C8).
- [x] Where this agent's skills live — *Owner: Jesus Lara*: `agents/fireflies_insights/skills/` under `AGENTS_DIR`, the convention already used by `agents/porygon/`, `agents/flex_dashboard/`, `agents/odoo_agent/` and `agents/security_advisor/`. Not `.agent/skills/`, which holds the SDD tooling's own skills.
- [x] Processed-meeting state — *Owner: Jesus Lara*: **reuse `MeetingRegistry`** (FEAT-472, merged). Verified not to be Obsidian-coupled at construction; the vault-bound verbs are simply unused.

### Raised during resolution — also resolved

- [x] **What stability window, concretely?** — *Owner: Jesus Lara*: two consecutive polls ~1.5 s apart with identical size and mtime (≈3 s total), exposed as a new `InboxConfig` field so slow sources can raise it. Not adaptive-by-size: that would be a heuristic on top of a heuristic and harder to test deterministically.
- [x] **`InboxConfig.stage_git` defaults to `True`** — *Owner: Jesus Lara*: left to **configuration**. The watcher neither forces nor overrides it; an operator who does not want a continuously-running watcher staging files into the wiki repo sets `stage_git: false`. This must be called out in `docs/wiki/inbox.md`, because the default was chosen for occasional manual runs, not for a daemon.
- [x] **The Jira template does not exist yet** — *Owner: Jesus Lara*: ship a **base template** in `agents/fireflies_insights/templates/`, committed to the repo and reachable via `JiraToolkit(templates_dir=…)` / `JIRA_TEMPLATES_DIR`. Its parameter set is spec work.
- [x] **`/agents/` is git-ignored wholesale** (discovered while answering the above, and it retroactively affects the skills decision too) — *Owner: Jesus Lara*: fix `.gitignore` rather than `git add -f`. See C14 and the verified rule block in Code Context.

**Nothing is left open.** The remaining detail work — the Jira template's exact
parameter set, the `InboxConfig` field name, and the acceptance criteria for the
stability window — is spec work for `/sdd-spec`, not an unresolved decision.
