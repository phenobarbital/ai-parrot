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
The LLM wiki already holds far more than code: authored memories
(`note | decision | lesson | concept`), the Jira ticket corpus (`issues`
namespace, FEAT-454), Obsidian vaults (meeting notes from FEAT-472 /
FEAT-481), the SDD work ledger (open issues, specs, tasks) and the ADR
plane. What it lacks is a **daily synthesis**: a one-page "what's on my
plate today" that groups open tickets, recent and upcoming meetings,
proposed decisions, in-progress tasks and drafts by project, surfaces
blockers first, and tells the reader what changed since yesterday.

Today that synthesis is done by hand (several `wikitoolkit query` /
`ledger ready` / `adr why` calls) or not at all. The user's sketch
(`wiki-daily-brief`, preserved verbatim below) describes the target
output. The sketch assumes every page carries typed frontmatter
(`type: project|meeting|ticket|decision|deliverable`, `status:`, dates,
`owner:`). The wiki does **not** have that today: the `pages` table has
no metadata column, vault frontmatter other than `summary`/`description`
is dropped at ingest, and Jira frontmatter survives only as text inside
the page body.

So the feature has two halves: (1) make the wiki able to answer
"which pages are tickets/meetings/decisions, with what status and date?"
cheaply, and (2) a `standup` command that collects, groups, renders and
stores the brief — deterministic by default, with an optional LLM
one-paragraph summary.

**Who is affected**: the wiki owner running it each morning (personal
mode by default), teams using `--team`, and coding agents that get it as
`/parrotwiki standup` and the `wiki_standup` MCP tool.

### Constraints and goals
Decisions taken in the discovery rounds (2026-10-03, Jesus):

- **Flow**: `type: feature`, `base_branch: dev`.
- **Sources (all four)**: Obsidian/vault pages with typed frontmatter; the
  Jira `issues` namespace; the SDD ledger + specs/tasks + memories; and a
  new **typed-entity convention** in the wiki so any ingest can populate
  project / meeting / ticket / decision / deliverable entities.
- **Entity intake (all four)**: frontmatter on ingested markdown is the
  primary path; `wikitoolkit remember` gains entity flags; mapping rules
  turn existing planes into entities (Jira issue → ticket, SDD spec →
  project, ledger issue → ticket, ADR → decision); and a dedicated
  `wikitoolkit entity add|list` command gives validated CRUD.
- **Synthesis**: hybrid — section lists are computed with no LLM
  (offline, cron-safe); only the "On your plate" paragraph uses a model,
  and only when one is configured. Without a model it degrades to a
  ranked bullet list, never fails.
- **Scope**: personal by default (`--me` identity: Jira assignee, memory
  author `human:<user>`, spec author), `--team` widens.
- **Project key**: resolution chain `project:` link → Jira project key →
  SDD feature slug → `Internal`.
- **Outputs**: wiki page in the local plane (category `brief`), a
  markdown file in a folder, `/parrotwiki standup` + `wiki_standup` MCP
  tool. stdout markdown/`--json` is implied by the CLI.
- **Delta**: diff against the previous stored brief ("New since last
  brief" / "Closed since last brief").
- **Hygiene**: computed from existing data only (stale tickets, old
  proposed decisions, ledger blockers, Jira watermark age) — no new lint.
- **Language**: `--language en|es`, default from a new
  `standup.default_language` key in `.parrot/wiki.json`.
- Read-only on entity pages: the command writes only the brief page and
  the brief file.
- Must not regress `wikitoolkit claude-hook` startup (FEAT-584 p50 budget,
  ledger issue `f0a40d0853f2`): anything that imports the ledger/decision
  chain must be lazily registered like `adr`.
- Compatible with FEAT-481's vault frontmatter vocabulary
  (`type: meeting-source`, `meeting_date`, `primary_project`, `projects`)
  — alias it, do not compete with it.
- Keep the `wiki/cli.py` diff to additive command blocks (5.4k-line hot
  file); logic lives in new modules.

Resolved in the open-question round (2026-10-03, Jesus) — see §Open
Questions for the full trail:

- `page_attrs` is **additive**, `SCHEMA_VERSION` stays `"3"`.
- Jira status → canonical ticket status mapping lives in `.parrot/wiki.json`
  (`standup.ticket_status_map`) with a shipped default; raw value kept.
- Brief file default folder: **always** `${PARROT_HOME}/wikis/briefs/`
  (`--out` overrides).
- Jira identity: `IssueFrontmatter` gains `assignee_email`; "me" matches
  `JIRA_USERNAME` against it, falling back to the display name.
- Back-fill via a new `wikitoolkit entity reindex` (re-reads stored bodies,
  no re-ingest, no LLM).
- FEAT-481 vocabulary is **aliased only**; FEAT-481 is not modified.
- Spanish: static heading table, item titles verbatim, only the LLM
  paragraph is written in the requested language.
- Brief pages use the open-string category `brief`.
- **Weekly/monthly roll-up is in scope**: `standup --period day|week|month`.
- This spec **owns** `wiki/entities.py` + `page_attrs`; the sibling
  `wikitoolkit inbox` spec depends on it and writes attrs.

---

### Recommended option / probable scope
**Option B** is recommended because:

- The user chose all four sources *and* a typed-entity convention; a
  convention that lives only inside one command's parser (Option A) is
  not a convention, it is a private heuristic that the next consumer
  (weekly roll-up, `wiki_query` filters, lint) re-implements.
- The brief's hard requirements — horizon filtering, "blocked first",
  day-over-day diff, per-type status enums — are index questions. One
  additive attrs table answers all of them in SQL; Option A answers them
  by loading every candidate body every morning.
- The cost that matters (touching ingest paths + a migration) is bounded:
  the table is additive, old planes open unchanged, and Option A's
  body-frontmatter reader is kept as the fallback so the brief works on
  day one even before `issues`/vault planes are re-ingested.
- Option C is rejected on the hybrid decision alone: the mechanical part
  must be deterministic and offline.

What we trade: a bigger first feature and a decision about
`SCHEMA_VERSION` (open question 1). Mitigation: phase the spec so the
attrs plane (store + vault + jira + remember + entity CLI) lands first and
the standup collectors run against it or the fallback.

---

Add a small **page attribute index** to the wiki store — one additive
table (`page_attrs(concept_id, key, value, value_kind)` with a composite
index) populated from frontmatter at every ingest path: vault scan,
markdown documents in `build`/`upsert`, `ingest-jira` (from
`IssueFrontmatter`), `remember` (new flags), and a new
`wikitoolkit entity add|list` command. A normalisation layer defines the
**entity vocabulary**: `type` ∈ {project, engagement, meeting, ticket,
decision, deliverable, person} with aliases (FEAT-481 `meeting-source` →
meeting), `status` enums per type, `project`, `date`, `due`, `owner`,
`language`. Mapping rules derive entities for planes that have no
frontmatter: ledger issue → ticket, SDD spec → project (via the task
index), ADR record → decision.

`wikitoolkit standup` then becomes a set of **collectors** (one per
source, each returning the same `BriefItem` shape), a **grouper**
(project resolution chain), a **renderer** (markdown, en/es heading
table, `--json`), an optional **LLM summariser**, and a **writer**
(brief page `brief:daily:<date>` in the local plane with its item ids
stored as attrs for the next day's diff, plus the markdown file).
Registered as a lazy click group so the hook fast path never imports it.
Exposed as `WikiStandupTool` in `tools.py` and as a `/parrotwiki standup`
bullet in the managed slash command.

✅ **Pros:**
- Entities become first-class and indexed: the brief filters by
  `status`/`date` in SQL, and `wiki_query`, roll-ups, lint and future
  agents reuse the same index.
- `remember --category meeting --project X --status held --date …` has a
  real home; `entity add` validates against the per-type enums.
- Day-over-day diff is trivial (previous brief's item ids are attrs).
- Additive migration: pre-existing v3 planes open; attrs fill in on the
  next `build`/`upsert`/`ingest-jira`.

❌ **Cons:**
- Touches the four ingest paths plus `store.py` — larger blast radius;
  `wiki/cli.py` is a hot file (rebase often).
- Planes built before the change have **empty** attrs until re-ingested
  (`ingest-jira --force` for `issues`; `build --force` for a vault).
  Collectors must fall back to body frontmatter parsing when attrs are
  missing (Option A's reader becomes the fallback).
- Whether this needs a `SCHEMA_VERSION` bump is a real decision (v3
  planes already broke v2 code once; see open questions).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | parse YAML blocks | existing dep |
| `PyYAML` | render brief frontmatter | existing dep |
| `click`, `rich` | CLI | existing deps |
| `pydantic>=2` | `BriefItem`, `EntityRecord`, per-type enums | existing dep |
| (optional) `WIKI_LIGHTWEIGHT_MODEL` via `LLMFactory` | one-paragraph summary | same env pattern as `ingest`/`remember --extract` |

🔗 **Existing Code to Reuse:**
- `wiki/store.py` DDL block (:93–107), `_MIGRATION_COLUMNS` (:229), `_migrate` (:1370) — precedent for an additive migration
- `wiki/vault_scan.py` `scan_vault` (:118), `_note_summary` (:90), `_note_body` (:103) — the only place vault frontmatter is read today
- `wiki/jira_render.py` `IssueFrontmatter` (:116) — the structured ticket fields to project into attrs
- `wiki/cli.py` `remember` (:3776–3820) + `_authoring_identity` (:3513) — authoring path and identity
- `wiki/lazy_commands.py` `LazyAdrGroup` (:21) — generalise into a `LazyGroup(import_path)` so `standup` and `adr` share it
- `wiki/tools.py` `WikiStatusTool` (:514), `create_wiki_tools` (:807) — MCP tool pattern and registration
- `wiki/claude_code/assets.py` `SLASH_COMMAND_MD` (:307, `argument-hint` :309) — add the `standup` bullet
- `wiki/obsidian_sync.py` `render_note` (:183) — frontmatter marker convention (`wiki_sync`/`wiki_scope`/`wiki_id`) for the brief file when it lands in a vault
- `wiki/jira_sync.py` `load_sync_state` (:176) — watermark age for the Hygiene section

---

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
packages/ai-parrot/src/parrot/knowledge/wiki/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/models.py
packages/ai-parrot/src/parrot/knowledge/wiki/project.py
packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
packages/ai-parrot/src/parrot/knowledge/wiki/context.py
packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py
packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py
packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py
packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py
packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
packages/ai-parrot/src/parrot/knowledge/wiki/obsidian_sync.py
packages/ai-parrot/src/parrot/knowledge/wiki/export.py
packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py
packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
packages/ai-parrot/src/parrot/agents/meeting_registry.py
.claude/commands/parrotwiki.md
sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md
sdd/proposals/wikitoolkit-new-ingestion.brainstorm.md

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
