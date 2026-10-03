# Wiki standup briefs

This runbook documents operational procedures for the wikitoolkit standup
feature (FEAT-627). All commands assume a working `wikitoolkit` installation
in an activated virtual environment.

## Generate a brief

### Daily standup (default)

```bash
wikitoolkit standup
```

### Weekly or monthly briefs

```bash
wikitoolkit standup --period week
wikitoolkit standup --period month
```

### Language selection

```bash
wikitoolkit standup --language es  # Spanish
wikitoolkit standup --language en  # English (default)
```

### Read-only output (MCP default)

```bash
wikitoolkit standup --no-llm           # Skip LLM summary
wikitoolkit standup --no-store         # Don't write to wiki store
wikitoolkit standup --no-file          # Don't write to output file
wikitoolkit standup --json             # Output raw JSON
wikitoolkit standup --no-store --no-file --json  # All read-only
```

### Team vs personal briefs

```bash
wikitoolkit standup --team    # All team members
wikitoolkit standup --me jlara  # Specific identity
```

### Output to file

```bash
wikitoolkit standup --out ./standups/2024-01-15.md
```

## Back-fill an existing issues plane

Reindex entity attributes into a wiki plane that was created before attributes
were fully supported:

```bash
# Dry run to see what would be updated
wikitoolkit entity reindex --store "${PARROT_HOME}/wikis/issues/.parrot/wiki" --dry-run

# Actual reindex (writes to the store)
wikitoolkit entity reindex --store "${PARROT_HOME}/wikis/issues/.parrot/wiki"
```

The `--store` path must point to a wiki store directory (contains `.parrot/wiki`
or equivalent backend files).

## Identity, storage and recovery

### Identity configuration

Identity is resolved from `~/.parrot/identity.json`:

```json
{
  "username": "jlara",
  "display_name": "Jesus Lara"
}
```

The identity format is `human:<username>`, without email. Override at runtime:

```bash
wikitoolkit standup --me other_user
```

### Output flags

| Flag | Effect |
|------|--------|
| `--no-store` | Skip writing to wiki store |
| `--no-file` | Skip writing to `--out` file |
| `--json` | Output machine-readable JSON |
| `--out <path>` | Write markdown to file |

### Vault markers and metadata

When a wiki plane is created from a vault (Obsidian, etc.), the original vault
metadata is preserved in the page body. If vault metadata is discarded during
ingest, a fresh source ingest is required to recover it — attributes stored as
frontmatter can be back-filled with `entity reindex`, but vault-specific
metadata cannot.

### Delta interpretation

The brief's "delta" section shows net changes for the period:

- **New**: Items created in the period
- **Updated**: Items modified in the period  
- **Closed**: Items resolved/closed in the period

Delta is computed per-period and does not accumulate across periods.

### Model fallback

If the LLM summary fails (network error, rate limit, model unavailable), the
brief still renders with raw data. No partial summary is stored. Use
`--no-llm` to skip LLM entirely and avoid fallback behavior.

### MCP opt-in persistence

MCP tool calls default to read-only (`--no-store --no-file`). To persist
standup output via MCP, explicitly pass:

```bash
wikitoolkit standup --store /path/to/wiki
# or
wikitoolkit standup --out /path/to/output.md
```

## Schedule

### Cron timing

Run at 07:00 UTC after the 06:17 Jira sweep. The delay ensures Jira data is
fully synchronized before the brief is generated.

### Cron template

```cron
# Daily standup at 07:00 UTC, Monday-Friday
0 7 * * 1-5 cd /PATH/TO/PROJECT && /PATH/TO/.venv/bin/wikitoolkit standup --period day --language en --out /var/log/standups/$(date +\%Y-\%m-\%d).md >> /var/log/standup.log 2>&1

# Weekly summary on Monday at 07:00 UTC
0 7 * * 1 cd /PATH/TO/PROJECT && /PATH/TO/.venv/bin/wikitoolkit standup --period week --language en --out /var/log/standups/week-$(date +\%Y-\%m-\%d).md >> /var/log/standup.log 2>&1
```

Replace `/PATH/TO/PROJECT` and `/PATH/TO/.venv` with deployment-specific paths.

### Logs and failure recovery

- Standup logs are written to the file specified in the cron redirect
  (`/var/log/standup.log` in the example).
- If a run fails, check the log for the error message.
- Failed runs do not write partial data; the next successful run produces
  a complete brief.
- No credentials are exposed in logs — identity is resolved locally from
  `~/.parrot/identity.json`.

## Troubleshooting

### "No identity configured"

Create `~/.parrot/identity.json` with your username:

```json
{
  "username": "your_username",
  "display_name": "Your Name"
}
```

### "Store not found"

Ensure the `--store` path exists and contains a valid wiki store:

```bash
ls -la /path/to/store/.parrot/
```

### "Entity reindex not updating attributes"

- The store must already contain pages with body content.
- Reindex only populates frontmatter attributes; it does not modify page bodies.
- For missing vault metadata, a fresh source ingest is required.

### "LLM summary failing"

- Check network connectivity to the configured LLM endpoint.
- Use `--no-llm` to bypass LLM entirely.
- Verify `WIKI_MODEL` or `WIKI_LIGHTWEIGHT_MODEL` environment variables.