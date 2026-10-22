# wikitoolkit standup

*FEAT-627. Spec: `sdd/specs/wikitoolkit-standup.spec.md`.*

`wikitoolkit standup` renders a deterministic brief for a day, week or month.
It reads work items from the wiki knowledge graph and, optionally, adds a short
model summary on top. The same brief is available to agents through the
`wiki_standup` MCP tool. Cron schedules and recovery steps are in the
[standup runbook](../runbooks/wiki-standup.md).

```bash
wikitoolkit standup                               # daily brief: stores a page + writes a file
wikitoolkit standup --period week --language es   # weekly brief, in Spanish
wikitoolkit standup --no-store --no-file          # read-only: print the brief, write nothing
wikitoolkit standup --no-llm --json               # deterministic only, machine-readable
wikitoolkit standup --team                        # everyone's items, not only yours
```

## What a brief contains

### Period and window

| `--period` | Window | Brief page id |
|---|---|---|
| `day` (default) | the anchor date ± the meeting horizon | `brief:daily:<YYYY-MM-DD>` |
| `week` | calendar week, starting on `standup.week_start` (Monday by default) | `brief:weekly:<ISO-year>-W<nn>` |
| `month` | calendar month | `brief:monthly:<YYYY-MM>` |

The anchor date is `--date`. Without it, the anchor is today in
`standup.timezone`, or in the system's local time when that is unset. The
horizon (`--horizon`, else `standup.horizon_days`, default 7) only widens
which **meeting** dates count, and only for `day` briefs.

### Sources

Six collectors run concurrently. When one fails, the failure appears under
**Diagnostics** and the rest of the brief still renders.

| Source | Reads |
|---|---|
| entities | meeting, decision and deliverable attributes on the local plane and every namespace |
| jira | the `issues` namespace: open tickets always, closed tickets only in week/month briefs |
| ledger | open or claimed work-ledger issues. A merge blocker of an in-progress feature is marked urgent. |
| tasks | `sdd/tasks/index/*.json`: tasks that are in progress, or pending with dependencies met |
| decisions | the ADR inventory: proposed or unreviewed decisions, plus accepted ones in week/month briefs |
| memories | note, concept, lesson and decision pages updated inside the window |

Git history is not read.

### Sections

- **`day`:** On your plate (at most 3 bullets), By project, Internal.
- **`week` / `month`:** Closed this period, Still open, Decisions taken, Daily brief sources.
- **Every period:** Since last brief, Hygiene, Diagnostics.

**Hygiene** reports:
- ledger blockers;
- stale decisions (`stale_decision_days`, 14 by default) and stale tickets (`stale_ticket_days`, 10 by default);
- the LLM state;
- unmapped ticket statuses;
- the Jira watermark;
- the number of attributes indexed;
- the last lint run.

### "Since last brief" (delta)

The brief compares its item ids with the items stored on the most recent
*earlier* brief of the **same period**, however old that brief is. There are
only two outcomes:

- **New:** the item is in this brief and was not in the earlier one.
- **Closed:** the item was in the earlier brief and is no longer present.

There is no "updated" state. When no earlier brief was stored, for example
after runs with `--no-store`, the section is empty.

## Options

`wikitoolkit standup --help` lists the option names without descriptions. This table is the reference.

| Option | Default | Meaning |
|---|---|---|
| `--period day\|week\|month` | `day` | Brief period. |
| `--date YYYY-MM-DD` | today | Anchor date. |
| `--horizon N` | `standup.horizon_days` (7) | Meeting horizon in days, from 1 to 90. Only applies to `day`. |
| `--team` | off | Include everyone's items. Cannot be combined with `--me`. |
| `--me ID` | resolved | Wiki identity to filter on, given verbatim (for example `human:jlara`). See [Identity](#identity). |
| `--language en\|es` | `standup.default_language` (`en`) | Brief language. |
| `--json` | off | Print the brief document as JSON instead of Markdown. |
| `--no-llm` | off | Skip the model summary and use the deterministic bullets. |
| `--out DIR` | see [Writes](#writes) | **Directory** for the Markdown file, not a file name. A relative path is resolved against the project root. |
| `--no-store` | off | Do not store the brief as a wiki page. |
| `--no-file` | off | Do not write the Markdown file. |
| `--ns LIST` | all configured | Comma-separated namespaces, or `all`. `--ns local` reads only the local plane. |
| `--path DIR` | auto-detect | Project root. Without it, the command walks up from the current directory looking for `.parrot/wiki.json` or `.git`. |
| `--store DIR` | project store | An **existing** wiki storage directory, used as the only read *and* write plane. Namespaces still come from the project config. |
| `--backend NAME` | config | Override the configured backend. Every backend except `arangodb` requires a built wiki. |

> **Writing is the CLI default.** Without `--no-store` and `--no-file`, every
> run stores a page and writes a file. `--json` and `--no-llm` change only the
> output and the summary. They do not make the run read-only.

## Writes

**Wiki page.** The id is the brief id, with `category="brief"` and
`origin="authored"`. The page carries these attributes: `type=deliverable`,
`status=draft`, date, owner, period, items (JSON), `source=brief` and language.
The page is written under the wiki write lock, and each write appends a
`STANDUP` line to the bookkeeper log.

**Markdown file.** The file name is the brief id with colons replaced by
dashes, for example `brief-daily-2026-10-04.md`. It is written to the first
directory that is set:

1. `--out`
2. `standup.out_dir`
3. `${PARROT_HOME:-~/.parrot}/wikis/briefs`

A file written inside a configured vault also gets vault-marker frontmatter.

The page and the file are written independently. When a write fails, the
failure is recorded as a diagnostic and the command still exits 0.

## Model summary

- The model is read from the environment variable named in `standup.llm_env`,
  which is `WIKI_LIGHTWEIGHT_MODEL` by default. The value has the form
  `provider:model`. No CLI flag selects the model.
- When that variable is unset, the command auto-detects a coding-agent CLI.
  Set `PARROT_NO_AUTO_LLM=1` to turn auto-detection off.
- The model receives at most 40 items: titles cut to 120 characters, with no
  bodies, URLs or owners. The call runs at temperature 0 with a 20-second
  timeout, and must return 1 to 3 bullets.
- When the call fails or returns something unusable, the brief falls back to
  3 deterministic ranked bullets and is still stored. The Hygiene `LLM:` line
  reports one of `ok`, `skipped: disabled`, `skipped: no model` or
  `failed: <reason>`.
- The summary is shown only in `day` briefs. For `week` and `month` the model
  is still called, but its bullets are not rendered. Use `--no-llm` there to
  avoid the call.

## Identity

The wiki identity used to filter "your" items is the first one found:

1. `standup.me.wiki` in `.parrot/wiki.json`. This takes precedence over `--me`.
2. `--me`.
3. `agent:$CLAUDE_AGENT_ID` or `agent:$PARROT_AGENT_ID`.
4. `human:<OS user>`.

Owners are compared verbatim, so pass the full identity: `--me human:jlara`,
not `--me jlara`. Use `standup.me.aliases` to list extra owner strings that
should also count as you.

The Jira identity is resolved in this order:

1. `standup.me.jira_account_id` in the config.
2. The cache `${PARROT_HOME}/jira_identity.json`, with the keys `account_id`,
   `display_name` and `resolved_at`.
3. A live Jira `myself()` call, which also fills the cache.

The live call happens only on runs that write. Read-only runs never contact
Jira.

## Configuration

Settings live under the `standup` key of `.parrot/wiki.json`. Every field is
optional, and unknown keys are rejected.

```json
{
  "standup": {
    "default_language": "en",
    "horizon_days": 7,
    "timezone": "America/New_York",
    "week_start": "monday",
    "out_dir": null,
    "me": {
      "wiki": "human:jlara",
      "aliases": [],
      "jira_account_id": null,
      "jira_display_name": null
    },
    "ticket_status_map": {},
    "project_map": {},
    "stale_ticket_days": 10,
    "stale_decision_days": 14,
    "llm_env": "WIKI_LIGHTWEIGHT_MODEL"
  }
}
```

- `ticket_status_map` maps raw Jira status names (case-insensitive) to one of
  the canonical statuses `open`, `in-progress`, `blocked`, `in-review` or
  `closed`. A map you supply replaces the built-in one. Statuses left
  unmapped are listed under Hygiene.
- `project_map` maps a Jira project key or SDD feature slug to the project
  page id or label used under "By project". Items that match nothing are
  grouped under "Internal".

## MCP tool: `wiki_standup`

Over MCP the tool is **read-only and makes no model call by default**. Writing
the page, writing the file and calling the model each need an explicit opt-in.

| Parameter | Default | Meaning |
|---|---|---|
| `period` | `"day"` | `day`, `week` or `month` |
| `date` | today | Anchor date, `YYYY-MM-DD` |
| `team` | `false` | Include team items |
| `horizon_days` | config | Meeting horizon, from 1 to 90 |
| `language` | config | `en` or `es` |
| `store` | `false` | Store the brief as a wiki page on the local plane |
| `write_file` | `false` | Also write the Markdown file |
| `use_llm` | `false` | Allow the model summary |

The tool has no `me` or `ns` parameter. It returns `markdown`, `brief_id`,
`written_page`, `written_file` and `diagnostics`. It is registered only when
the MCP server has a project root and config.

## Exit codes

| Code | When |
|---|---|
| `0` | The brief rendered. This includes runs where a source or a write failed; those failures appear under Diagnostics. |
| `1` | No project was found, `--path` is not a directory, the `--store` directory is missing, the wiki is not built ("Wiki not built yet"), the wiki config is invalid, or a store error occurred. |
| `2` | Usage error: `--team` combined with `--me`, an invalid choice, `--horizon` outside 1–90, or a bad `--date` format. |

## Related: `wikitoolkit entity`

FEAT-627 also added the `entity` group, which manages the typed attributes
(meeting, decision, deliverable) that the entities collector reads. It has
three subcommands: `entity add`, `entity list` and `entity reindex`.

`entity reindex` back-fills attributes into a plane that was built before
attributes existed:

```bash
wikitoolkit entity reindex --dry-run      # report what would change
wikitoolkit entity reindex                # rewrite attributes (takes the write lock, logs REINDEX)
wikitoolkit entity reindex --store "${PARROT_HOME:-$HOME/.parrot}/wikis/issues/<storage-dir>"
```

| Option | Meaning |
|---|---|
| `--category` | Only reindex pages of this category. |
| `--dry-run` | Count only. Nothing is written. |
| `--ns` | Only `local` is accepted. |
| `--path` / `--store` / `--backend` | Select the plane. The precedence is `--store`, then `--path`, then the `WIKI_STORE` environment variable, then the detected project. A missing `--store` directory **is created**. |

- The command needs a backend that supports attributes, which today means SQLite.
- It skips `authored` and `memory` pages, and it rewrites only attributes,
  never page bodies.
- It prints the counts of pages scanned, updated, unchanged and skipped.
