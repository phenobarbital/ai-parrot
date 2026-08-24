---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Jira Ticket Extractor → LLM Wiki (`issues` namespace)

**Feature ID**: FEAT-454
**Date**: 2026-08-24
**Author**: Jesus Lara (spec: Claude session 2026-08-24)
**Status**: draft
**Target version**: next minor
**Builds on**: FEAT-450 (`sdd/specs/wiki-namespaces.spec.md`), FEAT-451
(`sdd/specs/wikitoolkit-ingest-documents.spec.md`)
**Brainstorm**: `sdd/proposals/jira-extractor-llmwiki.brainstorm.md` (Option A)

---

## 1. Motivation & Business Requirements

### Problem Statement

Every architectural decision, bug reproduction, customer complaint and
acceptance criterion this team produces lands in Jira — and stays there.
Claude Code cannot reach it. The only path today is `JiraToolkit`, an
agent-facing toolkit: an LLM must decide to call a tool, form a JQL, pay
for the round-trip, and read a JSON envelope. That is fine for "transition
NAV-9269 to Done"; it is useless for "what do we already know about the
forms tenant-in-URL problem", because the answer requires *ranked retrieval
across the whole ticket corpus* — which is what the LLM Wiki does and what a
tool call does not.

The repo already has a knowledge plane Claude Code queries first
(`wikitoolkit query`, plus the six native MCP tools), and FEAT-450 gave it
namespaces so a second corpus can be federated in behind `ns::id`. The
ticket corpus is the single largest body of institutional knowledge not in
it.

**Who is affected**: every Claude Code session in this repo (a spec author
who needs a ticket's real acceptance criteria; a debugging session that
should surface the three earlier tickets about the same failure), and the
human operators who answer those questions from memory today.

**Why now**: FEAT-450 (namespaces) and FEAT-451 (`ingest` + document
frontmatter) both landed. The federation plumbing, the deterministic
frontmatter contract, and the vault-scan build path that turns a folder of
markdown into a queryable plane all exist. The remaining gap is a
deterministic Jira → markdown emitter plus a shared Jira read interface.

### Goals

- **G1 — Shared Jira read interface, no duplicated client code.** One core
  implementation of Jira reads (`parrot/interfaces/jira/`), consumed by both
  `JiraToolkit` and this feature's sweep, with full auth parity including
  OAuth 2.0 3LO. `jira` stays an optional, lazily-imported dependency; it
  must never become a hard core import.
- **G2 — Zero-LLM, byte-deterministic extraction by default.** Every
  frontmatter field is a Jira field or a pure function of one. Identical
  input produces identical bytes, so a cron run is free and diffable. An
  opt-in `--enrich` flag may add an LLM summary; the default path never
  calls a model.
- **G3 — One markdown document per ticket, updated in place.** Stable
  filename and stable `concept_id`; re-running updates the document, never
  creating a second copy, never accumulating duplicate pages or edges.
- **G4 — Human annotations survive every re-sync.** Content below the
  `<!-- jira-sync:end -->` marker is preserved byte-for-byte forever; the
  extractor owns only the region above it.
- **G5 — Incremental sweep.** Scope is declared as JQL; each run fetches
  only issues with `updated >=` the last successful watermark, so a
  daily/weekly cron stays cheap as the corpus grows.
- **G6 — Queryable as the `issues` namespace.** The corpus becomes its own
  plane, registered once via `wikitoolkit ns add`, reachable through
  `wikitoolkit query --ns issues` and the default broadcast.
- **G7 — Relations materialized as a navigable graph.** Jira issue links,
  epic/parent↔subtask hierarchy, person pages (assignee/reporter) and
  project/component/label roll-up pages.
- **G8 — Off-repo storage.** Generated markdown lives outside the git repo
  at a configurable path (default under `PARROT_HOME`), so internal ticket
  prose and customer names never enter git history.
- **G9 — No personal email in the plane.** Person pages carry display name
  and `accountId` only.
- **G10 — One command for the cron line.** `ingest-jira` builds the plane
  by default (`--no-build` to opt out), so the plane can never silently lag
  the files.
- **G11 — OKF-valid frontmatter.** `ConceptType` gains `Issue`, `Person`
  and `Project` so the emitted `type:` is a controlled-vocabulary value
  rather than a look-alike string.

### Non-Goals (explicitly out of scope)

- **Cross-namespace graph edges.** `wikitoolkit link` refuses them
  outright — *"Both pages must live in the same plane — there are no
  cross-namespace edges"* (`cli.py:2665-2666`). v1 links tickets to specs at
  **text/frontmatter level** (findable by `query`, openable by `page`, not
  traversable by `related`). Real federated edge traversal is deferred to a
  **follow-up spec extending FEAT-450** — decided in §3 clarification, see
  §8.
- **Ticket comments.** Explicitly excluded from v1 (largest token
  contributor, most churn on re-sync).
- **Attachment payloads.** Attachments and remote links are recorded as
  references (filename, size, URL) only; nothing is downloaded or ingested.
- **Writing into the repo plane.** `wikitoolkit build` on the repository and
  `repo_scan.py` are untouched — the same hard non-goal FEAT-402 and
  FEAT-451 both respected.
- **LLM triage / HITL manifest review.** Rejected in brainstorm — see
  `proposals/jira-extractor-llmwiki.brainstorm.md` Option C: `ingest` is
  charter- and LLM-driven by design, which contradicts an unattended
  zero-LLM sweep.
- **A direct plane writer.** Rejected in brainstorm Option B: it would
  discard the markdown artifact and hand-roll what `build --vault` already
  does.
- **Jira writes.** This feature is read-only against Jira. Ticket mutation
  stays `JiraToolkit`'s job.
- **Scheduling infrastructure.** The runbook documents cron; no scheduler
  is shipped.

---

## 2. Architectural Design

### Overview

The feature splits at the markdown boundary, and lets already-shipped code
own everything after it.

1. **Shared interface** (`parrot/interfaces/jira/`) — core, lazily importing
   `jira`. Owns connection + auth resolution (every mode `JiraToolkit`
   supports today, including 3LO via the already-core `JiraOAuthManager`)
   and the read surface: paginated JQL search, issue fetch, changelog,
   project metadata, auth probe. Returns validated pydantic models. This
   mirrors `parrot/interfaces/obsidian/`, whose docstring states the same
   intent: *"One vault-access + parsing core reused by ObsidianToolkit, the
   loaders, and wiki vault_scan"*. `JiraToolkit` is refactored to delegate,
   so there is exactly one Jira read implementation.
2. **Renderer** (`parrot/knowledge/wiki/jira_render.py`) — a pure function
   `JiraIssue → markdown`. Deterministic frontmatter (fixed key order,
   sorted collections, `None` omitted — the `render_frontmatter` contract at
   `documents.py:213-219`), body sections, `[[NAV-1234]]` wikilinks for
   relations, `#tags`, and preservation of everything below the sync marker.
   No network, no LLM, no I/O.
3. **Sweep** (`parrot/knowledge/wiki/jira_sync.py`) — resolves scope and
   watermark, pages through matching issues, renders and writes each
   document, emits satellite entity notes, detects orphans, and advances the
   watermark only after a fully successful run.
4. **Build + register** — existing code, unchanged. `build --vault` runs
   `scan_vault`, which already turns wikilinks into `references` edges,
   `#tags` into first-class tag pages, and folders into `contains` pages,
   writing `<issues-dir>/.parrot/wiki/wiki.db`. `ns add --store` registers
   the plane once as `issues`.

**Description rendering — the auth-independent path.** The Jira REST API
version is selected by auth mode (`/rest/api/3` for `oauth2_3lo`, else
`/rest/api/2` — `jiratoolkit.py:2173-2177`), and the two return *different*
description formats: ADF JSON on v3, wiki markup on v2. Rather than
implement either parser, the sweep requests `expand=renderedFields`, which
returns the description rendered as **HTML** identically on both versions,
and converts it with `html2text` (already pinned alongside `jira` in the
host `agents`/`mcp` extras). `html2text` must be configured explicitly
(`body_width=0`, no link-reference wrapping) so its output is deterministic.

**Storage layout** (`<issues-dir>`, default `${PARROT_HOME}/wikis/issues`):

```
issues/
├── NAV-9372.md                 # one document per ticket
├── people/jesus-lara.md        # person pages (accountId-derived slug)
├── projects/NAV.md             # project roll-up
├── components/navigator-forms.md
├── labels/multitenant.md
└── .parrot/
    ├── jira_sync.json          # watermark + extractor version (state)
    └── wiki/wiki.db            # the plane, built by `build --vault`
```

`.parrot/` is already in `VAULT_EXCLUDE_DIRS` (`vault_scan.py:58`), so the
state file and the plane are never re-ingested as notes.

### Component Diagram

```
                    parrot/interfaces/jira/          (M1, core, lazy `jira`)
                    ├── models.py  JiraIssue, JiraPerson, JiraIssueLink, ...
                    └── client.py  JiraInterface (auth + reads + parse)
                              │
              ┌───────────────┴────────────────┐
              │                                │
   parrot_tools/jiratoolkit.py      parrot/knowledge/wiki/jira_sync.py   (M4)
   JiraToolkit  (M2, delegates)     sweep: scope → fetch → render → write
   agent-facing envelope layer                │         │
                                              │         └──→ jira_render.py (M3)
                                              │              pure: JiraIssue → md
                                              ▼
                                   <issues-dir>/*.md  +  .parrot/jira_sync.json
                                              │
                                              ▼
                        wikitoolkit build --vault   (EXISTING, untouched)
                          scan_vault: wikilinks→edges, #tags→tag pages
                                              │
                                              ▼
                        <issues-dir>/.parrot/wiki/wiki.db
                                              │
                        wikitoolkit ns add issues --store …  (EXISTING)
                                              │
                                              ▼
              wikitoolkit query --ns issues   /   wiki_query MCP tool
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/interfaces/obsidian/` | pattern precedent | Shape to copy for `parrot/interfaces/jira/` (shared core, toolkit is a skin over it). |
| `parrot/auth/jira_oauth.py` | uses (no change) | `JiraOAuthManager` / `JiraTokenSet` already in **core** — 3LO parity needs no new dependency direction. |
| `parrot_tools/jiratoolkit.py` | modifies | Read methods delegate to `JiraInterface`. Public tool signatures and the `JiraToolEnvelope` shape MUST NOT change (FEAT-138/TASK-948). |
| `parrot/knowledge/wiki/cli.py` | extends | One new `ingest-jira` command. `build`, `ns`, `link` untouched. |
| `parrot/knowledge/wiki/vault_scan.py` | uses (no change) | `scan_vault()` consumed as-is via `build --vault`. |
| `parrot/knowledge/wiki/documents.py` | pattern precedent | `render_frontmatter` determinism contract mirrored, not modified. |
| `parrot/knowledge/okf/ontology.py` | extends | Additive: `ISSUE`, `PERSON`, `PROJECT` members. |
| `parrot/knowledge/wiki/export.py` | uses (no change) | `_okf_type_for` falls back to `category.title()` (`export.py:73`), so categories `issue`/`person`/`project` already project to the new type names. |
| `parrot/knowledge/graphindex/builder.py` | pattern precedent | `_loader_for` (`:667-704`) is the lazy optional-dependency idiom to copy. |
| `packages/ai-parrot/pyproject.toml` | modifies | Add a `jira` extra; today `jira` only rides `agents`/`mcp`. |
| `wikitoolkit build` (repo plane) | **none** | Hard non-goal. |

### Data Models

```python
# parrot/interfaces/jira/models.py  (M1)

class JiraPerson(BaseModel):
    """A Jira user. NO email field — G9."""
    account_id: str
    display_name: str

class JiraIssueLinkKind(str, Enum):
    BLOCKS = "blocks"
    BLOCKED_BY = "blocked_by"
    RELATES = "relates"
    DUPLICATES = "duplicates"
    DUPLICATED_BY = "duplicated_by"
    CLONES = "clones"
    CLONED_BY = "cloned_by"

class JiraIssueLink(BaseModel):
    kind: JiraIssueLinkKind
    target_key: str

class JiraChangeEvent(BaseModel):
    at: datetime
    field: str
    from_value: str | None = None
    to_value: str | None = None
    author: JiraPerson | None = None

class JiraAttachmentRef(BaseModel):
    """Reference only — never downloaded (Non-Goal)."""
    filename: str
    size_bytes: int | None = None
    mime_type: str | None = None
    url: str

class JiraRemoteLink(BaseModel):
    title: str
    url: str

class JiraIssue(BaseModel):
    key: str
    issue_id: str
    project_key: str
    issue_type: str                     # → frontmatter `category`
    status: str
    resolution: str | None = None
    priority: str | None = None
    summary: str                        # → frontmatter `title`
    description_html: str | None = None # from expand=renderedFields
    acceptance_criteria_html: str | None = None
    assignee: JiraPerson | None = None
    reporter: JiraPerson | None = None
    labels: list[str] = []
    components: list[str] = []
    epic_key: str | None = None
    parent_key: str | None = None
    subtask_keys: list[str] = []
    links: list[JiraIssueLink] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None
    resolved_at: datetime | None = None
    history: list[JiraChangeEvent] = []
    attachments: list[JiraAttachmentRef] = []
    remote_links: list[JiraRemoteLink] = []
    url: str                            # browse URL

# parrot/knowledge/wiki/jira_render.py  (M3)

class IssueFrontmatter(BaseModel):
    """Deterministic frontmatter projection.

    Field declaration order IS the emitted YAML key order (the
    documents.render_frontmatter contract). Collections sorted; None omitted.
    """
    type: ConceptType = ConceptType.ISSUE
    key: str
    title: str
    status: str
    resolution: str | None = None
    category: str                   # Jira issuetype
    project: str
    priority: str | None = None
    assignee: str | None = None
    assignee_id: str | None = None
    reporter: str | None = None
    reporter_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    resolved_at: str | None = None
    labels: list[str] = []
    components: list[str] = []
    epic: str | None = None
    parent: str | None = None
    subtasks: list[str] = []
    blocks: list[str] = []
    blocked_by: list[str] = []
    relates: list[str] = []
    duplicates: list[str] = []
    repo_pages: list[str] = []      # qualified ids, e.g. "repo::file:sdd/specs/x.spec.md"
    url: str
    sync: IssueSyncStamp

class IssueSyncStamp(BaseModel):
    fetched_at: str
    extractor_version: int
    unreachable_since: str | None = None   # set when the ticket stops resolving

# parrot/knowledge/wiki/jira_sync.py  (M4)

class JiraScopeState(BaseModel):
    jql: str
    jql_fingerprint: str            # sha256 of the normalized JQL
    last_watermark: str | None = None   # ISO-8601 `updated` high-water mark
    extractor_version: int
    last_run_at: str | None = None
    last_run_status: Literal["ok", "partial", "failed"] = "ok"

class JiraSyncState(BaseModel):
    """Persisted at <issues-dir>/.parrot/jira_sync.json."""
    version: int = 1
    scopes: dict[str, JiraScopeState] = {}   # keyed by jql_fingerprint

class SweepReport(BaseModel):
    fetched: int = 0
    written: int = 0
    unchanged: int = 0
    skipped: int = 0
    orphaned: int = 0
    entity_notes: int = 0
    unresolved_link_keys: list[str] = []
    watermark_advanced: bool = False
    errors: list[str] = []
```

### New Public Interfaces

```python
# parrot/interfaces/jira/client.py  (M1)

class JiraInterface:
    """Shared Jira read interface. Lazily imports `jira`."""

    def __init__(
        self,
        server_url: str | None = None,
        auth_type: str | None = None,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        oauth_consumer_key: str | None = None,
        oauth_key_cert: str | None = None,
        oauth_access_token: str | None = None,
        oauth_access_token_secret: str | None = None,
        credential_resolver: Any = None,
        request_timeout: float = 30.0,
        verify_credentials: bool = True,
    ) -> None: ...

    async def verify_auth(self) -> dict[str, Any]: ...
    async def get_issue(self, key: str, *, fields: str | None = None,
                        expand: str | None = None) -> dict[str, Any]: ...
    async def search_issues(self, jql: str, *, fields: str | None = None,
                            expand: str | None = None,
                            page_size: int = 100) -> AsyncIterator[dict[str, Any]]: ...
    async def get_changelog(self, key: str, page_size: int = 100) -> list[dict[str, Any]]: ...
    async def get_projects(self) -> list[dict[str, Any]]: ...
    @staticmethod
    def parse_issue(raw: dict[str, Any], *, base_url: str) -> JiraIssue: ...  # pure

# parrot/knowledge/wiki/jira_render.py  (M3)

SYNC_MARKER: str = (
    "<!-- jira-sync:end — everything below is yours; "
    "the extractor never touches it -->"
)
EXTRACTOR_VERSION: int = 1

def issue_filename(key: str) -> str: ...                # "NAV-9372" -> "NAV-9372.md"
def person_slug(person: JiraPerson) -> str: ...         # accountId-derived, stable
def split_at_marker(text: str) -> tuple[str, str]: ...  # (generated, human_tail)
def render_issue_document(issue: JiraIssue, *, fetched_at: datetime,
                          existing: str | None = None,
                          repo_pages: list[str] | None = None) -> str: ...
def render_person_note(person: JiraPerson, issue_keys: list[str], *,
                       existing: str | None = None) -> str: ...
def render_group_note(kind: Literal["project", "component", "label"], name: str,
                      issue_keys: list[str], *, existing: str | None = None) -> str: ...

# parrot/knowledge/wiki/jira_sync.py  (M4)

async def sweep_jira_issues(
    interface: JiraInterface,
    issues_dir: Path,
    *,
    jql: str,
    since: datetime | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> SweepReport: ...

def load_sync_state(issues_dir: Path) -> JiraSyncState: ...
def save_sync_state(issues_dir: Path, state: JiraSyncState) -> None: ...
```

**CLI surface** (M5, added to `parrot/knowledge/wiki/cli.py`):

```
wikitoolkit ingest-jira [OPTIONS]

  --jql TEXT           JQL scope (default: JIRA_WIKI_JQL, or project = <JIRA_DEFAULT_PROJECT>)
  --project TEXT       Shorthand for `project = <KEY>`
  --since DATE         Override the stored watermark (ISO-8601)
  --issues-dir PATH    Output directory (default: JIRA_WIKI_ISSUES_DIR
                       or ${PARROT_HOME}/wikis/issues)
  --build/--no-build   Build the plane after emitting (default: build)   [G10]
  --enrich             Opt-in LLM summary for thin descriptions (default: off) [G2]
  --force              Re-render every issue in scope, ignoring the watermark
  --dry-run            Report what would change; write nothing
  --json               Emit the SweepReport as JSON
  -q, --quiet          Only the final summary line
```

**Configuration keys** (navconfig-then-env, the `_cfg` idiom at
`jiratoolkit.py:751-760`):

| Key | Default | Purpose |
|---|---|---|
| `JIRA_WIKI_ISSUES_DIR` | `${PARROT_HOME}/wikis/issues` | Off-repo corpus root (G8) |
| `JIRA_WIKI_JQL` | `project = ${JIRA_DEFAULT_PROJECT}` | Default sweep scope |
| `JIRA_WIKI_NAMESPACE` | `issues` | Namespace name used by the runbook |
| `JIRA_INSTANCE`, `JIRA_AUTH_TYPE`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `JIRA_SECRET_TOKEN`, `JIRA_OAUTH_*`, `JIRA_REQUEST_TIMEOUT` | (existing) | Reused verbatim from `JiraToolkit` |

---

## 3. Module Breakdown

### Module 1: Shared Jira read interface
- **Path**: `parrot/interfaces/jira/__init__.py`, `models.py`, `client.py`
- **Responsibility**: All Jira connection/auth resolution and read
  operations, plus the pure `parse_issue` raw→`JiraIssue` projection. Lazy
  `jira` import with an actionable install error naming the extra. Preserves
  `JiraToolkit`'s no-heuristic auth discipline: an unresolved `auth_type`
  leaves the interface unauthenticated and every call raises rather than
  silently using a service account (`jiratoolkit.py:767-775`).
- **Depends on**: `parrot/auth/jira_oauth.py` (existing, core).

### Module 2: `JiraToolkit` delegation refactor
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
- **Responsibility**: Route the read methods (`jira_get_issue`,
  `jira_search_issues`, `jira_count_issues`, `jira_get_projects`,
  `jira_list_history`, `_get_full_changelog`, `_issue_to_dict`) through
  `JiraInterface`, keeping the envelope, permission, structured-output and
  error-hardening layers exactly as they are. **Zero public-surface change**;
  the existing envelope/permission/OAuth/defaults tests are the regression
  gate.
- **Depends on**: Module 1.

### Module 3: Deterministic renderer
- **Path**: `parrot/knowledge/wiki/jira_render.py`
- **Responsibility**: Pure `JiraIssue` → markdown document (frontmatter +
  body + wikilinks + tags), person/project/component/label notes, sync-marker
  split and preservation, HTML→markdown conversion of `renderedFields` with
  a fixed `html2text` configuration. No network, no LLM, no filesystem.
- **Depends on**: Module 1 (models), Module 6 (`ConceptType.ISSUE`).

### Module 4: Sweep, watermark and orphan handling
- **Path**: `parrot/knowledge/wiki/jira_sync.py`
- **Responsibility**: Resolve scope + watermark, page through issues, render
  and write documents (preserving human tails), accumulate entity-note
  membership, detect orphans, write `jira_sync.json` — advancing the
  watermark only on a fully successful run. Guards the output directory with
  the existing `wiki_write_lock`.
- **Depends on**: Modules 1, 3.

### Module 5: `wikitoolkit ingest-jira` command
- **Path**: `parrot/knowledge/wiki/cli.py` (new command only)
- **Responsibility**: Option parsing, config resolution, invoking the sweep,
  then invoking the existing build path unless `--no-build`, and reporting
  the `SweepReport` (human or `--json`).
- **Depends on**: Modules 1, 4.

### Module 6: OKF vocabulary extension
- **Path**: `parrot/knowledge/okf/ontology.py`
- **Responsibility**: Add `ISSUE = "Issue"`, `PERSON = "Person"`,
  `PROJECT = "Project"` to `ConceptType`. Purely additive — existing member
  string values must not change (the module's own design note).
- **Depends on**: nothing.

### Module 7: Packaging, runbook and namespace registration docs
- **Path**: `packages/ai-parrot/pyproject.toml`, `docs/` (runbook)
- **Responsibility**: Add the host `jira` extra; document the one-time
  `ns add issues --store …` registration, the cron line, and the
  credential keys — the shape TASK-2382 established for the notes namespace.
- **Depends on**: Module 5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_jira_interface_lazy_import_error` | M1 | With `jira` absent, instantiation/first call raises an error naming the install extra — no `ModuleNotFoundError` traceback. |
| `test_jira_interface_no_auth_heuristic` | M1 | Unresolved `auth_type` leaves the interface unauthenticated; every read raises instead of silently using env credentials. |
| `test_jira_interface_auth_modes` | M1 | Each mode (basic, token, oauth1, `oauth2_3lo`) resolves the expected server URL and client options. |
| `test_parse_issue_projection` | M1 | Raw Jira JSON → `JiraIssue`: links normalized to `JiraIssueLinkKind`, epic/parent/subtasks, attachments as refs, changelog events ordered. |
| `test_parse_issue_never_captures_email` | M1 | A raw payload containing `emailAddress` produces a `JiraPerson` with no email anywhere in the model dump (G9). |
| `test_render_issue_document_golden` | M3 | Fixed `JiraIssue` + fixed `fetched_at` renders byte-identical to a golden file (G2). |
| `test_render_issue_document_is_idempotent` | M3 | Rendering twice yields identical bytes; re-rendering its own output changes nothing. |
| `test_render_frontmatter_key_order_and_sorting` | M3 | Declaration key order preserved, collections sorted, `None` fields omitted. |
| `test_render_preserves_human_tail` | M3 | Content below `SYNC_MARKER` survives verbatim, including trailing whitespace and nested markers (G4). |
| `test_render_appends_missing_marker` | M3 | A hand-created file without the marker gains one; nothing is destroyed. |
| `test_render_wikilinks_and_tags` | M3 | Relations emit `[[KEY]]`; labels/components/project emit `#tags` that `scan_vault` will turn into tag pages. |
| `test_html_to_markdown_deterministic` | M3 | The same `renderedFields` HTML converts to the same markdown across runs; tables/code/links survive. |
| `test_person_slug_stable_from_account_id` | M3 | Slug derives from `accountId` and is unchanged by a display-name change. |
| `test_watermark_not_advanced_on_partial` | M4 | A mid-sweep failure leaves `last_watermark` untouched and `last_run_status="partial"` (G5). |
| `test_watermark_advances_on_success` | M4 | A clean run advances the watermark to the max `updated` seen. |
| `test_scope_keyed_by_jql_fingerprint` | M4 | Two different JQLs keep independent watermarks; changing the JQL does not reuse the other's. |
| `test_extractor_version_bump_forces_rerender` | M4 | A higher `EXTRACTOR_VERSION` re-renders documents even when `updated` is unchanged. |
| `test_unchanged_issue_not_rewritten` | M4 | An issue whose render is byte-identical counts as `unchanged` and the file mtime is untouched. |
| `test_orphan_detection` | M4 | A document whose key is no longer in scope is reported as `orphaned`, not silently left as a ghost page. |
| `test_unreachable_ticket_marked_not_deleted` | M4 | A 404/403 on a known ticket sets `sync.unreachable_since` and keeps the document. |
| `test_empty_result_set_probes_auth` | M4 | Zero results triggers the auth probe; a failed probe raises instead of advancing the watermark (the `AUTHENTICATED_FAILED` trap, `jiratoolkit.py:2257-2266`). |
| `test_dry_run_writes_nothing` | M4 | `--dry-run` reports counts and leaves the directory byte-identical. |
| `test_concept_type_additive` | M6 | New members exist with exact values `Issue`/`Person`/`Project`; every pre-existing member's `.value` is unchanged. |

### Integration Tests

| Test | Description |
|---|---|
| `test_sweep_to_queryable_plane` | Fake `JiraInterface` → sweep into a tmpdir → `build --vault` → `query` returns the ticket; `page` returns its frontmatter; `related` shows the wikilink edge to the linked ticket. |
| `test_resync_updates_in_place` | Sweep, mutate an issue's status, re-sweep: one document, one page, no duplicate pages or edges (G3). |
| `test_resync_preserves_human_annotation` | Append a human note below the marker, re-sweep with a changed ticket: the note survives and the generated region updates (G4). |
| `test_entity_notes_and_tag_pages` | Person/project/component/label notes exist and the built plane exposes tag pages aggregating their tickets (G7). |
| `test_namespace_registration_roundtrip` | `ns add issues --store <dir>/.parrot/wiki` then `query --ns issues` reaches the corpus, and the default broadcast includes it (G6). |
| `test_ingest_jira_builds_by_default` | The command builds the plane with no extra flag; `--no-build` leaves `wiki.db` absent/stale (G10). |
| `test_no_llm_calls_by_default` | A client factory that raises on any completion proves the default path never calls a model (G2). |
| `test_jiratoolkit_regression_after_delegation` | The existing envelope / permission / OAuth / defaults / error-hardening test suites pass unchanged against the refactored toolkit (M2). |
| `test_repo_plane_untouched` | Running the sweep does not modify the repository's own `.parrot/wiki` plane. |

### Test Data / Fixtures

```python
@pytest.fixture
def raw_issue() -> dict:
    """Raw Jira JSON for NAV-9372 with expand=renderedFields,changelog:
    issuelinks (blocks + duplicates), epic + parent, subtasks, 2 components,
    2 labels, 1 attachment, 1 remote link, a 3-entry changelog, and an
    `emailAddress` present on assignee/reporter (must be dropped)."""

@pytest.fixture
def fake_jira_interface(raw_issue):
    """In-memory JiraInterface stand-in: no network, scriptable result pages,
    and a failure-injection hook for the partial-sweep tests."""

@pytest.fixture
def issues_dir(tmp_path) -> Path:
    """Empty corpus root; assertions run against rendered bytes on disk."""

@pytest.fixture
def frozen_now() -> datetime:
    """Fixed `fetched_at` so golden-file comparisons are byte-stable."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -k jira -v`)
- [ ] All integration tests pass (`pytest packages/ai-parrot/tests/integration -k jira -v`)
- [ ] `jira` is **not** imported at `parrot.knowledge.wiki` or
      `parrot.interfaces` import time — verified by importing both with
      `jira` uninstalled/blocked.
- [ ] With `jira` absent, `wikitoolkit ingest-jira` fails with a single
      actionable message naming the install extra (no traceback).
- [ ] **G1**: `JiraToolkit`'s read methods contain no direct `jira`/REST
      calls — they delegate to `JiraInterface`. The pre-existing
      envelope/permission/OAuth/defaults/error-hardening tests pass
      unchanged, and `JiraToolEnvelope`'s shape is byte-compatible.
- [ ] **G1**: All four auth modes resolve, including `oauth2_3lo` via
      `JiraOAuthManager`.
- [ ] **G2**: A default-path sweep makes zero LLM calls (proven by a
      raising client factory), and two runs over identical input produce
      byte-identical documents.
- [ ] **G3**: Re-running the sweep over a changed ticket leaves exactly one
      document, one page and no duplicated edges.
- [ ] **G4**: Content below `<!-- jira-sync:end -->` is byte-identical
      after a re-sync that changes the generated region.
- [ ] **G5**: A second run with no Jira changes fetches 0 issues and writes
      0 documents; a mid-sweep failure does not advance the watermark.
- [ ] **G6**: `wikitoolkit query --ns issues "<ticket phrase>"` returns the
      ticket page, and `wikitoolkit page issues::file:NAV-<n>.md` renders
      its frontmatter.
- [ ] **G7**: `wikitoolkit related` on a ticket page returns its linked
      tickets, its epic, and its person/project pages.
- [ ] **G8**: No generated document is written inside the repository
      working tree; the default root resolves under `PARROT_HOME`.
- [ ] **G9**: `grep -ri "@" ` over the generated corpus finds no email
      address; `JiraPerson` has no email field.
- [ ] **G10**: `wikitoolkit ingest-jira` alone leaves a queryable, current
      plane; `--no-build` skips the build.
- [ ] **G11**: `ConceptType.ISSUE/PERSON/PROJECT` exist with values
      `Issue`/`Person`/`Project`, and no pre-existing member value changed.
- [ ] Attachments and remote links appear as references only — no file is
      downloaded by the sweep.
- [ ] Comments appear nowhere in the generated corpus (v1 non-goal).
- [ ] `wikitoolkit build` on the repository and `repo_scan.py` are
      unmodified (`git diff` clean for both).
- [ ] Runbook documents: credential keys, the one-time `ns add`, the cron
      line, and the `--force`/extractor-version re-render path.
- [ ] No breaking changes to any existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry below was verified against the working tree on 2026-08-24, at
> commit `c76fb35b2` (post-merge with `origin/dev`). The merge touched no
> file cited here.

### Verified Imports

```python
# Confirmed to resolve today:
from parrot.knowledge.wiki.vault_scan import is_obsidian_vault, scan_vault   # cli.py:1118-1121
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens      # vault_scan.py:45
from parrot.knowledge.wiki.repo_scan import (
    DEFAULT_BODY_MAX_CHARS, DEFAULT_MAX_FILE_BYTES, FileSlice, RepoScan,
    build_dir_pages, file_concept_id,
)                                                                            # vault_scan.py:37-44
from parrot.interfaces.obsidian.index import VaultIndex                      # vault_scan.py:33
from parrot.interfaces.obsidian.models import ObsidianNote                   # vault_scan.py:34
from parrot.interfaces.obsidian.parser import ObsidianNoteParser             # vault_scan.py:35
from parrot.knowledge.okf import (
    ConceptType, RelationType, RelatesTo, SourceProvenance, ConceptFrontmatter,
    project_frontmatter, parse_frontmatter, build_uri, parse_uri,
    flatten_concept_id_for_filename,
)                                                                            # okf/__init__.py:15-30
from parrot.knowledge.wiki.documents import render_frontmatter, split_frontmatter
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper                  # cli.py:2685
from parrot.knowledge.wiki.export import CATEGORY_TO_OKF_TYPE               # export.py:38
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet           # jira_oauth.py:86, :59
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py:118
def scan_vault(
    root: Path,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> tuple[RepoScan, VaultScanStats]: ...
# Edge relations produced (open-string `rel`), module docstring lines 16-21:
#   resolved [[wikilink]] -> "references";  ![[embed]] -> "embeds"
#   note -> tag page      -> "tagged";      folder      -> "contains"
# Unresolved wikilinks are DROPPED (vault_scan.py:183) and counted in
# VaultScanStats.unresolved_links (vault_scan.py:80).
def is_obsidian_vault(root: Path) -> bool: ...            # :62 — requires .obsidian/
VAULT_EXCLUDE_DIRS: frozenset[str] = frozenset(           # :58
    {".obsidian", ".trash", ".git", ".hg", ".svn", ".parrot"})
# vault_scan.py:166 — every note page is written with category="document"

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:215
class WikiPageRecord(BaseModel):
    concept_id: str          # 234, min_length=1
    node_id: Optional[str]   # 235
    title: str = ""          # 236
    category: str = "concept"  # 237 — OPEN STRING, not the ConceptType enum
    summary: str = ""        # 238
    body: str = ""           # 239
    source_id: Optional[str] = None  # 240
    token_count: int = 0     # 241
    origin: str = "ingest"   # 242 — "ingest" | "authored" | "memory"
    asserted_by: Optional[str] = None  # 243
# store.py:96-103 — edges table: (src TEXT, dst TEXT, rel TEXT DEFAULT
#   'references', provenance TEXT DEFAULT 'extracted', PK(src,dst,rel)).
#   No FK on src/dst.
    async def add_edges(self, edges: list[tuple]) -> int: ...              # :906
    async def replace_source_slice(self, source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None) -> dict: ...   # :928

# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py:209
def render_frontmatter(metadata: DocumentMetadata,
                       provenance: TriageProvenance | None = None) -> str: ...
# Determinism contract to MIRROR (docstring :213-219): fixed key order,
# sorted collections, None omitted, "" when fully empty.
# documents.py:39-50 — _FRONTMATTER_FIELD_ORDER = (title, author, created_at,
#   modified_at, page_count, word_count, language, content_type,
#   source_url, loader)
def split_frontmatter(text: str) -> tuple[dict[str, Any], str]: ...        # :253
class DocumentMetadata(BaseModel): ...   # :72 — document-shaped, NOT ticket-shaped
class DocumentAcquirer: ...              # :454
def resolve_sources(source: str, *, recursive: bool = True) -> list[DocumentRef]: ...  # :154

# packages/ai-parrot/src/parrot/knowledge/wiki/export.py
CATEGORY_TO_OKF_TYPE: dict[str, str] = {...}   # :38-45
def _okf_type_for(category: str) -> str:       # :73
    return CATEGORY_TO_OKF_TYPE.get(category, category.title() or "Other")
# ^ categories "issue"/"person"/"project" already project to
#   "Issue"/"Person"/"Project" via the .title() fallback — export.py needs NO change.
# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py:160-162 — the bundle
#   reader deliberately uses plain yaml.safe_load, NOT the OKF parser, "which
#   enforces the closed ConceptType enum".

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:181
class WikiNamespaceConfig(BaseModel):     # model_config = ConfigDict(extra="forbid") :210
    path: str | None          # 212 — another wiki project root  (kind: path)
    store: str | None         # 215 — pre-built store directory  (kind: store)
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"   # 218
    database: str | None      # 221 — ArangoDB database          (kind: database)
    credentials_env: str; vault: str | None; description: str; weight: float
    def storage_path(self, root: Path) -> Path: ...   # :381 (WikiProjectConfig)
    def db_path(self, root: Path) -> Path: ...        # :386 -> <storage>/wiki.db
def resolve_vault_dir(...) -> Path | None: ...        # :436

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
async def open_namespace_store(...): ...   # :340
async def resolve_namespaces(...): ...     # :433
class FederatedWikiStore(BaseWikiStore): ...  # :579
# :372 — `if kind in ("path", "vault"):` — a vault resolves like a project
#        root, defaulting to <vault>/.parrot/wiki (docstring :206-210)

# packages/ai-parrot/src/parrot/knowledge/okf/ontology.py
class ConceptType(str, Enum): ...   # :29 — Section, Policy, Control, Safeguard,
#   Evidence, Playbook, Procedure, Standard, Framework, Regulation, Guideline,
#   Symbol, Rationale, Skill, Concept, Document, Wiki Summary, Wiki Entity,
#   Wiki Comparison, Wiki Synthesis, Wiki Overview, Run, Claim, Other
#   Design note (docstring :13-14): existing member VALUES must not change.
class RelationType(str, Enum): ...  # :77 — references, maps_to, satisfies,
#   satisfied_by, supersedes, superseded_by, implements, part_of, defines,
#   mentions, explains, contains, extends, summarizes, contradicts, produced,
#   about, supported_by
class RelatesTo(BaseModel):         # :117
    concept: str; rel: RelationType = RelationType.REFERENCES

# packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py
class ConceptFrontmatter(BaseModel): ...                          # :35
def project_frontmatter(node: dict, tree_name: str) -> str: ...   # :101
def parse_frontmatter(text: str) -> ConceptFrontmatter: ...        # :154

# packages/ai-parrot/src/parrot/interfaces/obsidian/models.py:38 — the shape precedent
class ObsidianNote(BaseModel):
    path: Path; title: str; content: str      # content = frontmatter stripped
    frontmatter: dict; links: list[ObsidianLink]
    tags: set[str]; aliases: list[str]; dataview_queries: list[str]

# packages/ai-parrot/src/parrot/auth/jira_oauth.py — ALREADY IN CORE
class JiraTokenSet(BaseModel): ...   # :59
class JiraOAuthManager: ...          # :86

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit): ...                                  # :660
    def __init__(self, server_url=None, auth_type=None, username=None,
        password=None, token=None, oauth_consumer_key=None,
        oauth_key_cert=None, oauth_access_token=None,
        oauth_access_token_secret=None, default_project=None,
        credential_resolver=None, workflow_paths=None,
        verify_credentials=True, **kwargs): ...                          # :731
    def _init_jira_client(self) -> JIRA: ...                             # :955
    def _init_jira_client_from_token(self, token_set: Any) -> JIRA: ...  # :1017
    def _issue_to_dict(self, issue_obj: Any) -> Dict[str, Any]: ...      # :1134
    def _ensure_bounded_jql(self, jql: Optional[str]) -> str: ...        # :1198
    def _extract_field_history(self, changelog_entries, field_name): ... # :1291
    async def _get_full_changelog(self, issue: str, page_size: int = 100) # :1314
    async def jira_get_issue(...)                                        # :1358
    async def jira_get_projects(self) -> Dict[str, Any]: ...             # :2254
    async def jira_search_issues(self, jql: str, start_at: int = 0,
        max_results: Optional[int] = 100, fields: Optional[str] = None,
        expand: Optional[str] = None, json_result: bool = True,
        store_as_dataframe: bool = False, dataframe_name: Optional[str] = None,
        summary_only: bool = False,
        structured: Optional[StructuredOutputOptions] = None,
    ) -> JiraToolEnvelope: ...                                           # :2638
    async def jira_count_issues(self, jql: str,
        group_by: Optional[List[str]] = None) -> Dict[str, Any]: ...     # :2896
# :2173-2177 — API VERSION IS AUTH-DEPENDENT:
#   api_path = "/rest/api/3/myself" if self.auth_type == "oauth2_3lo"
#              else "/rest/api/2/myself"
#   → v3 returns ADF for description, v2 returns wiki markup. Use
#     expand=renderedFields (HTML) to be independent of both.
# :2257-2266 — Jira Cloud returns 200 + empty list + header
#   `X-Seraph-Loginreason: AUTHENTICATED_FAILED` on silently failed auth;
#   an empty result set MUST be probed via /myself, never trusted.
# :767-775 — no auth-type heuristic: unresolved auth_type => unauthenticated
#   state, every call raises AuthorizationRequired.
# :751-760 — `_cfg(key, default)`: navconfig first, then os.getenv.
# :205, :249 — `expand` already documented as accepting 'renderedFields'.

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:68
class SourceCollectionManager:
    def add_source(self, path: Path) -> SourceManifestEntry: ...  # :177 — PATH-shaped
    def mark_ingested(...)                                        # :293
    def record_document_metadata(...)                             # :423
    def find_by_uri(self, source_uri: str) -> str | None: ...     # :497
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `JiraInterface` | `jira.JIRA` | lazy import + `options`/`timeout` kwargs | `jiratoolkit.py:955-1033` |
| `JiraInterface` | `JiraOAuthManager` | per-user token resolution | `auth/jira_oauth.py:86` |
| `JiraToolkit` (refactored) | `JiraInterface` | delegation from read methods | `jiratoolkit.py:1358, 2254, 2638, 2896` |
| `jira_render` | `ConceptType.ISSUE` | frontmatter `type:` value | `okf/ontology.py:29` (member added by M6) |
| `jira_render` | `html2text` | `renderedFields` HTML → markdown | `pyproject.toml:297` (`html2text==2025.4.15`) |
| `jira_sync` | `wiki_write_lock` | output-directory writer guard | `cli.py:77, 1105` |
| `ingest-jira` | `build` / `scan_vault` | invokes existing build with vault mode | `cli.py:1044, 1071-1081, 1118-1133` |
| issues plane | `ns add --store` | one-time namespace registration | `cli.py:1826-1878` |
| ticket ↔ spec | frontmatter `repo_pages` + FTS | text-level join (no edge) | `cli.py:2665-2666` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/knowledge/wiki/sources/jira.py`~~ — **cannot exist.**
  `parrot/knowledge/wiki/sources.py` is already a **module** (40.3 KB,
  `SourceCollectionManager`); a `sources/` package beside it would shadow it
  and break `from .sources import SourceCollectionManager`. Use
  `parrot/interfaces/jira/` plus `wiki/jira_render.py` / `wiki/jira_sync.py`.
- ~~Cross-namespace edges~~ — **explicitly unsupported.** `wikitoolkit link`
  says so verbatim: *"Both pages must live in the same plane — there are no
  cross-namespace edges"* (`cli.py:2665-2666`). `edges.dst` is unconstrained
  TEXT (`store.py:96-99`), so an `issues::…`/`repo::…` string is *physically*
  storable but would be a dangling local id, never a traversable federated
  edge. Do NOT write one.
- ~~`ConceptType.ISSUE` / `.PERSON` / `.PROJECT`~~ — do not exist **yet**;
  they are added by Module 6 and must not be referenced before that lands.
- ~~`RelationType.BLOCKS` / `.DUPLICATES` / `.RELATES_TO`~~ — not in the
  vocabulary (`okf/ontology.py:77-114`) and **not added by this feature**.
  Link precision lives in the frontmatter (`blocks:`, `duplicates:`), while
  the graph edge from a wikilink is `references`.
- ~~`DocumentAcquirer` handling a non-file source~~ — `resolve_sources`
  (`documents.py:154`) yields `DocumentRef`s from paths and URLs only, and
  `_acquire_via_loader` (`:632`) calls a file loader. There is no record/API
  source shape; do not route Jira through it.
- ~~`SourceCollectionManager.add_source(uri: str)`~~ — the parameter is
  `path: Path` (`sources.py:177`). The `sources` table is filesystem-shaped;
  the watermark lives in `.parrot/jira_sync.json` instead.
- ~~`ns add --vault` on a plain directory~~ — the option requires
  `.obsidian/` (`cli.py:1864`, `is_obsidian_vault` at `vault_scan.py:62`).
  Register the issues plane with `--store <dir>/.parrot/wiki`. Only `build`
  has a `--vault` **flag** that forces vault mode without the marker dir.
- ~~An ADF parser anywhere in the repo~~ — none. No `jira2markdown`, no
  `atlassian_doc` module. Use `expand=renderedFields` + `html2text`.
- ~~An existing Jira→markdown renderer~~ — none. The only Jira-to-text code
  is `_apply_structured_output` (`jiratoolkit.py:1254`), which emits dicts
  for an LLM, not documents.
- ~~`wikitoolkit ingest-jira`, `parrot/interfaces/jira/`, `JiraInterface`,
  `JiraIssue`, `IssueFrontmatter`, `JiraSyncState`, `SweepReport`~~ — all
  new in this feature.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Lazy optional dependency**: copy `graphindex/builder.py:667-704`
  (`_loader_for`) — try the import, raise/log an actionable message naming
  the missing distribution, never let `ModuleNotFoundError` escape raw.
- **Shared-interface split**: `parrot/interfaces/obsidian/` is the model —
  the interface owns access + parsing, the toolkit is a thin agent-facing
  skin over it. Keep `JiraToolkit`'s envelope/permission layers in the
  toolkit, not the interface.
- **Determinism**: mirror `documents.render_frontmatter` (fixed key order,
  sorted collections, `None` omitted). Pin `html2text` options explicitly
  (`body_width=0`, `unicode_snob`, no reference links) — its defaults wrap
  lines, which would make output width-dependent.
- **No auth heuristics**: preserve `jiratoolkit.py:767-775` — an unresolved
  `auth_type` must NOT fall back to env credentials.
- **Async-first**: `aiohttp`/`asyncio.to_thread` around the sync `jira`
  client, as `JiraToolkit` already does. No blocking I/O in async paths.
- **Google-style docstrings + strict type hints; pydantic v2 models
  everywhere; `self.logger`, never `print`.**

### Known Risks / Gotchas

- **Silent Jira Cloud auth failure.** 200 + empty list +
  `X-Seraph-Loginreason: AUTHENTICATED_FAILED` (`jiratoolkit.py:2257-2266`).
  An empty page must trigger the `/myself` probe; otherwise the watermark
  advances over a corpus that was never fetched — the worst failure mode
  here, because it is silent and self-perpetuating.
- **Description format varies by auth mode** (ADF on v3, wiki markup on v2,
  `jiratoolkit.py:2173-2177`). Mitigation: `expand=renderedFields` + a
  fixed `html2text` config. A ticket with no rendered field must degrade to
  plain text, never raise.
- **`ConceptType` is enumerated into an LLM prompt.**
  `pageindex/okf/migrate.py:134-138` builds a classification prompt from
  `', '.join(t.value for t in ConceptType)`, and `tools/obsidian.py:749`
  validates against `sorted(item.value for item in ConceptType)`. Adding
  three members widens both. Additive and safe, but M6 must confirm neither
  consumer regresses (a section could now be classified `Issue`).
- **`cli.py` is a 123 KB hot file.** Every wiki feature touches it; expect
  textual conflicts with in-flight wiki work. Keep the new command
  self-contained and append it rather than interleaving edits.
- **`jiratoolkit.py` is contested.** FEAT-138/TASK-948 (envelope flip),
  TASK-953 (error hardening) and the 3LO spec all touch it. The delegation
  refactor must be behavior-preserving; the existing test suites are the
  gate, and they must pass **unchanged** (not adjusted to fit the refactor).
- **Human-region merge is the highest-consequence path.** A bad
  `split_at_marker` silently eats someone's notes. Test trailing whitespace,
  a missing marker, a duplicated marker, and a marker inside a code fence.
- **Unresolved wikilinks are dropped** (`vault_scan.py:183`) — a ticket
  linking outside the JQL scope loses its edge. The key still appears in the
  frontmatter, so nothing is lost; the sweep must report the count so
  operators can widen the JQL.
- **Concurrent writers.** The plane already refuses two writers
  (`wiki_write_lock`, `cli.py:1105`); the emitter needs the same guard on
  the issues directory, or two crons will interleave file writes.
- **Ticket key renames / project moves** leave orphan documents that become
  ghost pages forever unless detected (see `test_orphan_detection`).
- **PII discipline.** Raw Jira payloads carry `emailAddress` on every user
  object. The parse step must drop it at the boundary — not later — so it
  can never reach a document, a plane, or an OKF export.
- **`PARROT_HOME` default.** The corpus root must resolve outside the repo
  even when `PARROT_HOME` is unset; a relative default would write into the
  working tree and violate G8.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `jira` | `>=3.10` (host pins `==3.10.5`) | Jira REST client (pycontribs). Optional extra, lazily imported. `ai-parrot-tools/pyproject.toml:51`; host extras `pyproject.toml:305, 356, 389`. New host `jira` extra added by M7. |
| `html2text` | `==2025.4.15` | `renderedFields` HTML → markdown. Already pinned in the host `agents`/`mcp` extras (`pyproject.toml:297, 351, 384`). |
| `PyYAML` | (existing) | Deterministic frontmatter dump; already used by `documents.py` and `okf/frontmatter.py`. |
| `click` | (existing) | The `wikitoolkit` CLI is click-based. |
| `pydantic` | v2 (existing) | All models. |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree.
- **Rationale**: There is a real parallel seam (M1's interface + M2's
  toolkit refactor vs. M3's pure renderer), but the two files most likely to
  conflict — `cli.py` (123 KB, touched by every wiki feature) and
  `jiratoolkit.py` (contested by FEAT-138, TASK-953 and the 3LO spec) — are
  both hot repo-wide. Sequential tasks in one worktree keep those two edits
  from racing each other and make the single rebase against `dev` cheap. The
  gain from isolating one pure-function task does not pay for a second
  worktree on the same hot files.
- **Task ordering**: M6 (ConceptType) and M1 (interface) first — both are
  leaves. Then M3 (renderer, needs M1 models + M6 enum), then M2 (toolkit
  delegation, needs M1), then M4 (sweep, needs M1+M3), then M5 (CLI, needs
  M4), then M7 (packaging + runbook).
- **Cross-feature dependencies**: FEAT-450 (namespaces) and FEAT-451
  (`ingest`) are both **already merged** — no blocker. The follow-up
  cross-namespace-edge spec is downstream of this one and must NOT be
  waited on.
- **Suggested worktree**:
  ```bash
  git worktree add -b feat-454-jira-extractor-llmwiki \
    .claude/worktrees/feat-454-jira-extractor-llmwiki HEAD
  ```

---

## 8. Open Questions

> Resolved items were decided in the brainstorm (or the spec clarification
> round) and are carried forward for auditability — do not re-open them.

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`,
  `base_branch: dev`.
- [x] Where does the Jira code live, and how do we avoid the Agent depending
  on `JiraToolkit`? — *Resolved in brainstorm*: a shared read interface in
  **core**, lazily importing `jira`, consumed by both `JiraToolkit` and the
  sweep. Path corrected during code research to `parrot/interfaces/jira/`
  (not `wiki/sources/jira.py`, which would shadow the existing
  `wiki/sources.py` module) — see §3 M1 and §6 "Does NOT Exist".
- [x] Deterministic or LLM? — *Resolved in brainstorm*: zero-LLM default;
  opt-in `--enrich`. See G2, §2 CLI, AC "makes zero LLM calls".
- [x] How is the `issues` namespace materialized? — *Resolved in
  brainstorm*: its own plane, built from a folder of one-markdown-per-ticket,
  registered via `ns add --store`. See §2 Overview step 4 and G6.
- [x] Where do the markdown files live? — *Resolved in brainstorm*: outside
  the git repo, configurable, default `${PARROT_HOME}/wikis/issues`. See G8,
  §2 Storage layout, `JIRA_WIKI_ISSUES_DIR`.
- [x] Scope and re-run semantics? — *Resolved in brainstorm*: JQL scope plus
  an `updated >=` watermark, incremental upsert. See G5, `JiraSyncState`, M4.
- [x] Which relations in v1? — *Resolved in brainstorm*: issue links,
  epic/parent↔subtask, person pages, project/component/label pages. See G7.
- [x] How deep does each document go? — *Resolved in brainstorm*: core
  fields + description + acceptance criteria + status history + attachments
  and remote links as references. **Comments excluded from v1.** See §1
  Non-Goals and the AC.
- [x] Auth modes? — *Resolved in brainstorm*: full parity with
  `JiraToolkit`, including OAuth 2.0 3LO. See G1 and M1.
- [x] Person representation? — *Resolved in brainstorm*: display name +
  `accountId` only, **no email**. See G9, `JiraPerson`,
  `test_parse_issue_never_captures_email`.
- [x] Ticket↔spec linkage, given cross-namespace edges do not exist? —
  *Resolved in spec clarification*: **open a follow-up spec extending
  FEAT-450 with cross-namespace edges.** This feature ships the text-level
  join only (frontmatter `repo_pages` + the `**Jira**:` line the repo plane
  already FTS-indexes) and depends on nothing downstream. See §1 Non-Goals.
- [x] Extend `ConceptType`? — *Resolved in spec clarification*: **yes** —
  add `Issue`, `Person`, `Project`. Purely additive; existing values
  unchanged. See G11, M6, and the prompt-widening risk in §7.
- [x] Sync marker in v1? — *Resolved in spec clarification*: **yes.** See
  G4, `SYNC_MARKER`, `split_at_marker`, and the three preservation tests.
- [x] Should `ingest-jira` run the build itself? — *Resolved in spec
  clarification*: **yes, build by default with `--no-build` to opt out.**
  See G10 and §2 CLI surface.
- [x] Where does the watermark live? — *Resolved during spec research*:
  `<issues-dir>/.parrot/jira_sync.json`, keyed by JQL fingerprint and
  carrying `extractor_version` so a renderer change can force a full
  re-render. `.parrot/` is already excluded by `VAULT_EXCLUDE_DIRS`
  (`vault_scan.py:58`), so the state file is never ingested as a note.
  `SourceCollectionManager.add_source` is `Path`-shaped (`sources.py:177`),
  so the `sources` table was not a fit.
- [x] ADF → markdown conversion? — *Resolved during spec research*: the API
  version is auth-dependent (`jiratoolkit.py:2173-2177`), so fetch
  `expand=renderedFields` (HTML, identical on v2 and v3) and convert with
  the already-pinned `html2text`. No ADF parser is written.
- [x] Does the ingest need its own host extra? — *Resolved during spec
  research*: yes, add `jira = ["jira>=3.10"]` to
  `packages/ai-parrot/pyproject.toml` (M7); today it only rides
  `agents`/`mcp`.
- [ ] **Cron cadence and host for the sweep** — daily vs weekly, and which
  machine owns the schedule (developer workstation, CI runner, or a server).
  The runbook must name one; the code is indifferent. — *Owner: Jesus*
- [ ] **Which JQL scope ships as the documented default?** `project = NAV`
  is the obvious start, but the corpus's usefulness depends on whether
  closed/archived tickets and other projects are in scope. Needs a decision
  before the first production sweep, not before implementation. — *Owner: Jesus*
- [ ] **Acceptance-criteria field id.** The AC lives in a custom field whose
  id is instance-specific (`customfield_NNNNN`). Resolve it dynamically by
  field name via `get_projects`/field metadata, or configure it explicitly
  as `JIRA_WIKI_AC_FIELD`? Implementation-time decision. — *Owner: Jesus*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-24 | Jesus Lara (spec: Claude) | Initial draft from `jira-extractor-llmwiki.brainstorm.md` (Option A), with 17 resolved decisions carried forward and 3 open items. |
