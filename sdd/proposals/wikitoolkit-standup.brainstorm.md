---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [wiki, standup, daily-brief, entities, ledger, jira]
---

# Brainstorm: `wikitoolkit standup` — a morning daily brief synthesized from the wiki

**Date**: 2026-10-03
**Author**: Jesus Lara (discovery Q&A) + Claude
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

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

## Constraints & Requirements

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

## Options Explored

### Option A: Synthesis-only command, parse frontmatter at read time

`wikitoolkit standup` is a pure reader. It lists candidate pages through
the existing store API (`list_pages`, `search_fts`, `FederatedWikiStore`
for the `issues` namespace), parses the YAML frontmatter still present in
each page `body` with `python-frontmatter`, and pulls the structured
sources that already have APIs: `LedgerService.ready_work()` /
`merge_blockers()`, `DecisionRepository.inventory()`, and the per-spec
task indexes under `sdd/tasks/index/*.json`. It groups, renders and
stores the brief. No schema change; the "entity convention" is only a
parser vocabulary.

✅ **Pros:**
- Smallest diff; no migration, no `build`/`upsert`/`ingest-jira` changes.
- Works on planes built by older code (frontmatter is already in bodies).
- Ships the user-visible value (the brief) fastest.

❌ **Cons:**
- O(pages) body parsing every morning; no indexed filter by
  `status`/`date`, so the horizon filter is applied after loading bodies.
- Entities are not queryable by anything else (`wiki_query`, roll-ups,
  lint, MCP) — every future consumer re-parses.
- `remember --category meeting --status held` has nowhere to put the
  fields except inside the body text.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | parse YAML blocks from page bodies | already used by `ObsidianToolkit` / FEAT-481 |
| `click`, `rich` | CLI + table output | already core deps |

🔗 **Existing Code to Reuse:**
- `wiki/store.py` `BaseWikiStore.list_pages(category, limit, origin)` (:568) — candidate listing
- `wiki/federation.py` `FederatedWikiStore` (:622) + `cli.py::_federate` (:194) — read the `issues` namespace
- `wiki/ledger/service.py` `ready_work` (:201), `merge_blockers` (:322)
- `wiki/decisions/repository.py` `DecisionRepository.inventory()` (:63)
- `wiki/export.py` `page_frontmatter` (:86) — frontmatter shape for the brief file

---

### Option B: Entity attribute plane + standup (recommended)

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

### Option C: Agent-composed brief (AgentsFlow over the MCP tools)

The unconventional route: no new store code. A small `AgentsFlow`
(pattern: FEAT-481's `parrot/flows/wiki_ingest`) runs every morning with
the `wikitoolkit mcp` tools (`wiki_query`, `ledger_ready`,
`wiki_decision_why`, `wiki_page`) and a prompt that produces the brief in
the sketch's format, then `wiki_remember`s it as a page.

✅ **Pros:**
- Zero schema or ingest changes; prompt iteration is cheap.
- Naturally produces the prioritised "On your plate" prose.

❌ **Cons:**
- LLM-first: not deterministic, not offline, not cron-safe without
  credentials; costs tokens every morning for a mostly mechanical job.
- Contradicts the hybrid decision; the tool surface has no status/date
  filters, so the model would page through FTS results.
- Nothing becomes reusable for roll-ups or lint.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| parrot `AgentsFlow`, `AbstractClient` | orchestration | existing |

🔗 **Existing Code to Reuse:**
- `wiki/mcp_server.py` `create_wiki_mcp_server` (:91) — tool surface
- `wiki/tools.py` `create_wiki_tools` (:807)

---

## Recommendation

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

## Feature Description

### User-Facing Behavior

```bash
wikitoolkit standup                      # personal brief for today, markdown to stdout
wikitoolkit standup --team               # drop assignee/author filters
wikitoolkit standup --horizon 14         # recent/upcoming window (default 7 days)
wikitoolkit standup --language es        # or standup.default_language in .parrot/wiki.json
wikitoolkit standup --json               # BriefDocument as JSON
wikitoolkit standup --no-llm             # skip the summary paragraph even if a model is configured
wikitoolkit standup --out ~/vaults/work-notes/Briefs   # also write YYYY-MM-DD-daily.md (default from config)
wikitoolkit standup --no-store           # do not persist the brief page
wikitoolkit standup --date 2026-10-02    # re-render a past day (diff base is the brief before that date)
wikitoolkit standup --period week        # roll-up: ISO week containing --date (default: current week)
wikitoolkit standup --period month       # roll-up: calendar month; diff base = previous period's brief

wikitoolkit entity reindex               # back-fill page_attrs from frontmatter already stored in page bodies (no LLM, no re-ingest)
wikitoolkit entity reindex --store "${PARROT_HOME}/wikis/issues/.parrot/wiki"   # same for the Jira corpus plane (writes go to THAT plane)
wikitoolkit entity add meeting "Bullfrog unit-based commissions" --project roadshows \
    --status held --date 2026-09-22 --owner human:jlara
wikitoolkit entity list --type ticket --status blocked --project roadshows
wikitoolkit remember "Decide the prod deploy window" --category decision \
    --project roadshows --status proposed --due 2026-10-07
```

Rendered brief (sketch honoured; headings localised):

```markdown
# Daily Brief — 2026-10-03

## On your plate today
<≤3 bullets; LLM paragraph when a model is configured, ranked list otherwise>

## By project
### [[roadshows]] — active
- **Blocked / urgent:** issues::file:NAV-10016.md (blocked — prod deploy pending)
- **Open tickets:** …
- **Recent (7d):** [[2026-09-22-bullfrog-unit-based-commissions]]
- **Upcoming:** …
- **Open decisions:** … (4 days old)
- **Drafts in flight:** …
- **In-progress tasks:** TASK-3115 (FEAT-549)

## Internal
- Decisions to make: …   - Drafts to send: …

## Since last brief (2026-10-02)
- New: …   - Closed: …

## Hygiene
- Ledger blockers: 1 · Proposed decisions > 14d: 2 · Tickets untouched > 10d: 5
- Jira watermark: 2026-10-03T06:17Z (ingest-jira) · Wiki stale sources: 0
```

In Claude Code: `/parrotwiki standup [--team] [--horizon N]`; the MCP tool
`wiki_standup(team: bool = False, horizon_days: int = 7, period: str =
"day", language: str | None = None, store: bool = False)` returns the
markdown.

Empty projects (no items in the horizon, no open tickets) are omitted.
Each project's identifiers stay in its own section; cross-namespace items
are rendered with their qualified ids (`issues::file:NAV-10016.md`).

### Internal Behavior

1. **Entity attribute plane** (`wiki/entities.py` + `store.py`):
   `page_attrs(concept_id, key, value, value_kind)`; `BaseWikiStore`
   gains `upsert_attrs`, `list_by_attrs(filters, since, until, limit)`
   and attrs are included in `get_page`. `normalize_frontmatter(dict) ->
   EntityAttrs` applies the vocabulary and aliases (`meeting-source` →
   `meeting`, `meeting_date` → `date`, `primary_project` → `project`,
   Jira `status` → ticket status via a configurable map). Ingest paths
   call it: vault scan (every note), `build`/`upsert` for `.md` documents
   with a YAML block, `ingest-jira` (from `IssueFrontmatter`), `remember`
   (flags), `entity add`. Mapping rules materialise attrs for ledger
   issues (`kind`, `severity`, `status` → ticket), SDD specs (→ project,
   `status` from the task index) and decisions (→ decision,
   `source_status`/`review_status`).
2. **Collectors** (`wiki/standup/collectors.py`): one per source, all
   returning `list[BriefItem]` (`id`, `kind`, `title`, `status`,
   `project_hint`, `date`, `due`, `owner`, `urgency`, `namespace`, `url`).
   Sources: entity attrs (local + selected namespaces); `issues`
   namespace (attrs, fallback body-frontmatter); ledger
   (`ready_work`, `merge_blockers`, plus a new public
   `list_issues(statuses=("open","claimed"))` wrapping `_all_issues`);
   SDD task indexes (`sdd/tasks/index/*.json`, `status == in-progress`,
   `assigned_to`); decisions (`inventory()` filtered to
   `source_status == proposed` or inferred `review_status == unreviewed`);
   memories (`list_pages(origin=["memory","authored"])` with `updated_at`
   inside the horizon); meetings (entity `type: meeting`, `date` in
   `[today-h, today+h]`, status `held|scheduled`).
3. **Identity** (`wiki/standup/identity.py`): `--me` or config
   `standup.me` → `{wiki: human:<user>, jira: <assignee or id>, git:
   <email>}`; defaults from `_authoring_identity(None)`, `JIRA_USERNAME`
   and `git config user.email`. Personal mode filters tickets by
   assignee/assignee_id, memories/decisions by `asserted_by`, tasks by
   `assigned_to`; `--team` disables the filters.
4. **Grouper** (`wiki/standup/grouping.py`): project resolution chain
   (explicit `project` attr → page with `type: project` → Jira `project`
   key → task-index `feature` slug → `Internal`); projects ordered by
   item count; blocked/urgent first inside each section.
5. **Renderer** (`wiki/standup/render.py`): deterministic markdown from
   a `BriefDocument`; heading table for `en`/`es`; `--json` dumps the
   model. The summary paragraph comes from an optional LLM step that
   receives only the ranked `BriefItem` list (never page bodies) and is
   skipped when no model resolves — reuse the env pattern of
   `_build_triage_adapters` / `_extract_into_graph` through one shared
   `resolve_optional_llm(env_names)` helper.
6. **Writer** (`wiki/standup/writer.py`): page `brief:daily:<date>`
   (category `brief` — open string, no enum change; origin `authored`,
   `asserted_by` = identity) with attrs `type=deliverable`,
   `status=draft`, `date`, `owner`, `period`, and `items=<json ids>` for
   the diff; markdown file `<out>/<date>-daily.md` with frontmatter
   (`type: deliverable`, `status: draft`, `owner`, `wiki_id`). `<out>`
   defaults to `${PARROT_HOME}/wikis/briefs/` (outside the repo, G8
   precedent); `--out` / `standup.out_dir` override. When `<out>` is
   inside a registered vault, add the `wiki_sync`/`wiki_scope` markers so
   `sync obsidian --prune` treats it as managed. `WikiBookkeeper.
   log_operation(..., "STANDUP", ...)` records the run.
7. **Delta**: load the latest `brief:<period>:*` page before `--date`,
   compare item ids → "New since" / "Closed since".
8. **Roll-up** (`--period week|month`): same collectors with the window
   set to the ISO week / calendar month containing `--date` (both
   directions of the horizon collapse to the period bounds); page ids
   `brief:weekly:<YYYY-Www>` / `brief:monthly:<YYYY-MM>`, files
   `<YYYY-Www>-weekly.md` / `<YYYY-MM>-monthly.md`; the renderer drops
   "On your plate today" and "Upcoming" in favour of "Closed this period"
   / "Still open" / "Decisions taken"; the diff base is the previous
   period's brief. Daily briefs stored in the period are listed as
   sources so the LLM paragraph (if any) summarises them, not raw items.
9. **Back-fill** (`wikitoolkit entity reindex [--store DIR] [--category C]
   [--dry-run]`): iterates `list_pages` on the *writable* plane, parses
   the YAML block already stored in each body, normalises it and upserts
   attrs; idempotent, no LLM, no source re-read. Because foreign
   namespaces open read-only, the `issues` corpus is reindexed by pointing
   `--store` at its own plane (writes go there), never through `--ns`.
10. **Jira identity**: `IssueFrontmatter.assignee_email` (new, from the
    assignee object `ingest-jira` already fetches); personal mode matches
    `standup.me.jira` or `JIRA_USERNAME` against it and falls back to the
    display name. Canonical ticket status comes from
    `standup.ticket_status_map` (shipped default: To Do/Open → `open`,
    In Progress → `in-progress`, Blocked → `blocked`, In Review/Code
    Review → `in-review`, Done/Closed/Resolved → `closed`); the raw Jira
    name is kept as `status_raw`.
11. **Surfaces**: lazy click group `standup` (generalised `LazyGroup`);
   `WikiStandupTool` registered by `create_wiki_tools`; `standup` bullet
   in `SLASH_COMMAND_MD` and `.claude/commands/parrotwiki.md`; docs in
   `docs/wiki/cheatsheet.md` + a `docs/runbooks/wiki-standup.md` with the
   cron line (`07:00` after the `06:17` Jira sweep).

### Edge Cases & Error Handling

- **No attrs yet** (plane built before the feature): collectors fall
  back to parsing body frontmatter; the Hygiene section prints
  "entity index empty — run `wikitoolkit build --force` /
  `ingest-jira --force`" once.
- **`issues` namespace not registered / unreachable**: ticket section
  omitted with a one-line skip (same shape as `_echo_skips`).
- **No ledger shared root** (`find_shared_root` → None): ledger and task
  sections omitted, never an error.
- **No LLM configured** or the call fails: ranked bullets replace the
  paragraph; the brief still renders and persists; exit code 0.
- **Re-run on the same day**: the brief page is replaced (stable id), the
  file overwritten, the diff base stays the previous day.
- **Unknown `status` for a type**: `entity add` rejects it; ingest paths
  keep the raw value under `status_raw` and leave `status` unset so the
  item still appears under "Open tickets" only if the Jira map says so.
- **Timezone**: dates are compared as ISO calendar dates in the local
  timezone; `--date` is explicit.
- **Jira status vocabulary** differs per instance: `standup.ticket_status_map`
  in `.parrot/wiki.json` with the shipped default above; an unmapped Jira
  status is reported once in Hygiene ("3 tickets with unmapped status:
  'Awaiting QA'") and treated as `open`.
- **Language**: unknown `--language` → error; `es` headings come from a
  static table, item titles stay verbatim, only the LLM paragraph is
  written in the requested language.
- **Roll-up with no daily briefs stored**: the period brief is computed
  from live items only; the "sources" list is empty and says so.
- **`entity reindex` on a read-only plane** (`--ns` foreign namespace):
  refused with the same `write to namespace … requires --ns` style error;
  the message points at `--store`.

---

## Capabilities

### New Capabilities
- `wiki-entity-attributes`: page attribute index (`page_attrs`, additive,
  no schema bump) + entity vocabulary (`wiki/entities.py`, owned here;
  the `wikitoolkit inbox` spec depends on it), frontmatter normalisation
  at every ingest path, mapping rules for ledger/spec/decision planes,
  `wikitoolkit entity add|list|reindex`, `remember` entity flags.
- `wiki-standup-brief`: collectors, identity, grouping, rendering
  (en/es), optional LLM summary, brief page + file writer, diff,
  hygiene, `--period day|week|month` roll-ups, `wikitoolkit standup`,
  `wiki_standup` MCP tool, slash command.

### Modified Capabilities
- `llm-wiki` (wiki CLI): lazy `LazyGroup` generalisation; shared
  `resolve_optional_llm` helper replacing the two inline copies.
- `sdd-work-ledger`: a public `LedgerService.list_issues(statuses=…)`.
- `jira-extractor-llmwiki` (`ingest-jira`): emits attrs from
  `IssueFrontmatter`.
- `wiki-namespaces` / vault scan: frontmatter keys beyond
  `summary`/`description` are now indexed as attrs.
- Claude Code / Codex / Gemini managed assets: `standup` documented.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `wiki/store.py` (`SCHEMA_VERSION`, DDL, `BaseWikiStore`, `SQLiteWikiStore`) | modifies | additive `page_attrs` table + 3 methods; migration precedent `_MIGRATION_COLUMNS`/`_migrate` |
| `wiki/federation.py` `FederatedWikiStore` | modifies | forward `list_by_attrs` to namespace handles (read-only) |
| `wiki/vault_scan.py` | modifies | emit attrs from note frontmatter |
| `wiki/repo_scan.py` / `cli.py::_ingest_files` | modifies | attrs for `.md` documents with a YAML block |
| `wiki/jira_render.py` / `jira_sync.py` | modifies | attrs from `IssueFrontmatter` at render time; new `assignee_email` field (tests: `packages/ai-parrot/tests/knowledge/wiki/test_jira_render.py`) |
| `wiki/cli.py` | extends | `remember` flags, lazy `standup` + `entity` groups (additive blocks) |
| `wiki/lazy_commands.py` | modifies | `LazyAdrGroup` → generic `LazyGroup` |
| `wiki/ledger/service.py` | extends | public `list_issues` |
| `wiki/decisions/repository.py` | depends on | `inventory()` filter only |
| `wiki/tools.py`, `wiki/mcp_server.py` | extends | `WikiStandupTool` |
| `wiki/claude_code/assets.py`, `.claude/commands/parrotwiki.md`, `codex/assets.py`, `google/assets.py` | modifies | document `standup` |
| `wiki/project.py` `WikiProjectConfig` | extends | `standup: StandupConfig` (`default_language`, `horizon_days`, `me {wiki, jira, git}`, `out_dir` default `${PARROT_HOME}/wikis/briefs/`, `ticket_status_map`, `project_map`) |
| `wiki/bookkeeper.py` | depends on | `STANDUP` op tag (free string) |
| `docs/wiki/cheatsheet.md`, `docs/guides/llm-wiki-guide.md`, new `docs/runbooks/wiki-standup.md` | extends | usage + cron |
| FEAT-481 vault frontmatter (`type: meeting-source`, `meeting_date`, `primary_project`) | depends on | aliased by the vocabulary; no shared files |
| `wikitoolkit inbox` (sibling brainstorm `sdd/proposals/wikitoolkit-new-ingestion.brainstorm.md`, committed 2026-10-03, no spec yet) | integrates with | its `InboxClassification` (kind ∈ charter taxonomy, event date, tags) should write `page_attrs` (`type`, `date`, `project`) instead of collapsing kind into a page category; the Hygiene line "Inbox depth" reads its pending-count when the command exists |

No new runtime dependencies. No breaking change to the public store API.

---

## Code Context

### User-Provided Code

```markdown
# Source: user-provided (sketch of the target skill, pasted in the /sdd-brainstorm invocation)
---
name: wiki-daily-brief
description: Synthesize "what's on my plate today" from the wiki — active projects, open tickets, recent meetings, open decisions, upcoming deliverables. Read-only on entity pages. Run each morning.
---

# wiki-daily-brief

Synthesis skill — produces a one-page brief from the wiki's current state.

## Arguments

- `--wiki <path>` — target wiki. If omitted, walk up from cwd for `wiki.yml`.
- `--language <en|es>` — output language. Default: wiki's `default_language`.
- `--horizon <days>` — how far back to look for "recent" and forward for "upcoming". Default: 7.

## Procedure

1. **Locate the wiki + read INDEX.**

2. **Collect:**
   - **Active projects** — `type: project`, `status: active`.
   - **Active engagements** — `type: engagement`, `status: active`.
   - **Open tickets** — `type: ticket`, status `open`, `in-progress`, `blocked` or `in-review`. Surface `blocked` and anything flagged urgent first.
   - **Recent meetings** — `type: meeting`, slug date within last `<horizon>` days, status `held` or `scheduled`.
   - **Upcoming meetings** — `type: meeting`, slug date in next `<horizon>` days, status `scheduled`.
   - **Open decisions** — `type: decision`, status `proposed`.
   - **Drafts in flight** — `type: deliverable`, status `draft` or `sent` (not yet approved/rejected).
   - **Personal backlog** — `pendientes-vinojosa` if present.
   - **Stale flags** — anything that lint would warn about (only if pre-computed; otherwise skip).

3. **Group by project.** For each active project, summarize that project's slice. Order: project with most activity first. Company-level items go under **Internal**.

4. **Render the brief.** Format below.

5. **Write the brief** to `internal/briefs/YYYY-MM-DD-daily.md` (`type: deliverable`, `status: draft`, `owner: [<wiki owner>]`). Also print to stdout.

## Output format

# Daily Brief — <date>

## On your plate today

<2-3 sentence top-of-mind summary, prioritized>

## By project

### [[roadshows]] — active
- **Open tickets:** [[nav-10016-deploy-prod-troc-project-roadshow-units-sold]] (open — prod deploy pending)
- **Recent (7d):** [[2026-09-22-bullfrog-unit-based-commissions]]
- **Upcoming:** <scheduled meeting> — Thursday
- **Open decisions:** <proposed decision> (4 days old)
- **Drafts in flight:** [[roadshows-project-dossier]] (draft)

### [[peloton]] — active
...

## Internal
- Drafts to send today: <list>
- Decisions to make: <list>

## Hygiene
- Last lint: <date>
- Inbox depth: <count>
- Stale flags: <count>

---
Run `wiki-query` for any of the above. Run `wiki-ingest` if inbox has stuff.

## Rules

- **Read-only on entity pages.** Only writes the brief file itself.
- **Honor language.** Use `--language` or `default_language`; a project whose pages are `language: es` may be summarized in ES if the user asks.
- **Respect project separation.** Each project's identifiers stay in its own section.
- **TROC scope only** (`wiki.yml` → `scope`).
- **Skip empty projects.** If a project has no recent or upcoming activity and no open tickets in the horizon, omit its section.
- **Brief = prioritized, not exhaustive.** The "On your plate" top section should be ≤3 bullets, even if there are 20 things active. Use judgment.

`wiki-roll-up` covers the weekly/monthly side.
```

### Verified Codebase References

All paths below are relative to `packages/ai-parrot/src/parrot/knowledge/wiki/`
unless stated otherwise. Verified on `dev` @ `f289e5a7e` (2026-10-03) by
direct read.

#### Classes & Signatures
```python
# store.py:50
SCHEMA_VERSION = "3"

# store.py:93-107 — pages DDL (NO metadata / attrs / status / tags column)
# CREATE TABLE IF NOT EXISTS pages (
#     concept_id TEXT PRIMARY KEY, node_id TEXT, title TEXT NOT NULL,
#     category TEXT NOT NULL DEFAULT 'concept', summary TEXT NOT NULL DEFAULT '',
#     body TEXT NOT NULL DEFAULT '', source_id TEXT, token_count INTEGER NOT NULL DEFAULT 0,
#     created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
#     origin TEXT NOT NULL DEFAULT 'ingest', asserted_by TEXT, content_hash TEXT);
# edges(src, dst, rel DEFAULT 'references', provenance DEFAULT 'extracted')  # store.py:112
# pages_fts USING fts5(title, summary, body, content='pages', tokenize='unicode61')  # store.py:173
# _MIGRATION_COLUMNS (ALTER ADD precedent) store.py:229; async def _migrate(self, conn) store.py:1370

# store.py:409
class WikiPageRecord(BaseModel):
    concept_id: str            # line 444
    node_id: Optional[str]     # line 445
    # title, category (open str), summary, body, source_id, token_count,
    # origin ("ingest" | "memory" | "authored" | ...), asserted_by, updated_at, content_hash
    # — NO metadata/frontmatter dict, NO status, NO tags

# store.py:568 (abstract on BaseWikiStore; SQLite impl at :2034; federated at federation.py:950)
async def list_pages(self, category: Optional[str] = None, limit: int = 100,
                     origin: Optional[list[str]] = None) -> list[dict[str, Any]]: ...
# other abstract reads (store.py:543-605): get_page(concept_id, include_body=True),
#   search_fts(query, category=None, limit=10), neighbors(concept_id, rel=None, direction="both"),
#   dump_pages, dump_edges, stats, orphan_sources, broken_edges, missing_bodies
# writes: upsert_pages(list[WikiPageRecord]) -> int, add_edges(list[tuple]) -> int,
#   replace_source_slice(source_id, pages, edges=None), delete_page(concept_id) -> bool

# models.py:25 — 8 values, none for project/meeting/ticket/deliverable
class WikiPageCategory(str, Enum):
    SUMMARY="summary"; ENTITY="entity"; CONCEPT="concept"; COMPARISON="comparison"   # :42-45
    OVERVIEW="overview"; SYNTHESIS="synthesis"; ANSWER="answer"; ARCHIVE="archive"   # :46-49
# categories in the store are OPEN strings: vault uses "document"/"tag"; remember uses
#   note|decision|lesson|concept; ledger uses "spec"/"task"; memories are pages with origin="memory" (cli.py:3863)

# models.py:52
class WikiConfig(BaseModel):
    wiki_name: str; storage_dir: Path                     # :83-84
    lightweight_model: str | None = None                  # :97  (NOT read by any CLI LLM path)
    model: str | None = None                              # :101
    storage_backend: Literal["sqlite","memory","arangodb"] = "sqlite"   # :112
    charter_path: Path | None = None                      # :122

# project.py
class WikiNamespaceConfig(BaseModel): ...                 # :184
class ObsidianSyncConfig(BaseModel): ...                  # :283
class GlobalWikiRegistry(BaseModel): ...                  # :361
class WikiProjectConfig(BaseModel):                       # :382
    vault_dir: str | None                                 # ~:443
    namespaces: dict[str, WikiNamespaceConfig]            # ~:451
    obsidian_sync: ObsidianSyncConfig | None              # ~:458
    def ledger_path(self, root: Path) -> Path: ...        # :532  → root/.parrot/ledger
def load_project_config(root: Path) -> WikiProjectConfig: ...                     # :772
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig: ...  # :933 (USE THIS; test_env_call_sites enforces it)
def parrot_home() -> Path: ...                            # :1045  PARROT_HOME, default ~/.parrot
def load_global_registry(path=None) -> GlobalWikiRegistry: ...   # :1065  (~/.parrot/wikis.json, GLOBAL_REGISTRY_FILENAME :52)
def merge_namespaces(...): ...                            # :1122  (repo wins)
def find_shared_root(start: Path | None = None) -> Path | None: ...   # :1220

# federation.py
async def resolve_namespaces(root: Path, config: WikiProjectConfig, *, only: set[str] | None = None,
    registry_path: Path | None = None, read_only: bool = True,
    arango_timeout: float = DEFAULT_ARANGO_TIMEOUT) -> tuple[list[NamespaceHandle], list[NamespaceSkip]]: ...  # :461
class FederatedWikiStore(BaseWikiStore):                  # :622
    def scoped(self, selector): ...                       # :712
    async def search_fts(...)                             # :935
    async def list_pages(...)                             # :950
    async def get_page(...)                               # :960
    # add_edges :1357 — source must be local, destination may be a qualified foreign id (FEAT-532 §8)
    # writing a page id in a foreign namespace raises ValueError("write to namespace ... requires --ns") :1280
# context.py:83  qualify_id(namespace, page_id) -> "<ns>::<id>"

# cli.py (5491 lines)
# @click.group(name="wiki") :1437; def wiki(ctx, verbose) :1446; def main() :5457
# commands: mcp 1458, build 1472/1510, upsert 1788, query 1928/1955, page 2014/2026, related 2061,
#   status 2144/2148, communities 3364, export 3471/3480, remember 3776/3806, note 3946/3954,
#   link 4024/4033, memories 4084/4090, audit 4115, ground 4169, ingest 4701/4794,
#   ingest-jira 5168/5249, claude-hook 5442 (hidden)
# groups: symbols 2355, ns 2563, ledger 2849, schema 3212, sync 4242 (push 4254, pull 4288, obsidian 4336)
# adr: wiki.add_command(LazyAdrGroup(name="adr", help=...)) :2348-2352 (lazy, FEAT-584/TASK-3569)
def _declared_namespaces(config): ...                     # :153
def _selected_namespaces(ns_opt) -> set[str] | None: ...  # :171  None/"all" broadcast, "local" → empty set
def _federate(root, config, local, ns_opt) -> BaseWikiStore: ...   # :194
def _echo_skips(...): ...                                 # :338
def _open_store(root, config): ...                        # :464
def _run(coro): ...                                       # :560
def _env_setting(name: str) -> str | None: ...            # :565  navconfig first, then os.environ
def _resolve_read_store(...): ...                         # :583
def _authoring_identity(by: str | None) -> str: ...       # :3513  --by → CLAUDE_AGENT_ID/PARROT_AGENT_ID (agent:<v>) → human:<getpass.getuser()> → human:unknown  (NO git config)
def _resolve_write_store(...): ...                        # :3546
def _extract_into_graph(...): ...                         # :3709  WIKI_EXTRACT_LLM, prints "[extract skipped…]" when unconfigured (:3728)
def remember(text: str, path_: str | None, store_opt: str | None, backend_opt: str | None,
             title: str | None, category: str, links: tuple[str, ...], rel: str, ns_opt: str | None,
             source_uri: str | None, by: str | None, extract_: bool, as_json: bool) -> None: ...   # :3806
#   options: --title, --category (default "note", help "note | decision | lesson | concept"), --link (multiple),
#   --rel (default "references"), --ns, --source, --by, --extract, --json; page id = hash(title+category)
def memories(...): ...                                    # :4090  store.list_pages(category=category, limit=limit, origin=["memory","authored"])
def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]: ...   # :4477
#   env resolution :4908-4925: --lightweight-model/--model → _env_setting("WIKI_LIGHTWEIGHT_MODEL"/"WIKI_MODEL")
#   → parrot.clients.detection.detect_coding_agent_llm() (clients/detection.py:19) unless PARROT_NO_AUTO_LLM

# lazy_commands.py:21
class LazyAdrGroup(click.Group):   # _load_real_group / get_command / list_commands; hardcoded import of decisions.cli.adr

# vault_scan.py
def is_obsidian_vault(root) -> bool: ...                  # :62
def tag_concept_id(tag) -> str: ...                       # :74  "tag:<tag>"
def _note_summary(note: ObsidianNote) -> str: ...         # :90  only frontmatter summary/description are used
def _note_body(note: ObsidianNote, body_max_chars: int) -> str: ...   # :103  "# title", "Tags:", "Aliases:" + content
def scan_vault(...): ...                                  # :118  pages "file:<rel>" category "document"; tags → tag: pages + `tagged` edges
# YAML parsing delegated to parrot.interfaces.obsidian.parser.ObsidianNoteParser (imported :35)
# repo_scan.py:263 file_concept_id(rel) -> "file:<rel>"

# jira_render.py
SYNC_MARKER = "<!-- jira-sync:end — everything below is yours; the extractor never touches it -->"   # :39
class IssueFrontmatter(BaseModel):                        # :116
    type: ConceptType = ConceptType.ISSUE; key: str; title: str; status: str; resolution: str | None
    category: str  # Jira issuetype
    project: str; priority: str | None; assignee: str | None; assignee_id: str | None
    reporter: str | None; reporter_id: str | None
    created_at: str | None; updated_at: str | None; resolved_at: str | None
    labels: list[str]; components: list[str]; epic: str | None; parent: str | None
    subtasks/blocks/blocked_by/relates/duplicates: list[str]; repo_pages: list[str]; url: str
    sync: IssueSyncStamp                                  # :108
def render_issue_document(issue: JiraIssue, *, fetched_at: datetime, existing: str | None = None,
                          repo_pages: list[str] | None = None) -> str: ...   # :497
# jira_sync.py: resolve_issues_dir(explicit=None) -> Path :152 (default parrot_home()/"wikis"/"issues");
#   watermark <issues_dir>/.parrot/jira_sync.json (_SYNC_STATE_FILENAME :58); load_sync_state :176;
#   JiraScopeState.last_watermark :101

# ledger/service.py
class LedgerService:                                      # :98
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService": ...          # :116
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]: ...        # :152 (PRIVATE — only way to see claimed issues)
    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]: ...   # :201  status=="open" only, SEVERITY_ORDER
    async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str: ...  # :289
    async def merge_blockers(self, feature_id: str) -> list[dict[str, Any]]: ... # :322
    async def feature_index_status(self, feature_ids): ...                      # :383
# _issue_dict (:80): issue_id, title, status, kind, severity, acknowledged, discovered_from, about,
#   claimed_by, closed_by, closed_reason, resolved_by — NO timestamps (only LedgerEvent.ts events.py:110)
# ledger/events.py: IssueKind :22, IssueSeverity :23, IssueStatus = open|claimed|closed|superseded :24, SEVERITY_ORDER :26
# ledger/sdd_ingest.py: class SDDGraphIngest(store, shared_root) :51; ingest_all :66;
#   spec pages "spec:<filename>" category "spec" (:145,:166); task pages "task:<id>" category "task" origin "sdd-task" (:255-292)
#   → status/feature are BODY TEXT ONLY; structured status/started_at/assigned_to/feature_id live in sdd/tasks/index/*.json
# ledger/fix_planner.py:230 plan_fix_batch(issues, *, kind=None, severity=None, lane_override=None, ...)
# ledger/sdd_meta.py:45 KNOWN_PROJECTS: frozenset[str]  (re-exported by scripts/sdd/sdd_meta.py:10-12)

# decisions/models.py
class DecisionRecord(BaseModel):                          # :143
    source_status: Literal["unknown","proposed","accepted","rejected","deprecated","superseded"] = "unknown"   # :153
    origin: Literal["documented","inferred"]; review_status: Literal["unreviewed","accepted","rejected"]
    # inferred records MUST keep source_status="unknown" (validator :170-173)
class DecisionConfig(BaseModel): ...                      # :62  generation_enabled=False
# decisions/repository.py:26 DecisionRepository(store, max_records=10_000); async def inventory() -> list[DecisionRecord] :63
# decisions/service.py:96 DecisionService(store, root, config, structural=None, client=None); for_symbol :193; why :276
# decisions/cli.py:106 _build_service(path_, namespace, *, writable); decisions/tools.py: WikiDecisionWhyTool :140, create_decision_tools :210
# decisions/generation.py:64 resolve_client(config, client) — env WIKI_ADR_LLM

# tools.py
class WikiQueryTool(AbstractTool):                        # :225  args_schema WikiQueryInput :161
    async def _execute(self, question: str, budget_tokens: int = DEFAULT_BUDGET_TOKENS,
                       namespace: str | None = None, include_symbols: bool = False) -> str: ...   # :245
class WikiRememberTool(AbstractTool): ...                 # :336  (_execute :352, input :192)
class WikiStatusTool(AbstractTool):                       # :514
    async def _execute(self) -> ToolResult: ...           # :525  (WikiStatusInput :221, empty)
def create_wiki_tools(store, ..., ledger_service=None): ...   # :807  Query/Page/Related/Remember/Note/Status + ledger_* when service present (:839-849)

# mcp_server.py
def create_wiki_mcp_server(root: Path) -> StdioMCPServer: ...   # :91  load_effective_config → create_wiki_store;
#   ledger mounted read-only as namespace "ledger" when find_shared_root(root) (:160-198); server.register_tools(tools) :307; main :313

# claude_code/assets.py
SLASH_COMMAND_FILENAME = "parrotwiki.md"                  # :71
CLAUDE_MD_SECTION = ...                                   # :221  (markers CLAUDE_MD_BEGIN/END :23-24)
SLASH_COMMAND_MD = """---                                 # :307
argument-hint: [query <question> | page <id> | related <id> | remember <fact> | note <id> <text> | link <a> <b> | memories | audit | status | build | --wiki [dir]]   # :309
# bullet action list :321-345
# codex/assets.py: AGENTS_SECTION :26, SKILL :34 · google/assets.py: GEMINI_SECTION :32, SKILL :40 · coding_agents.py: _AGENTS :43

# obsidian_sync.py
SYNC_MARKER_KEY = "wiki_sync"; SYNC_SCOPE_KEY = "wiki_scope"; SYNC_ID_KEY = "wiki_id"   # :65,:72,:75
def project_scope(root, wiki_name) -> str: ...            # :91
def folder_for_category(...): ...                         # :147
def note_relpath(sync_config, namespace, category, concept_id) -> str: ...   # :160
def render_note(page: dict, related: list[tuple[str, str, str]], *, wiki_name, scope, namespace) -> str: ...   # :183
async def sync_obsidian(root, *, vault=None, namespaces=None, categories=None, prune=None,
                        dry_run=False, env=None) -> ObsidianSyncReport: ...   # :399

# export.py
async def export_okf_bundle(store: BaseWikiStore, output_dir: Path, wiki_name: str = "") -> WikiExportReport: ...   # :125
def page_frontmatter(...)   # :86  keys type, title, id, tags=[category], timestamp=updated_at, summary?, relates_to?

# bookkeeper.py:175
def log_operation(self, wiki_dir: Path, operation: str, details: str, timestamp: Optional[str] = None) -> None: ...  # free-string op

# ../pageindex/llm_adapter.py
class PageIndexLLMAdapter:   # :42; __init__(self, client: AbstractClient, model: Optional[str] = "gemini-3.1-flash-lite-preview", max_retries=3, retry_delay=1.0) :49
    async def ask(self, prompt, structured_output=None, temperature=0.0, system_prompt=None) -> str: ...   # :61
    async def ask_structured(self, prompt, output_type: type, temperature=0.0, system_prompt=None): ...     # :99

# packages/ai-parrot/src/parrot/agents/meeting_registry.py:167
class MeetingRegistry: ...   # FEAT-472 (done): Fireflies meeting notes in a vault, frontmatter fireflies_id/title/meeting_date
```

#### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord, SCHEMA_VERSION
from parrot.knowledge.wiki.models import WikiConfig, WikiPageCategory
from parrot.knowledge.wiki.project import (WikiProjectConfig, load_effective_config, parrot_home,
                                           find_shared_root, load_global_registry, merge_namespaces)
from parrot.knowledge.wiki.federation import FederatedWikiStore, resolve_namespaces
from parrot.knowledge.wiki.context import qualify_id
from parrot.knowledge.wiki.lazy_commands import LazyAdrGroup
from parrot.knowledge.wiki.vault_scan import scan_vault, is_obsidian_vault
from parrot.knowledge.wiki.jira_render import IssueFrontmatter, render_issue_document, SYNC_MARKER
from parrot.knowledge.wiki.jira_sync import resolve_issues_dir, load_sync_state
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, IssueStatus, SEVERITY_ORDER
from parrot.knowledge.wiki.ledger.sdd_meta import KNOWN_PROJECTS
from parrot.knowledge.wiki.decisions.models import DecisionRecord, DecisionConfig
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.tools import create_wiki_tools, WikiStatusTool
from parrot.knowledge.wiki.obsidian_sync import render_note, sync_obsidian
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.interfaces.obsidian.parser import ObsidianNoteParser
```

#### Key Attributes & Constants
- `SCHEMA_VERSION = "3"` (store.py:50) — v3 planes broke v2 code when bumped (memory: wiki FTS hotfix); restart the MCP server after any bump.
- `WikiPageRecord.origin` ∈ `"ingest" | "memory" | "authored" | "sdd-task" | …` — memories are selected by `origin`, not by a table.
- `IssueStatus` = `open | claimed | closed | superseded` (ledger/events.py:24); `ready_work` returns `open` only.
- `DecisionRecord.source_status == "proposed"` only for `origin == "documented"`; inferred candidates are `review_status == "unreviewed"`.
- Jira issue corpus lives outside the repo at `${PARROT_HOME}/wikis/issues` (G8); the namespace is registered by hand with `ns add issues --store … --global`.
- `_authoring_identity` never reads git; `sync` uses `parrot.knowledge.wiki.sync.default_local_identity` (cli.py:4269).
- Tests: `tests/knowledge/wiki/` (root, 100+ modules: `test_cli.py`, `test_authoring.py`, `test_ledger_*.py`, `test_obsidian_sync.py`, `test_namespaces_e2e.py`) and `packages/ai-parrot/tests/knowledge/wiki/` (`test_jira_render.py`, `test_vault_scan.py`, `test_mcp_server*.py`, own `conftest.py`); fixtures `wiki_config(tmp_path)` (tests/knowledge/wiki/conftest.py:59), autouse `isolated_parrot_home` (:41).
- Cron precedent: `docs/runbooks/jira-issues-namespace.md:105` ("The daily sweep") and `docs/wiki/cheatsheet.md:311`.
- FEAT-481 (in progress) vault vocabulary: `type: meeting-source`, `meeting_date`, `primary_project ∈ projects` (`sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md:198-212`).

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit standup`~~, ~~`brief`~~, ~~`daily`~~, ~~`entity`~~ commands; ~~`wiki_standup`~~ MCP tool; ~~`/parrotwiki standup`~~ — all new.
- ~~a page metadata / frontmatter / attributes column~~ on `pages`; ~~`WikiPageRecord.status`~~, ~~`.tags`~~, ~~`.metadata`~~ — the only metadata dict is `SourceManifestEntry.doc_metadata` (models.py:236), per source, not per page.
- ~~`WikiPageCategory.PROJECT | MEETING | TICKET | DELIVERABLE | DECISION | BRIEF`~~ — categories are open strings; add values only if a spec decides to.
- ~~`default_language`~~ / ~~`language`~~ config key anywhere in `project.py` / `models.py` (only `symbols lookup --language`, cli.py:2365, unrelated).
- ~~`WikiMemory`~~ model, ~~`memories` table~~ — memories are `pages` rows with `origin="memory"`.
- ~~`LedgerService.list_issues`~~ / any public "open + claimed" listing — only private `_all_issues`; ~~`opened_at`~~ in the issue dict.
- ~~structured `status` / `feature_id` / `started_at` on `task:` pages~~ — body text only; read `sdd/tasks/index/*.json`.
- ~~`DecisionRepository.list_proposed()`~~ — filter `inventory()` yourself.
- ~~a shared optional-LLM helper~~ — the skip-if-unconfigured logic is duplicated inline (cli.py:3728 and :4910); ~~`WikiConfig.lightweight_model` consumed by the CLI~~ — every path uses env vars.
- ~~a generic `LazyGroup`~~ — `LazyAdrGroup` hardcodes `decisions.cli.adr`.
- ~~`remote_cli.py`~~, ~~`@remote_aware`~~ — FEAT-569 is spec/proposal only, not in code.
- ~~`wiki.yml`~~, ~~`INDEX`~~, ~~`wiki-query` / `wiki-ingest` / `wiki-roll-up` skills~~, ~~`pendientes-vinojosa`~~ — artefacts of the user's sketch, not of this repo.
- ~~cross-namespace edges are rejected~~ — only the *source* must be local (federation.py:1357); foreign destinations are allowed as qualified ids.
- Vault frontmatter keys other than `summary`/`description` (and tags/aliases rendered into the body) are **not** persisted or indexed today.
- `issues` plane pages carry `IssueFrontmatter` as text in the body only; there is no structured status/assignee column to query.

---

## Parallelism Assessment

- **Internal parallelism**: mixed. Lane 1 (sequential, first): `page_attrs` store migration + `entities.py` vocabulary + `BaseWikiStore`/`FederatedWikiStore` methods. After Lane 1 lands, four ingest adapters are independent files (`vault_scan.py`, `_ingest_files`/`repo_scan.py`, `jira_render.py`/`jira_sync.py`, `remember`+`entity` CLI) and six collectors under `wiki/standup/` are independent modules sharing only `BriefItem`. Renderer/writer/identity/grouping depend on `BriefItem`; CLI group, MCP tool, assets and docs come last.
- **Cross-feature independence**: `wiki/cli.py` is hot (FEAT-569 `wikitoolkit-http-mcp`, FEAT-570 `expose-local-mcp-tools` and FEAT-557 `wikitoolkit-sqlite` all have tasks on `dev` with no worktree yet; FEAT-569 also targets `mcp_server.py`). FEAT-481 (in progress) writes the vault frontmatter this feature reads — no shared files, only vocabulary alignment. FEAT-578 (wiki ADR plane) owns `decisions/`; this feature reads `inventory()` only. The sibling `wikitoolkit inbox` brainstorm (2026-10-03) also plans a new `cli.py` command block and a `create_wiki_tools` entry, and its classifier taxonomy (meeting, briefing, decision, report, memo + event date) overlaps the entity vocabulary — the two specs must share one vocabulary module (`wiki/entities.py`) rather than define it twice. Rebase on `dev` before touching `cli.py`, `tools.py`, `mcp_server.py`.
- **Recommended isolation**: `mixed` — one feature worktree; Lane 1 sequential, then the adapter + collector tasks parallel-safe (distinct files), then a sequential tail for `cli.py`/`tools.py`/assets. The roll-up renderer mode and `entity reindex` are two more file-disjoint tasks in the parallel band. Lane 1 (`page_attrs` + `entities.py`) should be the first PR out of the worktree so the inbox spec can base on it.
- **Rationale**: the store migration is a single shared dependency and must land first; everything after it is file-disjoint by construction, which is exactly what the sdd-worker's per-task sub-worktrees exploit. The hot-file tail is kept sequential to avoid three concurrent diffs on `cli.py`.

---

## Open Questions

All resolved 2026-10-03 (Jesus, open-question round after the brainstorm).

- [x] **Schema bump or additive-only?** A new `page_attrs` table via `CREATE TABLE IF NOT EXISTS` needs no version bump, but keeping `SCHEMA_VERSION="3"` means older code opens a plane it does not fully understand (harmless for reads). Bumping to `"4"` breaks v3 readers (known gotcha). — *Owner: Jesus*: additive, `SCHEMA_VERSION` stays `"3"`; `wikitoolkit status` reports `attrs: N pages indexed`.
- [x] **Jira "open" status vocabulary**: where does the `status_raw` → canonical mapping live? — *Owner: Jesus*: `.parrot/wiki.json` `standup.ticket_status_map` with a shipped default (To Do/Open → open, In Progress → in-progress, Blocked → blocked, In Review/Code Review → in-review, Done/Closed/Resolved → closed); raw value kept as `status_raw`; unmapped statuses treated as open and reported in Hygiene.
- [x] **Default brief folder**: `${PARROT_HOME}/wikis/briefs/`, the vault, or `docs/`? — *Owner: Jesus*: always `${PARROT_HOME}/wikis/briefs/`; vault users pass `--out` (or `standup.out_dir`), and a vault target gets the `wiki_sync` markers.
- [x] **Identity for "me" in Jira**: `assignee` is a display name, `assignee_id` an account id, `JIRA_USERNAME` an email. — *Owner: Jesus*: add `assignee_email` to `IssueFrontmatter`; match `standup.me.jira` / `JIRA_USERNAME` against it, fall back to the display name.
- [x] **Back-fill of existing planes**: `ingest-jira --force` vs. a body re-read pass? — *Owner: Jesus*: new `wikitoolkit entity reindex [--store DIR] [--category] [--dry-run]` — re-reads stored bodies, no re-ingest, no LLM, idempotent; the `issues` plane is reindexed via `--store` (foreign namespaces are read-only).
- [x] **Vocabulary alignment with FEAT-481**: alias its `meeting-source` / `daily-note` / `synthesis`, or ask FEAT-481 to emit ours? — *Owner: Jesus*: alias only in `entities.py`; FEAT-481 is not modified.
- [x] **Spanish rendering**: static headings only vs. translating titles. — *Owner: Jesus*: static heading table, item titles verbatim, only the LLM paragraph is written in the requested language.
- [x] **`brief` as a `WikiPageCategory` value** or an open-string category? — *Owner: Jesus*: open-string `brief` (like `note`/`decision`); `export` lands it under `briefs/`; `memories --category brief` lists past briefs.
- [x] **Weekly/monthly roll-up** (`wiki-roll-up` in the sketch): follow-up spec or in scope? — *Owner: Jesus*: **in scope** as `standup --period day|week|month` (same collectors, period-bounded window, `brief:weekly:<YYYY-Www>` / `brief:monthly:<YYYY-MM>` pages, "Closed this period / Still open / Decisions taken" sections, diff against the previous period, daily briefs listed as sources). See Internal Behavior step 8.
- [x] **Ownership of the entity vocabulary vs. `wikitoolkit inbox`**: which spec owns `wiki/entities.py`? — *Owner: Jesus*: this spec owns `entities.py` + `page_attrs`; the inbox spec depends on it and its classifier writes attrs (`type`, `date`, `project`) from day one. Lane 1 of this feature is the first PR so inbox can base on it.
