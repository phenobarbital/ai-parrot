# Wiki standup briefs — runbook

Operational procedures for `wikitoolkit standup` (FEAT-627). The command
reference covers options, sections, identity, configuration and the MCP tool:
see [docs/wiki/standup.md](../wiki/standup.md). Run every command inside an
activated virtual environment.

## Generate a brief

```bash
wikitoolkit standup                                  # daily: stores the page and writes the file
wikitoolkit standup --period week                    # weekly
wikitoolkit standup --period month --language es     # monthly, in Spanish
wikitoolkit standup --no-store --no-file             # read-only: print only
wikitoolkit standup --no-store --no-file --json      # read-only, JSON output
wikitoolkit standup --team                           # everyone's items
wikitoolkit standup --me human:jlara                 # a specific identity (full form)
wikitoolkit standup --out ./standups                 # --out is a DIRECTORY
```

The file is written as `<out>/brief-daily-YYYY-MM-DD.md`, or
`brief-weekly-…` or `brief-monthly-…` for the other periods. Without `--out`,
the directory is `standup.out_dir`, else `${PARROT_HOME:-~/.parrot}/wikis/briefs`.

## Schedule

Run the brief after the daily Jira sweep, so the `issues` namespace is
current. A cron example:

```cron
# Daily brief at 07:00 UTC, Monday–Friday
0 7 * * 1-5 cd /PATH/TO/PROJECT && /PATH/TO/.venv/bin/wikitoolkit standup --period day --out /var/lib/standups >> /var/log/standup.log 2>&1

# Weekly brief on Monday at 07:05 UTC
5 7 * * 1 cd /PATH/TO/PROJECT && /PATH/TO/.venv/bin/wikitoolkit standup --period week --out /var/lib/standups >> /var/log/standup.log 2>&1
```

Replace `/PATH/TO/PROJECT` and `/PATH/TO/.venv` with deployment-specific
paths. Do not put a date in `--out`, because the command names the file itself.

To keep the brief stable and deterministic in cron, set the model explicitly
with `WIKI_LIGHTWEIGHT_MODEL=provider:model`. Alternatively, pass `--no-llm`
and set `PARROT_NO_AUTO_LLM=1`, so the run neither auto-detects a
coding-agent CLI nor calls a model.

## Failure behaviour

- A failing source (Jira, ledger, tasks, …) and a failing page or file write
  are both recorded under **Diagnostics**. The command still exits 0, so
  check the Diagnostics section, not only the exit code.
- The page and the file are written independently: one can succeed while the
  other fails. The next successful run overwrites both for the same brief id.
- When the model summary fails, the brief is still rendered and stored with
  the deterministic fallback bullets. The Hygiene `LLM:` line says why.
- Exit code 1 means no project was found, the wiki is not built, the
  `--store` directory is missing, or the config is invalid. Exit code 2 is a
  usage error, for example `--team` combined with `--me`.

## Back-fill attributes on an existing plane

Briefs read the meeting, decision and deliverable *attributes* of pages. A
plane built before attributes existed needs a reindex:

```bash
wikitoolkit entity reindex --dry-run          # counts only
wikitoolkit entity reindex                    # rewrite attributes (SQLite backend)
wikitoolkit entity reindex --store <storage-dir>
```

- `--store` is the storage directory itself. Careful: a missing directory is
  **created**, so a typo produces an empty plane instead of an error.
- Reindex skips `authored` and `memory` pages and never modifies page bodies.
- Metadata that was dropped at ingest time cannot be recovered by a reindex.
  Re-ingest the source instead.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "On your plate" is empty but you own items | Owners are compared verbatim. Use `--me human:<user>`, or set `standup.me.wiki` and `standup.me.aliases` in `.parrot/wiki.json`. A configured `standup.me.wiki` takes precedence over `--me`. |
| No Jira tickets in the brief | The Jira identity has not been resolved. Set `standup.me.jira_account_id`, or run one *writing* brief so the live lookup fills `${PARROT_HOME}/jira_identity.json`. Read-only runs never contact Jira. |
| "Wiki not built yet" | Run `wikitoolkit build` first. Only the `arangodb` backend skips this check. |
| "Since last brief" is always empty | No earlier brief of the same period was stored, for example because runs used `--no-store`. |
| Hygiene lists unmapped statuses | Add them to `standup.ticket_status_map`, mapping each to `open`, `in-progress`, `blocked`, `in-review` or `closed`. |
| `LLM: skipped: no model` | Set `WIKI_LIGHTWEIGHT_MODEL`, or the variable named in `standup.llm_env`. |
