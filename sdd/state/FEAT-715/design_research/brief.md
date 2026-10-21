<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
agents/fireflies_insights/secret_runtime.json
agents/fireflies_insights/templates/x.j2
agents/fireflies_wiki.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py
packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
packages/ai-parrot/pyproject.toml
packages/ai-parrot/src/parrot/agents/meeting_registry.py
packages/ai-parrot/src/parrot/agents/obsidian.py
packages/ai-parrot/src/parrot/bots/agent.py
packages/ai-parrot/src/parrot/bots/github_reviewer.py
packages/ai-parrot/src/parrot/knowledge/wiki/charter.py
packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py
packages/ai-parrot/src/parrot/knowledge/wiki/project.py
packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py
packages/ai-parrot/src/parrot/mcp/integration.py
packages/ai-parrot/src/parrot/registry/__init__.py
packages/ai-parrot/src/parrot/skills/file_registry.py
packages/ai-parrot/src/parrot/skills/loader.py
packages/ai-parrot/src/parrot/skills/mixin.py
packages/ai-parrot/src/parrot/skills/tools.py
packages/ai-parrot/src/parrot/tools/working_memory/tool.py
sdd/state/FEAT-263/findings/F010-workiq-fireflies.md

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
