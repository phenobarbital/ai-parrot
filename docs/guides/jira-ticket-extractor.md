# Jira Ticket Extractor → LLM Wiki (`issues` namespace)

> **FEAT-454** — Extract Jira tickets into the LLM Wiki as a federated
> `issues` namespace, queryable via `wikitoolkit query --ns issues` and the
> MCP `wiki_query` tool.

## Overview

The Jira Ticket Extractor converts your Jira ticket corpus into a
machine-first knowledge graph — one markdown document per ticket, built into
a queryable wiki plane, and federated alongside the codebase wiki. This lets
Claude Code (and any agent) answer questions like *"what do we already know
about the forms tenant-in-URL problem?"* with ranked retrieval across every
ticket, without making ad-hoc JQL calls.

**Key properties:**

- **Zero-LLM by default** — every field is a Jira field or a pure function of
  one. No model calls, no cost, deterministic output.
- **Incremental** — a watermark tracks the last `updated` timestamp per JQL
  scope; re-runs fetch only changed tickets.
- **Off-repo storage** — generated markdown lives outside the git repo (default
  `~/.parrot/wikis/issues`), so internal ticket prose and customer names never
  enter git history.
- **Human annotations survive** — content you write below the
  `<!-- jira-sync:end -->` marker is preserved byte-for-byte on every re-sync.
- **Federated** — once registered, the `issues` namespace appears in the
  default `wikitoolkit query` broadcast and in the MCP tools.

---

## Installation

The Jira extractor requires the `jira` extra of the `ai-parrot` package:

```bash
# Install the jira extra
pip install 'ai-parrot[jira]'

# Or with uv (inside your venv)
source .venv/bin/activate
uv pip install -e 'packages/ai-parrot[jira]'
```

This installs the `jira` client library and `html2text` (for converting Jira's
rendered HTML descriptions to markdown).

Verify:

```bash
python -c "import jira, html2text; print('OK')"
```

---

## Credentials

The extractor reuses the same credential keys as `JiraToolkit`. Set them via
environment variables or `navconfig`:

| Variable | Required | Description |
|---|---|---|
| `JIRA_INSTANCE` | **Yes** | Your Jira instance URL (e.g. `https://yourcompany.atlassian.net`) |
| `JIRA_AUTH_TYPE` | **Yes** | One of: `basic`, `token`, `oauth1`, `oauth2_3lo` |
| `JIRA_USERNAME` | For `basic` | Jira username |
| `JIRA_API_TOKEN` | For `basic`/`token` | API token (Atlassian account → API tokens) |
| `JIRA_SECRET_TOKEN` | For `token` | Alternative to `JIRA_API_TOKEN` |
| `JIRA_OAUTH_*` | For `oauth1` | OAuth 1.0 consumer key, key cert, access token, access token secret |
| `JIRA_REQUEST_TIMEOUT` | No | Request timeout in seconds (default: 30) |

### Auth modes

1. **`basic`** — email + API token. Simplest for Jira Cloud.
2. **`token`** — personal access token (PAT). Common for Jira Data Center.
3. **`oauth1`** — OAuth 1.0a with RSA key pair. For Jira Server/DC integrations.
4. **`oauth2_3lo`** — OAuth 2.0 three-legged. Per-user tokens via
   `JiraOAuthManager`. Uses API v3 (ADF descriptions), but the extractor
   requests `expand=renderedFields` (HTML) to be format-independent.

> **⚠️ Important**: `JIRA_AUTH_TYPE` has **no default**. Leaving it unset
> means every call raises `AuthorizationRequired`. The extractor does not
> guess credentials — this is by design.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `JIRA_WIKI_ISSUES_DIR` | `${PARROT_HOME}/wikis/issues` | Corpus root directory (off-repo) |
| `JIRA_WIKI_JQL` | `project = ${JIRA_DEFAULT_PROJECT}` | Default sweep scope |
| `JIRA_WIKI_NAMESPACE` | `issues` | Namespace name for registration |
| `JIRA_WIKI_AC_FIELD` | *(auto-resolved by field name)* | Custom field ID for Acceptance Criteria |
| `PARROT_HOME` | `~/.parrot` | Parent directory for all parrot data |

> **⚠️ Warning**: Do **not** point `JIRA_WIKI_ISSUES_DIR` inside a git
> checkout. The corpus contains internal ticket prose and customer names that
> must never enter git history (Goal G8).

### Default JQL scope

The shipped default is `project = ${JIRA_DEFAULT_PROJECT}` — a single project,
**no status filter**, **no date bound**. Closed and resolved tickets are kept
in scope deliberately: institutional knowledge lives mostly in finished work.

The watermark supplies incrementality, so the unbounded scope costs one full
backfill on the first run and near-zero afterward. To widen to more projects:

```bash
# Multi-project
export JIRA_WIKI_JQL="project in (NAV, PLAT, OPS)"

# Everything (use with caution on large instances)
export JIRA_WIKI_JQL="project is not EMPTY"
```

### Acceptance Criteria field

Jira Cloud uses custom fields for Acceptance Criteria. The extractor resolves
the field ID automatically by name from `GET /rest/api/2/field` (matching
"Acceptance Criteria" case-insensitively). If auto-resolution fails, set
`JIRA_WIKI_AC_FIELD` to your custom field ID (e.g. `customfield_10035`). When
neither resolves, the AC section is simply omitted — the extractor never raises
and never guesses.

---

## One-Time Setup: Namespace Registration

After the first successful sweep (or after building the plane manually), you
must register the `issues` namespace **once**. This is a required operator
action — `ingest-jira` never self-registers.

```bash
wikitoolkit ns add issues \
  --store ~/.parrot/wikis/issues/.parrot/wiki \
  --global \
  --description "Jira ticket corpus"
```

- **`--store`** points at the pre-built store directory containing `wiki.db`.
  Do **not** use `--vault` (it requires `.obsidian/`, which this corpus does
  not have).
- **`--global`** writes to `~/.parrot/wikis.json` (per-user) instead of the
  repo's `.parrot/wiki.json`, so the namespace is available across all
  projects.

Verify the registration:

```bash
wikitoolkit ns list
# Should show: issues  store  ~/.parrot/wikis/issues/.parrot/wiki
```

---

## Running the Sweep

### One-time full backfill

```bash
wikitoolkit ingest-jira
```

This fetches every ticket matching the JQL scope, renders one markdown document
per ticket, builds the wiki plane, and advances the watermark. The first run
may take several minutes for large projects.

### Incremental daily sweep (recommended)

After the initial backfill, schedule a daily cron job:

```cron
# Daily Jira → issues-namespace sweep (FEAT-454)
# Host: <your-machine>  |  Adjust path to your checkout/venv
17 6 * * *  cd /path/to/checkout && \
  /path/to/.venv/bin/wikitoolkit ingest-jira --quiet \
  >> /var/log/parrot/jira-ingest.log 2>&1
```

The incremental run fetches only tickets with `updated >=` the stored
watermark, so it is fast and cheap.

### CLI options

```
wikitoolkit ingest-jira [OPTIONS]

  --jql TEXT           JQL scope (default: JIRA_WIKI_JQL)
  --project TEXT       Shorthand for `project = <KEY>`
  --since DATE         Override the stored watermark (ISO-8601)
  --issues-dir PATH    Output directory (default: JIRA_WIKI_ISSUES_DIR)
  --build/--no-build   Build the plane after emitting (default: build)
  --enrich             Opt-in LLM summary for thin descriptions (default: off)
  --force              Re-render every issue, ignoring the watermark
  --dry-run            Report what would change; write nothing
  --json               Emit the SweepReport as JSON
  -q, --quiet          Only the final summary line
```

---

## Querying the Issues Namespace

Once the sweep has run and the namespace is registered:

```bash
# Search across all namespaces (including issues)
wikitoolkit query "forms tenant-in-URL problem"

# Search only the issues namespace
wikitoolkit query --ns issues "forms tenant-in-URL problem"

# Read a specific ticket page
wikitoolkit page issues::file:NAV-9372.md

# Follow relations (linked tickets, epic, person/project pages)
wikitoolkit related issues::file:NAV-9372.md
```

### From Claude Code / MCP tools

The same operations are available as MCP tools:

```
wiki_query("forms tenant-in-URL problem")              # searches all namespaces
wiki_query("forms tenant-in-URL problem", namespace="issues")
wiki_page("issues::file:NAV-9372.md")
wiki_related("issues::file:NAV-9372.md")
```

No extra MCP configuration is needed — the wikitoolkit MCP server resolves
registered namespaces at startup.

---

## Storage Layout

```
~/.parrot/wikis/issues/              # JIRA_WIKI_ISSUES_DIR
├── NAV-9372.md                      # one document per ticket
├── NAV-9373.md
├── people/
│   └── jesus-lara.md                # person pages (accountId-derived slug)
├── projects/
│   └── NAV.md                       # project roll-up
├── components/
│   └── navigator-forms.md           # component roll-up
├── labels/
│   └── multitenant.md               # label roll-up
└── .parrot/
    ├── jira_sync.json               # watermark + extractor version (state)
    └── wiki/
        └── wiki.db                  # the queryable plane (built by wikitoolkit)
```

### Document structure

Each ticket document has deterministic OKF frontmatter:

```yaml
---
type: Issue
key: NAV-9372
title: "Forms: tenant-in-URL double-encoding breaks …"
status: In Progress
category: Bug
project: NAV
priority: High
assignee: Jesus Lara
assignee_id: 557058:abcdef12-3456-…
labels:
  - multitenant
components:
  - navigator-forms
epic: NAV-9100
blocks:
  - NAV-9380
relates:
  - NAV-9250
url: https://yourcompany.atlassian.net/browse/NAV-9372
sync:
  fetched_at: "2026-08-24T06:17:00Z"
  extractor_version: 1
---

# NAV-9372: Forms: tenant-in-URL double-encoding breaks …

## Description

[… converted from Jira's rendered HTML via html2text …]

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Status History

| Date | Field | From | To | Author |
|---|---|---|---|---|
| 2026-08-20 | status | Open | In Progress | Jesus Lara |

## References

### Attachments
- screenshot.png (145 KB) — https://…

### Remote Links
- Figma mockup — https://figma.com/…

<!-- jira-sync:end — everything below is yours; the extractor never touches it -->
```

### Human annotations

Everything below the `<!-- jira-sync:end -->` marker is yours. Write notes,
context, decisions — the extractor preserves it byte-for-byte on every re-sync:

```markdown
<!-- jira-sync:end — everything below is yours; the extractor never touches it -->

## My Notes

This is the same root cause as NAV-9250 — the URL encoder runs twice when
the tenant slug contains a hyphen. See the fix attempt in PR #1847.
```

---

## Re-Rendering Everything

Two paths force a full re-render:

### 1. The `--force` flag

```bash
wikitoolkit ingest-jira --force
```

Ignores the stored watermark and re-renders every ticket in scope. Use this
when you change the JQL scope or want to pick up formatting improvements.

### 2. Extractor version bump

When the renderer code changes in a way that affects output (e.g. a new
frontmatter field, a changed section layout), `EXTRACTOR_VERSION` in
`jira_render.py` is incremented. On the next sweep, every document whose
`sync.extractor_version` is lower than the current version is re-rendered,
even if the ticket has not changed in Jira.

---

## Reading a SweepReport

The sweep emits a `SweepReport` (visible with `--json`):

```json
{
  "fetched": 142,
  "written": 38,
  "unchanged": 104,
  "skipped": 0,
  "orphaned": 2,
  "entity_notes": 15,
  "unresolved_link_keys": ["PLAT-501", "OPS-200"],
  "watermark_advanced": true,
  "errors": []
}
```

| Field | Meaning |
|---|---|
| `fetched` | Total issues returned by the JQL query |
| `written` | Documents that were created or updated |
| `unchanged` | Documents whose rendered output was byte-identical (file untouched) |
| `skipped` | Issues skipped due to errors (individual, not fatal) |
| `orphaned` | Documents on disk whose key is no longer in scope (ticket moved/renamed) |
| `entity_notes` | Person/project/component/label notes written |
| `unresolved_link_keys` | Tickets linked from rendered documents but not in scope — the edge is dropped but the key stays in frontmatter. **Fix**: widen `JIRA_WIKI_JQL` if those edges matter. |
| `watermark_advanced` | `true` on a clean run; `false` on failure or `--dry-run` |
| `errors` | Error messages from individual ticket failures |

### Run status

The watermark file (`jira_sync.json`) records `last_run_status`:

- **`ok`** — clean run, watermark advanced.
- **`partial`** — some tickets failed mid-sweep. Watermark is **not** advanced
  so the next run retries them. The process exits non-zero so cron mail
  surfaces it.
- **`failed`** — the sweep could not start (auth failure, network error).
  Watermark unchanged.

---

## What Is NOT Synced in v1

- **Comments** — excluded (largest token contributor, most churn). Planned for
  a future version.
- **Attachment payloads** — recorded as references only (filename, size, URL).
  Nothing is downloaded.
- **Cross-namespace graph edges** — `wikitoolkit related` cannot traverse from
  a ticket to a repo spec. The ticket↔spec join is **text-level**: frontmatter
  `repo_pages` field plus FTS. Use `wikitoolkit query` across namespaces to
  find the connection. A follow-up spec extending FEAT-450 will add real
  federated edge traversal.

### PII posture

Person pages carry **display name and `accountId` only**. No email address is
ever captured — the parser drops `emailAddress` at the Jira→model boundary
before any document or plane can see it (Goal G9).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every call raises an auth error | `JIRA_AUTH_TYPE` is unset — there is **no** heuristic default | Set `JIRA_AUTH_TYPE` explicitly |
| Sweep reports 0 fetched, run marked `partial` | Jira Cloud silent auth failure (`X-Seraph-Loginreason: AUTHENTICATED_FAILED`) — watermark did **not** advance | Re-check credentials; try `curl` against `/rest/api/2/myself` |
| `query --ns issues` finds nothing after a successful sweep | The namespace was never registered | Run the `wikitoolkit ns add` command (see [One-Time Setup](#one-time-setup-namespace-registration)) |
| `unresolved_link_keys` is non-empty | A ticket links outside the JQL scope; the edge is dropped but the key is still in frontmatter | Widen `JIRA_WIKI_JQL` if the edge matters |
| A large `orphaned` count | Tickets moved to another project or were renamed | Review orphan documents; they are never auto-deleted |
| Acceptance Criteria section missing | The AC custom field did not resolve | Set `JIRA_WIKI_AC_FIELD` to your custom field ID |
| `related` does not reach a repo spec from a ticket | Cross-namespace edges do not exist in v1 | Use `wikitoolkit query` across namespaces instead |
| `ModuleNotFoundError: jira` | The `jira` extra is not installed | `pip install 'ai-parrot[jira]'` |
| Plane is stale after a sweep | `--no-build` was passed, or the build step failed | Run `wikitoolkit build --vault ~/.parrot/wikis/issues` manually |

---

## Architecture

```
                    parrot/interfaces/jira/          (shared Jira read interface)
                    ├── models.py  JiraIssue, JiraPerson, JiraIssueLink, …
                    └── client.py  JiraInterface (auth + reads + parse)
                              │
              ┌───────────────┴────────────────┐
              │                                │
   parrot_tools/jiratoolkit.py      parrot/knowledge/wiki/jira_sync.py
   JiraToolkit  (delegates)         sweep: scope → fetch → render → write
   agent-facing envelope layer                │         │
                                              │         └──→ jira_render.py
                                              │              pure: JiraIssue → md
                                              ▼
                                   <issues-dir>/*.md  +  .parrot/jira_sync.json
                                              │
                                              ▼
                        wikitoolkit build --vault   (existing, untouched)
                                              │
                                              ▼
                        <issues-dir>/.parrot/wiki/wiki.db
                                              │
                        wikitoolkit ns add issues --store …  (one-time)
                                              │
                                              ▼
              wikitoolkit query --ns issues   /   wiki_query MCP tool
```

---

## See Also

- [WikiToolkit as Claude Code infrastructure](../wiki-claude-code.md) —
  codebase wiki setup and namespaces
- [LLM Wiki architecture](../llm-wiki.md) — PageIndex + GraphIndex +
  Ontology layers
- Spec: `sdd/specs/jira-extractor-llmwiki.spec.md`
