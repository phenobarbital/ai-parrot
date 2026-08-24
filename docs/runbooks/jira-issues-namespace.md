# Runbook — the `issues` namespace (Jira ticket corpus)

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki
**Audience**: operators running the daily sweep; Claude Code sessions
querying the corpus.
**Status**: current.

---

## What this is

Every Jira ticket matching a JQL scope is extracted into one deterministic
markdown document, plus satellite person/project/component/label notes,
under an off-repo corpus directory. `wikitoolkit build --vault` turns that
folder into a queryable, navigable SQLite plane — the same retrieval plane
`wikitoolkit query`/`page`/`related` already serve for the repository
itself — reachable as its own federated namespace (`--ns issues`,
FEAT-450).

Zero-LLM by default (G2): every frontmatter field is a Jira field or a
pure function of one, so an unchanged ticket produces byte-identical
output and a daily cron writes nothing when nothing changed.

## Install

```bash
source .venv/bin/activate
pip install 'ai-parrot[jira]'
# or, inside this monorepo's workspace:
uv pip install -e 'packages/ai-parrot[jira]'
python -c "import jira, html2text; print(jira.__version__, html2text.__file__)"
```

`jira` (pycontribs) and `html2text` are optional — every FEAT-454 module
imports them lazily, so `wikitoolkit --help` and every other command work
with neither installed. Only `wikitoolkit ingest-jira` needs them, and
fails with a single actionable line (naming this same install command) if
they are absent — never a raw traceback.

## Credentials

Reused verbatim from `JiraToolkit` — no new credential surface:

| Key | Purpose |
|---|---|
| `JIRA_INSTANCE` | Jira base URL (e.g. `https://yourcompany.atlassian.net`) |
| `JIRA_AUTH_TYPE` | One of `basic_auth`, `token_auth`, `oauth`, `oauth2_3lo` |
| `JIRA_USERNAME` | Basic-auth username |
| `JIRA_API_TOKEN` / `JIRA_PASSWORD` | Basic-auth secret |
| `JIRA_SECRET_TOKEN` | Personal Access Token (`token_auth`) |
| `JIRA_OAUTH_CONSUMER_KEY`, `JIRA_OAUTH_KEY_CERT`, `JIRA_OAUTH_ACCESS_TOKEN`, `JIRA_OAUTH_ACCESS_TOKEN_SECRET` | OAuth 1.0a (`oauth`) |
| `JIRA_REQUEST_TIMEOUT` | HTTP timeout in seconds (default `30`) |

**`JIRA_AUTH_TYPE` has no default.** Unlike some config keys, there is no
heuristic fallback — leaving it unset means every read call raises rather
than silently guessing a mode or falling back to a shared service account.
Set it explicitly.

For OAuth 2.0 (3LO), the corpus sweep authenticates the same way
`JiraToolkit` does via `JiraOAuthManager` — see that toolkit's own docs for
the per-user authorization flow. A cron sweep normally uses `basic_auth` or
`token_auth` (a service account), since 3LO is inherently per-human-user.

## One-time setup

The sweep only **emits markdown and builds the local plane** — it never
registers a namespace. Run this once, by hand, after the first successful
sweep:

```bash
wikitoolkit ns add issues \
  --store "${PARROT_HOME:-$HOME/.parrot}/wikis/issues/.parrot/wiki" \
  --global \
  --description "Jira ticket corpus"
```

- `--store` (not `--vault`): the issues directory has no `.obsidian/`
  marker, and `ns add --vault` requires one. `--store` points directly at
  a pre-built plane directory.
- `--global` writes `PARROT_HOME/wikis.json` (per-user), not this repo's
  `.parrot/wiki.json` — the ticket corpus is not part of any one
  repository.
- **This step is required.** `ingest-jira` never self-registers a
  namespace by design — `ns add` is documented as *"the only writer of
  namespace entries"* — so a successful sweep followed by
  `query --ns issues` finding nothing almost always means this step was
  skipped.

Verify:

```bash
wikitoolkit ns list --json | grep issues
```

## The daily sweep

```cron
# Daily Jira -> issues-namespace sweep (FEAT-454). Host: <FILL IN — operator choice>.
17 6 * * *  cd /path/to/checkout && \
  /path/to/.venv/bin/wikitoolkit ingest-jira --quiet \
  >> /var/log/parrot/jira-ingest.log 2>&1
```

Daily cadence is the resolved default (spec §8) — the code is indifferent
to cadence or host; both are operator choices. `ingest-jira` builds the
plane by default (G10), so the cron line above is the entire pipeline: no
separate `build` step is needed. A `"partial"` run (see below) exits
non-zero, so cron's own mail-on-failure already surfaces it — no extra
alerting wiring required.

## Querying it

```bash
wikitoolkit query --ns issues "tenant in the URL"
wikitoolkit page issues::file:NAV-9372.md
wikitoolkit related issues::file:NAV-9372.md
```

`related` follows the `[[KEY]]` wikilinks the renderer emits (epic,
parent, subtasks, blocks/duplicates/relates) plus the person/project pages
— all derived by the existing, unmodified `scan_vault`, never written as
edges by this feature directly.

## Scope: the default JQL and how to widen it

The shipped default (spec §8, resolved) is:

```
JIRA_WIKI_JQL   (unset) ->  project = ${JIRA_DEFAULT_PROJECT}
```

A single project, **no status filter, no date bound** — closed and
resolved tickets are in scope deliberately, since "what do we already know
about X" is answered mostly by finished work. The first run over this
scope is a full backfill; the stored watermark (`updated >=`) makes every
run after that fetch only what changed.

To widen scope, set `JIRA_WIKI_JQL` to any valid JQL, or pass `--jql`/
`--project` per invocation:

```bash
wikitoolkit ingest-jira --jql 'project in (NAV, FORMS) AND updated >= -30d'
wikitoolkit ingest-jira --project NAV
```

Changing the JQL starts a **new watermark scope** (keyed by a fingerprint
of the normalized JQL) — the old scope's watermark is untouched, so
widening never silently loses history for the narrower scope.

## Re-rendering everything

Two independent ways to force a full re-render, ignoring the stored
watermark:

- **`--force`** — re-fetches every issue in the JQL scope this run,
  regardless of the watermark. A byte-identical render still counts as
  `unchanged` and is not rewritten (mtime untouched).
- **An `EXTRACTOR_VERSION` bump** (code change, `parrot.knowledge.wiki
  .jira_render.EXTRACTOR_VERSION`) — the sweep detects a scope's stored
  `extractor_version` is older than the running code's and automatically
  forces a full re-render for that scope, even when `updated` is
  unchanged. This is how a renderer bugfix reaches already-synced tickets
  without an operator needing to remember `--force`.

```bash
wikitoolkit ingest-jira --force
```

## Reading a `SweepReport`

`ingest-jira` prints a summary (or `--json`/`-q` for machine/short output):

| Field | Meaning |
|---|---|
| `fetched` | Issues returned by this run's JQL |
| `written` | Documents actually rewritten (bytes changed) |
| `unchanged` | Byte-identical renders, left untouched |
| `orphaned` | Documents on disk whose key fell out of scope (full sweeps only — **never** deleted) |
| `entity_notes` | Person/project/component/label notes emitted this run |
| `unresolved_link_keys` | Relation targets that fell outside the JQL scope, so `scan_vault` dropped their edge (the key still survives in frontmatter) |
| `watermark_advanced` | `true` only after a fully successful pass |
| `errors` | Non-empty means the run is `"partial"` — the watermark was **not** advanced |

A non-empty `unresolved_link_keys` is not a bug — it is the signal to
widen `JIRA_WIKI_JQL` if that relation matters for the corpus. A
`"partial"` run means exactly what it says: something failed mid-sweep,
the watermark was deliberately left untouched so the next run does not
trust an incomplete pass, and `ingest-jira` exits non-zero.

## Your own notes survive every re-sync

Every generated document and every satellite note ends with:

```
<!-- jira-sync:end — everything below is yours; the extractor never touches it -->
```

Anything you (or a teammate) write **below** that line survives every
future re-sync byte-for-byte, forever — the extractor only ever owns the
region above it. A hand-created file with no marker gains one on first
sync; nothing in it is discarded.

## What is not synced in v1

- **Comments.** Explicitly out of scope — the largest token contributor
  and highest-churn field on re-sync.
- **Attachment payloads.** Recorded as references only (filename, size,
  URL) — nothing is downloaded.
- **Cross-namespace edges.** `wikitoolkit link` refuses them outright:
  *"Both pages must live in the same plane — there are no cross-namespace
  edges"*. A ticket ↔ repo-spec relationship is a **text-level join
  only** — the frontmatter `repo_pages` list plus the `**Jira**:` line the
  repo plane already FTS-indexes, findable by `query`, openable by `page`,
  **not** traversable by `related`. Real federated edge traversal across
  namespaces is deferred to a follow-up spec extending FEAT-450.
- **PII beyond display name.** Person pages carry `displayName` and
  `accountId` only — no email address is ever captured (G9). The parse
  boundary drops `emailAddress` before it can reach any model, document,
  or export.

## G8 — keep the corpus out of git

The default corpus root (`${PARROT_HOME}/wikis/issues`) resolves outside
the repository working tree even when `PARROT_HOME` is unset. **Do not**
point `JIRA_WIKI_ISSUES_DIR` at a path inside a git checkout — internal
ticket prose and customer names must never enter git history.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every call raises an auth error | `JIRA_AUTH_TYPE` unset — there is **no** heuristic default | Set it explicitly |
| Sweep reports 0 fetched, run marked `"partial"` | Jira Cloud silent auth failure (`X-Seraph-Loginreason: AUTHENTICATED_FAILED`) — the watermark deliberately did **not** advance | Re-check/rotate credentials |
| `query --ns issues` finds nothing after a successful sweep | The namespace was never registered — `ns add` is a required one-time step | Run the `ns add` command above |
| `unresolved_link_keys` is non-empty | A ticket links outside the JQL scope; the edge is dropped but the key is still in the frontmatter | Widen `JIRA_WIKI_JQL` if the relation matters |
| A large `orphaned` count | Tickets moved project, were renamed, or the JQL narrowed | Review; documents are never auto-deleted |
| Acceptance-criteria section missing from a ticket | The AC custom field did not resolve (no `JIRA_WIKI_AC_FIELD` and no by-name match) | Set `JIRA_WIKI_AC_FIELD` to the exact custom field id |
| `related` does not reach a repo spec | Cross-namespace edges do not exist by design | Use `query` across namespaces instead of `related` |

---

## Configuration reference

| Key | Default | Purpose |
|---|---|---|
| `JIRA_WIKI_ISSUES_DIR` | `${PARROT_HOME}/wikis/issues` | Off-repo corpus root (G8) |
| `JIRA_WIKI_JQL` | `project = ${JIRA_DEFAULT_PROJECT}` | Default sweep scope |
| `JIRA_WIKI_NAMESPACE` | `issues` | Namespace name this runbook registers |
| `JIRA_WIKI_AC_FIELD` | (unset) | Acceptance-criteria custom field id; falls back to a by-name match, else the section is omitted |
| `JIRA_INSTANCE`, `JIRA_AUTH_TYPE`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `JIRA_SECRET_TOKEN`, `JIRA_OAUTH_*`, `JIRA_REQUEST_TIMEOUT` | (existing) | Reused verbatim from `JiraToolkit` |

## CLI reference

```
wikitoolkit ingest-jira --help
```

```
--jql TEXT              JQL scope (default: JIRA_WIKI_JQL, or `project =
                        <JIRA_DEFAULT_PROJECT>`).
--project TEXT          Shorthand for `project = <KEY>`.
--since TEXT            Override the stored watermark (ISO-8601).
--issues-dir DIRECTORY  Output directory (default: JIRA_WIKI_ISSUES_DIR or
                        ${PARROT_HOME}/wikis/issues).
--build / --no-build    Build the plane after emitting (FEAT-454, G10).
                        [default: build]
--enrich                Opt-in LLM summary for thin descriptions — not
                        implemented in v1.
--force                 Re-render every issue in scope, ignoring the stored
                        watermark.
--dry-run               Report what would change; write nothing at all.
--json                  Emit the SweepReport as JSON.
-q, --quiet             Only print the final summary line.
```

## See also

- Spec: `sdd/specs/jira-extractor-llmwiki.spec.md`
- Shared read interface: `packages/ai-parrot/src/parrot/interfaces/jira/`
- Renderer: `packages/ai-parrot/src/parrot/knowledge/wiki/jira_render.py`
- Sweep: `packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py`
- CLI command: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  (`ingest-jira`)
