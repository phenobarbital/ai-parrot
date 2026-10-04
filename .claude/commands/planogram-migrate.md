---
description: Migrate troc.planograms_configurations (schema + existing rows) to the perceive → identify → compare cycle — export, convert, review, apply on confirmation, preflight
argument-hint: "[--dir <workdir>] [--only <config_name>...] [--dry-run] [--resume]"
allowed-tools: Bash, Read, Edit
---

# /planogram-migrate — Planogram configuration migration (FEAT-574, FEAT-612)

Run the deployment sequence of `docs/pipelines/planogram-cycle-migration.md`
against the live `troc.planograms_configurations` table: apply the ALTER
script, export every active row, convert each one into a candidate, review
the unresolved items **with the user**, and — only after an explicit yes —
write the approved rows back and prove readiness with the preflight.

The mechanical part lives in `parrot_pipelines.planogram.migration_runner`;
this command is the judgment around it (the review, the safety gates, the
write decision).

## Usage

```
/planogram-migrate                       # full sequence, new work directory
/planogram-migrate --dry-run             # export + convert + render, write nothing
/planogram-migrate --resume --dir artifacts/planogram-migration/2026-10-01
/planogram-migrate --only epson_endcap_v2 hisense_tv_display_v1
```

## Ground rules

- **Two steps write to the database**: `alter` (Step 2) and `apply` (Step 6).
  Each needs its own explicit confirmation in this session. An earlier yes
  never carries over, and `--dry-run` skips both.
- **Never invent planogram content.** Quantities, descriptors, selectors,
  expected-empty facings and weights are the user's decisions. Propose,
  show the evidence from the original row, and ask.
- The DSN is `querysource.conf.default_dsn` (the writable DSN of the active
  environment — `ENV` selects which one). The runner resolves it itself and
  logs only `host:port/database`. Never print the DSN, never write it to a
  file, never pass it with `--dsn` on a command line that gets logged.
- Exported rows are private: the work directory lives under `artifacts/`
  (git-ignored). Never `git add` it, never paste whole rows into chat.
- Scores of the migrated types are **not comparable** with the old ones
  (runbook § "What changes in scores") — say so in the final report.

Every runner call below is:

```bash
source .venv/bin/activate && python -m parrot_pipelines.planogram.migration_runner <subcommand> ...
```

Exit codes: `0` ok · `2` unresolved / not-ready rows (expected mid-flow, not
a failure) · `1` usage, I/O or database error (stop and report).

---

## Step 1 — Parse and gate

1. Work directory: `--dir` if given, else
   `artifacts/planogram-migration/<YYYY-MM-DD>`. With `--resume` the
   directory must already hold `original/`; without it, it must not.
2. Resolve the target (connects to nothing, shows no credentials):
   ```bash
   ... migration_runner target
   ```
   Exit `1` → `querysource.conf.default_dsn` is not configured: stop and say so.
3. **Show the user the `host:port/database` line and get them to confirm it
   is the intended environment** (prod / staging / dev). To target another
   one, prefix every runner call with `ENV=<env>` — keep the same prefix for
   the whole run, and repeat the target check after changing it.
4. Read-only baseline:
   ```bash
   ... migration_runner preflight
   ```
   - "column slots_definition does not exist" or similar → Step 2 is needed.
   - Exit `0` → every active row is already ready: report and stop.
   - Exit `2` → show a table (`config_name`, type, problems) and continue.

## Step 2 — Schema (writes — confirm)

Skip when Step 1 shows the columns already exist.

```bash
... migration_runner alter            # prints the statements, executes nothing
```

Show the four `ALTER TABLE` statements (idempotent, additive: two nullable
columns, two `DROP NOT NULL`), **ask for confirmation**, then:

```bash
... migration_runner alter --yes
```

Under `--dry-run`, print the statements and move on.

## Step 3 — Export

Skip under `--resume`.

```bash
... migration_runner export --dir <workdir>
```

Writes one file per active row to `<workdir>/original/`. The runner refuses
to overwrite an existing export — these files are the rollback copy; never
edit them.

## Step 4 — Convert

```bash
... migration_runner convert --dir <workdir>
```

The JSON summary gives one status per row:

| Status | Meaning |
|---|---|
| `ready` | already passes preflight — no candidate, nothing to do |
| `converted` | candidate written to `<workdir>/candidates/<name>.json` |
| `kept` | a reviewed candidate already existed and was left untouched |
| `unsupported` | `planogram_type` is not one of the six registered types |

`unsupported` rows block the preflight: the user must fix the type or set
`is_active = FALSE` by hand — this command does not do either.

With `--only`, limit Steps 5–6 to those config names (delete nothing; just
render with `--partial` and leave the rest blocked).

Never pass `--force` after review has started — it regenerates candidates
and discards the edits.

## Step 5 — Review with the user

A candidate file holds the proposed `slots_definition`, the original
`planogram_config` with `rule_bindings` and `layout_profile` merged in, and
two lists: `unresolved` (must be emptied) and `warnings` (must be read).

For each candidate with problems, one row at a time:

1. Read the candidate and its `original/` twin.
2. Present every `unresolved` item with the evidence from the original row,
   and ask the user for the decision. Typical items:
   - `quantity_range [a, b]` → the exact number of facings (a placeholder of
     one facing was created).
   - `descriptors are required` → the facing's `display_name` and
     distinguishing descriptors.
   - `zone selector required for …` / `section … configure a zone selector`
     → the `layout_profile.zone_selectors` entries.
   - `scoring_weights: map to definition/profile weights`.
   - `candidate does not validate: …` / `invalid layout_profile: …` → fix the
     named field path.
3. Apply the decision by editing the candidate file (`slots_definition`,
   `planogram_config.rule_bindings`, `planogram_config.layout_profile`), and
   remove the `unresolved` entry **only once it is actually resolved**.
4. Surface the warnings too — "slot order taken from list order" in
   particular needs a human yes per shelf.

Emptying `unresolved` does not bypass validation: `render` re-runs the same
checks the runtime preflight uses.

Loop until:

```bash
... migration_runner render --dir <workdir>
```

exits `0` and writes `<workdir>/apply.sql`. Exit `2` lists what is still
blocked. Use `--partial` only if the user explicitly wants to migrate the
approved rows now and the rest later — and remind them the deployment stays
blocked until every active row is ready.

## Step 6 — Apply (writes — confirm)

1. Summarize what `apply.sql` will do: number of rows, their names, and that
   it only sets `slots_definition` and `planogram_config`. It is one
   transaction; each row is guarded by its exported `updated_at`, so a row
   changed since the export aborts the whole transaction with nothing
   written.
2. Under `--dry-run`, **stop here**: report the path of `apply.sql` for
   manual application.
3. **Ask for explicit confirmation**, naming the target database again.
4. Then:
   ```bash
   ... migration_runner apply --dir <workdir> --yes
   ```
   On "missing or changed since the export": nothing was written. Start over
   with a new work directory (re-export), carrying the review decisions over
   by hand.

## Step 7 — Verify

```bash
... migration_runner preflight
```

Exit `0` → every active row is ready; the new runtime can be deployed.
Exit `2` → list the remaining rows and go back to Step 4/5 for them.

## Step 8 — Report

```
Planogram configuration migration — <database>

  Schema (ALTER):   applied / already present / skipped (dry-run)
  Active rows:      N
  Already ready:    N
  Migrated now:     N   (<names>)
  Still blocked:    N   (<names + reason>)
  Unsupported:      N   (<names>)
  Preflight:        READY / NOT READY
  Work directory:   <workdir>   (originals kept for rollback)

Next: deploy the new runtime only when Preflight is READY.
Scores of migrated types are not comparable with pre-migration values.
```

## Rollback

The release deletes no data. To undo the row updates, restore
`slots_definition` and `planogram_config` from `<workdir>/original/*.json`
(hand-written SQL, user-applied) and redeploy the prior runtime. The added
columns can stay.

## Error handling

| Situation | Action |
|---|---|
| `target` exits `1` | `querysource.conf.default_dsn` is not configured; stop. Never ask the user to paste a DSN in chat. |
| Target is not the environment the user meant | Stop; re-run with `ENV=<env>` on every runner call. Never assume prod vs. staging. |
| Read-only DSN / permission denied on `alter` or `apply` | Nothing was written. Finish as dry-run and hand over `apply.sql`. |
| Export directory already populated | Use `--resume`, or a new `--dir`. Never delete the originals. |
| `unsupported` row | Report; the user fixes the type or deactivates the row by hand. |
| User does not know an unresolved value | Leave the row blocked; never guess to get to exit `0`. |
| `apply` aborts on a changed row | Nothing written; re-export into a new directory. |
| Runner exit `1` | Stop and show the logged error. |

## Related

| Command | Purpose |
|---|---|
| `/planogram-migrate` | Whole-table migration (THIS) |
| `python -m parrot_pipelines.planogram.migration convert <file>` | Convert one config file offline |
| `python -m parrot_pipelines.planogram.migration preflight --dsn …` | Read-only readiness report |
| `docs/pipelines/planogram-cycle-migration.md` | The runbook this command executes |
