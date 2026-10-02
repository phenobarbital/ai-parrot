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

# Feature Specification: `wikitoolkit standup` — entity attributes + daily/weekly/monthly brief

**Feature ID**: FEAT-627
**Date**: 2026-10-03
**Author**: Jesus Lara (discovery + open-question rounds) + Claude
**Status**: draft
**Target version**: next minor
**Brainstorm**: `sdd/proposals/wikitoolkit-standup.brainstorm.md` (accepted 2026-10-03, Option B)
**Design research**: `sdd/state/FEAT-627/design_research/` (codex `gpt-5.6-luna`, 12 suggestions — §9)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The LLM wiki already holds far more than code: authored memories
(`note | decision | lesson | concept`), the Jira ticket corpus (`issues`
namespace, FEAT-454), Obsidian vaults (meeting notes from FEAT-472 / FEAT-481),
the SDD work ledger (open issues, specs, tasks) and the ADR plane. What it
lacks is a **synthesis**: a one-page "what's on my plate today" that groups
open tickets, recent and upcoming meetings, proposed decisions, in-progress
tasks and drafts by project, surfaces blockers first, and tells the reader
what changed since the last brief — plus the same view over a week or a
month.

Today that synthesis is done by hand (several `wikitoolkit query` /
`ledger ready` / `adr why` calls) or not at all. The user's sketch
(`wiki-daily-brief`, preserved verbatim in the brainstorm's *User-Provided
Code*) describes the target output and assumes every page carries typed
frontmatter (`type: project|meeting|ticket|decision|deliverable`, `status:`,
dates, `owner:`). The wiki does **not** have that today:

- the `pages` table has no metadata column (`store.py:93-107`);
- vault ingest keeps only `summary`/`description` from frontmatter and
  drops every other key (`vault_scan.py:90-103`);
- Jira frontmatter survives only as text inside the page body
  (`jira_render.py:116`, rendered by `render_issue_document`).

So the feature has two halves: **(1)** make the wiki able to answer "which
pages are tickets / meetings / decisions, with what status, project and
date?" cheaply and uniformly, and **(2)** a `standup` command that collects,
groups, renders and stores the brief — deterministic by default, with an
optional LLM one-paragraph summary.

### Goals

- **G1 — Entity attribute plane.** An additive `page_attrs` table in the
  SQLite store (no `SCHEMA_VERSION` bump), carried on `WikiPageRecord.attrs`
  and written in the same transaction as the page, populated from
  frontmatter at every ingest boundary (vault scan, markdown documents in
  `build`/`upsert` — which is how the Jira corpus is built — `remember`
  entity flags, `wikitoolkit entity add`).
- **G2 — One entity vocabulary**, owned by this spec in
  `parrot/knowledge/wiki/entities.py`: closed `type` set (incl. `task`),
  per-type canonical `status` enums, `project`/`date`/`due`/`owner`/`source`
  keys, and aliases for FEAT-481's vault vocabulary (`meeting-source`,
  `meeting_date`, `primary_project`) and Jira's `issue`. The sibling
  `wikitoolkit inbox` spec depends on this module and writes attrs from day
  one; it never redefines the taxonomy.
- **G3 — `wikitoolkit standup [--period day|week|month]`**: deterministic
  collectors over entity attrs, the `issues` namespace, the SDD ledger, the
  per-spec task indexes, the ADR plane and memories; project grouping
  (`project:` → Jira key → SDD slug → `Internal`); blocked/urgent first;
  "since last brief" diff; Hygiene from existing data; `en`/`es` headings.
- **G4 — Personal by default, `--team` widens**, with an identity model that
  respects FEAT-454 **G9** (no email in the plane): Jira matching uses
  `assignee_id`, resolved once from `/myself` and cached.
- **G5 — Hybrid synthesis**: section lists never need a model; only the
  "On your plate" paragraph uses an optional LLM over a bounded structured
  projection, and the deterministic brief is always written even when the
  model fails.
- **G6 — Three surfaces**: CLI (lazily registered), `wiki_standup` MCP tool
  (read-only unless `store=true`), `/parrotwiki standup`.
- **G7 — Outputs**: brief page `brief:<period>:<id>` in the local plane
  (open-string category `brief`) and a markdown file under
  `${PARROT_HOME}/wikis/briefs/` (atomic write; `--out` overrides).
- **G8 — Back-fill** via `wikitoolkit entity reindex` (re-reads stored
  bodies, no re-ingest, no LLM).
- **G9 — Hook budget**: the `claude-hook` fast path (FEAT-584) must not
  import `entities`, `standup/` or any new heavy module.

### Non-Goals (explicitly out of scope)

- Changing `wikitoolkit build`'s offline/no-LLM contract or the LLM ingest
  orchestrator (`ingest.py`); attrs extraction is deterministic frontmatter
  parsing only.
- Modifying FEAT-481 (Fireflies → vault) or FEAT-472; their vocabulary is
  aliased, never rewritten (brainstorm Q6).
- Full attrs parity for the ArangoDB / Postgres stores in v1 — they report
  `supports_attrs = False` and collectors fall back to body-frontmatter
  parsing (§8 Q11).
- A new lint pass. Hygiene reads what exists (ledger blockers, decision ages,
  Jira watermark, FEAT-625's `lint/report.json` when present).
- Translating item titles; only headings are localised and only the optional
  LLM paragraph is written in the requested language (brainstorm Q7).
- Adding `assignee_email` (or any email) to the Jira corpus — the brainstorm's
  Q4 answer was superseded during spec research by the G9 guard
  (`parrot/interfaces/jira/models.py:1-13`); see §8 Q4.
- The inbox classifier itself (`wikitoolkit inbox`, sibling brainstorm
  `sdd/proposals/wikitoolkit-new-ingestion.brainstorm.md`) — it consumes
  `entities.py`.
- Rejected in brainstorm: a reader-only command parsing bodies every morning
  (Option A, kept only as the fallback path) and an agent-composed brief
  (Option C).

---

## 2. Architectural Design

### Overview

**Half 1 — entity attributes.** `WikiPageRecord` gains
`attrs: dict[str, str]` (default empty). `SQLiteWikiStore.upsert_pages` /
`replace_source_slice` write those rows into a new `page_attrs(concept_id,
key, value)` table **in the same transaction as the page row**, and
`delete_page` / `replace_source_slice` remove attrs of pages that go away —
so attrs can never outlive or lag their page (codex S1). The table is created
by the normal DDL replay and, for pre-existing v3 planes, by a table-presence
check in `_migrate`; read-only planes that lack it answer `supports_attrs =
False` and `list_by_attrs()` returns `[]` (codex S2). `SCHEMA_VERSION` stays
`"3"` (brainstorm Q1). `BaseWikiStore` gets four non-abstract methods with
"unsupported" defaults (`supports_attrs`, `get_attrs`, `list_by_attrs`,
`upsert_attrs`); SQLite and the in-memory store implement them; Arango and
Postgres inherit the defaults (codex S6). `FederatedWikiStore` forwards
`list_by_attrs` to every handle that supports it and qualifies ids.

Attrs are extracted **at the source boundary, never from stored bodies**
(codex S3): `repo_scan.build_file_slice` parses the leading YAML block of
markdown documents (the same block `_markdown_summary` already recognises)
and `vault_scan.scan_vault` uses `note.frontmatter`; both call
`entities.normalize_frontmatter()` and set `record.attrs`. Because
`ingest-jira` builds the `issues` plane through `build.callback` → the same
markdown path, Jira tickets get attrs with **no change to `jira_render.py`**.
`wikitoolkit entity reindex` is the one exception: it re-parses the YAML
block that is still present in stored bodies, for planes built before this
feature.

**Half 2 — the brief.** `parrot/knowledge/wiki/standup/` is a package of
pure collectors (one per source, all returning `list[BriefItem]`), an
identity resolver, a project grouper, a deterministic renderer (`en`/`es`
heading table), an optional LLM summariser over a bounded projection (codex
S11), and a writer that stores the brief page under the wiki writer lock and
replaces the markdown file atomically (codex S9). Ledger issues, SDD tasks
and ADR decisions are read through their **native APIs** (a new public
`LedgerService.list_issues`, the per-spec task index JSON, and
`DecisionRepository.inventory()`), not through attrs — so no existing plane
needs a materialisation change (codex S4/S5). Identity follows G9: Jira
tickets are matched on `assignee_id`, resolved once from `JiraInterface`'s
`/myself` probe and cached outside the corpus.

**Surfaces.** `LazyAdrGroup` is generalised into `LazyGroup(import_path,
attr)` so `adr`, `standup` and `entity` all defer their imports (codex S7);
`WikiStandupTool` is registered by `create_wiki_tools` with `store=False`
by default (codex S10); the `/parrotwiki` slash command (managed asset and
the checked-in copy) documents `standup`.

### Component Diagram

```
                     ┌──────────── ingest boundaries ────────────┐
 vault_scan.scan_vault ──note.frontmatter──┐                      │
 repo_scan.build_file_slice ──YAML block───┼─► entities.normalize_frontmatter()
 cli remember --category/--project/… ──────┤        │  (aliases, per-type enums)
 cli entity add / reindex ─────────────────┘        ▼
                                           WikiPageRecord.attrs
                                                    │ same transaction (M1)
                                                    ▼
                               SQLiteWikiStore.pages + page_attrs ──► list_by_attrs()
                               (InMemoryWikiStore idem; Arango/Postgres: supports_attrs=False)

 wikitoolkit standup [--period day|week|month] [--team] [--language] [--out] [--json]
        │
        ├─ identity.resolve()        standup.me · _authoring_identity · JIRA_* → /myself (cached, G9)
        ├─ periods.window()          timezone + week_start + horizon, injectable clock
        ├─ collectors (parallel, each → list[BriefItem])
        │     entities  : local + namespaces via list_by_attrs (fallback: body YAML)
        │     jira      : issues:: pages type=ticket → ticket_status_map → canonical
        │     ledger    : LedgerService.list_issues(open|claimed) + merge_blockers
        │     tasks     : sdd/tasks/index/*.json  status=in-progress / assigned_to
        │     decisions : DecisionRepository.inventory()  proposed | unreviewed
        │     memories  : list_pages(origin=memory|authored) updated_at in window
        ├─ grouping.resolve_project()   project attr → project page → Jira key → SDD slug → Internal
        ├─ render.render_markdown(doc, language)   (+ optional llm.summarize(projection))
        ├─ delta.diff(previous brief page attrs.items)
        └─ writer.write(page brief:<period>:<id> under wiki_write_lock; file tmp→os.replace)

 MCP  WikiStandupTool(store=False)  ──►  same pipeline, local plane only
 CLI  LazyGroup("…standup.cli", "standup") · LazyGroup("…entity_cli", "entity") · LazyGroup("…decisions.cli", "adr")
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `wiki/store.py` `WikiPageRecord` (:409), `SQLiteWikiStore` (:878), DDL (:93-110), `_migrate` (:1370) | modifies | `attrs` field; `page_attrs` table; same-transaction writes; table-presence migration; `stats()` gains `attrs_pages` |
| `wiki/store.py` `BaseWikiStore` (:525) | extends | non-abstract `supports_attrs` / `get_attrs` / `list_by_attrs` / `upsert_attrs` defaults |
| `wiki/file_store.py` `InMemoryWikiStore` (:73) | modifies | real attrs implementation (tests + `memory` backend) |
| `wiki/federation.py` `FederatedWikiStore` (:622), `_EmptyStore` (:1576) | modifies | forward `list_by_attrs`/`get_attrs` with qualified ids; `_EmptyStore` returns `[]` |
| `wiki/repo_scan.py` `build_file_slice` (:572, markdown branch :643) | modifies | parse YAML block → `record.attrs` |
| `wiki/vault_scan.py` `scan_vault` (:118, record at :163-171) | modifies | `note.frontmatter` → `record.attrs` |
| `wiki/cli.py` `remember` (:3776-3820), `memories` (:4090), `status` (:2148), `wiki.add_command(LazyAdrGroup…)` (:2347-2352) | extends | entity flags; `attrs:` line; lazy `standup` + `entity` groups; `--category brief` listing works unchanged |
| `wiki/lazy_commands.py` `LazyAdrGroup` (:21) | modifies | generalised `LazyGroup`; `LazyAdrGroup` kept as a thin subclass |
| `wiki/ledger/service.py` `LedgerService` (:98) | extends | public `list_issues(statuses=…)` wrapping `_all_issues` (:152) |
| `wiki/decisions/repository.py` `DecisionRepository.inventory()` (:63) | uses | filtered to `source_status == "proposed"` or inferred + `review_status == "unreviewed"`; age from ADR page `updated_at` |
| `parrot/interfaces/jira/client.py` `JiraInterface` (`_probe_auth_sync` :376) | extends | `async myself() -> JiraPerson` (accountId + displayName only — G9) |
| `wiki/jira_render.py` `IssueFrontmatter` (:116) | depends on | read as attrs (`type: issue` → `ticket`, `status` → `status_raw`, `updated_at` → `date`, `project`, `assignee_id`); **not modified** |
| `wiki/project.py` `WikiProjectConfig` (:382), `WikiEnvOverlay` (:816), `wiki_write_lock` (:74), `parrot_home` (:1045) | extends / uses | `standup: StandupConfig` on both config and overlay (codex S8); lock around brief page writes |
| `wiki/tools.py` `create_wiki_tools` (:807), `WikiStatusTool` pattern (:514) | extends | `WikiStandupTool` |
| `wiki/claude_code/assets.py` `SLASH_COMMAND_MD` (:307, `argument-hint` :309, bullets :321-345); `.claude/commands/parrotwiki.md` (:34) | modifies | `standup` + `entity` documented in both (same task) |
| `wiki/bookkeeper.py` `log_operation` (:175) | uses | `STANDUP`, `ENTITY`, `REINDEX` op tags (free strings) |
| `wiki/jira_sync.py` `load_sync_state` (:176), `resolve_issues_dir` (:152) | uses | Hygiene: watermark age |
| FEAT-625 `wikitoolkit lint` `<storage_dir>/lint/report.json` | depends on (soft) | Hygiene "Last lint" when the file exists; absent → line omitted |
| FEAT-481 vault frontmatter (`type: meeting-source`, `meeting_date`, `primary_project ∈ projects`) | depends on | aliased in `entities.py` |
| `sdd/proposals/wikitoolkit-new-ingestion.brainstorm.md` (inbox) | provides to | inbox classifier writes `record.attrs` through `normalize_frontmatter` |
| `docs/wiki/cheatsheet.md` (:489), `docs/guides/llm-wiki-guide.md` (:921), new `docs/runbooks/wiki-standup.md` | extends | usage + cron line (`07:00`, after the `06:17` Jira sweep) |

### Data Models

```python
# parrot/knowledge/wiki/entities.py (new)
EntityType = Literal["project", "engagement", "meeting", "ticket", "task",
                     "decision", "deliverable", "person"]

STATUS_BY_TYPE: dict[EntityType, tuple[str, ...]] = {
    "project":     ("active", "paused", "done", "archived"),
    "engagement":  ("active", "paused", "done", "archived"),
    "meeting":     ("scheduled", "held", "cancelled"),
    "ticket":      ("open", "in-progress", "blocked", "in-review", "closed"),
    "task":        ("pending", "in-progress", "done", "done-with-issues"),
    "decision":    ("proposed", "accepted", "rejected", "superseded", "deprecated"),
    "deliverable": ("draft", "sent", "approved", "rejected"),
    "person":      (),
}
OPEN_STATUSES: dict[EntityType, frozenset[str]]   # ticket: open|in-progress|blocked|in-review; task: pending|in-progress; …
URGENT_STATUSES = frozenset({"blocked"})           # rendered first inside every section

ATTR_KEYS = ("type", "status", "status_raw", "project", "date", "due", "owner",
             "source", "language", "period", "items", "urgent")
# Aliases (brainstorm Q6, FEAT-481 untouched): meeting-source→meeting, meeting_date→date,
#   primary_project→project, issue→ticket, updated_at→date (tickets), due_date→due
TYPE_ALIASES: dict[str, EntityType]; KEY_ALIASES: dict[str, str]

class EntityAttrs(BaseModel):
    """Normalised, validated attrs for one page (what lands in page_attrs)."""
    type: EntityType | None = None
    status: str | None = None          # canonical — only when in STATUS_BY_TYPE[type]
    status_raw: str | None = None      # always kept when the source had a status
    project: str | None = None
    date: str | None = None            # ISO calendar date (YYYY-MM-DD)
    due: str | None = None
    owner: str | None = None           # "human:<user>" | "agent:<id>" | free text from frontmatter
    source: str | None = None          # jira | vault | markdown | memory | entity-cli | inbox | brief
    language: str | None = None
    extra: dict[str, str] = {}         # unknown scalar keys, prefixed "x_" in page_attrs
    def to_rows(self) -> dict[str, str]: ...

def normalize_frontmatter(fm: Mapping[str, Any], *, source: str, strict: bool = False) -> EntityAttrs: ...
def parse_leading_yaml(text: str) -> dict[str, Any] | None: ...   # same delimiter/key rules as repo_scan._markdown_summary

# parrot/knowledge/wiki/standup/models.py (new)
Period = Literal["day", "week", "month"]

class PeriodWindow(BaseModel):
    period: Period; anchor: date; start: date; end: date      # inclusive bounds, computed in StandupConfig.timezone
    recent_start: date; upcoming_end: date                     # day: anchor±horizon; week/month: == start/end
    brief_id: str                                              # brief:daily:YYYY-MM-DD | brief:weekly:YYYY-Www | brief:monthly:YYYY-MM

class BriefItem(BaseModel):
    id: str                       # concept id, qualified for foreign namespaces (issues::file:NAV-10016.md)
    kind: EntityType
    title: str
    status: str | None; status_raw: str | None
    project_hint: str | None      # raw hint; resolved by grouping
    date: date | None; due: date | None
    owner: str | None
    urgent: bool = False
    namespace: str | None = None
    url: str | None = None
    source: str                   # entities | jira | ledger | tasks | decisions | memories
    age_days: int | None = None

class BriefSection(BaseModel):
    key: str                      # blocked | tickets | recent | upcoming | decisions | drafts | tasks | memories
    items: list[BriefItem]

class ProjectSlice(BaseModel):
    project: str; status: str | None; sections: list[BriefSection]; activity: int

class HygieneReport(BaseModel):
    ledger_blockers: int; proposed_decisions_older_than: int; stale_tickets: int
    unmapped_statuses: dict[str, int]; jira_watermark: str | None
    attrs_indexed: int | None; last_lint: str | None; llm: str   # "ok" | "skipped: no model" | "failed: <diag>"

class BriefDocument(BaseModel):
    window: PeriodWindow; identity: "StandupIdentity"; team: bool; language: str
    on_your_plate: list[str]      # ≤3 bullets — LLM paragraph split, or ranked fallback
    projects: list[ProjectSlice]; internal: list[BriefSection]
    delta_new: list[BriefItem]; delta_closed: list[BriefItem]; previous_brief_id: str | None
    sources: list[str]            # week/month: daily brief ids inside the window
    hygiene: HygieneReport
    item_ids: list[str]           # persisted as attrs.items (JSON) — delta source of truth

class BriefProjection(BaseModel):          # the ONLY thing the LLM sees (codex S11)
    period: Period; language: str
    items: list[dict]             # ≤40 × {kind, title[:120], status, project, age_days, urgent}; no bodies, no urls

# parrot/knowledge/wiki/standup/identity.py (new)
class StandupIdentity(BaseModel):
    wiki: str                     # "human:<user>" — from standup.me.wiki or _authoring_identity(None)
    jira_account_id: str | None   # standup.me.jira_account_id → cache → JiraInterface.myself() (G9)
    jira_display_name: str | None # fallback match only
    git_email: str | None         # informational; never written to the plane
    aliases: list[str] = []       # extra assigned_to values treated as "me" (task index)

# parrot/knowledge/wiki/project.py (modifies :382 / :816)
class StandupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_language: Literal["en", "es"] = "en"
    horizon_days: int = Field(default=7, ge=1, le=90)
    timezone: str | None = None            # IANA name; None → system local
    week_start: Literal["monday", "sunday"] = "monday"
    out_dir: str | None = None             # None → ${PARROT_HOME}/wikis/briefs
    me: StandupIdentityConfig = StandupIdentityConfig()
    ticket_status_map: dict[str, str] = DEFAULT_TICKET_STATUS_MAP   # raw Jira name → canonical ticket status
    project_map: dict[str, str] = {}       # Jira key / SDD slug → project page id or label
    stale_ticket_days: int = 10
    stale_decision_days: int = 14
    llm_env: str = "WIKI_LIGHTWEIGHT_MODEL"

DEFAULT_TICKET_STATUS_MAP = {"To Do": "open", "Open": "open", "Backlog": "open",
    "In Progress": "in-progress", "Blocked": "blocked", "In Review": "in-review",
    "Code Review": "in-review", "Done": "closed", "Closed": "closed", "Resolved": "closed"}
```

### New Public Interfaces

```python
# CLI (lazily registered; see M6)
# wikitoolkit standup [--period day|week|month] [--date YYYY-MM-DD] [--horizon N] [--team | --me ID]
#                     [--language en|es] [--json] [--no-llm] [--out DIR] [--no-store] [--no-file]
#                     [--ns NAME] [--path P] [--store DIR] [--backend B]
# wikitoolkit entity add <type> <title> [--project P] [--status S] [--date D] [--due D] [--owner O] [--link ID --rel R] [--by ID] [--json]
# wikitoolkit entity list [--type T] [--status S] [--project P] [--since D] [--until D] [--ns NAME] [--limit N] [--json]
# wikitoolkit entity reindex [--category C] [--dry-run] [--path P] [--store DIR] [--backend B]   # local/--store plane only
# wikitoolkit remember … [--type T] [--project P] [--status S] [--date D] [--due D] [--owner O]   # entity flags (M4)

# Store contract (M1) — BaseWikiStore non-abstract defaults
class BaseWikiStore:
    supports_attrs: bool = False
    async def get_attrs(self, concept_id: str) -> dict[str, str]: ...                       # default {}
    async def list_by_attrs(self, filters: Mapping[str, str | Sequence[str]], *, date_key: str | None = None,
                            since: str | None = None, until: str | None = None,
                            limit: int = 200) -> list[dict[str, Any]]: ...                 # default []
    async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int: ...  # default raises AttrsUnsupportedError

# Ledger (M8)
class LedgerService:
    async def list_issues(self, statuses: Sequence[str] = ("open", "claimed"), *, kind: IssueKind | None = None,
                          about_prefix: str | None = None) -> list[dict[str, Any]]: ...

# Jira (M8)
class JiraInterface:
    async def myself(self) -> JiraPerson: ...   # accountId + displayName only (G9)

# MCP (M7)
# wiki_standup(period="day", date=None, team=False, horizon_days=None, language=None, store=False, write_file=False) -> markdown + summary dict
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: attrs store contract | yes | DDL, same-transaction rule, `supports_attrs` defaults, `_migrate` table check, `stats()["attrs_pages"]` all fixed below | — |
| M2: ingest-boundary extraction | yes | `parse_leading_yaml` rules = `_markdown_summary`'s; `record.attrs` only; no body change | — |
| M3: entity vocabulary | yes | enums, aliases, `normalize_frontmatter` semantics fixed in §2 Data Models | — |
| M4: entity CLI + remember flags | yes | option names, error codes (`E_ENTITY_TYPE`, `E_ENTITY_STATUS`), `reindex` local-only rule | — |
| M5: standup package (collectors/identity/periods/grouping/render/llm/writer/delta) | partly | collectors, periods, writer, delta are mechanical; **render wording + `es` table and the LLM prompt stay with the thinking model** | localisation + prompt wording |
| M6: CLI `standup` + `LazyGroup` + `resolve_optional_llm` + `status` line | yes | signatures fixed; `LazyGroup(import_path, attr)` | — |
| M7: MCP tool + assets + docs + runbook | yes | tool schema fixed (`store=False` default); docs mirror CLI help | — |
| M8: `LedgerService.list_issues` + `JiraInterface.myself` | yes | signatures fixed; G9 invariant test required | — |

### Module 1: Attrs store contract (`page_attrs`)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`, `file_store.py`, `federation.py`
- **Responsibility**: `WikiPageRecord.attrs`; `page_attrs` DDL + index; same-transaction write in `upsert_pages` / `replace_source_slice` (delete rows for the page, insert new ones when `attrs` is non-empty); attrs deleted with the page in `delete_page` / `replace_source_slice`; `_migrate` creates the table on a writable v3 plane that lacks it and records `attrs` support; read-only planes without the table → `supports_attrs = False`; `get_page(...)` includes `"attrs": {...}`; `stats()` gains `attrs_pages`; `InMemoryWikiStore` mirror; `FederatedWikiStore.list_by_attrs` fan-out with `qualify_id`, `_EmptyStore` → `[]`.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # store.py (modifies store.py:409, :525, :93-110, :1370, :2034, :2228)
  class WikiPageRecord(BaseModel):                       # verified: store.py:409
      attrs: dict[str, str] = Field(default_factory=dict)
      """Entity attributes persisted to ``page_attrs`` in the same transaction as the page.
      Keys are vocabulary keys (``type``, ``status``, …) or ``x_<key>`` for pass-through scalars."""

  class AttrsUnsupportedError(RuntimeError):
      """Raised by ``upsert_attrs`` on a store/plane that cannot persist attributes."""

  class BaseWikiStore(ABC):                              # verified: store.py:525
      supports_attrs: bool = False
      async def get_attrs(self, concept_id: str) -> dict[str, str]:
          """Attributes of one page; ``{}`` when none or unsupported."""
      async def list_by_attrs(self, filters: Mapping[str, str | Sequence[str]], *, date_key: str | None = None,
                              since: str | None = None, until: str | None = None,
                              limit: int = 200) -> list[dict[str, Any]]:
          """Page stubs (no bodies) whose attrs match every filter (AND; a sequence value is IN).
          ``date_key``/``since``/``until`` compare ISO dates lexicographically, inclusive. ``[]`` when unsupported."""
      async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int:
          """Write attrs for an existing page; ``replace=False`` merges. Raises AttrsUnsupportedError by default."""

  # DDL added after store.py:110 (`CREATE INDEX IF NOT EXISTS idx_pages_node …`):
  # CREATE TABLE IF NOT EXISTS page_attrs (concept_id TEXT NOT NULL REFERENCES pages(concept_id) ON DELETE CASCADE,
  #     key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (concept_id, key));
  # CREATE INDEX IF NOT EXISTS idx_page_attrs_kv ON page_attrs(key, value);
  class SQLiteWikiStore(BaseWikiStore):                  # verified: store.py:878
      supports_attrs = True   # set False at open time when the table is absent and the plane is read-only
      # upsert_pages / replace_source_slice / delete_page: attrs rows written/deleted inside the SAME `async with self._write()` block
      async def _migrate(self, conn) -> None: ...         # verified: store.py:1370 — adds page_attrs table-presence check
  ```

### Module 2: Ingest-boundary attrs extraction
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py`, `vault_scan.py`
- **Responsibility**: in `build_file_slice`, for markdown/rst documents, parse the leading YAML block with `entities.parse_leading_yaml` (same delimiter/`_YAML_KEY_RE` rules as `_markdown_summary`) and set `record.attrs = normalize_frontmatter(fm, source="markdown").to_rows()`; in `scan_vault`, use `note.frontmatter` with `source="vault"`. Bodies and summaries are unchanged. `_ingest_files` needs no change (attrs ride on the record); the Jira corpus gets attrs through this path when `ingest-jira` builds it (`cli.py:5249`, `build.callback` call).
- **Depends on**: M1, M3.
- **Interface Skeleton**:
  ```python
  # repo_scan.py (modifies repo_scan.py:643 — after `summary = _markdown_summary(content) or rel_path`)
  #   record.attrs = _document_attrs(content)      # new private helper, markdown/rst only
  def _document_attrs(content: str) -> dict[str, str]:
      """Attrs rows from a leading YAML block, or ``{}``. Never raises on bad YAML (logs at DEBUG)."""
  # vault_scan.py (modifies vault_scan.py:163-171 — the WikiPageRecord(...) for a note)
  #   record = WikiPageRecord(..., attrs=normalize_frontmatter(note.frontmatter, source="vault").to_rows())
  ```

### Module 3: Entity vocabulary
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/entities.py` (new)
- **Responsibility**: the §2 Data Models block: `EntityType`, `STATUS_BY_TYPE`, `OPEN_STATUSES`, `URGENT_STATUSES`, `TYPE_ALIASES`, `KEY_ALIASES`, `EntityAttrs`, `normalize_frontmatter`, `parse_leading_yaml`, `canonical_ticket_status(raw, status_map)`. Normalisation rules: keys lower-cased, aliases applied, lists joined (`projects: [a, b]` → `project=a` when `primary_project` absent, `x_projects=a,b`), dates coerced to `YYYY-MM-DD` (datetime → date, `date` objects accepted), `status` kept canonical only if it is in the enum for the resolved `type`, otherwise moved to `status_raw`; `strict=True` (entity CLI) raises `EntityValidationError(code="E_ENTITY_TYPE" | "E_ENTITY_STATUS" | "E_ENTITY_DATE")`. Pure, no I/O, no imports from `cli`/`store` (so the inbox spec and the hook-safe modules can import it).
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # entities.py (new)
  class EntityValidationError(ValueError):
      """Strict-mode normalisation failure; ``code`` ∈ {E_ENTITY_TYPE, E_ENTITY_STATUS, E_ENTITY_DATE}."""
      code: str
  def normalize_frontmatter(fm: Mapping[str, Any], *, source: str, strict: bool = False) -> EntityAttrs:
      """Apply aliases + enums; lenient by default (unknown type → attrs without ``type``)."""
  def parse_leading_yaml(text: str) -> dict[str, Any] | None:
      """Leading ``---`` block as a mapping, or None (no block / no top-level key / YAML error)."""
  def canonical_ticket_status(raw: str | None, status_map: Mapping[str, str]) -> str | None:
      """Case-insensitive lookup; None when unmapped (callers treat as open and count it in Hygiene)."""
  ```

### Module 4: Entity CLI + `remember` entity flags
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` (new), `cli.py` (`remember`)
- **Responsibility**: `entity add` (strict normalisation; page id `entity:<type>:<slug-hash>`, category = type, origin `authored`, `asserted_by` via `_authoring_identity`, body = title + optional `--body`, `--link/--rel` edges like `remember`); `entity list` (local + `--ns` via `list_by_attrs`; table or `--json`); `entity reindex` (iterate `list_pages` of the **writable** plane in pages of 500, `parse_leading_yaml(body)`, `upsert_attrs`; refuses `--ns` with the existing "write to namespace … requires" wording and points at `--store`; `--dry-run` counts only); `remember` gains `--type/--project/--status/--date/--due/--owner` and sets `attrs` on its record (`source="memory"`). All bookkeeper-logged (`ENTITY`, `REINDEX`).
- **Depends on**: M1, M3.
- **Interface Skeleton**:
  ```python
  # entity_cli.py (new) — registered lazily from cli.py (M6)
  @click.group(name="entity")
  def entity() -> None: """Typed entities: add, list and reindex page attributes."""
  @entity.command("add")    # args: type, title; options above; exit 2 + message on EntityValidationError
  @entity.command("list")
  @entity.command("reindex")
  # cli.py (modifies cli.py:3805 `@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")` of `remember`, :3806 signature)
  #   + options --type/--project/--status/--date/--due/--owner; remember(..., type_: str | None, project: str | None, status: str | None, date_: str | None, due: str | None, owner: str | None, ...)
  ```

### Module 5: `standup` package
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/standup/` — `__init__.py`, `models.py`, `config.py` (re-exports `StandupConfig` from `project.py`), `identity.py`, `periods.py`, `collectors/{entities,jira,ledger,tasks,decisions,memories}.py`, `grouping.py`, `render.py`, `llm.py`, `delta.py`, `writer.py`, `pipeline.py`
- **Responsibility**: see §2 Overview. Specifics decided here:
  - `periods.window(period, anchor, cfg, *, now=None)`: dates in `cfg.timezone` (IANA via `zoneinfo`; `None` → local); day → `[anchor-h, anchor+h]`; week → ISO week per `week_start`; month → calendar month; inclusive; `brief_id` per §2.
  - Collectors are `async def collect(ctx: CollectContext) -> list[BriefItem]`; each catches its own I/O errors into `ctx.diagnostics` and returns `[]` (a missing ledger root, unregistered `issues` namespace or unreachable plane never fails the brief). Entities collector: `list_by_attrs({"type": [...]})` per window; when `supports_attrs` is false for a plane, fallback = `list_pages(category in document|entity…)` + `parse_leading_yaml(body)` with a one-line diagnostic. Jira collector: `type=ticket, source in (markdown, jira)` from the `issues` namespace, canonical status via `canonical_ticket_status`, personal filter on `assignee_id` (then display name), unmapped raw statuses counted. Ledger: `LedgerService.list_issues(("open","claimed"))` + `merge_blockers` per in-progress feature id; `blocked` ⇔ severity critical & unacknowledged. Tasks: `sdd/tasks/index/*.json` (skip `_orphans.json`), `status == "in-progress"` (plus `pending` whose `depends_on` are all done, flagged `ready`), personal filter on `assigned_to ∈ {identity.wiki, *aliases}`. Decisions: `inventory()` filtered (`proposed`, or inferred & `unreviewed`), age from the ADR page `updated_at` (`list_pages(category=ADR_CATEGORY)`). Memories: `list_pages(origin=["memory","authored"])`, `updated_at` in window, personal filter on `asserted_by`; `category == "brief"` excluded.
  - `grouping.resolve_project(item, ctx)`: `project` attr → page with `type=project` (by id, then by title slug) → `cfg.project_map` → Jira `project` key → task-index `feature` slug → `Internal`; projects ordered by `activity` desc; inside each section `urgent` first, then due/date asc.
  - `render.render_markdown(doc, language)`: static heading table (`en`, `es`); item line = `- **<label>:** <link or qualified id> (<status> — <age>)`; empty projects omitted; roll-up (`week`/`month`) replaces "On your plate today"/"Upcoming" with "Closed this period" / "Still open" / "Decisions taken" and lists `doc.sources`.
  - `llm.summarize(projection, *, language, adapter) -> list[str] | None`: at most 3 bullets, `temperature=0`, 20 s timeout; any failure → `None` + diagnostic; prompt forbids adding facts not in the projection.
  - `delta.diff(current_ids, previous_page)`: previous = latest `brief:<period>:*` page with `attrs.period == period` and id < current; `items` attr is the JSON id list (source of truth); new/closed sets.
  - `writer.write(doc, *, store, cfg, out_dir, write_page, write_file)`: page `WikiPageRecord(concept_id=brief_id, category="brief", origin="authored", asserted_by=identity.wiki, attrs={type: deliverable, status: draft, date, owner, period, items, source: brief, language})` upserted **inside `wiki_write_lock(storage_dir)`**; file `<out>/<brief-slug>.md` written to `<file>.tmp` then `os.replace`; a `wiki_sync`/`wiki_scope`/`wiki_id` frontmatter when `<out>` is inside a configured `obsidian_sync.vault_dir`; bookkeeper `STANDUP`.
  - `pipeline.run(opts) -> BriefDocument`: the orchestration used by CLI and MCP.
- **Depends on**: M1, M3, M8; `project.py` (`StandupConfig`, `wiki_write_lock`, `parrot_home`, `load_effective_config`), `federation.resolve_namespaces`, `context.qualify_id`.
- **Interface Skeleton**:
  ```python
  # standup/pipeline.py (new)
  class StandupOptions(BaseModel):
      period: Period = "day"; anchor: date | None = None; horizon_days: int | None = None
      team: bool = False; me: str | None = None; language: Literal["en","es"] | None = None
      use_llm: bool = True; write_page: bool = True; write_file: bool = True; out_dir: Path | None = None
      namespaces: str | None = None; now: datetime | None = None   # injectable clock (tests)
  async def run(root: Path, options: StandupOptions, *, store: BaseWikiStore | None = None,
                effective: WikiEffectiveConfig | None = None) -> BriefDocument:
      """Collect → group → render → (llm) → delta → write. Never raises for a missing source; diagnostics land in Hygiene."""
  # standup/identity.py
  async def resolve_identity(cfg: StandupConfig, *, explicit: str | None = None, root: Path) -> StandupIdentity:
      """standup.me → explicit --me → _authoring_identity(None) (verified: cli.py:3513); Jira account id from
      cfg.me.jira_account_id → ${PARROT_HOME}/jira_identity.json → JiraInterface.myself() when JIRA_* is configured."""
  # standup/periods.py
  def window(period: Period, anchor: date, cfg: StandupConfig) -> PeriodWindow: ...
  # standup/render.py
  HEADINGS: dict[str, dict[str, str]]     # {"en": {...}, "es": {...}} — keys fixed: title, plate, by_project, internal, since, hygiene, …
  def render_markdown(doc: BriefDocument, language: str) -> str: ...
  # standup/llm.py
  async def summarize(projection: BriefProjection, *, language: str, adapter: PageIndexLLMAdapter,
                      timeout_s: float = 20.0) -> list[str] | None: ...
  # standup/writer.py
  async def write(doc: BriefDocument, rendered: str, *, store: BaseWikiStore, storage_dir: Path,
                  out_dir: Path, write_page: bool, write_file: bool, vault_dir: Path | None) -> WriteResult: ...
  ```

### Module 6: CLI wiring — `standup` group, `LazyGroup`, `resolve_optional_llm`, `status` line
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py`, `cli.py`, `standup/cli.py` (new)
- **Responsibility**: `LazyGroup(import_path: str, attr: str)` generalising `LazyAdrGroup` (kept as `class LazyAdrGroup(LazyGroup)` with the hardcoded path, so no caller changes); register `standup` and `entity` next to `adr` (`cli.py:2347-2352`); `standup/cli.py` defines the `standup` command (options in §2 New Public Interfaces; `--period` accepts `day|week|month`; `--json` dumps `BriefDocument`; exit 0 even when the LLM is skipped/failed; exit 1 only on store open failure). `resolve_optional_llm(env_names: Sequence[str], *, purpose: str) -> PageIndexLLMAdapter | None` in a new light module `wiki/llm_resolve.py` reproducing the inline pattern at `cli.py:3728` / `:4908-4925` (env via `_env_setting`, auto-detect via `detect_coding_agent_llm` unless `PARROT_NO_AUTO_LLM`, `LLMFactory.create`), used by `standup` (and offered to the two existing sites without changing their behaviour — follow-up). `status` prints `Attrs     : <N> pages indexed` (or `unsupported`).
- **Depends on**: M4, M5.
- **Interface Skeleton**:
  ```python
  # lazy_commands.py (modifies lazy_commands.py:21)
  class LazyGroup(click.Group):
      """Defer ``import_path`` until a subcommand is resolved (FEAT-584 hook budget)."""
      def __init__(self, *args: object, import_path: str, attr: str, **kwargs: object) -> None: ...
  class LazyAdrGroup(LazyGroup):
      """Backwards-compatible alias bound to ``parrot.knowledge.wiki.decisions.cli:adr``."""
  # cli.py (modifies cli.py:2347-2352)
  #   wiki.add_command(LazyGroup(name="standup", import_path="parrot.knowledge.wiki.standup.cli", attr="standup", help="…"))
  #   wiki.add_command(LazyGroup(name="entity",  import_path="parrot.knowledge.wiki.entity_cli",  attr="entity",  help="…"))
  # llm_resolve.py (new, light: imports nothing from cli/store at module load)
  def resolve_optional_llm(env_names: Sequence[str], *, purpose: str, logger: logging.Logger) -> PageIndexLLMAdapter | None: ...
  ```

### Module 7: MCP tool, managed assets, docs
- **Path**: `wiki/tools.py`, `wiki/claude_code/assets.py`, `.claude/commands/parrotwiki.md`, `wiki/codex/assets.py`, `wiki/google/assets.py`, `docs/wiki/cheatsheet.md`, `docs/guides/llm-wiki-guide.md`, `docs/runbooks/wiki-standup.md` (new)
- **Responsibility**: `WikiStandupTool` (`name="wiki_standup"`, `args_schema=WikiStandupInput`; **`store=False` and `write_file=False` by default**; when true, writes go to the local plane only — the tool is constructed with `root` + `config` like `VaultIngestTool` and runs `pipeline.run`; result = markdown + `{brief_id, written_page, written_file, diagnostics}`); registered in `create_wiki_tools` after `WikiStatusTool` (`tools.py:836`), count-sensitive tests updated (`test_mcp_server*.py`). Assets: `argument-hint` + bullets for `standup` and `entity` in `SLASH_COMMAND_MD` and the checked-in `parrotwiki.md` **in the same task**; one sentence in the Codex/Gemini skills. Docs: cheatsheet section before `## 12.`, guide section before `## Obsidian Vaults as Wiki Sources`, runbook with the cron line and the `entity reindex --store` back-fill recipe.
- **Depends on**: M5, M6.
- **Interface Skeleton**:
  ```python
  # tools.py (modifies tools.py:836-837 `WikiStatusTool(store), ]`)
  class WikiStandupInput(BaseModel):
      period: Literal["day","week","month"] = "day"; date: str | None = None; team: bool = False
      horizon_days: int | None = None; language: Literal["en","es"] | None = None
      store: bool = False; write_file: bool = False; use_llm: bool = False
  class WikiStandupTool(AbstractTool):                   # pattern verified: tools.py:514 (WikiStatusTool), :531 (VaultIngestTool ctor)
      name = "wiki_standup"; args_schema = WikiStandupInput
      def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None: ...
      async def _execute(self, **kwargs) -> ToolResult:
          """Render the brief; writes only when ``store``/``write_file`` are true (local plane, never a namespace)."""
  ```

### Module 8: Native-API seams — `LedgerService.list_issues`, `JiraInterface.myself`
- **Path**: `wiki/ledger/service.py`, `parrot/interfaces/jira/client.py`
- **Responsibility**: `list_issues(statuses, kind, about_prefix)` built on `_all_issues` + `_issue_dict` (same shape as `ready_work`, plus `claimed_by`), sorted by `SEVERITY_ORDER`; `myself()` wraps the existing `/myself` probe path and returns `JiraPerson(account_id, display_name)` via `parse._person` — **never** a raw dict, so `emailAddress` cannot leak (G9); the identity cache file holds only `account_id` + `display_name` + `resolved_at`.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # ledger/service.py (modifies: insert after ledger/service.py:215 `ready_work` body)
  async def list_issues(self, statuses: Sequence[str] = ("open", "claimed"), *, kind: IssueKind | None = None,
                        about_prefix: str | None = None) -> list[dict[str, Any]]:
      """Issues whose status ∈ ``statuses`` (default open+claimed), optional kind / ``about`` path-prefix filters."""
  # parrot/interfaces/jira/client.py (modifies: insert after client.py:484 `_probe_myself`)
  async def myself(self) -> JiraPerson:
      """Current user as a G9-safe ``JiraPerson`` (accountId + displayName from ``/myself``). Raises JiraAuthError."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_attrs_written_same_transaction` | M1 | `upsert_pages` with attrs → rows present; a forced failure after the page insert leaves no attrs (rollback) |
| `test_attrs_deleted_with_page` | M1 | `delete_page` / `replace_source_slice` remove attrs of dropped pages; replaced page gets the new set |
| `test_list_by_attrs_filters_and_dates` | M1 | AND filters, IN lists, inclusive `since`/`until` on `date_key` |
| `test_v3_plane_without_attrs_writable_migrates` | M1 | pre-feature v3 SQLite opens writable → table created, `supports_attrs` true (codex S2) |
| `test_v3_plane_without_attrs_readonly_unsupported` | M1 | same plane read-only → `supports_attrs` false, `list_by_attrs` `[]`, no error |
| `test_inmemory_attrs_parity` | M1 | `InMemoryWikiStore` passes the same contract tests |
| `test_arango_postgres_defaults_unsupported` | M1 | `supports_attrs` false; `upsert_attrs` raises `AttrsUnsupportedError` (no network) |
| `test_federated_list_by_attrs_qualifies_ids` | M1 | foreign handle results come back as `ns::id`; unsupported handle skipped with a skip record |
| `test_markdown_slice_attrs_from_frontmatter` | M2 | document with YAML block → `record.attrs`; body/summary unchanged; no block → `{}` |
| `test_vault_note_attrs_feat481_aliases` | M2+M3 | `type: meeting-source`, `meeting_date`, `primary_project`, `projects` → `meeting`, `date`, `project`, `x_projects` |
| `test_jira_issue_document_attrs` | M2+M3 | a `render_issue_document` output ingested through `build_file_slice` → `type=ticket`, `status_raw`, `date=updated_at`, `project`, `x_assignee_id`; no email key anywhere (G9) |
| `test_normalize_status_enum_and_raw` | M3 | canonical kept only when in the type's enum; otherwise `status_raw` only |
| `test_normalize_strict_errors` | M3 | `E_ENTITY_TYPE` / `E_ENTITY_STATUS` / `E_ENTITY_DATE` codes |
| `test_canonical_ticket_status_map` | M3 | default map, case-insensitive, unmapped → None |
| `test_entity_add_list_roundtrip` | M4 | CLI add → list by type/status/project; `--json` shape |
| `test_entity_reindex_backfills_and_refuses_ns` | M4 | pages with YAML bodies and empty attrs → filled; `--ns issues` refused with the `--store` hint; `--dry-run` writes nothing |
| `test_remember_entity_flags` | M4 | `remember --type decision --status proposed --project X` → attrs on the memory page |
| `test_periods_day_week_month` | M5 | inclusive bounds, ISO week with `week_start`, month edges, timezone from config, `brief_id` values |
| `test_collector_entities_window_and_fallback` | M5 | attrs path vs body-parse fallback when `supports_attrs` false; diagnostics recorded |
| `test_collector_jira_identity_g9` | M5 | personal filter on `assignee_id`, display-name fallback; unmapped statuses counted in Hygiene |
| `test_collector_ledger_tasks_decisions_memories` | M5 | each native source mapped to `BriefItem`; missing ledger root / index dir → `[]` + diagnostic |
| `test_grouping_resolution_chain` | M5 | project attr → project page → `project_map` → Jira key → SDD slug → Internal; ordering by activity, urgent first |
| `test_render_en_es_golden` | M5 | golden markdown for both languages; empty projects omitted; roll-up sections for week/month |
| `test_llm_projection_bounded_and_failsafe` | M5 | ≤40 items, titles ≤120 chars, no bodies; adapter raising/timeout → fallback bullets, brief still written |
| `test_delta_against_previous_brief` | M5 | new/closed computed from the stored `items` attr; first run → no delta section |
| `test_writer_lock_and_atomic_file` | M5 | page written under `wiki_write_lock`; file replaced via tmp + `os.replace`; vault markers only inside `vault_dir` |
| `test_standup_cli_matrix` | M6 | `--period`, `--json`, `--no-llm`, `--no-store`, `--out`, `--language es`, exit codes |
| `test_lazy_group_defers_import` | M6 | `wiki --help` never imports `standup`/`entity_cli`/`decisions.cli` (sys.modules assertion); subcommand resolution does |
| `test_hook_import_path_unchanged` | M6 | the `claude-hook` import set (existing timing test in `tests/knowledge/wiki/test_claude_code.py`) contains no `entities`/`standup` module (codex S7) |
| `test_status_attrs_line` | M6 | `Attrs     : N pages indexed` / `unsupported` |
| `test_wiki_standup_tool_readonly_default` | M7 | `store=False` writes nothing; `store=True` writes the local plane only; tool count tests updated |
| `test_assets_document_standup` | M7 | `SLASH_COMMAND_MD` and `.claude/commands/parrotwiki.md` both mention `standup` and `entity` |
| `test_ledger_list_issues` | M8 | open+claimed returned, closed excluded, kind/about filters, severity order |
| `test_jira_myself_g9` | M8 | raw `/myself` payload with `emailAddress` → `JiraPerson` dump contains no email; cache file has no email |

### Integration Tests
| Test | Description |
|---|---|
| `test_standup_end_to_end_sqlite` | fixture plane (vault notes with FEAT-481 frontmatter + Jira-rendered documents + memories) + fixture ledger root + task index + ADR page → `wikitoolkit standup --no-llm` renders all sections, stores `brief:daily:<date>` with `items`, writes the file; second run on the next day shows the delta |
| `test_standup_rollup_week` | daily briefs stored for 3 days → `--period week` lists them as sources and renders roll-up sections |
| `test_build_unaffected_without_frontmatter` | `build` over a code repo produces identical pages/edges (attrs empty) — `tests/knowledge/wiki/test_cli.py` parity |
| `test_ingest_jira_plane_has_ticket_attrs` | `ingest-jira --dry-run`-style fixture → built plane answers `list_by_attrs({"type":"ticket"})` |

### Test Data / Fixtures
```python
# tests/knowledge/wiki/standup/conftest.py
@pytest.fixture
def entity_plane(tmp_path, wiki_config) -> SQLiteWikiStore: ...     # pages with attrs across all 8 types + a brief
@pytest.fixture
def v3_plane_without_attrs(tmp_path) -> Path: ...                     # copied from tests/knowledge/wiki/test_store_migration_v2.py helpers
@pytest.fixture
def standup_root(tmp_path, isolated_parrot_home) -> Path: ...        # .parrot/wiki.json with standup config, ledger root, sdd/tasks/index/*.json
@pytest.fixture
def fake_adapter() -> PageIndexLLMAdapter: ...                        # canned / raising ask()
@pytest.fixture
def frozen_now() -> datetime: ...                                     # injected clock
```
Locations: `tests/knowledge/wiki/test_entities.py`, `test_store_attrs.py`,
`test_entity_cli.py`, `tests/knowledge/wiki/standup/test_*.py`; CLI cases
extend `tests/knowledge/wiki/test_cli.py`; Jira/G9 cases live next to
`packages/ai-parrot/tests/knowledge/wiki/test_jira_render.py`.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 — `page_attrs` exists in every SQLite plane written by this code; `SCHEMA_VERSION` is still `"3"`; a pre-feature v3 plane opens writable (table added) and read-only (`supports_attrs=False`, no error).
- [ ] AC2 — Attrs are written in the same transaction as the page and removed with it; no orphan rows after `replace_source_slice` / `delete_page` (tests above).
- [ ] AC3 — `entities.py` is the single vocabulary: `EntityType` includes `task`; per-type canonical status enums; FEAT-481 aliases; `normalize_frontmatter` is pure and import-light; the inbox spec imports it (no second taxonomy module).
- [ ] AC4 — Markdown documents (incl. the Jira corpus built by `ingest-jira`) and vault notes get attrs at ingest; bodies, summaries and edges are byte-identical to today; `jira_render.py` is unchanged.
- [ ] AC5 — `wikitoolkit entity add|list|reindex` and `remember --type/--project/--status/--date/--due/--owner` work as specified; `reindex` refuses foreign namespaces and supports `--store`.
- [ ] AC6 — `wikitoolkit standup` renders the sketch's sections for `--period day`, and the roll-up sections for `week`/`month`; empty projects omitted; blocked/urgent first; `--json` dumps `BriefDocument`.
- [ ] AC7 — Personal mode filters tickets by `assignee_id` (display-name fallback), tasks by `assigned_to`, memories/decisions by `asserted_by`; `--team` disables the filters; **no email is read from or written to any plane or cache (G9 grep over fixtures and cache).**
- [ ] AC8 — Without a configured model the brief renders and persists with ranked bullets; with a model, the paragraph is produced from a projection of ≤40 items / ≤120-char titles and any failure degrades to the same fallback with a Hygiene diagnostic; exit code 0 in both cases.
- [ ] AC9 — Brief page `brief:<period>:<id>` (category `brief`, origin `authored`, attrs incl. `items`) is written under `wiki_write_lock`; the markdown file lands in `${PARROT_HOME}/wikis/briefs/` by default (atomic replace), `--out` overrides, vault markers only inside `obsidian_sync.vault_dir`.
- [ ] AC10 — "Since last brief" lists new/closed items against the previous brief of the same period; first run omits the section.
- [ ] AC11 — Hygiene reports ledger blockers, proposed decisions older than `stale_decision_days`, tickets untouched > `stale_ticket_days`, unmapped Jira statuses, Jira watermark age, attrs index size, and FEAT-625 `lint/report.json` timestamp when present.
- [ ] AC12 — `--language es` and `standup.default_language` switch headings only; titles verbatim.
- [ ] AC13 — `standup`, `entity` and `adr` are lazily registered through `LazyGroup`; `wiki --help` and the `claude-hook` path import none of `entities`, `standup`, `entity_cli`, `decisions.cli` (sys.modules test).
- [ ] AC14 — `wiki_standup` MCP tool is read-only by default; `store=true` writes only the local plane; `/parrotwiki standup` documented in the managed asset and the checked-in command file.
- [ ] AC15 — `StandupConfig` is accepted by both `WikiProjectConfig` and `WikiEnvOverlay` (`extra="forbid"` honoured) with validated `default_language`, `timezone`, `week_start`, `ticket_status_map`.
- [ ] AC16 — `LedgerService.list_issues` and `JiraInterface.myself` exist with the stated signatures and tests.
- [ ] AC17 — Docs: cheatsheet, guide and `docs/runbooks/wiki-standup.md` (cron + back-fill recipe) updated.
- [ ] AC18 — `pytest tests/knowledge/wiki/ -q` (new + existing wiki suites) and `packages/ai-parrot/tests/knowledge/wiki/` pass; no breaking change to `BaseWikiStore`'s abstract surface (new methods are non-abstract).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` @ `7b4473649` (2026-10-03) by direct read; the brainstorm's
> anchors (verified @ `f289e5a7e` the same day) were re-checked — no code under
> `packages/` changed between the two commits. Paths below are relative to
> `packages/ai-parrot/src/parrot/knowledge/wiki/` unless stated otherwise.
> Implementation agents MUST NOT reference imports, attributes, or methods not
> listed here without first verifying they exist via `wikitoolkit query` / `grep` / `read`.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord, SCHEMA_VERSION, estimate_tokens  # store.py:50,409,525,878
from parrot.knowledge.wiki.file_store import InMemoryWikiStore                      # file_store.py:73
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore                    # arango_store.py:135
from parrot.knowledge.wiki.postgres_store import PostgresWikiStore                  # postgres_store.py:127
from parrot.knowledge.wiki.models import WikiConfig, WikiPageCategory               # models.py:52,25
from parrot.knowledge.wiki.project import (WikiProjectConfig, WikiEnvOverlay, WikiEffectiveConfig, ObsidianSyncConfig,
    load_effective_config, load_project_config, parrot_home, find_shared_root, wiki_write_lock,
    load_global_registry, merge_namespaces)                                         # project.py:382,816,878,283,933,772,1045,1220,74,1065,1122
from parrot.knowledge.wiki.federation import FederatedWikiStore, resolve_namespaces, NamespaceHandle, NamespaceSkip  # federation.py:622,461,96,78
from parrot.knowledge.wiki.context import qualify_id, DEFAULT_BUDGET_TOKENS, pack_results   # context.py:83; tools.py:19
from parrot.knowledge.wiki.lazy_commands import LazyAdrGroup                        # lazy_commands.py:21
from parrot.knowledge.wiki.repo_scan import build_file_slice, FileSlice, RepoScan, file_concept_id, _markdown_summary  # repo_scan.py:572,148,190,263,524
from parrot.knowledge.wiki.vault_scan import scan_vault, is_obsidian_vault          # vault_scan.py:118,62
from parrot.knowledge.wiki.jira_render import IssueFrontmatter, render_issue_document, SYNC_MARKER   # jira_render.py:116,497,39
from parrot.knowledge.wiki.jira_sync import resolve_issues_dir, load_sync_state     # jira_sync.py:152,176
from parrot.knowledge.wiki.ledger.service import LedgerService                      # ledger/service.py:98
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, IssueStatus, SEVERITY_ORDER   # ledger/events.py:22-26
from parrot.knowledge.wiki.ledger.sdd_meta import KNOWN_PROJECTS                    # ledger/sdd_meta.py:45
from parrot.knowledge.wiki.decisions.models import DecisionRecord, DecisionConfig, ADR_CATEGORY   # decisions/models.py:143,62,40
from parrot.knowledge.wiki.decisions.repository import DecisionRepository           # decisions/repository.py:26
from parrot.knowledge.wiki.tools import create_wiki_tools, WikiStatusTool, VaultIngestTool   # tools.py:807,514,531
from parrot.knowledge.wiki.obsidian_sync import render_note, sync_obsidian, SYNC_MARKER_KEY, SYNC_SCOPE_KEY, SYNC_ID_KEY  # obsidian_sync.py:183,399,65,72,75
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper                         # bookkeeper.py (log_operation :175)
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter              # ../pageindex/llm_adapter.py:42
from parrot.interfaces.jira import JiraInterface, JiraPerson                        # jira_sync.py:38 (re-export); models.py:21
from parrot.interfaces.jira.parse import _person                                    # parse.py:47 (G9 projection helper)
from parrot.interfaces.obsidian.parser import ObsidianNoteParser                    # vault_scan.py:35
from parrot.clients.detection import detect_coding_agent_llm                        # clients/detection.py:19 (used at cli.py:4908-4925)
from parrot.tools.abstract import AbstractTool, ToolResult                          # tools.py:24
```

### Existing Class Signatures
```python
# store.py
SCHEMA_VERSION = "3"                                                   # :50
# pages DDL :93-107 (concept_id PK, node_id, title, category DEFAULT 'concept', summary, body, source_id,
#   token_count, created_at, updated_at, origin DEFAULT 'ingest', asserted_by, content_hash); indexes :108-110
# edges(src, dst, rel, provenance) :112; pages_fts fts5(title, summary, body) :173
_MIGRATION_COLUMNS = ...                                               # :229 (used at :1357)
class WikiPageRecord(BaseModel):                                       # :409 — fields :444-… (concept_id, node_id, title, category, summary, body,
                                                                       #   source_id, token_count, origin, asserted_by, updated_at, content_hash); NO attrs yet
class BaseWikiStore(ABC):                                              # :525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int                              # abstract
    async def replace_source_slice(self, source_id, pages, edges=None)                            # abstract
    async def delete_page(self, concept_id: str) -> bool                                          # abstract
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict]        # :565
    async def list_pages(self, category: Optional[str] = None, limit: int = 100,
                         origin: Optional[list[str]] = None) -> list[dict[str, Any]]              # :568-573
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10)       # :576
    async def stats(self) -> dict[str, Any]                                                        # :596
class SQLiteWikiStore(BaseWikiStore):                                  # :878
    async def list_pages(...)                                          # :2034
    async def stats(self)                                              # :2228
    async def _migrate(self, conn) -> None                             # :1370 (version check :1367, _migrate_fts :1418)
# file_store.py
class InMemoryWikiStore(BaseWikiStore):                                # :73 — upsert_pages :377, replace_source_slice :503, delete_page :539, get_page :575, list_pages :589, stats :716
# arango_store.py / postgres_store.py
class ArangoDBWikiStore(BaseWikiStore)                                 # :135 — list_pages :917, stats :1101
class PostgresWikiStore(BaseWikiStore)                                 # :127 — list_pages :603, stats :812
# federation.py
class NamespaceSkip(BaseModel)                                         # :78
class NamespaceHandle                                                  # :96
async def resolve_namespaces(root, config, *, only=None, registry_path=None, read_only=True, arango_timeout=…)  # :461
class FederatedWikiStore(BaseWikiStore):                               # :622 — scoped :712, search_fts :935, list_pages :950, get_page :960, add_edges :1357 (local source only), foreign write guard :1280
class _EmptyStore(BaseWikiStore)                                       # :1576 — list_pages :1612
# repo_scan.py
class FileSlice(BaseModel): rel_path: str; record: WikiPageRecord; imports; language; symbols; refs; external_edges   # :148 (fields :181-187)
def _frontmatter_lead(block: list[str]) -> str                         # :117 (delimiter const :102, _YAML_KEY_RE :108)
def _markdown_summary(content: str) -> str                             # :524 — recognises the leading YAML block; summary from `summary`/`title`
def build_file_slice(root: Path, rel_path: str, body_max_chars=…, max_file_bytes=…, symbol_depth=2) -> FileSlice | None   # :572; markdown branch `summary = _markdown_summary(content) or rel_path` :643
def file_concept_id(rel_path: str) -> str                              # :263
# vault_scan.py
def _note_summary(note: ObsidianNote) -> str                           # :90 (reads note.frontmatter summary/description only)
def _note_body(note: ObsidianNote, body_max_chars: int) -> str         # :103
def scan_vault(root: Path, body_max_chars=…, max_file_bytes=…) -> tuple[RepoScan, VaultScanStats]   # :118; record = WikiPageRecord(...) :163; scan.files.append(FileSlice(rel_path=rel, record=record)) :171
# cli.py (5491 lines)
# group :1437; main :5457; commands: build 1472/1510, upsert 1788, query 1928/1955, page 2014/2026, status 2144/2148,
#   export 3471/3480, remember 3776/3806, note 3946/3954, link 4024/4033, memories 4084/4090, audit 4115,
#   ingest 4701/4794, ingest-jira 5168/5249 (builds via `build.callback(` when do_build), claude-hook 5442
# groups: symbols 2355, ns 2563, ledger 2849, schema 3212, sync 4242; adr registered at :2345-2352 via LazyAdrGroup
# module-level imports of ledger (LedgerService :108, fix_planner :109, events :110) — pre-existing hook cost (codex S7)
def _declared_namespaces(config) :153 · _selected_namespaces(ns_opt) :171 · _federate(root, config, local, ns_opt) :194
def _echo_skips(...) :338 · _open_store(root, config) :464 · _run(coro) :560 · _env_setting(name) -> str | None :565
def _resolve_read_store(...) :583 · _authoring_identity(by: str | None) -> str :3513 · _resolve_write_store(...) :3546
def _extract_into_graph(...) :3709 (skip-if-unconfigured at :3728) · _build_triage_adapters(lightweight_model, model) :4477 (env at :4908-4925)
async def _ingest_files(store, sources, root, scan, force=False) -> dict[str, int]   # :749; bulk `await store.upsert_pages(bulk_records)` :879
def remember(text, path_, store_opt, backend_opt, title, category, links, rel, ns_opt, source_uri, by, extract_, as_json) -> None   # :3806
#   last option before def: `@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")` :3805 (11 occurrences in file)
#   memory record built with origin="memory", asserted_by=… :3858-3866
def memories(...)  # :4090 — store.list_pages(category=category, limit=limit, origin=["memory", "authored"]) :4100
def status(path_, ns_opt, as_json) -> None   # :2148 — prints `Env       : …` etc.
# lazy_commands.py
class LazyAdrGroup(click.Group): _real_group cache; _load_real_group (imports decisions.cli.adr); get_command; list_commands   # :21-47
# jira_render.py
SYNC_MARKER :39; class IssueFrontmatter(BaseModel) :116 (type=ConceptType.ISSUE, key, title, status, resolution, category, project, priority,
#   assignee, assignee_id :133-134, reporter, reporter_id, created_at, updated_at, resolved_at, labels, components, epic, parent, …, url, sync)
def _render_frontmatter(...) :310; def render_issue_document(issue, *, fetched_at, existing=None, repo_pages=None) -> str :497
# jira_sync.py — resolve_issues_dir :152 (default parrot_home()/"wikis"/"issues"); load_sync_state(issues_dir) :176; imports JiraInterface, JiraPerson :38; wiki_write_lock :50
# parrot/interfaces/jira/models.py — class JiraPerson(BaseModel): account_id: str; display_name: str  :21-25  ("NO email field — G9", module docstring :1-13)
# parrot/interfaces/jira/parse.py — def _person(raw_user) -> JiraPerson | None :47 (reads accountId/displayName only, G9)
# parrot/interfaces/jira/client.py — class JiraInterface; _probe_auth_sync(self) -> dict :376 (raw /myself probe); async _probe_myself(self) -> dict :460; verify_auth :485; search_issues :531
# ledger/service.py
class LedgerService: __init__(index, store, log, shared_root) :98; from_root(root=None) :116; _all_issues() :152 (private);
#   open_issue :168; ready_work(kind=None) :201 (open only, SEVERITY_ORDER); get_context :289; merge_blockers(feature_id) :322; "# Public API (spec §2)" comment :165
# _issue_dict :80 → issue_id, title, status, kind, severity, acknowledged, discovered_from, about, claimed_by, closed_by, closed_reason, resolved_by (no timestamps)
# ledger/events.py — IssueKind :22, IssueSeverity :23, IssueStatus = open|claimed|closed|superseded :24, SEVERITY_ORDER :26
# ledger/sdd_ingest.py — SDDGraphIngest(store, shared_root) :51; _process_task_index_file :231 (json.load :241); task pages `task:<id>` category "task" origin "sdd-task" :255-292 (status is body text only)
# sdd/tasks/index/<slug>.json keys: base_branch, completed_at, created_at, feature, feature_id, spec, tasks[], type;
#   tasks[]: assigned_to, completed_at, depends_on, effort, feature, feature_id, file, id, parallel, parallelism_notes, priority, slug, spec, started_at, status, title
# decisions/models.py — class DecisionRecord :143 (source_status :153, origin, review_status, …; NO timestamps); DecisionConfig :62; ADR_CATEGORY = "adr" :40
# decisions/repository.py — DecisionRepository(store, max_records=10_000) :26; async inventory() -> list[DecisionRecord] :63
# project.py
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]   # :74 (context manager)
class ObsidianSyncConfig(BaseModel) :283 · class WikiProjectConfig(BaseModel) :382 (vault_dir :443, namespaces :451, obsidian_sync :458, symbol_depth :465, decisions :483; extra="forbid")
class WikiEnvOverlay(BaseModel) :816 (namespaces :856, vault_dir :857, obsidian_sync :858, sync_graph :859, …, claude :864; extra="forbid")
class WikiEffectiveConfig(BaseModel) :878 · load_project_config :772 · load_effective_config(root, env=None) :933 · parrot_home() :1045 · find_shared_root :1220
# tools.py — imports :10-24; WikiQueryTool :225; WikiRememberTool :336; WikiStatusTool :514 (__init__(store) :521, _execute() :525); VaultIngestTool(store, root, config) :531-545;
#   create_wiki_tools(store, ..., ledger_service=None) :807 — list ends `WikiStatusTool(store), ]` :836-837; ledger block `if ledger_service is not None:` :840
# mcp_server.py — create_wiki_mcp_server(root) -> StdioMCPServer :91; ledger overlay :160-198; server.register_tools(tools) :307
# claude_code/assets.py — SLASH_COMMAND_FILENAME :71; CLAUDE_MD_SECTION :221; SLASH_COMMAND_MD :307; argument-hint :309; bullets :321-345 (`audit` bullet :340)
# .claude/commands/parrotwiki.md — checked-in copy; `audit` bullet :34
# obsidian_sync.py — SYNC_MARKER_KEY :65, SYNC_SCOPE_KEY :72, SYNC_ID_KEY :75; project_scope :91; folder_for_category :147; note_relpath :160; render_note :183; sync_obsidian :399
# export.py — page_frontmatter :86; export_okf_bundle :125
# bookkeeper.py — log_operation(self, wiki_dir, operation, details, timestamp=None) :175 (free-string op)
# ../pageindex/llm_adapter.py — PageIndexLLMAdapter.__init__(client, model="gemini-3.1-flash-lite-preview", max_retries=3, retry_delay=1.0) :49; ask :61; ask_structured :99
# tests — tests/knowledge/wiki/conftest.py: isolated_parrot_home (autouse) :41, wiki_config(tmp_path) :59; CliRunner pattern tests/knowledge/wiki/test_cli.py:18,61
#   hook tests: tests/knowledge/wiki/test_claude_code.py; migration tests: tests/knowledge/wiki/test_store_migration_v2.py; backend meta: packages/ai-parrot/tests/knowledge/wiki/test_store_meta_backends.py
# docs — docs/wiki/cheatsheet.md `## 12. Exportar el wiki como markdown` :489; docs/guides/llm-wiki-guide.md `## Obsidian Vaults as Wiki Sources` :921; runbook precedent docs/runbooks/jira-issues-namespace.md
# FEAT-625 (sibling, approved): `wikitoolkit lint` writes `<storage_dir>/lint/report.json` + `report.md` (sdd/specs/wikitoolkit-lint.spec.md:437)
# FEAT-481 (sibling, in progress): vault `MeetingSourceFrontmatter` type="meeting-source", meeting_date, primary_project ∈ projects (sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md:198-212)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `WikiPageRecord.attrs` | `SQLiteWikiStore.upsert_pages` / `replace_source_slice` / `delete_page` | same `_write()` transaction | `store.py:878` (+ abstract :543-560) |
| `page_attrs` DDL | pages DDL block | appended after `idx_pages_node` | `store.py:110` |
| table-presence migration | `SQLiteWikiStore._migrate` | `PRAGMA table_info` / `CREATE TABLE IF NOT EXISTS` | `store.py:1370` |
| `_document_attrs` | `build_file_slice` markdown branch | after `_markdown_summary` call | `repo_scan.py:643` |
| vault attrs | `scan_vault` note record | `WikiPageRecord(..., attrs=…)` | `vault_scan.py:163-171` |
| Jira attrs | `ingest-jira` → `build.callback` → `_ingest_files` → `build_file_slice` | no new code in `jira_*` | `cli.py:5249` (do_build), `:749`, `:879` |
| `remember` entity flags | `remember` options + record | `attrs=` on the memory `WikiPageRecord` | `cli.py:3805-3806`, `:3858-3866` |
| `LazyGroup` registrations | `wiki.add_command(...)` | next to `adr` | `cli.py:2347-2352` |
| `WikiStandupTool` | `create_wiki_tools` tool list | append after `WikiStatusTool(store)` | `tools.py:836-837` |
| `StandupConfig` | `WikiProjectConfig` / `WikiEnvOverlay` | new field after `obsidian_sync` / `sync_graph` | `project.py:458`, `:859` |
| identity | `_authoring_identity(None)` | import from `cli` is NOT allowed in `standup/` (cycle + hook cost) → move the helper body to `wiki/identity.py` and re-export from `cli.py` | `cli.py:3513` |
| Jira identity | `JiraInterface.myself()` → `_person()` | G9 projection | `client.py:376,460`; `parse.py:47` |
| ledger collector | `LedgerService.list_issues` (new) / `merge_blockers` | `from_root(find_shared_root(root))` | `service.py:116,152,322`; `project.py:1220` |
| tasks collector | `sdd/tasks/index/*.json` | `json.load` (same keys as `_process_task_index_file`) | `ledger/sdd_ingest.py:231-241` |
| decisions collector | `DecisionRepository.inventory()` + `list_pages(category=ADR_CATEGORY)` | filter + age | `repository.py:63`; `models.py:40` |
| memories collector | `list_pages(origin=["memory","authored"])` | same call as `memories` | `cli.py:4100`; `store.py:568` |
| brief writer | `wiki_write_lock(storage_dir)` + `upsert_pages` | lock then write | `project.py:74` |
| brief file | `${PARROT_HOME}/wikis/briefs/` | `parrot_home()` | `project.py:1045` |
| Hygiene | `load_sync_state(resolve_issues_dir())`, FEAT-625 `lint/report.json` | read-only | `jira_sync.py:152,176` |
| optional LLM | `resolve_optional_llm` → `LLMFactory.create` → `PageIndexLLMAdapter` | same env pattern | `cli.py:3728`, `:4908-4925`; `llm_adapter.py:49` |

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit standup`~~, ~~`entity`~~, ~~`brief`~~, ~~`daily`~~ commands; ~~`wiki_standup`~~ MCP tool; ~~`/parrotwiki standup`~~ — all created here.
- ~~`WikiPageRecord.attrs`~~, ~~`page_attrs` table~~, ~~`BaseWikiStore.list_by_attrs` / `get_attrs` / `upsert_attrs` / `supports_attrs`~~, ~~`AttrsUnsupportedError`~~ — created by M1.
- ~~`parrot/knowledge/wiki/entities.py`~~, ~~`entity_cli.py`~~, ~~`standup/`~~, ~~`llm_resolve.py`~~, ~~`identity.py`~~ — created here; a naive grep for `entities` hits `parrot/knowledge/graphindex` and ontology code — unrelated.
- ~~`WikiPageCategory.PROJECT | MEETING | TICKET | TASK | DELIVERABLE | DECISION | BRIEF`~~ — categories stay open strings (brainstorm Q8); the enum (`models.py:25`, 8 values incl. `ARCHIVE`) is not extended.
- ~~`StandupConfig`~~, ~~`standup.default_language`~~, ~~`language` config key~~ — created in M5/M6; only `symbols lookup --language` (`cli.py:2365`) exists and is unrelated.
- ~~`LazyGroup`~~ — only `LazyAdrGroup` with a hardcoded import exists (`lazy_commands.py:21`).
- ~~`LedgerService.list_issues`~~ / any public open+claimed listing; ~~`opened_at` / `updated_at` in `_issue_dict`~~ — timestamps exist only on `LedgerEvent.ts` (`events.py:110`).
- ~~`DecisionRepository.list_proposed()`~~; ~~`DecisionRecord.created_at` / `updated_at`~~ — use the ADR page's `updated_at`.
- ~~structured `status` / `assigned_to` / `started_at` on `task:` pages~~ — body text only (`sdd_ingest.py:255-292`); read the index JSON.
- ~~`JiraPerson.email` / `IssueFrontmatter.assignee_email`~~ — forbidden by G9 (`models.py:1-13`); `JiraInterface.myself()` does not exist yet (only the `_probe_*` helpers) — created in M8.
- ~~`remote_cli.py` / `@remote_aware`~~ — FEAT-569 is not in code.
- ~~a shared optional-LLM helper~~ — the pattern is inline at `cli.py:3728` and `:4908-4925`; ~~`WikiConfig.lightweight_model` consumed by the CLI~~ — env vars only.
- ~~`WikiMemory` model / `memories` table~~ — memories are `pages` rows with `origin="memory"`.
- ~~cross-namespace edges rejected~~ — only the *source* must be local (`federation.py:1357`); foreign destinations are qualified ids.
- ~~`wiki.yml`~~, ~~`INDEX`~~, ~~`wiki-roll-up` / `wiki-query` / `wiki-ingest` skills~~, ~~`pendientes-vinojosa`~~ — artefacts of the user's sketch, not of this repo.
- Vault frontmatter keys other than `summary`/`description` (and tags/aliases rendered into the body) are **not** persisted or indexed today; Jira pages carry `IssueFrontmatter` as body text only.

### Edit Sites (Blueprint Anchors)

Verified against: `7b4473649` (dev, 2026-10-03). `/sdd-task` MUST re-run `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY (DDL) | `CREATE INDEX IF NOT EXISTS idx_pages_node     ON pages(node_id);` | `store.py:110` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY (record) | `class WikiPageRecord(BaseModel):` | `store.py:409` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY (base contract) | `    async def list_pages(` — **ambiguous (2)**; the abstract one is preceded by `    @abstractmethod` and followed by `    @abstractmethod\n    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10)` | `store.py:568` (abstract), `:2034` (SQLite) | 2 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY (SQLite class) | `class SQLiteWikiStore(BaseWikiStore):` | `store.py:878` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY (migration) | `    async def _migrate(self, conn` | `store.py:1370` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY (stats) | `    async def stats(self) -> dict[str, Any]:` — **ambiguous (2)**; the SQLite one sits inside `class SQLiteWikiStore` after `_migrate_fts` | `store.py:596` (abstract), `:2228` (SQLite) | 2 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` | MODIFY | `class InMemoryWikiStore(BaseWikiStore):` | `file_store.py:73` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | `class FederatedWikiStore(BaseWikiStore):` | `federation.py:622` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | `class _EmptyStore(BaseWikiStore):` | `federation.py:1576` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | `        summary = _markdown_summary(content) or rel_path` | `repo_scan.py:643` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py` | MODIFY | `        scan.files.append(FileSlice(rel_path=rel, record=record))` | `vault_scan.py:171` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/entities.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/identity.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/__init__.py` (+ `models.py`, `config.py`, `identity.py`, `periods.py`, `collectors/__init__.py`, `collectors/{entities,jira,ledger,tasks,decisions,memories}.py`, `grouping.py`, `render.py`, `llm.py`, `delta.py`, `writer.py`, `pipeline.py`, `cli.py`) | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY (lazy groups) | `wiki.add_command(` | `cli.py:2347` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY (identity re-export) | `def _authoring_identity(by: str | None) -> str:` | `cli.py:3513` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY (remember options) | `@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")` — **ambiguous (11)**; the `remember` one is immediately followed by `def remember(` and preceded by the `--extract` option's closing `)` | `cli.py:3805` | 11 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY (status line) | `        click.echo(f"Env       : {effective.env} ({overlay_label})")` | `cli.py:2155` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py` | MODIFY | `class LazyAdrGroup(click.Group):` | `lazy_commands.py:21` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]:` | `ledger/service.py:201` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/jira/client.py` | MODIFY | `    async def _probe_myself(self) -> dict[str, Any]:` | `client.py:460` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY (config) | `    obsidian_sync: ObsidianSyncConfig | None = Field(` | `project.py:458` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY (overlay) | `    sync_graph: bool | None = None` | `project.py:859` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `    if ledger_service is not None:` | `tools.py:840` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY (hint) | `argument-hint:` | `claude_code/assets.py:309` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY (bullets) | `` - `audit` — run `wikitoolkit audit` and summarise recent writes. `` | `claude_code/assets.py:340` | 1 |
| `.claude/commands/parrotwiki.md` | MODIFY | `` - `audit` — run `wikitoolkit audit` and summarise recent writes. `` | `parrotwiki.md:34` | 1 |
| `docs/wiki/cheatsheet.md` | MODIFY | `## 12. Exportar el wiki como markdown` | `cheatsheet.md:489` | 1 |
| `docs/guides/llm-wiki-guide.md` | MODIFY | `## Obsidian Vaults as Wiki Sources` | `llm-wiki-guide.md:921` | 1 |
| `docs/runbooks/wiki-standup.md` | CREATE | — | — | — |
| `tests/knowledge/wiki/test_entities.py`, `test_store_attrs.py`, `test_entity_cli.py`, `tests/knowledge/wiki/standup/*` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Same-transaction attrs** (codex S1): every SQLite write path that touches `pages` for a record with non-empty `attrs` deletes + inserts its `page_attrs` rows inside the same `async with self._write()` block; `ON DELETE CASCADE` is declared but `delete_page`/`replace_source_slice` also delete explicitly (SQLite foreign keys may be off).
- **Additive migration, no bump** (brainstorm Q1): `CREATE TABLE IF NOT EXISTS` in DDL replay + a `PRAGMA table_info(page_attrs)` check in `_migrate` (precedent `_MIGRATION_COLUMNS`, `store.py:229/1357`); read-only planes never attempt DDL.
- **Source-boundary extraction** (codex S3): attrs come from the parser that already sees the frontmatter (`note.frontmatter`, the YAML block in `build_file_slice`); never from stored bodies except in `entity reindex`.
- **Native APIs for ledger/tasks/decisions** (codex S4/S5): collectors adapt those sources at read time; no materialisation changes in `ledger/index.py`, `sdd_ingest.py` or `decisions/`.
- **Lazy registration** (FEAT-584, codex S7): `standup`, `entity` and `adr` via `LazyGroup`; `entities.py`, `llm_resolve.py`, `identity.py` must stay import-light (no `cli`, no `store`, no click at import for `entities`).
- **Identity helper relocation**: `_authoring_identity` body moves to `wiki/identity.py` (`authoring_identity`) and `cli.py:3513` becomes a one-line re-export, so `standup/` and `entity_cli.py` never import `cli`.
- **G9 everywhere**: `JiraInterface.myself()` → `_person()`; the identity cache stores `account_id` + `display_name` + `resolved_at` only; tests grep fixtures and cache for `@`.
- **Deterministic periods** (codex S9): `zoneinfo`, inclusive bounds, `week_start`, `--date`/injected `now`; brief page `items` attr is the delta source of truth; page written under `wiki_write_lock`; file via tmp + `os.replace`.
- **Bounded LLM input** (codex S11): only `BriefProjection` reaches the adapter; prompt forbids new facts; 20 s timeout; failure → fallback bullets + Hygiene `llm: failed: <diag>`.
- **MCP write semantics** (codex S10): `store`/`write_file` default `False`; writes route to the local plane (`_resolve_write_store` semantics); result reports `written_page`/`written_file`.
- **Config on both schemas** (codex S8): `StandupConfig` on `WikiProjectConfig` and `WikiEnvOverlay`, both `extra="forbid"`; overlay merge follows the existing field-wise precedence in `load_effective_config`.
- Repo rules: Google-style docstrings, strict typing, `self.logger`/module logger, `asyncio.to_thread` for sync I/O, `black` 120, `ruff` TID251 bans.

### Known Risks / Gotchas
- **`cli.py` is hot** (5.5k lines; FEAT-569/570/557/625 and the inbox spec also target it). Keep every change an additive block or a one-line re-export; rebase before each `cli.py` task.
- **Back-fill is operator work**: planes built before this feature have empty attrs; `entity reindex` (local / `--store`) fills them without touching sources. The `issues` corpus reindex must run against its own plane (`--store "${PARROT_HOME}/wikis/issues/.parrot/wiki"`), because foreign namespaces are read-only.
- **Jira status vocabulary** differs per instance: unmapped raw statuses count as open and are listed in Hygiene; operators extend `standup.ticket_status_map`.
- **No author on SDD specs** and `agent:sdd-ingest` on task pages (codex S5): personal filtering of tasks uses the index `assigned_to`; specs are grouped, never filtered. Documented limitation.
- **Decision age** comes from the ADR page `updated_at`, not from the record (no timestamps on `DecisionRecord`).
- **Hook budget already pays ledger imports** (`cli.py:108-110`, codex S7): this feature must not add to it; moving those pre-existing imports lazy is out of scope (§8 Q12).
- **Arango/Postgres**: `supports_attrs=False` → collectors fall back to body parsing with a diagnostic; parity is §8 Q11.
- **Tool-count tests** (`test_mcp_server*.py`) assert fixed tool lists — update them in the same task as `WikiStandupTool`.
- **Timezones**: `created_at`/`updated_at` are UTC ISO stamps; Jira dates carry offsets; compare as calendar dates in `StandupConfig.timezone`.
- **Concurrent runs**: `wiki_write_lock` serialises page writes; the file write is atomic; two runs in the same day converge on the same `brief_id`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `PyYAML` | already core (`jira_sync.py:35`) | parse leading YAML blocks (`parse_leading_yaml`) |
| `python-frontmatter` | already used by `ObsidianToolkit` / FEAT-481 | not required — `parse_leading_yaml` uses PyYAML directly to match `repo_scan`'s rules |
| `click`, `rich`, `pydantic>=2` | already core | CLI, tables, models |
| `zoneinfo` | stdlib | period windows |
| optional LLM via `LLMFactory` / `PageIndexLLMAdapter` | existing | "On your plate" paragraph |

**No new runtime dependencies.**

---

## 8. Open Questions

> Decision trail: [x] items are resolved and reflected in the spec body.

- [x] Q1 — Schema bump or additive-only? — *Resolved in brainstorm*: additive, `SCHEMA_VERSION` stays `"3"`; `wikitoolkit status` reports `attrs: N pages indexed`. (§2 Overview, M1, AC1)
- [x] Q2 — Where does the Jira status→canonical mapping live? — *Resolved in brainstorm*: `.parrot/wiki.json` `standup.ticket_status_map` with a shipped default (To Do/Open → open, In Progress → in-progress, Blocked → blocked, In Review/Code Review → in-review, Done/Closed/Resolved → closed); raw value kept as `status_raw`; unmapped statuses treated as open and reported in Hygiene. (§2 Data Models, M3, M5, AC11)
- [x] Q3 — Default brief folder? — *Resolved in brainstorm*: always `${PARROT_HOME}/wikis/briefs/`; vault users pass `--out` (or `standup.out_dir`), and a vault target gets the `wiki_sync` markers. (M5 writer, AC9)
- [x] Q4 — Identity for "me" in Jira? — *Resolved in brainstorm* as "add `assignee_email` to `IssueFrontmatter`", **superseded during spec research (2026-10-03, Jesus)** because FEAT-454 G9 forbids email in the plane: keep G9, match `assignee_id`, resolve the account id once from `JIRA_USERNAME` via `JiraInterface.myself()` (`/myself`) and cache it (no email) under `${PARROT_HOME}/jira_identity.json`; display name is the fallback. (§2 identity, M5, M8, AC7)
- [x] Q5 — Back-fill of existing planes? — *Resolved in brainstorm*: new `wikitoolkit entity reindex [--store DIR] [--category] [--dry-run]` — re-reads stored bodies, no re-ingest, no LLM, idempotent; the `issues` plane is reindexed via `--store`. (M4, AC5)
- [x] Q6 — Vocabulary alignment with FEAT-481? — *Resolved in brainstorm*: alias only in `entities.py`; FEAT-481 is not modified. (M3, Non-Goals)
- [x] Q7 — Spanish rendering? — *Resolved in brainstorm*: static heading table, item titles verbatim, only the LLM paragraph is written in the requested language. (M5 render, AC12)
- [x] Q8 — `brief` as a `WikiPageCategory` value? — *Resolved in brainstorm*: open-string `brief` (like `note`/`decision`); `export` lands it under `briefs/`; `memories --category brief` lists past briefs. (M5 writer, Does NOT Exist)
- [x] Q9 — Weekly/monthly roll-up? — *Resolved in brainstorm*: **in scope** as `standup --period day|week|month` (same collectors, period-bounded window, `brief:weekly:<YYYY-Www>` / `brief:monthly:<YYYY-MM>` pages, "Closed this period / Still open / Decisions taken" sections, diff against the previous period, daily briefs listed as sources). (M5 periods/render, AC6)
- [x] Q10 — Ownership of the entity vocabulary vs. `wikitoolkit inbox`? — *Resolved in brainstorm*: this spec owns `entities.py` + `page_attrs`; the inbox spec depends on it and its classifier writes attrs (`type`, `date`, `project`) from day one. Lane 1 of this feature is the first PR so inbox can base on it. (G2, Worktree Strategy)
- [ ] Q11 — Attrs parity for `ArangoDBWikiStore` / `PostgresWikiStore` (codex S6): v1 ships `supports_attrs=False` + body-parse fallback. Implement real attrs on those backends in this feature, or file it as a follow-up ledger item after merge? — *Owner: Jesus*
- [ ] Q12 — Pre-existing module-level ledger imports in `cli.py:108-110` (codex S7) already cost the `claude-hook` path. Open a `tech_debt` ledger issue to move them behind command execution, or fold it into this feature's M6? — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.157.0, reasoning high) · Status: completed
> · Transcript: `sdd/state/FEAT-627/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
> All 29 cited paths passed containment + existence checks.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make page attributes part of the page write lifecycle (architecture) | CONFIRM | Verified: `upsert_pages`/`replace_source_slice`/`delete_page` each own a transaction; a side table written separately would drift. Attrs now travel on `WikiPageRecord.attrs` and are written/deleted in the same `_write()` block. | §2 Overview, M1, AC2 |
| S2 | Handle missing `page_attrs` tables despite keeping schema v3 (risk) | CONFIRM | Verified: `_migrate` checks only `_MIGRATION_COLUMNS` (`store.py:229,1357`); read-only foreign planes skip replay. Added table-presence check + `supports_attrs=False` path + two tests. | M1, AC1, §4 |
| S3 | Extract attributes before source-specific body transformations (architecture) | CONFIRM | Verified: `_note_body` drops frontmatter; `build_file_slice` wraps content. Extraction moved to the source boundary; body parsing kept only for `entity reindex`. | §2 Overview, M2, §7 |
| S4 | Define an explicit task entity mapping (api) | CONFIRM | Verified: task pages carry status as body text only. `task` added to `EntityType` with the index's status enum; tasks collected from `sdd/tasks/index/*.json`. | §2 Data Models, M5 |
| S5 | Specify canonical status + identity normalisation before collectors (api) | CONFIRM | Per-type enums, `status_raw`, precedence rule, `ticket_status_map`, identity model and the SDD author limitation are now explicit. | §2 Data Models, M3, §7 risks, AC7 |
| S6 | Choose and document a backend contract for attributes (architecture) | CONFIRM + ESCALATE | Contract added to `BaseWikiStore` with non-abstract unsupported defaults; SQLite + InMemory implement; federation forwards. Arango/Postgres parity is a product decision. | M1; §8 Q11 |
| S7 | Audit the hook import graph instead of only lazily registering standup (risk) | CONFIRM (scoped) + ESCALATE | Verified: `cli.py:108-110` imports the ledger at module load; `project.py:28` imports `decisions.models`. This feature adds nothing to that path (`LazyGroup`, import-light modules, sys.modules test); the pre-existing cost is out of scope. | M6, AC13, §7; §8 Q12 |
| S8 | Add standup configuration to both base and overlay schemas (api) | CONFIRM | Verified `extra="forbid"` on both models. `StandupConfig` added to `WikiProjectConfig` and `WikiEnvOverlay`. | §2 Data Models, M5, AC15 |
| S9 | Make period boundaries and brief writes deterministic and recoverable (architecture) | CONFIRM | Timezone/week-start config, injectable clock, `wiki_write_lock`, tmp+`os.replace`, `items` attr as delta source of truth. | M5, §7, AC9/AC10 |
| S10 | Treat `wiki_standup` as an explicit mutating MCP operation (api) | CONFIRM | Tool defaults to read-only; writes local-only and reported; assets + checked-in command updated in one task. | M7, AC14 |
| S11 | Bound and sanitize the optional LLM summary input (risk) | CONFIRM | `BriefProjection` (≤40 items, ≤120-char titles, no bodies/urls), prompt forbids new facts, timeout, fail-safe write. | §2 Data Models, M5, AC8 |
| S12 | Build a cross-source and migration test matrix before collector implementation (testing) | CONFIRM | §4 now covers attrs lifecycle, v3-without-table (both modes), aliases, federated read-only, periods, delta, dual-output failure, hook import set, model-absent fallback. | §4 |

Summary: **12** confirmed · **0** rejected · **2** escalated (S6, S7 carry §8 questions in addition to their confirmed part).

---

## Worktree Strategy

- **Isolation unit**: one feature worktree (`.claude/worktrees/feat-FEAT-627-wikitoolkit-standup`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in parentheses):
  - M3 (`entities.py`) has no dependencies.
  - M1 (store contract) has no dependencies.
  - M2 → M1 (sets `record.attrs`), M2 → M3 (`normalize_frontmatter`).
  - M4 → M1, M3 (`upsert_attrs`, strict normalisation).
  - M8 has no dependencies (two independent seams; may run first).
  - M5 → M1, M3, M8 (`list_by_attrs`, vocabulary, `list_issues`, `myself`); M5 also owns `StandupConfig` in `project.py`.
  - M6 → M4, M5 (registers both groups; `status` line needs M1's `stats`).
  - M7 → M5, M6 (tool wraps `pipeline.run`; docs mirror CLI help).
  - Modules without an edge (M1 ∥ M3 ∥ M8; then M2 ∥ M4 ∥ M5-collectors) are expected to run concurrently. Inside M5, the collectors (six files), `periods.py`, `render.py`, `llm.py`, `delta.py`, `writer.py` are file-disjoint and may be separate parallel tasks once `models.py` + `config.py` exist.
- **Shared files** (their tasks get serialised): `store.py` (M1 DDL/record/contract/migration/stats — one task or a strict chain), `cli.py` (M4 remember flags, M6 lazy groups + identity re-export + status line), `project.py` (M5 config + overlay), `claude_code/assets.py` + `.claude/commands/parrotwiki.md` (M7, one task), `tools.py` (M7).
- **Exclusive resources**: none (no extension rebuild, no lockfile, no DB migration outside the SQLite DDL that tests exercise in `tmp_path`). The `test_mcp_server*.py` tool-count updates are part of the M7 tool task.
- **Cross-feature dependencies**: none must merge first. Coordination: FEAT-625 (`wikitoolkit lint`, approved) — Hygiene reads its report only if present; FEAT-481 (in progress) — vocabulary aliased, no shared files; the inbox spec (not yet written) must base on this feature's Lane 1 (M1+M3) — **open the Lane 1 PR early** (brainstorm Q10). FEAT-569/570/557 also touch `cli.py`/`tools.py`/`mcp_server.py`; rebase before those tasks.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-03 | Jesus Lara + Claude | Initial draft from the accepted brainstorm (Option B), 10 carried-forward decisions, Q4 re-resolved under G9, codex design research folded (12 suggestions) |
